# namespace 로 나눠 담기

한 저장소 안에서 지식을 여러 갈래로 갈라 담는 방법이에요. 팀별로, 프로젝트별로, 또는 실험용과 실제용으로 나눌 때 써요. 각 갈래를 namespace 라고 부르고, 그 이름이 `namespace_id` 예요.

::: warning 격리는 되지만 접근 통제는 아니에요
다른 namespace 의 데이터는 검색과 조회에 안 나와요. 그렇지만 누가 어느 namespace 를 볼지 막지는 않아요. 아무나 원하는 이름을 보내면 그 namespace 를 읽고 써요. 아래 "무엇을 막고 무엇을 못 막나"를 꼭 읽으세요.
:::

## 이름 규칙

글자와 숫자, 그리고 `.` `_` `:` `-` 만 써요. 최대 128자예요. 미지정이면 `default` 예요.

```text
team-a
project.arche
customer:acme
```

규칙에 어긋나면 `invalid_input` 으로 거부해요.

```text
namespace_id may contain only letters, digits, and . _ : -
```

## namespace 를 지정하는 법

**에이전트로 쓸 때**는 도구 인자로 넘겨요. MCP 호출에는 HTTP 헤더가 없어서 조회 도구 7개와 적재 도구 5개 모두 `namespace_id` 를 인자로 받아요.

```json
{ "keywords": ["환불"], "namespace_id": "team-a" }
```

MCP 클라이언트 설정에 헤더로 고정해 두는 방법도 있어요. HTTP 전송을 쓸 때만 돼요.

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

**REST 로 쓸 때**는 인증 헤더가 우선이에요.

```bash
curl -X POST http://localhost:8000/entities/find \
  -H "Authorization: Bearer ns:team-a" \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["환불"]}'
```

헤더 없이 본문에 넣어도 돼요.

```bash
curl -X POST http://localhost:8000/entities/find \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["환불"], "namespace_id": "team-a"}'
```

`GET` 요청은 본문이 없어서 쿼리 문자열로 받아요.

```bash
curl "http://localhost:8000/schema?namespace_id=team-a"
```

우선순위는 인증 헤더, 요청의 `namespace_id`, `default` 순이에요.

## 무엇이 namespace 안에서만 도나

**읽기.** 조회 도구 7개 전부가 지정한 namespace 안에서만 돌아요. 다른 namespace 의 노드는 검색에 안 걸리고, 이웃을 펼쳐도 안 나오고, 경로도 그 안에서만 이어져요. 다른 namespace 의 노드 ID 를 직접 넣어도 `entity_not_found` 예요.

**쓰기.** 적재한 노드와 관계는 지정한 namespace 에 들어가요.

**같은 대상 합치기.** 같은 회사가 여러 문서에 나올 때 하나로 모으는 판단도 같은 namespace 안에서만 해요. 그래서 team-a 의 "아크미"와 team-b 의 "아크미"는 서로 섞이지 않아요.

## 어떤 namespace 에 뭐가 있는지 보기

```bash
curl http://localhost:8000/admin/namespaces
```

```json
{ "data": { "namespaces": [ { "namespace_id": "default", "entity_count": 128 } ] } }
```

노드 수 내림차순으로 와요. 오타로 만들어진 namespace 를 찾을 때 유용해요.

## 자주 걸리는 자리

**적재는 team-a 에 했는데 조회가 비어 있어요.** 조회 쪽 이름이 다를 가능성이 커요. `/admin/namespaces` 로 실제 이름을 확인하세요. 오타로 적은 이름도 그대로 새 namespace 가 돼요. 미리 등록하는 절차가 없어서예요.

**여러 namespace 를 한 번에 보고 싶어요.** 지금은 안 돼요. 한 호출은 하나만 봐요. 여러 namespace 에 걸친 질의는 아직 없어요.

**다른 namespace 로 옮기고 싶어요.** 옮기는 연산은 없어요. 원하는 namespace 로 다시 적재하세요.

**namespace 를 지우고 싶어요.** namespace 단위로 지우는 연산도 없어요. 저장소를 통째로 비우는 것만 돼요.

## 무엇을 막고 무엇을 못 막나

막는 것은 **섞임**이에요. team-a 의 문서가 team-b 의 검색 결과에 끼어들지 않고, 같은 이름의 대상이 서로 합쳐지지 않아요.

못 막는 것은 **접근**이에요. `Authorization: Bearer ns:team-a` 는 로그인이 아니라 어느 namespace 를 볼지 고르는 값이고, 서버는 토큰을 검증하지 않아요. team-b 사람이 `ns:team-a` 를 보내면 team-a 를 읽고 써요. `/admin/*` 도 열려 있어요.

그래서 사람마다 볼 수 있는 범위를 갈라야 한다면 **Arche 앞단에서 처리해야 해요.** 프록시나 사내 인증이 사용자를 확인하고, 그 사용자에게 허용된 namespace 이름으로 `Authorization` 헤더를 다시 써서 Arche 로 넘기는 방식이에요. 이때 클라이언트가 보낸 본문의 `namespace_id` 도 함께 검사해야 헤더 우회를 막아요.

## 다음으로

- 서버 배치로 옮기려면 [팀과 그래프 공유하기](/operate/sharing)
- 도구별 필드는 [조회 도구 참조표](/query/tools)
- 주소와 헤더는 [REST API](/reference/rest-api)
