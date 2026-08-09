# 돌파 — 에이전트 반복 graph-only 가 graphify 를 압도 (2026-06-22)

## 한 줄 결론

arche 의 그래프만으로 (원본 문서 *미열람*) FinanceBench 33-MCQ 에서 **94-97%** —
graphify 의 동일 조건 (graph-only 에이전트) **57.6%** 를 **+36~39pp** 앞선다. 차이는
그래프에 귀속된다.

## 측정

| 조건 | 정답률 | 비고 |
| --- | --- | --- |
| graphify graph-only (에이전트 반복) | 57.6% | 기준 |
| arche 단발 graph-only (max_nodes 1000) | 45.5% | 반복 없음 |
| arche 단발 graph-only (max_nodes 3000) | 45.5% | recall 포화, 평탄 |
| **arche 에이전트 graph-only — RUN 1** | **97.0% (32/33)** | source 미사용 |
| **arche 에이전트 graph-only — RUN 2 (재현)** | **93.9% (31/33)** | 선택 일치 32/33 |
| (참고) combined 단발 (graph+chunk 내재화) | 75.8% | |

측정: 새 컨텍스트 서브에이전트 3 개 (배치 11 문항, 정답 키 미제공) 가 arche REST
프리미티브 (`/entities/find`, `/subgraph`, `/entities/{id}/neighbors`, `/paths/find`)
*만* 반복 호출. **원본 .md 파일 열람 / grep 금지** — graphify 와 동일한 graph-only
조건. 문항당 평균 API 호출 약 1.5 회.

## 왜 이게 진짜인가 (귀속 + 검증)

1. **인용 수치가 그래프에 실재** — 서브에이전트가 근거로 든 metric 노드를 직접 질의해
   확인: AMEX 실효세율 노드 "2022: 21.6%; 2021: 24.6%", PepsiCo 구조조정 노드
   "$411 million (2022)", JNJ 매출원가 노드 "2022: $31,089 million". 환각 아님.
2. **두 run 의 오답이 진짜 그래프 공백** — Q01 (quick ratio: 그래프에 대차대조표
   합계 없음 → 파생비율 도출 불가), Q12 (AMEX 등록 채권: 표지 정보 미추출). retrieval
   실패가 아니라 *추출 공백*. source 를 읽었다면 둘 다 맞혔을 문항 — 서브에이전트가
   진짜 graph-only 였다는 방증.
3. **재현성** — 독립 2 회 94-97%, 선택 일치 32/33.

## 무엇이 graphify 와 우리를 가르나 (상용 차별점)

| | 정량 추출 (값, 기간, 단위를 노드로) | 에이전트 반복 retrieval | 정답률 |
| --- | --- | --- | --- |
| graphify | 아니오 (범용 추출) | 예 | 57.6% |
| arche 단발 | 예 | 아니오 | 45.5% |
| **arche 에이전트** | **예** | **예** | **94-97%** |

두 요인의 곱이다:
- **정량 추출** (이번 세션 ingest 개선, `llm.py` 원칙 5/6 — metric 을 값, 기간, 단위
  포함한 별도 엔티티로) → 그래프가 *수치 사실을 보유*. graphify 의 범용 추출엔 없어
  graph-only 에이전트가 정량 질문을 못 풀고 57.6% 에서 막힌다.
- **에이전트 반복** → 단발의 부정확한 retrieval (anchor → 단일 subgraph) 을 극복,
  정확한 metric 노드를 찾아낸다. 단발 45.5% → 에이전트 94-97%.

## 이전 "scale 이 변수다 / 그래프 기여 0" 결론의 교정

지난 ablation (graph=grep, 그래프 기여 0) 은 **수치가 없던 옛 그래프** 위에서 측정됐고,
AUG-AGENTIC 에서 답은 source grep 이 냈다 (graph 1 / source 31). 그래서 "그래프 가치는
scale 현상" 으로 결론냈다. 그러나 *정량 추출로 강화된 그래프* 에서는 graph-only 단독이
94-97% 를 낸다 — **그래프의 병목은 scale 이 아니라 추출 완전성이었다.** ingest 가
정량 사실을 노드로 담는 순간, 6 문서 코퍼스에서도 그래프가 grep/graphify 를 크게 앞선다.

## 정직한 단서 (상용화 전 해소 대상)

1. **데이터 품질 — 회사 간 수치 오염**: "Boeing Cost of sales 2022: $40,576M" 은 실제
   PepsiCo 값, PepsiCo 순매출 노드가 "Advanced Micro Devices" 로 오라벨. company-prefix
   네이밍 가드가 완벽치 않다. 더 어려운 문항에서 오답 유발 가능 — 추출 시 회사 귀속
   강화 필요.
2. **단일 벤치마크, 단일 도메인** (finance). 정량 추출 원칙은 도메인 일반이나 비-finance
   미검증.
3. **서브에이전트 측정** (변량 94-97%). 결정적 하니스 컬럼으로 고정 필요.
4. **남은 추출 공백** — 파생 비율 (quick ratio), 표지 등록 정보. ingest 개선 여지.
5. **가치 제안은 amortization** — 그래프 1 회 빌드 (약 9 분 + OpenAI 비용) 후 질의는
   저비용 반복. 빌드 비용은 질의량으로 분산.

## 산출물 (이 결과를 낸 코드)

- ingest 정량 추출: `apps/api/src/arche_api/adapters/llm.py` (원칙 5/6),
  `domain/chunking.py` + `domain/ingest.py` (extraction_chunk_tokens).
- `/subgraph` 500 크래시 수정: `adapters/graph.py` `_clamp` (64 자 초과 관계 라벨이
  서브그래프 전체를 죽이던 회귀). 단위 테스트 `tests/unit/test_primitives.py` 3 개.
- `get_subgraph` max_nodes 상한 1000 → 5000 (`api/responses.py`).

부속: `eval/runs/agentic-graphonly-2026-06-22/`, `eval/runs/agentic-graphonly-repro-2026-06-22/`,
`eval/runs/maxnodes-sweep-2026-06-22/`, `eval/scripts/maxnodes_sweep.py`.
