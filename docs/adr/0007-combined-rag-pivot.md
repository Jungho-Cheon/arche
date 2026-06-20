# ADR-0007: Combined RAG 채택 — Opentology 의 정체성 변경

Status: accepted (amended by ADR-0008)
Date: 2026-06-20

> **Amendment (ADR-0008, 2026-06-20)**: 본 ADR 의 D2 가 정의한 1M 시점 재검증 (M6.5) 결과 Combined ≈ chunk (+0pp). 그러나 진단 결과 graph 데이터가 catastrophic over-merge 로 부패해 측정 자체가 무효. ADR-0008 이 *EntityConsolidator 를 M7 gating 으로 격상* 하고 ADR-0007 D2 의 *결정 분기 시점을 지연* 한다. 정체성 (D1) 과 기술 결정 (D3-D6) 은 유지. 자세한 evidence 는 [`eval/reports/2026-06-20-financebench-1M/CONCLUSION.md`](../../eval/reports/2026-06-20-financebench-1M/CONCLUSION.md).

## TL;DR

ADR-0001 의 Pareto 우월 가설은 2026-06-19 본 측정에서 *미달* 이었다 (Full-context 100% / Chunk 96.7% / Opentology 96.7% — 그래프 단독이 chunk 를 어느 한 축에서도 못 이김). 후속 진단에서 chunk 와 graph 의 *오답이 겹치지 않는다는* 사실이 발견되었고, 두 retrieval 결과를 *한 LLM 호출의 컨텍스트* 에 같이 넣는 **Combined RAG** 가 2026-06-20 재측정에서 100% 정확도 + Full-context 의 1/5 비용을 달성했다.

본 ADR 은 다음을 결정한다.

1. Opentology 의 정체성을 *그래프 KB* 에서 ***Combined RAG retrieval orchestrator*** 로 변경한다.
2. ADR-0001 의 Pareto 정의를 갱신한다 — Full-context 는 *비교 기준* 이 아닌 *상한* 이고, Pareto 비교의 *실 경쟁군* 은 chunk RAG 와 Combined 다.
3. Combined RAG 는 *graph 와 chunk 를 모두 유지* 한다. 둘 중 하나를 제거하지 않는다.

후속 PRD 6 (`docs/prd/6_post_mvp_combined.md`) 가 본 ADR 의 결정을 마일스톤 M7-M9 로 분해한다.

## 이 ADR 을 읽는 이유

- ADR-0001 의 가설 미달 → ADR-0007 의 정체성 변경으로 이어진 *결정의 사슬* 을 따라가고 싶다면
- Combined RAG 의 *어떤 측정 증거* 에 근거해 chunk-only / graph-only 가 *명시적으로 거절* 되었는지 알고 싶다면
- post-MVP 마일스톤 (M7-M9) 의 의사결정 기반을 확인하고 싶다면

## 읽기 전 권장 배경

- ADR-0001 — 본 ADR 이 갱신하는 원본 가설
- ADR-0005 — 측정 방법론 (본 ADR 의 측정이 의존)
- `eval/reports/2026-06-19-mvp-closure/CONCLUSION.md` — Pareto 미달 본 측정 결과
- `eval/reports/2026-06-20-combined-pivot/CONCLUSION.md` — Combined 100% 후속 측정

## Context — 왜 이 결정이 필요했나

### 본 측정 (2026-06-19, run 2126) 의 결론

| 컬럼 | 정확도 | 토큰 중앙값 | 지연 중앙값 | 비용 (90 호출) |
|---|---|---|---|---|
| Full-context (gpt-4.1) | 100.0% | 70K | 8.1s | $12.69 |
| Chunk RAG | 96.7% | 4.7K | 2.8s | $1.62 |
| Opentology (graph 단독) | 96.7% | 8.3K | 5.8s | $1.76 |

ADR-0001 의 Pareto 가설 — *Opentology 가 정확도/토큰/지연 모두에서 chunk 보다 우위* — 는 미달. Opentology 는 토큰/지연 어느 한 축에서도 chunk 를 못 이김.

### 진단에서 발견된 보완재 패턴

오답 집합을 비교하면:

- Chunk 오답: **Q02** (`synonym_alias`, 3-hop)
- Graph 오답: **Q25** (`cross_source`, 2-hop)
- 양쪽 다 틀린 질문: **0 / 30**
- Oracle hybrid 정답률 = **30 / 30 = 100%**

즉 두 retrieval 이 *서로 다른 종류의 질문* 에서 실패한다. Chunk 는 동의어/별칭 다중-홉에 약하고, graph 는 cross-source 단답에 약하다. 자세한 진단은 본 ADR 의 자매 보고서 `eval/reports/2026-06-19-mvp-closure/CONCLUSION.md` 와 사용자와의 후속 토론 기록 참조.

### Combined RAG 의 검증 (2026-06-20, run 0923)

Combined RAG = chunk RAG 의 top-k 청크와 Opentology 의 anchor → subgraph 를 *한 LLM 호출의 컨텍스트* 에 같이 넣고 답변시킴. 라우터 없음.

같은 데이터셋 / 같은 dataset hash 로 재측정 (corpus 재 ingest 포함):

| 컬럼 | 정확도 | 오답 | 토큰 중앙값 | 지연 중앙값 | 비용 (90 호출) |
|---|---|---|---|---|---|
| chunk_rag | 96.7% | Q02 | 8.5K | 2.85s | $0.97 |
| opentology | 90.0% | Q05, Q20, Q25 | 7.9K | 4.82s | $1.69 |
| **combined** | **100.0%** | **없음** | 15.7K | 5.11s | **$2.54** |

Combined 가 chunk 와 graph *각자의 오답을 모두 회복*. LLM 이 두 retrieval 결과를 컨텍스트 안에서 비교해 신뢰성 높은 쪽 자동 선택. Full-context 와 동률 정확도 + 1/5 비용.

### 본 결정이 필요한 이유

ADR-0001 의 가설이 미달했으므로, Opentology 의 정체성을 다음 중 하나로 *명시적으로* 정해야 한다.

1. Chunk RAG 만 채택 → graph 폐기 → 그러나 Q02 류 (페르소나의 핵심 페인) 해소 못함
2. Graph RAG 만 채택 → chunk 폐기 → 그러나 graph 단독 90% (ingest 마다 흔들림)
3. **Combined RAG 채택** → 100% + 비용 합리적
4. 사업 종료

본 ADR 은 (3) 을 선택한다.

## Decision — 무엇을 결정했나

### D1. Opentology 의 정체성 변경

**기존**: "Opentology = LLM·AI 에이전트가 도메인의 *관계 정보* 를 *최소한의 토큰과 시간으로* 활용하도록 돕는 *그래프 기반* 지식 베이스 도구" (ADR-0001 D1)

**변경**: "Opentology = chunk RAG 와 graph RAG 의 신호를 *단일 LLM 호출의 컨텍스트* 로 결합해 LLM·에이전트에게 제공하는 ***retrieval orchestrator***"

핵심 변화:
- "그래프 기반" → "chunk + graph 결합 기반"
- 그래프 단독 가치 명제 → 그래프가 chunk 의 약점을 *정정* 하는 *보완재* 로서의 가치 명제
- 외부 시스템은 Opentology API 하나만 호출 — 내부적으로 두 retrieval 을 결합

### D2. Pareto 비교 기준 갱신 (ADR-0001 D2 갱신)

**기존** (ADR-0001 D2): "Pareto 가설 = Opentology 가 Full-context 와 정확도 동률 + chunk RAG 보다 토큰/지연 우위"

**변경**: "Pareto 가설 = Combined 가 chunk RAG 와 정확도 *우위* + Full-context 의 *비용 대비 합리적* 비율 (Full-context 의 1/3 이하)"

이유:
- Full-context 는 *상한* 이지 *경쟁 대상* 이 아니다. 95K 코퍼스에서 $12.7/90 호출, 1M 코퍼스에서는 비용이 운영 옵션에서 빠진다.
- 실 경쟁군은 chunk RAG. Combined 의 가치는 *chunk 단독 대비 정확도 우위* 와 *Full-context 대비 비용 우위* 두 축으로 동시에 정의되어야 한다.

### D3. Graph 와 chunk 모두 유지 (chunk-only / graph-only 명시 거절)

**Chunk-only 거절** — 본 측정 Q02 (synonym_alias 3-hop) 가 사용자 페르소나의 핵심 페인 사례. 1/30 이 작아 보여도 페인의 본질이 거기에 있다 (메모리 `user_dogfooding_context` 참조). Graph 의 추가 비용 +$1.57/90 (호출당 +$0.017) 은 그 페인 해소 가치보다 작다.

**Graph-only 거절** — 본 측정 graph 단독 90%. EntityMatcher 의 alias 통합이 ingest 마다 흔들리는 신호 (2126 vs 0923 회차에서 graph 정확도가 96.7% → 90% 로 변동). Chunk 가 안정성 완충 역할.

### D4. 단일 LLM 호출 결합 (라우터 휴리스틱 명시 거절)

Combined 의 구현은 ***chunk top-k 청크 + opentology subgraph 를 *한 LLM 호출* 의 컨텍스트로 합치는 것*** 이다. 라우터로 *어느 도구를 쓸지* 선택하는 휴리스틱은 채택하지 *않는다*.

이유 (사용자와의 토론 기록):
- 라우터 자체가 또 다른 휴리스틱 — 임계값/규칙 튜닝 부담
- 두 retrieval 다 호출하는 비용이 단일 retrieval 의 1.5-2 배 수준에 그침 ($0.020 → $0.028)
- LLM 이 *내부적으로* 두 신호를 비교 → 라우터보다 일반화 잘 됨
- 본 측정에서 zero-overlap 오답 패턴이 *결합* 으로 자동 회복됨을 직접 확인

### D5. 기존 6 primitive API 유지 + 고수준 엔드포인트 추가

ADR-0006 의 6 primitive (`get_schema` / `find_entities` / `get_entity` / `get_neighbors` / `find_path` / `get_subgraph`) 는 *그대로 유지*. 자체 LLM 을 운영하는 사용자나 *그래프 직접 탐색* 이 필요한 에이전트를 위한 저수준 API.

새로 추가:
- `POST /answer` — Combined 답변 (1 LLM 호출, 응답에 choice/reasoning/provenance)
- `POST /retrieve` — 컨텍스트만 반환 (외부 LLM 이 답변 생성)
- `POST /retrieve/chunks` / `POST /retrieve/subgraph` — 단독 retrieval

`/answer` 가 *기본 채널*. 6 primitive 는 그대로지만 *기본 사용 경로가 아님*.

### D6. Provenance — Combined 응답의 1-class 필드

`/answer` 응답에 *어떤 신호가 답에 결정적이었는지* 를 구조화된 필드로 노출:

```json
{
  "choice": "b",
  "reasoning": "...",
  "provenance": {
    "decisive_source": "graph",
    "chunks_used": [...],
    "graph_used": {"entries": [...], "edges": [...]}
  }
}
```

이유:
- 자기 도메인에서 graph 가 결정적인지 chunk 가 결정적인지를 사용자가 *측정* 할 수 있어야 한다. graph 가 거의 안 쓰이면 graph 운영비를 줄일 결정 근거.
- 답변 신뢰성 검증 — 어느 출처를 근거로 답했는지 추적 가능.

## Consequences — 이 결정의 결과

### 긍정적

- Opentology 의 가치 명제가 *측정으로 검증된* 100% 정확도 + Full-context 의 1/5 비용으로 명료해짐
- 두 retrieval 의 *zero-overlap 오답 패턴* 은 *구조적* 현상 (chunk 는 lexical, graph 는 relational — 다른 신호 채널). 단일 측정 회차가 작더라도 가설 강도가 큼
- Graph 와 chunk 모두 유지 → 기존 작업 (M1-M6) 의 *전부 폐기* 가 아니라 *결합* 으로 살아남
- 사용자 페르소나의 핵심 페인 (synonym_alias 다중-홉) 이 명확히 해소

### 부정적 / 위험

- Combined 비용이 chunk 단독의 2.6 배 ($0.028 vs $0.011 per query). 비용 제약 강한 사용자에게 ROI 작을 가능성
- 본 측정은 단일 도메인 (한국어 커머스 정책) 단일 코퍼스 (95K) 단일 회차 (N=3). *영문 / 다도메인 / 큰 corpus 일반화 미검증* — Phase 3 (M9) 에서 해결
- 본 ADR 의 결정이 *유일한 해석* 은 아님. Microsoft GraphRAG / LangChain Hybrid 등 동급 도구 대비 *근본적 차별* 은 §2 분석에서 *opinionated 기본값 + eval 하니스 동봉 + idempotent ingest* 의 조합으로 정의했지만, 시장 검증 미완

### 위험 완화

- Phase 2 (M8) 의 최적화 — subgraph reranking / retrieval anchor / token budget allocator — 가 비용을 chunk 단독의 1.6 배 수준으로 떨어뜨리는 것이 목표
- Phase 3 (M9) 의 1M corpus + 외부 도구 측정 — 본 ADR 의 결정을 *외부 검증* 으로 굳히는 단계

## Alternatives considered — 거절된 대안

PRD 6 §5 의 "거절된 선택지" 표 참조. 요약:

- Chunk-only — 페인 해소 못함
- Graph-only — 안정성 부족
- 라우터 기반 hybrid — 추가 휴리스틱 부담, 비용 차이 작음
- Microsoft GraphRAG community summary — multi-pass ingest 비용 큼, Phase 3 재검토
- Full-context — 비용 5 배, 1M 시점 운영 옵션 아님
- 1M FinanceBench 즉시 검증 ($190) — 알고리즘 (combined) 우선, Phase 3 자체 corpus 대체

## References

- `docs/prd/6_post_mvp_combined.md` — 본 ADR 의 결정을 마일스톤 M7-M9 로 분해
- `eval/reports/2026-06-19-mvp-closure/CONCLUSION.md` — Pareto 미달 본 측정
- `eval/reports/2026-06-20-combined-pivot/CONCLUSION.md` — Combined 100% 후속 측정
- ADR-0001 — 본 ADR 이 갱신하는 원 가설
- ADR-0005 — 측정 방법론
- ADR-0006 — 6 primitive (유지)
- 메모리 `user_dogfooding_context` — 사용자 페르소나의 페인 사례
