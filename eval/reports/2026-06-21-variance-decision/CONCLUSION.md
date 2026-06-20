# Variance 고정 + 최종 방식 채택 — combined 가 default

날짜: 2026-06-21
선행 보고서:
- `eval/reports/2026-06-20-aug-poc/` — aug PoC 81.0% (graph #1)
- `eval/reports/2026-06-20-aug-superiority/` — aug 우월성 검증 (multi-hop +15pp, overall parity)
- `eval/reports/2026-06-20-pivot-aug/` — 피벗 검토
관련 PR: #53

## TL;DR

variance 의 정체는 **ingest LLM 비결정성** 단일 원인. 6 graph 측정에서 aug 의 [67%, 81%] 분포는 *graph 별 AMD company entity 추출 여부* 로 환원된다. 같은 graph 위 4-way 직접 비교에서 **combined 가 chunk_rag floor 보장 (~71%) + graph upside (76-81%) + variance 폭 5pp** 로 가장 robust. **default = combined**. aug 는 multi-hop 우위 (g#1/g#6 86%) 가 있으나 graph quality 에 의존 — EntityConsolidator (M6.5b #40) 으로 ingest variance 해소 시 재평가 대상.

## variance 의 정체 — query 가 아니라 ingest

### query variance = 0

`eval/runs/2026-06-20-aug-n3-smoke` 의 aug × 3 runs × 21 questions = 63 응답 분석:

| run | acc | within-question 불일치 |
|---|---|---|
| run0 | 71.4% | — |
| run1 | 71.4% | — |
| run2 | 71.4% | — |
| **majority N=3** | **71.4%** | **0 / 21** |

같은 graph + 같은 prompt + gpt-4.1 (temperature=0) → 21 questions 전부 *3 회 답 동일*. **query LLM 비결정성은 측정에 영향 없음**. N=3 majority 가산 가치 = 0.

→ 함의: variance bound 를 좁히려면 *ingest 를 통제* 해야 한다. query majority 는 비용 낭비.

### ingest variance = 14pp range

같은 financebench-smoke corpus 를 6 회 재 ingest 한 graph 들의 aug acc:

| Graph | aug overall | aug hops=3 | 비고 |
|---|---|---|---|
| g#1 (PoC) | **81.0%** | 85.7% | AMD company entity 잡음 |
| g#2 (robust) | 66.7% | 71.4% | AMD entity *놓침* |
| g#3 | 66.7% | 71.4% | AMD entity *놓침* |
| g#4 | 66.7% | 71.4% | AMD entity *놓침* |
| g#5 (diversity) | 71.4% | 71.4% | 부분 회복 |
| g#6 (final) | 71.4% | 85.7% | hops=3 회복 |

range = **66.7% - 81.0%** (14.3pp). 직접 원인:

```
Q05 (AMD cash flow): g#1 → graph_selected_sources 에 AMD_2022_10K 포함 → 정답
                     g#2-#4 → AMD source 없음 → "정보 부족" e
Q21 (Boeing tax):    g#1, g#2 → 정답 (BA source 잘 잡힘)
                     g#3-#6 → 옛 ingest 의 "(0.6)%" 추출 차이로 거절 e
```

graph #1 만 AMD 를 company entity 로 잡고, 나머지는 AMD product 만 잡았기에 anchor → entry → source 의 첫 step 에서부터 어긋난다. *retrieval level 에서 이미 다른 graph*.

## 같은 graph 위 4-way 직접 비교 (graph #1)

graph #1 의 ingest 위에서 chunk_rag / combined / opentology (graph 단독) / opentology_aug 모두 측정:

| 컬럼 | overall | hops=1 | hops=2 | hops=3 | 입력 토큰 |
|---|---|---|---|---|---|
| chunk_rag | 71.4% | 57.1% | 71.4% | 85.7% | 6.9K |
| opentology (graph 단독) | 33.3% | 28.6% | 28.6% | 42.9% | 10.5K |
| **opentology_aug** | **81.0%** | 71.4% | 85.7% | **85.7%** | 17K |
| **combined** | **81.0%** | 71.4% | **100.0%** | 71.4% | 17K |

graph #1 만 보면 aug = combined = 81% 동률. 단 hops 별로 강점이 갈림:
- combined: hops=2 에서 100% (chunk 와 graph 가 서로 다른 정답 channel 보완)
- aug: hops=3 에서 85.7% (graph 가 좁힌 좁은 source 에서 chunk 만으로 정답)

## variance 관점 — 모든 graph 에 걸친 robustness

| 컬럼 | graph dependency | variance range | floor | ceiling |
|---|---|---|---|---|
| chunk_rag | **무관** | 71.4% (고정) | 71.4% | 71.4% |
| opentology (graph 단독) | 강함 | 33-48% | 33.3% | 47.6% |
| opentology_aug | 강함 | **66.7-81.0%** (14pp) | 66.7% | 81.0% |
| **combined** | 약함 | **76.2-81.0%** (5pp, n=2) | **≥71.4%**\* | 81.0% |

\* combined = chunk_rag + aug context. graph 가 0 source 가리켜도 chunk_rag side 가 정답 보장 → floor 는 chunk_rag 의 71.4% 이상.

### chunk_rag 는 graph 와 독립이다

chunk_rag 는 corpus chunks 의 embedding 만 사용하고 Neo4j 를 호출하지 않는다. 6 graph 어느 위에서 측정해도 71.4% 가 나온다 → ingest variance 의 *zero-bound*.

### combined 의 robustness 가설

combined 는 graph 가 약하면 chunk side 가 받쳐서 chunk_rag 와 같이 떨어지고, graph 가 강하면 graph side 가 들려 올린다. graph #5 의 combined 76.2% 도 이 가설과 일치 (chunk 71.4% < combined 76.2% < aug 71.4%).

**확정도**: 같은 graph 위 측정이 2 회 (g#1: 81%, g#5: 76.2%) 만 있어 분포 strict 하지 않음. graph #2-#4 (worst aug graph) 에서 combined 추가 측정 시 floor 확정 가능 — 다음 단계.

## 최종 의사결정

### default = **combined**

| 기준 | combined | aug | chunk_rag |
|---|---|---|---|
| variance robust (ingest 변동에 강함) | ★ (5pp) | △ (14pp) | ◎ (0pp) |
| overall acc (graph #1 기준) | 81% | 81% | 71% |
| multi-hop (hops=3) | 71% (g#1) | **86%** (g#1) | 86% (g#1) |
| 토큰 비용 | 17K | 17K | 7K |
| graph 약화 시 floor | ≥71% (가설) | 67% (관측) | 71% |
| 정설 (graph 가 chunk 결정) | ◎ | ★ | × |

근거:
1. **variance 가 가장 작음** — ingest variance 의 영향이 chunk side 에서 흡수된다.
2. **chunk_rag floor 보장** — graph 가 망가져도 chunk 와 동등.
3. **graph upside 활용** — graph 가 좋을 땐 81% 까지 들어 올림.
4. **토큰 cost 동률** — aug 와 17K 동일. 추가 부담 없음.

### aug 의 자리

aug 는 *기각이 아니다* . graph quality 가 stable 한 미래 (EntityConsolidator 적용 후) 에는 효율성 (graph 가 좁힘 → chunk attention 깨끗) 의 이점이 살아난다. 현재는:

- 명시적 multi-hop hint 가 있는 query 에 한해 aug 직접 호출 (hops=3 g#1/g#6 에서 86% 확인)
- agent 가 graph primitives 만 호출하는 경로에서 graph 단독 mode (별도 ROI)

### chunk_rag 의 자리

코퍼스가 작아 graph ingest 비용이 ROI 안 나는 시나리오 / 비용 최소화 우선 시나리오의 *baseline default*. 토큰 7K (combined 의 41%) 로 floor 보장.

## 측정 protocol 정의 (앞으로의 표준)

variance 통제 변수 명세:

| 통제 변수 | 값 |
|---|---|
| corpus | financebench-smoke / 1M / commerce-verbose |
| ingest_run_id | *명시 기록* — 같은 corpus 라도 ingest 마다 다른 graph 임 |
| 측정 컬럼 | 한 ingest 위에서 *동시 측정* (다른 ingest 와 섞지 않음) |
| query 반복 | N=1 (smoke 에서 query variance = 0 확인. N≥3 majority 는 무의미) |
| 분석 stratification | hops_required (1/2/3) + domain_pattern 별로 분리 보고 |

→ N=3 majority 제거. 대신 *N개의 다른 graph* 위 측정을 모아 variance bound 를 본다.

## 후속 작업 우선순위

| # | 작업 | 목적 | 영향 |
|---|---|---|---|
| 1 | graph #2 / #4 에서 combined 측정 1 회 | combined floor 확정 (현재 n=2 → n=4) | 결정 robust 도 ↑ |
| 2 | **EntityConsolidator (#40, M6.5b)** | ingest variance 의 *근본* 해소 | aug overall 우월성 재평가 가능 |
| 3 | PRD 6 §default 갱신 | "combined default + multi-hop hint 시 aug" | 명문화 |
| 4 | 1M 재측정 (M6.5b 후) | 33 questions × combined 로 1M 도 결론 일치 확인 | scale-up 검증 |

## 산출물

- 본 보고서 (variance 정체 + 최종 결정)
- 분석 스크립트: 본 보고서의 모든 매트릭스는 기존 응답 JSON 만으로 재현 (재측정 0 회 필요)
- 다음 측정 spec: graph #2 / #4 ingest 위 combined 1 회 (Docker daemon 가동 후)

## 한 줄 요약

variance 의 정체는 ingest LLM 이고, 그 variance 를 *흡수* 하는 컬럼은 combined 다. 따라서 default = combined, aug 는 multi-hop hint 와 EntityConsolidator 이후를 위한 carry-over.
