"""계획용 GraphRepository 데코레이터 — 쓰기를 기록만 하고 실행하지 않는다.

WHY: 검증된 적재 루프(_upsert_entities 등)를 한 줄도 고치지 않고 "쓰지 않는
계획"을 얻기 위해, 포트 경계에서 쓰기를 가로챈다. 멀티청크 문서의 정합성은
정규명 읽기 오버레이로 보존한다(같은 정규명 반복 등장 시 계획 안에서도 한
점으로 병합).
"""

from __future__ import annotations

from .ingest_plan import RecordedWrite
from .models import MergeMutation, SourceRef, StoredEntity
from .ports import (
    DenseHit,
    EntityTypeStat,
    EntityWithCounts,
    GraphRepository,
    IngestionRunRecord,
    KeywordHit,
    NeighborhoodResult,
    PathResult,
    RelationTypeStat,
)


class PlanningGraphRepository(GraphRepository):
    def __init__(self, real: GraphRepository) -> None:
        self._real = real
        self.writes: list[RecordedWrite] = []
        # pending 인덱스 — 이번 계획에서 새로 만든 엔티티의 정규명 lookup.
        self._pending_by_norm: dict[str, StoredEntity] = {}
        self._rel_seq = 0

    # ---------- 쓰기: 기록만 ----------

    def create_entity(self, *, entity: StoredEntity) -> None:
        self.writes.append(RecordedWrite("create_entity", {"entity": entity}))
        if entity.normalized_name:
            self._pending_by_norm[entity.normalized_name] = entity

    def apply_merge_mutation(self, *, mutation: MergeMutation) -> None:
        before = self._real.get_stored_entity(entity_id=mutation.id)
        self.writes.append(
            RecordedWrite("apply_merge_mutation", {"mutation": mutation}, before=before)
        )

    def upsert_relation(
        self, *, from_id: str, to_id: str, rel_type: str, source_ref: SourceRef
    ) -> tuple[str, bool]:
        self._rel_seq += 1
        synthetic = f"plan_rel_{self._rel_seq}"
        self.writes.append(
            RecordedWrite(
                "upsert_relation",
                {"from_id": from_id, "to_id": to_id, "rel_type": rel_type,
                 "source_ref": source_ref},
            )
        )
        return synthetic, True

    def create_ingestion_run(self, *, run_id: str, source_path: str,
                             source_hash: str, started_at: str,
                             extractor_version: str) -> None:
        self.writes.append(RecordedWrite("create_ingestion_run", {
            "run_id": run_id, "source_path": source_path, "source_hash": source_hash,
            "started_at": started_at, "extractor_version": extractor_version}))

    def mark_entity_emitted(self, *, entity_id: str, run_id: str) -> None:
        self.writes.append(RecordedWrite(
            "mark_entity_emitted", {"entity_id": entity_id, "run_id": run_id}))

    def mark_relation_emitted(self, *, relation_id: str, run_id: str) -> None:
        self.writes.append(RecordedWrite(
            "mark_relation_emitted", {"relation_id": relation_id, "run_id": run_id}))

    def finalize_run(self, *, run_id: str, status: str, completed_at: str,
                     emitted_entity_ids: list[str],
                     emitted_relation_ids: list[str]) -> None:
        self.writes.append(RecordedWrite("finalize_run", {
            "run_id": run_id, "status": status, "completed_at": completed_at,
            "emitted_entity_ids": emitted_entity_ids,
            "emitted_relation_ids": emitted_relation_ids}))

    def apply_entity_diff(self, *, entity_id: str, source_path: str, run_id: str) -> str:
        self.writes.append(RecordedWrite("apply_entity_diff", {
            "entity_id": entity_id, "source_path": source_path, "run_id": run_id}))
        return "deleted"

    def apply_relation_diff(self, *, relation_id: str, source_path: str) -> str:
        self.writes.append(RecordedWrite("apply_relation_diff", {
            "relation_id": relation_id, "source_path": source_path}))
        return "deleted"

    def append_emitted_relations(self, *, run_id: str, relation_ids: list[str]) -> None:
        self.writes.append(RecordedWrite("append_emitted_relations", {
            "run_id": run_id, "relation_ids": relation_ids}))

    # ---------- 읽기: 오버레이 후 위임 ----------

    def find_by_normalized_name(self, *, normalized: str, type_: str) -> StoredEntity | None:
        pend = self._pending_by_norm.get(normalized)
        if pend is not None and pend.type == type_:
            return pend
        return self._real.find_by_normalized_name(normalized=normalized, type_=type_)

    def find_entity_id_by_normalized_name(self, *, normalized: str) -> str | None:
        pend = self._pending_by_norm.get(normalized)
        if pend is not None:
            return pend.id
        return self._real.find_entity_id_by_normalized_name(normalized=normalized)

    # ---------- 읽기: 순수 위임 (시그니처는 ports.py 와 동일하게 키워드 전용) ----------

    def ensure_indexes(self) -> None:
        return self._real.ensure_indexes()

    def healthcheck(self) -> bool:
        return self._real.healthcheck()

    def find_succeeded_run_by_hash(self, *, source_path: str, source_hash: str,
                                   extractor_version: str) -> IngestionRunRecord | None:
        return self._real.find_succeeded_run_by_hash(
            source_path=source_path, source_hash=source_hash,
            extractor_version=extractor_version)

    def find_latest_succeeded_run(self, *, source_path: str) -> IngestionRunRecord | None:
        return self._real.find_latest_succeeded_run(source_path=source_path)

    def get_schema_summary(self, *, examples_per_type: int = 5
                           ) -> tuple[list[EntityTypeStat], list[RelationTypeStat]]:
        return self._real.get_schema_summary(examples_per_type=examples_per_type)

    def get_entity_with_counts(self, *, entity_id: str) -> EntityWithCounts | None:
        return self._real.get_entity_with_counts(entity_id=entity_id)

    def expand_neighbors(self, *, entry_id: str, relation_types, direction: str,
                         hops: int, max_nodes: int) -> NeighborhoodResult:
        return self._real.expand_neighbors(
            entry_id=entry_id, relation_types=relation_types, direction=direction,
            hops=hops, max_nodes=max_nodes)

    def expand_subgraph(self, *, entry_ids, relation_types, hops: int,
                        max_nodes: int) -> NeighborhoodResult:
        return self._real.expand_subgraph(
            entry_ids=entry_ids, relation_types=relation_types, hops=hops,
            max_nodes=max_nodes)

    def find_shortest_paths(self, *, from_id: str, to_id: str, max_hops: int,
                            max_paths: int, relation_types) -> list[PathResult]:
        return self._real.find_shortest_paths(
            from_id=from_id, to_id=to_id, max_hops=max_hops, max_paths=max_paths,
            relation_types=relation_types)

    def entity_exists(self, *, entity_id: str) -> bool:
        return self._real.entity_exists(entity_id=entity_id)

    def count_entities_by_namespace(self) -> dict[str, int]:
        return self._real.count_entities_by_namespace()

    def get_stored_entity(self, *, entity_id: str) -> StoredEntity | None:
        return self._real.get_stored_entity(entity_id=entity_id)

    def close(self) -> None:
        return self._real.close()

    def vector_search(self, *, embedding, top_k: int, type_: str) -> list[StoredEntity]:
        return self._real.vector_search(embedding=embedding, top_k=top_k, type_=type_)

    def find_entities_dense(self, *, query_embedding, matched_keyword: str,
                            limit: int) -> list[DenseHit]:
        return self._real.find_entities_dense(
            query_embedding=query_embedding, matched_keyword=matched_keyword, limit=limit)

    def find_by_keywords_scored(self, *, keywords, limit_per_keyword: int
                                ) -> list[KeywordHit]:
        return self._real.find_by_keywords_scored(
            keywords=keywords, limit_per_keyword=limit_per_keyword)
