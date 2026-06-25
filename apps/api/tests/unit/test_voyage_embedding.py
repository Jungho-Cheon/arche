"""Voyage 임베딩 어댑터 — embed() 호출 형태 / 에러 변환 (ADR-0019).

WHY __new__ + fake client: VoyageEmbeddingProvider.__init__ 가 voyageai SDK 의
Client() 를 생성자 시점에 만든다. 테스트는 SDK 가 필요 없으므로 __new__ 로 우회하고
embed() 만 흉내내는 가짜 클라이언트를 주입한다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arche_api.adapters.embedding import VoyageEmbeddingProvider
from arche_api.domain.errors import DependencyUnavailableError


class _FakeClient:
    def __init__(self, embeddings=None, raise_exc=None) -> None:
        self._embeddings = embeddings or []
        self._raise = raise_exc
        self.calls: list[dict] = []

    def embed(self, texts, model, input_type):
        self.calls.append({"texts": texts, "model": model, "input_type": input_type})
        if self._raise is not None:
            raise self._raise
        return SimpleNamespace(embeddings=self._embeddings)


def _make_provider(client: _FakeClient) -> VoyageEmbeddingProvider:
    prov = VoyageEmbeddingProvider.__new__(VoyageEmbeddingProvider)
    prov.model_id = "voyage-3"
    prov._input_type = "document"  # type: ignore[attr-defined]
    prov._client = client  # type: ignore[attr-defined]
    return prov


def test_embed_returns_vectors_and_passes_model_input_type():
    client = _FakeClient(embeddings=[[0.1, 0.2], [0.3, 0.4]])
    prov = _make_provider(client)

    out = prov.embed(["a", "b"])

    assert out == [[0.1, 0.2], [0.3, 0.4]]
    assert client.calls[0]["model"] == "voyage-3"
    assert client.calls[0]["input_type"] == "document"


def test_embed_empty_short_circuits_without_call():
    client = _FakeClient()
    prov = _make_provider(client)
    assert prov.embed([]) == []
    assert client.calls == []  # SDK 호출 자체가 없어야 한다


def test_embed_wraps_sdk_error():
    client = _FakeClient(raise_exc=RuntimeError("network down"))
    prov = _make_provider(client)
    with pytest.raises(DependencyUnavailableError):
        prov.embed(["a"])
