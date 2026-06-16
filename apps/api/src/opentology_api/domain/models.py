"""도메인 모델 — PRD 3 §1 의 노드/엣지/소스 참조 스키마.

WHY pydantic v2: REST 응답이 PRD 3 §1.1 의 JSON Schema 와 *완전 일치* 해야 한다.
pydantic 으로 직렬화하면 응답 타입과 스키마 검증을 한 곳에서 관리한다.

WHY embedding 필드 비공개: PRD 3 §1.1 명시 — *Node 응답에 `embedding` 필드는
포함하지 않는다* . 내부 저장용 dataclass (StoredEntity) 와 응답용 모델 (Node) 을
분리해 누출을 막는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    description: str | None = Field(default=None, max_length=500)
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


def now_rfc3339() -> str:
    """RFC 3339 (UTC) timestamp — PRD 3 §1.1 의 `format: date-time` 충족."""
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
