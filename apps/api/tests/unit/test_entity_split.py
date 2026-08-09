"""잘못 합친 노드를 떼어내는 연산 (#B-1).

여기서 지키는 불변은 다섯이다. 확정 전에는 그래프가 그대로다, 관계는 출처를 따라
갈리고 갈리지 않는 건 사람에게 올라온다, 판단이 남아 있으면 확정이 거부된다,
떼어낸 노드는 원래부터 있던 노드와 같은 자격을 갖는다, 가른 뒤 재적재가 둘을 다시
합치지 않는다.
"""

from __future__ import annotations

import pytest

from arche_api.domain.entity_split import SplitService
from arche_api.domain.errors import (
    EntityNotFoundError,
    InvalidInputError,
    UnprocessableError,
)
from arche_api.domain.identity import EntityMerger, normalize
from arche_api.domain.models import ExtractedEntity, SourceRef

from .test_ingest_service import FakeEmbedder, FakeGraph

CONTRACT = "/docs/계약.md"
TERMS = "/docs/약관.md"


def _seed_merged_node(graph: FakeGraph) -> str:
    """서로 다른 둘("여름 프로모션"과 "여름 정산")이 한 노드로 뭉친 상태를 만든다."""
    from arche_api.domain.models import StoredEntity, now_rfc3339

    now = now_rfc3339()
    entity = StoredEntity(
        id="01J8XR4K9ZQ2N7M3VB0W4D6TYE",
        name="여름 프로모션",
        type="Program",
        aliases=["여름 정산", "썸머 프로모션"],
        description="여름에 도는 것들",
        properties={},
        source_refs=[SourceRef(source_path=CONTRACT), SourceRef(source_path=TERMS)],
        created_at=now,
        updated_at=now,
        embedding=[0.1] * 8,
        namespace_id="default",
        normalized_name=normalize("여름 프로모션"),
        normalized_aliases=[normalize("여름 정산"), normalize("썸머 프로모션")],
    )
    graph.create_entity(entity=entity)
    return entity.id


def _seed_neighbor(graph: FakeGraph, *, eid: str, name: str) -> str:
    from arche_api.domain.models import StoredEntity, now_rfc3339

    now = now_rfc3339()
    graph.create_entity(
        entity=StoredEntity(
            id=eid,
            name=name,
            type="Policy",
            aliases=[],
            description=None,
            properties={},
            source_refs=[],
            created_at=now,
            updated_at=now,
            embedding=[0.2] * 8,
            namespace_id="default",
            normalized_name=normalize(name),
        )
    )
    return eid


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph()


@pytest.fixture
def service(graph: FakeGraph) -> SplitService:
    return SplitService(graph=graph, embedder=FakeEmbedder())


def test_plan_does_not_touch_the_graph(graph, service):
    origin_id = _seed_merged_node(graph)
    before = dict(graph._entities)

    service.plan_split(
        plan_id="spl_1",
        entity_id=origin_id,
        new_name="여름 정산",
        move_aliases=["여름 정산"],
        move_source_paths=[TERMS],
    )

    assert graph._entities == before


def test_commit_splits_aliases_and_sources(graph, service):
    origin_id = _seed_merged_node(graph)
    plan = service.plan_split(
        plan_id="spl_1",
        entity_id=origin_id,
        new_name="여름 정산",
        move_source_paths=[TERMS],
    )
    plan.previewed = True

    result = service.commit_split(plan)

    origin = graph.get_stored_entity(entity_id=origin_id)
    new = graph.get_stored_entity(entity_id=result.new_entity_id)
    assert new.name == "여름 정산"
    assert [sr.source_path for sr in new.source_refs] == [TERMS]
    assert [sr.source_path for sr in origin.source_refs] == [CONTRACT]
    # new_name 이던 별칭은 원래 노드에서 빠진다. 남으면 그 이름으로 옛 노드가 계속 잡힌다.
    assert "여름 정산" not in origin.aliases
    assert normalize("여름 정산") not in origin.normalized_aliases


def test_split_node_is_a_first_class_node(graph, service):
    """떼어낸 노드도 자기 임베딩과 정규화 색인, 설명, 타입을 갖춘다."""
    origin_id = _seed_merged_node(graph)
    plan = service.plan_split(
        plan_id="spl_1",
        entity_id=origin_id,
        new_name="여름 정산",
        move_aliases=["썸머 프로모션"],
        move_source_paths=[TERMS],
    )
    plan.previewed = True
    result = service.commit_split(plan)

    new = graph.get_stored_entity(entity_id=result.new_entity_id)
    assert new.type == "Program"
    assert new.embedding
    assert new.normalized_name == normalize("여름 정산")
    assert new.normalized_aliases == [normalize("썸머 프로모션")]
    assert new.description == "여름에 도는 것들"
    # 이름으로 바로 찾힌다 — 원래부터 있던 노드와 같은 자격.
    found = graph.find_by_normalized_name(normalized=normalize("여름 정산"), type_="Program")
    assert found.id == new.id


def test_new_description_overrides_the_inherited_one(graph, service):
    origin_id = _seed_merged_node(graph)
    plan = service.plan_split(
        plan_id="spl_1",
        entity_id=origin_id,
        new_name="여름 정산",
        move_source_paths=[TERMS],
        new_description="여름 매출을 정산하는 절차",
    )

    assert plan.new_entity.description == "여름 매출을 정산하는 절차"


# ---------- 관계 배분 ----------


def test_relations_follow_their_source(graph, service):
    origin_id = _seed_merged_node(graph)
    a = _seed_neighbor(graph, eid="01J8XR5M2NPQ3R7S4TU5V6W7XY", name="환불 정책")
    b = _seed_neighbor(graph, eid="01J8XR6N3PQR4S7T5UV6W7X8YZ", name="정산 정책")
    rel_a, _ = graph.upsert_relation(
        from_id=origin_id, to_id=a, rel_type="APPLIES_TO", source_ref=SourceRef(source_path=CONTRACT)
    )
    rel_b, _ = graph.upsert_relation(
        from_id=origin_id, to_id=b, rel_type="APPLIES_TO", source_ref=SourceRef(source_path=TERMS)
    )

    plan = service.plan_split(
        plan_id="spl_1",
        entity_id=origin_id,
        new_name="여름 정산",
        move_source_paths=[TERMS],
    )

    by_id = {a.relation_id: a for a in plan.assignments}
    assert by_id[rel_a].decision == "keep"
    assert by_id[rel_b].decision == "move"
    assert plan.open_questions == []


def test_relation_spanning_both_sides_becomes_a_question(graph, service):
    origin_id = _seed_merged_node(graph)
    a = _seed_neighbor(graph, eid="01J8XR5M2NPQ3R7S4TU5V6W7XY", name="환불 정책")
    rel, _ = graph.upsert_relation(
        from_id=origin_id, to_id=a, rel_type="APPLIES_TO", source_ref=SourceRef(source_path=CONTRACT)
    )
    graph.upsert_relation(
        from_id=origin_id, to_id=a, rel_type="APPLIES_TO", source_ref=SourceRef(source_path=TERMS)
    )

    plan = service.plan_split(
        plan_id="spl_1",
        entity_id=origin_id,
        new_name="여름 정산",
        move_source_paths=[TERMS],
    )

    questions = plan.open_questions
    assert [q.relation_id for q in questions] == [rel]
    assert questions[0].reason == "출처가 양쪽에 걸침"


def test_commit_refuses_while_a_relation_is_undecided(graph, service):
    origin_id = _seed_merged_node(graph)
    a = _seed_neighbor(graph, eid="01J8XR5M2NPQ3R7S4TU5V6W7XY", name="환불 정책")
    graph.upsert_relation(
        from_id=origin_id, to_id=a, rel_type="APPLIES_TO", source_ref=SourceRef(source_path=CONTRACT)
    )
    graph.upsert_relation(
        from_id=origin_id, to_id=a, rel_type="APPLIES_TO", source_ref=SourceRef(source_path=TERMS)
    )
    plan = service.plan_split(
        plan_id="spl_1",
        entity_id=origin_id,
        new_name="여름 정산",
        move_source_paths=[TERMS],
    )
    plan.previewed = True

    with pytest.raises(UnprocessableError):
        service.commit_split(plan)


def test_human_decision_settles_the_question(graph, service):
    origin_id = _seed_merged_node(graph)
    a = _seed_neighbor(graph, eid="01J8XR5M2NPQ3R7S4TU5V6W7XY", name="환불 정책")
    rel, _ = graph.upsert_relation(
        from_id=origin_id, to_id=a, rel_type="APPLIES_TO", source_ref=SourceRef(source_path=CONTRACT)
    )
    graph.upsert_relation(
        from_id=origin_id, to_id=a, rel_type="APPLIES_TO", source_ref=SourceRef(source_path=TERMS)
    )

    plan = service.plan_split(
        plan_id="spl_2",
        entity_id=origin_id,
        new_name="여름 정산",
        move_source_paths=[TERMS],
        relation_decisions={rel: "move"},
    )
    plan.previewed = True
    result = service.commit_split(plan)

    assert plan.open_questions == []
    assert result.relations_moved == 1
    moved = graph.get_entity_relations(entity_id=result.new_entity_id)
    assert [e.type for e in moved] == ["APPLIES_TO"]
    assert graph.get_entity_relations(entity_id=origin_id) == []


def test_moved_relation_keeps_its_sources(graph, service):
    """옮긴 관계도 원래부터 그 자리에 있던 것처럼 출처를 그대로 들고 간다."""
    origin_id = _seed_merged_node(graph)
    a = _seed_neighbor(graph, eid="01J8XR5M2NPQ3R7S4TU5V6W7XY", name="환불 정책")
    graph.upsert_relation(
        from_id=origin_id, to_id=a, rel_type="APPLIES_TO", source_ref=SourceRef(source_path=TERMS)
    )

    plan = service.plan_split(
        plan_id="spl_1",
        entity_id=origin_id,
        new_name="여름 정산",
        move_source_paths=[TERMS],
    )
    plan.previewed = True
    result = service.commit_split(plan)

    moved = graph.get_entity_relations(entity_id=result.new_entity_id)
    assert [sr.source_path for sr in moved[0].source_refs] == [TERMS]


def test_without_source_split_every_relation_is_a_question(graph, service):
    """출처를 나누지 않으면 관계를 가를 근거가 없다 — 전부 사람에게 묻는다."""
    origin_id = _seed_merged_node(graph)
    a = _seed_neighbor(graph, eid="01J8XR5M2NPQ3R7S4TU5V6W7XY", name="환불 정책")
    graph.upsert_relation(
        from_id=origin_id, to_id=a, rel_type="APPLIES_TO", source_ref=SourceRef(source_path=TERMS)
    )

    plan = service.plan_split(
        plan_id="spl_1",
        entity_id=origin_id,
        new_name="여름 정산",
        move_aliases=["여름 정산"],
    )

    assert len(plan.open_questions) == 1
    assert plan.open_questions[0].reason == "출처를 나누지 않아 판단 근거가 없음"


# ---------- 가른 결정이 재적재를 견딘다 ----------


def test_split_survives_reingestion(graph, service):
    """재적재의 별칭 union 이 갈라 둔 결정을 되돌리지 못한다."""
    origin_id = _seed_merged_node(graph)
    plan = service.plan_split(
        plan_id="spl_1",
        entity_id=origin_id,
        new_name="여름 정산",
        move_source_paths=[TERMS],
    )
    plan.previewed = True
    service.commit_split(plan)
    origin = graph.get_stored_entity(entity_id=origin_id)

    # 같은 문서를 다시 적재하면 "여름 프로모션 (여름 정산)" 이 또 추출된다.
    mutation = EntityMerger.merge(
        origin,
        ExtractedEntity(name="여름 프로모션", type="Program", aliases=["여름 정산"]),
        SourceRef(source_path=CONTRACT),
        "2026-08-09T00:00:00Z",
    )

    assert "여름 정산" not in mutation.aliases
    assert normalize("여름 정산") not in mutation.normalized_aliases


def test_blocked_name_is_skipped_by_the_vector_matcher(graph, service):
    """임베딩이 아무리 가까워도 사람이 갈라 놓은 이름은 그 노드로 안 붙는다."""
    from arche_api.domain.identity import EntityMatcher

    origin_id = _seed_merged_node(graph)
    plan = service.plan_split(
        plan_id="spl_1",
        entity_id=origin_id,
        new_name="여름 정산",
        move_source_paths=[TERMS],
    )
    plan.previewed = True
    new_id = service.commit_split(plan).new_entity_id

    origin = graph.get_stored_entity(entity_id=origin_id)
    assert normalize("여름 정산") in origin.blocked_aliases
    new = graph.get_stored_entity(entity_id=new_id)
    assert normalize("여름 프로모션") in new.blocked_aliases

    matcher = EntityMatcher(repo=graph, embedder=FakeEmbedder())
    hit = matcher.match(ExtractedEntity(name="여름 정산", type="Program"))
    assert hit.existing is not None
    assert hit.existing.id == new_id


# ---------- 입력 거절 ----------


def test_unknown_entity_is_404(service):
    with pytest.raises(EntityNotFoundError):
        service.plan_split(
            plan_id="spl_1",
            entity_id="01J8XR4K9ZQ2N7M3VB0W4D6TYE",
            new_name="x",
            move_source_paths=["/a.md"],
        )


def test_rejects_moving_every_source(graph, service):
    origin_id = _seed_merged_node(graph)
    with pytest.raises(InvalidInputError):
        service.plan_split(
            plan_id="spl_1",
            entity_id=origin_id,
            new_name="여름 정산",
            move_source_paths=[CONTRACT, TERMS],
        )


def test_rejects_alias_the_node_never_had(graph, service):
    origin_id = _seed_merged_node(graph)
    with pytest.raises(InvalidInputError):
        service.plan_split(
            plan_id="spl_1",
            entity_id=origin_id,
            new_name="여름 정산",
            move_aliases=["없는 별칭"],
        )


def test_rejects_new_name_equal_to_origin(graph, service):
    origin_id = _seed_merged_node(graph)
    with pytest.raises(InvalidInputError):
        service.plan_split(
            plan_id="spl_1",
            entity_id=origin_id,
            new_name="여름 프로모션",
            move_source_paths=[TERMS],
        )


def test_rejects_when_nothing_is_being_moved(graph, service):
    origin_id = _seed_merged_node(graph)
    with pytest.raises(InvalidInputError):
        service.plan_split(plan_id="spl_1", entity_id=origin_id, new_name="여름 정산")
