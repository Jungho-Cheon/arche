"""4 단계 매처 — 각 step 의 hit / miss 동작.

테스트는 repo / embedder 를 mock 으로 주입해 step 별 분기를 따로 강제한다.
EMBEDDING_MATCH_THRESHOLD = 0.92 의 경계도 결정적으로 검증.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import math

from opentology_api.domain.identity import (
    EMBEDDING_MATCH_THRESHOLD,
    EntityMatcher,
    normalize,
)
from opentology_api.domain.models import (
    ExtractedEntity,
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
