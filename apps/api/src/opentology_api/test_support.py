"""테스트 전용 FakeGraph 어댑터 — MCP stdio e2e 테스트가 외부 Neo4j 없이 동작.

WHY 별도 모듈 + production 패키지에 포함: integration 테스트가 *본 서버를
subprocess 로 spawn* 한다 (실제 stdio 핸드셰이크 검증). subprocess 안에서 import
가능하려면 production 패키지 안에 위치해야 한다. 단 *production 코드가 본
모듈을 import 하지 않는다* — CLI 가 환경변수 `OPENTOLOGY_TEST_FAKE_GRAPH=1` 일
때만 lazy import.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from opentology_api.domain.ports import (
    DenseHit,
    EntityTypeStat,
    EntityWithCounts,
    GraphRepository,
    KeywordHit,
    NeighborhoodResult,
    PathResult,
    RelationTypeStat,
)

from .domain.models import Edge, Node, SourceRef, now_rfc3339


@dataclass
class _FakeData:
    """e2e 테스트의 고정 fixture — 2 노드 + 1 엣지."""

    node_a: Node = field(default_factory=lambda: _make_node("01HZX0G7M8N0RT0V0EXAMPLE01", "여름 쿠폰", "coupon"))
    node_b: Node = field(default_factory=lambda: _make_node("01HZX0G7M8N0RT0V0EXAMPLE02", "스니커즈", "product"))


def _make_node(node_id: str, name: str, type_: str) -> Node:
    now = now_rfc3339()
    return Node(
        id=node_id,
        name=name,
        type=type_,
        aliases=[],
        description=None,
        properties={},
        source_refs=[SourceRef(source_path="/tmp/fixture.md")],
        created_at=now,
        updated_at=now,
    )


def _make_edge(from_id: str, to_id: str, rel_type: str) -> Edge:
    now = now_rfc3339()
    return Edge.model_validate(
        {
            "id": "01HZX0G7M8N0RT0V0EXAMPLE03",
            "from": from_id,
            "to": to_id,
            "type": rel_type,
            "properties": {},
            "source_refs": [],
            "created_at": now,
            "updated_at": now,
        }
    )


class FakeGraph(GraphRepository):
    """결정적 in-memory 그래프 — 2 노드 + 1 엣지.

    WHY 최소 fixture: e2e 테스트는 *프로토콜 핸드셰이크* 와 *6 primitive 응답
    경로* 만 확인한다. 실제 BFS / 하이브리드 매칭 동작은 unit + live 에서.
    """

    def __init__(self) -> None:
        self._data = _FakeData()
        self._edge = _make_edge(
            from_id=self._data.node_a.id,
            to_id=self._data.node_b.id,
            rel_type="applies_to",
        )

    # ----- 인덱스 / 헬스 -----

    def ensure_indexes(self) -> None:
        pass

    def healthcheck(self) -> bool:
        return True

    # ----- 6 primitive 가 호출하는 메서드만 의미 있게 구현 -----

    def find_by_keywords_scored(
        self, *, keywords, limit_per_keyword
    ) -> list[KeywordHit]:
        # 단순 매칭: keyword 가 node_a.name 안에 포함되면 hit.
        hits: list[KeywordHit] = []
        for kw in keywords:
            for node in (self._data.node_a, self._data.node_b):
                if kw in node.name:
                    hits.append(KeywordHit(node=node, raw_score=0.5, matched_keyword=kw))
        return hits

    def find_entities_dense(
        self, *, query_embedding, matched_keyword, limit
    ) -> list[DenseHit]:
        # dense 는 항상 빈 결과 — lexical 만으로 fused score 가 의미 있게 산출.
        return []

    def get_schema_summary(self, *, examples_per_type=5):
        return (
            [
                EntityTypeStat(
                    type="coupon", count=1, examples=[(self._data.node_a.id, self._data.node_a.name)]
                ),
                EntityTypeStat(
                    type="product", count=1, examples=[(self._data.node_b.id, self._data.node_b.name)]
                ),
            ],
            [
                RelationTypeStat(
                    type="applies_to",
                    count=1,
                    common_pairs=[("coupon", "product", 1)],
                )
            ],
        )

    def get_entity_with_counts(self, *, entity_id):
        for node in (self._data.node_a, self._data.node_b):
            if node.id == entity_id:
                if node.id == self._data.node_a.id:
                    return EntityWithCounts(node=node, outgoing={"applies_to": 1}, incoming={})
                return EntityWithCounts(node=node, outgoing={}, incoming={"applies_to": 1})
        return None

    def count_entities_by_namespace(self):
        return {}

    def entity_exists(self, *, entity_id) -> bool:
        return entity_id in {self._data.node_a.id, self._data.node_b.id}

    def get_stored_entity(self, *, entity_id):
        return None

    def expand_neighbors(
        self, *, entry_id, relation_types, direction, hops, max_nodes
    ) -> NeighborhoodResult:
        if entry_id == self._data.node_a.id:
            return NeighborhoodResult(
                nodes=[self._data.node_a, self._data.node_b],
                edges=[self._edge],
                truncated=False,
            )
        if entry_id == self._data.node_b.id:
            return NeighborhoodResult(
                nodes=[self._data.node_b, self._data.node_a],
                edges=[self._edge],
                truncated=False,
            )
        return NeighborhoodResult(nodes=[], edges=[], truncated=False)

    def expand_subgraph(
        self, *, entry_ids, relation_types, hops, max_nodes
    ) -> NeighborhoodResult:
        nodes = []
        seen: set[str] = set()
        for eid in entry_ids:
            for node in (self._data.node_a, self._data.node_b):
                if node.id == eid and node.id not in seen:
                    nodes.append(node)
                    seen.add(node.id)
        # 엣지 — 둘 다 진입점이거나 인접 확장 결과로 포함.
        if self._data.node_a.id in seen and self._data.node_b.id in seen:
            edges = [self._edge]
        elif seen:
            # 인접 확장 — hops>=1 이면 반대편 노드도 포함.
            if hops >= 1 and self._data.node_a.id in seen:
                nodes.append(self._data.node_b)
                edges = [self._edge]
            elif hops >= 1 and self._data.node_b.id in seen:
                nodes.append(self._data.node_a)
                edges = [self._edge]
            else:
                edges = []
        else:
            edges = []
        return NeighborhoodResult(nodes=nodes, edges=edges, truncated=False)

    def find_shortest_paths(
        self, *, from_id, to_id, max_hops, max_paths, relation_types
    ) -> list[PathResult]:
        valid = (
            (from_id == self._data.node_a.id and to_id == self._data.node_b.id)
            or (from_id == self._data.node_b.id and to_id == self._data.node_a.id)
        )
        if not valid:
            return []
        if from_id == self._data.node_a.id:
            nodes = [self._data.node_a, self._data.node_b]
        else:
            nodes = [self._data.node_b, self._data.node_a]
        return [PathResult(nodes=nodes, edges=[self._edge], length=1)]

    # ----- 아래는 ingest 흐름 — MCP read 경로는 안 부른다. 안전한 no-op. -----

    def find_by_normalized_name(self, *, normalized, type_):
        return None

    def vector_search(self, *, embedding, top_k, type_):
        return []

    def create_entity(self, *, entity):
        return None

    def apply_merge_mutation(self, *, mutation):
        return None

    def upsert_relation(self, *, from_id, to_id, rel_type, source_ref):
        return ("rel", True)

    def find_succeeded_run_by_hash(
        self, *, source_path, source_hash, extractor_version=""
    ):
        return None

    def find_latest_succeeded_run(self, *, source_path):
        return None

    def create_ingestion_run(
        self, *, run_id, source_path, source_hash, started_at, extractor_version=""
    ):
        return None

    def mark_entity_emitted(self, *, entity_id, run_id):
        return None

    def mark_relation_emitted(self, *, relation_id, run_id):
        return None

    def finalize_run(
        self, *, run_id, status, completed_at, emitted_entity_ids, emitted_relation_ids
    ):
        return None

    def apply_entity_diff(self, *, entity_id, source_path, run_id):
        return "missing"

    def apply_relation_diff(self, *, relation_id, source_path):
        return "missing"

    def close(self) -> None:
        pass


class FakeEmbedder:
    """0 벡터 — dense path 가 빈 결과를 만든다."""

    def embed(self, texts):
        return [[0.0] * 1536 for _ in texts]


class FakeSettings:
    """e2e 테스트가 필요로 하는 두 필드만."""

    embedding_model = "fake/embedding-model"
    embedding_dimension = 1536
