"""임베디드 그래프 저장소 어댑터 — Kuzu (ADR-0020 투 트랙, 임베디드 기본값).

Neo4j 어댑터(`graph.py`)와 *같은 프리미티브 계약*(GraphRepository 포트)을 구현한다.
차이는 백엔드 방언뿐이고, 노드/엣지 → 응답 모델 변환은 `graph.py` 의 헬퍼를
그대로 재사용해 두 백엔드가 같은 결과 모양을 내도록 잠근다.

Kuzu 특성 반영:
- 스키마 명시 — Neo4j 처럼 schemaless 가 아니라 노드/관계 테이블을 먼저 만든다.
  임베딩은 고정 차원 배열 컬럼 `FLOAT[dim]` 로 둔다(차원은 Settings).
- 풀텍스트는 문자열 컬럼에만 걸 수 있어, name + aliases 를 `search_text` 로
  비정규화해 그 컬럼에 인덱스한다(Neo4j 는 [name, aliases] 배열에 직접 인덱스).
- 풀텍스트 인덱스는 쓰기 후 최신성을 보장하려고 *더티 플래그 + 읽기 시 재빌드* 로
  관리한다. 임베디드는 체험/단일 사용자/작은 코퍼스 가정이라 재빌드 비용 무시 가능.
  벡터 인덱스는 재빌드하지 않는다 — 이유는 `_refresh_indexes` 주석에.
- BFS/절단/hub_score/RRF 는 도메인/이 어댑터의 Python 로직으로 처리(Neo4j 와 동일
  방식). Cypher 가 지는 건 인덱스 조회, 단일 홉 확장, k-최단 경로, upsert 뿐.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any

from ..config import Settings
from ..domain.errors import DependencyUnavailableError, UnprocessableError
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
from .graph import (
    ENTITY_LABEL,
    RELATION_TYPE_LABEL_DEFAULT,
    _node_to_response,
    _node_to_stored,
    _order_rows_by_degree,
    _plan_endpoint_move,
    _record_to_edge,
    _source_ref_arrays,
    _to_run_record,
    _union,
)

logger = logging.getLogger(__name__)

_VECTOR_INDEX = "entity_embedding_idx"
_FTS_INDEX = "entity_search_idx"


class KuzuGraphRepository(GraphRepository):
    """Kuzu 임베디드 어댑터 — GraphRepository 계약을 Neo4j 어댑터와 동일하게 만족한다.
    Kuzu 는 in-process 라 커넥션이 곧 DB 핸들이라 프로세스 수명 동안 하나를 재사용한다
    (임베디드는 단일 라이터)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._dim = int(settings.embedding_dimension)
        self._indexes_dirty = True
        self._vector_built = False
        self._fts_built = False
        self._vector_index = _VECTOR_INDEX
        self._vector_reindexed = False
        try:
            import kuzu

            db_path = settings.kuzu_db_path
            if db_path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
            self._db = kuzu.Database(db_path)
            self._conn = kuzu.Connection(self._db)
            for ext in ("vector", "fts"):
                self._conn.execute(f"LOAD EXTENSION {ext}")
        except Exception as e:  # noqa: BLE001
            raise DependencyUnavailableError(f"kuzu init failed: {e}") from e

    # ---------- 저수준 실행 헬퍼 ----------

    def _exec(self, query: str, **params: Any) -> Any:
        return self._conn.execute(query, parameters=params)

    def _fetch(self, query: str, **params: Any) -> list[dict[str, Any]]:
        """결과를 컬럼명 → 값 dict 리스트로. RETURN 절엔 반드시 AS 별칭을 준다."""
        res = self._conn.execute(query, parameters=params)
        cols = res.get_column_names()
        out: list[dict[str, Any]] = []
        while res.has_next():
            row = res.get_next()
            out.append({c: row[i] for i, c in enumerate(cols)})
        return out

    def close(self) -> None:
        # Kuzu Database/Connection 은 GC 로 정리된다. 명시 close API 는 없음.
        self._conn = None
        self._db = None

    def healthcheck(self) -> bool:
        try:
            self._exec("RETURN 1")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("kuzu healthcheck failed: %s", e)
            return False

    # ---------- 스키마 / 인덱스 ----------

    def ensure_indexes(self) -> None:
        """노드/관계 테이블을 idempotent 하게 만든다. 인덱스는 첫 읽기 시점에 만든다
        (_refresh_indexes)."""
        dim = self._dim
        self._exec(
            f"""CREATE NODE TABLE IF NOT EXISTS {ENTITY_LABEL}(
                id STRING, name STRING, normalized_name STRING, search_text STRING,
                type STRING, description STRING,
                aliases STRING[], normalized_aliases STRING[], blocked_aliases STRING[],
                embedding FLOAT[{dim}], namespace_id STRING,
                source_paths STRING[], source_chunk_indexes INT64[],
                source_total_chunks INT64[],
                created_at STRING, updated_at STRING,
                PRIMARY KEY(id))"""
        )
        self._exec(
            """CREATE NODE TABLE IF NOT EXISTS IngestionRun(
                id STRING, source_path STRING, source_hash STRING,
                extractor_version STRING, started_at STRING, completed_at STRING,
                status STRING, emitted_entity_ids STRING[],
                emitted_relation_ids STRING[], PRIMARY KEY(id))"""
        )
        self._exec(
            f"""CREATE REL TABLE IF NOT EXISTS {RELATION_TYPE_LABEL_DEFAULT}(
                FROM {ENTITY_LABEL} TO {ENTITY_LABEL},
                id STRING, type STRING, source_paths STRING[],
                created_at STRING, updated_at STRING,
                emitted_in_run_ids STRING[], _just_created BOOLEAN)"""
        )
        self._exec(
            f"CREATE REL TABLE IF NOT EXISTS EMITTED_IN(FROM {ENTITY_LABEL} TO IngestionRun)"
        )
        # 이미 만들어진 DB 는 CREATE ... IF NOT EXISTS 가 컬럼을 더해 주지 않아, 나중에
        # 생긴 컬럼은 따로 붙인다. 이미 있으면 Kuzu 가 거부하므로 실패를 삼킨다.
        try:
            self._exec(f"ALTER TABLE {ENTITY_LABEL} ADD blocked_aliases STRING[]")
        except Exception:  # noqa: BLE001
            pass
        self._vector_index = self._resolve_vector_index()
        self._indexes_dirty = True

    def _existing_indexes(self) -> dict[str, str]:
        """이 DB 에 살아 있는 인덱스 이름 → 종류. 앞선 프로세스가 만든 것도 보인다."""
        try:
            rows = self._fetch("CALL SHOW_INDEXES() RETURN *")
        except Exception:  # noqa: BLE001
            return {}
        return {
            str(r["index_name"]): str(r["index_type"])
            for r in rows
            if r.get("table_name") == ENTITY_LABEL
        }

    def _resolve_vector_index(self) -> str:
        """지금 쓸 벡터 인덱스 이름. reindex 가 이름을 옮겨 두었을 수 있어 DB 에 묻는다."""
        for name, kind in self._existing_indexes().items():
            if kind == "HNSW":
                return name
        return _VECTOR_INDEX

    def _refresh_indexes(self) -> None:
        """더티면 인덱스를 지금 데이터에 맞춘다.

        두 인덱스의 성질이 다르다. FTS 는 이름을 지웠다 다시 써도 되고, 다시 만들 이유도
        있다 — 병합이 search_text 를 고쳐 써도 옛 단어가 계속 잡히기 때문이다. 벡터
        (HNSW) 는 반대다. Kuzu 0.11.3 은 지운 벡터 인덱스 이름을 다시 쓰지 못하고
        ("already exists" 또는 "not loaded yet"), 만든 뒤 들어오고 지워진 행은 알아서
        반영한다. 그래서 벡터는 없을 때만 만든다.

        두 인덱스 모두 빈 테이블에도 만들어지므로 노드 수는 보지 않는다.
        """
        if not self._indexes_dirty:
            return
        existing = self._existing_indexes()
        if _FTS_INDEX in existing:
            try:
                self._exec(f"CALL DROP_FTS_INDEX('{ENTITY_LABEL}', '{_FTS_INDEX}')")
            except Exception:  # noqa: BLE001
                pass
        self._exec(f"CALL CREATE_FTS_INDEX('{ENTITY_LABEL}', '{_FTS_INDEX}', ['search_text'])")
        self._fts_built = True

        if self._vector_index not in existing:
            self._exec(
                f"CALL CREATE_VECTOR_INDEX('{ENTITY_LABEL}', '{self._vector_index}', "
                "'embedding', metric := 'cosine')"
            )
        self._vector_built = True
        self._indexes_dirty = False

    def _mark_dirty(self) -> None:
        self._indexes_dirty = True

    @staticmethod
    def _next_vector_index_name(current: str) -> str:
        """다음 벡터 인덱스 이름. 지운 이름은 되살릴 수 없어 번호를 하나 올린다."""
        base, _, tail = current.rpartition("_")
        if base == _VECTOR_INDEX and tail.isdigit():
            return f"{_VECTOR_INDEX}_{int(tail) + 1}"
        return f"{_VECTOR_INDEX}_2"

    def reindex_vector(self) -> dict[str, Any]:
        """임베딩 모델 교체 대응 — 벡터 인덱스를 지금 차원으로 다시 만든다.

        지운 이름을 다시 쓸 수 없어 (Kuzu 0.11.3) 새 이름으로 만든다. 옛 이름은 이 DB
        에서 영영 못 쓰게 되므로 reindex 를 반복하면 번호가 계속 올라간다.

        만들고 나서 지운다. 순서를 뒤집으면 같은 커넥션에서 다음 생성이 카탈로그 오류로
        깨진다. 한 번 지우고 나면 그 커넥션에서는 벡터 인덱스를 더 만들지 못해, 두 번째
        요청은 재시작을 알리고 거부한다.
        """
        if self._vector_reindexed:
            raise UnprocessableError(
                "이 프로세스에서는 벡터 색인을 이미 다시 만들었습니다. "
                "한 번 더 하려면 프로세스를 다시 띄우세요."
            )
        old = self._vector_index if self._vector_index in self._existing_indexes() else None
        new = self._next_vector_index_name(self._vector_index) if old else self._vector_index
        self._exec(
            f"CALL CREATE_VECTOR_INDEX('{ENTITY_LABEL}', '{new}', "
            "'embedding', metric := 'cosine')"
        )
        if old:
            try:
                self._exec(f"CALL DROP_VECTOR_INDEX('{ENTITY_LABEL}', '{old}')")
            except Exception:  # noqa: BLE001
                pass
        self._vector_index = new
        self._vector_built = True
        self._vector_reindexed = True
        return {"index": self._vector_index, "dimension": self._dim}

    # ---------- 쓰기 헬퍼 ----------

    def _emb_param(self, embedding: list[float] | None) -> list[float] | None:
        """임베딩을 고정 차원 컬럼에 맞춘다. 차원 불일치/빈 값은 NULL(인덱스가 건너뜀)."""
        if embedding and len(embedding) == self._dim:
            return [float(x) for x in embedding]
        return None

    def _search_text(self, name: str | None, aliases: list[str] | None) -> str:
        parts = [name or ""]
        parts.extend(aliases or [])
        return " ".join(p for p in parts if p)

    # ---------- 4 단계 동일성 — read + write ----------

    def find_by_normalized_name(
        self, *, normalized: str, type_: str, namespace_id: str = "default"
    ) -> StoredEntity | None:
        rows = self._fetch(
            f"""MATCH (e:{ENTITY_LABEL})
                WHERE e.type = $t AND e.namespace_id = $ns
                  AND (e.normalized_name = $n OR list_contains(e.normalized_aliases, $n))
                RETURN e AS e LIMIT 1""",
            n=normalized,
            t=type_,
            ns=namespace_id,
        )
        return _node_to_stored(rows[0]["e"]) if rows else None

    def find_entity_id_by_normalized_name(
        self, *, normalized: str, namespace_id: str = "default"
    ) -> str | None:
        if not normalized:
            return None
        rows = self._fetch(
            f"""MATCH (e:{ENTITY_LABEL})
                WHERE e.namespace_id = $ns
                  AND (e.normalized_name = $n OR list_contains(e.normalized_aliases, $n))
                RETURN e.id AS id LIMIT 2""",
            n=normalized,
            ns=namespace_id,
        )
        return rows[0]["id"] if len(rows) == 1 else None

    def find_entities_by_name(
        self, *, normalized_name: str, namespace_id: str = "default"
    ) -> list[StoredEntity]:
        if not normalized_name:
            return []
        rows = self._fetch(
            f"""MATCH (e:{ENTITY_LABEL})
                WHERE e.namespace_id = $ns AND e.normalized_name = $n
                RETURN e AS e ORDER BY e.id LIMIT 5""",
            n=normalized_name,
            ns=namespace_id,
        )
        return [_node_to_stored(r["e"]) for r in rows]

    def vector_search(
        self,
        *,
        embedding: list[float],
        top_k: int,
        type_: str,
        namespace_id: str = "default",
    ) -> list[StoredEntity]:
        if not embedding:
            return []
        self._refresh_indexes()
        if not self._vector_built:
            return []
        oversample = max(top_k * 4, top_k)
        rows = self._fetch(
            f"""CALL QUERY_VECTOR_INDEX('{ENTITY_LABEL}', '{self._vector_index}', $vec, $k)
                WITH node AS n, distance
                WHERE n.type = $t AND n.namespace_id = $ns
                RETURN n AS e ORDER BY distance ASC LIMIT $lim""",
            vec=self._emb_param(embedding) or [float(x) for x in embedding],
            k=oversample,
            t=type_,
            ns=namespace_id,
            lim=top_k,
        )
        return [_node_to_stored(r["e"]) for r in rows]

    def find_entities_dense(
        self,
        *,
        query_embedding: list[float],
        matched_keyword: str,
        limit: int,
        namespace_id: str = "default",
    ) -> list[DenseHit]:
        if not query_embedding:
            return []
        self._refresh_indexes()
        if not self._vector_built:
            return []
        rows = self._fetch(
            f"""CALL QUERY_VECTOR_INDEX('{ENTITY_LABEL}', '{self._vector_index}', $vec, $k)
                WITH node AS n, distance
                WHERE n.namespace_id = $ns
                RETURN n AS e, distance AS d ORDER BY distance ASC LIMIT $lim""",
            vec=self._emb_param(query_embedding) or [float(x) for x in query_embedding],
            k=limit,
            ns=namespace_id,
            lim=limit,
        )
        hits: list[DenseHit] = []
        for r in rows:
            # cosine metric 의 distance = 1 - cosine_similarity. 응답 계약은 0..1 이라
            # similarity 로 되돌리고 clamp.
            sim = 1.0 - float(r["d"])
            hits.append(
                DenseHit(
                    node=_node_to_response(r["e"]),
                    raw_score=max(0.0, min(1.0, sim)),
                    matched_keyword=matched_keyword,
                )
            )
        return hits

    def find_by_keywords_scored(
        self,
        *,
        keywords: list[str],
        limit_per_keyword: int,
        namespace_id: str = "default",
    ) -> list[KeywordHit]:
        if not keywords:
            return []
        self._refresh_indexes()
        if not self._fts_built:
            return []
        hits: list[KeywordHit] = []
        for kw in keywords:
            query = (kw or "").strip()
            if not query:
                continue
            rows = self._fetch(
                f"""CALL QUERY_FTS_INDEX('{ENTITY_LABEL}', '{_FTS_INDEX}', $q)
                    WITH node AS n, score
                    WHERE n.namespace_id = $ns
                    RETURN n AS e, score AS s ORDER BY score DESC LIMIT $lim""",
                q=query,
                ns=namespace_id,
                lim=limit_per_keyword,
            )
            for r in rows:
                hits.append(
                    KeywordHit(
                        node=_node_to_response(r["e"]),
                        raw_score=float(r["s"]),
                        matched_keyword=kw,
                    )
                )
        return hits

    def create_entity(self, *, entity: StoredEntity) -> None:
        source_paths, source_chunks, source_totals = _source_ref_arrays(entity.source_refs)
        self._exec(
            f"""CREATE (e:{ENTITY_LABEL} {{
                id: $id, name: $name, normalized_name: $normalized_name,
                search_text: $search_text, type: $type, description: $description,
                aliases: $aliases, normalized_aliases: $normalized_aliases,
                blocked_aliases: $blocked_aliases,
                embedding: $embedding, namespace_id: $namespace_id,
                source_paths: $source_paths, source_chunk_indexes: $source_chunk_indexes,
                source_total_chunks: $source_total_chunks,
                created_at: $created_at, updated_at: $updated_at }})""",
            id=entity.id,
            name=entity.name,
            normalized_name=entity.normalized_name,
            search_text=self._search_text(entity.name, entity.aliases),
            type=entity.type,
            description=entity.description or "",
            aliases=list(entity.aliases or []),
            normalized_aliases=list(entity.normalized_aliases or []),
            blocked_aliases=list(entity.blocked_aliases or []),
            embedding=self._emb_param(entity.embedding),
            namespace_id=entity.namespace_id or "default",
            source_paths=source_paths,
            source_chunk_indexes=source_chunks,
            source_total_chunks=source_totals,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
        self._mark_dirty()

    def apply_merge_mutation(self, *, mutation: MergeMutation) -> None:
        source_paths, source_chunks, source_totals = _source_ref_arrays(mutation.source_refs)
        # search_text 는 병합된 aliases 를 반영해 갱신(이름은 병합에서 안 바뀜).
        # 이름을 다시 읽어 name + 새 aliases 로 재구성.
        name_rows = self._fetch(
            f"MATCH (e:{ENTITY_LABEL} {{id: $id}}) RETURN e.name AS name", id=mutation.id
        )
        name = name_rows[0]["name"] if name_rows else ""
        self._exec(
            f"""MATCH (e:{ENTITY_LABEL} {{id: $id}})
                SET e.aliases = $aliases,
                    e.normalized_aliases = $normalized_aliases,
                    e.search_text = $search_text,
                    e.description = $description,
                    e.source_paths = $source_paths,
                    e.source_chunk_indexes = $source_chunk_indexes,
                    e.source_total_chunks = $source_total_chunks,
                    e.updated_at = $updated_at""",
            id=mutation.id,
            aliases=list(mutation.aliases or []),
            normalized_aliases=list(mutation.normalized_aliases or []),
            search_text=self._search_text(name, mutation.aliases),
            description=mutation.description or "",
            source_paths=source_paths,
            source_chunk_indexes=source_chunks,
            source_total_chunks=source_totals,
            updated_at=mutation.updated_at,
        )
        if mutation.blocked_aliases is not None:
            self._exec(
                f"MATCH (e:{ENTITY_LABEL} {{id: $id}}) SET e.blocked_aliases = $blocked",
                id=mutation.id,
                blocked=list(mutation.blocked_aliases),
            )
        self._mark_dirty()

    def upsert_relation(
        self,
        *,
        from_id: str,
        to_id: str,
        rel_type: str,
        source_ref: SourceRef,
    ) -> tuple[str, bool]:
        from ulid import ULID

        new_id = str(ULID())
        now = now_rfc3339()
        rows = self._fetch(
            f"""MATCH (a:{ENTITY_LABEL} {{id: $from_id}}), (b:{ENTITY_LABEL} {{id: $to_id}})
                MERGE (a)-[r:{RELATION_TYPE_LABEL_DEFAULT} {{type: $rel_type}}]->(b)
                ON CREATE SET r.id = $new_id, r.source_paths = [$source_path],
                              r.created_at = $now, r.updated_at = $now,
                              r._just_created = true,
                              r.emitted_in_run_ids = []
                ON MATCH SET r.source_paths =
                                CASE WHEN list_contains(r.source_paths, $source_path)
                                     THEN r.source_paths
                                     ELSE list_append(r.source_paths, $source_path) END,
                             r.updated_at = $now, r._just_created = false
                RETURN r.id AS id, r._just_created AS created""",
            from_id=from_id,
            to_id=to_id,
            rel_type=rel_type,
            new_id=new_id,
            source_path=source_ref.source_path,
            now=now,
        )
        if not rows:
            return "", False
        self._mark_dirty()
        return rows[0]["id"], bool(rows[0]["created"])

    def get_entity_relations(
        self, *, entity_id: str, namespace_id: str = "default"
    ) -> list[Edge]:
        rows = self._fetch(
            f"""MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL})
                WHERE (a.id = $id OR b.id = $id)
                  AND a.namespace_id = $ns AND b.namespace_id = $ns
                RETURN r.id AS rel_id, r.type AS rel_type,
                       r.created_at AS rel_created_at, r.updated_at AS rel_updated_at,
                       r.source_paths AS rel_source_paths,
                       a.id AS from_id, b.id AS to_id""",
            id=entity_id,
            ns=namespace_id,
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
        rows = self._fetch(
            f"""MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $rid}}]->(b:{ENTITY_LABEL})
                RETURN a.id AS from_id, b.id AS to_id, r.type AS type,
                       r.source_paths AS source_paths, r.created_at AS created_at,
                       r.emitted_in_run_ids AS runs""",
            rid=relation_id,
        )
        if not rows:
            return
        rec = rows[0]
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
        existing = self._fetch(
            f"""MATCH (a:{ENTITY_LABEL} {{id: $from_id}})-[r:{RELATION_TYPE_LABEL_DEFAULT} {{type: $type}}]->(b:{ENTITY_LABEL} {{id: $to_id}})
                RETURN r.id AS id, r.source_paths AS source_paths,
                       r.emitted_in_run_ids AS runs""",
            from_id=from_id,
            to_id=to_id,
            type=rec["type"],
        )
        self._exec(
            f"MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $rid}}]->() DELETE r",
            rid=relation_id,
        )
        now = now_rfc3339()
        if existing:
            # 옮긴 자리에 같은 (from, type, to) 관계가 이미 있으면 출처와 회차를 합친다.
            keep = existing[0]
            self._exec(
                f"""MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $rid}}]->()
                    SET r.source_paths = $source_paths,
                        r.emitted_in_run_ids = $runs, r.updated_at = $now""",
                rid=keep["id"],
                source_paths=_union(list(keep["source_paths"] or []), source_paths),
                runs=_union(list(keep["runs"] or []), runs),
                now=now,
            )
        else:
            self._exec(
                f"""MATCH (a:{ENTITY_LABEL} {{id: $from_id}}), (b:{ENTITY_LABEL} {{id: $to_id}})
                    CREATE (a)-[r:{RELATION_TYPE_LABEL_DEFAULT} {{
                        id: $rid, type: $type, source_paths: $source_paths,
                        created_at: $created_at, updated_at: $now,
                        emitted_in_run_ids: $runs, _just_created: false }}]->(b)""",
                from_id=from_id,
                to_id=to_id,
                rid=relation_id,
                type=rec["type"],
                source_paths=source_paths,
                created_at=rec["created_at"],
                now=now,
                runs=runs,
            )
        self._mark_dirty()

    # ---------- IngestionRun + 차분 ----------

    def find_succeeded_run_by_hash(
        self, *, source_path: str, source_hash: str, extractor_version: str
    ) -> IngestionRunRecord | None:
        rows = self._fetch(
            """MATCH (r:IngestionRun)
               WHERE r.source_path = $p AND r.source_hash = $h
                 AND r.extractor_version = $v AND r.status = 'succeeded'
               RETURN r AS r ORDER BY r.completed_at DESC LIMIT 1""",
            p=source_path,
            h=source_hash,
            v=extractor_version,
        )
        return _to_run_record(rows[0]["r"]) if rows else None

    def find_latest_succeeded_run(
        self, *, source_path: str
    ) -> IngestionRunRecord | None:
        rows = self._fetch(
            """MATCH (r:IngestionRun)
               WHERE r.source_path = $p AND r.status = 'succeeded'
               RETURN r AS r ORDER BY r.completed_at DESC LIMIT 1""",
            p=source_path,
        )
        return _to_run_record(rows[0]["r"]) if rows else None

    def create_ingestion_run(
        self,
        *,
        run_id: str,
        source_path: str,
        source_hash: str,
        started_at: str,
        extractor_version: str,
    ) -> None:
        self._exec(
            """CREATE (r:IngestionRun {
                id: $id, source_path: $p, source_hash: $h, extractor_version: $v,
                started_at: $started, status: 'running',
                emitted_entity_ids: [], emitted_relation_ids: [] })""",
            id=run_id,
            p=source_path,
            h=source_hash,
            v=extractor_version,
            started=started_at,
        )

    def mark_entity_emitted(self, *, entity_id: str, run_id: str) -> None:
        self._exec(
            f"""MATCH (e:{ENTITY_LABEL} {{id: $eid}}), (r:IngestionRun {{id: $rid}})
                MERGE (e)-[:EMITTED_IN]->(r)""",
            eid=entity_id,
            rid=run_id,
        )

    def mark_relation_emitted(self, *, relation_id: str, run_id: str) -> None:
        self._exec(
            f"""MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $rid}}]->()
                SET r.emitted_in_run_ids =
                    CASE WHEN list_contains(r.emitted_in_run_ids, $run_id)
                         THEN r.emitted_in_run_ids
                         ELSE list_append(r.emitted_in_run_ids, $run_id) END""",
            rid=relation_id,
            run_id=run_id,
        )

    def finalize_run(
        self,
        *,
        run_id: str,
        status: str,
        completed_at: str,
        emitted_entity_ids: list[str],
        emitted_relation_ids: list[str],
    ) -> None:
        self._exec(
            """MATCH (r:IngestionRun {id: $id})
               SET r.status = $status, r.completed_at = $completed,
                   r.emitted_entity_ids = $eids, r.emitted_relation_ids = $rids""",
            id=run_id,
            status=status,
            completed=completed_at,
            eids=list(emitted_entity_ids),
            rids=list(emitted_relation_ids),
        )

    def append_emitted_relations(
        self, *, run_id: str, relation_ids: list[str]
    ) -> None:
        if not relation_ids:
            return
        rows = self._fetch(
            "MATCH (r:IngestionRun {id: $id}) RETURN r.emitted_relation_ids AS ids",
            id=run_id,
        )
        if not rows:
            return
        merged = list(rows[0]["ids"] or [])
        for rid in relation_ids:
            if rid not in merged:
                merged.append(rid)
        self._exec(
            "MATCH (r:IngestionRun {id: $id}) SET r.emitted_relation_ids = $ids",
            id=run_id,
            ids=merged,
        )

    def apply_entity_diff(
        self, *, entity_id: str, source_path: str, run_id: str
    ) -> str:
        rows = self._fetch(
            f"""MATCH (e:{ENTITY_LABEL} {{id: $id}})
                RETURN e.source_paths AS paths, e.source_chunk_indexes AS chunks,
                       e.source_total_chunks AS totals""",
            id=entity_id,
        )
        if not rows:
            return "missing"
        paths = list(rows[0]["paths"] or [])
        chunks = list(rows[0]["chunks"] or [])
        totals = list(rows[0]["totals"] or [])
        distinct_paths = set(paths)
        if not distinct_paths or distinct_paths == {source_path}:
            self._exec(
                f"MATCH (e:{ENTITY_LABEL} {{id: $id}}) DETACH DELETE e", id=entity_id
            )
            self._mark_dirty()
            return "deleted"
        new_paths: list[str] = []
        new_chunks: list[int] = []
        new_totals: list[int] = []
        for i, p in enumerate(paths):
            if p == source_path:
                continue
            new_paths.append(p)
            new_chunks.append(chunks[i] if i < len(chunks) else -1)
            new_totals.append(totals[i] if i < len(totals) else -1)
        self._exec(
            f"""MATCH (e:{ENTITY_LABEL} {{id: $id}})
                SET e.source_paths = $paths, e.source_chunk_indexes = $chunks,
                    e.source_total_chunks = $totals""",
            id=entity_id,
            paths=new_paths,
            chunks=new_chunks,
            totals=new_totals,
        )
        return "trimmed"

    def apply_relation_diff(self, *, relation_id: str, source_path: str) -> str:
        rows = self._fetch(
            f"""MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $id}}]->()
                RETURN r.source_paths AS paths""",
            id=relation_id,
        )
        if not rows:
            return "missing"
        paths = list(rows[0]["paths"] or [])
        distinct_paths = set(paths)
        if not distinct_paths or distinct_paths == {source_path}:
            self._exec(
                f"MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $id}}]->() DELETE r",
                id=relation_id,
            )
            self._mark_dirty()
            return "deleted"
        new_paths = [p for p in paths if p != source_path]
        self._exec(
            f"""MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT} {{id: $id}}]->()
                SET r.source_paths = $paths""",
            id=relation_id,
            paths=new_paths,
        )
        return "trimmed"

    # ---------- Read ----------

    def get_schema_summary(
        self, *, examples_per_type: int = 5, namespace_id: str = "default"
    ) -> tuple[list[EntityTypeStat], list[RelationTypeStat]]:
        entity_stats: list[EntityTypeStat] = []
        relation_stats: list[RelationTypeStat] = []
        type_rows = self._fetch(
            f"""MATCH (n:{ENTITY_LABEL}) WHERE n.namespace_id = $ns
                RETURN n.type AS type, count(*) AS count ORDER BY type""",
            ns=namespace_id,
        )
        for row in type_rows:
            examples = self._fetch(
                f"""MATCH (n:{ENTITY_LABEL}) WHERE n.type = $t AND n.namespace_id = $ns
                    RETURN n.id AS id, n.name AS name ORDER BY n.updated_at DESC LIMIT $k""",
                t=row["type"],
                ns=namespace_id,
                k=examples_per_type,
            )
            entity_stats.append(
                EntityTypeStat(
                    type=row["type"],
                    count=int(row["count"]),
                    examples=[(e["id"], e["name"]) for e in examples],
                )
            )
        rel_rows = self._fetch(
            f"""MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL})
                WHERE a.namespace_id = $ns AND b.namespace_id = $ns
                RETURN r.type AS type, count(*) AS count ORDER BY type""",
            ns=namespace_id,
        )
        for row in rel_rows:
            pairs = self._fetch(
                f"""MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL})
                    WHERE r.type = $t AND a.namespace_id = $ns AND b.namespace_id = $ns
                    RETURN a.type AS from_type, b.type AS to_type, count(*) AS c
                    ORDER BY c DESC LIMIT 5""",
                t=row["type"],
                ns=namespace_id,
            )
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
        rows = self._fetch(
            f"""MATCH (n:{ENTITY_LABEL} {{id: $id}}) WHERE n.namespace_id = $ns
                RETURN n.id AS id""",
            id=entity_id,
            ns=namespace_id,
        )
        return bool(rows)

    def count_entities_by_namespace(self) -> dict[str, int]:
        rows = self._fetch(
            f"""MATCH (e:{ENTITY_LABEL})
                RETURN e.namespace_id AS ns, count(*) AS c ORDER BY c DESC"""
        )
        return {r["ns"]: int(r["c"]) for r in rows}

    def _relation_degrees(self, namespace_id: str) -> dict[str, int]:
        rows = self._fetch(
            f"""MATCH (a:{ENTITY_LABEL})-[:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL})
                WHERE a.namespace_id = $ns AND b.namespace_id = $ns
                RETURN a.id AS from_id, b.id AS to_id""",
            ns=namespace_id,
        )
        degree: dict[str, int] = {}
        for row in rows:
            degree[row["from_id"]] = degree.get(row["from_id"], 0) + 1
            degree[row["to_id"]] = degree.get(row["to_id"], 0) + 1
        return degree

    def iter_entity_surfaces(self, *, namespace_id: str = "default") -> list[EntitySurface]:
        rows = self._fetch(
            f"""MATCH (e:{ENTITY_LABEL}) WHERE e.namespace_id = $ns
                RETURN e.id AS id, e.name AS name, e.type AS type,
                       e.normalized_name AS normalized_name, e.aliases AS aliases
                ORDER BY e.id""",
            ns=namespace_id,
        )
        degree = self._relation_degrees(namespace_id)
        return [
            EntitySurface(
                id=r["id"],
                name=r["name"] or "",
                type=r["type"] or "",
                normalized_name=r["normalized_name"] or "",
                aliases=list(r["aliases"] or []),
                relation_count=degree.get(r["id"], 0),
            )
            for r in rows
        ]

    def list_entities(
        self,
        *,
        namespace_id: str = "default",
        types: list[str] | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[int, list[StoredEntity]]:
        where = "e.namespace_id = $ns" + (" AND list_contains($types, e.type)" if types else "")
        params: dict[str, Any] = {"ns": namespace_id}
        if types:
            params["types"] = list(types)
        total_rows = self._fetch(
            f"MATCH (e:{ENTITY_LABEL}) WHERE {where} RETURN count(*) AS c", **params
        )
        rows = self._fetch(
            f"""MATCH (e:{ENTITY_LABEL}) WHERE {where}
                RETURN e AS e ORDER BY e.id SKIP $skip LIMIT $take""",
            skip=offset,
            take=limit,
            **params,
        )
        return int(total_rows[0]["c"]), [_node_to_stored(r["e"]) for r in rows]

    def get_stored_entity(self, *, entity_id: str) -> StoredEntity | None:
        rows = self._fetch(
            f"MATCH (e:{ENTITY_LABEL} {{id: $id}}) RETURN e AS e", id=entity_id
        )
        return _node_to_stored(rows[0]["e"]) if rows else None

    def get_entity_with_counts(
        self, *, entity_id: str, namespace_id: str = "default"
    ) -> EntityWithCounts | None:
        node_rows = self._fetch(
            f"""MATCH (n:{ENTITY_LABEL} {{id: $id}}) WHERE n.namespace_id = $ns
                RETURN n AS n""",
            id=entity_id,
            ns=namespace_id,
        )
        if not node_rows:
            return None
        node = _node_to_response(node_rows[0]["n"])
        out_rows = self._fetch(
            f"""MATCH (n:{ENTITY_LABEL} {{id: $id}})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(m:{ENTITY_LABEL})
                WHERE m.namespace_id = $ns
                RETURN r.type AS type, count(*) AS c""",
            id=entity_id,
            ns=namespace_id,
        )
        in_rows = self._fetch(
            f"""MATCH (n:{ENTITY_LABEL} {{id: $id}})<-[r:{RELATION_TYPE_LABEL_DEFAULT}]-(m:{ENTITY_LABEL})
                WHERE m.namespace_id = $ns
                RETURN r.type AS type, count(*) AS c""",
            id=entity_id,
            ns=namespace_id,
        )
        outgoing = {r["type"]: int(r["c"]) for r in out_rows}
        incoming = {r["type"]: int(r["c"]) for r in in_rows}
        return EntityWithCounts(node=node, outgoing=outgoing, incoming=incoming)

    # ---------- BFS 이웃/서브그래프 ----------

    def _degree_by_ids(self, ids: list[str]) -> dict[str, int]:
        if not ids:
            return {}
        rows = self._fetch(
            f"""MATCH (m:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]-()
                WHERE list_contains($ids, m.id)
                RETURN m.id AS id, count(r) AS deg""",
            ids=list(ids),
        )
        return {r["id"]: int(r["deg"]) for r in rows}

    def _expand_hop(
        self,
        *,
        frontier: list[str],
        direction: str,
        relation_types: list[str] | None,
        namespace_id: str,
    ) -> list[dict[str, Any]]:
        """frontier 한 홉 확장. graph.py 의 컬럼 계약과 같은 dict 리스트 반환."""
        rel_filter = ""
        params: dict[str, Any] = {"frontier": list(frontier), "ns": namespace_id}
        if relation_types:
            rel_filter = " AND list_contains($rtypes, r.type)"
            params["rtypes"] = list(relation_types)
        rel_ret = (
            "r.id AS rel_id, r.type AS rel_type, r.created_at AS rel_created_at, "
            "r.updated_at AS rel_updated_at, r.source_paths AS rel_source_paths"
        )
        rows: list[dict[str, Any]] = []
        if direction in ("outgoing", "both"):
            rows += self._fetch(
                f"""MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL})
                    WHERE list_contains($frontier, a.id) AND b.namespace_id = $ns{rel_filter}
                    RETURN a.id AS a_id, b.id AS b_id, b AS other, {rel_ret}""",
                **params,
            )
        if direction in ("incoming", "both"):
            rows += self._fetch(
                f"""MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL})
                    WHERE list_contains($frontier, b.id) AND a.namespace_id = $ns{rel_filter}
                    RETURN a.id AS a_id, b.id AS b_id, a AS other, {rel_ret}""",
                **params,
            )
        # 확장 대상(other)의 degree 를 붙여 hub 인지 절단(ADR-0017)에 쓴다.
        other_ids = [r["other"]["id"] for r in rows]
        deg = self._degree_by_ids(other_ids)
        for r in rows:
            r["other_degree"] = deg.get(r["other"]["id"], 0)
        return rows

    def _bfs(
        self,
        *,
        seed_ids: list[str],
        direction: str,
        relation_types: list[str] | None,
        hops: int,
        max_nodes: int,
        namespace_id: str,
    ) -> NeighborhoodResult:
        visited_nodes: dict[str, Node] = {}
        boundary_edges: dict[str, Edge] = {}
        # 진입점 노드들 (namespace 안만).
        seed_rows = self._fetch(
            f"""MATCH (n:{ENTITY_LABEL}) WHERE list_contains($ids, n.id) AND n.namespace_id = $ns
                RETURN n AS n""",
            ids=list(seed_ids),
            ns=namespace_id,
        )
        for r in seed_rows:
            node = _node_to_response(r["n"])
            visited_nodes[node.id] = node
        frontier_ids = list(visited_nodes.keys())
        truncated = False
        for _hop in range(hops):
            if not frontier_ids:
                break
            rows = self._expand_hop(
                frontier=frontier_ids,
                direction=direction,
                relation_types=relation_types,
                namespace_id=namespace_id,
            )
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
                other = r["other"]
                other_id = other["id"]
                if other_id in visited_nodes:
                    if edge.id not in boundary_edges:
                        boundary_edges[edge.id] = edge
                    continue
                if len(visited_nodes) >= max_nodes:
                    truncated = True
                    continue
                if edge.id not in boundary_edges:
                    boundary_edges[edge.id] = edge
                visited_nodes[other_id] = _node_to_response(other)
                next_frontier.append(other_id)
            if truncated:
                break
            frontier_ids = next_frontier
        edges = [
            e for e in boundary_edges.values()
            if e.from_ in visited_nodes and e.to in visited_nodes
        ]
        return NeighborhoodResult(
            nodes=list(visited_nodes.values()), edges=edges, truncated=truncated
        )

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
        return self._bfs(
            seed_ids=[entry_id],
            direction=direction,
            relation_types=relation_types,
            hops=hops,
            max_nodes=max_nodes,
            namespace_id=namespace_id,
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
        return self._bfs(
            seed_ids=list(entry_ids),
            direction="both",
            relation_types=relation_types,
            hops=hops,
            max_nodes=max_nodes,
            namespace_id=namespace_id,
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
        fetch_limit = min(50, max(max_paths * 5, 10))
        rows = self._fetch(
            f"""MATCH p = (a:{ENTITY_LABEL} {{id: $from_id}})
                    -[r:{RELATION_TYPE_LABEL_DEFAULT}* ALL SHORTEST 1..{int(max_hops)}]-
                    (b:{ENTITY_LABEL} {{id: $to_id}})
                WHERE a.namespace_id = $ns AND b.namespace_id = $ns
                RETURN nodes(p) AS nodes, rels(p) AS rels, length(p) AS length
                ORDER BY length ASC LIMIT $lim""",
            from_id=from_id,
            to_id=to_id,
            ns=namespace_id,
            lim=fetch_limit,
        )
        # namespace / relation_types 필터는 Python 에서 (Kuzu list-predicate 회피).
        filtered: list[dict[str, Any]] = []
        for row in rows:
            nodes = list(row["nodes"])
            rels = list(row["rels"])
            if any(n.get("namespace_id", "default") != namespace_id for n in nodes):
                continue
            rel_types = [rl.get("type") for rl in rels]
            if relation_types and not all(t in relation_types for t in rel_types):
                continue
            filtered.append({"nodes": nodes, "rels": rels, "length": int(row["length"])})

        endpoints = {from_id, to_id}
        intermediate_ids = {
            n["id"] for row in filtered for n in row["nodes"] if n["id"] not in endpoints
        }
        degree_by_id = self._degree_by_ids(list(intermediate_ids))

        paths: list[PathResult] = []
        for row in filtered:
            node_objs = [_node_to_response(n) for n in row["nodes"]]
            edges: list[Edge] = []
            for i, rel in enumerate(row["rels"]):
                edges.append(
                    _record_to_edge(
                        rel_id=rel.get("id"),
                        rel_type=rel.get("type"),
                        rel_created_at=rel.get("created_at"),
                        rel_updated_at=rel.get("updated_at"),
                        rel_source_paths=rel.get("source_paths"),
                        from_id=node_objs[i].id,
                        to_id=node_objs[i + 1].id,
                    )
                )
            hub_score = sum(
                math.log1p(degree_by_id.get(n.id, 0)) for n in node_objs[1:-1]
            )
            paths.append(
                PathResult(
                    nodes=node_objs,
                    edges=edges,
                    length=row["length"],
                    hub_score=hub_score,
                )
            )
        paths.sort(key=lambda p: (p.length, p.hub_score))
        return paths[:max_paths]
