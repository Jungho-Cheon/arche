# ADR-0008: M6.5 1M 측정 결과 + EntityConsolidator 를 M7 gating 으로 격상

Status: accepted, M6.5b applied 2026-06-21
Date: 2026-06-20 (decision), 2026-06-21 (M6.5b applied)
Amends: [ADR-0007](./0007-combined-rag-pivot.md)

## 2026-06-21 amendment — M6.5b 종료 + ADR-0007 D2 분기 결정

본 ADR 의 D2 에 명시된 M6.5b (EntityConsolidator) 가 PR #54 로 구현 + 같은 corpus 에 적용 + N=3 재측정 완료. 결과 표 (PROTOCOL.md + CONCLUSION.md 의 요약):

| 컬럼 | M6.5 (2026-06-20-1426) | M6.5b (2026-06-21-m65b-1024) | Δ |
|---|---|---|---|
| chunk_rag | 72.7% | 72.7% (재사용) | 0 |
| opentology (graph 단독) | 6.1% | 27.3% (N=3 majority) | **+21.2pp** |
| combined | 72.7% | **78.8% (N=3 majority, variance 0pp)** | **+6.1pp** |
| aliases ≥ 5 entity 수 | 13 alias 단일 노드 (Amcor plc) 외 다수 부패 | 4 (정상 자기지칭만) | over-merge 해소 |

본 결과로 ADR-0007 D2 의 *진짜 분기* (M6.5b 종료 후 재결정) 가 종료된다.

- **Combined 78.8% > chunk 72.7% (+6.1pp)** — ADR-0007 D2 의 "Combined ≥ chunk + 3pp" 충족.
- **ADR-0007 D1 (Combined 정체성) 유지**.
- **M7 (productization 코드 작업) unblock** — 본 ADR 의 D4 ("M6.5b 종료 전 M7 코드 착수 보류") 도 해제.

상세는 [eval/reports/2026-06-21-m65b-consolidator/CONCLUSION.md](../../eval/reports/2026-06-21-m65b-consolidator/CONCLUSION.md).

## TL;DR

ADR-0007 (Combined RAG 채택) 의 D2 가 정의한 1M 시점 재검증 (M6.5) 을 2026-06-20 FinanceBench 1M corpus (980K tokens, 33 MCQ) 에 실행했다. 결과 **chunk_rag 72.7% / opentology 6.1% / combined 72.7%** — Combined 가 chunk 와 같은 정확도. 표면적으로 ADR-0007 D2 의 "Combined ≈ chunk → D6 만 살리고 M7 단순화" 분기로 들어가야 하지만, *진단 결과* graph 데이터가 **catastrophic over-merge** 로 부패해 측정 자체가 무효.

본 ADR 은 다음을 결정한다.

1. **ADR-0007 D2 의 결정은 보류** — graph 가 정상 상태가 아닌 1M 측정으로 정체성 결정을 바꾸지 않는다.
2. **EntityConsolidator (기존 M8 P0, 이슈 #40) 를 M6.5b 로 승격**하고 M7 (productization) 의 gating 에 둔다.
3. **M6.5b 종료 후 opentology + combined 만 재측정**해 ADR-0007 D2 의 진짜 분기를 결정한다.
4. ADR-0007 의 본문 (정체성, D1, D3-D6) 은 *유지*. 본 ADR 은 M6.5 결과를 *측정 evidence 의 추가* 로 기록하며, ADR-0007 D2 의 *결정 시점만 지연* 한다.

후속 PR / 이슈는 본 ADR 의 결정을 milestone 트리에 반영한다.

> 용어 인라인 풀이.
>
> - **catastrophic over-merge**: EntityMatcher 의 cosine ≥ 0.92 임계값이 *generic 자기지칭* ("the Company", "we", "us") 을 cross-document 에서 동일 entity 로 합쳐, 6 개 회사 (AMD / AXP / BA / JNJ / PEP) 가 모두 "Amcor plc" 노드 한 곳에 흡수된 1M 시점 발현 모드.
> - **EntityConsolidator**: post-ingest 단계에서 ANN (approximate nearest neighbor) + LLM 검증으로 "정말 같은 entity 인지" 를 확인하고 *generic 자기지칭은 회사별로 분리 유지* 하는 후처리. PRD 6 §3.A 에 P0 로 명시됐던 작업 (이슈 #40).

## 이 ADR 을 읽는 이유

- ADR-0007 D2 의 1M 시점 재검증 (M6.5) 의 *결과* 와 그 *해석* 을 보고 싶다면
- 왜 M8 P0 가 M6.5b 로 격상되었는지, M7 이 왜 막혔는지 확인하고 싶다면
- 본 결정이 ADR-0007 의 *어떤 부분을 amend* 하고 *어떤 부분은 유지* 하는지 확인하고 싶다면

## 읽기 전 권장 배경

- [ADR-0007 — Combined RAG 채택](./0007-combined-rag-pivot.md) — 본 ADR 이 amend 하는 ADR. D2 에 정의된 1M 시점 재검증 분기 표
- [eval/reports/2026-06-20-financebench-1M/CONCLUSION.md](../../eval/reports/2026-06-20-financebench-1M/CONCLUSION.md) — 본 ADR 의 *측정 evidence*. 표·진단·로그가 여기 있다
- [PRD 6 §3.A](../prd/6_post_mvp_combined.md) — EntityConsolidator 의 *원래 P0 설계*

## Context — 왜 이 결정이 필요했나

### M6.5 의 직접 측정 결과

| 컬럼 | 정확도 | 토큰 중앙값 | 지연 중앙값 | 비용 (99 호출) |
|---|---|---|---|---|
| chunk_rag | 72.7% | 36.9K | 2.02s | $1.55 |
| opentology (graph 단독) | 6.1% | 4.1K | 3.56s | $1.20 |
| combined (chunk + graph) | 72.7% | 41.1K | 4.90s | $2.66 |

opentology 는 33 문항 중 31 개에 "정보 부족 (e)" 응답.

### 1 차 가설과 그 기각

처음에는 anchor extraction 의 *언어 mismatch* 가 원인이라 가설했다 — 영어 corpus 에 대해 anchor 가 한국어 entity ("당좌비율", "재무분석가") 를 만들어 그래프 매칭이 실패. 이는 사실이었고, `eval/src/opentology_eval/prompts.py:65` 의 ANCHOR_EXTRACTION_SYSTEM 프롬프트에 *질문의 언어를 보존* 하라는 원칙 + 영어 예시를 추가해 수정했다.

수정 후 anchor 는 영어로 정상 추출. **그러나 opentology 정확도는 6.1% 그대로**.

### 2 차 진단 — 진짜 원인: catastrophic EntityMatcher over-merge

직접 Neo4j 조회.

```cypher
MATCH (e:Entity) WHERE "Boeing" IN e.aliases RETURN e.name, e.aliases
```

→ "Amcor plc" 노드 1 개 반환. 이 노드의 aliases 가:
```
["Amcor", "the Company", "we", "our", "us", "Registrant",
 "AMD", "management", "American Express", "AXP", "Amex",
 "Boeing", "PepsiCo"]
```

13 개 alias 중 6 개가 *다른 회사명*. 게다가 이 노드의 description 은 American Express 의 설명 ("A globally integrated payments company, incorporated in New York, providing credit and charge cards, merchant acquisition, network services...").

즉 **AMCOR 노드는 이름만 AMCOR 이고 내용은 6 사가 섞인 부패 데이터**. 그래프의 *최상위 회사 entity 가 무효*.

원인 (ADR-0001 의 4 단계 EntityMatcher 기준).
1. 첫 ingest 된 10-K (AMCOR_2023) 에서 "the Company" / "we" / "us" / "Registrant" 같은 generic 자기지칭을 entity 로 추출
2. 다음 10-K (AMD_2022) 에서 동일 텍스트 "the Company" 가 *embedding cosine ≥ 0.92* (`apps/api/src/opentology_api/domain/identity.py` 의 `EMBEDDING_MATCH_THRESHOLD`) 를 만족 → 기존 Amcor 의 "the Company" entity 에 merge → AMD 도 alias 로 흡수
3. 매번 다음 10-K (AXP, BA, PEP, JNJ) 마다 동일 패턴 반복 → 모든 회사가 Amcor plc 에 흡수
4. 한편 회사명 자체 ("Boeing", "The Boeing Company") 는 별도 entity 로 살아남기도 함 (alias 매칭 우선순위 — 4 단계 중 2 번째 alias 매칭이 *기존 entity 가 그 alias 를 이미 가지면* 흡수). 그래서 그래프에 "The Boeing Company" 같은 깨끗한 노드 *도* 존재함

### Combined 가 chunk 와 같은 정확도인 이유

Combined runner 는 chunk top-k 청크 + subgraph 를 한 LLM 호출에 합친다. 본 회차에서:

- **subgraph 는 거의 항상 비어 있거나 부패** (over-merged Amcor plc 만 등장)
- **chunk top-k 는 정상** (벡터 RAG 는 entity merge 와 무관)
- 결과: combined 의 답변은 *chunk top-k 기반* (graph 가 도움도 방해도 거의 안 됨). chunk_rag 와 같은 정확도가 도출

## Decision

### D1. ADR-0007 D2 의 결정은 *현 시점 보류*

ADR-0007 D2 의 표 ("Combined ≥ chunk + 3pp" vs "Combined ≈ chunk" vs "chunk > Combined") 를 본 회차 직접 결과 (Combined ≈ chunk, +0pp) 에 그대로 매핑하지 *않는다*.

이유: graph 가 부패한 상태의 측정은 *graph 가 정상일 때 의 Combined 우위* 를 검증하지 못한다. 표면 결과를 그대로 채택하면 ADR-0007 의 D6 (provenance) 만 살리고 M7 을 단순화하는 분기로 빠지는데, 이는 *graph 가 실제로 가치가 없는 경우* 의 분기. 본 측정은 *graph 가 부패한 경우* 라 같은 결론을 도출할 수 없다.

### D2. EntityConsolidator (이슈 #40) 를 M6.5b 로 격상, M7 gating 에 추가

기존 milestone 트리.

```
M6.5 (gating) → M7 → M8 (EntityConsolidator 포함) → M9
```

신규 milestone 트리.

```
M6.5 (완료, 본 ADR 으로 종료) → M6.5b (EntityConsolidator) → M7 → M8 (잔여) → M9
```

M6.5b 의 종료 조건.
- post-ingest cleanup 절차 구현 (PRD 6 §3.A): ANN (Neo4j vector index) 으로 cosine 0.85-0.92 사이의 entity 쌍 후보 추출, LLM 으로 "정말 같은 entity 인지" 검증, "generic 자기지칭은 회사별로 분리 유지" 규칙 명시
- FinanceBench 1M corpus 재 ingest + EntityConsolidator 적용 후 over-merge 가 *수치적으로 감소* 했음을 evidence 로 첨부 (예: aliases 가 5 개 이상인 entity 수 감소)
- opentology + combined 만 N=3 재측정. chunk_rag 는 본 회차 결과 (`eval/runs/2026-06-20-1426/responses/chunk_rag/`) 그대로 재사용
- 본 ADR 의 표 (정확도 / 토큰 / 지연 / 비용) 갱신 + ADR-0007 D2 의 진짜 분기 결정

### D3. ADR-0007 의 정체성 (D1) 과 기술 결정 (D3-D6) 은 유지

본 ADR 은 ADR-0007 의 *결정 evidence 갱신* 에 해당하며 정체성 자체를 바꾸지 않는다.

- ADR-0007 D1 (정체성 = Combined RAG retrieval orchestrator) — 유지
- ADR-0007 D2 (Pareto 정의) — *결정 분기 시점만 지연*, 정의 자체는 유지
- ADR-0007 D3 (Graph + chunk 모두 유지) — 유지. 본 ADR 의 결정 = "graph 를 *고친 뒤* 진짜 분기 결정". graph 를 제거하지 않는다
- ADR-0007 D4 (단일 LLM 호출, 라우터 없음) — 유지
- ADR-0007 D5 (6 primitive + /answer + /retrieve) — 유지
- ADR-0007 D6 (provenance 1-class 필드) — 유지

### D4. M7 의 *코드 작업* 은 M6.5b 종료 전까지 착수하지 않음

M7 의 issue (#33-#39) 는 모두 *Combined 가 chunk 보다 우위* 라는 전제 위에 만들어졌다. M6.5b 의 결과가 그 전제를 무효화할 수도 있어 (예: EntityConsolidator 적용 후에도 graph 가 chunk 를 못 보완) M7 코드 착수는 보류.

단 *설계 문서 / 이슈 정리* 는 병행 가능 (CLAUDE.md 의 gating 정책과 동일).

### D5. dataset 보존 + 측정 산출물 보존

본 회차 (#46) 의 measurement 산출물은 머지 후에도 *보존* 한다 — M6.5b 에서 chunk_rag 결과를 재사용하기 때문.

- `eval/datasets/financebench-2026-06-20/` (dataset) — main 보존
- `eval/runs/2026-06-20-1426/responses/{chunk_rag,opentology,combined}/` (raw) — main 보존
- `eval/reports/2026-06-20-financebench-1M/` (보고서) — main 보존

## Considered Options

### O1. ADR-0007 D2 의 직접 분기 채택 ("D6 만 살리고 M7 단순화") — **거부**

직접 결과 (Combined +0pp) 를 그대로 D2 의 ±2pp 분기로 매핑할 수 있다. 이 경우 graph 를 옵션 노브로 격하하고 M7 (productization) 을 chunk-only 중심으로 단순화.

거부 이유.
- 본 회차 graph 가 *근본 실패가 아니라 부패한 상태*. 측정의 전제를 의심해야 함
- EntityConsolidator 가 *이미 ADR-0007 milestone 트리에 P0 작업으로 명시* (M8). 1M 측정으로 그 작업의 *시점만 앞당기는* 것이 자연스러운 결정
- "*만약 EntityConsolidator 를 안 만들었다면* graph 가 1M 에서 부패한다" 를 직접 evidence 로 가지게 됐다 — 이는 ADR-0007 의 graph 가치를 *기각* 하는 게 아니라 *전처리의 중요성을 강조* 하는 발견

### O2. ADR-0007 amend — chunk-only 로 피벗 — **거부**

직접 결과만 보면 graph 가 6% 라 *완전히 없애도* 정확도 손실이 없어 보인다 (Combined = chunk = 72.7%, 비용은 chunk 가 더 쌈).

거부 이유.
- 부패한 graph 의 6% 와 *정상 graph 의 6%* 는 의미가 완전히 다름. 95K 측정에서 graph 단독이 90% 였다는 사실이 *정상 상태의 graph 가치* 를 보장
- chunk-only 피벗은 *돌이키기 비용이 크다* (D3 의 chunk-only 거절 근거 참조 — synonym/alias 다중-홉 페인을 잃음)
- EntityConsolidator 만들면 graph 가 정상으로 돌아올 가능성이 충분히 큼

### O3. EntityConsolidator 를 *M7 의 일부* 로 묶기 — **거부**

M7 안에 EntityConsolidator 작업을 포함해 한 마일스톤으로 묶을 수 있다.

거부 이유.
- M7 의 다른 작업 (/answer, /retrieve, getting started, identity refresh, service mode) 은 *Combined 가 chunk 보다 우위* 라는 전제 위에 동작. EntityConsolidator 가 *그 전제를 다시 검증* 하는 단계이므로 *별도 마일스톤 (M6.5b)* 로 분리해야 gating 이 명확
- 마일스톤 단위가 "한 가지 결정을 끝내는 단위" 라는 원칙과 어긋남

## Consequences

### 즉시 영향

- M6.5 종료 + M6.5b 신설 + M7 의 gating 갱신 → STATUS.md / GitHub milestones 갱신
- ADR-0007 상단에 본 ADR 을 참조하는 amendment 박스 추가
- 측정 PR 머지 시 위 dataset / runs / reports 도 함께 보존

### 코드 작업 시 기억할 점

- **EntityMatcher 의 4 단계 + cosine ≥ 0.92 임계값은 *cross-document generic 자기지칭에 취약*** — `apps/api/src/opentology_api/domain/identity.py` 수정 시 본 ADR 을 참조 (특히 EMBEDDING_MATCH_THRESHOLD)
- **post-ingest 단계의 entity dedup 은 *별도 단계*** — ingest 자체는 빠르게, dedup 은 ingest 후 *비동기 / 별도 트리거* 로
- **dedup 알고리즘은 ANN (Neo4j vector index 의 KNN 검색) + LLM 검증** — Neo4j 5.x 의 `db.index.vector.queryNodes` 활용. LLM 호출은 후보 쌍 수에 비례 (수십-수백 쌍 예상)
- **generic 자기지칭은 *회사별로 분리* 유지 정책** — "the Company" 가 어느 10-K 에서 추출됐는지 source_path 로 회사 식별 후 별도 entity 로 분리

## Related

- [ADR-0007 — Combined RAG 채택](./0007-combined-rag-pivot.md) — 본 ADR 이 amend 하는 ADR
- [ADR-0001 — 프로젝트 정체성과 MVP 검증 가설](./0001-project-identity-and-mvp-validation-hypothesis.md) — 4 단계 EntityMatcher 의 원래 결정
- [PRD 6 §3.A](../prd/6_post_mvp_combined.md) — EntityConsolidator 의 원래 P0 설계
- [eval/reports/2026-06-20-financebench-1M/CONCLUSION.md](../../eval/reports/2026-06-20-financebench-1M/CONCLUSION.md) — 본 ADR 의 측정 evidence
