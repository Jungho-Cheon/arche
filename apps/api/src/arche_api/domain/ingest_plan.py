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
