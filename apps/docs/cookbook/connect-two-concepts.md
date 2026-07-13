# 두 개념이 어떻게 이어지는지 밝히기

"이 환불 정책이 저 상품군에 정말 닿나, 닿는다면 어떤 관계로 닿나?" 는 두 문서 사이의 연결을 묻는 질문입니다. 두 개념 각각은 찾기 쉬워도, 둘을 잇는 다리는 여러 문서에 흩어져 있습니다. Arche 에서는 두 노드를 찾아 그 사이 경로를 잇고, 경로가 얼마나 믿을 만한지까지 함께 판단합니다.

도구 두 개를 엮습니다. `find_entities` 를 두 번 불러 양 끝 노드의 ID 를 얻고, `find_path` 로 그 사이를 잇습니다. 아래는 MCP 도구 호출 기준이라 응답에 REST 의 `{"data": ...}` 봉투가 없습니다.

## 1. 양 끝 노드 찾기

두 개념을 각각 `find_entities` 로 찾습니다. 먼저 환불 정책 쪽입니다.

```json
{ "keywords": ["환불", "정책"], "limit": 5 }
```

```json
{
  "matches": [
    { "node": { "id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "name": "환불 정책", "type": "Policy" }, "score": 1.0, "matched_keyword": "환불" }
  ]
}
```

같은 식으로 상품군 쪽도 불러 그 ID(`01J8YS5M0AB3P8N4WC1XE7FZGH`)를 얻습니다. 이제 양 끝 노드의 ULID 두 개를 손에 쥡니다.

## 2. 두 점 잇기

두 ID 를 `find_path` 의 `from_id` 와 `to_id` 에 넣습니다.

```json
{ "from_id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "to_id": "01J8YS5M0AB3P8N4WC1XE7FZGH", "max_hops": 4 }
```

```json
{
  "paths": [
    {
      "nodes": [
        { "id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "name": "환불 정책", "type": "Policy" },
        { "id": "01J8YS5M0AB3P8N4WC1XE7FZGH", "name": "의류 카테고리", "type": "Category" }
      ],
      "edges": [
        { "from": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "to": "01J8YS5M0AB3P8N4WC1XE7FZGH", "type": "APPLIES_TO" }
      ],
      "length": 1,
      "hub_score": 0.0
    }
  ]
}
```

`paths` 가 짧은 순으로 옵니다. 각 경로의 `nodes` 와 `edges` 를 순서대로 읽으면 환불 정책이 의류 카테고리에 `APPLIES_TO` 로 한 단계에 닿는다는 걸 그대로 되짚을 수 있습니다. 두 점이 그래프에 있어도 `max_hops` 안에 길이 없으면 `paths` 가 빈 목록으로 올 뿐 오류는 아닙니다.

## 3. 연결을 믿어도 되는지 판단

각 경로에는 `hub_score` 가 함께 옵니다. 두 점이 이어졌다는 사실과 그 연결이 의미 있다는 사실은 다릅니다. 수많은 노드와 얽힌 허브를 다리로 삼은 경로는 "닿긴 닿지만 의미가 약한" 연결일 때가 많고, `hub_score` 는 한 경로가 그런 허브를 얼마나 거쳐 가는지를 한 숫자로 알려 줍니다.

- **0 이면 가장 단단한 연결**입니다. 위 예시처럼 한 단계로 바로 닿았거나, 거쳐 간 중간 노드가 모두 연결이 적은 고유한 점이라는 뜻입니다.
- **값이 낮을수록 더 구체적인 경로**입니다. 경쟁하는 경로가 여럿이면 낮은 쪽을 먼저 근거로 삼습니다.
- **값이 클수록 의심합니다.** 이 경로로만 닿는 결론은 강한 근거로 삼기 전에 더 구체적인 다른 연결이 있는지 한 번 더 확인하는 편이 안전합니다.

`find_path` 는 길이가 같은 경로들 사이에서 `hub_score` 가 낮은 것을 먼저 돌려주니, 앞에 오는 경로일수록 대체로 더 구체적입니다. 점수 계산 방식과 왜 낮은 값이 더 믿을 만한지는 [경로 품질과 hub_score](/concepts/path-quality)에서 다룹니다.

## 다음으로

- [상품에 적용 가능한 프로모션 찾기](/cookbook/applicable-promotions) — 한 노드의 이웃을 펼쳐 목표를 푸는 예시.
- [경로 품질과 hub_score](/concepts/path-quality) — hub_score 를 측정값과 함께 읽는 법.
- [그래프 조회 연산](/reference/primitives) — `find_path` 가 받는 입력과 응답 필드 참조표.
