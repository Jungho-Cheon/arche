"""Kuzu 임베디드 어댑터 컴포넌트 검증 (#146, ADR-0020).

각 프리미티브/능력이 Neo4j 어댑터와 같은 계약으로 동작하는지 서버 없이 확인한다.
Kuzu 는 in-process 라 별도 컨테이너가 필요 없어 unit 스위트에서 돈다.
"""

from __future__ import annotations

import types

import pytest
from ulid import ULID

from arche_api.domain.models import MergeMutation, SourceRef, StoredEntity, now_rfc3339

DIM = 4


def _settings(tmp_path):
    return types.SimpleNamespace(
        embedding_dimension=DIM, kuzu_db_path=str(tmp_path / "kuzu_db")
    )


def _entity(name, type_, embedding, *, aliases=None, ns="default", norm=None):
    now = now_rfc3339()
    return StoredEntity(
        id=str(ULID()),
        name=name,
        type=type_,
        aliases=aliases or [],
        description=f"{name} 설명",
        properties={},
        source_refs=[SourceRef(source_path=f"/docs/{name}.md")],
        created_at=now,
        updated_at=now,
        embedding=embedding,
        namespace_id=ns,
        normalized_name=(norm or name).lower(),
        normalized_aliases=[a.lower() for a in (aliases or [])],
    )


@pytest.fixture
def repo(tmp_path):
    from arche_api.adapters.kuzu_graph import KuzuGraphRepository

    r = KuzuGraphRepository(_settings(tmp_path))
    r.ensure_indexes()
    yield r
    r.close()


def _seed(repo):
    """Policy -APPLIES_TO-> Category -CONTAINS-> Product 3노드 2엣지."""
    policy = _entity("refund policy", "Policy", [1.0, 0.0, 0.0, 0.0], aliases=["환불"])
    category = _entity("clothing category", "Category", [0.0, 1.0, 0.0, 0.0])
    product = _entity("summer dress", "Product", [0.0, 0.0, 1.0, 0.0])
    for e in (policy, category, product):
        repo.create_entity(entity=e)
    rid1, created1 = repo.upsert_relation(
        from_id=policy.id, to_id=category.id, rel_type="APPLIES_TO",
        source_ref=SourceRef(source_path="/docs/refund policy.md"),
    )
    repo.upsert_relation(
        from_id=category.id, to_id=product.id, rel_type="CONTAINS",
        source_ref=SourceRef(source_path="/docs/clothing category.md"),
    )
    return policy, category, product, rid1, created1


def test_create_and_get_entity(repo):
    policy, *_ = _seed(repo)
    got = repo.get_stored_entity(entity_id=policy.id)
    assert got is not None
    assert got.name == "refund policy"
    assert got.type == "Policy"
    assert len(got.embedding) == DIM


def test_upsert_relation_idempotent(repo):
    policy, category, _, rid1, created1 = _seed(repo)
    assert created1 is True
    rid2, created2 = repo.upsert_relation(
        from_id=policy.id, to_id=category.id, rel_type="APPLIES_TO",
        source_ref=SourceRef(source_path="/docs/another.md"),
    )
    assert created2 is False
    assert rid2 == rid1  # 같은 (from,type,to) → 같은 관계


def test_entity_with_counts(repo):
    policy, category, product, *_ = _seed(repo)
    counts = repo.get_entity_with_counts(entity_id=category.id)
    assert counts is not None
    assert counts.outgoing.get("CONTAINS") == 1
    assert counts.incoming.get("APPLIES_TO") == 1


def test_entity_exists_respects_namespace(repo):
    policy, *_ = _seed(repo)
    assert repo.entity_exists(entity_id=policy.id) is True
    assert repo.entity_exists(entity_id=policy.id, namespace_id="other") is False
    assert repo.entity_exists(entity_id=str(ULID())) is False


def test_normalized_name_lookup(repo):
    policy, *_ = _seed(repo)
    found = repo.find_by_normalized_name(normalized="refund policy", type_="Policy")
    assert found is not None and found.id == policy.id
    fid = repo.find_entity_id_by_normalized_name(normalized="refund policy")
    assert fid == policy.id
    # alias 정규명으로도 hit
    assert repo.find_entity_id_by_normalized_name(normalized="환불") == policy.id


def test_count_by_namespace(repo):
    _seed(repo)
    repo.create_entity(entity=_entity("x", "T", [0.1, 0.2, 0.3, 0.4], ns="team-a"))
    counts = repo.count_entities_by_namespace()
    assert counts["default"] == 3
    assert counts["team-a"] == 1


def test_vector_search(repo):
    policy, *_ = _seed(repo)
    hits = repo.vector_search(embedding=[0.98, 0.02, 0.0, 0.0], top_k=2, type_="Policy")
    assert hits, "정책 벡터에 가까운 질의가 Policy 를 찾아야 함"
    assert hits[0].id == policy.id


def test_dense_hits_score_range(repo):
    _seed(repo)
    hits = repo.find_entities_dense(
        query_embedding=[1.0, 0.0, 0.0, 0.0], matched_keyword="환불", limit=3
    )
    assert hits
    for h in hits:
        assert 0.0 <= h.raw_score <= 1.0
        assert h.matched_keyword == "환불"


def test_fulltext_keyword_search(repo):
    policy, *_ = _seed(repo)
    hits = repo.find_by_keywords_scored(keywords=["환불"], limit_per_keyword=5)
    assert any(h.node.id == policy.id for h in hits)


def test_search_namespace_isolation(repo):
    _seed(repo)
    other = _entity("refund special", "Policy", [1.0, 0.0, 0.0, 0.0], aliases=["환불"], ns="team-a")
    repo.create_entity(entity=other)
    # default namespace 검색은 team-a 노드를 못 봐야 한다.
    dense = repo.find_entities_dense(
        query_embedding=[1.0, 0.0, 0.0, 0.0], matched_keyword="환불", limit=10,
        namespace_id="default",
    )
    assert all(h.node.id != other.id for h in dense)
    kw = repo.find_by_keywords_scored(keywords=["환불"], limit_per_keyword=10, namespace_id="default")
    assert all(h.node.id != other.id for h in kw)


def test_schema_summary(repo):
    _seed(repo)
    entity_stats, relation_stats = repo.get_schema_summary()
    types_seen = {s.type for s in entity_stats}
    assert {"Policy", "Category", "Product"} <= types_seen
    rel_types = {s.type for s in relation_stats}
    assert {"APPLIES_TO", "CONTAINS"} <= rel_types


def test_expand_neighbors(repo):
    policy, category, *_ = _seed(repo)
    res = repo.expand_neighbors(
        entry_id=policy.id, relation_types=None, direction="both",
        hops=1, max_nodes=50,
    )
    ids = {n.id for n in res.nodes}
    assert policy.id in ids and category.id in ids
    assert any(e.type == "APPLIES_TO" for e in res.edges)


def test_expand_subgraph(repo):
    policy, category, product, *_ = _seed(repo)
    res = repo.expand_subgraph(
        entry_ids=[policy.id], relation_types=None, hops=2, max_nodes=50
    )
    ids = {n.id for n in res.nodes}
    assert {policy.id, category.id, product.id} <= ids


def test_find_shortest_paths(repo):
    policy, category, product, *_ = _seed(repo)
    paths = repo.find_shortest_paths(
        from_id=policy.id, to_id=product.id, max_hops=4, max_paths=5,
        relation_types=None,
    )
    assert paths, "policy → product 경로가 있어야 함"
    p = paths[0]
    assert p.length == 2
    assert p.nodes[0].id == policy.id and p.nodes[-1].id == product.id
    assert p.hub_score >= 0.0


def test_ingestion_run_lifecycle(repo):
    policy, _, _, rid1, _ = _seed(repo)
    run_id = str(ULID())
    repo.create_ingestion_run(
        run_id=run_id, source_path="/docs/refund policy.md",
        source_hash="h1", started_at=now_rfc3339(), extractor_version="v1",
    )
    # running 상태에선 succeeded 조회 안 됨
    assert repo.find_succeeded_run_by_hash(
        source_path="/docs/refund policy.md", source_hash="h1", extractor_version="v1"
    ) is None
    repo.mark_entity_emitted(entity_id=policy.id, run_id=run_id)
    repo.mark_relation_emitted(relation_id=rid1, run_id=run_id)
    repo.finalize_run(
        run_id=run_id, status="succeeded", completed_at=now_rfc3339(),
        emitted_entity_ids=[policy.id], emitted_relation_ids=[rid1],
    )
    found = repo.find_succeeded_run_by_hash(
        source_path="/docs/refund policy.md", source_hash="h1", extractor_version="v1"
    )
    assert found is not None and found.id == run_id
    latest = repo.find_latest_succeeded_run(source_path="/docs/refund policy.md")
    assert latest is not None and latest.id == run_id
    repo.append_emitted_relations(run_id=run_id, relation_ids=[rid1, str(ULID())])
    latest2 = repo.find_latest_succeeded_run(source_path="/docs/refund policy.md")
    assert len(latest2.emitted_relation_ids) == 2  # rid1 dedupe + 1 신규


def test_entity_diff_delete_and_trim(repo):
    # 단일 소스 → 삭제
    e = _entity("temp", "T", [0.5, 0.5, 0.0, 0.0])
    repo.create_entity(entity=e)
    assert repo.apply_entity_diff(
        entity_id=e.id, source_path="/docs/temp.md", run_id="r"
    ) == "deleted"
    assert repo.get_stored_entity(entity_id=e.id) is None
    # 다중 소스 → trim
    now = now_rfc3339()
    e2 = StoredEntity(
        id=str(ULID()), name="multi", type="T", aliases=[], description="",
        properties={},
        source_refs=[SourceRef(source_path="/a.md"), SourceRef(source_path="/b.md")],
        created_at=now, updated_at=now, embedding=[0.1, 0.1, 0.1, 0.1],
        normalized_name="multi",
    )
    repo.create_entity(entity=e2)
    assert repo.apply_entity_diff(
        entity_id=e2.id, source_path="/a.md", run_id="r"
    ) == "trimmed"
    got = repo.get_stored_entity(entity_id=e2.id)
    assert got is not None
    assert [s.source_path for s in got.source_refs] == ["/b.md"]


def test_backend_factory_selects_by_flag(tmp_path):
    """ADR-0020 — 설정 플래그로 백엔드 어댑터를 고른다 (#146 완료 조건)."""
    from arche_api.adapters.graph import Neo4jGraphRepository
    from arche_api.adapters.kuzu_graph import KuzuGraphRepository
    from arche_api.api.deps import build_graph_repository

    base = dict(
        embedding_dimension=DIM,
        kuzu_db_path=str(tmp_path / "factory_db"),
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="x",
    )
    embedded = build_graph_repository(
        types.SimpleNamespace(graph_backend="embedded", **base)
    )
    assert isinstance(embedded, KuzuGraphRepository)
    neo4j = build_graph_repository(
        types.SimpleNamespace(graph_backend="neo4j", **base)
    )
    assert isinstance(neo4j, Neo4jGraphRepository)
    with pytest.raises(ValueError):
        build_graph_repository(types.SimpleNamespace(graph_backend="bogus", **base))


def test_merge_mutation_updates_aliases_and_fts(repo):
    policy, *_ = _seed(repo)
    repo.apply_merge_mutation(mutation=MergeMutation(
        id=policy.id, aliases=["환불", "반품"], description="갱신",
        properties={}, source_refs=policy.source_refs, updated_at=now_rfc3339(),
        normalized_aliases=["환불", "반품"],
    ))
    got = repo.get_stored_entity(entity_id=policy.id)
    assert "반품" in got.aliases
    # 새 alias 가 FTS 재빌드 후 검색돼야 함
    hits = repo.find_by_keywords_scored(keywords=["반품"], limit_per_keyword=5)
    assert any(h.node.id == policy.id for h in hits)


# ---------- 떼어내기 지원 (#B-1) ----------


def test_get_entity_relations_returns_both_directions(repo):
    policy, category, product, _, _ = _seed(repo)

    edges = repo.get_entity_relations(entity_id=category.id)

    assert {(e.from_, e.to) for e in edges} == {
        (policy.id, category.id),
        (category.id, product.id),
    }
    assert all(e.source_refs for e in edges)


def test_move_relation_endpoint_carries_the_relation_over(repo):
    policy, category, product, _, _ = _seed(repo)
    spun_off = _entity("clothing archive", "Category", [0.0, 0.9, 0.0, 0.0])
    repo.create_entity(entity=spun_off)
    before = {e.id: e for e in repo.get_entity_relations(entity_id=category.id)}
    rel_id = next(rid for rid, e in before.items() if e.to == product.id)

    repo.move_relation_endpoint(
        relation_id=rel_id, old_entity_id=category.id, new_entity_id=spun_off.id
    )

    moved = repo.get_entity_relations(entity_id=spun_off.id)
    assert [(e.id, e.from_, e.to) for e in moved] == [(rel_id, spun_off.id, product.id)]
    # 출처와 타입을 그대로 들고 간다 — 옮긴 관계가 원래 그 자리에 있던 것과 같아 보이게.
    assert moved[0].type == before[rel_id].type
    assert [sr.source_path for sr in moved[0].source_refs] == [
        sr.source_path for sr in before[rel_id].source_refs
    ]
    assert [e.to for e in repo.get_entity_relations(entity_id=category.id)] == [category.id]


def test_blocked_aliases_survive_a_round_trip(repo):
    entity = _entity("summer program", "Program", [1.0, 0.0, 0.0, 0.0], aliases=["여름"])
    repo.create_entity(entity=entity)

    repo.apply_merge_mutation(
        mutation=MergeMutation(
            id=entity.id,
            aliases=[],
            description="",
            properties={},
            source_refs=list(entity.source_refs),
            updated_at=now_rfc3339(),
            normalized_aliases=[],
            blocked_aliases=["여름"],
        )
    )

    assert repo.get_stored_entity(entity_id=entity.id).blocked_aliases == ["여름"]


def test_indexes_survive_reopening_the_database(tmp_path):
    """저장소를 다시 열어도 검색이 산다.

    인덱스는 디스크에 남는데 "만들었다" 표시는 프로세스 안에만 있다. 앞선 프로세스가
    만들어 둔 것을 새 프로세스가 없는 줄 알고 다시 만들려 들면 Kuzu 가 거부해, 재기동
    직후 첫 읽기가 통째로 깨진다.
    """
    from arche_api.adapters.kuzu_graph import KuzuGraphRepository

    settings = _settings(tmp_path)
    first = KuzuGraphRepository(settings)
    first.ensure_indexes()
    first.create_entity(entity=_entity("refund policy", "Policy", [1.0, 0.0, 0.0, 0.0]))
    assert first.find_by_keywords_scored(keywords=["refund"], limit_per_keyword=5)
    first.close()

    second = KuzuGraphRepository(settings)
    second.ensure_indexes()
    try:
        assert second.find_by_keywords_scored(keywords=["refund"], limit_per_keyword=5)
        assert second.find_entities_dense(
            query_embedding=[1.0, 0.0, 0.0, 0.0], matched_keyword="refund", limit=5
        )
    finally:
        second.close()


def test_writes_after_reopening_stay_searchable(tmp_path):
    """재기동 뒤에 쓴 노드도 두 색인에 잡힌다.

    쓰기가 인덱스를 더티로 표시하고 다음 읽기가 이를 맞춘다. 이 경로가 벡터 인덱스를
    다시 만들려 들면 같은 이름을 되쓰지 못해 거부당한다.
    """
    from arche_api.adapters.kuzu_graph import KuzuGraphRepository

    settings = _settings(tmp_path)
    first = KuzuGraphRepository(settings)
    first.ensure_indexes()
    first.create_entity(entity=_entity("refund policy", "Policy", [1.0, 0.0, 0.0, 0.0]))
    first.find_by_keywords_scored(keywords=["refund"], limit_per_keyword=5)
    first.close()

    second = KuzuGraphRepository(settings)
    second.ensure_indexes()
    try:
        second.create_entity(entity=_entity("summer dress", "Product", [0.0, 1.0, 0.0, 0.0]))
        assert second.find_by_keywords_scored(keywords=["summer"], limit_per_keyword=5)
        assert second.find_entities_dense(
            query_embedding=[0.0, 1.0, 0.0, 0.0], matched_keyword="summer", limit=5
        )
    finally:
        second.close()


def test_reindex_vector_rebuilds_under_a_fresh_name(repo):
    """reindex 는 새 이름으로 다시 만든다. 지운 이름은 그 DB 에서 되쓸 수 없다."""
    repo.create_entity(entity=_entity("refund policy", "Policy", [1.0, 0.0, 0.0, 0.0]))
    repo.find_entities_dense(
        query_embedding=[1.0, 0.0, 0.0, 0.0], matched_keyword="refund", limit=5
    )

    result = repo.reindex_vector()

    assert result["index"] != "entity_embedding_idx"
    assert repo.find_entities_dense(
        query_embedding=[1.0, 0.0, 0.0, 0.0], matched_keyword="refund", limit=5
    )
