"""reviewable ingest MCP tool 등록 단위 테스트 — Task 5.

검증 항목:
1. service/registry 없이 부팅한 서버 (read-only fake-boot 경로) 는 6 read tool
   만 노출하고 write tool 은 단 하나도 등록하지 않는다.
2. ingest_service + plan_registry 를 모두 주입하면 plan/preview/commit 세
   tool 이 추가된다 — 그러나 ADR-0006 D3 의 등록 금지 목록
   (WRITE_TOOL_NAMES_EXCLUDED, create_entity 등) 과는 겹치지 않는다.

WHY list_tools 를 직접 invoke: 기존 test_mcp_server.py 와 동일하게 데코레이터가
server.request_handlers[ListToolsRequest] 에 등록한 핸들러를 직접 호출해 *서버
객체 자체* 의 등록 상태를 본다.
"""

from __future__ import annotations

import asyncio

import mcp.types as mcp_types
import pytest

from arche_api.mcp_server import WRITE_TOOL_NAMES_EXCLUDED, build_mcp_server
from arche_api.test_support import FakeEmbedder, FakeGraph, FakeSettings


def _tools(server) -> list[mcp_types.Tool]:
    """등록된 Tool 객체 목록 — test_mcp_server.py 의 list_tools invoke 패턴 재사용."""
    handler = server.request_handlers[mcp_types.ListToolsRequest]
    req = mcp_types.ListToolsRequest(method="tools/list")
    result = asyncio.run(handler(req))
    inner = result.root
    assert isinstance(inner, mcp_types.ListToolsResult)
    return list(inner.tools)


def _tool_names(server) -> list[str]:
    """등록된 tool 이름 목록 — _tools 의 name 만 추린 헬퍼."""
    return [t.name for t in _tools(server)]


@pytest.fixture
def fake_ingest_service():
    """등록만 검증하므로 호출되지 않는 자리표시 service.

    build_mcp_server 는 service 가 None 인지만 보고 write tool 등록 여부를
    가른다 — 등록 경로에서 메서드를 호출하지 않으므로 빈 객체로 충분하다.
    """
    return object()


def test_read_only_server_has_no_write_tools():
    server = build_mcp_server(FakeGraph(), FakeEmbedder(), FakeSettings())
    names = _tool_names(server)
    assert "ingest_plan" not in names  # service 없으면 등록 안 됨
    assert "ingest_resolve" not in names  # resolve 도 service 없으면 등록 안 됨
    assert len(names) == 8  # 6 primitive + find_related (#140) + graph_health (#170/#171)


def test_server_with_service_exposes_ingest_write_tools(fake_ingest_service):
    from arche_api.api.plan_registry import PlanRegistry

    server = build_mcp_server(
        FakeGraph(),
        FakeEmbedder(),
        FakeSettings(),
        ingest_service=fake_ingest_service,
        plan_registry=PlanRegistry(),
    )
    names = _tool_names(server)
    assert {
        "ingest_plan",
        "ingest_preview",
        "ingest_resolve",
        "ingest_commit",
    } <= set(names)
    # write 금지 목록과는 겹치지 않아야 한다 (ADR-0006 D3).
    assert not (set(names) & WRITE_TOOL_NAMES_EXCLUDED)


def test_ingest_plan_input_schema_exposes_hints(fake_ingest_service):
    """ingest_plan 의 inputSchema 는 PlanIngestRequest 에서 파생되므로 enrichment
    hints 필드 (원문 불변 보강 메모) 가 자동 노출되어야 한다 — 회귀 잠금."""
    from arche_api.api.plan_registry import PlanRegistry

    server = build_mcp_server(
        FakeGraph(),
        FakeEmbedder(),
        FakeSettings(),
        ingest_service=fake_ingest_service,
        plan_registry=PlanRegistry(),
    )
    ingest_plan = next(t for t in _tools(server) if t.name == "ingest_plan")
    assert "hints" in ingest_plan.inputSchema["properties"]
