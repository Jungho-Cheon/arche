"""표준 에러 코드 enum — agent 가 enum 기반으로 분기할 수 있는 closed set."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    # 클라이언트 입력 (4xx)
    INVALID_INPUT = "invalid_input"           # 422 — 필드 형식/누락
    ENTITY_NOT_FOUND = "entity_not_found"     # 404 — id 가 없음
    TASK_NOT_FOUND = "task_not_found"         # 404 — task_id 가 없음
    NOT_AUTHORIZED = "not_authorized"         # 401 — auth header 없음/잘못됨
    PERMISSION_DENIED = "permission_denied"   # 403 — namespace/리소스 권한 없음
    RATE_LIMITED = "rate_limited"             # 429 — 호출 한도 초과
    CONFLICT = "conflict"                     # 409 — 동시 ingest 등
    DIRECTORY_NOT_FOUND = "directory_not_found"  # 422 — 디렉토리 미존재
    NOT_A_DIRECTORY = "not_a_directory"       # 422 — 파일을 디렉토리로 사용

    # 서버 에러 (5xx)
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"  # 503 — 그래프 백엔드 / LLM provider 다운
    EXTRACTION_FAILED = "extraction_failed"  # 500 — LLM 응답 파싱 실패 등
    INTERNAL_ERROR = "internal_error"        # 500 — 알려지지 않은 예외
    TIMEOUT = "timeout"                      # 504 — 백엔드 timeout


# HTTP 상태 코드 매핑 — enum 과 1:1.
ERROR_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_INPUT: 422,
    ErrorCode.ENTITY_NOT_FOUND: 404,
    ErrorCode.TASK_NOT_FOUND: 404,
    ErrorCode.NOT_AUTHORIZED: 401,
    ErrorCode.PERMISSION_DENIED: 403,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.CONFLICT: 409,
    ErrorCode.DIRECTORY_NOT_FOUND: 422,
    ErrorCode.NOT_A_DIRECTORY: 422,
    ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
    ErrorCode.EXTRACTION_FAILED: 500,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.TIMEOUT: 504,
}


def flatten_validation_errors(errors: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """pydantic `ValidationError.errors()` 를 agent 가 파싱 가능한 평탄 형태로 변환.

    각 항목은 정확히 세 키만 노출한다.
    - `loc`  — 위반 필드를 점 표기 한 문자열 (예: `body.keywords`). raw loc 튜플은
               직렬화 모양이 불안정해, agent 가 고칠 필드를 한 문자열로 식별하게 한다.
    - `type` — pydantic 위반 종류 (예: `too_short`, `less_than_equal`,
               `string_pattern_mismatch`). agent 의 enum 기반 분기 신호.
    - `msg`  — 사람이 읽는 설명.

    input / ctx 는 뺀다 — 원본 입력값과 컨텍스트(예외 객체 포함)는 JSON 직렬화가
    불안정하고 위반 식별에 불필요하다. REST 와 MCP 가 같은 헬퍼를 써 형태를 맞춘다.
    """
    flattened: list[dict[str, str]] = []
    for e in errors:
        loc = e.get("loc", ())
        flattened.append(
            {
                "loc": ".".join(str(part) for part in loc),
                "type": str(e.get("type", "")),
                "msg": str(e.get("msg", "")),
            }
        )
    return flattened
