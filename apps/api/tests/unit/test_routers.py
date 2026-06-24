"""FastAPI 라우터 응답 envelope + Node 스키마 형태."""

from __future__ import annotations

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
from opentology_api.domain.models import (
    ExtractedGraph,
    Node,
    SourceRef,
    StoredEntity,
    now_rfc3339,
)
from opentology_api.main import create_app


class StubGraph(GraphRepository):
    """find_by_keywords_scored 가 KeywordHit 리스트를 반환하도록 stub.

    `hits_by_keyword` 가 비어있으면 모든 keyword 가 보유한 노드 전부를 같은
    raw 점수로 surface 시킨다 (기존 단순 테스트 케이스 호환). 지정되어 있으면
    keyword 별 맞춤 hit 리스트 사용 (matched_keyword 검증용).
    """

    def __init__(
        self,
        nodes: list[Node] | None = None,
        healthy: bool = True,
        hits_by_keyword: dict[str, list[tuple[Node, float]]] | None = None,
    ) -> None:
        self._nodes = nodes or []
        self._healthy = healthy
        self._hits_by_keyword = hits_by_keyword

    def ensure_indexes(self) -> None:
        pass

    def healthcheck(self) -> bool:
        return self._healthy

    def find_by_normalized_name(self, *, normalized, type_):  # noqa: D401
        return None

    def vector_search(self, *, embedding, top_k, type_):  # noqa: D401
        return []

    def create_entity(self, *, entity):  # noqa: D401
        return None

    def apply_merge_mutation(self, *, mutation):  # noqa: D401
        return None

    def upsert_relation(self, *, from_id, to_id, rel_type, source_ref):  # noqa: D401
        return "rel", True

    def find_succeeded_run_by_hash(
        self, *, source_path, source_hash, extractor_version=""
    ):  # noqa: D401
        return None

    def find_latest_succeeded_run(self, *, source_path):  # noqa: D401
        return None

    def create_ingestion_run(
        self, *, run_id, source_path, source_hash, started_at, extractor_version=""
    ):  # noqa: D401
        return None

    def mark_entity_emitted(self, *, entity_id, run_id):  # noqa: D401
        return None

    def mark_relation_emitted(self, *, relation_id, run_id):  # noqa: D401
        return None

    def finalize_run(
        self,
        *,
        run_id,
        status,
        completed_at,
        emitted_entity_ids,
        emitted_relation_ids,
    ):  # noqa: D401
        return None

    def apply_entity_diff(self, *, entity_id, source_path, run_id):  # noqa: D401
        return "missing"

    def apply_relation_diff(self, *, relation_id, source_path):  # noqa: D401
        return "missing"

    def find_by_keywords_scored(  # noqa: D401
        self, *, keywords, limit_per_keyword
    ) -> list[KeywordHit]:
        hits: list[KeywordHit] = []
        if self._hits_by_keyword is not None:
            for kw in keywords:
                for n, score in self._hits_by_keyword.get(kw, [])[
                    :limit_per_keyword
                ]:
                    hits.append(
                        KeywordHit(node=n, raw_score=score, matched_keyword=kw)
                    )
            return hits
        # 기본: 보유 노드를 첫 keyword 로 surface (테스트 호환).
        for n in list(self._nodes)[:limit_per_keyword]:
            hits.append(
                KeywordHit(node=n, raw_score=1.0, matched_keyword=keywords[0])
            )
        return hits

    def find_entities_dense(  # noqa: D401
        self, *, query_embedding, matched_keyword, limit
    ) -> list[DenseHit]:
        # 본 stub 은 dense 신호 미공급. 라우터의 RRF 결합은 lexical-only 입력
        # 으로도 동작해야 한다.
        return []

    def get_schema_summary(self, *, examples_per_type=5):  # noqa: D401
        return ([], [])

    def get_entity_with_counts(self, *, entity_id):  # noqa: D401
        for n in self._nodes:
            if n.id == entity_id:
                return EntityWithCounts(node=n, outgoing={}, incoming={})
        return None

    def expand_neighbors(  # noqa: D401
        self,
        *,
        entry_id,
        relation_types,
        direction,
        hops,
        max_nodes,
    ) -> NeighborhoodResult:
        for n in self._nodes:
            if n.id == entry_id:
                return NeighborhoodResult(nodes=[n], edges=[], truncated=False)
        return NeighborhoodResult(nodes=[], edges=[], truncated=False)

    def expand_subgraph(  # noqa: D401
        self,
        *,
        entry_ids,
        relation_types,
        hops,
        max_nodes,
    ) -> NeighborhoodResult:
        kept = [n for n in self._nodes if n.id in set(entry_ids)]
        return NeighborhoodResult(nodes=kept, edges=[], truncated=False)

    def find_shortest_paths(  # noqa: D401
        self,
        *,
        from_id,
        to_id,
        max_hops,
        max_paths,
        relation_types,
    ) -> list[PathResult]:
        return []

    def count_entities_by_namespace(self):
        return {}

    def entity_exists(self, *, entity_id) -> bool:  # noqa: D401
        return any(n.id == entity_id for n in self._nodes)

    def get_stored_entity(self, *, entity_id):
        return None

    def close(self) -> None:
        pass


class StubLLM(LLMProvider):
    def extract(self, *, text=None, images=None, source_path, context=None) -> ExtractedGraph:
        return ExtractedGraph(entities=[], relations=[])


class StubEmbedder(EmbeddingProvider):
    def embed(self, texts):
        return [[0.0] * 3 for _ in texts]


def _make_node(
    name: str = "여름 쿠폰",
    node_id: str = "01HZX0G7M8N0RT0V0EXAMPLE00",
    type_: str = "coupon",
) -> Node:
    now = now_rfc3339()
    return Node(
        id=node_id,
        name=name,
        type=type_,
        aliases=["여름 환영 쿠폰"],
        description=None,
        properties={},
        source_refs=[SourceRef(source_path="/tmp/sample.md")],
        created_at=now,
        updated_at=now,
    )


def _client_with(graph: StubGraph) -> TestClient:
    app = create_app()
    app.state.graph_repo = graph
    app.state.llm_provider = StubLLM()
    app.state.embedding_provider = StubEmbedder()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[llm_provider_dep] = lambda: StubLLM()
    app.dependency_overrides[embedding_provider_dep] = lambda: StubEmbedder()
    return TestClient(app)


def test_healthz_returns_neo4j_state_ok():
    client = _client_with(StubGraph(healthy=True))
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "neo4j": "ok"}


def test_healthz_returns_neo4j_state_down():
    client = _client_with(StubGraph(healthy=False))
    r = client.get("/healthz")
    assert r.json()["neo4j"] == "down"


def test_find_entities_envelope_and_match_shape():
    """PRD 3 §0.3 envelope + §3.4 matches[].node/score/matched_keyword."""
    n = _make_node()
    client = _client_with(StubGraph(nodes=[n]))
    r = client.post("/entities/find", json={"keywords": ["여름"]})
    assert r.status_code == 200
    body = r.json()
    # PRD 3 §0.3 envelope
    assert set(body.keys()) == {"data"}
    assert set(body["data"].keys()) == {"matches"}
    assert len(body["data"]["matches"]) == 1
    match = body["data"]["matches"][0]
    # PRD 3 §3.4 매치 필드 (include_scores 기본 false 라 scores 없음)
    assert set(match.keys()) == {"node", "score", "matched_keyword"}
    assert match["matched_keyword"] == "여름"
    # max-normalize → 단일 매치는 1.0.
    assert match["score"] == 1.0
    node = match["node"]
    # PRD 3 §1.1: embedding 노출 금지
    assert "embedding" not in node
    for key in [
        "id",
        "name",
        "type",
        "aliases",
        "source_refs",
        "created_at",
        "updated_at",
    ]:
        assert key in node


def test_find_entities_include_scores_exposes_raw_lexical():
    n = _make_node()
    client = _client_with(StubGraph(nodes=[n]))
    r = client.post(
        "/entities/find",
        json={"keywords": ["여름"], "include_scores": True},
    )
    assert r.status_code == 200
    match = r.json()["data"]["matches"][0]
    assert "scores" in match
    assert "lexical" in match["scores"]
    assert "dense" in match["scores"]
    # stub 의 raw_score 1.0 이 lexical 로 노출.
    assert match["scores"]["lexical"] == 1.0
    # walking skeleton — dense 는 stub.
    assert match["scores"]["dense"] == 0.0


def test_find_entities_matched_keyword_picks_highest_score_keyword():
    """PRD 3 §3.5: 같은 노드가 여러 keyword 에서 surface 됐다면 가장 높은
    raw 점수의 keyword 가 matched_keyword 로 유지된다."""
    n = _make_node()
    hits_by_keyword = {
        "여름": [(n, 0.4)],
        "쿠폰": [(n, 0.9)],
    }
    client = _client_with(
        StubGraph(nodes=[n], hits_by_keyword=hits_by_keyword)
    )
    r = client.post(
        "/entities/find", json={"keywords": ["여름", "쿠폰"]}
    )
    assert r.status_code == 200
    match = r.json()["data"]["matches"][0]
    assert match["matched_keyword"] == "쿠폰"


def test_find_entities_types_filter():
    """PRD 3 §3.3: types 필터는 결과 노드의 type 이 리스트에 포함된 것만 남긴다."""
    coupon = _make_node(node_id="01HZX0G7M8N0RT0V0COUPON000", type_="coupon")
    product = _make_node(
        name="린넨 셔츠",
        node_id="01HZX0G7M8N0RT0V0PRODUCT00",
        type_="product",
    )
    hits_by_keyword = {
        "여름": [(coupon, 0.8), (product, 0.7)],
    }
    client = _client_with(
        StubGraph(nodes=[coupon, product], hits_by_keyword=hits_by_keyword)
    )
    r = client.post(
        "/entities/find",
        json={"keywords": ["여름"], "types": ["product"]},
    )
    assert r.status_code == 200
    matches = r.json()["data"]["matches"]
    assert len(matches) == 1
    assert matches[0]["node"]["type"] == "product"


def test_find_entities_limit_slices_result():
    """PRD 3 §3.3: limit 적용 (기본 10, max 50)."""
    # WHY ID 패턴 ^[0-9A-Z]{26}$ : 26 자 정확히. f-string 으로 3-digit suffix
    # + 23-char prefix 로 길이 보장.
    nodes = [
        _make_node(name=f"N{i}", node_id=f"01HZX0G7M8N0RT0V0LIMITX{i:03d}")
        for i in range(5)
    ]
    hits_by_keyword = {"여름": [(n, 1.0 - i * 0.1) for i, n in enumerate(nodes)]}
    client = _client_with(
        StubGraph(nodes=nodes, hits_by_keyword=hits_by_keyword)
    )
    r = client.post(
        "/entities/find", json={"keywords": ["여름"], "limit": 2}
    )
    assert r.status_code == 200
    assert len(r.json()["data"]["matches"]) == 2


def test_find_entities_rejects_empty_keywords():
    client = _client_with(StubGraph())
    r = client.post("/entities/find", json={"keywords": []})
    assert r.status_code == 422  # pydantic validation


def test_find_entities_rejects_limit_over_max():
    client = _client_with(StubGraph())
    r = client.post(
        "/entities/find", json={"keywords": ["x"], "limit": 999}
    )
    assert r.status_code == 422


# ---------- get_neighbors body id 정책 (이슈 #27 회귀 1) ----------


def test_get_neighbors_accepts_body_without_id():
    """기본 — body 에 id 없이 path 만으로 호출. 200."""
    node = _make_node(node_id="01HZX0G7M8N0RT0V0COUPON000")
    client = _client_with(StubGraph(nodes=[node]))
    r = client.post(
        "/entities/01HZX0G7M8N0RT0V0COUPON000/neighbors",
        json={"hops": 1},
    )
    assert r.status_code == 200


def test_get_neighbors_accepts_matching_body_id():
    """REST + MCP 1:1 매핑 — body 의 id 가 path 와 일치하면 허용 (PRD 3 §0.1)."""
    node = _make_node(node_id="01HZX0G7M8N0RT0V0COUPON000")
    client = _client_with(StubGraph(nodes=[node]))
    r = client.post(
        "/entities/01HZX0G7M8N0RT0V0COUPON000/neighbors",
        json={"id": "01HZX0G7M8N0RT0V0COUPON000", "hops": 1},
    )
    assert r.status_code == 200, r.text


def test_get_neighbors_rejects_mismatched_body_id():
    """path 와 body 의 id 가 다르면 invalid_input 400 envelope."""
    node = _make_node(node_id="01HZX0G7M8N0RT0V0COUPON000")
    client = _client_with(StubGraph(nodes=[node]))
    r = client.post(
        "/entities/01HZX0G7M8N0RT0V0COUPON000/neighbors",
        json={"id": "01HZX0G7M8N0RT0V0PRODUCT00", "hops": 1},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "invalid_input"
    assert body["error"]["details"]["path_entity_id"] == "01HZX0G7M8N0RT0V0COUPON000"
    assert body["error"]["details"]["body_id"] == "01HZX0G7M8N0RT0V0PRODUCT00"


def test_get_neighbors_rejects_unknown_extra_field():
    """extra='forbid' 는 그대로 — id 외의 추가 키는 여전히 422 로 거부."""
    node = _make_node(node_id="01HZX0G7M8N0RT0V0COUPON000")
    client = _client_with(StubGraph(nodes=[node]))
    r = client.post(
        "/entities/01HZX0G7M8N0RT0V0COUPON000/neighbors",
        json={"id": "01HZX0G7M8N0RT0V0COUPON000", "bogus": 1},
    )
    assert r.status_code == 422
