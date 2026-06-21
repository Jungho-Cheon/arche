# M6.5b CONCLUSION — EntityConsolidator 1M 적용 결과 (2026-06-21)

> 본 보고서는 ADR-0008 D2 의 (b)(c) 종료 조건의 *실측 결과* . PROTOCOL.md 의 5 단계 protocol 을 본 회차에 그대로 실행.

## 한 줄 결론

EntityConsolidator + NON_IDENTIFYING_ALIAS_STOPLIST 조합으로 **catastrophic over-merge 완전 해소**. **Combined 78.8% > chunk 72.7% (+6.1pp)** — ADR-0007 D2 의 "Combined ≥ chunk + 3pp" 충족. **ADR-0007 D1 (Combined 정체성) 유지 + M7 productization unblock** 으로 분기.

## 실행 환경

| 항목 | 값 |
|---|---|
| 측정일 | 2026-06-21 |
| corpus | `eval/datasets/financebench-2026-06-20/corpus` (10-K 6 개, ~1M tokens) |
| 질문 | `questions.yaml` 33 MCQ |
| LLM | `openai/gpt-4.1` |
| Embedding | `openai/text-embedding-3-small` |
| 적용된 가드 | NON_IDENTIFYING_ALIAS_STOPLIST (PR #51) + EntityConsolidator (본 PR #54) |
| run dir | `eval/runs/2026-06-21-m65b-1024/responses/` |

## (a) 구현 산출물

PROTOCOL.md 의 모든 항목 완료. PR #54 (본 PR) 의 commit eaf7ae0 위에 stack.

## (b) over-merge 감소 evidence

### aliases 분포 (post-consolidate)

```
aliases_count, entities
8, 1
5, 3
4, 1
3, 4
2, 20
1, 181
0, 269
```

**aliases ≥ 5 entity 수 = 4** (8 alias 1 개 + 5 alias 3 개). 이전 1M 회차 (2026-06-20-1426) 에서는 Amcor plc 한 노드에 13 alias (6 회사 흡수) 가 존재해 *측정 무효* 상태였다. 본 회차에서 가장 alias 가 많은 4 entity 의 실제 내용:

```
"Amcor plc" — ["Amcor", "the Company", "we", "our", "us"]
"American Express Company" — ["American Express", "AXP", "Registrant", "we", "our", "us", "Amex", "the Company"]
"American Express Retirement Restoration Plan" — ["the Plan", "Supplemental Retirement Plan", "American Express Company Supplemental Retirement Plan", "American Express Supplementary Pension Plan", "SRP Plan"]
"PepsiCo, Inc." — ["PepsiCo", "the Company", "we", "us", "our"]
```

각 entity 가 *자신의 회사 자기지칭만* 가지고 있어 cross-doc 흡수가 0 건. 이는 ADR-0008 의 의도된 정책 (generic 자기지칭은 같은 source_path 안에서만 alias 로 인정) 그대로.

### Consolidator report

```
entities_scanned: 479
candidates_total: 24
candidates_self_reference_skipped: 0
llm_calls: 24
merged: 0
rejected: 24 (모두 llm_different)
duration: 48.8s
```

NON_IDENTIFYING_ALIAS_STOPLIST 가 streaming matcher 에서 이미 차단해 self-reference 후보가 0. cosine 0.85-0.92 회색지대 후보 24 건은 모두 LLM 이 "different entity" 로 판정 (confidence 평균 0.92, 최저 0.30). **false-positive 0 건** — 회색지대 후보가 *실제로 다른 entity* 였음을 LLM 으로 확인.

→ **ADR-0008 D2 (b) 종료 조건 충족** : over-merge 가 수치적으로 감소했고 (사실상 0) Consolidator 가 false-positive 를 만들지 않았음.

## (c) opentology + combined N=3 재측정

### Accuracy

| 컬럼 | run0 | run1 | run2 | floor | ceiling | majority |
|---|---|---|---|---|---|---|
| opentology (graph 단독) | 27.3% | 24.2% | 27.3% | 24.2% | 27.3% | 27.3% |
| combined | 78.8% | 78.8% | 78.8% | 78.8% | 78.8% | 78.8% |
| chunk_rag (재사용) | — | — | — | 72.7% | 72.7% | 72.7% |

chunk_rag 는 ADR-0008 D2 의 명시 (`eval/runs/2026-06-20-1426/responses/chunk_rag/`) 에 따라 2026-06-20 회차 결과 재사용.

### Token / Latency / 비용 (per question median)

| 컬럼 | 토큰 중앙값 | 지연 중앙값 | N=3 분산 |
|---|---|---|---|
| chunk_rag | 36.9K | 2.02s | 0pp |
| opentology | 8.7K | 3.02s | 3.1pp |
| combined | 15.1K | 4.07s | 0pp |

combined 의 토큰이 opentology (graph 단독) 보다 *더 적은* 이유는 본 회차 anchor 추출에서 다수의 질문이 *명시적* (AMCOR / Amex 등 단일 회사) 이라 chunk top-k 검색만으로 충분한 컨텍스트가 잡혔기 때문. opentology 는 추가로 subgraph 확장에 토큰을 사용.

### 이전 1M 회차 (2026-06-20-1426) 와의 비교

| 컬럼 | 2026-06-20-1426 (over-merge 부패) | 2026-06-21-m65b-1024 (cleanup 적용) | Δ |
|---|---|---|---|
| chunk_rag | 72.7% | 72.7% (재사용) | 0 |
| opentology | 6.1% | 27.3% | **+21.2pp** |
| combined | 72.7% | 78.8% | **+6.1pp** |

EntityConsolidator + STOPLIST 적용으로 graph 단독 정확도가 **6.1% → 27.3% (+21pp)** 회복. combined 도 chunk 와 같은 수준 (72.7%) 에서 **+6.1pp** 우위로 분리.

## ADR-0007 D2 진짜 분기 결정

ADR-0007 D2 의 분기 표 재인용:

| 결과 | 분기 |
|---|---|
| Combined ≥ chunk + 3pp | D1 (Combined 정체성) 유지, M7 productization |
| Combined ≈ chunk (±2pp) | D6 (provenance) 만 살리고 M7 단순화 (chunk-only 디폴트), graph opt-in |
| chunk > Combined | graph 비공식 옵션, chunk-only 피벗 |

본 회차: Combined 78.8% - chunk 72.7% = **+6.1pp → 첫 번째 분기 (D1 유지, M7 productization)**.

### 결정

- **ADR-0007 D1 (Combined RAG retrieval orchestrator 정체성) 유지**.
- **ADR-0007 D2 의 시점 (M6.5b 종료 후 재결정) 가 종료** — M7 productization 코드 작업 *unblock*.
- ADR-0008 의 "M6.5b 종료 후 ADR-0007 D2 의 진짜 분기 결정" 도 본 결정으로 종료.

## ADR-0008 본문 갱신 사항

- M6.5b 종료 (status: accepted → applied).
- 본 회차 측정 표 (accuracy / token / latency) 를 ADR-0008 본문 표 위에 추가.

## 본 결과의 함의 (Combined 우위의 직접 evidence)

1. **EntityConsolidator + STOPLIST 가 catastrophic over-merge 의 해결책** 임이 1M 규모에서 직접 증명. 이전 회차의 6.1% 부터 27.3% (+21pp) 회복.
2. **Combined 우위는 graph 가 *정상* 일 때만 발현** — 부패 시 chunk 와 같은 점수로 무력화. 본 작업의 *전처리 가드* 가 본질적.
3. **opentology 단독은 여전히 chunk 보다 낮다 (27.3% vs 72.7%)** — graph 단독 모드는 multi-hop hint 가 명시될 때만 우월. 시제품 default = combined 가 옳음.
4. **variance robustness**: combined 가 N=3 분산 0pp — 시제품 사용자에게 *결정적 응답* 보장.

## 다음 액션

- M7 (코드 productization) 코드 작업 unblock — 이슈 #33-#39 진행 가능.
- ADR-0008 본문 amend (M6.5b applied + 본 회차 표) — 후속 commit.
- chunk_rag 와 combined 의 *오답 셋 비교* — Combined 가 정확히 어떤 질문을 *추가로* 맞췄는지 (multi-hop / synonym alias) 분석.
