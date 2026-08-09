"""떼어내기의 REST/MCP 표면 (#B-1).

도메인 동작은 test_entity_split.py 가 본다. 여기서 보는 건 통로다 — 두 표면이 같은
스키마를 쓰고, 미리 보기를 거치지 않은 확정이 REST 에서도 막히고, 계획 보관소가
적재와 따로 놀아 plan_id 를 엉뚱한 연산에 넘기면 걸린다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arche_api.api.deps import (
    embedding_provider_dep,
    graph_repo_dep,
    llm_provider_dep,
)
from arche_api.api.plan_registry import PlanRegistry
from arche_api.domain.models import ExtractedGraph, SourceRef, StoredEntity, now_rfc3339
from arche_api.main import create_app

from .test_ingest_service import FakeEmbedder, FakeGraph, FakeLLM

ORIGIN_ID = "01J8XR4K9ZQ2N7M3VB0W4D6TYE"
NEIGHBOR_ID = "01J8XR5M2NPQ3R7S4TU5V6W7XY"
CONTRACT = "/docs/계약.md"
TERMS = "/docs/약관.md"


@pytest.fixture
def client() -> tuple[TestClient, FakeGraph]:
    app = create_app()
    graph = FakeGraph()
    now = now_rfc3339()
    graph.create_entity(
        entity=StoredEntity(
            id=ORIGIN_ID,
            name="여름 프로모션",
            type="Program",
            aliases=["여름 정산"],
            description="여름에 도는 것들",
            properties={},
            source_refs=[SourceRef(source_path=CONTRACT), SourceRef(source_path=TERMS)],
            created_at=now,
            updated_at=now,
            embedding=[0.1] * 8,
            namespace_id="default",
            normalized_name="여름 프로모션",
            normalized_aliases=["여름 정산"],
        )
    )
    graph.create_entity(
        entity=StoredEntity(
            id=NEIGHBOR_ID,
            name="환불 정책",
            type="Policy",
            aliases=[],
            description=None,
            properties={},
            source_refs=[],
            created_at=now,
            updated_at=now,
            embedding=[0.2] * 8,
            namespace_id="default",
            normalized_name="환불 정책",
        )
    )
    graph.upsert_relation(
        from_id=ORIGIN_ID,
        to_id=NEIGHBOR_ID,
        rel_type="APPLIES_TO",
        source_ref=SourceRef(source_path=TERMS),
    )
    embedder = FakeEmbedder()
    llm = FakeLLM(ExtractedGraph(entities=[], relations=[]))
    app.state.graph_repo = graph
    app.state.llm_provider = llm
    app.state.embedding_provider = embedder
    app.state.plan_registry = PlanRegistry()
    app.state.split_registry = PlanRegistry()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[llm_provider_dep] = lambda: llm
    app.dependency_overrides[embedding_provider_dep] = lambda: embedder
    return TestClient(app), graph


def _plan(c: TestClient, **overrides) -> dict:
    body = {
        "entity_id": ORIGIN_ID,
        "new_name": "여름 정산",
        "move_source_paths": [TERMS],
    }
    body.update(overrides)
    r = c.post("/entities/split/plan", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_plan_preview_commit_splits_the_node(client):
    c, graph = client

    plan = _plan(c)
    assert plan["relations_moved"] == 1
    assert plan["open_questions"] == 0
    assert len(graph._entities) == 2  # 아직 그래프는 그대로

    r = c.post("/entities/split/preview", json={"plan_id": plan["plan_id"]})
    assert r.status_code == 200, r.text
    preview = r.json()["data"]
    assert preview["new_entity"]["name"] == "여름 정산"
    assert preview["origin"]["source_paths"] == [CONTRACT]
    assert preview["relations"][0]["reason"] == "출처가 모두 떼어내는 쪽"

    r = c.post("/entities/split/commit", json={"plan_id": plan["plan_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["relations_moved"] == 1
    assert len(graph._entities) == 3


def test_commit_without_preview_is_unprocessable(client):
    c, graph = client
    plan = _plan(c)

    r = c.post("/entities/split/commit", json={"plan_id": plan["plan_id"]})

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unprocessable"
    assert len(graph._entities) == 2


def test_split_plan_id_is_not_accepted_by_ingest_commit(client):
    """계획 보관소를 나눠 둔 덕에 엉뚱한 연산에 넘기면 바로 걸린다."""
    c, _ = client
    plan = _plan(c)

    r = c.post("/ingest/commit", json={"plan_id": plan["plan_id"]})

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_input"


def test_unknown_entity_is_404(client):
    c, _ = client

    r = c.post(
        "/entities/split/plan",
        json={
            "entity_id": "01J8XR9ZZZQ2N7M3VB0W4D6TYE",
            "new_name": "x",
            "move_source_paths": [TERMS],
        },
    )

    assert r.status_code == 404
    assert r.json()["error"]["code"] == "entity_not_found"


def test_openapi_lists_the_three_endpoints(client):
    c, _ = client

    paths = c.get("/openapi.json").json()["paths"]

    for p in ("/entities/split/plan", "/entities/split/preview", "/entities/split/commit"):
        assert p in paths, p
