"""correctness.score_correctness 의 happy / parse_error 경로."""

from __future__ import annotations

from opentology_eval.scoring.correctness import score_correctness


def test_correct_choice_returns_one() -> None:
    assert score_correctness({"choice": "a"}, "a") == 1


def test_case_insensitive() -> None:
    assert score_correctness({"choice": "A"}, "a") == 1
    assert score_correctness({"choice": " a "}, "a") == 1


def test_wrong_choice_returns_zero() -> None:
    assert score_correctness({"choice": "b"}, "a") == 0


def test_parse_error_returns_zero() -> None:
    assert score_correctness(None, "a") == 0


def test_missing_choice_returns_zero() -> None:
    assert score_correctness({"reasoning": "..."}, "a") == 0


def test_non_dict_returns_zero() -> None:
    assert score_correctness("a", "a") == 0  # type: ignore[arg-type]
