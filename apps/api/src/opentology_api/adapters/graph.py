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
    Edge,
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


@dataclass(frozen=True)
class DenseHit:
    """단일 query embedding 의 vector ANN 매치 한 건.

    WHY 별도 타입: KeywordHit 와 의미가 다르다. raw_score 는 *cosine similarity*
    (0..1 범위). RRF fusion 에서 rank 만 쓰지만, include_scores=true 일 때 raw
    값을 그대로 노출하므로 lexical 의 BM25 점수와 의미상 분리.
    """

    node: Node
    raw_score: float  # cosine similarity 0..1
    matched_keyword: str


# ---------- get_schema 보조 dataclass ----------


@dataclass(frozen=True)
class StoredChunk:
    """Neo4j (:Chunk) 노드의 어댑터 표현.

    `id` 형식 = `f"{source_path}#{chunk_index}"`. UNIQUE 보장 (PR 3 에서 추가
    한 chunk_id_unique constraint). text 자체를 저장 — 외부 사용자가 `/answer`
    또는 `/retrieve` 호출 시 chunk 본문을 받아야 LLM 컨텍스트로 쓸 수 있다.

    WHY embedding 필드 별도: vector_search 후 cosine 재정렬을 어댑터에서 안 하고
    Neo4j 의 vector index 가 cosine 정렬해 반환. 단 노출 시 메타로 같이 돌려준다.
    """

    id: str
    source_path: str
    chunk_index: int
    total_chunks: int
    text: str
    token_count: int


@dataclass(frozen=True)
class ChunkHit:
    """vector_search_chunks 결과 한 건. score 는 cosine similarity (0..1)."""

    chunk: StoredChunk
    score: float


@dataclass(frozen=True)
class EntityTypeStat:
    type: str
    count: int
    examples: list[tuple[str, str]]  # (id, name)


@dataclass(frozen=True)
class RelationTypeStat:
    type: str
    count: int
    common_pairs: list[tuple[str, str, int]]  # (from_type, to_type, count)


# ---------- get_entity 보조 dataclass ----------


@dataclass(frozen=True)
class EntityWithCounts:
    node: Node
    outgoing: dict[str, int]
    incoming: dict[str, int]


# ---------- neighbors/subgraph 결과 ----------


@dataclass(frozen=True)
class NeighborhoodResult:
    """확장 결과 — 진입점 포함 노드 + 이번 확장 경계 내 엣지.

    truncated 는 max_nodes 초과 여부. 어댑터가 *진입점에서 거리 가까운 순* 으로
    잘랐다는 사실은 신호로만 전달, 거리 정보는 응답에 노출 안 함 (PRD 3 §5.4
    의 스키마와 정합).
    """

    nodes: list[Node]
    edges: list[Edge]
    truncated: bool


# ---------- path 결과 ----------


@dataclass(frozen=True)
class PathResult:
    nodes: list[Node]
    edges: list[Edge]
    length: int


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
# Chunk (PRD 6 §1.1 의 /retrieve + /answer 가 사용하는 chunk store).
# 시제품 backbone spec (docs/superpowers/specs/post-mvp-prototype-backbone.md)
# 의 PR 3 에서 도입. Entity 와 동일한 vector index 패턴을 따라 인프라 단일화.
CHUNK_LABEL = "Chunk"
CHUNK_VECTOR_INDEX = "chunk_embedding_idx"
CHUNK_SOURCE_PATH_INDEX = "chunk_source_path_idx"


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
        self,
        *,
        query_embedding: list[float],
        matched_keyword: str,
        limit: int,
    ) -> list[DenseHit]:
        """단일 query embedding 에 대한 ANN top-k 결과.

        WHY keyword 단위로 호출: PRD 3 §3.4 의 `matched_keyword` 는 어느 input
        keyword 가 노드를 surface 시켰는지 보고해야 한다. 라우터가 keyword 별로
        본 메서드를 부르고 결과에 keyword 를 태깅한다 — fulltext 경로와 구조 동일.

        raw_score = cosine similarity (0..1). Neo4j vector index 의 score 가
        cosine 모드면 그대로 사용.
        """

    # ----- 5 primitive read 보조 (PRD 3 §2-7) -----

    @abstractmethod
    def get_schema_summary(
        self, *, examples_per_type: int = 5
    ) -> tuple[list[EntityTypeStat], list[RelationTypeStat]]:
        """get_schema 의 entity_types + relation_types 통계.

        examples_per_type — 각 엔티티 타입에서 노출할 example 노드 수 (PRD 3 §2.3
        maxItems 5). 결정 (선택 기준) 은 어댑터 내부에 둔다 (id 사전순, 또는 가장
        최근 갱신).
        """

    @abstractmethod
    def get_entity_with_counts(self, *, entity_id: str) -> EntityWithCounts | None:
        """단일 노드 + 인접 엣지의 (방향 × type) 카운트. 없으면 None."""

    @abstractmethod
    def expand_neighbors(
        self,
        *,
        entry_id: str,
        relation_types: list[str] | None,
        direction: str,
        hops: int,
        max_nodes: int,
    ) -> NeighborhoodResult:
        """진입점 1 개의 N-hop 이웃 + 경계 엣지. 진입점 포함.

        잘림 정책: 진입점에서 *거리 가까운 순* (BFS hop level) 정렬 후 max_nodes
        에서 절단. 그래프 DB 의 native 한도가 더 작으면 절단도 자연스럽게 그대로.
        """

    @abstractmethod
    def expand_subgraph(
        self,
        *,
        entry_ids: list[str],
        relation_types: list[str] | None,
        hops: int,
        max_nodes: int,
    ) -> NeighborhoodResult:
        """여러 진입점 N-hop union. 노드/엣지 dedupe.

        잘림 정책: 진입점들 중 *최단 거리* 기준 (multi-source BFS) 가까운 순.
        """

    @abstractmethod
    def find_shortest_paths(
        self,
        *,
        from_id: str,
        to_id: str,
        max_hops: int,
        max_paths: int,
        relation_types: list[str] | None,
    ) -> list[PathResult]:
        """from → to 의 k-shortest paths. 경로 없으면 빈 리스트.

        from/to 의 존재 여부 자체는 호출자가 별도 확인 (entity_not_found 매핑이
        라우터 책임). 본 메서드는 *경로가 없을 때* 와 *노드가 없을 때* 를 둘 다
        빈 리스트로 돌릴 수 있으므로 라우터가 노드 존재 여부를 별도 검증한다.
        """

    @abstractmethod
    def entity_exists(self, *, entity_id: str) -> bool:
        """단일 ID 가 그래프에 존재하는지 — find_path / get_neighbors 의 사전 검증."""

    # ----- Chunk store (PRD 6 §1.1 — /retrieve, /answer 의 의존성) -----

    @abstractmethod
    def upsert_chunks(self, *, chunks: list[StoredChunk], embeddings: list[list[float]]) -> int:
        """(:Chunk) 노드 batch UPSERT.

        `chunks[i]` 와 `embeddings[i]` 는 같은 index. id 기준 MERGE — 같은
        source_path + chunk_index 의 재 ingest 는 text/embedding 을 덮어쓴다.
        반환: UPSERT 된 노드 수.
        """

    @abstractmethod
    def delete_chunks_by_source(self, *, source_path: str) -> int:
        """주어진 source_path 의 모든 (:Chunk) 노드 삭제. 재 ingest 전 청소.

        반환: 삭제된 노드 수.
        """

    @abstractmethod
    def vector_search_chunks(
        self, *, embedding: list[float], top_k: int
    ) -> list[ChunkHit]:
        """질문 embedding 으로 chunk top-k 회수. cosine similarity 정렬.

        WHY top_k 우선: PRD 6 §1.3 의 `chunk_top_k` 노브가 이걸 직접 제어.
        """

    @abstractmethod
    def count_chunks(self) -> int:
        """(:Chunk) 총 개수 — `/healthz` 와 운영 가시성용."""

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
            # UNIQUE constraint — DB-level id 가드 + 자동 인덱스 생성.
            # WHY: walking skeleton 까지 application-level 만 보장이었음 (ULID
            # 충돌 확률 사실상 0). 단 동시 ingest / 버그 / migration 시 graph
            # 부패의 두 번째 가드. 2026-06-20 catastrophic over-merge 같은 *부패
            # 카테고리* 의 DB-level 방어. 자동 인덱스 덕에 id IN $ids 핫패스
            # (expand_subgraph, get_entity, mark_emitted) 도 같이 빨라진다.
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
            # Chunk store — PR 3 (시제품 backbone) 에서 도입.
            # UNIQUE: id = "{source_path}#{chunk_index}". 재 ingest 시 같은 청크
            # 가 덮어써지도록.
            s.run(
                f"CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS "
                f"FOR (c:{CHUNK_LABEL}) REQUIRE c.id IS UNIQUE"
            ).consume()
            # vector index — chunk_top_k retrieval 의 핫패스.
            s.run(
                f"CREATE VECTOR INDEX {CHUNK_VECTOR_INDEX} IF NOT EXISTS "
                f"FOR (c:{CHUNK_LABEL}) ON (c.embedding) "
                f"OPTIONS {{ indexConfig: {{ "
                f"`vector.dimensions`: {int(dim)}, "
                f"`vector.similarity_function`: 'cosine' "
                f"}} }}"
            ).consume()
            # source_path 인덱스 — delete_chunks_by_source 의 핫패스.
            s.run(
                f"CREATE INDEX {CHUNK_SOURCE_PATH_INDEX} IF NOT EXISTS "
                f"FOR (c:{CHUNK_LABEL}) ON (c.source_path)"
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
        self,
        *,
        query_embedding: list[float],
        matched_keyword: str,
        limit: int,
    ) -> list[DenseHit]:
        """단일 keyword 의 dense ANN — PRD 3 §3.5 의 dense path.

        Neo4j 5.15 의 vector index 에서 cosine similarity 모드의 score 는 0..1
        범위로 직접 비교 가능 (정확히는 (1 + cos)/2 가 아니라 cos 자체. Neo4j
        5.15 문서 기준 cosine 모드 score 는 cosine similarity 그대로).

        WHY 별도 한도 검증 없이 limit 그대로: ANN 호출은 빠르고 결과는 어차피
        fusion 단계에서 다시 잘려 나가므로 적당한 후보 풀 (limit) 을 그대로 사용.
        """
        if not query_embedding:
            return []
        with self._driver.session() as s:
            rows = s.run(
                "CALL db.index.vector.queryNodes($idx, $k, $vec) "
                "YIELD node, score "
                f"WHERE node:{ENTITY_LABEL} "
                "RETURN node, score ORDER BY score DESC LIMIT $limit",
                parameters={
                    "idx": VECTOR_INDEX,
                    "k": limit,
                    "vec": query_embedding,
                    "limit": limit,
                },
            ).data()
        return [
            DenseHit(
                node=_node_to_response(r["node"]),
                # WHY clamp [0, 1]: 부동소수 오차로 1.0 을 살짝 넘는 경우 PRD 3
                # §3.4 의 maximum 1 위반. 0 미만은 cosine 정의상 가능 (반대 방향)
                # 이지만 우리 응답 계약은 0..1 이라 동일하게 clamp.
                raw_score=max(0.0, min(1.0, float(r["score"]))),
                matched_keyword=matched_keyword,
            )
            for r in rows
        ]

    # ---------- 5 primitive read (PRD 3 §2-7) ----------

    def get_schema_summary(
        self, *, examples_per_type: int = 5
    ) -> tuple[list[EntityTypeStat], list[RelationTypeStat]]:
        """엔티티/관계 통계 + 타입별 example 노드.

        WHY 한 메서드에 두 통계: get_schema 가 한 번 호출되면 두 통계 모두 필요
        (PRD 3 §2.3). 두 쿼리를 분리하면 라우터에서 다시 묶어야 함 — 어댑터에서
        한 번에 묶어 반환.

        Examples 선택 기준: 각 type 별 가장 최근에 갱신된 노드 5 개 (updated_at
        DESC). WHY: 그래프 운영자가 "지금 살아있는 데이터" 의 모양을 확인하려는
        목적에 가장 가까운 신호.
        """
        entity_stats: list[EntityTypeStat] = []
        relation_stats: list[RelationTypeStat] = []
        with self._driver.session() as s:
            # 엔티티 타입 카운트
            type_rows = s.run(
                f"MATCH (n:{ENTITY_LABEL}) "
                "RETURN n.type AS type, count(*) AS count "
                "ORDER BY type"
            ).data()
            for row in type_rows:
                examples = s.run(
                    f"MATCH (n:{ENTITY_LABEL}) WHERE n.type = $t "
                    "RETURN n.id AS id, n.name AS name "
                    "ORDER BY n.updated_at DESC LIMIT $k",
                    t=row["type"],
                    k=examples_per_type,
                ).data()
                entity_stats.append(
                    EntityTypeStat(
                        type=row["type"],
                        count=int(row["count"]),
                        examples=[(e["id"], e["name"]) for e in examples],
                    )
                )

            # 관계 타입 카운트 — 단일 RELATES_TO 라벨 + type 속성 (graph.py 상단
            # WHY 라벨 단일화 코멘트 참조).
            rel_rows = s.run(
                f"MATCH ()-[r:{RELATION_TYPE_LABEL_DEFAULT}]->() "
                "RETURN r.type AS type, count(*) AS count "
                "ORDER BY type"
            ).data()
            for row in rel_rows:
                pairs = s.run(
                    f"MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL}) "
                    "WHERE r.type = $t "
                    "RETURN a.type AS from_type, b.type AS to_type, count(*) AS c "
                    "ORDER BY c DESC LIMIT 5",
                    t=row["type"],
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

    def entity_exists(self, *, entity_id: str) -> bool:
        with self._driver.session() as s:
            rec = s.run(
                f"MATCH (n:{ENTITY_LABEL} {{id: $id}}) RETURN n.id AS id",
                id=entity_id,
            ).single()
        return rec is not None

    # ---------- Chunk store ----------

    def upsert_chunks(
        self, *, chunks: list[StoredChunk], embeddings: list[list[float]]
    ) -> int:
        """(:Chunk) batch UPSERT — id 기준 MERGE.

        WHY UNWIND 단일 transaction: 같은 source_path 의 chunk 들이 한 번에
        들어온다. 개별 MERGE 보다 UNWIND batch 가 round-trip 을 한 자리에 모아
        ingest 비용을 줄인다.
        """
        if not chunks:
            return 0
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
            )
        rows = [
            {
                "id": c.id,
                "source_path": c.source_path,
                "chunk_index": c.chunk_index,
                "total_chunks": c.total_chunks,
                "text": c.text,
                "token_count": c.token_count,
                "embedding": emb,
            }
            for c, emb in zip(chunks, embeddings)
        ]
        with self._driver.session() as s:
            result = s.run(
                f"UNWIND $rows AS row "
                f"MERGE (c:{CHUNK_LABEL} {{id: row.id}}) "
                f"SET c.source_path = row.source_path, "
                f"    c.chunk_index = row.chunk_index, "
                f"    c.total_chunks = row.total_chunks, "
                f"    c.text = row.text, "
                f"    c.token_count = row.token_count, "
                f"    c.embedding = row.embedding "
                f"RETURN count(c) AS n",
                rows=rows,
            )
            row = result.single()
            return int(row["n"]) if row else 0

    def delete_chunks_by_source(self, *, source_path: str) -> int:
        with self._driver.session() as s:
            result = s.run(
                f"MATCH (c:{CHUNK_LABEL} {{source_path: $sp}}) "
                f"WITH c, c.id AS _ "  # iterator 안전성
                f"DETACH DELETE c "
                f"RETURN count(_) AS n",
                sp=source_path,
            )
            row = result.single()
            return int(row["n"]) if row else 0

    def vector_search_chunks(
        self, *, embedding: list[float], top_k: int
    ) -> list[ChunkHit]:
        """db.index.vector.queryNodes — Neo4j 5.15+ 표준 vector ANN.

        WHY 결과 후처리: queryNodes 는 score 를 cosine similarity 로 돌려준다
        (vector.similarity_function = 'cosine'). top_k 안에서 그대로 정렬돼 옴.
        """
        if top_k <= 0:
            return []
        with self._driver.session() as s:
            rows = s.run(
                f"CALL db.index.vector.queryNodes("
                f"'{CHUNK_VECTOR_INDEX}', $k, $emb) "
                f"YIELD node, score "
                f"RETURN node.id AS id, node.source_path AS source_path, "
                f"       node.chunk_index AS chunk_index, "
                f"       node.total_chunks AS total_chunks, "
                f"       node.text AS text, node.token_count AS token_count, "
                f"       score",
                k=int(top_k),
                emb=list(embedding),
            ).data()
        hits: list[ChunkHit] = []
        for r in rows:
            hits.append(
                ChunkHit(
                    chunk=StoredChunk(
                        id=str(r["id"]),
                        source_path=str(r["source_path"]),
                        chunk_index=int(r["chunk_index"]),
                        total_chunks=int(r["total_chunks"] or 1),
                        text=str(r["text"] or ""),
                        token_count=int(r["token_count"] or 0),
                    ),
                    score=float(r["score"] or 0.0),
                )
            )
        return hits

    def count_chunks(self) -> int:
        with self._driver.session() as s:
            row = s.run(
                f"MATCH (c:{CHUNK_LABEL}) RETURN count(c) AS n"
            ).single()
            return int(row["n"]) if row else 0

    def get_entity_with_counts(
        self, *, entity_id: str
    ) -> EntityWithCounts | None:
        """단일 노드 + outgoing/incoming relation type 카운트.

        WHY 한 트랜잭션 / 세 쿼리: pydantic 모델 변환은 라우터가 하지만, neo4j
        의 한 세션 안에서 3 호출을 묶어 일관된 스냅샷을 본다 (이론적으로 다른
        트랜잭션이 끼면 카운트가 노드와 어긋날 수 있지만 MVP 단일 사용자 가정
        아래에서는 비결정적 결과가 발생할 가능성 매우 낮음).
        """
        with self._driver.session() as s:
            node_row = s.run(
                f"MATCH (n:{ENTITY_LABEL} {{id: $id}}) RETURN n",
                id=entity_id,
            ).single()
            if node_row is None:
                return None
            node = _node_to_response(node_row["n"])
            out_rows = s.run(
                f"MATCH (n:{ENTITY_LABEL} {{id: $id}})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->() "
                "RETURN r.type AS type, count(*) AS c",
                id=entity_id,
            ).data()
            in_rows = s.run(
                f"MATCH (n:{ENTITY_LABEL} {{id: $id}})<-[r:{RELATION_TYPE_LABEL_DEFAULT}]-() "
                "RETURN r.type AS type, count(*) AS c",
                id=entity_id,
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
    ) -> NeighborhoodResult:
        """N-hop BFS — 진입점에서 거리 가까운 순으로 max_nodes 절단.

        WHY variable-length match 가 아닌 BFS 직접 구현 (Python side): Cypher 의
        `*1..N` 패턴은 "한 노드를 여러 번 방문" 하는 경로를 모두 돌려준다. 우리
        에게 필요한 건 *고유 노드 집합* 이고 그것을 *거리 순* 으로 절단하는 것.
        Python BFS 가 가장 직관적이고 변동 없는 잘림 정책을 보장.
        """
        # 진입점 노드부터 시작 — 존재 확인은 호출자 책임.
        visited_nodes: dict[str, Node] = {}
        boundary_edges: dict[str, Edge] = {}
        # frontier 는 (id, level) 튜플들의 리스트 — BFS 의 한 레벨씩 확장.
        with self._driver.session() as s:
            # 진입점 노드 자체 — PRD 3 §5.4 의 "nodes 에 진입점 포함" 충족.
            row = s.run(
                f"MATCH (n:{ENTITY_LABEL} {{id: $id}}) RETURN n",
                id=entry_id,
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
                ).data()
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
                    if edge.id not in boundary_edges:
                        boundary_edges[edge.id] = edge
                    other_node_data = r["other"]
                    other_id = other_node_data["id"]
                    if other_id in visited_nodes:
                        continue
                    if len(visited_nodes) >= max_nodes:
                        truncated = True
                        break
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
    ) -> NeighborhoodResult:
        """multi-source BFS — 여러 진입점에서 동시에 확장.

        잘림 정책: *진입점 집합으로부터의 최단 거리* 기준 가까운 순. 즉 진입점
        A 에서 1-hop 노드는 다른 진입점 B 에서 5-hop 떨어진 노드보다 먼저 채워
        진다 (multi-source BFS 의 level 정의).
        """
        visited_nodes: dict[str, Node] = {}
        boundary_edges: dict[str, Edge] = {}
        with self._driver.session() as s:
            # 진입점 노드들 (PRD 3 §7.4 — 진입점 포함, dedupe).
            rows = s.run(
                f"MATCH (n:{ENTITY_LABEL}) WHERE n.id IN $ids RETURN n",
                ids=entry_ids,
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
                ).data()
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
                    if edge.id not in boundary_edges:
                        boundary_edges[edge.id] = edge
                    other_data = r["other"]
                    other_id = other_data["id"]
                    if other_id in visited_nodes:
                        continue
                    if len(visited_nodes) >= max_nodes:
                        truncated = True
                        break
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
    ) -> list[PathResult]:
        """k-shortest paths — Cypher `allShortestPaths` + 길이 정렬.

        WHY allShortestPaths (variable-length): native 단일 호출로 *모든* 최단
        경로를 받는다. 더 긴 경로까지 필요할 가능성이 있어 별도 *2..N* hop 패스
        를 추가하는 옵션도 있지만, MVP 는 단일 cypher 로 시작 — 측정 결과 부족
        하면 본 메서드만 교체 (라우터 인터페이스 불변).

        relation_types 가 비어 있지 않으면 경로의 *모든* 엣지가 그 타입에 포함
        되어야 한다. Cypher 의 list 비교로 표현.
        """
        # WHY apoc.algo.allSimplePaths 가 아닌 native shortestPath 변형: APOC 가
        # 없을 수 있음. 5.15 native 만으로 동작 보장. allShortestPath 는 다중 결과
        # 를 반환 (모두 같은 길이). 더 긴 경로는 max_hops 안에서 별도 패턴 추가
        # 호출로 보충.
        #
        # WHY relationship 을 *properties-only* 로 RETURN: 이슈 #27 회귀 2 와
        # 동일 원인. driver 가 relationships(p) 리스트를 dict/객체 어느 한 형태
        # 로 일관 직렬화하지 않을 수 있다. 노드 → 노드 사이의 엣지 속성만 꺼내
        # 원시 값으로 묶는다.
        cypher = """
        MATCH (a:Entity {id: $from_id}), (b:Entity {id: $to_id})
        MATCH p = allShortestPaths((a)-[*1..%d]-(b))
        WITH p,
             [r IN relationships(p) | r.type] AS rel_types,
             length(p) AS len
        WHERE ($filter_rels = false OR all(t IN rel_types WHERE t IN $rel_types))
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
        LIMIT $max_paths
        """ % int(max_hops)
        with self._driver.session() as s:
            rows = s.run(
                cypher,
                from_id=from_id,
                to_id=to_id,
                filter_rels=bool(relation_types),
                rel_types=relation_types or [],
                max_paths=max_paths,
            ).data()
        paths: list[PathResult] = []
        for row in rows:
            node_objs = [_node_to_response(n) for n in row["nodes"]]
            # 엣지 방향 정규화 — Cypher 의 양방향 패턴 (-[]-) 은 r 의 start/end
            # 가 path 의 traversal 방향과 어긋날 수 있다. PRD 3 §6.4 의
            # "edges[i] 는 nodes[i] → nodes[i+1]" 보장을 위해 traversal 시
            # from/to 를 path 순서로 재정의한다.
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
            paths.append(
                PathResult(nodes=node_objs, edges=edges, length=int(row["length"]))
            )
        return paths


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


def _build_neighbor_expand_cypher(direction: str) -> str:
    """frontier 노드 집합에서 한 hop 을 확장하는 cypher.

    WHY pattern 을 direction 별로 분기: Cypher 의 `-[r]-` (양방향) 은 *어느 쪽이
    a* 인지 결정적이지 않다. outgoing / incoming 이 의미를 가지려면 명시적
    화살표가 필요.

    relation_types 필터는 cypher 파라미터 `use_rel_filter` (bool) 와 `rel_types`
    (list) 를 함께 받아 조건문에서 분기 — list 가 비었을 때 IN 검사가 항상 false
    가 되는 함정을 피한다.

    WHY 관계를 *properties-only select* 로: `s.run(...).data()` 가 relationship
    객체를 dict 로 일관 직렬화하지 않는 경로가 있다 (특히 UNION 쿼리). 특히
    Neo4j 5.x + neo4j-driver 5.x 에서 UNION 결과의 relationship 이 tuple 로
    변환되어 `_record_to_edge` 가 `TypeError: tuple indices must be integers`
    로 깨졌다 (이슈 #27 회귀 2). 해결: cypher 가 *원시 값* 만 RETURN 한다.
    driver 의 객체 직렬화 quirk 가 사라진다.

    출력 컬럼: a_id (from 쪽), b_id (to 쪽), other (확장 대상 노드 raw),
    rel_id / rel_type / rel_created_at / rel_updated_at / rel_source_paths
    (relationship 속성을 풀어둠).
    """
    rel_select = (
        "r.id AS rel_id, r.type AS rel_type, "
        "r.created_at AS rel_created_at, r.updated_at AS rel_updated_at, "
        "r.source_paths AS rel_source_paths"
    )
    if direction == "outgoing":
        pattern = f"(a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL})"
        select = f"a.id AS a_id, b.id AS b_id, b AS other, {rel_select}"
        where_frontier = "a.id IN $frontier"
    elif direction == "incoming":
        pattern = f"(a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL})"
        select = f"a.id AS a_id, b.id AS b_id, a AS other, {rel_select}"
        where_frontier = "b.id IN $frontier"
    else:
        # both — Cypher 의 한 쿼리에서 양방향을 한 번에 받으려면 UNION 또는
        # CASE 식이 필요. 가장 단순한 형태로 UNION 사용.
        return (
            f"MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL}) "
            "WHERE a.id IN $frontier "
            "AND ($use_rel_filter = false OR r.type IN $rel_types) "
            f"RETURN a.id AS a_id, b.id AS b_id, b AS other, {rel_select} "
            "UNION "
            f"MATCH (a:{ENTITY_LABEL})-[r:{RELATION_TYPE_LABEL_DEFAULT}]->(b:{ENTITY_LABEL}) "
            "WHERE b.id IN $frontier "
            "AND ($use_rel_filter = false OR r.type IN $rel_types) "
            f"RETURN a.id AS a_id, b.id AS b_id, a AS other, {rel_select}"
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
    """relationship properties → 응답 Edge.

    WHY *키워드 전용 primitive 인자* 로 단순화: 이전엔 neo4j Relationship 객체
    (`r.get`/`r.start_node` 등) 를 그대로 받았으나, `s.run(...).data()` 가 일부
    경로에서 relationship 을 tuple 로 직렬화해 `TypeError: tuple indices must be
    integers` 가 발생했다 (이슈 #27 회귀 2). 이제 cypher 가 properties-only
    select 로 *원시 값* 만 RETURN 하고, 호출자가 그 값을 그대로 전달한다.
    driver 의 객체 직렬화 quirk 가 완전히 사라진다.

    from_id / to_id 는 호출자가 명시 — 양방향 path traversal 에서 *진행 방향* 에
    맞춰 from/to 를 재정의할 때도 같은 함수를 쓰기 위함.
    """
    return Edge(
        id=rel_id,
        **{"from": from_id},
        to=to_id,
        type=rel_type or RELATION_TYPE_LABEL_DEFAULT,
        properties={},
        source_refs=[SourceRef(source_path=sp) for sp in (rel_source_paths or [])],
        created_at=rel_created_at,
        updated_at=rel_updated_at,
    )


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
