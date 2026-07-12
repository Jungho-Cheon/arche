# 시작하기

::: tip 이 페이지는 누구를 위한 것인가
여기서는 Docker 와 명령줄로 Arche 를 직접 설치하고 실행합니다. 개발자 대상 안내입니다. Arche 가 무엇인지 먼저 파악하고 싶다면 [Arche 소개](/intro)와 [왜 그래프인가](/concepts/why-graph)를 읽어 보세요.
:::

Arche 를 처음 띄워 보고 작은 문서 폴더를 그래프에 넣는 데까지 한 번에 가는 길잡이입니다. 명령은 위에서 아래로 그대로 따라 하면 됩니다.

::: tip 준비물
- **Docker** — 그래프 DB(Neo4j) 와 API 서버를 컨테이너로 한 번에 띄웁니다. [Docker Desktop](https://www.docker.com/products/docker-desktop/) 을 설치하세요. 아래 2단계는 `docker compose`(띄어쓰기, v2 문법)를 쓰므로, 터미널에서 `docker compose version` 을 쳤을 때 버전이 나오는지 먼저 확인하세요(구형 `docker-compose` v1 만 있으면 2단계가 막힙니다).
- **uv** — 파이썬 패키지/실행 도구입니다. 4단계의 `uv run ...` 명령을 내 머신에서 바로 실행할 때 씁니다. 설치는 [https://docs.astral.sh/uv/](https://docs.astral.sh/uv/) 를 참고하세요.
- **AI 모델 API 키 하나** — 기본 설정은 OpenAI 키(`OPENAI_API_KEY`) 하나로 추출과 임베딩을 모두 처리합니다. OpenAI 키는 [platform.openai.com](https://platform.openai.com/api-keys) 에서 발급받습니다. 키를 만들어도 결제 수단을 등록해 사용 크레딧이 있어야 API 가 실제로 응답합니다(크레딧이 없으면 4단계 적재가 `insufficient_quota` 로 막힙니다). 추출은 문서에서 점과 선을 뽑는 작업이고, 임베딩은 검색의 출발점을 찾기 위해 글을 숫자 벡터로 바꾸는 작업입니다.

OpenAI 말고 Claude(Anthropic) 와 Voyage 조합으로도 돌릴 수 있습니다. 모델 이름 접두사만 바꾸면 되고, 자세한 방법은 [모델 갈아끼우기](/guide/models)에 있습니다. 처음에는 파일 몇 개짜리 작은 폴더로 시작하길 권합니다.
:::

## 1단계 — 내려받고 키 채우기

저장소를 받은 뒤 환경 변수 파일을 만들고 OpenAI 키를 채웁니다.

```bash
git clone https://github.com/Jungho-Cheon/arche.git
cd arche
cp .env.example .env
```

저장소는 공개라 별도 권한 없이 clone 됩니다. 잘 받아지면 `arche` 폴더가 생기고, 그 안에 `apps/`, `docker-compose.yml`, `.env.example` 이 있습니다. `cd arche` 로 그 폴더에 들어간 상태에서 이후 단계를 이어 갑니다. `.env.example` 은 저장소에 함께 들어 있는 견본 파일입니다. 위 명령은 그걸 복사해 내 `.env` 를 만듭니다.

`.env` 를 열어 `OPENAI_API_KEY` 에 본인 키를 넣습니다. 기본 설정에서는 이 값이 있어야 추출과 임베딩이 작동합니다. `.env` 는 비밀값이 든 파일이니 형상관리(git)에 올리지 마세요(`.gitignore` 에 이미 들어 있습니다).

::: warning 적재하는 문서 내용이 외부 AI 업체로 전송됩니다
문서를 넣을 때 Arche 는 그 **문서 내용을 설정한 AI 공급자(OpenAI, Anthropic, Voyage)로 보내** 점과 선을 뽑고 임베딩을 만듭니다. 즉 적재하는 문서 전문이 사내 경계를 넘어 제3자 API 로 나갑니다. 정책, 계약서, 인사 규정처럼 밖으로 내보내면 안 되는 문서라면, 반출해도 되는 문서만 넣거나 사내에서 돌리는 로컬 모델로 바꾸는 방법을 검토하세요. `claude-code/*` 추출은 API 키 없이 로컬 인증을 쓰지만, 이 경우에도 내용은 Anthropic 으로 전송됩니다.
:::

## 2단계 — 한 번에 띄우기

1단계에서 clone 한 `arche` 폴더 안에서 실행합니다. 저장소에 포함된 `docker-compose.yml` 이 Neo4j 와 API 서버를 함께 정의하고 있어, 아래 명령 하나로 둘 다 올라옵니다.

```bash
docker compose up -d
```

처음 실행할 때는 이미지를 빌드하느라 몇 분 걸립니다. 다 뜨면 세 포트가 열립니다.

| 포트 | 무엇 | 열어 보기 |
| --- | --- | --- |
| `8000` | API 서버(REST + HTTP MCP) | `http://localhost:8000/docs` — 코드 없이 버튼으로 API 를 눌러 봅니다 |
| `7474` | Neo4j 브라우저 | `http://localhost:7474` — 그래프를 눈으로 봅니다. 아이디 `neo4j`, 비밀번호는 `.env` 의 `NEO4J_PASSWORD`(기본값 `arche`) |
| `7687` | Neo4j bolt | CLI 와 stdio MCP 가 그래프에 직접 붙을 때 쓰는 포트입니다 |

기본 이미지는 Neo4j 5.15 커뮤니티 판입니다. Arche 는 Neo4j 의 벡터 인덱스를 쓰므로, 사내 Neo4j 로 대체하려면 벡터 인덱스를 지원하는 5.11 이상이어야 합니다.

::: warning 이 포트들을 외부에 열지 마세요
기본 설정은 로컬 개발용입니다. `NEO4J_PASSWORD` 기본값 `arche` 는 약하고, API(8000)에는 인증이 없습니다. 운영에서 쓴다면 비밀번호를 강한 값으로 바꾸고, 이 세 포트를 인터넷이나 사내망에 그대로 노출하지 마세요(같은 네트워크의 누구나 그래프를 읽고 쓸 수 있습니다). 노출이 필요하면 프록시나 사내 인증 뒤에 두세요.
:::

::: warning 데이터는 어디에 남나
그래프는 `neo4j-data` 라는 Docker 볼륨에 쌓입니다. `docker compose down` 만 하면 볼륨은 남아 데이터가 보존되지만, `docker compose down -v` 는 볼륨까지 지워 그래프가 통째로 사라집니다. 운영에서 쓴다면 이 볼륨을 백업 대상으로 잡으세요. Neo4j 자체 백업 명령(`neo4j-admin database dump`)도 이 볼륨을 대상으로 씁니다.
:::

## 3단계 — 살아 있는지 확인

API 가 떴고 그래프 DB 와도 연결됐는지 확인합니다.

```bash
curl http://localhost:8000/healthz
# {"status":"ok","neo4j":"ok"}
```

`status` 는 API 자신이 응답하는지, `neo4j` 는 그래프 DB 와 통하는지를 나타냅니다. 둘 다 `ok` 면 준비가 끝난 겁니다.

::: tip neo4j 가 "down" 으로 보일 때
방금 `docker compose up -d` 를 했다면 그래프 DB 가 아직 부팅 중이라 `neo4j` 값이 잠깐 `"down"` 으로 나올 수 있습니다. 몇 초 뒤 다시 호출하면 `"ok"` 로 바뀝니다.
:::

## 4단계 — 첫 적재

작은 문서 폴더 하나를 그래프에 넣어 봅니다. `./내문서폴더` 를 실제 폴더 경로로 바꿔 주세요. 상대 경로는 지금 셸이 있는 위치를 기준으로 풀리니, 헷갈리면 절대 경로로 적는 편이 안전합니다.

```bash
uv run --project apps/api arche ingest ./내문서폴더
```

기본 OpenAI 경로는 `uv sync` 같은 별도 설치가 필요 없습니다. `uv run` 이 첫 실행 때 필요한 의존성을 알아서 내려받아 맞추므로, 처음 한 번은 몇 초에서 수십 초 조용히 걸릴 수 있습니다(멈춘 게 아닙니다). Anthropic 이나 Voyage 로 바꿀 때만 SDK 를 한 번 더 설치하는데, 자세한 건 [모델 갈아끼우기](/guide/models)에 있습니다.

이 명령은 **내 머신에서** 실행합니다. 그래프 DB(Neo4j)에 **곧장 붙어** 씁니다. API 서버(`localhost:8000`)를 거치지 않습니다. 그래서 이 명령이 돌려면 2단계에서 띄운 Neo4j 가 살아 있어야 하고, `.env` 의 키가 채워져 있어야 합니다(추출과 임베딩에 쓰기 때문입니다). API 서버가 떠 있을 필요는 없습니다.

::: tip 무엇이 무엇에 붙나
적재하는 길이 세 갈래인데 붙는 대상이 다릅니다.

- **`arche ingest`(CLI)** 와 **`arche mcp serve`(에이전트용 stdio)** — 그래프 DB(Neo4j)에 **직접** 붙습니다. Neo4j 만 떠 있으면 되고 API 서버는 필요 없습니다.
- **`POST /admin/ingest`(HTTP)** — API 서버를 거칩니다. 이 길만 API 서버가 떠 있어야 합니다.

`docker compose up` 은 Neo4j 와 API 서버를 함께 띄우므로 어느 길이든 쓸 수 있습니다.
:::

폴더 안의 글과 PDF, 이미지를 읽어 점(엔티티) 과 선(관계) 을 뽑아 그래프에 저장합니다. 같은 폴더를 다시 넣으면 바뀐 부분만 갱신합니다.

잘 되면 파일마다 한 줄씩 찍히고 마지막에 요약이 나옵니다. `12e 9r` 은 그 파일에서 점 12 개와 선 9 개를 뽑았다는 뜻입니다.

```text
[1/3] /docs/pricing.md (2 chunks) ... 12e 9r in 3.4s
[2/3] /docs/policy.pdf ... 7e 5r in 2.1s
[3/3] /docs/diagram.png ... 4e 3r in 1.8s

ingest summary:
  files: 3 processed, 0 skipped (of 3 total)
  graph: +23 entities, +17 relations (chunks: 5)
```

요약의 `processed` 가 1 이상이면 최소한 파일이 그래프에 들어간 것입니다(빈 폴더를 넣으면 `0 processed` 가 찍히니, 그때는 폴더 경로를 다시 확인하세요). 들어간 걸 눈으로 확인하려면 Neo4j 브라우저(`http://localhost:7474`)를 열고 질의창에 `MATCH (n) RETURN n LIMIT 25` 를 넣어 봅니다. 방금 뽑은 점과 선이 보이면 성공입니다. 여기까지 됐다면 이제 [에이전트에 연결하기](/guide/agent-integration)로 넘어가 실제로 질문을 던져 볼 차례입니다.

::: tip 보안 모델
현재 버전의 API 에는 별도 인증이 없습니다. `Authorization: Bearer ns:<이름>` 헤더는 로그인 수단이 아니라 namespace(칸막이) 를 지정하는 라우팅 힌트입니다. 관리 엔드포인트(`/admin/*`) 도 열려 있으니, 로컬 테스트 외의 환경에서 쓸 때는 API 앞에 자체 프록시를 두어 접근을 제한하세요.
:::

## 5단계 — 첫 질의

그래프가 채워졌으니 이제 질문을 던져 볼 차례입니다. 여기서는 API 서버에 조회 하나를 손으로 부릅니다. 이건 에이전트 없이 확인하는 저수준 방법이고, 실제로 쓰는 기본 통로는 에이전트가 MCP 로 붙는 것입니다([에이전트에 연결하기](/guide/agent-integration)).

먼저 방금 넣은 문서에 자주 나올 법한 낱말 하나로 출발점 노드를 찾습니다. 아래 `환불` 자리에 내 문서에 실제로 있는 낱말을 넣으세요.

```bash
curl -X POST http://localhost:8000/entities/find \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["환불"], "limit": 3}'
```

가장 잘 맞는 노드가 점수 순으로 옵니다. 각 `node.id` 가 다른 조회에 넘길 26자리 식별자(ULID)입니다.

```json
{
  "data": {
    "matches": [
      { "node": { "id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "name": "환불 정책", "type": "Policy" }, "score": 1.0, "matched_keyword": "환불" }
    ]
  }
}
```

여기서 받은 `id` 를 그대로 이웃 펼치기에 넣으면, 그 노드가 어떤 점들과 이어져 있는지 한 걸음 볼 수 있습니다. 아래 ID 는 자리만 채운 값이니, 방금 응답에서 받은 내 그래프의 실제 `id` 로 바꿔 부르세요.

```bash
curl -X POST http://localhost:8000/entities/01J8XR4K9ZQ2N7M3VB0W4D6TYE/neighbors \
  -H "Content-Type: application/json" \
  -d '{"hops": 1}'
```

이웃 노드와 그들을 잇는 관계가 함께 옵니다. 여기까지 왔다면 "적재 → 질의 → 답 조각"의 한 바퀴를 손으로 돈 것입니다.

::: tip matches 가 비어 있다면
그 낱말이 그래프의 표현과 어긋난 것입니다. 다른 낱말로 바꾸거나, 먼저 `curl http://localhost:8000/schema` 로 어떤 타입의 점이 들었는지 보고 낱말을 골라 다시 부르세요.
:::

## 다음으로

여기까지 왔다면 첫 질의까지 돌려 봤습니다. 이제 깊이 들어갈 차례입니다.

- [에이전트에 연결하기](/guide/agent-integration) — Arche 를 실제로 쓰는 기본 통로. AI 에이전트가 MCP 로 붙어 하나의 연결로 문서를 넣고 그래프를 질의합니다. 위에서 본 `curl` 호출은 에이전트 없이 손으로 확인하는 저수준 방법입니다.
- [문서를 그래프에 넣기](/guide/ingest) — 적재를 더 다루는 법, 미리 보고 확정하는 흐름, 추출이 빈약할 때 보강하는 법.
- [그래프에 질의하기](/guide/query) — 6가지 그래프 기본 조회로 답에 필요한 연결을 따라가는 법.
- [팀별 지식 격리 (namespace)](/guide/namespace) — 한 그래프 DB 안에서 팀이나 프로젝트별로 지식을 나눠 담는 법.
- 처음 실행에서 문제가 생겼다면 [에러 코드](/reference/errors)와 [환경 변수](/reference/configuration)를 참고하세요.
