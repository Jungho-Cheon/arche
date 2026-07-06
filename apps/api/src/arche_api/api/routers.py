"""REST routers — graph primitives 6 개 (PRD 3 §2-7) + healthz + admin ingest.

본 파일은 *얇은 라우터* 만 담는다. 비즈니스 로직 (RRF fusion / BFS 절단 /
find_path 매핑) 은 `services.py` 가 책임. 라우터는 FastAPI 입출력 변환
(`response_model`, envelope 감싸기) + HTTP 의존성 wire-up 만.

WHY services 추출 (#7 PR): PRD 3 §0.1 의 1:1 매핑 — REST 와 MCP 가 *같은 동작*
을 노출하려면 비즈니스 로직을 한 곳에서 정의해야 한다. REST 라우터는 services
를 호출하면서 DataEnvelope 으로 감싸고, MCP 어댑터는 같은 services 를 호출하면
서 envelope 없이 그대로 돌려준다.

WHY response_model 명시: FastAPI 가 OpenAPI 를 자동 생성할 때, response_model
이 *명시되어야* PRD 3 의 JSON Schema 와 일치하는 스키마가 `/openapi.json` 에
노출된다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from arche_api.domain.ports import EmbeddingProvider, GraphRepository

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
    settings_dep,
    task_registry_dep,
)
from .responses import (
    FindPathRequest,
    FindPathResponse,
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

logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])
entities_router = APIRouter(prefix="/entities", tags=["entities"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])
schema_router = APIRouter(tags=["schema"])
paths_router = APIRouter(prefix="/paths", tags=["paths"])
subgraph_router = APIRouter(prefix="/subgraph", tags=["subgraph"])


@health_router.get("/healthz", response_model=HealthzResponse)
def healthz(graph: GraphRepository = Depends(graph_repo_dep)) -> HealthzResponse:
    """liveness + neo4j 의존성 확인."""
    neo4j_state = "ok" if graph.healthcheck() else "down"
    return HealthzResponse(status="ok", neo4j=neo4j_state)


# ---------- find_entities (PRD 3 §3) ----------


@entities_router.post(
    "/find",
    response_model=DataEnvelope[FindEntitiesResponse],
    # WHY response_model_exclude_none: PRD 3 §3.4 의 `scores` 는 *include_scores
    # =true 일 때만 노출* . pydantic 기본 직렬화는 None 키도 포함하므로 응답
    # 단에서 None 필드를 제외해 contract 를 충족.
    #
    # #109 — 값이 없는 필드(None)를 다루는 규칙을 *모든* 조회·관리 응답에서
    # 하나로 통일한다: None 은 키 자체를 뺀다. 예전에는 이 엔드포인트와
    # ingest status 만 None 을 뺐고, get_entity 등 나머지는 `description: null`
    # 처럼 빈 값을 그대로 실어 보내, 문서와 소비 코드가 엔드포인트마다 다른
    # 규칙을 설명·처리해야 했다. 모든 응답이 같은 규칙을 따르도록 아래 조회
    # 라우터에도 같은 플래그를 단다.
    response_model_exclude_none=True,
)
def find_entities(
    body: FindEntitiesRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
    embedder: EmbeddingProvider = Depends(embedding_provider_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[FindEntitiesResponse]:
    """find_entities — services.find_entities 위임.

    ADR-0015 — namespace 결정: body 명시 > auth header > "default" (issue #98).
    """
    namespace_id = body.namespace_id or auth.namespace_id
    payload = services.find_entities(
        body, graph=graph, embedder=embedder, namespace_id=namespace_id
    )
    return DataEnvelope(data=payload)


# ---------- get_schema (PRD 3 §2) ----------


@schema_router.get(
    "/schema",
    response_model=DataEnvelope[GetSchemaResponse],
    response_model_exclude_none=True,  # #109 — None 은 키 제외 (응답 전체 통일)
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
    """그래프 모양 조회 — services.get_schema 위임.

    #104 — namespace 결정: query 명시 > auth header > "default". GET 이라 본문이
    없으므로 다른 4 조회 도구(본문 namespace_id)와 대칭이 되도록 query 로 받는다.
    MCP 표면은 이미 6 도구 모두 인자로 받아 대칭이다 — REST 의 두 GET 만 예외였다.
    """
    ns = namespace_id or auth.namespace_id
    payload = services.get_schema(graph=graph, settings=settings, namespace_id=ns)
    return DataEnvelope(data=payload)


# ---------- get_entity (PRD 3 §4) ----------


@entities_router.get(
    "/{entity_id}",
    response_model=DataEnvelope[GetEntityResponse],
    response_model_exclude_none=True,  # #109 — None 은 키 제외 (응답 전체 통일)
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
    """ID 로 단일 노드 + 인접 엣지 카운트 — services.get_entity 위임.

    #104 — namespace 결정: query 명시 > auth header > "default" (다른 조회 도구와
    대칭). 결정된 namespace 밖의 id 는 404 (issue #98 — 우회 차단).
    """
    ns = namespace_id or auth.namespace_id
    payload = services.get_entity(entity_id=entity_id, graph=graph, namespace_id=ns)
    return DataEnvelope(data=payload)


# ---------- get_neighbors (PRD 3 §5) ----------


@entities_router.post(
    "/{entity_id}/neighbors",
    response_model=DataEnvelope[GetNeighborsResponse],
    response_model_exclude_none=True,  # #109 — None 은 키 제외 (응답 전체 통일)
)
def get_neighbors(
    entity_id: str,
    body: GetNeighborsRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[GetNeighborsResponse]:
    """진입점의 N-hop 이웃 — services.get_neighbors 위임.

    WHY path + body id 일치 검증: PRD 3 §0.1 의 REST + MCP 1:1 매핑 때문 body 에
    도 id 를 *선택* 으로 받는다. REST 호출이 body 의 id 까지 보냈는데 path 의
    entity_id 와 다르면 진입점이 모호해진다 — `invalid_input` 400 으로 분기.

    ADR-0015 — namespace 결정: body 명시 > auth header > "default" (issue #98).
    """
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


# ---------- find_path (PRD 3 §6) ----------


@paths_router.post(
    "/find",
    response_model=DataEnvelope[FindPathResponse],
    response_model_exclude_none=True,  # #109 — None 은 키 제외 (응답 전체 통일)
)
def find_path(
    body: FindPathRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[FindPathResponse]:
    """두 노드 사이 k-shortest path — services.find_path 위임.

    ADR-0015 — namespace 결정: body 명시 > auth header > "default" (issue #98).
    """
    namespace_id = body.namespace_id or auth.namespace_id
    payload = services.find_path(body, graph=graph, namespace_id=namespace_id)
    return DataEnvelope(data=payload)


# ---------- get_subgraph (PRD 3 §7) ----------


@subgraph_router.post(
    "",
    response_model=DataEnvelope[GetSubgraphResponse],
    response_model_exclude_none=True,  # #109 — None 은 키 제외 (응답 전체 통일)
)
def get_subgraph(
    body: GetSubgraphRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[GetSubgraphResponse]:
    """여러 진입점 union N-hop — services.get_subgraph 위임.

    ADR-0015 — namespace 결정: body 명시 > auth header > "default" (issue #98).
    """
    namespace_id = body.namespace_id or auth.namespace_id
    payload = services.get_subgraph(body, graph=graph, namespace_id=namespace_id)
    return DataEnvelope(data=payload)


# ---------- admin/ingest (M1 슬라이스 — 본 PR 무관, 그대로 유지) ----------


@admin_router.post(
    "/ingest",
    status_code=202,
    response_model=DataEnvelope[AdminIngestResponse],
    response_model_exclude_none=True,  # #109 — None 은 키 제외 (응답 전체 통일)
)
def admin_ingest(
    body: AdminIngestRequest,
    response: Response,
    service: IngestService = Depends(ingest_service_dep),
    registry: IngestTaskRegistry = Depends(task_registry_dep),
    auth: AuthContext = Depends(auth_context_dep),
) -> DataEnvelope[AdminIngestResponse]:
    """admin ingest — PRD 2 §1.2 의 비동기 작업 생성.

    *입력 검증* 만 동기적으로 한 뒤 background asyncio.Task 로 ingest 흐름을
    띄우고 즉시 202 + task_id 응답. 진행 상태는 GET status 로 polling.
    """
    directory = Path(body.directory_path)
    if not directory.exists():
        # #110 — API 는 컨테이너 안에서 돌므로 directory_path 는 *컨테이너에서 보이는*
        # 경로여야 한다. 호스트 경로를 그대로 넣어 실패하는 사례가 잦아, 메시지와
        # details.hint 로 원인을 짚어 준다 (호스트 폴더는 볼륨으로 마운트해야 컨테
        # 이너 경로로 접근 가능).
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

    # ADR-0015 D2 — namespace 결정: body 명시 > auth header > "default".
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
    response_model_exclude_none=True,  # #109 — None 은 키 제외 (응답 전체 통일)
)
def admin_namespaces(
    graph: GraphRepository = Depends(graph_repo_dep),
) -> DataEnvelope[AdminNamespacesResponse]:
    """ADR-0015 D6 — namespace 별 entity 수. 운영 가시성."""
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
    """PRD 2 §1.3 — 작업 상태 조회. running / succeeded / failed."""
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
            error=(
                AdminIngestError(**body["error"])
                if body["error"] is not None
                else None
            ),
        )
    )
