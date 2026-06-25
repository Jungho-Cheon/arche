from __future__ import annotations

from pathlib import Path

import yaml

from arche_eval.runlog import (
    RunDirs,
    hash_directory,
    hash_file,
    make_run_id,
    write_meta_yaml,
)


def test_run_id_format() -> None:
    rid = make_run_id()
    assert len(rid) == len("2026-01-01-1200")


def test_hash_directory_deterministic(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    (tmp_path / "b.md").write_text("world", encoding="utf-8")
    h1 = hash_directory(tmp_path)
    h2 = hash_directory(tmp_path)
    assert h1 == h2
    assert h1.startswith("sha256:")


def test_hash_directory_changes_on_modification(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    h1 = hash_directory(tmp_path)
    (tmp_path / "a.md").write_text("hello!", encoding="utf-8")
    h2 = hash_directory(tmp_path)
    assert h1 != h2


def test_meta_yaml_includes_required_keys(tmp_path: Path) -> None:
    run_id = "2026-06-16-2100"
    dirs = RunDirs.create(tmp_path, run_id)
    questions = tmp_path / "questions.yaml"
    questions.write_text("dataset_id: x\nquestions: []\n", encoding="utf-8")
    write_meta_yaml(
        run_dir=dirs.root,
        run_id=run_id,
        timestamp="2026-06-16T21:00:00+09:00",
        runs=3,
        columns=["full_context", "chunk_rag"],
        llm_model="openai/gpt-4.1",
        embedding_model="openai/text-embedding-3-small",
        corpus_hash="sha256:abc",
        questions_hash=hash_file(questions),
        hyperparameters={"temperature": 0, "chunk_size": 800},
    )
    meta = yaml.safe_load((dirs.root / "meta.yaml").read_text(encoding="utf-8"))
    assert meta["measurement_id"] == run_id
    assert meta["models"]["llm"] == "openai/gpt-4.1"
    assert meta["models"]["embedding"] == "openai/text-embedding-3-small"
    assert meta["corpus_hash"] == "sha256:abc"
    assert meta["questions_hash"].startswith("sha256:")
    assert meta["runs"] == 3
    assert meta["columns"] == ["full_context", "chunk_rag"]
