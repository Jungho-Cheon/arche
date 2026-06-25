"""파일 로더 — 텍스트 (`.txt` / `.md`) + PDF + 이미지 (PRD 2 §2.1 / §3.4).

WHY 멀티모달 분기:
  베이스라인 두 컬럼 (full-context, chunk_rag) 의 corpus 가 검증 도메인의 PDF 약관 /
  UI 스크린샷을 포함하는 시점이 됐다 (이슈 #14). 모달별 처리:
    - 텍스트 파일 — full-context 의 직렬화 블록 + chunk_rag 의 청크화 소스.
    - PDF — 페이지 단위로 텍스트 추출. 텍스트 페이지는 직렬화 블록 + 청크 소스에
      포함. 텍스트가 없는 이미지 페이지는 *full-context 의 멀티모달 이미지 입력*
      에 별도로 들어가고 chunk_rag 는 무시.
    - 이미지 파일 (`.png` 등) — full-context 의 멀티모달 이미지 입력. chunk_rag 는
      무시 (PRD 4 §2 의 대조군 정의 + 본 파일 docstring 의 "이미지 무시 이유" 코멘트).

WHY chunk_rag 가 이미지를 무시:
  PRD 4 §2 의 chunk RAG 대조군은 *전형적 텍스트 RAG* . 이미지 청크화는 multimodal
  embedding 모델이 필요해 변수가 추가된다 (ADR-0001 D3 의 측정 통제 변수 정책 위반).
  MVP 단계에선 이미지 입력이 *청크 인덱스에 들어가지 않을 뿐* — 에러는 아니다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .multimodal import (
    IMAGE_EXTS,
    PDF_EXTS,
    ImageInput,
    PdfPage,
    extract_pdf,
    load_image_as_b64,
)


logger = logging.getLogger(__name__)


SUPPORTED_TEXT_EXTS: frozenset[str] = frozenset({".txt", ".md"})
# 본 집합과 `lint/_supported_exts.SUPPORTED_EXTS` 는 동일 (PRD 2 §2.1 의 코어
# SUPPORTED_EXTS 의 사본). 코어가 새 모달을 추가하면 두 곳 모두 갱신.
SUPPORTED_EXTS: frozenset[str] = frozenset(SUPPORTED_TEXT_EXTS | PDF_EXTS | IMAGE_EXTS)


FileKind = Literal["text", "pdf", "image"]


class UnsupportedFileType(NotImplementedError):
    """확장자가 SUPPORTED_EXTS 에 없을 때."""


@dataclass(frozen=True)
class CorpusFile:
    """디스크 파일 + 모달 분류."""

    path: Path
    kind: FileKind


@dataclass(frozen=True)
class SerializedCorpus:
    """full-context 컬럼이 LLM 에 전달할 corpus 직렬화 결과.

    - `text` : PRD 4 §1.2 형식의 텍스트 블록. PDF 텍스트 페이지 + 이미지 캡션 포함.
    - `images` : 멀티모달 user content 에 image_url block 으로 들어갈 이미지들.
      파일 이미지 + PDF 의 텍스트 없는 이미지 페이지 가 모두 평탄화되어 한 리스트.
    """

    text: str
    images: list[ImageInput] = field(default_factory=list)


class FileLoader:
    """corpus 디렉토리에서 텍스트 / PDF / 이미지 파일을 재귀 수집."""

    def __init__(self, root: Path) -> None:
        if not root.exists() or not root.is_dir():
            raise ValueError(f"corpus root not a directory: {root}")
        self.root = root

    def discover(self) -> list[CorpusFile]:
        """지원 파일을 정렬해 반환. 미지원 확장자는 *명시 예외* .

        WHY 명시 예외: 측정 코퍼스에 알 수 없는 포맷이 *조용히 누락* 되면 정확도가
        변하는데 원인을 추적하기 어렵다 (PRD 4 §0 의 명시성 원칙). 사용자가 해당
        파일을 의도적으로 제외하려면 `.archeignore` 와 같은 형식을 별도 도입.
        """
        found: list[CorpusFile] = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext in SUPPORTED_TEXT_EXTS:
                found.append(CorpusFile(path=p, kind="text"))
            elif ext in PDF_EXTS:
                found.append(CorpusFile(path=p, kind="pdf"))
            elif ext in IMAGE_EXTS:
                found.append(CorpusFile(path=p, kind="image"))
            else:
                raise UnsupportedFileType(
                    f"알 수 없는 파일 포맷 {ext} ({p}). "
                    f"지원 확장자: {sorted(SUPPORTED_EXTS)}"
                )
        return found

    def read(self, path: Path) -> str:
        """텍스트 파일 본문을 그대로 반환. PDF/이미지 는 별도 메서드.

        WHY 분리: PDF/이미지 는 `str` 단일 반환으로 표현하기 어렵다 (페이지 시퀀스 /
        바이너리). 호출자가 모달을 알고 적절한 메서드를 부르도록.
        """
        ext = path.suffix.lower()
        if ext in SUPPORTED_TEXT_EXTS:
            return path.read_text(encoding="utf-8")
        if ext in PDF_EXTS:
            raise UnsupportedFileType(
                f"PDF 는 read() 가 아닌 extract_pdf_pages() 로 처리하세요 ({path})."
            )
        if ext in IMAGE_EXTS:
            raise UnsupportedFileType(
                f"이미지는 read() 가 아닌 load_image() 로 처리하세요 ({path})."
            )
        raise UnsupportedFileType(f"알 수 없는 파일 포맷 {ext} ({path}).")

    def extract_pdf_pages(self, path: Path) -> list[PdfPage]:
        """PDF 파일을 페이지 시퀀스로. 호출자는 텍스트 / 이미지 페이지를 분기."""
        return extract_pdf(path)

    def load_image(self, path: Path) -> ImageInput:
        """이미지 파일 → 멀티모달 LLM 입력 형태."""
        b64, mime = load_image_as_b64(path)
        return ImageInput(b64_data=b64, mime_type=mime)

    def serialize_corpus(self, files: list[CorpusFile]) -> SerializedCorpus:
        """PRD 4 §1.2 형식으로 텍스트 블록 + 이미지 리스트 분리.

        규칙:
          - 텍스트 파일 → `=== FILE: <rel> ===` 헤더 + 본문.
          - PDF — 페이지 단위로:
              * 텍스트가 있는 페이지 → 같은 파일 블록 안에 페이지 헤더 + 텍스트 이어붙임.
              * 텍스트가 비고 이미지가 있는 페이지 → 캡션만 텍스트 블록에 두고,
                이미지는 `images` 리스트에 평탄화.
          - 이미지 파일 → 텍스트 블록에 `=== IMAGE: <rel> ===` 캡션만 + `images`
            에 한 장 추가.

        WHY 캡션:
          LLM 이 reasoning 에서 *어느 이미지를 봤는지* 인용할 수 있어야 judge 단계의
          faithfulness 채점이 가능하다 (PRD 4 §4.4).
        """
        blocks: list[str] = []
        images: list[ImageInput] = []

        for cf in files:
            rel = cf.path.relative_to(self.root)
            if cf.kind == "text":
                content = self.read(cf.path)
                blocks.append(f"=== FILE: {rel} ===\n{content}")
            elif cf.kind == "pdf":
                blocks.append(self._serialize_pdf(rel, cf.path, images))
            elif cf.kind == "image":
                img = self.load_image(cf.path)
                images.append(img)
                blocks.append(
                    f"=== IMAGE: {rel} ===\n"
                    f"(이미지 첨부됨 — 본 텍스트 블록 다음 user content 에 "
                    f"image_url 로 포함)"
                )
            else:  # pragma: no cover — Literal 가 막아주지만 fail-fast.
                raise UnsupportedFileType(f"알 수 없는 kind: {cf.kind}")

        return SerializedCorpus(text="\n\n".join(blocks), images=images)

    def _serialize_pdf(
        self, rel: Path, path: Path, images_out: list[ImageInput]
    ) -> str:
        """PDF 한 파일을 텍스트 블록으로 직렬화 + 이미지 페이지를 images_out 에 추가.

        WHY images_out 인자 (return tuple 대신):
          호출자가 평탄화된 *한 리스트* 를 모은다. 본 메서드가 그 리스트에 직접
          append 하면 호출자가 재조립 코드를 줄일 수 있다 (내부 helper 이므로
          순수성보다 호출자 단순성을 우선).
        """
        from base64 import b64encode

        pages = self.extract_pdf_pages(path)
        page_blocks: list[str] = [f"=== FILE: {rel} ==="]

        for page in pages:
            page_text = (page.text or "").strip()
            if page_text:
                page_blocks.append(
                    f"--- PAGE {page.page_index + 1}/{page.total_pages} ---\n"
                    f"{page_text}"
                )
                # 같은 페이지에 이미지가 있어도 텍스트가 있으면 *텍스트만* 직렬화에
                # 넣는다. 이미지는 PR 의 결정 — 텍스트 페이지의 임베디드 이미지는
                # 본 PR 범위에서 *멀티모달 입력으로 보내지 않는다* . WHY: 텍스트
                # 페이지의 이미지는 보통 장식 (로고 / 페이지 헤더) 이 많아 정확도
                # 측정에 노이즈만 증가시킬 가능성이 높다. 이미지 페이지 (텍스트
                # 없음) 만 멀티모달 입력에 추가해 통제된 신호로 둔다.
            elif page.images:
                # 텍스트 없는 이미지 페이지 → 멀티모달 입력에 추가 + 캡션만 본문에.
                for raw, mime in zip(page.images, page.image_mime_types):
                    images_out.append(
                        ImageInput(
                            b64_data=b64encode(raw).decode("ascii"),
                            mime_type=mime,
                        )
                    )
                page_blocks.append(
                    f"--- PAGE {page.page_index + 1}/{page.total_pages} "
                    f"(이미지 페이지) ---\n"
                    f"(이 페이지의 이미지 {len(page.images)} 장이 본 텍스트 블록 "
                    f"다음 user content 에 image_url 로 포함됨)"
                )
            else:
                # 텍스트도 이미지도 없는 빈 페이지 — 조용히 skip.
                logger.debug(
                    "pdf_page_empty_skipped page=%d/%d source=%s",
                    page.page_index + 1,
                    page.total_pages,
                    path,
                )

        return "\n\n".join(page_blocks)

    def iter_text_units_for_chunking(
        self, files: list[CorpusFile]
    ) -> list[tuple[Path, str]]:
        """chunk_rag 가 청크화할 *텍스트 단위* 의 평탄화 리스트.

        규칙:
          - 텍스트 파일 → (path, 본문) 한 항목.
          - PDF → 페이지마다 (path, 페이지 텍스트) — *텍스트가 있는 페이지만* .
            chunk_rag 는 페이지 경계가 있는 PDF 라도 *한 파일을 한 청크 소스* 로
            볼 수 있으나, 페이지 텍스트를 *각각의 청크 소스* 로 두면 청크 출처
            (source_path) 가 페이지 단위로 명확해져 디버깅이 쉽다. 단 현재
            chunk_corpus 의 source_path 는 파일 단위 — 페이지 텍스트를 하나로
            *이어붙여* 단일 항목으로 반환해 호환을 유지한다.
          - 이미지 파일 / 이미지 페이지 → *skip + warning 로그* . WHY: PRD 4 §2 의
            chunk RAG 대조군은 텍스트 RAG 만이라 이미지 청크화는 변수 추가.

        Returns:
            (path, text) 의 리스트. chunk_corpus 에 그대로 전달.
        """
        out: list[tuple[Path, str]] = []
        skipped_images = 0

        for cf in files:
            if cf.kind == "text":
                out.append((cf.path, self.read(cf.path)))
            elif cf.kind == "pdf":
                pages = self.extract_pdf_pages(cf.path)
                texts: list[str] = []
                image_only_pages = 0
                for page in pages:
                    if (page.text or "").strip():
                        texts.append(page.text)
                    elif page.images:
                        image_only_pages += 1
                if image_only_pages:
                    logger.warning(
                        "chunk_rag_skip_pdf_image_pages source=%s pages=%d",
                        cf.path,
                        image_only_pages,
                    )
                if texts:
                    # 페이지 사이에 빈 줄 두 개 — chunk 모듈의 paragraph splitter
                    # 가 페이지 경계를 자연 paragraph 경계로 인식한다.
                    out.append((cf.path, "\n\n".join(texts)))
            elif cf.kind == "image":
                skipped_images += 1
            else:  # pragma: no cover
                raise UnsupportedFileType(f"알 수 없는 kind: {cf.kind}")

        if skipped_images:
            logger.warning(
                "chunk_rag_skip_image_files count=%d root=%s",
                skipped_images,
                self.root,
            )
        return out
