"""PDF 텍스트 + 이미지 추출 — `apps/api/adapters/pdf.py` 복제.

WHY 복제:
  PRD 4 §0 의 eval ↔ apps/api 격리. eval 의 corpus 가 PDF 를 포함할 때 텍스트와
  임베디드 이미지를 페이지 단위로 분리하기 위해 *동일 구조* 의 함수를 둔다.

WHY pypdf:
  순수 Python + BSD-3. 원본과 동일한 선택.

WHY 텍스트 + 이미지 페이지 분리:
  - 텍스트가 있는 페이지는 full-context 의 *텍스트 블록* 에 들어간다.
  - 텍스트가 비고 이미지만 있는 페이지는 *멀티모달 user content* 의 이미지로 별도 전달.
  IngestService 와 동일한 결정 (PRD 2 §3.4) 을 eval 측에서도 재사용.

raises:
  InvalidPdfError — PDF 파일이 깨졌거나 pypdf 가 열지 못함. 호출자는 *해당 파일만
  skip + warning 로그* 의 PRD 2 §8 패턴을 따른다.

마지막 동기화 — 원본 `apps/api/src/opentology_api/adapters/pdf.py` (PR #23).
원본이 바뀌면 본 모듈도 함께 갱신.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path


logger = logging.getLogger(__name__)


# `lint/_supported_exts.PDF_EXTS` 와 동일해야 한다.
PDF_EXTS: frozenset[str] = frozenset({".pdf"})


class InvalidPdfError(ValueError):
    """PDF 파일이 아니거나 깨졌을 때."""


@dataclass(frozen=True)
class PdfPage:
    """한 페이지의 추출 결과 (원본 dataclass 와 필드 동일).

    - `page_index` : 0-based.
    - `total_pages` : PDF 전체 페이지 수.
    - `text` : 페이지의 본문 텍스트. 추출 실패 / 이미지 페이지면 빈 문자열.
    - `images` : 페이지에서 추출된 이미지 바이트들.
    - `image_mime_types` : `images` 와 같은 순서/길이의 MIME 타입.
    """

    page_index: int
    total_pages: int
    text: str
    images: list[bytes] = field(default_factory=list)
    image_mime_types: list[str] = field(default_factory=list)


def extract_pdf(path: Path) -> list[PdfPage]:
    """PDF 를 페이지 단위로 분해. 원본과 동일한 시그니처/동작.

    Raises:
        InvalidPdfError — pypdf 미설치 / 파일이 PDF 가 아님 / 깨진 PDF.
    """
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as e:
        raise InvalidPdfError(
            f"pypdf is not installed: {e}. Run `uv sync --extra dev` in eval/."
        ) from e

    try:
        reader = PdfReader(str(path))
    except (PdfReadError, OSError, ValueError) as e:
        raise InvalidPdfError(f"failed to open PDF {path}: {e}") from e

    total = len(reader.pages)
    pages: list[PdfPage] = []

    for i, page in enumerate(reader.pages):
        # WHY try/except: 텍스트 추출 실패해도 이미지 폴백 (멀티모달 호출) 이
        # 가능하게 페이지를 빈 텍스트로 보존.
        try:
            text = page.extract_text() or ""
        except Exception as e:  # noqa: BLE001 — pypdf 내부 에러 다양.
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
        try:
            for img in page.images:
                data = img.data
                if not data:
                    continue
                mime = _detect_image_mime(data, fallback_name=img.name)
                if mime is None:
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


# WHY magic-number 우선: PDF 내부 리소스 이름은 확장자가 없을 수 있다.
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
    if fallback_name:
        lower = fallback_name.lower()
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith(".jpg") or lower.endswith(".jpeg"):
            return "image/jpeg"
        if lower.endswith(".webp"):
            return "image/webp"
    return None
