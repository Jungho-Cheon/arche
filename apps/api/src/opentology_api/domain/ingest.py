"""Ingest 서비스 — 4 단계 동일성 + idempotent 차분 (PRD 2 §5).

흐름 (PRD 2 §6 의 본 슬라이스 형태):
  파일 읽기 → source_hash 계산 → 같은 hash 의 성공 회차가 있으면 short-circuit
  → 그렇지 않으면 IngestionRun 생성 → LLM 추출 → 엔티티별 4 단계 매처 →
  match 면 EntityMerger 로 merge, miss 면 create_entity → 관계 upsert →
  이전 회차 emitted 와 비교해 사라진 노드/관계 diff 적용 → run 종결

WHY 단일 사용자 가정 (concurrency 없음): MVP 는 단일 환경 (ADR-0002 D2). 같은
source_path 에 대한 동시 ingest 는 발생하지 않는다고 가정. post-MVP 의 multi-user
가 들어오면 IngestionRun 노드를 advisory lock 으로 활용 (running 상태가 살아
있으면 두 번째 호출 reject) 하는 패턴이 자연스럽다.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ulid import ULID

from ..adapters.embedding import EmbeddingProvider
from ..adapters.graph import GraphRepository
from ..adapters.llm import LLMProvider
from .errors import InvalidInputError, UnsupportedFileTypeError
from .identity import EntityMatcher, EntityMerger, normalize
from .models import (
    ExtractedGraph,
    SourceRef,
    StoredEntity,
    now_rfc3339,
)


logger = logging.getLogger(__name__)


SUPPORTED_EXTS = {".txt", ".md"}
# WHY 분리: PDF / 이미지는 follow-up issue #5 — 명확한 에러로 user 가 경로 알도록.
PENDING_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class IngestResult:
    source_path: str
    entities_created: int
    entities_updated: int
    relations_created: int
    relations_skipped_dangling: int
    entity_ids: list[str]
    # WHY by_step dict: 측정 회차 디버깅 + threshold tuning 의 신호. PRD 2 §5.1
    # 의 step 별 동작이 실제로 어떻게 분포하는지 응답에 노출 — 1/2/3 만 노출
    # (step 4 = 신규 생성이므로 entities_created 로 동치).
    entities_matched_by_step: dict[int, int] = field(default_factory=dict)
    # WHY shortcircuit + diff 카운터: 본문 사양 (G/H) — 사용자 보고용 + 테스트
    # assert 둘 다 필요.
    short_circuited: bool = False
    entities_deleted: int = 0
    entities_trimmed: int = 0
    relations_deleted: int = 0
    relations_trimmed: int = 0


class IngestService:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        graph: GraphRepository,
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._graph = graph

    def ingest_file(self, path: Path) -> IngestResult:
        path = path.resolve()
        if path.is_dir():
            raise InvalidInputError(
                "Directory ingest is not supported in the walking skeleton — "
                "follow-up issue #2 covers directory crawl with watch/dry-run."
            )
        if not path.exists():
            raise InvalidInputError(f"File not found: {path}")

        ext = path.suffix.lower()
        if ext in PENDING_EXTS:
            raise UnsupportedFileTypeError(
                f"File type {ext} is pending — follow-up issue #5 (PDF + image "
                "multimodal extraction). Walking skeleton supports {.txt, .md} only."
            )
        if ext not in SUPPORTED_EXTS:
            raise UnsupportedFileTypeError(
                f"Unsupported extension {ext}. Walking skeleton supports "
                f"{sorted(SUPPORTED_EXTS)} only."
            )

        source_path = str(path)
        raw_bytes = path.read_bytes()
        source_hash = hashlib.sha256(raw_bytes).hexdigest()

        # Short-circuit — 같은 (path, hash) 의 성공 회차가 이미 있다면 LLM/임베딩
        # 호출 자체를 건너뛴다. PRD 2 §5.4 의 1 번 조건.
        prior_success = self._graph.find_succeeded_run_by_hash(
            source_path=source_path, source_hash=source_hash
        )
        if prior_success is not None:
            logger.info(
                "short-circuit: matching succeeded run id=%s for %s",
                prior_success.id,
                source_path,
            )
            return IngestResult(
                source_path=source_path,
                entities_created=0,
                entities_updated=len(prior_success.emitted_entity_ids),
                relations_created=0,
                relations_skipped_dangling=0,
                entity_ids=list(prior_success.emitted_entity_ids),
                entities_matched_by_step={},
                short_circuited=True,
            )

        # 새 IngestionRun 시작.
        run_id = str(ULID())
        started_at = now_rfc3339()
        self._graph.create_ingestion_run(
            run_id=run_id,
            source_path=source_path,
            source_hash=source_hash,
            started_at=started_at,
        )

        # 이전 성공 회차 (hash 가 다른) 를 차분 비교 대상으로 캐싱.
        prior_for_diff = self._graph.find_latest_succeeded_run(
            source_path=source_path
        )

        text = raw_bytes.decode("utf-8")

        try:
            extracted = self._llm.extract(text=text, source_path=source_path)
            source_ref = SourceRef(source_path=source_path, chunk_index=None)

            matcher = EntityMatcher(repo=self._graph, embedder=self._embedder)
            merger = EntityMerger()

            name_to_id, entity_metrics = self._upsert_entities(
                extracted=extracted,
                source_ref=source_ref,
                matcher=matcher,
                merger=merger,
                run_id=run_id,
            )

            rel_created, rel_dangling, rel_ids = self._upsert_relations(
                extracted=extracted,
                name_to_id=name_to_id,
                source_ref=source_ref,
                run_id=run_id,
            )

            # 차분 — 이전 회차가 emit 했는데 이번엔 안 한 것 처리.
            diff_metrics = self._apply_diff(
                prior=prior_for_diff,
                new_entity_ids=set(name_to_id.values()),
                new_relation_ids=set(rel_ids),
                source_path=source_path,
                run_id=run_id,
            )

            self._graph.finalize_run(
                run_id=run_id,
                status="succeeded",
                completed_at=now_rfc3339(),
                emitted_entity_ids=list(name_to_id.values()),
                emitted_relation_ids=list(rel_ids),
            )

            return IngestResult(
                source_path=source_path,
                entities_created=entity_metrics["created"],
                entities_updated=entity_metrics["updated"],
                relations_created=rel_created,
                relations_skipped_dangling=rel_dangling,
                entity_ids=list(name_to_id.values()),
                entities_matched_by_step=entity_metrics["by_step"],
                short_circuited=False,
                entities_deleted=diff_metrics["entities_deleted"],
                entities_trimmed=diff_metrics["entities_trimmed"],
                relations_deleted=diff_metrics["relations_deleted"],
                relations_trimmed=diff_metrics["relations_trimmed"],
            )
        except Exception:
            # 실패 — run 을 failed 로 마킹해 다음 호출에서 short-circuit 되지
            # 않도록 (succeeded 만 short-circuit 한다).
            self._graph.finalize_run(
                run_id=run_id,
                status="failed",
                completed_at=now_rfc3339(),
                emitted_entity_ids=[],
                emitted_relation_ids=[],
            )
            raise

    def _upsert_entities(
        self,
        *,
        extracted: ExtractedGraph,
        source_ref: SourceRef,
        matcher: EntityMatcher,
        merger: EntityMerger,
        run_id: str,
    ) -> tuple[dict[str, str], dict]:
        name_to_id: dict[str, str] = {}
        created = 0
        updated = 0
        by_step: dict[int, int] = {1: 0, 2: 0, 3: 0}
        now = now_rfc3339()

        for e_new in extracted.entities:
            result = matcher.match(e_new)
            if result.existing is not None and result.step in (1, 2, 3):
                # 병합 분기.
                mutation = EntityMerger.merge(
                    existing=result.existing,
                    e_new=e_new,
                    new_source_ref=source_ref,
                    now=now,
                )
                self._graph.apply_merge_mutation(mutation=mutation)
                name_to_id[e_new.name] = result.existing.id
                updated += 1
                by_step[result.step] += 1
                self._graph.mark_entity_emitted(
                    entity_id=result.existing.id, run_id=run_id
                )
                logger.debug(
                    "entity merged step=%d existing_id=%s new_name=%s",
                    result.step,
                    result.existing.id,
                    e_new.name,
                )
                continue

            # 신규 — embedding 계산 + create.
            # WHY 이름만 임베딩: PRD 2 §5.6 의 임베딩 대상은 "name + description
            # + aliases" 가 본격 형태지만 본 PR 의 슬라이스는 *PR #16 동일* 한
            # "이름만" 을 유지. 임베딩 대상 변경은 별도 follow-up — 그 변경 자체가
            # threshold 0.92 의 의미를 바꾸기 때문에 같은 PR 에 묶지 않는다.
            embed_out = self._embedder.embed([e_new.name])
            if not embed_out:
                raise RuntimeError(
                    f"embedding returned empty for name={e_new.name!r}"
                )
            new_id = str(ULID())
            stored = StoredEntity(
                id=new_id,
                name=e_new.name,
                type=e_new.type,
                aliases=list(e_new.aliases or []),
                description=e_new.description,
                properties={},
                source_refs=[source_ref],
                created_at=now,
                updated_at=now,
                embedding=embed_out[0],
                normalized_name=normalize(e_new.name),
                normalized_aliases=[
                    normalize(a) for a in (e_new.aliases or []) if normalize(a)
                ],
            )
            self._graph.create_entity(entity=stored)
            self._graph.mark_entity_emitted(entity_id=new_id, run_id=run_id)
            name_to_id[e_new.name] = new_id
            created += 1

        return name_to_id, {
            "created": created,
            "updated": updated,
            "by_step": by_step,
        }

    def _upsert_relations(
        self,
        *,
        extracted: ExtractedGraph,
        name_to_id: dict[str, str],
        source_ref: SourceRef,
        run_id: str,
    ) -> tuple[int, int, list[str]]:
        created = 0
        dangling = 0
        rel_ids: list[str] = []
        for r in extracted.relations:
            from_id = name_to_id.get(r.from_name)
            to_id = name_to_id.get(r.to_name)
            if not from_id or not to_id:
                dangling += 1
                logger.warning(
                    "skip dangling relation from=%s to=%s type=%s source=%s",
                    r.from_name,
                    r.to_name,
                    r.type,
                    source_ref.source_path,
                )
                continue
            rid, was_created = self._graph.upsert_relation(
                from_id=from_id,
                to_id=to_id,
                rel_type=r.type,
                source_ref=source_ref,
            )
            if not rid:
                # 어댑터가 from/to 매치 실패 시 ("", False) 반환 — 방어.
                dangling += 1
                continue
            rel_ids.append(rid)
            self._graph.mark_relation_emitted(relation_id=rid, run_id=run_id)
            if was_created:
                created += 1
        return created, dangling, rel_ids

    def _apply_diff(
        self,
        *,
        prior,
        new_entity_ids: set[str],
        new_relation_ids: set[str],
        source_path: str,
        run_id: str,
    ) -> dict[str, int]:
        metrics = {
            "entities_deleted": 0,
            "entities_trimmed": 0,
            "relations_deleted": 0,
            "relations_trimmed": 0,
        }
        if prior is None:
            return metrics

        # WHY 관계 먼저: 엔티티 DETACH DELETE 가 인접 관계를 함께 지운다. 관계
        # diff 를 나중에 돌리면 노드가 cascade 로 사라지면서 관계가 "missing"
        # 으로 보고된다 (실제로는 삭제됐는데 카운터가 안 잡힘). 따라서 관계 →
        # 엔티티 순서로 처리한다.
        for rid in prior.emitted_relation_ids:
            if rid in new_relation_ids:
                continue
            outcome = self._graph.apply_relation_diff(
                relation_id=rid, source_path=source_path
            )
            if outcome == "deleted":
                metrics["relations_deleted"] += 1
            elif outcome == "trimmed":
                metrics["relations_trimmed"] += 1

        for eid in prior.emitted_entity_ids:
            if eid in new_entity_ids:
                continue
            outcome = self._graph.apply_entity_diff(
                entity_id=eid, source_path=source_path, run_id=run_id
            )
            if outcome == "deleted":
                metrics["entities_deleted"] += 1
            elif outcome == "trimmed":
                metrics["entities_trimmed"] += 1

        return metrics
