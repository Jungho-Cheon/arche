"""REST 요청/응답 envelope."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..domain.models import Node
from .security import validate_optional_namespace_id

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
    """{ "data": <payload> } 형태의 성공 응답 envelope."""

    model_config = ConfigDict(extra="forbid")

    data: T


# ---------- find_entities ----------


class FindEntitiesRequest(BaseModel):
    """find_entities 입력."""

    model_config = ConfigDict(extra="forbid")

    # 빈 리스트는 계속 거부한다. 앵커 추출에 실패한 호출자가 [] 를 보내는 일이 있는데,
    # 그걸 열거로 받으면 검색에 실패한 호출이 조용히 전량을 돌려받는다. 열거는 필드를
    # *생략* 했을 때만 한다.
    keywords: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=32,
        description=(
            "앵커 키워드. 주면 유사도 상위를 돌려준다. 필드를 생략하면 검색이 아니라 "
            "*열거* 가 되어 types/namespace 조건에 맞는 노드를 id 순으로 전량 훑는다."
        ),
    )
    types: list[str] | None = Field(
        default=None,
        description="필터 — 결과 노드의 type 이 이 리스트에 포함된 것만 반환.",
    )
    limit: int = Field(default=10, ge=1, le=200)
    offset: int = Field(
        default=0,
        ge=0,
        description="이 개수만큼 건너뛴 다음부터. total 과 함께 쪽수를 넘길 때 쓴다.",
    )
    include_scores: bool = Field(
        default=False,
        description=(
            "True 이면 매치마다 lexical/dense 원점수를 응답에 함께 담는다 "
            "(디버깅, 직접 재정렬용)."
        ),
    )
    # 질의할 namespace. REST 는 미지정 시 auth 헤더 > "default", MCP 는 "default".
    namespace_id: str | None = Field(
        default=None,
        min_length=1,
        description="질의할 namespace. 미지정 시 auth 헤더 또는 'default'",
    )

    _ns_check = field_validator("namespace_id")(validate_optional_namespace_id)


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
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fused score (0..1). keywords 없이 열거한 결과면 null (고른 기준이 유사도가 아니다).",
    )
    matched_keyword: str | None = Field(
        default=None,
        description="이 노드를 surface 시킨 input keyword. 열거 결과면 null.",
    )
    scores: MatchScores | None = Field(
        default=None,
        description="include_scores=true 일 때만 set.",
    )


class FindEntitiesResponse(BaseModel):
    """find_entities 출력. envelope 으로 감싼 형태가 최종 REST 응답이다."""

    model_config = ConfigDict(extra="forbid")

    matches: list[EntityMatch]
    total: int = Field(
        default=0,
        ge=0,
        description=(
            "이 조건에 해당하는 노드의 전체 수. matches 는 offset/limit 로 잘린 한 쪽이라, "
            "받은 개수를 전부로 읽지 않게 하려고 늘 함께 돌려준다."
        ),
    )
    offset: int = Field(default=0, ge=0)


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

    _ns_check = field_validator("namespace_id")(validate_optional_namespace_id)


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
