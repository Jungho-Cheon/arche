"""검토형 적재 5 개의 REST 표면 (#B-2).

MCP 에만 있던 plan → preview → resolve → commit 을 REST 로도 연다. 여기서 지키는
불변은 셋이다. 두 통로가 같은 스키마를 쓴다, 미리 보기를 거치지 않은 확정은 REST
에서도 막힌다, 계획 보관소를 공유해 한 통로에서 세운 계획을 다른 통로에서 확정할
수 있다.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from arche_api.api.deps import (
    embedding_provider_dep,
    graph_repo_dep,
    llm_provider_dep,
)
from arche_api.api.plan_registry import PlanRegistry
from arche_api.domain.models import ExtractedEntity, ExtractedGraph, ExtractedRelation
from arche_api.main import create_app

from .test_ingest_service import FakeEmbedder, FakeGraph, FakeLLM


def _client() -> tuple[TestClient, FakeGraph, PlanRegistry]:
    """fake 어댑터 위에 앱을 띄운다. TestClient 를 context manager 로 쓰지 않아
    lifespan 이 돌지 않으므로 app.state 를 직접 채운다 (다른 라우터 테스트와 같은 방식)."""
    app = create_app()
    graph = FakeGraph()
    llm = FakeLLM(
        ExtractedGraph(
            entities=[
                ExtractedEntity(name="환불 정책", type="Policy"),
                ExtractedEntity(name="여름 프로모션", type="Promotion"),
            ],
            relations=[
                ExtractedRelation(
                    from_name="여름 프로모션", to_name="환불 정책", type="APPLIES_TO"
                )
            ],
        )
    )
    embedder = FakeEmbedder()
    registry = PlanRegistry()
    app.state.graph_repo = graph
    app.state.llm_provider = llm
    app.state.embedding_provider = embedder
    app.state.plan_registry = registry
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[llm_provider_dep] = lambda: llm
    app.dependency_overrides[embedding_provider_dep] = lambda: embedder
    return TestClient(app), graph, registry


def test_plan_preview_commit_writes_to_graph(tmp_path: Path):
    """계획 → 미리 보기 → 확정 세 호출을 거쳐야 그래프에 쓰인다."""
    doc = tmp_path / "policy.md"
    doc.write_text("여름 프로모션은 환불 정책을 따른다.", encoding="utf-8")
    client, graph, _ = _client()

    r = client.post("/ingest/plan", json={"path": str(doc)})
    assert r.status_code == 200, r.text
    plan = r.json()["data"]
    assert plan["entities_created"] == 2
    assert plan["source_path"] == str(doc)
    # 계획 단계에서는 그래프가 그대로다.
    assert graph._entities == {}

    r = client.post("/ingest/preview", json={"plan_id": plan["plan_id"]})
    assert r.status_code == 200, r.text
    preview = r.json()["data"]
    assert {e["name"] for e in preview["new_entities"]} == {"환불 정책", "여름 프로모션"}

    r = client.post("/ingest/commit", json={"plan_id": plan["plan_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["entities_created"] == 2
    assert len(graph._entities) == 2


def test_commit_without_preview_is_unprocessable(tmp_path: Path):
    """MCP 에만 있던 안전 latch 가 REST 에서도 걸린다."""
    doc = tmp_path / "policy.md"
    doc.write_text("여름 프로모션은 환불 정책을 따른다.", encoding="utf-8")
    client, graph, _ = _client()

    plan_id = client.post("/ingest/plan", json={"path": str(doc)}).json()["data"]["plan_id"]
    r = client.post("/ingest/commit", json={"plan_id": plan_id})

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unprocessable"
    assert graph._entities == {}


def test_content_endpoint_plans_without_a_file():
    """본문을 직접 넘기면 서버에 파일을 떨구지 않고 계획이 선다."""
    client, _, _ = _client()

    r = client.post(
        "/ingest/content",
        json={"content": "여름 프로모션은 환불 정책을 따른다.", "source_id": "confluence:PAGE-9"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["data"]["source_path"] == "confluence:PAGE-9"


def test_unknown_plan_id_reports_the_lifetime():
    """계획이 없거나 수명이 지났을 때, 수명을 details 에 실어 다시 계획하게 안내한다."""
    client, _, _ = _client()

    r = client.post("/ingest/preview", json={"plan_id": "pln_없음"})

    assert r.status_code == 400
    body = r.json()["error"]
    assert body["code"] == "invalid_input"
    assert body["details"]["plan_ttl_seconds"] > 0


def test_expired_plan_is_gone(tmp_path: Path):
    """수명이 지난 계획은 확정되지 않는다."""
    doc = tmp_path / "policy.md"
    doc.write_text("여름 프로모션은 환불 정책을 따른다.", encoding="utf-8")
    client, graph, registry = _client()
    now = [0.0]
    registry.clock = lambda: now[0]

    plan_id = client.post("/ingest/plan", json={"path": str(doc)}).json()["data"]["plan_id"]
    now[0] = registry.ttl_seconds + 1
    r = client.post("/ingest/preview", json={"plan_id": plan_id})

    assert r.status_code == 400
    assert graph._entities == {}


def test_namespace_falls_back_to_auth_header(tmp_path: Path):
    """조회 엔드포인트와 같은 우선순위 — body 명시 > auth header > default."""
    doc = tmp_path / "policy.md"
    doc.write_text("여름 프로모션은 환불 정책을 따른다.", encoding="utf-8")
    client, _, registry = _client()

    plan_id = client.post(
        "/ingest/plan",
        json={"path": str(doc)},
        headers={"Authorization": "Bearer ns:team-a"},
    ).json()["data"]["plan_id"]

    assert registry.get(plan_id).namespace_id == "team-a"


def test_body_namespace_beats_auth_header(tmp_path: Path):
    doc = tmp_path / "policy.md"
    doc.write_text("여름 프로모션은 환불 정책을 따른다.", encoding="utf-8")
    client, _, registry = _client()

    plan_id = client.post(
        "/ingest/plan",
        json={"path": str(doc), "namespace_id": "team-b"},
        headers={"Authorization": "Bearer ns:team-a"},
    ).json()["data"]["plan_id"]

    assert registry.get(plan_id).namespace_id == "team-b"


def test_resolve_rejects_a_question_the_plan_never_asked(tmp_path: Path):
    """resolve 는 계획이 묻지 않은 question_id 를 조용히 넘기지 않고 거부한다."""
    doc = tmp_path / "policy.md"
    doc.write_text("여름 프로모션은 환불 정책을 따른다.", encoding="utf-8")
    client, _, _ = _client()

    plan_id = client.post("/ingest/plan", json={"path": str(doc)}).json()["data"]["plan_id"]
    r = client.post(
        "/ingest/resolve",
        json={"plan_id": plan_id, "resolutions": [{"question_id": "q_없음", "decision": "merge"}]},
    )

    assert r.status_code == 400
    assert r.json()["error"]["details"]["question_ids"] == ["q_없음"]


def test_v1_prefix_serves_the_same_endpoints(tmp_path: Path):
    doc = tmp_path / "policy.md"
    doc.write_text("여름 프로모션은 환불 정책을 따른다.", encoding="utf-8")
    client, _, _ = _client()

    r = client.post("/v1/ingest/plan", json={"path": str(doc)})

    assert r.status_code == 200, r.text


def test_openapi_lists_the_five_endpoints():
    """OpenAPI 로 만든 클라이언트가 적재를 덮는다 — 예외 조항이 사라진 근거."""
    client, _, _ = _client()

    paths = client.get("/openapi.json").json()["paths"]

    for p in ("/ingest/plan", "/ingest/content", "/ingest/preview", "/ingest/resolve", "/ingest/commit"):
        assert p in paths, p
