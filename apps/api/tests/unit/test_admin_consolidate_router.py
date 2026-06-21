"""/admin/consolidate REST 라우터 — TestClient + dependency_override.

워커 thread 가 즉시 끝나도록 *동기적* 인 FakeConsolidator 를 주입하고, status
폴링이 succeeded report 를 평탄화해 응답 envelope 으로 노출하는지 검증.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from opentology_api.api.admin_consolidate import ConsolidateTaskRegistry
from opentology_api.api.deps import (
    consolidate_task_registry_dep,
    consolidator_dep,
)
from opentology_api.domain.consolidate import (
    ConsolidationReport,
    EntityConsolidator,
)
from opentology_api.main import create_app


class _StubConsolidator(EntityConsolidator):
    """consolidate() 만 override — 외부 의존성 없이 결과 객체 반환."""

    def __init__(self, report: ConsolidationReport) -> None:
        self._report = report

    def consolidate(self, *, dry_run: bool = False, progress=None):
        # dry_run 신호만 report 메타에 반영.
        self._report.duration_seconds = 0.01
        return self._report


def _client(report: ConsolidationReport) -> TestClient:
    app = create_app()
    registry = ConsolidateTaskRegistry()
    app.state.consolidate_task_registry = registry
    app.dependency_overrides[consolidate_task_registry_dep] = lambda: registry
    app.dependency_overrides[consolidator_dep] = lambda: _StubConsolidator(report)
    return TestClient(app)


def _wait_task_done(client: TestClient, status_url: str, timeout: float = 2.0) -> dict:
    """worker thread 가 끝날 때까지 polling — 짧은 in-memory 실행이라 ~10ms."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(status_url)
        if r.status_code == 200 and r.json()["data"]["state"] != "running":
            return r.json()["data"]
        time.sleep(0.01)
    raise AssertionError(f"task did not finish in {timeout}s")


def test_post_consolidate_returns_task_id():
    report = ConsolidationReport(
        entities_scanned=10,
        candidates_total=2,
        candidates_self_reference_skipped=1,
        llm_calls=1,
        merged_pairs=[("01AAAAAAAAAAAAAAAAAAAAAAAA", "01BBBBBBBBBBBBBBBBBBBBBBBB", 0.88, 0.92)],
        rejected_pairs=[
            ("01CCCCCCCCCCCCCCCCCCCCCCCC", "01DDDDDDDDDDDDDDDDDDDDDDDD", 0.86, "self_reference_separation"),
        ],
    )
    with _client(report) as c:
        r = c.post("/admin/consolidate", json={})
    assert r.status_code == 202
    data = r.json()["data"]
    assert data["task_id"].startswith("con_")
    assert data["status_url"].startswith("/admin/consolidate/")


def test_status_returns_report_metrics():
    report = ConsolidationReport(
        entities_scanned=20,
        candidates_total=3,
        candidates_self_reference_skipped=1,
        llm_calls=2,
        merged_pairs=[("01AAAAAAAAAAAAAAAAAAAAAAAA", "01BBBBBBBBBBBBBBBBBBBBBBBB", 0.88, 0.91)],
        rejected_pairs=[
            ("01CCCCCCCCCCCCCCCCCCCCCCCC", "01DDDDDDDDDDDDDDDDDDDDDDDD", 0.86, "self_reference_separation"),
        ],
    )
    with _client(report) as c:
        post = c.post("/admin/consolidate", json={"dry_run": False})
        status_url = post.json()["data"]["status_url"]
        result = _wait_task_done(c, status_url)
    assert result["state"] == "succeeded"
    assert result["progress"]["entities_scanned"] == 20
    assert result["metrics"]["merged"] == 1
    assert result["metrics"]["rejected"] == 1
    assert result["sample"]["merged_pairs"][0]["similarity"] == 0.88
    assert result["sample"]["merged_pairs"][0]["confidence"] == 0.91


def test_dry_run_flag_propagated():
    report = ConsolidationReport(entities_scanned=5)
    with _client(report) as c:
        post = c.post("/admin/consolidate", json={"dry_run": True})
        status_url = post.json()["data"]["status_url"]
        result = _wait_task_done(c, status_url)
    assert result["dry_run"] is True
    assert result["state"] == "succeeded"


def test_status_404_on_unknown_task():
    report = ConsolidationReport()
    with _client(report) as c:
        r = c.get("/admin/consolidate/con_NOPE/status")
    assert r.status_code == 404


def test_failed_task_records_error():
    class _FailingConsolidator:
        def consolidate(self, *, dry_run: bool = False, progress=None):
            raise RuntimeError("boom")

    app = create_app()
    registry = ConsolidateTaskRegistry()
    app.state.consolidate_task_registry = registry
    app.dependency_overrides[consolidate_task_registry_dep] = lambda: registry
    app.dependency_overrides[consolidator_dep] = lambda: _FailingConsolidator()

    with TestClient(app) as c:
        post = c.post("/admin/consolidate", json={})
        status_url = post.json()["data"]["status_url"]
        result = _wait_task_done(c, status_url)
    assert result["state"] == "failed"
    assert result["error"]["code"] == "RuntimeError"
    assert "boom" in result["error"]["message"]
