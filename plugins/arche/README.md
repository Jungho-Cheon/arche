# Arche plugin (Claude Code)

에이전트가 Arche 그래프 지식베이스를 **의도대로** 쓰게 하는 하네스다. 도구만 노출하는 게 아니라, 언제 무엇을 어떤 순서로 부를지의 사용 패턴을 스킬로 규정한다.

담긴 것:

- **MCP 서버 등록** (`.mcp.json`) — `uvx` 으로 `arche` 를 받아 stdio MCP 서버로 띄운다. 저장소 백엔드는 임베디드 Kuzu(서버 불필요), 추출은 구독형 `claude-code`(API 키 불필요), 임베딩은 OpenAI 소액.
- **스킬 `arche-ingest`** — 외부 소스(Confluence/Jira/URL)나 로컬 파일을 사람 검토 게이트(plan/content → preview → resolve → commit)로 적재한다.
- **스킬 `arche-query`** — 질문을 그래프 프리미티브로 접근해 그래프 근거로만 답한다.

## 전제조건

- [uv](https://docs.astral.sh/uv/) — MCP 서버가 uv 위에서 돈다. `curl -LsSf https://astral.sh/uv/install.sh | sh` 로 설치한다.

이게 전부다. 서버 실행 파일은 플러그인이 `uvx` 으로 직접 받으므로 저장소를 클론하거나 `arche` 를 미리 설치할 필요가 없다.

단 uv 자체는 미리 있어야 한다. 없으면 플러그인을 깔아도 서버가 시작되지 않는다. `uvx --version` 으로 확인한다. 깔려 있는데도 도구가 안 붙으면 PATH 문제일 수 있다 — GUI 로 켠 클라이언트는 셸 프로필의 PATH 를 못 받을 수 있어서, `which uvx` 로 나온 절대 경로를 `command` 에 적으면 우회된다.

참조는 태그로 고정해 둔다. 브랜치로 두면 서버를 띄울 때마다 git fetch 가 일어나 네트워크가 없으면 안 뜬다.

## 설치

```
/plugin marketplace add Jungho-Cheon/arche
/plugin install arche@arche
```

설치하면 두 스킬(`/arche-ingest`, `/arche-query`)이 생기고, Claude 가 맥락에 따라 자동으로도 부른다. Arche MCP 도구(적재/조회)도 함께 붙는다. 첫 실행은 의존성을 받느라 몇 초 걸리고 그다음부터는 1 초 안쪽이다.

## 임베딩 키

추출은 Claude Code 구독 인증을 쓰므로 키가 필요 없다. 임베딩만 키를 쓴다.

키가 없어도 서버는 뜨고 도구 목록도 보인다. 임베딩이 필요한 호출에서 무엇을 채워야 하는지 알려 주고, 그때 아래를 실행하면 된다. 재시작은 필요 없다.

```bash
arche config set-key    # ~/.config/arche/config.env 에 권한 600 으로 저장
```

`arche` 를 터미널에서도 쓰려면 그때 따로 설치한다. 플러그인만 쓸 거라면 필요 없다.

```bash
uv tool install "arche-api @ git+https://github.com/Jungho-Cheon/arche.git@v0.1.2#subdirectory=apps/api"
```

## 쓰는 법

- **적재** — "이 Confluence 페이지를 Arche 에 넣어줘" 처럼 시키면 `arche-ingest` 가 흐름을 잡는다. 에이전트가 Atlassian MCP 로 페이지를 읽고 `ingest_content` 로 계획 → 미리보기를 보여주고 → 네 확인 후 커밋.
- **질의** — "환불 규정이 어떻게 적용돼?" 처럼 물으면 `arche-query` 가 `find_entities` 로 진입점을 잡고 순회해 그래프 근거로 답한다.

## 설정 바꾸기

`.mcp.json` 의 `env` 로 provider/백엔드를 바꾼다. 예: 전부 OpenAI 로 하려면 `ARCHE_API_LLM_MODEL=openai/gpt-4.1-mini`, 프로덕션 Neo4j 는 `ARCHE_API_GRAPH_BACKEND=neo4j` + Neo4j 접속 변수. 자세한 변수는 Arche 문서의 환경 변수 레퍼런스 참조.
