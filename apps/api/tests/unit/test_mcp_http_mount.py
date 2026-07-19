"""MCP HTTP transport mount — ADR-0014 D1/D2 단위 테스트.

mount_mcp_routes 가 FastAPI app 에 정확한 endpoint 들을 등록하는지, 인증 미달
시 401 을 반환하는지 검증. 실제 streaming 동작은 integration 수준 — 본 단위는
*마운트 정합* 만.
"""

from __future__ import annotations

import asyncio

import mcp.types as mcp_types
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arche_api.mcp_http import mount_mcp_routes
from arche_api.test_support import FakeEmbedder, FakeGraph, FakeSettings


def _app_with_mcp() -> FastAPI:
    app = FastAPI()
    mount_mcp_routes(
        app,
        graph=FakeGraph(),
        embedder=FakeEmbedder(),
        settings=FakeSettings(),
    )
    return app


def _mounted_tool_names(app: FastAPI) -> list[str]:
    """마운트된 MCP 서버가 노출하는 도구 이름 목록.

    mount_mcp_routes 가 app.state.mcp_server 에 얹어 둔 서버 객체의 list_tools
    핸들러를 직접 호출한다 (test_mcp_write_tools.py 의 invoke 패턴과 동일).
    """
    server = app.state.mcp_server
    handler = server.request_handlers[mcp_types.ListToolsRequest]
    req = mcp_types.ListToolsRequest(method="tools/list")
    result = asyncio.run(handler(req))
    return [t.name for t in result.root.tools]


def test_routes_mounted_at_v1_prefix():
    app = _app_with_mcp()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/mcp/v1/sse" in paths
    assert "/mcp/v1/message" in paths
    assert "/mcp/v1/" in paths


def test_authorization_invalid_scheme_returns_401():
    app = _app_with_mcp()
    with TestClient(app) as c:
        r = c.post("/mcp/v1/", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401
    body = r.json()
    assert body["detail"]["error"]["code"] == "not_authorized"


def test_no_authorization_does_not_block_at_auth_layer():
    # 인증 헤더 없으면 default namespace — auth layer 가 401 던지지 않음.
    # 실제 streaming endpoint 동작은 별도 integration 단계에서.
    from arche_api.api.auth import parse_authorization_header

    ctx = parse_authorization_header(None)
    assert ctx.namespace_id == "default"


def test_bearer_namespace_token_passes_auth_check():
    from arche_api.api.auth import parse_authorization_header

    ctx = parse_authorization_header("Bearer ns:work-a")
    assert ctx.namespace_id == "work-a"


# ---------- #107 — HTTP 전송의 적재 도구 동등성 (stdio 와 같은 도구 노출) ----------


def test_http_mount_without_ingest_exposes_only_read_tools():
    """ingest_service/plan_registry 미주입 시 조회 도구만 (6 primitive + find_related)."""
    app = _app_with_mcp()
    names = _mounted_tool_names(app)
    assert len(names) == 7  # 6 primitive + find_related (#140)
    assert "ingest_plan" not in names
    assert "ingest_commit" not in names


def test_http_mount_with_ingest_exposes_all_tools_like_stdio():
    """ingest_service + plan_registry 를 주입하면 HTTP 전송도 검토형 적재 도구
    4개를 더해 stdio serve 와 같은 도구 집합(7 read + 4 ingest)을 노출한다 (#107)."""
    from arche_api.api.plan_registry import PlanRegistry

    app = FastAPI()
    mount_mcp_routes(
        app,
        graph=FakeGraph(),
        embedder=FakeEmbedder(),
        settings=FakeSettings(),
        ingest_service=object(),  # 등록 여부만 보므로 자리표시로 충분
        plan_registry=PlanRegistry(),
    )
    names = set(_mounted_tool_names(app))
    assert {
        "ingest_plan",
        "ingest_preview",
        "ingest_resolve",
        "ingest_commit",
    } <= names
    assert len(names) == 11  # 7 read (6 primitive + find_related) + 4 ingest
