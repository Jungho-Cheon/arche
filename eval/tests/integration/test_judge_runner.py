"""judge_runner — mock LLM 으로 run_dir 전체 처리."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import yaml

from opentology_eval.providers import LLMResult, LLMUsage
from opentology_eval.scoring.judge_runner import run_judge_on_run_dir


def _r(score: int) -> LLMResult:
    """JSON {score, rationale} 응답 stub."""
    parsed = {"score": score, "rationale": "stub"}
    return LLMResult(
        raw_response=json.dumps(parsed),
        parsed=parsed,
        parse_error=None,
        usage=LLMUsage(input_tokens=30, output_tokens=10),
        latency_ms=100,
        model="anthropic/claude-sonnet-4-6",
    )


def _make_run(tmp_path: Path) -> Path:
    """1 질문 × 3 컬럼 × 1 run 의 run_dir."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "questions.yaml").write_text(
        yaml.safe_dump(
            {
                "dataset_id": "test",
                "questions": [
                    {
                        "id": "Q01",
                        "question": "테스트?",
                        "reference_reasoning": "ref",
                        "expected_sources": [],
                        "tags": [],
                        "options": [
                            {"id": "a", "text": "정답", "is_correct": True},
                            {"id": "b", "text": "오답", "is_correct": False},
                        ],
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    for col, parsed in (
        ("full_context", {"choice": "a", "reasoning": "fc 추론"}),
        ("chunk_rag", {"choice": "a", "reasoning": "cr 추론"}),
    ):
        (run_dir / "responses" / col).mkdir(parents=True)
        (run_dir / "responses" / col / "Q01_run0.json").write_text(
            json.dumps(
                {
                    "column": col,
                    "question_id": "Q01",
                    "run_index": 0,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "embedding_tokens": 5,
                    "total_tokens": 125,
                    "latency_ms": 500,
                    "model": "openai/gpt-4.1",
                    "parsed": parsed,
                    "parse_error": None,
                }
            ),
            encoding="utf-8",
        )
    # opentology — 답변 nested.
    (run_dir / "responses" / "opentology").mkdir(parents=True)
    (run_dir / "responses" / "opentology" / "Q01_run0.json").write_text(
        json.dumps(
            {
                "column": "opentology",
                "question_id": "Q01",
                "run_index": 0,
                "anchor_extraction": {
                    "input_tokens": 10, "output_tokens": 5, "latency_ms": 100,
                    "model": "openai/gpt-4.1",
                    "parsed": {"entities": []}, "parse_error": None,
                },
                "answer_generation": {
                    "input_tokens": 50, "output_tokens": 20, "latency_ms": 300,
                    "model": "openai/gpt-4.1",
                    "parsed": {"choice": "a", "reasoning": "op 추론"},
                    "parse_error": None,
                },
                "embedding_tokens_estimated": 0,
                "total_input_tokens": 60, "total_output_tokens": 25,
                "total_tokens": 85, "total_latency_ms": 400,
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def test_run_judge_emits_one_row_per_column(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path)
    judge_llm = MagicMock()
    # reasoning + faithfulness 두 호출이 컬럼당 발생.
    judge_llm.complete.side_effect = [
        _r(2), _r(1),  # full_context
        _r(1), _r(1),  # chunk_rag
        _r(2), _r(1),  # opentology
    ]
    summary = run_judge_on_run_dir(
        run_dir=run_dir,
        judge_llm=judge_llm,
        judge_model_label="anthropic/claude-sonnet-4-6",
        mapping_seed=42,
    )
    assert summary.questions_count == 1
    assert summary.rows_emitted == 3
    assert summary.reasoning_parse_errors == 0
    assert summary.faithfulness_parse_errors == 0

    # mapping.json 이 있고 익명화 라벨이 셋.
    mapping = json.loads((run_dir / "judge" / "mapping.json").read_text())
    assert set(mapping["Q01"].keys()) == {"A", "B", "C"}
    assert set(mapping["Q01"].values()) == {"full_context", "chunk_rag", "opentology"}

    # scores.jsonl 한 줄 = 한 응답.
    lines = (run_dir / "judge" / "scores.jsonl").read_text().strip().split("\n")
    assert len(lines) == 3
    rows = [json.loads(ln) for ln in lines]
    cols = {r["column"] for r in rows}
    assert cols == {"full_context", "chunk_rag", "opentology"}
    for r in rows:
        # 점수가 정수로 기록됨.
        assert isinstance(r["reasoning_quality"], int)
        assert isinstance(r["faithfulness"], int)
        assert r["anonymized_label"] in {"A", "B", "C"}


def test_judge_skips_when_student_reasoning_empty(tmp_path: Path) -> None:
    """parse_error 로 reasoning 이 빈 응답은 judge 호출 안 함, None 기록."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "questions.yaml").write_text(
        yaml.safe_dump(
            {
                "dataset_id": "test",
                "questions": [
                    {"id": "Q01", "question": "?", "reference_reasoning": "ref",
                     "expected_sources": [], "tags": [],
                     "options": [
                         {"id": "a", "text": "A", "is_correct": True},
                         {"id": "b", "text": "B", "is_correct": False},
                     ]}
                ],
            }, allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (run_dir / "responses" / "full_context").mkdir(parents=True)
    (run_dir / "responses" / "full_context" / "Q01_run0.json").write_text(
        json.dumps(
            {
                "column": "full_context",
                "question_id": "Q01",
                "run_index": 0,
                "input_tokens": 100,
                "output_tokens": 0,
                "latency_ms": 500,
                "model": "openai/gpt-4.1",
                "parsed": None,
                "parse_error": "JSONDecodeError",
            }
        ),
        encoding="utf-8",
    )
    judge_llm = MagicMock()
    summary = run_judge_on_run_dir(
        run_dir=run_dir,
        judge_llm=judge_llm,
        judge_model_label="anthropic/claude-sonnet-4-6",
        columns=("full_context",),
    )
    # judge 가 호출되지 않음.
    judge_llm.complete.assert_not_called()
    assert summary.rows_emitted == 1
    assert summary.reasoning_parse_errors == 1
