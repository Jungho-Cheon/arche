from __future__ import annotations

from pathlib import Path

import pytest

from opentology_eval.loaders import FileLoader, UnsupportedFileType


def test_discover_finds_md_files_sorted(corpus_dir: Path) -> None:
    loader = FileLoader(corpus_dir)
    files = loader.discover()
    names = [f.name for f in files]
    assert names == sorted(names)
    assert set(names) == {"catalog.md", "coupon.md", "promotion.md"}


def test_serialize_corpus_uses_prd_format(corpus_dir: Path) -> None:
    loader = FileLoader(corpus_dir)
    files = loader.discover()
    serialized = loader.serialize_corpus(files)
    # PRD 4 §1.2 형식: 파일별 헤더 블록.
    assert "=== FILE: catalog.md ===" in serialized
    assert "=== FILE: coupon.md ===" in serialized
    assert "=== FILE: promotion.md ===" in serialized
    # 파일 본문이 헤더 뒤에 등장.
    assert "쿠폰 X 는 프로모션 P 에 속한다" in serialized


def test_pdf_raises_not_implemented_with_followup_issue(tmp_path: Path) -> None:
    pdf = tmp_path / "spec.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    loader = FileLoader(tmp_path)
    with pytest.raises(UnsupportedFileType) as exc:
        loader.discover()
    # follow-up 이슈 식별자가 메시지에 박혀 있어야 한다.
    assert "#5" in str(exc.value)
    assert "PDF" in str(exc.value) or ".pdf" in str(exc.value)


def test_image_raises_not_implemented(tmp_path: Path) -> None:
    img = tmp_path / "diagram.png"
    img.write_bytes(b"\x89PNG dummy")
    loader = FileLoader(tmp_path)
    with pytest.raises(UnsupportedFileType):
        loader.discover()
