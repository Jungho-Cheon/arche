"""Live: 실제 Anthropic API 로 judge 1 호출 — `RUN_LIVE_TESTS=1` + `ANTHROPIC_API_KEY`."""

from __future__ import annotations

import os

import pytest

from arche_eval.providers import AnthropicProvider
from arche_eval.scoring.judge import (
    DEFAULT_JUDGE_MODEL,
    score_reasoning_quality,
)


pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def _require_live_env() -> None:
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        pytest.skip("RUN_LIVE_TESTS=1 가 아닌 환경에서는 live 테스트 스킵")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY 미설정 — 스킵")


def test_anthropic_judge_returns_valid_score() -> None:
    """실제 Anthropic 호출 — 정수 score + rationale 텍스트가 돌아온다."""
    model_id = DEFAULT_JUDGE_MODEL.split("/", 1)[1]
    provider = AnthropicProvider(
        model_id=model_id, api_key=os.environ["ANTHROPIC_API_KEY"]
    )
    result = score_reasoning_quality(
        provider,
        reference_reasoning=(
            "쿠폰 X 는 프로모션 P 에 속한다. P 는 카테고리 C 에 적용된다. "
            "C 는 상품 A 만 포함. 따라서 정답은 상품 A."
        ),
        student_reasoning="상품 A 가 쿠폰 X 의 적용 대상이다.",
    )
    assert result.score in (0, 1, 2)
    assert result.input_tokens > 0
    assert result.output_tokens > 0
