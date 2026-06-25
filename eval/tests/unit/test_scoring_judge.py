"""scoring.judge — 프롬프트 / 매핑 / score 파싱 / 재시도."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from arche_eval.providers import LLMResult, LLMUsage
from arche_eval.scoring.judge import (
    DEFAULT_JUDGE_MODEL,
    build_mapping,
    invert_mapping,
    read_mapping,
    score_faithfulness,
    score_reasoning_quality,
    write_mapping,
)


def _r(parsed: dict[str, Any] | None, parse_error: str | None = None) -> LLMResult:
    return LLMResult(
        raw_response=str(parsed) if parsed else "",
        parsed=parsed,
        parse_error=parse_error,
        usage=LLMUsage(input_tokens=50, output_tokens=10),
        latency_ms=200,
        model="anthropic/claude-sonnet-4-6",
    )


def test_build_mapping_each_question_independent() -> None:
    qids = ["Q01", "Q02", "Q03"]
    mapping = build_mapping(qids, seed=42)
    assert set(mapping.keys()) == set(qids)
    for qid, m in mapping.items():
        assert set(m.keys()) == {"A", "B", "C"}
        assert set(m.values()) == {"full_context", "chunk_rag", "arche"}


def test_build_mapping_reproducible_with_seed() -> None:
    qids = ["Q01", "Q02"]
    a = build_mapping(qids, seed=7)
    b = build_mapping(qids, seed=7)
    assert a == b


def test_invert_mapping_round_trip() -> None:
    forward = {"A": "full_context", "B": "chunk_rag", "C": "arche"}
    inv = invert_mapping(forward)
    assert inv == {"full_context": "A", "chunk_rag": "B", "arche": "C"}


def test_mapping_persistence(tmp_path: Path) -> None:
    mapping = {"Q01": {"A": "arche", "B": "chunk_rag", "C": "full_context"}}
    write_mapping(mapping, tmp_path / "mapping.json")
    assert read_mapping(tmp_path / "mapping.json") == mapping


def test_score_reasoning_quality_happy_path() -> None:
    judge_llm = MagicMock()
    judge_llm.complete.return_value = _r({"score": 2, "rationale": "모든 hop 식별"})
    result = score_reasoning_quality(
        judge_llm,
        reference_reasoning="ref",
        student_reasoning="stu",
    )
    assert result.score == 2
    assert "모든 hop" in result.rationale
    assert result.parse_error is None
    assert result.retried is False


def test_score_reasoning_quality_retries_on_parse_error() -> None:
    judge_llm = MagicMock()
    judge_llm.complete.side_effect = [
        _r(None, parse_error="JSONDecodeError"),
        _r({"score": 1, "rationale": "일부"}),
    ]
    result = score_reasoning_quality(
        judge_llm,
        reference_reasoning="ref",
        student_reasoning="stu",
    )
    assert result.score == 1
    assert result.retried is True
    # 두 호출 토큰이 합산.
    assert result.input_tokens == 100


def test_score_reasoning_quality_invalid_score_returns_none() -> None:
    judge_llm = MagicMock()
    judge_llm.complete.side_effect = [
        _r({"score": 5, "rationale": "out of range"}),
        _r({"score": 9, "rationale": "still bad"}),
    ]
    result = score_reasoning_quality(
        judge_llm,
        reference_reasoning="ref",
        student_reasoning="stu",
    )
    assert result.score is None
    assert result.parse_error is not None


def test_score_faithfulness_happy_path() -> None:
    judge_llm = MagicMock()
    judge_llm.complete.return_value = _r({"score": 1, "rationale": "ok"})
    result = score_faithfulness(
        judge_llm,
        provided_context="ctx",
        student_reasoning="stu",
    )
    assert result.score == 1
    assert result.parse_error is None


def test_score_faithfulness_zero_is_valid() -> None:
    judge_llm = MagicMock()
    judge_llm.complete.return_value = _r({"score": 0, "rationale": "환각 의심"})
    result = score_faithfulness(
        judge_llm,
        provided_context="ctx",
        student_reasoning="stu",
    )
    assert result.score == 0


def test_default_judge_model_is_anthropic() -> None:
    """ADR-0005 D4 — 답변이 OpenAI 면 judge 는 Anthropic 계열."""
    assert DEFAULT_JUDGE_MODEL.startswith("anthropic/")
