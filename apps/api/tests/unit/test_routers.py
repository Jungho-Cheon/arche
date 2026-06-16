"""FastAPI 라우터 응답 envelope + Node 스키마 형태."""

from __future__ import annotations

from fastapi.testclient import TestClient

from opentology_api.adapters.embedding import EmbeddingProvider
from opentology_api.adapters.graph import GraphRepository
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
    def __init__(self, nodes: list[Node] | None = None, healthy: bool = True) -> None:
        self._nodes = nodes or []
        self._healthy = healthy

    def ensure_indexes(self) -> None:
        pass

    def healthcheck(self) -> bool:
        return self._healthy

    def upsert_entity(self, *, entity: StoredEntity):  # noqa: D401
        return entity.id, True

    def upsert_relation(self, *, from_id, to_id, rel_type, source_ref):  # noqa: D401
        return "rel", True

    def find_by_name_exact(self, *, name):  # noqa: D401
        return None

    def find_by_keywords(self, *, keywords, limit) -> list[Node]:  # noqa: D401
        return list(self._nodes)[:limit]

    def find_entities_dense(self, *, keywords, limit):
        raise NotImplementedError

    def close(self) -> None:
        pass


class StubLLM(LLMProvider):
    def extract(self, text, source_path) -> ExtractedGraph:
        return ExtractedGraph(entities=[], relations=[])


class StubEmbedder(EmbeddingProvider):
    def embed(self, texts):
        return [[0.0] * 3 for _ in texts]


def _make_node(name: str = "여름 쿠폰") -> Node:
    now = now_rfc3339()
    return Node(
        id="01HZX0G7M8N0RT0V0EXAMPLE00",
        name=name,
        type="coupon",
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


def test_find_entities_envelope_and_node_shape():
    n = _make_node()
    client = _client_with(StubGraph(nodes=[n]))
    r = client.post("/entities/find", json={"keywords": ["여름"]})
    assert r.status_code == 200
    body = r.json()
    # PRD 3 §0.3 envelope
    assert set(body.keys()) == {"data"}
    assert set(body["data"].keys()) == {"entities"}
    assert len(body["data"]["entities"]) == 1
    node = body["data"]["entities"][0]
    # PRD 3 §1.1: embedding 노출 금지
    assert "embedding" not in node
    # 필수 필드
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


def test_find_entities_rejects_empty_keywords():
    client = _client_with(StubGraph())
    r = client.post("/entities/find", json={"keywords": []})
    assert r.status_code == 422  # pydantic validation
