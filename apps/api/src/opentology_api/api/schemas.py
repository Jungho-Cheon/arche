"""REST 요청/응답 envelope — PRD 3 §0.3."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import Node


T = TypeVar("T")


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


class DataEnvelope(BaseModel, Generic[T]):
    """{ "data": <payload> } — PRD 3 §0.3."""

    model_config = ConfigDict(extra="forbid")

    data: T


# ---------- find_entities (walking skeleton 슬라이스) ----------


class FindEntitiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(min_length=1, max_length=32)
    limit: int = Field(default=10, ge=1, le=50)


class FindEntitiesResponse(BaseModel):
    """walking skeleton 응답 — *Node 배열* .

    WHY *full* PRD 3 §3.4 (matches[].node + score + matched_keyword) 가 아닌
    축약본: 본 워커 사양은 `payload { "entities": [Node, ...] }` 를 요구.
    하이브리드 매칭 (#6) 도입 시 응답을 PRD 3 §3.4 형태로 확장한다.
    """

    model_config = ConfigDict(extra="forbid")

    entities: list[Node]


# ---------- admin/ingest ----------


class AdminIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(min_length=1, description="단일 파일 절대 경로 (.txt 또는 .md)")


class AdminIngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    entities_created: int
    entities_updated: int
    relations_created: int
    relations_skipped_dangling: int


# ---------- healthz ----------


class HealthzResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    neo4j: str
