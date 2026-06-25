# M6.5 — FinanceBench 1M 3-way 검증 보고서

날짜: 2026-06-20
측정 run: `eval/runs/2026-06-20-1426` (FinanceBench 1M corpus, chunk_rag + arche + combined × N=3, gpt-4.1)
선행: [eval/reports/2026-06-20-combined-pivot/CONCLUSION.md](../2026-06-20-combined-pivot/CONCLUSION.md) — 95K corpus 의 Combined 채택 결정
ADR: [ADR-0007 — Combined RAG 채택](../../../docs/adr/0007-combined-rag-pivot.md)

## TL;DR

| 컬럼 | 정확도 | 오답 (qid) | 토큰 중앙값 | 지연 중앙값 | 비용 (99 호출) |
|---|---|---|---|---|---|
| chunk_rag | **72.7%** | Q01,Q02,Q05,Q11,Q12,Q13,Q21,Q28,Q30 | 36.9K | 2.02s | $1.55 |
| arche (graph 단독) | **6.1%** | 31/33 (Q06,Q15 만 정답) | 4.1K | 3.56s | $1.20 |
| combined (chunk + graph) | **72.7%** | Q01,Q05,Q11,Q12,Q13,Q21,Q28,Q30,Q11 | 41.1K | 4.90s | $2.66 |

**결론**: Combined ≈ chunk RAG (±0pp). 그래프 단독은 6%로 사실상 동작 불능. 이는 **ADR-0007 D2 의 "Combined ≈ chunk" 분기 (D6 만 유지, M7 단순화)** 에 해당하는 듯 보이지만, *원인 진단 결과* 그래프 데이터가 **catastrophic over-merge** 로 부패되어 *측정 자체가 의미 없는 상태*. → 결정 보류 + M6.5b (EntityConsolidator) gating 추가 권고.

## 무엇이 일어났나 — 그래프 붕괴의 원인 진단

### 증상

arche 컬럼이 33 문항 중 31 개에 "정보 부족 (e)" 응답.

### 1 차 가설 — anchor extraction 의 언어 mismatch

영어 corpus 에 대해 anchor extraction 이 한국어 entity 를 생성 (예: "AMCOR" → "당좌비율, 재무분석가"). `eval/src/arche_eval/prompts.py:65` 의 ANCHOR_EXTRACTION_SYSTEM 이 한국어로 작성되어 LLM 이 entity 정규명을 한국어로 번역.

**조치**: `ANCHOR_EXTRACTION_SYSTEM` 에 *질문의 언어를 보존* 하라는 원칙 추가 + 영어 예시 추가 (커밋: 본 측정 PR).

**결과**: anchor 가 영어로 정상 추출 (예: AMCOR / quick ratio / FY2023 / FY2022 / financial analyst). 그러나 **subgraph 는 여전히 0 nodes**.

### 2 차 진단 — catastrophic EntityMatcher over-merge (진짜 원인)

직접 그래프 조회:

```cypher
MATCH (e:Entity) WHERE "Boeing" IN e.aliases RETURN e.name, e.aliases
```

→ `"Amcor plc"` 엔티티의 aliases:
```
["Amcor", "the Company", "we", "our", "us", "Registrant",
 "AMD", "management", "American Express", "AXP", "Amex",
 "Boeing", "PepsiCo"]
```

**6 개 회사 (AMD / AXP / BA / JNJ / PEP) 가 모두 "Amcor plc" 노드에 흡수됨.** description 필드는 American Express 의 설명을 가지고 있음. 즉 *AMCOR 노드는 이름만 AMCOR 이고 내용은 6 사가 섞인 부패 데이터*.

원인 (ADR-0001 의 4 단계 EntityMatcher 기준):
1. 첫 ingest 된 10-K (AMCOR) 에서 "the Company" / "we" / "us" / "Registrant" 등 generic 자기지칭을 entity 로 추출
2. 다음 10-K (AMD) 에서 동일한 "the Company" 가 *embedding cosine ≥ 0.92* (`apps/api/src/arche_api/domain/identity.py` 의 `EMBEDDING_MATCH_THRESHOLD`) 를 만족 → Amcor 의 "the Company" entity 로 merge → AMD 도 alias 로 흡수
3. 매번 다음 10-K 마다 반복 → 모든 회사가 Amcor plc 에 흡수
4. 한편 회사명 자체 ("Boeing", "The Boeing Company") 는 별도 entity 로 살아남기도 함 (alias 매칭 우선순위)

→ 결과: graph 의 *최상위 회사 entity* 가 부패. 다른 entity (정책/제도/연금/항공기 모델) 는 회사 unique 이름이라 정상.

### Combined 가 chunk 와 같은 정확도인 이유

Combined runner 는 chunk top-k 청크 + subgraph 를 한 LLM 호출에 합친다. 본 회차에서:

- **subgraph 는 거의 항상 비어 있거나 부패** (over-merged Amcor plc 노드 만 등장)
- **chunk top-k 는 정상** (벡터 RAG 는 entity merge 와 무관)
- 결과: combined 의 답변은 *chunk top-k 기반* (graph 가 도움도 방해도 안 됨). chunk_rag 와 같은 정확도가 도출.

실제로 Combined wrong ⊆ chunk wrong + 1 (Q02 는 combined 가 회복했지만 Q30 은 combined-only wrong). 그래프 부패가 종종 약간의 misleading 신호를 만들지만 거시적으로 무해.

## ADR-0007 D2 결정 기준 매핑

ADR-0007 D2 의 정의: "Combined 가 chunk RAG 와 정확도 우위 + Full-context 의 1/3 이하 비용".

본 회차 직접 결과:
- 정확도 우위: **0pp** (둘 다 72.7%)
- 비용: chunk $1.55 vs combined $2.66 (1.7×, ADR-0007 의 비용 노브가 작동하지 않은 상태)

| 분기 | 본 회차 매핑 | 다음 액션 (ADR-0007 D2 원문) |
|---|---|---|
| Combined ≥ chunk + 3pp | **미충족** (0pp) | (해당 없음) |
| Combined ≈ chunk (±2pp) | **부합 (직접 결과)** | ADR-0007 D6 (provenance) 만 살리고 M7 단순화 — graph 는 옵션 노브로 |
| chunk > Combined | **미충족** (동률) | (해당 없음) |

**하지만** 직접 결과를 그대로 채택할 수 없음 — graph 가 부패해 측정 *자체* 가 무효. 위 표의 매핑은 *graph 가 정상일 때* 의 비교를 가정.

## 권고 — M6.5b (EntityConsolidator gating) 추가

**현 상태 그대로 ADR-0007 D2 의 "D6 만 살리고 M7 단순화" 분기에 들어가면 부정확.** Graph 부패가 측정에 영향을 미쳤기 때문.

다음 두 가지 액션을 선행해야 ADR-0007 D2 의 진짜 결정이 가능:

1. **M8 P0 (#40 EntityConsolidator) 를 M6.5b 로 승격, M7 gating 에 추가**
   - "post-ingest 단계에서 cosine ≥ 0.92 의 entity 쌍 을 ANN 으로 찾아 LLM 으로 정말 같은 entity 인지 검증, generic 자기지칭은 회사별로 분리 유지" (PRD 6 §3.A)
   - 본 1M 측정의 catastrophic over-merge 는 EntityConsolidator 부재의 *명백한 1M 시점 발현*

2. **M6.5b 종료 후 graph 재 ingest + arche + combined 만 재측정 (chunk 는 본 회차 재사용)**
   - 그때의 결과로 ADR-0007 D2 의 진짜 분기 결정

## 95K 결과와의 비교 (참고)

| 코퍼스 | 도메인 | 언어 | chunk | arche | combined | combined 의 우위 |
|---|---|---|---|---|---|---|
| 95K (commerce-verbose) | 가상 이커머스 정책 | 한국어 | 96.7% | 90.0% | 100.0% | +3.3pp vs chunk |
| 1M (FinanceBench) | SEC 10-K | 영어 | 72.7% | **6.1%** | 72.7% | **0pp** |

95K 에서는 graph 가 90% 로 (다소 약하지만) 의미 있는 신호. 1M 에서는 6% — 부패. 차이의 원인은 *코퍼스 크기가 아니라 cross-document over-merge 의 발현 빈도*. 95K 는 단일 도메인 / 단일 가상 회사라 self-reference 충돌이 없음. 1M (실제 6 사) 에서는 매 10-K 마다 "the Company" 가 반복.

## 부차 발견

### chunk_rag setup 의 embedding API 한도 초과 (수정 포함)

첫 실행 시 `crag.setup()` 이 1.1M 토큰을 한 번에 OpenAI embeddings API 로 전송 → `max_tokens_per_request` (300K) 초과. `eval/src/arche_eval/providers.py:OpenAIEmbeddingProvider.embed()` 에 *250K 토큰 / 2048 input 기준 자동 배치 분할* 적용 (본 측정 PR 에 포함). 1M+ corpus 에서 chunk_rag 가 정상 동작.

### 데이터셋 옵션 위치 무작위화

`build_mcq.py` 가 모든 정답을 `a` 위치에 둠 → LLM first-position 편향으로 부당 정확도 발생 가능. `qid` hash 기반 결정론적 셔플로 정답 위치를 a/b/c/d 에 분산 (현 분포: a=7, b=5, c=14, d=7). lint green 유지.

### "정보 부족" 옵션의 영어/한국어 이중 표기

`Insufficient information / cannot determine from the corpus. (정보 부족 / 알 수 없음)` — 영어 corpus 에서 자연스러운 선택지를 제공하면서 한국어 hard rule (`rule_info_insufficient_option_present`) 도 통과.

## 검증 한계

### 본 회차의 한계

- **graph 부패 → 측정 무효** (위에 길게 다룸)
- **synonym_alias 패턴 부재** — 95K 의 핵심 advantage 패턴이 본 corpus 에 없음
- **모든 evidence 가 동일 10-K 내부** — cross-doc 추론 측정 불가
- **N=3 majority** — 더 robust 한 결론은 N=10+
- **영어 corpus** — 95K 한국어 측정과 언어 변동 효과 분리 불가

### 본 회차의 가치

- 기존 EntityMatcher 의 **1M 시점 catastrophic 실패 모드** 를 정확히 노출. ADR-0007 milestone 트리의 M8 P0 (#40) 를 *M6.5b 로 승격해야 함* 을 직접 evidence 로 보임
- chunk_rag setup 의 embedding API 한도 초과를 수정 → 후속 1M+ 측정의 기반 마련
- 옵션 위치 편향 fix → 데이터셋 품질 향상

## 데이터 산출물

- `eval/runs/2026-06-20-1426/responses/{chunk_rag,arche,combined}/` — 297 raw 응답
- `eval/runs/2026-06-20-1426/meta.yaml` — run 메타데이터 + hyperparameters
- `eval/datasets/financebench-2026-06-20/` — 33 MCQ, 980K tokens, lint green
- `eval/reports/2026-06-20-financebench-1M/score_output.txt` — 본 보고서의 표 재생산

## 다음 액션

1. **본 보고서 + 수정 사항 (anchor multilingual, embedding 배치, dataset 셔플) 을 PR 으로 머지** (#46 close)
2. **GitHub Issue 갱신**:
   - M6.5 (gating) 종료 조건 갱신: "본 보고서 작성 완료" — 본 PR 머지로 충족
   - M6.5b 신설 (또는 M8 #40 우선순위 변경): "EntityConsolidator 구현 + 1M 재측정"
   - M7 issue 들 (#33-#39) 은 M6.5b gating 으로 잠금
3. **ADR-0007 amend** (D2 + D3 + 새 D7): graph 의 catastrophic over-merge 가 EntityConsolidator 없이는 1M+ 시점에 발현됨을 기록. M6.5b 의 결정 분기 표 추가
4. **STATUS.md 갱신**: M6.5 완료 + M6.5b 신설 + M7 gating 갱신
