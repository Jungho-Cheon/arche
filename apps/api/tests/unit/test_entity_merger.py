"""EntityMerger — PRD 2 §5.3 의 병합 규칙 표.

embedding 은 도메인 타입 (MergeMutation) 에 *필드 자체가 없어* 재계산 회피를
타입으로 강제. 본 테스트는 나머지 규칙 (aliases / description / properties /
source_refs / updated_at) 을 한 줄씩 검증.
"""

from __future__ import annotations

from opentology_api.domain.identity import EntityMerger
from opentology_api.domain.models import (
    ExtractedEntity,
    SourceRef,
    StoredEntity,
)


def _existing(
    *,
    aliases=None,
    description=None,
    properties=None,
    source_refs=None,
) -> StoredEntity:
    return StoredEntity(
        id="id_X",
        name="쿠폰 X",
        type="coupon",
        aliases=aliases or [],
        description=description,
        properties=properties or {},
        source_refs=source_refs or [SourceRef(source_path="/s1.md")],
        created_at="2026-06-15T00:00:00Z",
        updated_at="2026-06-15T00:00:00Z",
        embedding=[0.1, 0.2],
        normalized_name="쿠폰 x",
    )


def test_aliases_union_dedupes_by_normalized():
    existing = _existing(aliases=["여름 쿠폰"])
    new = ExtractedEntity(
        name="쿠폰 X", type="coupon", aliases=["여름 쿠폰 ", "X 쿠폰"]
    )
    m = EntityMerger.merge(
        existing=existing,
        e_new=new,
        new_source_ref=SourceRef(source_path="/s2.md"),
        now="2026-06-16T00:00:00Z",
    )
    # 정규화 후 dedupe — '여름 쿠폰' 은 1 번만.
    # 표기는 *먼저 등장한 것* 우선 (existing 의 '여름 쿠폰').
    assert m.aliases.count("여름 쿠폰") + m.aliases.count("여름 쿠폰 ") == 1
    assert "여름 쿠폰" in m.aliases
    assert "X 쿠폰" in m.aliases


def test_description_longer_wins_new_replaces_existing():
    existing = _existing(description="짧은 설명")
    new = ExtractedEntity(
        name="쿠폰 X",
        type="coupon",
        description="훨씬 더 긴 설명으로 본문 컨텍스트가 풍부함",
    )
    m = EntityMerger.merge(
        existing=existing,
        e_new=new,
        new_source_ref=SourceRef(source_path="/s2.md"),
        now="2026-06-16T00:00:00Z",
    )
    assert m.description == "훨씬 더 긴 설명으로 본문 컨텍스트가 풍부함"


def test_description_tie_keeps_existing():
    existing = _existing(description="동률")
    new = ExtractedEntity(name="쿠폰 X", type="coupon", description="동률")
    m = EntityMerger.merge(
        existing=existing,
        e_new=new,
        new_source_ref=SourceRef(source_path="/s2.md"),
        now="2026-06-16T00:00:00Z",
    )
    assert m.description == "동률"


def test_properties_existing_wins_on_conflict():
    existing = _existing(properties={"region": "KR", "color": "red"})
    new = ExtractedEntity(
        name="쿠폰 X",
        type="coupon",
        properties={"region": "JP", "season": "summer"},
    )
    m = EntityMerger.merge(
        existing=existing,
        e_new=new,
        new_source_ref=SourceRef(source_path="/s2.md"),
        now="2026-06-16T00:00:00Z",
    )
    # 기존 우선 — region 은 KR 유지. season 은 신규 (충돌 없음) 추가.
    assert m.properties["region"] == "KR"
    assert m.properties["color"] == "red"
    assert m.properties["season"] == "summer"


def test_source_refs_dedupe_by_tuple():
    existing = _existing(source_refs=[SourceRef(source_path="/s1.md")])
    new = ExtractedEntity(name="쿠폰 X", type="coupon")
    m = EntityMerger.merge(
        existing=existing,
        e_new=new,
        new_source_ref=SourceRef(source_path="/s1.md"),  # 중복
        now="2026-06-16T00:00:00Z",
    )
    assert len(m.source_refs) == 1


def test_source_refs_appends_when_distinct():
    existing = _existing(source_refs=[SourceRef(source_path="/s1.md")])
    m = EntityMerger.merge(
        existing=existing,
        e_new=ExtractedEntity(name="쿠폰 X", type="coupon"),
        new_source_ref=SourceRef(source_path="/s2.md"),
        now="2026-06-16T00:00:00Z",
    )
    assert {sr.source_path for sr in m.source_refs} == {"/s1.md", "/s2.md"}


def test_updated_at_set_to_now():
    existing = _existing()
    m = EntityMerger.merge(
        existing=existing,
        e_new=ExtractedEntity(name="쿠폰 X", type="coupon"),
        new_source_ref=SourceRef(source_path="/s2.md"),
        now="2026-06-16T12:34:56Z",
    )
    assert m.updated_at == "2026-06-16T12:34:56Z"


def test_mutation_has_no_embedding_field():
    """타입에 embedding 필드가 없어 재계산을 *원천적으로* 차단."""
    existing = _existing()
    m = EntityMerger.merge(
        existing=existing,
        e_new=ExtractedEntity(name="쿠폰 X", type="coupon"),
        new_source_ref=SourceRef(source_path="/s2.md"),
        now="2026-06-16T00:00:00Z",
    )
    assert not hasattr(m, "embedding")
