"""그래프 저장소 어댑터 — Neo4j 5.13+ 내장 인덱스 사용 (ADR-0004 D1).

핵심 책임:
- ensure_indexes() — 부팅 시 idempotent 하게 인덱스 보장
- upsert_entity() — 이름 정확 매칭 (1-step identity, walking skeleton)
- upsert_relation() — (from_id, type, to_id) 3-튜플 유일성 (PRD 2 §5.5)
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
    Node,
    SourceRef,
    StoredEntity,
    now_rfc3339,
)


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
ENTITY_LABEL = "Entity"
RELATION_TYPE_LABEL_DEFAULT = "RELATES_TO"  # 폴백 — 추출 시 type 이 비면


class GraphRepository(ABC):
    @abstractmethod
    def ensure_indexes(self) -> None: ...

    @abstractmethod
    def healthcheck(self) -> bool: ...

    @abstractmethod
    def upsert_entity(self, *, entity: StoredEntity) -> tuple[str, bool]:
        """(엔티티 id, created?) — 새로 생성됐으면 True, 병합됐으면 False."""

    @abstractmethod
    def upsert_relation(
        self,
        *,
        from_id: str,
        to_id: str,
        rel_type: str,
        source_ref: SourceRef,
    ) -> tuple[str, bool]: ...

    @abstractmethod
    def find_by_name_exact(self, *, name: str) -> StoredEntity | None: ...

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
    """Neo4j 5.13+ 어댑터.

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
        """부팅 시 idempotent 하게 인덱스 보장.

        WHY 세 가지 인덱스:
        - fulltext (name + aliases): find_by_keywords_scored 의 lexical 신호.
        - vector (embedding): #6 후속의 dense 신호. *지금은 사용 안 함* 이지만
          미리 만들어 #6 가 마이그레이션을 안 하도록.
        - btree (name): upsert 시 *정확 이름 매칭* (1-step identity) 의 빠른
          lookup. fulltext 만으로는 exact-match 속도가 보장 안 된다.
        """
        dim = self._settings.embedding_dimension
        with self._driver.session() as s:
            s.run(
                f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX} IF NOT EXISTS "
                f"FOR (e:{ENTITY_LABEL}) ON EACH [e.name, e.aliases]"
            ).consume()
            # WHY 프로시저 형태: Neo4j 5.13 은 CREATE VECTOR INDEX 구문 미지원 (5.15+).
            # `db.index.vector.createNodeIndex` 는 같은 이름으로 두 번 호출하면 에러를
            # 던지므로 SHOW INDEXES 로 idempotent 가드.
            existing = s.run(
                "SHOW INDEXES YIELD name WHERE name = $name RETURN count(*) AS c",
                name=VECTOR_INDEX,
            ).single()
            if existing is None or existing["c"] == 0:
                s.run(
                    "CALL db.index.vector.createNodeIndex("
                    "$name, $label, $prop, $dim, $sim)",
                    name=VECTOR_INDEX,
                    label=ENTITY_LABEL,
                    prop="embedding",
                    dim=dim,
                    sim="cosine",
                ).consume()
            s.run(
                f"CREATE INDEX entity_name_btree IF NOT EXISTS "
                f"FOR (e:{ENTITY_LABEL}) ON (e.name)"
            ).consume()

    # ---------- Upsert ----------

    def find_by_name_exact(self, *, name: str) -> StoredEntity | None:
        with self._driver.session() as s:
            rec = s.run(
                f"MATCH (e:{ENTITY_LABEL}) WHERE e.name = $name RETURN e LIMIT 1",
                name=name,
            ).single()
        if rec is None:
            return None
        return _node_to_stored(rec["e"])

    def upsert_entity(self, *, entity: StoredEntity) -> tuple[str, bool]:
        """1-step identity: 이름 정확 매칭. 있으면 병합, 없으면 신규.

        병합 규칙 (PRD 2 §5.3 의 축약본 — walking skeleton):
        - aliases: union
        - description: 비어있던 쪽 채움 (기존 우선)
        - source_refs: append (중복 제거)
        - embedding: 갱신 (다시 계산했으므로)
        - updated_at: now
        """
        existing = self.find_by_name_exact(name=entity.name)
        with self._driver.session() as s:
            # WHY chunk index sentinel (-1): Neo4j property collection 은 null
            # 요소를 허용하지 않는다. walking skeleton 은 청크 분할이 없어 모든
            # source_ref 의 chunk_index 가 None. -1 을 "분할 없음" 의 sentinel 로
            # 두고 응답 직렬화 시 다시 None 으로 매핑한다 (PRD 3 §1.3 의 nullable).
            source_chunks = [
                sr.chunk_index if sr.chunk_index is not None else -1
                for sr in entity.source_refs
            ]
            if existing is None:
                s.run(
                    f"""
                    CREATE (e:{ENTITY_LABEL} {{
                        id: $id, name: $name, type: $type,
                        aliases: $aliases, description: $description,
                        embedding: $embedding,
                        source_paths: $source_paths,
                        source_chunk_indexes: $source_chunk_indexes,
                        created_at: $created_at, updated_at: $updated_at
                    }})
                    """,
                    id=entity.id,
                    name=entity.name,
                    type=entity.type,
                    aliases=entity.aliases,
                    description=entity.description or "",
                    embedding=entity.embedding,
                    source_paths=[sr.source_path for sr in entity.source_refs],
                    source_chunk_indexes=source_chunks,
                    created_at=entity.created_at,
                    updated_at=entity.updated_at,
                ).consume()
                return entity.id, True

            # 병합 — existing.id 유지.
            merged_aliases = sorted(set(existing.aliases) | set(entity.aliases))
            merged_description = existing.description or entity.description or ""
            new_paths = [sr.source_path for sr in entity.source_refs]
            s.run(
                f"""
                MATCH (e:{ENTITY_LABEL} {{id: $id}})
                SET e.aliases = $aliases,
                    e.description = $description,
                    e.embedding = $embedding,
                    e.source_paths = coalesce(e.source_paths, []) + $new_paths,
                    e.source_chunk_indexes = coalesce(e.source_chunk_indexes, []) + $new_chunks,
                    e.updated_at = $updated_at
                """,
                id=existing.id,
                aliases=merged_aliases,
                description=merged_description,
                embedding=entity.embedding,
                new_paths=new_paths,
                new_chunks=source_chunks,
                updated_at=entity.updated_at,
            ).consume()
            return existing.id, False

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
    refs: list[SourceRef] = []
    for i, p in enumerate(paths):
        ci = chunks[i] if i < len(chunks) else None
        # -1 sentinel → None (PRD 3 §1.3 의 nullable chunk_index 복원).
        if ci == -1:
            ci = None
        refs.append(SourceRef(source_path=p, chunk_index=ci))
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
