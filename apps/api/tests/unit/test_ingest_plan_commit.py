"""IngestService.plan_file / commit_plan — record/replay 동일성 검증 (Task 3).

WHY 기존 더블 재사용: test_ingest_service.py 의 FakeGraph / FakeEmbedder / FakeLLM
는 이미 4 단계 매처 + 관계 upsert + 차분 흐름을 충실히 흉내낸다. 새 더블을 만들지
않고 그대로 재사용해 plan(쓰지 않음) → commit(재생) 결과가 *직접 ingest* 와
카운트까지 동일함을 비교한다. (test_support.FakeGraph 는 관계를 저장하지 않아
동일성 비교에는 부적합 — 그래서 unit 쪽 더블을 쓴다.)
"""

from __future__ import annotations

from pathlib import Path

from arche_api.domain.ingest import IngestResult, IngestService
from arche_api.domain.ingest_plan import IngestPlan, RecordedWrite
from arche_api.domain.models import (
    ExtractedEntity,
    ExtractedGraph,
    ExtractedRelation,
)

# 검증된 ingest 흐름 더블을 그대로 재사용 (DRY — 새 더블 금지).
from tests.unit.test_ingest_service import FakeEmbedder, FakeGraph, FakeLLM


def _extracted() -> ExtractedGraph:
    """문서 "Acme Corp acquired Beta Inc." 에 대응하는 결정적 추출 결과."""
    return ExtractedGraph(
        entities=[
            ExtractedEntity(name="Acme Corp", type="company"),
            ExtractedEntity(name="Beta Inc", type="company"),
        ],
        relations=[
            ExtractedRelation(
                from_name="Acme Corp", to_name="Beta Inc", type="acquired"
            )
        ],
    )


def _service(graph: FakeGraph) -> IngestService:
    # 기존 unit 더블 조립 패턴 재사용 (test_ingest_service._build_service 와 동일 형태).
    return IngestService(
        llm=FakeLLM(_extracted()), embedder=FakeEmbedder(), graph=graph
    )


def test_plan_does_not_write_then_commit_matches_direct_ingest(tmp_path: Path):
    doc = tmp_path / "a.md"
    doc.write_text("Acme Corp acquired Beta Inc.", encoding="utf-8")

    # plan_file 은 그래프에 쓰지 않고 변경 묶음만 기록한다.
    g1 = FakeGraph()
    svc1 = _service(g1)
    plan = svc1.plan_file(doc)
    assert len(g1._entities) == 0  # 계획만 — 실제 그래프는 비어 있어야 한다.
    assert len(plan.writes) > 0
    assert plan.source_hash != ""

    # commit_plan 은 기록된 쓰기를 진짜 그래프에 재생한다.
    g2 = FakeGraph()
    committed = _service(g2).commit_plan(plan)

    # 비교 기준 — 같은 문서를 직접 ingest 했을 때.
    g3 = FakeGraph()
    direct = _service(g3).ingest_file(doc)

    assert committed.entities_created == direct.entities_created
    assert committed.relations_created == direct.relations_created
    # commit 이 진짜 그래프에 노드 2 + 관계 1 을 실제로 만들었는지.
    assert len(g2._entities) == len(g3._entities) == 2
    assert len(g2._relations) == len(g3._relations) == 1
    # 신선 파일 경로는 어떤 삭제·trim 도 만들지 않는다 (회귀 가드 — issue #88).
    assert committed.entities_deleted == direct.entities_deleted == 0
    assert committed.entities_trimmed == direct.entities_trimmed == 0
    assert committed.relations_deleted == direct.relations_deleted == 0
    assert committed.relations_trimmed == direct.relations_trimmed == 0


class _RecordingGraph:
    """commit_plan 재생만 검증하는 가벼운 더블 (issue #88).

    WHY 별도 더블: 삭제/trim 분리 테스트는 apply_*_diff 의 반환을 호출마다
    통제해야 하고, 합성 id 치환 테스트는 mark_relation_emitted / finalize_run /
    append_emitted_relations 가 실제로 받은 인자를 그대로 포착해야 한다. 기존
    FakeGraph 의 apply_*_diff 는 엔티티 상태로 결과를 결정해 통제가 어렵고,
    emit 기록은 set 으로 합쳐 호출 인자 원형을 잃는다 — 그래서 호출 인자를
    있는 그대로 기록·재생하는 최소 더블을 둔다.
    """

    def __init__(
        self,
        *,
        rel_returns: list[str] | None = None,
        entity_diff_by_id: dict[str, str] | None = None,
        relation_diff_by_id: dict[str, str] | None = None,
    ) -> None:
        # upsert_relation 이 순서대로 돌려줄 진짜 id 큐.
        self._rel_returns = list(rel_returns or [])
        self._entity_diff_by_id = entity_diff_by_id or {}
        self._relation_diff_by_id = relation_diff_by_id or {}
        self.upsert_relation_calls: list[dict] = []
        self.mark_relation_emitted_calls: list[dict] = []
        self.finalize_run_calls: list[dict] = []
        self.append_emitted_relations_calls: list[dict] = []

    def upsert_relation(self, **kwargs) -> tuple[str, bool]:
        self.upsert_relation_calls.append(kwargs)
        real_id = self._rel_returns.pop(0)
        return real_id, True

    def mark_relation_emitted(self, *, relation_id: str, run_id: str) -> None:
        self.mark_relation_emitted_calls.append(
            {"relation_id": relation_id, "run_id": run_id}
        )

    def finalize_run(self, **kwargs) -> None:
        self.finalize_run_calls.append(kwargs)

    def append_emitted_relations(self, **kwargs) -> None:
        self.append_emitted_relations_calls.append(kwargs)

    def apply_entity_diff(self, *, entity_id: str, **_) -> str:
        return self._entity_diff_by_id[entity_id]

    def apply_relation_diff(self, *, relation_id: str, **_) -> str:
        return self._relation_diff_by_id[relation_id]


def _bare_result() -> IngestResult:
    return IngestResult(
        source_path="x.md",
        entities_created=0,
        entities_updated=0,
        relations_created=0,
        relations_skipped_dangling=0,
        entity_ids=[],
    )


def _plan(writes: list[RecordedWrite]) -> IngestPlan:
    return IngestPlan(
        plan_id="pln_test",
        source_path="x.md",
        source_hash="h",
        extractor_version="v",
        created_at="t",
        previewed=False,
        writes=writes,
        result=_bare_result(),
    )


def _commit_service(graph: _RecordingGraph) -> IngestService:
    # commit_plan 은 llm/embedder 를 쓰지 않는다. 컨텍스트 동봉 빌더는 끄고
    # 재생 경로만 통과시킨다.
    return IngestService(
        llm=FakeLLM(_extracted()),
        embedder=FakeEmbedder(),
        graph=graph,  # type: ignore[arg-type]
        enable_context_aware_extraction=False,
    )


def test_commit_plan_splits_deletion_and_trim_counts():
    """apply_*_diff 의 실제 반환으로 네 카운터를 분리 집계한다 (issue #88)."""
    graph = _RecordingGraph(
        entity_diff_by_id={"e_del": "deleted", "e_trim": "trimmed"},
        relation_diff_by_id={"r_del": "deleted", "r_trim": "trimmed"},
    )
    plan = _plan(
        [
            RecordedWrite(
                "apply_entity_diff",
                {"entity_id": "e_del", "source_path": "x.md", "run_id": "run1"},
            ),
            RecordedWrite(
                "apply_entity_diff",
                {"entity_id": "e_trim", "source_path": "x.md", "run_id": "run1"},
            ),
            RecordedWrite(
                "apply_relation_diff",
                {"relation_id": "r_del", "source_path": "x.md"},
            ),
            RecordedWrite(
                "apply_relation_diff",
                {"relation_id": "r_trim", "source_path": "x.md"},
            ),
        ]
    )

    result = _commit_service(graph).commit_plan(plan)

    assert result.entities_deleted == 1
    assert result.entities_trimmed == 1
    assert result.relations_deleted == 1
    assert result.relations_trimmed == 1


def test_commit_plan_substitutes_synthetic_relation_id():
    """합성 plan_rel_N 을 mark/finalize/append 전반에서 진짜 id 로 치환 (issue #88)."""
    graph = _RecordingGraph(rel_returns=["REAL1"])
    plan = _plan(
        [
            RecordedWrite(
                "upsert_relation",
                {
                    "from_id": "a",
                    "to_id": "b",
                    "rel_type": "acquired",
                    "source_ref": None,
                },
            ),
            RecordedWrite(
                "mark_relation_emitted",
                {"relation_id": "plan_rel_1", "run_id": "run1"},
            ),
            RecordedWrite(
                "append_emitted_relations",
                {"run_id": "run1", "relation_ids": ["plan_rel_1"]},
            ),
            RecordedWrite(
                "finalize_run",
                {
                    "run_id": "run1",
                    "status": "succeeded",
                    "completed_at": "t",
                    "emitted_entity_ids": [],
                    "emitted_relation_ids": ["plan_rel_1"],
                },
            ),
        ]
    )

    _commit_service(graph).commit_plan(plan)

    assert graph.mark_relation_emitted_calls == [
        {"relation_id": "REAL1", "run_id": "run1"}
    ]
    assert graph.append_emitted_relations_calls[0]["relation_ids"] == ["REAL1"]
    assert graph.finalize_run_calls[0]["emitted_relation_ids"] == ["REAL1"]
