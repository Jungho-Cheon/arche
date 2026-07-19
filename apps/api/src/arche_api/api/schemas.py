"""REST 요청/응답 envelope."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..domain.models import Node
from .security import validate_namespace_id

T = TypeVar("T")


def _validate_optional_namespace(v: str | None) -> str | None:
    """namespace_id 필드 검증 — 미지정(None)은 통과, 값이 있으면 형식 검사(#142)."""
    return v if v is None else validate_namespace_id(v)


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


class DataEnvelope(BaseModel, Generic[T]):
    """{ "data": <payload> } 형태의 성공 응답 envelope."""

    model_config = ConfigDict(extra="forbid")

    data: T


# ---------- find_entities ----------


class FindEntitiesRequest(BaseModel):
    """find_entities 입력."""

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
    # 질의할 namespace. REST 는 미지정 시 auth 헤더 > "default", MCP 는 "default".
    namespace_id: str | None = Field(
        default=None,
        min_length=1,
        description="질의할 namespace. 미지정 시 auth 헤더 또는 'default'",
    )

    _ns_check = field_validator("namespace_id")(_validate_optional_namespace)


class MatchScores(BaseModel):
    """include_scores=true 일 때 노출되는 raw 점수. dense 는 값이 없어도 키를 노출해
    응답 형태가 키 등장 여부로 갈리지 않게 한다."""

    model_config = ConfigDict(extra="forbid")

    lexical: float = Field(ge=0.0)
    dense: float = Field(ge=0.0, le=1.0)


class EntityMatch(BaseModel):
    """matches[] 한 항목."""

    model_config = ConfigDict(extra="forbid")

    node: Node
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Fused score (0..1).",
    )
    matched_keyword: str = Field(
        description="이 노드를 surface 시킨 input keyword.",
    )
    scores: MatchScores | None = Field(
        default=None,
        description="include_scores=true 일 때만 set.",
    )


class FindEntitiesResponse(BaseModel):
    """find_entities 출력. envelope 으로 감싼 형태가 최종 REST 응답이다."""

    model_config = ConfigDict(extra="forbid")

    matches: list[EntityMatch]


# ---------- admin/ingest ----------


class AdminIngestRequest(BaseModel):
    """디렉토리 경로 + dry_run 옵션. admin REST 는 디렉토리만 받는다(단일 파일은 CLI ingest)."""

    model_config = ConfigDict(extra="forbid")

    directory_path: str = Field(
        min_length=1, description="디렉토리 절대 경로 (재귀 크롤 대상)"
    )
    dry_run: bool = Field(
        default=False, description="True 면 그래프에 쓰지 않고 추출만 수행."
    )
    # namespace override. 미지정 시 auth 헤더의 namespace 또는 "default".
    namespace_id: str | None = Field(
        default=None,
        description="entity 의 namespace. 미지정 시 'default' 또는 auth 헤더 추출",
    )

    _ns_check = field_validator("namespace_id")(_validate_optional_namespace)


# ---------- admin/namespaces ----------


class NamespaceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace_id: str
    entity_count: int


class AdminNamespacesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespaces: list[NamespaceSummary]


class AdminIngestResponse(BaseModel):
    """202 Accepted 응답 본문 — 작업 ID + 상태 polling URL."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    status_url: str


class AdminIngestProgress(BaseModel):
    """ingest 작업 진행 상태. files_skipped 는 내용이 안 바뀌어 short-circuit 된 파일,
    files_pending_skipped 와 files_unsupported_skipped 는 crawl 단계에서 확장자로
    걸러진 파일(각각 지원 예정, 미지원)이다."""

    model_config = ConfigDict(extra="forbid")

    files_total: int = Field(description="crawl 이 수집한 지원 파일 총 수 (ingest 시도 대상).")
    files_processed: int = Field(description="ingest 를 완료한 파일 수 (short-circuit 제외).")
    files_skipped: int = Field(
        description=(
            "ingest 단계 short-circuit 파일 수 — 내용(SHA-256) + 추출기 버전이 같아 "
            "재추출 없이 건너뛴 파일. 예: 내용 변경 없이 동일 디렉토리를 재실행."
        )
    )
    files_pending_skipped: int = Field(
        description=(
            "crawl 단계 PENDING_EXTS 분류 파일 수. PENDING_EXTS 가 현재 비어 있어 "
            "항상 0 — 오디오/동영상 등 지원 예정 형식을 위한 예약 필드."
        )
    )
    files_unsupported_skipped: int = Field(
        description=(
            "crawl 단계 미지원 확장자 파일 수 — SUPPORTED_EXTS 와 PENDING_EXTS "
            "어느 쪽에도 속하지 않는 확장자. 예: .json, .py, .csv."
        )
    )


class AdminIngestMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities_created: int
    entities_updated: int
    relations_created: int
    relations_skipped_dangling: int
    chunks_total: int


class AdminIngestError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class AdminIngestStatusResponse(BaseModel):
    """ingest status 응답 본문."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    state: str
    progress: AdminIngestProgress
    metrics: AdminIngestMetrics
    error: AdminIngestError | None = None


# ---------- healthz ----------


class HealthzResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    graph: str
