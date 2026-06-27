"""Unit 테스트 공용 fixture — reviewable ingest 서비스 함수용 더블.

WHY 가벼운 더블 (FakeGraph 전체 재사용 아님): plan/preview/commit *서비스 함수*
의 안전 latch (previewed + stale) 는 그래프의 실제 적재 동작과 무관하다. 검증
대상은 "previewed 가 아니면 거부 / depends 노드가 사라졌으면 거부" 라는 분기뿐
이므로, `entity_exists` 와 `commit_plan` 만 흉내내는 최소 더블로 충분하다.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from arche_api.domain.ingest import IngestResult
from arche_api.domain.ingest_plan import AmbiguousMatch, IngestPlan, RecordedWrite


class _FakeGraph:
    """서비스 latch 검증용 그래프 더블 — entity_exists 만 노출.

    `exists` 로 stale 시나리오를 토글한다 (True = 의존 노드가 살아 있음).
    """

    def __init__(self, *, exists: bool = True) -> None:
        self._exists = exists

    def entity_exists(self, *, entity_id: str) -> bool:
        return self._exists


class _FakeService:
    """IngestService 대역 — commit_plan 과 _graph 만 제공.

    commit_plan 은 카운터가 채워진 단순 IngestResult 를 돌려준다. 서비스
    `commit_plan` 함수가 latch 통과 후 도메인 메서드를 호출해 응답으로 변환하는지
    확인하는 용도라, 실제 그래프 재생은 흉내내지 않는다.
    """

    def __init__(self, graph: _FakeGraph) -> None:
        self._graph = graph
        # resolve_plan 호출 인자를 기록해 서비스가 도메인 메서드로 위임하는지 검증.
        self.resolve_calls: list[tuple[IngestPlan, dict[str, str]]] = []
        # plan_file 이 받은 hints 를 기록해 서비스가 입력을 그대로 전달하는지 검증.
        self.last_plan_file_hints: str | None = None

    def plan_file(
        self, path, *, namespace_id: str = "default", hints: str | None = None
    ) -> IngestPlan:  # noqa: ANN001
        """plan_file 대역 — 받은 hints 를 기록하고 최소 IngestPlan 을 돌려준다.

        서비스 `plan_ingest` 가 요청의 hints 를 도메인 `plan_file` 로 그대로
        전달하는지만 보는 더블이라, 추출은 흉내내지 않고 인자만 기록한다.
        """
        self.last_plan_file_hints = hints
        return IngestPlan(
            plan_id="pln_fake",
            source_path=str(path),
            source_hash="deadbeef",
            extractor_version="p2:test",
            created_at="2026-06-27T00:00:00Z",
            previewed=False,
            writes=[],
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

    def commit_plan(self, plan: IngestPlan) -> IngestResult:
        return IngestResult(
            source_path=plan.source_path,
            entities_created=2,
            entities_updated=1,
            relations_created=1,
            relations_skipped_dangling=0,
            entity_ids=[],
            relations_deleted=0,
        )

    def resolve_plan(
        self, plan: IngestPlan, resolutions: dict[str, str]
    ) -> IngestPlan:
        """해소된 정제 계획 대역 — 같은 plan_id 로 질문을 비운 계획을 돌려준다.

        실제 IngestService.resolve_plan 은 plan_file 을 재실행하지만, 서비스
        `resolve_ingest` 가 (1) question_id 검증 후 (2) 도메인 메서드로 위임하고
        (3) 결과를 같은 plan_id 로 재보관하는지만 보는 더블이라 질문만 비운다.
        """
        self.resolve_calls.append((plan, dict(resolutions)))
        return replace(plan, open_questions=[], previewed=False)


@pytest.fixture
def fake_service():
    """기본 fake_service — entity_exists 가 True (의존 노드 존재)."""
    return _FakeService(_FakeGraph(exists=True))


@pytest.fixture
def make_plan():
    """plan_id "pln_1" 의 IngestPlan 을 만든다 (previewed / depends 토글 가능)."""

    def _make(
        *,
        previewed: bool = False,
        writes: list[RecordedWrite] | None = None,
        depends_on_entity_ids: list[str] | None = None,
        open_questions: list[AmbiguousMatch] | None = None,
    ) -> IngestPlan:
        return IngestPlan(
            plan_id="pln_1",
            source_path="/tmp/a.md",
            source_hash="deadbeef",
            extractor_version="p2:test",
            created_at="2026-06-27T00:00:00Z",
            previewed=previewed,
            writes=writes or [],
            result=IngestResult(
                source_path="/tmp/a.md",
                entities_created=2,
                entities_updated=1,
                relations_created=1,
                relations_skipped_dangling=0,
                entity_ids=[],
            ),
            depends_on_entity_ids=depends_on_entity_ids or [],
            open_questions=open_questions or [],
        )

    return _make
