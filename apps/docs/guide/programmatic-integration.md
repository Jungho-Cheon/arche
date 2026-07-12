# 코드로 에이전트에 붙이기

[에이전트에 연결하기](/guide/agent-integration)가 Claude Desktop 같은 완성 클라이언트에 설정 한 조각을 적는 길이라면, 이 장은 직접 짠 에이전트나 오케스트레이터에 Arche 를 코드로 붙이는 길입니다. MCP 클라이언트로 서버에 붙어 도구 목록을 받아 오고, 한 질문을 풀 때까지 도구를 이어 부르는 흐름을 처음부터 끝까지 코드로 보여 줍니다.

::: tip 준비물
[시작하기](/guide/getting-started)로 그래프 DB(Neo4j)를 띄우고 문서를 조금 적재해 둔 상태를 전제합니다. 아래 예시는 Python 의 [`mcp`](https://pypi.org/project/mcp/) 클라이언트 라이브러리를 씁니다(`pip install mcp` 또는 `uv add mcp`).
:::

## MCP 서버에 붙어 도구 목록 받기

MCP 클라이언트는 `arche mcp serve --stdio` 를 자식 프로세스로 띄우고 그 표준 입출력에 붙습니다. 붙고 나면 `initialize` 로 손을 맞춘 뒤 `list_tools` 로 서버가 노출하는 도구(조회 6 + 검토형 적재 4)를 받아 옵니다.

```python
import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# arche 프로세스에 넘길 접속 정보. .env 자동 탐색에 기대지 말고 여기서 직접 넘긴다
# (작업 폴더 문제로 .env 를 못 찾는 함정은 에이전트에 연결하기 문서 참고).
SERVER = StdioServerParameters(
    command="uv",
    args=["run", "--project", "/path/to/arche/apps/api", "arche", "mcp", "serve", "--stdio"],
    env={
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "arche",
        "OPENAI_API_KEY": "sk-...",
    },
)


async def main() -> None:
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([t.name for t in tools.tools])
            # ['get_schema', 'find_entities', 'get_entity', 'get_neighbors',
            #  'find_path', 'get_subgraph', 'ingest_plan', 'ingest_preview',
            #  'ingest_resolve', 'ingest_commit']


asyncio.run(main())
```

MCP 도구는 응답을 봉투 없이 돌려줍니다(REST 의 `{ "data": ... }` 껍질이 없습니다). `call_tool` 이 돌려주는 결과의 본문은 텍스트 조각 하나에 JSON 으로 담겨 오므로, 아래처럼 풀어 씁니다.

```python
import json
from mcp import ClientSession


async def call(session: ClientSession, name: str, args: dict) -> dict:
    """MCP 도구 하나를 부르고 payload(dict)를 돌려준다. 오류면 예외."""
    result = await session.call_tool(name, args)
    payload = json.loads(result.content[0].text)
    if result.isError:
        # 봉투 없는 MCP 오류는 { "error": { "code", "message", "details } } 모양.
        err = payload.get("error", {})
        raise RuntimeError(f"{name} 실패: {err.get('code')} — {err.get('message')}")
    return payload
```

## 한 질문을 푸는 호출 루프

Arche 는 한 방에 답을 주지 않습니다. 작은 조회를 이어 붙여 답에 필요한 연결을 따라가는 쪽은 부르는 에이전트입니다. 아래는 "이 프로모션에 어떤 환불 규정이 걸리나" 같은 질문을, 도구를 이어 부르며 푸는 최소 오케스트레이터입니다. 문서가 설명한 멈춤 신호 세 가지(빈 결과 / 충분한 근거 / 호출 예산 소진)를 코드로 옮겼습니다.

```python
async def answer_question(session: ClientSession, keywords: list[str], budget: int = 8) -> dict:
    """키워드로 출발점을 잡고, 예산 안에서 이웃과 경로를 따라 근거를 모은다."""
    calls = 0

    # 1) 키워드 → 출발점 ID. 거의 모든 흐름이 여기서 시작한다.
    found = await call(session, "find_entities", {"keywords": keywords, "limit": 5})
    calls += 1
    matches = found["matches"]
    if not matches:
        # 빈 결과 = 이 갈래는 막힘. 낱말을 바꾸거나 get_schema 로 타입을 보고 다시.
        return {"status": "no_entry_point", "keywords": keywords}

    anchor_ids = [m["node"]["id"] for m in matches[:2]]
    evidence: list[dict] = []

    # 2) 두 출발점이 실제로 이어지는지 경로로 확인 (출발점이 둘 이상일 때).
    if len(anchor_ids) >= 2 and calls < budget:
        paths = await call(
            session,
            "find_path",
            {"from_id": anchor_ids[0], "to_id": anchor_ids[1], "max_hops": 4},
        )
        calls += 1
        best = choose_path(paths["paths"])
        if best is not None:
            evidence.append({"kind": "path", "path": best})

    # 3) 근거가 부족하면 출발점 이웃을 한 걸음 펼쳐 관계를 더 캔다.
    if not evidence and calls < budget:
        neighbors = await call(
            session, "get_neighbors", {"id": anchor_ids[0], "hops": 1, "max_nodes": 50}
        )
        calls += 1
        evidence.append({"kind": "neighbors", "edges": neighbors["edges"]})

    # 충분한 근거가 모였거나 예산을 다 썼으면 멈추고 가진 것으로 답한다.
    return {"status": "answered" if evidence else "insufficient", "evidence": evidence, "calls": calls}
```

## hub_score 로 경로 고르기

`find_path` 가 경로를 여럿 돌려줄 때, 어느 경로를 근거로 삼을지는 부르는 쪽이 정합니다. 각 경로에 딸려 오는 `hub_score` 가 길잡이입니다. 값이 낮을수록 더 구체적이고, `0` 이면 가장 단단한 직접 연결입니다. 값이 크면 수많은 노드와 얽힌 허브를 다리로 삼은 "닿긴 닿지만 의미가 약한" 경로라 근거로 삼기 전에 의심해야 합니다(자세한 원리는 [경로 품질과 hub_score](/concepts/path-quality)).

```python
def choose_path(paths: list[dict]) -> dict | None:
    """가장 구체적인 경로를 고른다 — hub_score 낮은 것 우선, 같으면 짧은 것."""
    if not paths:
        return None
    ranked = sorted(paths, key=lambda p: (p["hub_score"], p["length"]))
    best = ranked[0]
    # hub_score 가 높으면 근거로 삼기 전에 경고 — relation_types 를 좁혀 다시 부르는
    # 것도 방법이다(허브 다리 대신 특정 관계를 강제).
    if best["hub_score"] > 3.0:
        best = {**best, "warning": "hub_score 가 높음 — 근거로 삼기 전 의심"}
    return best
```

## 프레임워크에 얹기 — OpenAI Agents SDK 예시

직접 루프를 짜는 대신, MCP 를 지원하는 에이전트 프레임워크에 Arche 서버를 그대로 물릴 수도 있습니다. 이때는 도구를 손으로 부르지 않고, 모델이 도구 목록을 보고 스스로 골라 부릅니다. [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) 는 stdio MCP 서버를 바로 받습니다.

```python
from agents import Agent, Runner
from agents.mcp import MCPServerStdio

INSTRUCTIONS = (
    "너는 사내 문서 그래프를 조회해 답하는 도우미다. 거의 모든 질의는 find_entities "
    "로 출발점 노드를 찾는 데서 시작한다. 두 개념이 이어지는지 볼 때는 find_path 를 "
    "쓰고, 경로의 hub_score 가 높으면 근거로 삼기 전에 의심해라(낮을수록 구체적). "
    "빈 결과면 낱말을 바꾸고, 근거가 충분하면 더 부르지 말고 답해라."
)


async def main() -> None:
    async with MCPServerStdio(
        params={
            "command": "uv",
            "args": ["run", "--project", "/path/to/arche/apps/api", "arche", "mcp", "serve", "--stdio"],
            "env": {"NEO4J_URI": "bolt://localhost:7687", "NEO4J_PASSWORD": "arche", "OPENAI_API_KEY": "sk-..."},
        }
    ) as arche:
        agent = Agent(name="arche-helper", instructions=INSTRUCTIONS, mcp_servers=[arche])
        result = await Runner.run(agent, "이 여름 프로모션에 어떤 환불 규정이 걸리나?")
        print(result.final_output)
```

LangGraph 나 다른 프레임워크도 MCP 클라이언트 어댑터를 통해 같은 식으로 붙습니다. 어느 쪽이든 서버를 어떤 명령으로 띄울지와 접속 정보(`env`)만 넘기면 됩니다.

## REST 로 붙는다면 — OpenAPI 스펙

에이전트를 쓰지 않고 REST 조회를 직접 부르는 클라이언트를 만든다면, API 서버가 내놓는 OpenAPI 스펙을 그대로 쓰는 편이 빠릅니다. 서버를 띄운 뒤 아래 두 주소가 열립니다.

| 주소 | 무엇 |
| --- | --- |
| `GET /openapi.json` | 기계가 읽는 OpenAPI 스펙. `openapi-generator` 같은 도구로 타입 있는 클라이언트를 자동 생성 |
| `GET /docs` | 사람이 버튼으로 눌러 보는 Swagger UI |

이 스펙은 조회 6개와 관리 엔드포인트(`/admin/*`)를 덮습니다. 검토형 적재 도구 네 개는 MCP 로만 노출되므로 OpenAPI 스펙에는 없습니다(REST 로 문서를 넣는 건 `POST /admin/ingest` 라는 별도 경로입니다). 응답 봉투(`{ "data": ... }`)와 에러 코드는 [그래프 조회 연산](/reference/primitives)과 [에러 코드](/reference/errors)에 정리돼 있습니다.

::: warning 예시 코드는 뼈대입니다
위 코드는 흐름을 보여 주는 최소 뼈대입니다. 실제 서비스에서는 재시도(임베딩 provider 일시 장애 시 `dependency_unavailable`), 타임아웃, namespace 지정(`namespace_id` 인자), 로깅을 상황에 맞게 더하세요.
:::

## 다음으로

- [에이전트에 연결하기](/guide/agent-integration) — 완성 클라이언트(Claude Desktop 등)에 설정으로 붙이는 길, 전송 방식(stdio / HTTP), 도구 이름표.
- [그래프에 질의하기](/guide/query) — 여섯 조회 연산을 실제 호출과 응답으로.
- [경로 품질과 hub_score](/concepts/path-quality) — 경로를 언제 의심해야 하는지.
