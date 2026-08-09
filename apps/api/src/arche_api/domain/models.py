"""도메인 모델 — 노드/엣지/소스 참조 스키마.

응답 모델은 pydantic 으로 직렬화해 REST 스키마와 한곳에서 맞춘다. embedding 은
Node 응답에 넣지 않으려고 저장용 StoredEntity 와 응답용 Node 를 분리한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------- 응답 모델 (REST 노출) ----------


class SourceRef(BaseModel):
    """소스 참조 — 어느 문서의 몇 번째 청크에서 나왔는지."""

    model_config = ConfigDict(extra="forbid")

    source_path: str
    chunk_index: int | None = None
    total_chunks: int | None = None


class Node(BaseModel):
    """REST 응답용 Node — embedding 필드 없음."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[0-9A-Z]{26}$")
    name: str = Field(max_length=200)
    type: str = Field(max_length=64)
    aliases: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=2000)
    properties: dict[str, str | int | float | bool] = Field(default_factory=dict)
    source_refs: list[SourceRef] = Field(default_factory=list)
    created_at: str  # RFC 3339
    updated_at: str  # RFC 3339


class Edge(BaseModel):
    """관계 엣지 — REST 응답 형태."""

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
    # LLM 이 기존 entity 와의 매칭을 지목한 id. 있으면 매처를 건너뛰고 바로 병합한다.
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


# ---------- 저장 표현 (그래프 어댑터 입력) ----------


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
    namespace_id: str = "default"
    normalized_name: str = ""
    # 검색용 정규화 alias 사본. 표기형 aliases 는 그대로 두고 이 사본으로 lookup 한다.
    normalized_aliases: list[str] = field(default_factory=list)
    # 이 노드가 다시 흡수하면 안 되는 정규화 별칭. 노드를 둘로 가른 뒤 재적재가
    # 갈라 둔 별칭을 도로 union 해 합치는 걸 막는다.
    blocked_aliases: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MergeMutation:
    """EntityMerger 의 결과 — 어댑터가 한 트랜잭션으로 set 한다. embedding 필드가
    없어 "병합 시 embedding 재계산 안 함"을 타입으로 강제한다."""

    id: str
    aliases: list[str]
    description: str
    properties: dict[str, Any]
    source_refs: list[SourceRef]
    updated_at: str
    normalized_aliases: list[str] = field(default_factory=list)
    # None 이면 저장된 값을 그대로 둔다. 리스트를 주면 그 값으로 교체한다.
    blocked_aliases: list[str] | None = None


def now_rfc3339() -> str:
    """RFC 3339 (UTC) timestamp."""
    return datetime.now(tz=UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
