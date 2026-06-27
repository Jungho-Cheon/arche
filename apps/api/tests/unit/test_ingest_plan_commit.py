"""IngestService.plan_file / commit_plan — record/replay 동일성 검증 (Task 3).

WHY 기존 더블 재사용: test_ingest_service.py 의 FakeGraph / FakeEmbedder / FakeLLM
는 이미 4 단계 매처 + 관계 upsert + 차분 흐름을 충실히 흉내낸다. 새 더블을 만들지
않고 그대로 재사용해 plan(쓰지 않음) → commit(재생) 결과가 *직접 ingest* 와
카운트까지 동일함을 비교한다. (test_support.FakeGraph 는 관계를 저장하지 않아
동일성 비교에는 부적합 — 그래서 unit 쪽 더블을 쓴다.)
"""

from __future__ import annotations

from pathlib import Path

from arche_api.domain.ingest import IngestService
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
