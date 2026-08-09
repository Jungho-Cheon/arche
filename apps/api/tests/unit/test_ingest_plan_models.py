import pytest
from pydantic import ValidationError

from arche_api.api.plan_registry import PlanRegistry
from arche_api.api.plan_schemas import QuestionView
from arche_api.domain.ingest import IngestResult
from arche_api.domain.ingest_plan import IngestPlan, PlanQuestionKind, RecordedWrite


def _question(kind: object) -> dict:
    return {
        "question_id": "q1",
        "extracted_name": "A",
        "extracted_type": "Company",
        "candidate_id": "01H",
        "candidate_name": "A Inc",
        "similarity": 0.9,
        "kind": kind,
    }


def test_plan_question_kind_is_closed_set():
    # #105 — kind 는 닫힌 목록. 값을 더하면 응답 계약이 바뀌므로 여기도 함께 고친다.
    assert [k.value for k in PlanQuestionKind] == [
        "possible_missed_merge",
        "same_name_different_type",
    ]


def test_plan_question_accepts_known_kind():
    q = QuestionView(**_question("possible_missed_merge"))
    assert q.kind is PlanQuestionKind.POSSIBLE_MISSED_MERGE
    # str 상속이라 값 문자열과도 동등 — 기존 소비자 호환.
    assert q.kind == "possible_missed_merge"


def test_plan_question_rejects_unknown_kind():
    # 목록에 없는 종류는 스키마 검증에서 거부된다 (계약 고정).
    with pytest.raises(ValidationError):
        QuestionView(**_question("something_else"))


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
