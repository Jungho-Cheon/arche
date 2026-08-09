"""계획용 GraphRepository 데코레이터 — 쓰기를 실행하지 않고 기록만 한다.

포트 경계에서 쓰기를 가로채 적재 루프를 안 고치고 "쓰지 않는 계획"을 얻는다.
멀티청크 정합성은 정규명 읽기 오버레이로 보존한다. domain/README.md 참조."""

from __future__ import annotations

from .ingest_plan import RecordedWrite
from .models import Edge, MergeMutation, SourceRef, StoredEntity
from .ports import (
    DenseHit,
    EntitySurface,
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

    def find_by_normalized_name(
        self, *, normalized: str, type_: str, namespace_id: str = "default"
    ) -> StoredEntity | None:
        # 오버레이도 namespace 로 거른다(cross-namespace 후보를 다리로 안 쓰게, issue #94).
        pend = self._pending_by_norm.get(normalized)
        if (
            pend is not None
            and pend.type == type_
            and (pend.namespace_id or "default") == namespace_id
        ):
            return pend
        return self._real.find_by_normalized_name(
            normalized=normalized, type_=type_, namespace_id=namespace_id
        )

    def find_entity_id_by_normalized_name(
        self, *, normalized: str, namespace_id: str = "default"
    ) -> str | None:
        pend = self._pending_by_norm.get(normalized)
        if pend is not None and (pend.namespace_id or "default") == namespace_id:
            return pend.id
        return self._real.find_entity_id_by_normalized_name(
            normalized=normalized, namespace_id=namespace_id
        )

    def find_entities_by_name(
        self, *, normalized_name: str, namespace_id: str = "default"
    ) -> list[StoredEntity]:
        real = self._real.find_entities_by_name(
            normalized_name=normalized_name, namespace_id=namespace_id
        )
        pend = self._pending_by_norm.get(normalized_name)
        if pend is None or (pend.namespace_id or "default") != namespace_id:
            return real
        if any(e.id == pend.id for e in real):
            return real
        return [*real, pend]

    def get_entity_relations(
        self, *, entity_id: str, namespace_id: str = "default"
    ) -> list[Edge]:
        return self._real.get_entity_relations(entity_id=entity_id, namespace_id=namespace_id)

    def move_relation_endpoint(
        self, *, relation_id: str, old_entity_id: str, new_entity_id: str
    ) -> None:
        """떼어내기의 쓰기. 지금 이 래퍼를 타고 오지는 않지만, 쓰기가 계획 단계에서
        진짜 그래프로 새는 일이 없도록 다른 쓰기와 같이 기록만 한다."""
        self.writes.append(
            RecordedWrite(
                "move_relation_endpoint",
                {
                    "relation_id": relation_id,
                    "old_entity_id": old_entity_id,
                    "new_entity_id": new_entity_id,
                },
            )
        )

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

    def get_schema_summary(self, *, examples_per_type: int = 5,
                           namespace_id: str = "default"
                           ) -> tuple[list[EntityTypeStat], list[RelationTypeStat]]:
        return self._real.get_schema_summary(
            examples_per_type=examples_per_type, namespace_id=namespace_id)

    def get_entity_with_counts(self, *, entity_id: str, namespace_id: str = "default"
                               ) -> EntityWithCounts | None:
        return self._real.get_entity_with_counts(
            entity_id=entity_id, namespace_id=namespace_id)

    def expand_neighbors(self, *, entry_id: str, relation_types, direction: str,
                         hops: int, max_nodes: int, namespace_id: str = "default"
                         ) -> NeighborhoodResult:
        return self._real.expand_neighbors(
            entry_id=entry_id, relation_types=relation_types, direction=direction,
            hops=hops, max_nodes=max_nodes, namespace_id=namespace_id)

    def expand_subgraph(self, *, entry_ids, relation_types, hops: int,
                        max_nodes: int, namespace_id: str = "default"
                        ) -> NeighborhoodResult:
        return self._real.expand_subgraph(
            entry_ids=entry_ids, relation_types=relation_types, hops=hops,
            max_nodes=max_nodes, namespace_id=namespace_id)

    def find_shortest_paths(self, *, from_id: str, to_id: str, max_hops: int,
                            max_paths: int, relation_types,
                            namespace_id: str = "default") -> list[PathResult]:
        return self._real.find_shortest_paths(
            from_id=from_id, to_id=to_id, max_hops=max_hops, max_paths=max_paths,
            relation_types=relation_types, namespace_id=namespace_id)

    def entity_exists(self, *, entity_id: str, namespace_id: str = "default") -> bool:
        return self._real.entity_exists(
            entity_id=entity_id, namespace_id=namespace_id)

    def count_entities_by_namespace(self) -> dict[str, int]:
        return self._real.count_entities_by_namespace()

    def iter_entity_surfaces(self, *, namespace_id: str = "default") -> list[EntitySurface]:
        return self._real.iter_entity_surfaces(namespace_id=namespace_id)

    def list_entities(
        self,
        *,
        namespace_id: str = "default",
        types: list[str] | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[int, list[StoredEntity]]:
        return self._real.list_entities(
            namespace_id=namespace_id, types=types, offset=offset, limit=limit
        )

    def get_stored_entity(self, *, entity_id: str) -> StoredEntity | None:
        return self._real.get_stored_entity(entity_id=entity_id)

    def close(self) -> None:
        return self._real.close()

    def vector_search(
        self, *, embedding, top_k: int, type_: str, namespace_id: str = "default"
    ) -> list[StoredEntity]:
        return self._real.vector_search(
            embedding=embedding, top_k=top_k, type_=type_, namespace_id=namespace_id
        )

    def find_entities_dense(self, *, query_embedding, matched_keyword: str,
                            limit: int, namespace_id: str = "default") -> list[DenseHit]:
        return self._real.find_entities_dense(
            query_embedding=query_embedding, matched_keyword=matched_keyword,
            limit=limit, namespace_id=namespace_id)

    def find_by_keywords_scored(self, *, keywords, limit_per_keyword: int,
                                namespace_id: str = "default") -> list[KeywordHit]:
        return self._real.find_by_keywords_scored(
            keywords=keywords, limit_per_keyword=limit_per_keyword,
            namespace_id=namespace_id)
