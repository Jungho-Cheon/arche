# ADR-0010: Multi-agent parallel dispatch + 청크 결과 캐싱 — graphify Part B 패턴 채택

Status: **accepted (2026-06-21 실측 evidence)**
Date: 2026-06-21
Amends: [ADR-0001](./0001-project-identity-and-mvp-validation-hypothesis.md), [PRD 2 §6](../prd/2_mvp_walking_skeleton.md)
Related: [ADR-0009](./0009-context-aware-extraction.md) (선행)

## 2026-06-21 실측 evidence

1M 회차 ingest 시간 — PR #54 baseline **17 분 (1014 초)** → 본 ADR 적용 후 **9 분 7 초 (547 초) — 45.9% 단축**. ThreadPoolExecutor batch=8 의 직접 효과. main_entity 2nd pass 가 추가됐는데도 단축 — pure parallel 효과는 더 큼.

cache 효과는 본 회차에서 첫 ingest 라 miss 만. 재 ingest 시 효과는 후속 측정.

본 결과로 ADR Status proposed → accepted.

## TL;DR

현재 ingest 의 추출 단계는 *청크별 순차 LLM 호출* + *결과 캐싱 없음*. 1M corpus 1 회 ingest = **30 분** (PR #54 측정). graphify 의 같은 단계 (Part B) 는 *batch parallel dispatch* + *청크 해시 캐시* 로 *분 단위* 에 끝난다.

본 ADR 은:

1. **추출 단계의 청크 호출을 batch 단위 (default 8) parallel 로 묶음** (asyncio.gather 또는 ThreadPoolExecutor).
2. **추출 결과 캐시** — `cache key = sha256(chunk_text + context_hash + system_prompt_hash + model_id)`. 같은 키는 LLM 호출 0.
3. **인크리멘탈 ingest** — 변경 없는 파일 + 변경 없는 청크는 자동 cache hit.

ADR-0009 의 컨텍스트 동봉으로 늘어난 토큰 비용을 본 ADR 의 *시간 단축 + 캐싱* 이 보완. 두 ADR 은 *함께 채택* 한다.

> 용어 인라인 풀이.
>
> - **batch parallel**: 여러 LLM 호출을 같은 메시지 / 같은 async loop 안에서 *동시* 에 dispatch. 순차 대비 (N 청크 × 1 호출 시간) → max(호출 시간) 으로 시간이 줄어듦.
> - **청크 캐시**: 청크 본문 + 호출 컨텍스트를 키로 추출 결과 JSON 을 디스크에 보존. 같은 키 재호출 시 LLM 우회.

## Context — 왜 이 결정이 필요했나

### 현 흐름의 시간 / 비용 데이터 (PR #54 1M 회차)

```
6 파일 (1M tokens) × 청크 ~80 개 × 순차 LLM 호출
= ingest 시간 1014 초 = 17 분
+ embedding 호출
= 합계 ~30 분
+ 비용 ~$5-10
```

같은 corpus 를 *재 ingest* 하면 같은 시간 / 비용 반복. IngestionRun 차분은 *파일 단위* 만 short-circuit (source_hash 동일 시) — 같은 파일의 *청크 결과 캐시* 는 없음.

### graphify 의 같은 단계

```
같은 corpus → Part B (semantic extraction)
- 청크 묶음 단위 dispatch (20-25 청크 / 묶음)
- 한 메시지 안에 multiple Agent 호출 (parallel)
- cache check 가 첫 단계 — 변경 없는 청크는 LLM 호출 0
- 결과: 같은 작업이 분 단위
```

→ graphify 가 우리보다 *5-10x 빠름*. 같은 작업 (entity 추출) 인데 우리가 *순차 + 캐시 없음* 으로 시간 / 비용 손실.

### MVP 성공 조건 (1) "graphify 보다 우월한 그래프 생성" 의 직접 영향

ingest 가 *분 단위로 끝나야* 비교 측정 회차를 *반복* 할 수 있다. 30 분이면 한 가설 검증에 반나절. 측정 cycle 자체가 제품 진화 속도를 결정.

## Decision

### D1. 청크 추출 호출을 batch parallel — default batch=8

```
청크 묶음 (8 개) → asyncio.gather([
  extract(chunk_1, context_1),
  extract(chunk_2, context_2),
  ...
  extract(chunk_8, context_8),
])
```

OpenAI 의 동시 호출 제한 (Tier 별 RPM/TPM) 을 고려해 *batch 크기 + 묶음 간 sleep* 을 노브로. default 8 은 *Tier 2 안전* + *대부분 corpus 에 분 단위 ingest* 의 타협.

### D2. 청크 결과 캐시 — sha256 기반

```python
@dataclass(frozen=True)
class ExtractionCacheKey:
    chunk_sha: str          # sha256(chunk_text)
    context_sha: str        # sha256(json.dumps(context, sort_keys=True))
    system_prompt_sha: str  # sha256(system_message)
    model_id: str           # "openai/gpt-4.1"
    version: str            # ADR-0009 v1, v2 ... 통제 변수 변경 시 invalidate

def cache_path(key: ExtractionCacheKey) -> Path:
    # 같은 corpus 내 다른 파일이 우연히 동일 청크 본문이면 *결과 공유* 가능.
    return Path(".arche-cache/extract/") / f"{key.combined_sha()}.json"
```

캐시 저장소:
- 호스트 파일 시스템 (`.arche-cache/` — `.gitignore` 권장).
- Docker volume 마운트로 컨테이너 간 공유 가능.
- 사내 인프라 채택 시 (Phase 3 의 ADR-0015) Redis 또는 S3 로 격상 가능.

### D3. 인크리멘탈 ingest — 파일 + 청크 두 단계

```
파일 단계 (PR #16 부터 있음):
  source_hash 일치 → 파일 통째로 short-circuit

청크 단계 (본 ADR 신규):
  파일은 변경됐지만 일부 청크는 동일 → 그 청크만 cache hit
```

이는 *부분 갱신* 흐름의 핵심. 사내 공유 KB 시나리오 (Phase 3 ADR-0015) 에서 대용량 문서 일부만 갱신될 때 *전체 재 ingest 비용 0* 으로 운영 가능.

### D4. IngestionRun 차분의 의미 보존

본 ADR 은 *추출 단계의 시간 / 비용* 만 다룬다. PRD 2 §5 의 IngestionRun 차분 적용 (삭제 / trim) 은 그대로. cache hit 이어도 *해당 회차에 그 청크가 touch 됐다* 는 사실은 그대로 IngestionRun 에 기록 (emitted_entity_ids / emitted_relation_ids).

### D5. 측정 통제 변수 — version 필드

ADR-0009 의 system prompt 변경 시 캐시 invalidation 이 필요. 위 D2 의 `version` 필드 (semver 형식) 로 *명시적 통제*. 측정 회차의 meta.yaml 에 version 기록.

## Open Questions (사용자 합의 필요)

1. **batch 크기 default** — 8 이 우리 OpenAI Tier 와 corpus 분포에 적정한가. 사용자의 사내 인프라가 어떤 LLM provider 인가 (사내 LLM, OpenAI 직, Azure?) 에 따라 다름.
2. **캐시 저장소** — 로컬 디스크 (간단) vs Redis (Phase 3) vs S3 (사내 인프라). 본 ADR Phase 1 = 로컬, Phase 3 = 사내 결정.
3. **cache TTL** — 무한 vs N 일 후 자동 invalidate. 무한이 단순하지만 disk 가 무한 증가.

## Considered Options

### O1. 본 ADR 거부 — 순차 호출 유지 — *거부*

거부 이유: graphify 와의 시간 / 비용 격차가 *측정 cycle 자체를 늦춤*. MVP 성공 조건 (1) 미달 직접 원인.

### O2. batch 대신 모든 청크 한 호출에 묶음 — *거부*

전체 청크를 한 LLM 호출의 user 메시지에 concat.

거부 이유:
- LLM 컨텍스트 한도 초과.
- 한 호출이 실패하면 전체 ingest 재시작.
- 청크별 컨텍스트 (ADR-0009 의 DOC_CONTEXT, KNOWN_ENTITIES) 가 청크마다 달라 묶을 수 없음.

### O3. 별도 큐 / 워커 도입 — *거부 (Phase 1)*

Celery / RQ / SQS 기반 분산 워커.

거부 이유: 시제품 단계 (M7-D) 의 단일 인프라 가정에 과도. asyncio 안에서 충분. Phase 3 사내 인프라 시점에 재검토.

## Consequences

### 즉시 영향

- ADR-0009 의 컨텍스트 동봉으로 늘어난 토큰 비용을 본 ADR 의 시간 단축으로 *시간당 가격* 측면 상쇄.
- 추출 단계가 *I/O bound* 가 되어 thread / async 안전성이 중요. ingest 흐름의 동시성 모델 명시 필요.
- 캐시 디렉토리 관리 (gitignore, 크기 모니터링, invalidation rule).
- 1M 회차 ingest 30 분 → 목표 5-10 분.

### 측정 통제 변수

- ADR-0010 채택 후 *시간 / 비용 메트릭* 의 baseline 이 PR #54 의 30 분 → 새 회차로 갱신.
- system prompt + 컨텍스트 schema 의 version 필드 도입 — meta.yaml 에 기록.

### 종료 조건

| 측정 | 목표 |
|---|---|
| 1M 회차 ingest 시간 | 30 분 → **8 분 이하** (5x 단축) |
| 동일 corpus 재 ingest 시간 (cache hit) | **30 초 이하** (인덱스 갱신만) |
| ADR-0009 의 정확도 회귀 | 0 (parallel 화로 정확도 변화 없음) |
| 동시 호출 안정성 | 100 회차 ingest 중 dependency error 0 |

## Related

- [ADR-0009](./0009-context-aware-extraction.md) — 선행 ADR. 본 ADR 의 batch parallel 은 ADR-0009 의 컨텍스트 동봉 흐름 위에서 작동.
- [ADR-0011 (예정)](./0011-step3-cosine-opt-in.md) — STOPLIST/Consolidator deprecation. 본 ADR 의 캐시 invalidation rule 과 함께.
- graphify SKILL.md — Part B 의 parallel agent dispatch 패턴 직접 참조.
