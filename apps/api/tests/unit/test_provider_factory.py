"""Provider 팩토리 — 모델 접두사로 LLM/임베딩 어댑터를 고른다 (ADR-0019).

WHY SimpleNamespace settings: 팩토리는 settings 의 몇몇 속성(provider 접두사 +
모델 식별자 + api_key)만 읽는다. 진짜 Settings 는 .env 를 읽으므로, 테스트는 그
속성만 가진 가벼운 더블을 넘긴다. 어댑터 생성자는 SDK 클라이언트를 만들지만
*네트워크 호출은 생성 시점에 일어나지 않으므로* 더미 키로도 안전하다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arche_api.adapters.embedding import OpenAIEmbeddingProvider, VoyageEmbeddingProvider
from arche_api.adapters.llm import AnthropicLLMProvider, OpenAILLMProvider
from arche_api.adapters.providers import (
    build_embedding_provider,
    build_llm_provider,
    supported_embedding_providers,
    supported_llm_providers,
)


def _llm_settings(model: str) -> SimpleNamespace:
    provider = model.split("/", 1)[0] if "/" in model else "openai"
    model_id = model.split("/", 1)[1] if "/" in model else model
    return SimpleNamespace(
        llm_model=model,
        llm_provider=provider,
        llm_model_id=model_id,
        openai_api_key="sk-test",
        anthropic_api_key="sk-test",
    )


def _embed_settings(model: str) -> SimpleNamespace:
    provider = model.split("/", 1)[0] if "/" in model else "openai"
    model_id = model.split("/", 1)[1] if "/" in model else model
    return SimpleNamespace(
        embedding_model=model,
        embedding_provider=provider,
        embedding_model_id=model_id,
        openai_api_key="sk-test",
        voyage_api_key="sk-test",
    )


def test_llm_prefix_selects_adapter():
    assert isinstance(
        build_llm_provider(_llm_settings("openai/gpt-4.1")), OpenAILLMProvider
    )
    assert isinstance(
        build_llm_provider(_llm_settings("anthropic/claude-sonnet-4-5")),
        AnthropicLLMProvider,
    )


def test_embedding_prefix_selects_adapter():
    assert isinstance(
        build_embedding_provider(_embed_settings("openai/text-embedding-3-small")),
        OpenAIEmbeddingProvider,
    )
    assert isinstance(
        build_embedding_provider(_embed_settings("voyage/voyage-3")),
        VoyageEmbeddingProvider,
    )


def test_built_adapter_carries_resolved_model_id():
    """접두사는 떨어지고 실제 API 모델 식별자만 어댑터에 전달된다."""
    llm = build_llm_provider(_llm_settings("anthropic/claude-sonnet-4-5"))
    assert llm.model_id == "claude-sonnet-4-5"
    embed = build_embedding_provider(_embed_settings("voyage/voyage-3"))
    assert embed.model_id == "voyage-3"


def test_unknown_llm_provider_raises_with_supported_list():
    with pytest.raises(ValueError) as exc:
        build_llm_provider(_llm_settings("mistral/mixtral"))
    assert "mistral" in str(exc.value)
    # 에러 메시지가 지원 목록을 알려줘 사용자가 바로 고칠 수 있어야 한다.
    assert "openai" in str(exc.value)


def test_unknown_embedding_provider_raises_with_supported_list():
    with pytest.raises(ValueError) as exc:
        build_embedding_provider(_embed_settings("cohere/embed-v3"))
    assert "cohere" in str(exc.value)
    assert "voyage" in str(exc.value)


def test_supported_lists_are_sorted():
    assert supported_llm_providers() == ["anthropic", "openai"]
    assert supported_embedding_providers() == ["openai", "voyage"]
