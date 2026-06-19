# Opentology MVP 측정 보고서 — 2026-06-19-2126

Questions: 30 | Runs/Q: 3 | Overrides: 0

## 메트릭 표

| 컬럼 | Accuracy | Median input tokens | Median output tokens | Median latency (ms) | p95 latency | Reasoning quality (med) | Faithfulness (mean) | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| Full-context | 100.0% | 69,642 | 214.5 | 8,078 | 17,468 | 2.0 | 32.2% | $12.6935 |
| Chunk RAG | 96.7% | 4,680 | 169.5 | 2,836 | 4,585 | 2.0 | 35.6% | $1.6208 |
| Opentology | 96.7% | 8,311 | 205.5 | 5,765 | 9,718 | 2.0 | 34.4% | $1.7557 |

## Pareto 우월 판정

Pareto 우월: 미달 — Accuracy 0.967 < Full-context 1.000 / Total tokens (median) 8546 > Chunk RAG 8523 / Latency (median) 5765ms > Chunk RAG 2836ms

- Accuracy: NG
- Tokens (median): NG
- Latency (median): NG

사유:
  - Accuracy 0.967 < Full-context 1.000
  - Total tokens (median) 8546 > Chunk RAG 8523
  - Latency (median) 5765ms > Chunk RAG 2836ms

## Failure mode breakdown

| 컬럼 | parse_error | wrong_choice | 정보부족 옵션 |
|---|---|---|---|
| Full-context | 0 | 0 | 0 |
| Chunk RAG | 0 | 3 | 0 |
| Opentology | 0 | 3 | 0 |

## 한 단락 해석

세 컬럼의 정확도는 Full-context 100.0%, Chunk RAG 96.7%, Opentology 96.7% 다. 질문당 토큰 (중간값) 은 각각 69,860 / 8,523 / 8,546 이고, 지연 (중간값) 은 8,078ms / 2,836ms / 5,765ms 다. Pareto 우월: 미달 — Accuracy 0.967 < Full-context 1.000 / Total tokens (median) 8546 > Chunk RAG 8523 / Latency (median) 5765ms > Chunk RAG 2836ms. 본 회차는 자동 채점 기준 결과로, 본인 검토 덮어쓰기 0 건이 점수에 반영됐다.
