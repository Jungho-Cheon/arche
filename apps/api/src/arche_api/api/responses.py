"""읽기 primitive 의 요청과 응답 Pydantic 모델.

공통 메타데이터(Node/Edge/SourceRef)는 domain/models.py 에서 import 해 모든 응답이
같은 모델을 쓰게 한다. FastAPI response_model 로 넘기면 OpenAPI 스키마가 자동으로
계약과 일치해, caller 가 OpenAPI 만 보고 contract 를 안다."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..domain.models import Edge, Node
from .security import validate_optional_namespace_id, validate_relation_types

_ULID_PATTERN = re.compile(r"^[0-9A-Z]{26}$")


# ---------- get_schema ----------


class EntityTypeExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


class EntityTypeSummary(BaseModel):
    """entity_types[] 한 항목."""

    model_config = ConfigDict(extra="forbid")

    type: str
    count: int = Field(ge=0)
    examples: list[EntityTypeExample] = Field(default_factory=list, max_length=5)


class RelationTypePair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_type: str
    to_type: str
    count: int = Field(ge=0)


class RelationTypeSummary(BaseModel):
    """relation_types[] 한 항목."""

    model_config = ConfigDict(extra="forbid")

    type: str
    count: int = Field(ge=0)
    common_pairs: list[RelationTypePair] = Field(default_factory=list, max_length=5)


class EmbeddingInfo(BaseModel):
    """embedding_info — caller 가 같은 모델로 정렬할 수 있게 model 과 dimension 을
    함께 노출한다(모델만 주면 caller 가 dim 을 가정해야 해 호환 실패가 늦게 드러난다)."""

    model_config = ConfigDict(extra="forbid")

    model: str
    dimension: int = Field(ge=1)


class GetSchemaResponse(BaseModel):
    """get_schema 응답."""

    model_config = ConfigDict(extra="forbid")

    entity_types: list[EntityTypeSummary]
    relation_types: list[RelationTypeSummary]
    embedding_info: EmbeddingInfo


# ---------- get_entity ----------


class EdgeCounts(BaseModel):
    """outgoing / incoming 별 관계 타입 카운트. 각 dict 는 {relation_type: count}."""

    model_config = ConfigDict(extra="forbid")

    outgoing: dict[str, int] = Field(default_factory=dict)
    incoming: dict[str, int] = Field(default_factory=dict)


class GetEntityResponse(BaseModel):
    """get_entity 응답."""

    model_config = ConfigDict(extra="forbid")

    node: Node
    edge_counts: EdgeCounts


# ---------- get_neighbors ----------


class GetNeighborsRequest(BaseModel):
    """get_neighbors 입력. id 가 선택인 건 REST 와 MCP 가 같은 스키마를 공유하기
    때문이다 — REST 는 path 의 entity_id, MCP 는 body 의 id 가 진입점이다. 둘 다 set
    이면 라우터가 일치를 검증하고 불일치 시 400 으로 분기한다."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, pattern=r"^[0-9A-Z]{26}$")
    relation_types: list[str] | None = None
    direction: str = Field(default="both", pattern=r"^(outgoing|incoming|both)$")
    hops: int = Field(default=1, ge=1, le=5)
    max_nodes: int = Field(default=100, ge=1, le=500)
    # 순회할 namespace. 미지정 시 auth 헤더(REST) 또는 "default".
    namespace_id: str | None = Field(default=None, min_length=1)

    _ns_check = field_validator("namespace_id")(validate_optional_namespace_id)
    _rel_check = field_validator("relation_types")(validate_relation_types)


class GetNeighborsResponse(BaseModel):
    """get_neighbors 응답. truncated 는 max_nodes 초과 여부."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[Node]
    edges: list[Edge]
    truncated: bool


# ---------- find_path ----------


class FindPathRequest(BaseModel):
    """find_path 입력. from_id == to_id 는 라우터에서 422 로 분기한다."""

    model_config = ConfigDict(extra="forbid")

    from_id: str = Field(pattern=r"^[0-9A-Z]{26}$")
    to_id: str = Field(pattern=r"^[0-9A-Z]{26}$")
    max_hops: int = Field(default=4, ge=1, le=6)
    max_paths: int = Field(default=5, ge=1, le=20)
    relation_types: list[str] | None = None
    # 경로를 찾을 namespace. 미지정 시 auth 헤더(REST) 또는 "default".
    namespace_id: str | None = Field(default=None, min_length=1)

    _ns_check = field_validator("namespace_id")(validate_optional_namespace_id)
    _rel_check = field_validator("relation_types")(validate_relation_types)


class PathSegment(BaseModel):
    """paths[] 한 항목."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[Node]
    edges: list[Edge]
    length: int = Field(ge=1)
    # hub_score: 경로 중간 노드(끝점 제외)의 log(1+degree) 합. 낮을수록 구체적이고,
    # 높을수록 과연결 허브를 다리로 쓴 "의미가 약한" 연결일 수 있다. 같은 length 면
    # 낮은 것을 먼저 돌려준다. 소비 에이전트는 높은 hub_score 경로를 의심해야 한다.
    hub_score: float = Field(default=0.0, ge=0.0)


class FindPathResponse(BaseModel):
    """find_path 응답. 경로 없으면 paths=[] (에러 아님)."""

    model_config = ConfigDict(extra="forbid")

    paths: list[PathSegment]


# ---------- get_subgraph ----------


class GetSubgraphRequest(BaseModel):
    """get_subgraph 입력. entry_ids 각 원소는 validator 로 ULID 를 강제한다(pydantic
    Field 는 list item pattern 을 native 표현하지 못한다)."""

    model_config = ConfigDict(extra="forbid")

    entry_ids: list[str] = Field(min_length=1, max_length=20)
    # 순회할 namespace. 미지정 시 auth 헤더(REST) 또는 "default".
    namespace_id: str | None = Field(default=None, min_length=1)
    hops: int = Field(default=2, ge=1, le=4)
    # 상한이 큰 건 truncation 이 정답률 병목이라 큰 윈도우를 열어두기 위함. 직렬화가
    # 컨텍스트를 넘으면 호출자가 조절한다.
    max_nodes: int = Field(default=200, ge=1, le=5000)
    relation_types: list[str] | None = None

    _ns_check = field_validator("namespace_id")(validate_optional_namespace_id)
    _rel_check = field_validator("relation_types")(validate_relation_types)

    @field_validator("entry_ids")
    @classmethod
    def _check_entry_ids(cls, v: list[str]) -> list[str]:
        for entry_id in v:
            if not _ULID_PATTERN.match(entry_id):
                raise ValueError(f"entry_id is not ULID: {entry_id}")
        return v


class GetSubgraphResponse(BaseModel):
    """get_subgraph 응답. entry_ids 는 echo 한다."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[Node]
    edges: list[Edge]
    entry_ids: list[str]
    truncated: bool


# ---------- find_related ----------


class FindRelatedRequest(BaseModel):
    """find_related 입력 — 시드 노드 집합에서 구조적으로 가까운 관련 노드 top-k.

    시드에서 감쇠 확산한 근접도로 관련 노드를 한 번에 회수해, 에이전트가 get_neighbors
    를 여러 번 왕복하는 비용을 없앤다(Personalized PageRank 착상). damping 은 한 홉
    멀어질 때마다 곱해지는 감쇠 계수(0<d<1)로, 작을수록 시드 바로 옆을 선호한다."""

    model_config = ConfigDict(extra="forbid")

    seeds: list[str] = Field(min_length=1, max_length=20)
    top_k: int = Field(default=10, ge=1, le=100)
    max_hops: int = Field(default=2, ge=1, le=4)
    damping: float = Field(default=0.5, gt=0.0, lt=1.0)
    relation_types: list[str] | None = None
    # 확장할 namespace. 미지정 시 auth 헤더(REST) 또는 "default".
    namespace_id: str | None = Field(default=None, min_length=1)

    _ns_check = field_validator("namespace_id")(validate_optional_namespace_id)
    _rel_check = field_validator("relation_types")(validate_relation_types)

    @field_validator("seeds")
    @classmethod
    def _check_seeds(cls, v: list[str]) -> list[str]:
        for seed in v:
            if not _ULID_PATTERN.match(seed):
                raise ValueError(f"seed is not ULID: {seed}")
        return v


class RelatedNode(BaseModel):
    """find_related 결과 한 항목 — 관련 노드 + 근접 점수 + 시드까지의 최단 거리."""

    model_config = ConfigDict(extra="forbid")

    node: Node
    # 0..1 로 정규화된 근접 점수 (top-1 = 1.0). 여러 시드에 가까울수록, 가까운
    # 홉일수록 높다. 절대값이 아니라 *이 응답 안에서의 상대 순위* 로 해석한다.
    score: float = Field(ge=0.0, le=1.0)
    # 어느 시드로부터든 가장 가까운 홉 수 (>=1 — 시드 자신은 결과에서 제외).
    distance: int = Field(ge=1)


class FindRelatedResponse(BaseModel):
    """find_related 응답. seeds 는 echo, truncated 는 후보가 top_k 초과로 잘렸는지."""

    model_config = ConfigDict(extra="forbid")

    related: list[RelatedNode]
    seeds: list[str]
    truncated: bool
