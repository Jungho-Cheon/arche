"""Arche REST 클라이언트 단위 — httpx.MockTransport 로 응답 mock."""

from __future__ import annotations

import httpx
import pytest

from arche_eval.clients import (
    ArcheClient,
    ArcheClientError,
    ArcheUnavailableError,
)


def _mock_client(handler) -> ArcheClient:
    transport = httpx.MockTransport(handler)
    inner = httpx.Client(transport=transport, base_url="http://test")
    return ArcheClient(base_url="http://test", client=inner)


def test_get_schema_unwraps_data_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/schema"
        return httpx.Response(
            200,
            json={
                "data": {
                    "entity_types": [],
                    "relation_types": [],
                    "embedding_info": {"model": "m", "dimension": 1},
                }
            },
        )

    client = _mock_client(handler)
    data = client.get_schema()
    assert "entity_types" in data
    assert "embedding_info" in data


def test_find_entities_sends_keywords_and_limit() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"data": {"matches": [{"node": {"id": "X"}, "score": 0.9}]}},
        )

    client = _mock_client(handler)
    data = client.find_entities(keywords=["쿠폰 X"], limit=5, include_scores=True)
    assert seen["body"]["keywords"] == ["쿠폰 X"]
    assert seen["body"]["limit"] == 5
    assert seen["body"]["include_scores"] is True
    assert data["matches"][0]["node"]["id"] == "X"


def test_error_envelope_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "error": {
                    "code": "entity_not_found",
                    "message": "no such id",
                    "details": {"id": "Z"},
                }
            },
        )

    client = _mock_client(handler)
    with pytest.raises(ArcheClientError) as ei:
        client.get_entity(id="Z")
    assert ei.value.status_code == 404
    assert ei.value.code == "entity_not_found"
    assert ei.value.details == {"id": "Z"}


def test_network_failure_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = _mock_client(handler)
    with pytest.raises(ArcheUnavailableError):
        client.get_schema()


def test_non_json_response_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    client = _mock_client(handler)
    with pytest.raises(ArcheUnavailableError):
        client.get_schema()


def test_primitive_call_log_records_result_size() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "nodes": [{"id": "A"}, {"id": "B"}],
                    "edges": [{"id": "E1"}],
                    "entry_ids": ["A"],
                    "truncated": False,
                }
            },
        )

    client = _mock_client(handler)
    log: list = []
    data = client.get_subgraph(entry_ids=["A"], hops=2, log=log)
    assert len(data["nodes"]) == 2
    assert len(log) == 1
    assert log[0].name == "get_subgraph"
    assert log[0].result_size == {"nodes": 2, "edges": 1, "truncated": False}
    assert log[0].latency_ms >= 0
    assert log[0].input["entry_ids"] == ["A"]


def test_primitive_call_log_records_error_when_envelope_returns_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": {
                    "code": "unprocessable",
                    "message": "from_id == to_id",
                }
            },
        )

    client = _mock_client(handler)
    log: list = []
    with pytest.raises(ArcheClientError):
        client.find_path(from_id="X", to_id="X", log=log)
    assert len(log) == 1
    assert log[0].name == "find_path"
    assert log[0].error is not None
    assert log[0].error["code"] == "unprocessable"


def test_admin_ingest_polling_succeeds() -> None:
    states = iter(
        [
            {
                "task_id": "t",
                "state": "running",
                "progress": {},
                "metrics": {},
                "error": None,
            },
            {
                "task_id": "t",
                "state": "succeeded",
                "progress": {},
                "metrics": {},
                "error": None,
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": next(states)})

    client = _mock_client(handler)
    result = client.wait_for_ingest(
        task_id="t", poll_interval_seconds=0.0, max_wait_seconds=1.0
    )
    assert result["state"] == "succeeded"


def test_admin_ingest_polling_failed_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "task_id": "t",
                    "state": "failed",
                    "progress": {},
                    "metrics": {},
                    "error": {"code": "bad_thing", "message": "oops"},
                }
            },
        )

    client = _mock_client(handler)
    with pytest.raises(ArcheClientError) as ei:
        client.wait_for_ingest(
            task_id="t", poll_interval_seconds=0.0, max_wait_seconds=1.0
        )
    assert ei.value.code == "bad_thing"
