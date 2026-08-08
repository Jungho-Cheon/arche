# namespace 로 나눠 담기

한 저장소 안에서 지식을 여러 칸으로 나눠 담는 방법입니다. 팀별로, 프로젝트별로, 또는 실험용과 실제용으로 가를 때 씁니다. 칸 이름을 `namespace_id` 라고 부릅니다.

::: warning 격리는 되지만 접근 통제는 아닙니다
다른 칸의 데이터는 검색과 조회에 안 나옵니다. 그렇지만 누가 어느 칸을 볼지 막지는 않습니다. 아무나 원하는 칸 이름을 보내면 그 칸을 읽고 씁니다. 이 글 마지막의 "무엇을 막고 무엇을 못 막나"를 꼭 읽으세요.
:::

## 이름 규칙

글자와 숫자, 그리고 `.` `_` `:` `-` 만 씁니다. 최대 128자입니다. 미지정이면 `default` 입니다.

```text
team-a
project.arche
customer:acme
```

규칙에 어긋나면 `invalid_input` 으로 거부합니다.

```text
namespace_id may contain only letters, digits, and . _ : -
```

## 칸을 지정하는 법

**에이전트로 쓸 때**는 도구 인자로 넘깁니다. MCP 호출에는 HTTP 헤더가 없어서 조회 도구 7개와 적재 도구 5개 모두 `namespace_id` 를 인자로 받습니다.

```json
{ "keywords": ["환불"], "namespace_id": "team-a" }
```

MCP 클라이언트 설정에 헤더로 못 박아 두는 방법도 있습니다. HTTP 전송을 쓸 때만 됩니다.

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

**REST 로 쓸 때**는 인증 헤더가 우선입니다.

```bash
curl -X POST http://localhost:8000/entities/find \
  -H "Authorization: Bearer ns:team-a" \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["환불"]}'
```

헤더 없이 본문에 넣어도 됩니다.

```bash
curl -X POST http://localhost:8000/entities/find \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["환불"], "namespace_id": "team-a"}'
```

`GET` 요청은 본문이 없어서 쿼리 문자열로 받습니다.

```bash
curl "http://localhost:8000/schema?namespace_id=team-a"
```

우선순위는 인증 헤더, 요청의 `namespace_id`, `default` 순입니다.

## 무엇이 칸 안에서만 도나

**읽기.** 조회 도구 7개 전부가 그 칸 안에서만 돕니다. 다른 칸의 노드는 검색에 안 걸리고, 이웃을 펼쳐도 안 나오고, 경로도 그 칸 안에서만 이어집니다. 다른 칸의 노드 ID 를 직접 넣어도 `entity_not_found` 입니다.

**쓰기.** 적재한 노드와 관계는 지정한 칸에 들어갑니다.

**같은 대상 합치기.** 같은 회사가 여러 문서에 나올 때 하나로 모으는 판단도 같은 칸 안에서만 합니다. 그래서 team-a 의 "아크미"와 team-b 의 "아크미"는 서로 섞이지 않습니다.

## 어떤 칸에 뭐가 있는지 보기

```bash
curl http://localhost:8000/admin/namespaces
```

```json
{ "data": { "namespaces": [ { "namespace_id": "default", "entity_count": 128 } ] } }
```

노드 수 내림차순으로 옵니다. 오타로 만든 칸을 찾을 때 유용합니다.

## 자주 걸리는 자리

**적재는 team-a 에 했는데 조회가 비어 있습니다.** 조회 쪽 칸 이름이 다를 가능성이 큽니다. `/admin/namespaces` 로 실제 이름을 확인하세요. 오타로 만든 칸도 그냥 만들어집니다. 미리 등록하는 절차가 없어서입니다.

**여러 칸을 한 번에 보고 싶습니다.** 지금은 안 됩니다. 한 호출은 한 칸만 봅니다. 여러 칸에 걸친 질의는 아직 없습니다.

**칸을 옮기고 싶습니다.** 옮기는 연산은 없습니다. 원하는 칸으로 다시 적재하세요.

**칸을 지우고 싶습니다.** 칸 단위로 지우는 연산도 없습니다. 저장소를 통째로 비우는 것만 됩니다.

## 무엇을 막고 무엇을 못 막나

막는 것은 **섞임**입니다. team-a 의 문서가 team-b 의 검색 결과에 끼어들지 않고, 같은 이름의 대상이 서로 합쳐지지 않습니다.

못 막는 것은 **접근**입니다. `Authorization: Bearer ns:team-a` 는 로그인이 아니라 칸을 고르는 값이고, 서버는 토큰을 검증하지 않습니다. team-b 사람이 `ns:team-a` 를 보내면 team-a 를 읽고 씁니다. `/admin/*` 도 열려 있습니다.

그래서 사람마다 볼 수 있는 칸을 갈라야 한다면 **Arche 앞단에서 처리해야 합니다.** 프록시나 사내 인증이 사용자를 확인하고, 그 사용자에게 허용된 칸 이름으로 `Authorization` 헤더를 다시 써서 Arche 로 넘기는 방식입니다. 이때 클라이언트가 보낸 본문의 `namespace_id` 도 함께 검사해야 헤더 우회를 막습니다.

## 다음으로

- 서버 배치로 옮기려면 [팀과 그래프 공유하기](/operate/sharing)
- 도구별 필드는 [조회 도구 참조표](/query/tools)
- 주소와 헤더는 [REST API](/reference/rest-api)
