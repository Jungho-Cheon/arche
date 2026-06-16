# Graph Report - .  (2026-06-17)

## Corpus Check
- Corpus is ~46,494 words - fits in a single context window. You may not need a graph.

## Summary
- 827 nodes · 2031 edges · 52 communities (49 shown, 3 thin omitted)
- Extraction: 73% EXTRACTED · 27% INFERRED · 0% AMBIGUOUS · INFERRED: 552 edges (avg confidence: 0.54)
- Token cost: 27,186 input · 6,796 output

## Community Hubs (Navigation)
- [[_COMMUNITY_API Layer & DI Wiring|API Layer & DI Wiring]]
- [[_COMMUNITY_Identity E2E Tests|Identity E2E Tests]]
- [[_COMMUNITY_Live Integration Tests|Live Integration Tests]]
- [[_COMMUNITY_Routers PRD-3 Tests|Routers PRD-3 Tests]]
- [[_COMMUNITY_Adapter Protocols|Adapter Protocols]]
- [[_COMMUNITY_Chunk RAG Index|Chunk RAG Index]]
- [[_COMMUNITY_Eval Baseline Columns|Eval Baseline Columns]]
- [[_COMMUNITY_Entity Matcher Core|Entity Matcher Core]]
- [[_COMMUNITY_Ingest Service Tests|Ingest Service Tests]]
- [[_COMMUNITY_Test Graph Fakes|Test Graph Fakes]]
- [[_COMMUNITY_Eval CLI & Runlog|Eval CLI & Runlog]]
- [[_COMMUNITY_Ingest Service Domain|Ingest Service Domain]]
- [[_COMMUNITY_Eval Columns Setup|Eval Columns Setup]]
- [[_COMMUNITY_Entity Matcher Tests|Entity Matcher Tests]]
- [[_COMMUNITY_Eval Config|Eval Config]]
- [[_COMMUNITY_Eval File Loader|Eval File Loader]]
- [[_COMMUNITY_Name Normalization|Name Normalization]]
- [[_COMMUNITY_Eval CLI Commands|Eval CLI Commands]]
- [[_COMMUNITY_Neo4j Repository|Neo4j Repository]]
- [[_COMMUNITY_Entity Merger Rules|Entity Merger Rules]]
- [[_COMMUNITY_Graph Repo Lookups|Graph Repo Lookups]]
- [[_COMMUNITY_Relation & Node Model|Relation & Node Model]]
- [[_COMMUNITY_Adapters Doc Index|Adapters Doc Index]]
- [[_COMMUNITY_LLM Adapter & Models|LLM Adapter & Models]]
- [[_COMMUNITY_ADR-34 Vector Strategy|ADR-3/4 Vector Strategy]]
- [[_COMMUNITY_API Skeleton Notes|API Skeleton Notes]]
- [[_COMMUNITY_Questions YAML Loader|Questions YAML Loader]]
- [[_COMMUNITY_ADR-6 MCP Primitives|ADR-6 MCP Primitives]]
- [[_COMMUNITY_PRD-3 Primitives|PRD-3 Primitives]]
- [[_COMMUNITY_OpenAI LLM Adapter|OpenAI LLM Adapter]]
- [[_COMMUNITY_ADR-1 Pareto Hypothesis|ADR-1 Pareto Hypothesis]]
- [[_COMMUNITY_Ingestion Run Records|Ingestion Run Records]]
- [[_COMMUNITY_Lucene Escape|Lucene Escape]]
- [[_COMMUNITY_ADR-5 Measurement|ADR-5 Measurement]]
- [[_COMMUNITY_Corpus Tiny Domain|Corpus Tiny Domain]]
- [[_COMMUNITY_LLM Adapter Tests|LLM Adapter Tests]]
- [[_COMMUNITY_Graph Repo Helpers|Graph Repo Helpers]]
- [[_COMMUNITY_PRD-2 Ingest Spec|PRD-2 Ingest Spec]]
- [[_COMMUNITY_ADR-2 Scope Boundaries|ADR-2 Scope Boundaries]]
- [[_COMMUNITY_API CLI Entrypoint|API CLI Entrypoint]]
- [[_COMMUNITY_PRD-4 Eval Harness|PRD-4 Eval Harness]]
- [[_COMMUNITY_OpenAI Embedding Provider|OpenAI Embedding Provider]]
- [[_COMMUNITY_Merge Mutation Apply|Merge Mutation Apply]]
- [[_COMMUNITY_Dense Search Stub|Dense Search Stub]]
- [[_COMMUNITY_API CLI Ingest|API CLI Ingest]]

## God Nodes (most connected - your core abstractions)
1. `SourceRef` - 49 edges
2. `StoredEntity` - 49 edges
3. `FakeGraph` - 49 edges
4. `GraphRepository` - 46 edges
5. `Neo4jGraphRepository` - 46 edges
6. `IngestService` - 45 edges
7. `StubGraph` - 42 edges
8. `ExtractedGraph` - 38 edges
9. `FileLoader` - 36 edges
10. `ExtractedEntity` - 33 edges

## Surprising Connections (you probably didn't know these)
- `FakeGraph` --semantically_similar_to--> `Neo4jGraphRepository (referenced)`  [INFERRED] [semantically similar]
  apps/api/tests/unit/test_ingest_service.py → /Users/jungho1000/workspace/private/opentology/apps/api/src/opentology_api/adapters/graph.py
- `StubGraph` --semantically_similar_to--> `Neo4jGraphRepository (referenced)`  [INFERRED] [semantically similar]
  apps/api/tests/unit/test_routers.py → /Users/jungho1000/workspace/private/opentology/apps/api/src/opentology_api/adapters/graph.py
- `OpenAIEmbeddingProvider` --implements--> `EmbeddingProvider Protocol`  [INFERRED]
  eval/src/opentology_eval/providers.py → /Users/jungho1000/workspace/private/opentology/eval/src/opentology_eval/providers.py
- `Entry-point reading order (PRD -> ADR -> STATUS -> specs)` --references--> `ADR Index README`  [INFERRED]
  CLAUDE.md → /Users/jungho1000/workspace/private/opentology/docs/adr/README.md
- `OpenAIEmbeddingProvider` --conceptually_related_to--> `DEFAULT_EMBEDDING_MODEL constant`  [INFERRED]
  apps/api/src/opentology_api/adapters/embedding.py → /Users/jungho1000/workspace/private/opentology/apps/api/src/opentology_api/config.py

## Import Cycles
- 1-file cycle: `apps/api/src/opentology_api/main.py -> apps/api/src/opentology_api/main.py`
- 1-file cycle: `eval/src/opentology_eval/runlog.py -> eval/src/opentology_eval/runlog.py`
- 2-file cycle: `apps/api/src/opentology_api/api/deps.py -> apps/api/src/opentology_api/main.py -> apps/api/src/opentology_api/api/deps.py`
- 2-file cycle: `apps/api/src/opentology_api/api/routers.py -> apps/api/src/opentology_api/main.py -> apps/api/src/opentology_api/api/routers.py`
- 3-file cycle: `apps/api/src/opentology_api/api/deps.py -> apps/api/src/opentology_api/main.py -> apps/api/src/opentology_api/api/routers.py -> apps/api/src/opentology_api/api/deps.py`

## Hyperedges (group relationships)
- **find_entities lexical retrieval pipeline** — api_routers_find_entities, api_routers_fuse_keyword_hits, adapters_graph_neo4jgraphrepository, adapters_graph_keywordhit, api_schemas_entitymatch [INFERRED 0.85]
- **4-step entity identity matching flow** — domain_identity_entitymatcher, domain_identity_normalize, domain_identity_cosine, adapters_graph_graphrepository, adapters_embedding_embeddingprovider [INFERRED 0.85]
- **Ingest pipeline (file → extract → match → upsert → diff)** — domain_ingest_ingestservice, adapters_llm_llmprovider, adapters_embedding_embeddingprovider, adapters_graph_graphrepository, domain_identity_entitymatcher, domain_identity_entitymerger [INFERRED 0.85]
- **4-step identity matching covered by unit + integration tests** — unit_test_entity_matcher, unit_test_ingest_service, integration_test_identity_e2e, concept_4step_identity_matching [EXTRACTED 1.00]
- **Live proof stack: real OpenAI + real Neo4j with RUN_LIVE_TESTS gate** — live_proof_alias_and_deletion, live_test_idempotency_live, live_test_live_e2e, concept_live_test_gate_run_live_tests [EXTRACTED 1.00]
- **Diff lifecycle: prior run emitted set vs new emitted set → delete/trim routing** — unit_test_diff_logic, unit_test_ingest_service, integration_test_identity_e2e, concept_diff_delete_vs_trim [EXTRACTED 1.00]
- **chunk RAG single-question pipeline (embed query -> top-k -> LLM)** — columns_chunk_rag_runner, providers_embeddingprovider_protocol, columns_chunk_rag_memoryindex, providers_llmprovider_protocol, prompts_build_chunk_rag_user [EXTRACTED 1.00]
- **Control variables shared by 3 columns (LLM + embedding model)** — config_default_llm_model, config_default_embedding_model, concept_control_variables, concept_pareto_hypothesis [EXTRACTED 1.00]
- **Strict JSON schema enforcement for choice/reasoning across both columns** — prompts_response_format_choice_reasoning, providers_openaiprovider, columns_full_context_runner, columns_chunk_rag_runner [EXTRACTED 1.00]
- **Pareto Validation Triangle (Hypothesis -> Measurement -> Harness)** — adr_0001_pareto_superiority_hypothesis, adr_0005_measurement_methodology, prd_4_evaluation_harness [EXTRACTED 1.00]
- **Graph Primitives Set (all six primitives form the MCP/REST surface)** — prd_3_get_schema_primitive, prd_3_find_entities_primitive, prd_3_get_entity_primitive, prd_3_get_neighbors_primitive, prd_3_find_path_primitive, prd_3_get_subgraph_primitive [EXTRACTED 1.00]
- **Three-way Evaluation Columns (Full-context / Chunk RAG / Opentology)** — prd_4_full_context_column, prd_4_chunk_rag_column, prd_4_opentology_column [EXTRACTED 1.00]

## Communities (52 total, 3 thin omitted)

### Community 0 - "API Layer & DI Wiring"
Cohesion: 0.05
Nodes (99): EmbeddingProvider, 텍스트 배치 → 임베딩 벡터 배치. 순서 보존., GraphRepository, KeywordHit, status='running' 으로 새 회차 노드 생성., `(:Entity)-[:EMITTED_IN]->(:IngestionRun)` 보장 (MERGE)., relation 의 `emitted_in_run_ids` 배열에 run_id 추가 (dedupe)., run 의 종결 — status + completed_at + 이번에 손댄 id 목록 기록. (+91 more)

### Community 1 - "Identity E2E Tests"
Cohesion: 0.05
Nodes (35): IngestService, RUN_LIVE_TESTS=1 gating for live tests, Short-circuit on Unchanged Source Hash, testcontainers-driven isolated Neo4j integration test, 실제 Neo4j 컨테이너 위에서 인덱스 + upsert + find 흐름.  WHY testcontainers: docker compose 스택, E2E: ingest 픽스처 → fulltext 검색 → 응답 노드 확인., repo(), test_ingest_and_find_by_keyword() (+27 more)

### Community 2 - "Live Integration Tests"
Cohesion: 0.17
Nodes (45): AdminIngestRequest, AdminIngestResponse, build_default_components(), 프로덕션 부팅 경로에서 사용. 테스트는 별도 구성., admin_ingest(), find_entities(), _fuse_keyword_hits(), healthz() (+37 more)

### Community 3 - "Routers PRD-3 Tests"
Cohesion: 0.08
Nodes (20): PRD 3 §0.3 envelope + §3.4 matches[].node/score/matched_keyword, GraphRepository, _client_with(), _make_node(), FastAPI 라우터 응답 envelope + Node 스키마 형태., PRD 3 §0.3 envelope + §3.4 matches[].node/score/matched_keyword., PRD 3 §3.5: 같은 노드가 여러 keyword 에서 surface 됐다면 가장 높은     raw 점수의 keyword 가 matched, PRD 3 §3.3: types 필터는 결과 노드의 type 이 리스트에 포함된 것만 남긴다. (+12 more)

### Community 4 - "Adapter Protocols"
Cohesion: 0.10
Nodes (29): Path, Entity Diff: delete (single source) vs trim (shared source), _EmbConstant, _EmbDeterministic, _entities_in_graph(), _LLMScripted, _make_extracted(), _make_service() (+21 more)

### Community 5 - "Chunk RAG Index"
Cohesion: 0.11
Nodes (17): 컬럼 (2) 청크 벡터 RAG — PRD 4 §2., 컬럼 (1) Full-context LLM — PRD 4 §1., Any, Question, Any, 파일 로더 — .txt / .md 만 지원. PDF·이미지는 issue #5 의존., build_chunk_rag_user(), build_full_context_user() (+9 more)

### Community 6 - "Eval Baseline Columns"
Cohesion: 0.17
Nodes (23): FullContextRunner, Path, Path, Path, LLMResult, LLMUsage, load_questions(), Option (+15 more)

### Community 7 - "Entity Matcher Core"
Cohesion: 0.16
Nodes (21): datetime, Any, Path, Path, CLI — `opentology-eval` 진입점. PRD 4 §6 의 서브커맨드 중 setup / ask / run 만.  judge / sp, ChunkRAGRunner (referenced), FullContextRunner (referenced), hash_directory() (+13 more)

### Community 8 - "Ingest Service Tests"
Cohesion: 0.17
Nodes (17): 4-Step Entity Identity Matching, Embedding Match Threshold = 0.92, EntityMatcher (referenced), _entity(), FakeEmbedder, FakeRepo, 4 단계 매처 — 각 step 의 hit / miss 동작.  테스트는 repo / embedder 를 mock 으로 주입해 step 별 분기를, 0.92 임계점 — 정확히 cosine 0.92 인 후보가 hit. (+9 more)

### Community 9 - "Test Graph Fakes"
Cohesion: 0.15
Nodes (16): EvalConfig (frozen dataclass), Path, EvalConfig, load_config(), _normalize(), 런타임 설정 — 모델 식별자는 환경 변수로 오버라이드 가능, 기본값은 코드에 고정.  WHY: PRD 4 §2.7 통제 변수 — 컬럼 (1)(2, provider 접두사 제거한 실제 API 모델 식별자., provider 접두사가 없으면 openai/ 를 붙여 canonical 형태로.      WHY: 본 베이스라인은 OpenAI 단일 provi (+8 more)

### Community 10 - "Eval CLI & Runlog"
Cohesion: 0.13
Nodes (13): Chunk, ChunkRAGRunner, _IndexEntry, _MemoryIndex, chromadb 의존을 피하기 위한 in-process 인덱스. cosine 유사도 top-k.      WHY in-memory: 측정 하니스, corpus 를 청크화하고 모든 청크를 임베딩해 인덱스에 적재., TOP_K=8 hyperparameter, amortized setup embedding tokens (+5 more)

### Community 11 - "Ingest Service Domain"
Cohesion: 0.16
Nodes (18): normalize() as identity control variable (ADR-0001), normalize(), 엔티티 이름 정규화 — *측정 통제 변수* .      동작:       1. `strip()` — 양 끝 공백 제거.       2. Unic, normalize (referenced), normalize 가 ingest 흐름 안에서 호출되는지 확인 (스모크)., test_normalize_smoke(), `normalize()` — PRD 2 §5.1 의 control variable.  WHY 케이스 분리: normalize 출력 형태가 바뀌면, # WHY: 조사/접미사 제거는 false positive 가 많아 의도적으로 안 한다. (+10 more)

### Community 12 - "Eval Columns Setup"
Cohesion: 0.22
Nodes (17): help, Path, ask(), _load_env(), 전체 실행 — 두 베이스라인 컬럼 × N runs., 청크 인덱스 setup — 임베딩 호출까지 수행, 호출 수치를 출력., 단일 질문 × 단일 컬럼 호출 (디버깅용)., run() (+9 more)

### Community 13 - "Entity Matcher Tests"
Cohesion: 0.19
Nodes (14): Path, Path, SUPPORTED_TEXT_EXTS={.txt,.md}, UnsupportedFileType exception, FileLoader, PDF / 이미지 등 아직 어댑터가 연결되지 않은 포맷., corpus 디렉토리에서 텍스트 파일을 재귀 수집., 지원 텍스트 파일만 정렬해 반환. 비지원 포맷은 *발견 시 예외*.          WHY 예외: 측정 코퍼스에 PDF/이미지가 섞여 있으면 * (+6 more)

### Community 14 - "Eval Config"
Cohesion: 0.12
Nodes (7): _backfill_normalized_names, Neo4jGraphRepository, Neo4j 5.15+ 어댑터.      WHY driver 1 개 보존: bolt 커넥션 풀은 driver 내부에서 관리된다. 매 요청, 부팅 시 idempotent 하게 인덱스 + 백필 보장.          인덱스 구성:         - fulltext (name + alia, 이번 회차가 손대지 않은 이전 emitted entity 처리.          - 노드의 source_paths 가 *오직 source_pat, 관계의 차분 — 같은 규칙. source_paths 가 단일이면 삭제, 아니면 trim., Settings

### Community 15 - "Eval File Loader"
Cohesion: 0.18
Nodes (16): Chunk RAG Baseline (800 tok / 100 overlap, cl100k_base), Path, Chunk, chunk_corpus(), _count_tokens(), 청크 분할 — PRD 4 §2.2.  규칙: 800 토큰, overlap 100, paragraph → sentence 분할. *Opentolo, 파일 리스트 → 모든 청크. files: (path, content) 의 튜플 리스트., 텍스트 → 청크 본문 리스트. 토큰 기준 800/overlap 100.      알고리즘 (paragraph → sentence):     1. (+8 more)

### Community 16 - "Name Normalization"
Cohesion: 0.22
Nodes (8): ABC, OpenAIEmbeddingProvider, 임베딩 어댑터 — 노드 임베딩 생성.  WHY 모델 식별자를 config 에서: ADR-0001 통제 변수 + ADR-0003 D2. 청크 벡터, 그래프 저장소 어댑터 — Neo4j 5.15+ 내장 인덱스 사용 (ADR-0004 D1).  핵심 책임: - ensure_indexes() —, LLM provider 어댑터 — 추출 결과를 ExtractedGraph 로 반환.  WHY 추상 + 단일 구현: PRD 2 §4 의 *교체 가, DependencyUnavailableError, 도메인 예외 — PRD 3 §9 의 에러 코드 카탈로그와 매핑., `opentology` CLI — walking skeleton 의 in-process 진입점.  WHY in-process (HTTP 가 아닌

### Community 17 - "Eval CLI Commands"
Cohesion: 0.18
Nodes (13): apps/api README — walking skeleton, Control variables — same LLM, same embedding model across columns, PRD 2 §5.1 4-step entity identity, (:IngestionRun) idempotent diff model, Pareto hypothesis (accuracy vs token cost), Walking skeleton 1% slice, DEFAULT_EMBEDDING_MODEL constant, DEFAULT_LLM_MODEL constant (+5 more)

### Community 18 - "Neo4j Repository"
Cohesion: 0.23
Nodes (13): PRD 2 §5.3 Merge Rules (aliases union, longer desc wins, existing properties win), EntityMerger (referenced), _existing(), EntityMerger — PRD 2 §5.3 의 병합 규칙 표.  embedding 은 도메인 타입 (MergeMutation) 에 *필드 자, 타입에 embedding 필드가 없어 재계산을 *원천적으로* 차단., test_aliases_union_dedupes_by_normalized(), test_description_longer_wins_new_replaces_existing(), test_description_tie_keeps_existing() (+5 more)

### Community 19 - "Entity Merger Rules"
Cohesion: 0.15
Nodes (7): `normalized_name == normalized AND type == type_` 정확 일치., ANN top-k 후보를 *embedding 포함* 으로 반환. cosine 재계산은 도메인.          type 필터는 ANN 사전 필터, 새 엔티티 노드 생성. id 는 호출자가 생성 (ULID)., 정규화 키 lookup — 노드의 정규명 OR 정규화된 alias 중 한 곳이라도 hit.          WHY OR alias 까지: PRD, ANN top-k 후보. type 사후 필터.          WHY 사후 필터: Neo4j 5.15 의 `db.index.vector.quer, 새 엔티티 — `normalized_name` 포함. id 충돌 시 IntegrityError 가 정상.          WHY chunk_in, StoredEntity

### Community 20 - "Graph Repo Lookups"
Cohesion: 0.18
Nodes (10): 3-튜플 유일성 (PRD 2 §5.5) — MERGE on (from_id, type, to_id).          WHY 동적 라벨이 아닌, SourceRef, PRD 3 §1.1: Node serialization hides embedding, now_rfc3339(), RFC 3339 (UTC) timestamp — PRD 3 §1.1 의 `format: date-time` 충족., Node model (referenced), PRD 3 §1.1 의 Node 스키마 형태 검증., test_node_minimal_serializes_per_prd() (+2 more)

### Community 21 - "Relation & Node Model"
Cohesion: 0.19
Nodes (9): EXTRACTION_RESPONSE_FORMAT (strict JSON schema), OpenAILLMProvider, OpenAI chat completion 으로 한 번 시도, 파싱 실패 시 1 회 재시도.          PRD 2 §4.3 의 재시도 정책, 본문 → 엔티티/관계 추출. 실패 시 DependencyUnavailableError., Korean extraction SYSTEM_PROMPT, _to_extracted_graph(), Any, ExtractedGraph (+1 more)

### Community 22 - "Adapters Doc Index"
Cohesion: 0.15
Nodes (13): Commerce Business Rules as Validation Domain, Latency Measurement (median + p95, controlled conditions) (D7), LLM-as-Judge with Anonymized Order (D4), MCQ + Forced Reasoning Format (D1), ADR-0005: Measurement Methodology (Accuracy, Tokens, Latency), N=3 Repetition for Reproducibility (D8), Rationale: MCQ + anonymization mitigates LLM judge position/length/self-preference bias, Spot-Check by Author for Suspicious Cases (D5) (+5 more)

### Community 23 - "LLM Adapter & Models"
Cohesion: 0.17
Nodes (10): Path, BaseSettings, get_settings(), 런타임 설정 — 환경 변수로 오버라이드, 기본값은 코드에 고정.  WHY 환경 변수 prefix `OPENTOLOGY_API_*`: `OPENT, 앱 전역 설정. uvicorn 부팅 시 한 번 로드., provider 접두사 제거한 실제 API 모델 식별자., singleton 액세서. 테스트는 monkeypatch 로 _settings 를 갈아끼울 수 있다., 테스트 격리용 — 환경 변수 패치 후 다시 로드하고 싶을 때. (+2 more)

### Community 24 - "ADR-3/4 Vector Strategy"
Cohesion: 0.20
Nodes (12): Dual Alias Normalization (ingest-time + query-time) (D3), ADR-0003: Graph Entry Point Strategy (Hybrid Lexical + Dense), Node-level Embedding (not chunk-level) (D2), Embedded Vector Index in Graph DB (D1), Embedding Model as Pluggable Adapter (D2), No Separate Vector DB Service (Pinecone/Qdrant/etc rejected), Rationale: Avoid container/sync/backup overhead during hypothesis validation; modern DBs ship production-grade vector indexes, Separation Principle: Vector Search != Separate Vector DB (D3) (+4 more)

### Community 25 - "API Skeleton Notes"
Cohesion: 0.24
Nodes (11): Hybrid Entry-Point Matching (BM25 + Dense via RRF), Rationale: Identifier-centric domains (commerce) reward BM25, but dense absorbs alias/paraphrase for portability, find_entities Primitive (lexical + dense RRF fusion), find_path Primitive (two-node path search), get_entity Primitive (single node detail), get_neighbors Primitive (N-hop expansion), get_schema Primitive (entity/relation type introspection), get_subgraph Primitive (multi-entry-point traversal) (+3 more)

### Community 26 - "Questions YAML Loader"
Cohesion: 0.27
Nodes (10): embedding_provider_dep(), graph_repo_dep(), ingest_service_dep(), llm_provider_dep(), FastAPI 의존성 — singleton service / repository 구성.  WHY 모듈 전역 + lazy: 부팅 시 호출되는 st, EmbeddingProvider, GraphRepository, IngestService (+2 more)

### Community 27 - "ADR-6 MCP Primitives"
Cohesion: 0.20
Nodes (9): settings_dep(), Settings, Typer CLI app, CLI ingest command, CLI version command, get_settings singleton, OpentologyError, 공통 베이스 — code, message, details 셋이 envelope 의 error 로 직렬화된다. (+1 more)

### Community 28 - "PRD-3 Primitives"
Cohesion: 0.28
Nodes (5): IngestionRunRecord, 같은 (path, hash) 의 성공 run 이 이미 있는지 — short-circuit 판정., 동일 source_path 의 가장 최근 성공 run — 차분 비교의 기준., `(:IngestionRun)` 노드의 슬림 표현 — 차분 알고리즘이 다루는 필드만.      `emitted_entity_ids` 는 *해당, _to_run_record()

### Community 29 - "OpenAI LLM Adapter"
Cohesion: 0.31
Nodes (8): _lucene_escape(), Lucene 특수 문자 escape — fulltext 쿼리 안전성.      WHY: keyword 에 콜론 / 따옴표가 섞이면 fulltex, _lucene_escape (referenced), Lucene escape — fulltext 쿼리 안전성., test_empty_yields_wildcard(), test_multi_token_wrapped_in_parens(), test_simple_keyword_unchanged(), test_special_chars_escaped()

### Community 30 - "ADR-1 Pareto Hypothesis"
Cohesion: 0.22
Nodes (9): Caller-side Anchor Extraction (LLM responsibility offloaded to caller), Caller Responsibility (Anchor extraction + Synthesis) (D4), Post-MVP Chat Layer as Thin Wrapper above Core (D5), Graph Primitives Only (no natural language endpoint) (D1), ADR-0006: MCP/REST Primitives Surface, Coexistence with Neo4j MCP (D6), Primitives Set: get_schema, find_entities, get_entity, get_neighbors, find_path, get_subgraph (D2), Rationale: MCP ecosystem standard pattern exposes primitives, not NL; core avoids query-time LLM dependency (+1 more)

### Community 31 - "Ingestion Run Records"
Cohesion: 0.31
Nodes (9): Corpus Tiny: Catalog (Product A/B, Category C/D), Corpus Tiny: Coupon Policy (Coupon X/Y, aliases), Domain Entity: Category C (contains Product A), Domain Entity: Coupon X (with aliases), Domain Entity: Product A, Domain Entity: Promotion P (applies to Category C only), Corpus Tiny: Promotion Policy (Promotion P/Q, Category C/D), questions.yaml Schema (Question + Option with failure_mode_tested) (+1 more)

### Community 32 - "Lucene Escape"
Cohesion: 0.32
Nodes (7): _extract_source_refs(), _node_to_response(), _node_to_stored(), fulltext 인덱스를 *keyword 별로* 따로 호출.          WHY keyword 별 분리: PRD 3 §3.4 의 `match, neo4j Node → StoredEntity (내부)., neo4j Node → 응답 Node (embedding 제외)., Any

### Community 33 - "ADR-5 Measurement"
Cohesion: 0.25
Nodes (8): One-page Report as MVP Exit Condition (D7), Opentology Project Identity (Graph KB tool for LLMs), Pareto Superiority Hypothesis (accuracy = full-context, tokens > chunk RAG), ADR-0001: Project Identity and MVP Validation Hypothesis, Rationale: Long-context LLMs make efficiency the differentiator, 3-way Measurement (Full-context vs Chunk RAG vs Opentology), PRD 1: MVP Spec, MVP In-Scope Items (ingest, graph load, hybrid index, primitives, deliverables)

### Community 34 - "Corpus Tiny Domain"
Cohesion: 0.29
Nodes (7): Idempotent Ingestion (D6), Chunk Only When Context Window Exceeded (§3), Diff-Apply Re-ingest for Idempotency (§5.4), Entity Identity Algorithm (4-step: normalized name -> alias -> embedding sim -> new), Entity/Relation Extraction JSON Schema (§4.3), PRD 2: Ingest Specification, skeleton_sample.md (test fixture: 여름 환영 쿠폰 entities)

### Community 35 - "LLM Adapter Tests"
Cohesion: 0.33
Nodes (7): Entity/Relation Audit Log deferred (D5), Auth/Access Control/Multi-tenant deferred (D2, post-MVP rank 1), Chat / Multi-turn Sessions deferred (D3), Eval Gate / CI Integration deferred (D6), Frontend (Web UI) entirely out of scope (D1), ADR-0002: MVP Scope Boundaries, Rationale: Each in-scope item adds direct + indirect cognitive cost to hypothesis verification

### Community 36 - "Graph Repo Helpers"
Cohesion: 0.38
Nodes (7): OpenAI gpt-4.1 chosen for 1M context, Eval Package README (baseline columns 1+2), text-embedding-3-small (1536-dim) as shared embedding, Column 2: Chunk Vector RAG Baseline, PRD 4: Evaluation Harness (3-way), Column 1: Full-context LLM Harness, Judge Anonymization (A/B/C, randomized order)

### Community 37 - "PRD-2 Ingest Spec"
Cohesion: 0.29
Nodes (7): Repo entry-point CLAUDE.md, Entry-point reading order (PRD -> ADR -> STATUS -> specs), legacy-opentology reference policy (do not consult), Public artifact accessibility rule (self-contained issues/ADRs), Session role modes (orchestrator vs worker), Worker mode end-of-task checklist (PR + Closes #N), Writing tone policy (no jargon, no colloquial verbs)

### Community 38 - "ADR-2 Scope Boundaries"
Cohesion: 0.40
Nodes (3): `EntityMerger` 결과를 한 트랜잭션으로 set. embedding/normalized_name 은 변경 없음., 병합 — aliases/description/source_refs/updated_at 만 갱신.          WHY source_refs 를, MergeMutation

### Community 39 - "API CLI Entrypoint"
Cohesion: 0.40
Nodes (3): dense 매칭 — walking skeleton 에서는 미구현.          WHY stub: PRD 3 §3.5 + ADR-0003 D1, Node, NotImplementedError

### Community 40 - "PRD-4 Eval Harness"
Cohesion: 0.40
Nodes (5): help, Path, Argument, ingest(), 단일 파일 → 엔티티/관계 추출 → Neo4j 적재.

### Community 42 - "Merge Mutation Apply"
Cohesion: 0.67
Nodes (3): Path, corpus_dir(), questions_path()

## Knowledge Gaps
- **74 isolated node(s):** `Settings`, `Any`, `IngestService`, `Path`, `Argument` (+69 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `datetime` connect `Entity Matcher Core` to `API Layer & DI Wiring`?**
  _High betweenness centrality (0.261) - this node is a cross-community bridge._
- **Why does `Neo4jGraphRepository` connect `Eval Config` to `API Layer & DI Wiring`, `Lucene Escape`, `Live Integration Tests`, `Identity E2E Tests`, `Adapter Protocols`, `ADR-2 Scope Boundaries`, `API CLI Entrypoint`, `PRD-4 Eval Harness`, `Name Normalization`, `Eval CLI Commands`, `Entity Merger Rules`, `Graph Repo Lookups`, `LLM Adapter & Models`, `Questions YAML Loader`, `ADR-6 MCP Primitives`, `PRD-3 Primitives`, `OpenAI LLM Adapter`?**
  _High betweenness centrality (0.120) - this node is a cross-community bridge._
- **Why does `GraphRepository` connect `API Layer & DI Wiring` to `Live Integration Tests`, `Routers PRD-3 Tests`, `ADR-2 Scope Boundaries`, `API CLI Entrypoint`, `Eval Config`, `Name Normalization`, `Entity Merger Rules`, `Graph Repo Lookups`, `Questions YAML Loader`, `PRD-3 Primitives`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Are the 37 inferred relationships involving `SourceRef` (e.g. with `EmbeddingProvider` and `GraphRepository`) actually correct?**
  _`SourceRef` has 37 INFERRED edges - model-reasoned connections that need verification._
- **Are the 40 inferred relationships involving `StoredEntity` (e.g. with `EmbeddingProvider` and `GraphRepository`) actually correct?**
  _`StoredEntity` has 40 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `FakeGraph` (e.g. with `EmbeddingProvider` and `GraphRepository`) actually correct?**
  _`FakeGraph` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 17 inferred relationships involving `GraphRepository` (e.g. with `ExtractedGraph` and `IngestService`) actually correct?**
  _`GraphRepository` has 17 INFERRED edges - model-reasoned connections that need verification._