"""도메인 모델 — PRD 3 §1 의 노드/엣지/소스 참조 스키마.

WHY pydantic v2: REST 응답이 PRD 3 §1.1 의 JSON Schema 와 *완전 일치* 해야 한다.
pydantic 으로 직렬화하면 응답 타입과 스키마 검증을 한 곳에서 관리한다.

WHY embedding 필드 비공개: PRD 3 §1.1 명시 — *Node 응답에 `embedding` 필드는
포함하지 않는다* . 내부 저장용 dataclass (StoredEntity) 와 응답용 모델 (Node) 을
분리해 누출을 막는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------- 응답 모델 (REST 노출) ----------


class SourceRef(BaseModel):
    """PRD 3 §1.3 SourceRef."""

    model_config = ConfigDict(extra="forbid")

    source_path: str
    chunk_index: int | None = None
    total_chunks: int | None = None


class Node(BaseModel):
    """PRD 3 §1.1 Node — REST 응답 형태. embedding 필드 없음."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[0-9A-Z]{26}$")
    name: str = Field(max_length=200)
    type: str = Field(max_length=64)
    aliases: list[str] = Field(default_factory=list)
    # WHY 2000: F (description 강화) 측정에서 정량 수치 / 시계열 보존 시 500 자를
    # 넘는 케이스 다수. F 자체는 aug 모드 (default) 에서 후퇴라 rollback 했지만,
    # max_length 한도는 강화된 상태 그대로 유지 — 향후 graph-only profile 또는
    # 도메인 (긴 description 이 자연스러운) 에서 재사용 가능.
    description: str | None = Field(default=None, max_length=2000)
    properties: dict[str, str | int | float | bool] = Field(default_factory=dict)
    source_refs: list[SourceRef] = Field(default_factory=list)
    created_at: str  # RFC 3339
    updated_at: str  # RFC 3339


class Edge(BaseModel):
    """PRD 3 §1.2 Edge."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[0-9A-Z]{26}$")
    from_: str = Field(alias="from", pattern=r"^[0-9A-Z]{26}$")
    to: str = Field(pattern=r"^[0-9A-Z]{26}$")
    type: str = Field(max_length=64)
    properties: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[SourceRef] = Field(default_factory=list)
    created_at: str
    updated_at: str


# ---------- LLM 추출 결과 (내부) ----------


@dataclass(frozen=True)
class ExtractedEntity:
    name: str
    type: str
    aliases: list[str] = field(default_factory=list)
    description: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    # ADR-0009 D2: 추출 단계에서 LLM 이 기존 graph entity 와의 매칭을 결정한
    # 경우, 해당 entity id 를 명시. 값이 있으면 ingest 흐름이 Step 1-3 매처를
    # 건너뛰고 곧바로 merge 한다. 값이 없으면 기존 매처 fallback (점진 도입).
    matched_existing_id: str | None = None


@dataclass(frozen=True)
class ExtractedRelation:
    from_name: str
    to_name: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedGraph:
    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]


# ---------- 저장 표현 (Neo4j 어댑터 입력) ----------


@dataclass(frozen=True)
class StoredEntity:
    """그래프에 적재되는 엔티티 — embedding 포함 (내부 전용)."""

    id: str
    name: str
    type: str
    aliases: list[str]
    description: str | None
    properties: dict[str, Any]
    source_refs: list[SourceRef]
    created_at: str
    updated_at: str
    embedding: list[float]
    # ADR-0015 D1 — namespace property. 본 entity 가 속한 namespace.
    # 기존 노드는 backfill 없이 default 로 간주. cross-namespace 공유는 ADR-0015
    # D3 의 명시 opt-in.
    namespace_id: str = "default"
    normalized_name: str = ""  # WHY default: PR #16 의 노드는 이 필드가 없다 — backfill 로 채움.
    # WHY 정규화된 alias 사본을 따로 저장: PRD 2 §5.1 Step 1·2 의 lookup 은
    # *normalize 된 키 == 정규명 OR 정규명 alias 중 하나* 면 hit 여야 한다.
    # 표기형 aliases 는 그대로 두고, 검색용 정규화 사본을 병행 저장해 단일
    # 인덱스로 양쪽 케이스를 모두 흡수.
    normalized_aliases: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MergeMutation:
    """`EntityMerger` 의 결과 — adapter 가 한 트랜잭션으로 set 한다.

    WHY domain/models 에 둠: 어댑터 (`graph.py`) 와 도메인 (`identity.py`) 둘
    다 참조하므로 두 모듈의 상위 (models) 에 정의해 import 순환 회피.
    `embedding` 필드는 의도적으로 없다 — PRD 2 §5.3 "병합 시 embedding 재계산
    안 함" 을 타입으로 강제.
    """

    id: str
    aliases: list[str]
    description: str
    properties: dict[str, Any]
    source_refs: list[SourceRef]
    updated_at: str
    normalized_aliases: list[str] = field(default_factory=list)


def now_rfc3339() -> str:
    """RFC 3339 (UTC) timestamp — PRD 3 §1.1 의 `format: date-time` 충족."""
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
