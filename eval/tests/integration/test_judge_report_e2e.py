"""End-to-end: 컬럼 응답 → judge (mock) → spotcheck (non-interactive) → report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import yaml

from arche_eval.providers import LLMResult, LLMUsage
from arche_eval.scoring import aggregate_run, write_report
from arche_eval.scoring.judge_runner import run_judge_on_run_dir
from arche_eval.scoring.spotcheck import apply_overrides_file


def _r(score: int) -> LLMResult:
    parsed = {"score": score, "rationale": "stub"}
    return LLMResult(
        raw_response=json.dumps(parsed),
        parsed=parsed,
        parse_error=None,
        usage=LLMUsage(input_tokens=30, output_tokens=10),
        latency_ms=100,
        model="anthropic/claude-sonnet-4-6",
    )


def _build_run_dir(tmp_path: Path) -> Path:
    """3 컬럼 × 3 질문 × 3 run = 27 응답."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "questions.yaml").write_text(
        yaml.safe_dump(
            {
                "dataset_id": "test",
                "questions": [
                    {
                        "id": f"Q0{i}",
                        "question": f"질문 {i}",
                        "reference_reasoning": "ref",
                        "expected_sources": [],
                        "tags": [],
                        "options": [
                            {"id": "a", "text": "정답", "is_correct": True},
                            {"id": "b", "text": "오답", "is_correct": False},
                            {"id": "e", "text": "정보 부족 / 모름", "is_correct": False},
                        ],
                    }
                    for i in (1, 2, 3)
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    # full_context — 토큰 매우 크고 latency 크고 정확도 100% (가설 가의 cost ceiling).
    (run_dir / "responses" / "full_context").mkdir(parents=True)
    for q in (1, 2, 3):
        for r in range(3):
            (run_dir / "responses" / "full_context" / f"Q0{q}_run{r}.json").write_text(
                json.dumps(
                    {
                        "column": "full_context",
                        "question_id": f"Q0{q}",
                        "run_index": r,
                        "input_tokens": 100000 + r * 100,
                        "output_tokens": 100 + r * 10,
                        "latency_ms": 20000 + r * 100,
                        "model": "openai/gpt-4.1",
                        "parsed": {"choice": "a", "reasoning": "fc 추론"},
                        "parse_error": None,
                    }
                ),
                encoding="utf-8",
            )

    # chunk_rag — 토큰 작고 정확도 부분.
    (run_dir / "responses" / "chunk_rag").mkdir(parents=True)
    correctness_pattern_cr = {
        "Q01": ["a", "a", "a"],
        "Q02": ["b", "b", "a"],
        "Q03": ["e", "e", "e"],
    }
    for q in (1, 2, 3):
        for r in range(3):
            choice = correctness_pattern_cr[f"Q0{q}"][r]
            (run_dir / "responses" / "chunk_rag" / f"Q0{q}_run{r}.json").write_text(
                json.dumps(
                    {
                        "column": "chunk_rag",
                        "question_id": f"Q0{q}",
                        "run_index": r,
                        "input_tokens": 2000 + r * 10,
                        "output_tokens": 50,
                        "embedding_tokens": 30,
                        "total_tokens": 2080 + r * 10,
                        "latency_ms": 2000 + r * 50,
                        "model": "openai/gpt-4.1",
                        "parsed": {"choice": choice, "reasoning": "cr 추론"},
                        "parse_error": None,
                    }
                ),
                encoding="utf-8",
            )

    # arche — 토큰 더 작고 latency 더 작고 정확도 더 높음 (Pareto 통과 시뮬레이션).
    (run_dir / "responses" / "arche").mkdir(parents=True)
    correctness_pattern_op = {
        "Q01": ["a", "a", "a"],
        "Q02": ["a", "a", "a"],
        "Q03": ["a", "e", "e"],
    }
    for q in (1, 2, 3):
        for r in range(3):
            choice = correctness_pattern_op[f"Q0{q}"][r]
            (run_dir / "responses" / "arche" / f"Q0{q}_run{r}.json").write_text(
                json.dumps(
                    {
                        "column": "arche",
                        "question_id": f"Q0{q}",
                        "run_index": r,
                        "anchor_extraction": {
                            "input_tokens": 30, "output_tokens": 10, "latency_ms": 200,
                            "model": "openai/gpt-4.1",
                            "parsed": {"entities": []}, "parse_error": None,
                        },
                        "answer_generation": {
                            "input_tokens": 800, "output_tokens": 40, "latency_ms": 1000,
                            "model": "openai/gpt-4.1",
                            "parsed": {"choice": choice, "reasoning": "op 추론"},
                            "parse_error": None,
                        },
                        "embedding_tokens_estimated": 8,
                        "total_input_tokens": 830, "total_output_tokens": 50,
                        "total_tokens": 888, "total_latency_ms": 1200 + r * 10,
                    }
                ),
                encoding="utf-8",
            )
    return run_dir


def test_judge_then_spotcheck_then_report(tmp_path: Path) -> None:
    run_dir = _build_run_dir(tmp_path)

    # ----- judge (mock) -----
    judge_llm = MagicMock()
    # 27 응답 × 2 호출 (reasoning + faithfulness) = 54 stub.
    # 단순 cycle: reasoning=2, faithfulness=1.
    judge_llm.complete.side_effect = ([_r(2), _r(1)] * 27)

    summary = run_judge_on_run_dir(
        run_dir=run_dir,
        judge_llm=judge_llm,
        judge_model_label="anthropic/claude-sonnet-4-6",
        mapping_seed=42,
    )
    assert summary.rows_emitted == 27

    # ----- spotcheck (non-interactive) -----
    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(
        json.dumps(
            [
                {
                    "question_id": "Q01",
                    "column": "full_context",
                    "run_index": 0,
                    "human_reasoning_quality": 0,
                    "human_faithfulness": None,
                    "note": "통합 테스트",
                }
            ]
        ),
        encoding="utf-8",
    )
    count = apply_overrides_file(run_dir, overrides_path)
    assert count == 1

    # ----- report -----
    agg = aggregate_run(run_dir)
    md_path, data_path = write_report(run_dir, agg, run_ts="2026-06-17-1200")
    assert md_path.exists()
    md = md_path.read_text(encoding="utf-8")

    # 9 칸 표 헤더.
    assert "Median input tokens" in md
    assert "p95 latency" in md
    assert "Reasoning quality" in md
    # Pareto 판정 섹션.
    assert "Pareto 우월" in md
    # Failure mode 표.
    assert "parse_error" in md
    assert "unknown_choice" in md or "정보부족" in md

    # 보고서 데이터 JSON 의 Pareto 평가.
    data = json.loads(data_path.read_text(encoding="utf-8"))
    pareto = data["pareto"]
    # Arche 가 토큰 / latency 우월, 정확도도 full_context 이상.
    assert pareto["tokens_ok"] is True
    assert pareto["latency_ok"] is True

    # full_context 정확도 1.0, arche 정확도 7/9 → accuracy_ok = False.
    assert pareto["accuracy_ok"] is False

    # override count 가 보고서에 반영.
    assert data["override_count_total"] == 1
    assert data["columns"]["full_context"]["override_count"] == 1
