"""EntityConsolidator — post-ingest cross-doc cleanup (ADR-0008 D2).

스트리밍 EntityMatcher (`identity.py`) 의 한계 두 가지를 후처리로 보정한다.

1. *순서 의존* — 같은 두 표현이 시간차 ingest 시 cosine 0.92 임계를 통과 못 해
   별도 노드로 굳어진 경우. 모든 entity 가 적재된 *후* 에 보면 가시.
2. *cosine 0.85-0.92 사이 회색지대* — 의미상 같지만 표면형이 떨어진 쌍 (예
   "VVIP" 와 "VVIP1 등급" 또는 "다이아 등급"). streaming threshold 를 낮추면
   false positive 폭발 위험이라 *후처리에 LLM 검증* 단계를 끼워 안전하게 통합.

ADR-0008 D2 의 *추가 가드* — generic 자기지칭 ("the Company", "we", "당사" 등)
은 source_path 가 *다른 문서* 면 *절대 합치지 않는다* . 1M 측정 (2026-06-20)
의 catastrophic over-merge 직접 원인이 이 케이스라 LLM 호출 전에 hard skip.

알고리즘 O(n × k × log n):

- 모든 entity stream — name + type + embedding + aliases + description + source_refs.
- 각 entity 에 대해 vector_search top_k 후보 (이미 인덱스로 ANN).
- cosine 0.85 이상 0.92 미만인 *후보 쌍* 만 LLM 검증 큐.
- 후보 쌍에 대해 LLM 호출: "둘이 정말 같은 entity 인가" + 양쪽 이웃 요약 동봉.
- same=true AND confidence ≥ 0.8 → 두 노드 병합 (survivor 는 created_at 빠른 쪽).
- inbound + outbound 관계는 survivor 로 옮기고 loser 노드 삭제.

WHY 도메인-only: I/O 는 `GraphRepository` / `ConsolidationLLM` 인터페이스로 주입
받고 본 모듈 자체는 *입력→출력 변환* 만 책임. 단위 테스트가 어댑터 없이 형태를
굳힐 수 있게 (`EntityMatcher` 와 동일 패턴, ADR-0001 측정 통제 변수 원칙).
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..adapters.graph import GraphRepository
from .identity import (
    EMBEDDING_MATCH_THRESHOLD,
    NON_IDENTIFYING_ALIAS_STOPLIST,
    EntityMerger,
    normalize,
)
from .models import MergeMutation, StoredEntity, now_rfc3339


logger = logging.getLogger(__name__)


# WHY 0.85 lower bound: PRD 6 §3.A 의 설계 — streaming 의 0.92 threshold 가
# 놓치는 *의미는 같지만 표면형이 떨어진* 쌍을 잡되, *명백히 다른 두 표현* 까지
# 후보화하지 않는 균형점. 0.85 미만은 후보 자체를 만들지 않아 LLM 호출 비용 0.
# 변경 시 ADR-0008 amend 필요 (측정 통제 변수).
CONSOLIDATION_LOWER_SIMILARITY: float = 0.85


# WHY 0.8 confidence: LLM 의 "same=true" 만으로는 부족 — confidence 가 동시에
# 0.8 이상일 때만 실제 merge. 0.5-0.79 의 모호 케이스는 *분리 유지* 가 안전 측
# 기본값. 추후 메트릭에서 false positive 발생 시 0.85 로 올린다.
MIN_MERGE_CONFIDENCE: float = 0.8


# WHY 후보 ANN top_k = 8: 회색지대 (0.85-0.92) 후보는 top 후보 안에 거의 다 들어
# 온다. 8 이상으로 키워도 추가 hit 률이 급격히 떨어지고 LLM 호출 비용만 증가.
CONSOLIDATION_TOP_K: int = 8


# WHY 이웃 요약에 최대 8 개: LLM 입력 토큰 통제 + 충분한 컨텍스트의 균형.
# survivor 와 loser 양쪽 이웃 8 + 8 = 16 entity 이름이면 회사 식별성 / 도메인
# 단서로 충분.
NEIGHBORHOOD_PEEK: int = 8


@dataclass(frozen=True)
class CandidatePair:
    """ANN + cosine 필터를 통과해 LLM 검증 큐에 올라온 쌍.

    similarity 는 통과한 cosine 값 (디버깅 / 리포트용). a 와 b 는 *id 사전순*
    으로 정렬해 둔다 — 같은 쌍이 양쪽에서 surface 되어도 dedup 키 안정성.
    """

    a: StoredEntity
    b: StoredEntity
    similarity: float


@dataclass(frozen=True)
class ConsolidationDecision:
    """LLM 검증 결과 한 건."""

    same: bool
    confidence: float
    reason: str | None = None


class ConsolidationLLM(ABC):
    """후보 쌍의 동일성 판정 — 본 모듈의 *유일* 한 LLM 의존성.

    WHY 추상화: 측정 통제 변수 (프롬프트 + JSON schema 본문) 가 한 곳에 묶여야
    한다. 어댑터 (OpenAI 구현) 는 본 인터페이스를 만족하는 단일 호출만 노출.
    """

    @abstractmethod
    def judge_same_entity(
        self,
        *,
        a: StoredEntity,
        b: StoredEntity,
        a_neighbors: list[str],
        b_neighbors: list[str],
        a_source_paths: list[str],
        b_source_paths: list[str],
    ) -> ConsolidationDecision: ...


@dataclass
class ConsolidationReport:
    """consolidate 한 회차의 결과 — admin 응답 / evidence 기록용.

    merged_pairs 의 각 항목은 (survivor_id, loser_id, similarity, confidence).
    rejected_pairs 는 (a_id, b_id, similarity, reason).
    """

    entities_scanned: int = 0
    candidates_total: int = 0
    candidates_self_reference_skipped: int = 0
    llm_calls: int = 0
    merged_pairs: list[tuple[str, str, float, float]] = field(default_factory=list)
    rejected_pairs: list[tuple[str, str, float, str]] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def merged_count(self) -> int:
        return len(self.merged_pairs)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_pairs)


def _cosine(a: list[float], b: list[float]) -> float:
    """`identity._cosine` 와 동일 — 모듈 경계 줄이려 로컬 사본.

    의도적으로 가져오기보다 복제 — 측정 통제 변수 (cosine 정의) 가 둘 사이에
    서로 다른 경로로 갈라지지 않도록.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _is_generic_self_reference(entity: StoredEntity) -> bool:
    """이름 자체가 generic 자기지칭 stoplist 에 들어가는가.

    WHY name 만 검사: alias 는 *함께 살아 있는* 정상 entity 에도 stoplist 항목이
    딸려 있을 수 있다 (예: "Boeing" 의 aliases 에 "we" 가 포함). name 자체가
    stoplist 면 *그 노드가 generic 자기지칭* 으로 추출된 것 — 그 경우만 separation
    정책의 대상.
    """
    return normalize(entity.name) in NON_IDENTIFYING_ALIAS_STOPLIST


def _has_shared_source_path(
    a: StoredEntity, b: StoredEntity
) -> bool:
    """두 entity 가 *같은 source_path* 를 공유하는가.

    공유하면 generic 자기지칭이라도 *같은 문서 내 동일 주체* 일 가능성. 공유
    안 하면 서로 다른 문서의 자기지칭 → 절대 합치지 않음 (ADR-0008 직접 원인).
    """
    a_paths = {r.source_path for r in a.source_refs}
    b_paths = {r.source_path for r in b.source_refs}
    return bool(a_paths & b_paths)


def _pair_key(a_id: str, b_id: str) -> tuple[str, str]:
    return (a_id, b_id) if a_id <= b_id else (b_id, a_id)


class EntityConsolidator:
    """후처리 cross-doc entity cleanup — ADR-0008 D2.

    consume 함수 한 개. 호출자는 progress 콜백으로 진행도 (admin task UI) 를
    받을 수 있다.
    """

    def __init__(
        self,
        *,
        repo: GraphRepository,
        llm: ConsolidationLLM,
        top_k: int = CONSOLIDATION_TOP_K,
        lower_similarity: float = CONSOLIDATION_LOWER_SIMILARITY,
        min_confidence: float = MIN_MERGE_CONFIDENCE,
        neighborhood_peek: int = NEIGHBORHOOD_PEEK,
    ) -> None:
        self._repo = repo
        self._llm = llm
        self._top_k = top_k
        self._lower = lower_similarity
        self._min_confidence = min_confidence
        self._peek = neighborhood_peek

    def consolidate(
        self,
        *,
        dry_run: bool = False,
        progress: object | None = None,
    ) -> ConsolidationReport:
        """전체 그래프 1 회 sweep.

        Steps:
          1. 모든 entity stream (id, name, type, embedding, aliases, source_refs).
          2. 각 entity 에 대해 ANN top_k 후보. cosine ∈ [lower, EMBEDDING_MATCH_THRESHOLD)
             인 쌍만 후보화 (≥ EMBEDDING_MATCH_THRESHOLD 는 이미 streaming 이 합쳤음).
          3. 후보 쌍 dedupe (id 사전순) 후 generic 자기지칭 separation 게이트.
          4. LLM 으로 동일성 판정.
          5. (dry_run 이 아니면) merge — survivor 는 created_at 빠른 쪽.
        """
        import time

        started = time.monotonic()
        report = ConsolidationReport()
        seen_pairs: set[tuple[str, str]] = set()
        candidates: list[CandidatePair] = []

        for entity in self._repo.iterate_entities():
            report.entities_scanned += 1
            if not entity.embedding:
                continue
            hits = self._repo.vector_search(
                embedding=entity.embedding, top_k=self._top_k, type_=entity.type
            )
            for cand in hits:
                if cand.id == entity.id:
                    continue
                key = _pair_key(entity.id, cand.id)
                if key in seen_pairs:
                    continue
                sim = _cosine(entity.embedding, cand.embedding)
                if not (self._lower <= sim < EMBEDDING_MATCH_THRESHOLD):
                    continue
                seen_pairs.add(key)
                a, b = (entity, cand) if entity.id <= cand.id else (cand, entity)
                candidates.append(CandidatePair(a=a, b=b, similarity=sim))

        report.candidates_total = len(candidates)
        logger.info(
            "consolidate: scanned=%d candidates=%d (lower=%.2f, upper=%.2f)",
            report.entities_scanned,
            report.candidates_total,
            self._lower,
            EMBEDDING_MATCH_THRESHOLD,
        )

        # 동일 회차에서 이미 merge 된 entity 의 id 를 추적 — 같은 entity 가 두
        # 쌍에서 모두 surface 되어도 두 번째 merge 시 stale data 를 다시 부르지
        # 않도록.
        merged_loser_ids: set[str] = set()

        for pair in candidates:
            a, b = pair.a, pair.b
            if a.id in merged_loser_ids or b.id in merged_loser_ids:
                report.rejected_pairs.append(
                    (a.id, b.id, pair.similarity, "already_merged_in_run")
                )
                continue

            # generic 자기지칭 separation 게이트.
            a_generic = _is_generic_self_reference(a)
            b_generic = _is_generic_self_reference(b)
            if (a_generic or b_generic) and not _has_shared_source_path(a, b):
                report.candidates_self_reference_skipped += 1
                report.rejected_pairs.append(
                    (a.id, b.id, pair.similarity, "self_reference_separation")
                )
                continue

            a_neighbors = self._repo.neighbor_names(
                entity_id=a.id, limit=self._peek
            )
            b_neighbors = self._repo.neighbor_names(
                entity_id=b.id, limit=self._peek
            )
            a_paths = sorted({r.source_path for r in a.source_refs})
            b_paths = sorted({r.source_path for r in b.source_refs})

            decision = self._llm.judge_same_entity(
                a=a,
                b=b,
                a_neighbors=a_neighbors,
                b_neighbors=b_neighbors,
                a_source_paths=a_paths,
                b_source_paths=b_paths,
            )
            report.llm_calls += 1

            if not (decision.same and decision.confidence >= self._min_confidence):
                report.rejected_pairs.append(
                    (
                        a.id,
                        b.id,
                        pair.similarity,
                        f"llm_different (conf={decision.confidence:.2f})",
                    )
                )
                continue

            survivor, loser = _pick_survivor(a, b)
            if dry_run:
                report.merged_pairs.append(
                    (survivor.id, loser.id, pair.similarity, decision.confidence)
                )
                continue

            try:
                _merge_loser_into_survivor(
                    repo=self._repo, survivor=survivor, loser=loser
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "consolidate merge failed survivor=%s loser=%s",
                    survivor.id,
                    loser.id,
                )
                report.rejected_pairs.append(
                    (a.id, b.id, pair.similarity, "merge_failed")
                )
                continue

            merged_loser_ids.add(loser.id)
            report.merged_pairs.append(
                (survivor.id, loser.id, pair.similarity, decision.confidence)
            )

        report.duration_seconds = time.monotonic() - started
        logger.info(
            "consolidate done: merged=%d rejected=%d llm_calls=%d duration=%.1fs",
            report.merged_count,
            report.rejected_count,
            report.llm_calls,
            report.duration_seconds,
        )
        return report


def _pick_survivor(
    a: StoredEntity, b: StoredEntity
) -> tuple[StoredEntity, StoredEntity]:
    """survivor / loser 결정 — created_at 빠른 쪽 survivor.

    동률이면 id 사전순으로 결정 (안정성). created_at 자체가 비면 *상대편* 을
    survivor 로 양보 (정렬 안정성 < 데이터 유무).
    """
    if a.created_at and not b.created_at:
        return a, b
    if b.created_at and not a.created_at:
        return b, a
    if (a.created_at or "") < (b.created_at or ""):
        return a, b
    if (b.created_at or "") < (a.created_at or ""):
        return b, a
    return (a, b) if a.id <= b.id else (b, a)


def _merge_loser_into_survivor(
    *, repo: GraphRepository, survivor: StoredEntity, loser: StoredEntity
) -> None:
    """survivor 의 필드를 union 후 set + loser 의 in/out 엣지 transfer + delete.

    순서:
      1. survivor 의 MergeMutation 적용 (aliases / description / source_refs union).
      2. loser 의 inbound + outbound 관계를 survivor 로 옮김 — (other, type, survivor)
         가 이미 있으면 source_paths 만 union, 없으면 새 관계 생성.
      3. loser 노드 삭제 (DETACH).

    WHY 1 → 2 → 3 순서: 만약 transfer 도중 실패해도 survivor 의 union 결과는
    살아 남는다 (idempotent 재호출 시 dup-merge 안 됨). loser 의 관계는 그대로
    남으면 다음 sweep 에서 다시 시도.
    """
    now = now_rfc3339()
    mutation = EntityMerger.merge_loser_entity(
        survivor=survivor, loser=loser, now=now
    )
    repo.apply_merge_mutation(mutation=mutation)
    repo.transfer_relations_to_survivor(
        survivor_id=survivor.id, loser_id=loser.id, now=now
    )
    repo.delete_entity(entity_id=loser.id)


def select_self_reference_pairs(
    pairs: Iterable[CandidatePair],
) -> list[CandidatePair]:
    """테스트 / 진단용 헬퍼 — generic 자기지칭이 끼었지만 source_path 분리된 쌍.

    `_is_generic_self_reference` + `_has_shared_source_path` 의 결합 규칙을
    상위 코드 (admin diagnostics) 가 재사용할 수 있게 export.
    """
    out: list[CandidatePair] = []
    for p in pairs:
        a_g = _is_generic_self_reference(p.a)
        b_g = _is_generic_self_reference(p.b)
        if (a_g or b_g) and not _has_shared_source_path(p.a, p.b):
            out.append(p)
    return out
