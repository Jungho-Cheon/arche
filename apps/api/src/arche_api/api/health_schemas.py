"""그래프 건강 점검과 노드 열거의 요청/응답 모델."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .security import validate_optional_namespace_id


class GraphHealthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace_id: str | None = Field(
        default=None, description="점검할 namespace. 미지정 시 'default'"
    )
    max_samples: int = Field(
        default=20,
        ge=1,
        le=200,
        description="신호마다 실어 보낼 예시 최대 개수. 개수 집계는 늘 전량이다.",
    )

    _ns_check = field_validator("namespace_id")(validate_optional_namespace_id)


class TypeCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    count: int


class DuplicateNameView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_name: str
    entity_ids: list[str]
    names: list[str]
    types: list[str]


class OverMergeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    name: str
    reasons: list[str] = Field(
        description="왜 뭉침으로 의심하는지. 예: alias_count=41>30, distinct_identifiers=3"
    )


class IsolatedView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    type: str


class GraphHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace_id: str
    entity_count: int
    type_counts: list[TypeCount] = Field(
        description="타입별 노드 수. get_schema 와 달리 자르지 않고 전량을 담는다."
    )
    duplicate_names: list[DuplicateNameView] = Field(
        description="정규명이 같은 노드 묶음. 같은 대상이 갈라졌다는 신호."
    )
    duplicate_name_total: int
    overmerged: list[OverMergeView] = Field(
        description="서로 다른 둘이 한 노드로 뭉쳤다고 의심되는 노드."
    )
    overmerged_total: int
    isolated: list[IsolatedView] = Field(description="관계가 하나도 없는 노드.")
    isolated_total: int
    truncated: bool = Field(
        description="예시 목록 중 하나라도 max_samples 에서 잘렸는지. 개수는 잘려도 전량이다."
    )
