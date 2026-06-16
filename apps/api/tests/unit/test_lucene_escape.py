"""Lucene escape — fulltext 쿼리 안전성."""

from __future__ import annotations

from opentology_api.adapters.graph import _lucene_escape


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
