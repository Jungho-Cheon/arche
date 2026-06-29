# 시작하기

Arche 를 처음 띄워 보고 작은 문서 폴더를 그래프에 넣는 데까지 한 번에 가는 길잡이입니다. 명령은 위에서 아래로 그대로 따라 하면 됩니다.

::: tip 준비물
- **Docker** — 그래프 DB(Neo4j) 와 API 를 컨테이너로 한 번에 띄웁니다.
- **AI 모델 API 키 하나** — 기본 설정은 OpenAI 키(`OPENAI_API_KEY`) 하나로 추출과 임베딩을 모두 처리합니다. 추출은 문서에서 점과 선을 뽑는 작업이고, 임베딩은 검색의 출발점을 찾기 위해 글을 숫자 벡터로 바꾸는 작업입니다.

OpenAI 말고 Claude(Anthropic) 와 Voyage 조합으로도 돌릴 수 있습니다. 모델 이름 접두사만 바꾸면 되고, 자세한 방법은 [모델 갈아끼우기](/guide/models)에 있습니다. 처음에는 파일 몇 개짜리 작은 폴더로 시작하길 권합니다.
:::

## 1단계 — 내려받고 키 채우기

저장소를 받은 뒤 환경 변수 파일을 만들고 OpenAI 키를 채웁니다.

```bash
git clone https://github.com/Jungho-Cheon/arche.git
cd arche
cp .env.example .env
```

`.env` 를 열어 `OPENAI_API_KEY` 에 본인 키를 넣습니다. 기본 설정에서는 이 값이 있어야 추출과 임베딩이 작동합니다.

## 2단계 — 한 번에 띄우기

그래프 DB 와 API 를 함께 올립니다.

```bash
docker compose up -d
```

처음 실행할 때는 이미지를 빌드하느라 몇 분 걸립니다. 다 뜨면 두 곳을 열어봅니다.

- **API 문서(Swagger)** — `http://localhost:8000/docs`. 코드를 짜지 않고 버튼만 눌러 API 를 호출해 봅니다.
- **Neo4j 브라우저** — `http://localhost:7474`. 그래프를 눈으로 봅니다. 아이디는 `neo4j`, 비밀번호는 `.env` 의 `NEO4J_PASSWORD` 값입니다(기본값 `arche`).

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

작은 문서 폴더 하나를 그래프에 넣어 봅니다. `./내문서폴더` 를 실제 폴더 경로로 바꿔 주세요.

```bash
uv run --project apps/api arche ingest ./내문서폴더
```

폴더 안의 글과 PDF, 이미지를 읽어 점(엔티티) 과 선(관계) 을 뽑아 그래프에 저장합니다. 같은 폴더를 다시 넣으면 바뀐 부분만 갱신합니다.

## 다음으로

여기까지 왔다면 그래프가 채워졌습니다. 이제 깊이 들어갈 차례입니다.

- [문서를 그래프에 넣기](/guide/ingest) — 적재를 더 다루는 법, 미리 보고 확정하는 흐름, 추출이 빈약할 때 보강하는 법.
- [그래프에 질의하기](/guide/query) — 6가지 그래프 기본 조회로 답에 필요한 연결을 따라가는 법.
- [팀별 지식 격리 (namespace)](/guide/namespace) — 한 그래프 DB 안에서 팀이나 프로젝트별로 지식을 나눠 담는 법.
