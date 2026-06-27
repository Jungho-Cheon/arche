"""reviewable ingest 의 요청/응답 스키마 — plan → preview → commit.

WHY 별도 모듈 (schemas.py 와 분리): plan/preview/commit 은 graph primitive
(find_entities 등) 와 *다른 사용 흐름* 이다 — 적재 전 변경 묶음을 사람이 검토하는
관리자(admin) 통로. 입력/출력 계약을 한 모듈에 모아 reviewable ingest 의 표면을
한눈에 보이게 한다. 모든 모델은 schemas.py 의 관례대로 `extra="forbid"` 로
*예상치 못한 키를 거부* 한다 (계약 어긋남을 silent pass 시키지 않음).

세 단계의 의미:
  - plan  : 파일을 *쓰지 않고* 추출만 돌려 변경 묶음(IngestPlan)을 만든다.
            응답(PlanSummary)은 만들 엔티티/병합/관계/삭제 수의 요약.
  - preview: 그 변경 묶음을 항목 단위로 펼쳐 보여준다(PlanPreview). 이 호출이
            계획을 "미리보기 완료" 로 표시한다 — commit 의 안전 latch 전제.
  - commit : 미리보기를 거친 계획을 진짜 그래프에 적용한다(IngestCommitResponse).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------- plan ----------


class PlanIngestRequest(BaseModel):
    """plan 입력 — 적재 후보 파일의 절대 경로."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, description="적재 계획을 세울 파일의 절대 경로")


class PlanSummary(BaseModel):
    """plan 응답 — 만들 변경의 *개수* 요약. 세부는 preview 가 펼친다."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(description="이후 preview/commit 호출에 쓰는 계획 식별자")
    source_path: str
    entities_created: int = Field(ge=0, description="새로 만들 엔티티 수")
    entities_merged: int = Field(ge=0, description="기존 엔티티에 병합할 수")
    relations_created: int = Field(ge=0, description="새로 만들 관계 수")
    deletion_count: int = Field(
        ge=0, description="차분으로 삭제/트림될 엔티티·관계 수"
    )
    open_questions: int = Field(
        default=0,
        ge=0,
        description="사람 판단을 기다리는 '놓친 병합 후보' 질문 수 (near-miss)",
    )


# ---------- preview ----------


class PreviewRequest(BaseModel):
    """preview 입력 — plan 이 돌려준 계획 식별자."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1)


class NewEntityView(BaseModel):
    """새로 만들 엔티티 한 건의 미리보기."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    aliases: list[str] = Field(default_factory=list)


class MergeView(BaseModel):
    """기존 엔티티 병합 한 건의 미리보기 — 병합 전 이름과 병합 후 별칭."""

    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(description="병합 대상 (살아남는) 엔티티 id")
    before_name: str = Field(description="병합 전 대상 엔티티 이름 (없으면 빈 문자열)")
    after_aliases: list[str] = Field(default_factory=list)


class RelationView(BaseModel):
    """새로 만들 관계 한 건의 미리보기."""

    model_config = ConfigDict(extra="forbid")

    from_id: str
    to_id: str
    type: str


class QuestionView(BaseModel):
    """'놓친 병합 후보' 질문 한 건의 미리보기 (near-miss disambiguation).

    추출된 엔티티(extracted_*)가 기존 노드(candidate_*)와 임계 바로 아래
    유사도(similarity)라 새 점으로 떨어졌다 — 같은 대상인지 사람에게 묻는다.
    answer 는 resolve(merge/keep)로 보낸다.
    """

    model_config = ConfigDict(extra="forbid")

    question_id: str
    extracted_name: str
    extracted_type: str
    candidate_id: str
    candidate_name: str
    similarity: float
    kind: str


class PlanPreview(BaseModel):
    """preview 응답 — 변경 묶음을 항목 단위로 펼친 형태."""

    model_config = ConfigDict(extra="forbid")

    new_entities: list[NewEntityView]
    merges: list[MergeView]
    new_relations: list[RelationView]
    deletion_count: int = Field(ge=0)
    questions: list[QuestionView] = Field(
        default_factory=list,
        description="사람 판단을 기다리는 near-miss 병합 후보 질문 목록",
    )


# ---------- resolve ----------


class ResolutionItem(BaseModel):
    """질문 한 건에 대한 사람의 결정 — merge(같은 대상) 또는 keep(다른 대상)."""

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1)
    decision: Literal["merge", "keep"]


class ResolveRequest(BaseModel):
    """resolve 입력 — 계획 식별자 + 그 계획의 질문에 대한 결정 묶음."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1)
    resolutions: list[ResolutionItem]


# ---------- commit ----------


class CommitRequest(BaseModel):
    """commit 입력 — 미리보기를 거친 계획의 식별자."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1)


class IngestCommitResponse(BaseModel):
    """commit 응답 — 그래프에 실제로 반영된 변경 카운터."""

    model_config = ConfigDict(extra="forbid")

    entities_created: int = Field(ge=0)
    entities_updated: int = Field(ge=0)
    relations_created: int = Field(ge=0)
    deletions: int = Field(ge=0)
