"""그래프 저장소 어댑터 — GraphRepository 포트의 Neo4j 5.15+ 구현.

부팅 시 인덱스 보장, 4 단계 동일성의 write 분기(create/merge), 정규명/벡터/fulltext
lookup, 관계 upsert, IngestionRun 기록과 차분을 Cypher 로 수행한다. 동일성/병합
결정은 도메인이 하고 이 어댑터는 적용만 한다."""

from __future__ import annotations

import logging
import math
from typing import Any

from neo4j import GraphDatabase

from ..config import Settings
from ..domain.errors import DependencyUnavailableError
from ..domain.models import (
    Edge,
    MergeMutation,
    Node,
    SourceRef,
    StoredEntity,
    now_rfc3339,
)
from ..domain.ports import (
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

# ---------- get_schema 보조 dataclass ----------






# ---------- get_entity 보조 dataclass ----------




# ---------- neighbors/subgraph 결과 ----------




# ---------- path 결과 ----------




logger = logging.getLogger(__name__)


# 인덱스 이름은 의도가 드러나게 고정한다(Neo4j MCP 와 같은 DB 공존 가능, ADR-0006).
FULLTEXT_INDEX = "entity_name_idx"
VECTOR_INDEX = "entity_embedding_idx"
NORMALIZED_NAME_INDEX = "entity_normalized_name_idx"
INGESTION_RUN_LABEL = "IngestionRun"
INGESTION_RUN_SOURCE_INDEX = "ingestion_run_source_idx"
ENTITY_LABEL = "Entity"
RELATION_TYPE_LABEL_DEFAULT = "RELATES_TO"  # 폴백 — 추출 시 type 이 비면
EMITTED_IN = "EMITTED_IN"










class Neo4jGraphRepository(GraphRepository):
    """Neo4j 5.15+ 어댑터. driver 1 개를 유지한다(bolt 커넥션 풀이 driver 내부에 있어
    매 요청 재생성하면 풀이 무의미)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        try:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
        except Exception as e:  # noqa: BLE001
            raise DependencyUnavailableError(f"neo4j driver init failed: {e}") from e

    def close(self) -> None:
        self._driver.close()

    # ---------- 헬스 / 인덱스 ----------

    def healthcheck(self) -> bool:
        try:
            with self._driver.session() as s:
                s.run("RETURN 1").consume()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("neo4j healthcheck failed: %s", e)
            return False

    def ensure_indexes(self) -> None:
        """부팅 시 idempotent 하게 인덱스 + 백필 보장.

        인덱스 — fulltext(name+aliases), vector(embedding), btree(name),
        btree(normalized_name), btree(IngestionRun.source_path). normalized_name 이
        비어 있는 옛 노드는 백필로 채운다(두 번째 호출은 no-op)."""
        dim = self._settings.embedding_dimension
        with self._driver.session() as s:
            # UNIQUE constraint — DB-level id 가드. 자동 인덱스라 id IN $ids 핫패스도 빨라진다.
            s.run(
                f"CREATE CONSTRAINT entity_id_unique IF NOT EXISTS "
                f"FOR (e:{ENTITY_LABEL}) REQUIRE e.id IS UNIQUE"
            ).consume()
            s.run(
                f"CREATE CONSTRAINT ingestion_run_id_unique IF NOT EXISTS "
                f"FOR (r:{INGESTION_RUN_LABEL}) REQUIRE r.id IS UNIQUE"
            ).consume()
            # 관계 id UNIQUE — Neo4j 5.7+ 의 relationship property constraint.
            s.run(
                f"CREATE CONSTRAINT relation_id_unique IF NOT EXISTS "
                f"FOR ()-[r:{RELATION_TYPE_LABEL_DEFAULT}]-() REQUIRE r.id IS UNIQUE"
            ).consume()
            s.run(
                f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX} IF NOT EXISTS "
                f"FOR (e:{ENTITY_LABEL}) ON EACH [e.name, e.aliases]"
            ).consume()
            # indexConfig 는 파라미터 바인딩을 안 받아 dim 을 리터럴로 박고, 점 포함
            # key 는 백틱으로 감싼다(Neo4j 5.15 Cypher 제약).
            s.run(
                f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS "
                f"FOR (e:{ENTITY_LABEL}) ON (e.embedding) "
                f"OPTIONS {{ indexConfig: {{ "
                f"`vector.dimensions`: {int(dim)}, "
                f"`vector.similarity_function`: 'cosine' "
                f"}} }}"
            ).consume()
            s.run(
                f"CREATE INDEX entity_name_btree IF NOT EXISTS "
                f"FOR (e:{ENTITY_LABEL}) ON (e.name)"
            ).consume()
            s.run(
                f"CREATE INDEX {NORMALIZED_NAME_INDEX} IF NOT EXISTS "
                f"FOR (e:{ENTITY_LABEL}) ON (e.normalized_name)"
            ).consume()
            s.run(
                f"CREATE INDEX {INGESTION_RUN_SOURCE_INDEX} IF NOT EXISTS "
                f"FOR (r:{INGESTION_RUN_LABEL}) ON (r.source_path)"
            ).consume()
            # normalize 는 server-side 로 못 돌려, 노드를 받아 클라이언트에서 계산 후 batch SET.
            self._backfill_normalized_names(s)

    def reindex_vector(self) -> dict[str, Any]:
        """벡터 색인을 DROP 후 현재 차원으로 다시 만든다(임베딩 모델 교체 대응).

        CREATE IF NOT EXISTS 는 기존 색인이 있으면 no-op 이라, 차원이 바뀌면 먼저
        DROP 해야 새 차원이 반영된다. 색인 구조만 다시 만들고 저장된 embedding 값은
        재계산하지 않는다(그건 재적재의 몫). 반환은 색인 이름 + 차원 요약."""
        dim = int(self._settings.embedding_dimension)
        with self._driver.session() as s:
            # 옛 차원의 색인 제거. 없으면 no-op (IF EXISTS).
            s.run(f"DROP INDEX {VECTOR_INDEX} IF EXISTS").consume()
            # ensure_indexes 와 동일 구문.
            s.run(
                f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS "
                f"FOR (e:{ENTITY_LABEL}) ON (e.embedding) "
                f"OPTIONS {{ indexConfig: {{ "
                f"`vector.dimensions`: {dim}, "
                f"`vector.similarity_function`: 'cosine' "
                f"}} }}"
            ).consume()
        logger.info("rebuilt vector index %s at dimension %d", VECTOR_INDEX, dim)
        return {"index": VECTOR_INDEX, "dimension": dim}

    def _backfill_normalized_names(self, session: Any) -> None:
        from ..domain.identity import normalize

        records = session.run(
            f"MATCH (e:{ENTITY_LABEL}) "
            "WHERE e.normalized_name IS NULL OR e.normalized_name = '' "
            "RETURN e.id AS id, e.name AS name, e.aliases AS aliases"
        ).data()
        if not records:
            return
        updates = [
            {
                "id": r["id"],
                "normalized": normalize(r["name"] or ""),
                "normalized_aliases": [
                    normalize(a) for a in (r.get("aliases") or []) if normalize(a)
                ],
            }
            for r in records
        ]
        session.run(
            f"UNWIND $rows AS row "
            f"MATCH (e:{ENTITY_LABEL} {{id: row.id}}) "
            "SET e.normalized_name = row.normalized, "
            "    e.normalized_aliases = row.normalized_aliases",
            rows=updates,
        ).consume()
        logger.info("backfilled normalized_name for %d entities", len(updates))

    # ---------- 4 단계 동일성 — read + write ----------

    def find_by_normalized_name(
        self, *, normalized: str, type_: str, namespace_id: str = "default"
    ) -> StoredEntity | None:
        """정규화 키 lookup — 노드의 정규명 또는 정규화된 alias 중 하나라도 일치하면
        hit(두 경우를 한 쿼리로 처리). namespace 안에서만 매칭한다(issue #94)."""
        with self._driver.session() as s:
            rec = s.run(
                f"MATCH (e:{ENTITY_LABEL}) "
                "WHERE e.type = $t "
                "  AND coalesce(e.namespace_id, 'default') = $ns "
                "  AND (e.normalized_name = $n "
                "       OR $n IN coalesce(e.normalized_aliases, [])) "
                "RETURN e LIMIT 1",
                n=normalized,
                t=type_,
                ns=namespace_id,
            ).single()
        if rec is None:
            return None
        return _node_to_stored(rec["e"])

    def find_entity_id_by_normalized_name(
        self, *, normalized: str, namespace_id: str = "default"
    ) -> str | None:
        """타입 무관 정규명 lookup — 관계 엔드포인트 해소용. 정규명 또는 정규화 alias 가
        일치하는 노드를 유일할 때만(LIMIT 2 로 판정) 돌려주고, 둘 이상이면 모호해 None.
        namespace 안에서만 해소한다."""
        if not normalized:
            return None
        with self._driver.session() as s:
            rows = s.run(
                f"MATCH (e:{ENTITY_LABEL}) "
                "WHERE coalesce(e.namespace_id, 'default') = $ns "
                "  AND (e.normalized_name = $n "
                "       OR $n IN coalesce(e.normalized_aliases, [])) "
                "RETURN e.id AS id LIMIT 2",
                n=normalized,
                ns=namespace_id,
            ).data()
        if len(rows) == 1:
            return rows[0]["id"]
        return None


    def find_entities_by_name(
        self, *, normalized_name: str, namespace_id: str = "default"
    ) -> list[StoredEntity]:
        if not normalized_name:
            return []
        with self._driver.session() as s:
            rows = s.run(
                f"MATCH (e:{ENTITY_LABEL}) "
                "WHERE coalesce(e.namespace_id, 'default') = $ns "
                "  AND e.normalized_name = $n "
                "RETURN e AS e ORDER BY e.id LIMIT 5",
                n=normalized_name,
                ns=namespace_id,
            ).data()
        return [_node_to_stored(r["e"]) for r in rows]
    def vector_search(
        self,
        *,
        embedding: list[float],
        top_k: int,
        type_: str,
        namespace_id: str = "default",
    ) -> list[StoredEntity]:
        """ANN top-k 후보. queryNodes 가 라벨/속성 사전 필터를 못 받아, top_k*4 로
        oversample 한 뒤 type + namespace 로 사후 필터한다."""
        if not embedding:
            return []
        oversample = max(top_k * 4, top_k)
        with self._driver.session() as s:
            rows = s.run(
                "CALL db.index.vector.queryNodes($idx, $k, $vec) "
                "YIELD node, score "
                "WITH node, score "
                f"WHERE node:{ENTITY_LABEL} AND node.type = $t "
                "  AND coalesce(node.namespace_id, 'default') = $ns "
                "RETURN node ORDER BY score DESC LIMIT $limit",
                parameters={
                    "idx": VECTOR_INDEX,
                    "k": oversample,
                    "vec": embedding,
                    "t": type_,
                    "ns": namespace_id,
                    "limit": top_k,
                },
            ).data()
        return [_node_to_stored(r["node"]) for r in rows]

    def create_entity(self, *, entity: StoredEntity) -> None:
        """새 엔티티 생성. Neo4j list 속성은 null 원소를 못 담아 chunk_index 는 -1
        sentinel 로 저장하고 응답 직렬화에서 None 으로 복원한다."""
        source_paths, source_chunks, source_totals = _source_ref_arrays(entity.source_refs)
        with self._driver.session() as s:
            s.run(
                f"""
                CREATE (e:{ENTITY_LABEL} {{
                    id: $id, name: $name, normalized_name: $normalized_name,
                    normalized_aliases: $normalized_aliases,
                    blocked_aliases: $blocked_aliases,
                    type: $type, aliases: $aliases, description: $description,
                    embedding: $embedding,
                    namespace_id: $namespace_id,
                    source_paths: $source_paths,
                    source_chunk_indexes: $source_chunk_indexes,
                    source_total_chunks: $source_total_chunks,
                    created_at: $created_at, updated_at: $updated_at
                }})
                """,
                id=entity.id,
                name=entity.name,
                normalized_name=entity.normalized_name,
                normalized_aliases=list(entity.normalized_aliases or []),
                blocked_aliases=list(entity.blocked_aliases or []),
                type=entity.type,
                aliases=entity.aliases,
                description=entity.description or "",
                embedding=entity.embedding,
                namespace_id=entity.namespace_id or "default",
                source_paths=source_paths,
                source_chunk_indexes=source_chunks,
                source_total_chunks=source_totals,
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            ).consume()

    def apply_merge_mutation(self, *, mutation: MergeMutation) -> None:
        """병합 — aliases/description/source_refs/updated_at 만 갱신한다. source_refs 는
        도메인이 이미 dedupe 한 최종 리스트라 어댑터는 통째로 교체만 한다."""
        source_paths, source_chunks, source_totals = _source_ref_arrays(mutation.source_refs)
        with self._driver.session() as s:
            s.run(
                f"""
                MATCH (e:{ENTITY_LABEL} {{id: $id}})
                SET e.aliases = $aliases,
                    e.normalized_aliases = $normalized_aliases,
                    e.description = $description,
                    e.source_paths = $source_paths,
                    e.source_chunk_indexes = $source_chunk_indexes,
                    e.source_total_chunks = $source_total_chunks,
                    e.updated_at = $updated_at
                """,
                id=mutation.id,
                aliases=mutation.aliases,
                normalized_aliases=list(mutation.normalized_aliases or []),
                description=mutation.description,
                source_paths=source_paths,
                source_chunk_indexes=source_chunks,
                source_total_chunks=source_totals,
                updated_at=mutation.updated_at,
            ).consume()
            if mutation.blocked_aliases is not None:
                s.run(
                    f"MATCH (e:{ENTITY_LABEL} {{id: $id}}) SET e.blocked_aliases = $blocked",
                    id=mutation.id,
                    blocked=list(mutation.blocked_aliases),
                ).consume()

    def upsert_relation(
        self,
        *,
        from_id: str,
        to_id: str,
        rel_type: str,
        source_ref: SourceRef,
    ) -> tuple[str, bool]:
        """(from_id, type, to_id) 3-튜플 유일성으로 MERGE 한다. 관계 라벨은 Cypher 에서
        파라미터화가 안 되고 폭발하면 관리가 어려워, 단일 RELATES_TO 라벨 + type 속성으로 둔다."""
        from ulid import ULID

        new_id = str(ULID())
        now = now_rfc3339()
        # created 판정은 _just_created 플래그로. created_at 는 초 단위라 같은 초의
        # 두 호출을 구분 못 해, ON CREATE 에서만 세우는 별도 플래그가 필요하다.
        with self._driver.session() as s:
            result = s.run(
                f"""
                MATCH (a:{ENTITY_LABEL} {{id: $from_id}})
                MATCH (b:{ENTITY_LABEL} {{id: $to_id}})
                MERGE (a)-[r:{RELATION_TYPE_LABEL_DEFAULT} {{type: $rel_type}}]->(b)
                ON CREATE SET r.id = $new_id,
                              r.source_paths = [$source_path],
                              r.created_at = $now,
                              r.updated_at = $now,
                              r._just_created = true
                ON MATCH SET  r.source_paths =
                                CASE WHEN $source_path IN coalesce(r.source_paths, [])
                                     THEN r.source_paths
                                     ELSE coalesce(r.source_paths, []) + [$source_path] END,
                              r.updated_at = $now,
                              r._just_created = false
                RETURN r.id AS id, r._just_created AS created
                """,
                parameters={
                    "from_id": from_id,
                    "to_id": to_id,
                    "rel_type": rel_type,
                    "new_id": new_id,
                    "source_path": source_ref.source_path,
                    "now": now,
                },
            ).single()
        if result is None:
            # dangling — from 또는 to 가 그래프에 없음
            return "", False
        return result["id"], bool(result["created"])

    def get_entity_relations(
        self, *, entity_id: str, namespace_id: str = "default"
    ) -> list[Edge]:
        with self._driver.session() as s:
            rows = list(
                s.run(
                    f"""
                    MATCH (n:{ENTITY_LABEL} {{id: $id}})-[r:{RELATION_TYPE_LABEL_DEFAULT}]-(m:{ENTITY_LABEL})
                    WHERE n.namespace_id = $ns AND m.namespace_id = $ns
                    RETURN r.id AS rel_id, r.type AS rel_type,
                           r.created_at AS rel_created_at, r.updated_at AS rel_updated_at,
                           r.source_paths AS rel_source_paths,
                           startNode(r).id AS from_id, endNode(r).id AS to_id
                    """,
                    id=entity_id,
                    ns=namespace_id,
                )
            )
        return [
            _record_to_edge(
                rel_id=r["rel_id"],
                rel_type=r["rel_type"],
                rel_created_at=r["rel_created_at"],
                rel_updated_at=r["rel_updated_at"],
                rel_source_paths=list(r["rel_source_paths"] or []),
                from_id=r["from_id"],
                to_id=r["to_id"],
            )
            for r in rows
        ]

    def move_relation_endpoint(
        self, *, relation_id: str, old_entity_id: str, new_entity_id: str
    ) -> None:
        """Neo4j 는 엣지의 끝점을 바꾸는 문법이 없어, 옮길 자리에 같은 관계를 새로 만들고
        옛 엣지를 지운다. id 와 출처, 만든 시각, 적재 회차를 그대로 들고 가 옮긴 관계가
        원래부터 그 자리에 있던 관계와 똑같아 보이게 한다."""
        with self._driver.session() as s:
            rec = s.run(
                f"""
                MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $rid}}]->(b:{ENTITY_LABEL})
                RETURN a.id AS from_id, b.id AS to_id, r.type AS type,
                       coalesce(r.source_paths, []) AS source_paths,
                       r.created_at AS created_at,
                       coalesce(r.emitted_in_run_ids, []) AS runs
                """,
                rid=relation_id,
            ).single()
            if rec is None:
                return
            plan = _plan_endpoint_move(
                from_id=rec["from_id"],
                to_id=rec["to_id"],
                old_entity_id=old_entity_id,
                new_entity_id=new_entity_id,
            )
            if plan is None:
                return
            from_id, to_id = plan
            source_paths = list(rec["source_paths"] or [])
            runs = list(rec["runs"] or [])
            existing = s.run(
                f"""
                MATCH (a:{ENTITY_LABEL} {{id: $from_id}})-[r:{RELATION_TYPE_LABEL_DEFAULT} {{type: $type}}]->(b:{ENTITY_LABEL} {{id: $to_id}})
                RETURN r.id AS id, coalesce(r.source_paths, []) AS source_paths,
                       coalesce(r.emitted_in_run_ids, []) AS runs
                """,
                from_id=from_id,
                to_id=to_id,
                type=rec["type"],
            ).single()
            s.run(
                f"MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $rid}}]-() DELETE r",
                rid=relation_id,
            ).consume()
            now = now_rfc3339()
            if existing is not None:
                # 옮긴 자리에 같은 (from, type, to) 관계가 이미 있으면 출처와 회차를 합친다.
                s.run(
                    f"""
                    MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $rid}}]-()
                    SET r.source_paths = $source_paths,
                        r.emitted_in_run_ids = $runs, r.updated_at = $now
                    """,
                    rid=existing["id"],
                    source_paths=_union(list(existing["source_paths"] or []), source_paths),
                    runs=_union(list(existing["runs"] or []), runs),
                    now=now,
                ).consume()
                return
            s.run(
                f"""
                MATCH (a:{ENTITY_LABEL} {{id: $from_id}})
                MATCH (b:{ENTITY_LABEL} {{id: $to_id}})
                CREATE (a)-[r:{RELATION_TYPE_LABEL_DEFAULT} {{
                    id: $rid, type: $type, source_paths: $source_paths,
                    created_at: $created_at, updated_at: $now,
                    emitted_in_run_ids: $runs, _just_created: false
                }}]->(b)
                """,
                from_id=from_id,
                to_id=to_id,
                rid=relation_id,
                type=rec["type"],
                source_paths=source_paths,
                created_at=rec["created_at"],
                now=now,
                runs=runs,
            ).consume()

    # ---------- IngestionRun + 차분 ----------

    def find_succeeded_run_by_hash(
        self, *, source_path: str, source_hash: str, extractor_version: str
    ) -> IngestionRunRecord | None:
        with self._driver.session() as s:
            # extractor_version 까지 일치해야 short-circuit. 추출 로직이 바뀌면 같은
            # 파일도 재추출된다. 옛 회차는 이 값이 없어(null) 불일치 → 재추출.
            rec = s.run(
                f"MATCH (r:{INGESTION_RUN_LABEL}) "
                "WHERE r.source_path = $p AND r.source_hash = $h "
                "  AND coalesce(r.extractor_version, '') = $v "
                "  AND r.status = 'succeeded' "
                "RETURN r ORDER BY r.completed_at DESC LIMIT 1",
                p=source_path,
                h=source_hash,
                v=extractor_version,
            ).single()
        return _to_run_record(rec["r"]) if rec else None

    def find_latest_succeeded_run(
        self, *, source_path: str
    ) -> IngestionRunRecord | None:
        with self._driver.session() as s:
            rec = s.run(
                f"MATCH (r:{INGESTION_RUN_LABEL}) "
                "WHERE r.source_path = $p AND r.status = 'succeeded' "
                "RETURN r ORDER BY r.completed_at DESC LIMIT 1",
                p=source_path,
            ).single()
        return _to_run_record(rec["r"]) if rec else None

    def create_ingestion_run(
        self,
        *,
        run_id: str,
        source_path: str,
        source_hash: str,
        started_at: str,
        extractor_version: str,
    ) -> None:
        with self._driver.session() as s:
            s.run(
                f"""
                CREATE (r:{INGESTION_RUN_LABEL} {{
                    id: $id, source_path: $p, source_hash: $h,
                    extractor_version: $v,
                    started_at: $started, status: 'running',
                    emitted_entity_ids: [], emitted_relation_ids: []
                }})
                """,
                id=run_id,
                p=source_path,
                h=source_hash,
                v=extractor_version,
                started=started_at,
            ).consume()

    def mark_entity_emitted(self, *, entity_id: str, run_id: str) -> None:
        with self._driver.session() as s:
            s.run(
                f"""
                MATCH (e:{ENTITY_LABEL} {{id: $eid}})
                MATCH (r:{INGESTION_RUN_LABEL} {{id: $rid}})
                MERGE (e)-[:{EMITTED_IN}]->(r)
                """,
                eid=entity_id,
                rid=run_id,
            ).consume()

    def mark_relation_emitted(self, *, relation_id: str, run_id: str) -> None:
        # edge 에 edge 를 못 달아, run_id 를 relation 의 array property 에 append(dedupe)한다.
        with self._driver.session() as s:
            s.run(
                f"""
                MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $rid}}]->()
                SET r.emitted_in_run_ids =
                    CASE WHEN $run_id IN coalesce(r.emitted_in_run_ids, [])
                         THEN r.emitted_in_run_ids
                         ELSE coalesce(r.emitted_in_run_ids, []) + [$run_id] END
                """,
                rid=relation_id,
                run_id=run_id,
            ).consume()

    def finalize_run(
        self,
        *,
        run_id: str,
        status: str,
        completed_at: str,
        emitted_entity_ids: list[str],
        emitted_relation_ids: list[str],
    ) -> None:
        with self._driver.session() as s:
            s.run(
                f"""
                MATCH (r:{INGESTION_RUN_LABEL} {{id: $id}})
                SET r.status = $status,
                    r.completed_at = $completed,
                    r.emitted_entity_ids = $eids,
                    r.emitted_relation_ids = $rids
                """,
                id=run_id,
                status=status,
                completed=completed_at,
                eids=emitted_entity_ids,
                rids=emitted_relation_ids,
            ).consume()

    def append_emitted_relations(
        self, *, run_id: str, relation_ids: list[str]
    ) -> None:
        """이미 finalize 된 run 의 emitted_relation_ids 에 dedupe append (issue #78).

        디렉토리 2-pass 가 정방향 cross-file 관계를 *원래 그 관계를 추출한 파일의
        run* 에 귀속시킨다. 차분(apply_*_diff)은 run 노드의 emitted_relation_ids
        배열을 기준으로 삭제 여부를 판정하므로, 2-pass 관계를 이 배열에 넣어야
        그 파일의 다음 재적재 차분이 관계를 잘못 삭제하지 않는다. 포트 docstring
        참조. 빈 입력이면 호출 자체를 생략.
        """
        if not relation_ids:
            return
        with self._driver.session() as s:
            # reduce 로 각 id 를 dedupe append — 같은 id 가 이미 있으면 그대로 둔다.
            s.run(
                f"""
                MATCH (r:{INGESTION_RUN_LABEL} {{id: $id}})
                WITH r, reduce(acc = coalesce(r.emitted_relation_ids, []),
                               x IN $rids |
                               CASE WHEN x IN acc THEN acc ELSE acc + [x] END
                              ) AS merged
                SET r.emitted_relation_ids = merged
                """,
                id=run_id,
                rids=relation_ids,
            ).consume()

    def apply_entity_diff(
        self, *, entity_id: str, source_path: str, run_id: str
    ) -> str:
        """이번 회차가 손대지 않은 이전 emitted entity 처리.

        - source_paths 가 오직 source_path 뿐이면 노드 + 인접 관계 삭제(DETACH DELETE).
        - 그 외는 source_paths/source_chunk_indexes 에서 그 항목만 제거한다. 이전 회차
          EMITTED_IN 엣지는 회차 히스토리라 건드리지 않는다."""
        with self._driver.session() as s:
            row = s.run(
                f"MATCH (e:{ENTITY_LABEL} {{id: $id}}) "
                "RETURN e.source_paths AS paths, "
                "       e.source_chunk_indexes AS chunks, "
                "       e.source_total_chunks AS totals",
                id=entity_id,
            ).single()
            if row is None:
                return "missing"
            paths = list(row["paths"] or [])
            chunks = list(row["chunks"] or [])
            totals = list(row["totals"] or [])
            distinct_paths = set(paths)
            if not distinct_paths or distinct_paths == {source_path}:
                # 단일 소스에서 온 노드 — 통째로 삭제.
                s.run(
                    f"MATCH (e:{ENTITY_LABEL} {{id: $id}}) DETACH DELETE e",
                    id=entity_id,
                ).consume()
                return "deleted"
            # 다른 소스도 들어 있음 — 해당 source_path 만 잘라낸다.
            # 세 배열은 같은 인덱스로 짝지어 있어 함께 trim 해야 (path, chunk, total) 복원이 맞는다.
            new_paths: list[str] = []
            new_chunks: list[int] = []
            new_totals: list[int] = []
            for i, p in enumerate(paths):
                if p == source_path:
                    continue
                new_paths.append(p)
                new_chunks.append(chunks[i] if i < len(chunks) else -1)
                new_totals.append(totals[i] if i < len(totals) else -1)
            s.run(
                f"""
                MATCH (e:{ENTITY_LABEL} {{id: $id}})
                SET e.source_paths = $paths,
                    e.source_chunk_indexes = $chunks,
                    e.source_total_chunks = $totals
                """,
                id=entity_id,
                paths=new_paths,
                chunks=new_chunks,
                totals=new_totals,
            ).consume()
            return "trimmed"

    def apply_relation_diff(
        self, *, relation_id: str, source_path: str
    ) -> str:
        """관계의 차분 — 같은 규칙. source_paths 가 단일이면 삭제, 아니면 trim."""
        with self._driver.session() as s:
            row = s.run(
                f"""
                MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $id}}]->()
                RETURN r.source_paths AS paths
                """,
                id=relation_id,
            ).single()
            if row is None:
                return "missing"
            paths = list(row["paths"] or [])
            distinct_paths = set(paths)
            if not distinct_paths or distinct_paths == {source_path}:
                s.run(
                    f"""
                    MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $id}}]->()
                    DELETE r
                    """,
                    id=relation_id,
                ).consume()
                return "deleted"
            new_paths = [p for p in paths if p != source_path]
            s.run(
                f"""
                MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $id}}]->()
                SET r.source_paths = $paths
                """,
                id=relation_id,
                paths=new_paths,
            ).consume()
            return "trimmed"

    # ---------- Read ----------

    def find_by_keywords_scored(
        self,
        *,
        keywords: list[str],
        limit_per_keyword: int,
        namespace_id: str = "default",
    ) -> list[KeywordHit]:
        """fulltext 인덱스를 keyword 별로 따로 호출한다. 한 OR 쿼리로 보내면 어느
        keyword 가 노드를 surface 시켰는지 알 수 없어, keyword 단위로 부르고 결과에
        태깅한다. 점수 정규화는 전체 집합을 보는 상위 레이어의 몫이라 여기선 raw 점수만."""
        if not keywords:
            return []
        hits: list[KeywordHit] = []
        with self._driver.session() as s:
            for kw in keywords:
                lucene_query = _lucene_escape(kw)
                records = s.run(
                    """
                    CALL db.index.fulltext.queryNodes($idx, $q) YIELD node, score
                    WHERE coalesce(node.namespace_id, 'default') = $ns
                    RETURN node, score
                    ORDER BY score DESC
                    LIMIT $limit
                    """,
                    parameters={
                        "idx": FULLTEXT_INDEX,
                        "q": lucene_query,
                        "ns": namespace_id,
                        "limit": limit_per_keyword,
                    },
                ).data()
                for rec in records:
                    hits.append(
                        KeywordHit(
                            node=_node_to_response(rec["node"]),
                            raw_score=float(rec["score"]),
                            matched_keyword=kw,
                        )
                    )
        return hits

    def find_entities_dense(
        self,
        *,
        query_embedding: list[float],
        matched_keyword: str,
        limit: int,
        namespace_id: str = "default",
    ) -> list[DenseHit]:
        """단일 query embedding 의 dense ANN. cosine 모드 score 는 그대로 0..1 이라
        바로 쓴다. 결과는 fusion 에서 다시 잘리므로 limit 을 그대로 후보 풀로 둔다."""
        if not query_embedding:
            return []
        with self._driver.session() as s:
            rows = s.run(
                "CALL db.index.vector.queryNodes($idx, $k, $vec) "
                "YIELD node, score "
                f"WHERE node:{ENTITY_LABEL} "
                "  AND coalesce(node.namespace_id, 'default') = $ns "
                "RETURN node, score ORDER BY score DESC LIMIT $limit",
                parameters={
                    "idx": VECTOR_INDEX,
                    "k": limit,
                    "vec": query_embedding,
                    "ns": namespace_id,
                    "limit": limit,
                },
            ).data()
        return [
            DenseHit(
                node=_node_to_response(r["node"]),
                # 부동소수 오차와 반대 방향 cosine 을 응답 계약(0..1)에 맞춰 clamp.
                raw_score=max(0.0, min(1.0, float(r["score"]))),
                matched_keyword=matched_keyword,
            )
            for r in rows
        ]

    # ---------- read primitive ----------

    def get_schema_summary(
        self, *, examples_per_type: int = 5, namespace_id: str = "default"
    ) -> tuple[list[EntityTypeStat], list[RelationTypeStat]]:
        """엔티티/관계 통계 + 타입별 example 노드를 한 번에 묶어 반환한다. example 은
        type 별 가장 최근 갱신 노드(updated_at DESC)를 고른다."""
        entity_stats: list[EntityTypeStat] = []
        relation_stats: list[RelationTypeStat] = []
        with self._driver.session() as s:
            # 엔티티 타입 카운트(namespace 안).
            type_rows = s.run(
                f"MATCH (n:{ENTITY_LABEL}) "
                "WHERE coalesce(n.namespace_id, 'default') = $ns "
                "RETURN n.type AS type, count(*) AS count "
                "ORDER BY type",
                ns=namespace_id,
            ).data()
            for row in type_rows:
                examples = s.run(
                    f"MATCH (n:{ENTITY_LABEL}) WHERE n.type = $t "
                    "  AND coalesce(n.namespace_id, 'default') = $ns "
                    "RETURN n.id AS id, n.name AS name "
                    "ORDER BY n.updated_at DESC LIMIT $k",
                    t=row["type"],
                    ns=namespace_id,
                    k=examples_per_type,
                ).data()
                entity_stats.append(
                    EntityTypeStat(
                        type=row["type"],
                        count=int(row["count"]),
                        examples=[(e["id"], e["name"]) for e in examples],
                    )
                )

            # 관계 타입 카운트 — 단일 RELATES_TO 라벨 + type 속성.
            rel_rows = s.run(
                f"MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL}) "
                "WHERE coalesce(a.namespace_id, 'default') = $ns "
                "  AND coalesce(b.namespace_id, 'default') = $ns "
                "RETURN r.type AS type, count(*) AS count "
                "ORDER BY type",
                ns=namespace_id,
            ).data()
            for row in rel_rows:
                pairs = s.run(
                    f"MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL}) "
                    "WHERE r.type = $t "
                    "  AND coalesce(a.namespace_id, 'default') = $ns "
                    "  AND coalesce(b.namespace_id, 'default') = $ns "
                    "RETURN a.type AS from_type, b.type AS to_type, count(*) AS c "
                    "ORDER BY c DESC LIMIT 5",
                    t=row["type"],
                    ns=namespace_id,
                ).data()
                relation_stats.append(
                    RelationTypeStat(
                        type=row["type"],
                        count=int(row["count"]),
                        common_pairs=[
                            (p["from_type"], p["to_type"], int(p["c"])) for p in pairs
                        ],
                    )
                )
        return entity_stats, relation_stats

    def entity_exists(
        self, *, entity_id: str, namespace_id: str = "default"
    ) -> bool:
        with self._driver.session() as s:
            rec = s.run(
                f"MATCH (n:{ENTITY_LABEL} {{id: $id}}) "
                "WHERE coalesce(n.namespace_id, 'default') = $ns "
                "RETURN n.id AS id",
                id=entity_id,
                ns=namespace_id,
            ).single()
        return rec is not None

    def count_entities_by_namespace(self) -> dict[str, int]:
        with self._driver.session() as s:
            rows = s.run(
                f"MATCH (e:{ENTITY_LABEL}) "
                "RETURN coalesce(e.namespace_id, 'default') AS ns, count(*) AS c "
                "ORDER BY c DESC"
            ).data()
        return {r["ns"]: int(r["c"]) for r in rows}

    def find_overmerged_entities(
        self, *, max_aliases: int = 30, max_distinct_ids: int = 2
    ) -> list:
        """기존 그래프의 과잉 병합 의심 노드를 탐지한다. 모든 Entity 의 (id, name,
        aliases)에 결정적 detector 를 적용한다. 운영자 검토용이라 포트가 아닌 구현체에만 둔다."""
        from ..domain.identity import detect_overmerged_entities

        with self._driver.session() as s:
            rows = s.run(
                f"MATCH (e:{ENTITY_LABEL}) "
                "RETURN e.id AS id, e.name AS name, "
                "coalesce(e.aliases, []) AS aliases"
            ).data()
        return detect_overmerged_entities(
            ((r["id"], r["name"] or "", list(r["aliases"] or [])) for r in rows),
            max_aliases=max_aliases,
            max_distinct_ids=max_distinct_ids,
        )

    def get_stored_entity(self, *, entity_id: str) -> StoredEntity | None:
        with self._driver.session() as s:
            rec = s.run(
                f"MATCH (e:{ENTITY_LABEL} {{id: $id}}) RETURN e",
                id=entity_id,
            ).single()
        if rec is None:
            return None
        return _node_to_stored(rec["e"])

    def get_entity_with_counts(
        self, *, entity_id: str, namespace_id: str = "default"
    ) -> EntityWithCounts | None:
        """단일 노드 + outgoing/incoming relation type 카운트. 한 세션 안에서 세
        쿼리를 묶어 일관된 스냅샷을 본다."""
        with self._driver.session() as s:
            # namespace 밖 노드는 없는 것으로 본다.
            node_row = s.run(
                f"MATCH (n:{ENTITY_LABEL} {{id: $id}}) "
                "WHERE coalesce(n.namespace_id, 'default') = $ns "
                "RETURN n",
                id=entity_id,
                ns=namespace_id,
            ).single()
            if node_row is None:
                return None
            node = _node_to_response(node_row["n"])
            # 카운트도 같은 namespace 의 이웃 엣지만 — 다른 namespace 로 가는 엣지는
            # 격리상 존재하지 않아야 하지만, 방어적으로 상대 노드도 namespace 로 거른다.
            out_rows = s.run(
                f"MATCH (n:{ENTITY_LABEL} {{id: $id}})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(m:{ENTITY_LABEL}) "
                "WHERE coalesce(m.namespace_id, 'default') = $ns "
                "RETURN r.type AS type, count(*) AS c",
                id=entity_id,
                ns=namespace_id,
            ).data()
            in_rows = s.run(
                f"MATCH (n:{ENTITY_LABEL} {{id: $id}})<-[r:{RELATION_TYPE_LABEL_DEFAULT}]-(m:{ENTITY_LABEL}) "
                "WHERE coalesce(m.namespace_id, 'default') = $ns "
                "RETURN r.type AS type, count(*) AS c",
                id=entity_id,
                ns=namespace_id,
            ).data()
        outgoing = {row["type"]: int(row["c"]) for row in out_rows}
        incoming = {row["type"]: int(row["c"]) for row in in_rows}
        return EntityWithCounts(node=node, outgoing=outgoing, incoming=incoming)

    def expand_neighbors(
        self,
        *,
        entry_id: str,
        relation_types: list[str] | None,
        direction: str,
        hops: int,
        max_nodes: int,
        namespace_id: str = "default",
    ) -> NeighborhoodResult:
        """N-hop BFS — 진입점에서 거리 가까운 순으로 max_nodes 절단. Cypher `*1..N` 은
        노드를 여러 번 방문한 경로를 다 돌려줘, 고유 노드 집합을 거리 순으로 자르려면
        Python BFS 가 잘림 정책을 더 확실히 보장한다."""
        # 진입점 노드부터 시작 — 존재 확인은 호출자 책임.
        visited_nodes: dict[str, Node] = {}
        boundary_edges: dict[str, Edge] = {}
        # frontier 는 (id, level) 튜플들의 리스트 — BFS 의 한 레벨씩 확장.
        with self._driver.session() as s:
            # 진입점 노드부터. namespace 밖이면 빈 결과.
            row = s.run(
                f"MATCH (n:{ENTITY_LABEL} {{id: $id}}) "
                "WHERE coalesce(n.namespace_id, 'default') = $ns "
                "RETURN n",
                id=entry_id,
                ns=namespace_id,
            ).single()
            if row is None:
                return NeighborhoodResult(nodes=[], edges=[], truncated=False)
            visited_nodes[entry_id] = _node_to_response(row["n"])

            frontier_ids = [entry_id]
            truncated = False
            for _hop in range(hops):
                if not frontier_ids:
                    break
                # 각 hop 에서 frontier 의 *전체* 를 한 쿼리로 확장 — N+1 회피.
                rows = s.run(
                    _build_neighbor_expand_cypher(direction),
                    frontier=frontier_ids,
                    rel_types=relation_types,
                    use_rel_filter=bool(relation_types),
                    ns=namespace_id,
                ).data()
                # 허브 인지 절단 — max_nodes 초과 시 낮은 degree(구체적) 이웃을 우선
                # 남기려고 degree 오름차순으로 처리한다. 배경은 ADR-0017.
                rows = _order_rows_by_degree(rows)
                next_frontier: list[str] = []
                for r in rows:
                    edge = _record_to_edge(
                        rel_id=r["rel_id"],
                        rel_type=r["rel_type"],
                        rel_created_at=r["rel_created_at"],
                        rel_updated_at=r["rel_updated_at"],
                        rel_source_paths=r["rel_source_paths"],
                        from_id=r["a_id"],
                        to_id=r["b_id"],
                    )
                    other_node_data = r["other"]
                    other_id = other_node_data["id"]
                    if other_id in visited_nodes:
                        # 이미 방문한 노드로의 엣지는 경계 엣지로 유지(절단과 무관).
                        if edge.id not in boundary_edges:
                            boundary_edges[edge.id] = edge
                        continue
                    if len(visited_nodes) >= max_nodes:
                        truncated = True
                        continue
                    if edge.id not in boundary_edges:
                        boundary_edges[edge.id] = edge
                    visited_nodes[other_id] = _node_to_response(other_node_data)
                    next_frontier.append(other_id)
                if truncated:
                    break
                frontier_ids = next_frontier
        # 경계 엣지에서 양쪽 노드가 visited 인 것만 응답에 남긴다 — 한쪽이 잘림
        # 으로 제외된 엣지가 dangling 으로 남지 않도록.
        edges = [
            e for e in boundary_edges.values()
            if e.from_ in visited_nodes and e.to in visited_nodes
        ]
        return NeighborhoodResult(
            nodes=list(visited_nodes.values()),
            edges=edges,
            truncated=truncated,
        )

    def expand_subgraph(
        self,
        *,
        entry_ids: list[str],
        relation_types: list[str] | None,
        hops: int,
        max_nodes: int,
        namespace_id: str = "default",
    ) -> NeighborhoodResult:
        """multi-source BFS — 여러 진입점에서 동시에 확장.

        잘림 정책: *진입점 집합으로부터의 최단 거리* 기준 가까운 순. 즉 진입점
        A 에서 1-hop 노드는 다른 진입점 B 에서 5-hop 떨어진 노드보다 먼저 채워
        진다 (multi-source BFS 의 level 정의).
        """
        visited_nodes: dict[str, Node] = {}
        boundary_edges: dict[str, Edge] = {}
        with self._driver.session() as s:
            # 진입점 노드들(dedupe). namespace 밖 진입점은 무시.
            rows = s.run(
                f"MATCH (n:{ENTITY_LABEL}) WHERE n.id IN $ids "
                "  AND coalesce(n.namespace_id, 'default') = $ns RETURN n",
                ids=entry_ids,
                ns=namespace_id,
            ).data()
            for r in rows:
                node = _node_to_response(r["n"])
                visited_nodes[node.id] = node

            frontier_ids = list(visited_nodes.keys())
            truncated = False
            for _hop in range(hops):
                if not frontier_ids:
                    break
                rows = s.run(
                    _build_neighbor_expand_cypher("both"),
                    frontier=frontier_ids,
                    rel_types=relation_types,
                    use_rel_filter=bool(relation_types),
                    ns=namespace_id,
                ).data()
                # 허브 인지 절단 — expand_neighbors 와 동일 원리.
                rows = _order_rows_by_degree(rows)
                next_frontier: list[str] = []
                for r in rows:
                    edge = _record_to_edge(
                        rel_id=r["rel_id"],
                        rel_type=r["rel_type"],
                        rel_created_at=r["rel_created_at"],
                        rel_updated_at=r["rel_updated_at"],
                        rel_source_paths=r["rel_source_paths"],
                        from_id=r["a_id"],
                        to_id=r["b_id"],
                    )
                    other_data = r["other"]
                    other_id = other_data["id"]
                    if other_id in visited_nodes:
                        if edge.id not in boundary_edges:
                            boundary_edges[edge.id] = edge
                        continue
                    if len(visited_nodes) >= max_nodes:
                        truncated = True
                        continue
                    if edge.id not in boundary_edges:
                        boundary_edges[edge.id] = edge
                    visited_nodes[other_id] = _node_to_response(other_data)
                    next_frontier.append(other_id)
                if truncated:
                    break
                frontier_ids = next_frontier
        edges = [
            e for e in boundary_edges.values()
            if e.from_ in visited_nodes and e.to in visited_nodes
        ]
        return NeighborhoodResult(
            nodes=list(visited_nodes.values()),
            edges=edges,
            truncated=truncated,
        )

    def find_shortest_paths(
        self,
        *,
        from_id: str,
        to_id: str,
        max_hops: int,
        max_paths: int,
        relation_types: list[str] | None,
        namespace_id: str = "default",
    ) -> list[PathResult]:
        """k-shortest paths — allShortestPaths 로 모든 최단 경로를 받아 길이순 정렬한다.
        relation_types 가 있으면 경로의 모든 엣지가 그 타입이어야 한다."""
        # relationships(p) 를 properties-only 로 RETURN 한다 — driver 가 relationship
        # 리스트를 일관 직렬화하지 않을 수 있어 엣지 속성만 원시 값으로 꺼낸다.
        # fetch_limit 을 max_paths 보다 넉넉히 잡아, 허브를 안 거치는 구체적 경로를
        # hub_score 로 재정렬한 뒤 자른다(Cypher LIMIT 만으론 허브 경로가 먼저 잘려 든다).
        fetch_limit = min(50, max(max_paths * 5, 10))
        # 관계는 RELATES_TO 만 따라간다. 무제한 확장은 EMITTED_IN provenance 엣지까지
        # 타고 들어가 직렬화 크래시와 "같은 run 에서 나옴" 가짜 다리를 만든다.
        # 양 끝점과 경로의 모든 노드는 같은 namespace 안이어야 한다.
        cypher = """
        MATCH (a:Entity {id: $from_id}), (b:Entity {id: $to_id})
        WHERE coalesce(a.namespace_id, 'default') = $ns
          AND coalesce(b.namespace_id, 'default') = $ns
        MATCH p = allShortestPaths((a)-[:%s*1..%d]-(b))
        WITH p,
             [r IN relationships(p) | r.type] AS rel_types,
             length(p) AS len
        WHERE ($filter_rels = false OR all(t IN rel_types WHERE t IN $rel_types))
          AND all(n IN nodes(p) WHERE coalesce(n.namespace_id, 'default') = $ns)
        RETURN nodes(p) AS nodes,
               [r IN relationships(p) | {
                   id: r.id,
                   type: r.type,
                   created_at: r.created_at,
                   updated_at: r.updated_at,
                   source_paths: r.source_paths
               }] AS rels,
               len AS length
        ORDER BY length ASC
        LIMIT $fetch_limit
        """ % (RELATION_TYPE_LABEL_DEFAULT, int(max_hops))
        with self._driver.session() as s:
            rows = s.run(
                cypher,
                from_id=from_id,
                to_id=to_id,
                filter_rels=bool(relation_types),
                rel_types=relation_types or [],
                ns=namespace_id,
                fetch_limit=fetch_limit,
            ).data()

            # 중간 노드 degree 를 한 쿼리로 조회한다(끝점 제외). comprehension 안의
            # 서브쿼리 degree 는 5.x 에서 불안정해, id 를 모아 단일 MATCH 로 받는다.
            endpoints = {from_id, to_id}
            intermediate_ids = {
                n["id"]
                for row in rows
                for n in row["nodes"]
                if n["id"] not in endpoints
            }
            degree_by_id: dict[str, int] = {}
            if intermediate_ids:
                deg_rows = s.run(
                    f"MATCH (n:{ENTITY_LABEL}) WHERE n.id IN $ids "
                    f"RETURN n.id AS id, COUNT {{ (n)-[:{RELATION_TYPE_LABEL_DEFAULT}]-() }} AS deg",
                    ids=list(intermediate_ids),
                ).data()
                degree_by_id = {r["id"]: int(r["deg"]) for r in deg_rows}

        paths: list[PathResult] = []
        for row in rows:
            node_objs = [_node_to_response(n) for n in row["nodes"]]
            # 엣지 방향 정규화 — 양방향 패턴은 r 의 start/end 가 traversal 방향과
            # 어긋날 수 있어, edges[i] 가 nodes[i]→nodes[i+1] 이 되게 재정의한다.
            edges: list[Edge] = []
            for i, rel_props in enumerate(row["rels"]):
                edges.append(
                    _record_to_edge(
                        rel_id=rel_props["id"],
                        rel_type=rel_props.get("type"),
                        rel_created_at=rel_props.get("created_at"),
                        rel_updated_at=rel_props.get("updated_at"),
                        rel_source_paths=rel_props.get("source_paths"),
                        from_id=node_objs[i].id,
                        to_id=node_objs[i + 1].id,
                    )
                )
            # hub_score = 중간 노드 (끝점 제외) 의 log(1+degree) 합. 끝점만 있는
            # 1-hop 직접 경로는 중간 노드가 없어 0.0 (가장 구체적 = 최선).
            hub_score = sum(
                math.log1p(degree_by_id.get(n.id, 0))
                for n in node_objs[1:-1]
            )
            paths.append(
                PathResult(
                    nodes=node_objs,
                    edges=edges,
                    length=int(row["length"]),
                    hub_score=hub_score,
                )
            )
        # 같은 길이면 hub_score 가 낮은 (구체적) 경로 우선 → max_paths 로 절단.
        paths.sort(key=lambda p: (p.length, p.hub_score))
        return paths[:max_paths]


# ---------- helpers ----------


def _node_to_stored(node: Any) -> StoredEntity:
    """neo4j Node → StoredEntity (내부)."""
    return StoredEntity(
        id=node["id"],
        name=node["name"],
        type=node["type"],
        aliases=list(node.get("aliases") or []),
        description=node.get("description"),
        properties={},
        source_refs=_extract_source_refs(node),
        created_at=node["created_at"],
        updated_at=node["updated_at"],
        embedding=list(node.get("embedding") or []),
        normalized_name=node.get("normalized_name") or "",
        normalized_aliases=list(node.get("normalized_aliases") or []),
        blocked_aliases=list(node.get("blocked_aliases") or []),
        # 이걸 빠뜨리면 읽어 온 노드가 전부 자기를 default 소속이라고 말한다. 노드가
        # 어느 namespace 인지 되묻는 쪽(떼어내기 등)이 늘 default 로 판정해 격리가 뚫린다.
        namespace_id=node.get("namespace_id") or "default",
    )


def _to_run_record(node: Any) -> IngestionRunRecord:
    return IngestionRunRecord(
        id=node["id"],
        source_path=node["source_path"],
        source_hash=node["source_hash"],
        started_at=node["started_at"],
        completed_at=node.get("completed_at"),
        status=node["status"],
        emitted_entity_ids=list(node.get("emitted_entity_ids") or []),
        emitted_relation_ids=list(node.get("emitted_relation_ids") or []),
        extractor_version=node.get("extractor_version") or "",
    )


def _clamp(value: str | None, max_length: int) -> str | None:
    """문자열을 응답 모델의 max_length 로 자른다(None 은 그대로).

    이미 저장된 값이 모델 상한을 넘으면 BFS 가 그 노드/엣지에 닿는 순간 pydantic
    string_too_long 으로 응답 전체가 500 으로 죽는다. 재적재는 비싸므로 읽기 경계에서
    잘라 프리미티브가 어떤 데이터에도 안 깨지게 한다(노드/엣지 자체는 보존)."""
    if value is None:
        return None
    return value if len(value) <= max_length else value[:max_length]


def _node_to_response(node: Any) -> Node:
    """neo4j Node → 응답 Node (embedding 제외)."""
    return Node(
        id=node["id"],
        # name 200 / type 64 / description 2000 — domain.models.Node 의 상한.
        # 초과 시 clamp 해 BFS 가 비정상 노드에서 500 나는 것을 방지.
        name=_clamp(node["name"], 200),
        type=_clamp(node["type"], 64),
        aliases=list(node.get("aliases") or []),
        description=_clamp(node.get("description"), 2000),
        properties={},
        source_refs=_extract_source_refs(node),
        created_at=node["created_at"],
        updated_at=node["updated_at"],
    )


def _union(a: list[str], b: list[str]) -> list[str]:
    """순서를 지키며 합친다. 관계를 옮길 때 출처와 회차 목록이 한쪽만 남지 않게."""
    out = list(a)
    seen = set(a)
    for item in b:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _plan_endpoint_move(
    *, from_id: str, to_id: str, old_entity_id: str, new_entity_id: str
) -> tuple[str, str] | None:
    """관계의 끝점을 옮긴 뒤의 (from, to). 옮길 자리가 없으면 None."""
    new_from = new_entity_id if from_id == old_entity_id else from_id
    new_to = new_entity_id if to_id == old_entity_id else to_id
    if (new_from, new_to) == (from_id, to_id):
        return None
    return new_from, new_to


def _source_ref_arrays(source_refs: list[SourceRef]) -> tuple[list[str], list[int], list[int]]:
    """SourceRef 리스트를 그래프 저장용 세 배열(paths/chunk_indexes/total_chunks)로.
    그래프 list 속성은 null 원소를 못 담아 None 은 -1 sentinel 로 바꾸고, 세 배열은
    같은 인덱스로 짝진다."""
    paths = [sr.source_path for sr in source_refs]
    chunks = [sr.chunk_index if sr.chunk_index is not None else -1 for sr in source_refs]
    totals = [sr.total_chunks if sr.total_chunks is not None else -1 for sr in source_refs]
    return paths, chunks, totals


def _extract_source_refs(node: Any) -> list[SourceRef]:
    paths = list(node.get("source_paths") or [])
    chunks = list(node.get("source_chunk_indexes") or [])
    totals = list(node.get("source_total_chunks") or [])
    refs: list[SourceRef] = []
    for i, p in enumerate(paths):
        ci = chunks[i] if i < len(chunks) else None
        tc = totals[i] if i < len(totals) else None
        # -1 sentinel → None 복원.
        if ci == -1:
            ci = None
        if tc == -1:
            tc = None
        refs.append(SourceRef(source_path=p, chunk_index=ci, total_chunks=tc))
    return refs


def _order_rows_by_degree(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """이웃 확장 row 를 other_degree 오름차순으로 안정 정렬한다. 절단 시 낮은
    degree(구체적) 이웃을 남기고 허브부터 버린다. degree 없는 row 는 0(맨 앞)."""
    return sorted(rows, key=lambda r: r.get("other_degree") or 0)


def _build_neighbor_expand_cypher(direction: str) -> str:
    """frontier 노드 집합에서 한 hop 을 확장하는 cypher.

    방향(outgoing/incoming)이 의미를 가지려면 명시적 화살표가 필요해 direction 별로
    패턴을 분기한다. relationship 은 properties-only 로 RETURN 한다 — driver 가 UNION
    결과의 relationship 을 tuple 로 직렬화하는 경로가 있어, 원시 값만 꺼내 그 quirk 를
    피한다. 출력은 a_id/b_id/other + relationship 속성들."""
    rel_select = (
        "r.id AS rel_id, r.type AS rel_type, "
        "r.created_at AS rel_created_at, r.updated_at AS rel_updated_at, "
        "r.source_paths AS rel_source_paths"
    )
    # other_degree: 확장 대상 노드의 연결 수. 절단 시 낮은 degree 를 우선 남기는 정렬 키.
    deg_out = f"COUNT {{ (b)-[:{RELATION_TYPE_LABEL_DEFAULT}]-() }} AS other_degree"
    deg_in = f"COUNT {{ (a)-[:{RELATION_TYPE_LABEL_DEFAULT}]-() }} AS other_degree"
    # 확장 대상(other) 노드가 요청 namespace 안일 때만 따라간다. frontier 는 이미
    # in-namespace 라 other 만 거르면 순회가 namespace 를 안 넘는다.
    if direction == "outgoing":
        pattern = f"(a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL})"
        select = f"a.id AS a_id, b.id AS b_id, b AS other, {rel_select}, {deg_out}"
        where_frontier = "a.id IN $frontier AND coalesce(b.namespace_id, 'default') = $ns"
    elif direction == "incoming":
        pattern = f"(a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL})"
        select = f"a.id AS a_id, b.id AS b_id, a AS other, {rel_select}, {deg_in}"
        where_frontier = "b.id IN $frontier AND coalesce(a.namespace_id, 'default') = $ns"
    else:
        # both — Cypher 의 한 쿼리에서 양방향을 한 번에 받으려면 UNION 또는
        # CASE 식이 필요. 가장 단순한 형태로 UNION 사용.
        return (
            f"MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL}) "
            "WHERE a.id IN $frontier AND coalesce(b.namespace_id, 'default') = $ns "
            "AND ($use_rel_filter = false OR r.type IN $rel_types) "
            f"RETURN a.id AS a_id, b.id AS b_id, b AS other, {rel_select}, {deg_out} "
            "UNION "
            f"MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL}) "
            "WHERE b.id IN $frontier AND coalesce(a.namespace_id, 'default') = $ns "
            "AND ($use_rel_filter = false OR r.type IN $rel_types) "
            f"RETURN a.id AS a_id, b.id AS b_id, a AS other, {rel_select}, {deg_in}"
        )
    return (
        f"MATCH {pattern} "
        f"WHERE {where_frontier} "
        "AND ($use_rel_filter = false OR r.type IN $rel_types) "
        f"RETURN {select}"
    )


def _record_to_edge(
    *,
    rel_id: str,
    rel_type: str | None,
    rel_created_at: Any,
    rel_updated_at: Any,
    rel_source_paths: list[str] | None,
    from_id: str,
    to_id: str,
) -> Edge:
    """relationship 속성(원시 값) → 응답 Edge. from_id/to_id 를 호출자가 명시하는 건
    양방향 traversal 에서 진행 방향에 맞춰 from/to 를 재정의하기 위함이다."""
    return Edge(
        id=rel_id,
        **{"from": from_id},
        to=to_id,
        # Edge.type 상한 64 로 clamp — 초과 라벨이 서브그래프 전체를 500 으로 죽이지 않게.
        type=_clamp(rel_type or RELATION_TYPE_LABEL_DEFAULT, 64) or RELATION_TYPE_LABEL_DEFAULT,
        properties={},
        source_refs=[SourceRef(source_path=sp) for sp in (rel_source_paths or [])],
        created_at=rel_created_at,
        updated_at=rel_updated_at,
    )


_LUCENE_SPECIAL = '+-&|!(){}[]^"~*?:\\/'

# Lucene 은 대문자 AND/OR/NOT 를 boolean 연산자로 해석해 ParseException 을 낸다.
# _lucene_escape 가 이 토큰을 소문자화해 일반 term 으로 중립화한다(분석기도 소문자화).
_LUCENE_RESERVED_WORDS = {"AND", "OR", "NOT"}


def _lucene_escape(s: str) -> str:
    """Lucene 특수 문자 escape — keyword 의 콜론/따옴표가 파서를 깨뜨리지 않게 모두
    백슬래시로 escape 한다."""
    out: list[str] = []
    for ch in s:
        if ch in _LUCENE_SPECIAL:
            out.append("\\" + ch)
        elif ch.isspace():
            out.append(" ")
        else:
            out.append(ch)
    escaped = "".join(out).strip()
    # 예약 연산자(AND/OR/NOT) 대문자 토큰을 소문자화해 boolean 연산자 파싱을 막는다.
    if escaped:
        tokens = [
            t.lower() if t in _LUCENE_RESERVED_WORDS else t
            for t in escaped.split(" ")
        ]
        escaped = " ".join(t for t in tokens if t)
    # 멀티 토큰은 괄호로 묶어 OR 결합과 충돌하지 않게.
    if " " in escaped:
        return f"({escaped})"
    return escaped or "*"
