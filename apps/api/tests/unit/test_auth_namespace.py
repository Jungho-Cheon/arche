"""Auth + namespace 미들웨어 — ADR-0014 D3 + ADR-0015 D1/D2 단위 테스트."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from opentology_api.api.auth import (
    DEFAULT_NAMESPACE,
    AuthContext,
    parse_authorization_header,
)


def test_no_header_returns_default_namespace_anonymous():
    ctx = parse_authorization_header(None)
    assert isinstance(ctx, AuthContext)
    assert ctx.namespace_id == DEFAULT_NAMESPACE
    assert ctx.user_id is None
    assert ctx.token is None


def test_empty_header_returns_default_namespace():
    ctx = parse_authorization_header("")
    assert ctx.namespace_id == DEFAULT_NAMESPACE


def test_non_bearer_scheme_raises_401():
    with pytest.raises(HTTPException) as exc:
        parse_authorization_header("Basic abc:def")
    assert exc.value.status_code == 401
    body = exc.value.detail
    assert body["error"]["code"] == "not_authorized"


def test_bearer_token_with_ns_prefix_extracts_namespace():
    ctx = parse_authorization_header("Bearer ns:work-a")
    assert ctx.namespace_id == "work-a"
    assert ctx.token == "ns:work-a"


def test_bearer_token_with_ns_prefix_falls_back_to_default_when_empty():
    ctx = parse_authorization_header("Bearer ns:")
    assert ctx.namespace_id == DEFAULT_NAMESPACE
    assert ctx.token == "ns:"


def test_generic_bearer_token_preserves_user_id_and_default_ns():
    ctx = parse_authorization_header("Bearer abc123-secret")
    assert ctx.namespace_id == DEFAULT_NAMESPACE
    assert ctx.user_id == "abc123-secret"
    assert ctx.token == "abc123-secret"


def test_bearer_with_uppercase_scheme_accepted():
    ctx = parse_authorization_header("BEARER ns:papers")
    assert ctx.namespace_id == "papers"
