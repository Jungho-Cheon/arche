"""REST routers — healthz / find_entities / admin ingest (async task)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..adapters.graph import GraphRepository, KeywordHit
from ..domain.errors import OpentologyError
from ..domain.ingest import IngestService
from .admin_tasks import (
    IngestTaskRegistry,
    spawn_ingest_task,
    state_to_status_dict,
)
from .deps import graph_repo_dep, ingest_service_dep, task_registry_dep
from .schemas import (
    AdminIngestError,
    AdminIngestMetrics,
    AdminIngestProgress,
    AdminIngestRequest,
    AdminIngestResponse,
    AdminIngestStatusResponse,
    DataEnvelope,
    EntityMatch,
    ErrorBody,
    ErrorEnvelope,
    FindEntitiesRequest,
    FindEntitiesResponse,
    HealthzResponse,
    MatchScores,
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
    # WHY response_model_exclude_none: PRD 3 §3.4 의 `scores` 는 *include_scores
    # =true 일 때만 노출* . pydantic 기본 직렬화는 None 키도 포함하므로 응답
    # 단에서 None 필드를 제외해 contract 를 충족.
    response_model_exclude_none=True,
)
def find_entities(
    body: FindEntitiesRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
) -> DataEnvelope[FindEntitiesResponse]:
    """find_entities — PRD 3 §3.4 응답 (walking skeleton 의 lexical-only).

    동작 (PRD 3 §3.5 의 단순화):
    1. 각 input keyword 에 대해 fulltext (BM25 류) top-k 조회 — 어댑터가 raw
       Lucene 점수와 함께 keyword 를 태깅해 돌려준다.
    2. 노드 ID 단위 union — 같은 노드가 여러 keyword 에서 surface 됐다면
       *가장 높은 raw 점수* 를 만든 keyword 를 `matched_keyword` 로 유지.
    3. score 정규화 — 결과 집합 안에서 최댓값으로 나눠 0..1 범위로 매핑.
       walking skeleton 은 lexical-only 라 RRF 없이 max-normalize 한 BM25
       점수가 곧 `score`. 하이브리드 (#6) 도입 시 RRF fused score 로 교체.
    4. `types` 필터 → `limit` slice → `include_scores` 옵션 적용.

    하이브리드 fusion 자체는 #6 follow-up. 본 라우터는 인터페이스를 PRD 3 §3.4
    형태로 *지금* 고정해 caller (eval 의 Opentology 컬럼 등) 가 안정적으로
    의존할 수 있게 한다.
    """
    try:
        # WHY limit_per_keyword 가 입력 limit 보다 크게: 여러 keyword 가 같은
        # 노드를 surface 시키는 경우를 흡수하려면 keyword 별 풀이 입력 limit
        # 보다 넉넉해야 한다. 50 (PRD 3 §3.3 의 limit 상한) 이상으로는 잡지 않음.
        per_kw = min(50, max(body.limit * 2, 10))
        hits = graph.find_by_keywords_scored(
            keywords=body.keywords, limit_per_keyword=per_kw
        )
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

    matches = _fuse_keyword_hits(
        hits,
        types=body.types,
        limit=body.limit,
        include_scores=body.include_scores,
    )
    return DataEnvelope(data=FindEntitiesResponse(matches=matches))


def _fuse_keyword_hits(
    hits: list[KeywordHit],
    *,
    types: list[str] | None,
    limit: int,
    include_scores: bool,
) -> list[EntityMatch]:
    """노드 ID 단위 union + max-normalize + types/limit/include_scores 적용.

    WHY 이 단계가 라우터에 있는가: 정규화는 *결과 집합 단위 통계* (max) 를
    필요로 하므로 단일 어댑터 호출 안에서 결정할 수 없다. 어댑터는 raw 점수,
    라우터가 사용자 계약을 따른다 (PRD 3 §3.4 의 0..1).
    """
    # 1) types 필터 — 입력 단계에서 미리 거르면 max-normalize 의 denominator
    # 가 필터 후 결과 기준이 되어 사용자에게 더 의미 있는 0..1 분포.
    if types:
        type_set = set(types)
        hits = [h for h in hits if h.node.type in type_set]

    # 2) 노드 ID 단위 union (PRD 3 §3.5) — 가장 높은 raw 점수 + 그 keyword.
    best_per_node: dict[str, KeywordHit] = {}
    for h in hits:
        existing = best_per_node.get(h.node.id)
        if existing is None or h.raw_score > existing.raw_score:
            best_per_node[h.node.id] = h

    fused = list(best_per_node.values())
    if not fused:
        return []

    # 3) max-normalize — top match 가 1.0 이 되도록.
    # WHY max-normalize: walking skeleton 은 RRF 가 없고 BM25 점수 분포는
    # 코퍼스 크기 / IDF 에 따라 절대값이 달라진다. 결과 집합 안에서의 *상대
    # 순위* 만 0..1 로 표현. #6 에서 RRF fused score 로 교체되면 정규화 자체가
    # 불필요해진다 (RRF 출력이 이미 비교 가능).
    max_score = max(h.raw_score for h in fused) or 1.0

    # 4) 점수 내림차순 정렬 후 limit slice (PRD 3 §3.3 default 10, max 50).
    fused.sort(key=lambda h: h.raw_score, reverse=True)
    fused = fused[:limit]

    matches: list[EntityMatch] = []
    for h in fused:
        normalized = h.raw_score / max_score if max_score > 0 else 0.0
        # 부동소수 오차 방어 — PRD 3 §3.4 의 minimum 0 / maximum 1 강제.
        normalized = max(0.0, min(1.0, normalized))
        scores: MatchScores | None = None
        if include_scores:
            # walking skeleton: dense path 는 아직 stub (#6) — 0.0 으로 채워서
            # 키 존재 여부로 응답 형태가 갈리지 않게.
            scores = MatchScores(lexical=h.raw_score, dense=0.0)
        matches.append(
            EntityMatch(
                node=h.node,
                score=normalized,
                matched_keyword=h.matched_keyword,
                scores=scores,
            )
        )
    return matches


@admin_router.post(
    "/ingest",
    status_code=202,
    response_model=DataEnvelope[AdminIngestResponse],
)
def admin_ingest(
    body: AdminIngestRequest,
    response: Response,
    service: IngestService = Depends(ingest_service_dep),
    registry: IngestTaskRegistry = Depends(task_registry_dep),
) -> DataEnvelope[AdminIngestResponse]:
    """admin ingest — PRD 2 §1.2 의 비동기 작업 생성.

    *입력 검증* 만 동기적으로 한 뒤 background asyncio.Task 로 ingest 흐름을
    띄우고 즉시 202 + task_id 응답. 진행 상태는 GET status 로 polling.
    """
    directory = Path(body.directory_path)
    if not directory.exists():
        # WHY 동기 검증: 디렉토리 부재는 *작업을 시작하기 전에* 호출자에게 빠른
        # 신호를 줘야 의미. 404 가 아니라 422 — 입력 자체가 잘못된 케이스.
        raise HTTPException(
            status_code=422,
            detail=ErrorEnvelope(
                error=ErrorBody(
                    code="directory_not_found",
                    message=f"Directory not found: {directory}",
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

    state = spawn_ingest_task(
        registry=registry,
        service=service,
        directory_path=directory,
        dry_run=body.dry_run,
    )
    response.status_code = 202
    return DataEnvelope(
        data=AdminIngestResponse(
            task_id=state.task_id,
            status_url=f"/admin/ingest/{state.task_id}/status",
        )
    )


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
