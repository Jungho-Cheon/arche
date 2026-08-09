"""지연 provider — 키가 없어도 서버가 뜨고, 채우면 재시작 없이 이어진다 (#160).

WHY SimpleNamespace settings: 지연 provider 는 settings 에서 provider 접두사와 키만
읽는다. 진짜 Settings 는 파일을 읽으므로 필요한 속성만 가진 더블을 넘긴다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arche_api.adapters.providers import (
    LazyEmbeddingProvider,
    LazyLLMProvider,
    missing_embedding_credential,
    missing_llm_credential,
)
from arche_api.domain.errors import DependencyUnavailableError


def _settings(*, openai_api_key=None, llm_model="openai/gpt-4.1") -> SimpleNamespace:
    return SimpleNamespace(
        llm_model=llm_model,
        llm_provider=llm_model.split("/", 1)[0],
        llm_model_id=llm_model.split("/", 1)[1],
        embedding_model="openai/text-embedding-3-small",
        embedding_provider="openai",
        embedding_model_id="text-embedding-3-small",
        openai_api_key=openai_api_key,
        anthropic_api_key=None,
        voyage_api_key=None,
    )


def test_missing_credential_reports_env_var_name():
    assert missing_embedding_credential(_settings()) == "OPENAI_API_KEY"
    assert missing_llm_credential(_settings()) == "OPENAI_API_KEY"


def test_empty_key_counts_as_missing():
    assert missing_embedding_credential(_settings(openai_api_key="")) == "OPENAI_API_KEY"


def test_present_key_is_not_missing():
    assert missing_embedding_credential(_settings(openai_api_key="sk-x")) is None


def test_claude_code_needs_no_key():
    assert missing_llm_credential(_settings(llm_model="claude-code/sonnet")) is None


def test_construction_does_not_touch_credentials(monkeypatch: pytest.MonkeyPatch):
    """생성만으로는 어떤 설정도 읽지 않는다 — 서버 부팅이 키에 걸리지 않아야 한다."""

    def _boom() -> SimpleNamespace:
        raise AssertionError("생성 시점에 설정을 읽으면 안 된다")

    LazyEmbeddingProvider(_boom)
    LazyLLMProvider(_boom)


def test_empty_batch_returns_without_resolving():
    def _boom() -> SimpleNamespace:
        raise AssertionError("빈 배치는 provider 를 만들 필요가 없다")

    assert LazyEmbeddingProvider(_boom).embed([]) == []


def test_missing_key_raises_actionable_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("arche_api.config._settings", _settings())

    with pytest.raises(DependencyUnavailableError) as excinfo:
        LazyEmbeddingProvider(lambda: _settings()).embed(["x"])

    message = excinfo.value.message
    assert "arche config set-key" in message
    assert "OPENAI_API_KEY" in message


def test_failure_is_not_cached(monkeypatch: pytest.MonkeyPatch):
    """키를 채운 뒤 재시작 없이 이어져야 하므로 실패를 캐시하면 안 된다."""
    monkeypatch.setattr("arche_api.config._settings", _settings())
    filled: list[bool] = [False]

    def _factory() -> SimpleNamespace:
        return _settings(openai_api_key="sk-later" if filled[0] else None)

    provider = LazyEmbeddingProvider(_factory)
    with pytest.raises(DependencyUnavailableError):
        provider.embed(["x"])

    filled[0] = True
    # 여기서 예외가 없다는 것이 "재시작 없이 이어진다" 의 실체다. 실제 임베딩 호출은
    # 네트워크를 타므로 어댑터 생성까지만 확인한다.
    assert provider._resolve() is not None


def test_llm_delegates_after_resolution(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("arche_api.config._settings", _settings(openai_api_key="sk-x"))
    provider = LazyLLMProvider(lambda: _settings(openai_api_key="sk-x"))

    assert provider.extraction_fingerprint()
