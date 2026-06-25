# Graph Report - .  (2026-06-17)

## Corpus Check
- 89 files · ~53,794 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1027 nodes · 2577 edges · 63 communities (59 shown, 4 thin omitted)
- Extraction: 71% EXTRACTED · 29% INFERRED · 0% AMBIGUOUS · INFERRED: 742 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]

## God Nodes (most connected - your core abstractions)
1. `FakeGraph` - 68 edges
2. `IngestService` - 48 edges
3. `SourceRef` - 48 edges
4. `StoredEntity` - 48 edges
5. `FakeEmbedder` - 45 edges
6. `GraphRepository` - 43 edges
7. `StubGraph` - 40 edges
8. `Neo4jGraphRepository` - 39 edges
9. `ExtractedGraph` - 38 edges
10. `FakeLLM` - 36 edges

## Surprising Connections (you probably didn't know these)
- `Entry-point reading order (PRD -> ADR -> STATUS -> specs)` --references--> `ADR Index README`  [INFERRED]
  CLAUDE.md → /Users/jungho1000/workspace/private/arche/docs/adr/README.md
- `FakeRepo` --shares_data_with--> `EntityMatcher (referenced)`  [INFERRED]
  apps/api/tests/unit/test_entity_matcher.py → /Users/jungho1000/workspace/private/arche/apps/api/src/arche_api/domain/identity.py
- `OpenAIEmbeddingProvider` --implements--> `EmbeddingProvider Protocol`  [INFERRED]
  eval/src/arche_eval/providers.py → /Users/jungho1000/workspace/private/arche/eval/src/arche_eval/providers.py
- `repo()` --calls--> `Neo4jGraphRepository`  [INFERRED]
  apps/api/tests/integration/test_identity_e2e.py → apps/api/src/arche_api/adapters/graph.py
- `repo()` --calls--> `Neo4jGraphRepository`  [INFERRED]
  apps/api/tests/integration/test_neo4j_repo.py → apps/api/src/arche_api/adapters/graph.py

## Import Cycles
- 1-file cycle: `apps/api/src/arche_api/main.py -> apps/api/src/arche_api/main.py`
- 1-file cycle: `eval/src/arche_eval/runlog.py -> eval/src/arche_eval/runlog.py`
- 2-file cycle: `apps/api/src/arche_api/api/routers.py -> apps/api/src/arche_api/main.py -> apps/api/src/arche_api/api/routers.py`
- 2-file cycle: `apps/api/src/arche_api/api/deps.py -> apps/api/src/arche_api/main.py -> apps/api/src/arche_api/api/deps.py`
- 3-file cycle: `apps/api/src/arche_api/api/deps.py -> apps/api/src/arche_api/main.py -> apps/api/src/arche_api/api/routers.py -> apps/api/src/arche_api/api/deps.py`

## Communities (63 total, 4 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.08
Nodes (92): AdminIngestRequest, AdminIngestResponse, AdminIngestStatusResponse, IngestTaskRegistry, IngestTaskState, _on_progress(), Admin ingest 의 비동기 작업 registry — PRD 2 §1.2 + §1.3.  구조:   POST /admin/ingest →, worker thread 진입점 — 동기 ingest 흐름 + state 종결.      error code 명명: exception 타입 이름 (+84 more)

### Community 1 - "Community 1"
Cohesion: 0.09
Nodes (27): EmbeddingProvider, 텍스트 배치 → 임베딩 벡터 배치. 순서 보존., GraphRepository, KeywordHit, status='running' 으로 새 회차 노드 생성., `(:Entity)-[:EMITTED_IN]->(:IngestionRun)` 보장 (MERGE)., relation 의 `emitted_in_run_ids` 배열에 run_id 추가 (dedupe)., run 의 종결 — status + completed_at + 이번에 손댄 id 목록 기록. (+19 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (20): PRD 3 §0.3 envelope + §3.4 matches[].node/score/matched_keyword, GraphRepository, _client_with(), _make_node(), FastAPI 라우터 응답 envelope + Node 스키마 형태., PRD 3 §0.3 envelope + §3.4 matches[].node/score/matched_keyword., PRD 3 §3.5: 같은 노드가 여러 keyword 에서 surface 됐다면 가장 높은     raw 점수의 keyword 가 matched, PRD 3 §3.3: types 필터는 결과 노드의 type 이 리스트에 포함된 것만 남긴다. (+12 more)

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (37): _apply_overlap(), chunk_text(), count_tokens(), _encoder(), _force_split_by_tokens(), _pack_into_budget(), LLM 컨텍스트 초과 시 텍스트를 청크로 분할 — PRD 2 §3.  흐름:   count_tokens(text) → 컨텍스트의 70% 이하면, 폴백 분할 — 큰 단위에서 작은 단위로 단계적으로 내려간다.      각 단위에서 *한 단위가 budget 을 넘으면* 다음 작은 단위로 그 안 (+29 more)

### Community 4 - "Community 4"
Cohesion: 0.18
Nodes (28): EmbeddingProvider, ExtractedGraph, GraphRepository, LLMProvider, Path, SourceRef, StoredEntity, Chunk (+20 more)

### Community 5 - "Community 5"
Cohesion: 0.13
Nodes (30): Path, Path, crawl(), CrawlSummary, _is_excluded_dir(), _load_ignore_spec(), 디렉토리 재귀 수집 — PRD 2 §2.  흐름:   crawl(root) → root 아래 .txt / .md 파일을 정렬된 순서로 yield, 디렉토리를 재귀 탐색하며 자동 제외 + spec 매칭을 즉시 적용.      WHY Path.rglob 가 아닌 수동 재귀: rglob 은 디렉 (+22 more)

### Community 6 - "Community 6"
Cohesion: 0.13
Nodes (26): ExtractedGraph, FakeGraph, IngestService, Path, DirectoryIngestResult, FileProgressEvent, 한 파일 처리 이벤트.      - `index` / `total` : 디렉토리 안의 i/n.     - `chunks_total` : 해당 파, 디렉토리 모드 — 파일별 IngestResult 묶음 + 집계 (PRD 2 §7.2 의 메트릭).      `pending_skipped` / (+18 more)

### Community 7 - "Community 7"
Cohesion: 0.14
Nodes (28): ChunkRAGRunner, TOP_K=8 hyperparameter, amortized setup embedding tokens, PRD 4 §2.7 — embedding+LLM token accounting, help, Path, Path, ask() (+20 more)

### Community 8 - "Community 8"
Cohesion: 0.10
Nodes (22): Chunk, _IndexEntry, _MemoryIndex, 컬럼 (2) 청크 벡터 RAG — PRD 4 §2., chromadb 의존을 피하기 위한 in-process 인덱스. cosine 유사도 top-k.      WHY in-memory: 측정 하니스, corpus 를 청크화하고 모든 청크를 임베딩해 인덱스에 적재., Chunk RAG Baseline (800 tok / 100 overlap, cl100k_base), Path (+14 more)

### Community 9 - "Community 9"
Cohesion: 0.15
Nodes (24): FullContextRunner, Path, Path, Path, LLMResult, LLMUsage, load_questions(), Option (+16 more)

### Community 10 - "Community 10"
Cohesion: 0.11
Nodes (27): FileProgressEvent, help, IngestService, Path, FileProgressEvent, Argument, help, _format_progress_line() (+19 more)

### Community 11 - "Community 11"
Cohesion: 0.13
Nodes (16): ABC, OpenAIEmbeddingProvider, 임베딩 어댑터 — 노드 임베딩 생성.  WHY 모델 식별자를 config 에서: ADR-0001 통제 변수 + ADR-0003 D2. 청크 벡터, 그래프 저장소 어댑터 — Neo4j 5.15+ 내장 인덱스 사용 (ADR-0004 D1).  핵심 책임: - ensure_indexes() —, LLM provider 어댑터 — 추출 결과를 ExtractedGraph 로 반환.  WHY 추상 + 단일 구현: PRD 2 §4 의 *교체 가, DependencyUnavailableError, ArcheError, 도메인 예외 — PRD 3 §9 의 에러 코드 카탈로그와 매핑. (+8 more)

### Community 12 - "Community 12"
Cohesion: 0.09
Nodes (19): RUN_LIVE_TESTS=1 gating for live tests, Short-circuit on Unchanged Source Hash, main(), PR 본문용 proof — 컨테이너화된 Neo4j + 실제 OpenAI 위에서 alias 병합과 삭제 차분의 결과를 stdout 으로 찍는다., _count_entities(), _count_relations(), Live idempotency — 실제 OpenAI + 실제 Neo4j (compose 스택) 위에서.  RUN_LIVE_TESTS=1 일 때만, 두 번 ingest — entity/relation 카운트 불변. (+11 more)

### Community 13 - "Community 13"
Cohesion: 0.16
Nodes (21): Path, _entities_in_graph(), _LLMScripted, _make_extracted(), _make_service(), 4 단계 동일성 + 차분 — 실 Neo4j 위에서 끝에서 끝까지.  WHY testcontainers: Cypher 쿼리 형태와 인덱스 동작은, 공백 변형 — 두 번째 추출이 같은 노드로 병합., 새 엔티티의 alias 가 기존 정규명을 가리키면 Step 2 매칭. (+13 more)

### Community 14 - "Community 14"
Cohesion: 0.21
Nodes (23): ExtractedGraph, IngestService, Path, ExtractedRelation, _build_service(), FakeLLM, Ingest 파이프라인 — 어댑터 mocking 으로 4 단계 동일성 + 차분 흐름 검증.  WHY in-memory fake repo: Ing, 같은 파일 두 번 — 두 번째는 short-circuit (LLM 호출 0). (+15 more)

### Community 15 - "Community 15"
Cohesion: 0.16
Nodes (21): datetime, Any, Path, Path, CLI — `arche-eval` 진입점. PRD 4 §6 의 서브커맨드 중 setup / ask / run 만.  judge / sp, ChunkRAGRunner (referenced), FullContextRunner (referenced), hash_directory() (+13 more)

### Community 16 - "Community 16"
Cohesion: 0.11
Nodes (15): _extract_source_refs(), _node_to_response(), _node_to_stored(), `normalized_name == normalized AND type == type_` 정확 일치., ANN top-k 후보를 *embedding 포함* 으로 반환. cosine 재계산은 도메인.          type 필터는 ANN 사전 필터, 새 엔티티 노드 생성. id 는 호출자가 생성 (ULID)., 정규화 키 lookup — 노드의 정규명 OR 정규화된 alias 중 한 곳이라도 hit.          WHY OR alias 까지: PRD, ANN top-k 후보. type 사후 필터.          WHY 사후 필터: Neo4j 5.15 의 `db.index.vector.quer (+7 more)

### Community 17 - "Community 17"
Cohesion: 0.19
Nodes (19): EmbeddingProvider, GraphRepository, MergeMutation, SourceRef, StoredEntity, StoredEntity, _cosine(), MatchResult (+11 more)

### Community 18 - "Community 18"
Cohesion: 0.15
Nodes (19): ExtractedGraph, Path, EmbeddingProvider, LLMProvider, _build_large_doc(), ChunkAwareFakeLLM, IngestService 가 본문을 청크 분할해서 LLM 을 *청크 단위로* 호출하는지 검증.  작은 model_context_tokens 를, 같은 엔티티 B 가 두 청크에서 등장 — source_refs 에 두 ref (서로 다른     chunk_index) 가 누적되어야 한다 (P (+11 more)

### Community 19 - "Community 19"
Cohesion: 0.17
Nodes (17): 4-Step Entity Identity Matching, Embedding Match Threshold = 0.92, EntityMatcher (referenced), _entity(), FakeEmbedder, FakeRepo, 4 단계 매처 — 각 step 의 hit / miss 동작.  테스트는 repo / embedder 를 mock 으로 주입해 step 별 분기를, 0.92 임계점 — 정확히 cosine 0.92 인 후보가 hit. (+9 more)

### Community 20 - "Community 20"
Cohesion: 0.18
Nodes (15): Path, Path, SUPPORTED_TEXT_EXTS={.txt,.md}, UnsupportedFileType exception, FileLoader, 파일 로더 — .txt / .md 만 지원. PDF·이미지는 issue #5 의존., PDF / 이미지 등 아직 어댑터가 연결되지 않은 포맷., corpus 디렉토리에서 텍스트 파일을 재귀 수집. (+7 more)

### Community 21 - "Community 21"
Cohesion: 0.11
Nodes (9): Neo4jGraphRepository, Neo4j 5.15+ 어댑터.      WHY driver 1 개 보존: bolt 커넥션 풀은 driver 내부에서 관리된다. 매 요청, 부팅 시 idempotent 하게 인덱스 + 백필 보장.          인덱스 구성:         - fulltext (name + alia, 새 엔티티 — `normalized_name` 포함. id 충돌 시 IntegrityError 가 정상.          WHY chunk_in, 이번 회차가 손대지 않은 이전 emitted entity 처리.          - 노드의 source_paths 가 *오직 source_pat, 관계의 차분 — 같은 규칙. source_paths 가 단일이면 삭제, 아니면 trim., Settings, Path (+1 more)

### Community 22 - "Community 22"
Cohesion: 0.16
Nodes (18): normalize() as identity control variable (ADR-0001), normalize(), 엔티티 이름 정규화 — *측정 통제 변수* .      동작:       1. `strip()` — 양 끝 공백 제거.       2. Unic, normalize (referenced), normalize 가 ingest 흐름 안에서 호출되는지 확인 (스모크)., test_normalize_smoke(), `normalize()` — PRD 2 §5.1 의 control variable.  WHY 케이스 분리: normalize 출력 형태가 바뀌면, # WHY: 조사/접미사 제거는 false positive 가 많아 의도적으로 안 한다. (+10 more)

### Community 23 - "Community 23"
Cohesion: 0.12
Nodes (4): fake_graph(), FakeGraph, In-memory 그래프 — 4 단계 매처 + 차분 검증에 충분한 동작., _record()

### Community 24 - "Community 24"
Cohesion: 0.27
Nodes (14): FakeGraph, Path, _client(), Admin ingest 비동기 응답 — PRD 2 §1.2 + §1.3.  POST /admin/ingest → 202 + { task_id,, 라이브 ingest 흐름을 fake adapter 위에 띄운다., GET status 를 폴링해 target state 에 도달할 때까지 대기., PRD 2 §1.2 — 202 + { task_id, status_url } 응답., test_dry_run_does_not_persist_to_graph() (+6 more)

### Community 25 - "Community 25"
Cohesion: 0.19
Nodes (11): EvalConfig (frozen dataclass), EvalConfig, load_config(), _normalize(), 런타임 설정 — 모델 식별자는 환경 변수로 오버라이드 가능, 기본값은 코드에 고정.  WHY: PRD 4 §2.7 통제 변수 — 컬럼 (1)(2, provider 접두사 제거한 실제 API 모델 식별자., provider 접두사가 없으면 openai/ 를 붙여 canonical 형태로.      WHY: 본 베이스라인은 OpenAI 단일 provi, 환경 변수에서 설정 로드. .env 는 호출자가 미리 로드한다. (+3 more)

### Community 26 - "Community 26"
Cohesion: 0.24
Nodes (10): IngestService, Entity Diff: delete (single source) vs trim (shared source), _CallRecorder, _make_prior(), _make_service_with(), 차분 적용 — 이전 회차 emitted set 과 새 회차 emitted set 의 차이가 어떻게 delete / trim / no-op 로 매, 이번 회차에서 다시 emit 된 엔티티/관계는 차분 콜백을 건드리지 않는다., test_diff_kept_entities_are_not_passed_to_repo() (+2 more)

### Community 27 - "Community 27"
Cohesion: 0.23
Nodes (13): PRD 2 §5.3 Merge Rules (aliases union, longer desc wins, existing properties win), EntityMerger (referenced), _existing(), EntityMerger — PRD 2 §5.3 의 병합 규칙 표.  embedding 은 도메인 타입 (MergeMutation) 에 *필드 자, 타입에 embedding 필드가 없어 재계산을 *원천적으로* 차단., test_aliases_union_dedupes_by_normalized(), test_description_longer_wins_new_replaces_existing(), test_description_tie_keeps_existing() (+5 more)

### Community 28 - "Community 28"
Cohesion: 0.15
Nodes (13): Commerce Business Rules as Validation Domain, Latency Measurement (median + p95, controlled conditions) (D7), LLM-as-Judge with Anonymized Order (D4), MCQ + Forced Reasoning Format (D1), ADR-0005: Measurement Methodology (Accuracy, Tokens, Latency), N=3 Repetition for Reproducibility (D8), Rationale: MCQ + anonymization mitigates LLM judge position/length/self-preference bias, Spot-Check by Author for Suspicious Cases (D5) (+5 more)

### Community 29 - "Community 29"
Cohesion: 0.21
Nodes (9): 컬럼 (1) Full-context LLM — PRD 4 §1., Any, Question, Any, Question, build_chunk_rag_user(), build_full_context_user(), 프롬프트 — PRD 4 §1.3-1.4 (full-context) 와 §2.5-2.6 (chunk RAG) 의 한국어 본문 그대로. (+1 more)

### Community 30 - "Community 30"
Cohesion: 0.21
Nodes (8): EXTRACTION_RESPONSE_FORMAT (strict JSON schema), OpenAILLMProvider, OpenAI chat completion 으로 한 번 시도, 파싱 실패 시 1 회 재시도.          PRD 2 §4.3 의 재시도 정책, 본문 → 엔티티/관계 추출. 실패 시 DependencyUnavailableError., Korean extraction SYSTEM_PROMPT, _to_extracted_graph(), Any, ExtractedGraph

### Community 31 - "Community 31"
Cohesion: 0.20
Nodes (12): Dual Alias Normalization (ingest-time + query-time) (D3), ADR-0003: Graph Entry Point Strategy (Hybrid Lexical + Dense), Node-level Embedding (not chunk-level) (D2), Embedded Vector Index in Graph DB (D1), Embedding Model as Pluggable Adapter (D2), No Separate Vector DB Service (Pinecone/Qdrant/etc rejected), Rationale: Avoid container/sync/backup overhead during hypothesis validation; modern DBs ship production-grade vector indexes, Separation Principle: Vector Search != Separate Vector DB (D3) (+4 more)

### Community 32 - "Community 32"
Cohesion: 0.23
Nodes (7): Any, EmbeddingProvider, EmbeddingResult, LLMProvider, LLMResult, LLM / 임베딩 provider 추상화 — 테스트에서 mock 으로 갈아끼우기 위한 최소 인터페이스., Protocol

### Community 33 - "Community 33"
Cohesion: 0.24
Nodes (11): Hybrid Entry-Point Matching (BM25 + Dense via RRF), Rationale: Identifier-centric domains (commerce) reward BM25, but dense absorbs alias/paraphrase for portability, find_entities Primitive (lexical + dense RRF fusion), find_path Primitive (two-node path search), get_entity Primitive (single node detail), get_neighbors Primitive (N-hop expansion), get_schema Primitive (entity/relation type introspection), get_subgraph Primitive (multi-entry-point traversal) (+3 more)

### Community 34 - "Community 34"
Cohesion: 0.27
Nodes (8): _lucene_escape(), fulltext 인덱스를 *keyword 별로* 따로 호출.          WHY keyword 별 분리: PRD 3 §3.4 의 `match, Lucene 특수 문자 escape — fulltext 쿼리 안전성.      WHY: keyword 에 콜론 / 따옴표가 섞이면 fulltex, Lucene escape — fulltext 쿼리 안전성., test_empty_yields_wildcard(), test_multi_token_wrapped_in_parens(), test_simple_keyword_unchanged(), test_special_chars_escaped()

### Community 35 - "Community 35"
Cohesion: 0.20
Nodes (9): apps/api README — walking skeleton, Control variables — same LLM, same embedding model across columns, PRD 2 §5.1 4-step entity identity, (:IngestionRun) idempotent diff model, Pareto hypothesis (accuracy vs token cost), Walking skeleton 1% slice, Arche API — walking skeleton.  이 패키지는 PRD 2 (소스 입력과 그래프 적재) 와 PRD 3 (Graph, README — Arche overview & hypothesis (+1 more)

### Community 36 - "Community 36"
Cohesion: 0.20
Nodes (6): BaseSettings, _EmbConstant, 이름 무관하게 같은 벡터 — 임베딩 유사도 1.0 → Step 3 항상 hit.      Step 3 분기 검증용. 다른 시나리오는 _EmbDe, 앱 전역 설정. uvicorn 부팅 시 한 번 로드., provider 접두사 제거한 실제 API 모델 식별자., Settings

### Community 37 - "Community 37"
Cohesion: 0.20
Nodes (5): testcontainers-driven isolated Neo4j integration test, 실제 Neo4j 컨테이너 위에서 인덱스 + upsert + find 흐름.  WHY testcontainers: docker compose 스택, E2E: ingest 픽스처 → fulltext 검색 → 응답 노드 확인., repo(), test_ingest_and_find_by_keyword()

### Community 38 - "Community 38"
Cohesion: 0.28
Nodes (5): IngestionRunRecord, 같은 (path, hash) 의 성공 run 이 이미 있는지 — short-circuit 판정., 동일 source_path 의 가장 최근 성공 run — 차분 비교의 기준., `(:IngestionRun)` 노드의 슬림 표현 — 차분 알고리즘이 다루는 필드만.      `emitted_entity_ids` 는 *해당, _to_run_record()

### Community 39 - "Community 39"
Cohesion: 0.22
Nodes (9): Caller-side Anchor Extraction (LLM responsibility offloaded to caller), Caller Responsibility (Anchor extraction + Synthesis) (D4), Post-MVP Chat Layer as Thin Wrapper above Core (D5), Graph Primitives Only (no natural language endpoint) (D1), ADR-0006: MCP/REST Primitives Surface, Coexistence with Neo4j MCP (D6), Primitives Set: get_schema, find_entities, get_entity, get_neighbors, find_path, get_subgraph (D2), Rationale: MCP ecosystem standard pattern exposes primitives, not NL; core avoids query-time LLM dependency (+1 more)

### Community 40 - "Community 40"
Cohesion: 0.31
Nodes (9): Corpus Tiny: Catalog (Product A/B, Category C/D), Corpus Tiny: Coupon Policy (Coupon X/Y, aliases), Domain Entity: Category C (contains Product A), Domain Entity: Coupon X (with aliases), Domain Entity: Product A, Domain Entity: Promotion P (applies to Category C only), Corpus Tiny: Promotion Policy (Promotion P/Q, Category C/D), questions.yaml Schema (Question + Option with failure_mode_tested) (+1 more)

### Community 41 - "Community 41"
Cohesion: 0.25
Nodes (8): One-page Report as MVP Exit Condition (D7), Arche Project Identity (Graph KB tool for LLMs), Pareto Superiority Hypothesis (accuracy = full-context, tokens > chunk RAG), ADR-0001: Project Identity and MVP Validation Hypothesis, Rationale: Long-context LLMs make efficiency the differentiator, 3-way Measurement (Full-context vs Chunk RAG vs Arche), PRD 1: MVP Spec, MVP In-Scope Items (ingest, graph load, hybrid index, primitives, deliverables)

### Community 42 - "Community 42"
Cohesion: 0.32
Nodes (5): _count_entities(), _count_relations(), Live directory ingest — 디렉토리 모드 + 청크 분할 두 가지를 한 번에 검증.  RUN_LIVE_TESTS=1 일 때만 실행, 디렉토리 두 번 → count 불변 + 큰 파일 청크 분할이 정상 동작., test_directory_ingest_is_idempotent_and_includes_chunked_file()

### Community 43 - "Community 43"
Cohesion: 0.29
Nodes (7): Idempotent Ingestion (D6), Chunk Only When Context Window Exceeded (§3), Diff-Apply Re-ingest for Idempotency (§5.4), Entity Identity Algorithm (4-step: normalized name -> alias -> embedding sim -> new), Entity/Relation Extraction JSON Schema (§4.3), PRD 2: Ingest Specification, skeleton_sample.md (test fixture: 여름 환영 쿠폰 entities)

### Community 44 - "Community 44"
Cohesion: 0.33
Nodes (7): Entity/Relation Audit Log deferred (D5), Auth/Access Control/Multi-tenant deferred (D2, post-MVP rank 1), Chat / Multi-turn Sessions deferred (D3), Eval Gate / CI Integration deferred (D6), Frontend (Web UI) entirely out of scope (D1), ADR-0002: MVP Scope Boundaries, Rationale: Each in-scope item adds direct + indirect cognitive cost to hypothesis verification

### Community 45 - "Community 45"
Cohesion: 0.29
Nodes (6): PRD 3 §1.1: Node serialization hides embedding, Node model (referenced), PRD 3 §1.1 의 Node 스키마 형태 검증., test_node_minimal_serializes_per_prd(), test_node_rejects_bad_ulid(), test_now_rfc3339_is_utc_zulu()

### Community 46 - "Community 46"
Cohesion: 0.38
Nodes (7): OpenAI gpt-4.1 chosen for 1M context, Eval Package README (baseline columns 1+2), text-embedding-3-small (1536-dim) as shared embedding, Column 2: Chunk Vector RAG Baseline, PRD 4: Evaluation Harness (3-way), Column 1: Full-context LLM Harness, Judge Anonymization (A/B/C, randomized order)

### Community 47 - "Community 47"
Cohesion: 0.29
Nodes (7): Repo entry-point CLAUDE.md, Entry-point reading order (PRD -> ADR -> STATUS -> specs), legacy-arche reference policy (do not consult), Public artifact accessibility rule (self-contained issues/ADRs), Session role modes (orchestrator vs worker), Worker mode end-of-task checklist (PR + Closes #N), Writing tone policy (no jargon, no colloquial verbs)

### Community 48 - "Community 48"
Cohesion: 0.40
Nodes (3): `EntityMerger` 결과를 한 트랜잭션으로 set. embedding/normalized_name 은 변경 없음., 병합 — aliases/description/source_refs/updated_at 만 갱신.          WHY source_refs 를, MergeMutation

### Community 49 - "Community 49"
Cohesion: 0.40
Nodes (3): dense 매칭 — walking skeleton 에서는 미구현.          WHY stub: PRD 3 §3.5 + ADR-0003 D1, Node, NotImplementedError

### Community 50 - "Community 50"
Cohesion: 0.40
Nodes (3): _EmbDeterministic, 이름별로 서로 멀어지는 벡터 — Step 3 매칭 의도적 회피., 문자 ord 를 *문자별 dim* 으로 매핑 — 짧은 다른 이름끼리는 cosine 이 낮다.

### Community 52 - "Community 52"
Cohesion: 0.67
Nodes (3): Path, corpus_dir(), questions_path()

## Knowledge Gaps
- **73 isolated node(s):** `Settings`, `Any`, `Argument`, `help`, `Path` (+68 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `IngestService` connect `Community 4` to `Community 0`, `Community 1`, `Community 36`, `Community 6`, `Community 10`, `Community 11`, `Community 13`, `Community 14`, `Community 17`, `Community 18`, `Community 50`, `Community 21`, `Community 23`, `Community 26`?**
  _High betweenness centrality (0.139) - this node is a cross-community bridge._
- **Why does `datetime` connect `Community 15` to `Community 11`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Why does `ingest()` connect `Community 10` to `Community 0`, `Community 4`, `Community 7`, `Community 11`, `Community 21`, `Community 30`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Are the 25 inferred relationships involving `FakeGraph` (e.g. with `FakeGraph` and `Path`) actually correct?**
  _`FakeGraph` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `IngestService` (e.g. with `Path` and `Path`) actually correct?**
  _`IngestService` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Are the 37 inferred relationships involving `SourceRef` (e.g. with `EmbeddingProvider` and `GraphRepository`) actually correct?**
  _`SourceRef` has 37 INFERRED edges - model-reasoned connections that need verification._
- **Are the 40 inferred relationships involving `StoredEntity` (e.g. with `EmbeddingProvider` and `GraphRepository`) actually correct?**
  _`StoredEntity` has 40 INFERRED edges - model-reasoned connections that need verification._