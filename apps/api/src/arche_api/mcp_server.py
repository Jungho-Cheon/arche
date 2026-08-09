"""MCP stdio 어댑터 — graph primitive 를 표준 MCP tool 로 노출한다.

REST 와 MCP 가 같은 스키마를 노출하도록 api/services.py 의 순수 함수를 직접 호출해
인코딩만 다르게 돌려준다. tool 의 input_schema 는 Pydantic 모델의 model_json_schema()
에서 끌어와 REST OpenAPI 와 같은 출처를 공유하고, _inline_defs 가 $defs 참조를 inline
해 flat JSON Schema 로 만든다(일부 MCP 클라이언트가 $defs 를 못 푼다).

직접 그래프 변형 write 는 MCP 에 노출하지 않는다. reviewable ingest 의 다섯 tool 만
예외로, 사람 미리보기+확인 latch 를 강제하며 ingest_service 와 plan_registry 가 함께
주입된 서버에서만 등록된다. read-only 부팅 경로는 read tool 만 노출한다."""

from __future__ import annotations

import copy
import json
import logging
from typing import TYPE_CHECKING, Any

import jsonschema
import mcp.types as mcp_types
from mcp.server.lowlevel import Server
from pydantic import BaseModel, ValidationError

from arche_api.domain.ports import EmbeddingProvider, GraphRepository

from .api import services
from .api.error_codes import flatten_validation_errors
from .api.plan_schemas import (
    CommitRequest,
    PlanContentRequest,
    PlanIngestRequest,
    PreviewRequest,
    ResolveRequest,
)
from .api.responses import (
    FindPathRequest,
    FindRelatedRequest,
    GetNeighborsRequest,
    GetSubgraphRequest,
)
from .api.schemas import FindEntitiesRequest
from .api.split_schemas import (
    SplitCommitRequest,
    SplitPlanRequest,
    SplitPreviewRequest,
)
from .config import Settings
from .domain.errors import ArcheError, InvalidInputError

if TYPE_CHECKING:
    from .api.plan_registry import PlanRegistry
    from .domain.ingest import IngestService

logger = logging.getLogger(__name__)


# tool description 을 한 곳에 모은다. 측정 재현성에 영향을 주므로 신중히 바꾼다.
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
    "find_related": (
        "Given a set of seed node IDs, return the top-k nodes structurally "
        "CLOSEST to them, ranked by a proximity score, in ONE call. Use this "
        "instead of walking `get_neighbors` hop by hop when you want 'what else "
        "is related to these entities' — it folds a multi-hop exploration into a "
        "single request so intermediate results never re-enter your context. "
        "Each result carries `score` (0..1, relative rank within this response; "
        "higher = closer to more seeds and via shorter hops) and `distance` (the "
        "shortest hop count to any seed). Seeds are the entry points you already "
        "know (e.g. from `find_entities`); they are excluded from the results. "
        "TUNING: raise `max_hops` to reach farther, lower `damping` to prefer "
        "immediate neighbors, and pass `relation_types` to restrict the spread "
        "to specific edges."
    ),
    # reviewable ingest — description 에 사람 검토를 건너뛰지 말라는 행동 지침을 싣는다.
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
        'namespace (default "default"); the plan keeps that namespace through '
        "preview/resolve/commit, so identity matching and writes stay inside it."
    ),
    "ingest_content": (
        "Plan ingestion of raw text you already have in hand — content you read "
        "from an external source (a Confluence/Jira page, a URL, another tool's "
        "MCP) — WITHOUT writing it to a file first. Same review flow as "
        "ingest_plan: extraction runs without touching the graph, the change set "
        "is stashed under a returned `plan_id`, and you MUST call ingest_preview "
        "then ingest_commit (only after the human confirms). Pass `content` (the "
        "text) and `source_id`, a stable label that stands in for a file path "
        '(e.g. "confluence:PAGE-123" or the document URL): idempotent '
        "re-ingestion and diffing key off it, so re-ingesting the same source "
        "with an updated body must reuse the same source_id. Optionally pass "
        "`hints` and `namespace_id` exactly like ingest_plan. Use this instead of "
        "ingest_plan whenever the agent fetched the content itself rather than "
        "being handed a file on disk."
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
        'Each resolution pairs a `question_id` with a `decision`: "merge" '
        "means the new entity is the SAME as the suggested existing entity, "
        '"keep" means it is genuinely new and distinct. This refines the same '
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
    # 떼어내기 — 잘못 합친 노드를 되돌리는 유일한 길. 같은 검토 latch 를 쓴다.
    "entity_split_plan": (
        "Plan splitting ONE node that wrongly merged two different real-world "
        "things back into two nodes, WITHOUT writing to the graph. Give "
        "`entity_id`, the `new_name` for the split-off node (usually one of the "
        "node's own aliases), and what moves with it: `move_aliases` and "
        "`move_source_paths`. Relations are assigned automatically by the source "
        "document they came from; any relation whose sources fall on both sides "
        "(or that has no source left) is surfaced as a question you MUST ask the "
        "human about. Feed their answers back as `relation_decisions` and plan "
        "again — planning is cheap here because no extraction runs. Then call "
        "entity_split_preview, show the human both resulting nodes, and only "
        "call entity_split_commit after they confirm."
    ),
    "entity_split_preview": (
        "Expand a split plan (by `plan_id`): what each of the two nodes will "
        "look like afterwards, and where every relation goes with a one-line "
        "reason. This arms the safety latch that entity_split_commit requires. "
        "If `questions` is non-empty the split cannot be committed — ask the "
        "human about each and re-plan with `relation_decisions`."
    ),
    "entity_split_commit": (
        "Apply a previously previewed split (by `plan_id`). Rejected "
        "(unprocessable) without a prior entity_split_preview, while any "
        "relation is still undecided, or if the origin node disappeared. After "
        "the split the two nodes refuse to re-absorb each other's aliases, so "
        "re-ingesting the same documents will not merge them back."
    ),
}


# reviewable ingest tool — service 주입 시에만 등록된다. 사람 검토 latch 를 통과한
# 변경만 반영하므로 write 금지 목록과 별개로 허용된다.
INGEST_TOOL_NAMES: tuple[str, ...] = (
    "ingest_plan",
    "ingest_content",
    "ingest_preview",
    "ingest_resolve",
    "ingest_commit",
)

# 떼어내기 tool — 적재와 같이 사람 검토 latch 를 통과한 변경만 반영한다.
SPLIT_TOOL_NAMES: tuple[str, ...] = (
    "entity_split_plan",
    "entity_split_preview",
    "entity_split_commit",
)


# 노출 금지 — 등록조차 하지 않는 write tool 이름(단위 테스트가 부재를 검증한다).
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

    Pydantic v2 의 ref 는 항상 #/$defs/<key> 형식이라 가벼운 walker 로 처리한다(추가
    의존성 회피). 현재 모델은 모두 비순환이라 cycle 처리는 없다.
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


_NAMESPACE_PROPERTY: dict[str, Any] = {
    "type": "string",
    "minLength": 1,
    "description": "조회할 namespace. 미지정 시 'default'",
}


def _namespace_only_schema() -> dict[str, Any]:
    """입력이 namespace 뿐인 도구의 스키마.

    get_schema 는 본문이 없지만 namespace 는 받아야 한다. 이걸 빼면 dispatch 가 읽는
    namespace_id 를 스키마가 거부해, MCP 로는 default 말고 다른 namespace 를 볼 길이
    없어진다.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"namespace_id": _NAMESPACE_PROPERTY},
    }


def _build_tools() -> list[mcp_types.Tool]:
    """read tool 의 등록 manifest."""
    return [
        mcp_types.Tool(
            name="get_schema",
            description=_TOOL_DESCRIPTIONS["get_schema"],
            inputSchema=_namespace_only_schema(),
        ),
        mcp_types.Tool(
            name="find_entities",
            description=_TOOL_DESCRIPTIONS["find_entities"],
            inputSchema=_build_input_schema(FindEntitiesRequest),
        ),
        mcp_types.Tool(
            name="get_entity",
            description=_TOOL_DESCRIPTIONS["get_entity"],
            # MCP 입력은 { id } (REST 는 URL path).
            inputSchema={
                "type": "object",
                "additionalProperties": False,
                "required": ["id"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[0-9A-Z]{26}$"},
                    "namespace_id": _NAMESPACE_PROPERTY,
                },
            },
        ),
        mcp_types.Tool(
            name="get_neighbors",
            description=_TOOL_DESCRIPTIONS["get_neighbors"],
            # MCP 입력은 body 필드 + id 를 한 객체로 합친다(REST 는 URL path 로 id 를 받는다).
            inputSchema=_merge_id_into_schema(_build_input_schema(GetNeighborsRequest)),
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
        mcp_types.Tool(
            name="find_related",
            description=_TOOL_DESCRIPTIONS["find_related"],
            inputSchema=_build_input_schema(FindRelatedRequest),
        ),
    ]


def _build_ingest_tools() -> list[mcp_types.Tool]:
    """reviewable ingest 의 5 tool — service 가 주입된 서버에서만 등록.

    입력 스키마는 plan_schemas 의 Pydantic 모델에서 그대로 끌어와 REST 통로와
    같은 출처를 공유한다 (read tool 과 동일 원칙). ingest_plan 은 `{path}`,
    ingest_content 는 `{content, source_id}`, preview/commit 은 `{plan_id}`,
    resolve 는 `{plan_id, resolutions}`.
    """
    return [
        mcp_types.Tool(
            name="ingest_plan",
            description=_TOOL_DESCRIPTIONS["ingest_plan"],
            inputSchema=_build_input_schema(PlanIngestRequest),
        ),
        mcp_types.Tool(
            name="ingest_content",
            description=_TOOL_DESCRIPTIONS["ingest_content"],
            inputSchema=_build_input_schema(PlanContentRequest),
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


def _build_split_tools() -> list[mcp_types.Tool]:
    """떼어내기의 3 tool — 적재와 마찬가지로 registry 가 주입된 서버에서만 등록.
    입력 스키마는 split_schemas 의 Pydantic 모델에서 그대로 끌어와 REST 와 같은
    출처를 공유한다."""
    return [
        mcp_types.Tool(
            name="entity_split_plan",
            description=_TOOL_DESCRIPTIONS["entity_split_plan"],
            inputSchema=_build_input_schema(SplitPlanRequest),
        ),
        mcp_types.Tool(
            name="entity_split_preview",
            description=_TOOL_DESCRIPTIONS["entity_split_preview"],
            inputSchema=_build_input_schema(SplitPreviewRequest),
        ),
        mcp_types.Tool(
            name="entity_split_commit",
            description=_TOOL_DESCRIPTIONS["entity_split_commit"],
            inputSchema=_build_input_schema(SplitCommitRequest),
        ),
    ]


def _merge_id_into_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """get_neighbors 입력 — REST 의 URL path id 를 MCP body 의 properties 에 끼워 넣어
    한 객체로 만든다."""
    out = copy.deepcopy(schema)
    props = out.setdefault("properties", {})
    props["id"] = {"type": "string", "pattern": "^[0-9A-Z]{26}$"}
    required = list(out.get("required", []))
    if "id" not in required:
        required.insert(0, "id")
    out["required"] = required
    return out


# ---------- tool 실행 디스패치 ----------


def _validate_arguments(
    name: str, arguments: dict[str, Any], schemas_by_name: dict[str, dict[str, Any]]
) -> None:
    """선언한 입력 스키마로 인자를 검사한다. 어긋나면 invalid_input 으로 올린다."""
    schema = schemas_by_name.get(name)
    if schema is None:
        return
    try:
        jsonschema.validate(instance=arguments, schema=schema)
    except jsonschema.ValidationError as e:
        raise InvalidInputError(
            e.message, details={"tool": name, "field": ".".join(str(p) for p in e.absolute_path)}
        ) from None


def _dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    graph: GraphRepository,
    embedder: EmbeddingProvider,
    settings: Settings,
    ingest_service: IngestService | None = None,
    plan_registry: PlanRegistry | None = None,
    split_registry: PlanRegistry | None = None,
) -> BaseModel:
    """단일 tool 호출을 services 로 위임. 입력 검증 실패는 ValidationError 로 전파.

    MCP 는 HTTP auth 가 없어 질의 namespace 를 도구 인자 namespace_id(미지정 시
    "default")로 받는다. REST 는 auth header 로 결정하고, 두 표면이 같은 services 로
    namespace 를 흘려보낸다.
    """
    # 인자에 실린 namespace (없으면 "default"). 4 body 도구는 검증된 body 에서,
    # get_schema/get_entity 는 인자 dict 에서 직접 꺼낸다.
    arg_ns = arguments.get("namespace_id") or "default"
    if name == "get_schema":
        return services.get_schema(graph=graph, settings=settings, namespace_id=arg_ns)
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
        return services.get_entity(entity_id=entity_id, graph=graph, namespace_id=arg_ns)
    if name == "get_neighbors":
        # services.get_neighbors 는 entity_id 와 body 를 나눠 받아, id 만 떼어낸다.
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
        return services.find_path(body, graph=graph, namespace_id=body.namespace_id or "default")
    if name == "get_subgraph":
        body = GetSubgraphRequest.model_validate(arguments)
        return services.get_subgraph(body, graph=graph, namespace_id=body.namespace_id or "default")
    if name == "find_related":
        body = FindRelatedRequest.model_validate(arguments)
        return services.find_related(body, graph=graph, namespace_id=body.namespace_id or "default")
    # reviewable ingest — service/registry 가 주입된 서버에서만 등록되므로, 여기
    # 도달했다면 둘 다 존재한다. 방어적으로 None 을 막는다.
    if name in INGEST_TOOL_NAMES:
        if ingest_service is None or plan_registry is None:
            raise ValueError(f"tool `{name}` requires an ingest service")
        if name == "ingest_plan":
            plan_body = PlanIngestRequest.model_validate(arguments)
            return services.plan_ingest(plan_body, service=ingest_service, registry=plan_registry)
        if name == "ingest_content":
            content_body = PlanContentRequest.model_validate(arguments)
            return services.plan_ingest_content(
                content_body, service=ingest_service, registry=plan_registry
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
        return services.commit_plan(commit_body, service=ingest_service, registry=plan_registry)
    if name in SPLIT_TOOL_NAMES:
        if split_registry is None:
            raise ValueError(f"tool `{name}` requires a split registry")
        from .domain.entity_split import SplitService

        split_service = SplitService(graph=graph, embedder=embedder)
        if name == "entity_split_plan":
            return services.plan_entity_split(
                SplitPlanRequest.model_validate(arguments),
                service=split_service,
                registry=split_registry,
            )
        if name == "entity_split_preview":
            return services.preview_entity_split(
                SplitPreviewRequest.model_validate(arguments), registry=split_registry
            )
        return services.commit_entity_split(
            SplitCommitRequest.model_validate(arguments),
            service=split_service,
            registry=split_registry,
        )
    # 등록되지 않은 이름 — MCP 클라이언트의 잘못된 호출.
    raise ValueError(f"unknown tool: {name}")


# ---------- 에러 변환 ----------


# 도메인 code 를 MCP 표준 에러의 data.code 에 실어 caller 가 분류하게 한다.
# JSON-RPC code 는 표준값(-32602/-32603)을 쓴다.
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

    ArcheError 는 도메인 code 를 그대로, ValidationError 는 invalid_input, 그 외는
    internal_error 로 매핑한다.
    """
    if isinstance(exc, ArcheError):
        return mcp_types.ErrorData(
            code=_ARCHE_TO_RPC_CODE.get(exc.code, -32603),
            message=exc.message,
            data={"code": exc.code, "details": exc.details},
        )
    if isinstance(exc, ValidationError):
        # REST 와 동일 평탄화 — 직렬화 불가능한 input/ctx 를 떨구고 loc/type/msg 만 노출.
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
    split_registry: PlanRegistry | None = None,
) -> Server:
    """MCP Server 객체 생성 + tool 등록.

    기본은 7 read tool 만 등록한다. `ingest_service` 와 `plan_registry` 가 *둘 다*
    주입되면 reviewable ingest 의 5 tool (plan/content/preview/resolve/commit) 을 추가로 등록한다.
    어느 한쪽이 None 이면 추가하지 않는다 — LLM 이 없는 read-only fake-boot 경로
    (CLI 의 ARCHE_TEST_FAKE_GRAPH) 를 보호하기 위함이다.

    반환된 서버는 `mcp.server.stdio.stdio_server()` async context 안에서
    `server.run(read, write, server.create_initialization_options())` 로 구동.
    """
    instructions = (
        "Arche graph primitives. Use `get_schema` first to inspect the graph "
        "shape, then `find_entities` to anchor user keywords to nodes, and "
        "traverse with `get_neighbors` / `find_path` / `get_subgraph`. To pull "
        "everything related to a set of anchor nodes in one call, use "
        "`find_related` instead of walking neighbors hop by hop."
    )
    register_ingest = ingest_service is not None and plan_registry is not None
    if register_ingest and split_registry is None:
        # 쓰기를 여는 서버면 떼어내기도 함께 연다. 계획 보관소를 안 넘겼으면 이
        # 서버 수명만큼 사는 것을 하나 만든다.
        from .api.plan_registry import PlanRegistry as _PlanRegistry

        split_registry = _PlanRegistry()
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
            "resolve, or commit on the human's behalf. If you find one node that "
            "wrongly holds two different real-world things, split it back apart "
            "with the same ritual: `entity_split_plan` -> `entity_split_preview` "
            "-> human confirms -> `entity_split_commit`."
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
        tools = tools + _build_ingest_tools() + _build_split_tools()
    _assert_no_write_tools(tools)

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return tools

    schemas_by_name = {t.name: t.inputSchema for t in tools}

    # validate_input=False 로 두고 스키마 검사를 직접 한다. SDK 에 맡기면 검사가 이
    # 핸들러 *앞* 에서 끝나 맨 문자열("Input validation error: ...")을 돌려주는데,
    # 그러면 같은 "입력이 틀렸다" 인데 응답 모양이 둘이 된다. error.code 로 분기하는
    # 클라이언트가 한쪽에서 깨진다.
    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
        """MCP tool 호출 — payload (PRD 3 §0.4: envelope 없음) 를 JSON text 로 반환.

        SDK 데코레이터는 raise 한 Exception 을 짧은 문자열로만 변환해 data.code 가
        사라진다. 도메인 code 를 보존하려고 핸들러가 직접 CallToolResult(isError=True)
        를 반환하고, caller 는 isError 로 분기해 text content 를 JSON 파싱한다. content
        는 모든 클라이언트가 보장하는 TextContent 를 쓴다.
        """
        try:
            _validate_arguments(name, arguments, schemas_by_name)
            result = _dispatch_tool(
                name,
                arguments,
                graph=graph,
                embedder=embedder,
                settings=settings,
                ingest_service=ingest_service,
                plan_registry=plan_registry,
                split_registry=split_registry,
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
                    mcp_types.TextContent(type="text", text=json.dumps(body, ensure_ascii=False))
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
    """등록 직전 안전 가드 — read-only 계약을 코드 레벨에서 보호한다."""
    names = {t.name for t in tools}
    leaked = names & WRITE_TOOL_NAMES_EXCLUDED
    if leaked:
        raise RuntimeError(f"refusing to register write tools: {sorted(leaked)}")


# ---------- stdio 실행 진입점 (CLI 에서 호출) ----------


async def run_stdio_server(
    graph: GraphRepository,
    embedder: EmbeddingProvider,
    settings: Settings,
    *,
    ingest_service: IngestService | None = None,
    plan_registry: PlanRegistry | None = None,
    split_registry: PlanRegistry | None = None,
) -> None:
    """stdio transport 로 서버를 띄운다(server.run 이 async 라 asyncio.run 으로 호출).
    ingest_service + plan_registry 를 함께 넘기면 reviewable ingest tool 까지 노출한다."""
    from mcp.server.stdio import stdio_server  # local import — 부팅 시 SDK 로딩 비용 한 번만.

    server = build_mcp_server(
        graph,
        embedder,
        settings,
        ingest_service=ingest_service,
        plan_registry=plan_registry,
        split_registry=split_registry,
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
