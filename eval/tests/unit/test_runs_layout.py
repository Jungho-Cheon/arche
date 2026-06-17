"""runs.layout.init_run_dir — corpus 해시 결정성 / questions.yaml 사본 / meta.yaml 키."""

from __future__ import annotations

from pathlib import Path

import yaml

from opentology_eval.runs.layout import init_run_dir


def _make_corpus(tmp_path: Path) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    (corpus / "sub").mkdir(parents=True)
    (corpus / "a.md").write_text("# A\n본문 A", encoding="utf-8")
    (corpus / "sub" / "b.md").write_text("# B\n본문 B", encoding="utf-8")
    questions = tmp_path / "questions.yaml"
    questions.write_text(
        yaml.safe_dump(
            {
                "dataset_id": "test",
                "questions": [
                    {
                        "id": "Q01",
                        "question": "?",
                        "reference_reasoning": "ref",
                        "expected_sources": [],
                        "tags": [],
                        "options": [
                            {"id": "a", "text": "A", "is_correct": True},
                            {"id": "b", "text": "B", "is_correct": False},
                        ],
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return corpus, questions


def test_init_run_dir_creates_layout(tmp_path: Path) -> None:
    corpus, questions = _make_corpus(tmp_path)
    output_root = tmp_path / "runs"
    run_dir = init_run_dir(
        output_root,
        timestamp="2026-06-17-1234",
        corpus_path=corpus,
        questions_path=questions,
        columns_meta={
            "full_context": {"llm_model": "openai/gpt-4.1"},
            "chunk_rag": {"llm_model": "openai/gpt-4.1", "embedding_model": "openai/text-embedding-3-small"},
            "opentology": {"llm_model": "openai/gpt-4.1"},
        },
        judge_meta={"model": "anthropic/claude-sonnet-4-6"},
        runs_count=3,
    )
    assert run_dir == output_root / "2026-06-17-1234"
    assert (run_dir / "questions.yaml").exists()
    assert (run_dir / "corpus_hash.txt").exists()
    assert (run_dir / "meta.yaml").exists()
    # responses/ 하위 디렉토리도 만들어졌는지.
    assert (run_dir / "responses" / "full_context").is_dir()
    assert (run_dir / "responses" / "chunk_rag").is_dir()
    assert (run_dir / "responses" / "opentology").is_dir()


def test_meta_yaml_has_required_keys(tmp_path: Path) -> None:
    corpus, questions = _make_corpus(tmp_path)
    output_root = tmp_path / "runs"
    run_dir = init_run_dir(
        output_root,
        timestamp="2026-06-17-1234",
        corpus_path=corpus,
        questions_path=questions,
        columns_meta={
            "opentology": {"llm_model": "openai/gpt-4.1"},
        },
        judge_meta={"model": "anthropic/claude-sonnet-4-6"},
        runs_count=3,
    )
    meta = yaml.safe_load((run_dir / "meta.yaml").read_text(encoding="utf-8"))
    assert meta["run_id"] == "2026-06-17-1234"
    assert meta["judge"]["model"] == "anthropic/claude-sonnet-4-6"
    assert meta["runs"]["count"] == 3
    assert meta["corpus_hash"].startswith("sha256:")
    assert meta["questions_hash"].startswith("sha256:")
    assert "opentology" in meta["columns"]


def test_corpus_hash_deterministic(tmp_path: Path) -> None:
    corpus, questions = _make_corpus(tmp_path)
    run_a = init_run_dir(
        tmp_path / "a", timestamp="ts1",
        corpus_path=corpus, questions_path=questions,
        columns_meta={}, judge_meta={"model": "x"}, runs_count=1,
    )
    run_b = init_run_dir(
        tmp_path / "b", timestamp="ts2",
        corpus_path=corpus, questions_path=questions,
        columns_meta={}, judge_meta={"model": "x"}, runs_count=1,
    )
    assert (run_a / "corpus_hash.txt").read_text() == (run_b / "corpus_hash.txt").read_text()


def test_corpus_hash_changes_with_content(tmp_path: Path) -> None:
    corpus, questions = _make_corpus(tmp_path)
    run_a = init_run_dir(
        tmp_path / "a", timestamp="ts1",
        corpus_path=corpus, questions_path=questions,
        columns_meta={}, judge_meta={"model": "x"}, runs_count=1,
    )
    # corpus 의 파일 하나 변경.
    (corpus / "a.md").write_text("# A\n수정된 본문", encoding="utf-8")
    run_b = init_run_dir(
        tmp_path / "b", timestamp="ts2",
        corpus_path=corpus, questions_path=questions,
        columns_meta={}, judge_meta={"model": "x"}, runs_count=1,
    )
    assert (run_a / "corpus_hash.txt").read_text() != (run_b / "corpus_hash.txt").read_text()


def test_questions_copy_is_independent(tmp_path: Path) -> None:
    """questions.yaml 의 *사본* — 원본 변경이 run 디렉토리에 영향 없음."""
    corpus, questions = _make_corpus(tmp_path)
    run_dir = init_run_dir(
        tmp_path / "runs", timestamp="ts1",
        corpus_path=corpus, questions_path=questions,
        columns_meta={}, judge_meta={"model": "x"}, runs_count=1,
    )
    original_copy = (run_dir / "questions.yaml").read_text(encoding="utf-8")
    questions.write_text("dataset_id: changed\nquestions: []\n", encoding="utf-8")
    assert (run_dir / "questions.yaml").read_text(encoding="utf-8") == original_copy
