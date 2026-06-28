# STATUS — Arche 현재 상태

> 이 파일의 위치: 본 저장소에 기여하는 모두를 위한 **단일 진입점**. 마일스톤 진행도 / 다음 액션 / 알려진 stub 표가 한 페이지에 모인다.

## 현재 상태 — 측정 기반 방향 확정 + 구조 정리 (2026-06-25)

ADR-0016 측정으로 제품 방향이 확정됐다: **에이전트 반복 graph-only 가 graphify 를 압도** (FinanceBench 94-97% vs 57.6%, MedHop 30% vs 10%). 정확도의 레버는 모델/규모가 아니라 *추출 완전성* 이다. 이에 따라 답변 LLM 을 Arche 외부로 빼고 (graph primitive 만 노출), 정량 (수치·표) 인지 추출을 채택. ADR-0017 이 경로 *정밀도* (허브 인지 점수) 로 보강 — promiscuous 허브를 다리로 쓰는 가짜 경로 제거.

검증이 안정화되자 구조를 확정했다.

| ADR | 결정 | 코드 반영 |
|---|---|---|
| [0016](./docs/adr/0016-agentic-graphonly-and-quantitative-extraction.md) | graph-only + 정량 추출, 답변 LLM 외부화 | 적용 |
| [0017](./docs/adr/0017-hub-aware-path-scoring.md) | 허브 인지 경로 점수 (find_path 정밀도 + hub_score 노출) | 적용 |
| [0018](./docs/adr/0018-monorepo-and-agnostic-boundaries.md) | monorepo + 능력별 포트 (GraphStore/VectorIndex/LexicalIndex) + 추출 계약 도메인화 | 적용 (`apps/api`) |
| [0019](./docs/adr/0019-multi-provider-factory.md) | 모델 provider 팩토리 + Anthropic/Voyage 어댑터 (설정만으로 교체, OpenAI-free 경로) | 적용 (`apps/api/adapters`) |

> 도구 메모: 코드 네비게이션용 graphify (`graphify-out/`) 는 2026-06-25 사용 중단 + 저장소에서 제거. 단 graphify 를 *외부 벤치마크 baseline* 으로 인용한 측정 기록 (아래 블록들) 은 Arche 가 측정으로 이긴 상대로서 정체성 근거이므로 *보존* 한다.

아래 "이전 상태" 블록과 마일스톤 표는 ADR-0016 피벗 *이전* 기준이다. 0016~0019 와 충돌하는 셀은 위 결정이 우선하며, 표 전면 재구성은 구현 계획서 확정 시점에 한 번 수행한다 (아래 "갱신 정책" 참조).

## 이전 상태 — M7-D Phase 1 RFC 시작 (파괴적 재구성, 2026-06-21)

PR #54 의 EntityConsolidator 1M 적용 결과 (Combined 78.8% > chunk 72.7%) 로 ADR-0007 D2 분기는 "D1 유지 + M7 unblock" 으로 결정. 그러나 *graphify 와의 비교 평가* (2026-06-21 합의) 에서 다음이 드러남:

1. 우리 도구의 *그래프 생성 자체* 가 graphify 보다 손해. 손실 요인 7 종: 순차 호출, 캐싱 부재, 임베딩 강제, AST 미활용, Step 3 cosine 자기갚음, INFERRED edge 부재, **추출 단계 컨텍스트 부재 (root cause)**.
2. STOPLIST + Consolidator 는 *증상 가림*. 동명이인 / 학술 논문 / 다회사 KB 시나리오 미해결.
3. MVP 성공 최소 조건 (사용자 goal 2026-06-21): graphify 우월 그래프 + Agent API + MCP + 사내 공유 KB.

→ M7 (productization) 직진 대신 **M7-D (Destructive rebuild)** 로 진로 변경. 3 Phase 시퀀스:

| Phase | 목표 | 산출물 | 상태 |
|---|---|---|---|
| Phase 1 — graphify parity 회복 | 추출 단계 컨텍스트 동봉 + parallel + 캐싱 + Step 3 옵션화 | ADR-0009/0010/0011 (accepted) + 5 PR 코드 + **1M 실측 evidence** | **★ 완료** |
| Phase 2 — Agent API + MCP HTTP | Agent 친화 contract + MCP HTTP transport | ADR-0013 RFC + ADR-0014 + **mcp_http.py** (Streamable HTTP + SSE) | **MCP HTTP 코드 완료** |
| Phase 3 — 공유 KB 운영 모델 | 사내 인프라 활용 + namespace 부분 공유 | ADR-0015 + **auth.py + Kubernetes manifest 골격** | **최소 viable + 배치 가이드** |

### 2026-06-21 1M 검증 핵심

PR #54 baseline 17 분 / 479 entities / Consolidator 가드 필요 → **M7-D 9 분 7 초 (-45%) / 422 entities / Consolidator 없이도 over-merge 0**. ADR-0009 의 root-cause 해법 (matched_existing_id 78 건 = 18.5%) 이 *추출 단계에서* 매칭 결정. 상세 — [CONCLUSION](./eval/reports/2026-06-21-m7d-1M-validation/CONCLUSION.md).

상세:
- [ADR-0009 — Context-aware extraction](./docs/adr/0009-context-aware-extraction.md)
- [ADR-0010 — Multi-agent parallel + cache](./docs/adr/0010-multi-agent-parallel-and-cache.md)
- [ADR-0011 — Step 3 cosine opt-in + STOPLIST/Consolidator deprecation](./docs/adr/0011-step3-cosine-opt-in.md)
- [Phase 1 spec — 5 PR 분할](./docs/superpowers/specs/destructive-rebuild-phase1.md)

본 RFC 머지 (사용자 합의 후) → Phase 1 의 PR B-E 진행. PR #54 (EntityConsolidator) 는 *baseline 으로 머지 유지* → Phase 1 의 deprecation 경로 시작점.

## 이전 상태 — M6.5 종료, M6.5b (EntityConsolidator) 신설 gating + smoke 로 Combined 유의미성 1 차 확인

M1-M6 모든 마일스톤 완료. 2026-06-19 본 측정 (Pareto 우월 가설 미달) → 2026-06-20 95K 후속 검증 (**Combined RAG 100%** , ADR-0007 채택) → 2026-06-20 1M FinanceBench 재검증 (M6.5) 에서 **graph catastrophic over-merge** 발견. ADR-0008 로 EntityConsolidator 를 M7 gating (M6.5b) 으로 격상.

**2026-06-20 smoke 검증** (`eval/reports/2026-06-20-smoke-stoplist-fix/`): 임시 patch (`NON_IDENTIFYING_ALIAS_STOPLIST`) 만으로 graph 33.3% / combined 81.0% / chunk 71.4% — **Combined +9.5pp chunk 우위**. ADR-0007 D2 의 "≥ chunk + 3pp" 기준 충족. **Combined RAG 의 유의미성 1 차 입증** + EntityConsolidator 본 구현 가치 입증.

| 컬럼 | Accuracy | 오답 | 토큰(중앙값) | 지연(중앙값) | 비용 (90 호출) |
|---|---|---|---|---|---|
| Full-context (gpt-4.1) | 100.0% | 없음 | 70K | 8.1s | $12.7 |
| Chunk RAG | 96.7% | Q02 (synonym_alias 3-hop) | 8.5K | 2.85s | $0.97 |
| Arche (graph 단독) | 90.0% | Q05, Q20, Q25 | 7.9K | 4.82s | $1.69 |
| **Combined (chunk + graph 단일 호출)** | **100.0%** | **없음** | 15.7K | 5.11s | **$2.54** |

핵심 발견: chunk 와 graph 의 오답 집합이 *서로 겹치지 않음* (Q02 ↔ Q05/Q20/Q25). Combined 는 두 retrieval 결과를 *한 LLM 호출의 컨텍스트* 에 같이 넣어 LLM 이 두 신호를 비교, *모든* 단독 실패를 회복.

- 상세 (1차): `eval/runs/2026-06-19-2126/report.md` (Pareto 미달 결론)
- 상세 (2차/피벗): `eval/reports/2026-06-20-combined-pivot/CONCLUSION.md` (Combined 채택)
- 측정 데이터: `eval/runs/2026-06-20-0923/responses/{chunk_rag,arche,combined}/`

## 한 줄

Arche = LLM·AI 에이전트가 *도메인 지식의 관계* 를 *최소한의 토큰과 시간으로* 활용하도록 돕는, 그래프 기반 지식 베이스 도구. 자세한 가치 명제와 검증 가설은 [`docs/prd/1_mvp.md`](./docs/prd/1_mvp.md) 와 ADR-0001.

## 검증 흐름 헬스

핵심 흐름이 끝까지 가는가. 표가 *제품의 살아있는 진행도 신호* .

| 단계 | 상태 | 비고 |
|---|---|---|
| 소스 입력 (디렉토리 크롤) | 완료 | `arche ingest <dir>` + `.archeignore` + 자동 제외 + `--dry-run` (#2). `--watch` 는 post-MVP |
| 엔티티/관계 추출 (멀티모달 LLM) | 완료 | `.txt` / `.md` + 청크 분할 (heading→paragraph→sentence + 20% overlap) 완료 (#3). 동일성은 4 단계 + idempotent 차분 완료 (#4). PDF 페이지 텍스트 + 임베디드 이미지 + 단일 이미지 파일 멀티모달 호출 완료 (#5). 파일별 실패 isolation (PRD 2 §8) 적용 |
| 그래프 적재 (idempotent) | 완료 | 4 단계 동일성 (정규화 / 별칭 / 임베딩 유사도 0.92) + IngestionRun 기반 차분 적용 (#4) + 청크 분할 (#3) 도 동일성 매처가 청크 경계 무관하게 흡수. 동일성 매칭·관계 cross-doc 해소는 namespace 안에서만 (#92 계획 자료구조 + #94 매처/repo 후보 검색, ADR-0015 격리) |
| 그래프 진입점 인덱싱 (어휘 + dense 하이브리드) | 완료 | fulltext + 벡터 인덱스 + 하이브리드 검색 (lexical + dense, RRF k=60). raw 점수는 `include_scores=true` 로 노출 |
| Graph Primitives REST API | 완료 | 6 primitive 모두 (`get_schema` / `find_entities` 하이브리드 / `get_entity` + edge_counts / `get_neighbors` BFS + 절단 / `find_path` k-shortest / `get_subgraph` multi-source BFS) + `/healthz` + `/admin/ingest`. OpenAPI 는 `/openapi.json` 으로 노출. MCP 어댑터는 #7. cypher relationship 직렬화 hotfix (#27) — UNION/variable-length 결과를 properties-only RETURN 으로 정규화, get_neighbors body+path id 1:1 매핑 |
| Graph Primitives MCP 서버 | 완료 (stdio) | `arche mcp serve --stdio` 가 6 primitive 를 표준 MCP tool 로 노출 (#7). REST 와 *동일 입출력 schema* (Pydantic 단일 source). HTTP+SSE 는 post-MVP (PRD 3 §8.1) |
| 청크 벡터 RAG 베이스라인 하니스 | 완료 | #15 머지 (eval/). PDF 어댑터 연결 완료 — PDF 텍스트 페이지를 청크 소스로 사용 (#14). 이미지 입력은 PRD 4 §2 의 통제 변수 정책으로 무시 + warning 로그 |
| Full-context LLM 베이스라인 하니스 | 완료 | #15 머지 (eval/). PDF/이미지 어댑터 연결 완료 — PDF 텍스트는 직렬화 본문에, 이미지 파일 + PDF 이미지 페이지는 멀티모달 user content 로 동봉 (#14) |
| Arche 컬럼 (anchor 추출 + primitives 조합 + 직렬화) | 완료 | #10 머지 (eval/columns/arche.py + eval/clients/arche.py + eval/serializers.py) |
| 30 개 MCQ 평가 셋 | 완료 | `eval/datasets/commerce-verbose-20260618/` — 8 부서 33 파일 (md 20 / pdf 10 / png 3), 95K 토큰, 30 MCQ. lint green |
| 3-way 측정 보고서 | 완료 (1 회) | `eval/runs/2026-06-19-2126/report.md` — gpt-4.1 N=3, 30 MCQ × 3 컬럼 × 3 runs = 270 응답 + judge 270 rows + Pareto 판정. 가설 *미달* |

## 마일스톤 진행도

| # | 이름 | 상태 |
|---|---|---|
| M1 | 코드 골격 + 인프라 (FastAPI, 그래프 DB, 임베딩 어댑터) | 완료 |
| M2 | Ingest 파이프라인 (소스 → 엔티티/관계 → 그래프, idempotent) | 완료 |
| M3 | Graph Primitives (REST + MCP) | 완료 — REST 6 primitive (#19) + MCP stdio (#7). HTTP+SSE 는 post-MVP |
| M4 | 베이스라인 하니스 (full-context + 청크 RAG) | 완료 (#10, #15) |
| M5 | 평가 데이터 (상거래 검증 도메인 소스 + 30 MCQ) | 완료 — commerce-verbose-20260618 (33 파일 95K 토큰, 30 MCQ, lint green) + financebench-2026-06-20 (6 파일 980K 토큰, 33 MCQ, lint green) |
| M6 | 3-way 측정 + 보고서 1 회 | 완료 — 2026-06-19-2126 (gpt-4.1 N=3) + 후속 Combined 검증 2026-06-20-0923 (Combined RAG 100% 달성, 피벗 확정) |
| M6.5 | 1M corpus 3-way 재검증 (gating) | 완료 — `eval/reports/2026-06-20-financebench-1M/CONCLUSION.md`. Combined ≈ chunk (+0pp), 그러나 graph 부패로 측정 무효. ADR-0008 |
| ~~M6.5b~~ | ~~EntityConsolidator + 1M 재측정 (gating)~~ | **superseded (ADR-0016/0017)** — 아래 "마일스톤 재정렬" 참조 |
| ~~M7~~ | ~~Combined RAG productization~~ | **superseded (ADR-0016 D1)** — Combined 단발은 측정 baseline 으로만 유지, 제품 소비 방식은 에이전트 반복 graph-only |
| ~~M8~~ | ~~Combined 품질·비용 최적화~~ | **superseded (ADR-0016 D1)** — 단발 파이프라인 최적화는 외부 에이전트 반복 모델에서 무의미 |
| M9 | Scale·다도메인·외부 비교 | 보류 (방향 유효, 우선순위 후순위) |

### 마일스톤 재정렬 (ADR-0016 피벗, 2026-06-25 반영)

ADR-0016 측정이 제품 방향을 바꾸면서 (에이전트 반복 graph-only 94-97% > graphify 57.6%, 답변 LLM 외부화) Combined RAG 를 중심으로 짠 M6.5b~M8 의 전제가 무너졌다. 각 마일스톤의 종결 상태.

| 옛 마일스톤 | 무엇이었나 | 왜 superseded | 종결 |
|---|---|---|---|
| M6.5b (EntityConsolidator gating) | post-ingest dedup 으로 over-merge 잡고 ADR-0007 D2 분기 결정 | ADR-0007 D2 분기 자체가 Combined 전제. 동일성 해소는 ADR-0009 추출 단계 매칭 + ADR-0017 정밀도(허브 인지)로 대체. ADR-0011 이 Consolidator deprecation 경로 명시 | 닫음 (#40, #50) |
| M7 (Combined productization) | 내재화 `/answer` 단발 엔드포인트 + 운영화 | ADR-0016 D1 — 답변 LLM 을 외부(MCP/REST)에 두고 프리미티브 반복 호출이 제품 기본. `/answer` 미구현(코드 확인) | 닫음 (#33~39) |
| M8 (Combined 최적화) | 단발 호출 컨텍스트 패킹 최적화(anchor/rerank/budget) | retrieval 오케스트레이션이 외부 에이전트로 이동 → 단발 패킹 가정 무효 | 닫음 (#41~43) |

**실제 남은 백로그 (피벗 이후 유효):**
- **문서 간 엔티티 동일성 해소 강화** — ADR-0016 D4 가 지목한 진짜 다음 레버 (관계-사슬 도메인 천장의 원인). 추출 단계 cross-doc 병합률 ↑. 관련 이슈 #28 (multi-chunk multi-hop 추출 누락 + cross-chunk identity collapse).
- **API 에러 계약 정규화** — #26 (Pydantic 422 → PRD 3 §0.3 envelope). 피벗과 무관하게 유효.
- **결정적 측정 하니스 컬럼** — ADR-0016 한계 §3 (서브에이전트 측정을 고정 컬럼으로).

> ADR-0016 은 아직 `proposed (RFC)` 상태지만, 이를 amend 한 ADR-0017 과 후속 ADR-0018/0019 가 피벗을 기정사실로 빌드했고 코드도 D1 을 따른다(=`/answer` 없음, 프리미티브만). **권고: ADR-0016 을 accepted 로 승격** (본 STATUS 정정은 ADR 본문을 건드리지 않음 — CLAUDE.md ADR 자동갱신 금지 규칙 준수).

## 알려진 stub 표

| 위치 | stub 동작 | 해소 이슈 |
|---|---|---|
| (없음 — M1 완료) | | |

## 다음 액션 (ADR-0016 피벗 이후)

옛 M6.5b→M9 시퀀스는 Combined RAG 전제가 무너져 위 "마일스톤 재정렬" 로 종결했다. 피벗 이후 유효한 작업.

| 우선순위 | 작업 | 종료 조건 | 이슈 |
|---|---|---|---|
| ✅ 완료 | cross-chunk/cross-doc 관계 엔드포인트 해소 (#28 의 multi-hop 사슬 끊김) | 관계 해소를 청크 루프 뒤로 미루고 그래프 정규명 fallback 추가. find_path 4-hop 사슬 복원 (단위+통합 테스트) | #28 |
| 1 🔒 예산 게이트 | 문서 간 엔티티 동일성 해소 강화 (추출 단계 cross-doc 병합) | cross-doc 병합률 ↑ + 관계-사슬 도메인(MedHop류) 천장 상승 evidence. ADR-0009 LLM 매칭 강화 축 | [#82](https://github.com/Jungho-Cheon/arche/issues/82) |
| ✅ 완료 | cross-file *정방향* 관계 해소 (디렉토리 2-pass) | 모든 파일 적재 후 결정적 2-pass 가 1-pass dangling 을 그래프 정규명으로 재해소하고, 회수한 관계를 *원 파일 run* 의 emitted_relation_ids 에 귀속(`append_emitted_relations`)시켜 재적재 차분 회귀 0. 추가 LLM 호출 없음. find_path 순서 비의존 (단위+통합 테스트) | #78 |
| ✅ 완료 | API 에러 계약 정규화 | Pydantic 위반(`RequestValidationError`)을 `invalid_input` ErrorEnvelope 으로 정규화. HTTP 코드는 ADR-0013 D2(422)를 따른다 — 이슈 본문의 옛 400 표기(PRD 3 §9)는 ADR-0013 이 422 로 amend 했고 코드/테스트가 이를 잠그고 있어 422 유지로 확정. `details.errors[]` 를 `flatten_validation_errors` 로 평탄화(`loc` 점 표기 + `type` + `msg`, `input`/`ctx` 제외)해 agent 가 위반 필드를 식별. REST/MCP 동일 헬퍼. 단위+통합 테스트 | #26 |
| 4 🔒 예산 게이트 (코드 슬라이스 완료) | 결정적 측정 하니스 컬럼 (에이전트 반복 graph-only 고정) | **컬럼 코드+단위 테스트 11개 머지 (PR #86, 키 불필요)** — `eval/columns/arche_agentic.py` ReAct 반복 루프(`max_steps` budget + 반복 가드 + 강제 답변, graph-only 격리). 남은 것: 재현 측정으로 94-97% 재확인(예산 게이트) + 다중 컬럼 `run`/보고서 집계 | [#83](https://github.com/Jungho-Cheon/arche/issues/83) |
| 후순위 🔒 예산 게이트 | Scale·다도메인·외부 비교 (옛 M9) | 1M 한국어 corpus + 외부 도구 비교 | [#84](https://github.com/Jungho-Cheon/arche/issues/84) |
| ✅ 완료 | 검토형 적재 계획의 namespace 보존 | `IngestPlan.namespace_id` 추가 — `plan_file` 이 받은 namespace 를 기록, `resolve_plan` 이 그 namespace 로 재계획(default 회귀 방지), `ingest_plan` 진입점이 요청 namespace 전달. PR #91 리뷰의 latent 한계 해소 (단위 회귀 락) | #92 |
| ✅ 완료 | 동일성 매칭의 namespace 격리 | `EntityMatcher` + repo 후보 검색 3종(`find_by_normalized_name`/`vector_search`/`find_entity_id_by_normalized_name`)을 namespace 로 스코프(Neo4j Cypher `coalesce(namespace_id,'default')` 필터). #92 가 남긴 cross-namespace 과병합 가능성 제거 — 생성 쓰기뿐 아니라 매칭·관계 cross-doc 해소도 같은 namespace 안에서만 (단위 4 + 실 Neo4j 통합 1) | #94 |

상세 측정 근거 — `eval/reports/2026-06-22-graphify-mcq-baseline/` (BREAKTHROUGH-AGENTIC-GRAPHONLY / GENERALIZATION-MEDHOP / SCALE-IS-THE-VARIABLE) + ADR-0016/0017.

### 백로그 갈무리 (2026-06-26)

코드 이슈(#28 / #78 / #26 + namespace 격리 #92 / #94)는 모두 완료·머지됐다. **남은 백로그 3개(우선순위 1·4·후순위)는 종료 조건이 전부 *eval evidence*(실측 정확도·병합률) 라 LLM API 호출 비용이 든다.** 현재 저장소 환경에는 측정용 API 키가 없어 *지금 비용을 들이지 않고* 각 항목을 grab 가능한 자기완결적 이슈로 정의해 파킹했다. 🔒 예산 게이트 표시 = 예산/키 확보(사람 결정, HITL) 전까지 착수 보류.

- **#82** (우선순위 1) — 추출 단계 cross-doc 동일성 강화. 1 사이클 약 \$15-20, 강화 라운드 약 \$40-70, MedHop-only 축소안 약 \$10/사이클(gpt-4.1 + text-embedding-3-small 기준 실측 추정).
- **#83** (우선순위 4) — agentic graph-only 재현 컬럼. *컬럼 코드+단위 테스트는 키 없이 선행 가능*, 94-97% 재측정만 예산 게이트.
- **#84** (후순위) — Scale·다도메인·외부 비교.

예산 확보 시 권장 착수 순서: #82 → #83(재측정) → #84. #83 의 코드 슬라이스만 키 없이 먼저 진행하는 선택도 가능(이슈 본문 참조).

## 갱신 정책

- **워커 모드 PR** — 본 PR 이 위 표 (흐름 헬스 · 마일스톤 · stub · 다음 액션) 의 어느 셀에 영향을 주는지 확인하고, **PR 머지 직전 같은 커밋에서 STATUS.md 의 해당 셀을 토글** 한다.
- **오케스트레이터 모드** — 세션 시작 시 STATUS.md 를 먼저 읽는다.
- **재구성 시점** — 구현 계획서가 작성되어 본 STATUS 의 골격이 실제 데이터로 채워질 시점에 한 번 재구성.
