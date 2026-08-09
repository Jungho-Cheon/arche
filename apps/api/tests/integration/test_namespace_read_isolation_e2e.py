"""읽기 경로 namespace 격리 — 실 Neo4j 위에서 끝에서 끝까지 (issue #98).

#92/#94 가 적재와 매칭 경로를 namespace 로 격리했다. 본 모듈은 *읽기/질의* 경로
(검색, 단건 조회, 존재 확인, 순회)가 같은 namespace 안의 노드만 보는지를 실
Neo4j Cypher 로 잠근다 — FakeGraph 가 실 쿼리와 갈라지지 않게.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

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
    from arche_api.config import Settings

    return Settings(
        OPENAI_API_KEY="test",
        NEO4J_URI=neo4j_container.get_connection_url(),
        NEO4J_USER="neo4j",
        NEO4J_PASSWORD=neo4j_container.password,
        ARCHE_API_LLM_MODEL="openai/gpt-4.1",
        ARCHE_API_EMBEDDING_MODEL="openai/text-embedding-3-small",
        ARCHE_API_EMBEDDING_DIMENSION=8,
    )


@pytest.fixture(scope="module")
def repo(settings):
    from arche_api.adapters.graph import Neo4jGraphRepository

    r = Neo4jGraphRepository(settings)
    r.ensure_indexes()
    yield r
    r.close()


def _now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _entity(*, id_: str, name: str, namespace_id: str, type_: str = "coupon"):
    from arche_api.domain.models import SourceRef, StoredEntity

    now = _now()
    return StoredEntity(
        id=id_,
        name=name,
        type=type_,
        aliases=[],
        description=None,
        properties={},
        source_refs=[SourceRef(source_path="/tmp/ns.md")],
        created_at=now,
        updated_at=now,
        embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        normalized_name=name.lower(),
        normalized_aliases=[],
        namespace_id=namespace_id,
    )


# ns-a: A1 -> A2 (belongs_to). ns-b: B1 (이름은 A1 과 같은 "쿠폰 X").
A1 = "01HZNSAAAAAAAAAAAAAAAAAAA1"
A2 = "01HZNSAAAAAAAAAAAAAAAAAAA2"
B1 = "01HZNSBBBBBBBBBBBBBBBBBBB1"


@pytest.fixture(scope="module")
def seeded_two_namespaces(repo):
    from arche_api.domain.models import SourceRef

    a1 = _entity(id_=A1, name="쿠폰 X", namespace_id="ns-a")
    a2 = _entity(id_=A2, name="프로모션 P", namespace_id="ns-a", type_="promotion")
    b1 = _entity(id_=B1, name="쿠폰 X", namespace_id="ns-b")
    for e in (a1, a2, b1):
        if not repo.entity_exists(entity_id=e.id):
            repo.create_entity(entity=e)
    repo.upsert_relation(
        from_id=A1,
        to_id=A2,
        rel_type="belongs_to",
        source_ref=SourceRef(source_path="/tmp/ns.md"),
    )
    return {"a1": A1, "a2": A2, "b1": B1}


def test_keyword_search_scoped_by_namespace(repo, seeded_two_namespaces):
    """find_by_keywords_scored 는 요청 namespace 의 노드만 돌려준다."""
    hits_a = repo.find_by_keywords_scored(
        keywords=["쿠폰"], limit_per_keyword=10, namespace_id="ns-a"
    )
    ids_a = {h.node.id for h in hits_a}
    assert A1 in ids_a
    assert B1 not in ids_a  # 다른 namespace 의 동명 노드는 안 보인다.


def test_entity_exists_scoped_by_namespace(repo, seeded_two_namespaces):
    """entity_exists 는 다른 namespace 노드를 없는 것으로 본다."""
    assert repo.entity_exists(entity_id=B1, namespace_id="ns-b") is True
    assert repo.entity_exists(entity_id=B1, namespace_id="ns-a") is False


def test_get_entity_with_counts_scoped_by_namespace(repo, seeded_two_namespaces):
    """get_entity_with_counts 는 namespace 밖 id 에 None 을 돌려준다."""
    assert (
        repo.get_entity_with_counts(entity_id=B1, namespace_id="ns-a") is None
    )
    assert (
        repo.get_entity_with_counts(entity_id=B1, namespace_id="ns-b") is not None
    )


def test_expand_neighbors_scoped_by_namespace(repo, seeded_two_namespaces):
    """expand_neighbors 는 namespace 안의 이웃만 확장한다."""
    result = repo.expand_neighbors(
        entry_id=A1,
        relation_types=None,
        direction="both",
        hops=2,
        max_nodes=50,
        namespace_id="ns-a",
    )
    ids = {n.id for n in result.nodes}
    assert A1 in ids and A2 in ids
    assert B1 not in ids
