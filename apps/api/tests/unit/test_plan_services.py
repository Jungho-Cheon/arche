"""plan/preview/commit 서비스 함수의 안전 latch 검증.

핵심 불변 (브리프 Task 4): commit 은 *미리보기를 거친 계획에 한해서만* 진행된다.
사용자가 변경 묶음을 눈으로 확인하기 전에 그래프를 건드리는 사고를 막는다.
"""

from __future__ import annotations

import pytest

from arche_api.api import services
from arche_api.api.plan_registry import PlanRegistry
from arche_api.api.plan_schemas import (
    CommitRequest,
    PlanIngestRequest,
    PreviewRequest,
)
from arche_api.domain.errors import InvalidInputError, UnprocessableError
from arche_api.domain.ingest import IngestResult
from arche_api.domain.ingest_plan import IngestPlan, RecordedWrite
from arche_api.domain.models import MergeMutation, StoredEntity


def _stored_entity(
    *, eid: str, name: str, etype: str, aliases: list[str]
) -> StoredEntity:
    """테스트용 StoredEntity — 미리보기 직렬화에 쓰이는 필드만 의미값, 나머지는 빈값."""
    return StoredEntity(
        id=eid,
        name=name,
        type=etype,
        aliases=aliases,
        description=None,
        properties={},
        source_refs=[],
        created_at="2026-06-27T00:00:00Z",
        updated_at="2026-06-27T00:00:00Z",
        embedding=[],
    )


def test_commit_refuses_without_preview(make_plan, fake_service):
    reg = PlanRegistry()
    reg.create(make_plan(previewed=False))
    with pytest.raises(UnprocessableError):
        services.commit_plan(
            CommitRequest(plan_id="pln_1"), service=fake_service, registry=reg
        )


def test_preview_sets_flag_then_commit_ok(make_plan, fake_service):
    reg = PlanRegistry()
    reg.create(make_plan(previewed=False))
    services.preview_plan(PreviewRequest(plan_id="pln_1"), registry=reg)
    assert reg.get("pln_1").previewed is True
    services.commit_plan(
        CommitRequest(plan_id="pln_1"), service=fake_service, registry=reg
    )


# ---------- Important 1: preview 직렬화 (writes → view) ----------


def test_preview_serializes_writes(make_plan):
    """preview 가 writes 의 각 종류를 알맞은 view 로 펼치는지 검증.

    create_entity → NewEntityView, apply_merge_mutation → MergeView,
    upsert_relation → RelationView, apply_entity_diff → deletion_count.
    """
    new_entity = _stored_entity(
        eid="01HNEW", name="결제 모듈", etype="Service", aliases=["pay", "billing"]
    )
    before_entity = _stored_entity(
        eid="01HTARGET", name="기존 결제", etype="Service", aliases=["old"]
    )
    mutation = MergeMutation(
        id="01HTARGET",
        aliases=["pay", "billing", "old"],
        description="병합 결과",
        properties={},
        source_refs=[],
        updated_at="2026-06-27T00:00:00Z",
    )
    writes = [
        RecordedWrite("create_entity", {"entity": new_entity}),
        RecordedWrite(
            "apply_merge_mutation",
            {"mutation": mutation},
            before=before_entity,
        ),
        RecordedWrite(
            "upsert_relation",
            {"from_id": "01HNEW", "to_id": "01HTARGET", "rel_type": "depends_on"},
        ),
        RecordedWrite("apply_entity_diff", {"diff": object()}),
    ]
    reg = PlanRegistry()
    reg.create(make_plan(writes=writes))

    preview = services.preview_plan(PreviewRequest(plan_id="pln_1"), registry=reg)

    assert len(preview.new_entities) == 1
    assert preview.new_entities[0].name == "결제 모듈"
    assert preview.new_entities[0].type == "Service"
    assert preview.new_entities[0].aliases == ["pay", "billing"]

    assert len(preview.merges) == 1
    assert preview.merges[0].target_id == mutation.id
    assert preview.merges[0].before_name == before_entity.name
    assert preview.merges[0].after_aliases == mutation.aliases

    assert len(preview.new_relations) == 1
    assert preview.new_relations[0].from_id == "01HNEW"
    assert preview.new_relations[0].to_id == "01HTARGET"
    assert preview.new_relations[0].type == "depends_on"

    assert preview.deletion_count == 1


# ---------- Important 2: stale latch (의존 노드 소멸) ----------


def test_commit_refuses_when_dependency_is_stale(make_plan):
    """미리보기를 거쳤어도 의존 노드가 사라졌으면 422 (stale; re-plan)."""
    from .conftest import _FakeGraph, _FakeService

    service = _FakeService(_FakeGraph(exists=False))
    reg = PlanRegistry()
    reg.create(
        make_plan(previewed=True, depends_on_entity_ids=["01HMISSING"])
    )
    with pytest.raises(UnprocessableError, match="stale"):
        services.commit_plan(
            CommitRequest(plan_id="pln_1"), service=service, registry=reg
        )


# ---------- Minor: 알 수 없는 plan_id ----------


def test_commit_unknown_plan_id_raises_invalid_input(fake_service):
    reg = PlanRegistry()
    with pytest.raises(InvalidInputError):
        services.commit_plan(
            CommitRequest(plan_id="pln_missing"), service=fake_service, registry=reg
        )


def test_preview_unknown_plan_id_raises_invalid_input():
    reg = PlanRegistry()
    with pytest.raises(InvalidInputError):
        services.preview_plan(PreviewRequest(plan_id="pln_missing"), registry=reg)


# ---------- Minor: plan_ingest 의 개수 집계 ----------


class _StubPlanService:
    """plan_file 만 흉내내는 IngestService 대역 — 주어진 writes 로 plan 을 만든다."""

    def __init__(self, writes: list[RecordedWrite]) -> None:
        self._writes = writes

    def plan_file(self, path) -> IngestPlan:  # noqa: ANN001
        return IngestPlan(
            plan_id="pln_stub",
            source_path=str(path),
            source_hash="deadbeef",
            extractor_version="p2:test",
            created_at="2026-06-27T00:00:00Z",
            previewed=False,
            writes=self._writes,
            result=IngestResult(
                source_path=str(path),
                entities_created=0,
                entities_updated=0,
                relations_created=0,
                relations_skipped_dangling=0,
                entity_ids=[],
            ),
            depends_on_entity_ids=[],
        )


def test_plan_ingest_tallies_write_counts():
    """plan_ingest 의 PlanSummary 카운터가 writes 종류별 개수와 일치하는지."""
    entity = _stored_entity(
        eid="01HE", name="n", etype="t", aliases=[]
    )
    mutation = MergeMutation(
        id="01HM",
        aliases=[],
        description="",
        properties={},
        source_refs=[],
        updated_at="2026-06-27T00:00:00Z",
    )
    writes = [
        RecordedWrite("create_entity", {"entity": entity}),
        RecordedWrite("create_entity", {"entity": entity}),
        RecordedWrite("apply_merge_mutation", {"mutation": mutation}),
        RecordedWrite(
            "upsert_relation",
            {"from_id": "a", "to_id": "b", "rel_type": "r"},
        ),
        RecordedWrite("apply_entity_diff", {"diff": object()}),
        RecordedWrite("apply_relation_diff", {"diff": object()}),
    ]
    service = _StubPlanService(writes)
    reg = PlanRegistry()

    summary = services.plan_ingest(
        PlanIngestRequest(path="/tmp/a.md"), service=service, registry=reg
    )

    assert summary.entities_created == 2
    assert summary.entities_merged == 1
    assert summary.relations_created == 1
    assert summary.deletion_count == 2
    # plan 이 레지스트리에 보관됐는지도 확인 (이후 preview/commit 가능).
    assert reg.get("pln_stub") is not None
