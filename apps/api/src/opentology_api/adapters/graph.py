"""그래프 저장소 어댑터 — Neo4j 5.15+ 내장 인덱스 사용 (ADR-0004 D1).

핵심 책임:
- ensure_indexes() — 부팅 시 idempotent 하게 인덱스 + 백필 보장
- create_entity() / apply_merge_mutation() — 4 단계 동일성 (PRD 2 §5.1) 흐름의
  *write* 분기 두 가지. 결정은 도메인 (`EntityMatcher` + `EntityMerger`) 이,
  적용은 어댑터가.
- find_by_normalized_name() — Step 1·2 의 정규화 키 lookup.
- vector_search() — Step 3 의 임베딩 ANN 후보 반환.
- upsert_relation() — (from_id, type, to_id) 3-튜플 유일성 (PRD 2 §5.5).
- IngestionRun CRUD + diff 적용 — PRD 2 §5.4 의 차분 알고리즘.
- find_by_keywords_scored() — fulltext 인덱스로 진입점 검색 (lexical-only),
  keyword 별 raw 점수 동봉 (PRD 3 §3.4 의 matched_keyword + score 산출용)
- find_entities_dense() — *stub* . 하이브리드는 #6 의 후속.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase

from ..config import Settings
from ..domain.errors import DependencyUnavailableError
from ..domain.models import (
    MergeMutation,
    Node,
    SourceRef,
    StoredEntity,
    now_rfc3339,
)


@dataclass(frozen=True)
class IngestionRunRecord:
    """`(:IngestionRun)` 노드의 슬림 표현 — 차분 알고리즘이 다루는 필드만.

    `emitted_entity_ids` 는 *해당 회차가 손댄* (created or merged) 엔티티 id
    의 집합. relation 은 별도 컬렉션 (`emitted_relation_ids`) 으로 분리 — 두
    set 의 사용 시점이 다르고 Neo4j 가 array 를 native 로 다루므로 단일 배열
    두 개가 가장 단순.
    """

    id: str
    source_path: str
    source_hash: str
    started_at: str
    completed_at: str | None
    status: str  # "running" | "succeeded" | "failed"
    emitted_entity_ids: list[str]
    emitted_relation_ids: list[str]


@dataclass(frozen=True)
class KeywordHit:
    """단일 keyword 의 fulltext 매치 한 건.

    WHY dataclass: 라우터 레이어가 keyword 별 raw Lucene 점수 + 어느 keyword
    가 surface 시켰는지 두 정보를 모두 받아 PRD 3 §3.4 의 matched_keyword 와
    score 를 도출한다 (§3.5: 같은 노드가 여러 keyword 에서 surface 됐다면
    가장 높은 점수의 keyword 유지). 어댑터는 *데이터* 만 책임지고 fusion 은
    상위 레이어가 책임.
    """

    node: Node
    raw_score: float
    matched_keyword: str


logger = logging.getLogger(__name__)


# WHY 인덱스 이름 고정: ADR-0006 D6 — Neo4j MCP 와 *같은 DB 에 공존* 가능해야
# 한다. Opentology 가 만드는 인덱스는 prefix 없이 의도가 드러나는 이름으로
# 둔다 (MCP 가 인덱스 충돌을 일으키지 않는 한 prefix 는 over-engineering).
FULLTEXT_INDEX = "entity_name_idx"
VECTOR_INDEX = "entity_embedding_idx"
NORMALIZED_NAME_INDEX = "entity_normalized_name_idx"
INGESTION_RUN_LABEL = "IngestionRun"
INGESTION_RUN_SOURCE_INDEX = "ingestion_run_source_idx"
ENTITY_LABEL = "Entity"
RELATION_TYPE_LABEL_DEFAULT = "RELATES_TO"  # 폴백 — 추출 시 type 이 비면
EMITTED_IN = "EMITTED_IN"


class GraphRepository(ABC):
    @abstractmethod
    def ensure_indexes(self) -> None: ...

    @abstractmethod
    def healthcheck(self) -> bool: ...

    # ----- 4 단계 동일성 + 병합/생성 -----

    @abstractmethod
    def find_by_normalized_name(
        self, *, normalized: str, type_: str
    ) -> StoredEntity | None:
        """`normalized_name == normalized AND type == type_` 정확 일치."""

    @abstractmethod
    def vector_search(
        self, *, embedding: list[float], top_k: int, type_: str
    ) -> list[StoredEntity]:
        """ANN top-k 후보를 *embedding 포함* 으로 반환. cosine 재계산은 도메인.

        type 필터는 ANN 사전 필터가 가능하면 사전, 안 되면 사후 필터로 적용.
        """

    @abstractmethod
    def create_entity(self, *, entity: StoredEntity) -> None:
        """새 엔티티 노드 생성. id 는 호출자가 생성 (ULID)."""

    @abstractmethod
    def apply_merge_mutation(self, *, mutation: MergeMutation) -> None:
        """`EntityMerger` 결과를 한 트랜잭션으로 set. embedding/normalized_name 은 변경 없음."""

    # ----- 관계 -----

    @abstractmethod
    def upsert_relation(
        self,
        *,
        from_id: str,
        to_id: str,
        rel_type: str,
        source_ref: SourceRef,
    ) -> tuple[str, bool]: ...

    # ----- IngestionRun + 차분 -----

    @abstractmethod
    def find_succeeded_run_by_hash(
        self, *, source_path: str, source_hash: str
    ) -> IngestionRunRecord | None:
        """같은 (path, hash) 의 성공 run 이 이미 있는지 — short-circuit 판정."""

    @abstractmethod
    def find_latest_succeeded_run(
        self, *, source_path: str
    ) -> IngestionRunRecord | None:
        """동일 source_path 의 가장 최근 성공 run — 차분 비교의 기준."""

    @abstractmethod
    def create_ingestion_run(
        self, *, run_id: str, source_path: str, source_hash: str, started_at: str
    ) -> None:
        """status='running' 으로 새 회차 노드 생성."""

    @abstractmethod
    def mark_entity_emitted(self, *, entity_id: str, run_id: str) -> None:
        """`(:Entity)-[:EMITTED_IN]->(:IngestionRun)` 보장 (MERGE)."""

    @abstractmethod
    def mark_relation_emitted(self, *, relation_id: str, run_id: str) -> None:
        """relation 의 `emitted_in_run_ids` 배열에 run_id 추가 (dedupe)."""

    @abstractmethod
    def finalize_run(
        self,
        *,
        run_id: str,
        status: str,
        completed_at: str,
        emitted_entity_ids: list[str],
        emitted_relation_ids: list[str],
    ) -> None:
        """run 의 종결 — status + completed_at + 이번에 손댄 id 목록 기록."""

    @abstractmethod
    def apply_entity_diff(
        self, *, entity_id: str, source_path: str, run_id: str
    ) -> str:
        """이전 회차의 emitted entity 중 이번 회차가 touch 하지 않은 것 처리.

        반환값 — "deleted" 또는 "trimmed". 동작:
        - 노드의 source_paths 가 *오직 source_path 만* 포함 → 노드 + 인접 관계 삭제.
        - 그 외 → source_paths/source_chunk_indexes 에서 source_path 해당 항목 제거.
        호출자는 이전 run 의 entity_ids 와 새 run 의 entity_ids 의 set difference 만 넘긴다.
        """

    @abstractmethod
    def apply_relation_diff(
        self, *, relation_id: str, source_path: str
    ) -> str:
        """이전 회차의 emitted relation 중 이번 회차가 touch 하지 않은 것 처리.

        반환값 — "deleted" 또는 "trimmed".
        """

    # ----- 검색 (#6 와 무관, 본 PR 에서는 PR #16 코드 그대로 보존) -----

    @abstractmethod
    def find_by_keywords_scored(
        self, *, keywords: list[str], limit_per_keyword: int
    ) -> list[KeywordHit]:
        """각 keyword 별로 fulltext 매칭 결과를 반환 (raw Lucene 점수 포함).

        같은 노드가 여러 keyword 에서 매칭될 수 있으므로 union/dedup 은 호출자
        책임 (PRD 3 §3.5).
        """

    @abstractmethod
    def find_entities_dense(
        self, *, keywords: list[str], limit: int
    ) -> list[Node]: ...

    @abstractmethod
    def close(self) -> None: ...


class Neo4jGraphRepository(GraphRepository):
    """Neo4j 5.15+ 어댑터.

    WHY driver 1 개 보존: bolt 커넥션 풀은 driver 내부에서 관리된다. 매 요청
    재생성하면 풀이 의미 없어지고 latency 가 늘어난다.
    """

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

        인덱스 구성:
        - fulltext (name + aliases): find_by_keywords_scored 의 lexical 신호.
        - vector (embedding): 4 단계 동일성 Step 3 의 ANN 후보 풀.
        - btree on name: 인간이 직접 조회할 때 빠른 lookup (관찰가능성).
        - btree on `normalized_name`: 4 단계 동일성 Step 1·2 의 정확 일치 lookup.
        - btree on `IngestionRun.source_path`: 차분 알고리즘의 "직전 성공 run"
          조회.

        백필: 본 함수는 PR #16 의 기존 노드 (즉 `normalized_name` 이 비어있는
        엔티티) 를 idempotent 하게 채운다 — 두 번 호출되어도 두 번째는 no-op.
        백필 자체는 단순 SET 이므로 트랜잭션 한 건이면 충분 (코퍼스가 작은
        MVP 가정).
        """
        dim = self._settings.embedding_dimension
        with self._driver.session() as s:
            s.run(
                f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX} IF NOT EXISTS "
                f"FOR (e:{ENTITY_LABEL}) ON EACH [e.name, e.aliases]"
            ).consume()
            # Neo4j 5.15+ 표준 vector index 구문.
            # WHY 인라인 dim: OPTIONS 의 indexConfig 는 parameter 바인딩을
            # 받지 않으므로 (Cypher 가 리터럴만 허용) 정수를 직접 삽입한다.
            # dim 은 Settings 에서 온 신뢰 가능 값.
            # WHY 백틱 키: Neo4j 5.15 의 Cypher 파서는 map literal 안에서 점이
            # 포함된 key 를 *backtick* 으로 감싸야 받아들인다 (single-quoted
            # string 키는 SyntaxError). 즉 `\`vector.dimensions\`: 1536` 형태.
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
            # 백필 — normalize 결과를 직접 계산해 Cypher 에 박는다.
            # WHY 두 단계 (조회 → 업데이트): Neo4j Cypher 에는 Python 함수가
            # 없어 normalize 를 server-side 로 실행할 수 없다. 노드 리스트를
            # 받아 클라이언트에서 normalize 한 뒤 한 transaction 에 batch SET.
            self._backfill_normalized_names(s)

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
        self, *, normalized: str, type_: str
    ) -> StoredEntity | None:
        """정규화 키 lookup — 노드의 정규명 OR 정규화된 alias 중 한 곳이라도 hit.

        WHY OR alias 까지: PRD 2 §5.1 Step 1 의 매칭은 *새 엔티티의 이름* 이
        그래프의 *기존 엔티티의 정규명 또는 정규화된 alias* 와 일치해도 같은
        엔티티로 본다. 두 경우를 한 인덱스 쿼리로 처리해 매처를 단순화.
        """
        with self._driver.session() as s:
            rec = s.run(
                f"MATCH (e:{ENTITY_LABEL}) "
                "WHERE e.type = $t "
                "  AND (e.normalized_name = $n "
                "       OR $n IN coalesce(e.normalized_aliases, [])) "
                "RETURN e LIMIT 1",
                n=normalized,
                t=type_,
            ).single()
        if rec is None:
            return None
        return _node_to_stored(rec["e"])

    def vector_search(
        self, *, embedding: list[float], top_k: int, type_: str
    ) -> list[StoredEntity]:
        """ANN top-k 후보. type 사후 필터.

        WHY 사후 필터: Neo4j 5.15 의 `db.index.vector.queryNodes` 는 라벨/속성
        사전 필터를 직접 받지 않는다 (필터는 별도 MATCH WHERE 단계). 정확도를
        위해 후보 풀을 *top_k * 4* 로 확보한 뒤 type 으로 줄인다. 코퍼스가
        작은 MVP 가정에서 비용 차이는 무시 가능.
        """
        if not embedding:
            return []
        oversample = max(top_k * 4, top_k)
        with self._driver.session() as s:
            rows = s.run(
                "CALL db.index.vector.queryNodes($idx, $k, $vec) "
                "YIELD node, score "
                "WITH node, score "
                f"WHERE node:{ENTITY_LABEL} AND node.type = $t "
                "RETURN node ORDER BY score DESC LIMIT $limit",
                parameters={
                    "idx": VECTOR_INDEX,
                    "k": oversample,
                    "vec": embedding,
                    "t": type_,
                    "limit": top_k,
                },
            ).data()
        return [_node_to_stored(r["node"]) for r in rows]

    def create_entity(self, *, entity: StoredEntity) -> None:
        """새 엔티티 — `normalized_name` 포함. id 충돌 시 IntegrityError 가 정상.

        WHY chunk_index sentinel: Neo4j 의 list 속성은 null 원소를 허용하지
        않는다. PR #16 부터 사용 중인 -1 sentinel 을 그대로 보존 — 응답 직렬화
        는 -1 → None 으로 복원.
        """
        source_chunks = [
            sr.chunk_index if sr.chunk_index is not None else -1
            for sr in entity.source_refs
        ]
        # WHY total_chunks 도 동일 sentinel: chunk_index 와 같이 -1 → None 복원.
        # 분할 안 된 파일은 둘 다 None 으로 들어와 양쪽 모두 -1 로 저장된다.
        source_totals = [
            sr.total_chunks if sr.total_chunks is not None else -1
            for sr in entity.source_refs
        ]
        with self._driver.session() as s:
            s.run(
                f"""
                CREATE (e:{ENTITY_LABEL} {{
                    id: $id, name: $name, normalized_name: $normalized_name,
                    normalized_aliases: $normalized_aliases,
                    type: $type, aliases: $aliases, description: $description,
                    embedding: $embedding,
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
                type=entity.type,
                aliases=entity.aliases,
                description=entity.description or "",
                embedding=entity.embedding,
                source_paths=[sr.source_path for sr in entity.source_refs],
                source_chunk_indexes=source_chunks,
                source_total_chunks=source_totals,
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            ).consume()

    def apply_merge_mutation(self, *, mutation: MergeMutation) -> None:
        """병합 — aliases/description/source_refs/updated_at 만 갱신.

        WHY source_refs 를 *기존 + 새 ref 합집합* 전체 교체로 set: domain
        EntityMerger 가 이미 dedupe 한 최종 리스트를 만들어 준다. 어댑터가
        다시 dedup 시도하면 두 자리에 dedupe 로직이 살아 fragile 해진다.
        """
        source_chunks = [
            sr.chunk_index if sr.chunk_index is not None else -1
            for sr in mutation.source_refs
        ]
        source_totals = [
            sr.total_chunks if sr.total_chunks is not None else -1
            for sr in mutation.source_refs
        ]
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
                source_paths=[sr.source_path for sr in mutation.source_refs],
                source_chunk_indexes=source_chunks,
                source_total_chunks=source_totals,
                updated_at=mutation.updated_at,
            ).consume()

    def upsert_relation(
        self,
        *,
        from_id: str,
        to_id: str,
        rel_type: str,
        source_ref: SourceRef,
    ) -> tuple[str, bool]:
        """3-튜플 유일성 (PRD 2 §5.5) — MERGE on (from_id, type, to_id).

        WHY 동적 라벨이 아닌 단일 RELATES_TO 라벨 + type 속성: Cypher 의 관계
        라벨은 파라미터화 불가하고, 라벨이 폭발하면 인덱스 관리가 복잡해진다.
        walking skeleton 은 단일 라벨에 type 속성으로 시작. post-MVP 에서 라벨
        승격은 측정 후 결정.
        """
        from ulid import ULID

        new_id = str(ULID())
        now = now_rfc3339()
        # WHY 별도 created_flag: created_at 가 second precision 이라 두 호출이 같은
        # 초에 일어나면 r.created_at == $now 가 두 분기 모두에서 True. 결정적인
        # created 신호는 *MERGE 결과* 자체에서 받아야 한다. 여기서는 별도 dummy
        # property 를 SetOnCreate 로 박아 그 존재를 확인.
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

    # ---------- IngestionRun + 차분 ----------

    def find_succeeded_run_by_hash(
        self, *, source_path: str, source_hash: str
    ) -> IngestionRunRecord | None:
        with self._driver.session() as s:
            rec = s.run(
                f"MATCH (r:{INGESTION_RUN_LABEL}) "
                "WHERE r.source_path = $p AND r.source_hash = $h "
                "  AND r.status = 'succeeded' "
                "RETURN r ORDER BY r.completed_at DESC LIMIT 1",
                p=source_path,
                h=source_hash,
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
    ) -> None:
        with self._driver.session() as s:
            s.run(
                f"""
                CREATE (r:{INGESTION_RUN_LABEL} {{
                    id: $id, source_path: $p, source_hash: $h,
                    started_at: $started, status: 'running',
                    emitted_entity_ids: [], emitted_relation_ids: []
                }})
                """,
                id=run_id,
                p=source_path,
                h=source_hash,
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
        # WHY relation 은 edge property 로: Neo4j 의 property graph 모델은 edge
        # 에 edge 를 달 수 없다. 대안으로 relation 의 array property 에 run_id
        # 를 append (dedupe).
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

    def apply_entity_diff(
        self, *, entity_id: str, source_path: str, run_id: str
    ) -> str:
        """이번 회차가 손대지 않은 이전 emitted entity 처리.

        - 노드의 source_paths 가 *오직 source_path 만* 들어있으면 노드 + 인접
          관계 모두 삭제 (DETACH DELETE).
        - 그 외는 해당 source_path 항목을 source_paths/source_chunk_indexes 의
          *동일 인덱스* 에서 한 번에 제거. EMITTED_IN 의 *이번 회차가 아닌*
          이전 회차 엣지는 그대로 둔다 — 회차 히스토리는 다른 회차의 추적에도
          쓰이므로 일괄 삭제는 위험.
        """
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
            # WHY 세 array 동시 trim: 세 배열이 동일 인덱스 단위로 이어 있어야
            # `_extract_source_refs` 가 올바른 (path, chunk_index, total_chunks)
            # 묶음을 복원할 수 있다. 한 array 만 trim 하면 인덱스가 어긋난다.
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
        self, *, keywords: list[str], limit_per_keyword: int
    ) -> list[KeywordHit]:
        """fulltext 인덱스를 *keyword 별로* 따로 호출.

        WHY keyword 별 분리: PRD 3 §3.4 의 `matched_keyword` 는 *어느 input
        keyword 가 이 노드를 surface 시켰는지* 를 정확히 보고해야 한다. 모든
        keyword 를 하나의 OR 쿼리로 보내면 점수는 받지만 어느 항이 매칭됐는지
        파서가 알려주지 않는다. keyword 단위로 호출하고 결과에 keyword 를
        태깅한 뒤, 상위 레이어가 노드 ID 로 union 하면서 점수 max 유지하는
        구조로 둔다.

        WHY 어댑터는 raw 점수만: 0..1 정규화 (PRD 3 §3.4) 는 *전체 결과 집합*
        을 봐야 하므로 (예: max-normalize) 라우터에서 수행. 어댑터는 단일
        Lucene/BM25 의 raw 점수만 책임.

        성능 노트: keyword 수만큼 query 가 늘어남. walking skeleton 단계 비용
        은 무시 가능. #6 의 dense + RRF 도입 시 fusion 단계에서 함께 재검토.
        """
        if not keywords:
            return []
        hits: list[KeywordHit] = []
        with self._driver.session() as s:
            for kw in keywords:
                lucene_query = _lucene_escape(kw)
                records = s.run(
                    """
                    CALL db.index.fulltext.queryNodes($idx, $q) YIELD node, score
                    RETURN node, score
                    ORDER BY score DESC
                    LIMIT $limit
                    """,
                    parameters={
                        "idx": FULLTEXT_INDEX,
                        "q": lucene_query,
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
        self, *, keywords: list[str], limit: int
    ) -> list[Node]:
        """dense 매칭 — walking skeleton 에서는 미구현.

        WHY stub: PRD 3 §3.5 + ADR-0003 D1 의 하이브리드는 #6 follow-up. 인터페이스
        와 인덱스 (1536-dim cosine) 는 *지금* 박아 두고, 호출 경로만 막아 둔다.
        """
        raise NotImplementedError(
            "hybrid retrieval pending — lexical + dense fusion is follow-up issue #6"
        )


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
    )


def _node_to_response(node: Any) -> Node:
    """neo4j Node → 응답 Node (embedding 제외)."""
    return Node(
        id=node["id"],
        name=node["name"],
        type=node["type"],
        aliases=list(node.get("aliases") or []),
        description=node.get("description"),
        properties={},
        source_refs=_extract_source_refs(node),
        created_at=node["created_at"],
        updated_at=node["updated_at"],
    )


def _extract_source_refs(node: Any) -> list[SourceRef]:
    paths = list(node.get("source_paths") or [])
    chunks = list(node.get("source_chunk_indexes") or [])
    totals = list(node.get("source_total_chunks") or [])
    refs: list[SourceRef] = []
    for i, p in enumerate(paths):
        ci = chunks[i] if i < len(chunks) else None
        tc = totals[i] if i < len(totals) else None
        # -1 sentinel → None (PRD 3 §1.3 의 nullable chunk_index/total_chunks 복원).
        if ci == -1:
            ci = None
        if tc == -1:
            tc = None
        refs.append(SourceRef(source_path=p, chunk_index=ci, total_chunks=tc))
    return refs


_LUCENE_SPECIAL = '+-&|!(){}[]^"~*?:\\/'


def _lucene_escape(s: str) -> str:
    """Lucene 특수 문자 escape — fulltext 쿼리 안전성.

    WHY: keyword 에 콜론 / 따옴표가 섞이면 fulltext 파서가 깨진다. 모든 특수
    문자를 백슬래시로 escape. 결과는 phrase 매칭이 아니라 token 매칭에 가깝다.
    """
    out: list[str] = []
    for ch in s:
        if ch in _LUCENE_SPECIAL:
            out.append("\\" + ch)
        elif ch.isspace():
            out.append(" ")
        else:
            out.append(ch)
    escaped = "".join(out).strip()
    # 멀티 토큰은 괄호로 묶어 OR 결합과 충돌하지 않게.
    if " " in escaped:
        return f"({escaped})"
    return escaped or "*"
