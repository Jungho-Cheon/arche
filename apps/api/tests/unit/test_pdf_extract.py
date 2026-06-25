"""PDF adapter — pypdf 텍스트/이미지 추출 + 에러 변환 (PRD 2 §2.1 + §8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arche_api.adapters.pdf import PdfPage, extract_pdf
from arche_api.domain.errors import InvalidInputError

from ..fixtures._pdf_builder import build_text_pdf, write_text_pdf


def test_extract_pdf_returns_one_page_per_pdf_page(tmp_path: Path):
    """페이지 수와 텍스트 내용이 정확히 추출된다."""
    path = write_text_pdf(
        tmp_path / "two_pages.pdf", ["First page body.", "Second page body."]
    )
    pages = extract_pdf(path)
    assert len(pages) == 2
    assert all(isinstance(p, PdfPage) for p in pages)
    # 페이지 인덱싱은 0-based, total_pages 는 두 페이지 모두 2.
    assert pages[0].page_index == 0
    assert pages[1].page_index == 1
    assert pages[0].total_pages == 2 == pages[1].total_pages
    # 텍스트 추출 — 본문 토큰이 포함되면 성공 (pypdf 가 공백/줄바꿈을 normalize 할 수 있음).
    assert "First page body" in pages[0].text
    assert "Second page body" in pages[1].text


def test_extract_pdf_with_no_text_returns_empty_text(tmp_path: Path):
    """contents 가 비어 있는 페이지 → text='' + images=[].

    이 케이스는 IngestService 가 *호출 자체를 스킵* 하는 분기로 들어간다.
    """
    path = write_text_pdf(tmp_path / "blank.pdf", [""])
    pages = extract_pdf(path)
    assert len(pages) == 1
    assert pages[0].text.strip() == ""
    assert pages[0].images == []


def test_extract_pdf_invalid_bytes_raises_invalid_input(tmp_path: Path):
    """깨진 바이트는 도메인 에러로 변환 — 호출자가 파일별 격리 (PRD 2 §8)."""
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is not a pdf")
    with pytest.raises(InvalidInputError):
        extract_pdf(path)


def test_extract_pdf_missing_file_raises_invalid_input(tmp_path: Path):
    """존재하지 않는 경로도 InvalidInputError 로 통일된다."""
    with pytest.raises(InvalidInputError):
        extract_pdf(tmp_path / "does_not_exist.pdf")


def test_build_text_pdf_smoke():
    """fixture builder 자체 가드 — 바이트가 PDF 1.4 형태로 시작한다."""
    raw = build_text_pdf(["hi"])
    assert raw.startswith(b"%PDF-1.4")
    assert raw.rstrip().endswith(b"%%EOF")
