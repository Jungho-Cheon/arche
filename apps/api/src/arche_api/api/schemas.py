"""REST 요청/응답 envelope — PRD 3 §0.3."""

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
    # ADR-0015 — 질의할 namespace. REST 는 미지정 시 auth 헤더 > "default". MCP 는
    # 미지정 시 "default". 검색을 이 namespace 안으로 가둔다 (issue #98 읽기 격리).
    namespace_id: str | None = Field(
        default=None,
        min_length=1,
        description="ADR-0015 — 질의할 namespace. 미지정 시 auth 헤더 또는 'default'",
    )

    _ns_check = field_validator("namespace_id")(_validate_optional_namespace)


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
    """PRD 2 §1.2 — 디렉토리 경로 + dry_run 옵션.

    WHY directory_path: PRD 2 §1.2 가 명시. 단일 파일 ingest 는 CLI 의 `ingest`
    명령으로 처리 (CLI 는 디렉토리/파일 양쪽 받지만 admin REST 는 디렉토리만
    노출 — *멀티 파일 흐름의 진입점* 으로 의미를 좁힌다).
    """

    model_config = ConfigDict(extra="forbid")

    directory_path: str = Field(
        min_length=1, description="디렉토리 절대 경로 (재귀 크롤 대상)"
    )
    dry_run: bool = Field(
        default=False, description="True 면 그래프에 쓰지 않고 추출만 수행."
    )
    # ADR-0015 D2 — namespace 명시 override. 부재 시 auth 헤더의 namespace 또는
    # "default" 사용.
    namespace_id: str | None = Field(
        default=None,
        description="ADR-0015 — entity 의 namespace. 미지정 시 'default' 또는 auth 헤더 추출",
    )

    _ns_check = field_validator("namespace_id")(_validate_optional_namespace)


# ---------- admin/namespaces (ADR-0015 D6) ----------


class NamespaceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace_id: str
    entity_count: int


class AdminNamespacesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespaces: list[NamespaceSummary]


class AdminIngestResponse(BaseModel):
    """PRD 2 §1.2 — 202 Accepted 응답 본문 (작업 ID + 상태 polling URL)."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    status_url: str


class AdminIngestProgress(BaseModel):
    """ingest 작업 진행 상태 — GET /admin/ingest/{task_id}/status 의 progress 필드.

    세 카운터는 발생 단계와 조건이 다르다.

    files_skipped             : ingest 단계에서 short-circuit 된 파일 수. 확장자는
                                지원하지만 (path, SHA-256, 추출기 버전) 이 일치하는
                                성공 회차가 이미 그래프에 있어 LLM 호출을 생략.
    files_pending_skipped     : crawl 단계에서 PENDING_EXTS 로 분류된 파일 수.
                                PENDING_EXTS 가 현재 비어 있어 항상 0. 계약 필드로
                                유지하며 오디오/동영상 등 지원 예정 형식을 위해 예약.
    files_unsupported_skipped : crawl 단계에서 SUPPORTED_EXTS 와 PENDING_EXTS 어느
                                쪽에도 속하지 않는 확장자로 분류된 파일 수.
                                예: .json, .py, .csv.
    """

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
    """PRD 2 §1.3 의 status 응답 본문."""

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
