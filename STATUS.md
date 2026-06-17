# STATUS — Opentology 현재 상태

> 이 파일의 위치: 본 저장소에 기여하는 모두를 위한 **단일 진입점**. 마일스톤 진행도 / 다음 액션 / 알려진 stub 표가 한 페이지에 모인다.

## 현재 상태 — Walking Skeleton + Ingest 완료

M1 (Walking Skeleton + Ingest) 가 main 에 모두 들어왔다. 단일 텍스트 / 디렉토리 / PDF / 이미지 어느 모달이든 → 엔티티/관계 추출 → Neo4j 적재 → 6 graph primitive (REST + MCP) 까지 끝에서 끝까지 동작한다. 다음 단계는 M5 (평가 데이터) + M6 (3-way 측정).

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
| Graph Primitives REST API | 완료 | 6 primitive 모두 (`get_schema` / `find_entities` 하이브리드 / `get_entity` + edge_counts / `get_neighbors` BFS + 절단 / `find_path` k-shortest / `get_subgraph` multi-source BFS) + `/healthz` + `/admin/ingest`. OpenAPI 는 `/openapi.json` 으로 노출. MCP 어댑터는 #7 |
| Graph Primitives MCP 서버 | 완료 (stdio) | `opentology mcp serve --stdio` 가 6 primitive 를 표준 MCP tool 로 노출 (#7). REST 와 *동일 입출력 schema* (Pydantic 단일 source). HTTP+SSE 는 post-MVP (PRD 3 §8.1) |
| 청크 벡터 RAG 베이스라인 하니스 | 완료 | #15 머지 (eval/) |
| Full-context LLM 베이스라인 하니스 | 완료 | #15 머지 (eval/) |
| Opentology 컬럼 (anchor 추출 + primitives 조합 + 직렬화) | 완료 | #10 머지 (eval/columns/opentology.py + eval/clients/opentology.py + eval/serializers.py) |
| 30 개 MCQ 평가 셋 | 미착수 | lint 도구 완료 (#12) — `opentology-eval lint --dataset <dir>` 가 PRD 5 §6 의 hard fail / warn 검증 + `--dry-run-ingest` 토큰·비용 추정 |
| 3-way 측정 보고서 | 완료 (도구) | judge / spotcheck / aggregate / report 도구 일체 완료 (#11). 실 측정은 #13 가 30 MCQ 만들면 가능 |

## 마일스톤 진행도

| # | 이름 | 상태 |
|---|---|---|
| M1 | 코드 골격 + 인프라 (FastAPI, 그래프 DB, 임베딩 어댑터) | 완료 (#1 ~ #5 모두 머지) |
| M2 | Ingest 파이프라인 (소스 → 엔티티/관계 → 그래프, idempotent) | 미착수 |
| M3 | Graph Primitives (REST + MCP) | 완료 — REST 6 primitive (#19) + MCP stdio (#7). HTTP+SSE 는 post-MVP |
| M4 | 베이스라인 하니스 (full-context + 청크 RAG) | 미착수 |
| M5 | 평가 데이터 (상거래 검증 도메인 소스 + 30 MCQ) | 부분 — 데이터셋 형식 (PRD 5) + lint 도구 (#12) 완료, 실 30 MCQ 작성 (#13) 대기 |
| M6 | 3-way 측정 + 보고서 1 회 | 부분 — 도구 완료, 실 측정은 #13 (30 MCQ) 후 |

위 골격은 *구현 계획서* 가 확정되면 그 결정에 맞춰 갱신된다.

## 알려진 stub 표

| 위치 | stub 동작 | 해소 이슈 |
|---|---|---|
| (없음 — M1 완료) | | |

## 다음 액션

| 우선순위 | 항목 | 비고 |
|---|---|---|
| P1 | 30 MCQ 평가 셋 (#13) | 사용자 HITL — 검증 도메인 질문 작성 |
| P2 | eval PDF / 이미지 어댑터 연결 (#14) | ingest 가 받을 수 있으니 eval 도 같은 경로 |

## 갱신 정책

- **워커 모드 PR** — 본 PR 이 위 표 (흐름 헬스 · 마일스톤 · stub · 다음 액션) 의 어느 셀에 영향을 주는지 확인하고, **PR 머지 직전 같은 커밋에서 STATUS.md 의 해당 셀을 토글** 한다.
- **오케스트레이터 모드** — 세션 시작 시 STATUS.md 를 먼저 읽는다.
- **재구성 시점** — 구현 계획서가 작성되어 본 STATUS 의 골격이 실제 데이터로 채워질 시점에 한 번 재구성.
