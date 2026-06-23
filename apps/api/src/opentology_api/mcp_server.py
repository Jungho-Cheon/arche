"""MCP stdio 어댑터 — 6 graph primitive 를 표준 MCP tool 로 노출 (PRD 3 §8).

WHY 본 모듈의 존재: PRD 3 §0.1 — REST 와 MCP 는 *같은 입출력 스키마* . 본 어댑터
는 `api/services.py` 의 순수 함수를 직접 호출해 REST 라우터와 동일한 결과를
*인코딩만 다르게* 돌려준다 (JSON-RPC over stdio vs JSON over HTTP).

WHY input_schema source 단일화: PRD 3 §8.3 — 각 tool 의 input_schema 는 PRD 3
§2-7 의 JSON Schema 와 *완전 동일* . Pydantic 모델의 `model_json_schema()` 출력
을 그대로 입력 스키마로 쓰면 REST 의 OpenAPI 와 *같은 출처* 를 공유 — 한 곳을
바꾸면 두 통로 모두에 반영된다.

WHY `$defs` 평탄화: MCP 클라이언트 (Claude Desktop 포함) 는 *flat JSON Schema*
를 기대한다. Pydantic 의 `model_json_schema()` 가 generic / 중첩 모델에 대해
`$defs` 참조를 만들면 일부 클라이언트가 못 푼다. 본 모듈의 `_inline_defs` 가
참조를 모두 inline 해 자기완결 스키마로 변환.

WHY write tool 미노출: ADR-0006 D3 — Opentology MCP 는 *read-only* . admin
ingest / create_entity 같은 write 는 CLI 와 admin REST 에만 노출. 본 어댑터는
6 read tool 만 등록.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

import mcp.types as mcp_types
from mcp.server.lowlevel import Server
from pydantic import BaseModel, ValidationError

from .adapters.embedding import EmbeddingProvider
from .adapters.graph import GraphRepository
from .api import services
from .api.responses import (
    FindPathRequest,
    GetNeighborsRequest,
    GetSubgraphRequest,
)
from .api.schemas import FindEntitiesRequest
from .config import Settings
from .domain.errors import OpentologyError


logger = logging.getLogger(__name__)


# WHY 6 tool 의 description 을 한 곳에 모음: PRD 3 §2.2 / §3.2 / §4.2 / §5.2 /
# §6.2 / §7.2 의 영어 원문 그대로. 측정 결과의 reproducibility 영향 — 변경하려면
# PRD 3 amend 필요.
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_schema": (
        "Inspect the shape of the knowledge graph — entity types, relation "
        "types, counts, and example nodes per type."
    ),
    "find_entities": (
        "Find graph nodes matching one or more anchor keywords using lexical "
        "+ dense vector hybrid retrieval. Caller is expected to have "
        "extracted these keywords from a user question."
    ),
    "get_entity": (
        "Fetch full details of a single node by its ID, including direct edge "
        "counts per relation type."
    ),
    "get_neighbors": (
        "Get neighbors of a node, optionally filtered by relation type and "
        "direction, expanded up to N hops."
    ),
    "find_path": (
        "Find paths between two nodes — useful when reasoning about *how* "
        "two entities are related (e.g. 'why does coupon X apply to product "
        "Y'). Each path carries `hub_score`: the summed connectivity "
        "(log degree) of its *intermediate* nodes, endpoints excluded. "
        "LOWER hub_score = a more SPECIFIC path; HIGHER = the path leans on a "
        "promiscuous hub (a node linked to very many others) as a bridge, "
        "which often means 'connected but not meaningfully related'. Paths are "
        "returned lowest-hub_score first. TUNING: if your best path has a high "
        "hub_score, do not trust it as evidence — re-call with `relation_types` "
        "set to the specific relation you expect, to force a typed connection "
        "instead of a generic hub bridge. A hub_score of 0 means a direct or "
        "fully specific path."
    ),
    "get_subgraph": (
        "Extract a subgraph centered on multiple entry-point nodes, expanded "
        "N hops. Returns deduplicated nodes and edges within the radius."
    ),
}


# 노출 금지 (ADR-0006 D3) — 등록조차 하지 않는 write tool 이름. 단위 테스트가
# *이 이름 중 어느 것도 list_tools 에 등장하지 않음* 을 검증한다.
WRITE_TOOL_NAMES_EXCLUDED: frozenset[str] = frozenset(
    {"create_entity", "create_relation", "delete_entity", "delete_relation", "admin_ingest"}
)


def _build_input_schema(model_cls: type[BaseModel] | None) -> dict[str, Any]:
    """Pydantic 모델 → flat JSON Schema (MCP tool input_schema 형식).

    동작:
    1. `model_json_schema()` 호출.
    2. `$defs` 참조 (`{"$ref": "#/$defs/X"}`) 를 inline.
    3. 메타데이터 (title / description / $defs) 제거 — MCP 클라이언트가 무시
       하지만 잡음이 적도록.

    `model_cls=None` 은 `get_schema` 같은 *입력 없음* tool.
    """
    if model_cls is None:
        return {"type": "object", "additionalProperties": False, "properties": {}}
    raw = model_cls.model_json_schema()
    schema = _inline_defs(raw)
    # 모듈 docstring 같은 description 은 LLM 에 노이즈가 될 수 있으므로 제거.
    # 단 title 은 일부 클라이언트가 UX 표시에 쓰므로 유지.
    schema.pop("description", None)
    return schema


def _inline_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """`$defs` 와 `$ref` 를 재귀적으로 inline 해 자기완결 스키마로 변환.

    WHY 자체 구현: jsonschema 라이브러리의 RefResolver 도 가능하지만, 본 모듈은
    `pydantic.model_json_schema()` 출력 *형태만* 다루면 충분. 추가 의존성을
    피해 가벼운 walker 로 처리.

    동작 가정 — Pydantic v2 가 만드는 ref 는 항상 `#/$defs/<key>` 형식. 다른
    URI 는 처리하지 않는다 (사용처 없음).

    cycle 방지 — 자기 참조가 있는 모델은 본 코드에서 다루지 않는다 (현재 모델
    들은 모두 비순환). 만약 추후 순환 모델이 들어오면 별도 처리 필요.
    """
    schema = copy.deepcopy(schema)
    defs: dict[str, Any] = schema.pop("$defs", {}) or {}

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                key = ref.split("/")[-1]
                target = defs.get(key)
                if target is None:
                    # 참조가 깨졌으면 원본을 보존 (방어).
                    return node
                # ref 대체 + sibling 키 (description 등) 머지.
                merged = _walk(copy.deepcopy(target))
                if isinstance(merged, dict):
                    for k, v in node.items():
                        if k == "$ref":
                            continue
                        merged.setdefault(k, v)
                return merged
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(item) for item in node]
        return node

    walked = _walk(schema)
    assert isinstance(walked, dict)
    return walked


def _build_tools() -> list[mcp_types.Tool]:
    """6 tool 의 등록 manifest — PRD 3 §0.1 의 1:1 매핑 표."""
    return [
        mcp_types.Tool(
            name="get_schema",
            description=_TOOL_DESCRIPTIONS["get_schema"],
            inputSchema=_build_input_schema(None),
        ),
        mcp_types.Tool(
            name="find_entities",
            description=_TOOL_DESCRIPTIONS["find_entities"],
            inputSchema=_build_input_schema(FindEntitiesRequest),
        ),
        mcp_types.Tool(
            name="get_entity",
            description=_TOOL_DESCRIPTIONS["get_entity"],
            # PRD 3 §4.3 — MCP 입력은 `{ id }` (REST 는 URL path)
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "required": ["id"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[0-9A-Z]{26}$"},
                },
            },
        ),
        mcp_types.Tool(
            name="get_neighbors",
            description=_TOOL_DESCRIPTIONS["get_neighbors"],
            # PRD 3 §5.3 — MCP 입력은 body 필드 + id 를 *한 객체* 로 합친 형태.
            # REST 는 URL path 가 id 를 받지만 MCP 는 단일 입력 객체이므로 id 를
            # 풀어서 포함.
            inputSchema=_merge_id_into_schema(
                _build_input_schema(GetNeighborsRequest)
            ),
        ),
        mcp_types.Tool(
            name="find_path",
            description=_TOOL_DESCRIPTIONS["find_path"],
            inputSchema=_build_input_schema(FindPathRequest),
        ),
        mcp_types.Tool(
            name="get_subgraph",
            description=_TOOL_DESCRIPTIONS["get_subgraph"],
            inputSchema=_build_input_schema(GetSubgraphRequest),
        ),
    ]


def _merge_id_into_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """`get_neighbors` 의 입력 — REST 의 URL path id 를 MCP body 안에 합친다.

    PRD 3 §5.3 의 JSON Schema 는 `id` + `relation_types` + `direction` + `hops`
    + `max_nodes` 를 *한 객체* 로 묶는다. REST 는 URL path 가 id 를 운반하지만
    MCP 는 단일 입력 객체이므로 id 를 properties 에 끼워 넣어야 PRD 와 정확
    일치한다.
    """
    out = copy.deepcopy(schema)
    props = out.setdefault("properties", {})
    props["id"] = {"type": "string", "pattern": "^[0-9A-Z]{26}$"}
    required = list(out.get("required", []))
    if "id" not in required:
        required.insert(0, "id")
    out["required"] = required
    return out


# ---------- tool 실행 디스패치 ----------


def _dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    graph: GraphRepository,
    embedder: EmbeddingProvider,
    settings: Settings,
) -> BaseModel:
    """단일 tool 호출을 services 로 위임. 입력 검증 실패는 ValidationError 로 전파."""
    if name == "get_schema":
        return services.get_schema(graph=graph, settings=settings)
    if name == "find_entities":
        body = FindEntitiesRequest.model_validate(arguments)
        return services.find_entities(body, graph=graph, embedder=embedder)
    if name == "get_entity":
        entity_id = arguments.get("id")
        if not isinstance(entity_id, str):
            raise ValueError("`id` is required and must be a string")
        return services.get_entity(entity_id=entity_id, graph=graph)
    if name == "get_neighbors":
        # WHY id 분리: services.get_neighbors 는 entity_id 와 body 를 분리해 받는
        # 다. MCP 입력은 한 객체이므로 id 만 떼어 body 모델에 검증을 맡긴다.
        args = dict(arguments)
        entity_id = args.pop("id", None)
        if not isinstance(entity_id, str):
            raise ValueError("`id` is required and must be a string")
        body = GetNeighborsRequest.model_validate(args)
        return services.get_neighbors(entity_id=entity_id, body=body, graph=graph)
    if name == "find_path":
        body = FindPathRequest.model_validate(arguments)
        return services.find_path(body, graph=graph)
    if name == "get_subgraph":
        body = GetSubgraphRequest.model_validate(arguments)
        return services.get_subgraph(body, graph=graph)
    # 등록되지 않은 이름 — MCP 클라이언트의 잘못된 호출.
    raise ValueError(f"unknown tool: {name}")


# ---------- 에러 변환 ----------


# WHY 에러 매핑 표를 명시: PRD 3 §9 의 code 카탈로그를 MCP 표준 에러 형식의
# data.code 에 그대로 노출. MCP 의 JSON-RPC code 는 -32602 (invalid params) /
# -32603 (internal) 같은 표준값을 쓰되, *Opentology 의 code* 는 data.code 에
# 함께 실어 caller 가 분류 가능하게 한다.
_OPENTOLOGY_TO_RPC_CODE: dict[str, int] = {
    "invalid_input": -32602,
    "unsupported_file_type": -32602,
    "entity_not_found": -32602,
    "unprocessable": -32602,
    "dependency_unavailable": -32603,
    "rate_limited": -32603,
    "internal_error": -32603,
}


def _to_mcp_error(exc: BaseException) -> mcp_types.ErrorData:
    """도메인 / 검증 예외 → MCP 표준 에러 (data.code 에 Opentology code).

    분기:
    - OpentologyError → 도메인 code (§9 카탈로그) 그대로 data.code.
    - pydantic ValidationError → invalid_input.
    - 그 외 → internal_error.
    """
    if isinstance(exc, OpentologyError):
        return mcp_types.ErrorData(
            code=_OPENTOLOGY_TO_RPC_CODE.get(exc.code, -32603),
            message=exc.message,
            data={"code": exc.code, "details": exc.details},
        )
    if isinstance(exc, ValidationError):
        return mcp_types.ErrorData(
            code=-32602,
            message="invalid input",
            data={"code": "invalid_input", "details": {"errors": exc.errors()}},
        )
    if isinstance(exc, ValueError):
        # 단일 string 인자 같은 가벼운 입력 위반.
        return mcp_types.ErrorData(
            code=-32602,
            message=str(exc),
            data={"code": "invalid_input"},
        )
    logger.exception("MCP tool raised unexpected exception")
    return mcp_types.ErrorData(
        code=-32603,
        message="internal error",
        data={"code": "internal_error"},
    )


# ---------- 서버 구성 ----------


def build_mcp_server(
    graph: GraphRepository,
    embedder: EmbeddingProvider,
    settings: Settings,
) -> Server:
    """MCP Server 객체 생성 + 6 tool 등록.

    반환된 서버는 `mcp.server.stdio.stdio_server()` async context 안에서
    `server.run(read, write, server.create_initialization_options())` 로 구동.
    """
    server: Server = Server(
        name="opentology",
        version="0.1.0",
        instructions=(
            "Opentology graph primitives. Read-only. Use `get_schema` first to "
            "inspect the graph shape, then `find_entities` to anchor user "
            "keywords to nodes, and traverse with `get_neighbors` / "
            "`find_path` / `get_subgraph`."
        ),
    )

    tools = _build_tools()
    _assert_no_write_tools(tools)

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return tools

    @server.call_tool()
    async def _call_tool(
        name: str, arguments: dict[str, Any]
    ) -> mcp_types.CallToolResult:
        """MCP tool 호출 — payload (PRD 3 §0.4: envelope 없음) 를 JSON text 로 반환.

        WHY CallToolResult 직접 반환: MCP SDK 의 call_tool 데코레이터는 핸들러가
            raise 한 일반 Exception 을 잡아 *짧은 문자열 에러 메시지* 로만 변환
            한다 (data.code 같은 구조 정보 손실). 본 어댑터는 PRD 3 §9 의 도메인
            code 를 보존해야 하므로 핸들러가 *직접* `CallToolResult(isError=True,
            content=[<JSON error body>])` 를 반환한다. caller (Claude Desktop /
            테스트) 는 isError 플래그로 분기 후 text content 를 JSON 파싱해
            `{ "error": { code, message, details } }` 로 도메인 정보를 얻는다.

        WHY text content type: MCP 의 ContentBlock 중 `TextContent` 는 모든
            클라이언트가 보장. 추후 structured content 로 바꿀 수 있지만 MVP 는
            text 가 가장 호환성 높다.
        """
        try:
            result = _dispatch_tool(
                name, arguments, graph=graph, embedder=embedder, settings=settings
            )
        except BaseException as exc:  # noqa: BLE001
            err = _to_mcp_error(exc)
            body = {
                "error": {
                    "code": (err.data or {}).get("code", "internal_error"),
                    "message": err.message,
                    "details": (err.data or {}).get("details", {}),
                }
            }
            return mcp_types.CallToolResult(
                content=[
                    mcp_types.TextContent(
                        type="text", text=json.dumps(body, ensure_ascii=False)
                    )
                ],
                isError=True,
            )

        # payload — Pydantic 모델 → dict → JSON 직렬화. by_alias 로 Edge.from_
        # → from 직렬화.
        payload = result.model_dump(by_alias=True, exclude_none=False)
        text = json.dumps(payload, ensure_ascii=False)
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=text)],
            isError=False,
        )

    return server


def _assert_no_write_tools(tools: list[mcp_types.Tool]) -> None:
    """등록 직전 안전 가드 — ADR-0006 D3 의 read-only 계약을 코드 레벨에서 보호."""
    names = {t.name for t in tools}
    leaked = names & WRITE_TOOL_NAMES_EXCLUDED
    if leaked:
        raise RuntimeError(
            f"refusing to register write tools (ADR-0006 D3): {sorted(leaked)}"
        )


# ---------- stdio 실행 진입점 (CLI 에서 호출) ----------


async def run_stdio_server(
    graph: GraphRepository,
    embedder: EmbeddingProvider,
    settings: Settings,
) -> None:
    """stdio transport 로 서버를 띄운다.

    WHY async: MCP SDK 의 server.run 은 async. CLI 진입점에서 `asyncio.run` 으로
    호출한다.
    """
    from mcp.server.stdio import stdio_server  # local import — 부팅 시 SDK 로딩 비용 한 번만.

    server = build_mcp_server(graph, embedder, settings)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
