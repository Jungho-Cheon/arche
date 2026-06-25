"""Lucene escape — fulltext 쿼리 안전성."""

from __future__ import annotations

from arche_api.adapters.graph import _lucene_escape


def test_simple_keyword_unchanged():
    assert _lucene_escape("쿠폰") == "쿠폰"


def test_special_chars_escaped():
    out = _lucene_escape("X:Y")
    assert "\\:" in out


def test_multi_token_wrapped_in_parens():
    out = _lucene_escape("여름 쿠폰")
    assert out.startswith("(") and out.endswith(")")


def test_empty_yields_wildcard():
    assert _lucene_escape("") == "*"


def test_reserved_operator_AND_neutralized():
    # 대문자 AND 가 boolean 연산자로 파싱되지 않도록 소문자화 (2026-06-22 ingest 실패).
    out = _lucene_escape("Valuation AND Qualifying")
    assert "AND" not in out  # 대문자 연산자가 남지 않아야 함
    assert "and" in out
    # 멀티 토큰이라 괄호로 감싸야 함.
    assert out.startswith("(") and out.endswith(")")


def test_reserved_operator_standalone():
    assert _lucene_escape("AND") == "and"
    assert _lucene_escape("OR") == "or"
    assert _lucene_escape("NOT") == "not"
