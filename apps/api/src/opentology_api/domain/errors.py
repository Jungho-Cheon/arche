"""도메인 예외 — PRD 3 §9 의 에러 코드 카탈로그와 매핑."""

from __future__ import annotations


class OpentologyError(Exception):
    """공통 베이스 — code, message, details 셋이 envelope 의 error 로 직렬화된다."""

    code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidInputError(OpentologyError):
    code = "invalid_input"
    http_status = 400


class UnsupportedFileTypeError(OpentologyError):
    """PDF/이미지 등 walking skeleton 범위 밖 — issue #5 follow-up."""

    code = "unsupported_file_type"
    http_status = 400


class DependencyUnavailableError(OpentologyError):
    code = "dependency_unavailable"
    http_status = 503
