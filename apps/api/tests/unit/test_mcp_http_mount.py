"""MCP HTTP transport mount — ADR-0014 D1/D2 단위 테스트.

mount_mcp_routes 가 FastAPI app 에 정확한 endpoint 들을 등록하는지, 인증 미달
시 401 을 반환하는지 검증. 실제 streaming 동작은 integration 수준 — 본 단위는
*마운트 정합* 만.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opentology_api.mcp_http import mount_mcp_routes
from opentology_api.test_support import FakeEmbedder, FakeGraph, FakeSettings


def _app_with_mcp() -> FastAPI:
    app = FastAPI()
    mount_mcp_routes(
        app,
        graph=FakeGraph(),
        embedder=FakeEmbedder(),
        settings=FakeSettings(),
    )
    return app


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
    from opentology_api.api.auth import parse_authorization_header

    ctx = parse_authorization_header(None)
    assert ctx.namespace_id == "default"


def test_bearer_namespace_token_passes_auth_check():
    from opentology_api.api.auth import parse_authorization_header

    ctx = parse_authorization_header("Bearer ns:work-a")
    assert ctx.namespace_id == "work-a"
