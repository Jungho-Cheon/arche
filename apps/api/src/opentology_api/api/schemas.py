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


# ---------- find_entities (PRD 3 §3.3 / §3.4) ----------


class FindEntitiesRequest(BaseModel):
    """입력 — PRD 3 §3.3.

    WHY `types` / `include_scores` 도 본 슬라이스에서 구현: 둘 다 *입력 계약*
    이므로 (PRD 3 §3.3 이 source of truth) caller 가 호환을 가정한다. 하이브리드
    구현 (#6) 전까지도 lexical-only 컨텍스트에서 의미 있게 동작 가능.
    """

    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(min_length=1, max_length=32)
    types: list[str] | None = Field(
        default=None,
        description="필터 — 결과 노드의 type 이 이 리스트에 포함된 것만 반환.",
    )
    limit: int = Field(default=10, ge=1, le=50)
    include_scores: bool = Field(
        default=False,
        description="True 이면 매치별 raw lexical/dense 점수 동봉 (디버깅 / 커스텀 re-rank).",
    )


class MatchScores(BaseModel):
    """include_scores=true 일 때 노출되는 raw 점수 (PRD 3 §3.4).

    WHY dense 는 0.0 으로 채워서라도 키를 노출: 하이브리드 도입 (#6) 이후에도
    응답 형태가 *키 등장 여부* 로 갈리지 않게. lexical 만 동작 중이라는 사실은
    별도 컨텍스트 (README 의 walking skeleton 한계 표) 로 안내.
    """

    model_config = ConfigDict(extra="forbid")

    lexical: float = Field(ge=0.0)
    dense: float = Field(ge=0.0, le=1.0)


class EntityMatch(BaseModel):
    """PRD 3 §3.4 의 matches[] 한 항목."""

    model_config = ConfigDict(extra="forbid")

    node: Node
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Fused score — walking skeleton 은 lexical-only 라 max-normalize 된 fulltext 점수.",
    )
    matched_keyword: str = Field(
        description="이 노드를 surface 시킨 input keyword (PRD 3 §3.5: 가장 높은 점수의 keyword).",
    )
    scores: MatchScores | None = Field(
        default=None,
        description="include_scores=true 일 때만 set.",
    )


class FindEntitiesResponse(BaseModel):
    """PRD 3 §3.4 출력. envelope 으로 감싼 형태가 최종 REST 응답."""

    model_config = ConfigDict(extra="forbid")

    matches: list[EntityMatch]


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
