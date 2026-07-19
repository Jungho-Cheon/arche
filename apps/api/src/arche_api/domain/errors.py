"""도메인 예외 — 각 예외가 code 와 http_status 를 들고 있다. main.py 의 핸들러가
ArcheError 를 catch 해 그대로 error envelope 으로 직렬화한다."""

from __future__ import annotations


class ArcheError(Exception):
    """공통 베이스 — code, message, details 셋이 envelope 의 error 로 직렬화된다."""

    code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidInputError(ArcheError):
    code = "invalid_input"
    http_status = 400


class UnsupportedFileTypeError(ArcheError):
    """지원하지 않는 파일 형식."""

    code = "unsupported_file_type"
    http_status = 400


class EntityNotFoundError(ArcheError):
    """단일 ID 가 그래프에 없음(404). 그래프 엔진 자체가 죽으면
    DependencyUnavailableError 로 분기되므로 타입으로 구분한다."""

    code = "entity_not_found"
    http_status = 404


class UnprocessableError(ArcheError):
    """스키마는 맞지만 의미상 처리 불가 — 예: find_path 의 from_id == to_id."""

    code = "unprocessable"
    http_status = 422


class DependencyUnavailableError(ArcheError):
    code = "dependency_unavailable"
    http_status = 503


class RateLimitedError(ArcheError):
    """post-MVP 용 — 현재 어느 라우터도 raise 하지 않는다. 에러 카탈로그를 코드와
    1:1 로 맞추려고 미리 정의만 해 둔다."""

    code = "rate_limited"
    http_status = 429
