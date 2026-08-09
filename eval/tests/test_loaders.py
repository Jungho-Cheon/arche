from __future__ import annotations

from pathlib import Path

import pytest

from arche_eval.loaders import (
    FileLoader,
    SerializedCorpus,
    UnsupportedFileType,
)


def test_discover_finds_md_files_sorted(corpus_dir: Path) -> None:
    loader = FileLoader(corpus_dir)
    files = loader.discover()
    names = [f.path.name for f in files]
    assert names == sorted(names)
    assert set(names) == {"catalog.md", "coupon.md", "promotion.md"}
    # 모두 text kind.
    assert {f.kind for f in files} == {"text"}


def test_serialize_corpus_uses_prd_format(corpus_dir: Path) -> None:
    loader = FileLoader(corpus_dir)
    files = loader.discover()
    serialized = loader.serialize_corpus(files)
    assert isinstance(serialized, SerializedCorpus)
    # PRD 4 §1.2 형식: 파일별 헤더 블록.
    assert "=== FILE: catalog.md ===" in serialized.text
    assert "=== FILE: coupon.md ===" in serialized.text
    assert "=== FILE: promotion.md ===" in serialized.text
    # 파일 본문이 헤더 뒤에 등장.
    assert "쿠폰 X 는 프로모션 P 에 속한다" in serialized.text
    # 텍스트만 corpus 라 이미지는 빈 리스트.
    assert serialized.images == []


def test_discover_unknown_extension_raises(tmp_path: Path) -> None:
    """알 수 없는 확장자는 *조용한 누락* 없이 명시 raise (PRD 4 §0)."""
    (tmp_path / "doc.xyz").write_text("hello", encoding="utf-8")
    loader = FileLoader(tmp_path)
    with pytest.raises(UnsupportedFileType) as exc:
        loader.discover()
    assert ".xyz" in str(exc.value)


def test_discover_mixed_modalities_classified(tmp_path: Path) -> None:
    """텍스트 + PDF + 이미지가 섞이면 모두 발견 + kind 분류."""
    from tests.fixtures._pdf_builder import write_text_pdf
    from tests.fixtures._png_builder import write_red_pixel_png

    (tmp_path / "a.md").write_text("# md", encoding="utf-8")
    write_text_pdf(tmp_path / "b.pdf", ["page one"])
    write_red_pixel_png(tmp_path / "c.png")

    loader = FileLoader(tmp_path)
    files = loader.discover()
    by_kind = {f.path.name: f.kind for f in files}
    assert by_kind == {"a.md": "text", "b.pdf": "pdf", "c.png": "image"}


def test_serialize_corpus_includes_pdf_text_pages(tmp_path: Path) -> None:
    from tests.fixtures._pdf_builder import write_text_pdf

    write_text_pdf(tmp_path / "spec.pdf", ["page one alpha", "page two beta"])
    loader = FileLoader(tmp_path)
    files = loader.discover()
    serialized = loader.serialize_corpus(files)
    assert "=== FILE: spec.pdf ===" in serialized.text
    assert "page one alpha" in serialized.text
    assert "page two beta" in serialized.text
    # 두 페이지 모두 텍스트 페이지 → 이미지 없음.
    assert serialized.images == []


def test_serialize_corpus_image_file_in_multimodal_input(tmp_path: Path) -> None:
    from tests.fixtures._png_builder import write_red_pixel_png

    write_red_pixel_png(tmp_path / "diagram.png")
    loader = FileLoader(tmp_path)
    files = loader.discover()
    serialized = loader.serialize_corpus(files)

    # 본문엔 캡션만.
    assert "=== IMAGE: diagram.png ===" in serialized.text
    # 이미지는 멀티모달 리스트로.
    assert len(serialized.images) == 1
    img = serialized.images[0]
    assert img.mime_type == "image/png"
    assert img.b64_data  # base64 string 비어 있지 않음.


def test_iter_text_units_skips_image_files(tmp_path: Path) -> None:
    """chunk_rag 측 — 이미지 파일은 청크화 소스에서 skip."""
    from tests.fixtures._png_builder import write_red_pixel_png

    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    write_red_pixel_png(tmp_path / "c.png")

    loader = FileLoader(tmp_path)
    files = loader.discover()
    units = loader.iter_text_units_for_chunking(files)
    # 텍스트 1 개만.
    assert len(units) == 1
    assert units[0][0].name == "a.md"


def test_iter_text_units_pdf_only_text_pages(tmp_path: Path) -> None:
    """PDF 의 텍스트 페이지만 청크화 소스에 들어간다."""
    from tests.fixtures._pdf_builder import write_text_pdf

    write_text_pdf(tmp_path / "spec.pdf", ["page one alpha"])
    loader = FileLoader(tmp_path)
    files = loader.discover()
    units = loader.iter_text_units_for_chunking(files)
    assert len(units) == 1
    path, content = units[0]
    assert path.name == "spec.pdf"
    assert "page one alpha" in content


def test_read_pdf_raises_directs_to_extract_method(tmp_path: Path) -> None:
    """read() 는 텍스트만. PDF 는 명시 메시지로 다른 메서드 안내."""
    from tests.fixtures._pdf_builder import write_text_pdf

    write_text_pdf(tmp_path / "spec.pdf", ["x"])
    loader = FileLoader(tmp_path)
    with pytest.raises(UnsupportedFileType) as exc:
        loader.read(tmp_path / "spec.pdf")
    assert "extract_pdf_pages" in str(exc.value)
