"""잘못 합친 노드를 떼어내는 연산의 요청/응답 스키마 — plan → preview → commit.

검토형 적재와 같은 의례를 탄다. 계획은 그래프를 읽기만 하고, 미리 보기가 무엇이
어디로 가는지 펼치며 확정의 안전 latch 를 걸고, 확정에서만 그래프가 바뀐다.

적재와 달리 resolve 단계가 없다. 적재의 resolve 는 추출을 다시 돌리는 비용을 피하려고
있는데, 떼어내기는 계획에 LLM 호출이 없어 결정을 실어 다시 계획하는 게 더 싸고
단순하다. 사람이 정한 관계 배정은 plan 요청의 relation_decisions 로 넣는다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SplitPlanRequest(BaseModel):
    """떼어내기 계획 입력 — 어느 노드를, 무엇을 떼어, 어떤 이름으로."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(min_length=1, description="둘로 가를 노드의 id")
    new_name: str = Field(
        min_length=1,
        max_length=200,
        description="떼어낸 노드의 이름. 보통 원래 노드의 별칭 중 하나",
    )
    move_aliases: list[str] = Field(
        default_factory=list,
        description="떼어낸 노드로 옮길 별칭. 원래 노드에 있는 별칭이어야 한다",
    )
    move_source_paths: list[str] = Field(
        default_factory=list,
        description=(
            "떼어낸 노드로 옮길 출처. 관계를 어느 쪽에 붙일지도 이 목록으로 갈린다. "
            "비워 두면 모든 관계가 사람 판단 항목으로 올라온다"
        ),
    )
    relation_decisions: dict[str, Literal["keep", "move"]] = Field(
        default_factory=dict,
        description=(
            "출처로 갈리지 않는 관계에 대한 사람의 결정. "
            "{관계 id: keep|move}. 미리 보기가 물은 것을 여기 담아 다시 계획한다"
        ),
    )
    new_description: str | None = Field(
        default=None,
        max_length=2000,
        description="떼어낸 노드의 설명. 주지 않으면 원래 노드의 설명을 물려받는다",
    )
    namespace_id: str = Field(
        default="default", min_length=1, description="대상 노드가 속한 namespace"
    )


class SplitSummary(BaseModel):
    """계획 응답 — 무엇이 얼마나 움직이는지 개수 요약. 세부는 preview 가 펼친다."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(description="이후 preview/commit 호출에 쓰는 계획 식별자")
    origin_id: str
    origin_name: str
    new_name: str
    aliases_moved: int = Field(ge=0)
    aliases_kept: int = Field(ge=0)
    source_refs_moved: int = Field(ge=0)
    source_refs_kept: int = Field(ge=0)
    relations_moved: int = Field(ge=0, description="출처를 따라 떼어낸 노드로 갈 관계 수")
    relations_kept: int = Field(ge=0, description="원래 노드에 남을 관계 수")
    open_questions: int = Field(
        ge=0, description="출처만으로 갈리지 않아 사람이 정해야 하는 관계 수"
    )


class SplitPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1)


class SplitEntityView(BaseModel):
    """떼어낸 뒤 두 노드가 각각 어떤 모습이 되는지."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    type: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    # 설명을 기계적으로 가를 방법이 없어 떼어낸 노드는 원래 설명을 물려받는다. 그러면
    # 그 설명은 새 노드에 대해 틀린 말일 수 있다. 확정 전에 눈으로 볼 것을 알린다.
    description_inherited: bool = Field(
        default=False,
        description="원래 노드의 설명을 그대로 물려받았는지. True 면 새 노드와 안 맞을 수 있다",
    )
    source_paths: list[str] = Field(default_factory=list)


class SplitRelationView(BaseModel):
    """관계 한 건이 어디로 가는지와 그 근거."""

    model_config = ConfigDict(extra="forbid")

    relation_id: str
    type: str
    direction: Literal["outgoing", "incoming"]
    other_id: str
    other_name: str
    source_paths: list[str] = Field(default_factory=list)
    decision: Literal["keep", "move", "ask"]
    reason: str = Field(description="왜 그렇게 갈렸는지 한 줄")


class SplitPreview(BaseModel):
    """미리 보기 응답 — 두 노드의 모습과 관계별 행선지."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    origin: SplitEntityView = Field(description="떼어내고 남는 쪽")
    new_entity: SplitEntityView = Field(description="떼어내 새로 만들 쪽")
    relations: list[SplitRelationView] = Field(default_factory=list)
    questions: list[SplitRelationView] = Field(
        default_factory=list,
        description="decision 이 ask 인 관계만 추린 목록. 남아 있으면 확정이 거부된다",
    )


class SplitCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1)


class SplitCommitResponse(BaseModel):
    """확정 응답 — 그래프에 실제로 반영된 변경."""

    model_config = ConfigDict(extra="forbid")

    origin_id: str
    new_entity_id: str
    aliases_moved: int = Field(ge=0)
    source_refs_moved: int = Field(ge=0)
    relations_moved: int = Field(ge=0)
    relations_kept: int = Field(ge=0)
