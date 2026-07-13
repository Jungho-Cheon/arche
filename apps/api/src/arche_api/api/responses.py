"""Primitive REST 응답 모델 — PRD 3 §2-7 의 출력 JSON Schema 와 1:1.

본 모듈은 5 개 primitive (`get_schema` / `get_entity` / `get_neighbors` /
`find_path` / `get_subgraph`) 의 *요청·응답 Pydantic 모델* 만 모은다. 공통 메타
데이터 (Node / Edge / SourceRef) 는 `domain/models.py` 에서 import — *모든
primitive 응답이 같은 모듈에서 같은 모델* 을 쓰도록 보장한다. (이슈 #6 의
acceptance criteria: "공통 메타데이터가 모든 응답에서 동일 형태".)

WHY 응답 모듈을 분리: schemas.py 는 walking skeleton (find_entities / admin
ingest) 의 입력/출력만 담고 있고, 5 primitive 가 들어오면 한 파일이 너무 두꺼
워진다. 라우터별 응답 모델을 별도 모듈로 떼어 둔다.

WHY pydantic 으로 출력 모델까지: FastAPI 의 `response_model=...` 인자로 넘기면
OpenAPI 스키마 (`/openapi.json`) 가 *PRD 3 의 JSON Schema 와 자동 일치* . 즉
caller (eval 의 Arche 컬럼 / MCP 어댑터 / SDK 생성기) 가 OpenAPI 만 보고
도 contract 를 안다.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..domain.models import Edge, Node
from .security import validate_namespace_id, validate_relation_types

# WHY 모듈 상수: 여러 곳에서 같은 패턴 — 한 곳에 정의해 ADR / PRD 변경 시 단일
# 갱신.
_ULID_PATTERN = re.compile(r"^[0-9A-Z]{26}$")


def _validate_optional_namespace(v: str | None) -> str | None:
    """namespace_id 필드 검증 — 미지정(None)은 통과, 값이 있으면 형식 검사(#142)."""
    return v if v is None else validate_namespace_id(v)


# ---------- get_schema (PRD 3 §2) ----------


class EntityTypeExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


class EntityTypeSummary(BaseModel):
    """PRD 3 §2.3 entity_types[] 한 항목."""

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
    """PRD 3 §2.3 relation_types[] 한 항목."""

    model_config = ConfigDict(extra="forbid")

    type: str
    count: int = Field(ge=0)
    common_pairs: list[RelationTypePair] = Field(default_factory=list, max_length=5)


class EmbeddingInfo(BaseModel):
    """PRD 3 §2.3 embedding_info — caller 가 같은 모델로 정렬할 수 있게 노출.

    WHY model + dimension 둘 다: 모델 식별자만 보면 caller 가 dim 을 가정해야
    하고, 가정이 어긋나면 호환 실패가 *실행 시점* 까지 미뤄진다. 두 필드를 같이
    노출하면 sanity check 가 즉시 가능 (ADR-0006 D5 의 future-friendly slot).
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    dimension: int = Field(ge=1)


class GetSchemaResponse(BaseModel):
    """PRD 3 §2.3 응답."""

    model_config = ConfigDict(extra="forbid")

    entity_types: list[EntityTypeSummary]
    relation_types: list[RelationTypeSummary]
    embedding_info: EmbeddingInfo


# ---------- get_entity (PRD 3 §4) ----------


class EdgeCounts(BaseModel):
    """PRD 3 §4.4 — outgoing / incoming 별 관계 타입 카운트.

    각 dict 는 `{relation_type: count}` 형태. PRD 3 §4.4 의 additionalProperties
    는 integer minimum 0 — pydantic 의 dict[str, int] 로 자연스럽게 표현.
    """

    model_config = ConfigDict(extra="forbid")

    outgoing: dict[str, int] = Field(default_factory=dict)
    incoming: dict[str, int] = Field(default_factory=dict)


class GetEntityResponse(BaseModel):
    """PRD 3 §4.4 응답."""

    model_config = ConfigDict(extra="forbid")

    node: Node
    edge_counts: EdgeCounts


# ---------- get_neighbors (PRD 3 §5) ----------


class GetNeighborsRequest(BaseModel):
    """PRD 3 §5.3 입력.

    WHY id 가 *선택* (path 가 우선): PRD 3 §0.1 의 REST + MCP 1:1 매핑 때문.
    REST 호출 (`POST /entities/{entity_id}/neighbors`) 은 path 의 entity_id 가
    진입점이고, MCP 호출 (`tools/call get_neighbors {id: ...}`) 은 body 의 id
    가 진입점이다. 두 표면이 *같은 입력 스키마* 를 공유하도록 body 에도 id 를
    선택 필드로 허용한다.

    REST 라우터는 path 와 body 둘 다 set 이면 일치 검증 — 불일치 시
    `invalid_input` 400 envelope 으로 분기한다 (이슈 #27 회귀 1).
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, pattern=r"^[0-9A-Z]{26}$")
    relation_types: list[str] | None = None
    direction: str = Field(default="both", pattern=r"^(outgoing|incoming|both)$")
    hops: int = Field(default=1, ge=1, le=5)
    max_nodes: int = Field(default=100, ge=1, le=500)
    # ADR-0015 — 순회할 namespace. 미지정 시 auth 헤더(REST) 또는 "default" (issue #98).
    namespace_id: str | None = Field(default=None, min_length=1)

    _ns_check = field_validator("namespace_id")(_validate_optional_namespace)
    _rel_check = field_validator("relation_types")(validate_relation_types)


class GetNeighborsResponse(BaseModel):
    """PRD 3 §5.4 응답. truncated 는 max_nodes 초과 여부."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[Node]
    edges: list[Edge]
    truncated: bool


# ---------- find_path (PRD 3 §6) ----------


class FindPathRequest(BaseModel):
    """PRD 3 §6.3 입력. from_id == to_id 는 라우터에서 422 unprocessable 로 분기."""

    model_config = ConfigDict(extra="forbid")

    from_id: str = Field(pattern=r"^[0-9A-Z]{26}$")
    to_id: str = Field(pattern=r"^[0-9A-Z]{26}$")
    max_hops: int = Field(default=4, ge=1, le=6)
    max_paths: int = Field(default=5, ge=1, le=20)
    relation_types: list[str] | None = None
    # ADR-0015 — 경로를 찾을 namespace. 미지정 시 auth 헤더(REST) 또는 "default" (#98).
    namespace_id: str | None = Field(default=None, min_length=1)

    _ns_check = field_validator("namespace_id")(_validate_optional_namespace)
    _rel_check = field_validator("relation_types")(validate_relation_types)


class PathSegment(BaseModel):
    """PRD 3 §6.4 paths[] 한 항목."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[Node]
    edges: list[Edge]
    length: int = Field(ge=1)
    # hub_score: 경로 *중간* 노드 (끝점 제외) 의 log(1+degree) 합. 0.0 = 모든
    # 중간 노드가 고유 (또는 1-hop 직접 경로) = 가장 구체적. 값이 클수록 경로가
    # promiscuous 허브 (수많은 엔티티와 연결된 공유 노드/추출 artifact) 를 다리로
    # 쓴다는 뜻 — "닿긴 닿지만 의미가 약한" 연결일 가능성. 같은 length 의 경로
    # 중 hub_score 가 낮은 것을 어댑터가 먼저 돌려준다. 소비 에이전트는 hub_score
    # 가 높은 경로를 *근거로 채택하기 전에 의심* 해야 한다. (ADR-0017)
    hub_score: float = Field(default=0.0, ge=0.0)


class FindPathResponse(BaseModel):
    """PRD 3 §6.4 응답. 경로 없을 시 paths=[] (에러 아님)."""

    model_config = ConfigDict(extra="forbid")

    paths: list[PathSegment]


# ---------- get_subgraph (PRD 3 §7) ----------


class GetSubgraphRequest(BaseModel):
    """PRD 3 §7.3 입력.

    WHY entry_ids 각 원소를 field_validator 로 ULID 검증: PRD 3 §7.3 schema 의
    items 가 `pattern: ^[0-9A-Z]{26}$`. pydantic v2 의 Field 는 list item pattern
    을 native 표현하지 않으므로 validator 로 강제. 위반은 422 (pydantic 검증
    실패) — 코드 카탈로그의 invalid_input 과 의미 동등.
    """

    model_config = ConfigDict(extra="forbid")

    entry_ids: list[str] = Field(min_length=1, max_length=20)
    # ADR-0015 — 순회할 namespace. 미지정 시 auth 헤더(REST) 또는 "default" (issue #98).
    namespace_id: str | None = Field(default=None, min_length=1)
    hops: int = Field(default=2, ge=1, le=4)
    # 2026-06-22: 상한 1000 → 5000. clamp 수정으로 큰 서브그래프 500 크래시가
    # 사라졌고, max_nodes 300→1000 sweep 에서 정답률이 recall 회복으로 +9pp
    # 올라 (truncation 이 병목) 더 큰 윈도우 활용 여지를 연다. 큰 컨텍스트 모델
    # (gpt-4.1 1M) 가정 — 직렬화가 윈도우를 넘으면 호출자가 조절.
    max_nodes: int = Field(default=200, ge=1, le=5000)
    relation_types: list[str] | None = None

    _ns_check = field_validator("namespace_id")(_validate_optional_namespace)
    _rel_check = field_validator("relation_types")(validate_relation_types)

    @field_validator("entry_ids")
    @classmethod
    def _check_entry_ids(cls, v: list[str]) -> list[str]:
        for entry_id in v:
            if not _ULID_PATTERN.match(entry_id):
                raise ValueError(f"entry_id is not ULID: {entry_id}")
        return v


class GetSubgraphResponse(BaseModel):
    """PRD 3 §7.4 응답. entry_ids 는 echo (caller 가 결과 안에서 진입점 구분)."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[Node]
    edges: list[Edge]
    entry_ids: list[str]
    truncated: bool
