# ADR-0009: Context-aware extraction — *추출 단계* 에 문서 메타 + 기존 graph KB 동봉

Status: proposed (RFC)
Date: 2026-06-21
Amends: [ADR-0001](./0001-project-identity-and-mvp-validation-hypothesis.md) §5 (entity 추출), [ADR-0003](./0003-graph-entry-point-strategy-hybrid-lexical-dense.md), [ADR-0008](./0008-entity-consolidator-gating.md) (deprecation 경로 포함)

## TL;DR

현재 ingest 의 entity 추출은 *청크 단위 독립 LLM 호출* 이라 *문서 컨텍스트* 와 *이미 그래프에 있는 entity* 를 모르고 추출한다. 그 결과:

- "the Company" 가 *어느 회사의 자기지칭인지* 풀이 못 함 → ADR-0008 의 catastrophic over-merge 의 *root cause*.
- 동명이인 ("John" 두 사람) 을 disambiguate 못 함 → 단순 cross-doc 시나리오 (여러 회사 다니는 개인 KB) 에서 부패.
- 같은 entity 가 이미 그래프에 있어도 *추출 후 후처리 매칭 (Step 1-3 + Consolidator)* 으로 비싸게 통합.

본 ADR 은 **추출 단계의 LLM 호출 시점에 *4 종 컨텍스트 (문서 메타 + 주 entity + 기존 graph KNOWN_ENTITIES + schema summary)* 를 동봉**해 위 한계를 *예방* 으로 전환한다. 후처리 가드 (STOPLIST + EntityConsolidator) 의 역할은 *자연 deprecation* 경로로 들어간다.

> 용어 인라인 풀이.
>
> - **추출 단계 (extraction step)**: ingest 흐름에서 *청크 본문 → ExtractedGraph (entity + relation 목록)* 를 만드는 단일 LLM 호출. 현재 `apps/api/src/opentology_api/adapters/llm.py:OpenAILLMProvider.extract`.
> - **컨텍스트 동봉 (context priming)**: 호출의 system / user 메시지에 *청크 본문 외의 보조 정보* 를 prepend 해 LLM 의 판단을 돕는 일반적 패턴.
> - **KNOWN_ENTITIES**: 이미 그래프에 적재된 entity 중 *본 청크와 관련 가능성이 있는 후보 N 개* 의 (id, name, aliases, type, 1-line description) 목록.

## 이 ADR 을 읽는 이유

- ADR-0008 의 EntityConsolidator 가 *증상 가림* 임을 인정하고 *root cause* 를 다루는 방향 으로 가는 이유와 형태를 알고 싶다면.
- 추출 단계의 LLM 호출이 *어떤 정보를 받아야* 정확해지는지, 비용 trade-off 가 어떻게 되는지.
- 본 ADR 채택 후 STOPLIST + EntityConsolidator 가 어떤 deprecation 경로로 들어가는지.
- ADR-0001 / ADR-0003 / ADR-0008 중 *어떤 결정을 amend* 하고 *어떤 결정은 유지* 하는지.

## 읽기 전 권장 배경

- [ADR-0001 §5 (entity 추출)](./0001-project-identity-and-mvp-validation-hypothesis.md) — 4 단계 EntityMatcher 가 측정 통제 변수.
- [ADR-0008](./0008-entity-consolidator-gating.md) — catastrophic over-merge 의 직접 evidence + EntityConsolidator 가 *후처리* 로 다루는 한계.
- PR #54 의 CONCLUSION (`eval/reports/2026-06-21-m65b-consolidator/CONCLUSION.md`) — STOPLIST + Consolidator 가 cleanup 한 1M 결과 baseline.
- graphify SKILL.md — 비교 대상의 *parallel agent dispatch + 청크 캐시 + AST 우선* 패턴.

## Context — 왜 이 결정이 필요했나

### 현 흐름의 정확한 상태

`apps/api/src/opentology_api/domain/ingest.py:ingest_file` 의 추출 호출 흐름:

```
파일 읽기
  → chunk_text(text) (heading→paragraph→sentence + overlap)
  → 각 청크에 대해 _llm.extract(text=chunk.text)
    └ system: ENTITY_EXTRACTION_SYSTEM (static, 문서 / graph 무관)
    └ user: chunk.text  ← 청크 본문 외 *아무것도 없음*
  → ExtractedGraph 통합
  → 4 단계 EntityMatcher (정규화/별칭/cosine 0.92)
  → IngestionRun 차분 적용
```

이 흐름의 *치명적 누락*:

1. **문서 메타 없음** — 같은 파일의 첫 페이지에서 "Amcor plc" 라 공식 회사명이 등장해도, *다음 청크* 의 "the Company" 호출은 그 사실을 모름.
2. **그래프 state 없음** — 같은 entity 가 이미 그래프에 있어도 LLM 은 *새로 추출* 만 함. 매칭은 추출 *후* Step 1-3 후처리.
3. **schema 일관성 없음** — 알려진 entity type (company / policy / product 등) 을 LLM 에 전달 안 해 매 호출마다 다른 type 명이 나올 수 있음.

### 이게 만든 직접 비용

| 비용 | ADR-0008 evidence | 추정 원인 |
|---|---|---|
| catastrophic over-merge | Amcor plc 한 노드에 6 회사 흡수 | (1) 누락 → "the Company" 가 generic 으로 추출 → Step 3 cosine 매칭에서 cross-doc 합쳐짐 |
| STOPLIST 도입 비용 | PR #51 | (1) 의 *증상 가림* |
| EntityConsolidator 비용 | PR #54, $0.5/회차 | (1) 의 *증상* 의 추가 가드 |
| 동명이인 부패 가능성 | (검증 안 됨, 사용자 사례) | (1)(2) 누락 |
| 매칭 후처리 비용 | 모든 ingest 호출 | (2) 누락 |

ADR-0008 본문 "직접 원인" 절이 가리키는 4 단계 EntityMatcher 의 cosine 0.92 매칭이 *증상 발현 지점* 이지만, 그 직접 원인은 *추출 단계에 컨텍스트가 없어 generic reference 가 그대로 entity 로 들어옴* 이다.

### graphify 와의 비교 — 우리가 만든 손실

graphify 의 동등 단계:

- 같은 디렉토리 청크 묶음을 한 message 안에 *parallel agent* 로 dispatch.
- 한 agent 가 *여러 청크* 를 같은 컨텍스트로 추출 → frontmatter / 인접 파일 인식.
- 결과 캐시 (`graphify-out/cache/`) — 청크 해시 기반 재사용.

→ graphify 도 *완벽한 context-aware* 는 아니지만, 같은 묶음 단위 컨텍스트가 *우리보다 풍부*. 우리는 청크 1 개씩 독립 호출.

## Decision

### D1. 추출 단계 LLM 호출에 *4 종 컨텍스트* 를 동봉

`LLMProvider.extract` 의 system / user 메시지를 다음과 같이 확장한다.

```
system:
  [기존 ENTITY_EXTRACTION_SYSTEM]
  +
  [INSTRUCTION] 다음 청크에서 entity / relation 을 추출하라. 호출에 동봉된
  [DOC_CONTEXT], [KNOWN_ENTITIES], [SCHEMA] 를 *반드시 참조* 한다.

  [매칭 정책]
  - 청크 내 표현이 [KNOWN_ENTITIES] 의 한 entity 와 *같은 대상* 을 가리킨다고
    판단되면, 새 entity 를 만들지 말고 그 id 를 `matched_existing_id` 필드에 명시.
  - 1인칭 자기지칭 ("the Company", "we", "we", "당사") 은 [DOC_CONTEXT] 의 *문서
    주 entity* 이름으로 *resolve 해서* 추출 — 절대 generic 한 이름 으로 entity 화하지 않는다.
  - 알려진 type 명 ([SCHEMA] 참조) 을 우선 사용. 새 type 은 정말 필요할 때만.

user:
  [DOC_CONTEXT]
  file_path: AMCOR_2023_10K.md
  main_entity: { id: "01J...", name: "Amcor plc", type: "company",
                 aliases: ["Amcor", "the Company", "we", "us", "our"] }
  preceding_chunks_summary: "...앞 청크 5 줄 요약..."

  [KNOWN_ENTITIES]  ← 청크 본문에 등장 가능성이 있는 후보만
  - { id: "01J...", name: "Amcor plc", aliases: ["Amcor","we","the Company"],
      type: "company", desc: "Australian packaging company..." }
  - { id: "01J...", name: "Quick ratio", aliases: ["당좌비율"],
      type: "metric", desc: "Liquidity ratio..." }
  - ...

  [SCHEMA]
  entity_types: company (47), metric (23), policy (15), product (8), person (4)
  relation_types: REPORTS, EXCEPTION_FOR, COMPETES_WITH, ...

  [CHUNK]
  <청크 본문 그대로>
```

### D2. `ExtractedEntity` 에 `matched_existing_id` 필드 추가

LLM 응답 JSON 의 entity schema 에 다음 필드를 추가:

```json
{
  "name": "the Company",
  "type": "company",
  "aliases": ["the Company"],
  "matched_existing_id": "01J7K...AMCORID",   // 추출 단계에서 LLM 이 결정
  "description": "...",
  "properties": {...}
}
```

`matched_existing_id` 가 *명시* 되어 있으면 ingest 흐름은:

- 4 단계 EntityMatcher (Step 1-3) 를 **skip**.
- 곧바로 `apply_merge_mutation` 으로 기존 entity 와 병합 (EntityMerger.merge).
- 매칭이 *추출 단계의 LLM 결정* 으로 이동.

`matched_existing_id` 가 *없으면* 기존 4 단계 매처가 그대로 작동 (점진 도입).

### D3. *문서 주 entity* 식별을 위한 2nd pass

문서당 1 회 별도 LLM 호출로 *문서 전체의 주 entity* 를 식별한다.

```
1st pass (문서 1 회):
  input: 파일 첫 N 줄 (보통 제목 + 1-2 단락)
  output: { main_entity: { canonical_name, type, aliases } }
  cost: 1 호출 / 문서 (보통 ~500 토큰 input)

2nd pass (청크별, 위 D1 의 호출):
  user 의 [DOC_CONTEXT].main_entity 에 1st pass 결과 동봉
```

대안 (3rd 옵션): 2nd pass 의 첫 청크 자체에서 `main_entity` 도 추출. 1 호출 절약. 본 ADR 은 *명시적 2nd pass* 가 더 robust 라 판단 (첫 청크가 짧을 수 있음).

### D4. KNOWN_ENTITIES 후보 선정 — 청크별 hybrid 검색

전체 entity 를 동봉하면 토큰 폭발. 본 ADR 은 *각 청크당 N (default 10) 후보* 만 동봉한다.

선정 알고리즘:
1. 청크 본문에서 명사구 추출 (LLM 호출 0 — regex / spacy / 단순 noun chunking).
2. 각 명사구로 hybrid 검색 (`find_by_keywords_scored` + `find_entities_dense`, 본 코드 이미 있음).
3. RRF 융합 후 top-N (default 10) 후보.
4. 같은 source_path 의 이전 chunk 가 *방금 추출한 entity* 도 후보에 prepend (문서 내 일관성).

### D5. STOPLIST + EntityConsolidator 의 deprecation 경로

본 ADR 채택 후의 단계적 deprecation:

| 단계 | 시점 | STOPLIST | Consolidator |
|---|---|---|---|
| Phase 1 (본 ADR 도입) | M7-D-1 | 유지 (보조 가드) | 유지 (보조 가드, dry_run 만) |
| Phase 2 (vs graphify 벤치 통과 시) | M7-D-3 | deprecated 표시 | deprecated 표시 |
| Phase 3 (1M 회차 재측정 → 가드 없이도 견고함 확인 시) | M7-D-5 | 코드 삭제 | 코드 삭제 |

본 ADR 은 *증상 가림 가드를 즉시 제거하지 않는다* — root-cause 해법이 *충분히 견고함을 측정으로 확인하기 전* 까지는 보조 가드 유지.

### D6. measurement 통제 변수 변경 *명시*

본 ADR 은 ADR-0001 §5 의 *측정 통제 변수* (추출 프롬프트 + 4 단계 매처) 를 변경한다. 변경 영향:

- 모든 측정 회차의 그래프가 달라짐. 기존 회차 결과 (eval/runs/) 는 *baseline* 으로 보존하되 *직접 비교* 가 아닌 *시점 evidence* 로 해석.
- ADR-0005 (측정 방법론) 의 *측정 통제 변수 변경 시 새 회차 시작* 규칙에 따라 본 ADR 채택 직후 *새 측정 회차* 시작.
- 새 회차의 metadata 에 ADR-0009 적용 명시.

## Open Questions (사용자 합의 필요)

본 ADR 은 *RFC* 단계 — 다음 결정은 사용자 합의 후 본 ADR 에 inline 채워진다.

1. **2nd pass 의 형태** — D3 의 명시적 2nd pass vs 첫 청크에서 동시 추출. *robustness vs 비용* trade-off.
2. **KNOWN_ENTITIES 후보 수 N** — default 10 이 우리 corpus 에 적정한가. 너무 적으면 매칭 누락, 너무 많으면 토큰 폭발.
3. **`matched_existing_id` 의 LLM 결정에 대한 신뢰도** — LLM 이 잘못 매칭해 *오히려 새로운 부패* 를 만들 가능성. confidence 필드 추가 + threshold 가드 필요한가.
4. **점진 도입 vs 한 번에 교체** — 본 ADR 은 점진 도입 (matched_existing_id 부재 시 기존 매처 동작) 을 제안. 한 번에 교체하면 작업이 단순하지만 *측정 회차 비용* 추가.

## Considered Options

### O1. 본 ADR 거부 — STOPLIST + Consolidator 유지 — *거부*

PR #54 의 baseline 으로 충분히 견고. 추가 변경 없이 운영.

거부 이유:
- ADR-0008 의 결과가 *graphify 와의 비교* 에서 우리 시스템의 *그래프 생성 자체* 가 열위임을 인정해야 한다 (본 사용자 합의). 증상 가림 가드만으로는 *graphify 우월* 라는 MVP 성공 조건 (사용자 goal) 미달.
- 동명이인, 학술 논문, 다회사 KB 같은 시나리오에서 *현 가드로는 못 푸는 케이스* 존재. 본질적 해법 필요.

### O2. graphify 채택 — *거부*

graphify 를 그대로 사용하고 그 위에 답변 오케스트레이션만 얹기.

거부 이유:
- graphify 는 *생성 도구* 이지 *서버형 LLM-facing API* 가 아님. 사내 인프라 / 공유 KB 운영에 맞지 않음.
- ADR-0007 D1 의 정체성 (Combined RAG retrieval orchestrator) 은 graphify 와 다른 축.
- 다만 graphify 의 *추출 패턴 (parallel + cache + AST 우선)* 은 채택 — 본 ADR + ADR-0010.

### O3. 단일 LLM 호출로 전체 문서 추출 — *거부*

청크 분할 없이 *문서 전체* 를 한 호출에 넣고 추출.

거부 이유:
- 1M 토큰 문서 (10-K) 는 LLM 컨텍스트 한도 초과.
- 청크 분할의 본질적 이유 (LLM 컨텍스트 한도 + 비용) 가 그대로 유지됨.
- 청크 단위 + 컨텍스트 동봉 (본 ADR) 이 trade-off 최적.

## Consequences

### 즉시 영향

- ADR-0001 §5 의 4 단계 EntityMatcher 가 *옵션 경로* 가 됨 — `matched_existing_id` 있으면 skip.
- ADR-0003 의 hybrid 검색이 *KNOWN_ENTITIES 후보 선정* 에도 재사용 (이미 있는 인프라).
- ADR-0008 의 EntityConsolidator 가 *deprecation 경로* 로 진입.
- 측정 회차가 새로 시작 — 기존 회차 (2026-06-19 ~ 2026-06-21) 는 *baseline* 으로 보존.

### 코드 작업 시 기억할 점

- **추출 프롬프트는 *측정 통제 변수* (ADR-0001)** — 본 ADR 의 D1 system message 가 *새 통제 변수*. 변경 시 ADR amend + 새 회차.
- **KNOWN_ENTITIES 후보 선정의 *비결정성* 가드** — hybrid 검색은 결정론적이지만 RRF 와 N 의 cutoff 가 통제 변수.
- **`matched_existing_id` 잘못된 결정의 영향** — LLM 이 잘못 매칭하면 *새 부패* 가 발생. 측정에서 false-positive 율을 직접 추적해야 함.
- **점진 도입** — `matched_existing_id` 부재 시 기존 매처 그대로 작동. 사용자가 안전하게 roll-back 가능.

### 종료 조건 (vs graphify 벤치마크)

본 ADR 의 *성공 측정* :

| 측정 | 목표 |
|---|---|
| 동일 corpus (FinanceBench 1M) ingest 시 over-merge entity 수 | 0 (현 4 + STOPLIST/Consolidator 가드 없이) |
| ingest 시간 | 현 30 분 대비 50% 이하 (ADR-0010 multi-agent + 캐싱 후) |
| ingest 비용 | 현 회차 대비 ±10% 이내 (KNOWN_ENTITIES 토큰 추가 vs STOPLIST/Consolidator 호출 제거의 상쇄) |
| opentology + combined 정확도 (1M FinanceBench) | combined ≥ PR #54 의 78.8% (회귀 0) |
| **vs graphify 벤치마크** | 같은 corpus → graphify 와 *동등 또는 우월* 한 cross-doc INFERRED edge 수 + 우월한 매칭 정확도 |

마지막 행이 본 goal 의 MVP 성공 조건 (1) "graphify 보다 우월한 그래프 생성" 의 직접 충족 evidence.

## Related

- [ADR-0001](./0001-project-identity-and-mvp-validation-hypothesis.md) — §5 가 amend 됨.
- [ADR-0003](./0003-graph-entry-point-strategy-hybrid-lexical-dense.md) — KNOWN_ENTITIES 후보 선정에 hybrid 검색 재사용.
- [ADR-0008](./0008-entity-consolidator-gating.md) — Consolidator 의 deprecation 경로.
- [ADR-0010 (예정)](./0010-multi-agent-parallel-and-cache.md) — graphify Part B 패턴 + 청크 캐시.
- [ADR-0011 (예정)](./0011-step3-cosine-opt-in.md) — Step 3 cosine 매칭의 옵션화 + STOPLIST/Consolidator 코드 deprecation.
