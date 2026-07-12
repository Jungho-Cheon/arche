# 팀별 지식 격리 (namespace)

한 그래프 DB 를 여러 팀이 같이 쓰다 보면, A 팀 문서에서 뽑은 노드가 B 팀 검색에 섞여 나오는 일이 생깁니다. namespace(여러 팀의 지식을 한 그래프에 두면서 팀끼리 섞이지 않게 갈라 두는 칸막이)는 이 문제를 풀려고 둔 논리적 칸입니다. 그래프 DB 는 하나만 띄워 두고, 적재한 데이터와 질의를 각자의 칸 안으로 가둬 서로 새어 나가지 않게 합니다.

호출 주소는 모두 로컬에서 띄운 API(`http://localhost:8000`) 기준입니다.

::: warning namespace 는 접근 통제가 아닙니다
namespace 는 데이터를 칸으로 갈라 **섞이지 않게** 하는 장치이지, 팀 사이 접근을 막는 보안 경계가 아닙니다. 현재 API 에는 인증이 없어서, 호출하는 쪽이 헤더나 본문에 다른 칸 이름을 적으면 그 칸을 그대로 읽고 쓸 수 있습니다. 우발적 혼입은 막지만 의도적이거나 실수로 옆 칸을 지정하는 접근은 못 막습니다. 팀 간 실제 접근 통제가 필요하면 API 앞에 프록시나 사내 인증(SSO)을 두어 그 계층에서 칸을 강제하세요.
:::

## 칸을 정하는 법 — Authorization 헤더

요청이 어느 칸에 속하는지는 `Authorization` 헤더로 정합니다. 값은 `Bearer ns:<이름>` 형식이고, `ns:` 뒤에 붙인 이름이 그대로 namespace 가 됩니다. 예를 들어 `Bearer ns:work-a` 를 실으면 그 요청은 `work-a` 칸에서 처리됩니다.

문서를 적재할 때 헤더를 실으면 거기서 만들어진 노드가 그 칸에 들어갑니다.

```bash
curl -X POST http://localhost:8000/admin/ingest \
  -H "Authorization: Bearer ns:work-a" \
  -H "Content-Type: application/json" \
  -d '{"directory_path": "/docs/work-a"}'
```

질의할 때 같은 헤더를 실으면 그 칸 안에서만 찾습니다.

```bash
curl -X POST http://localhost:8000/entities/find \
  -H "Authorization: Bearer ns:work-a" \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["환불"]}'
```

같은 키워드라도 `work-a` 와 `work-b` 는 서로 다른 결과를 돌려줍니다. 적재가 칸별로 갈려 있으니 검색도 칸별로 갈립니다.

## 어느 칸으로 갈지 정해지는 순서

::: tip 결정 순서
한 요청의 namespace 는 다음 우선순위로 정해집니다.

1. **요청 본문의 `namespace_id`** — 본문을 받는 연산(`find_entities`, `get_neighbors`, `find_path`, `get_subgraph`, 적재)에서 `namespace_id` 를 직접 적으면 그 값이 가장 셉니다. 본문이 없는 `GET /schema` 와 `GET /entities/{id}` 는 대신 `?namespace_id=` 질의 변수(query parameter)로 같은 자리를 채웁니다.
2. **`Bearer ns:` 헤더** — 본문이나 질의 변수에 `namespace_id` 가 없으면 헤더의 칸을 씁니다.
3. **`default`** — 둘 다 없으면 `default` 칸으로 갑니다.

헤더를 아예 안 실으면 그 요청은 전부 `default` 로 갑니다. 칸을 따로 나누지 않은 채로도 그냥 쓸 수 있도록 한 기본값입니다.
:::

본문에 `namespace_id` 를 직접 적는 방식은 헤더로 한 칸에 로그인해 둔 상태에서 한 번만 다른 칸을 들여다보고 싶을 때 편합니다.

## 칸막이가 막는 범위

namespace 는 데이터가 드나드는 길목 전체에 걸립니다.

- **적재** — 문서에서 뽑은 노드와 관계는 요청이 속한 칸에 기록됩니다.
- **같은 대상 합치기** — 새 노드가 기존 노드와 같은 실체인지 따져 합칠 때도 같은 칸 안에서만 비교합니다. 다른 칸의 노드와는 합쳐지지 않습니다.
- **모든 조회 연산** — 키워드 검색, 이웃 펼치기, 경로 찾기, 부분 그래프 모두 그 칸 안으로 범위가 좁혀집니다.

ID 를 직접 찍어 노드를 가져오는 `get_entity` 도 마찬가지입니다. 다른 칸에 있는 노드의 ID 로 조회하면 그 노드가 실제로 있더라도 `404` 를 돌려줍니다. ID 를 이것저것 찍어 보며 옆 칸 데이터를 엿보는 우회로를 막으려는 동작입니다.

## 앞단 인증으로 칸을 강제하기

맨 위 경고에서 짚었듯 namespace 는 우발적 혼입만 막고 접근 통제는 아닙니다. 팀 사이 실제 접근을 막으려면 API 앞에 프록시나 사내 인증(SSO)을 두고 그 계층에서 칸을 강제해야 합니다. 그런데 "프록시 뒤에 두라"만으로는 부족합니다. 두 가지를 반드시 챙겨야 격리가 실제로 성립합니다.

**1. 헤더를 프록시가 직접 써서 넘기세요 (클라이언트가 보낸 값을 믿지 마세요).** `ns:work-a` 토큰은 인증이 아니라 라우팅 힌트입니다. 클라이언트가 보낸 `Authorization` 을 그대로 통과시키면 아무나 `Bearer ns:work-b` 를 실어 옆 칸을 지정할 수 있습니다. 그래서 프록시가 사용자를 인증한 뒤, 그 사용자에게 허용된 namespace 로 `Authorization: Bearer ns:<허용된-namespace>` 를 **서버 측에서 새로 써서** Arche 로 넘겨야 합니다. 클라이언트가 보낸 `Authorization` 은 프록시에서 버리고 덮어씁니다.

**2. 본문의 `namespace_id` 를 막거나 검증하세요.** [어느 칸으로 갈지 정해지는 순서](#어느-칸으로-갈지-정해지는-순서)에서 봤듯, 요청 본문(또는 질의 변수)의 `namespace_id` 가 헤더보다 우선합니다. 그래서 프록시가 헤더를 아무리 단단히 써서 넘겨도, 클라이언트가 본문에 `"namespace_id": "work-b"` 를 넣으면 그 값이 헤더를 이깁니다. 프록시가 요청 본문의 `namespace_id` 를 걷어내거나, 허용된 칸과 일치하는지 검증해야 합니다.

이 둘 중 하나라도 빠지면 프록시를 세워도 격리가 종이호랑이가 됩니다. 참고로 `Bearer` 스킴이면서 `ns:` 접두사가 없는 토큰(예: 사내 SSO 가 발급한 JWT)은 거부되지 않고 조용히 `default` 칸으로 갑니다. 게이트웨이가 그런 토큰을 그대로 흘려보내지 않도록, `ns:<namespace>` 형태로 헤더를 직접 써서 넘기는 위 1번을 지키세요([에이전트에 연결하기](/guide/agent-integration#원격에서-붙기-http-전송)의 인증 안내와 같은 맥락입니다).

## 어떤 칸이 있는지 보기

지금 그래프에 어떤 칸이 있고 각 칸에 노드가 몇 개 들었는지는 `/admin/namespaces` 로 봅니다. 운영 중에 칸 구성을 한눈에 확인하라고 둔 조회용 연산입니다.

```bash
curl http://localhost:8000/admin/namespaces
# {"data":{"namespaces":[{"namespace_id":"work-a","entity_count":128},{"namespace_id":"default","entity_count":12}]}}
```

`namespaces` 는 노드 수가 많은 칸부터 차례로 옵니다. 각 항목의 `namespace_id` 가 칸 이름이고 `entity_count` 가 그 칸에 든 노드 수입니다.

::: warning 아직 안 되는 것 — 칸 일부만 공유
지금 namespace 는 단단한 경계입니다. 한 질의가 여러 칸을 한꺼번에 보거나, 특정 칸 일부만 다른 칸과 공유하는 식은 아직 안 됩니다. 칸을 넘나드는 질의가 필요하면 칸마다 따로 호출해 결과를 직접 합쳐야 합니다. 경계를 이렇게 잡은 까닭과 칸이 데이터 위에서 어떻게 표현되는지는 [namespace 격리 모델](/concepts/namespace-model)에서 다룹니다.
:::

## 다음으로

- [namespace 격리 모델](/concepts/namespace-model) — 경계를 이렇게 잡은 이유와 데이터 표현 방식.
- [환경 변수](/reference/configuration) — namespace 관련 설정을 포함한 API 환경 변수 전체 목록.
