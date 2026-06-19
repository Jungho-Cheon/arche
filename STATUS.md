# STATUS — Opentology 현재 상태

> 이 파일의 위치: 본 저장소에 기여하는 모두를 위한 **단일 진입점**. 마일스톤 진행도 / 다음 액션 / 알려진 stub 표가 한 페이지에 모인다.

## 현재 상태 — MVP 종료, 가설 검증 미달

M1-M6 모든 마일스톤 완료. 2026-06-19 본 측정 (gpt-4.1, N=3, 30 MCQ × 3 컬럼) 결과 **Pareto 우월 가설 미달** — 본 도메인 (95K 토큰, multi-hop 위주) 에서 Opentology 컬럼이 베이스라인 두 컬럼 (Full-context, Chunk RAG) 보다 정확도·지연·토큰 어느 한 축에서도 우위를 못 잡았다.

| 컬럼 | Accuracy | 토큰(중간값) | 지연(중간값) | 비용(전체) |
|---|---|---|---|---|
| Full-context (gpt-4.1) | 100.0% | 69K | 8.1초 | $12.7 |
| Chunk RAG | 96.7% | 4.7K | 2.8초 | $1.6 |
| Opentology | 96.7% | 8.3K | 5.8초 | $1.8 |

상세: `eval/runs/2026-06-19-2126/report.md`. 가설 검증 1회로 *MVP 자체는 종료*. 결과 해석 + post-MVP 방향은 다음 액션 표 참조.

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
| M6 | 3-way 측정 + 보고서 1 회 | 완료 — 2026-06-19-2126 (gpt-4.1 N=3) |

위 골격은 *구현 계획서* 가 확정되면 그 결정에 맞춰 갱신된다.

## 알려진 stub 표

| 위치 | stub 동작 | 해소 이슈 |
|---|---|---|
| (없음 — M1 완료) | | |

## 다음 액션 (post-MVP)

| 우선순위 | 항목 | 비고 |
|---|---|---|
| P0 | 코드베이스 적재 ADR (AST + LLM) | 메모리 `project_post_mvp_code_ingest_adr`. MVP 종료 직후 첫 작업 |
| P1 | 가설 재검증 — 더 큰 corpus (>1M 토큰) + 깊은 multi-hop 도메인 | 본 측정 미달 사유 = corpus 95K 가 작아 Full-context 가 완벽 처리, Opentology 차별성 안 보임 |
| P1 | anchor 추출 정확도 개선 | wrong_choice 3 건 — anchor LLM 이 옳은 ULID 진입점을 못 잡는 경우. anchor 모델 분리/프롬프트 강화 |
| P1 | Opentology latency 단축 | 5.8초 vs Chunk RAG 2.8초. primitive 호출 직렬화/사전 캐싱 |
| P2 | ingest 품질 — cross-chunk identity / multi-hop 관계 추출 (#28) | 본 측정에서도 Opentology 의 한계 신호 일부 발생 |
| P2 | invalid_input envelope 정규화 (#26) | Pydantic 422 → PRD 3 §0.3 envelope |

## 갱신 정책

- **워커 모드 PR** — 본 PR 이 위 표 (흐름 헬스 · 마일스톤 · stub · 다음 액션) 의 어느 셀에 영향을 주는지 확인하고, **PR 머지 직전 같은 커밋에서 STATUS.md 의 해당 셀을 토글** 한다.
- **오케스트레이터 모드** — 세션 시작 시 STATUS.md 를 먼저 읽는다.
- **재구성 시점** — 구현 계획서가 작성되어 본 STATUS 의 골격이 실제 데이터로 채워질 시점에 한 번 재구성.
