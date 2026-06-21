"""LLM 어댑터의 파싱 / 재시도 동작."""

from __future__ import annotations

import json

import pytest

from opentology_api.adapters.llm import OpenAILLMProvider
from opentology_api.domain.errors import DependencyUnavailableError


def _make_provider_with_responses(responses: list[str]) -> OpenAILLMProvider:
    """OpenAI 클라이언트 초기화를 우회하기 위해 __new__ 로 객체 생성.

    WHY __new__ + 수동 attribute 주입: __init__ 가 openai SDK 를 생성자 시점에
    참조하는데, 테스트에서 그 SDK 가 필요 없어 통째로 우회한다.
    """
    prov = OpenAILLMProvider.__new__(OpenAILLMProvider)
    prov.model_id = "gpt-4.1"
    prov._client = None  # type: ignore[attr-defined]

    call_count = {"i": 0}

    def fake_call(
        *,
        text: str | None = None,
        images: list | None = None,  # noqa: ARG001 — 인자 시그니처 호환만 맞춘다
        context=None,  # noqa: ARG001
    ) -> str:
        idx = call_count["i"]
        call_count["i"] += 1
        return responses[idx]

    prov._call = fake_call  # type: ignore[method-assign]
    return prov


def test_extract_parses_strict_json():
    payload = {
        "entities": [
            {"name": "쿠폰X", "type": "coupon", "aliases": ["X쿠폰"], "description": None}
        ],
        "relations": [
            {"from": "쿠폰X", "to": "프로모션P", "type": "applies_to", "description": None}
        ],
    }
    prov = _make_provider_with_responses([json.dumps(payload)])
    result = prov.extract(text="dummy", source_path="/tmp/x.md")
    assert len(result.entities) == 1
    assert result.entities[0].name == "쿠폰X"
    assert result.entities[0].aliases == ["X쿠폰"]
    assert result.relations[0].from_name == "쿠폰X"
    assert result.relations[0].type == "applies_to"


def test_extract_retries_once_on_parse_failure():
    good = json.dumps({"entities": [], "relations": []})
    prov = _make_provider_with_responses(["not json", good])
    result = prov.extract(text="dummy", source_path="/tmp/x.md")
    assert result.entities == []
    assert result.relations == []


def test_extract_raises_after_two_failures():
    prov = _make_provider_with_responses(["nope", "still nope"])
    with pytest.raises(DependencyUnavailableError):
        prov.extract(text="dummy", source_path="/tmp/x.md")
