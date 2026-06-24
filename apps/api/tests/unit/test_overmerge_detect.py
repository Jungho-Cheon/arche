"""ADR-0017 방향 6 — detect_overmerged_entities 의 결정적 과잉병합 탐지."""
from __future__ import annotations

from opentology_api.domain.identity import detect_overmerged_entities


def test_clean_entities_not_flagged():
    ents = [
        ("e1", "lurasidone", ["DB08815"]),  # name + 1 ID = 깨끗
        ("e2", "thymidylate synthase (P04818)", ["P04818"]),
        ("e3", "American Express Company", ["AmEx"]),
    ]
    assert detect_overmerged_entities(ents) == []


def test_flags_alias_count_outlier():
    flags = detect_overmerged_entities(
        [("g", "Contact sensitization to oxazolone", [f"alias{i}" for i in range(95)])]
    )
    assert len(flags) == 1
    assert any("alias_count=95" in r for r in flags[0].reasons)


def test_flags_multiple_distinct_identifiers():
    # 서로 다른 단백질 ID 다수 = 별개 엔티티 병합 흔적.
    flags = detect_overmerged_entities(
        [("g", "garbage", ["P00747", "P05121", "P27361", "DB00472"])]
    )
    assert len(flags) == 1
    assert any("distinct_identifiers" in r for r in flags[0].reasons)


def test_flags_deixis_aliases_leaked():
    flags = detect_overmerged_entities(
        [("g", "some concept", ["this study", "our findings", "we"])]
    )
    assert len(flags) == 1
    assert any("non_identifying_aliases" in r for r in flags[0].reasons)


def test_single_id_not_flagged_as_distinct():
    # name 과 alias 가 같은 ID 1개만 → 병합 흔적 아님.
    assert detect_overmerged_entities([("e", "drug (DB00472)", ["DB00472"])]) == []
