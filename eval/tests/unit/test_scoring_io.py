"""scoring.io — 응답 로더 + 컬럼별 canonical 메트릭 추출."""

from __future__ import annotations

import json
from pathlib import Path

from arche_eval.scoring.io import (
    extract_metrics,
    read_column_responses,
)


def test_read_column_responses_jsonl(tmp_path: Path) -> None:
    """PRD 4 §3.6 명세 — `responses/<column>.jsonl` 한 줄 = 한 응답."""
    run_dir = tmp_path / "run"
    (run_dir / "responses").mkdir(parents=True)
    jsonl = run_dir / "responses" / "full_context.jsonl"
    jsonl.write_text(
        json.dumps({"question_id": "Q01", "run_index": 0}) + "\n"
        + json.dumps({"question_id": "Q01", "run_index": 1}) + "\n",
        encoding="utf-8",
    )
    rows = read_column_responses(run_dir, "full_context")
    assert len(rows) == 2
    assert rows[0]["question_id"] == "Q01"


def test_read_column_responses_dir_layout(tmp_path: Path) -> None:
    """기존 컬럼 PR (#15, #20) 의 출력 — `responses/<column>/Q*_run*.json`."""
    run_dir = tmp_path / "run"
    (run_dir / "responses" / "chunk_rag").mkdir(parents=True)
    (run_dir / "responses" / "chunk_rag" / "Q01_run0.json").write_text(
        json.dumps({"question_id": "Q01", "run_index": 0}), encoding="utf-8"
    )
    (run_dir / "responses" / "chunk_rag" / "Q01_run1.json").write_text(
        json.dumps({"question_id": "Q01", "run_index": 1}), encoding="utf-8"
    )
    rows = read_column_responses(run_dir, "chunk_rag")
    assert len(rows) == 2


def test_read_column_responses_missing_returns_empty(tmp_path: Path) -> None:
    assert read_column_responses(tmp_path, "arche") == []


def test_extract_metrics_full_context() -> None:
    response = {
        "column": "full_context",
        "question_id": "Q01",
        "run_index": 0,
        "input_tokens": 100,
        "output_tokens": 20,
        "latency_ms": 500,
        "model": "openai/gpt-4.1",
        "parsed": {"choice": "a", "reasoning": "정답 추론"},
        "parse_error": None,
    }
    m = extract_metrics(response, "full_context")
    assert m.input_tokens == 100
    assert m.output_tokens == 20
    assert m.embedding_tokens == 0
    assert m.total_tokens == 120
    assert m.latency_ms == 500
    assert m.parsed_choice == "a"
    assert m.parsed_reasoning == "정답 추론"
    assert m.parse_error is None


def test_extract_metrics_chunk_rag_uses_total_tokens_field() -> None:
    response = {
        "column": "chunk_rag",
        "question_id": "Q02",
        "run_index": 1,
        "input_tokens": 200,
        "output_tokens": 30,
        "embedding_tokens": 15,
        "total_tokens": 245,
        "latency_ms": 1000,
        "model": "openai/gpt-4.1",
        "parsed": {"choice": "b", "reasoning": "x"},
        "parse_error": None,
    }
    m = extract_metrics(response, "chunk_rag")
    assert m.input_tokens == 200
    assert m.embedding_tokens == 15
    # total_tokens 필드를 그대로 사용.
    assert m.total_tokens == 245


def test_extract_metrics_arche_aggregates_anchor_plus_answer() -> None:
    response = {
        "column": "arche",
        "question_id": "Q03",
        "run_index": 0,
        "anchor_extraction": {
            "input_tokens": 10,
            "output_tokens": 5,
            "latency_ms": 100,
            "model": "openai/gpt-4.1",
            "parsed": {"entities": []},
            "parse_error": None,
        },
        "answer_generation": {
            "input_tokens": 300,
            "output_tokens": 40,
            "latency_ms": 800,
            "model": "openai/gpt-4.1",
            "parsed": {"choice": "c", "reasoning": "그래프 기반 추론"},
            "parse_error": None,
        },
        "embedding_tokens_estimated": 8,
        "total_input_tokens": 310,
        "total_output_tokens": 45,
        "total_tokens": 363,
        "total_latency_ms": 900,
    }
    m = extract_metrics(response, "arche")
    assert m.input_tokens == 310
    assert m.output_tokens == 45
    assert m.embedding_tokens == 8
    assert m.total_tokens == 363
    assert m.latency_ms == 900
    assert m.parsed_choice == "c"
    assert m.parsed_reasoning == "그래프 기반 추론"


def test_extract_metrics_arche_anchor_parse_error_propagates() -> None:
    """anchor 가 실패하고 answer parsed 도 None 인 경우 parse_error 가 anchor 사유를 담는다."""
    response = {
        "column": "arche",
        "question_id": "Q04",
        "run_index": 0,
        "anchor_extraction": {
            "input_tokens": 10,
            "output_tokens": 5,
            "latency_ms": 100,
            "model": "openai/gpt-4.1",
            "parsed": None,
            "parse_error": "JSON decode failed",
        },
        "answer_generation": {
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": 0,
            "model": "openai/gpt-4.1",
            "parsed": None,
            "parse_error": None,
        },
        "total_input_tokens": 10,
        "total_output_tokens": 5,
        "total_tokens": 15,
        "total_latency_ms": 100,
    }
    m = extract_metrics(response, "arche")
    assert m.parsed_choice is None
    assert m.parse_error is not None
    assert "anchor_parse_error" in m.parse_error
