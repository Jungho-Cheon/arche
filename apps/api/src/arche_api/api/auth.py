"""Auth + namespace 미들웨어 — Bearer 토큰에서 namespace_id 를 뽑는다.

토큰 검증은 외부(사내 SSO gateway / API key store)에 위임하고 이 모듈은 주입 포인트만
정의한다. 시제품 기본값은 토큰 자체가 namespace_id 다(예: `Bearer ns:work-a`). 사내
인프라를 도입하면 JWT decoder 등으로 교체한다."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


DEFAULT_NAMESPACE = "default"
# 시제품 단계 — 토큰 prefix 가 "ns:" 로 시작하면 그 뒤가 namespace.
TOKEN_PREFIX = "ns:"


@dataclass(frozen=True)
class AuthContext:
    """요청 1 건의 인증 컨텍스트. handler / dependency 가 받는 표준 dataclass."""

    namespace_id: str
    user_id: str | None = None
    token: str | None = None


def parse_authorization_header(header_value: str | None) -> AuthContext:
    """Authorization header → AuthContext.

    시제품 default — 헤더가 없으면 default namespace 로 anonymous 진행 (단일
    사용자 / 사내 단일 호스트 가정). 사내 인프라 도입 시 *strict* 모드로 전환:
    헤더 없으면 401.
    """
    if not header_value:
        return AuthContext(namespace_id=DEFAULT_NAMESPACE)
    if not header_value.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "not_authorized",
                    "message": "Authorization header must use Bearer scheme",
                }
            },
        )
    token = header_value[7:].strip()
    if token.startswith(TOKEN_PREFIX):
        ns = token[len(TOKEN_PREFIX) :] or DEFAULT_NAMESPACE
        return AuthContext(namespace_id=ns, token=token)
    # 일반 토큰 — 시제품 단계는 토큰 자체를 user_id 대신 보관.
    return AuthContext(
        namespace_id=DEFAULT_NAMESPACE, user_id=token, token=token
    )


def auth_context_dep(request: Request) -> AuthContext:
    """FastAPI dependency — 요청 헤더에서 AuthContext 추출.

    사내 인프라 도입 시 (Phase 3 결정) JWT decoder / SSO 콜백으로 교체. 본 함수가
    *주입 포인트* — 호출자 (router) 가 이 함수 결과만 사용하고 검증 방식 자체는
    캡슐화.
    """
    return parse_authorization_header(request.headers.get("authorization"))
