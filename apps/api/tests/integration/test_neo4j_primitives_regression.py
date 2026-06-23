"""실 Neo4j 위에서 primitive 의 cypher 응답 직렬화를 검증.

WHY 본 모듈: 이슈 #27 회귀 2 — `s.run(...).data()` 가 relationship 객체를
*tuple* 로 직렬화하는 경로 (특히 UNION 쿼리) 가 production 에서만 노출된다.
unit 의 FakeGraph 와 기존 testcontainers (`find_by_keywords_scored`, identity
단계) 는 이 경로를 한 번도 호출하지 않았다. 본 모듈이 그 공백을 메운다:

- `expand_neighbors` (UNION 쿼리, direction="both" 포함)
- `expand_subgraph` (multi-source UNION)
- `find_shortest_paths` (variable-length + relationships(p) 매핑)

세 메서드 모두 *원시 값* 만 RETURN 하도록 cypher 가 정규화되어 driver 의
직렬화 quirk 가 사라졌는지를 확인한다.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest


docker_available = pytest.importorskip("testcontainers.neo4j")
Neo4jContainer = docker_available.Neo4jContainer

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def neo4j_container():
    if os.environ.get("SKIP_INTEGRATION") == "1":
        pytest.skip("integration skipped via env")
    with Neo4jContainer("neo4j:5.15-community") as neo4j:
        yield neo4j


@pytest.fixture(scope="module")
def settings(neo4j_container):
    from opentology_api.config import Settings

    return Settings(
        OPENAI_API_KEY="test",
        NEO4J_URI=neo4j_container.get_connection_url(),
        NEO4J_USER="neo4j",
        NEO4J_PASSWORD=neo4j_container.password,
        OPENTOLOGY_API_LLM_MODEL="openai/gpt-4.1",
        OPENTOLOGY_API_EMBEDDING_MODEL="openai/text-embedding-3-small",
    )


@pytest.fixture(scope="module")
def repo(settings):
    from opentology_api.adapters.graph import Neo4jGraphRepository

    r = Neo4jGraphRepository(settings)
    r.ensure_indexes()
    yield r
    r.close()


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _make_entity(*, id_: str, name: str, type_: str = "thing"):
    from opentology_api.domain.models import SourceRef, StoredEntity

    now = _now()
    return StoredEntity(
        id=id_,
        name=name,
        type=type_,
        aliases=[],
        description=None,
        properties={},
        source_refs=[SourceRef(source_path="/tmp/regression.md")],
        created_at=now,
        updated_at=now,
        embedding=[0.0] * 1536,
        normalized_name=name.lower(),
        normalized_aliases=[],
    )


# 26-자 ULID 패턴 만족 (0-9A-Z 만 사용).
COUPON_ID = "01HZX0G7M8N0RT0V0COUPON000"
PROMO_ID = "01HZX0G7M8N0RT0V0PROMOXX00"
CATEGORY_ID = "01HZX0G7M8N0RT0V0CATXX0000"
PRODUCT_A_ID = "01HZX0G7M8N0RT0V0PRODUCTA0"


@pytest.fixture(scope="module")
def seeded_chain(repo):
    """4 노드 chain: 쿠폰 → 프로모션 → 카테고리 → 상품A (모두 belongs_to).

    이 픽스처는 module scope — 세 회귀 테스트가 같은 그래프를 재사용한다.
    각 테스트는 *읽기 전용* 이므로 상호 간섭 없음.
    """
    from opentology_api.domain.models import SourceRef

    coupon = _make_entity(id_=COUPON_ID, name="쿠폰 X", type_="coupon")
    promo = _make_entity(id_=PROMO_ID, name="프로모션 P", type_="promotion")
    category = _make_entity(id_=CATEGORY_ID, name="카테고리 C", type_="category")
    product = _make_entity(id_=PRODUCT_A_ID, name="상품 A", type_="product")
    for e in (coupon, promo, category, product):
        # 이미 적재돼 있으면 IntegrityError — fixture 가 첫 호출에서만 적재되도록
        # entity_exists 로 가드.
        if not repo.entity_exists(entity_id=e.id):
            repo.create_entity(entity=e)
    src = SourceRef(source_path="/tmp/regression.md")
    repo.upsert_relation(
        from_id=COUPON_ID, to_id=PROMO_ID, rel_type="belongs_to", source_ref=src
    )
    repo.upsert_relation(
        from_id=PROMO_ID,
        to_id=CATEGORY_ID,
        rel_type="applies_to",
        source_ref=src,
    )
    repo.upsert_relation(
        from_id=CATEGORY_ID,
        to_id=PRODUCT_A_ID,
        rel_type="contains",
        source_ref=src,
    )
    return {
        "coupon": COUPON_ID,
        "promo": PROMO_ID,
        "category": CATEGORY_ID,
        "product": PRODUCT_A_ID,
    }


# ---------- ADR-0017 hub-aware path ordering ----------
# A 에서 B 로 가는 길이-2 경로가 둘: 하나는 *구체적* 중간 노드 (degree 2), 다른
# 하나는 *promiscuous 허브* 중간 노드 (decoy 다수와 연결되어 degree 높음). 같은
# 길이라도 어댑터는 hub_score 가 낮은 (구체적) 경로를 먼저 돌려줘야 한다.
HUB_SRC = "01HZXHUB0000000000000000A1"
HUB_DST = "01HZXHUB0000000000000000B2"
HUB_SPEC = "01HZXHUB0000000000000000C3"
HUB_HUB = "01HZXHUB0000000000000000D4"
HUB_DECOYS = [f"01HZXHUB0000000000000000E{i}" for i in range(8)]


@pytest.fixture(scope="module")
def seeded_hub(repo):
    from opentology_api.domain.models import SourceRef

    src = SourceRef(source_path="/tmp/hub.md")
    nodes = {
        HUB_SRC: "엔티티 A",
        HUB_DST: "엔티티 B",
        HUB_SPEC: "구체적 중간",
        HUB_HUB: "공유 허브",
    }
    for i, did in enumerate(HUB_DECOYS):
        nodes[did] = f"decoy {i}"
    for nid, name in nodes.items():
        if not repo.entity_exists(entity_id=nid):
            repo.create_entity(entity=_make_entity(id_=nid, name=name))
    # 두 길이-2 경로: A-SPEC-B, A-HUB-B.
    for a, b in [
        (HUB_SRC, HUB_SPEC),
        (HUB_SPEC, HUB_DST),
        (HUB_SRC, HUB_HUB),
        (HUB_HUB, HUB_DST),
    ]:
        repo.upsert_relation(from_id=a, to_id=b, rel_type="links", source_ref=src)
    # 허브를 decoy 다수와 연결 → degree 폭증 (promiscuous).
    for did in HUB_DECOYS:
        repo.upsert_relation(
            from_id=HUB_HUB, to_id=did, rel_type="links", source_ref=src
        )
    return {"a": HUB_SRC, "b": HUB_DST, "spec": HUB_SPEC, "hub": HUB_HUB}


def test_find_shortest_paths_prefers_specific_over_hub(repo, seeded_hub):
    """ADR-0017 — 같은 길이의 두 경로 중 promiscuous 허브를 *경유하지 않는*
    구체적 경로가 먼저 와야 하고, hub_score 가 그 순서를 정량적으로 뒷받침해야
    한다. 끝점 (A,B) 은 hub_score 합에서 제외된다."""
    paths = repo.find_shortest_paths(
        from_id=seeded_hub["a"],
        to_id=seeded_hub["b"],
        max_hops=2,
        max_paths=2,
        relation_types=None,
    )
    assert len(paths) == 2, "A→B 길이-2 경로가 둘 (구체적/허브) 있어야 함"
    # 첫 경로가 더 구체적 (hub_score 낮음).
    assert paths[0].hub_score < paths[1].hub_score
    # 첫 경로의 중간 노드 = 구체적 노드, 둘째 = 허브.
    assert paths[0].nodes[1].id == seeded_hub["spec"]
    assert paths[1].nodes[1].id == seeded_hub["hub"]
    # 끝점 제외 검증 — 구체적 경로의 중간 노드 degree 는 2 (A,B 와만 연결)
    # 이므로 hub_score = log(1+2) ≈ 1.0986.
    import math

    assert abs(paths[0].hub_score - math.log1p(2)) < 1e-6


def test_find_shortest_paths_direct_edge_zero_hub_score(repo, seeded_chain):
    """1-hop 직접 경로는 중간 노드가 없어 hub_score = 0.0 (가장 구체적)."""
    paths = repo.find_shortest_paths(
        from_id=seeded_chain["coupon"],
        to_id=seeded_chain["promo"],
        max_hops=1,
        max_paths=3,
        relation_types=None,
    )
    assert len(paths) >= 1
    assert paths[0].length == 1
    assert paths[0].hub_score == 0.0


def _assert_edge_shape(edge):
    """이슈 #27 회귀 2 의 검증 포인트 — 모든 핵심 필드가 *원시 string* 으로
    채워지고, tuple 등의 자료형이 아니어야 한다."""
    assert isinstance(edge.id, str) and len(edge.id) == 26
    assert isinstance(edge.from_, str) and len(edge.from_) == 26
    assert isinstance(edge.to, str) and len(edge.to) == 26
    assert isinstance(edge.type, str) and edge.type
    assert isinstance(edge.created_at, str) and "T" in edge.created_at
    assert isinstance(edge.updated_at, str) and "T" in edge.updated_at


def test_expand_neighbors_serializes_edges_both_direction(repo, seeded_chain):
    """회귀 2 의 핵심 — UNION 양방향 쿼리에서 relationship 직렬화 정상."""
    result = repo.expand_neighbors(
        entry_id=seeded_chain["promo"],
        relation_types=None,
        direction="both",
        hops=1,
        max_nodes=100,
    )
    # 프로모션의 이웃 = 쿠폰 + 카테고리 (둘 다 정확히 1-hop)
    node_ids = {n.id for n in result.nodes}
    assert seeded_chain["coupon"] in node_ids
    assert seeded_chain["category"] in node_ids
    assert len(result.edges) >= 2
    for e in result.edges:
        _assert_edge_shape(e)
    assert result.truncated is False


def test_expand_neighbors_outgoing_only(repo, seeded_chain):
    """direction='outgoing' 도 같은 properties-only select 경로를 타는지."""
    result = repo.expand_neighbors(
        entry_id=seeded_chain["coupon"],
        relation_types=None,
        direction="outgoing",
        hops=1,
        max_nodes=100,
    )
    node_ids = {n.id for n in result.nodes}
    assert seeded_chain["promo"] in node_ids
    for e in result.edges:
        _assert_edge_shape(e)
        assert e.from_ == seeded_chain["coupon"]


def test_expand_subgraph_returns_serialized_edges(repo, seeded_chain):
    """회귀 2 의 트리거 — `/subgraph` 가 production 에서 500 으로 깨졌던 경로.

    두 진입점에서 2-hop union BFS. UNION 쿼리의 relationship 직렬화가
    정상이면 edges 의 모든 필드가 string.
    """
    result = repo.expand_subgraph(
        entry_ids=[seeded_chain["coupon"], seeded_chain["product"]],
        relation_types=None,
        hops=2,
        max_nodes=50,
    )
    # 두 진입점에서 2-hop 안에 포함되는 노드 — 둘 다 entry + 1-hop 이웃까지.
    assert len(result.nodes) >= 3
    assert len(result.edges) >= 2
    for e in result.edges:
        _assert_edge_shape(e)
    assert result.truncated is False


def test_find_shortest_paths_returns_serialized_path(repo, seeded_chain):
    """회귀 3 — 4-hop 안의 chain 에서 양방향 path 가 발견되어야 한다."""
    paths = repo.find_shortest_paths(
        from_id=seeded_chain["coupon"],
        to_id=seeded_chain["product"],
        max_hops=4,
        max_paths=3,
        relation_types=None,
    )
    assert len(paths) >= 1, "쿠폰 → 상품 A 4-hop 경로가 그래프에 있어야 함"
    p = paths[0]
    # length 는 hop 수 (relationships 수) — 3 (coupon→promo→category→product).
    assert p.length == 3
    # nodes 는 length + 1 = 4 개.
    assert len(p.nodes) == 4
    assert p.nodes[0].id == seeded_chain["coupon"]
    assert p.nodes[-1].id == seeded_chain["product"]
    # edges 는 length 개 + 모든 필드 원시 직렬화.
    assert len(p.edges) == p.length
    for e in p.edges:
        _assert_edge_shape(e)
    # PRD 3 §6.4 의 "edges[i] 는 nodes[i] → nodes[i+1]" 보장.
    for i, e in enumerate(p.edges):
        assert e.from_ == p.nodes[i].id
        assert e.to == p.nodes[i + 1].id
