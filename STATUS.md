# STATUS — Opentology 현재 상태

> 이 파일의 위치: 본 저장소에 기여하는 모두를 위한 **단일 진입점**. 마일스톤 진행도 / 다음 액션 / 알려진 stub 표가 한 페이지에 모인다.

## 현재 상태 — MVP 피벗 확정: Combined RAG (chunk + graph 단일 호출)

M1-M6 모든 마일스톤 완료. 2026-06-19 본 측정 (Pareto 우월 가설 미달) 후 2026-06-20 후속 검증에서 **Combined RAG 가 100% 정확도 + Full-context 의 1/5 비용** 으로 가장 합리적 방향임이 확인되었다.

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
| M5 | 평가 데이터 (상거래 검증 도메인 소스 + 30 MCQ) | 완료 — commerce-verbose-20260618 (33 파일 95K 토큰, 30 MCQ, lint green) |
| M6 | 3-way 측정 + 보고서 1 회 | 완료 — 2026-06-19-2126 (gpt-4.1 N=3) + 후속 Combined 검증 2026-06-20-0923 (Combined RAG 100% 달성, 피벗 확정) |

위 골격은 *구현 계획서* 가 확정되면 그 결정에 맞춰 갱신된다.

## 알려진 stub 표

| 위치 | stub 동작 | 해소 이슈 |
|---|---|---|
| (없음 — M1 완료) | | |

## 다음 액션 (Combined RAG 피벗 이후)

| 우선순위 | 항목 | 비고 |
|---|---|---|
| **P0** | ADR-0007: Combined RAG 채택 + ADR-0001 Pareto 정의 갱신 (full-context 는 *비교 기준* 이 아닌 *상한*) | 본 회차 직접 후속. 2026-06-20 결정 기록 |
| **P0** | API 컬럼 정리 — `/answer` 엔드포인트가 combined 흐름을 기본 (chunk + subgraph 단일 호출), 단독 모드는 baseline 측정용으로 보존 | 제품 정체성 변경 반영 (그래프 KB → retrieval orchestrator) |
| P1 | 코드베이스 적재 ADR (AST + LLM) | 메모리 `project_post_mvp_code_ingest_adr`. MVP 피벗 다음 큰 방향 |
| P1 | 큰 corpus (300K-1M) 재검증 | combined 우월성이 corpus 크기에서 유지되는지 확인. 95K 한정 결론 |
| P1 | EntityMatcher 강화 | Q05/Q20 alias 미통합 — graph 단독 정확도가 회차마다 흔들리는 신호. matcher 가 강해지면 combined 의 안정성도 추가 향상 |
| P2 | Combined 비용 최적화 — subgraph reranking | 입력 토큰 15.7K → 8-10K 로 줄이면 chunk 단독 비용에 근접 |
| P2 | anchor 추출 정확도 개선 | anchor LLM 이 옳은 ULID 진입점을 못 잡는 경우 (이전 회차 기준) |
| P2 | ingest 품질 — cross-chunk identity / multi-hop 관계 추출 (#28) | graph 보완재 가치를 키우기 위함 |
| P2 | invalid_input envelope 정규화 (#26) | Pydantic 422 → PRD 3 §0.3 envelope |

## 갱신 정책

- **워커 모드 PR** — 본 PR 이 위 표 (흐름 헬스 · 마일스톤 · stub · 다음 액션) 의 어느 셀에 영향을 주는지 확인하고, **PR 머지 직전 같은 커밋에서 STATUS.md 의 해당 셀을 토글** 한다.
- **오케스트레이터 모드** — 세션 시작 시 STATUS.md 를 먼저 읽는다.
- **재구성 시점** — 구현 계획서가 작성되어 본 STATUS 의 골격이 실제 데이터로 채워질 시점에 한 번 재구성.
