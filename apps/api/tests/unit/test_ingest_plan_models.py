from arche_api.api.plan_registry import PlanRegistry
from arche_api.domain.ingest import IngestResult
from arche_api.domain.ingest_plan import IngestPlan, RecordedWrite


def _plan(plan_id: str = "pln_1") -> IngestPlan:
    return IngestPlan(
        plan_id=plan_id,
        source_path="/x/a.md",
        source_hash="h",
        extractor_version="p2:abc",
        created_at="2026-06-27T00:00:00Z",
        previewed=False,
        writes=[RecordedWrite(method="create_entity", kwargs={"entity": object()})],
        result=IngestResult(
            source_path="/x/a.md",
            entities_created=1,
            entities_updated=0,
            relations_created=0,
            relations_skipped_dangling=0,
            entity_ids=["01H"],
        ),
        depends_on_entity_ids=[],
    )


def test_registry_roundtrip_and_mark_previewed():
    reg = PlanRegistry()
    reg.create(_plan("pln_1"))
    assert reg.get("pln_1").previewed is False
    reg.mark_previewed("pln_1")
    assert reg.get("pln_1").previewed is True
    assert reg.get("missing") is None
