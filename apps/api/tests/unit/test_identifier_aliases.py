"""ADR-0017 방향 2 — extract_identifier_aliases 의 고정밀 식별자 추출."""
from __future__ import annotations

from opentology_api.domain.identity import extract_identifier_aliases


def test_parenthetical_id_extracted():
    assert extract_identifier_aliases("thymidylate synthase (P04818)") == ["P04818"]
    assert extract_identifier_aliases("interleukin-4 (P05112)") == ["P05112"]


def test_bare_adjacent_id_extracted():
    assert extract_identifier_aliases("serotonin P34969") == ["P34969"]
    assert "DB00472" in extract_identifier_aliases("fluoxetine DB00472 level")


def test_multiple_ids_deduped_in_order():
    out = extract_identifier_aliases("DB00642 (Alimta) targets P04818 and P00374")
    assert out == ["DB00642", "P04818", "P00374"]


def test_generic_short_codes_excluded():
    # 숫자 3개 미만 → generic 코드(over-merge 위험)이므로 제외.
    for name in [
        "Annual Report (10-K)",
        "Form 8-K filing",
        "vitamin B12",
        "Q3 2022 revenue",
        "Section 404(b)",
        "Rule S-1",
    ]:
        assert extract_identifier_aliases(name) == [], name


def test_non_id_names_yield_nothing():
    for name in ["American Express Company", "쿠폰 X", "the present study", ""]:
        assert extract_identifier_aliases(name) == [], name


def test_uniprot_with_mixed_alnum():
    assert extract_identifier_aliases("Q9NQ94 development") == ["Q9NQ94"]
