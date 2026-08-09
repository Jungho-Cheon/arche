"""REST routers — graph primitives + healthz + admin ingest.

얇은 라우터만 담는다. 비즈니스 로직은 services.py 가 책임지고, 라우터는 FastAPI
입출력 변환(response_model, envelope)과 의존성 wire-up 만 한다. response_model 을
명시해야 OpenAPI 에 계약과 일치하는 스키마가 노출된다."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from arche_api.domain.ports import EmbeddingProvider, GraphRepository

from ..domain.entity_split import SplitService
from ..domain.errors import InvalidInputError
from ..domain.ingest import IngestService
from . import services
from .admin_tasks import (
    IngestTaskRegistry,
    spawn_ingest_task,
    state_to_status_dict,
)
from .auth import AuthContext, auth_context_dep
from .deps import (
    embedding_provider_dep,
    graph_repo_dep,
    ingest_service_dep,
    plan_registry_dep,
    settings_dep,
    split_registry_dep,
    split_service_dep,
    task_registry_dep,
)
from .plan_registry import PlanRegistry
from .plan_schemas import (
    CommitRequest,
    IngestCommitResponse,
    PlanContentRequest,
    PlanIngestRequest,
    PlanPreview,
    PlanSummary,
    PreviewRequest,
    ResolveRequest,
)
from .responses import (
    FindPathRequest,
    FindPathResponse,
    FindRelatedRequest,
    FindRelatedResponse,
    GetEntityResponse,
    GetNeighborsRequest,
    GetNeighborsResponse,
    GetSchemaResponse,
    GetSubgraphRequest,
    GetSubgraphResponse,
)
from .schemas import (
    AdminIngestError,
    AdminIngestMetrics,
    AdminIngestProgress,
    AdminIngestRequest,
    AdminIngestResponse,
    AdminIngestStatusResponse,
    AdminNamespacesResponse,
    DataEnvelope,
    ErrorBody,
    ErrorEnvelope,
    FindEntitiesRequest,
    FindEntitiesResponse,
    HealthzResponse,
    NamespaceSummary,
)
from .split_schemas import (
    SplitCommitRequest,
    SplitCommitResponse,
    SplitPlanRequest,
    SplitPreview,
    SplitPreviewRequest,
    SplitSummary,
)

logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])
entities_router = APIRouter(prefix="/entities", tags=["entities"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])
schema_router = APIRouter(tags=["schema"])
paths_router = APIRouter(prefix="/paths", tags=["paths"])
subgraph_router = APIRouter(prefix="/subgraph", tags=["subgraph"])
related_router = APIRouter(prefix="/related", tags=["related"])
ingest_router = APIRouter(prefix="/ingest", tags=["ingest"])
# 떼어내기는 노드를 다루는 연산이라 /entities 아래 둔다. /admin 아래가 아닌 이유는
# 검토가 관리자 기능이 아니라 일상 작업이기 때문이다.
split_router = APIRouter(prefix="/entities/split", tags=["split"])


@health_router.get("/healthz", response_model=HealthzResponse)
def healthz(graph: GraphRepository = Depends(graph_repo_dep)) -> HealthzResponse:
    """liveness + 그래프 백엔드 의존성 확인."""
    graph_state = "ok" if graph.healthcheck() else "down"
    return HealthzResponse(status="ok", graph=graph_state)


# ---------- find_entities ----------


@entities_router.post(
    "/find",
    response_model=DataEnvelope[FindEntitiesResponse],
    # None 필드는 키를 뺀다 — 모든 조회·관리 응답에서 같은 규칙을 쓴다.
    response_model_exclude_none=True,
)
def find_entities(
    body: FindEntitiesRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
    embedder: EmbeddingProvider = Depends(embedding_provider_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[FindEntitiesResponse]:
    """find_entities — services.find_entities 위임.

    namespace 결정: body 명시 > auth header > "default".
    """
    namespace_id = body.namespace_id or auth.namespace_id
    payload = services.find_entities(
        body, graph=graph, embedder=embedder, namespace_id=namespace_id
    )
    return DataEnvelope(data=payload)


# ---------- get_schema ----------


@schema_router.get(
    "/schema",
    response_model=DataEnvelope[GetSchemaResponse],
    response_model_exclude_none=True,  # None 필드는 키를 뺀다(응답 전체 통일)
)
def get_schema(
    namespace_id: str | None = Query(
        default=None,
        min_length=1,
        description="질의할 namespace. 미지정 시 auth 헤더 또는 'default'",
    ),
    graph: GraphRepository = Depends(graph_repo_dep),
    settings=Depends(settings_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[GetSchemaResponse]:
    """그래프 모양 조회 — services.get_schema 위임. GET 이라 본문이 없어 namespace 를
    query 로 받는다(query > auth header > "default")."""
    ns = namespace_id or auth.namespace_id
    payload = services.get_schema(graph=graph, settings=settings, namespace_id=ns)
    return DataEnvelope(data=payload)


# ---------- get_entity ----------


@entities_router.get(
    "/{entity_id}",
    response_model=DataEnvelope[GetEntityResponse],
    response_model_exclude_none=True,  # None 필드는 키를 뺀다(응답 전체 통일)
)
def get_entity(
    entity_id: str,
    namespace_id: str | None = Query(
        default=None,
        min_length=1,
        description="조회할 namespace. 미지정 시 auth 헤더 또는 'default'",
    ),
    graph: GraphRepository = Depends(graph_repo_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[GetEntityResponse]:
    """ID 로 단일 노드 + 인접 엣지 카운트 — services.get_entity 위임. namespace 는
    query > auth header > "default". 그 밖의 id 는 404."""
    ns = namespace_id or auth.namespace_id
    payload = services.get_entity(entity_id=entity_id, graph=graph, namespace_id=ns)
    return DataEnvelope(data=payload)


# ---------- get_neighbors ----------


@entities_router.post(
    "/{entity_id}/neighbors",
    response_model=DataEnvelope[GetNeighborsResponse],
    response_model_exclude_none=True,  # None 필드는 키를 뺀다(응답 전체 통일)
)
def get_neighbors(
    entity_id: str,
    body: GetNeighborsRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[GetNeighborsResponse]:
    """진입점의 N-hop 이웃 — services.get_neighbors 위임. REST/MCP 가 스키마를 공유해
    body 에도 id 를 선택으로 받는데, path 의 entity_id 와 다르면 400 으로 분기한다.
    namespace 는 body > auth header > "default"."""
    if body.id is not None and body.id != entity_id:
        raise InvalidInputError(
            "path entity_id and body id mismatch",
            details={"path_entity_id": entity_id, "body_id": body.id},
        )
    namespace_id = body.namespace_id or auth.namespace_id
    payload = services.get_neighbors(
        entity_id=entity_id, body=body, graph=graph, namespace_id=namespace_id
    )
    return DataEnvelope(data=payload)


# ---------- find_path ----------


@paths_router.post(
    "/find",
    response_model=DataEnvelope[FindPathResponse],
    response_model_exclude_none=True,  # None 필드는 키를 뺀다(응답 전체 통일)
)
def find_path(
    body: FindPathRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[FindPathResponse]:
    """두 노드 사이 k-shortest path — services.find_path 위임.

    namespace 결정: body 명시 > auth header > "default".
    """
    namespace_id = body.namespace_id or auth.namespace_id
    payload = services.find_path(body, graph=graph, namespace_id=namespace_id)
    return DataEnvelope(data=payload)


# ---------- get_subgraph ----------


@subgraph_router.post(
    "",
    response_model=DataEnvelope[GetSubgraphResponse],
    response_model_exclude_none=True,  # None 필드는 키를 뺀다(응답 전체 통일)
)
def get_subgraph(
    body: GetSubgraphRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[GetSubgraphResponse]:
    """여러 진입점 union N-hop — services.get_subgraph 위임.

    namespace 결정: body 명시 > auth header > "default".
    """
    namespace_id = body.namespace_id or auth.namespace_id
    payload = services.get_subgraph(body, graph=graph, namespace_id=namespace_id)
    return DataEnvelope(data=payload)


# ---------- find_related ----------


@related_router.post(
    "/find",
    response_model=DataEnvelope[FindRelatedResponse],
    response_model_exclude_none=True,  # None 필드는 키를 뺀다(응답 전체 통일)
)
def find_related(
    body: FindRelatedRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[FindRelatedResponse]:
    """시드 집합에서 구조적으로 가까운 관련 노드 top-k — services.find_related 위임.

    namespace 결정: body 명시 > auth header > "default".
    """
    namespace_id = body.namespace_id or auth.namespace_id
    payload = services.find_related(body, graph=graph, namespace_id=namespace_id)
    return DataEnvelope(data=payload)


# ---------- 떼어내기: plan → preview → commit ----------
# 잘못 합친 노드를 둘로 가른다. 적재와 같은 안전 latch 를 쓰되 resolve 단계가 없다 —
# 계획에 LLM 호출이 없어, 사람이 정한 관계 배정을 실어 다시 계획하는 편이 싸다.


@split_router.post(
    "/plan",
    response_model=DataEnvelope[SplitSummary],
    response_model_exclude_none=True,
)
def entity_split_plan(
    body: SplitPlanRequest,
    service: SplitService = Depends(split_service_dep),
    registry: PlanRegistry = Depends(split_registry_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[SplitSummary]:
    """떼어내기 계획 — services.plan_entity_split 위임. 그래프는 읽기만 한다."""
    if "namespace_id" not in body.model_fields_set:
        body = body.model_copy(update={"namespace_id": auth.namespace_id})
    payload = services.plan_entity_split(body, service=service, registry=registry)
    return DataEnvelope(data=payload)


@split_router.post(
    "/preview",
    response_model=DataEnvelope[SplitPreview],
    response_model_exclude_none=True,
)
def entity_split_preview(
    body: SplitPreviewRequest,
    registry: PlanRegistry = Depends(split_registry_dep),
) -> DataEnvelope[SplitPreview]:
    """두 노드의 최종 모습과 관계별 행선지 — services.preview_entity_split 위임."""
    payload = services.preview_entity_split(body, registry=registry)
    return DataEnvelope(data=payload)


@split_router.post(
    "/commit",
    response_model=DataEnvelope[SplitCommitResponse],
    response_model_exclude_none=True,
)
def entity_split_commit(
    body: SplitCommitRequest,
    service: SplitService = Depends(split_service_dep),
    registry: PlanRegistry = Depends(split_registry_dep),
) -> DataEnvelope[SplitCommitResponse]:
    """미리 보기를 거치고 판단이 끝난 계획만 반영 — services.commit_entity_split 위임."""
    payload = services.commit_entity_split(body, service=service, registry=registry)
    return DataEnvelope(data=payload)


# ---------- 검토형 적재: plan → preview → resolve → commit ----------
# MCP 의 ingest_* 도구 5 개와 같은 스키마, 같은 서비스 함수를 쓴다. /admin/ingest 는
# 검토 없이 바로 쓰는 대량 경로라 이 묶음과 별개다.


def _plan_namespace(body: PlanIngestRequest | PlanContentRequest, auth: AuthContext) -> str:
    """계획이 속할 namespace — body 명시 > auth header > "default".

    스키마의 namespace_id 기본값이 "default" 라 값만 봐서는 명시했는지 알 수 없다.
    pydantic 의 model_fields_set 으로 실제 입력 여부를 갈라 조회 엔드포인트와 같은
    우선순위를 지킨다."""
    if "namespace_id" in body.model_fields_set:
        return body.namespace_id
    return auth.namespace_id


@ingest_router.post(
    "/plan",
    response_model=DataEnvelope[PlanSummary],
    response_model_exclude_none=True,
)
def ingest_plan(
    body: PlanIngestRequest,
    service: IngestService = Depends(ingest_service_dep),
    registry: PlanRegistry = Depends(plan_registry_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[PlanSummary]:
    """파일 하나의 변경 묶음을 그래프를 건드리지 않고 만든다 — services.plan_ingest 위임.

    path 는 API 서버가 보는 경로다. 서버가 읽을 수 없는 자리의 문서라면 본문을 직접
    넘기는 POST /ingest/content 를 쓴다."""
    resolved = body.model_copy(update={"namespace_id": _plan_namespace(body, auth)})
    payload = services.plan_ingest(resolved, service=service, registry=registry)
    return DataEnvelope(data=payload)


@ingest_router.post(
    "/content",
    response_model=DataEnvelope[PlanSummary],
    response_model_exclude_none=True,
)
def ingest_content(
    body: PlanContentRequest,
    service: IngestService = Depends(ingest_service_dep),
    registry: PlanRegistry = Depends(plan_registry_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[PlanSummary]:
    """넘겨받은 텍스트로 변경 묶음을 만든다 — services.plan_ingest_content 위임.
    파일을 서버에 떨구지 않아도 되므로 REST 통합의 기본 경로다."""
    resolved = body.model_copy(update={"namespace_id": _plan_namespace(body, auth)})
    payload = services.plan_ingest_content(resolved, service=service, registry=registry)
    return DataEnvelope(data=payload)


@ingest_router.post(
    "/preview",
    response_model=DataEnvelope[PlanPreview],
    response_model_exclude_none=True,
)
def ingest_preview(
    body: PreviewRequest,
    registry: PlanRegistry = Depends(plan_registry_dep),
) -> DataEnvelope[PlanPreview]:
    """계획을 항목 단위로 펼치고 commit 의 안전 latch 를 건다 — services.preview_plan 위임."""
    payload = services.preview_plan(body, registry=registry)
    return DataEnvelope(data=payload)


@ingest_router.post(
    "/resolve",
    response_model=DataEnvelope[PlanSummary],
    response_model_exclude_none=True,
)
def ingest_resolve(
    body: ResolveRequest,
    service: IngestService = Depends(ingest_service_dep),
    registry: PlanRegistry = Depends(plan_registry_dep),
) -> DataEnvelope[PlanSummary]:
    """미리 보기가 물은 질문에 사람의 결정을 반영해 계획을 다듬는다 —
    services.resolve_ingest 위임. 계획의 namespace 는 보관된 값을 그대로 쓴다."""
    payload = services.resolve_ingest(body, service=service, registry=registry)
    return DataEnvelope(data=payload)


@ingest_router.post(
    "/commit",
    response_model=DataEnvelope[IngestCommitResponse],
    response_model_exclude_none=True,
)
def ingest_commit(
    body: CommitRequest,
    service: IngestService = Depends(ingest_service_dep),
    registry: PlanRegistry = Depends(plan_registry_dep),
) -> DataEnvelope[IngestCommitResponse]:
    """미리 보기를 거친 계획만 그래프에 반영한다 — services.commit_plan 위임.
    미리 보기 없이 부르면 unprocessable 로 거부된다."""
    payload = services.commit_plan(body, service=service, registry=registry)
    return DataEnvelope(data=payload)


# ---------- admin/ingest ----------


@admin_router.post(
    "/ingest",
    status_code=202,
    response_model=DataEnvelope[AdminIngestResponse],
    response_model_exclude_none=True,  # None 필드는 키를 뺀다(응답 전체 통일)
)
def admin_ingest(
    body: AdminIngestRequest,
    response: Response,
    service: IngestService = Depends(ingest_service_dep),
    registry: IngestTaskRegistry = Depends(task_registry_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[AdminIngestResponse]:
    """admin ingest — 비동기 작업 생성. 입력 검증만 동기로 하고 background Task 로
    ingest 를 띄운 뒤 202 + task_id 를 즉시 응답한다(진행은 GET status 로 polling)."""
    directory = Path(body.directory_path)
    if not directory.exists():
        # directory_path 는 API 컨테이너 안에서 보이는 경로여야 한다. 호스트 경로를
        # 그대로 넣어 실패하는 사례가 잦아 메시지와 details.hint 로 원인을 짚어 준다.
        raise HTTPException(
            status_code=422,
            detail=ErrorEnvelope(
                error=ErrorBody(
                    code="directory_not_found",
                    message=(
                        f"Directory not found: {directory}. "
                        "이 경로는 API 컨테이너 안에서 보이는 경로여야 합니다. "
                        "호스트 폴더라면 볼륨으로 마운트한 뒤 컨테이너 경로로 넣으세요."
                    ),
                    details={
                        "path": str(directory),
                        "hint": "directory_path must be accessible from inside the API container (mount host folders as a volume).",
                    },
                )
            ).model_dump(),
        )
    if not directory.is_dir():
        raise HTTPException(
            status_code=422,
            detail=ErrorEnvelope(
                error=ErrorBody(
                    code="not_a_directory",
                    message=f"Path is not a directory: {directory}",
                )
            ).model_dump(),
        )

    # namespace 결정: body 명시 > auth header > "default".
    namespace_id = body.namespace_id or auth.namespace_id
    state = spawn_ingest_task(
        registry=registry,
        service=service,
        directory_path=directory,
        dry_run=body.dry_run,
        namespace_id=namespace_id,
    )
    response.status_code = 202
    return DataEnvelope(
        data=AdminIngestResponse(
            task_id=state.task_id,
            status_url=f"/admin/ingest/{state.task_id}/status",
        )
    )


@admin_router.get(
    "/namespaces",
    response_model=DataEnvelope[AdminNamespacesResponse],
    response_model_exclude_none=True,  # None 필드는 키를 뺀다(응답 전체 통일)
)
def admin_namespaces(
    graph: GraphRepository = Depends(graph_repo_dep),
) -> DataEnvelope[AdminNamespacesResponse]:
    """namespace 별 entity 수 — 운영 가시성."""
    by_ns = graph.count_entities_by_namespace()
    namespaces = sorted(
        (NamespaceSummary(namespace_id=ns, entity_count=c) for ns, c in by_ns.items()),
        key=lambda s: -s.entity_count,
    )
    return DataEnvelope(data=AdminNamespacesResponse(namespaces=namespaces))


@admin_router.get(
    "/ingest/{task_id}/status",
    response_model=DataEnvelope[AdminIngestStatusResponse],
    response_model_exclude_none=True,
)
def admin_ingest_status(
    task_id: str,
    registry: IngestTaskRegistry = Depends(task_registry_dep),
) -> DataEnvelope[AdminIngestStatusResponse]:
    """작업 상태 조회 — running / succeeded / failed."""
    state = registry.get(task_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorEnvelope(
                error=ErrorBody(
                    code="task_not_found",
                    message=f"task not found: {task_id}",
                )
            ).model_dump(),
        )
    body = state_to_status_dict(state)
    return DataEnvelope(
        data=AdminIngestStatusResponse(
            task_id=body["task_id"],
            state=body["state"],
            progress=AdminIngestProgress(**body["progress"]),
            metrics=AdminIngestMetrics(**body["metrics"]),
            error=(AdminIngestError(**body["error"]) if body["error"] is not None else None),
        )
    )
