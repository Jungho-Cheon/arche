"""Graph primitive 비즈니스 로직 — REST 라우터와 MCP 어댑터의 공통 진입점.

REST 와 MCP 가 같은 스키마와 같은 동작을 노출하므로, fusion/순회/매핑 같은 로직을
여기 한 곳에 모으고 두 통로는 얇은 어댑터로만 둔다. 순수 서비스 함수(Pydantic 입력→
응답)라 HTTP 의존성이 없고, 에러는 도메인 예외로만 raise 한다. envelope 은 REST
라우터가 감싼다(MCP 응답은 payload 만)."""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from arche_api.domain.ports import DenseHit, EmbeddingProvider, GraphRepository, KeywordHit

from ..config import Settings
from ..domain.entity_split import source_ref_paths as split_source_ref_paths
from ..domain.errors import (
    DependencyUnavailableError,
    EntityNotFoundError,
    InvalidInputError,
    UnprocessableError,
)
from ..domain.models import Edge, Node
from .plan_schemas import (
    CommitRequest,
    IngestCommitResponse,
    MergeView,
    NewEntityView,
    PlanContentRequest,
    PlanIngestRequest,
    PlanPreview,
    PlanSummary,
    PreviewRequest,
    QuestionView,
    RelationView,
    ResolveRequest,
)
from .security import ensure_entity_id, ensure_namespace_id
from .split_schemas import (
    SplitCommitRequest,
    SplitCommitResponse,
    SplitEntityView,
    SplitPlanRequest,
    SplitPreview,
    SplitPreviewRequest,
    SplitRelationView,
    SplitSummary,
)

if TYPE_CHECKING:
    from ..domain.entity_split import SplitPlan, SplitService
    from ..domain.ingest import IngestService
    from ..domain.ingest_plan import IngestPlan
    from .plan_registry import PlanRegistry
from .responses import (
    EdgeCounts,
    EmbeddingInfo,
    EntityTypeExample,
    EntityTypeSummary,
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
    PathSegment,
    RelatedNode,
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


# RRF k — 측정 통제 변수. 라우터/어댑터/테스트가 같은 값을 참조한다.
RRF_K = 60


# ---------- get_schema ----------


def get_schema(
    *,
    graph: GraphRepository,
    settings: Settings,
    namespace_id: str = "default",
) -> GetSchemaResponse:
    """그래프 모양 조회 — entity_types / relation_types / embedding_info.

    namespace_id 로 통계를 이 namespace 안으로 가둔다.
    """
    # 요청 모델을 거치지 않는 namespace 는 여기서 형식 검증한다 (#142).
    namespace_id = ensure_namespace_id(namespace_id)
    entity_stats, relation_stats = graph.get_schema_summary(
        examples_per_type=5, namespace_id=namespace_id
    )
    return GetSchemaResponse(
        entity_types=[
            EntityTypeSummary(
                type=stat.type,
                count=stat.count,
                examples=[EntityTypeExample(id=eid, name=name) for eid, name in stat.examples],
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


# ---------- find_entities ----------


def find_entities(
    body: FindEntitiesRequest,
    *,
    graph: GraphRepository,
    embedder: EmbeddingProvider,
    namespace_id: str = "default",
) -> FindEntitiesResponse:
    """어휘 + dense 하이브리드 + RRF.

    keyword 별 fulltext top-k(lexical) + ANN top-k(dense)를 노드 ID 단위로 union 해
    RRF 로 결합하고, types 필터 → 점수 내림차순 → limit slice. 임베딩이 죽으면 503 을
    그대로 raise 한다(lexical-only silent fallback 은 측정 무결성을 해친다)."""
    # 요청 모델 밖 namespace 형식 검증 (#142).
    namespace_id = ensure_namespace_id(namespace_id)
    # keyword 별 풀을 입력 limit 보다 넉넉히 — 여러 keyword 가 같은 노드를 낼 수 있다.
    per_kw = min(50, max(body.limit * 2, 10))

    lexical_hits = graph.find_by_keywords_scored(
        keywords=body.keywords, limit_per_keyword=per_kw, namespace_id=namespace_id
    )

    # keyword 를 한 번에 배치 임베딩한다(호출 1회, 입력 순서 보존).
    try:
        keyword_vectors = embedder.embed(body.keywords)
    except DependencyUnavailableError:
        raise
    except Exception as e:  # noqa: BLE001
        # 어댑터 밖(network/dns)에서 난 예외도 같은 의미라 503 으로 명시 변환한다.
        raise DependencyUnavailableError(f"embedding call failed: {e}") from e

    if len(keyword_vectors) != len(body.keywords):
        # embed 출력 길이가 다르면 zip 이 조용히 잘려, 명시적 에러로 올린다.
        raise DependencyUnavailableError(
            f"embedding length mismatch: got {len(keyword_vectors)} expected {len(body.keywords)}"
        )

    dense_hits: list[DenseHit] = []
    for kw, vec in zip(body.keywords, keyword_vectors, strict=True):
        dense_hits.extend(
            graph.find_entities_dense(
                query_embedding=vec,
                matched_keyword=kw,
                limit=per_kw,
                namespace_id=namespace_id,
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
    """RRF (Reciprocal Rank Fusion).

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
        fused_rows.append((fused_total, best_kw, node, best_raw_lex, best_raw_dense))

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


# ---------- get_entity ----------


def get_entity(
    *,
    entity_id: str,
    graph: GraphRepository,
    namespace_id: str = "default",
) -> GetEntityResponse:
    """ID 로 단일 노드 + 인접 엣지 카운트 조회. 없거나 namespace 밖이면
    EntityNotFoundError."""
    # 요청 모델 밖 namespace 와 id 형식 검증 (#142).
    namespace_id = ensure_namespace_id(namespace_id)
    entity_id = ensure_entity_id(entity_id)
    result = graph.get_entity_with_counts(entity_id=entity_id, namespace_id=namespace_id)
    if result is None:
        raise EntityNotFoundError(f"entity not found: {entity_id}", details={"id": entity_id})
    return GetEntityResponse(
        node=result.node,
        edge_counts=EdgeCounts(outgoing=result.outgoing, incoming=result.incoming),
    )


# ---------- get_neighbors ----------


def get_neighbors(
    *,
    entity_id: str,
    body: GetNeighborsRequest,
    graph: GraphRepository,
    namespace_id: str = "default",
) -> GetNeighborsResponse:
    """진입점의 N-hop 이웃. 진입점 노드 포함. 순회는 이 namespace 안에서만 (#98)."""
    # 요청 모델 밖 namespace 형식 검증 (#142).
    namespace_id = ensure_namespace_id(namespace_id)
    if not graph.entity_exists(entity_id=entity_id, namespace_id=namespace_id):
        raise EntityNotFoundError(f"entity not found: {entity_id}", details={"id": entity_id})
    result = graph.expand_neighbors(
        entry_id=entity_id,
        relation_types=body.relation_types,
        direction=body.direction,
        hops=body.hops,
        max_nodes=body.max_nodes,
        namespace_id=namespace_id,
    )
    return GetNeighborsResponse(
        nodes=result.nodes,
        edges=result.edges,
        truncated=result.truncated,
    )


# ---------- find_path ----------


def find_path(
    body: FindPathRequest,
    *,
    graph: GraphRepository,
    namespace_id: str = "default",
) -> FindPathResponse:
    """두 노드 사이 k-shortest path(양 끝점과 경로 모두 이 namespace 안).

    from_id == to_id 면 422, 끝점이 없으면 404, 노드는 있지만 경로가 없으면 200+paths=[]."""
    # 요청 모델 밖 namespace 형식 검증 (#142).
    namespace_id = ensure_namespace_id(namespace_id)
    if body.from_id == body.to_id:
        raise UnprocessableError(
            "from_id and to_id must differ",
            details={"from_id": body.from_id, "to_id": body.to_id},
        )
    if not graph.entity_exists(entity_id=body.from_id, namespace_id=namespace_id):
        raise EntityNotFoundError(f"entity not found: {body.from_id}", details={"id": body.from_id})
    if not graph.entity_exists(entity_id=body.to_id, namespace_id=namespace_id):
        raise EntityNotFoundError(f"entity not found: {body.to_id}", details={"id": body.to_id})
    paths = graph.find_shortest_paths(
        from_id=body.from_id,
        to_id=body.to_id,
        max_hops=body.max_hops,
        max_paths=body.max_paths,
        relation_types=body.relation_types,
        namespace_id=namespace_id,
    )
    return FindPathResponse(
        paths=[
            PathSegment(nodes=p.nodes, edges=p.edges, length=p.length, hub_score=p.hub_score)
            for p in paths
        ]
    )


# ---------- get_subgraph ----------


def get_subgraph(
    body: GetSubgraphRequest,
    *,
    graph: GraphRepository,
    namespace_id: str = "default",
) -> GetSubgraphResponse:
    """여러 진입점 union N-hop(진입점 echo 포함, 이 namespace 안에서만 확장).
    없거나 namespace 밖인 진입점은 entity_not_found 대신 조용히 무시하고 나머지만
    확장한다."""
    # 요청 모델 밖 namespace 형식 검증 (#142).
    namespace_id = ensure_namespace_id(namespace_id)
    result = graph.expand_subgraph(
        entry_ids=body.entry_ids,
        relation_types=body.relation_types,
        hops=body.hops,
        max_nodes=body.max_nodes,
        namespace_id=namespace_id,
    )
    return GetSubgraphResponse(
        nodes=result.nodes,
        edges=result.edges,
        entry_ids=body.entry_ids,
        truncated=result.truncated,
    )


# ---------- find_related ----------


def find_related(
    body: FindRelatedRequest,
    *,
    graph: GraphRepository,
    namespace_id: str = "default",
) -> FindRelatedResponse:
    """시드 집합에서 구조적으로 가까운 관련 노드 top-k.

    get_subgraph 순회(다중 시드 BFS)로 반경 안의 서브그래프를 한 번 가져온 뒤 시드
    로부터의 감쇠 확산 근접도를 계산한다. 그래서 백엔드와 무관하고 GDS 같은 추가
    인프라가 필요 없다. 정확한 PageRank 수치가 아니라 왕복을 한 번으로 접는 근접
    랭킹이 목표다. 없는 시드는 조용히 무시한다."""
    namespace_id = ensure_namespace_id(namespace_id)
    # 근접 랭킹이 의미를 가지려면 후보 풀이 top_k 보다 넉넉해야 한다. get_subgraph
    # 는 시드에서 가까운 순으로 max_nodes 에서 자르므로, 풀을 top_k 의 배수로 잡아
    # "top_k 를 채울 만큼 가까운 노드" 를 확보한다.
    pool = min(2000, max(body.top_k * 10, 100))
    result = graph.expand_subgraph(
        entry_ids=body.seeds,
        relation_types=body.relation_types,
        hops=body.max_hops,
        max_nodes=pool,
        namespace_id=namespace_id,
    )
    related, truncated = _score_proximity(
        seeds=body.seeds,
        nodes=result.nodes,
        edges=result.edges,
        top_k=body.top_k,
        damping=body.damping,
    )
    return FindRelatedResponse(
        related=related,
        seeds=body.seeds,
        # 풀 자체가 잘렸거나(result.truncated) 후보가 top_k 를 넘어 잘렸으면 truncated.
        truncated=truncated or result.truncated,
    )


def _score_proximity(
    *,
    seeds: list[str],
    nodes: list[Node],
    edges: list[Edge],
    top_k: int,
    damping: float,
) -> tuple[list[RelatedNode], bool]:
    """다중 시드 감쇠 확산 근접도 — 순수 함수 (테스트 용이).

    각 시드에서 BFS 로 최단 홉 거리를 구하고, 노드마다 시드별 기여
    `damping ** distance` 를 합산한다. 여러 시드에 가깝거나 가까운 홉일수록 점수가
    높다. 시드 자신은 결과에서 제외한다. 점수는 이 응답 안에서 max-normalize 해
    0..1 로 돌려준다 (find_entities 의 정규화와 같은 규약).

    반환 (related, truncated) — truncated 는 후보 수가 top_k 를 넘어 잘렸는지.
    """
    node_by_id = {n.id: n for n in nodes}
    # 무방향 인접 — 근접도는 방향을 구분하지 않는다. 양 끝점이 모두 서브그래프
    # 안에 있는 엣지만 사용한다.
    adjacency: dict[str, set[str]] = {}
    for e in edges:
        if e.from_ in node_by_id and e.to in node_by_id:
            adjacency.setdefault(e.from_, set()).add(e.to)
            adjacency.setdefault(e.to, set()).add(e.from_)

    seed_set = set(seeds)
    seeds_present = [s for s in seeds if s in node_by_id]
    if not seeds_present:
        return [], False

    score: dict[str, float] = {}
    min_dist: dict[str, int] = {}
    for seed in seeds_present:
        for node_id, dist in _bfs_distances(seed, adjacency).items():
            score[node_id] = score.get(node_id, 0.0) + damping**dist
            if node_id not in min_dist or dist < min_dist[node_id]:
                min_dist[node_id] = dist

    # 시드는 결과에서 제외 — caller 가 이미 아는 진입점이다.
    candidate_ids = [nid for nid in score if nid not in seed_set]
    if not candidate_ids:
        return [], False

    # 점수 내림차순 → 같은 점수면 가까운 거리 우선 → id 사전순(결정성).
    candidate_ids.sort(key=lambda nid: (-score[nid], min_dist[nid], nid))
    truncated = len(candidate_ids) > top_k
    kept = candidate_ids[:top_k]

    max_score = max(score[nid] for nid in kept) or 1.0
    related = [
        RelatedNode(
            node=node_by_id[nid],
            score=max(0.0, min(1.0, score[nid] / max_score)),
            distance=min_dist[nid],
        )
        for nid in kept
    ]
    return related, truncated


def _bfs_distances(start: str, adjacency: dict[str, set[str]]) -> dict[str, int]:
    """start 로부터 각 노드의 최단 홉 거리 (start 포함, 거리 0)."""
    dist: dict[str, int] = {start: 0}
    queue: deque[str] = deque([start])
    while queue:
        cur = queue.popleft()
        for nb in adjacency.get(cur, ()):
            if nb not in dist:
                dist[nb] = dist[cur] + 1
                queue.append(nb)
    return dist


# ---------- reviewable ingest: plan → preview → commit ----------
# 적재 전 변경을 사람이 검토하는 흐름. plan 이 변경 묶음을 만들어 레지스트리에 보관,
# preview 가 펼치며 "미리보기 완료" 로 표시, commit 은 미리보기를 거친 경우에만 적용한다.
# "지금 적용해도 안전한가" 판단(미리보기 전제 + stale 검출)은 도메인이 아니라 이 서비스에 둔다.


def _require_plan(plan_id: str, registry: PlanRegistry) -> IngestPlan:
    """plan_id 로 계획을 찾고, 없으면 거부한다. 계획은 수명이 지나도 사라지므로 두
    경우를 한 메시지로 묶고 details 에 수명을 실어 다시 계획하면 된다고 알린다."""
    plan = registry.get(plan_id)
    if plan is None:
        raise InvalidInputError(
            "unknown or expired plan_id",
            details={"plan_id": plan_id, "plan_ttl_seconds": registry.ttl_seconds},
        )
    return plan


def _summarize_plan(plan: IngestPlan) -> PlanSummary:
    """IngestPlan 의 writes 종류별 개수 + 미해소 질문 수를 PlanSummary 로 집계한다."""
    n_new = sum(1 for w in plan.writes if w.method == "create_entity")
    n_merge = sum(1 for w in plan.writes if w.method == "apply_merge_mutation")
    n_rel = sum(1 for w in plan.writes if w.method == "upsert_relation")
    n_del = sum(1 for w in plan.writes if w.method in ("apply_entity_diff", "apply_relation_diff"))
    return PlanSummary(
        plan_id=plan.plan_id,
        source_path=plan.source_path,
        entities_created=n_new,
        entities_merged=n_merge,
        relations_created=n_rel,
        deletion_count=n_del,
        open_questions=len(plan.open_questions),
    )


def plan_ingest(
    body: PlanIngestRequest,
    *,
    service: IngestService,
    registry: PlanRegistry,
) -> PlanSummary:
    """파일을 쓰지 않고 변경 묶음을 만들어 레지스트리에 보관 + 개수 요약 반환."""
    plan = service.plan_file(Path(body.path), namespace_id=body.namespace_id, hints=body.hints)
    registry.create(plan)
    return _summarize_plan(plan)


def plan_ingest_content(
    body: PlanContentRequest,
    *,
    service: IngestService,
    registry: PlanRegistry,
) -> PlanSummary:
    """콘텐츠판 plan — 파일 없이 텍스트로 변경 묶음을 만들어 보관하고 요약한다.
    이후 preview/resolve/commit 은 파일 경로판과 같은 plan_id 흐름을 탄다."""
    plan = service.plan_content(
        content=body.content,
        source_id=body.source_id,
        namespace_id=body.namespace_id,
        hints=body.hints,
    )
    registry.create(plan)
    return _summarize_plan(plan)


def preview_plan(
    body: PreviewRequest,
    *,
    registry: PlanRegistry,
) -> PlanPreview:
    """변경 묶음을 항목 단위로 펼치고 계획을 "미리보기 완료" 로 표시한다. 미리보기를
    실제로 받아 본 호출만 플래그를 세워야 commit latch 가 의미를 가지므로 여기서 표시한다."""
    plan = _require_plan(body.plan_id, registry)
    registry.mark_previewed(plan.plan_id)
    new_entities = [
        NewEntityView(
            name=w.kwargs["entity"].name,
            type=w.kwargs["entity"].type,
            aliases=list(w.kwargs["entity"].aliases),
        )
        for w in plan.writes
        if w.method == "create_entity"
    ]
    merges = [
        MergeView(
            target_id=w.kwargs["mutation"].id,
            before_name=(w.before.name if w.before else ""),
            after_aliases=list(w.kwargs["mutation"].aliases),
        )
        for w in plan.writes
        if w.method == "apply_merge_mutation"
    ]
    new_relations = [
        RelationView(
            from_id=w.kwargs["from_id"],
            to_id=w.kwargs["to_id"],
            type=w.kwargs["rel_type"],
        )
        for w in plan.writes
        if w.method == "upsert_relation"
    ]
    n_del = sum(1 for w in plan.writes if w.method in ("apply_entity_diff", "apply_relation_diff"))
    questions = [
        QuestionView(
            question_id=q.question_id,
            extracted_name=q.extracted_name,
            extracted_type=q.extracted_type,
            candidate_id=q.candidate_id,
            candidate_name=q.candidate_name,
            similarity=q.similarity,
            kind=q.kind,
        )
        for q in plan.open_questions
    ]
    return PlanPreview(
        new_entities=new_entities,
        merges=merges,
        new_relations=new_relations,
        deletion_count=n_del,
        questions=questions,
    )


def resolve_ingest(
    body: ResolveRequest,
    *,
    service: IngestService,
    registry: PlanRegistry,
) -> PlanSummary:
    """사람이 답한 모호성 질문을 적용해 *같은 plan_id* 로 계획을 다듬는다.

    흐름:
      1. plan_id 로 계획을 찾는다 (없으면 InvalidInputError).
      2. resolutions 의 question_id 가 모두 계획의 open_questions 에 있는지 검증한다.
         도메인 resolve_plan 은 알 수 없는 id 를 조용히 무시하지만(멱등), 통로는 틀린
         id 를 사용자에게 알려야 하므로 위임 전에 거부한다.
      3. {question_id: decision} 맵으로 도메인 resolve_plan 에 위임한다.
      4. 정제된 계획을 *같은 plan_id* 로 레지스트리에 다시 보관한다 (previewed 는
         resolve_plan 이 False 로 초기화 — 다시 미리보기를 거쳐야 commit 가능).
      5. 정제 계획의 요약(남은 질문 수 포함)을 돌려준다.
    """
    plan = _require_plan(body.plan_id, registry)
    known_ids = {q.question_id for q in plan.open_questions}
    unknown = [r.question_id for r in body.resolutions if r.question_id not in known_ids]
    if unknown:
        raise InvalidInputError(
            "unknown question_id",
            details={"plan_id": plan.plan_id, "question_ids": unknown},
        )
    refined = service.resolve_plan(plan, {r.question_id: r.decision for r in body.resolutions})
    registry.create(refined)
    return _summarize_plan(refined)


def commit_plan(
    body: CommitRequest,
    *,
    service: IngestService,
    registry: PlanRegistry,
) -> IngestCommitResponse:
    """미리보기를 거친 계획만 그래프에 적용한다 (안전 latch).

    latch 두 단계:
      1. previewed=False → 422 unprocessable. 사용자가 변경을 눈으로 확인하기 전에
         그래프를 건드리는 사고를 막는다.
      2. depends_on_entity_ids 중 *지금은 사라진* 노드가 있으면 → 422. 계획을 세운
         시점과 적용 시점 사이에 그래프가 바뀌어 병합 대상이 없어진 경우, 재생이
         어긋난 결과를 만든다. "stale; re-plan" 으로 명시 거부해 다시 계획하도록.
    """
    plan = _require_plan(body.plan_id, registry)
    if not plan.previewed:
        raise UnprocessableError(
            "call ingest_preview before commit", details={"plan_id": plan.plan_id}
        )
    for eid in plan.depends_on_entity_ids:
        if not service._graph.entity_exists(entity_id=eid):
            raise UnprocessableError(
                "plan is stale; re-plan",
                details={"plan_id": plan.plan_id, "missing_entity_id": eid},
            )
    result = service.commit_plan(plan)
    return IngestCommitResponse(
        entities_created=result.entities_created,
        entities_updated=result.entities_updated,
        relations_created=result.relations_created,
        deletions=result.relations_deleted,
    )


# ---------- 떼어내기: plan → preview → commit ----------
# 잘못 합친 노드를 둘로 가른다. 적재와 같은 안전 latch 를 쓰되 resolve 단계가 없다 —
# 계획에 LLM 호출이 없어, 사람이 정한 관계 배정을 실어 다시 계획하는 편이 싸다.


def _require_split_plan(plan_id: str, registry: PlanRegistry) -> SplitPlan:
    plan = registry.get(plan_id)
    if plan is None:
        raise InvalidInputError(
            "unknown or expired plan_id",
            details={"plan_id": plan_id, "plan_ttl_seconds": registry.ttl_seconds},
        )
    return plan


def _split_summary(plan: SplitPlan) -> SplitSummary:
    moved = [a for a in plan.assignments if a.decision == "move"]
    kept = [a for a in plan.assignments if a.decision == "keep"]
    return SplitSummary(
        plan_id=plan.plan_id,
        origin_id=plan.origin_id,
        origin_name=plan.origin_name,
        new_name=plan.new_entity.name,
        aliases_moved=len(plan.new_entity.aliases),
        aliases_kept=len(plan.origin_mutation.aliases),
        source_refs_moved=len(plan.new_entity.source_refs),
        source_refs_kept=len(plan.origin_mutation.source_refs),
        relations_moved=len(moved),
        relations_kept=len(kept),
        open_questions=len(plan.open_questions),
    )


def _relation_view(assignment) -> SplitRelationView:  # noqa: ANN001
    return SplitRelationView(
        relation_id=assignment.relation_id,
        type=assignment.rel_type,
        direction=assignment.direction,
        other_id=assignment.other_id,
        other_name=assignment.other_name,
        source_paths=list(assignment.source_paths),
        decision=assignment.decision,
        reason=assignment.reason,
    )


def plan_entity_split(
    body: SplitPlanRequest,
    *,
    service: SplitService,
    registry: PlanRegistry,
) -> SplitSummary:
    """그래프를 건드리지 않고 떼어내기 계획을 세워 보관한다."""
    from ulid import ULID

    plan = service.plan_split(
        plan_id=f"spl_{ULID()}",
        entity_id=ensure_entity_id(body.entity_id),
        new_name=body.new_name,
        move_aliases=body.move_aliases,
        move_source_paths=body.move_source_paths,
        relation_decisions=dict(body.relation_decisions),
        new_description=body.new_description,
        namespace_id=ensure_namespace_id(body.namespace_id),
    )
    registry.create(plan)
    return _split_summary(plan)


def preview_entity_split(
    body: SplitPreviewRequest,
    *,
    registry: PlanRegistry,
) -> SplitPreview:
    """두 노드가 어떤 모습이 되고 관계가 어디로 가는지 펼치고, 확정 latch 를 건다."""
    plan = _require_split_plan(body.plan_id, registry)
    registry.mark_previewed(plan.plan_id)
    relations = [_relation_view(a) for a in plan.assignments]
    return SplitPreview(
        plan_id=plan.plan_id,
        origin=SplitEntityView(
            id=plan.origin_id,
            name=plan.origin_name,
            type=plan.new_entity.type,
            aliases=list(plan.origin_mutation.aliases),
            description=plan.origin_mutation.description or None,
            source_paths=split_source_ref_paths(plan.origin_mutation.source_refs),
        ),
        new_entity=SplitEntityView(
            id=plan.new_entity.id,
            name=plan.new_entity.name,
            type=plan.new_entity.type,
            aliases=list(plan.new_entity.aliases),
            description=plan.new_entity.description,
            source_paths=split_source_ref_paths(plan.new_entity.source_refs),
        ),
        relations=relations,
        questions=[r for r in relations if r.decision == "ask"],
    )


def commit_entity_split(
    body: SplitCommitRequest,
    *,
    service: SplitService,
    registry: PlanRegistry,
) -> SplitCommitResponse:
    """미리 보기를 거치고 사람 판단이 모두 끝난 계획만 그래프에 반영한다."""
    plan = _require_split_plan(body.plan_id, registry)
    if not plan.previewed:
        raise UnprocessableError(
            "call entity_split_preview before commit", details={"plan_id": plan.plan_id}
        )
    result = service.commit_split(plan)
    return SplitCommitResponse(
        origin_id=result.origin_id,
        new_entity_id=result.new_entity_id,
        aliases_moved=result.aliases_moved,
        source_refs_moved=result.source_refs_moved,
        relations_moved=result.relations_moved,
        relations_kept=result.relations_kept,
    )
