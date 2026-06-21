# ADR-0011: Step 3 cosine 매칭의 옵션화 + STOPLIST/Consolidator deprecation 경로

Status: proposed (RFC)
Date: 2026-06-21
Amends: [ADR-0001](./0001-project-identity-and-mvp-validation-hypothesis.md) §5, [ADR-0008](./0008-entity-consolidator-gating.md)
Requires: [ADR-0009](./0009-context-aware-extraction.md) (선행 — `matched_existing_id` 도입)

## TL;DR

ADR-0009 가 *추출 단계의 LLM* 이 *기존 graph entity 와의 매칭* 을 결정하게 만든다 (`matched_existing_id`). 이게 robust 하게 작동하면 *Step 1-3 후처리 매칭* 은 *fallback / 검증 경로* 로 의미가 축소되고, 그 위에 쌓인 STOPLIST (PR #51) + EntityConsolidator (PR #54) 도 *historical baseline* 으로 deprecate 가능.

본 ADR 은:

1. **Step 3 (cosine 매칭) 을 default off** — 명시 opt-in (`enable_cosine_matching=true`) 으로만 작동.
2. **Step 1-2 (정확/별칭 매칭) 은 유지** — 결정적이고 부패 위험 없음.
3. **STOPLIST + Consolidator** — Phase 1 에서는 *유지 (보조 가드)*, Phase 2 (벤치 통과) 시 deprecated 표시, Phase 3 (재측정 견고함 확인) 시 코드 삭제.

## 이 ADR 을 읽는 이유

- ADR-0008 의 EntityConsolidator 가 *왜 Phase 1 에서 유지되고 Phase 3 에서 삭제* 되는지의 단계적 경로.
- Step 3 cosine 매칭이 *어떤 조건에서만 살아남는지* — 예: 측정 회차의 비교 baseline 으로만 opt-in.
- 측정 통제 변수의 *큰 변경* 명시 — ADR-0009 + ADR-0010 + ADR-0011 이 *함께* 새 회차의 baseline 을 정의.

## 읽기 전 권장 배경

- [ADR-0009](./0009-context-aware-extraction.md) — `matched_existing_id` 필드와 *예방으로의 전환* 정의.
- [ADR-0008](./0008-entity-consolidator-gating.md) — catastrophic over-merge 의 직접 원인 + 본 ADR 의 deprecation 대상.

## Context — 왜 이 결정이 필요했나

### Step 3 cosine 매칭의 본질적 위험

`apps/api/src/opentology_api/domain/identity.py:EntityMatcher.match` 의 Step 3:

```
Step 3 — 임베딩 유사도 (cosine ≥ 0.92)
  embedder.embed([e_new.name])[0] → vector ANN top_k=5 → cosine ≥ 0.92 합침
```

이 매칭의 *입력은 entity name 하나*. 컨텍스트 없음.

문제:
- "the Company" 두 노드는 *항상 cosine ~ 1.0* — 같은 단어이므로. catastrophic over-merge 의 직접 발현 경로.
- "John" 두 노드도 마찬가지.
- 일반적으로 *고유성이 약한 단어* (1인칭, 대명사, 추상 명사) 가 *모두 같은 패턴*.

### STOPLIST 의 한계

PR #51 의 NON_IDENTIFYING_ALIAS_STOPLIST 가 *영어/한국어 자기지칭* 만 차단. 학술 ("this paper", "the present study"), 일기 ("I"), 코드 ("self", "this") 등은 추가 항목 필요. *도메인별 사전 유지보수* 비용.

### Consolidator 의 한계

PR #54 의 EntityConsolidator 가 0.85-0.92 회색지대를 LLM 검증으로 처리하지만:
- *후처리* 라 ingest 후 별도 작업 단계.
- LLM 호출 비용 ($0.5/회).
- LLM 의 *false-positive 판정* 위험.

### ADR-0009 가 만드는 변화

ADR-0009 의 `matched_existing_id` 가 *추출 단계에서* 매칭을 결정하면:
- "the Company" 가 추출 단계에서 *문서 주 entity 의 id 로 resolve* → cross-doc 부패 0.
- "John" 도 KNOWN_ENTITIES 안의 컨텍스트 (description + 이웃) 로 disambiguate.
- Step 3 cosine 매칭이 *해결하려던 문제* 가 *예방* 됨.

→ Step 3 가 *기존 문제는 해결 못 하면서 위험만 만드는 단계* 가 된다. opt-in 으로 격하.

## Decision

### D1. Step 3 cosine 매칭을 *opt-in*

```python
@dataclass
class IngestConfig:
    enable_cosine_matching: bool = False  # default off (ADR-0011)
    cosine_threshold: float = 0.92        # opt-in 시 사용
```

기본 흐름:
- Step 1 (정규화 정확 일치) — 유지
- Step 2 (별칭 정확 일치) — 유지
- Step 3 (cosine) — **skip (config 로 켜야 작동)**
- Step 4 (신규 생성)

이는 *추출 단계의 `matched_existing_id` 가 주 매칭 경로* 라는 전제 위에 작동. matched_existing_id 가 없으면 Step 1-2 fallback. Step 3 는 *특수 측정 회차의 비교 baseline* 으로만 opt-in.

### D2. STOPLIST 의 단계별 deprecation

Phase 1 (ADR-0009 + ADR-0010 + 본 ADR D1 적용):
- STOPLIST 유지. 보조 가드 — *혹시* matched_existing_id 가 누락된 generic reference 가 추출되어도 Step 2 에서 막힘.
- ADR-0011 의 새 회차 baseline 이 *STOPLIST + 새 흐름* 결합.

Phase 2 (vs graphify 벤치 통과 + 다도메인 측정 통과):
- STOPLIST 코드에 `# DEPRECATED — see ADR-0011 D2 Phase 2` 표시.
- 새 회차의 metadata 에 stoplist_active=false 옵션 추가.
- 가드 없이 측정.

Phase 3 (재측정 견고함 확인 — 가드 없이 over-merge 0):
- STOPLIST 코드 *삭제*.
- ADR-0008, PR #51 을 *historical context* 로 ADR-README 에 표시.

### D3. EntityConsolidator 의 단계별 deprecation

Phase 1: 유지 (dry_run 만). 새 흐름의 결과를 검증하는 *후처리 audit*.
Phase 2: 코드에 `# DEPRECATED — see ADR-0011 D3 Phase 2` 표시. 측정 회차에서 비활성.
Phase 3: 코드 *삭제*. PR #54 를 historical 로 표시.

### D4. 측정 통제 변수 — 새 baseline 정의

ADR-0009 + ADR-0010 + 본 ADR 채택 후 새 측정 baseline:

```yaml
extraction:
  prompt_version: "v2-context-aware"
  context_priming: { doc_metadata: true, main_entity: true,
                     known_entities_top_k: 10, schema_summary: true }
  matched_existing_id_field: true
matching:
  step1_exact_normalized: true
  step2_exact_alias: true
  step3_cosine: false       # opt-in
  cosine_threshold: 0.92    # if opt-in
guards:
  non_identifying_stoplist: true   # Phase 1 만
  consolidator: false              # dry_run audit 만
```

새 회차의 meta.yaml 에 위 객체 그대로 기록.

## Open Questions

1. **Step 3 cosine 의 *완전 삭제* 시점** — Phase 3 의 견고함 확인 측정에서 어떤 numerical threshold 가 "삭제 가능" 판정인가. *over-merge 0 + multi-hop 정확도 회귀 0* 두 조건?
2. **STOPLIST 의 일부 항목 (한국어 자기지칭) 은 다른 보편 가드로 흡수 가능한가** — 한국어 자기지칭은 ADR-0009 의 *문서 주 entity resolve* 만으로 처리되는가, 따로 가드 필요한가.

## Considered Options

### O1. 본 ADR 거부 — Step 3 + STOPLIST + Consolidator 유지 — *거부*

ADR-0008 + PR #54 의 현 baseline 으로 충분.

거부 이유: MVP 성공 조건 (1) graphify 우월의 기준이 *root-cause 해법의 우아함*. *증상 가림 가드 3 단* 보다 *추출 단계 예방* 이 단순하고 다도메인에 일반화.

### O2. Step 3 + STOPLIST + Consolidator 를 즉시 삭제 — *거부*

ADR-0009 채택과 동시에 모두 삭제.

거부 이유: ADR-0009 의 robustness 가 *측정 전* 이라 즉시 삭제는 위험. Phase 1 의 보조 가드 유지가 안전.

## Consequences

### 즉시 영향

- 측정 baseline 이 *완전히 새 회차* 시작. 기존 회차 (2026-06-19 ~ 2026-06-21) 는 *historical*.
- ingest 흐름이 단순화 (Step 3 + Consolidator 호출 사라짐 — Phase 2 부터).
- ingest 비용 — Step 3 embedding 호출 감소 (Phase 2 부터). Consolidator $0.5 / 회 절감 (Phase 2 부터).

### 종료 조건

| Phase | 측정 | 목표 |
|---|---|---|
| Phase 1 | 1M 회차 over-merge entity 수 (STOPLIST + Consolidator 유지, Step 3 off) | 0 |
| Phase 2 | 1M 회차 over-merge entity 수 (STOPLIST 비활성, Consolidator 비활성, Step 3 off) | ≤ 4 (PR #54 의 정상 자기지칭 4 와 동등) |
| Phase 3 | 다도메인 (commerce 95K + financebench 1M + 한국어 corpus) over-merge | 0 |

Phase 3 통과 시 STOPLIST + Consolidator + Step 3 코드 *모두 삭제*.

## Related

- [ADR-0009](./0009-context-aware-extraction.md) — 본 ADR 의 *선행 조건*. matched_existing_id 가 작동해야 본 ADR 의 deprecation 이 안전.
- [ADR-0010](./0010-multi-agent-parallel-and-cache.md) — 본 ADR 의 새 baseline 측정이 ADR-0010 의 시간 단축 위에서 *반복 가능*.
- [ADR-0008](./0008-entity-consolidator-gating.md) — 본 ADR 이 deprecate 하는 대상. ADR-0008 의 evidence (1M 회차 결과) 는 *Phase 1 의 baseline* 으로 보존.
- PR #51 (STOPLIST), PR #54 (Consolidator) — 본 ADR 의 deprecation 대상 코드.
