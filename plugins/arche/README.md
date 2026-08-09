# Arche plugin (Claude Code)

에이전트가 Arche 그래프 지식베이스를 **의도대로** 쓰게 하는 하네스다. 도구만 노출하는 게 아니라, 언제 무엇을 어떤 순서로 부를지의 사용 패턴을 스킬로 규정한다.

담긴 것:

- **MCP 서버 등록** (`.mcp.json`) — `arche mcp serve --stdio` 를 Claude Code 에 연결한다. 저장소 백엔드는 임베디드 Kuzu(서버 불필요), 추출은 구독형 `claude-code`(API 키 불필요), 임베딩은 OpenAI 소액.
- **스킬 `arche-ingest`** — 외부 소스(Confluence/Jira/URL)나 로컬 파일을 사람 검토 게이트(plan/content → preview → resolve → commit)로 적재한다.
- **스킬 `arche-query`** — 질문을 그래프 프리미티브로 접근해 그래프 근거로만 답한다.

## 전제조건

이 플러그인은 Arche MCP 서버를 **연결만** 한다. 서버 실행 파일(`arche` CLI)은 따로 설치한다.

```bash
# apps/api 를 설치해 `arche` 가 PATH 에 있게 한다 (예: uv tool install 또는 pip)
uv tool install /path/to/arche/apps/api    # 또는: pip install /path/to/arche/apps/api
arche version                              # 설치 확인
```

임베딩용 키를 넣는다(추출은 구독 인증이라 키 불필요):

```bash
arche config set-key           # 임베딩 전용, 소액. ~/.config/arche/config.env 에 저장
```

## 설치

```
/plugin marketplace add Jungho-Cheon/arche
/plugin install arche@arche
```

설치하면 두 스킬(`/arche-ingest`, `/arche-query`)이 생기고, Claude 가 맥락에 따라 자동으로도 부른다. Arche MCP 도구(적재/조회)도 함께 붙는다.

## 쓰는 법

- **적재** — "이 Confluence 페이지를 Arche 에 넣어줘" 처럼 시키면 `arche-ingest` 가 흐름을 잡는다. 에이전트가 Atlassian MCP 로 페이지를 읽고 `ingest_content` 로 계획 → 미리보기를 보여주고 → 네 확인 후 커밋.
- **질의** — "환불 규정이 어떻게 적용돼?" 처럼 물으면 `arche-query` 가 `find_entities` 로 진입점을 잡고 순회해 그래프 근거로 답한다.

## 설정 바꾸기

`.mcp.json` 의 `env` 로 provider/백엔드를 바꾼다. 예: 전부 OpenAI 로 하려면 `ARCHE_API_LLM_MODEL=openai/gpt-4.1-mini`, 프로덕션 Neo4j 는 `ARCHE_API_GRAPH_BACKEND=neo4j` + Neo4j 접속 변수. 자세한 변수는 Arche 문서의 환경 변수 레퍼런스 참조.
