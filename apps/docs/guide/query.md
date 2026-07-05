# 그래프에 질의하기

문서를 적재해 그래프를 채웠다면, 이제 그 그래프에 물어볼 차례입니다. Arche 는 한 방에 답을 주는 검색창이 아니라, 작은 조회 연산 여섯 개를 묶어 답에 필요한 연결을 직접 따라가는 도구입니다. 연산 하나하나는 단순합니다. 키워드로 시작점을 찾고, 한 점의 이웃을 펼치고, 두 점 사이 경로를 잇는 식입니다. 답을 조립하는 쪽은 호출하는 에이전트고, Arche 는 매번 작은 사실 조각만 돌려줍니다.

이 장은 그 여섯 연산을 실제 호출과 응답으로 하나씩 보여 줍니다. 호출 주소는 모두 로컬에서 띄운 API(`http://localhost:8000`) 기준이고, 예시에 나오는 `01J8XR4K9ZQ2N7M3VB0W4D6TYE` 같은 값은 자리만 채운 가짜 ID 입니다.

## 응답 봉투

먼저 모든 응답이 공통으로 쓰는 겉모양을 짚고 갑니다. 성공이든 실패든 응답은 한 겹 봉투에 담겨 옵니다.

성공하면 결과가 `data` 안에 들어옵니다.

```json
{ "data": { "...": "조회 결과" } }
```

실패하면 `error` 안에 코드와 메시지가 들어옵니다.

```json
{ "error": { "code": "entity_not_found", "message": "entity not found: 01J..." } }
```

그래서 앞으로 나오는 응답 예시는 모두 `{"data": ...}` 로 시작합니다. 에러 코드의 전체 목록과 뜻은 [에러 코드](/reference/errors)에 있습니다.

## 엔티티 ID 얻기

여섯 연산 중 넷(`get_entity`, `get_neighbors`, `find_path`, `get_subgraph`)은 노드를 ID 로 가리킵니다. ID 는 ULID 형식인데, 시간순으로 정렬되는 26자리 식별자(`01J8XR4K9ZQ2N7M3VB0W4D6TYE` 처럼 숫자와 대문자로만 된 26글자)입니다. 사람이 외우라고 만든 값이 아니라서, 처음에는 이 ID 를 어디서 구하나 싶습니다.

답은 `find_entities` 입니다. 알고 있는 건 보통 "환불 정책" 같은 말이지 ID 가 아니므로, 거의 모든 질의는 키워드를 ID 로 바꾸는 데서 출발합니다. `find_entities` 로 후보 노드와 그 ID 를 받고, 그 ID 를 나머지 연산에 넘기는 흐름이 이 장 전체의 뼈대입니다.

## 그래프 모양 보기 — get_schema

처음 보는 그래프라면 어떤 종류의 점과 선이 들어 있는지부터 봅니다. `get_schema` 는 엔티티 타입과 관계 타입을 개수와 함께 돌려줍니다.

```bash
curl http://localhost:8000/schema
# {"data":{"entity_types":[{"type":"Policy","count":12,"examples":[{"id":"01J...","name":"환불 정책"}]}],"relation_types":[{"type":"APPLIES_TO","count":8,"common_pairs":[{"from_type":"Policy","to_type":"Product","count":5}]}],"embedding_info":{"model":"text-embedding-3-small","dimension":1536}}}
```

`entity_types` 와 `relation_types` 로 그래프에 어떤 타입이 얼마나 있는지 한눈에 잡고, `examples` 에 딸려 오는 실제 ID 로 곧장 다음 조회를 이어갈 수 있습니다. `embedding_info` 는 진입점 검색에 쓰인 임베딩 모델과 벡터 차원을 알려 줍니다. 임베딩은 글을 숫자 벡터로 바꿔 의미가 가까운 노드를 찾게 해 주는 표현입니다.

## 키워드로 찾기 — find_entities

`find_entities` 는 키워드 목록을 받아 가장 잘 맞는 노드를 돌려줍니다. 입력 필드는 단어 하나가 아니라 목록인 `keywords`, 그리고 개수 상한인 `limit`(기본 10, 1~50)입니다.

```bash
curl -X POST http://localhost:8000/entities/find \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["환불", "정책"], "limit": 5}'
# {"data":{"matches":[{"node":{"id":"01J8XR4K9ZQ2N7M3VB0W4D6TYE","name":"환불 정책","type":"Policy","aliases":[],"properties":{},"source_refs":[{"source_path":"policies/refund.md"}],"created_at":"2026-06-29T10:00:00Z","updated_at":"2026-06-29T10:00:00Z"},"score":1.0,"matched_keyword":"환불"}]}}
```

응답의 `matches` 는 점수 높은 순으로 정렬돼 있고, 각 항목은 이렇게 읽습니다.

- `node` — 찾은 노드. 여기 들어 있는 `id` 가 다른 연산에 넘길 그 ID 입니다.
- `score` — 0 에서 1 사이로 맞춰진 적합도. 1 에 가까울수록 잘 맞은 결과입니다.
- `matched_keyword` — 그 노드를 가장 세게 끌어올린 입력 키워드.

점수는 두 갈래 검색을 합쳐 냅니다. 키워드마다 글자가 겹치는 노드를 찾는 어휘 검색과 임베딩 벡터로 의미가 가까운 노드를 찾는 의미 검색을 따로 돌린 뒤, 두 결과를 순위 기반으로 합쳐(k=60 은 순위를 합칠 때 쓰는 안정화 상수로, 값이 클수록 상위 순위의 영향이 완만해집니다) 합산 점수를 0~1 로 정규화한 값이 `score` 입니다. 두 갈래를 같이 쓰므로 표기가 조금 달라도(예: "환불" 대 "반품") 의미가 통하면 걸립니다. 다만 임베딩 호출이 실패하면 어휘 검색만으로 슬그머니 답하지 않고 그대로 오류로 끊습니다. 반쪽짜리 결과를 정상처럼 돌려주지 않으려는 선택입니다.

::: tip 원점수가 필요하면 include_scores
요청에 `include_scores: true` 를 넣으면 각 매치에 `scores: {lexical, dense}` 가 함께 옵니다. 어휘(`lexical`)와 의미(`dense`) 각각의 원점수라, 직접 다시 순위를 매기거나 왜 이 노드가 올라왔는지 따져 볼 때 씁니다.
:::

타입을 좁히려면 `types` 에 원하는 타입 목록을 주면 되고, 한 그래프 DB 안에서 팀이나 프로젝트별로 지식을 나눠 담았다면 `namespace_id` 로 그 칸 안에서만 찾게 할 수 있습니다([팀별 지식 격리](/guide/namespace) 참고).

## 노드 하나 들여다보기 — get_entity

ID 를 손에 쥐었으면 `get_entity` 로 그 노드 한 개와, 거기에 붙은 관계가 타입별로 몇 개인지를 봅니다.

```bash
curl http://localhost:8000/entities/01J8XR4K9ZQ2N7M3VB0W4D6TYE
# {"data":{"node":{...},"edge_counts":{"outgoing":{"APPLIES_TO":3},"incoming":{"REFERS_TO":1}}}}
```

`node` 는 `find_entities` 가 돌려준 것과 같은 모양입니다. ID, 이름, 타입, 설명(`description`, 없으면 생략), 별칭(`aliases`), 속성(`properties`), 출처(`source_refs`), 생성과 수정 시각을 담습니다. 응답에 임베딩 벡터는 들어 있지 않습니다. `edge_counts` 는 이 노드에서 나가는 관계(`outgoing`)와 들어오는 관계(`incoming`)를 타입별 개수로 보여 줘서, 다음에 어느 방향으로 이웃을 펼쳐 볼지 가늠하게 해 줍니다.

## 이웃 펼치기 — get_neighbors

한 노드를 진입점으로 잡고 N 단계 안에 닿는 이웃을 펼칩니다. 진입점 노드는 결과에 함께 들어옵니다.

```bash
curl -X POST http://localhost:8000/entities/01J8XR4K9ZQ2N7M3VB0W4D6TYE/neighbors \
  -H "Content-Type: application/json" \
  -d '{"hops": 1, "direction": "both", "max_nodes": 50}'
# {"data":{"nodes":[...],"edges":[...],"truncated":false}}
```

- `hops` — 몇 단계까지 펼칠지(기본 1, 1~5).
- `direction` — 따라갈 방향. `outgoing`(나가는), `incoming`(들어오는), `both`(양쪽) 중 하나이고 기본은 `both`.
- `max_nodes` — 돌려줄 노드 수 상한(기본 100, 1~500).

응답의 `nodes` 와 `edges` 가 펼쳐진 조각 그래프입니다. 각 `edge` 에는 어느 노드에서 어느 노드로 향하는지가 `from` 과 `to` 로 들어 있어, 노드를 다시 이어 붙일 수 있습니다. `truncated` 가 `true` 면 `max_nodes` 에 걸려 일부가 잘렸다는 뜻이니, 상한을 올리거나 `relation_types` 로 관계 타입을 좁혀 다시 부르면 됩니다.

## 두 점 잇기 — find_path

두 노드 ID 사이를 잇는 짧은 경로 몇 개를 찾습니다. "이 정책이 저 상품에 어떻게 닿는가" 같은, 문서 여러 개에 걸친 연결을 물을 때 씁니다.

```bash
curl -X POST http://localhost:8000/paths/find \
  -H "Content-Type: application/json" \
  -d '{"from_id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "to_id": "01J8YS5M0AB3P8N4WC1XE7FZGH", "max_hops": 4}'
# {"data":{"paths":[{"nodes":[...],"edges":[...],"length":2,"hub_score":0.0}]}}
```

`from_id` 에서 `to_id` 까지 `max_hops`(기본 4, 1~6) 안에 닿는 경로를 짧은 순으로 돌려줍니다. 각 경로의 `length` 는 단계 수고, `nodes` 와 `edges` 로 경로를 그대로 되짚을 수 있습니다. 두 점이 그래프에 있어도 제약 안에서 길이 없으면 `paths` 가 빈 목록으로 올 뿐 오류는 아닙니다.

::: tip hub_score 로 경로 의심하기
각 경로에는 `hub_score` 가 함께 옵니다. 값이 0 이면 가장 구체적인 직접 연결이고, 값이 클수록 수많은 노드와 얽힌 허브를 다리로 삼은 경로라 "닿긴 닿지만 의미가 약한" 연결일 수 있습니다. 이 점수를 어떻게 읽고 언제 의심해야 하는지는 [경로 품질과 hub_score](/concepts/path-quality)에서 다룹니다.
:::

## 여러 점에서 한꺼번에 펼치기 — get_subgraph

진입점이 여럿일 때, 각 진입점에서 N 단계씩 펼친 결과를 하나로 합쳐 돌려줍니다. 한 주제를 여러 시작점에서 동시에 훑을 때 유용합니다.

```bash
curl -X POST http://localhost:8000/subgraph \
  -H "Content-Type: application/json" \
  -d '{"entry_ids": ["01J8XR4K9ZQ2N7M3VB0W4D6TYE"], "hops": 2, "max_nodes": 200}'
# {"data":{"nodes":[...],"edges":[...],"entry_ids":["01J8XR4K9ZQ2N7M3VB0W4D6TYE"],"truncated":false}}
```

`entry_ids` 에 진입점 ID 를(최대 20개) 주면 각각에서 `hops`(기본 2, 1~4)만큼 펼친 노드와 `edges`를 합쳐 줍니다. 응답의 `entry_ids` 는 넘긴 진입점을 그대로 되돌려 줘서, 합쳐진 결과 안에서 어디가 출발점이었는지 짚게 해 줍니다. 목록에 그래프에 없는 ID 가 섞여 있으면 오류를 내지 않고 있는 것만 조용히 펼칩니다.

## 여러 단계를 엮어 답 만들기

연산 하나로는 보통 답이 안 나옵니다. 진짜 쓸모는 작은 연산을 엮을 때 나옵니다. "환불 정책이 어떤 상품군에 걸리나" 라는, 정책 문서와 상품 문서에 흩어진 질문을 예로 들어 봅니다.

1. **키워드를 ID 로** — `find_entities` 에 `{"keywords": ["환불", "정책"]}` 을 보내 "환불 정책" 노드를 찾고, 응답 `matches[0].node.id` 에서 그 ID(`01J8XR4K9ZQ2N7M3VB0W4D6TYE`)를 꺼냅니다. 상품군 쪽도 같은 식으로 ID 를 구합니다.
2. **이웃 펼치기** — 그 ID 를 `get_neighbors` 에 진입점으로 넣어 한두 단계 이웃을 펼칩니다. 응답 `edges` 에서 `APPLIES_TO` 같은 관계가 어느 노드로 향하는지를 `from`/`to` 로 읽으면, 정책이 직접 걸린 상품이나 상품군이 드러납니다.
3. **두 점 사이를 확인** — 특정 상품군에 정말 닿는지 확실히 하려면, 1단계에서 구한 두 ID 를 `find_path` 의 `from_id` 와 `to_id` 에 넣어 경로가 실제로 있는지, 몇 단계인지, `hub_score` 가 낮아 믿을 만한 연결인지를 확인합니다.

여기서 짚을 점은 답을 엮는 쪽이 호출하는 에이전트라는 사실입니다. Arche 는 매 호출에 작은 사실 조각(노드 하나, 이웃 한 묶음, 경로 하나)만 돌려주고, 그 조각을 어떤 순서로 어떻게 이어 붙여 결론을 낼지는 호출하는 쪽이 정합니다. 그래서 같은 여섯 연산으로도 질문에 따라 전혀 다른 흐름이 나옵니다.

## 다음으로

각 연산의 입력 필드와 응답 필드를 빠짐없이 정리한 표는 [조회 연산 참조](/reference/primitives)에 있습니다. 노드와 `edges`가 담는 모든 필드, 기본값과 허용 범위를 확인할 때 펼쳐 보세요.
