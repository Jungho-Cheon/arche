"""Graph primitive 비즈니스 로직 — REST 라우터와 MCP 어댑터의 *공통 진입점* .

WHY 모듈 분리: PRD 3 §0.1 의 1:1 매핑 — REST 와 MCP 는 *같은 입출력 스키마* 와
*같은 동작* 을 노출한다. 두 통로가 각자 비즈니스 로직 (RRF fusion / BFS 절단 /
find_path 매핑) 을 복사하면, 한쪽 수정이 다른 쪽에 누락되어 PRD 3 §0.1 의 정합
계약이 깨진다. 따라서 비즈니스 로직은 *한 곳* (본 모듈) 에 모으고, 라우터는
FastAPI 어댑터 (HTTPException + envelope), MCP 어댑터는 MCP 프로토콜 어댑터로
얇게 동작한다.

본 모듈은 **순수 서비스 함수** 만 담는다 — Pydantic 입력 모델을 받고, Pydantic
응답 모델을 돌려준다. FastAPI 의 `Depends` / `HTTPException` / `Request` 같은
HTTP 의존성은 없다. 에러는 도메인 예외 (`OpentologyError` 계열) 로만 raise —
REST 는 글로벌 핸들러로, MCP 는 `_to_mcp_error` 로 변환한다.

WHY envelope (`DataEnvelope`) 미사용: PRD 3 §0.4 — MCP 의 응답은 *primitive
payload 만* (envelope 없음). REST 라우터가 envelope 으로 감싸는 책임을 진다.
"""

from __future__ import annotations

import logging

from ..adapters.embedding import EmbeddingProvider
from ..adapters.graph import DenseHit, GraphRepository, KeywordHit
from ..config import Settings
from ..domain.errors import (
    DependencyUnavailableError,
    EntityNotFoundError,
    UnprocessableError,
)
from ..domain.models import Node
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
    EntityMatch,
    FindEntitiesRequest,
    FindEntitiesResponse,
    MatchScores,
)


logger = logging.getLogger(__name__)


# WHY RRF k 상수 (60): PRD 3 §3.5 권장값. 측정 통제 변수 (ADR-0001) — 변경 시
# ADR-0003 amend + 새 측정 회차 필요. 모듈 상수로 기록해 라우터/어댑터/테스트가
# 같은 값을 참조하도록 한다.
RRF_K = 60


# ---------- get_schema (PRD 3 §2) ----------


def get_schema(
    *,
    graph: GraphRepository,
    settings: Settings,
) -> GetSchemaResponse:
    """그래프 모양 조회 — entity_types / relation_types / embedding_info."""
    entity_stats, relation_stats = graph.get_schema_summary(examples_per_type=5)
    return GetSchemaResponse(
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


# ---------- find_entities (PRD 3 §3) ----------


def find_entities(
    body: FindEntitiesRequest,
    *,
    graph: GraphRepository,
    embedder: EmbeddingProvider,
) -> FindEntitiesResponse:
    """어휘 + dense 하이브리드 + RRF (k=60).

    동작 (PRD 3 §3.5):
    1. 각 input keyword 에 대해 fulltext top-k (lexical) + ANN top-k (dense).
    2. 노드 ID 단위 union — RRF 결합.
    3. types 필터 → 점수 내림차순 → limit slice → include_scores 옵션 적용.

    *graceful fallback 없음* — 임베딩 의존성이 죽으면 503 dependency_unavailable
    을 그대로 raise. lexical-only silent fallback 은 측정 무결성을 해친다.
    """
    # WHY limit_per_keyword 가 입력 limit 보다 크게: 여러 keyword 가 같은 노드를
    # surface 시키는 경우를 흡수하려면 keyword 별 풀이 입력 limit 보다 넉넉해야.
    per_kw = min(50, max(body.limit * 2, 10))

    lexical_hits = graph.find_by_keywords_scored(
        keywords=body.keywords, limit_per_keyword=per_kw
    )

    # dense path — 각 keyword 별 임베딩 1 회 → ANN.
    # WHY 배치 임베딩: keyword 가 32 개까지 가능하므로 한 번에 list 로 보내 호출
    # 횟수를 1 회로 단축. OpenAI embeddings API 는 입력 list 의 순서를 보존한다.
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

    dense_hits: list[DenseHit] = []
    for kw, vec in zip(body.keywords, keyword_vectors, strict=True):
        dense_hits.extend(
            graph.find_entities_dense(
                query_embedding=vec, matched_keyword=kw, limit=per_kw
            )
        )

    matches = _fuse_with_rrf(
        lexical_hits=lexical_hits,
        dense_hits=dense_hits,
        keywords=body.keywords,
        types=body.types,
        limit=body.limit,
        include_scores=body.include_scores,
    )
    return FindEntitiesResponse(matches=matches)


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

    각 keyword 별로 별도 rank list 가 들어온다. fusion 단계:

    1. keyword 별로 lexical 결과는 raw_score 내림차순 정렬해 rank 부여 (1-based).
    2. keyword 별로 dense 결과는 raw_score (cosine) 내림차순 정렬해 rank 부여.
    3. 노드 ID 단위 union — 각 노드의 fused score 누적
       = sum over keywords of (1/(k + lex_rank) + 1/(k + dense_rank)).
       각 항은 *해당 keyword 의 lexical/dense 에서 surface 됐을 때만* 더한다.
    4. matched_keyword: *가장 큰 단일 keyword 기여* 가 발생한 keyword 유지.
    5. types 필터 → 점수 내림차순 → limit slice.
    """
    # 1) keyword 별 rank 부여 — lexical
    per_kw_lex_rank: dict[tuple[str, str], int] = {}  # (keyword, node_id) -> rank
    per_kw_lex_raw: dict[tuple[str, str], float] = {}
    lex_node_to_obj: dict[str, Node] = {}
    for kw in keywords:
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


# ---------- get_entity (PRD 3 §4) ----------


def get_entity(
    *,
    entity_id: str,
    graph: GraphRepository,
) -> GetEntityResponse:
    """ID 로 단일 노드 + 인접 엣지 카운트 조회.

    엔티티 없으면 EntityNotFoundError (REST 404 / MCP entity_not_found).
    """
    result = graph.get_entity_with_counts(entity_id=entity_id)
    if result is None:
        raise EntityNotFoundError(
            f"entity not found: {entity_id}", details={"id": entity_id}
        )
    return GetEntityResponse(
        node=result.node,
        edge_counts=EdgeCounts(
            outgoing=result.outgoing, incoming=result.incoming
        ),
    )


# ---------- get_neighbors (PRD 3 §5) ----------


def get_neighbors(
    *,
    entity_id: str,
    body: GetNeighborsRequest,
    graph: GraphRepository,
) -> GetNeighborsResponse:
    """진입점의 N-hop 이웃. 진입점 노드 포함."""
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
    return GetNeighborsResponse(
        nodes=result.nodes,
        edges=result.edges,
        truncated=result.truncated,
    )


# ---------- find_path (PRD 3 §6) ----------


def find_path(
    body: FindPathRequest,
    *,
    graph: GraphRepository,
) -> FindPathResponse:
    """두 노드 사이 k-shortest path.

    422 unprocessable: from_id == to_id.
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
    return FindPathResponse(
        paths=[
            PathSegment(nodes=p.nodes, edges=p.edges, length=p.length)
            for p in paths
        ]
    )


# ---------- get_subgraph (PRD 3 §7) ----------


def get_subgraph(
    body: GetSubgraphRequest,
    *,
    graph: GraphRepository,
) -> GetSubgraphResponse:
    """여러 진입점 union N-hop. 진입점 echo 포함.

    진입점 중 일부가 그래프에 없으면 — 별도 entity_not_found 를 raise 하지 않고
    *존재하는 것만* 확장한다 (PRD 3 §11 미정 결정 — 본 PR 의 합리적 결정).
    """
    result = graph.expand_subgraph(
        entry_ids=body.entry_ids,
        relation_types=body.relation_types,
        hops=body.hops,
        max_nodes=body.max_nodes,
    )
    return GetSubgraphResponse(
        nodes=result.nodes,
        edges=result.edges,
        entry_ids=body.entry_ids,
        truncated=result.truncated,
    )
