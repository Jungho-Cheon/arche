"""/answer + /retrieve REST 라우터 — TestClient + dependency override.

WHY router 별 단위 테스트: service flow 는 test_answer_service.py 가, 본 모듈은
HTTP envelope + 의존성 wire-up + 요청 검증을 본다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from opentology_api.adapters.embedding import EmbeddingProvider
from opentology_api.adapters.graph import ChunkHit, KeywordHit, StoredChunk
from opentology_api.answer.llm import AnswerLLM, AnswerLLMResult, AnswerLLMUsage
from opentology_api.api.deps import (
    answer_llm_dep,
    embedding_provider_dep,
    graph_repo_dep,
)
from opentology_api.domain.models import Node
from opentology_api.main import create_app
from opentology_api.test_support import FakeGraph


class _Embedder(EmbeddingProvider):
    def embed(self, texts):
        return [[0.1] * 8 for _ in texts]


class _AnswerLLM(AnswerLLM):
    def complete(self, *, system, user, response_format):
        if "엔티티 멘션" in system:
            return AnswerLLMResult(
                raw="{...}",
                parsed={"entities": []},
                parse_error=None,
                usage=AnswerLLMUsage(input_tokens=10, output_tokens=5),
                model="fake",
                latency_ms=10,
            )
        name = response_format["json_schema"]["name"]
        if name == "OpenAnswer":
            parsed = {"answer": "테스트 답변", "reasoning": "근거"}
        else:
            parsed = {"choice": "a", "reasoning": "근거"}
        return AnswerLLMResult(
            raw="{...}",
            parsed=parsed,
            parse_error=None,
            usage=AnswerLLMUsage(input_tokens=300, output_tokens=80),
            model="fake",
            latency_ms=100,
        )


def _ulid(tag: int) -> str:
    raw = f"{tag:026d}".upper()
    return (raw + "Z" * 26)[:26]


class _Graph(FakeGraph):
    def vector_search_chunks(self, *, embedding, top_k):
        return [
            ChunkHit(
                chunk=StoredChunk(
                    id="docs/a.md#0",
                    source_path="docs/a.md",
                    chunk_index=0,
                    total_chunks=1,
                    text="본문 청크",
                    token_count=5,
                ),
                score=0.8,
            )
        ][:top_k]

    def find_by_keywords_scored(self, *, keywords, limit_per_keyword):
        if not keywords:
            return []
        return [
            KeywordHit(
                node=Node(
                    id=_ulid(1),
                    name="엔티티1",
                    type="policy",
                    aliases=[],
                    description="설명",
                    properties={},
                    source_refs=[],
                    created_at="2026-06-21T00:00:00Z",
                    updated_at="2026-06-21T00:00:00Z",
                ),
                raw_score=1.0,
                matched_keyword=keywords[0],
            )
        ]


def _client() -> TestClient:
    app = create_app()
    graph = _Graph()
    embedder = _Embedder()
    answer_llm = _AnswerLLM()
    app.state.graph_repo = graph
    app.state.embedding_provider = embedder
    app.state.answer_llm = answer_llm
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[embedding_provider_dep] = lambda: embedder
    app.dependency_overrides[answer_llm_dep] = lambda: answer_llm
    return TestClient(app)


def test_post_answer_open_ended_returns_envelope():
    with _client() as c:
        r = c.post("/answer", json={"question": "테스트?"})
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    data = body["data"]
    assert "answer" in data
    assert data["provenance"]["mode_used"] == "combined"
    assert data["provenance"]["graph"] is not None
    assert data["choice"] is None
    assert data["usage"]["answer_model"] == "fake"


def test_post_answer_mcq_returns_choice():
    with _client() as c:
        r = c.post(
            "/answer",
            json={
                "question": "테스트?",
                "options": [
                    {"id": "a", "text": "x"},
                    {"id": "b", "text": "y"},
                ],
                "mode": "chunks",
            },
        )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["choice"] == "a"
    assert data["provenance"]["mode_used"] == "chunks"
    assert data["provenance"]["graph"] is None


def test_post_retrieve_returns_chunks_and_subgraph():
    with _client() as c:
        r = c.post("/retrieve", json={"question": "?"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["chunks"]) == 1
    assert data["subgraph"] is not None


def test_post_retrieve_chunks_skips_graph():
    with _client() as c:
        r = c.post("/retrieve/chunks", json={"question": "?", "top_k": 3})
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["chunks"]) == 1
    assert "subgraph" not in data


def test_post_answer_rejects_empty_question():
    with _client() as c:
        r = c.post("/answer", json={"question": ""})
    assert r.status_code == 422
