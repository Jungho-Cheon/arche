"""4 단계 매처 — 각 step 의 hit / miss 동작.

테스트는 repo / embedder 를 mock 으로 주입해 step 별 분기를 따로 강제한다.
EMBEDDING_MATCH_THRESHOLD = 0.92 의 경계도 결정적으로 검증.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arche_api.domain.identity import (
    EMBEDDING_MATCH_THRESHOLD,
    EntityMatcher,
    normalize,
)
from arche_api.domain.models import (
    ExtractedEntity,
    SourceRef,
    StoredEntity,
)


@dataclass
class FakeRepo:
    """find_by_normalized_name / vector_search 만 책임."""

    norm_index: dict[tuple[str, str], StoredEntity]
    vector_pool: list[StoredEntity]

    def find_by_normalized_name(self, *, normalized: str, type_: str):
        return self.norm_index.get((normalized, type_))

    def vector_search(self, *, embedding, top_k, type_):
        return [c for c in self.vector_pool if c.type == type_][:top_k]


class FakeEmbedder:
    def __init__(self, vec: list[float] | None = None) -> None:
        self.vec = vec or [1.0, 0.0]
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [self.vec for _ in texts]


def _entity(
    name: str,
    *,
    type_: str = "coupon",
    embedding: list[float] | None = None,
) -> StoredEntity:
    return StoredEntity(
        id=f"id_{name}",
        name=name,
        type=type_,
        aliases=[],
        description=None,
        properties={},
        source_refs=[],
        created_at="2026-06-16T00:00:00Z",
        updated_at="2026-06-16T00:00:00Z",
        embedding=embedding or [],
        normalized_name=normalize(name),
    )


def test_step1_exact_normalized_name_hit():
    target = _entity("쿠폰 X")
    repo = FakeRepo(
        norm_index={("쿠폰 x", "coupon"): target},
        vector_pool=[],
    )
    embedder = FakeEmbedder()
    matcher = EntityMatcher(repo=repo, embedder=embedder)

    result = matcher.match(ExtractedEntity(name="쿠폰  X", type="coupon"))
    assert result.step == 1
    assert result.existing is target
    # Step 1 hit 시 embedder 호출 안 됨 (비용 통제).
    assert embedder.calls == 0


def test_step2_alias_second_position_hit():
    target = _entity("쿠폰 X")
    repo = FakeRepo(
        norm_index={("여름 환영 쿠폰", "coupon"): target},
        vector_pool=[],
    )
    embedder = FakeEmbedder()
    matcher = EntityMatcher(repo=repo, embedder=embedder)

    result = matcher.match(
        ExtractedEntity(
            name="모름",
            type="coupon",
            aliases=["무관 별칭", "여름 환영 쿠폰"],
        )
    )
    assert result.step == 2
    assert result.existing is target
    assert embedder.calls == 0


def test_step3_embedding_above_threshold_hit():
    """0.92 임계점 — 정확히 cosine 0.92 인 후보가 hit."""
    # 후보 임베딩을 cosine 0.92 가 되도록 설계: query = [1,0], cand 의 cosine
    # = 0.92 → cand = [0.92, sqrt(1-0.92^2)].
    cand_vec = [0.92, math.sqrt(1 - 0.92**2)]
    cand = _entity("쿠폰 X1", embedding=cand_vec)
    repo = FakeRepo(norm_index={}, vector_pool=[cand])
    embedder = FakeEmbedder(vec=[1.0, 0.0])
    matcher = EntityMatcher(repo=repo, embedder=embedder)

    result = matcher.match(ExtractedEntity(name="쿠폰 X2", type="coupon"))
    assert result.step == 3
    assert result.existing is cand
    assert embedder.calls == 1


def test_step3_embedding_just_below_threshold_misses():
    """0.91999 — threshold 미만 → step 3 miss → step 4."""
    sim = 0.919999
    cand_vec = [sim, math.sqrt(1 - sim**2)]
    cand = _entity("거의 비슷", embedding=cand_vec)
    repo = FakeRepo(norm_index={}, vector_pool=[cand])
    embedder = FakeEmbedder(vec=[1.0, 0.0])
    matcher = EntityMatcher(repo=repo, embedder=embedder)

    result = matcher.match(ExtractedEntity(name="쿠폰 X2", type="coupon"))
    assert result.step == 4
    assert result.existing is None
    # threshold 보다 정확히 EMBEDDING_MATCH_THRESHOLD 위에 있어야 hit.
    assert sim < EMBEDDING_MATCH_THRESHOLD


def test_step4_all_miss_returns_none():
    repo = FakeRepo(norm_index={}, vector_pool=[])
    embedder = FakeEmbedder(vec=[1.0, 0.0])
    matcher = EntityMatcher(repo=repo, embedder=embedder)

    result = matcher.match(
        ExtractedEntity(name="완전 새로운 노드", type="coupon")
    )
    assert result.step == 4
    assert result.existing is None


def test_type_filter_blocks_match():
    """이름은 같아도 type 이 다르면 matching 되면 안 된다."""
    target = _entity("X", type_="product")
    repo = FakeRepo(norm_index={("x", "product"): target}, vector_pool=[])
    embedder = FakeEmbedder()
    matcher = EntityMatcher(repo=repo, embedder=embedder)

    result = matcher.match(ExtractedEntity(name="X", type="coupon"))
    # product 로 인덱싱된 노드는 coupon 입력에 안 잡힌다.
    assert result.step == 4


# ---------- NON_IDENTIFYING_ALIAS_STOPLIST regression (ADR-0008) ----------


def test_step2_skips_non_identifying_alias_stoplist():
    """generic 자기지칭 ("the Company") alias 는 cross-doc Step 2 lookup 에서 제외.

    M6.5 FinanceBench 1M 측정에서 직접 관찰된 catastrophic over-merge 의 원인.
    AMCOR 의 normalized_aliases 에 "the company" 가 인덱싱된 상태에서 AMD 의 같은
    alias 가 Step 2 lookup 으로 AMCOR 와 매칭되면 안 됨.
    """
    amcor = _entity("Amcor plc", type_="Company")
    # 가정: 이전 ingest 에서 "the company" 가 (옛 코드의 버그로) 인덱싱돼 있었다.
    # 본 fix 적용 후에는 인덱싱 자체가 안 되지만, *방어적으로* matcher 도
    # stoplist alias 의 lookup 을 건너뛴다.
    repo = FakeRepo(
        norm_index={("the company", "Company"): amcor},
        vector_pool=[],
    )
    embedder = FakeEmbedder()
    matcher = EntityMatcher(repo=repo, embedder=embedder)

    result = matcher.match(
        ExtractedEntity(
            name="Advanced Micro Devices, Inc.",
            type="Company",
            aliases=["AMD", "the Company", "we", "us"],
        )
    )
    # AMCOR 와 매칭되지 않고 step 4 (신규) — 임베딩까지 갔지만 vector_pool 도 비어
    # 결국 신규 entity.
    assert result.step == 4
    assert result.existing is None


def test_step2_skips_scientific_discourse_aliases():
    """논문 담론 자기지칭("this study" / "our findings")도 Step 2 에서 제외.

    MedHop 실측에서 관측된 over-merge — 논문마다 "this study" 가 같은 문자열이라
    cross-document alias 일치로 무관한 엔티티가 한 노드로 뭉쳤다. 기존 stoplist 는
    10-K 자기지칭만 담아 이 케이스를 못 막았다(2026-06-23 확장).
    """
    paper_a = _entity("Contact sensitization to oxazolone", type_="concept")
    repo = FakeRepo(
        # 이전 논문에서 "this study" 가 인덱싱돼 있었다고 가정.
        norm_index={("this study", "concept"): paper_a},
        vector_pool=[],
    )
    matcher = EntityMatcher(repo=repo, embedder=FakeEmbedder())
    result = matcher.match(
        ExtractedEntity(
            name="lithium-induced neuritogenesis",
            type="concept",
            aliases=["this study", "our findings", "the present results"],
        )
    )
    # 무관한 두 논문이 "this study" 로 병합되면 안 됨 → 신규(step 4).
    assert result.step == 4
    assert result.existing is None


def test_generic_deixis_pattern_catches_unseen_variants():
    """결정적 패턴이 명시 목록에 없는 변형도 비-식별로 판정."""
    from arche_api.domain.identity import is_identifying_alias

    for phrase in [
        "the present study",
        "our findings",
        "these results",
        "this investigation",
        "the current methodology",
        "our experiments",
    ]:
        assert not is_identifying_alias(phrase), phrase


def test_deixis_pattern_does_not_eat_real_entities():
    """담론 단어가 들어가도 *순수 deixis 형태가 아니면* 식별성 유지 (병합 가능).

    안전 방향은 under-merge 지만, 명백한 도메인 엔티티까지 막으면 안 된다.
    """
    from arche_api.domain.identity import is_identifying_alias

    for phrase in [
        "Framingham Heart Study",  # 고유명 + study
        "thymidylate synthase",
        "P34969",
        "the Boeing Company",  # "the Company" 와 달리 식별성 있음
        "study group A",  # 한정사 없이 추가 토큰
    ]:
        assert is_identifying_alias(phrase), phrase


def test_step2_still_matches_identifying_alias():
    """stoplist 가 아닌 일반 alias 는 종전대로 Step 2 매칭."""
    coupon = _entity("쿠폰 X")
    repo = FakeRepo(
        norm_index={("여름 환영 쿠폰", "coupon"): coupon},
        vector_pool=[],
    )
    embedder = FakeEmbedder()
    matcher = EntityMatcher(repo=repo, embedder=embedder)

    result = matcher.match(
        ExtractedEntity(
            name="다른 이름",
            type="coupon",
            aliases=["여름 환영 쿠폰", "the Company"],  # stoplist 와 일반 alias 혼합
        )
    )
    # "여름 환영 쿠폰" 으로 Step 2 hit (the Company 는 건너뜀).
    assert result.step == 2
    assert result.existing is coupon


def test_merger_excludes_stoplist_from_normalized_aliases():
    """병합 후 normalized_aliases 인덱스에 stoplist alias 가 *들어가지 않음*."""
    from arche_api.domain.identity import EntityMerger

    existing = _entity("Amcor plc", type_="Company")
    existing = StoredEntity(
        id=existing.id,
        name=existing.name,
        type=existing.type,
        aliases=["Amcor"],
        description=None,
        properties={},
        source_refs=[],
        created_at=existing.created_at,
        updated_at=existing.updated_at,
        embedding=[],
        normalized_name=existing.normalized_name,
        normalized_aliases=["amcor"],
    )
    new = ExtractedEntity(
        name="Amcor plc",
        type="Company",
        aliases=["the Company", "we", "us", "Australia operations"],
    )
    source_ref = SourceRef(source_path="x.md", chunk_index=0)
    mutation = EntityMerger.merge(existing, new, source_ref, now="2026-06-20T00:00:00Z")

    # 표시용 aliases 에는 stoplist alias 도 들어감 (사용자 가독성).
    assert "the Company" in mutation.aliases
    assert "we" in mutation.aliases
    # normalized_aliases 인덱스에는 stoplist alias *없음*.
    assert "the company" not in mutation.normalized_aliases
    assert "we" not in mutation.normalized_aliases
    assert "us" not in mutation.normalized_aliases
    # 일반 alias 는 정상 인덱싱.
    assert "amcor" in mutation.normalized_aliases
    assert "australia operations" in mutation.normalized_aliases
