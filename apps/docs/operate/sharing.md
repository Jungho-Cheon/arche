# 팀과 그래프 공유하기

혼자 쓰던 임베디드 그래프에서 여러 사람이 같이 보는 서버 배치로 옮기는 방법이에요. Neo4j 와 Arche API 서버를 띄우고, 에이전트가 네트워크 너머로 붙게 바꿔요.

왜 두 배치가 있고 무엇이 달라지는지는 [저장소 배치](/operate/storage)에서 다뤄요.

::: warning 기존 그래프는 따라오지 않아요
저장소를 바꾸면 다른 저장소를 보게 될 뿐, Kuzu 폴더에 쌓아 둔 내용은 Neo4j 로 옮겨지지 않아요. 옮긴 뒤 문서를 다시 적재해야 해요.
:::

## 1. Neo4j 와 API 서버 띄우기

저장소에 `docker compose` 설정이 들어 있어 둘을 한 번에 올려요. 먼저 `.env` 에 키와 비밀번호를 채워요.

```bash
# .env
OPENAI_API_KEY=sk-...
NEO4J_PASSWORD=강한-비밀번호로-바꾸세요
```

띄워요.

```bash
docker compose up -d
```

처음에는 이미지를 빌드하느라 몇 분 걸려요. 세 포트가 열려요.

| 포트 | 무엇 | 확인 |
| --- | --- | --- |
| `8000` | Arche API 서버 | `http://localhost:8000/docs` |
| `7474` | Neo4j 브라우저 | `http://localhost:7474` |
| `7687` | Neo4j bolt | CLI 와 stdio MCP 가 접속하는 포트 |

`docker compose` 설정은 API 서버의 저장소를 Neo4j 로 지정해 둬요. 컨테이너로 띄우면 이 값을 따로 만질 필요가 없어요.

## 2. 살아 있는지 확인

```bash
curl http://localhost:8000/healthz
```

```json
{ "status": "ok", "graph": "ok" }
```

`graph` 가 `"down"` 이면 Neo4j 가 아직 부팅 중일 수 있어요. 몇 초 뒤 다시 부르세요. 계속 `"down"` 이면 컨테이너 상태를 봐요.

```bash
docker compose ps
docker compose logs arche-neo4j
```

## 3. 내 컴퓨터의 CLI 도 Neo4j 를 보게 하기

컨테이너 밖에서 `arche` 명령을 쓴다면 그쪽도 저장소를 바꿔요. `.env` 에 두 줄을 더해요.

```bash
ARCHE_API_GRAPH_BACKEND=neo4j
NEO4J_URI=bolt://localhost:7687
```

`NEO4J_USER` 는 기본값 `neo4j` 를 그대로 쓰고, `NEO4J_PASSWORD` 는 위에서 정한 값과 같아야 해요.

이제 CLI 적재가 Neo4j 로 들어가요.

```bash
arche ingest ./내문서폴더
```

## 4. 에이전트를 원격으로 연결하기

같은 기계에서 쓴다면 지금까지처럼 stdio 로 연결해도 돼요. 저장소만 Neo4j 를 보면 되니까요.

팀원이 각자의 컴퓨터에서 연결하려면 HTTP 전송을 써요. API 서버가 `/mcp/v1` 에 이미 마운트하고 있어 따로 띄울 게 없어요.

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

stdio 와 HTTP 는 **같은 도구 15개**를 같은 이름과 같은 스키마로 노출해요. 에이전트 쪽에서 바뀌는 건 접속 설정뿐이에요. 전송 방식 선택은 [에이전트와 연결하기](/integrate/agent)에서 더 다뤄요.

## 5. 팀별로 namespace 나누기

한 Neo4j 안에서 팀이나 프로젝트별로 지식을 나눠 담으려면 `namespace_id` 를 써요. [namespace 로 나눠 담기](/operate/namespace)를 보세요.

## 사내에 두기 전에

::: danger 기본 설정을 그대로 열지 마세요
`docker compose` 기본값은 로컬 개발용이에요. 사내망이나 인터넷에 그대로 노출하면 같은 네트워크의 누구나 그래프를 읽고 쓸 수 있어요.

- `NEO4J_PASSWORD` 기본값 `arche` 를 강한 값으로 바꿔요.
- API 서버는 토큰을 검증하지 않아요. `Authorization: Bearer ns:team-a` 는 어느 namespace 를 볼지 고르는 값이지 로그인이 아니에요. 아무나 보내면 그 namespace 를 읽고 써요.
- `/admin/*` 관리 엔드포인트도 열려 있어요.
- 세 포트를 그대로 노출하지 말고 프록시나 사내 인증 뒤에 두세요.
:::

## 데이터는 어디에 남나

그래프는 `neo4j-data` 라는 Docker 볼륨에 쌓여요.

```bash
docker compose down     # 컨테이너만 내림, 데이터는 남음
docker compose down -v  # 볼륨까지 지움, 그래프가 사라짐
```

`-v` 를 붙이면 그래프가 통째로 사라져요. 운영에서 쓴다면 이 볼륨을 백업 대상으로 잡으세요. Neo4j 자체 백업 명령도 이 볼륨을 대상으로 써요.

## 임베디드로 되돌리기

`.env` 에서 백엔드를 되돌리면 돼요.

```bash
ARCHE_API_GRAPH_BACKEND=embedded
```

Neo4j 에 넣은 내용은 임베디드로 따라오지 않아요. 예전 Kuzu 폴더를 지우지 않았다면 그 상태로 돌아가요.

## 다음으로

- 두 배치의 차이는 [저장소 배치](/operate/storage)
- 접속 설정 값은 [환경 변수](/reference/configuration)
- namespace 나누기는 [namespace 로 나눠 담기](/operate/namespace)
