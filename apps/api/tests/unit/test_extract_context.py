"""ExtractContext / ExtractContextBuilder / render_context_block — ADR-0009 PR B.

FakeGraph stub 으로 KNOWN_ENTITIES 후보 선정 + schema summary + context block
직렬화 검증.
"""

from __future__ import annotations

from arche_api.domain.extract_context import (
    ExtractContext,
    ExtractContextBuilder,
    KnownEntity,
    SchemaSummary,
    extract_keywords,
    render_context_block,
)
from arche_api.domain.models import Node, SourceRef, now_rfc3339
from arche_api.domain.ports import EntityTypeStat, KeywordHit, RelationTypeStat
from arche_api.test_support import FakeGraph


def _node(id_: str, name: str, type_: str, aliases=None, desc=None) -> Node:
    now = now_rfc3339()
    return Node(
        id=id_,
        name=name,
        type=type_,
        aliases=list(aliases or []),
        description=desc,
        properties={},
        source_refs=[SourceRef(source_path="/tmp/x.md")],
        created_at=now,
        updated_at=now,
    )


def _ulid(tag: int) -> str:
    return f"{tag:026d}".upper()


# ----- extract_keywords -----


def test_extract_keywords_picks_proper_nouns_and_skips_trivial():
    text = (
        "The Company filed Q1 2026 results. Amcor plc reported strong growth. "
        "Boeing remained stable. Notes: management commented."
    )
    kws = extract_keywords(text, limit=6)
    # 고유명사 추정 토큰만 (Amcor, Boeing, Company...) — 단 Company 는 trivial 에서 제외.
    assert "Amcor" in kws
    assert "Boeing" in kws
    # trivial 제외 — Q1, Notes, The, Company.
    assert "Q1" not in kws
    assert "Notes" not in kws
    assert "The" not in kws
    assert "Company" not in kws


def test_extract_keywords_handles_korean():
    # 같은 명사를 여러 번 등장시켜 빈도 정렬에서 surface 되도록.
    text = (
        "쿠팡 의 정산 정책. 쿠팡 셀러 정책 은 매월 정산. 쿠팡 셀러 정책 변경."
    )
    kws = extract_keywords(text, limit=4)
    # 빈도 DESC: 쿠팡 (3), 셀러 (2) / 정산 (2) / 정책 (3).
    assert "쿠팡" in kws
    assert "정책" in kws


def test_extract_keywords_orders_by_frequency():
    text = "A B C A A B"
    # extract_keywords 패턴은 1 자 단어 매칭 안 함 — 빈 결과 OK.
    # 빈도 정렬 검증을 위해 2 자 이상 사용:
    text = "Boeing Boeing Boeing Amcor Amcor Tesla"
    kws = extract_keywords(text, limit=3)
    assert kws == ["Boeing", "Amcor", "Tesla"]


# ----- ExtractContextBuilder -----


class _StubGraph(FakeGraph):
    def __init__(
        self,
        keyword_results: dict[str, list[KeywordHit]] | None = None,
        entity_stats: list[EntityTypeStat] | None = None,
        relation_stats: list[RelationTypeStat] | None = None,
    ) -> None:
        super().__init__()
        self._kw_results = keyword_results or {}
        self._entity_stats = entity_stats or []
        self._relation_stats = relation_stats or []

    def find_by_keywords_scored(self, *, keywords, limit_per_keyword, namespace_id="default"):
        hits: list[KeywordHit] = []
        for kw in keywords:
            hits.extend(self._kw_results.get(kw, [])[:limit_per_keyword])
        return hits

    def get_schema_summary(self, *, examples_per_type=5, namespace_id="default"):
        return self._entity_stats, self._relation_stats


def test_builder_returns_empty_known_entities_when_no_hits():
    builder = ExtractContextBuilder(graph=_StubGraph())
    ctx = builder.build(
        source_path="/tmp/a.md", chunk_text="Random text with Amcor and Boeing."
    )
    assert ctx.known_entities == []
    assert ctx.schema.entity_types == []
    assert ctx.is_empty_graph()


def test_builder_returns_top_k_known_entities_ranked_by_raw_score():
    nodes = {
        "Amcor": _node(_ulid(1), "Amcor plc", "company", aliases=["Amcor"], desc="..."),
        "Boeing": _node(_ulid(2), "Boeing Co", "company", aliases=["Boeing"], desc="aircraft"),
    }
    kw_results = {
        "Amcor": [KeywordHit(node=nodes["Amcor"], raw_score=0.9, matched_keyword="Amcor")],
        "Boeing": [KeywordHit(node=nodes["Boeing"], raw_score=0.5, matched_keyword="Boeing")],
    }
    builder = ExtractContextBuilder(graph=_StubGraph(keyword_results=kw_results))
    ctx = builder.build(
        source_path="/tmp/a.md", chunk_text="Amcor and Boeing financial details"
    )
    assert len(ctx.known_entities) == 2
    # 점수 DESC.
    assert ctx.known_entities[0].name == "Amcor plc"
    assert ctx.known_entities[1].name == "Boeing Co"


def test_builder_dedupes_by_node_id_keeping_max_score():
    nodes = {"Amcor": _node(_ulid(1), "Amcor plc", "company")}
    # 두 keyword 가 같은 node 를 surface 시킴.
    kw_results = {
        "Amcor": [KeywordHit(node=nodes["Amcor"], raw_score=0.4, matched_keyword="Amcor")],
        "Boeing": [KeywordHit(node=nodes["Amcor"], raw_score=0.9, matched_keyword="Boeing")],
    }
    builder = ExtractContextBuilder(graph=_StubGraph(keyword_results=kw_results))
    ctx = builder.build(
        source_path="/tmp/a.md", chunk_text="Amcor and Boeing context"
    )
    assert len(ctx.known_entities) == 1
    assert ctx.known_entities[0].id == _ulid(1)


def test_builder_collects_schema_summary():
    entity_stats = [
        EntityTypeStat(type="company", count=47, examples=[]),
        EntityTypeStat(type="policy", count=15, examples=[]),
    ]
    relation_stats = [
        RelationTypeStat(type="REPORTS", count=10, common_pairs=[]),
        RelationTypeStat(type="COMPETES_WITH", count=5, common_pairs=[]),
    ]
    builder = ExtractContextBuilder(
        graph=_StubGraph(
            entity_stats=entity_stats, relation_stats=relation_stats
        )
    )
    ctx = builder.build(source_path="/tmp/a.md", chunk_text="anything")
    assert ctx.schema.entity_types == [("company", 47), ("policy", 15)]
    assert sorted(ctx.schema.relation_types) == ["COMPETES_WITH", "REPORTS"]


# ----- render_context_block -----


def test_render_includes_three_section_headers_and_known_entities():
    ctx = ExtractContext(
        doc=__import__("arche_api.domain.extract_context", fromlist=["DocContext"]).DocContext(
            file_path="/x.md",
            main_entity_name="Amcor plc",
            main_entity_type="company",
            main_entity_aliases=["Amcor", "the Company"],
        ),
        known_entities=[
            KnownEntity(
                id=_ulid(1),
                name="Amcor plc",
                type="company",
                aliases=["Amcor"],
                description_one_line="...",
            )
        ],
        schema=SchemaSummary(
            entity_types=[("company", 5)], relation_types=["REPORTS"]
        ),
    )
    block = render_context_block(ctx)
    assert "[DOC_CONTEXT]" in block
    assert "main_entity:" in block
    assert "Amcor plc" in block
    assert "[KNOWN_ENTITIES]" in block
    assert _ulid(1) in block
    assert "[SCHEMA]" in block
    assert "REPORTS" in block


def test_render_handles_empty_graph_gracefully():
    from arche_api.domain.extract_context import DocContext

    ctx = ExtractContext(
        doc=DocContext(file_path="/x.md"),
        known_entities=[],
        schema=SchemaSummary(entity_types=[], relation_types=[]),
    )
    block = render_context_block(ctx)
    assert "[DOC_CONTEXT]" in block
    assert "[KNOWN_ENTITIES]" in block
    assert "(없음" in block  # 비어 있다는 표시
    assert "[SCHEMA]" in block


# ----- enrichment (source-preserving 보강 메모) -----


def test_render_includes_enrichment_block_when_present():
    from arche_api.domain.extract_context import DocContext

    ctx = ExtractContext(
        doc=DocContext(file_path="/a.md"),
        known_entities=[],
        schema=SchemaSummary(entity_types=[], relation_types=[]),
        enrichment="AmEx = American Express. Treat each table row as a fact.",
    )
    out = render_context_block(ctx)
    assert "[ENRICHMENT]" in out
    assert "AmEx = American Express" in out
    # [DOC_CONTEXT] 다음에 위치 (KNOWN_ENTITIES 앞).
    assert out.index("[DOC_CONTEXT]") < out.index("[ENRICHMENT]")
    assert out.index("[ENRICHMENT]") < out.index("[KNOWN_ENTITIES]")


def test_render_omits_enrichment_when_absent():
    from arche_api.domain.extract_context import DocContext

    ctx = ExtractContext(
        doc=DocContext(file_path="/a.md"),
        known_entities=[],
        schema=SchemaSummary(entity_types=[], relation_types=[]),
    )
    assert "[ENRICHMENT]" not in render_context_block(ctx)
    # 공백만 있는 경우도 통째 생략 — 캐시 키 불변.
    ctx_ws = ExtractContext(
        doc=DocContext(file_path="/a.md"),
        known_entities=[],
        schema=SchemaSummary(entity_types=[], relation_types=[]),
        enrichment="   \n  ",
    )
    assert "[ENRICHMENT]" not in render_context_block(ctx_ws)


def test_builder_sets_enrichment():
    builder = ExtractContextBuilder(graph=_StubGraph())
    ctx = builder.build(
        source_path="/a.md", chunk_text="body", enrichment="X"
    )
    assert ctx.enrichment == "X"
    # 기본값은 None — 비보강 경로 backward-compatible.
    ctx_default = builder.build(source_path="/a.md", chunk_text="body")
    assert ctx_default.enrichment is None
