# REST API

Arche API 서버가 받는 HTTP 주소(엔드포인트) 19개를 모은 참조표입니다. 조회 7개와 그래프를 바꾸는 8개는 [조회 도구 참조표](/query/tools), [적재 도구 참조표](/ingest/tools)의 MCP 도구와 같은 스키마를 쓰고, 나머지는 상태 확인과 관리 엔드포인트입니다.

REST 는 에이전트를 쓰지 않고 직접 부를 때의 통로입니다. 에이전트를 연결하는 기본 통로는 MCP 이고, [에이전트와 연결하기](/integrate/agent)에서 다룹니다.

## 최소 예시

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

## 엔드포인트 목록

| 메서드 | 경로 | 하는 일 |
| --- | --- | --- |
| `GET` | `/healthz` | API 와 그래프 백엔드가 살아 있는지 확인 |
| `GET` | `/schema` | 그래프에 어떤 타입의 노드와 관계가 있는지 |
| `POST` | `/entities/find` | 키워드로 출발점 노드 찾기 |
| `GET` | `/entities/{entity_id}` | 노드 하나의 상세와 인접 관계 수 |
| `POST` | `/entities/{entity_id}/neighbors` | N 홉 이웃 펼치기 |
| `POST` | `/paths/find` | 두 노드를 잇는 경로 찾기 |
| `POST` | `/subgraph` | 여러 출발점 주변을 한꺼번에 펼치기 |
| `POST` | `/related/find` | 시드와 구조적으로 가까운 노드 회수 |
| `POST` | `/ingest/plan` | 파일 하나의 적재를 계획만 하기 |
| `POST` | `/ingest/content` | 넘겨받은 텍스트로 계획하기 |
| `POST` | `/ingest/preview` | 계획을 항목 단위로 펼치기 |
| `POST` | `/ingest/resolve` | 미리 보기가 물은 질문에 답하기 |
| `POST` | `/ingest/commit` | 확인한 계획을 그래프에 반영 |
| `POST` | `/entities/split/plan` | 잘못 합친 노드를 가를 계획 세우기 |
| `POST` | `/entities/split/preview` | 갈랐을 때의 두 노드와 관계 행선지 |
| `POST` | `/entities/split/commit` | 확인한 대로 노드 가르기 |
| `POST` | `/admin/ingest` | 폴더를 비동기로 적재 |
| `GET` | `/admin/ingest/{task_id}/status` | 적재 작업 진행 상태 |
| `GET` | `/admin/namespaces` | namespace 별 노드 수 |

모든 경로는 루트와 `/v1` 접두사 양쪽에 올라옵니다. `POST /entities/find` 와 `POST /v1/entities/find` 는 같은 엔드포인트입니다.

OpenAPI 스펙은 `/openapi.json` 에, 눌러 볼 수 있는 화면은 `/docs` 에 있습니다.

## 응답 형식

성공 응답은 payload 를 `data` 로 감쌉니다.

```json
{ "data": { "matches": [] } }
```

실패 응답은 `error` 를 담고 HTTP 상태 코드가 함께 옵니다.

```json
{ "error": { "code": "entity_not_found", "message": "...", "details": {} } }
```

값이 `null` 인 필드는 응답에서 키째 빠집니다. 코드 목록은 [에러 코드](/reference/errors)에 있습니다.

## 인증과 namespace

`Authorization` 헤더는 로그인 수단이 아니라 어느 namespace 를 볼지 고르는 값입니다. 형식은 `Bearer ns:<namespace_id>` 입니다.

```bash
curl -X POST http://localhost:8000/entities/find \
  -H "Authorization: Bearer ns:team-a" \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["환불"]}'
```

우선순위는 인증 헤더, 요청의 `namespace_id`, `default` 순입니다. `GET` 요청은 본문이 없어서 `namespace_id` 를 쿼리 문자열로 받습니다.

헤더가 없으면 401 이 아니라 `default` namespace 로 진행합니다. Bearer 형식이 아니면 `not_authorized` 로 401 입니다.

::: warning API 자체에는 접근 통제가 없습니다
현재 버전은 토큰을 검증하지 않습니다. `Bearer ns:team-a` 를 아무나 보내면 그 namespace 를 읽고 씁니다. `/admin/*` 도 열려 있습니다. 로컬이 아닌 환경에 둔다면 API 앞에 프록시나 사내 인증을 두세요. 자세한 경계는 [namespace 로 나눠 담기](/operate/namespace)에서 다룹니다.
:::

## GET /healthz

```bash
curl http://localhost:8000/healthz
```

```json
{ "status": "ok", "graph": "ok" }
```

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `status` | `string` | API 자신이 응답하는지 |
| `graph` | `string` | 그래프 백엔드와 통하는지 |

이 응답은 `data` 로 감싸지 않습니다. `graph` 가 `"down"` 이면 그래프 백엔드에 닿지 못한 상태입니다. Neo4j 를 갓 띄웠다면 부팅 중일 수 있으니 몇 초 뒤 다시 부릅니다.

## 조회 엔드포인트 7개

요청 필드와 응답 필드는 [조회 도구 참조표](/query/tools)에 있습니다. MCP 도구와 스키마가 같고, REST 만의 차이는 셋입니다.

- 성공 응답을 `{ "data": ... }` 로 한 번 더 감쌉니다.
- `GET /schema` 와 `GET /entities/{entity_id}` 는 `namespace_id` 를 쿼리 문자열로 받습니다.
- `POST /entities/{entity_id}/neighbors` 는 경로의 `entity_id` 를 진입점으로 씁니다. 본문에도 `id` 를 넣으면 값이 같은지 검사합니다.

## 검토형 적재 5개와 떼어내기 3개

요청 필드와 응답 필드는 [적재 도구 참조표](/ingest/tools)에 있습니다. MCP 도구와 스키마가 같고, REST 만의 차이는 셋입니다.

- 성공 응답을 `{ "data": ... }` 로 한 번 더 감쌉니다.
- `namespace_id` 를 본문에 넣지 않으면 `Authorization` 헤더의 namespace 를 씁니다. 조회 엔드포인트와 같은 우선순위입니다.
- `POST /ingest/plan` 의 `path` 는 **API 서버가 보는 경로**입니다. 서버가 읽을 수 없는 자리의 문서라면 본문을 직접 넘기는 `POST /ingest/content` 를 쓰는 편이 확실합니다.

::: warning 계획은 서버 프로세스 안에만 삽니다
계획을 세운 요청과 확정하는 요청이 **같은 프로세스에 닿아야** 합니다. 워커를 여럿 띄우면 계획을 못 찾는 요청이 생기므로, 지금 버전은 단일 프로세스 배치를 전제로 합니다.

서버를 재시작하면 진행 중이던 계획이 사라집니다. 확인 없이 방치된 계획도 기본 3600초가 지나면 버려집니다(`ARCHE_API_PLAN_TTL_SECONDS`). 미리 보기나 `resolve` 로 계획을 건드리면 이 시계는 다시 시작하므로, 사람이 검토하는 동안 만료되지는 않습니다.

사라진 계획으로 부르면 `invalid_input` 이고 `details.plan_ttl_seconds` 에 수명이 실려 옵니다. 그때는 계획부터 다시 세웁니다.
:::

미리 보기를 거치지 않은 `POST /ingest/commit` 과 `POST /entities/split/commit` 은 `unprocessable` 로 거부됩니다. MCP 에만 있던 안전 장치가 REST 에서도 똑같이 걸립니다.

## POST /admin/ingest

폴더를 재귀로 훑어 적재합니다. 검증만 동기로 하고 실제 적재는 뒤에서 도는 작업으로 띄운 뒤 `202` 와 작업 번호를 바로 돌려줍니다.

<!-- @include: ./_generated/requests/admin-ingest.md -->

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `task_id` | `string` | 진행 상태를 물을 때 쓰는 작업 번호 |
| `status_url` | `string` | 상태 조회 경로 |

`directory_path` 는 **API 서버가 보는 경로**입니다. 서버를 컨테이너로 띄웠다면 호스트 경로가 아니라 컨테이너 안에서 보이는 경로를 넣어야 합니다. 없는 경로를 주면 `directory_not_found` 로 422 이고, `details.hint` 에 원인을 함께 돌려줍니다.

검토 단계가 없어서 이 경로는 사람 확인 없이 바로 그래프에 씁니다. 확인 뒤 확정하고 싶다면 `POST /ingest/plan` 부터 시작하는 검토형 적재를 씁니다. 대신 그쪽은 파일 하나씩만 다룹니다.

## GET /admin/ingest/{task_id}/status

```json
{
  "data": {
    "task_id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE",
    "state": "running",
    "progress": {
      "files_total": 12,
      "files_processed": 5,
      "files_skipped": 1,
      "files_pending_skipped": 0,
      "files_unsupported_skipped": 3
    },
    "metrics": {
      "entities_created": 41,
      "entities_updated": 6,
      "relations_created": 33,
      "relations_skipped_dangling": 2,
      "chunks_total": 9
    }
  }
}
```

`state` 는 `running`, `succeeded`, `failed` 중 하나입니다. 실패하면 `error` 에 `code` 와 `message` 가 담깁니다.

| `progress` 필드 | 뜻 |
| --- | --- |
| `files_total` | 훑어서 모은 지원 파일 수 |
| `files_processed` | 적재를 마친 파일 수 |
| `files_skipped` | 내용과 추출기 버전이 같아 다시 뽑지 않고 건너뛴 파일 수 |
| `files_pending_skipped` | 지원 예정 형식으로 걸러진 파일 수. 지금은 항상 0 |
| `files_unsupported_skipped` | 받지 않는 확장자라 걸러진 파일 수. 예를 들어 `.json`, `.py`, `.csv` |

같은 폴더를 내용 변경 없이 다시 넣으면 `files_processed` 가 0 이고 `files_skipped` 가 올라갑니다. 정상 동작입니다.

없는 `task_id` 를 물으면 `task_not_found` 로 404 입니다. 작업 기록은 서버 프로세스 안에만 있어서 서버를 재시작하면 사라집니다.

## GET /admin/namespaces

```json
{ "data": { "namespaces": [ { "namespace_id": "default", "entity_count": 128 } ] } }
```

노드 수 내림차순으로 옵니다.

## 같이 보기

- [REST 로 직접 부르기](/integrate/rest) — 코드에서 부르는 법
- [조회 도구 참조표](/query/tools) — 요청과 응답 필드 전체
- [환경 변수](/reference/configuration) — 서버 설정
