# 에이전트에 5줄로 붙이기

에이전트에 Arche 를 붙이는 데 필요한 건 설정 한 조각입니다. MCP 클라이언트(Claude Desktop, Cursor 같은)에 아래 다섯 줄을 더하면 에이전트가 Arche 도구를 부를 수 있습니다. 별도 연동 코드는 없습니다.

```json
{ "mcpServers": {
  "arche": {
    "command": "uv",
    "args": ["run", "--project", "/path/to/arche/apps/api", "arche", "mcp", "serve", "--stdio"]
} } }
```

`/path/to/arche` 를 내려받은 저장소 경로로 바꿔 적고 클라이언트를 다시 켜면, 대화창의 도구 목록에 Arche 조회 도구 여섯 개와 검토형 적재 도구 네 개가 올라옵니다.

::: tip 먼저 그래프 DB 와 키가 준비돼 있어야 합니다
이 설정으로 띄우는 서버는 그래프 DB(Neo4j)에 직접 붙고, 문서를 넣을 때 AI 모델 키를 씁니다. 아직 준비 전이라면 [시작하기](/guide/getting-started)로 Neo4j 를 올리고 키를 채운 뒤 돌아오세요. 접속 정보를 설정에 직접 넘기는 `env` 블록 방식은 [에이전트에 연결하기](/guide/agent-integration#접속-정보-키-를-어떻게-넘기나)에서 다룹니다.
:::

## 첫 호출 — 키워드로 출발점 찾기

붙었으면 에이전트가 첫 도구를 부를 차례입니다. 거의 모든 흐름은 `find_entities` 에서 시작합니다. 사용자가 아는 건 보통 "환불 정책" 같은 말이지 노드의 ID 가 아니라서, 먼저 키워드를 노드 ID 로 바꿔야 하기 때문입니다.

에이전트가 이렇게 부릅니다.

```json
{ "keywords": ["환불", "정책"], "limit": 5 }
```

돌아오는 응답입니다. MCP 응답에는 REST 의 `{"data": ...}` 봉투가 없어 payload 가 그대로 옵니다.

```json
{
  "matches": [
    {
      "node": { "id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "name": "환불 정책", "type": "Policy" },
      "score": 1.0,
      "matched_keyword": "환불"
    }
  ]
}
```

`matches[0].node.id` 의 ULID(26자리 식별자)가 다음 도구에 넘길 출발점입니다. 이 ID 를 `get_neighbors` 나 `find_path` 에 넘기면 이웃을 펼치거나 다른 노드와의 경로를 잇습니다.

## 다음으로

- [상품에 적용 가능한 프로모션 찾기](/cookbook/applicable-promotions) — `find_entities` 로 찾은 ID 를 `get_neighbors` 에 이어 목표를 푸는 예시.
- [두 개념이 어떻게 이어지는지 밝히기](/cookbook/connect-two-concepts) — 두 노드를 `find_path` 로 잇고 `hub_score` 로 연결을 판단하는 예시.
- [에이전트에 연결하기](/guide/agent-integration) — 전송 방식, 접속 정보 넘기기, 도구 이름표, 호출 흐름 전체.
- [그래프 조회 연산](/reference/primitives) — 각 도구가 받는 입력과 돌려주는 필드 참조표.
