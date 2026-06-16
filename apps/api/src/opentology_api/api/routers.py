"""REST routers — healthz / find_entities / admin ingest."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..adapters.graph import GraphRepository
from ..domain.errors import OpentologyError
from ..domain.ingest import IngestService
from .deps import graph_repo_dep, ingest_service_dep
from .schemas import (
    AdminIngestRequest,
    AdminIngestResponse,
    DataEnvelope,
    ErrorBody,
    ErrorEnvelope,
    FindEntitiesRequest,
    FindEntitiesResponse,
    HealthzResponse,
)


logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])
entities_router = APIRouter(prefix="/entities", tags=["entities"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])


@health_router.get("/healthz", response_model=HealthzResponse)
def healthz(graph: GraphRepository = Depends(graph_repo_dep)) -> HealthzResponse:
    """liveness + neo4j 의존성 확인.

    WHY ok/down 두 가지: docker compose healthcheck 가 200 이면 ok 로 본다.
    neo4j 가 down 이어도 200 을 돌려 *API 자체* 는 살아있음을 표현 (의존 상태는
    body 로). 만약 강한 readiness 가 필요해지면 별도 /readyz 추가.
    """
    neo4j_state = "ok" if graph.healthcheck() else "down"
    return HealthzResponse(status="ok", neo4j=neo4j_state)


@entities_router.post(
    "/find",
    response_model=DataEnvelope[FindEntitiesResponse],
)
def find_entities(
    body: FindEntitiesRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
) -> DataEnvelope[FindEntitiesResponse]:
    """find_entities — walking skeleton 의 lexical-only 슬라이스.

    PRD 3 §3 의 하이브리드는 #6 follow-up. 본 구현은 fulltext (BM25 류) 만.
    """
    try:
        nodes = graph.find_by_keywords(keywords=body.keywords, limit=body.limit)
    except OpentologyError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("find_entities failed")
        raise HTTPException(
            status_code=500,
            detail=ErrorEnvelope(
                error=ErrorBody(code="internal_error", message=str(e))
            ).model_dump(),
        )
    return DataEnvelope(data=FindEntitiesResponse(entities=nodes))


@admin_router.post(
    "/ingest",
    response_model=DataEnvelope[AdminIngestResponse],
)
def admin_ingest(
    body: AdminIngestRequest,
    service: IngestService = Depends(ingest_service_dep),
) -> DataEnvelope[AdminIngestResponse]:
    """admin ingest — PRD 2 §1.2 의 admin REST. walking skeleton 은 *동기 처리* .

    WHY sync: PRD 2 §1.3 의 async state machine 은 multi-file 흐름에서 의미가
    있다. 단일 파일 + 작은 corpus 슬라이스에서는 sync 가 디버깅 가능성을 키운다.
    """
    result = service.ingest_file(Path(body.file_path))
    return DataEnvelope(
        data=AdminIngestResponse(
            source_path=result.source_path,
            entities_created=result.entities_created,
            entities_updated=result.entities_updated,
            relations_created=result.relations_created,
            relations_skipped_dangling=result.relations_skipped_dangling,
        )
    )
