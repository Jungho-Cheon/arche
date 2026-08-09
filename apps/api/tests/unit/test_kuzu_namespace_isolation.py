"""namespace 를 받는 메서드 전부가 진짜 어댑터에서 격리를 지키는지.

이 파일이 있는 이유. 단위 테스트의 그래프 더블 12 개 중 10 개가 namespace_id 를 인자로
받고는 본문에서 쓰지 않는다. 그러니 읽기 경로에서 namespace 가 새도 더블 위의 테스트는
전부 통과한다. 실제로 확정 단계가 namespace 를 안 넘기던 결함이 그렇게 숨어 있었다.

여기서는 진짜 Kuzu 어댑터에 두 namespace 를 채우고, 한쪽에서 물었을 때 다른 쪽 것이
섞여 나오지 않는지 메서드마다 확인한다. namespace 를 받는 메서드를 새로 만들면 아래
목록에 더한다 — 마지막 테스트가 빠뜨림을 잡는다.

격리가 깨지면 조회는 성공하고 답만 틀린다. 사용자가 가장 알아채기 어려운 실패다.
"""

from __future__ import annotations

import inspect
import types

import pytest
from ulid import ULID

from arche_api.domain.models import SourceRef, StoredEntity, now_rfc3339
from arche_api.domain.ports import GraphStore, LexicalIndex, VectorIndex

DIM = 4
HERE = "ns-here"
THERE = "ns-there"


def _entity(name: str, type_: str, embedding: list[float], namespace_id: str) -> StoredEntity:
    now = now_rfc3339()
    return StoredEntity(
        id=str(ULID()),
        name=name,
        type=type_,
        aliases=[],
        description=f"{name} 설명",
        properties={},
        source_refs=[SourceRef(source_path=f"/docs/{namespace_id}.md")],
        created_at=now,
        updated_at=now,
        embedding=embedding,
        namespace_id=namespace_id,
        normalized_name=name.lower(),
        normalized_aliases=[],
    )


@pytest.fixture
def two_namespaces(tmp_path):
    """양쪽 namespace 에 *이름과 타입이 똑같은* 노드 두 개씩과 관계 하나씩.

    이름을 같게 두는 것이 요점이다. 이름이 다르면 격리가 깨져도 검색어가 안 걸려
    우연히 통과한다.
    """
    from arche_api.adapters.kuzu_graph import KuzuGraphRepository

    settings = types.SimpleNamespace(
        embedding_dimension=DIM, kuzu_db_path=str(tmp_path / "kuzu_db")
    )
    repo = KuzuGraphRepository(settings)
    repo.ensure_indexes()

    made: dict[str, dict[str, StoredEntity]] = {}
    for ns in (HERE, THERE):
        policy = _entity("환불 정책", "Policy", [1.0, 0.0, 0.0, 0.0], ns)
        product = _entity("여름 원피스", "Product", [0.0, 1.0, 0.0, 0.0], ns)
        repo.create_entity(entity=policy)
        repo.create_entity(entity=product)
        repo.upsert_relation(
            from_id=policy.id,
            to_id=product.id,
            rel_type="APPLIES_TO",
            source_ref=SourceRef(source_path=f"/docs/{ns}.md"),
        )
        made[ns] = {"policy": policy, "product": product}

    yield repo, made
    repo.close()


def test_lookup_by_name_stays_inside_the_namespace(two_namespaces):
    repo, made = two_namespaces

    hit = repo.find_by_normalized_name(normalized="환불 정책", type_="Policy", namespace_id=HERE)
    assert hit is not None
    assert hit.id == made[HERE]["policy"].id

    by_id = repo.find_entity_id_by_normalized_name(normalized="환불 정책", namespace_id=THERE)
    assert by_id == made[THERE]["policy"].id

    # 이름이 같은 노드가 양쪽에 하나씩 있다. 격리가 깨지면 둘 다 나온다.
    by_name = repo.find_entities_by_name(normalized_name="환불 정책", namespace_id=HERE)
    assert [e.id for e in by_name] == [made[HERE]["policy"].id]


def test_entity_exists_does_not_see_across_the_namespace(two_namespaces):
    repo, made = two_namespaces
    there_id = made[THERE]["policy"].id

    assert repo.entity_exists(entity_id=there_id, namespace_id=THERE) is True
    assert repo.entity_exists(entity_id=there_id, namespace_id=HERE) is False


def test_single_entity_reads_stay_inside_the_namespace(two_namespaces):
    repo, made = two_namespaces
    there_id = made[THERE]["policy"].id

    assert repo.get_entity_with_counts(entity_id=there_id, namespace_id=THERE) is not None
    assert repo.get_entity_with_counts(entity_id=there_id, namespace_id=HERE) is None

    assert repo.get_entity_relations(entity_id=there_id, namespace_id=THERE)
    assert repo.get_entity_relations(entity_id=there_id, namespace_id=HERE) == []


def test_search_stays_inside_the_namespace(two_namespaces):
    repo, made = two_namespaces
    here_ids = {e.id for e in made[HERE].values()}

    lexical = repo.find_by_keywords_scored(
        keywords=["환불"], limit_per_keyword=10, namespace_id=HERE
    )
    assert lexical
    assert {h.node.id for h in lexical} <= here_ids

    dense = repo.find_entities_dense(
        query_embedding=[1.0, 0.0, 0.0, 0.0], matched_keyword="환불", limit=10, namespace_id=HERE
    )
    assert dense
    assert {h.node.id for h in dense} <= here_ids

    vectors = repo.vector_search(
        embedding=[1.0, 0.0, 0.0, 0.0], top_k=10, type_="Policy", namespace_id=HERE
    )
    assert vectors
    assert {e.id for e in vectors} <= here_ids


def test_traversal_stays_inside_the_namespace(two_namespaces):
    repo, made = two_namespaces
    here = made[HERE]
    here_ids = {e.id for e in here.values()}

    neighbors = repo.expand_neighbors(
        entry_id=here["policy"].id,
        relation_types=None,
        direction="both",
        hops=2,
        max_nodes=50,
        namespace_id=HERE,
    )
    assert {n.id for n in neighbors.nodes} <= here_ids

    subgraph = repo.expand_subgraph(
        entry_ids=[here["policy"].id],
        relation_types=None,
        hops=2,
        max_nodes=50,
        namespace_id=HERE,
    )
    assert {n.id for n in subgraph.nodes} <= here_ids

    paths = repo.find_shortest_paths(
        from_id=here["policy"].id,
        to_id=here["product"].id,
        max_hops=3,
        max_paths=5,
        relation_types=None,
        namespace_id=HERE,
    )
    assert paths
    for path in paths:
        assert {n.id for n in path.nodes} <= here_ids


def test_paths_do_not_bridge_two_namespaces(two_namespaces):
    """한쪽 노드에서 다른 쪽 노드로 길이 뚫리면 안 된다."""
    repo, made = two_namespaces

    crossing = repo.find_shortest_paths(
        from_id=made[HERE]["policy"].id,
        to_id=made[THERE]["product"].id,
        max_hops=4,
        max_paths=5,
        relation_types=None,
        namespace_id=HERE,
    )
    assert crossing == []


def test_schema_summary_counts_only_one_namespace(two_namespaces):
    repo, _ = two_namespaces

    entity_types, relation_types = repo.get_schema_summary(examples_per_type=5, namespace_id=HERE)

    # 양쪽에 같은 타입이 하나씩 있다. 격리가 깨지면 2 가 된다.
    assert {t.type: t.count for t in entity_types} == {"Policy": 1, "Product": 1}
    assert {t.type: t.count for t in relation_types} == {"APPLIES_TO": 1}


def test_every_namespace_aware_method_is_covered_here():
    """namespace 를 받는 메서드가 늘면 이 파일도 늘어야 한다.

    빠뜨린 채로 두면 그 메서드의 격리는 아무도 안 본다. 새 메서드를 더했다면 위에
    검사를 쓰고 아래 목록에 이름을 더해라.
    """
    covered = {
        "entity_exists",
        "expand_neighbors",
        "expand_subgraph",
        "find_by_keywords_scored",
        "find_by_normalized_name",
        "find_entities_dense",
        "find_entities_by_name",
        "find_entity_id_by_normalized_name",
        "find_shortest_paths",
        "get_entity_relations",
        "get_entity_with_counts",
        "get_schema_summary",
        "vector_search",
    }

    declared = set()
    for port in (GraphStore, VectorIndex, LexicalIndex):
        for name, fn in vars(port).items():
            if not callable(fn):
                continue
            try:
                params = inspect.signature(fn).parameters
            except (TypeError, ValueError):
                continue
            if "namespace_id" in params:
                declared.add(name)

    assert declared == covered, f"검사 없는 메서드: {sorted(declared - covered)}"


def test_stored_entity_reports_the_namespace_it_lives_in(two_namespaces):
    """읽어 온 노드가 자기 namespace 를 제대로 말해야 한다.

    이 값을 안 채우면 모든 노드가 자기를 default 소속이라고 말한다. 노드의 namespace 를
    되묻는 쪽(떼어내기가 그렇다)이 늘 default 로 판정해, 다른 namespace 에서는 아예
    못 찾거나 반대로 남의 namespace 노드를 제 것처럼 다루게 된다.
    """
    repo, made = two_namespaces

    for ns in (HERE, THERE):
        stored = repo.get_stored_entity(entity_id=made[ns]["policy"].id)
        assert stored is not None
        assert stored.namespace_id == ns

    found = repo.find_by_normalized_name(
        normalized="환불 정책", type_="Policy", namespace_id=THERE
    )
    assert found.namespace_id == THERE
