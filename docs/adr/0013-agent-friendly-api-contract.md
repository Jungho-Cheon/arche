# ADR-0013: Agent 친화적 API contract — 응답 envelope, 에러 코드, OpenAPI, idempotency, latency budget, next-action hints

Status: proposed (RFC)
Date: 2026-06-21
Amends: [ADR-0006](./0006-mcp-rest-primitives-surface.md)
Phase: 2 of M7-D

## TL;DR

MVP 성공 최소 조건 (사용자 goal 2026-06-21) 의 (2) "Agent 친화적인 API". 본 ADR 은 *"Agent 친화" 가 구체적으로 무엇을 의미하는가* 를 6 종의 contract 로 명시한다:

1. **DataEnvelope[T] / ErrorEnvelope** 응답 envelope (현 코드 일부 구현)
2. **표준 에러 코드 세트** (entity_not_found / dependency_unavailable / task_not_found 등)
3. **OpenAPI 3.1 자동 export** + Agent 가 schema 만으로 호출 가능
4. **Idempotent endpoint** 명시 — POST /admin/ingest 등 재호출 안전
5. **Latency budget** — 각 endpoint 의 p95 목표 명시 + 헤더 노출
6. **Next-action hints** — 응답 안에 *다음 호출 후보* 명시 (HATEOAS-lite)

추가로:
- REST + MCP 의 *입출력 schema 단일 source* (ADR-0006 D5 강화)
- API versioning (URL prefix `/v1/` 또는 헤더)

## 이 ADR 을 읽는 이유

- Agent (Claude / GPT / 자체 LLM 에이전트) 가 본 API 를 *프로토콜 지식만으로* 호출하려면 어떤 contract 가 필요한가.
- ADR-0006 의 "graph primitives 만 노출" 결정이 *agent 친화* 의 필요조건이지만 충분조건은 아님 — 본 ADR 이 충분조건을 정의.
- 사용자 goal 의 (2)(3) 조건이 함께 충족되는 형태.

## Context — 왜 이 결정이 필요했나

### 현 상태의 산발적 contract

`apps/api/src/arche_api/api/schemas.py` 에 `DataEnvelope` 가 있지만 일관 적용 안 됨:

- `/answer` 의 응답 — DataEnvelope[AnswerResponse] ✓
- `/admin/ingest` 의 응답 — DataEnvelope[AdminIngestResponse] ✓
- `/healthz` — DataEnvelope 안 씀 (단순 객체)

에러 처리:
- `ArcheError` 가 exception handler 에서 ErrorEnvelope 으로 변환 (`main.py`)
- 그러나 *모든* 에러가 통과하지는 않음 — FastAPI 의 422 validation 은 raw FastAPI 형식

OpenAPI:
- 자동 생성 (`/openapi.json`) ✓
- 그러나 *agent 가 실제로 사용할 만한 깊이* 의 description / example 부족

Idempotency:
- POST /admin/ingest 가 source_hash 기반 short-circuit ✓
- 그러나 *클라이언트가 안전하게 재호출 가능한지* 헤더로 안 알림

Latency:
- 측정 회차 데이터로 사후 분석은 가능
- 그러나 *agent 가 호출 시점에 timeout 결정* 할 수 있는 명시적 budget 없음

### Agent 가 본 API 를 호출할 때 겪는 문제

가상 시나리오: Claude 가 본 API 의 `/answer` 를 호출 → 422 응답 → Claude 가 *어떤 필드를 고쳐야 하는지* 응답에서 명확히 못 읽음.

또는: Claude 가 `/admin/ingest` 호출 → 5 분 후 504 timeout → 같은 ingest 가 진행 중인지, 재호출 안전한지 모름.

이런 *agent UX* 의 누락은 *API 가 LLM 의 도구로* 작동할 때 *환각 / 잘못된 재시도* 의 원인.

## Decision

### D1. DataEnvelope[T] / ErrorEnvelope 통일 적용

*모든* HTTP 응답이 다음 형태 중 하나:

```json
// 성공
{ "data": { /* T */ }, "meta": { /* optional */ } }

// 에러
{ "error": { "code": "string", "message": "string", "details": { } } }
```

예외 없음. 422 (validation) 도 ErrorEnvelope 으로 wrap. FastAPI 의 기본 422 형식을 *exception handler* 로 가로채 ErrorEnvelope 으로 변환.

`/healthz` 도 DataEnvelope 형식으로 정렬.

### D2. 표준 에러 코드 세트 (closed enum)

```
# 클라이언트 입력 에러 (4xx)
invalid_input            # 422 — 필드 형식/누락
entity_not_found         # 404 — id 가 없음
task_not_found           # 404 — task_id 가 없음
not_authorized           # 401 — auth header 없음/잘못됨
permission_denied        # 403 — namespace/리소스 권한 없음
rate_limited             # 429 — 호출 한도 초과
conflict                 # 409 — 동시 ingest 등

# 서버 에러 (5xx)
dependency_unavailable   # 503 — Neo4j / LLM provider 다운
extraction_failed        # 500 — LLM 응답 파싱 실패 등
internal_error           # 500 — 알려지지 않은 예외
timeout                  # 504 — 백엔드 timeout
```

추가 코드 도입 시 ADR amend. *agent 가 enum 기반 분기* 가능.

`details` 필드 — 각 코드별 정의된 schema. 예: entity_not_found = `{ "entity_id": "..." }`.

### D3. OpenAPI 3.1 + agent 사용 가능 깊이

- 모든 endpoint 의 `summary` + `description` 한국어/영어 병기. **목적 + 호출 시점 + 응답 형태** 한 문단.
- 모든 request body / response 의 `example` 필수.
- 에러 코드별 example response 동봉 (FastAPI `responses=` 인자 활용).
- `/openapi.json` 이 *agent 가 단독 호출 가능* 한 수준의 documentation.

```python
@app.post(
    "/answer",
    summary="Combined RAG 단일 호출 답변",
    description="...",
    responses={
        200: {"description": "성공", "model": DataEnvelope[AnswerResponse]},
        422: {"description": "invalid_input", "model": ErrorEnvelope, "examples": {...}},
        503: {"description": "dependency_unavailable", "model": ErrorEnvelope},
    },
)
```

### D4. Idempotency 명시

POST 중 idempotent 한 것은 응답 헤더에 `Idempotent: true` + body 의 `meta` 에 `idempotency_key` (server-derived) 명시.

```
POST /admin/ingest { "directory_path": "..." }
→ 응답 헤더: Idempotent: true (source_hash 기반)
→ 응답 본문 meta: { "idempotency_key": "sha256:..." }
```

같은 idempotency_key 재호출 시 *같은 task_id 반환* (현 short-circuit 로직 강화).

### D5. Latency budget — 헤더 노출

각 endpoint 의 *p95 목표* 를 코드에서 명시 + 응답 헤더로 echo.

```
Server-Timing: total;dur=4070, p95-target=5000
```

| Endpoint | p95 목표 | 비고 |
|---|---|---|
| `/answer` | 5s | Combined RAG 단일 호출 |
| `/retrieve` | 3s | LLM 호출 없음 |
| `/retrieve/chunks` | 1s | chunk vector 만 |
| `/entities/find` | 1s | hybrid 검색 |
| 6 graph primitives | 0.5s | DB 단일 쿼리 |
| `/admin/ingest` (POST) | 즉시 (202) | task_id 반환만 |
| `/healthz` | 100ms | |

목표 미달 시 *경고 헤더* `X-Latency-Warning: exceeded-p95` 추가 — agent 가 retry / backoff 결정 가능.

### D6. Next-action hints

각 응답에 *다음 호출 후보* 를 meta 에 명시 (HATEOAS-lite).

```json
// /entities/find 응답
{
  "data": { "matches": [...] },
  "meta": {
    "next_actions": [
      { "purpose": "Get entity detail", "method": "POST", "path": "/entities/{id}/get" },
      { "purpose": "Expand neighbors", "method": "POST", "path": "/entities/{id}/neighbors" }
    ]
  }
}
```

Agent 가 *그래프 탐색을 자율적으로* 진행할 수 있게. *URL 패턴 + 의미* 만 제공 (정확한 URL 은 entity id 로 fill in).

### D7. REST + MCP schema 단일 source

ADR-0006 D5 의 결정 강화:

- pydantic 모델이 *단일 truth*
- REST router 는 pydantic → JSON
- MCP tool definition 은 pydantic → MCP schema 변환 (자동)
- 변환 유틸 (`mcp_tool_from_pydantic`) 한 곳에서 관리

ADR-0014 (MCP HTTP transport) 도 이 단일 source 위에서 작동.

### D8. API versioning — URL prefix `/v1/`

모든 endpoint 가 `/v1/` prefix.

```
/v1/answer
/v1/retrieve
/v1/entities/find
/v1/admin/ingest
...
```

deprecation 시 `/v2/` 신설 + `/v1/` 유지 6 개월. `Deprecation: true` 헤더 + `Sunset: 2026-12-31` 헤더 (RFC 8594).

`/healthz`, `/openapi.json`, `/docs` 는 version prefix 없음 (관습).

## Open Questions

1. **D5 latency budget 의 *p95 목표*** — 표의 값이 적정한가. 현 측정 (PR #54) 에서 `/answer` p95 가 4-5s 였음.
2. **D6 next-action hints 의 상세도** — 단순 link vs JSON-LD/HAL 같은 표준. *agent 토큰 비용* 과의 trade-off.
3. **D8 versioning 의 *언제 깨야 하나*** — Phase 3 사내 인프라 도입 시 v2 가 자연스러운가?

## Considered Options

### O1. 현 상태 유지 — *거부*

DataEnvelope 부분 적용 + 산발 에러 형식.

거부 이유: agent 가 본 API 를 *프로토콜 지식만으로* 호출 못함. MVP 성공 조건 (2) 미달.

### O2. OpenAI Function Calling 호환 schema 직접 노출 — *거부*

각 endpoint 의 schema 를 OpenAI tool definition 형식으로 직접 export.

거부 이유:
- OpenAI 의존 — Claude / Gemini / 사내 LLM 호환성 깨짐.
- MCP 가 이미 vendor-neutral 표준 (ADR-0014 와 정합).
- OpenAPI 3.1 → 각 vendor 형식 변환은 generic.

### O3. GraphQL 도입 — *거부 (Phase 1-2 범위)*

거부 이유: 현 REST + MCP 두 표면이 정의된 *primitive* 와 정합. GraphQL 추가는 *trimming 자유도* 우위가 있지만 *primitive 단순성* 과 충돌. 사내 인프라 시점 (Phase 3) 에 재검토.

## Consequences

### 즉시 영향

- 모든 router 의 응답 형식 통일 작업 (D1).
- exception handler 확장 (D2).
- pydantic 모델에 example 추가 (D3).
- /v1/ prefix 마이그레이션 (D8) — 클라이언트 (eval/, MCP) 동시 갱신.

### 측정 — Phase 2 종료 조건

| 측정 | 목표 |
|---|---|
| OpenAPI 만으로 외부 agent (Claude) 가 `/answer` 호출 성공률 | ≥ 95% |
| 422 응답에서 agent 가 *어떤 필드 고쳐야 하는지* 정확히 식별 | 100% |
| Idempotent 재호출 안전성 | 100% |
| p95 budget 미달 endpoint 수 | 0 |
| MCP tool 호출 결과 = REST 호출 결과 | 100% 일치 |

## Related

- [ADR-0006](./0006-mcp-rest-primitives-surface.md) — 본 ADR 이 amend. *무엇을 노출하는가* (primitives) 는 그대로, *어떻게 노출하는가* (contract) 가 본 ADR.
- [ADR-0014](./0014-mcp-http-transport.md) — 본 ADR 의 D7 (단일 source) 위에서 작동.
- [ADR-0009](./0009-context-aware-extraction.md) — agent 호출의 *입력 품질* 향상. 본 ADR 은 *출력 품질*.
