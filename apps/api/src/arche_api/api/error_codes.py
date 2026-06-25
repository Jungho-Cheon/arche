"""표준 에러 코드 enum — ADR-0013 D2.

agent 가 *enum 기반 분기* 가능하도록 closed set. 추가 코드 도입 시 ADR amend.
각 코드의 `details` 필드 schema 는 정의에 인라인 명시.
"""

from __future__ import annotations

from enum import Enum


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
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"  # 503 — Neo4j / LLM provider 다운
    EXTRACTION_FAILED = "extraction_failed"  # 500 — LLM 응답 파싱 실패 등
    INTERNAL_ERROR = "internal_error"        # 500 — 알려지지 않은 예외
    TIMEOUT = "timeout"                      # 504 — 백엔드 timeout


# HTTP 상태 코드 매핑 — ADR-0013 D2 의 closed enum 과 1:1.
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
