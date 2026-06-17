"""REST routers — graph primitives 6 개 (PRD 3 §2-7) + healthz + admin ingest.

본 파일은 *얇은 라우터* 만 담는다. 비즈니스 로직 (RRF fusion / BFS 절단) 은
어댑터에서 책임지고, 라우터는 입력 → 어댑터 호출 → 응답 직렬화 + 에러 매핑 만.

WHY response_model 명시: FastAPI 가 OpenAPI 를 자동 생성할 때, response_model
이 *명시되어야* PRD 3 의 JSON Schema 와 일치하는 스키마가 `/openapi.json` 에
노출된다. 명시 없으면 FastAPI 가 return 타입에서 추론하지만 envelope 의 generic
T 는 추론 정확도가 떨어진다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..adapters.embedding import EmbeddingProvider
from ..adapters.graph import DenseHit, GraphRepository, KeywordHit
from ..domain.errors import (
    DependencyUnavailableError,
    EntityNotFoundError,
    OpentologyError,
    UnprocessableError,
)
from ..domain.ingest import IngestService
from ..domain.models import Edge, Node, SourceRef
from .admin_tasks import (
    IngestTaskRegistry,
    spawn_ingest_task,
    state_to_status_dict,
)
from .deps import (
    embedding_provider_dep,
    graph_repo_dep,
    ingest_service_dep,
    settings_dep,
    task_registry_dep,
)
from .responses import (
    EdgeCounts,
    EmbeddingInfo,
    EntityTypeExample,
    EntityTypeSummary,
    FindPathRequest,
    FindPathResponse,
    GetEntityResponse,
    GetNeighborsRequest,
    GetNeighborsResponse,
    GetSchemaResponse,
    GetSubgraphRequest,
    GetSubgraphResponse,
    PathSegment,
    RelationTypePair,
    RelationTypeSummary,
)
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
schema_router = APIRouter(tags=["schema"])
paths_router = APIRouter(prefix="/paths", tags=["paths"])
subgraph_router = APIRouter(prefix="/subgraph", tags=["subgraph"])


# WHY RRF k 상수 (60): PRD 3 §3.5 권장값. 측정 통제 변수 (ADR-0001) — 변경 시
# ADR-0003 amend + 새 측정 회차 필요. 라우터에 상수로 박아 두면 우회가 어렵다.
RRF_K = 60


@health_router.get("/healthz", response_model=HealthzResponse)
def healthz(graph: GraphRepository = Depends(graph_repo_dep)) -> HealthzResponse:
    """liveness + neo4j 의존성 확인.

    WHY ok/down 두 가지: docker compose healthcheck 가 200 이면 ok 로 본다.
    neo4j 가 down 이어도 200 을 돌려 *API 자체* 는 살아있음을 표현 (의존 상태는
    body 로). 만약 강한 readiness 가 필요해지면 별도 /readyz 추가.
    """
    neo4j_state = "ok" if graph.healthcheck() else "down"
    return HealthzResponse(status="ok", neo4j=neo4j_state)


# ---------- find_entities (PRD 3 §3) ----------


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
    embedder: EmbeddingProvider = Depends(embedding_provider_dep),
) -> DataEnvelope[FindEntitiesResponse]:
    """find_entities — PRD 3 §3 의 어휘 + dense 하이브리드 + RRF (k=60).

    동작 (PRD 3 §3.5):
    1. 각 input keyword 에 대해
       (a) fulltext top-k 조회 (lexical rank list, BM25 raw score 포함).
       (b) keyword 임베딩 1 회 호출 → vector ANN top-k (dense rank list, cosine).
    2. 노드 ID 단위 union — 같은 노드가 여러 keyword 에서 surface 됐다면 *가장
       높은 fused score* 를 만든 keyword 를 matched_keyword 로 유지.
    3. RRF 결합 (k=60) — `score = 1/(k + rank_lexical) + 1/(k + rank_dense)`.
       두 신호 중 한 쪽에서만 surface 된 노드는 결측 신호 항이 0.
    4. types 필터 → 점수 내림차순 → limit slice → include_scores 옵션 적용.

    *graceful fallback 없음* — 임베딩 의존성이 죽으면 503 dependency_unavailable
    을 그대로 올린다. WHY: lexical-only 로 silent fallback 하면 caller (eval 의
    Opentology 컬럼) 가 측정 회차 사이에 *동작 모드가 바뀌었음을 모른다* . 명시
    적 503 이 측정 무결성을 보장.
    """
    # WHY limit_per_keyword 가 입력 limit 보다 크게: 여러 keyword 가 같은 노드를
    # surface 시키는 경우를 흡수하려면 keyword 별 풀이 입력 limit 보다 넉넉해야.
    per_kw = min(50, max(body.limit * 2, 10))
    try:
        lexical_hits = graph.find_by_keywords_scored(
            keywords=body.keywords, limit_per_keyword=per_kw
        )
    except OpentologyError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("find_entities lexical path failed")
        raise HTTPException(
            status_code=500,
            detail=ErrorEnvelope(
                error=ErrorBody(code="internal_error", message=str(e))
            ).model_dump(),
        )

    # dense path — 각 keyword 별 임베딩 1 회 → ANN.
    # WHY 배치 임베딩: keyword 가 32 개까지 가능하므로 한 번에 list 로 보내 호출
    # 횟수를 1 회로 단축. OpenAI embeddings API 는 입력 list 의 순서를 보존한다.
    dense_hits: list[DenseHit] = []
    try:
        keyword_vectors = embedder.embed(body.keywords)
    except DependencyUnavailableError:
        raise
    except Exception as e:  # noqa: BLE001
        # 임베딩 호출 자체가 죽으면 503 으로 명시 변환. WHY: OpenAI SDK 의 일부
        # 예외는 DependencyUnavailableError 로 wrap 되지만, 우리 어댑터 외부의
        # 모듈 (network, dns) 에서 발생하는 예외도 같은 의미를 가지므로 503 으로.
        raise DependencyUnavailableError(f"embedding call failed: {e}") from e

    if len(keyword_vectors) != len(body.keywords):
        # WHY 방어: embed 가 입력 길이와 다른 출력을 돌리면 후속 zip 이 silently
        # 잘림. 명시적 에러로 끌어올린다.
        raise DependencyUnavailableError(
            f"embedding length mismatch: got {len(keyword_vectors)} expected {len(body.keywords)}"
        )

    try:
        for kw, vec in zip(body.keywords, keyword_vectors, strict=True):
            dense_hits.extend(
                graph.find_entities_dense(
                    query_embedding=vec, matched_keyword=kw, limit=per_kw
                )
            )
    except OpentologyError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("find_entities dense path failed")
        raise HTTPException(
            status_code=500,
            detail=ErrorEnvelope(
                error=ErrorBody(code="internal_error", message=str(e))
            ).model_dump(),
        )

    matches = _fuse_with_rrf(
        lexical_hits=lexical_hits,
        dense_hits=dense_hits,
        keywords=body.keywords,
        types=body.types,
        limit=body.limit,
        include_scores=body.include_scores,
    )
    return DataEnvelope(data=FindEntitiesResponse(matches=matches))


def _fuse_with_rrf(
    lexical_hits: list[KeywordHit],
    dense_hits: list[DenseHit],
    *,
    keywords: list[str],
    types: list[str] | None,
    limit: int,
    include_scores: bool,
) -> list[EntityMatch]:
    """RRF (Reciprocal Rank Fusion, k=60) — PRD 3 §3.5.

    각 keyword 별로 별도 rank list 가 들어온다. fusion 은 다음 단계:

    1. keyword 별로 lexical 결과는 raw_score 내림차순 정렬해 rank 부여 (1-based).
    2. keyword 별로 dense 결과는 raw_score (cosine) 내림차순 정렬해 rank 부여.
    3. 노드 ID 단위 union — 각 노드의 fused score 누적
       = sum over keywords of (1/(k + lex_rank) + 1/(k + dense_rank)).
       각 항은 *해당 keyword 의 lexical/dense 에서 surface 됐을 때만* 더한다.
    4. matched_keyword: *가장 큰 단일 keyword 기여* 가 발생한 keyword 유지.
       (PRD 3 §3.5: 가장 높은 점수의 keyword.)
    5. types 필터 → 점수 내림차순 → limit slice.

    WHY 라우터 안에서 fusion: 어댑터는 *데이터* 만 책임 (KeywordHit / DenseHit
    raw 점수). fusion 은 *사용자 계약* (PRD 3 §3.4 의 0..1 score) 로의 변환이라
    상위 레이어가 적절.
    """
    # 1) keyword 별 rank 부여 — lexical
    per_kw_lex_rank: dict[tuple[str, str], int] = {}  # (keyword, node_id) -> rank
    per_kw_lex_raw: dict[tuple[str, str], float] = {}
    lex_node_to_obj: dict[str, Node] = {}
    for kw in keywords:
        # 이 keyword 의 hit 만 추출 + score desc 정렬
        kw_hits = sorted(
            [h for h in lexical_hits if h.matched_keyword == kw],
            key=lambda h: h.raw_score,
            reverse=True,
        )
        for rank, h in enumerate(kw_hits, start=1):
            per_kw_lex_rank[(kw, h.node.id)] = rank
            per_kw_lex_raw[(kw, h.node.id)] = h.raw_score
            lex_node_to_obj[h.node.id] = h.node

    # 2) keyword 별 rank 부여 — dense
    per_kw_dense_rank: dict[tuple[str, str], int] = {}
    per_kw_dense_raw: dict[tuple[str, str], float] = {}
    dense_node_to_obj: dict[str, Node] = {}
    for kw in keywords:
        kw_hits = sorted(
            [h for h in dense_hits if h.matched_keyword == kw],
            key=lambda h: h.raw_score,
            reverse=True,
        )
        for rank, h in enumerate(kw_hits, start=1):
            per_kw_dense_rank[(kw, h.node.id)] = rank
            per_kw_dense_raw[(kw, h.node.id)] = h.raw_score
            dense_node_to_obj[h.node.id] = h.node

    # 3) 노드 ID union — fused score + 최고 기여 keyword 추적
    all_node_ids = set(lex_node_to_obj.keys()) | set(dense_node_to_obj.keys())
    fused_rows: list[
        tuple[float, str, Node, float, float]
    ] = []  # (fused_total, matched_kw, node, raw_lex, raw_dense)
    for node_id in all_node_ids:
        node = lex_node_to_obj.get(node_id) or dense_node_to_obj.get(node_id)
        assert node is not None
        fused_total = 0.0
        # WHY tie-break by raw lex+dense magnitude: 여러 keyword 가 같은 rank
        # (=같은 contrib) 으로 노드를 surface 시킬 수 있다 (예: 각 keyword 에서
        # 단일 hit). PRD 3 §3.5 의 "가장 높은 점수의 keyword" 의도는 *raw 신호
        # 가 강한* keyword 를 보존하는 것 — RRF contrib 동률일 때는 raw 점수의
        # 합 (lex + dense) 으로 tie-break.
        best_score: tuple[float, float] = (-1.0, -1.0)
        best_kw: str = ""
        best_raw_lex = 0.0
        best_raw_dense = 0.0
        for kw in keywords:
            lex_rank = per_kw_lex_rank.get((kw, node_id))
            dense_rank = per_kw_dense_rank.get((kw, node_id))
            contrib = 0.0
            if lex_rank is not None:
                contrib += 1.0 / (RRF_K + lex_rank)
            if dense_rank is not None:
                contrib += 1.0 / (RRF_K + dense_rank)
            if contrib == 0.0:
                continue
            fused_total += contrib
            raw_lex_kw = per_kw_lex_raw.get((kw, node_id), 0.0)
            raw_dense_kw = per_kw_dense_raw.get((kw, node_id), 0.0)
            key = (contrib, raw_lex_kw + raw_dense_kw)
            if key > best_score:
                best_score = key
                best_kw = kw
                best_raw_lex = raw_lex_kw
                best_raw_dense = raw_dense_kw
        if fused_total == 0.0:
            continue
        fused_rows.append(
            (fused_total, best_kw, node, best_raw_lex, best_raw_dense)
        )

    if not fused_rows:
        return []

    # 4) types 필터
    if types:
        type_set = set(types)
        fused_rows = [row for row in fused_rows if row[2].type in type_set]
        if not fused_rows:
            return []

    # 5) 점수 내림차순 + limit + max-normalize 로 0..1
    # WHY max-normalize after fusion: RRF 의 raw 합산은 keyword 수에 따라 절대값
    # 범위가 달라진다 (단일 keyword 면 최대 2/(k+1) ~ 0.033, 다수 keyword 면 그
    # 합). PRD 3 §3.4 의 score range 0..1 을 충족하려면 결과 집합 내 max 로 정규
    # 화. 순위 정보는 보존.
    fused_rows.sort(key=lambda r: r[0], reverse=True)
    fused_rows = fused_rows[:limit]
    max_score = max(r[0] for r in fused_rows) or 1.0

    matches: list[EntityMatch] = []
    for fused_total, kw, node, raw_lex, raw_dense in fused_rows:
        normalized = fused_total / max_score if max_score > 0 else 0.0
        normalized = max(0.0, min(1.0, normalized))
        scores: MatchScores | None = None
        if include_scores:
            scores = MatchScores(lexical=raw_lex, dense=raw_dense)
        matches.append(
            EntityMatch(
                node=node,
                score=normalized,
                matched_keyword=kw,
                scores=scores,
            )
        )
    return matches


# ---------- get_schema (PRD 3 §2) ----------


@schema_router.get(
    "/schema",
    response_model=DataEnvelope[GetSchemaResponse],
)
def get_schema(
    graph: GraphRepository = Depends(graph_repo_dep),
    settings=Depends(settings_dep),
) -> DataEnvelope[GetSchemaResponse]:
    """그래프 모양 조회 — entity_types / relation_types / embedding_info.

    WHY 캐시 없음 (MVP): 코퍼스 작고 호출 빈도 낮다. 측정 후 필요하면 short TTL
    cache 도입.
    """
    entity_stats, relation_stats = graph.get_schema_summary(examples_per_type=5)
    return DataEnvelope(
        data=GetSchemaResponse(
            entity_types=[
                EntityTypeSummary(
                    type=stat.type,
                    count=stat.count,
                    examples=[
                        EntityTypeExample(id=eid, name=name)
                        for eid, name in stat.examples
                    ],
                )
                for stat in entity_stats
            ],
            relation_types=[
                RelationTypeSummary(
                    type=stat.type,
                    count=stat.count,
                    common_pairs=[
                        RelationTypePair(from_type=ft, to_type=tt, count=c)
                        for ft, tt, c in stat.common_pairs
                    ],
                )
                for stat in relation_stats
            ],
            embedding_info=EmbeddingInfo(
                model=settings.embedding_model,
                dimension=settings.embedding_dimension,
            ),
        )
    )


# ---------- get_entity (PRD 3 §4) ----------


@entities_router.get(
    "/{entity_id}",
    response_model=DataEnvelope[GetEntityResponse],
)
def get_entity(
    entity_id: str,
    graph: GraphRepository = Depends(graph_repo_dep),
) -> DataEnvelope[GetEntityResponse]:
    """ID 로 단일 노드 + 인접 엣지 카운트 조회 — PRD 3 §4.4.

    엔티티 없으면 entity_not_found 404 (예외가 main.py 의 글로벌 핸들러에서
    envelope 으로 변환).
    """
    result = graph.get_entity_with_counts(entity_id=entity_id)
    if result is None:
        raise EntityNotFoundError(
            f"entity not found: {entity_id}", details={"id": entity_id}
        )
    return DataEnvelope(
        data=GetEntityResponse(
            node=result.node,
            edge_counts=EdgeCounts(
                outgoing=result.outgoing, incoming=result.incoming
            ),
        )
    )


# ---------- get_neighbors (PRD 3 §5) ----------


@entities_router.post(
    "/{entity_id}/neighbors",
    response_model=DataEnvelope[GetNeighborsResponse],
)
def get_neighbors(
    entity_id: str,
    body: GetNeighborsRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
) -> DataEnvelope[GetNeighborsResponse]:
    """진입점의 N-hop 이웃. 진입점 노드 포함 (PRD 3 §5.4)."""
    if not graph.entity_exists(entity_id=entity_id):
        raise EntityNotFoundError(
            f"entity not found: {entity_id}", details={"id": entity_id}
        )
    result = graph.expand_neighbors(
        entry_id=entity_id,
        relation_types=body.relation_types,
        direction=body.direction,
        hops=body.hops,
        max_nodes=body.max_nodes,
    )
    return DataEnvelope(
        data=GetNeighborsResponse(
            nodes=result.nodes,
            edges=result.edges,
            truncated=result.truncated,
        )
    )


# ---------- find_path (PRD 3 §6) ----------


@paths_router.post(
    "/find",
    response_model=DataEnvelope[FindPathResponse],
)
def find_path(
    body: FindPathRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
) -> DataEnvelope[FindPathResponse]:
    """두 노드 사이 k-shortest path — PRD 3 §6.

    422 unprocessable: from_id == to_id (스키마는 통과하지만 의미상 처리 불가).
    404 entity_not_found: from 또는 to 가 그래프에 없음.
    200 + paths=[]: 노드는 있지만 max_hops / relation_types 제약 안에서 경로 없음.
    """
    if body.from_id == body.to_id:
        raise UnprocessableError(
            "from_id and to_id must differ",
            details={"from_id": body.from_id, "to_id": body.to_id},
        )
    if not graph.entity_exists(entity_id=body.from_id):
        raise EntityNotFoundError(
            f"entity not found: {body.from_id}", details={"id": body.from_id}
        )
    if not graph.entity_exists(entity_id=body.to_id):
        raise EntityNotFoundError(
            f"entity not found: {body.to_id}", details={"id": body.to_id}
        )
    paths = graph.find_shortest_paths(
        from_id=body.from_id,
        to_id=body.to_id,
        max_hops=body.max_hops,
        max_paths=body.max_paths,
        relation_types=body.relation_types,
    )
    return DataEnvelope(
        data=FindPathResponse(
            paths=[
                PathSegment(nodes=p.nodes, edges=p.edges, length=p.length)
                for p in paths
            ]
        )
    )


# ---------- get_subgraph (PRD 3 §7) ----------


@subgraph_router.post(
    "",
    response_model=DataEnvelope[GetSubgraphResponse],
)
def get_subgraph(
    body: GetSubgraphRequest,
    graph: GraphRepository = Depends(graph_repo_dep),
) -> DataEnvelope[GetSubgraphResponse]:
    """여러 진입점 union N-hop. 진입점 echo 포함 (PRD 3 §7.4).

    진입점 중 일부가 그래프에 없으면 — 별도 entity_not_found 를 raise 하지 않고
    *존재하는 것만* 확장한다. WHY: PRD 3 §7.3 은 entry_ids 의 부재를 에러로 정의
    하지 않았고, 부분 hit 이 caller (분산 측정) 에게 의미 있는 결과일 수 있다.
    이 결정은 본 PR 의 *합리적 결정* (PRD 3 §11 미정 결정의 일부). 만약 추후
    "전부 존재해야 함" 으로 강제하려면 별도 follow-up 이슈로.
    """
    result = graph.expand_subgraph(
        entry_ids=body.entry_ids,
        relation_types=body.relation_types,
        hops=body.hops,
        max_nodes=body.max_nodes,
    )
    return DataEnvelope(
        data=GetSubgraphResponse(
            nodes=result.nodes,
            edges=result.edges,
            entry_ids=body.entry_ids,
            truncated=result.truncated,
        )
    )


# ---------- admin/ingest (M1 슬라이스 — 본 PR 무관, 그대로 유지) ----------


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
