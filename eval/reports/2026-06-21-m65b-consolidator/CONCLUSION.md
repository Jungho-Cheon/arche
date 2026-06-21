# M6.5b CONCLUSION — EntityConsolidator 1M 적용 결과 (2026-06-21)

> 본 보고서는 ADR-0008 D2 의 (b)(c) 종료 조건을 측정한 결과. PROTOCOL.md 의 5 단계 protocol 을 본 회차에 그대로 실행.

## 실행 환경

| 항목 | 값 |
|---|---|
| 측정일 | 2026-06-21 |
| corpus | `eval/datasets/financebench-2026-06-20/corpus` (6 개 10-K, 1M 토큰 규모) |
| LLM | `openai/gpt-4.1` |
| Embedding | `openai/text-embedding-3-small` |
| Pre-fix | NON_IDENTIFYING_ALIAS_STOPLIST (PR #51) + EntityConsolidator (본 PR) 둘 다 적용 |

## (b) over-merge 감소 evidence

(측정 대기)

## (c) opentology + combined N=3 재측정

(측정 대기)

## ADR-0007 D2 진짜 분기 결정

(측정 후 결정)
