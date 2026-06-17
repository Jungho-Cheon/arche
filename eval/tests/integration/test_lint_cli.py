"""lint CLI 통합 — Typer CliRunner 로 exit 코드 + 출력 검증."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opentology_eval.cli import app


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "datasets"
    / "valid_minimal"
)


pytestmark = pytest.mark.integration


def _copy_fixture(tmp_path: Path) -> Path:
    dst = tmp_path / "dataset"
    shutil.copytree(FIXTURE_ROOT, dst)
    return dst


def test_lint_valid_dataset_exit_zero(tmp_path: Path) -> None:
    dataset = _copy_fixture(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["lint", "--dataset", str(dataset)])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_lint_missing_correct_answer_exit_one(tmp_path: Path) -> None:
    dataset = _copy_fixture(tmp_path)
    # Q01 의 정답을 false 로 — 정답 0 개.
    qfile = dataset / "questions.yaml"
    text = qfile.read_text(encoding="utf-8")
    text = text.replace(
        '        text: "상품 A"\n        is_correct: true',
        '        text: "상품 A"\n        is_correct: false',
        1,
    )
    qfile.write_text(text, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["lint", "--dataset", str(dataset)])
    assert result.exit_code == 1
    assert "FAILED" in result.stdout
    assert "no_correct_answer" in result.stderr


def test_lint_unknown_failure_mode_exit_one(tmp_path: Path) -> None:
    dataset = _copy_fixture(tmp_path)
    qfile = dataset / "questions.yaml"
    text = qfile.read_text(encoding="utf-8")
    text = text.replace("missed_category_hop", "bogus_mode", 1)
    qfile.write_text(text, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["lint", "--dataset", str(dataset)])
    assert result.exit_code == 1
    assert "unknown_failure_mode" in result.stderr


def test_lint_missing_expected_source_exit_one(tmp_path: Path) -> None:
    dataset = _copy_fixture(tmp_path)
    # refund.md 제거.
    (dataset / "corpus" / "policy" / "refund.md").unlink()

    runner = CliRunner()
    result = runner.invoke(app, ["lint", "--dataset", str(dataset)])
    assert result.exit_code == 1
    assert "expected_source_missing" in result.stderr


def test_lint_dry_run_outputs_estimate(tmp_path: Path) -> None:
    dataset = _copy_fixture(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app, ["lint", "--dataset", str(dataset), "--dry-run-ingest"]
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "dry-run ingest estimate" in result.stdout
    assert "total_files" in result.stdout
    assert "openai/gpt-4o" in result.stdout


def test_lint_dataset_not_exist(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["lint", "--dataset", str(tmp_path / "nope")]
    )
    assert result.exit_code == 1
    assert "dataset_root_missing" in result.stderr


def test_lint_unsupported_corpus_file_warns(tmp_path: Path) -> None:
    dataset = _copy_fixture(tmp_path)
    (dataset / "corpus" / "extra.docx").write_bytes(b"PK\x03\x04")

    runner = CliRunner()
    result = runner.invoke(app, ["lint", "--dataset", str(dataset)])
    # warn 은 exit 0 을 유지.
    assert result.exit_code == 0
    assert "unsupported_corpus_file" in result.stderr
