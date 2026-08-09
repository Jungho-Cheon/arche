"""계획용 자료구조 — 쓰기 의도를 기록한 묶음(record/replay).

외부 기술에 의존하지 않는 순수 도메인 표현이라 domain 에 둔다."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ingest import IngestResult
    from .models import StoredEntity


class PlanQuestionKind(str, Enum):
    """검토형 적재 질문의 종류 — 닫힌 목록. 응답 스키마에 enum 으로 노출돼 소비자가
    값 집합을 계약으로 삼는다.

    - POSSIBLE_MISSED_MERGE: 새 항목이 기존 노드와 임계 바로 아래 유사도라 자동
      병합되지 않고 새 점으로 떨어졌다 — 같은 대상인지 사람에게 묻는다.
    - SAME_NAME_DIFFERENT_TYPE: 이름은 같은데 타입이 달라 갈라졌다. 매칭이 타입까지
      보는데 타입 라벨은 문서마다 추출 모델이 새로 지어서 생긴다.
    """

    POSSIBLE_MISSED_MERGE = "possible_missed_merge"
    SAME_NAME_DIFFERENT_TYPE = "same_name_different_type"


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
    kind: PlanQuestionKind = PlanQuestionKind.POSSIBLE_MISSED_MERGE


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
    # 놓친 병합 후보 질문. plan_file 이 정렬하고 개수를 자르고 번호를 붙인 뒤 채운다.
    open_questions: list[AmbiguousMatch] = field(default_factory=list)
    # 사람이 답한 강제 매칭 힌트 맵. 값은 "merge:<id>" 또는 "keep". resolve 가 누적한다.
    resolved: dict[str, str] = field(default_factory=dict)
    # 에이전트 보강 메모. 프롬프트 [ENRICHMENT] prefix 로만 들어가고 provenance 엔 영향 없다.
    hints: str | None = None
    # 이 계획이 속한 namespace. resolve 재계획이 같은 namespace 를 유지하도록 보존한다
    # (안 그러면 default 로 되돌아가 격리가 깨진다, issue #92).
    namespace_id: str = "default"
    # 본문으로 세운 계획이면 그 본문. resolve 는 재계획을 하는데, 이게 없으면 source_path
    # (본문 계획에서는 파일 경로가 아니라 출처 라벨) 를 파일로 열려다 실패한다.
    source_content: str | None = None
