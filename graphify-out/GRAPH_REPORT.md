# Graph Report - primitives-five  (2026-06-17)

## Corpus Check
- 91 files · ~61,639 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1604 nodes · 4090 edges · 107 communities (97 shown, 10 thin omitted)
- Extraction: 59% EXTRACTED · 41% INFERRED · 0% AMBIGUOUS · INFERRED: 1670 edges (avg confidence: 0.52)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `bc1f5f2f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

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
- [[_COMMUNITY_Live Tests Conftest|Live Tests Conftest]]
- [[_COMMUNITY_Eval Tests Conftest|Eval Tests Conftest]]
- [[_COMMUNITY_API Package Init|API Package Init]]
- [[_COMMUNITY_Columns Init|Columns Init]]
- [[_COMMUNITY_Eval Package Init|Eval Package Init]]
- [[_COMMUNITY_Init Stub 50|Init Stub 50]]
- [[_COMMUNITY_Init Stub 51|Init Stub 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 88|Community 88]]
- [[_COMMUNITY_Community 89|Community 89]]
- [[_COMMUNITY_Community 90|Community 90]]
- [[_COMMUNITY_Community 91|Community 91]]
- [[_COMMUNITY_Community 92|Community 92]]
- [[_COMMUNITY_Community 93|Community 93]]
- [[_COMMUNITY_Community 94|Community 94]]
- [[_COMMUNITY_Community 95|Community 95]]
- [[_COMMUNITY_Community 96|Community 96]]
- [[_COMMUNITY_Community 97|Community 97]]
- [[_COMMUNITY_Community 98|Community 98]]
- [[_COMMUNITY_Community 99|Community 99]]

## God Nodes (most connected - your core abstractions)
1. `SourceRef` - 71 edges
2. `FakeGraph` - 71 edges
3. `ExtractedGraph` - 70 edges
4. `GraphRepository` - 66 edges
5. `PrimitiveStubGraph` - 56 edges
6. `StubGraph` - 55 edges
7. `ExtractedEntity` - 54 edges
8. `StoredEntity` - 51 edges
9. `ExtractedRelation` - 48 edges
10. `EmbeddingProvider` - 47 edges

## Surprising Connections (you probably didn't know these)
- `repo()` --calls--> `Neo4jGraphRepository`  [INFERRED]
  apps/api/tests/integration/test_identity_e2e.py → apps/api/src/opentology_api/adapters/graph.py
- `repo()` --calls--> `Neo4jGraphRepository`  [INFERRED]
  apps/api/tests/integration/test_neo4j_repo.py → apps/api/src/opentology_api/adapters/graph.py
- `IngestService` --uses--> `IngestTaskRegistry`  [INFERRED]
  apps/api/src/opentology_api/api/deps.py → apps/api/src/opentology_api/api/admin_tasks.py
- `IngestTaskRegistry` --uses--> `IngestTaskRegistry`  [INFERRED]
  apps/api/src/opentology_api/api/deps.py → apps/api/src/opentology_api/api/admin_tasks.py
- `_EmbDeterministic` --semantically_similar_to--> `FakeEmbedder`  [INFERRED] [semantically similar]
  apps/api/tests/integration/test_identity_e2e.py → apps/api/tests/unit/test_ingest_service.py

## Import Cycles
- 1-file cycle: `apps/api/src/opentology_api/main.py -> apps/api/src/opentology_api/main.py`
- 1-file cycle: `eval/src/opentology_eval/runlog.py -> eval/src/opentology_eval/runlog.py`
- 2-file cycle: `apps/api/src/opentology_api/api/routers.py -> apps/api/src/opentology_api/main.py -> apps/api/src/opentology_api/api/routers.py`

## Communities (107 total, 10 thin omitted)

### Community 0 - "API Layer & DI Wiring"
Cohesion: 0.13
Nodes (113): AdminIngestRequest, AdminIngestResponse, AdminIngestStatusResponse, IngestTaskRegistry, IngestTaskState, _on_progress(), Admin ingest 의 비동기 작업 registry — PRD 2 §1.2 + §1.3.  구조:   POST /admin/ingest →, worker thread 진입점 — 동기 ingest 흐름 + state 종결.      error code 명명: exception 타입 이름 (+105 more)

### Community 1 - "Identity E2E Tests"
Cohesion: 0.23
Nodes (45): EmbeddingProvider, DenseHit, EntityTypeStat, EntityWithCounts, KeywordHit, NeighborhoodResult, PathResult, 확장 결과 — 진입점 포함 노드 + 이번 확장 경계 내 엣지.      truncated 는 max_nodes 초과 여부. 어댑터가 *진입점에서 (+37 more)

### Community 2 - "Live Integration Tests"
Cohesion: 0.07
Nodes (19): _client_with(), _make_node(), FastAPI 라우터 응답 envelope + Node 스키마 형태., PRD 3 §0.3 envelope + §3.4 matches[].node/score/matched_keyword., PRD 3 §3.5: 같은 노드가 여러 keyword 에서 surface 됐다면 가장 높은     raw 점수의 keyword 가 matched, PRD 3 §3.3: types 필터는 결과 노드의 type 이 리스트에 포함된 것만 남긴다., PRD 3 §3.3: limit 적용 (기본 10, max 50)., find_by_keywords_scored 가 KeywordHit 리스트를 반환하도록 stub.      `hits_by_keyword` 가 비 (+11 more)

### Community 3 - "Routers PRD-3 Tests"
Cohesion: 0.07
Nodes (39): _apply_overlap(), chunk_text(), count_tokens(), _encoder(), _force_split_by_tokens(), _pack_into_budget(), LLM 컨텍스트 초과 시 텍스트를 청크로 분할 — PRD 2 §3.  흐름:   count_tokens(text) → 컨텍스트의 70% 이하면, 폴백 분할 — 큰 단위에서 작은 단위로 단계적으로 내려간다.      각 단위에서 *한 단위가 budget 을 넘으면* 다음 작은 단위로 그 안 (+31 more)

### Community 4 - "Adapter Protocols"
Cohesion: 0.15
Nodes (41): EmbeddingProvider, ExtractedGraph, GraphRepository, LLMProvider, Path, SourceRef, Path, StoredEntity (+33 more)

### Community 5 - "Chunk RAG Index"
Cohesion: 0.13
Nodes (30): Path, Path, crawl(), CrawlSummary, _is_excluded_dir(), _load_ignore_spec(), 디렉토리 재귀 수집 — PRD 2 §2.  흐름:   crawl(root) → root 아래 .txt / .md 파일을 정렬된 순서로 yield, 디렉토리를 재귀 탐색하며 자동 제외 + spec 매칭을 즉시 적용.      WHY Path.rglob 가 아닌 수동 재귀: rglob 은 디렉 (+22 more)

### Community 6 - "Eval Baseline Columns"
Cohesion: 0.24
Nodes (19): ExtractedGraph, Path, _build(), IngestService.ingest_directory — 디렉토리 모드 + 진행 콜백 + dry-run.  청크 분할은 별도 test_inge, dry-run — LLM 호출은 일어나지만 그래프에 노드가 생성되지 않는다., PDF / 이미지는 follow-up #5 — files_pending_skipped 로 분리 카운트., `.opentologyignore` 의 패턴이 파일을 제외한다., 디렉토리 안의 .md + .txt 가 모두 처리된다. (+11 more)

### Community 7 - "Entity Matcher Core"
Cohesion: 0.17
Nodes (13): Path, Path, Path, load_questions(), Option, Question, QuestionSet, questions.yaml 로더 — PRD 5 §3.1 스키마. (+5 more)

### Community 8 - "Ingest Service Tests"
Cohesion: 0.20
Nodes (14): Path, Chunk, chunk_corpus(), _count_tokens(), 청크 분할 — PRD 4 §2.2.  규칙: 800 토큰, overlap 100, paragraph → sentence 분할. *Opentolo, 파일 리스트 → 모든 청크. files: (path, content) 의 튜플 리스트., 텍스트 → 청크 본문 리스트. 토큰 기준 800/overlap 100.      알고리즘 (paragraph → sentence):     1., _split_paragraphs() (+6 more)

### Community 9 - "Test Graph Fakes"
Cohesion: 0.26
Nodes (15): ChunkRAGRunner, Any, Path, LLMResult, LLMResult, LLMUsage, _fake_embedder(), _fake_llm_result() (+7 more)

### Community 10 - "Eval CLI & Runlog"
Cohesion: 0.11
Nodes (27): FileProgressEvent, help, IngestService, Option, Path, FileProgressEvent, Argument, _format_progress_line() (+19 more)

### Community 11 - "Ingest Service Domain"
Cohesion: 0.18
Nodes (9): OpenAIEmbeddingProvider, Settings, DependencyUnavailableError, OpentologyError, RateLimitedError, 도메인 예외 — PRD 3 §9 의 에러 코드 카탈로그와 매핑.  코드 표 (PRD 3 §9):  | HTTP | code, 공통 베이스 — code, message, details 셋이 envelope 의 error 로 직렬화된다., post-MVP. MVP 에서는 사용 안 함 — 코드 카탈로그 형태만 미리 정의.      WHY 미리 정의: PRD 3 §9 의 카탈로그를 * (+1 more)

### Community 12 - "Eval Columns Setup"
Cohesion: 0.32
Nodes (5): _count_entities(), _count_relations(), Live idempotency — 실제 OpenAI + 실제 Neo4j (compose 스택) 위에서.  RUN_LIVE_TESTS=1 일 때만, 두 번 ingest — entity/relation 카운트 불변., test_reingest_same_file_keeps_counts_constant()

### Community 13 - "Entity Matcher Tests"
Cohesion: 0.14
Nodes (25): Path, _EmbDeterministic, _entities_in_graph(), _LLMScripted, _make_extracted(), _make_service(), 4 단계 동일성 + 차분 — 실 Neo4j 위에서 끝에서 끝까지.  WHY testcontainers: Cypher 쿼리 형태와 인덱스 동작은, 이름별로 서로 멀어지는 벡터 — Step 3 매칭 의도적 회피. (+17 more)

### Community 14 - "Eval Config"
Cohesion: 0.16
Nodes (26): IngestionRunRecord, `(:IngestionRun)` 노드의 슬림 표현 — 차분 알고리즘이 다루는 필드만.      `emitted_entity_ids` 는 *해당, _to_run_record(), ExtractedGraph, IngestService, Path, _build_service(), FakeEmbedder (+18 more)

### Community 15 - "Eval File Loader"
Cohesion: 0.12
Nodes (31): datetime, help, Option, Path, Any, Path, Path, ask() (+23 more)

### Community 16 - "Name Normalization"
Cohesion: 0.11
Nodes (10): `normalized_name == normalized AND type == type_` 정확 일치., ANN top-k 후보를 *embedding 포함* 으로 반환. cosine 재계산은 도메인.          type 필터는 ANN 사전 필터, 새 엔티티 노드 생성. id 는 호출자가 생성 (ULID)., run 의 종결 — status + completed_at + 이번에 손댄 id 목록 기록., 이전 회차의 emitted entity 중 이번 회차가 touch 하지 않은 것 처리.          반환값 — "deleted" 또는 "tr, 여러 진입점 N-hop union. 노드/엣지 dedupe.          잘림 정책: 진입점들 중 *최단 거리* 기준 (multi-sourc, 정규화 키 lookup — 노드의 정규명 OR 정규화된 alias 중 한 곳이라도 hit.          WHY OR alias 까지: PRD, ANN top-k 후보. type 사후 필터.          WHY 사후 필터: Neo4j 5.15 의 `db.index.vector.quer (+2 more)

### Community 17 - "Eval CLI Commands"
Cohesion: 0.16
Nodes (15): EmbeddingProvider, GraphRepository, MergeMutation, SourceRef, StoredEntity, _cosine(), MatchResult, 엔티티 동일성 4 단계 + 병합 규칙 — PRD 2 §5.1 ~ §5.3.  이 모듈은 *순수 도메인 로직* 만 담는다. I/O 는 `Graph (+7 more)

### Community 18 - "Neo4j Repository"
Cohesion: 0.19
Nodes (14): Path, _build_large_doc(), ChunkAwareFakeLLM, IngestService 가 본문을 청크 분할해서 LLM 을 *청크 단위로* 호출하는지 검증.  작은 model_context_tokens 를, 같은 엔티티 B 가 두 청크에서 등장 — source_refs 에 두 ref (서로 다른     chunk_index) 가 누적되어야 한다 (P, 같은 큰 파일 두 번 ingest — 두 번째는 short-circuit (LLM 호출 추가 0)., 청크 본문 안의 marker 를 보고 다른 ExtractedGraph 를 돌려준다.      chunk 1: {A, B}     chunk 2:, heading 두 개 — 각각 MARK_ONE / MARK_TWO 를 포함한 본문. (+6 more)

### Community 19 - "Entity Merger Rules"
Cohesion: 0.10
Nodes (30): normalize(), 엔티티 이름 정규화 — *측정 통제 변수* .      동작:       1. `strip()` — 양 끝 공백 제거.       2. Unic, _entity(), FakeEmbedder, FakeRepo, 4 단계 매처 — 각 step 의 hit / miss 동작.  테스트는 repo / embedder 를 mock 으로 주입해 step 별 분기를, 0.92 임계점 — 정확히 cosine 0.92 인 후보가 hit., 0.91999 — threshold 미만 → step 3 miss → step 4. (+22 more)

### Community 20 - "Graph Repo Lookups"
Cohesion: 0.17
Nodes (14): Path, Path, NotImplementedError, FileLoader, 파일 로더 — .txt / .md 만 지원. PDF·이미지는 issue #5 의존., PDF / 이미지 등 아직 어댑터가 연결되지 않은 포맷., corpus 디렉토리에서 텍스트 파일을 재귀 수집., 지원 텍스트 파일만 정렬해 반환. 비지원 포맷은 *발견 시 예외*.          WHY 예외: 측정 코퍼스에 PDF/이미지가 섞여 있으면 * (+6 more)

### Community 21 - "Relation & Node Model"
Cohesion: 0.10
Nodes (9): Neo4jGraphRepository, Neo4j 5.15+ 어댑터.      WHY driver 1 개 보존: bolt 커넥션 풀은 driver 내부에서 관리된다. 매 요청, 부팅 시 idempotent 하게 인덱스 + 백필 보장.          인덱스 구성:         - fulltext (name + alia, 이번 회차가 손대지 않은 이전 emitted entity 처리.          - 노드의 source_paths 가 *오직 source_pat, 관계의 차분 — 같은 규칙. source_paths 가 단일이면 삭제, 아니면 trim., Path, main(), PR 본문용 proof — 컨테이너화된 Neo4j + 실제 OpenAI 위에서 alias 병합과 삭제 차분의 결과를 stdout 으로 찍는다. (+1 more)

### Community 22 - "Adapters Doc Index"
Cohesion: 0.06
Nodes (35): _fuse_with_rrf(), RRF (Reciprocal Rank Fusion, k=60) — PRD 3 §3.5.      각 keyword 별로 별도 rank list, _client_with(), _make_edge(), _make_node(), PrimitiveStubGraph, 5 primitive 라우터 + RRF + 에러 envelope — PRD 3 §2-7, §9.  본 파일은 *단위 테스트* — 실제 Neo4j, 단일 keyword + lexical-only 1 hit → score 1.0 (max-normalize). (+27 more)

### Community 23 - "LLM Adapter & Models"
Cohesion: 0.08
Nodes (6): StoredEntity, IngestionRunRecord, fake_graph(), FakeGraph, In-memory 그래프 — 4 단계 매처 + 차분 검증에 충분한 동작., _record()

### Community 24 - "ADR-3/4 Vector Strategy"
Cohesion: 0.25
Nodes (15): FakeGraph, Path, TestClient, _client(), Admin ingest 비동기 응답 — PRD 2 §1.2 + §1.3.  POST /admin/ingest → 202 + { task_id,, 라이브 ingest 흐름을 fake adapter 위에 띄운다., GET status 를 폴링해 target state 에 도달할 때까지 대기., PRD 2 §1.2 — 202 + { task_id, status_url } 응답. (+7 more)

### Community 25 - "API Skeleton Notes"
Cohesion: 0.19
Nodes (10): EvalConfig, load_config(), _normalize(), 런타임 설정 — 모델 식별자는 환경 변수로 오버라이드 가능, 기본값은 코드에 고정.  WHY: PRD 4 §2.7 통제 변수 — 컬럼 (1)(2, provider 접두사 제거한 실제 API 모델 식별자., provider 접두사가 없으면 openai/ 를 붙여 canonical 형태로.      WHY: 본 베이스라인은 OpenAI 단일 provi, 환경 변수에서 설정 로드. .env 는 호출자가 미리 로드한다., test_default_models_pin_control_variables() (+2 more)

### Community 26 - "Questions YAML Loader"
Cohesion: 0.27
Nodes (9): IngestService, _CallRecorder, _make_prior(), _make_service_with(), 차분 적용 — 이전 회차 emitted set 과 새 회차 emitted set 의 차이가 어떻게 delete / trim / no-op 로 매, 이번 회차에서 다시 emit 된 엔티티/관계는 차분 콜백을 건드리지 않는다., test_diff_kept_entities_are_not_passed_to_repo(), test_diff_no_prior_run_is_noop() (+1 more)

### Community 27 - "ADR-6 MCP Primitives"
Cohesion: 0.29
Nodes (11): _existing(), EntityMerger — PRD 2 §5.3 의 병합 규칙 표.  embedding 은 도메인 타입 (MergeMutation) 에 *필드 자, 타입에 embedding 필드가 없어 재계산을 *원천적으로* 차단., test_aliases_union_dedupes_by_normalized(), test_description_longer_wins_new_replaces_existing(), test_description_tie_keeps_existing(), test_mutation_has_no_embedding_field(), test_properties_existing_wins_on_conflict() (+3 more)

### Community 28 - "PRD-3 Primitives"
Cohesion: 0.11
Nodes (17): Commerce Business Rules as Validation Domain, One-page Report as MVP Exit Condition (D7), Opentology Project Identity (Graph KB tool for LLMs), Pareto Superiority Hypothesis (accuracy = full-context, tokens > chunk RAG), Rationale: Long-context LLMs make efficiency the differentiator, 3-way Measurement (Full-context vs Chunk RAG vs Opentology), Latency Measurement (median + p95, controlled conditions) (D7), LLM-as-Judge with Anonymized Order (D4) (+9 more)

### Community 29 - "OpenAI LLM Adapter"
Cohesion: 0.18
Nodes (10): FullContextRunner, 컬럼 (1) Full-context LLM — PRD 4 §1., Any, Question, Any, Question, build_chunk_rag_user(), build_full_context_user() (+2 more)

### Community 30 - "ADR-1 Pareto Hypothesis"
Cohesion: 0.23
Nodes (7): OpenAILLMProvider, LLM provider 어댑터 — 추출 결과를 ExtractedGraph 로 반환.  WHY 추상 + 단일 구현: PRD 2 §4 의 *교체 가, OpenAI chat completion 으로 한 번 시도, 파싱 실패 시 1 회 재시도.          PRD 2 §4.3 의 재시도 정책, 본문 → 엔티티/관계 추출. 실패 시 DependencyUnavailableError., _to_extracted_graph(), Any, ExtractedGraph

### Community 31 - "Ingestion Run Records"
Cohesion: 0.29
Nodes (8): Embedded Vector Index in Graph DB (D1), Embedding Model as Pluggable Adapter (D2), No Separate Vector DB Service (Pinecone/Qdrant/etc rejected), Rationale: Avoid container/sync/backup overhead during hypothesis validation; modern DBs ship production-grade vector indexes, Separation Principle: Vector Search != Separate Vector DB (D3), ADR-0004: Vector Infra (Graph DB internal index, no separate vector DB), Neo4j 5.15-community Service (vector + fulltext index in one DB), docker-compose.yml (neo4j 5.15 + api)

### Community 32 - "Lucene Escape"
Cohesion: 0.32
Nodes (5): EmbeddingProvider, EmbeddingResult, LLMProvider, LLM / 임베딩 provider 추상화 — 테스트에서 mock 으로 갈아끼우기 위한 최소 인터페이스., Protocol

### Community 33 - "ADR-5 Measurement"
Cohesion: 0.24
Nodes (10): Hybrid Entry-Point Matching (BM25 + Dense via RRF), Rationale: Identifier-centric domains (commerce) reward BM25, but dense absorbs alias/paraphrase for portability, find_entities Primitive (lexical + dense RRF fusion), find_path Primitive (two-node path search), get_entity Primitive (single node detail), get_neighbors Primitive (N-hop expansion), get_schema Primitive (entity/relation type introspection), get_subgraph Primitive (multi-entry-point traversal) (+2 more)

### Community 34 - "Corpus Tiny Domain"
Cohesion: 0.36
Nodes (7): _lucene_escape(), Lucene 특수 문자 escape — fulltext 쿼리 안전성.      WHY: keyword 에 콜론 / 따옴표가 섞이면 fulltex, Lucene escape — fulltext 쿼리 안전성., test_empty_yields_wildcard(), test_multi_token_wrapped_in_parens(), test_simple_keyword_unchanged(), test_special_chars_escaped()

### Community 35 - "LLM Adapter Tests"
Cohesion: 0.08
Nodes (23): 1. .env 준비, 2. 인프라 + API 기동, 3. 단일 파일 ingest, 4. find_entities 호출, 4 단계 동일성, apps/api — Opentology Walking Skeleton, Neo4j 5.15+ Community, OpenAI gpt-4.1 + text-embedding-3-small (+15 more)

### Community 36 - "Graph Repo Helpers"
Cohesion: 0.20
Nodes (6): BaseSettings, _EmbConstant, 이름 무관하게 같은 벡터 — 임베딩 유사도 1.0 → Step 3 항상 hit.      Step 3 분기 검증용. 다른 시나리오는 _EmbDe, 앱 전역 설정. uvicorn 부팅 시 한 번 로드., provider 접두사 제거한 실제 API 모델 식별자., Settings

### Community 37 - "PRD-2 Ingest Spec"
Cohesion: 0.20
Nodes (6): 실제 Neo4j 컨테이너 위에서 인덱스 + upsert + find 흐름.  WHY testcontainers: docker compose 스택, #6 — dense path 활성화. 임의 query vector 에 대해 ANN 결과 (혹은 빈) 반환.      cosine 매치를 강제할, E2E: ingest 픽스처 → fulltext 검색 → 응답 노드 확인., repo(), test_find_entities_dense_returns_dense_hits(), test_ingest_and_find_by_keyword()

### Community 38 - "ADR-2 Scope Boundaries"
Cohesion: 0.06
Nodes (15): ABC, 임베딩 어댑터 — 노드 임베딩 생성.  WHY 모델 식별자를 config 에서: ADR-0001 통제 변수 + ADR-0003 D2. 청크 벡터, GraphRepository, 같은 (path, hash) 의 성공 run 이 이미 있는지 — short-circuit 판정., 동일 source_path 의 가장 최근 성공 run — 차분 비교의 기준., status='running' 으로 새 회차 노드 생성., `(:Entity)-[:EMITTED_IN]->(:IngestionRun)` 보장 (MERGE)., relation 의 `emitted_in_run_ids` 배열에 run_id 추가 (dedupe). (+7 more)

### Community 39 - "API CLI Entrypoint"
Cohesion: 0.16
Nodes (12): Caller-side Anchor Extraction (LLM responsibility offloaded to caller), Dual Alias Normalization (ingest-time + query-time) (D3), ADR-0003: Graph Entry Point Strategy (Hybrid Lexical + Dense), Node-level Embedding (not chunk-level) (D2), Caller Responsibility (Anchor extraction + Synthesis) (D4), Post-MVP Chat Layer as Thin Wrapper above Core (D5), Graph Primitives Only (no natural language endpoint) (D1), Coexistence with Neo4j MCP (D6) (+4 more)

### Community 40 - "PRD-4 Eval Harness"
Cohesion: 0.21
Nodes (9): 상품 카탈로그, 쿠폰 정책, Domain Entity: Category C (contains Product A), Domain Entity: Coupon X (with aliases), Domain Entity: Product A, Domain Entity: Promotion P (applies to Category C only), 프로모션 정책, questions.yaml Schema (Question + Option with failure_mode_tested) (+1 more)

### Community 41 - "OpenAI Embedding Provider"
Cohesion: 0.14
Nodes (13): MVP In-Scope Items (ingest, graph load, hybrid index, primitives, deliverables), In scope (이번에 만든다), MVP 범위, MVP가 검증하려는 가설 — Pareto 우월, Out of scope (이번에는 안 만든다 — post-MVP로 이월), 개요, 그래프 적재, 그래프 진입점 매칭 (+5 more)

### Community 42 - "Merge Mutation Apply"
Cohesion: 0.32
Nodes (5): _count_entities(), _count_relations(), Live directory ingest — 디렉토리 모드 + 청크 분할 두 가지를 한 번에 검증.  RUN_LIVE_TESTS=1 일 때만 실행, 디렉토리 두 번 → count 불변 + 큰 파일 청크 분할이 정상 동작., test_directory_ingest_is_idempotent_and_includes_chunked_file()

### Community 43 - "Dense Search Stub"
Cohesion: 0.29
Nodes (6): Idempotent Ingestion (D6), Chunk Only When Context Window Exceeded (§3), Diff-Apply Re-ingest for Idempotency (§5.4), Entity Identity Algorithm (4-step: normalized name -> alias -> embedding sim -> new), Entity/Relation Extraction JSON Schema (§4.3), skeleton_sample.md (test fixture: 여름 환영 쿠폰 entities)

### Community 44 - "API CLI Ingest"
Cohesion: 0.33
Nodes (6): Entity/Relation Audit Log deferred (D5), Auth/Access Control/Multi-tenant deferred (D2, post-MVP rank 1), Chat / Multi-turn Sessions deferred (D3), Eval Gate / CI Integration deferred (D6), Frontend (Web UI) entirely out of scope (D1), Rationale: Each in-scope item adds direct + indirect cognitive cost to hypothesis verification

### Community 45 - "Live Tests Conftest"
Cohesion: 0.21
Nodes (9): 3-튜플 유일성 (PRD 2 §5.5) — MERGE on (from_id, type, to_id).          WHY 동적 라벨이 아닌, now_rfc3339(), RFC 3339 (UTC) timestamp — PRD 3 §1.1 의 `format: date-time` 충족., _edge(), _node(), PRD 3 §1.1 의 Node 스키마 형태 검증., test_node_minimal_serializes_per_prd(), test_node_rejects_bad_ulid() (+1 more)

### Community 46 - "Eval Tests Conftest"
Cohesion: 0.22
Nodes (9): OpenAI gpt-4.1 chosen for 1M context, Opentology MVP — 평가 하니스 (베이스라인 두 컬럼), 실행 방법, 왜 이 provider / 모델인가, 응답 JSON 스키마, text-embedding-3-small (1536-dim) as shared embedding, Column 2: Chunk Vector RAG Baseline, Column 1: Full-context LLM Harness (+1 more)

### Community 47 - "API Package Init"
Cohesion: 0.33
Nodes (6): Repo entry-point CLAUDE.md, legacy-opentology reference policy (do not consult), Public artifact accessibility rule (self-contained issues/ADRs), Session role modes (orchestrator vs worker), Worker mode end-of-task checklist (PR + Closes #N), Writing tone policy (no jargon, no colloquial verbs)

### Community 48 - "Columns Init"
Cohesion: 0.40
Nodes (3): `EntityMerger` 결과를 한 트랜잭션으로 set. embedding/normalized_name 은 변경 없음., 병합 — aliases/description/source_refs/updated_at 만 갱신.          WHY source_refs 를, MergeMutation

### Community 49 - "Eval Package Init"
Cohesion: 0.09
Nodes (21): _build_neighbor_expand_cypher(), _extract_source_refs(), _node_to_response(), _node_to_stored(), 그래프 저장소 어댑터 — Neo4j 5.15+ 내장 인덱스 사용 (ADR-0004 D1).  핵심 책임: - ensure_indexes() —, 단일 노드 + outgoing/incoming relation type 카운트.          WHY 한 트랜잭션 / 세 쿼리: pydanti, N-hop BFS — 진입점에서 거리 가까운 순으로 max_nodes 절단.          WHY variable-length match 가, multi-source BFS — 여러 진입점에서 동시에 확장.          잘림 정책: *진입점 집합으로부터의 최단 거리* 기준 가까운 순 (+13 more)

### Community 52 - "Community 52"
Cohesion: 0.67
Nodes (3): Path, corpus_dir(), questions_path()

### Community 55 - "Community 55"
Cohesion: 0.06
Nodes (36): 0. 책임 분리, 10. Out of scope (MVP 에서 안 만드는 ingest 기능), 1.1 CLI, 1.2 Admin REST 엔드포인트, 1.3 작업 상태 조회, 1. 입력 인터페이스, 2.1 지원 파일 포맷 (MVP), 2.2 재귀 규칙 (+28 more)

### Community 56 - "Community 56"
Cohesion: 0.07
Nodes (28): ADR-0005: MVP 측정 방법론 — 정확도, 토큰, 지연, Consequences, Considered Options, Context — 왜 이 결정이 필요했나, D10. 보고서 형식 — 한 장, D1. 질문 형식 — MCQ + 이유 서술, D2. 시스템 응답 형식 — 강제 JSON, D3. 정확도 채점 — 3 차원, 총 0-4 점 (+20 more)

### Community 57 - "Community 57"
Cohesion: 0.07
Nodes (26): (a) 어휘 매칭 (BM25 / 희소 검색), ADR-0003: 그래프 진입점 선정 전략 — 어휘 매칭 + dense 임베딩 하이브리드, (b) 밀집 벡터 (dense 단독), (c) 하이브리드 (BM25 + 밀집), Consequences, Considered Options, Context — 왜 이 결정이 필요했나, D1. 진입점 선정 = (caller 의 anchor 추출) + (Opentology 의 하이브리드 매칭) (+18 more)

### Community 58 - "Community 58"
Cohesion: 0.08
Nodes (3): GraphRepository, FakeGraph, 단순 in-memory 그래프 — 노드 + 엣지 + 사전 정의된 lexical/dense hits.

### Community 59 - "Community 59"
Cohesion: 0.08
Nodes (24): ADR-0006: MCP/REST 표면 — Graph Primitives, 자연어 미수용, Consequences, Considered Options, Context — 왜 이 결정이 필요했나, D1. MCP 와 REST 모두 graph primitives 만 노출, D2. Primitives 집합 (MVP), D3. Write 작업은 MCP 에 노출하지 않음, D4. Caller 의 책임 — 의도 해석과 합성 (+16 more)

### Community 60 - "Community 60"
Cohesion: 0.09
Nodes (23): ADR-0001: 프로젝트 정체성과 MVP 검증 가설, Consequences, Considered Options, Context — 왜 이 결정이 필요했나, D1. 프로젝트 정체성, D2. MVP 가 검증하려는 가설 — Pareto 우월, D3. 비교 실험 — 3-way 측정 (정확도 + 토큰 + 지연 3 메트릭), D4. 검증 도메인 — 상거래 비즈니스 규칙 (+15 more)

### Community 61 - "Community 61"
Cohesion: 0.09
Nodes (21): ADR-0004: 벡터 인프라 — 그래프 DB 내장 벡터 인덱스, 별도 벡터 DB 서비스 미도입, Consequences, Considered Options, Context — 왜 이 결정이 필요했나, D1. dense 임베딩은 그래프 DB 내장 벡터 인덱스에 저장, D2. 임베딩 모델은 *외부 서비스* (라이브러리/API), DB 와 분리, D3. "벡터 검색 ≠ 별도 벡터 DB" 의 분리 원칙, D4. 도메인 확장 시의 진화 경로 (+13 more)

### Community 62 - "Community 62"
Cohesion: 0.10
Nodes (21): ADR-0002: MVP 범위 경계 — 무엇을 의도적으로 미루는가, Consequences, Considered Options, Context — 왜 이 결정이 필요했나, D1. 웹 화면 (FE) 전부, D2. 인증 · 접근제어 · 멀티 테넌트, D3. 채팅 · 멀티턴 세션, D4. 다국어 처리 (+13 more)

### Community 63 - "Community 63"
Cohesion: 0.10
Nodes (21): 0. 책임, 1.1 같은 corpus 의 변형, 1. 디렉토리 구조, 2. `meta.yaml`, 3.1 완전한 JSON Schema (YAML 으로 표현되지만 스키마는 동일), 3.2 제약 (스키마로는 표현 어려운 비즈니스 룰), 3.3 한 질문의 완전한 예, 3. `questions.yaml` — 30 MCQ 세트 (+13 more)

### Community 64 - "Community 64"
Cohesion: 0.14
Nodes (17): build_default_components(), 프로덕션 부팅 경로에서 사용. 테스트는 별도 구성., settings_dep(), Settings, FastAPI, 5 primitive + find_entities 의 라이브 흐름 — 실제 Neo4j + OpenAI.  본 라이브 테스트는 다음 흐름을 한 번, find_entities → get_subgraph → find_path 연속., ingest 한 도메인에서 키워드로 매칭이 나온다. (+9 more)

### Community 65 - "Community 65"
Cohesion: 0.22
Nodes (13): embedding_provider_dep(), graph_repo_dep(), ingest_service_dep(), llm_provider_dep(), FastAPI 의존성 — singleton service / repository 구성.  WHY 모듈 전역 + lazy: 부팅 시 호출되는 st, Admin ingest 의 in-process 작업 registry.      WHY app.state 에서 가져옴: lifespan 에서 한, task_registry_dep(), EmbeddingProvider (+5 more)

### Community 66 - "Community 66"
Cohesion: 0.21
Nodes (6): Chunk, _IndexEntry, _MemoryIndex, 컬럼 (2) 청크 벡터 RAG — PRD 4 §2., chromadb 의존을 피하기 위한 in-process 인덱스. cosine 유사도 top-k.      WHY in-memory: 측정 하니스, corpus 를 청크화하고 모든 청크를 임베딩해 인덱스에 적재.

### Community 67 - "Community 67"
Cohesion: 0.18
Nodes (10): Working with this repo, 공개 아티팩트 접근성 규칙, 관련 저장소, 세션 역할 모드, 시작 시 진입점 (순서), 이 저장소는 어디서 시작하나, 작성 톤, 작업이 끝났을 때 (워커 모드) (+2 more)

### Community 68 - "Community 68"
Cohesion: 0.20
Nodes (10): ADR 이 무엇인가, ADR 작성 규칙, Architecture Decision Records (ADR), Retrieval / 인덱싱, 가설과 범위, 메타: ADR 톤과 분량, 외부 표면 (API / MCP), 처음 들어왔다면 — 0001 부터 순서대로 (+2 more)

### Community 69 - "Community 69"
Cohesion: 0.20
Nodes (10): 4.1 자동 채점 — Correctness, 4.2 LLM judge — Reasoning quality, 4.3 LLM judge — Faithfulness, 4.4 Judge 모델 선택, 4.5 Judge 호출 시 컬럼 익명화, 4. 채점 (ADR-0005), 사용자 프롬프트, 사용자 프롬프트 (+2 more)

### Community 70 - "Community 70"
Cohesion: 0.22
Nodes (8): STATUS — Opentology 현재 상태, 갱신 정책, 검증 흐름 헬스, 다음 액션, 마일스톤 진행도, 알려진 stub 표, 한 줄, 현재 상태 — Walking Skeleton 진행 중

### Community 71 - "Community 71"
Cohesion: 0.39
Nodes (7): _client(), 5 primitive + find_entities 의 통합 흐름 — Neo4j 없이 FakeGraph 위에서.  본 통합 테스트는 *FastAP, find_entities → get_entity → get_neighbors → get_subgraph → find_path., test_error_envelope_for_unknown_entity(), test_full_primitive_chain(), test_get_schema_chain(), test_openapi_six_primitives_present()

### Community 72 - "Community 72"
Cohesion: 0.36
Nodes (7): OpenAILLMProvider, _make_provider_with_responses(), LLM 어댑터의 파싱 / 재시도 동작., OpenAI 클라이언트 초기화를 우회하기 위해 __new__ 로 객체 생성.      WHY __new__ + 수동 attribute 주입: _, test_extract_parses_strict_json(), test_extract_raises_after_two_failures(), test_extract_retries_once_on_parse_failure()

### Community 73 - "Community 73"
Cohesion: 0.25
Nodes (8): 0. 위치와 책임, 10. Out of scope (MVP 측정 하니스가 안 다루는 것), 7.1 meta.yaml 예시, 7. 로그 저장 구조, 8. 보고서 형식 (한 장), 9. 미정 결정 (구현 설계 단계), PRD 4 — 평가 하니스 (3-way 측정), 참조 ADR

### Community 74 - "Community 74"
Cohesion: 0.25
Nodes (8): 2.1 흐름, 2.2 청크 분할 알고리즘, 2.3 벡터 인덱스 (측정 한정), 2.4 검색, 2.5 시스템 프롬프트, 2.6 사용자 프롬프트 패턴, 2.7 토큰 카운트 규칙, 2. 컬럼 2 — 청크 벡터 RAG (대조)

### Community 75 - "Community 75"
Cohesion: 0.25
Nodes (8): 3.1 흐름, 3.3 서브그래프 직렬화 형식 (Step 5), 3.4 답변 생성 LLM 호출 (Step 6), 3.5 Primitive 호출 시퀀스 — 기본 형태, 3.6 토큰 카운트 규칙, 3. 컬럼 3 — Opentology (그래프 노드 RAG + 탐색), 사용자 프롬프트 패턴, 시스템 프롬프트

### Community 76 - "Community 76"
Cohesion: 0.33
Nodes (6): 3-way 비교 절차, Q&A 셋 — MCQ + 이유 서술 형식, 검증 도메인, 검증 방식, 소스 셋 구성 원칙, 종료 조건

### Community 77 - "Community 77"
Cohesion: 0.33
Nodes (6): 0.1 두 통로의 1:1 매핑, 0.2 인증 / 격리, 0.3 응답 공통 envelope (REST), 0.4 MCP 응답, 0.5 ID 형식, 0. 표면 일반

### Community 78 - "Community 78"
Cohesion: 0.33
Nodes (6): 3.1 REST, 3.2 MCP tool, 3.3 입력, 3.4 출력, 3.5 매칭 알고리즘 (ADR-0003 D1), 3. `find_entities`

### Community 79 - "Community 79"
Cohesion: 0.33
Nodes (6): 1.1 흐름, 1.2 corpus 직렬화 형식, 1.3 시스템 프롬프트, 1.4 사용자 프롬프트 패턴, 1.5 토큰/지연 기록, 1. 컬럼 1 — Full-context LLM (cost ceiling reference)

### Community 80 - "Community 80"
Cohesion: 0.40
Nodes (5): 11. 미정 결정 (구현 설계 단계), 12. Out of scope (MVP 에서 노출 안 함), 9. 에러 코드 카탈로그, PRD 3 — Graph Primitives (REST + MCP), 참조 ADR

### Community 81 - "Community 81"
Cohesion: 0.40
Nodes (5): 4.1 REST, 4.2 MCP tool, 4.3 입력 (MCP), 4.4 출력, 4. `get_entity`

### Community 82 - "Community 82"
Cohesion: 0.40
Nodes (5): 5.1 REST, 5.2 MCP tool, 5.3 입력, 5.4 출력, 5. `get_neighbors`

### Community 83 - "Community 83"
Cohesion: 0.40
Nodes (5): 6.1 REST, 6.2 MCP tool, 6.3 입력, 6.4 출력, 6. `find_path`

### Community 84 - "Community 84"
Cohesion: 0.40
Nodes (5): 7.1 REST, 7.2 MCP tool, 7.3 입력, 7.4 출력, 7. `get_subgraph`

### Community 85 - "Community 85"
Cohesion: 0.40
Nodes (4): Opentology, 검증 가설 한 줄, 이 저장소 이전의 작업, 진입점

### Community 87 - "Community 87"
Cohesion: 0.50
Nodes (3): 런타임 설정 — 환경 변수로 오버라이드, 기본값은 코드에 고정.  WHY 환경 변수 prefix `OPENTOLOGY_API_*`: `OPENT, 테스트 격리용 — 환경 변수 패치 후 다시 로드하고 싶을 때., reset_settings_for_test()

### Community 88 - "Community 88"
Cohesion: 0.50
Nodes (4): 10.1 일관성 모델, 10.2 동시성, 10.3 응답 크기 상한, 10. 동작 가정과 한계

### Community 89 - "Community 89"
Cohesion: 0.50
Nodes (4): 1.1 Node, 1.2 Edge, 1.3 SourceRef, 1. 공통 메타데이터 스키마

### Community 90 - "Community 90"
Cohesion: 0.50
Nodes (4): 2.1 REST, 2.2 MCP tool, 2.3 응답, 2. `get_schema`

### Community 91 - "Community 91"
Cohesion: 0.50
Nodes (4): 8.1 두 transport, 8.2 stdio 어댑터, 8.3 tool 등록 manifest, 8. MCP 어댑터

### Community 92 - "Community 92"
Cohesion: 0.50
Nodes (4): 3.2 Anchor 추출 LLM 호출 (Step 2), 결과 → keywords, 시스템 프롬프트, 입력 (사용자 프롬프트)

### Community 93 - "Community 93"
Cohesion: 0.50
Nodes (4): 5.1 트리거 조건 (ADR-0005 D5), 5.2 검토 UI, 5.3 덮어쓴 점수 기록, 5. Spot-check 흐름

### Community 94 - "Community 94"
Cohesion: 0.50
Nodes (4): 6.1 측정 전체 실행, 6.2 단계별 실행 (디버깅용), 6.3 환경 변수, 6. 실행 절차 (CLI)

## Knowledge Gaps
- **358 isolated node(s):** `Settings`, `Edge`, `Any`, `FileProgressEvent`, `Argument` (+353 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Neo4jGraphRepository` connect `Relation & Node Model` to `Community 64`, `Identity E2E Tests`, `Adapter Protocols`, `Graph Repo Helpers`, `ADR-2 Scope Boundaries`, `PRD-2 Ingest Spec`, `Merge Mutation Apply`, `Ingest Service Domain`, `Eval Columns Setup`, `Live Tests Conftest`, `Eval Config`, `Entity Matcher Tests`, `Columns Init`, `Eval Package Init`, `Name Normalization`, `Eval CLI & Runlog`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `datetime` connect `Eval File Loader` to `Adapter Protocols`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Why does `IngestService` connect `Adapter Protocols` to `API Layer & DI Wiring`, `Community 65`, `Identity E2E Tests`, `Graph Repo Helpers`, `Eval Baseline Columns`, `Eval CLI & Runlog`, `Entity Matcher Tests`, `Eval Config`, `Neo4j Repository`, `Relation & Node Model`, `LLM Adapter & Models`, `Questions YAML Loader`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Are the 60 inferred relationships involving `SourceRef` (e.g. with `EmbeddingProvider` and `GraphRepository`) actually correct?**
  _`SourceRef` has 60 INFERRED edges - model-reasoned connections that need verification._
- **Are the 26 inferred relationships involving `FakeGraph` (e.g. with `FakeGraph` and `Path`) actually correct?**
  _`FakeGraph` has 26 INFERRED edges - model-reasoned connections that need verification._
- **Are the 66 inferred relationships involving `ExtractedGraph` (e.g. with `EmbeddingProvider` and `ExtractedGraph`) actually correct?**
  _`ExtractedGraph` has 66 INFERRED edges - model-reasoned connections that need verification._
- **Are the 37 inferred relationships involving `GraphRepository` (e.g. with `ExtractedGraph` and `NeighborhoodResult`) actually correct?**
  _`GraphRepository` has 37 INFERRED edges - model-reasoned connections that need verification._