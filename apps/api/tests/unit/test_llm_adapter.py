"""LLM 어댑터의 파싱 / 재시도 동작."""

from __future__ import annotations

import json

import pytest

from arche_api.adapters.llm import OpenAILLMProvider
from arche_api.domain.errors import DependencyUnavailableError


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


# ---------- ADR-0017 코드-델타: extraction_fingerprint ----------


def _provider_with_model(model_id: str) -> OpenAILLMProvider:
    prov = OpenAILLMProvider.__new__(OpenAILLMProvider)
    prov.model_id = model_id
    prov._client = None  # type: ignore[attr-defined]
    return prov


def test_extraction_fingerprint_is_deterministic_hex():
    prov = _provider_with_model("gpt-4.1")
    fp1 = prov.extraction_fingerprint()
    fp2 = prov.extraction_fingerprint()
    assert fp1 == fp2  # 결정적
    assert len(fp1) == 16
    assert all(c in "0123456789abcdef" for c in fp1)


def test_extraction_fingerprint_changes_with_model():
    """모델이 바뀌면 지문이 바뀐다 → short-circuit 이 풀려 재추출."""
    assert (
        _provider_with_model("gpt-4.1").extraction_fingerprint()
        != _provider_with_model("gpt-5").extraction_fingerprint()
    )


def test_extraction_fingerprint_tracks_system_prompt():
    """SYSTEM_PROMPT 가 바뀌면 지문이 바뀐다 (프롬프트 변경 = 코드-델타 트리거).

    monkeypatch 없이, 지문 산출 재료에 SYSTEM_PROMPT 가 실제로 들어가는지 확인한다.
    """
    import hashlib

    from arche_api.adapters import llm as llm_mod

    prov = _provider_with_model("gpt-4.1")
    # 현재 SYSTEM_PROMPT 로 만든 지문.
    current = prov.extraction_fingerprint()
    # SYSTEM_PROMPT 에 한 글자만 더해 직접 재료를 만들어 보면 달라져야 한다.
    material = (
        llm_mod.SYSTEM_PROMPT
        + "X"
        + "\x00"
        + json.dumps(
            llm_mod.EXTRACTION_RESPONSE_FORMAT, sort_keys=True, ensure_ascii=False
        )
        + "\x00"
        + "gpt-4.1"
    )
    altered = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    assert current != altered
