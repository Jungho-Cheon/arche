"""PDF 텍스트 + 이미지 추출 — pypdf 사용. 페이지 단위로 분리.

WHY pypdf:
- 순수 Python, 라이센스 BSD-3 호환. 운영/배포 시 라이센스 부담이 없다.
- `pdfplumber` 는 `pdfminer.six` 의존이라 무거움. `pymupdf` 는 AGPL 이라 OSS+SaaS
  배포 시 강한 제약. MVP 의 PDF 는 *대부분 텍스트 + 일부 이미지 페이지* 가정 —
  pypdf 의 텍스트 추출 품질이면 충분.
- OCR (이미지 페이지의 글자 인식) 은 본 PR 범위 밖이지만, 텍스트가 비어 있고
  이미지가 있는 페이지는 *그 페이지 자체를 이미지로 멀티모달 호출* 하는 폴백을
  `IngestService` 가 채운다 (PRD 2 §2.1 + §3.4).

흐름:
  `extract_pdf(path)` → 페이지마다 `PdfPage(page_index, total_pages, text, images)`
  반환. 텍스트는 `page.extract_text()`, 이미지는 `page.images` 의 `.data` 바이트
  를 모은다. pypdf 가 throw 한 예외는 `DependencyUnavailableError` 가 아니라
  도메인 에러 `InvalidInputError` 로 변환 — 호출자가 *그 파일만 skip + 다른
  파일 계속* 의 PRD 2 §8 시나리오를 따르도록 (`UnsupportedFileTypeError` 도 아닌
  이유: 확장자는 지원하지만 *내용이 깨진* 케이스).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.errors import InvalidInputError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PdfPage:
    """한 페이지의 추출 결과.

    - `page_index` : 0-based.
    - `total_pages` : PDF 전체 페이지 수.
    - `text` : 페이지의 본문 텍스트. 추출 실패 / 이미지 페이지면 빈 문자열.
    - `images` : 페이지에서 추출된 이미지 바이트들. 빈 리스트면 텍스트만.
    - `image_mime_types` : `images` 와 같은 순서/길이의 MIME 타입.
    """

    page_index: int
    total_pages: int
    text: str
    images: list[bytes] = field(default_factory=list)
    image_mime_types: list[str] = field(default_factory=list)


def extract_pdf(path: Path) -> list[PdfPage]:
    """PDF 를 페이지 단위로 분해.

    WHY pypdf.PdfReader 직접: 스트리밍이 아니라 메모리 적재 후 페이지 인덱스
    접근. MVP 의 PDF 크기는 보통 수 MB 이하 — 스트리밍 이득이 작고 코드가
    단순해진다.

    raises:
        InvalidInputError — 파일이 PDF 가 아니거나 깨졌을 때. 호출자는 이
            예외를 잡아 *해당 파일만 skip + warning 로그* (PRD 2 §8).
    """
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as e:  # 셋업 누락 — 즉시 raise.
        raise InvalidInputError(
            f"pypdf is not installed: {e}. Run `uv sync` in apps/api."
        ) from e

    try:
        reader = PdfReader(str(path))
    except (PdfReadError, OSError, ValueError) as e:
        raise InvalidInputError(
            f"failed to open PDF {path}: {e}"
        ) from e

    total = len(reader.pages)
    pages: list[PdfPage] = []

    for i, page in enumerate(reader.pages):
        # 텍스트 추출 — 실패해도 페이지를 빈 텍스트로 보존해 이미지 폴백이 가능
        # 하도록 한다. 한 페이지의 텍스트 추출 실패가 *전체 PDF skip* 으로 번지지
        # 않게 분리.
        try:
            text = page.extract_text() or ""
        except Exception as e:  # noqa: BLE001 — pypdf 가 다양한 내부 에러 throw
            logger.warning(
                "pdf_extract_text failed page=%d/%d source=%s err=%s",
                i + 1,
                total,
                path,
                e,
            )
            text = ""

        images: list[bytes] = []
        mime_types: list[str] = []
        # WHY try/except: pypdf 의 이미지 추출은 PDF 의 인라인 이미지 스트림
        # 인코딩에 따라 깨질 수 있다 (JBIG2 / JPEG2000 등). 실패해도 텍스트는
        # 살리도록 분리해 잡는다.
        try:
            for img in page.images:
                # `img.data` 는 디코드된 원본 바이트 (pypdf 가 stream filter
                # 적용 후 노출). 확장자는 `img.name` 에 들어가는데 항상 신뢰할
                # 수는 없어 magic-number 로 보정한다.
                data = img.data
                if not data:
                    continue
                mime = _detect_image_mime(data, fallback_name=img.name)
                if mime is None:
                    # 알 수 없는 포맷은 멀티모달 입력에 못 쓰니 skip.
                    logger.debug(
                        "pdf_image_skipped unknown_mime page=%d source=%s name=%s",
                        i + 1,
                        path,
                        img.name,
                    )
                    continue
                images.append(data)
                mime_types.append(mime)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "pdf_extract_images failed page=%d/%d source=%s err=%s",
                i + 1,
                total,
                path,
                e,
            )

        pages.append(
            PdfPage(
                page_index=i,
                total_pages=total,
                text=text,
                images=images,
                image_mime_types=mime_types,
            )
        )

    return pages


# WHY magic-number 감지: pypdf 의 `img.name` 은 PDF 내부 리소스 이름이라 확장자가
# 없을 수 있다. 첫 바이트로 포맷을 식별해 멀티모달 호출의 MIME 헤더를 정확히 둔다.
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_JPEG_SIG = b"\xff\xd8\xff"
_WEBP_SIG_HEAD = b"RIFF"
_WEBP_SIG_TAIL = b"WEBP"
_GIF_SIG_87 = b"GIF87a"
_GIF_SIG_89 = b"GIF89a"


def _detect_image_mime(data: bytes, *, fallback_name: str | None) -> str | None:
    if data.startswith(_PNG_SIG):
        return "image/png"
    if data.startswith(_JPEG_SIG):
        return "image/jpeg"
    if data[:4] == _WEBP_SIG_HEAD and data[8:12] == _WEBP_SIG_TAIL:
        return "image/webp"
    if data.startswith(_GIF_SIG_87) or data.startswith(_GIF_SIG_89):
        return "image/gif"
    # magic-number 가 잡히지 않으면 fallback 으로 확장자 추정.
    if fallback_name:
        lower = fallback_name.lower()
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith(".jpg") or lower.endswith(".jpeg"):
            return "image/jpeg"
        if lower.endswith(".webp"):
            return "image/webp"
    return None
