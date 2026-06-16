"""`normalize()` — PRD 2 §5.1 의 control variable.

WHY 케이스 분리: normalize 출력 형태가 바뀌면 그래프 동일성 인덱스 값이 모두
달라진다 (ADR-0001 통제 변수). 의도된 정규화 범위 (공백/NFC/lowercase/양끝 흔한
구두점) 만 동작하고 그 이상은 *하지 않는다* 는 사실이 테스트로 굳어야 한다.
"""

from __future__ import annotations

import unicodedata

from opentology_api.domain.identity import normalize


def test_strip_and_lowercase_basic():
    assert normalize("  Hello World  ") == "hello world"


def test_internal_whitespace_collapsed():
    assert normalize("쿠폰\tX\n\n응모") == "쿠폰 x 응모"


def test_nfc_normalization_makes_decomposed_equal_composed():
    # 'ㄱ' 분해형 + 합성형 — NFC 후 같은 결과여야 한다.
    composed = "쿠폰"
    decomposed = unicodedata.normalize("NFD", composed)
    assert normalize(decomposed) == normalize(composed)


def test_trailing_punctuation_trimmed():
    assert normalize("쿠폰 X.") == "쿠폰 x"
    assert normalize("'쿠폰 X'") == "쿠폰 x"
    assert normalize("\"쿠폰 X\"") == "쿠폰 x"
    assert normalize(",쿠폰-X-") == "쿠폰-x"


def test_internal_punctuation_preserved():
    # 내부 구두점은 보존 — "X:Y" 같은 식별자가 깨지면 안 된다.
    assert normalize("X:Y") == "x:y"


def test_korean_particles_not_removed():
    # WHY: 조사/접미사 제거는 false positive 가 많아 의도적으로 안 한다.
    # "쿠폰을" 과 "쿠폰" 은 *다른* 정규화 결과.
    assert normalize("쿠폰을") != normalize("쿠폰")


def test_empty_and_whitespace_only_return_empty():
    assert normalize("") == ""
    assert normalize("   ") == ""
    assert normalize("\t\n") == ""


def test_only_punctuation_returns_empty():
    assert normalize("...") == ""
    assert normalize("''") == ""


def test_mixed_case_english_inside_korean():
    assert normalize("쿠폰 ABC123") == "쿠폰 abc123"


def test_none_input_returns_empty():
    assert normalize(None) == ""  # type: ignore[arg-type]
