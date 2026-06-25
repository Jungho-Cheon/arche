"""5 primitive + find_entities 의 통합 흐름 — Neo4j 없이 FakeGraph 위에서.

본 통합 테스트는 *FastAPI 라우터 + 응답 직렬화 + 에러 envelope* 의 contract 가
PRD 3 와 정확히 일치하는지 한 번에 검증한다. 어댑터 (Neo4jGraphRepository) 자체
검증은 `test_neo4j_repo.py` (testcontainers).

WHY tests/integration 에 둠: 단일 라우터 단위가 아닌 *여러 primitive 의 조합*
시나리오 (find_entities → get_entity → get_neighbors → get_subgraph → find_path)
가 들어가므로 단위 테스트보다 한 단계 위.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from arche_api.api.deps import (
    embedding_provider_dep,
    graph_repo_dep,
    llm_provider_dep,
)
from arche_api.domain.models import (
    Edge,
    ExtractedGraph,
    Node,
    SourceRef,
    now_rfc3339,
)
from arche_api.domain.ports import (
    EmbeddingProvider,
    EntityTypeStat,
    EntityWithCounts,
    GraphRepository,
    KeywordHit,
    LLMProvider,
    NeighborhoodResult,
    PathResult,
    RelationTypeStat,
)
from arche_api.main import create_app


def _node(node_id: str, name: str, type_: str = "coupon") -> Node:
    now = now_rfc3339()
    return Node(
        id=node_id,
        name=name,
        type=type_,
        aliases=[],
        description=None,
        properties={},
        source_refs=[SourceRef(source_path="/tmp/x.md")],
        created_at=now,
        updated_at=now,
    )


def _edge(eid: str, from_id: str, to_id: str, rel_type: str = "belongs_to") -> Edge:
    now = now_rfc3339()
    return Edge.model_validate(
        {
            "id": eid,
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
    """단순 in-memory 그래프 — 노드 + 엣지 + 사전 정의된 lexical/dense hits."""

    def __init__(self) -> None:
        # 작은 도메인: A(쿠폰) → B(프로모션) → C(카테고리)
        self.a = _node("01AAAA0000000000000000000A", "여름 환영 쿠폰", "coupon")
        self.b = _node("01BBBB0000000000000000000B", "여름 프로모션", "promotion")
        self.c = _node("01CCCC0000000000000000000C", "여름 의류", "category")
        self.e_ab = _edge("01EAB0000000000000000000AB", self.a.id, self.b.id, "belongs_to")
        self.e_bc = _edge("01EBC0000000000000000000BC", self.b.id, self.c.id, "applies_to")
        self._nodes = {n.id: n for n in [self.a, self.b, self.c]}
        self._edges = [self.e_ab, self.e_bc]

    def ensure_indexes(self) -> None: ...

    def healthcheck(self) -> bool:
        return True

    def find_by_normalized_name(self, *, normalized, type_):
        return None

    def vector_search(self, *, embedding, top_k, type_):
        return []

    def create_entity(self, *, entity): ...

    def apply_merge_mutation(self, *, mutation): ...

    def upsert_relation(self, *, from_id, to_id, rel_type, source_ref):
        return "rel", True

    def find_succeeded_run_by_hash(
        self, *, source_path, source_hash, extractor_version=""
    ):
        return None

    def find_latest_succeeded_run(self, *, source_path):
        return None

    def create_ingestion_run(
        self, *, run_id, source_path, source_hash, started_at, extractor_version=""
    ): ...

    def mark_entity_emitted(self, *, entity_id, run_id): ...

    def mark_relation_emitted(self, *, relation_id, run_id): ...

    def finalize_run(
        self,
        *,
        run_id,
        status,
        completed_at,
        emitted_entity_ids,
        emitted_relation_ids,
    ): ...

    def apply_entity_diff(self, *, entity_id, source_path, run_id):
        return "missing"

    def apply_relation_diff(self, *, relation_id, source_path):
        return "missing"

    def find_by_keywords_scored(self, *, keywords, limit_per_keyword):
        # 모든 keyword 가 A 만 surface — 단순 케이스.
        return [
            KeywordHit(node=self.a, raw_score=1.0, matched_keyword=keywords[0])
        ]

    def find_entities_dense(self, *, query_embedding, matched_keyword, limit):
        return []

    def get_schema_summary(self, *, examples_per_type=5):
        return (
            [
                EntityTypeStat(type="coupon", count=1, examples=[(self.a.id, self.a.name)]),
                EntityTypeStat(type="promotion", count=1, examples=[(self.b.id, self.b.name)]),
                EntityTypeStat(type="category", count=1, examples=[(self.c.id, self.c.name)]),
            ],
            [
                RelationTypeStat(
                    type="belongs_to",
                    count=1,
                    common_pairs=[("coupon", "promotion", 1)],
                ),
                RelationTypeStat(
                    type="applies_to",
                    count=1,
                    common_pairs=[("promotion", "category", 1)],
                ),
            ],
        )

    def get_entity_with_counts(self, *, entity_id):
        node = self._nodes.get(entity_id)
        if node is None:
            return None
        outgoing: dict[str, int] = {}
        incoming: dict[str, int] = {}
        for e in self._edges:
            if e.from_ == entity_id:
                outgoing[e.type] = outgoing.get(e.type, 0) + 1
            if e.to == entity_id:
                incoming[e.type] = incoming.get(e.type, 0) + 1
        return EntityWithCounts(node=node, outgoing=outgoing, incoming=incoming)

    def expand_neighbors(
        self, *, entry_id, relation_types, direction, hops, max_nodes
    ) -> NeighborhoodResult:
        # 단순 1-hop 확장 (direction=both): A → B, B → C.
        nodes: list[Node] = []
        edges: list[Edge] = []
        if entry_id not in self._nodes:
            return NeighborhoodResult(nodes=[], edges=[], truncated=False)
        nodes.append(self._nodes[entry_id])
        seen = {entry_id}
        frontier = [entry_id]
        for _ in range(hops):
            next_frontier: list[str] = []
            for nid in frontier:
                for e in self._edges:
                    other: str | None = None
                    if e.from_ == nid and direction in {"outgoing", "both"}:
                        other = e.to
                    elif e.to == nid and direction in {"incoming", "both"}:
                        other = e.from_
                    if other is None:
                        continue
                    if relation_types and e.type not in relation_types:
                        continue
                    if e not in edges:
                        edges.append(e)
                    if other in seen:
                        continue
                    if len(nodes) >= max_nodes:
                        return NeighborhoodResult(
                            nodes=nodes,
                            edges=[ee for ee in edges if ee.from_ in seen and ee.to in seen],
                            truncated=True,
                        )
                    nodes.append(self._nodes[other])
                    seen.add(other)
                    next_frontier.append(other)
            frontier = next_frontier
        edges = [e for e in edges if e.from_ in seen and e.to in seen]
        return NeighborhoodResult(nodes=nodes, edges=edges, truncated=False)

    def expand_subgraph(
        self, *, entry_ids, relation_types, hops, max_nodes
    ) -> NeighborhoodResult:
        nodes: dict[str, Node] = {
            i: self._nodes[i] for i in entry_ids if i in self._nodes
        }
        for entry in list(nodes.keys()):
            sub = self.expand_neighbors(
                entry_id=entry,
                relation_types=relation_types,
                direction="both",
                hops=hops,
                max_nodes=max_nodes,
            )
            for n in sub.nodes:
                nodes[n.id] = n
        edges: list[Edge] = []
        for e in self._edges:
            if e.from_ in nodes and e.to in nodes:
                if relation_types and e.type not in relation_types:
                    continue
                edges.append(e)
        return NeighborhoodResult(
            nodes=list(nodes.values()), edges=edges, truncated=False
        )

    def find_shortest_paths(
        self, *, from_id, to_id, max_hops, max_paths, relation_types
    ) -> list[PathResult]:
        # 하드코딩 — A → C 는 A→B→C (len=2). 다른 쌍은 없음.
        if from_id == self.a.id and to_id == self.c.id:
            return [
                PathResult(
                    nodes=[self.a, self.b, self.c],
                    edges=[self.e_ab, self.e_bc],
                    length=2,
                )
            ]
        return []

    def count_entities_by_namespace(self):
        return {}

    def entity_exists(self, *, entity_id) -> bool:
        return entity_id in self._nodes

    def get_stored_entity(self, *, entity_id):
        return None

    def close(self) -> None:
        pass


class _LLM(LLMProvider):
    def extract(self, *, text=None, images=None, source_path, context=None) -> ExtractedGraph:
        return ExtractedGraph(entities=[], relations=[])


class _Emb(EmbeddingProvider):
    def embed(self, texts):
        return [[0.0] * 1536 for _ in texts]


def _client() -> tuple[TestClient, FakeGraph]:
    graph = FakeGraph()
    app = create_app()
    app.state.graph_repo = graph
    app.state.llm_provider = _LLM()
    app.state.embedding_provider = _Emb()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[llm_provider_dep] = lambda: _LLM()
    app.dependency_overrides[embedding_provider_dep] = lambda: _Emb()
    return TestClient(app), graph


def test_full_primitive_chain():
    """find_entities → get_entity → get_neighbors → get_subgraph → find_path."""
    client, g = _client()
    # 1) find_entities — A 가 매치.
    r = client.post("/entities/find", json={"keywords": ["여름"]})
    assert r.status_code == 200
    matches = r.json()["data"]["matches"]
    assert matches[0]["node"]["id"] == g.a.id

    # 2) get_entity — A 의 edge counts.
    r = client.get(f"/entities/{g.a.id}")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["edge_counts"]["outgoing"] == {"belongs_to": 1}

    # 3) get_neighbors — A 의 1-hop 이웃 (B).
    r = client.post(f"/entities/{g.a.id}/neighbors", json={"hops": 1})
    assert r.status_code == 200
    data = r.json()["data"]
    assert {n["id"] for n in data["nodes"]} == {g.a.id, g.b.id}

    # 4) get_subgraph — A 와 C 진입점, 2-hop, 전체 그래프 확장.
    r = client.post(
        "/subgraph",
        json={"entry_ids": [g.a.id, g.c.id], "hops": 2},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["entry_ids"] == [g.a.id, g.c.id]
    assert {n["id"] for n in data["nodes"]} == {g.a.id, g.b.id, g.c.id}

    # 5) find_path — A → C.
    r = client.post(
        "/paths/find", json={"from_id": g.a.id, "to_id": g.c.id}
    )
    assert r.status_code == 200
    path = r.json()["data"]["paths"][0]
    assert path["length"] == 2
    assert path["nodes"][0]["id"] == g.a.id
    assert path["nodes"][-1]["id"] == g.c.id


def test_get_schema_chain():
    client, _ = _client()
    r = client.get("/schema")
    assert r.status_code == 200
    data = r.json()["data"]
    types = {t["type"] for t in data["entity_types"]}
    assert {"coupon", "promotion", "category"}.issubset(types)


def test_openapi_six_primitives_present():
    client, _ = _client()
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/schema",
        "/entities/find",
        "/entities/{entity_id}",
        "/entities/{entity_id}/neighbors",
        "/paths/find",
        "/subgraph",
    }.issubset(set(paths.keys()))


def test_error_envelope_for_unknown_entity():
    client, _ = _client()
    r = client.get("/entities/01UNKNOWN0000000000000000A")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "entity_not_found"
    assert "id" in body["error"]["details"]
