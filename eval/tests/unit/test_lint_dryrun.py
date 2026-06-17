"""dry_run_ingest 단위 테스트 — PRD 5 §6.1."""

from __future__ import annotations

from pathlib import Path

from opentology_eval.lint.dryrun import dry_run_ingest


def test_dry_run_empty_corpus(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    est = dry_run_ingest(corpus)
    assert est.total_files == 0
    assert est.total_chunks_estimated == 0
    assert est.total_input_tokens_estimated == 0


def test_dry_run_missing_corpus(tmp_path: Path) -> None:
    est = dry_run_ingest(tmp_path / "nope")
    assert est.total_files == 0


def test_dry_run_text_files(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("# Title\n\n본문 단락이 여러 줄로 들어갑니다.", encoding="utf-8")
    (corpus / "b.txt").write_text("두 번째 파일의 본문입니다.", encoding="utf-8")

    est = dry_run_ingest(corpus)
    assert est.total_files == 2
    assert est.by_ext == {".md": 1, ".txt": 1}
    # 작은 파일이라 청크는 각각 1 개.
    assert est.total_chunks_estimated == 2
    assert est.total_input_tokens_estimated > 0
    # 비용은 모델 등록되어 있으면 > 0.
    assert "openai/gpt-4o" in est.estimated_cost_usd
    assert est.estimated_cost_usd["openai/gpt-4o"] >= 0


def test_dry_run_image_and_pdf(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "doc.pdf").write_bytes(b"%PDF-1.4 dummy")
    (corpus / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    est = dry_run_ingest(corpus)
    assert est.total_files == 2
    # PDF 1 + image 1 = 2 호출 (페이지 추정 1).
    assert est.total_chunks_estimated == 2
    # PDF 보수치 + 이미지 보수치.
    assert est.total_input_tokens_estimated > 1000


def test_dry_run_skips_unsupported(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("x", encoding="utf-8")
    (corpus / "b.docx").write_bytes(b"PK\x03\x04")
    est = dry_run_ingest(corpus)
    # docx 는 추정에서 제외.
    assert est.total_files == 1
    assert ".md" in est.by_ext
    assert ".docx" not in est.by_ext


def test_dry_run_includes_known_models(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("hello world", encoding="utf-8")
    est = dry_run_ingest(corpus, llm_model="openai/gpt-4o-mini")
    # 비용 표에 mini 와 4o 둘 다 등장.
    assert "openai/gpt-4o" in est.estimated_cost_usd
    assert "openai/gpt-4o-mini" in est.estimated_cost_usd
