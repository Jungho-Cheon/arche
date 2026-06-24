"""Admin ingest 비동기 응답 — PRD 2 §1.2 + §1.3.

POST /admin/ingest → 202 + { task_id, status_url } (즉시 응답).
GET /admin/ingest/{task_id}/status → state/progress/metrics 반환.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from opentology_api.api.admin_tasks import IngestTaskRegistry
from opentology_api.api.deps import (
    embedding_provider_dep,
    graph_repo_dep,
    llm_provider_dep,
)
from opentology_api.domain.models import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
)
from opentology_api.main import create_app

from .test_ingest_service import FakeEmbedder, FakeGraph, FakeLLM


def _client(tmp_path: Path) -> tuple[TestClient, FakeGraph]:
    """라이브 ingest 흐름을 fake adapter 위에 띄운다."""
    app = create_app()
    graph = FakeGraph()
    llm = FakeLLM(
        ExtractedGraph(
            entities=[
                ExtractedEntity(name="A", type="t"),
                ExtractedEntity(name="B", type="t"),
            ],
            relations=[ExtractedRelation(from_name="A", to_name="B", type="rel")],
        )
    )
    embedder = FakeEmbedder()
    app.state.graph_repo = graph
    app.state.llm_provider = llm
    app.state.embedding_provider = embedder
    app.state.ingest_task_registry = IngestTaskRegistry()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[llm_provider_dep] = lambda: llm
    app.dependency_overrides[embedding_provider_dep] = lambda: embedder
    return TestClient(app), graph


def _wait_for_state(client: TestClient, task_id: str, target: str, timeout: float = 5.0):
    """GET status 를 폴링해 target state 에 도달할 때까지 대기."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        r = client.get(f"/admin/ingest/{task_id}/status")
        assert r.status_code == 200
        body = r.json()["data"]
        if body["state"] == target:
            return body
        time.sleep(0.02)
    raise AssertionError(f"state never reached {target}: last={body}")


def test_post_admin_ingest_returns_202_with_task_id_and_status_url(tmp_path: Path):
    """PRD 2 §1.2 — 202 + { task_id, status_url } 응답."""
    (tmp_path / "a.md").write_text("doc a", encoding="utf-8")
    client, _ = _client(tmp_path)
    r = client.post(
        "/admin/ingest", json={"directory_path": str(tmp_path), "dry_run": False}
    )
    assert r.status_code == 202
    body = r.json()["data"]
    assert "task_id" in body
    assert body["task_id"].startswith("ing_")
    assert body["status_url"] == f"/admin/ingest/{body['task_id']}/status"


def test_get_status_eventually_reports_succeeded(tmp_path: Path):
    (tmp_path / "a.md").write_text("doc a", encoding="utf-8")
    client, _ = _client(tmp_path)
    post = client.post("/admin/ingest", json={"directory_path": str(tmp_path)})
    task_id = post.json()["data"]["task_id"]

    final = _wait_for_state(client, task_id, target="succeeded")
    assert final["progress"]["files_total"] == 1
    assert final["progress"]["files_processed"] == 1
    assert final["metrics"]["entities_created"] == 2
    assert final["metrics"]["relations_created"] == 1
    # response_model_exclude_none 으로 error: None 은 응답에서 제외된다.
    assert "error" not in final


def test_get_status_unknown_task_returns_404(tmp_path: Path):
    client, _ = _client(tmp_path)
    r = client.get("/admin/ingest/does_not_exist/status")
    assert r.status_code == 404


def test_post_admin_ingest_rejects_missing_directory(tmp_path: Path):
    client, _ = _client(tmp_path)
    r = client.post(
        "/admin/ingest", json={"directory_path": str(tmp_path / "nope")}
    )
    assert r.status_code == 422
    body = r.json()
    # ErrorEnvelope 안에 directory_not_found 코드.
    assert "directory_not_found" in str(body)


def test_post_admin_ingest_rejects_path_that_is_a_file(tmp_path: Path):
    p = tmp_path / "x.md"
    p.write_text("doc", encoding="utf-8")
    client, _ = _client(tmp_path)
    r = client.post("/admin/ingest", json={"directory_path": str(p)})
    assert r.status_code == 422
    assert "not_a_directory" in str(r.json())


def test_dry_run_does_not_persist_to_graph(tmp_path: Path):
    (tmp_path / "a.md").write_text("doc a", encoding="utf-8")
    client, graph = _client(tmp_path)
    r = client.post(
        "/admin/ingest",
        json={"directory_path": str(tmp_path), "dry_run": True},
    )
    task_id = r.json()["data"]["task_id"]
    _wait_for_state(client, task_id, target="succeeded")
    # 그래프 비어 있음.
    assert graph._entities == {}
