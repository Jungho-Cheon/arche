# Arche API — 아키텍처 (코드 파악용)

이 문서는 `apps/api` 를 처음 보는 사람이 **전체 구조 → 계층 책임 → 데이터 모델
(ERD) → 요청 흐름** 순으로 코드를 따라갈 수 있게 한다. 결정의 *근거* 는 각
ADR (`docs/adr/`) 에 있고, 여기서는 *지금 코드가 어떻게 생겼는지* 를 설명한다.

> 한 줄 정의: Arche API 는 AI 에이전트와 그래프 데이터베이스(Neo4j) 사이에
> 앉아, 문서를 그래프로 **적재(ingest)** 하고 그래프를 **질의(query)** 하는
> 프리미티브를 REST + MCP 두 통로로 노출하는 백엔드다.

---

## 1. 한눈에 — 계층

```
            ┌─────────────────────────────────────────────────┐
  소비자     │  AI 에이전트 (Claude/GPT/…)   ·   eval 하베스    │
            │  [후속] web-ui · 외부 TS 에이전트                │
            └───────────────┬─────────────────┬───────────────┘
                            │ REST (HTTP)     │ MCP (stdio/HTTP)
            ════════════════▼═════════════════▼════════════════  ← 단일 계약 경계
            ┌─────────────────────────────────────────────────┐
  api/      │ routers (얇음)  →  services (RRF·BFS·매핑 로직)   │
            │ deps (wire-up) · schemas/responses · auth · errors│
            └───────────────┬─────────────────────────────────┘
                            │ 포트(ABC)만 의존
            ┌───────────────▼─────────────────────────────────┐
  domain/   │ ingest (적재 4단계+차분) · identity (동일성/병합) │  ← 순수 로직
            │ extraction_contract · extract_context · chunking  │     (외부 의존 없음)
            │ main_entity · crawl · models · errors             │
            └───────────────┬─────────────────────────────────┘
                            │ 포트(ABC) 구현
            ┌───────────────▼─────────────────────────────────┐
  adapters/ │ Neo4jGraphRepository (GraphStore+Vector+Lexical)  │  ← 외부 기술
            │ {OpenAI,Anthropic}LLM, {OpenAI,Voyage}Embed, pdf  │
            │ providers.py (모델 접두사로 어댑터 고르는 팩토리)   │
            └───────────────┬─────────────────────────────────┘
                            │ bolt
                    ┌───────▼────────┐
                    │  Neo4j 5.x     │
                    └────────────────┘
```

핵심 원칙 (헥사고날 / 포트-어댑터):
- **api** 는 HTTP/MCP 입출력 변환만. 비즈니스 로직은 `services.py` 한 곳.
- **domain** 은 순수 로직. *포트(추상 인터페이스)* 에만 의존하고 구체 기술
  (Neo4j/OpenAI) 은 모른다.
- **adapters** 는 포트를 특정 기술로 구현한다. 교체 가능 (ADR-0018 agnostic).
- **계약 경계** — 소비자는 REST/MCP 계약만 본다. Python 내부는 안 본다. 그래서
  어느 에이전트든(Agent-agnostic) 붙을 수 있다.

> 포트 위치: 모든 포트 ABC + 포트가 주고받는 DTO 는 `domain/ports.py` 에 있다.
> 도메인이 자기 포트를 소유하므로 **도메인은 어댑터를 import 하지 않는다** (import
> 방향이 바깥→안 으로 흐른다). `LLMProvider` 포트 ↔ `ExtractContext` 순환은
> `ExtractContext` 를 `TYPE_CHECKING` 으로 미뤄 끊었다 (`from __future__ import
> annotations` 로 힌트가 문자열이라 런타임 평가 없음).

---

## 2. 계층별 책임 + 파일 지도

### api/ — 노출 표면
| 파일 | 책임 |
|---|---|
| `main.py` | FastAPI 앱 생성, lifespan 에서 어댑터 wire-up + 인덱스 마이그레이션 + MCP 라우트 마운트. 라우터를 `/` 와 `/v1/` 양쪽에 등록 (ADR-0013 D8 버전닝). |
| `api/routers.py` | 얇은 REST 라우터 6 프리미티브 + healthz + admin/ingest. 입출력을 `DataEnvelope` 으로 감싸고 `services` 에 위임. |
| `api/services.py` | **비즈니스 로직 단일 출처** — find_entities 의 RRF 융합, get_neighbors/subgraph 의 BFS 결과 매핑, find_path 매핑. REST 와 MCP 가 *같은* 동작을 노출하도록 여기 모은다. |
| `api/deps.py` | 의존성 주입 — 싱글톤 graph/llm/embedder + `IngestService` 조립. |
| `api/schemas.py` / `api/responses.py` | pydantic 요청/응답 모델 (REST 계약 = PRD 3 §1 JSON Schema). |
| `api/auth.py` | `AuthContext` — "누가 + 어느 워크스페이스(namespace)". 지금은 헤더 기반, 후속 SSO 가 같은 컨텍스트를 채움. |
| `api/admin_tasks.py` | 비동기 ingest 작업 registry + 진행 상태. |
| `mcp_server.py` / `mcp_http.py` | MCP (stdio / HTTP) 전송. 같은 프리미티브를 도구로 노출, `services` 에 위임. |

### domain/ — 순수 로직 (외부 의존 없음)
| 파일 | 책임 |
|---|---|
| `domain/ingest.py` | **적재 파이프라인** — 파일 읽기 → hash short-circuit → 청크 분할 → LLM 추출 → 4단계 동일성 매칭 → 병합/생성 → 관계 upsert → 이전 회차와 차분. |
| `domain/identity.py` | 엔티티 동일성 — `EntityMatcher` (4단계), `EntityMerger`, 식별자-별칭 추출, 과잉병합 탐지 (ADR-0017), stoplist/deixis 가드. |
| `domain/ports.py` | **포트 — 코어가 외부에 요구하는 추상 인터페이스 + 입출력 DTO.** `GraphStore`/`VectorIndex`/`LexicalIndex` + 합성 `GraphRepository`, `LLMProvider`, `EmbeddingProvider`, 그리고 이들이 주고받는 DTO(`KeywordHit`/`NeighborhoodResult`/`PathResult` 등). 도메인이 자기 포트를 소유 (ADR-0018). |
| `domain/extraction_contract.py` | **provider-중립 추출 계약** — `EXTRACTION_SYSTEM_PROMPT` + 엔티티/관계 JSON 스키마. "무엇을 어떻게 추출" (ADR-0018 D3). |
| `domain/extract_context.py` | 추출 시 동봉하는 컨텍스트 블록 (DOC_CONTEXT/KNOWN_ENTITIES/SCHEMA — ADR-0009). |
| `domain/main_entity.py` | 문서당 1회, 자기지칭("당사")을 풀 주 엔티티 추출 (2nd pass). |
| `domain/chunking.py` | 토큰 예산 기반 본문 청크 분할. |
| `domain/crawl.py` | 디렉토리 크롤 + gitignore 필터. |
| `domain/models.py` | 도메인 모델 — 응답용 pydantic (`Node`/`Edge`) vs 내부 dataclass (`StoredEntity` 등). |

### adapters/ — 외부 기술 구현
| 파일 | 책임 |
|---|---|
| `adapters/graph.py` | 구현 `Neo4jGraphRepository` (포트는 `domain/ports.py` 에서 import). Neo4j Cypher + 인덱스. |
| `adapters/llm.py` | `OpenAILLMProvider` (중립 계약 → OpenAI `response_format` 봉투) + `AnthropicLLMProvider` (→ Anthropic tool-use) + `ClaudeCodeLLMProvider` (→ `claude -p` 구독 경유, 키 불필요·텍스트 전용). 모두 같은 포트/중립 계약 구현 (ADR-0019). |
| `adapters/embedding.py` | `OpenAIEmbeddingProvider` + `VoyageEmbeddingProvider` (포트 import, ADR-0019). |
| `adapters/providers.py` | provider 팩토리 — 모델 식별자 접두사(`openai/anthropic/voyage`)로 어느 어댑터를 만들지 고른다. 호출부(deps/cli)는 이 팩토리만 부른다 (ADR-0019 D2). |
| `adapters/pdf.py` / `adapters/image_loader.py` | PDF/이미지 로딩. |
| `adapters/extract_cache.py` | 청크별 추출 캐시 (ADR-0010). |

---

## 3. 능력별 포트 (agnostic 이음매 — ADR-0018 D2)

`GraphRepository` 는 세 능력의 합성 포트다. 백엔드가 셋을 native 로 다 갖지 않을
수 있으므로 능력별로 갈라 둔다.

```
GraphRepository(GraphStore, VectorIndex, LexicalIndex)   ← 도메인이 의존하는 합성 포트
        ▲              ▲            ▲
        │ 구현         │            │
  Neo4jGraphRepository  ─────────────┘   ← 지금은 한 store 가 셋을 모두 구현 (ADR-0004)
```

| 포트 | 능력 | 주요 메서드 |
|---|---|---|
| `GraphStore` | 순수 그래프 | create_entity, apply_merge_mutation, upsert_relation, expand_neighbors, expand_subgraph, find_shortest_paths, get_schema_summary, IngestionRun 기록·차분, 수명주기 |
| `VectorIndex` | 임베딩 ANN | vector_search, find_entities_dense |
| `LexicalIndex` | 어휘 fulltext | find_by_keywords_scored |

LLM/임베딩도 같은 패턴: `LLMProvider` / `EmbeddingProvider` 포트를 provider별
어댑터가 구현한다. 현재 LLM 은 OpenAI + Anthropic, 임베딩은 OpenAI + Voyage 두
구현이 있고 (ADR-0019), 어느 것을 쓸지는 `adapters/providers.py` 팩토리가 모델
식별자 접두사(`openai/gpt-4.1`, `anthropic/claude-...`, `voyage/voyage-3`)로 고른다.
새 provider 추가 = 어댑터 구현 + 팩토리 레지스트리 한 줄 (호출부 불변).

---

## 4. 데이터 모델 (ERD)

### 4.1 Neo4j 그래프 스키마 (실제 저장 형태)

```
 ┌────────────────────────────┐            ┌────────────────────────────┐
 │ (:Entity)                  │  RELATES_TO│ (:Entity)                  │
 │  id            (ULID, uniq)│───────────▶│  id                        │
 │  name                      │  {type,    │  name                      │
 │  type                      │   id,      │  …                         │
 │  aliases        []         │   source_  │                            │
 │  normalized_name (idx)     │   refs…}   └────────────────────────────┘
 │  normalized_aliases []     │
 │  description               │   * RELATES_TO 는 단일 관계 라벨 + `type`
 │  properties     {}         │     속성으로 의미 구분 (동적 라벨 대신).
 │  embedding      [float]    │     유일성 = (from_id, type, to_id) MERGE.
 │  namespace_id   (=워크스페이스)│
 │  source_paths   []         │
 └──────────┬─────────────────┘
            │ EMITTED_IN                ┌────────────────────────────┐
            └──────────────────────────▶│ (:IngestionRun)            │
                                        │  id, source_path,          │
                                        │  source_hash,              │
                                        │  extractor_version,        │  ← (path,hash,version)
                                        │  status, started/completed │     = short-circuit 게이트
                                        └────────────────────────────┘
```

인덱스/제약 (`ensure_indexes`):
- `entity_id_unique` / `ingestion_run_id_unique` / `relation_id_unique` — 제약.
- `entity_name_idx` — **fulltext** (name + aliases) → `LexicalIndex`.
- `entity_embedding_idx` — **vector** (cosine, 1536d) → `VectorIndex`.
- `entity_normalized_name_idx` — btree → 4단계 동일성 Step 1/2.
- `ingestion_run_source_idx` — short-circuit/차분 조회.

워크스페이스 격리 = `namespace_id` 속성 (ADR-0015). web-ui 의 "워크스페이스별
조회" 가 여기 매핑된다.

### 4.2 코드 모델 — 응답용 vs 내부용 (관심사 분리)

```
LLM 추출 결과            내부 저장 표현             REST 응답 (계약)
ExtractedEntity   ──▶   StoredEntity        ──▶   Node
ExtractedRelation       (embedding 포함,           (embedding 없음!
ExtractedGraph           namespace_id,              PRD 3 §1.1)
                         normalized_* 포함)
                        MergeMutation (병합 결과, embedding 미포함 = 타입으로 강제)
```

`StoredEntity.embedding` 은 내부 전용이고 `Node` 응답에는 의도적으로 없다 (누출
방지). 적재는 `ExtractedEntity → StoredEntity`, 조회 응답은 `StoredEntity → Node`.

---

## 5. 요청 흐름

### 5.1 질의 — `find_entities` (하이브리드 검색)
```
POST /entities/find {keywords}
  → services.find_entities
      ├─ LexicalIndex.find_by_keywords_scored  (fulltext, keyword별)
      ├─ EmbeddingProvider.embed → VectorIndex.find_entities_dense (ANN, keyword별)
      └─ RRF 융합 (k=60) → 순위 결합 → matches
  → DataEnvelope(FindEntitiesResponse)
```
나머지 프리미티브: `get_schema` / `get_entity` / `get_neighbors`(N-hop BFS) /
`find_path`(k-최단경로, hub_score 정렬 — ADR-0017) / `get_subgraph`(다중 진입점 union).

### 5.2 적재 — `admin/ingest` (비동기)
```
POST /admin/ingest {directory_path, namespace_id}
  → 입력 검증 후 202 + task_id (백그라운드 asyncio.Task)
  → IngestService.ingest_directory → 파일별 ingest_file:
      1. source_hash 계산
      2. (path, hash, extractor_version) 성공 회차 있으면 SHORT-CIRCUIT (skip)
         · extractor_version = f"p{파이프라인버전}:{llm.extraction_fingerprint()}"
           → 프롬프트/스키마/모델/로직 바뀌면 재추출 (ADR-0017 코드-델타)
      3. IngestionRun(status=running) 생성
      4. 컨텍스트 70% 초과면 청크 분할 → 청크별 LLM 추출(캐시) → 병합
      5. 엔티티별 4단계 동일성 (EntityMatcher):
           Step1 정규화 이름 일치 → Step2 별칭 일치 → Step3 임베딩 ANN+cosine
           → Step4 miss=신규생성. (또는 LLM 이 matched_existing_id 직접 지정 = Step0)
      6. match→EntityMerger 병합 / miss→create_entity. 식별자-별칭 후처리 enrich.
      7. 관계 upsert (3-튜플 유일성).
      8. 이전 회차 emitted 와 비교 → 사라진 노드/관계 차분 적용 (deleted/trimmed).
      9. finalize_run.
  → GET /admin/ingest/{task_id}/status 로 진행률 polling
```
디렉토리 모드는 단일 파일 idempotent 단위를 직렬 반복 — 변경 안 된 파일은 2번에서
자동 skip (델타 적재).

---

## 6. agnostic 요약 (ADR-0018)

| 축 | 상태 | 이음매 |
|---|---|---|
| Agent-agnostic | 달성 | REST + MCP 가 같은 `services` 위임. 소비자는 계약만 봄. |
| DB-agnostic | 이음매 확보 | 능력별 포트(`GraphStore`/`VectorIndex`/`LexicalIndex`). 지금은 Neo4j 한 store. |
| LLM-agnostic | 실증 | `LLMProvider` 포트 + provider-중립 추출 계약을 OpenAI(`response_format`) + Anthropic(tool-use) + Claude Code(`claude -p`, 키 불필요) 로 번역 (ADR-0019). 임베딩도 OpenAI + Voyage 두 구현. 팩토리가 모델 접두사로 선택. |

---

## 7. 빠른 시작 (개발)

```bash
# 의존성
uv sync --extra dev
# 린트
uvx ruff check src/ tests/
# 단위 테스트
uv run pytest tests/unit -q
# 통합 테스트 (Docker 필요 — testcontainers 가 Neo4j 기동)
uv run pytest tests/integration -q
# 로컬 기동
uv run uvicorn arche_api.main:app --reload
```
