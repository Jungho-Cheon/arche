"""Anthropic 추출 어댑터 — tool-use 번역 / 파싱 / 재시도 / 지문 동작 (ADR-0019).

WHY __new__ + fake client: AnthropicLLMProvider.__init__ 가 anthropic SDK 의
Anthropic() 를 생성자 시점에 만든다. 테스트는 그 SDK 인스턴스가 필요 없으므로
__new__ 로 우회하고 messages.create 만 흉내내는 가짜 클라이언트를 주입한다 —
test_llm_adapter.py 의 OpenAI 어댑터 테스트와 같은 전략.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from arche_api.adapters.llm import AnthropicLLMProvider
from arche_api.domain.errors import DependencyUnavailableError


def _tool_use_block(name: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=payload)


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


class _FakeMessages:
    """messages.create 호출을 순서대로 미리 준비한 응답으로 답한다."""

    def __init__(self, responses: list) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses[len(self.calls) - 1]


def _make_provider(responses: list) -> AnthropicLLMProvider:
    prov = AnthropicLLMProvider.__new__(AnthropicLLMProvider)
    prov.model_id = "claude-sonnet-4-5"
    prov._max_tokens = 1024  # type: ignore[attr-defined]
    prov._client = SimpleNamespace(messages=_FakeMessages(responses))  # type: ignore[attr-defined]
    return prov


def test_extract_translates_tool_use_input_to_graph():
    payload = {
        "entities": [
            {"name": "쿠폰X", "type": "coupon", "aliases": ["X쿠폰"], "description": None}
        ],
        "relations": [{"from": "쿠폰X", "to": "프로모션P", "type": "applies_to"}],
    }
    resp = SimpleNamespace(content=[_tool_use_block("extracted_graph", payload)])
    prov = _make_provider([resp])

    result = prov.extract(text="dummy", source_path="/tmp/x.md")

    assert result.entities[0].name == "쿠폰X"
    assert result.entities[0].aliases == ["X쿠폰"]
    assert result.relations[0].from_name == "쿠폰X"
    assert result.relations[0].type == "applies_to"


def test_extract_forces_tool_choice_with_neutral_schema():
    """중립 추출 스키마가 tool 의 input_schema 로, tool_choice 가 강제되는지 확인."""
    from arche_api.domain.extraction_contract import EXTRACTION_ENTITY_RELATION_SCHEMA

    payload = {"entities": [], "relations": []}
    resp = SimpleNamespace(content=[_tool_use_block("extracted_graph", payload)])
    prov = _make_provider([resp])

    prov.extract(text="dummy", source_path="/tmp/x.md")

    call = prov._client.messages.calls[0]  # type: ignore[attr-defined]
    assert call["tool_choice"] == {"type": "tool", "name": "extracted_graph"}
    assert call["tools"][0]["input_schema"] is EXTRACTION_ENTITY_RELATION_SCHEMA


def test_extract_retries_once_then_succeeds():
    """tool_use 블록이 없는 첫 응답 → 같은 입력으로 1 회 재시도해 성공."""
    bad = SimpleNamespace(content=[_text_block("죄송합니다, 도구를 못 썼어요")])
    good = SimpleNamespace(
        content=[_tool_use_block("extracted_graph", {"entities": [], "relations": []})]
    )
    prov = _make_provider([bad, good])

    result = prov.extract(text="dummy", source_path="/tmp/x.md")

    assert result.entities == []
    assert len(prov._client.messages.calls) == 2  # type: ignore[attr-defined]


def test_extract_raises_after_two_failures():
    bad = SimpleNamespace(content=[_text_block("no tool")])
    prov = _make_provider([bad, bad])
    with pytest.raises(DependencyUnavailableError):
        prov.extract(text="dummy", source_path="/tmp/x.md")


def test_complete_uses_tool_use_when_schema_present():
    """complete 가 OpenAI json_schema 봉투에서 안쪽 스키마를 꺼내 tool-use 로 강제."""
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    response_format = {"type": "json_schema", "json_schema": {"schema": schema}}
    resp = SimpleNamespace(content=[_tool_use_block("result", {"answer": "42"})])
    prov = _make_provider([resp])

    out = prov.complete(system="sys", user="q", response_format=response_format)

    assert out.parse_error is None
    assert out.parsed == {"answer": "42"}
    call = prov._client.messages.calls[0]  # type: ignore[attr-defined]
    assert call["tools"][0]["input_schema"] is schema


def test_complete_falls_back_to_text_json_without_schema():
    """스키마가 없으면 평문 응답을 받아 JSON 파싱한다."""
    resp = SimpleNamespace(content=[_text_block(json.dumps({"answer": "hi"}))])
    prov = _make_provider([resp])

    out = prov.complete(system="sys", user="q", response_format={})

    assert out.parsed == {"answer": "hi"}


def test_extract_requires_text_or_images():
    prov = _make_provider([])
    from arche_api.domain.errors import UnsupportedFileTypeError

    with pytest.raises(UnsupportedFileTypeError):
        prov.extract(source_path="/tmp/x.md")


# ---------- extraction_fingerprint ----------


def _provider_with_model(model_id: str) -> AnthropicLLMProvider:
    prov = AnthropicLLMProvider.__new__(AnthropicLLMProvider)
    prov.model_id = model_id
    return prov


def test_fingerprint_is_deterministic_hex():
    prov = _provider_with_model("claude-sonnet-4-5")
    fp = prov.extraction_fingerprint()
    assert prov.extraction_fingerprint() == fp
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)


def test_fingerprint_differs_from_openai_same_model_name():
    """provider 토큰 때문에 같은 모델명이라도 OpenAI 지문과 달라진다.

    provider 교체는 추출 결과를 바꾸므로 재추출(코드-델타)이 맞다.
    """
    from arche_api.adapters.llm import OpenAILLMProvider

    anthropic_fp = _provider_with_model("same-model").extraction_fingerprint()
    openai_prov = OpenAILLMProvider.__new__(OpenAILLMProvider)
    openai_prov.model_id = "same-model"
    assert anthropic_fp != openai_prov.extraction_fingerprint()
