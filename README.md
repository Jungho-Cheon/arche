# Opentology

> LLM 과 AI 에이전트가 *도메인 지식의 관계* 를 *최소한의 토큰과 시간으로* 활용해 정확한 답을 내도록 돕는, **Combined RAG (청크 벡터 검색 + 그래프 컨텍스트) 단일 호출 오케스트레이터** .

문서에서 엔티티와 관계를 추출해 그래프로 저장하고, 두 가지 채널로 노출한다:

1. **`POST /answer`** — 사용자의 질문에 *Combined RAG 한 LLM 호출* 로 답변 + 어느 신호가 결정적이었는지 (`provenance.decisive_source`). 시제품 사용자의 *기본 채널* .
2. **`POST /retrieve`** — chunks + subgraph 컨텍스트만 (자체 LLM 운영자용).
3. **Graph primitives 6 종** — `get_schema` / `find_entities` / `get_entity` / `get_neighbors` / `find_path` / `get_subgraph`. 에이전트가 *원자적 그래프 작업* 만 골라 쓰는 저수준 경로.

## 5 분 시작 가이드

[`docs/getting-started.md`](./docs/getting-started.md) — `docker compose up` 한 줄 → 자기 문서 ingest → `/answer` 호출까지.

## 진입점

- **[`docs/prd/1_mvp.md`](./docs/prd/1_mvp.md)** — MVP 사양.
- **[`docs/prd/6_post_mvp_combined.md`](./docs/prd/6_post_mvp_combined.md)** — post-MVP Combined RAG 청사진 + §0.1 의 default = combined 결정.
- **[`docs/adr/`](./docs/adr/)** — 의사결정 기록. 0001 부터 0008 까지 순서대로 읽으면 한 묶음.
- **[`STATUS.md`](./STATUS.md)** — 현재 진행 상태.

## 검증 결과 한 줄 (2026-06-21)

financebench-smoke (21 MCQ) 6 graph 측정 + 95K 한국어 코퍼스 30 MCQ 측정 종합:

| 컬럼 | floor | ceiling | variance range | 비고 |
|---|---|---|---|---|
| chunk_rag | 71.4% | 71.4% | 0pp (graph 무관) | baseline |
| opentology (graph 단독) | 33.3% | 47.6% | 14pp | graph quality 의존 |
| **combined (default)** | **≥71% (chunk floor)** | **81%** | **5pp** | ★ variance robust |
| opentology_aug (graph-guided chunk) | 66.7% | 81.0% | 14pp | multi-hop hint 시 우월 (hops=3 +15pp) |

→ **default = combined**, multi-hop hint 일 때만 `mode: "aug"` 선택. 자세한 분석은 [`eval/reports/2026-06-21-variance-decision/`](./eval/reports/2026-06-21-variance-decision/CONCLUSION.md).

## 코드베이스 파악

`graphify-out/` 에 사전 빌드된 지식 그래프가 있다. `GRAPH_REPORT.md` 의 god node + 커뮤니티 라벨로 작업 영역 위치를 잡고, `graph.json` 직접 읽기 또는 `graphify` CLI 로 질의. 자세한 사용법은 [`CLAUDE.md`](./CLAUDE.md) 의 "코드 파악 시 — 그래프 우선" 섹션.

## 이 저장소 이전의 작업

2026-06-15 PRD 재정립 이전의 작업은 별도 저장소 `legacy-opentology` 에 보존되어 있다. 본 저장소의 의사결정과 무관하다.
