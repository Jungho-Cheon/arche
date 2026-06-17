"""5 primitive + find_entities 의 라이브 흐름 — 실제 Neo4j + OpenAI.

본 라이브 테스트는 다음 흐름을 한 번에 검증한다:

  ingest 작은 디렉토리 → find_entities (lexical + dense + RRF) → get_subgraph
  → find_path → get_schema

WHY 단일 디렉토리 / 단일 테스트로 묶음: live 환경의 비용 (OpenAI API + Neo4j
컨테이너 / 서버) 가 적지 않다. 한 회차의 ingest 비용을 여러 primitive 의
검증에 재사용한다.

활성화: 환경 변수 `RUN_LIVE_TESTS=1` (기존 컨벤션과 정합).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live_enabled() -> bool:
    return os.environ.get("RUN_LIVE_TESTS") == "1"


@pytest.fixture(scope="module")
def setup_world(tmp_path_factory, live_enabled):
    if not live_enabled:
        pytest.skip("RUN_LIVE_TESTS != 1 — live skipped")
    # 픽스처 디렉토리 작성 — 작은 도메인 한 단락.
    tmp = tmp_path_factory.mktemp("primitives_live")
    (tmp / "domain.md").write_text(
        """
# 여름 프로모션

여름 환영 쿠폰은 신규 가입 회원에게 발급되는 쿠폰이다. 여름 시즌 프로모션의
일부이며, 여름 의류 카테고리의 상품 (린넨 셔츠, 면 반바지) 에 적용된다.
""".strip(),
        encoding="utf-8",
    )

    from opentology_api.adapters.embedding import OpenAIEmbeddingProvider
    from opentology_api.adapters.graph import Neo4jGraphRepository
    from opentology_api.adapters.llm import OpenAILLMProvider
    from opentology_api.config import get_settings
    from opentology_api.domain.ingest import IngestService

    settings = get_settings()
    graph = Neo4jGraphRepository(settings)
    graph.ensure_indexes()
    llm = OpenAILLMProvider(
        model_id=settings.llm_model_id, api_key=settings.openai_api_key
    )
    embedder = OpenAIEmbeddingProvider(
        model_id=settings.embedding_model_id, api_key=settings.openai_api_key
    )
    service = IngestService(llm=llm, embedder=embedder, graph=graph)
    service.ingest_file(tmp / "domain.md")
    yield graph, embedder, tmp
    graph.close()


def test_find_entities_hybrid_rrf_returns_matches(setup_world):
    """ingest 한 도메인에서 키워드로 매칭이 나온다."""
    from fastapi.testclient import TestClient

    from opentology_api.api.deps import (
        embedding_provider_dep,
        graph_repo_dep,
    )
    from opentology_api.main import create_app

    graph, embedder, _ = setup_world
    app = create_app()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[embedding_provider_dep] = lambda: embedder
    client = TestClient(app)

    r = client.post(
        "/entities/find",
        json={"keywords": ["여름 쿠폰"], "include_scores": True},
    )
    assert r.status_code == 200
    matches = r.json()["data"]["matches"]
    assert len(matches) >= 1
    # RRF score 0..1, raw 점수 노출.
    m0 = matches[0]
    assert 0.0 <= m0["score"] <= 1.0
    assert "lexical" in m0["scores"]
    assert "dense" in m0["scores"]


def test_get_schema_lists_entity_types(setup_world):
    from fastapi.testclient import TestClient

    from opentology_api.api.deps import graph_repo_dep
    from opentology_api.main import create_app

    graph, _, _ = setup_world
    app = create_app()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    client = TestClient(app)

    r = client.get("/schema")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["entity_types"]) > 0
    assert data["embedding_info"]["dimension"] == 1536


def test_get_subgraph_then_find_path(setup_world):
    """find_entities → get_subgraph → find_path 연속."""
    from fastapi.testclient import TestClient

    from opentology_api.api.deps import (
        embedding_provider_dep,
        graph_repo_dep,
    )
    from opentology_api.main import create_app

    graph, embedder, _ = setup_world
    app = create_app()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[embedding_provider_dep] = lambda: embedder
    client = TestClient(app)

    # 진입점 두 개 찾기
    r = client.post("/entities/find", json={"keywords": ["여름", "쿠폰"]})
    matches = r.json()["data"]["matches"]
    assert len(matches) >= 1
    entry_ids = [m["node"]["id"] for m in matches[:2]]

    # subgraph 확장
    r = client.post(
        "/subgraph", json={"entry_ids": entry_ids, "hops": 2}
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["nodes"]) >= 1
    assert data["entry_ids"] == entry_ids

    if len(entry_ids) >= 2:
        r = client.post(
            "/paths/find",
            json={"from_id": entry_ids[0], "to_id": entry_ids[1]},
        )
        assert r.status_code == 200
        # 경로가 있을 수도 없을 수도 — 둘 다 정상.
        assert "paths" in r.json()["data"]
