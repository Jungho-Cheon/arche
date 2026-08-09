# Arche plugin (Claude Code)

에이전트가 Arche 그래프 지식베이스를 **의도대로** 쓰게 하는 플러그인이에요. 도구만 붙이는 게 아니라, 언제 무엇을 어떤 순서로 부를지의 사용 패턴을 스킬로 함께 설치해요.

## 설치

```text
/plugin marketplace add Jungho-Cheon/arche
/plugin install arche@arche
```

설치하면 `/arche-ingest` 와 `/arche-query` 두 명령이 생기고, Arche 도구 12개(조회 7 + 검토형 적재 5)가 함께 붙어요. 맥락에 맞으면 Claude 가 알아서도 불러요.

첫 실행은 의존성을 받느라 몇 초 걸리고 그다음부터는 1 초 안쪽이에요.

## 전제조건

[uv](https://docs.astral.sh/uv/) 하나예요. 없으면 아래로 설치해요.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

서버 실행 파일은 플러그인이 `uvx` 로 직접 받으므로 저장소를 클론하거나 `arche` 를 미리 설치할 필요가 없어요. **다만 uv 자체는 미리 있어야 해요.** 없으면 플러그인을 깔아도 서버가 시작되지 않아요. `uvx --version` 으로 확인하세요.

깔려 있는데도 도구가 안 붙으면 PATH 문제일 수 있어요. 아이콘으로 켠 클라이언트는 셸 프로필의 PATH 를 못 받을 수 있어서, `which uvx` 로 나온 절대 경로를 `.mcp.json` 의 `command` 에 적으면 우회돼요.

## 임베딩 키

추출은 Claude Code 구독 인증을 쓰므로 키가 필요 없어요. 임베딩만 키를 써요.

키가 없어도 서버는 뜨고 도구 목록도 보여요. 임베딩이 필요한 호출에서 무엇을 채워야 하는지 알려 주고, 그때 아래를 실행하면 돼요. 재시작은 필요 없어요.

```bash
arche config set-key    # ~/.config/arche/config.env 에 권한 600 으로 저장
```

`arche` 를 터미널에서도 쓰려면 그때 따로 설치해요. 플러그인만 쓸 거라면 필요 없어요.

```bash
uv tool install "arche-api @ git+https://github.com/Jungho-Cheon/arche.git@v0.1.2#subdirectory=apps/api"
```

## 쓰는 법

**적재** — "이 Confluence 페이지를 Arche 에 넣어줘" 처럼 시키면 `arche-ingest` 가 흐름을 잡아요. 에이전트가 Atlassian MCP 로 페이지를 읽고 `ingest_content` 로 계획을 세운 뒤, 무엇이 바뀔지 보여 주고, 확인을 받고서야 확정해요.

**질의** — "환불 규정이 어떻게 적용돼?" 처럼 물으면 `arche-query` 가 `find_entities` 로 진입점을 잡고 관계를 따라가 그래프 근거로만 답해요.

## 기본 설정과 바꾸는 법

`.mcp.json` 이 이렇게 잡아 둬요. 저장소는 임베디드 Kuzu(서버 불필요), 추출은 구독형 `claude-code`(API 키 불필요), 임베딩은 OpenAI 소액.

같은 파일의 `env` 로 바꿔요. 전부 OpenAI 로 하려면 `ARCHE_API_LLM_MODEL=openai/gpt-4.1-mini`, 팀이 공유하는 Neo4j 를 보려면 `ARCHE_API_GRAPH_BACKEND=neo4j` 와 접속 변수를 넣어요. 값 목록은 Arche 문서의 환경 변수 참조표에 있어요.

참조는 태그로 고정해 뒀어요. 브랜치로 두면 서버를 띄울 때마다 git fetch 가 일어나 네트워크가 없으면 안 떠요.
