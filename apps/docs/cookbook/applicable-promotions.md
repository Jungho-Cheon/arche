# 상품에 적용 가능한 프로모션 찾기

"이 상품에 지금 걸 수 있는 프로모션이 뭐지?" 는 상품 문서 하나로는 답이 안 나오는 질문입니다. 프로모션은 별도 문서에 있고, 어떤 상품군에 걸리는지는 그 사이 관계에 있습니다. Arche 에서는 상품 노드를 출발점으로 잡고 이웃으로 걸린 프로모션을 펼쳐 답합니다.

도구 두 개를 엮습니다. `find_entities` 로 상품 노드의 ID 를 얻고, `get_neighbors` 로 그 노드에 붙은 프로모션 관계를 펼칩니다. 아래는 MCP 도구 호출 기준이고, 응답에는 REST 의 `{"data": ...}` 봉투가 없습니다.

## 1. 상품 노드 찾기

상품 이름을 키워드로 `find_entities` 를 부릅니다.

```json
{ "keywords": ["여름 원피스"], "limit": 5 }
```

```json
{
  "matches": [
    {
      "node": { "id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "name": "여름 원피스", "type": "Product" },
      "score": 1.0,
      "matched_keyword": "여름 원피스"
    }
  ]
}
```

`matches[0].node.id` 에서 상품 노드의 ULID 를 꺼냅니다. 결과가 비어 있으면 키워드가 그래프의 표현과 어긋난 것이니, 낱말을 바꾸거나 `get_schema` 로 실제 상품 타입 이름을 보고 다시 잡습니다.

## 2. 걸린 프로모션 펼치기

그 ID 를 `get_neighbors` 에 진입점으로 넣어 한 단계 이웃을 펼칩니다. 프로모션이 상품을 향하는 방향이라면 들어오는 관계이므로 `direction` 을 `incoming` 으로, 방향을 모르면 `both` 로 둡니다.

```json
{ "id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "hops": 1, "direction": "both", "max_nodes": 50 }
```

```json
{
  "nodes": [
    { "id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "name": "여름 원피스", "type": "Product" },
    { "id": "01J8Z0PRMTN7A9B3C4D5E6F7GH", "name": "여름 시즌 15% 할인", "type": "Promotion" }
  ],
  "edges": [
    { "from": "01J8Z0PRMTN7A9B3C4D5E6F7GH", "to": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "type": "APPLIES_TO" }
  ],
  "truncated": false
}
```

`edges` 에서 `APPLIES_TO` 관계가 상품 노드(`to`)를 향하는 프로모션 노드(`from`)를 짚으면, 그게 이 상품에 걸린 프로모션입니다. `nodes` 에서 그 `from` ID 에 해당하는 노드를 찾아 이름과 타입을 읽습니다.

`truncated` 가 `true` 면 `max_nodes` 에 걸려 일부가 잘렸다는 뜻이니, 상한을 올리거나 `relation_types` 에 `["APPLIES_TO"]` 처럼 관계 타입을 좁혀 프로모션 관계만 다시 펼칩니다.

## 걸리는 조건까지 확인하려면

프로모션이 상품에 걸리는지뿐 아니라 그 조건(기간, 최소 금액 같은)까지 알고 싶다면, 프로모션 노드를 다시 `get_neighbors` 로 한 단계 더 펼칩니다. 프로모션에서 나가는 관계를 따라가면 조건 노드가 드러납니다. 한 상품과 한 프로모션이 정말 이어지는지 경로로 못박아 확인하려면 [두 개념이 어떻게 이어지는지 밝히기](/cookbook/connect-two-concepts)의 `find_path` 흐름을 씁니다.

## 다음으로

- [그래프에 질의하기](/guide/query) — 여섯 조회 연산을 실제 호출과 응답으로.
- [그래프 조회 연산](/reference/primitives) — `get_neighbors` 가 받는 입력과 응답 필드 참조표.
