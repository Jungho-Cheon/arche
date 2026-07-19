"""find_related (#140) — 근접도 채점 + REST/MCP 계약 단위 테스트.

유료 eval 없이 검증 가능한 부분만 다룬다: 감쇠 확산 근접도 랭킹의 결정적 동작
(거리 감쇠 / 다중 시드 합산 / 시드 제외 / top_k 절단 / 빈 결과)과 라우터/MCP
표면 노출. 왕복/토큰 절감의 정량 evidence 는 #83 측정 하니스의 몫이다 — 여기서는
"여러 홉 탐색이 한 번의 호출로 접힌다" 는 프리미티브의 모양을 계약으로 고정한다.
"""

from __future__ import annotations

from arche_api.api.responses import FindRelatedRequest
from arche_api.api.services import _score_proximity, find_related
from arche_api.domain.ports import NeighborhoodResult

from .test_primitives import (
    PrimitiveStubGraph,
    _client_with,
    _make_edge,
    _make_node,
)

# 26 자 ULID (^[0-9A-Z]{26}$).
S = "01SEED00000000000000000000"
S1 = "01SEED10000000000000000000"
S2 = "01SEED20000000000000000000"
A = "01NODEA0000000000000000000"
B = "01NODEB0000000000000000000"
X = "01NODEX0000000000000000000"
Y = "01NODEY0000000000000000000"


# ---------- _score_proximity (순수 채점 로직) ----------


def test_proximity_decays_with_distance():
    """S-A-B 사슬 — 가까운 A 가 먼 B 보다 높은 점수. 시드 S 는 결과에서 제외."""
    nodes = [_make_node(node_id=S), _make_node(node_id=A), _make_node(node_id=B)]
    edges = [
        _make_edge(edge_id="01EDGESA000000000000000000", from_id=S, to_id=A),
        _make_edge(edge_id="01EDGEAB000000000000000000", from_id=A, to_id=B),
    ]
    related, truncated = _score_proximity(
        seeds=[S], nodes=nodes, edges=edges, top_k=10, damping=0.5
    )
    ids = [r.node.id for r in related]
    assert ids == [A, B]  # S 제외, 가까운 순
    assert related[0].distance == 1 and related[1].distance == 2
    # A raw=0.5^1=0.5, B raw=0.5^2=0.25 → max-normalize → 1.0, 0.5.
    assert related[0].score == 1.0
    assert related[1].score == 0.5
    assert truncated is False


def test_proximity_sums_over_multiple_seeds():
    """두 시드 모두에 인접한 X 가, 한 시드에만 인접한 Y 보다 높다 (기여 합산)."""
    nodes = [
        _make_node(node_id=S1),
        _make_node(node_id=S2),
        _make_node(node_id=X),
        _make_node(node_id=Y),
    ]
    edges = [
        _make_edge(edge_id="01EDGE1X000000000000000000", from_id=S1, to_id=X),
        _make_edge(edge_id="01EDGE2X000000000000000000", from_id=S2, to_id=X),
        _make_edge(edge_id="01EDGE1Y000000000000000000", from_id=S1, to_id=Y),
    ]
    related, _ = _score_proximity(seeds=[S1, S2], nodes=nodes, edges=edges, top_k=10, damping=0.5)
    ids = [r.node.id for r in related]
    assert ids[0] == X  # 0.5+0.5=1.0 > Y 의 0.5
    assert Y in ids
    assert related[0].score == 1.0


def test_proximity_top_k_truncates_and_flags():
    """후보가 top_k 를 넘으면 잘리고 truncated=True."""
    nodes = [_make_node(node_id=S), _make_node(node_id=A), _make_node(node_id=B)]
    edges = [
        _make_edge(edge_id="01EDGESA000000000000000000", from_id=S, to_id=A),
        _make_edge(edge_id="01EDGESB000000000000000000", from_id=S, to_id=B),
    ]
    related, truncated = _score_proximity(seeds=[S], nodes=nodes, edges=edges, top_k=1, damping=0.5)
    assert len(related) == 1
    assert truncated is True


def test_proximity_empty_when_no_seed_present():
    """시드가 서브그래프에 없으면 빈 결과 (get_subgraph 와 같은 조용한 무시)."""
    nodes = [_make_node(node_id=A)]
    related, truncated = _score_proximity(seeds=[S], nodes=nodes, edges=[], top_k=10, damping=0.5)
    assert related == []
    assert truncated is False


def test_proximity_isolated_seed_has_no_related():
    """시드는 있지만 인접 노드가 없으면 관련 노드 없음."""
    nodes = [_make_node(node_id=S)]
    related, _ = _score_proximity(seeds=[S], nodes=nodes, edges=[], top_k=10, damping=0.5)
    assert related == []


# ---------- REST 라우터 계약 ----------


def test_find_related_rest_returns_ranked_envelope():
    """POST /related/find — 단일 호출로 근접 랭킹된 노드 + score/distance 반환."""
    nodes = [_make_node(node_id=S), _make_node(node_id=A), _make_node(node_id=B)]
    edges = [
        _make_edge(edge_id="01EDGESA000000000000000000", from_id=S, to_id=A),
        _make_edge(edge_id="01EDGEAB000000000000000000", from_id=A, to_id=B),
    ]
    stub = PrimitiveStubGraph(
        subgraph_result=NeighborhoodResult(nodes=nodes, edges=edges, truncated=False)
    )
    client = _client_with(stub)
    resp = client.post("/related/find", json={"seeds": [S], "top_k": 10})
    assert resp.status_code == 200
    data = resp.json()["data"]
    ids = [r["node"]["id"] for r in data["related"]]
    assert ids == [A, B]
    assert data["seeds"] == [S]
    assert data["related"][0]["distance"] == 1
    assert data["related"][0]["score"] == 1.0


def test_find_related_rest_rejects_non_ulid_seed():
    """시드가 ULID 형식이 아니면 422 (pydantic 검증)."""
    client = _client_with(PrimitiveStubGraph())
    resp = client.post("/related/find", json={"seeds": ["not-a-ulid"]})
    assert resp.status_code == 422


def test_find_related_openapi_exposes_endpoint():
    """OpenAPI 에 /related/find 가 노출된다 (계약 가시성)."""
    client = _client_with(PrimitiveStubGraph())
    schema = client.get("/openapi.json").json()
    assert "/related/find" in schema["paths"]


# ---------- 서비스 함수: get_subgraph 재사용 확인 ----------


def test_find_related_service_reuses_subgraph_traversal():
    """find_related 는 새 저장소 기능 없이 expand_subgraph 순회로 동작한다."""
    nodes = [_make_node(node_id=S), _make_node(node_id=A)]
    edges = [_make_edge(edge_id="01EDGESA000000000000000000", from_id=S, to_id=A)]
    stub = PrimitiveStubGraph(
        subgraph_result=NeighborhoodResult(nodes=nodes, edges=edges, truncated=False)
    )
    out = find_related(FindRelatedRequest(seeds=[S], top_k=5), graph=stub, namespace_id="default")
    assert [r.node.id for r in out.related] == [A]
    assert out.truncated is False
