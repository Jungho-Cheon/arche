"""MCP stdio 어댑터 단위 테스트 — PRD 3 §8.

검증 항목:
1. `build_mcp_server` 가 6 tool 을 등록 (write tool 미포함).
2. 각 tool 의 `inputSchema` 가 `$defs` 참조 없이 평탄화됨.
3. 각 tool 의 description 이 PRD 3 §2.2/§3.2/§4.2/§5.2/§6.2/§7.2 원문.
4. tool 호출이 services 함수로 위임.
5. 도메인 예외 → MCP 표준 에러 + `data.code` 매핑.

WHY 라우터 없이 직접 호출: list_tools / call_tool 데코레이터가 등록한 핸들러
는 server.request_handlers 안에 저장된다. 본 테스트는 *서버 객체 자체* 의 등록
상태와 직접 dispatch 결과를 검증.
"""

from __future__ import annotations

import asyncio
import json

import mcp.types as mcp_types
import pytest
from pydantic import ValidationError

from arche_api.domain.errors import (
    DependencyUnavailableError,
    EntityNotFoundError,
)
from arche_api.domain.models import Edge, Node, SourceRef, now_rfc3339
from arche_api.domain.ports import EntityTypeStat, NeighborhoodResult, RelationTypeStat
from arche_api.mcp_server import (
    WRITE_TOOL_NAMES_EXCLUDED,
    _build_tools,
    _dispatch_tool,
    _inline_defs,
    _to_mcp_error,
    build_mcp_server,
)

from .test_primitives import PrimitiveStubGraph

# ---------- helpers ----------


_ENT_A = "01HZX0G7M8N0RT0V0EXAMPLE01"
_ENT_B = "01HZX0G7M8N0RT0V0EXAMPLE02"


def _make_node(node_id: str = _ENT_A, name: str = "쿠폰") -> Node:
    now = now_rfc3339()
    return Node(
        id=node_id,
        name=name,
        type="coupon",
        aliases=[],
        description=None,
        properties={},
        source_refs=[SourceRef(source_path="/tmp/x.md")],
        created_at=now,
        updated_at=now,
    )


class _StubEmbedder:
    def embed(self, texts):
        return [[0.0] * 1536 for _ in texts]


class _StubSettings:
    embedding_model = "openai/text-embedding-3-small"
    embedding_dimension = 1536


# ---------- tool registration ----------


def test_build_tools_registers_exactly_six():
    """PRD 3 §0.1 의 6 primitive."""
    tools = _build_tools()
    names = [t.name for t in tools]
    assert names == [
        "get_schema",
        "find_entities",
        "get_entity",
        "get_neighbors",
        "find_path",
        "get_subgraph",
    ]


def test_no_write_tools_registered():
    """ADR-0006 D3 — write tool 등록 금지."""
    tools = _build_tools()
    names = {t.name for t in tools}
    assert not (names & WRITE_TOOL_NAMES_EXCLUDED)


def test_descriptions_match_prd():
    """PRD 3 §2.2 / §3.2 / §4.2 / §5.2 / §6.2 / §7.2 원문 — 측정 통제 변수."""
    tools = {t.name: t for t in _build_tools()}
    assert "Inspect the shape" in tools["get_schema"].description
    assert "hybrid retrieval" in tools["find_entities"].description
    assert "edge counts per relation type" in tools["get_entity"].description
    assert "Get neighbors of a node" in tools["get_neighbors"].description
    assert "Find paths between two nodes" in tools["find_path"].description
    assert "Extract a subgraph" in tools["get_subgraph"].description


# ---------- input_schema 평탄화 ----------


def test_input_schemas_have_no_defs_references():
    """`$defs` 참조가 inline 평탄화되어야 한다 (Claude Desktop 호환)."""
    tools = _build_tools()
    for tool in tools:
        schema = tool.inputSchema
        assert "$defs" not in schema, f"{tool.name} still has $defs"
        # 깊이 우선 walk 로 `$ref` 키가 어디에도 없는지 확인.
        _assert_no_refs(schema, path=tool.name)


def _assert_no_refs(node, *, path: str) -> None:
    if isinstance(node, dict):
        assert "$ref" not in node, f"$ref leaked at {path}"
        for k, v in node.items():
            _assert_no_refs(v, path=f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _assert_no_refs(v, path=f"{path}[{i}]")


def test_inline_defs_handles_ref_substitution():
    """$ref → inline 치환 동작 단위 검증."""
    raw = {
        "type": "object",
        "properties": {
            "child": {"$ref": "#/$defs/Child"},
        },
        "$defs": {"Child": {"type": "string", "maxLength": 5}},
    }
    out = _inline_defs(raw)
    assert "$defs" not in out
    assert out["properties"]["child"] == {"type": "string", "maxLength": 5}


def test_get_entity_input_schema_requires_id_with_ulid_pattern():
    """PRD 3 §4.3 — get_entity 의 MCP 입력 = { id: ULID }."""
    tools = {t.name: t for t in _build_tools()}
    schema = tools["get_entity"].inputSchema
    assert schema["required"] == ["id"]
    assert schema["properties"]["id"]["pattern"] == "^[0-9A-Z]{26}$"
    assert schema["additionalProperties"] is False


def test_get_neighbors_input_schema_includes_id_field():
    """PRD 3 §5.3 — MCP body 에 id 가 끼어 있어야 함 (REST path 와 다름)."""
    tools = {t.name: t for t in _build_tools()}
    schema = tools["get_neighbors"].inputSchema
    assert "id" in schema["properties"]
    assert "id" in schema["required"]
    assert schema["properties"]["id"]["pattern"] == "^[0-9A-Z]{26}$"


# ---------- dispatch (services 위임) ----------


def test_dispatch_get_schema_returns_payload():
    graph = PrimitiveStubGraph(
        entity_type_stats=[
            EntityTypeStat(type="coupon", count=3, examples=[(_ENT_A, "쿠폰")])
        ],
        relation_type_stats=[
            RelationTypeStat(type="applies_to", count=2, common_pairs=[])
        ],
    )
    out = _dispatch_tool(
        "get_schema",
        {},
        graph=graph,
        embedder=_StubEmbedder(),
        settings=_StubSettings(),
    )
    payload = out.model_dump()
    assert payload["entity_types"][0]["type"] == "coupon"
    assert payload["embedding_info"]["model"] == "openai/text-embedding-3-small"


def test_dispatch_get_entity_returns_payload():
    node = _make_node()
    graph = PrimitiveStubGraph(
        nodes=[node],
        edge_counts={_ENT_A: {"outgoing": {"applies_to": 2}, "incoming": {}}},
    )
    out = _dispatch_tool(
        "get_entity",
        {"id": _ENT_A},
        graph=graph,
        embedder=_StubEmbedder(),
        settings=_StubSettings(),
    )
    payload = out.model_dump()
    assert payload["node"]["id"] == _ENT_A
    assert payload["edge_counts"]["outgoing"] == {"applies_to": 2}


def test_dispatch_get_entity_missing_raises_entity_not_found():
    graph = PrimitiveStubGraph(nodes=[])
    with pytest.raises(EntityNotFoundError):
        _dispatch_tool(
            "get_entity",
            {"id": _ENT_A},
            graph=graph,
            embedder=_StubEmbedder(),
            settings=_StubSettings(),
        )


def test_dispatch_get_entity_missing_id_raises_value_error():
    graph = PrimitiveStubGraph(nodes=[])
    with pytest.raises(ValueError):
        _dispatch_tool(
            "get_entity",
            {},
            graph=graph,
            embedder=_StubEmbedder(),
            settings=_StubSettings(),
        )


def test_dispatch_get_neighbors_splits_id_from_body():
    node = _make_node()
    neighbor = _make_node(node_id=_ENT_B, name="여름")
    edge = Edge.model_validate(
        {
            "id": "01HZX0G7M8N0RT0V0EXAMPLE03",
            "from": _ENT_A,
            "to": _ENT_B,
            "type": "applies_to",
            "properties": {},
            "source_refs": [],
            "created_at": now_rfc3339(),
            "updated_at": now_rfc3339(),
        }
    )
    graph = PrimitiveStubGraph(
        nodes=[node, neighbor],
        neighbors_result=NeighborhoodResult(
            nodes=[node, neighbor], edges=[edge], truncated=False
        ),
    )
    out = _dispatch_tool(
        "get_neighbors",
        {"id": _ENT_A, "hops": 1, "direction": "both"},
        graph=graph,
        embedder=_StubEmbedder(),
        settings=_StubSettings(),
    )
    payload = out.model_dump(by_alias=True)
    assert payload["truncated"] is False
    assert {n["id"] for n in payload["nodes"]} == {_ENT_A, _ENT_B}
    assert payload["edges"][0]["from"] == _ENT_A


def test_dispatch_find_path_same_id_raises_unprocessable():
    from arche_api.domain.errors import UnprocessableError

    graph = PrimitiveStubGraph(nodes=[_make_node()])
    with pytest.raises(UnprocessableError):
        _dispatch_tool(
            "find_path",
            {"from_id": _ENT_A, "to_id": _ENT_A},
            graph=graph,
            embedder=_StubEmbedder(),
            settings=_StubSettings(),
        )


def test_dispatch_get_subgraph_echos_entry_ids():
    node = _make_node()
    graph = PrimitiveStubGraph(nodes=[node])
    out = _dispatch_tool(
        "get_subgraph",
        {"entry_ids": [_ENT_A], "hops": 1, "max_nodes": 100},
        graph=graph,
        embedder=_StubEmbedder(),
        settings=_StubSettings(),
    )
    payload = out.model_dump()
    assert payload["entry_ids"] == [_ENT_A]
    assert payload["nodes"][0]["id"] == _ENT_A


def test_dispatch_unknown_tool_raises_value_error():
    graph = PrimitiveStubGraph()
    with pytest.raises(ValueError, match="unknown tool"):
        _dispatch_tool(
            "delete_entity",
            {"id": _ENT_A},
            graph=graph,
            embedder=_StubEmbedder(),
            settings=_StubSettings(),
        )


# ---------- 에러 변환 ----------


def test_to_mcp_error_entity_not_found_carries_code():
    """PRD 3 §9 의 도메인 code 가 MCP 에러 data.code 에 노출."""
    exc = EntityNotFoundError("missing", details={"id": _ENT_A})
    err = _to_mcp_error(exc)
    assert isinstance(err, mcp_types.ErrorData)
    assert err.data["code"] == "entity_not_found"
    assert err.data["details"]["id"] == _ENT_A


def test_to_mcp_error_dependency_unavailable_carries_code():
    err = _to_mcp_error(DependencyUnavailableError("embed down"))
    assert err.data["code"] == "dependency_unavailable"


def test_to_mcp_error_validation_error_maps_to_invalid_input():
    """pydantic 검증 실패 → invalid_input."""
    try:
        from arche_api.api.schemas import FindEntitiesRequest

        FindEntitiesRequest.model_validate({"keywords": []})
    except ValidationError as ve:
        err = _to_mcp_error(ve)
        assert err.data["code"] == "invalid_input"
        errors = err.data["details"]["errors"]
        # REST 와 동일한 평탄화 (issue #26) — loc 점 표기 + type + msg 3 키만.
        assert any(
            e["loc"] == "keywords" and e["type"] == "too_short" for e in errors
        )
        assert all(set(e.keys()) == {"loc", "type", "msg"} for e in errors)
    else:
        raise AssertionError("expected ValidationError")


# ---------- build_mcp_server e2e (in-process) ----------


def test_build_mcp_server_call_tool_returns_text_payload():
    """call_tool 핸들러가 services 결과를 JSON text 로 직렬화."""
    node = _make_node()
    graph = PrimitiveStubGraph(
        nodes=[node],
        edge_counts={_ENT_A: {"outgoing": {}, "incoming": {}}},
    )
    server = build_mcp_server(graph, _StubEmbedder(), _StubSettings())

    # call_tool 데코레이터는 request_handlers 에 CallToolRequest 핸들러를 등록.
    # 핸들러 시그니처는 lowlevel 의 통상 형식 — `(req) -> CallToolResult` async.
    # 직접 invoke 하려면 request_handlers[CallToolRequest] 를 호출.
    handler = server.request_handlers[mcp_types.CallToolRequest]

    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name="get_entity", arguments={"id": _ENT_A}),
    )
    result = asyncio.run(handler(req))
    # ServerResult 안에 CallToolResult 가 wrap 되어 있다.
    inner = result.root
    assert isinstance(inner, mcp_types.CallToolResult)
    assert len(inner.content) == 1
    text_block = inner.content[0]
    assert isinstance(text_block, mcp_types.TextContent)
    payload = json.loads(text_block.text)
    assert payload["node"]["id"] == _ENT_A
    assert "edge_counts" in payload


def test_build_mcp_server_call_tool_returns_isError_with_domain_code():
    """도메인 예외 → CallToolResult(isError=True) + text 안 JSON 의 error.code.

    WHY isError + JSON body: SDK 의 call_tool 데코레이터는 raise 한 예외를 *짧은
    string* 으로만 변환하므로 PRD 3 §9 의 도메인 code 를 보존하려면 핸들러가
    직접 CallToolResult 를 만들어야 한다.
    """
    graph = PrimitiveStubGraph(nodes=[])
    server = build_mcp_server(graph, _StubEmbedder(), _StubSettings())
    handler = server.request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name="get_entity", arguments={"id": _ENT_A}),
    )
    result = asyncio.run(handler(req))
    inner = result.root
    assert isinstance(inner, mcp_types.CallToolResult)
    assert inner.isError is True
    body = json.loads(inner.content[0].text)
    assert body["error"]["code"] == "entity_not_found"
    assert body["error"]["details"]["id"] == _ENT_A


def test_build_mcp_server_list_tools_returns_six():
    graph = PrimitiveStubGraph()
    server = build_mcp_server(graph, _StubEmbedder(), _StubSettings())
    handler = server.request_handlers[mcp_types.ListToolsRequest]
    req = mcp_types.ListToolsRequest(method="tools/list")
    result = asyncio.run(handler(req))
    inner = result.root
    assert isinstance(inner, mcp_types.ListToolsResult)
    assert len(inner.tools) == 6
