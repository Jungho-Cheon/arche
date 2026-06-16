# STATUS — Opentology 현재 상태

> 이 파일의 위치: 본 저장소에 기여하는 모두를 위한 **단일 진입점**. 마일스톤 진행도 / 다음 액션 / 알려진 stub 표가 한 페이지에 모인다.

## 현재 상태 — Walking Skeleton 진행 중

M1 (Walking Skeleton + Ingest) 의 *첫 슬라이스* 가 main 에 들어가는 중. 단일 텍스트 파일 → 엔티티/관계 추출 → Neo4j 적재 → `find_entities` lexical 검색까지 끝에서 끝까지 동작한다. 후속 슬라이스 (디렉토리 크롤 / 청크 / 4-step identity / PDF·이미지 / 나머지 5 primitives / MCP) 는 issue #2 ~ #7 로 분리되어 있다.

## 한 줄

Opentology = LLM·AI 에이전트가 *도메인 지식의 관계* 를 *최소한의 토큰과 시간으로* 활용하도록 돕는, 그래프 기반 지식 베이스 도구. 자세한 가치 명제와 검증 가설은 [`docs/prd/1_mvp.md`](./docs/prd/1_mvp.md) 와 ADR-0001.

## 검증 흐름 헬스

핵심 흐름이 끝까지 가는가. 표가 *제품의 살아있는 진행도 신호* .

| 단계 | 상태 | 비고 |
|---|---|---|
| 소스 입력 (디렉토리 크롤) | 미착수 | 단일 파일 ingest 만 동작 (#1). 디렉토리 크롤 / `--watch` / `--dry-run` 은 #2 |
| 엔티티/관계 추출 (멀티모달 LLM) | 부분 | `.txt` / `.md` 단일 파일 + 청크 분할 없음 (#1). PDF / 이미지는 #5 |
| 그래프 적재 (idempotent) | 부분 | 1-step 이름 정확 매칭 동일성만 (#1). 4-step (별칭 / 임베딩 유사도 / LLM judge) 은 #4 |
| 그래프 진입점 인덱싱 (어휘 + dense 하이브리드) | 부분 | fulltext + 벡터 인덱스 둘 다 *생성* . 검색은 lexical-only 이고 dense + RRF 하이브리드는 #6 |
| Graph Primitives REST API | 부분 | `find_entities` (lexical) + `/admin/ingest` + `/healthz` (#1). 나머지 5 primitives (`get_schema` / `get_entity` / `get_neighbors` / `find_path` / `get_subgraph`) 는 #6 |
| Graph Primitives MCP 서버 | 미착수 | stdio 어댑터 #7 |
| 청크 벡터 RAG 베이스라인 하니스 | 완료 | #15 머지 (eval/) |
| Full-context LLM 베이스라인 하니스 | 완료 | #15 머지 (eval/) |
| 30 개 MCQ 평가 셋 | 미착수 | |
| 3-way 측정 보고서 | 미착수 | (3) Opentology 컬럼은 본 슬라이스가 토대 (#10) |

## 마일스톤 진행도

| # | 이름 | 상태 |
|---|---|---|
| M1 | 코드 골격 + 인프라 (FastAPI, 그래프 DB, 임베딩 어댑터) | 진행 중 |
| M2 | Ingest 파이프라인 (소스 → 엔티티/관계 → 그래프, idempotent) | 미착수 |
| M3 | Graph Primitives (REST + MCP) | 미착수 |
| M4 | 베이스라인 하니스 (full-context + 청크 RAG) | 미착수 |
| M5 | 평가 데이터 (상거래 검증 도메인 소스 + 30 MCQ) | 미착수 |
| M6 | 3-way 측정 + 보고서 1 회 | 미착수 |

위 골격은 *구현 계획서* 가 확정되면 그 결정에 맞춰 갱신된다.

## 알려진 stub 표

| 위치 | stub 동작 | 해소 이슈 |
|---|---|---|
| `Neo4jGraphRepository.find_entities_dense` | `NotImplementedError` raise — 하이브리드 매칭의 dense 신호 + RRF 결합 | #6 |
| `apps/api` 의 `find_entities` REST 응답 | PRD 3 §3.4 의 `matches[].node + score + matched_keyword` 형식이 아닌 *Node 배열* 축약본 | #6 |
| `apps/api` ingest 의 청크 분할 | 컨텍스트 초과 분할 미구현 (단일 파일 통째로 LLM 전달) | #3 |
| `apps/api` ingest 의 엔티티 동일성 | 1-step (이름 정확 매칭) 만. 별칭 / 임베딩 유사도 / LLM judge 미구현 | #4 |
| `apps/api` ingest 의 PDF/이미지 | `UnsupportedFileTypeError` raise + #5 안내 | #5 |
| `apps/api` 의 admin ingest | 동기 처리 (PRD 2 §1.3 의 task_id + polling 미구현) | #2 |

## 다음 액션

| 우선순위 | 항목 | 비고 |
|---|---|---|
| P0 | 디렉토리 크롤 + 변경 감지 (#2) | walking skeleton 위에 multi-file 흐름 얹음 |
| P0 | 청크 분할 + overlap (#3) | LLM 컨텍스트 초과 케이스 해소 |
| P0 | 4-step 엔티티 동일성 (#4) | 별칭 / 임베딩 / LLM judge |
| P1 | PDF / 이미지 멀티모달 추출 (#5) | 검증 도메인 소스 파일 형태에 맞춰 |
| P1 | 나머지 5 graph primitives + dense + RRF (#6) | 이 PR 의 stub 해소 |
| P1 | MCP stdio 어댑터 (#7) | ADR-0006 D2 |

## 갱신 정책

- **워커 모드 PR** — 본 PR 이 위 표 (흐름 헬스 · 마일스톤 · stub · 다음 액션) 의 어느 셀에 영향을 주는지 확인하고, **PR 머지 직전 같은 커밋에서 STATUS.md 의 해당 셀을 토글** 한다.
- **오케스트레이터 모드** — 세션 시작 시 STATUS.md 를 먼저 읽는다.
- **재구성 시점** — 구현 계획서가 작성되어 본 STATUS 의 골격이 실제 데이터로 채워질 시점에 한 번 재구성.
