"""5 primitive 라우터 + RRF + 에러 envelope — PRD 3 §2-7, §9.

본 파일은 *단위 테스트* — 실제 Neo4j 없이 GraphRepository stub 으로 라우터의
계약 (응답 형태 / 에러 envelope / 절단 동작 / OpenAPI 노출) 만 검증한다. 그래프
DB 의 실제 BFS / k-shortest paths 동작은 integration / live 테스트에서.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from opentology_api.adapters.embedding import EmbeddingProvider
from opentology_api.adapters.graph import (
    DenseHit,
    EntityTypeStat,
    EntityWithCounts,
    GraphRepository,
    KeywordHit,
    NeighborhoodResult,
    PathResult,
    RelationTypeStat,
)
from opentology_api.adapters.llm import LLMProvider
from opentology_api.api.deps import (
    embedding_provider_dep,
    graph_repo_dep,
    llm_provider_dep,
)
from opentology_api.api.services import _fuse_with_rrf
from opentology_api.domain.models import (
    Edge,
    ExtractedGraph,
    Node,
    SourceRef,
    now_rfc3339,
)
from opentology_api.main import create_app


# ---------- 공통 stub ----------


def _make_node(
    *,
    name: str = "여름 쿠폰",
    node_id: str = "01HZX0G7M8N0RT0V0EXAMPLE00",
    type_: str = "coupon",
) -> Node:
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


def _make_edge(
    *,
    edge_id: str,
    from_id: str,
    to_id: str,
    rel_type: str = "belongs_to",
) -> Edge:
    now = now_rfc3339()
    return Edge.model_validate(
        {
            "id": edge_id,
            "from": from_id,
            "to": to_id,
            "type": rel_type,
            "properties": {},
            "source_refs": [],
            "created_at": now,
            "updated_at": now,
        }
    )


class PrimitiveStubGraph(GraphRepository):
    """5 primitive 응답을 결정적으로 만드는 stub.

    각 메서드에 *고정 결과* 를 주입하는 식으로 라우터 동작만 검증.
    """

    def __init__(
        self,
        *,
        nodes: list[Node] | None = None,
        edges: list[Edge] | None = None,
        entity_type_stats: list[EntityTypeStat] | None = None,
        relation_type_stats: list[RelationTypeStat] | None = None,
        paths_result: list[PathResult] | None = None,
        neighbors_result: NeighborhoodResult | None = None,
        subgraph_result: NeighborhoodResult | None = None,
        edge_counts: dict[str, dict[str, dict[str, int]]] | None = None,
    ) -> None:
        self._nodes_by_id = {n.id: n for n in (nodes or [])}
        self._edges = edges or []
        self._entity_type_stats = entity_type_stats or []
        self._relation_type_stats = relation_type_stats or []
        self._paths_result = paths_result or []
        self._neighbors_result = neighbors_result
        self._subgraph_result = subgraph_result
        self._edge_counts = edge_counts or {}

    def ensure_indexes(self) -> None:
        pass

    def healthcheck(self) -> bool:
        return True

    def find_by_normalized_name(self, *, normalized, type_):  # noqa: D401
        return None

    def vector_search(self, *, embedding, top_k, type_):  # noqa: D401
        return []

    def create_entity(self, *, entity):  # noqa: D401
        return None

    def apply_merge_mutation(self, *, mutation):  # noqa: D401
        return None

    def upsert_relation(self, *, from_id, to_id, rel_type, source_ref):
        return "rel", True

    def find_succeeded_run_by_hash(self, *, source_path, source_hash):
        return None

    def find_latest_succeeded_run(self, *, source_path):
        return None

    def create_ingestion_run(self, *, run_id, source_path, source_hash, started_at):
        return None

    def mark_entity_emitted(self, *, entity_id, run_id):
        return None

    def mark_relation_emitted(self, *, relation_id, run_id):
        return None

    def finalize_run(
        self,
        *,
        run_id,
        status,
        completed_at,
        emitted_entity_ids,
        emitted_relation_ids,
    ):
        return None

    def apply_entity_diff(self, *, entity_id, source_path, run_id):
        return "missing"

    def apply_relation_diff(self, *, relation_id, source_path):
        return "missing"

    def find_by_keywords_scored(self, *, keywords, limit_per_keyword):
        return []

    def find_entities_dense(self, *, query_embedding, matched_keyword, limit):
        return []

    def get_schema_summary(self, *, examples_per_type=5):
        return (self._entity_type_stats, self._relation_type_stats)

    def get_entity_with_counts(self, *, entity_id):
        node = self._nodes_by_id.get(entity_id)
        if node is None:
            return None
        counts = self._edge_counts.get(entity_id, {})
        return EntityWithCounts(
            node=node,
            outgoing=counts.get("outgoing", {}),
            incoming=counts.get("incoming", {}),
        )

    def expand_neighbors(
        self, *, entry_id, relation_types, direction, hops, max_nodes
    ) -> NeighborhoodResult:
        if self._neighbors_result is not None:
            return self._neighbors_result
        return NeighborhoodResult(nodes=[], edges=[], truncated=False)

    def expand_subgraph(
        self, *, entry_ids, relation_types, hops, max_nodes
    ) -> NeighborhoodResult:
        if self._subgraph_result is not None:
            return self._subgraph_result
        kept = [self._nodes_by_id[i] for i in entry_ids if i in self._nodes_by_id]
        return NeighborhoodResult(nodes=kept, edges=[], truncated=False)

    def find_shortest_paths(
        self, *, from_id, to_id, max_hops, max_paths, relation_types
    ) -> list[PathResult]:
        return self._paths_result

    def entity_exists(self, *, entity_id) -> bool:
        return entity_id in self._nodes_by_id

    def get_stored_entity(self, *, entity_id):
        return None

    def close(self) -> None:
        pass


class _StubLLM(LLMProvider):
    def extract(self, *, text=None, images=None, source_path, context=None) -> ExtractedGraph:
        return ExtractedGraph(entities=[], relations=[])


class _StubEmbedder(EmbeddingProvider):
    """텍스트 길이에 맞춰 1536-dim zero 벡터 — dense path 가 빈 결과 반환하게."""

    def embed(self, texts):
        return [[0.0] * 1536 for _ in texts]


def _client_with(graph: GraphRepository) -> TestClient:
    app = create_app()
    app.state.graph_repo = graph
    app.state.llm_provider = _StubLLM()
    app.state.embedding_provider = _StubEmbedder()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[llm_provider_dep] = lambda: _StubLLM()
    app.dependency_overrides[embedding_provider_dep] = lambda: _StubEmbedder()
    return TestClient(app)


# ---------- RRF (find_entities) ----------


def test_rrf_single_keyword_lexical_only_normalized_score_one():
    """단일 keyword + lexical-only 1 hit → score 1.0 (max-normalize)."""
    n = _make_node()
    hits = [KeywordHit(node=n, raw_score=0.42, matched_keyword="여름")]
    matches = _fuse_with_rrf(
        lexical_hits=hits,
        dense_hits=[],
        keywords=["여름"],
        types=None,
        limit=10,
        include_scores=False,
    )
    assert len(matches) == 1
    assert matches[0].score == 1.0
    assert matches[0].matched_keyword == "여름"


def test_rrf_lexical_and_dense_both_contribute():
    """동일 노드가 lexical + dense 양쪽에서 surface 되면 contrib 합산."""
    n = _make_node()
    lex = [KeywordHit(node=n, raw_score=0.5, matched_keyword="x")]
    dense = [DenseHit(node=n, raw_score=0.9, matched_keyword="x")]
    matches = _fuse_with_rrf(
        lexical_hits=lex,
        dense_hits=dense,
        keywords=["x"],
        types=None,
        limit=10,
        include_scores=True,
    )
    assert len(matches) == 1
    # 양쪽 rank 1 → 2 / (60 + 1) → 0.0327. max-normalize → 1.0.
    assert matches[0].score == 1.0
    assert matches[0].scores is not None
    assert matches[0].scores.lexical == 0.5
    assert matches[0].scores.dense == 0.9


def test_rrf_orders_by_rank_not_raw_score_magnitude():
    """RRF 의 핵심: 결합 점수는 *각 신호의 rank* 만 의존.

    A — lexical rank 1 (raw 0.01) 만. contrib = 1/(60+1) = 0.01639.
    B — dense rank 5 (raw 0.99) 만. contrib = 1/(60+5) = 0.01538.

    raw 값은 A 가 훨씬 작지만 rank 가 더 앞이라 fused score 는 A 가 더 높다.
    """
    a = _make_node(node_id="01AAA0G7M8N0RT0V0EXAMPLE00")
    b = _make_node(node_id="01BBB0G7M8N0RT0V0EXAMPLE00", name="b")
    lex = [KeywordHit(node=a, raw_score=0.01, matched_keyword="x")]
    # B 를 dense rank 5 로 만들려면 더 높은 4 개를 함께 보내야 한다. 그 4 개는
    # *별도 노드* 라 fused 결과에도 들어오지만, 우리는 *A 의 상대 위치* 만
    # 확인한다 — A 가 B 보다 앞.
    pads = [
        _make_node(node_id=f"01PAD{i:021d}", name=f"pad{i}")
        for i in range(4)
    ]
    dense = [
        DenseHit(node=p, raw_score=0.99 - i * 0.01, matched_keyword="x")
        for i, p in enumerate(pads)
    ]
    dense.append(DenseHit(node=b, raw_score=0.99, matched_keyword="x"))
    matches = _fuse_with_rrf(
        lexical_hits=lex,
        dense_hits=dense,
        keywords=["x"],
        types=None,
        limit=10,
        include_scores=False,
    )
    by_id = {m.node.id: i for i, m in enumerate(matches)}
    assert by_id[a.id] < by_id[b.id]


def test_rrf_types_filter():
    coupon = _make_node(node_id="01CCC0G7M8N0RT0V0EXAMPLE00", type_="coupon")
    product = _make_node(node_id="01PPP0G7M8N0RT0V0EXAMPLE00", type_="product")
    lex = [
        KeywordHit(node=coupon, raw_score=1.0, matched_keyword="x"),
        KeywordHit(node=product, raw_score=0.9, matched_keyword="x"),
    ]
    matches = _fuse_with_rrf(
        lexical_hits=lex,
        dense_hits=[],
        keywords=["x"],
        types=["product"],
        limit=10,
        include_scores=False,
    )
    assert len(matches) == 1
    assert matches[0].node.type == "product"


# ---------- get_schema ----------


def test_get_schema_returns_entity_and_relation_stats_with_embedding_info():
    """PRD 3 §2.3 응답 형태 + embedding_info 노출."""
    graph = PrimitiveStubGraph(
        entity_type_stats=[
            EntityTypeStat(
                type="coupon",
                count=2,
                examples=[("01EXAMPLE0000000000000COUP", "여름 쿠폰")],
            )
        ],
        relation_type_stats=[
            RelationTypeStat(
                type="belongs_to",
                count=3,
                common_pairs=[("coupon", "promotion", 2)],
            )
        ],
    )
    client = _client_with(graph)
    r = client.get("/schema")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"data"}
    data = body["data"]
    assert set(data.keys()) == {"entity_types", "relation_types", "embedding_info"}
    assert data["entity_types"][0]["type"] == "coupon"
    assert data["entity_types"][0]["examples"][0]["name"] == "여름 쿠폰"
    assert data["relation_types"][0]["common_pairs"][0]["from_type"] == "coupon"
    # embedding_info — model + dimension 노출.
    assert "model" in data["embedding_info"]
    assert data["embedding_info"]["dimension"] >= 1


# ---------- get_entity ----------


def test_get_entity_returns_node_with_edge_counts():
    n = _make_node()
    graph = PrimitiveStubGraph(
        nodes=[n],
        edge_counts={
            n.id: {"outgoing": {"belongs_to": 2}, "incoming": {"contains": 1}}
        },
    )
    client = _client_with(graph)
    r = client.get(f"/entities/{n.id}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["node"]["id"] == n.id
    assert data["edge_counts"]["outgoing"] == {"belongs_to": 2}
    assert data["edge_counts"]["incoming"] == {"contains": 1}
    # PRD 3 §1.1: embedding 노출 금지.
    assert "embedding" not in data["node"]


def test_get_entity_missing_returns_entity_not_found_404_envelope():
    """PRD 3 §9: entity_not_found 404 + envelope `error.code`."""
    graph = PrimitiveStubGraph(nodes=[])
    client = _client_with(graph)
    r = client.get("/entities/01MISSING0000000000000000A")
    assert r.status_code == 404
    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == "entity_not_found"
    assert body["error"]["details"]["id"] == "01MISSING0000000000000000A"


# ---------- get_neighbors ----------


def test_get_neighbors_returns_nodes_edges_truncated():
    entry = _make_node(node_id="01ENTRY0G7M8N0RT0V0EXAMPLE")
    neighbor = _make_node(node_id="01NEIGH0G7M8N0RT0V0EXAMPLE", name="이웃")
    edge = _make_edge(
        edge_id="01EDGE00G7M8N0RT0V0EXAMPLE",
        from_id=entry.id,
        to_id=neighbor.id,
    )
    graph = PrimitiveStubGraph(
        nodes=[entry, neighbor],
        neighbors_result=NeighborhoodResult(
            nodes=[entry, neighbor], edges=[edge], truncated=False
        ),
    )
    client = _client_with(graph)
    r = client.post(
        f"/entities/{entry.id}/neighbors", json={"hops": 1, "max_nodes": 10}
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert {n["id"] for n in data["nodes"]} == {entry.id, neighbor.id}
    assert data["truncated"] is False
    # PRD 3 §5.4 — 진입점도 응답 nodes 에 포함.
    assert entry.id in {n["id"] for n in data["nodes"]}


def test_get_neighbors_unknown_entry_returns_404():
    graph = PrimitiveStubGraph(nodes=[])
    client = _client_with(graph)
    r = client.post(
        "/entities/01MISSING0000000000000000A/neighbors",
        json={"hops": 1},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "entity_not_found"


def test_get_neighbors_truncated_flag_propagates():
    entry = _make_node(node_id="01ENTRY0G7M8N0RT0V0EXAMPLE")
    graph = PrimitiveStubGraph(
        nodes=[entry],
        neighbors_result=NeighborhoodResult(
            nodes=[entry], edges=[], truncated=True
        ),
    )
    client = _client_with(graph)
    r = client.post(f"/entities/{entry.id}/neighbors", json={"max_nodes": 1})
    assert r.status_code == 200
    assert r.json()["data"]["truncated"] is True


# ---------- find_path ----------


def test_find_path_from_equals_to_returns_unprocessable_422():
    """PRD 3 §9: from == to → unprocessable 422."""
    n = _make_node()
    graph = PrimitiveStubGraph(nodes=[n])
    client = _client_with(graph)
    r = client.post(
        "/paths/find",
        json={"from_id": n.id, "to_id": n.id},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unprocessable"


def test_find_path_no_route_returns_200_empty_paths():
    """PRD 3 §6.4 — 경로 없으면 paths=[] (에러 아님)."""
    a = _make_node(node_id="01AAA0G7M8N0RT0V0EXAMPLE00")
    b = _make_node(node_id="01BBB0G7M8N0RT0V0EXAMPLE00")
    graph = PrimitiveStubGraph(nodes=[a, b], paths_result=[])
    client = _client_with(graph)
    r = client.post(
        "/paths/find", json={"from_id": a.id, "to_id": b.id}
    )
    assert r.status_code == 200
    assert r.json()["data"]["paths"] == []


def test_find_path_returns_paths_with_length_and_alignment():
    a = _make_node(node_id="01AAA0G7M8N0RT0V0EXAMPLE00")
    mid = _make_node(node_id="01MID0G7M8N0RT0V0EXAMPLE00", name="mid")
    b = _make_node(node_id="01BBB0G7M8N0RT0V0EXAMPLE00")
    e1 = _make_edge(edge_id="01E1000000000000000000EDGE", from_id=a.id, to_id=mid.id)
    e2 = _make_edge(edge_id="01E2000000000000000000EDGE", from_id=mid.id, to_id=b.id)
    graph = PrimitiveStubGraph(
        nodes=[a, mid, b],
        paths_result=[PathResult(nodes=[a, mid, b], edges=[e1, e2], length=2)],
    )
    client = _client_with(graph)
    r = client.post(
        "/paths/find",
        json={"from_id": a.id, "to_id": b.id},
    )
    assert r.status_code == 200
    path = r.json()["data"]["paths"][0]
    # PRD 3 §6.4 — edges[i] 는 nodes[i] → nodes[i+1].
    assert path["nodes"][0]["id"] == a.id
    assert path["nodes"][-1]["id"] == b.id
    assert path["length"] == 2
    assert path["edges"][0]["from"] == a.id
    assert path["edges"][0]["to"] == mid.id


def test_find_path_unknown_endpoint_returns_404():
    a = _make_node(node_id="01AAA0G7M8N0RT0V0EXAMPLE00")
    graph = PrimitiveStubGraph(nodes=[a])
    client = _client_with(graph)
    r = client.post(
        "/paths/find",
        json={"from_id": a.id, "to_id": "01MISSING0000000000000000A"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "entity_not_found"


# ---------- get_subgraph ----------


def test_get_subgraph_echoes_entry_ids_and_returns_truncated_flag():
    a = _make_node(node_id="01AAA0G7M8N0RT0V0EXAMPLE00")
    b = _make_node(node_id="01BBB0G7M8N0RT0V0EXAMPLE00")
    graph = PrimitiveStubGraph(
        nodes=[a, b],
        subgraph_result=NeighborhoodResult(nodes=[a, b], edges=[], truncated=True),
    )
    client = _client_with(graph)
    r = client.post(
        "/subgraph",
        json={"entry_ids": [a.id, b.id], "hops": 1, "max_nodes": 1},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["entry_ids"] == [a.id, b.id]
    assert data["truncated"] is True


# ---------- OpenAPI ----------


def test_openapi_lists_all_six_primitive_endpoints():
    """OpenAPI 스키마에 6 primitive 경로 모두 등록."""
    graph = PrimitiveStubGraph()
    client = _client_with(graph)
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/schema" in paths and "get" in paths["/schema"]
    assert "/entities/find" in paths and "post" in paths["/entities/find"]
    assert "/entities/{entity_id}" in paths and "get" in paths["/entities/{entity_id}"]
    assert (
        "/entities/{entity_id}/neighbors" in paths
        and "post" in paths["/entities/{entity_id}/neighbors"]
    )
    assert "/paths/find" in paths and "post" in paths["/paths/find"]
    assert "/subgraph" in paths and "post" in paths["/subgraph"]


# ---------- ID 형식 검증 ----------


def test_find_path_rejects_non_ulid_input():
    """PRD 3 §0.5 — ID 는 ULID 형식. 위반은 422 (pydantic validation)."""
    graph = PrimitiveStubGraph()
    client = _client_with(graph)
    r = client.post(
        "/paths/find",
        json={"from_id": "not-a-ulid", "to_id": "01AAA0G7M8N0RT0V0EXAMPLE00"},
    )
    assert r.status_code == 422


def test_get_subgraph_rejects_non_ulid_entry():
    graph = PrimitiveStubGraph()
    client = _client_with(graph)
    r = client.post("/subgraph", json={"entry_ids": ["bad-id"]})
    assert r.status_code == 422
