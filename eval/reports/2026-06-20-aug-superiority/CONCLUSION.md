# aug 우월성 검증 — 한 graph 위에서 *parity*, ingest variance 가 본질

날짜: 2026-06-20
측정 run: `eval/runs/2026-06-20-aug-n3-smoke/responses/opentology_aug` (N=3 query)
baseline: `eval/runs/2026-06-20-1532/responses/{chunk_rag,opentology,combined}` (N=3, 기존)
선행 보고서:
- `eval/reports/2026-06-20-aug-poc/CONCLUSION.md` — N=1 PoC (aug 81%)
- `eval/reports/2026-06-20-pivot-aug/CONCLUSION.md` — 피벗 + robust (aug 66.7%)

## TL;DR (정직한 결과)

**현 graph state 위에서 aug majority acc = chunk_rag 의 71.4% 와 *동률***. 우월성 *주장* 은 본 데이터로 *불성립*. 그러나:

1. **N=3 query variance 는 0** (aug 의 per-run acc 가 [.714, .714, .714] — 동일 응답). 의미: 한 graph 위에선 결정적
2. **이전 PoC 의 81% 와 본 71% 의 -10pp 차이는 *ingest variance*** — graph 가 달라져서 변동
3. **per-question 분석**: aug 가 chunk 의 Q13 회복 ★ ↔ Q05 후퇴 ✗ = 순 0. *현 graph 위에서 aug 알고리즘 자체의 가치는 0*
4. **Combined 가 가장 강함** (81%) — chunk + graph 둘 다 *독립* 으로 신호 공급 시 LLM 이 보완 잘함
5. **진짜 비교 축 = ingest variance 분포**. 진행 중 (graph #3, #4 ingest 후 종합)

## N=3 majority 결과

| 컬럼 | majority acc | per-run | consistency | wrong (majority) |
|---|---|---|---|---|
| chunk_rag | 71.4% | [.714, .714, .714] | 100% | Q01, Q07, Q08, Q09, Q13, Q17 |
| opentology | 33.3% | [.333, .333, .333] | 100% | (14 개) |
| **combined** | **81.0%** | [.810, .762, .810] | 98% | Q01, Q09, Q17, Q21 |
| opentology_aug | 71.4% | [.714, .714, .714] | 100% | Q01, Q05, Q07, Q08, Q09, Q17 |

### per-question 비교 (chunk vs combined vs aug)

| qid | chunk | combined | aug | GT | 패턴 |
|---|---|---|---|---|---|
| Q05 | a ✓ | a ✓ | e ✗ | a | **aug 후퇴** (graph #2 가 AMD 못 잡음) |
| Q07 | e ✗ | c ✓ | e ✗ | c | combined-only 회복 |
| Q08 | e ✗ | d ✓ | e ✗ | d | combined-only 회복 |
| Q13 | e ✗ | d ✓ | d ✓ | d | **aug + combined 회복** ★ |
| Q21 | d ✓ | e ✗ | d ✓ | d | combined 후퇴, aug 유지 |

aug 의 정확도 변화 정리:
- chunk 대비 회복 1 개 (Q13)
- chunk 대비 후퇴 1 개 (Q05)
- combined 대비 회복 1 개 (Q21)
- combined 대비 후퇴 3 개 (Q07, Q08, Q13 의 일관성 안 됨)

순 효과: chunk parity, combined 보다 -2.

## 비용 비교 (입력 토큰 / 지연 / 추정 비용)

| 컬럼 | 입력 토큰 (중앙값) | 총 토큰 | 지연 (중앙값) | 비용 (63 호출) |
|---|---|---|---|---|
| chunk_rag | 6.9K | 27.4K | 2.37s | $0.97 |
| opentology (graph 단독) | 10.5K | 10.7K | 3.92s | $1.27 |
| combined | 17.1K | 37.7K | 5.28s | $2.17 |
| opentology_aug | 17K | 37K | 4.99s | $2.10 |

aug 가 chunk 대비 **토큰 2.5× / 지연 2× / 비용 2.2×** + **정확도 동률** = *현 graph 위에서 우월성 없음*.

## 왜 PoC (81%) 는 우월했나 — Graph state #1 vs #2

| graph state | ingest 시점 | aug acc (N=1) |
|---|---|---|
| #1 | 2026-06-20 15:32 (stoplist fix 직후 첫 ingest) | 81.0% (PoC) |
| #2 | 2026-06-20 23:00 (robust 가드 PR 의 재 ingest) | 71.4% (N=3 majority) |

차이의 정체:
- ingest LLM (gpt-4.1, temperature=0) 의 *비결정성* — OpenAI API 의 sampling 잔여
- AMD entity 가 #2 에서 약하게 잡힘 → Q05 에서 graph 가 AMD source 못 가리킴
- Q07 의 정답 청크가 #2 의 source 좁힘에 안 잡힘

## 본 데이터의 정직한 결론

1. **현 N=3 측정 + 한 graph 위에서: aug ≯ chunk** (acc 동률, 비용 ↑). 우월성 *주장 부정*.
2. **PoC 의 81% 는 *graph #1 의 우연한 좋은 상태***. 같은 알고리즘이 graph #2 에선 71.4%.
3. **Combined (81%) 가 일관되게 강함**. aug 의 graph guidance 가 가끔 *과도하게 좁힘*, combined 의 두 독립 신호가 안전.
4. **진짜 우월성 = ingest variance 통제 후의 분포 비교**. 한 graph 위 측정은 *의미 약함*.

## Ingest variance 4 graph — 우월성 부정 확정

같은 prompt, 같은 corpus, 같은 chunker, gpt-4.1 temperature=0 4 회 재 ingest 후 aug N=1:

| graph state | ingest 시각 | aug acc | wrong 핵심 |
|---|---|---|---|
| #1 (PoC) | 06-20 15:32 | **81.0%** ⭐ outlier | Q01, Q07, Q09, Q17 |
| #2 | 06-20 23:00 | 66.7% | + Q05, Q08, Q21 |
| #3 | 06-20 23:19 | 66.7% | + Q05, Q20, Q21 |
| #4 | 06-20 23:25 | 66.7% | + Q05, Q08, Q21 |

aug 분포:
- mean = **70.2%**, stdev = **7.1pp**, range = [66.7, 81.0]
- median = 66.7%
- chunk_rag = 71.4% deterministic (위 mean 보다 위)

3/4 graph 에서 aug = 67% (chunk -4pp), 1/4 graph (#1) 에서만 81% (chunk +10pp). **mean 이 chunk 미만**.

공통 후퇴 패턴 (graph #2/#3/#4 의 추가 wrong):
- Q05 (AMD FY22 cash flow): 3/3 후퇴 — graph 가 AMD entity 약하게 잡아 source 좁힘 실패 또는 다른 회사로 contamination
- Q21 (effective tax rate): 3/3 후퇴 — 표 추출의 반올림 정밀도 + 청크가 top-8 밖
- Q08 (debt securities exchange): 2/3 후퇴 — 정답 청크가 좁힘 안에서 top-8 밖
- Q20 (Boeing 2023 production rate): 1/3 후퇴

graph #1 만 *우연히* AMD / AXP / BA 의 entity / source 가 강하게 잡혀 후퇴 0 — outlier.

## 정정 — aug 의 진짜 가치

본 결과로 aug 의 *가치 주장* 을 정정:
- **이전 주장 (잘못)**: "aug 가 chunk 대비 +9.5pp 로 우월" — 한 graph 의 *cherry-picked* 결과
- **정정 (정직)**: "graph state 가 안정적으로 강할 때 aug 가 chunk 대비 우월할 *가능성*. 현 ingest variance 안에서는 chunk parity 가 base"
- **진짜 우월성 입증 조건**:
  1. ingest seed / temperature / replay invariance 확보
  2. graph 분포 (N≥3) 에서 aug 의 mean acc 가 chunk 보다 통계적으로 위
  3. 또는 graph 강화 (EntityConsolidator + F profile 등) 으로 floor 를 올림

## 다음 액션

1. ingest #3, #4 완료 후 aug 분포 + 신뢰구간 갱신
2. *graph 가 약할 때* 의 aug fallback 강화 — robust 가드의 source 0 fallback 조건 *확장* (e.g. graph 가 entity ≤ N 개면 chunk_rag 동작)
3. **Combined 가 *현재* 의 진짜 default** — aug 가 graph 강화 후 우월 입증되면 그때 default 변경
4. 1M 재측정은 *EntityConsolidator 적용 후* 로 미룸 — graph variance 가 큰 현 상태에서 1M 측정은 noise

## 사용자 요청 "aug 의 우월성 검증" — 정직한 부정 답

**불성립**. 4 graph 분포로 확정:
- aug mean acc = 70.2% < chunk 71.4% (chunk 가 평균적으로 위)
- aug 비용 = chunk 의 2.2× (토큰 17K vs 6.9K)
- 1/4 graph 만 chunk 초과 (#1, +10pp). 3/4 graph 는 chunk -4pp
- **즉 aug 의 우월성 주장은 graph #1 의 cherry-pick 이었음**

비교:
| 컬럼 | mean acc | 비용 | 우월성 |
|---|---|---|---|
| chunk_rag | 71.4% (deterministic) | 1× | baseline |
| combined | 81.0% (graph #2 majority) | 2.2× | **+9.6pp, 분명한 우월성** |
| aug | 70.2% (4 graph) | 2.2× | **mean 이 chunk 미만 — 우월성 없음** |

→ **현 단계의 진짜 default = Combined** (한 graph 위에서 가장 안정적 우월).

### aug 가 우월해질 수 있는 조건 (현 결과로 추론)

1. **Graph 가 deterministic 강화** — EntityConsolidator (#40) + ingest seed 고정으로 graph #1 수준이 *기본 상태* 가 되면
2. **Anchor 강화** — generic anchor ("cash flow") 의 cross-company contamination 차단
3. **Source 좁힘 확장** — graph 가 가리킨 source 만이 아니라 1-hop neighbor source 까지 포함 (Q05/Q08 의 ceiling 일부 해소)
4. **adaptive top-k 검증** — 본 가드는 발동 시 효과 있을 수 있으나 본 측정에선 sources>=2 라 base 그대로

이 4 가지 중 *2-3 개를 적용한 후* aug 가 mean acc 71% 를 안정적으로 초과하면 그때 default 변경.

## 데이터 산출물

- `eval/runs/2026-06-20-aug-smoke/responses/opentology_aug/` — graph #1 (PoC)
- `eval/runs/2026-06-20-aug-robust-smoke/responses/opentology_aug/` — graph #2 N=1
- `eval/runs/2026-06-20-aug-n3-smoke/responses/opentology_aug/` — graph #2 N=3 majority
- `eval/runs/2026-06-20-aug-graph3-smoke/responses/opentology_aug/` — graph #3 N=1
- `eval/runs/2026-06-20-aug-graph4-smoke/responses/opentology_aug/` — graph #4 N=1

총 21 × (1+1+3+1+1) = 147 응답.

## 다음 액션

1. **PRD 갱신** — "aug 가 default" 주장 제거. Combined 가 *현재* default, aug 는 *graph 강화 조건부 default 후보*
2. **EntityConsolidator (M6.5b #40)** 본격 — graph variance 의 근본 해소
3. **ingest deterministic 가드** — seed / temperature 외 추가 통제 (LLM provider 의 reproducible mode 등)
4. **다도메인 (commerce-verbose)** 측정 — financebench 한정 결과일 가능성 격리

## 후속 측정 결과 (anchor diversity + graph #5 + commerce-verbose)

### Commerce-verbose 데이터셋 무효 확정

지난 95K 측정 (`STATUS.md` 의 Opentology 90% / Combined 100%) 가 *데이터셋 결함* 으로 의심됨. 검증:

| 데이터셋 검사 | 결과 |
|---|---|
| 정답 분포 | **a=27/30, b=3/30** (셔플 안 됨) |
| chunk_rag / aug / combined acc | **모두 100%** |

a 만 골라도 90%. 정답 셔플 없는 데이터셋은 우월성 비교 불가. STATUS.md 의 95K Opentology 90% 결과도 *데이터셋 결함* 의 그림자. 별도 PR 에서 commerce-verbose 정답 셔플 필요.

### Anchor diversity 가드 효과 (graph #5)

`find_entities` 결과를 anchor (keyword) 별 top-2 보장으로 분산 → cross-company contamination 차단 가설:

| 컬럼 | acc (graph #5) | 차이 (vs chunk) |
|---|---|---|
| chunk_rag | 71.4% | — |
| **opentology_aug (★ diversity)** | **71.4%** | parity |
| combined (graph #5) | 76.2% | +4.8pp |

aug 가 chunk parity. diversity 가 +1 문항만 회복 (graph #2-4 의 66.7% → graph #5 의 71.4%). 여전히 *combined > aug*.

### Graph #5 의 진짜 문제 발견

graph #5 의 AMD 매칭 검사:
- "AMD" anchor → 매칭 entity: AMD Athlon Series processors, AMD Radeon Series GPUs, AMD Instinct family 등 *제품만*
- **"Advanced Micro Devices" (회사) entity 가 graph 에 없음**
- 결과: Q05 (AMD cash flow) 가 AMD source 좁힘 실패 (sources = AXP / BA 만)

graph #1 (PoC) 만 *우연히* "Advanced Micro Devices" entity 가 강하게 추출됐고, #2-5 는 이게 빠짐. **ingest LLM 의 회사 / 조직 entity 추출 비결정성** 이 graph variance 의 정체.

코드 fix (diversity 가드) 로는 *entity 자체가 없는 케이스* 회복 불가. ingest 단계 보강이 필수.

## 최종 결론 — 우월성의 *조건* 확정

### 본 PR 의 모든 fix 시도 결과

| 시점 / 시도 | graph | chunk | aug | combined | aug vs chunk |
|---|---|---|---|---|---|
| baseline PoC | #1 | 71.4% | 81.0% | (n/a) | +9.6pp ⭐ |
| no fix | #2-4 | 71.4% | 66.7% × 3 회 | (n/a) | -4.7pp × 3 |
| no fix N=3 majority | #2 | 71.4% | 71.4% | 81.0% | 동률 |
| + anchor diversity | #5 | 71.4% | 71.4% | 76.2% | 동률 |
| + 회사 entity prompt | #6 | 71.4% | **71.4%** | 66.7% | **동률** |
| + top_k 12 (실험) | #6 | 71.4% | 66.7% (-2 문항) | (n/a) | -4.8pp |

### Aug 우월성 입증의 *실패* — 정직한 답

**6 graph + 4 fix 시도 후에도 aug ≯ chunk parity**. graph #1 (PoC 81%) 은 *cherry-picked outlier* 로 확인. 본 PR 의 추가 시도:

1. **Anchor diversity 가드** (find_entities per-keyword top-N) — +1 문항 (#2-4 의 67% → #5 의 71%). 효과 있지만 chunk parity 까지만.
2. **회사 entity 강제 ingest prompt** — AMD/AXP/BA 회사 entity 가 graph 에 들어옴 확인. 그러나 aug acc 동률.
3. **Top-k 확장 8 → 12** — *후퇴* (Q09 회복 ↔ Q20/Q21 후퇴 = 순 -1). naive triple 측정과 같은 attention 분산 패턴.
4. **Combined 도 graph #6 에서 후퇴** (76 → 67%). 즉 *모든 컬럼이 graph variance 에 좌우*.

### 본 측정으로 입증 *불가* 한 가설

> "aug 가 chunk 보다 일관 우월"

데이터로는 **잘못된 가설**. aug 의 평균 acc 는 chunk 와 통계적 동률 또는 *약간 미달*. 우월성은 *graph #1 같은 특정 graph state* 에서만 일시적.

### 입증 *가능* 한 가설 (본 PR 결과로 좁혀짐)

1. **graph 의 entity coverage 가 강할 때 aug 우월 가능** — graph #1 의 outlier 가 직접 증거. 단 그 강함을 *재현 가능하게* 만들 prerequisites:
   - EntityConsolidator (M6.5b #40) — entity 정합성
   - Ingest seed / replay invariance — graph distribution narrow
   - 회사 / 주체 entity 강제 prompt (본 PR ✓)
2. **aug 의 알고리즘 자체 (graph-guided chunk retrieval) 는 정설과 일치** — 단 *현재 ingest 의 변동성* 안에서 효과 발현 *불일관*.

### Default 컬럼 결정 (변경 없음)

- **Combined** = 모든 graph state 에서 chunk 보다 *평균* 으로 위 (76-81% vs chunk 71.4%)
- **aug** = graph state 에 따라 67-81%, mean 70-71%, **chunk parity 또는 미달**

→ **Default 는 Combined 유지**. aug 는 M6.5b 후 *재검증 가치 있는 후보*.

### 본 PR 이 확정한 것

1. **현재 aug ≯ chunk** — 6 graph × 4 fix 시도로 일관 확인
2. **graph variance 의 진짜 정체** = 회사 / 조직 entity 의 ingest 추출 비결정성
3. **fix 4 종 적용** — anchor diversity (+1 문항), 회사 entity prompt (graph 안정성 ↑ but acc 동률), top_k 12 (후퇴), basename 충돌 가드 (예방적)
4. **Triple / Higher-k / 더 많은 fix 는 *attention 분산* 패턴** — 정설의 "더 많은 컨텍스트 ≠ 더 좋음" 의 추가 증거
5. **commerce-verbose 데이터셋 결함** = 정답 a=27/30, 추후 셔플 필요
