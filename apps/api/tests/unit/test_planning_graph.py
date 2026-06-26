from arche_api.domain.models import StoredEntity, MergeMutation, SourceRef
from arche_api.domain.planning_graph import PlanningGraphRepository
from arche_api.test_support import FakeGraph  # existing GraphRepository double


def _stored(id_: str, name: str, norm: str) -> StoredEntity:
    return StoredEntity(
        id=id_, name=name, type="Org", aliases=[], description=None,
        properties={}, source_refs=[], created_at="t", updated_at="t",
        embedding=[0.0], normalized_name=norm,
    )


def test_writes_are_recorded_not_executed():
    real = FakeGraph()
    planning = PlanningGraphRepository(real)
    planning.create_entity(entity=_stored("01H", "Acme", "acme"))
    assert real.find_by_normalized_name(normalized="acme", type_="Org") is None
    assert [w.method for w in planning.writes] == ["create_entity"]


def test_normalized_overlay_sees_pending_entity():
    real = FakeGraph()
    planning = PlanningGraphRepository(real)
    planning.create_entity(entity=_stored("01H", "Acme", "acme"))
    hit = planning.find_by_normalized_name(normalized="acme", type_="Org")
    assert hit is not None and hit.id == "01H"


def test_merge_records_before_snapshot():
    real = FakeGraph()
    real.create_entity(entity=_stored("01H", "Acme", "acme"))
    planning = PlanningGraphRepository(real)
    mut = MergeMutation(
        id="01H", aliases=["AcmeCorp"], description="d", properties={},
        source_refs=[SourceRef(source_path="/a.md")], updated_at="t2",
    )
    planning.apply_merge_mutation(mutation=mut)
    rec = planning.writes[-1]
    assert rec.method == "apply_merge_mutation"
    assert rec.before is not None and rec.before.id == "01H"
