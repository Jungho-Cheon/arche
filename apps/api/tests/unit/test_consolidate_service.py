"""EntityConsolidator 도메인 단위 테스트 — ADR-0008 D2.

FakeConsolidationLLM + ConsolidatorGraph 로 sweep 흐름 / generic 자기지칭 분리
/ idempotent merge / dry_run 분기를 모두 외부 의존성 없이 검증.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

import pytest

from opentology_api.adapters.graph import GraphRepository
from opentology_api.domain.consolidate import (
    CONSOLIDATION_LOWER_SIMILARITY,
    ConsolidationDecision,
    ConsolidationLLM,
    EntityConsolidator,
)
from opentology_api.domain.identity import EMBEDDING_MATCH_THRESHOLD
from opentology_api.domain.models import (
    MergeMutation,
    SourceRef,
    StoredEntity,
    now_rfc3339,
)
from opentology_api.test_support import FakeGraph


def _ulid(tag: int) -> str:
    """26 자 ULID 패턴 ID (단위 테스트 결정성 우선)."""
    return f"{tag:026d}".replace("0", "A", 1) if tag == 0 else f"{tag:026d}"


def _stored(
    *,
    id: str,
    name: str,
    type_: str = "company",
    aliases: list[str] | None = None,
    description: str | None = None,
    embedding: list[float] | None = None,
    source_paths: list[str] | None = None,
    created_at: str | None = None,
) -> StoredEntity:
    now = created_at or now_rfc3339()
    refs = [SourceRef(source_path=p) for p in (source_paths or ["docs/a.md"])]
    return StoredEntity(
        id=id,
        name=name,
        type=type_,
        aliases=aliases or [],
        description=description,
        properties={},
        source_refs=refs,
        created_at=now,
        updated_at=now,
        embedding=embedding or [0.0] * 8,
        normalized_name=name.lower(),
        normalized_aliases=[a.lower() for a in (aliases or [])],
    )


@dataclass
class ConsolidatorGraph(FakeGraph):
    """consolidator sweep 의 in-memory 그래프 stub.

    `entities` 는 id → StoredEntity. `vector_search` 는 단순 cosine top-k.
    `apply_merge_mutation` 은 메모리 노드 갱신, `delete_entity` 는 노드 제거,
    `transfer_relations_to_survivor` 는 호출 추적.
    """

    entities: dict[str, StoredEntity] = field(default_factory=dict)
    neighbor_map: dict[str, list[str]] = field(default_factory=dict)
    transfer_calls: list[tuple[str, str]] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)
    merge_mutations: list[MergeMutation] = field(default_factory=list)

    def __post_init__(self) -> None:
        FakeGraph.__init__(self)

    def add(self, entity: StoredEntity) -> None:
        self.entities[entity.id] = entity

    def set_neighbors(self, entity_id: str, names: list[str]) -> None:
        self.neighbor_map[entity_id] = names

    # --- GraphRepository overrides ---

    def iterate_entities(self, *, batch_size=200) -> Iterator[StoredEntity]:
        for eid in sorted(self.entities):
            yield self.entities[eid]

    def vector_search(self, *, embedding, top_k, type_):
        scored: list[tuple[float, StoredEntity]] = []
        for e in self.entities.values():
            if e.type != type_:
                continue
            scored.append((_cosine(embedding, e.embedding), e))
        scored.sort(key=lambda r: r[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def neighbor_names(self, *, entity_id, limit):
        return list(self.neighbor_map.get(entity_id, []))[:limit]

    def apply_merge_mutation(self, *, mutation):
        e = self.entities[mutation.id]
        merged = StoredEntity(
            id=mutation.id,
            name=e.name,
            type=e.type,
            aliases=mutation.aliases,
            description=mutation.description or e.description,
            properties=mutation.properties,
            source_refs=mutation.source_refs,
            created_at=e.created_at,
            updated_at=mutation.updated_at,
            embedding=e.embedding,
            normalized_name=e.normalized_name,
            normalized_aliases=mutation.normalized_aliases,
        )
        self.entities[mutation.id] = merged
        self.merge_mutations.append(mutation)

    def transfer_relations_to_survivor(self, *, survivor_id, loser_id, now):
        self.transfer_calls.append((survivor_id, loser_id))

    def delete_entity(self, *, entity_id):
        self.deleted_ids.append(entity_id)
        self.entities.pop(entity_id, None)


def _cosine(a, b) -> float:
    import math

    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


@dataclass
class FakeLLM(ConsolidationLLM):
    """간단한 LLM stub — 호출 인자 기록 + 사전 정의 응답."""

    responses: dict[tuple[str, str], ConsolidationDecision] = field(
        default_factory=dict
    )
    default: ConsolidationDecision = field(
        default_factory=lambda: ConsolidationDecision(
            same=False, confidence=0.0, reason="default"
        )
    )
    calls: list[tuple[str, str]] = field(default_factory=list)

    def judge_same_entity(
        self,
        *,
        a,
        b,
        a_neighbors,
        b_neighbors,
        a_source_paths,
        b_source_paths,
    ):
        key = (a.id, b.id) if a.id <= b.id else (b.id, a.id)
        self.calls.append(key)
        return self.responses.get(key, self.default)


# WHY embedding 쌍 설계: 정확한 cosine 으로 단위 벡터 쌍을 만든다.
# `a = e1`, `b = cos·e1 + sin·e2` 형태로 두면 cosine(a,b) = cos 그대로.
def _vec_with_cos_to_unit_e1(cos_value: float) -> list[float]:
    import math

    sin = math.sqrt(max(0.0, 1.0 - cos_value * cos_value))
    return [cos_value, sin] + [0.0] * 6


_UNIT_E1: list[float] = [1.0] + [0.0] * 7


class TestEntityConsolidator:
    def test_in_band_pair_merged_when_llm_confirms(self):
        # 두 entity 가 cosine ~ 0.88 — 회색지대.
        graph = ConsolidatorGraph()
        a = _stored(
            id=_ulid(1),
            name="VVIP",
            embedding=list(_UNIT_E1),
            source_paths=["docs/loyalty.md"],
            created_at="2026-06-01T00:00:00Z",
        )
        b = _stored(
            id=_ulid(2),
            name="다이아 등급",
            embedding=_vec_with_cos_to_unit_e1(0.88),  # cosine ~ 0.90
            source_paths=["docs/policy.md"],
            created_at="2026-06-02T00:00:00Z",
        )
        graph.add(a)
        graph.add(b)
        graph.set_neighbors(a.id, ["프리미엄 쿠폰", "전용 상담"])
        graph.set_neighbors(b.id, ["전용 상담", "VIP 라운지"])

        sim = _cosine(a.embedding, b.embedding)
        assert CONSOLIDATION_LOWER_SIMILARITY <= sim < EMBEDDING_MATCH_THRESHOLD

        llm = FakeLLM(
            responses={
                (a.id, b.id): ConsolidationDecision(
                    same=True, confidence=0.92, reason="same loyalty tier"
                )
            }
        )
        consolidator = EntityConsolidator(repo=graph, llm=llm)
        report = consolidator.consolidate()

        assert report.candidates_total == 1
        assert report.llm_calls == 1
        assert report.merged_count == 1
        survivor, loser, _, conf = report.merged_pairs[0]
        # survivor = 더 빠른 created_at = a.
        assert survivor == a.id
        assert loser == b.id
        assert conf == pytest.approx(0.92)
        # 그래프 mutate 흔적.
        assert graph.transfer_calls == [(a.id, b.id)]
        assert graph.deleted_ids == [b.id]
        # survivor 의 aliases 에 loser 의 name 흡수.
        survivor_now = graph.entities[a.id]
        assert "다이아 등급" in survivor_now.aliases

    def test_low_confidence_rejected(self):
        graph = ConsolidatorGraph()
        a = _stored(id=_ulid(1), name="VVIP", embedding=list(_UNIT_E1))
        b = _stored(id=_ulid(2), name="다이아 등급", embedding=_vec_with_cos_to_unit_e1(0.88))
        graph.add(a)
        graph.add(b)
        llm = FakeLLM(
            responses={
                (a.id, b.id): ConsolidationDecision(
                    same=True, confidence=0.6, reason="weak"
                )
            }
        )
        report = EntityConsolidator(repo=graph, llm=llm).consolidate()
        assert report.merged_count == 0
        assert report.rejected_count == 1
        reason = report.rejected_pairs[0][3]
        assert "llm_different" in reason

    def test_out_of_band_pair_not_candidate(self):
        # 두 벡터가 직교 — cosine ≈ 0. 후보 자체에 들어가지 않음 (LLM 호출 0).
        graph = ConsolidatorGraph()
        a = _stored(
            id=_ulid(1), name="VVIP", embedding=[1.0, 0, 0, 0, 0, 0, 0, 0]
        )
        b = _stored(
            id=_ulid(2),
            name="자동차",
            embedding=[0, 0, 0, 0, 0, 0, 0, 1.0],
        )
        graph.add(a)
        graph.add(b)
        llm = FakeLLM()
        report = EntityConsolidator(repo=graph, llm=llm).consolidate()
        assert report.candidates_total == 0
        assert report.llm_calls == 0
        assert report.merged_count == 0

    def test_above_streaming_threshold_skipped(self):
        # cosine ≥ 0.92 는 streaming matcher 가 이미 처리. consolidator 는 건드리지 않음.
        graph = ConsolidatorGraph()
        a = _stored(id=_ulid(1), name="VVIP", embedding=list(_UNIT_E1))
        b = _stored(id=_ulid(2), name="VVIP1", embedding=_vec_with_cos_to_unit_e1(0.95))
        sim = _cosine(a.embedding, b.embedding)
        assert sim >= EMBEDDING_MATCH_THRESHOLD
        graph.add(a)
        graph.add(b)
        llm = FakeLLM()
        report = EntityConsolidator(repo=graph, llm=llm).consolidate()
        assert report.candidates_total == 0
        assert report.merged_count == 0

    def test_generic_self_reference_separation_skips_llm(self):
        # "the Company" 두 노드가 다른 source_path → LLM 호출 없이 분리 유지.
        graph = ConsolidatorGraph()
        a = _stored(
            id=_ulid(1),
            name="the Company",
            embedding=list(_UNIT_E1),
            source_paths=["docs/amcor_10k.md"],
        )
        b = _stored(
            id=_ulid(2),
            name="the Company",
            embedding=_vec_with_cos_to_unit_e1(0.88),
            source_paths=["docs/amd_10k.md"],
        )
        graph.add(a)
        graph.add(b)
        llm = FakeLLM()  # called 면 default same=False
        report = EntityConsolidator(repo=graph, llm=llm).consolidate()
        assert report.candidates_self_reference_skipped == 1
        assert report.llm_calls == 0
        assert report.merged_count == 0
        # rejected reason.
        assert any(
            "self_reference_separation" in r[3] for r in report.rejected_pairs
        )

    def test_generic_self_reference_same_source_path_goes_to_llm(self):
        # 같은 source_path 의 두 "the Company" 는 LLM 검증.
        graph = ConsolidatorGraph()
        a = _stored(
            id=_ulid(1),
            name="the Company",
            embedding=list(_UNIT_E1),
            source_paths=["docs/amcor_10k.md"],
        )
        b = _stored(
            id=_ulid(2),
            name="the Company",
            embedding=_vec_with_cos_to_unit_e1(0.88),
            source_paths=["docs/amcor_10k.md"],
        )
        graph.add(a)
        graph.add(b)
        llm = FakeLLM(
            responses={
                (a.id, b.id): ConsolidationDecision(
                    same=True, confidence=0.9, reason="same doc"
                )
            }
        )
        report = EntityConsolidator(repo=graph, llm=llm).consolidate()
        assert report.candidates_self_reference_skipped == 0
        assert report.llm_calls == 1
        assert report.merged_count == 1

    def test_dry_run_records_pairs_without_mutate(self):
        graph = ConsolidatorGraph()
        a = _stored(id=_ulid(1), name="A", embedding=list(_UNIT_E1))
        b = _stored(id=_ulid(2), name="B", embedding=_vec_with_cos_to_unit_e1(0.88))
        graph.add(a)
        graph.add(b)
        llm = FakeLLM(
            responses={
                (a.id, b.id): ConsolidationDecision(
                    same=True, confidence=0.95, reason="x"
                )
            }
        )
        report = EntityConsolidator(repo=graph, llm=llm).consolidate(dry_run=True)
        assert report.merged_count == 1
        # mutate 안 됨.
        assert graph.transfer_calls == []
        assert graph.deleted_ids == []
        assert graph.merge_mutations == []

    def test_already_merged_pair_skipped_in_run(self):
        # a-b, b-c 는 모두 회색지대 (cos 0.88) 후보, a-c 는 직교 (후보 X).
        # 첫 쌍 (a, b) merge 시 b 가 loser → 두 번째 쌍 (b, c) 는 b 가 이미
        # loser 라 already_merged_in_run 분기로 skip.
        import math

        graph = ConsolidatorGraph()
        # a 는 e1, b 는 (0.88, sin θ_b, 0, ..), c 는 (0.88, -sin θ_b, 0, ..)
        # 가 아닌 2θ 평면 회전으로 두면 a-b 0.88, b-c 0.88, a-c < 0.85.
        # b 와 c 의 e1 성분은 동일 0.88, e2 성분은 sin(arccos(0.88)) 의
        # 부호만 다름. cos(b, c) = 0.88*0.88 + sin*(-sin) = 0.7744 - 0.2256
        # = 0.5488 — 회색지대 밖. 다른 구성이 필요.
        # 깔끔한 구성: b 의 회전각 θ ≈ arccos(0.88) ≈ 28.36°, c 는 b 에서
        # 다시 28.36° 회전. a-b cos=0.88, b-c cos=0.88, a-c cos=cos(56.72°)
        # ≈ 0.5488 (후보 X).
        target = 0.88
        sin_t = math.sqrt(1 - target * target)
        cos_2t = 2 * target * target - 1
        sin_2t = 2 * target * sin_t
        a = _stored(id=_ulid(1), name="A", embedding=list(_UNIT_E1))
        b = _stored(
            id=_ulid(2), name="B", embedding=[target, sin_t] + [0.0] * 6
        )
        c = _stored(
            id=_ulid(3), name="C", embedding=[cos_2t, sin_2t] + [0.0] * 6
        )
        graph.add(a)
        graph.add(b)
        graph.add(c)

        decisions = {}
        for x, y in [(a, b), (b, c)]:
            key = (x.id, y.id) if x.id <= y.id else (y.id, x.id)
            decisions[key] = ConsolidationDecision(
                same=True, confidence=0.95, reason="x"
            )
        llm = FakeLLM(responses=decisions)
        report = EntityConsolidator(repo=graph, llm=llm).consolidate()

        # candidates 는 (a-b), (b-c) 두 쌍만. (a-c) 는 cos ≈ 0.5488 → 후보 X.
        assert report.candidates_total == 2
        # 첫 쌍 (a, b) merge → b loser. 두 번째 쌍 (b, c) 는 already_merged_in_run.
        assert report.merged_count == 1
        merged_loser_ids = {l for _, l, _, _ in report.merged_pairs}
        assert b.id in merged_loser_ids
        rejected_reasons = [r[3] for r in report.rejected_pairs]
        assert any("already_merged_in_run" in r for r in rejected_reasons)

    def test_zero_embedding_skipped(self):
        # embedding 이 비었거나 zero vector 인 entity 는 후보에 안 들어감.
        graph = ConsolidatorGraph()
        a = _stored(id=_ulid(1), name="A", embedding=[])
        b = _stored(id=_ulid(2), name="B", embedding=_vec_with_cos_to_unit_e1(0.88))
        graph.add(a)
        graph.add(b)
        llm = FakeLLM()
        report = EntityConsolidator(repo=graph, llm=llm).consolidate()
        # a 의 embedding 이 비어 sweep 자체에서 skip — 후보 풀 비어.
        assert report.candidates_total == 0
        assert report.llm_calls == 0
