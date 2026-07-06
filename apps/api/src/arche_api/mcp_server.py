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

WHY write tool 노출 제한: ADR-0006 D3 — `create_entity` / `delete_relation`
같은 *직접 그래프 변형* write 는 MCP 에 노출하지 않는다 (CLI 와 admin REST
전용). 단 reviewable ingest 의 4 tool (ingest_plan / ingest_preview /
ingest_resolve / ingest_commit) 은 예외다: 사람의 미리보기 + 확인 latch 를
강제하므로, LLM 이 검토 없이 그래프를 바꾸지 못한다. 이 네 tool 은 `ingest_service` 와
`plan_registry` 가 *함께 주입된* 서버에서만 등록된다 (production serve 경로).
LLM 이 없는 read-only fake-boot 경로는 6 read tool 만 노출한다.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import TYPE_CHECKING, Any

import mcp.types as mcp_types
from mcp.server.lowlevel import Server
from pydantic import BaseModel, ValidationError

from arche_api.domain.ports import EmbeddingProvider, GraphRepository

from .api import services
from .api.error_codes import flatten_validation_errors
from .api.plan_schemas import (
    CommitRequest,
    PlanIngestRequest,
    PreviewRequest,
    ResolveRequest,
)
from .api.responses import (
    FindPathRequest,
    GetNeighborsRequest,
    GetSubgraphRequest,
)
from .api.schemas import FindEntitiesRequest
from .config import Settings
from .domain.errors import ArcheError

if TYPE_CHECKING:
    from .api.plan_registry import PlanRegistry
    from .domain.ingest import IngestService

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
    # reviewable ingest (plan -> preview -> commit). 이 세 tool 은 LLM 이 사람의
    # 검토를 *건너뛰고* 그래프를 바꾸지 못하도록 다음 행동 지침을 description 에
    # 명시한다. ingest_service + plan_registry 가 주입된 서버에서만 등록된다.
    "ingest_plan": (
        "Plan ingestion of a single file: run extraction WITHOUT writing to "
        "the graph, stash the change set under a returned `plan_id`, and return "
        "a count summary (entities to create/merge, relations to create, "
        "deletions). After planning you MUST call ingest_preview and show the "
        "human the delta, then ingest_commit only after the human confirms. "
        "Never plan and commit in one breath. Optionally pass `hints` (a "
        "glossary or domain notes) to improve extraction of a poorly-structured "
        "document; hints never modify the stored source, they only guide "
        "extraction. Optionally pass `namespace_id` to plan into a specific "
        "namespace (default \"default\"); the plan keeps that namespace through "
        "preview/resolve/commit, so identity matching and writes stay inside it."
    ),
    "ingest_preview": (
        "Expand a planned change set (by `plan_id`) item by item — the new "
        "entities, merges into existing entities, new relations, and deletion "
        "count — so the human can review it before anything touches the graph. "
        "This call also arms the safety latch that ingest_commit requires. The "
        "response also carries `questions`: if it is non-empty, the extraction "
        "found new entities that look close to existing ones but not close "
        "enough to merge automatically. You MUST ask the human about each "
        "question and call ingest_resolve with their answers before commit."
    ),
    "ingest_resolve": (
        "Apply the human's answers to a plan's open `questions` (by `plan_id`). "
        "Each resolution pairs a `question_id` with a `decision`: \"merge\" "
        "means the new entity is the SAME as the suggested existing entity, "
        "\"keep\" means it is genuinely new and distinct. This refines the same "
        "plan_id in place and clears the safety latch, so you MUST call "
        "ingest_preview again afterwards (and review any remaining questions) "
        "before ingest_commit."
    ),
    "ingest_commit": (
        "Apply a previously previewed plan (by `plan_id`) to the graph. Do not "
        "call without a prior ingest_preview on this plan_id: commit is "
        "rejected (unprocessable) unless the plan was previewed, and also "
        "rejected if the graph drifted and the plan went stale (re-plan)."
    ),
}


# reviewable ingest tool 이름 — service 주입 시에만 등록되는 plan/preview/resolve/commit.
# WRITE_TOOL_NAMES_EXCLUDED (등록 금지 목록) 와는 *별개* 다: 이 네 tool 은 사람
# 검토 latch 를 통과한 변경만 반영하므로 허용된다.
INGEST_TOOL_NAMES: tuple[str, ...] = (
    "ingest_plan",
    "ingest_preview",
    "ingest_resolve",
    "ingest_commit",
)


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


def _build_ingest_tools() -> list[mcp_types.Tool]:
    """reviewable ingest 의 4 tool — service 가 주입된 서버에서만 등록.

    입력 스키마는 plan_schemas 의 Pydantic 모델에서 그대로 끌어와 REST 통로와
    같은 출처를 공유한다 (read tool 과 동일 원칙). ingest_plan 은 `{path}`,
    preview/commit 은 `{plan_id}`, resolve 는 `{plan_id, resolutions}`.
    """
    return [
        mcp_types.Tool(
            name="ingest_plan",
            description=_TOOL_DESCRIPTIONS["ingest_plan"],
            inputSchema=_build_input_schema(PlanIngestRequest),
        ),
        mcp_types.Tool(
            name="ingest_preview",
            description=_TOOL_DESCRIPTIONS["ingest_preview"],
            inputSchema=_build_input_schema(PreviewRequest),
        ),
        mcp_types.Tool(
            name="ingest_resolve",
            description=_TOOL_DESCRIPTIONS["ingest_resolve"],
            inputSchema=_build_input_schema(ResolveRequest),
        ),
        mcp_types.Tool(
            name="ingest_commit",
            description=_TOOL_DESCRIPTIONS["ingest_commit"],
            inputSchema=_build_input_schema(CommitRequest),
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
    ingest_service: IngestService | None = None,
    plan_registry: PlanRegistry | None = None,
) -> BaseModel:
    """단일 tool 호출을 services 로 위임. 입력 검증 실패는 ValidationError 로 전파.

    WHY namespace: MCP(stdio)는 HTTP auth 가 없으므로 질의 namespace 를 도구 인자의
    `namespace_id`(미지정 시 "default")로 받는다 (issue #98 읽기 격리). REST 는 auth
    header 로 결정 — 두 표면이 같은 services 함수에 namespace 를 흘려보낸다.
    """
    # 인자에 실린 namespace (없으면 "default"). 4 body 도구는 검증된 body 에서,
    # get_schema/get_entity 는 인자 dict 에서 직접 꺼낸다.
    arg_ns = arguments.get("namespace_id") or "default"
    if name == "get_schema":
        return services.get_schema(
            graph=graph, settings=settings, namespace_id=arg_ns
        )
    if name == "find_entities":
        body = FindEntitiesRequest.model_validate(arguments)
        return services.find_entities(
            body,
            graph=graph,
            embedder=embedder,
            namespace_id=body.namespace_id or "default",
        )
    if name == "get_entity":
        entity_id = arguments.get("id")
        if not isinstance(entity_id, str):
            raise ValueError("`id` is required and must be a string")
        return services.get_entity(
            entity_id=entity_id, graph=graph, namespace_id=arg_ns
        )
    if name == "get_neighbors":
        # WHY id 분리: services.get_neighbors 는 entity_id 와 body 를 분리해 받는
        # 다. MCP 입력은 한 객체이므로 id 만 떼어 body 모델에 검증을 맡긴다.
        args = dict(arguments)
        entity_id = args.pop("id", None)
        if not isinstance(entity_id, str):
            raise ValueError("`id` is required and must be a string")
        body = GetNeighborsRequest.model_validate(args)
        return services.get_neighbors(
            entity_id=entity_id,
            body=body,
            graph=graph,
            namespace_id=body.namespace_id or "default",
        )
    if name == "find_path":
        body = FindPathRequest.model_validate(arguments)
        return services.find_path(
            body, graph=graph, namespace_id=body.namespace_id or "default"
        )
    if name == "get_subgraph":
        body = GetSubgraphRequest.model_validate(arguments)
        return services.get_subgraph(
            body, graph=graph, namespace_id=body.namespace_id or "default"
        )
    # reviewable ingest — service/registry 가 주입된 서버에서만 등록되므로, 여기
    # 도달했다면 둘 다 존재한다. 방어적으로 None 을 막는다.
    if name in INGEST_TOOL_NAMES:
        if ingest_service is None or plan_registry is None:
            raise ValueError(f"tool `{name}` requires an ingest service")
        if name == "ingest_plan":
            plan_body = PlanIngestRequest.model_validate(arguments)
            return services.plan_ingest(
                plan_body, service=ingest_service, registry=plan_registry
            )
        if name == "ingest_preview":
            preview_body = PreviewRequest.model_validate(arguments)
            return services.preview_plan(preview_body, registry=plan_registry)
        if name == "ingest_resolve":
            resolve_body = ResolveRequest.model_validate(arguments)
            return services.resolve_ingest(
                resolve_body, service=ingest_service, registry=plan_registry
            )
        # ingest_commit
        commit_body = CommitRequest.model_validate(arguments)
        return services.commit_plan(
            commit_body, service=ingest_service, registry=plan_registry
        )
    # 등록되지 않은 이름 — MCP 클라이언트의 잘못된 호출.
    raise ValueError(f"unknown tool: {name}")


# ---------- 에러 변환 ----------


# WHY 에러 매핑 표를 명시: PRD 3 §9 의 code 카탈로그를 MCP 표준 에러 형식의
# data.code 에 그대로 노출. MCP 의 JSON-RPC code 는 -32602 (invalid params) /
# -32603 (internal) 같은 표준값을 쓰되, *Arche 의 code* 는 data.code 에
# 함께 실어 caller 가 분류 가능하게 한다.
_ARCHE_TO_RPC_CODE: dict[str, int] = {
    "invalid_input": -32602,
    "unsupported_file_type": -32602,
    "entity_not_found": -32602,
    "unprocessable": -32602,
    "dependency_unavailable": -32603,
    "rate_limited": -32603,
    "internal_error": -32603,
}


def _to_mcp_error(exc: BaseException) -> mcp_types.ErrorData:
    """도메인 / 검증 예외 → MCP 표준 에러 (data.code 에 Arche code).

    분기:
    - ArcheError → 도메인 code (§9 카탈로그) 그대로 data.code.
    - pydantic ValidationError → invalid_input.
    - 그 외 → internal_error.
    """
    if isinstance(exc, ArcheError):
        return mcp_types.ErrorData(
            code=_ARCHE_TO_RPC_CODE.get(exc.code, -32603),
            message=exc.message,
            data={"code": exc.code, "details": exc.details},
        )
    if isinstance(exc, ValidationError):
        # REST 핸들러와 동일한 평탄화 — raw exc.errors() 의 input/ctx (직렬화 불가
        # 가능) 를 떨구고 loc 점 표기 + type + msg 만 노출 (issue #26).
        return mcp_types.ErrorData(
            code=-32602,
            message="invalid input",
            data={
                "code": "invalid_input",
                "details": {"errors": flatten_validation_errors(exc.errors())},
            },
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
    *,
    ingest_service: IngestService | None = None,
    plan_registry: PlanRegistry | None = None,
) -> Server:
    """MCP Server 객체 생성 + tool 등록.

    기본은 6 read tool 만 등록한다. `ingest_service` 와 `plan_registry` 가 *둘 다*
    주입되면 reviewable ingest 의 4 tool (plan/preview/resolve/commit) 을 추가로 등록한다.
    어느 한쪽이 None 이면 추가하지 않는다 — LLM 이 없는 read-only fake-boot 경로
    (CLI 의 ARCHE_TEST_FAKE_GRAPH) 를 보호하기 위함이다.

    반환된 서버는 `mcp.server.stdio.stdio_server()` async context 안에서
    `server.run(read, write, server.create_initialization_options())` 로 구동.
    """
    instructions = (
        "Arche graph primitives. Use `get_schema` first to inspect the graph "
        "shape, then `find_entities` to anchor user keywords to nodes, and "
        "traverse with `get_neighbors` / `find_path` / `get_subgraph`."
    )
    register_ingest = ingest_service is not None and plan_registry is not None
    if register_ingest:
        # reviewable ingest 의식: 계획 -> 미리보기 -> 질문 해소 -> 사람 확인 ->
        # 반영. LLM 이 사람의 검토를 건너뛰고 그래프를 바꾸지 못하도록 순서를
        # 명시한다.
        instructions += (
            " Writing to the graph follows a plan -> preview -> resolve open "
            "questions -> confirm -> commit ritual: call `ingest_plan` to stage "
            "a file's changes without touching the graph, then `ingest_preview` "
            "to expand the delta and show it to the human. If the preview "
            "carries `questions` (new entities that look close to existing "
            "ones), ask the human about each and feed their answers to "
            "`ingest_resolve`, then `ingest_preview` again. Only after the human "
            "explicitly confirms call `ingest_commit`. Never skip the preview, "
            "resolve, or commit on the human's behalf."
        )
    else:
        # 쓰기 tool 이 없는 read-only 부팅 경로 (ARCHE_TEST_FAKE_GRAPH 등) — 원래의
        # read-only 안내를 보존한다. register_ingest 경로에는 붙이지 않는다: 그
        # 서버는 plan/commit 으로 그래프를 *바꿀 수 있어* read-only 가 아니다.
        instructions += " Read-only: these tools never modify the graph."

    server: Server = Server(
        name="arche",
        version="0.1.0",
        instructions=instructions,
    )

    tools = _build_tools()
    if register_ingest:
        tools = tools + _build_ingest_tools()
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
                name,
                arguments,
                graph=graph,
                embedder=embedder,
                settings=settings,
                ingest_service=ingest_service,
                plan_registry=plan_registry,
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
    *,
    ingest_service: IngestService | None = None,
    plan_registry: PlanRegistry | None = None,
) -> None:
    """stdio transport 로 서버를 띄운다.

    WHY async: MCP SDK 의 server.run 은 async. CLI 진입점에서 `asyncio.run` 으로
    호출한다.

    `ingest_service` + `plan_registry` 를 함께 넘기면 reviewable ingest tool 까지
    노출한다 (production serve 경로). fake-boot 는 둘 다 생략해 read-only.
    """
    from mcp.server.stdio import stdio_server  # local import — 부팅 시 SDK 로딩 비용 한 번만.

    server = build_mcp_server(
        graph,
        embedder,
        settings,
        ingest_service=ingest_service,
        plan_registry=plan_registry,
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
