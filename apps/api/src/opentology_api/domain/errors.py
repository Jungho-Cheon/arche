"""도메인 예외 — PRD 3 §9 의 에러 코드 카탈로그와 매핑.

코드 표 (PRD 3 §9):

| HTTP | code                    | 의미                                                |
|------|-------------------------|-----------------------------------------------------|
| 400  | invalid_input           | 요청이 스키마와 안 맞음. details 에 위반 필드      |
| 404  | entity_not_found        | 단일 ID 가 그래프에 없음 (get_entity / find_path 등)|
| 422  | unprocessable           | 스키마는 맞지만 의미상 처리 불가 (from == to 등)   |
| 429  | rate_limited            | (post-MVP) 호출 빈도 제한 초과                      |
| 500  | internal_error          | 예기치 못한 서버 오류                                |
| 503  | dependency_unavailable  | 그래프 DB / 임베딩 모델 응답 없음                    |

WHY 한 모듈에 모은 베이스 + 서브클래스: 예외별 HTTP code / 응답 envelope code
의 매핑을 *한 곳* 에서 관리. main.py 의 exception handler 는 OpentologyError 만
catch 해 cope/http_status 를 그대로 envelope 으로 직렬화한다.
"""

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


class EntityNotFoundError(OpentologyError):
    """단일 ID 조회 실패 — get_entity / get_neighbors / find_path 의 from/to.

    WHY 별도 클래스: PRD 3 §9 의 404 매핑은 *ID 가 그래프에 없을 때만* . 그래프
    엔진 자체가 죽으면 dependency_unavailable 로 분기되므로 두 경로를 타입으로
    구분.
    """

    code = "entity_not_found"
    http_status = 404


class UnprocessableError(OpentologyError):
    """스키마는 맞지만 의미상 처리 불가 — 예: find_path 의 from_id == to_id."""

    code = "unprocessable"
    http_status = 422


class DependencyUnavailableError(OpentologyError):
    code = "dependency_unavailable"
    http_status = 503


class RateLimitedError(OpentologyError):
    """post-MVP. MVP 에서는 사용 안 함 — 코드 카탈로그 형태만 미리 정의.

    WHY 미리 정의: PRD 3 §9 의 카탈로그를 *코드와 1:1* 로 맞추기 위해. MVP 의
    어느 라우터도 raise 하지 않지만, post-MVP 에서 throttle middleware 가 들어올
    때 단일 import 로 활용 가능.
    """

    code = "rate_limited"
    http_status = 429
