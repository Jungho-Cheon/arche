# Neo4j 활용 검토 — 잘 쓰는 부분 / 안티패턴 / 비효율

날짜: 2026-06-20
범위: `apps/api/src/opentology_api/adapters/graph.py` (1485 줄, 23 곳의 session)
관련: ADR-0002 (Neo4j 채택), ADR-0006 (graph primitives), Neo4j 5.15 community

## TL;DR

전반적으로 **walking skeleton 단계의 합리적 선택** (vector / fulltext index 활용, MERGE on 3-튜플, allShortestPaths native) 이 많고 **WHY 코멘트** 가 결정 근거를 잘 남김. 다만 4 가지 *프로덕션 전 보강 거리* 와 2 가지 *지금 영향 있는 비효율* 존재:

- 즉시 보강 (작은 비용 / 큰 영향): UNIQUE constraint 없음, Fulltext N+1 호출
- 중기 보강: execute_write/read 누락 (재시도 가드), Python BFS 의 round-trip
- 장기 결정: parallel array (`source_paths` / `source_chunk_indexes` / `source_total_chunks`) 의 스키마 정합성, Neo4j 5.18+ vector pre-filter 업그레이드 검토

## 1. 적재적소 — 잘 활용 중

| 기능 | 사용처 | 평가 |
|---|---|---|
| Vector index (cosine) | `vector_search`, `find_entities_dense` | 5.15 native API 그대로. dim/similarity OPTIONS 인라인 — Cypher parameter 제약 회피의 모범 |
| Fulltext index (Lucene/BM25) | `find_by_keywords_scored` | 4 단계 동일성 Step 2 + RRF 의 lexical 신호 정확히 분리 |
| Btree on `normalized_name` | `find_by_normalized_name` | Step 1·2 정확 일치 lookup 의 인덱스 적중 |
| Btree on `IngestionRun.source_path` | `find_latest_succeeded_run` | 차분 알고리즘의 핫패스 인덱스 적중 |
| `MERGE` on (from_id, type, to_id) | `upsert_relation` | 3-튜플 유일성 (PRD §5.5) 의 DB-level 보장 |
| `ON CREATE / ON MATCH SET` | `upsert_relation` | created vs updated 분기를 *단일 round-trip* 에 |
| `allShortestPaths` (native) | `find_shortest_paths` | APOC 의존 회피, k-shortest 의 idiomatic 표현 |
| `CREATE INDEX IF NOT EXISTS` | `ensure_indexes` | 부팅 idempotent — restart 안전 |

## 2. 안티패턴 / 비효율 — 개선 후보

### A. UNIQUE constraint 부재 (★ 즉시 보강 권장)

엔티티 / 관계 / IngestionRun 의 `id` 가 **application-level 에서만 unique**.

```cypher
-- 현재
CREATE (e:Entity { id: $id, ... })   -- 중복 id 받으면 두 노드 생성

-- 권장
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
  FOR (e:Entity) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT ingestion_run_id_unique IF NOT EXISTS
  FOR (r:IngestionRun) REQUIRE r.id IS UNIQUE;

-- 관계 id (5.7+): REQUIRE r.id IS UNIQUE
```

**영향**: 우리가 본 catastrophic over-merge 와 *같은 종류* 의 DB-level 가드 추가. 동시 ingest / 버그 / migration 시 graph 부패 방지.

**비용**: 3 줄 `CREATE CONSTRAINT` + ensure_indexes 에 추가. 기존 데이터에 중복 id 가 없으면 즉시 적용 가능.

### B. Fulltext 가 keyword 별 N 번 호출 (★ 즉시 보강 권장)

```python
# 현재 — find_by_keywords_scored, 코드 코멘트도 "성능 노트: ... 무시 가능"
for kw in keywords:
    s.run("CALL db.index.fulltext.queryNodes($idx, $q) ...", q=lucene_escape(kw))
```

질문 1 회당 keyword 10 개면 fulltext 호출 10 회. smoke 21 MCQ × 10 = **210 회**.

**개선**:
```cypher
CALL db.index.fulltext.queryNodes($idx, $or_query) YIELD node, score
RETURN node, score, /* 매칭된 keyword 추적용 */
       [kw IN $keywords WHERE (
         toLower(node.name) CONTAINS toLower(kw) OR
         any(a IN node.aliases WHERE toLower(a) CONTAINS toLower(kw))
       )] AS matched_keywords
```

또는 `db.index.fulltext.queryNodes` 의 결과에 BM25 score 만 받고 keyword 매핑은 어댑터에서 후처리. 한 번의 fulltext 호출 + 어댑터 Python 매핑.

**영향**: latency × 10 → × 1 (1 단계 추출의 round-trip 대폭 절감). graph 컬럼의 3.92s → 추정 3s 이하.

**비용**: matched_keyword 매핑 로직 (응답 계약 유지 위해) 작성.

### C. Unmanaged transactions — execute_write / execute_read 누락

23 곳 모두 `with self._driver.session() as s: s.run(...)`. neo4j Python driver 5.x 권장은 `session.execute_write(fn)` / `session.execute_read(fn)`:

- 자동 재시도 (transient TransientError 발생 시)
- routing (cluster 시) — 단일 인스턴스에서는 차이 작음
- 트랜잭션 함수 스코프가 명확

**영향**: 단일 사용자 MVP 에서는 큰 영향 없음. ingest 동시 / Neo4j Aura cluster 이전 시 잠재적 transient 에러에 약함.

**비용**: 23 곳 수정. 패턴 통일.

### D. BFS 가 Python side 구현 (hop 마다 round-trip)

```python
# expand_neighbors / expand_subgraph
for _hop in range(hops):
    rows = s.run(_build_neighbor_expand_cypher(direction), frontier=frontier_ids, ...)
    # Python 에서 next_frontier 계산
```

hops=2 면 round-trip 2 회. 트레이드오프 코멘트로 "직관적 / 변동 없는 잘림 정책" 명시.

**대안 (낮은 호출 수)**:
- `MATCH (entry)-[*1..h]-(n) WITH n, length(...) AS dist ... ORDER BY dist LIMIT $max` 단일 query
- 또는 APOC `apoc.path.expandConfig({minLevel: 1, maxLevel: h, uniqueness: 'NODE_GLOBAL', limit: $max})` — 단 APOC 의존성 도입

**영향**: latency 감축 (round-trip ↓), graph 컬럼의 3.92s 의 일부 가지 (B 와 합쳐 2.5s 이하 가능).

**비용**: variable-length path 의 *잘림 정책 재설계*. 현재 BFS 의 "거리 순 절단" 을 Cypher 에서 보장하려면 `WITH ... ORDER BY dist LIMIT $max` 패턴 + uniqueness 보장 — 가능하지만 측정 검증 필요.

### E. Vector search 후 type 사후 필터 (Neo4j 5.15 제약)

```python
# vector_search — 4× oversample 후 WHERE 로 type 필터
oversample = max(top_k * 4, top_k)
"... WHERE node:Entity AND node.type = $t ..."
```

5.18+ 부터 `db.index.vector.queryNodes` 가 *pre-filtering* 지원. 5.15 → 5.18+ 업그레이드 시:
- oversample 4× 제거 → ANN 후보 풀이 작아지고 정확도 ↑
- 사후 WHERE 제거 → cost ↓

**영향**: Neo4j 마이너 업그레이드 (5.15 → 5.18+) 의 직접 ROI. 호환성 확인 필요.

**비용**: 업그레이드 자체 (docker image tag + 회귀 테스트).

### F. Parallel arrays — `source_paths` / `source_chunk_indexes` / `source_total_chunks`

한 entity 의 source_refs 가 *triple of lists* 로 저장:
```
source_paths        = ['a.md', 'b.md']
source_chunk_indexes = [3, -1]   ← -1 sentinel = null
source_total_chunks  = [10, -1]
```

**문제**:
- i 인덱스 정합성이 application-level 만 보장 (DB 가 모름)
- merge / dedupe 시 세 list 동기화 필요 (`apply_merge_mutation` 의 set 패턴)
- sentinel -1 의 의미가 코드 안에만

**대안 1 — Sub-node**:
```
(:Entity)-[:HAS_SOURCE]->(:SourceRef {source_path, chunk_index, total_chunks})
```
장점: query 력 ↑ (예: "이 chunk_index 가 가리키는 entity 들"), DB-level 정합성. 단점: 노드 수 증가, MERGE 로직 복잡.

**대안 2 — JSON property**:
```
e.source_refs_json = '[{"source_path":"a.md","chunk_index":3,...},...]'
```
장점: 응답 직렬화 단순. 단점: query 력 잃음, 텍스트 색인 비용.

**평가**: walking skeleton 단계에선 parallel array 가 합리적. *EntityConsolidator (M6.5b)* 작업 묶음에서 함께 결정 — Consolidator 가 source_path 기반 회사 분리를 다루므로 자연스러운 묶음.

### G. `_just_created` dummy property 영구 남음

`upsert_relation` 의 `ON CREATE SET r._just_created = true / ON MATCH SET r._just_created = false` 가 *매 호출마다 덮어쓰기* 라 영구 남는다.

**영향**: 의도된 동작 (호출 후 즉시 읽음). 단 stale property 가 entity / relation 마다 늘어남.

**개선**: 호출 후 `MATCH (a)-[r {id: $id}]->(b) REMOVE r._just_created` 또는 `apoc.do.case` 패턴.

**비용**: 작음. 측정 영향은 무시 가능.

### H. `MATCH (n) WHERE n.id IN $ids` 가 핫패스에 다수

`expand_subgraph` / `mark_entity_emitted` / `apply_entity_diff` 등에서 id IN 패턴 다수. 현재 entity.id 에 명시적 인덱스 없음 → label scan + property filter.

A 의 UNIQUE constraint 가 추가되면 *자동 인덱스* 생성 → 본 문제 해소. A 가 두 번째 가치.

## 3. 우선순위 권장

| 순위 | 항목 | 영향 | 비용 | 묶을 작업 |
|---|---|---|---|---|
| 1 | A — UNIQUE constraint 3 개 | 부패 방지 + B 의 id index 동시 | 작음 (3 줄) | 본 PR 안 |
| 2 | B — Fulltext OR-batch | latency ↓ + cost ↓ × 10 | 중간 (매핑 로직) | M8 최적화 |
| 3 | C — execute_write/read | 재시도 가드 | 중간 (23 곳) | M7 productization 직전 |
| 4 | D — BFS Cypher 단일화 | latency ↓ (1-2 hops 핫패스) | 큼 (절단 정책 검증) | M8 최적화 |
| 5 | F — Parallel array 결정 | 정합성 + query 력 | 큼 (스키마) | M6.5b EntityConsolidator 와 함께 |
| 6 | E — Neo4j 5.18+ 업그레이드 | ANN 정확도 + latency | 큼 (인프라) | M9 scale 시 |

## 4. 본 검토 한계

- 동시성 / Aura cluster 시나리오는 직접 측정 안 함 — 패턴 검토만
- `apoc` 의존성 도입 시 트레이드오프는 별도 ADR 거리 (이전에 의도적으로 native 만 사용 결정)
- B (fulltext batch) 의 정확한 latency 절감폭은 PoC 측정 필요 — 본 검토는 *호출 횟수 감소* 만 확정
