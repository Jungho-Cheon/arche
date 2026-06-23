# STATUS — Opentology 현재 상태

> 이 파일의 위치: 본 저장소에 기여하는 모두를 위한 **단일 진입점**. 마일스톤 진행도 / 다음 액션 / 알려진 stub 표가 한 페이지에 모인다.

## 현재 상태 — M7-D Phase 1 RFC 시작 (파괴적 재구성, 2026-06-21)

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
| Opentology (graph 단독) | 90.0% | Q05, Q20, Q25 | 7.9K | 4.82s | $1.69 |
| **Combined (chunk + graph 단일 호출)** | **100.0%** | **없음** | 15.7K | 5.11s | **$2.54** |

핵심 발견: chunk 와 graph 의 오답 집합이 *서로 겹치지 않음* (Q02 ↔ Q05/Q20/Q25). Combined 는 두 retrieval 결과를 *한 LLM 호출의 컨텍스트* 에 같이 넣어 LLM 이 두 신호를 비교, *모든* 단독 실패를 회복.

- 상세 (1차): `eval/runs/2026-06-19-2126/report.md` (Pareto 미달 결론)
- 상세 (2차/피벗): `eval/reports/2026-06-20-combined-pivot/CONCLUSION.md` (Combined 채택)
- 측정 데이터: `eval/runs/2026-06-20-0923/responses/{chunk_rag,opentology,combined}/`

## 한 줄

Opentology = LLM·AI 에이전트가 *도메인 지식의 관계* 를 *최소한의 토큰과 시간으로* 활용하도록 돕는, 그래프 기반 지식 베이스 도구. 자세한 가치 명제와 검증 가설은 [`docs/prd/1_mvp.md`](./docs/prd/1_mvp.md) 와 ADR-0001.

## 검증 흐름 헬스

핵심 흐름이 끝까지 가는가. 표가 *제품의 살아있는 진행도 신호* .

| 단계 | 상태 | 비고 |
|---|---|---|
| 소스 입력 (디렉토리 크롤) | 완료 | `opentology ingest <dir>` + `.opentologyignore` + 자동 제외 + `--dry-run` (#2). `--watch` 는 post-MVP |
| 엔티티/관계 추출 (멀티모달 LLM) | 완료 | `.txt` / `.md` + 청크 분할 (heading→paragraph→sentence + 20% overlap) 완료 (#3). 동일성은 4 단계 + idempotent 차분 완료 (#4). PDF 페이지 텍스트 + 임베디드 이미지 + 단일 이미지 파일 멀티모달 호출 완료 (#5). 파일별 실패 isolation (PRD 2 §8) 적용 |
| 그래프 적재 (idempotent) | 완료 | 4 단계 동일성 (정규화 / 별칭 / 임베딩 유사도 0.92) + IngestionRun 기반 차분 적용 (#4) + 청크 분할 (#3) 도 동일성 매처가 청크 경계 무관하게 흡수 |
| 그래프 진입점 인덱싱 (어휘 + dense 하이브리드) | 완료 | fulltext + 벡터 인덱스 + 하이브리드 검색 (lexical + dense, RRF k=60). raw 점수는 `include_scores=true` 로 노출 |
| Graph Primitives REST API | 완료 | 6 primitive 모두 (`get_schema` / `find_entities` 하이브리드 / `get_entity` + edge_counts / `get_neighbors` BFS + 절단 / `find_path` k-shortest / `get_subgraph` multi-source BFS) + `/healthz` + `/admin/ingest`. OpenAPI 는 `/openapi.json` 으로 노출. MCP 어댑터는 #7. cypher relationship 직렬화 hotfix (#27) — UNION/variable-length 결과를 properties-only RETURN 으로 정규화, get_neighbors body+path id 1:1 매핑 |
| Graph Primitives MCP 서버 | 완료 (stdio) | `opentology mcp serve --stdio` 가 6 primitive 를 표준 MCP tool 로 노출 (#7). REST 와 *동일 입출력 schema* (Pydantic 단일 source). HTTP+SSE 는 post-MVP (PRD 3 §8.1) |
| 청크 벡터 RAG 베이스라인 하니스 | 완료 | #15 머지 (eval/). PDF 어댑터 연결 완료 — PDF 텍스트 페이지를 청크 소스로 사용 (#14). 이미지 입력은 PRD 4 §2 의 통제 변수 정책으로 무시 + warning 로그 |
| Full-context LLM 베이스라인 하니스 | 완료 | #15 머지 (eval/). PDF/이미지 어댑터 연결 완료 — PDF 텍스트는 직렬화 본문에, 이미지 파일 + PDF 이미지 페이지는 멀티모달 user content 로 동봉 (#14) |
| Opentology 컬럼 (anchor 추출 + primitives 조합 + 직렬화) | 완료 | #10 머지 (eval/columns/opentology.py + eval/clients/opentology.py + eval/serializers.py) |
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
| **M6.5b** | **EntityConsolidator + 1M 재측정 (신규 gating)** | **pending** — ADR-0008 신설. EntityConsolidator 구현 → 1M 재 ingest → opentology + combined 재측정 → ADR-0007 D2 진짜 분기 결정 |
| M7 | Combined RAG productization | pending (M6.5b 종료 후) |
| M8 | Combined 품질·비용 최적화 (잔여) | pending (M7 종료 후, EntityConsolidator 는 M6.5b 로 이동) |
| M9 | Scale·다도메인·외부 비교 | pending (M8 종료 후) |

위 골격은 *구현 계획서* 가 확정되면 그 결정에 맞춰 갱신된다.

## 알려진 stub 표

| 위치 | stub 동작 | 해소 이슈 |
|---|---|---|
| (없음 — M1 완료) | | |

## 다음 액션 (M6.5 결과 반영) — M6.5b → M7 → M8 → M9

| 마일스톤 | 종료 조건 | 핵심 이슈 |
|---|---|---|
| M6.5 — 1M corpus 3-way 재검증 | 완료. 보고서 — `eval/reports/2026-06-20-financebench-1M/CONCLUSION.md`. 결과: Combined ≈ chunk (+0pp). graph 부패로 직접 분기 결정 보류. ADR-0008 신설 | #44 ✓ / #45 (deferred) / #46 ✓ |
| **M6.5b — EntityConsolidator + 1M 재측정 (gating)** | post-ingest ANN + LLM 검증 dedup 구현 + 1M corpus 재 ingest 후 over-merge 감소 evidence + opentology/combined 재측정 → ADR-0007 D2 진짜 분기 결정 | (신규) #40 EntityConsolidator 를 M8 → M6.5b 로 이동 + 1M 재측정 이슈 신설 |
| M7 — Combined RAG productization | docker-compose up + ingest + `curl /answer` 만으로 외부 사용자가 답 받기 | #33 /answer, #34 /retrieve, #35 provenance, #36 노브, #37 Getting Started, #38 identity refresh, #39 service mode |
| M8 — Combined 품질·비용 최적화 (잔여) | 95K 재측정 토큰 ≤ 10K / latency ≤ 3.5s / 정확도 100% 유지 | #41 retrieval anchor, #42 subgraph reranking, #43 budget allocator (#40 은 M6.5b 로 이동) |
| M9 — Scale·다도메인·외부 비교 | 1M 자체 한국어 corpus 측정 + 외부 도구 (LangChain Hybrid / Microsoft GraphRAG) 비교 evidence | TBD (M8 종료 후 도출) |

상세 — `docs/prd/6_post_mvp_combined.md` §4 + ADR-0008. ADR-0007 의 정체성/기술 결정은 유지되며 ADR-0008 이 D2 의 *결정 시점만 지연*.

**M6.5b 가 gating** — M7-M9 의 *코드 작업* 은 M6.5b 종료 전까지 착수하지 않음. 설계 문서/이슈 정리는 병행 가능. M6.5 의 *직접 결과* (Combined ≈ chunk) 만으로 ADR-0007 D2 의 "M7 단순화" 분기에 들어가는 것은 *graph 부패가 측정에 영향* 을 줬으므로 거부 (ADR-0008 D1).

## 갱신 정책

- **워커 모드 PR** — 본 PR 이 위 표 (흐름 헬스 · 마일스톤 · stub · 다음 액션) 의 어느 셀에 영향을 주는지 확인하고, **PR 머지 직전 같은 커밋에서 STATUS.md 의 해당 셀을 토글** 한다.
- **오케스트레이터 모드** — 세션 시작 시 STATUS.md 를 먼저 읽는다.
- **재구성 시점** — 구현 계획서가 작성되어 본 STATUS 의 골격이 실제 데이터로 채워질 시점에 한 번 재구성.
