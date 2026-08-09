"""FileLoader 의 멀티모달 분기 unit 테스트 (PRD 4 §1.2 + §2 + 이슈 #14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arche_eval.loaders import (
    FileLoader,
    SerializedCorpus,
    UnsupportedFileType,
)
from tests.fixtures._pdf_builder import write_text_pdf
from tests.fixtures._png_builder import write_red_pixel_png


def test_discover_sorted_and_classified(tmp_path: Path) -> None:
    (tmp_path / "z.md").write_text("md", encoding="utf-8")
    (tmp_path / "a.txt").write_text("txt", encoding="utf-8")
    write_text_pdf(tmp_path / "m.pdf", ["x"])
    write_red_pixel_png(tmp_path / "n.png")

    files = FileLoader(tmp_path).discover()
    # 정렬: a.txt, m.pdf, n.png, z.md
    assert [f.path.name for f in files] == ["a.txt", "m.pdf", "n.png", "z.md"]
    assert [f.kind for f in files] == ["text", "pdf", "image", "text"]


def test_discover_unknown_ext_raises(tmp_path: Path) -> None:
    (tmp_path / "ok.md").write_text("ok", encoding="utf-8")
    (tmp_path / "bad.csv").write_text("a,b", encoding="utf-8")
    with pytest.raises(UnsupportedFileType) as exc:
        FileLoader(tmp_path).discover()
    assert ".csv" in str(exc.value)


def test_serialize_corpus_text_only_returns_no_images(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# hello", encoding="utf-8")
    loader = FileLoader(tmp_path)
    out = loader.serialize_corpus(loader.discover())
    assert isinstance(out, SerializedCorpus)
    assert "=== FILE: a.md ===" in out.text
    assert "# hello" in out.text
    assert out.images == []


def test_serialize_corpus_pdf_text_pages_inline(tmp_path: Path) -> None:
    write_text_pdf(
        tmp_path / "spec.pdf",
        ["page one alpha beta", "page two gamma delta"],
    )
    loader = FileLoader(tmp_path)
    out = loader.serialize_corpus(loader.discover())
    assert "=== FILE: spec.pdf ===" in out.text
    assert "PAGE 1/2" in out.text
    assert "PAGE 2/2" in out.text
    assert "page one alpha beta" in out.text
    assert "page two gamma delta" in out.text
    # 텍스트 페이지 PDF — 이미지 없음.
    assert out.images == []


def test_serialize_corpus_image_file_caption_and_image(tmp_path: Path) -> None:
    write_red_pixel_png(tmp_path / "diag.png")
    loader = FileLoader(tmp_path)
    out = loader.serialize_corpus(loader.discover())
    # 본문엔 캡션만.
    assert "=== IMAGE: diag.png ===" in out.text
    # 이미지는 별도 리스트.
    assert len(out.images) == 1
    assert out.images[0].mime_type == "image/png"
    assert out.images[0].b64_data


def test_iter_text_units_for_chunking_skips_images(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    write_red_pixel_png(tmp_path / "c.png")
    loader = FileLoader(tmp_path)
    units = loader.iter_text_units_for_chunking(loader.discover())
    assert len(units) == 1
    assert units[0][0].name == "a.md"


def test_iter_text_units_for_chunking_pdf_text_pages_only(tmp_path: Path) -> None:
    write_text_pdf(tmp_path / "spec.pdf", ["page one", "page two"])
    loader = FileLoader(tmp_path)
    units = loader.iter_text_units_for_chunking(loader.discover())
    assert len(units) == 1
    path, text = units[0]
    assert path.name == "spec.pdf"
    assert "page one" in text
    assert "page two" in text
