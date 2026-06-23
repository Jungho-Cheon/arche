# ADR-0014: MCP HTTP+SSE transport — 사내 인프라 / 외부 agent 양쪽 노출

Status: proposed (RFC)
Date: 2026-06-21
Amends: [ADR-0006](./0006-mcp-rest-primitives-surface.md)
Phase: 2 of M7-D

## TL;DR

현 MCP 어댑터는 *stdio transport 만* (`opentology mcp serve --stdio`). 이는 *로컬 agent (Claude Code CLI 등)* 에서는 작동하지만, MVP 성공 조건 (사용자 goal 2026-06-21) 의 (3) MCP 제공 + (4) 사내 인프라 활용을 위해서는 **HTTP+SSE transport** 또는 **Streamable HTTP** 가 필요하다.

본 ADR 은:

1. **MCP Streamable HTTP transport 추가** (2024-11 spec).
2. **stdio transport 와 코드 공유** — 단일 핸들러, transport adapter 만 분리.
3. **인증 / 권한 전파** — HTTP header → MCP context.
4. **사내 인프라 배치** — gateway 뒤 + namespace 격리 (ADR-0015 와 정합).

## 이 ADR 을 읽는 이유

- 외부 agent (Claude Desktop / Cursor / 자체 LLM) 가 *사내 opentology 서비스* 를 도구로 등록하려면 어떤 transport 가 필요한가.
- MCP stdio 가 *로컬 한정* 인 제약을 어떻게 푸는가.
- ADR-0006 의 *MCP 표면 결정* 위에서 *transport 만 추가* 하는 형태.

## Context — 왜 이 결정이 필요했나

### MCP transport 옵션 (2024-11 spec)

| Transport | 사용 시나리오 |
|---|---|
| stdio | 같은 호스트의 agent → 도구 프로세스 spawn |
| HTTP+SSE (legacy) | 원격 agent → HTTP 호출 + SSE 로 progress 스트림 |
| Streamable HTTP (신규, 2024-11) | 단일 HTTP endpoint 가 양방향 streaming |

stdio 만 있을 때 한계:
- 외부 agent (Claude.ai, ChatGPT, Gemini) 가 *원격 호출* 불가.
- 사내 인프라 (Kubernetes pod, internal LB) 뒤 배치 불가.
- 여러 사용자가 *같은 KB 인스턴스* 공유 (Phase 3) 불가.

### 사내 인프라 (Phase 3 ADR-0015) 와의 연계

사용자 goal 의 (4) "사내 인프라를 활용한 공유 KB 구축" 이 필요. 가정:

- opentology API 서비스가 사내 Kubernetes 또는 docker host 에 배치.
- 사용자의 LLM agent (claude.ai 또는 사내 LLM) 가 *원격* HTTP 호출.
- 인증은 사내 SSO 또는 API key.

stdio 는 이 시나리오 *완전 미달*. HTTP transport 필수.

## Decision

### D1. Streamable HTTP 가 default — HTTP+SSE 도 호환

```
POST /mcp/v1/                 # single endpoint, JSON-RPC 2.0
Accept: text/event-stream     # streaming response
Authorization: Bearer <token>
```

응답 body 는 *server-sent events* (text/event-stream). 도구 호출 결과를 *progress + final* 로 스트림.

```
data: {"jsonrpc":"2.0","method":"notifications/progress","params":{...}}

data: {"jsonrpc":"2.0","id":1,"result":{...}}
```

legacy HTTP+SSE 클라이언트 호환:
- `GET /mcp/v1/sse` (server → client SSE)
- `POST /mcp/v1/message` (client → server)

### D2. stdio + HTTP 코드 공유

```
opentology_api/mcp/
├── handlers.py        # tool 호출 핸들러 — transport 무관
├── tool_registry.py   # 6 primitive + /answer 도구 정의
├── transports/
│   ├── stdio.py       # 현 코드 이동
│   ├── http.py        # 신규 (Streamable HTTP)
│   └── sse.py         # legacy 호환
└── cli.py             # `opentology mcp serve --stdio|--http`
```

핸들러는 *transport 와 무관* — 같은 dependency injection (graph repo / answer service).

### D3. 인증 / 권한

- `Authorization: Bearer <token>` 헤더 → MCP context 에 user_id / namespace 주입.
- 토큰 검증은 *외부* (사내 SSO gateway 또는 API key store) — 본 ADR 은 검증 방식 자체를 정하지 않고 *주입 포인트* 만 명시.
- 토큰 부재 / 잘못 → ADR-0013 D2 의 `not_authorized` 코드 반환.

### D4. namespace 격리 (ADR-0015 와 정합)

토큰에서 추출한 `namespace_id` 가 *모든 그래프 호출의 implicit filter*.

```
agent → POST /mcp/v1/ (find_entities { name: "John" })
  → handler 가 token 에서 namespace="work-a" 추출
  → graph.find_entities(name="John", namespace="work-a")
  → "work-a" 안의 John 만 반환
```

cross-namespace 접근은 *별도 권한* 필요. ADR-0015 의 namespace 모델 위에서 작동.

### D5. 사내 인프라 배치 patterns

본 ADR 은 *어떤 인프라에 배치하라* 를 정하지 않는다 (사용자 결정). 대신 *배치 가능성* 보장:

- 단일 binary (`opentology mcp serve --http --port 8080`) 가 컨테이너 한 개에 들어감.
- 헬스체크 endpoint `/healthz` 가 LB 와 호환.
- 12-factor app 원칙 — 설정은 env var.
- ADR-0010 의 캐시 디렉토리는 *공유 volume* 으로 마운트 가능.

가능한 배치:
1. Kubernetes Deployment + Service + Ingress
2. Docker Compose (사내 단일 호스트)
3. Systemd service (bare metal)
4. Cloud Run / Lambda + EFS / S3 캐시

사용자가 Phase 3 ADR-0015 에서 결정.

## Open Questions

1. **Streamable HTTP 의 *MCP SDK 지원* 상태** — `mcp` Python SDK 가 2024-11 spec 의 streamable HTTP 를 안정 지원하는가? 아니면 HTTP+SSE legacy 만 가능?
2. **D3 인증의 *구체적 형태*** — JWT? Opaque token? mTLS? 사내 SSO 의 형태에 의존.
3. **D5 배치 — Kubernetes vs Docker Compose vs Bare metal** — 사용자의 사내 인프라 결정.

## Considered Options

### O1. stdio 만 유지 — *거부*

거부 이유: MVP 성공 조건 (4) 사내 공유 KB 미달.

### O2. REST API 만 노출하고 MCP 자체 안 함 — *거부*

agent 가 REST 만 호출.

거부 이유:
- ADR-0006 D5 의 *primitive 단일 source* 결정 의미 없어짐.
- 외부 agent (Claude Desktop) 의 *도구 등록* UX 가 MCP 표준 기반. REST 만 노출 시 agent 가 *툴 인식* 못 함.
- vendor lock-in 방지 (OpenAI Function Calling 만 노출보다 MCP 가 vendor neutral).

### O3. gRPC streaming — *거부*

거부 이유:
- agent ecosystem (Claude / ChatGPT / 사내 LLM) 의 *표준 transport* 가 MCP HTTP. gRPC 추가는 *복잡도* 만.
- 사내 인프라 (대부분 HTTP) 와 정합 떨어짐.

## Consequences

### 즉시 영향

- MCP transport 추상화 리팩토링 (D2).
- 인증 미들웨어 도입 (D3) — ADR-0015 의 namespace 와 동시 작업.
- 배치 가이드 작성 (`docs/deploy/`).

### Phase 2 종료 조건

| 측정 | 목표 |
|---|---|
| Claude Desktop / Cursor 에서 *원격* opentology MCP 등록 성공 | ★ |
| HTTP transport 호출 / stdio 호출 결과 일치 | 100% |
| 인증 실패 시 not_authorized 응답 | 100% |
| ADR-0013 D7 의 *MCP = REST 결과* 정합 | 100% |

## Related

- [ADR-0006](./0006-mcp-rest-primitives-surface.md) — MCP 표면 결정. 본 ADR 이 transport 만 amend.
- [ADR-0013](./0013-agent-friendly-api-contract.md) — REST 와 같은 contract. 단일 schema source.
- [ADR-0015](./0015-shared-kb-operating-model.md) — 본 ADR 의 namespace 격리가 ADR-0015 의 namespace 모델 위에서 작동.
