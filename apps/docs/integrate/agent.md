# 에이전트와 연결하기

에이전트가 Arche 를 부르게 하는 방법입니다. 연결하는 방식은 셋이고, 에이전트와 Arche 가 같은 기계에 있는지에 따라 갈립니다.

| 방식 | 언제 | 설정 |
| --- | --- | --- |
| Claude Code 플러그인 | Claude Code 를 쓸 때 | 명령 두 줄, 사전 설치 없음 |
| stdio 전송 | 다른 MCP 클라이언트, 같은 기계 | 설정 다섯 줄 |
| HTTP 전송 | 네트워크 너머 원격 에이전트 | 주소와 헤더 |

어느 방식이든 **같은 도구 12개**가 같은 이름과 같은 스키마로 올라옵니다. 조회 7개와 검토형 적재 5개입니다.

## Claude Code 플러그인

도구만 연결하는 게 아니라 언제 무엇을 어떤 순서로 부를지의 사용 패턴까지 스킬로 함께 설치합니다. Claude Code 를 쓴다면 이쪽이 가장 손이 적게 갑니다.

```text
/plugin marketplace add Jungho-Cheon/arche
/plugin install arche@arche
```

설치하면 `/arche-ingest` 와 `/arche-query` 두 명령이 생기고, 맥락에 맞으면 Claude 가 알아서도 부릅니다.

전제조건은 uv 하나입니다. 실행 파일은 플러그인이 `uv tool run` 으로 직접 받으므로 미리 설치할 게 없습니다. 임베딩 키는 안 넣어도 도구가 올라오고, 넣는 방법은 [시작하기](/getting-started)의 2단계에 있습니다.

플러그인 기본 설정은 추출을 Claude Code 구독 인증으로 돌려서 추출용 API 키가 필요 없습니다. 대신 이미지와 PDF 이미지 페이지가 빠집니다. 바꾸려면 [모델 갈아끼우기](/operate/models)를 보세요.

설치부터 첫 질의까지 따라가려면 [시작하기](/getting-started)로 가세요.

## stdio 전송

Claude Desktop, Cursor 처럼 MCP 를 받는 클라이언트에 직접 등록합니다. 에이전트와 Arche 가 같은 기계에 있을 때 프로세스를 파이프로 잇는 방식입니다.

```json
{
  "mcpServers": {
    "arche": {
      "command": "arche",
      "args": ["mcp", "serve", "--stdio"]
    }
  }
}
```

`arche` 를 도구로 설치하지 않았다면 저장소 경로로 부릅니다.

```json
{
  "mcpServers": {
    "arche": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/arche/apps/api", "arche", "mcp", "serve", "--stdio"]
    }
  }
}
```

설정을 고치고 클라이언트를 다시 켜면 도구 목록에 12개가 올라옵니다.

### 설정 값 넘기기

`.env` 대신 클라이언트 설정의 `env` 로 넘길 수 있습니다. 어느 저장소를 볼지, 어떤 모델을 쓸지가 여기서 갈립니다.

```json
{
  "mcpServers": {
    "arche": {
      "command": "arche",
      "args": ["mcp", "serve", "--stdio"],
      "env": {
        "ARCHE_API_GRAPH_BACKEND": "embedded",
        "ARCHE_API_LLM_MODEL": "claude-code/sonnet",
        "ARCHE_API_EMBEDDING_MODEL": "openai/text-embedding-3-small",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

값 목록은 [환경 변수](/reference/configuration)에 있습니다.

**그래프가 어디에 쌓이는지 주의하세요.** 임베디드 저장소의 기본 경로는 상대 경로라, 클라이언트가 서버를 띄운 자리를 기준으로 풀립니다. 어디서 띄우든 같은 그래프를 보게 하려면 `ARCHE_API_KUZU_DB_PATH` 에 절대 경로를 적으세요.

## HTTP 전송

네트워크 너머 에이전트를 붙일 때 씁니다. `arche mcp serve` 로는 안 되고 **API 서버가 띄웁니다.** 서버가 기동하면서 `/mcp/v1` 아래에 자동으로 마운트합니다.

```bash
uvicorn arche_api.main:app
```

`docker compose up -d` 로 띄운 서버에도 이미 마운트돼 있습니다.

클라이언트 설정입니다.

```json
{
  "mcpServers": {
    "arche": {
      "url": "http://arche.사내주소:8000/mcp/v1/",
      "headers": { "Authorization": "Bearer ns:team-a" }
    }
  }
}
```

두 가지 전송을 함께 노출합니다.

| 경로 | 방식 |
| --- | --- |
| `POST /mcp/v1/` | Streamable HTTP. 한 주소가 양방향을 처리합니다 |
| `GET /mcp/v1/sse` 와 `POST /mcp/v1/message` | 예전 HTTP+SSE. 두 주소를 함께 씁니다 |

클라이언트가 지원하는 쪽을 쓰면 됩니다. 어느 쪽이든 도구 이름과 입출력은 같습니다.

`arche mcp serve --no-stdio` 를 시도하면 종료 코드 2 로 끝나며 이 메시지가 나옵니다.

```text
[error] `arche mcp serve` 는 stdio 전송 전용입니다. HTTP(SSE) 로 붙이려면 API 서버를 띄우세요: `uvicorn arche_api.main:app` → /mcp/v1.
```

::: danger HTTP 로 열면 적재까지 네트워크 너머로 열립니다
`/mcp/v1` 에는 조회뿐 아니라 문서를 그래프에 넣는 도구 5개도 함께 올라옵니다. 서버는 `Authorization` 토큰을 검증하지 않으므로, 닿을 수 있는 누구나 그래프를 읽고 씁니다.

사내망이나 인터넷에 노출한다면 앞단에 프록시나 사내 인증을 세우세요. 자세한 경계는 [namespace 로 나눠 담기](/operate/namespace)에서 다룹니다.
:::

## 붙은 뒤 알아 둘 것

**응답을 감싸지 않습니다.** MCP 는 payload 를 그대로 돌려줍니다. REST 처럼 `{ "data": ... }` 로 감싸지 않습니다. 실패는 `isError: true` 와 함께 `{ "error": { ... } }` 로 옵니다.

**namespace 는 도구 인자로 넘깁니다.** MCP 호출에는 HTTP 헤더가 없어서 도구마다 `namespace_id` 를 받습니다. 미지정이면 `default` 입니다. HTTP 전송에서는 클라이언트 설정의 `Authorization` 헤더로 고정할 수도 있습니다.

**쓰기 도구는 없습니다.** 노드를 만들거나 관계를 지우는 도구는 노출되지 않습니다. 그래프를 바꾸는 길은 사람 확인을 거치는 검토형 적재뿐입니다. 서버는 기동 직전에 쓰기 도구가 섞였는지 검사하고, 섞여 있으면 등록을 거부합니다.

## 도구가 안 보일 때

**클라이언트를 다시 켰는지** 확인하세요. 설정을 고쳐도 재시작 전에는 반영되지 않습니다.

**uv 가 깔려 있는지** 확인하세요. 플러그인은 `uv` 로 서버를 띄우므로, 없으면 서버가 시작조차 못 합니다.

```bash
uv --version
```

없으면 [docs.astral.sh/uv](https://docs.astral.sh/uv/) 를 보고 설치한 뒤 클라이언트를 다시 켜세요.

**깔려 있는데도 안 붙으면 PATH 를 의심하세요.** uv 는 보통 `~/.local/bin` 에 설치되는데, 이 자리는 셸 프로필이 PATH 에 넣어 줍니다. 터미널에서 켠 클라이언트는 그 PATH 를 물려받지만 **아이콘으로 켠 앱은 못 받을 수 있습니다.** 터미널에서는 잡히는데 클라이언트에서만 안 붙는다면 이 경우입니다.

```bash
which uv
```

나온 경로를 설정의 `command` 에 그대로 적으면 우회됩니다.

```json
{ "command": "/Users/me/.local/bin/uv", "args": ["tool", "run", "..."] }
```

직접 등록한 설정에서 `"command": "arche"` 를 쓴다면 같은 확인을 `arche` 로 하세요.

**서버가 조용히 죽지 않았는지** 봅니다. 저장소 설정이 틀리면 기동하다 멈춥니다. 같은 설정으로 터미널에서 직접 띄워 보면 오류가 보입니다. 모델과 키 설정이 틀린 경우는 기동을 막지 않고 도구를 부를 때 드러납니다.

```bash
arche mcp serve --stdio
```

## 다음으로

- 첫 적재와 질의는 [시작하기](/getting-started)
- 에이전트 없이 부르려면 [REST 로 직접 부르기](/integrate/rest)
- 도구별 필드는 [조회 도구 참조표](/query/tools)와 [적재 도구 참조표](/ingest/tools)
