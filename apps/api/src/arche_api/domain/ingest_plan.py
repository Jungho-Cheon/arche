"""계획용 자료구조 — 쓰기 의도를 기록한 묶음 (record/replay).

WHY domain 에 둠: PlanningGraphRepository 와 IngestService.plan_file 둘 다
참조하고, 외부 기술(Neo4j/OpenAI)에 의존하지 않는 순수 도메인 표현이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ingest import IngestResult
    from .models import StoredEntity


@dataclass(frozen=True)
class AmbiguousMatch:
    """계획 단계에서 발견한 '놓친 병합 후보' 질문 한 건.

    추출된 엔티티(extracted_*)가 기존 노드(candidate_*)와 임계 바로 아래
    유사도(similarity)라 새 점으로 떨어졌다 — 같은 대상인지 사람에게 묻는다.
    question_id 는 plan_file 이 부여한다(레이어 하단에선 "").
    """

    question_id: str
    extracted_name: str
    extracted_type: str
    candidate_id: str
    candidate_name: str
    similarity: float
    kind: str = "possible_missed_merge"


@dataclass(frozen=True)
class RecordedWrite:
    """가로챈 GraphRepository 쓰기 호출 한 건.

    method — 포트의 쓰기 메서드 이름. kwargs — 그 호출의 키워드 인자(이미
    해소된 도메인 객체). before — apply_merge_mutation 일 때 *병합 전* 대상
    엔티티 스냅샷(미리보기 전후 비교용).
    """

    method: str
    kwargs: dict[str, Any]
    before: StoredEntity | None = None


@dataclass
class IngestPlan:
    """한 파일 계획의 완결된 변경 묶음. commit 이 writes 를 순서대로 재생한다."""

    plan_id: str
    source_path: str
    source_hash: str
    extractor_version: str
    created_at: str
    previewed: bool
    writes: list[RecordedWrite]
    result: IngestResult
    depends_on_entity_ids: list[str] = field(default_factory=list)
    # 놓친 병합 후보(near-miss) 질문 — plan_file 이 result.ambiguities 를 유사도
    # 내림차순 정렬 + 상한 cap + question_id 부여 후 채운다. 미리보기 UI 가 사람에게
    # "이 둘이 같은 대상인가?" 를 묻는 입력. NORMAL ingest 는 이 필드를 만들지 않는다.
    open_questions: list[AmbiguousMatch] = field(default_factory=list)
    # ask-human-on-ambiguity (해소 엔진) — 사람이 답한 질문을 *추출 엔티티 서명*
    # ("<정규명>\x00<type>") 단위로 누적한 강제 매칭 힌트 맵. 값은
    # "merge:<candidate_id>"(해당 candidate 로 강제 병합) 또는 "keep"(강제 새 노드 +
    # 재질문 억제). resolve_plan 이 plan.open_questions 로 번역해 채우고, 다음
    # resolve_plan 호출이 여기에 *덧붙여* 누적한다. NORMAL ingest/plan 은 비어 있다.
    resolved: dict[str, str] = field(default_factory=dict)
