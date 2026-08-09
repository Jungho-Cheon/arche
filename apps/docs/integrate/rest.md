# REST 로 직접 부르기

에이전트를 쓰지 않고 코드에서 Arche 를 직접 부르는 방법입니다. 조회 7개가 HTTP 엔드포인트로 열려 있어, 그 위에 원하는 검색 흐름을 직접 짜면 됩니다.

에이전트를 연결하는 기본 통로는 MCP 입니다. REST 는 자체 서비스에 끼워 넣거나, 에이전트 없이 그래프를 다룰 때 씁니다. MCP 쪽은 [에이전트와 연결하기](/integrate/agent)에 있습니다.

## 서버 띄우기

REST 를 쓰려면 API 서버가 떠 있어야 합니다. CLI 적재나 stdio MCP 와 달리 이 길만 서버를 거칩니다.

```bash
uvicorn arche_api.main:app
```

Neo4j 와 함께 컨테이너로 띄우려면 [팀과 그래프 공유하기](/operate/sharing)를 보세요.

살아 있는지 확인합니다.

```bash
curl http://localhost:8000/healthz
```

```json
{ "status": "ok", "graph": "ok" }
```

## 한 바퀴 돌려 보기

거의 모든 흐름은 키워드를 노드 ID 로 바꾸는 데서 시작합니다.

```bash
curl -X POST http://localhost:8000/entities/find \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["환불"], "limit": 3}'
```

```json
{
  "data": {
    "matches": [
      {
        "node": { "id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "name": "환불 정책", "type": "Policy" },
        "score": 1.0,
        "matched_keyword": "환불"
      }
    ]
  }
}
```

받은 `id` 를 다음 조회에 넘깁니다. 관련된 것을 한 번에 모으려면 `find_related` 가 왕복이 적습니다.

```bash
curl -X POST http://localhost:8000/related/find \
  -H "Content-Type: application/json" \
  -d '{"seeds": ["01J8XR4K9ZQ2N7M3VB0W4D6TYE"], "top_k": 10}'
```

어느 도구를 언제 쓰는지는 [그래프에 묻기](/query/)에 정리돼 있습니다.

## 응답 다루기

성공은 payload 를 `data` 로 감싸고, 실패는 `error` 를 담습니다.

```json
{ "error": { "code": "entity_not_found", "message": "...", "details": {} } }
```

`code` 로 갈라 쓰고 `message` 는 로그에 남깁니다. 값이 `null` 인 필드는 응답에서 키째 빠지므로, 없는 키를 그대로 읽지 말고 기본값을 두세요.

`invalid_input` 은 `details.errors[]` 에 어느 필드가 왜 걸렸는지 목록으로 담아 줍니다. 요청을 만드는 코드를 고칠 때 이 값을 보면 됩니다.

코드 목록은 [에러 코드](/reference/errors)에 있습니다.

## 스키마에서 클라이언트 만들기

OpenAPI 스펙이 `/openapi.json` 에 자동으로 올라옵니다. 응답 모델이 코드의 스키마에서 나오므로 스펙과 실제 동작이 어긋나지 않습니다.

```bash
curl http://localhost:8000/openapi.json > arche-openapi.json
```

이 스펙으로 언어별 클라이언트를 생성하면 조회 7개와 관리 엔드포인트를 덮습니다. **검토형 적재 도구 5개는 MCP 에만 있어 스펙에 없습니다.** REST 로 문서를 넣는 길은 `POST /admin/ingest` 라는 별도 경로입니다.

눌러 보면서 확인하려면 `/docs` 를 브라우저로 엽니다.

## 버전 접두사

모든 경로는 루트와 `/v1` 양쪽에 올라옵니다.

```text
POST /entities/find
POST /v1/entities/find
```

둘은 같은 엔드포인트입니다. 나중에 계약이 갈릴 때를 대비하려면 `/v1` 쪽을 쓰세요.

## namespace 지정

`Authorization` 헤더가 우선입니다.

```bash
curl -X POST http://localhost:8000/entities/find \
  -H "Authorization: Bearer ns:team-a" \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["환불"]}'
```

헤더 없이 요청 본문의 `namespace_id` 로 넘겨도 됩니다. `GET` 요청은 쿼리 문자열로 받습니다.

::: warning 이 헤더는 로그인이 아닙니다
서버는 토큰을 검증하지 않습니다. 아무나 원하는 이름을 보내면 그 namespace 를 읽고 씁니다. 사용자별로 볼 수 있는 범위를 갈라야 한다면 Arche 앞단에서 처리해야 합니다. 자세한 방법은 [namespace 로 나눠 담기](/operate/namespace)에 있습니다.
:::

## 자주 걸리는 자리

**`graph` 가 `"down"` 입니다.** 그래프 백엔드에 닿지 못한 상태입니다. Neo4j 를 갓 띄웠다면 부팅 중일 수 있으니 몇 초 뒤 다시 부르세요. 계속 그렇다면 접속 정보를 확인합니다.

**`matches` 가 비어 있습니다.** 에러가 아니라 그 키워드로 걸리는 노드가 없다는 뜻입니다. `GET /schema` 로 어떤 타입이 들어 있는지 보고 키워드를 바꿉니다.

**적재가 `directory_not_found` 로 막힙니다.** `directory_path` 는 API 서버가 보는 경로입니다. 서버가 컨테이너 안에 있으면 호스트 경로를 그대로 넣으면 안 됩니다.

## 다음으로

- 엔드포인트별 필드는 [REST API](/reference/rest-api)
- 도구 고르는 법은 [그래프에 묻기](/query/)
- 문서를 넣으려면 [문서를 그래프에 넣기](/ingest/)
