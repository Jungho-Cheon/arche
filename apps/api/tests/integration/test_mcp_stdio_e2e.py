"""MCP stdio e2e — 본 서버를 subprocess 로 spawn 해 핸드셰이크 + 6 tool 호출.

검증 흐름:
1. stdio_client 가 `opentology mcp serve --stdio` 를 subprocess 로 띄움.
2. ClientSession.initialize() → JSON-RPC 핸드셰이크 성공.
3. list_tools() → 6 tool 확인.
4. call_tool(get_schema / find_entities / get_entity / get_neighbors / find_path
   / get_subgraph) → 각각 PRD 3 §2-7 의 출력 형태.
5. 에러 케이스 (없는 ID) → isError=True + 도메인 code.

WHY subprocess (in-process 아님): MCP SDK 의 stdio transport 는 *실제 stdin/
stdout 스트림* 을 통해 JSON-RPC 메시지를 주고받는다. in-process 로 read/write
스트림을 만들어 server.run 을 직접 돌리는 방법도 있으나, 본 테스트는 *사용자
환경 (Claude Desktop) 과 동일한 spawn 경로* 를 검증해 stdio 핸드셰이크 회귀를
잡는 게 목적이라 subprocess 로 띄운다.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


_ENT_A = "01HZX0G7M8N0RT0V0EXAMPLE01"
_ENT_B = "01HZX0G7M8N0RT0V0EXAMPLE02"


def _server_params() -> StdioServerParameters:
    """본 서버를 fake graph 모드로 spawn 하는 파라미터.

    WHY `sys.executable -m opentology_api.cli`: pytest 가 띄운 가상환경의 Python
    을 그대로 재사용해 *같은 site-packages* 로 서버를 띄운다. shell PATH 의
    `opentology` 가 다른 환경을 가리킬 위험을 회피.
    """
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "opentology_api.cli", "mcp", "serve", "--stdio"],
        env={
            **os.environ,
            "OPENTOLOGY_TEST_FAKE_GRAPH": "1",
        },
    )


async def test_initialize_and_list_tools_returns_six():
    """initialize 핸드셰이크 + 6 tool list."""
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            names = [t.name for t in result.tools]
            assert names == [
                "get_schema",
                "find_entities",
                "get_entity",
                "get_neighbors",
                "find_path",
                "get_subgraph",
            ]


async def test_call_get_schema_returns_entity_types():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_schema", arguments={})
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            types_ = {e["type"] for e in payload["entity_types"]}
            assert types_ == {"coupon", "product"}
            assert payload["embedding_info"]["dimension"] == 1536


async def test_call_get_entity_returns_node():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_entity", arguments={"id": _ENT_A})
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            assert payload["node"]["id"] == _ENT_A
            assert payload["edge_counts"]["outgoing"] == {"applies_to": 1}


async def test_call_get_entity_not_found_returns_isError_with_code():
    """없는 ID → isError=True + body.error.code = entity_not_found (PRD 3 §9)."""
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "get_entity", arguments={"id": "01HZX0G7M8N0RT0V0EXAMPLE99"}
            )
            assert result.isError is True
            body = json.loads(result.content[0].text)
            assert body["error"]["code"] == "entity_not_found"


async def test_call_get_neighbors_returns_edges():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "get_neighbors",
                arguments={"id": _ENT_A, "hops": 1, "direction": "both"},
            )
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            ids = {n["id"] for n in payload["nodes"]}
            assert ids == {_ENT_A, _ENT_B}
            assert payload["edges"][0]["from"] == _ENT_A
            assert payload["truncated"] is False


async def test_call_find_path_returns_path():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "find_path",
                arguments={"from_id": _ENT_A, "to_id": _ENT_B},
            )
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            assert len(payload["paths"]) == 1
            path = payload["paths"][0]
            assert path["length"] == 1
            assert [n["id"] for n in path["nodes"]] == [_ENT_A, _ENT_B]


async def test_call_find_path_same_id_returns_unprocessable():
    """from == to → isError + unprocessable (PRD 3 §9, §6)."""
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "find_path",
                arguments={"from_id": _ENT_A, "to_id": _ENT_A},
            )
            assert result.isError is True
            body = json.loads(result.content[0].text)
            assert body["error"]["code"] == "unprocessable"


async def test_call_get_subgraph_echos_entry_ids():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "get_subgraph",
                arguments={"entry_ids": [_ENT_A, _ENT_B], "hops": 1, "max_nodes": 50},
            )
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            assert payload["entry_ids"] == [_ENT_A, _ENT_B]
            assert {n["id"] for n in payload["nodes"]} == {_ENT_A, _ENT_B}


async def test_call_find_entities_returns_match():
    """간단 lexical 매칭 — '쿠폰' 키워드로 node_a 가 surface 되어야 함."""
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "find_entities",
                arguments={"keywords": ["쿠폰"], "limit": 5},
            )
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            assert len(payload["matches"]) >= 1
            assert payload["matches"][0]["node"]["name"] == "여름 쿠폰"


async def test_invalid_input_schema_rejected_by_sdk():
    """SDK 가 inputSchema 로 입력을 검증 — 빈 keywords 는 minItems 위반."""
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "find_entities",
                arguments={"keywords": []},
            )
            # SDK 의 inputSchema validation 실패 — isError=True 단계에서 차단.
            assert result.isError is True
