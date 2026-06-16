"""차분 적용 — 이전 회차 emitted set 과 새 회차 emitted set 의 차이가
어떻게 delete / trim / no-op 로 매핑되는지.

WHY 별도 파일: 차분 로직은 IngestService._apply_diff 안에 있지만, 동작 자체는
*repo 의 apply_entity_diff / apply_relation_diff* 가 노드 상태를 기준으로
결정한다. 본 테스트는 그 라우팅 (어떤 ID 가 어떤 콜백으로 가는가) 을 굳힌다.
"""

from __future__ import annotations

from opentology_api.adapters.graph import IngestionRunRecord
from opentology_api.domain.ingest import IngestService


class _CallRecorder:
    def __init__(self, entity_outcomes: dict[str, str], rel_outcomes: dict[str, str]):
        self._entity_outcomes = entity_outcomes
        self._rel_outcomes = rel_outcomes
        self.entity_calls: list[str] = []
        self.relation_calls: list[str] = []

    def apply_entity_diff(self, *, entity_id, source_path, run_id):
        self.entity_calls.append(entity_id)
        return self._entity_outcomes.get(entity_id, "missing")

    def apply_relation_diff(self, *, relation_id, source_path):
        self.relation_calls.append(relation_id)
        return self._rel_outcomes.get(relation_id, "missing")


def _make_prior(entity_ids, relation_ids):
    return IngestionRunRecord(
        id="run_prev",
        source_path="/s.md",
        source_hash="hashA",
        started_at="2026-06-15T00:00:00Z",
        completed_at="2026-06-15T00:00:10Z",
        status="succeeded",
        emitted_entity_ids=list(entity_ids),
        emitted_relation_ids=list(relation_ids),
    )


def _make_service_with(recorder: _CallRecorder) -> IngestService:
    # repository 를 통째로 mock — IngestService 의 _apply_diff 만 직접 호출.
    svc = IngestService.__new__(IngestService)
    svc._graph = recorder  # type: ignore[attr-defined]
    svc._llm = None  # type: ignore[attr-defined]
    svc._embedder = None  # type: ignore[attr-defined]
    return svc


def test_diff_routes_only_unhandled_ids_to_repo_callbacks():
    prior = _make_prior(["E1", "E2", "E3"], ["R1", "R2"])
    rec = _CallRecorder(
        entity_outcomes={"E2": "deleted", "E3": "trimmed"},
        rel_outcomes={"R2": "deleted"},
    )
    svc = _make_service_with(rec)
    metrics = svc._apply_diff(
        prior=prior,
        new_entity_ids={"E1"},  # E2, E3 가 사라짐
        new_relation_ids={"R1"},  # R2 가 사라짐
        source_path="/s.md",
        run_id="run_new",
    )
    assert metrics == {
        "entities_deleted": 1,
        "entities_trimmed": 1,
        "relations_deleted": 1,
        "relations_trimmed": 0,
    }
    assert sorted(rec.entity_calls) == ["E2", "E3"]
    assert rec.relation_calls == ["R2"]


def test_diff_no_prior_run_is_noop():
    rec = _CallRecorder(entity_outcomes={}, rel_outcomes={})
    svc = _make_service_with(rec)
    metrics = svc._apply_diff(
        prior=None,
        new_entity_ids={"E1"},
        new_relation_ids={"R1"},
        source_path="/s.md",
        run_id="run_new",
    )
    assert metrics == {
        "entities_deleted": 0,
        "entities_trimmed": 0,
        "relations_deleted": 0,
        "relations_trimmed": 0,
    }
    assert rec.entity_calls == []
    assert rec.relation_calls == []


def test_diff_kept_entities_are_not_passed_to_repo():
    """이번 회차에서 다시 emit 된 엔티티/관계는 차분 콜백을 건드리지 않는다."""
    prior = _make_prior(["E1", "E2"], ["R1"])
    rec = _CallRecorder(entity_outcomes={}, rel_outcomes={})
    svc = _make_service_with(rec)
    svc._apply_diff(
        prior=prior,
        new_entity_ids={"E1", "E2"},
        new_relation_ids={"R1"},
        source_path="/s.md",
        run_id="run_new",
    )
    assert rec.entity_calls == []
    assert rec.relation_calls == []
