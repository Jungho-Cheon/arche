"""Cypher 인젝션 심층 방어 회귀 (#142).

Cypher 를 구성하는 모든 경로는 파라미터 바인딩(`$param`)만 쓰므로 사용자 입력을
질의 문자열에 이어 붙이는 인젝션은 구조적으로 불가능하다(`adapters/graph.py`
감사). 본 테스트는 그 위의 심층 방어를 잠근다.

1. 형식 검증 — 신뢰 불가 입력(namespace_id / relation_types / 엔티티 id)이 비정상
   형태일 때 질의에 닿기 전에 걸러진다. body(422) / 헤더, 쿼리, MCP 인자(400) 양쪽.
2. 파라미터 바인딩의 무해화 — 질의 탈출을 노린 문자열이 형식 관문을 통과하더라도
   *데이터* 로만 취급된다(그래프가 그 값을 파라미터로 그대로 받는다).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from arche_api.api.deps import (
    embedding_provider_dep,
    graph_repo_dep,
    llm_provider_dep,
)
from arche_api.api.security import (
    ensure_entity_id,
    ensure_namespace_id,
    validate_namespace_id,
    validate_relation_types,
)
from arche_api.domain.errors import InvalidInputError
from arche_api.domain.ports import NeighborhoodResult
from arche_api.main import create_app
from arche_api.mcp_server import _dispatch_tool

from .test_primitives import (
    PrimitiveStubGraph,
    _make_node,
    _StubEmbedder,
    _StubLLM,
)

_ENT_A = "01HZX0G7M8N0RT0V0EXAMPLE01"
_ENT_B = "01HZX0G7M8N0RT0V0EXAMPLE02"

# 질의 탈출을 노린 전형적 페이로드 — 파라미터 바인딩이라 이들도 실행되지 않는다.
_INJECTION_STRINGS = [
    'default" DETACH DELETE (n) //',
    "default'}) MATCH (x) DETACH DELETE x //",
    "ns` RETURN 1 //",
    "a b",  # 공백 — 식별자에 등장하면 안 됨
]


# ---------- 순수 검증기 ----------


@pytest.mark.parametrize("value", ["default", "work-a", "team_1", "a.b", "ns:work-a"])
def test_validate_namespace_id_accepts_normal(value):
    assert validate_namespace_id(value) == value


@pytest.mark.parametrize("value", _INJECTION_STRINGS)
def test_validate_namespace_id_rejects_injection(value):
    with pytest.raises(ValueError):
        validate_namespace_id(value)


def test_validate_namespace_id_rejects_empty_and_too_long():
    with pytest.raises(ValueError):
        validate_namespace_id("")
    with pytest.raises(ValueError):
        validate_namespace_id("a" * 129)


def test_ensure_namespace_id_wraps_as_invalid_input():
    assert ensure_namespace_id("work-a") == "work-a"
    with pytest.raises(InvalidInputError):
        ensure_namespace_id('x" //')


def test_validate_relation_types_accepts_normal_and_none():
    assert validate_relation_types(None) is None
    assert validate_relation_types(["RELATES_TO", "applies to"]) == [
        "RELATES_TO",
        "applies to",
    ]


def test_validate_relation_types_rejects_too_many():
    with pytest.raises(ValueError):
        validate_relation_types([f"T{i}" for i in range(33)])


def test_validate_relation_types_rejects_too_long_item():
    with pytest.raises(ValueError):
        validate_relation_types(["A" * 65])


@pytest.mark.parametrize("bad", ["has\nnewline", "nul\x00byte", "tab\there"])
def test_validate_relation_types_rejects_control_chars(bad):
    with pytest.raises(ValueError):
        validate_relation_types([bad])


def test_ensure_entity_id_accepts_ulid_rejects_others():
    assert ensure_entity_id(_ENT_A) == _ENT_A
    for bad in ["short", "01hzlowercase00000000000000", 'x" //', ""]:
        with pytest.raises(InvalidInputError):
            ensure_entity_id(bad)


# ---------- REST 경계 ----------


class _RecordingGraph(PrimitiveStubGraph):
    """expand_neighbors 가 받은 relation_types / namespace_id 를 기록한다.

    파라미터 바인딩이 악성 문자열을 *데이터* 로 넘긴다는 것을, 그래프가 그 값을
    인자로 그대로 받았다는 사실로 확인하기 위한 stub.
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.seen_relation_types = None
        self.seen_namespace = None

    def expand_neighbors(
        self, *, entry_id, relation_types, direction, hops, max_nodes, namespace_id="default"
    ) -> NeighborhoodResult:
        self.seen_relation_types = relation_types
        self.seen_namespace = namespace_id
        return NeighborhoodResult(nodes=[], edges=[], truncated=False)


def _client_with(graph) -> TestClient:
    app = create_app()
    app.state.graph_repo = graph
    app.state.llm_provider = _StubLLM()
    app.state.embedding_provider = _StubEmbedder()
    app.dependency_overrides[graph_repo_dep] = lambda: graph
    app.dependency_overrides[llm_provider_dep] = lambda: _StubLLM()
    app.dependency_overrides[embedding_provider_dep] = lambda: _StubEmbedder()
    return TestClient(app)


def test_find_path_rejects_malicious_namespace_in_body():
    client = _client_with(PrimitiveStubGraph(nodes=[]))
    r = client.post(
        "/paths/find",
        json={"from_id": _ENT_A, "to_id": _ENT_B, "namespace_id": 'x" //'},
    )
    assert r.status_code == 422


def test_get_schema_rejects_malicious_namespace_query():
    client = _client_with(PrimitiveStubGraph(nodes=[]))
    r = client.get("/schema", params={"namespace_id": 'x" DETACH DELETE (n) //'})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_input"


def test_neighbors_rejects_malicious_namespace_in_auth_header():
    """헤더에서 해소된 namespace 는 body 모델을 거치지 않는다 — 서비스 초크포인트."""
    node = _make_node(node_id=_ENT_A)
    client = _client_with(PrimitiveStubGraph(nodes=[node]))
    r = client.post(
        f"/entities/{_ENT_A}/neighbors",
        json={"hops": 1, "max_nodes": 10},
        headers={"Authorization": 'Bearer ns:evil" DETACH DELETE (n) //'},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_input"


def test_neighbors_rejects_oversized_relation_types():
    node = _make_node(node_id=_ENT_A)
    client = _client_with(PrimitiveStubGraph(nodes=[node]))
    r = client.post(
        f"/entities/{_ENT_A}/neighbors",
        json={"relation_types": [f"T{i}" for i in range(33)]},
    )
    assert r.status_code == 422


def test_neighbors_injection_relation_type_is_bound_not_executed():
    """질의 탈출을 노린 관계 타입도 형식 관문(길이/제어문자)을 통과하면 그래프에
    *파라미터* 로 그대로 전달된다 — 실행되지 않고 데이터로만 취급."""
    node = _make_node(node_id=_ENT_A)
    graph = _RecordingGraph(nodes=[node])
    client = _client_with(graph)
    payload = "RELATES_TO`}) DETACH DELETE (n) //"  # 64 자 이내, 제어문자 없음
    r = client.post(
        f"/entities/{_ENT_A}/neighbors",
        json={"relation_types": [payload], "hops": 1, "max_nodes": 10},
    )
    assert r.status_code == 200
    assert graph.seen_relation_types == [payload]


# ---------- MCP 경계 ----------


class _StubSettings:
    embedding_model = "openai/text-embedding-3-small"
    embedding_dimension = 1536


def test_mcp_find_path_rejects_malicious_namespace():
    graph = PrimitiveStubGraph(nodes=[])
    with pytest.raises(ValidationError):
        _dispatch_tool(
            "find_path",
            {"from_id": _ENT_A, "to_id": _ENT_B, "namespace_id": 'x" //'},
            graph=graph,
            embedder=_StubEmbedder(),
            settings=_StubSettings(),
        )


def test_mcp_get_entity_rejects_non_ulid_id():
    graph = PrimitiveStubGraph(nodes=[])
    with pytest.raises(InvalidInputError):
        _dispatch_tool(
            "get_entity",
            {"id": 'x" DETACH DELETE (n) //'},
            graph=graph,
            embedder=_StubEmbedder(),
            settings=_StubSettings(),
        )


def test_mcp_get_schema_rejects_malicious_namespace_arg():
    graph = PrimitiveStubGraph(nodes=[])
    with pytest.raises(InvalidInputError):
        _dispatch_tool(
            "get_schema",
            {"namespace_id": 'x" //'},
            graph=graph,
            embedder=_StubEmbedder(),
            settings=_StubSettings(),
        )
