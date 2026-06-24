"""Phase 2 + Phase 3 본격 contracts — ADR-0013/0014/0015 의 코드 evidence.

- /v1/ prefix alias 노출 (ADR-0013 D8)
- 422 validation 이 ErrorEnvelope 으로 wrap (ADR-0013 D1)
- 에러 코드 enum 의 일관성 (ADR-0013 D2)
- /admin/namespaces (ADR-0015 D6)
- ingest body 의 namespace_id 옵션 (ADR-0015 D2)
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from opentology_api.api.admin_tasks import IngestTaskRegistry
from opentology_api.api.deps import (
    embedding_provider_dep,
    graph_repo_dep,
    llm_provider_dep,
    task_registry_dep,
)
from opentology_api.api.error_codes import ERROR_HTTP_STATUS, ErrorCode
from opentology_api.main import create_app
from opentology_api.test_support import FakeEmbedder, FakeGraph


class _StubLLM:
    def extract(self, **kwargs):
        from opentology_api.domain.models import ExtractedGraph
        return ExtractedGraph(entities=[], relations=[])

    def complete(self, **kwargs):
        raise NotImplementedError


def _client_namespaces(ns_data: dict[str, int]) -> TestClient:
    app = create_app()
    graph = FakeGraph()
    # patch count_entities_by_namespace.
    graph.count_entities_by_namespace = lambda: ns_data  # type: ignore[method-assign]
    app.state.graph_repo = graph
    app.state.llm_provider = _StubLLM()
    app.state.embedding_provider = FakeEmbedder()
    app.state.ingest_task_registry = IngestTaskRegistry()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[llm_provider_dep] = lambda: _StubLLM()
    app.dependency_overrides[embedding_provider_dep] = lambda: FakeEmbedder()
    app.dependency_overrides[task_registry_dep] = lambda: app.state.ingest_task_registry
    return TestClient(app)


# ---------- ADR-0013 D8 — /v1/ versioning ----------


def test_v1_alias_is_mounted_for_healthz():
    # 실 호출로 alias 작동 확인 (fastapi 의 _IncludedRouter 가 path 노출 안 함).
    with _client_namespaces({}) as c:
        r_root = c.get("/healthz")
        r_v1 = c.get("/v1/healthz")
        r_v1_entities = c.post("/v1/entities/find", json={"keywords": ["x"]})
        r_v1_admin_ns = c.get("/v1/admin/namespaces")
    assert r_root.status_code == 200
    assert r_v1.status_code == 200
    assert r_root.json() == r_v1.json()
    # 422 가 아닌 200 = v1/ entities 도 정상 호출.
    assert r_v1_entities.status_code == 200
    # v1/ admin 도 정상.
    assert r_v1_admin_ns.status_code == 200


def test_v1_healthz_responds_same_as_root_healthz():
    with _client_namespaces({}) as c:
        r1 = c.get("/healthz")
        r2 = c.get("/v1/healthz")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


# ---------- ADR-0013 D1 — 422 ErrorEnvelope ----------


def test_validation_422_returns_error_envelope_shape():
    with _client_namespaces({}) as c:
        # find_entities 가 keywords 없이 호출되면 422.
        r = c.post("/entities/find", json={})
    assert r.status_code == 422
    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == ErrorCode.INVALID_INPUT.value
    assert "details" in body["error"]
    assert "errors" in body["error"]["details"]


# ---------- ADR-0013 D2 — 에러 코드 enum ----------


def test_error_code_enum_has_expected_codes():
    expected = {
        "invalid_input", "entity_not_found", "task_not_found",
        "not_authorized", "permission_denied", "rate_limited",
        "conflict", "directory_not_found", "not_a_directory",
        "dependency_unavailable", "extraction_failed",
        "internal_error", "timeout",
    }
    actual = {e.value for e in ErrorCode}
    assert expected.issubset(actual)


def test_error_code_http_status_mapping_consistent():
    assert ERROR_HTTP_STATUS[ErrorCode.INVALID_INPUT] == 422
    assert ERROR_HTTP_STATUS[ErrorCode.NOT_AUTHORIZED] == 401
    assert ERROR_HTTP_STATUS[ErrorCode.ENTITY_NOT_FOUND] == 404
    assert ERROR_HTTP_STATUS[ErrorCode.DEPENDENCY_UNAVAILABLE] == 503


# ---------- ADR-0015 D6 — /admin/namespaces ----------


def test_admin_namespaces_returns_summary_sorted_by_count():
    with _client_namespaces({"work-a": 50, "default": 100, "work-b": 30}) as c:
        r = c.get("/admin/namespaces")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["namespaces"]) == 3
    # entity_count DESC.
    counts = [n["entity_count"] for n in data["namespaces"]]
    assert counts == sorted(counts, reverse=True)
    assert data["namespaces"][0]["namespace_id"] == "default"


def test_admin_namespaces_empty_graph_returns_empty_list():
    with _client_namespaces({}) as c:
        r = c.get("/admin/namespaces")
    assert r.status_code == 200
    assert r.json()["data"]["namespaces"] == []


def test_admin_namespaces_available_under_v1_prefix():
    with _client_namespaces({"default": 5}) as c:
        r = c.get("/v1/admin/namespaces")
    assert r.status_code == 200
    assert r.json()["data"]["namespaces"][0]["namespace_id"] == "default"
