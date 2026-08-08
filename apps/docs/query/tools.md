# 조회 도구 참조표

Arche 그래프를 읽는 도구 7개의 요청 필드와 응답 필드를 모은 참조표입니다. 같은 7개가 MCP 도구와 REST 엔드포인트 양쪽에 같은 이름과 같은 스키마로 올라옵니다. 질문 모양에 따라 어느 도구를 고를지는 [그래프에 묻기](/query/)에서 다룹니다.

## 최소 예시

거의 모든 흐름은 `find_entities` 로 시작합니다. 사용자가 아는 건 노드 ID 가 아니라 "환불 정책" 같은 말이라, 먼저 키워드를 ID 로 바꿔야 해서입니다.

```json
{ "keywords": ["환불", "정책"], "limit": 5 }
```

```json
{
  "matches": [
    {
      "node": { "id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "name": "환불 정책", "type": "Policy" },
      "score": 1.0,
      "matched_keyword": "환불"
    }
  ]
}
```

`matches[0].node.id` 의 26자리 ULID 가 다른 도구에 넘길 출발점입니다.

## 도구 목록

<!-- @include: ../reference/_generated/tool-catalog-query.md -->

노드를 만들거나 관계를 지우는 쓰기 도구는 MCP 에 노출되지 않습니다. MCP 서버는 기동 직전에 쓰기 도구가 섞였는지 검사하고, 섞여 있으면 등록을 거부합니다.

## 공통 규약

**응답 봉투.** REST 는 성공 결과를 `{ "data": payload }` 로 감싸고, MCP 는 payload 를 그대로 돌려줍니다. 실패는 양쪽 다 `{ "error": { "code", "message", "details" } }` 모양이고, MCP 응답에는 `isError: true` 가 함께 섭니다. 코드 목록은 [에러 코드](/reference/errors)에 있습니다.

**namespace 지정.** MCP 호출에는 HTTP 헤더가 없어서 7개 모두 `namespace_id` 를 도구 인자로 받습니다. REST 는 `Authorization` 헤더를 먼저 보고, 없으면 본문이나 쿼리의 `namespace_id`, 그것도 없으면 `default` 를 씁니다. 자세한 규칙은 [namespace 로 나눠 담기](/operate/namespace)에 있습니다.

**ID 형식.** 모든 노드와 관계 ID 는 26자리 ULID 입니다(`^[0-9A-Z]{26}$`). 형식이 어긋나면 `invalid_input` 으로 거부합니다.

## 도구별 상세

### get_schema

그래프에 어떤 타입의 노드와 관계가 몇 개씩 있는지 돌려줍니다. 요청 필드는 `namespace_id` 하나입니다.

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `entity_types` | `EntityTypeSummary[]` | 타입별 노드 요약 |
| `relation_types` | `RelationTypeSummary[]` | 타입별 관계 요약 |
| `embedding_info` | `EmbeddingInfo` | 그래프를 채운 임베딩 모델과 차원 |

`EntityTypeSummary` 는 `type`, `count`, `examples`(최대 5개, 각각 `id` 와 `name`)를 담습니다. `RelationTypeSummary` 는 `type`, `count`, `common_pairs`(최대 5개, 각각 `from_type`, `to_type`, `count`)를 담습니다. `EmbeddingInfo` 는 `model` 과 `dimension` 을 담습니다.

`embedding_info` 의 `dimension` 이 지금 설정한 임베딩 모델의 차원과 다르면, 그래프를 채울 때와 다른 모델을 쓰고 있다는 뜻입니다. [모델 갈아끼우기](/operate/models)에서 복구 절차를 다룹니다.

<!-- @include: ../reference/_generated/requests/find_entities.md -->

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `matches` | `EntityMatch[]` | 점수 내림차순 |

`EntityMatch` 는 `node`, `score`, `matched_keyword`, `scores` 를 담습니다. `score` 는 어휘 검색과 벡터 검색을 RRF 로 합친 0~1 값이고, `matched_keyword` 는 이 노드를 끌어올린 입력 키워드입니다. `scores` 는 `include_scores` 가 `true` 일 때만 실리며 `lexical` 과 `dense` raw 점수를 담습니다.

`matches` 가 빈 배열이면 에러가 아니라 그 키워드로 걸리는 노드가 없다는 뜻입니다. `get_schema` 로 어떤 타입이 들어 있는지 보고 키워드를 바꿔 다시 부릅니다.

### get_entity

노드 하나의 상세와 타입별 인접 관계 수를 돌려줍니다. 요청 필드는 `id` 와 `namespace_id` 입니다.

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `node` | `Node` | 노드 상세 |
| `edge_counts` | `EdgeCounts` | `outgoing` 과 `incoming` 각각 `{관계타입: 개수}` |

없는 ID 를 주면 `entity_not_found` 로 404 입니다.

<!-- @include: ../reference/_generated/requests/get_neighbors.md -->

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `nodes` | `Node[]` | 진입 노드 포함 |
| `edges` | `Edge[]` | 위 노드를 잇는 관계 |
| `truncated` | `bool` | `max_nodes` 에 걸려 잘렸으면 `true` |

`direction` 은 `outgoing`, `incoming`, `both` 중 하나입니다. `id` 가 선택 필드인 건 REST 와 MCP 가 같은 스키마를 쓰기 때문입니다. REST 는 경로의 `entity_id` 를, MCP 는 본문의 `id` 를 진입점으로 씁니다. REST 에서 둘 다 주면 값이 같은지 검사하고 다르면 거부합니다.

<!-- @include: ../reference/_generated/requests/find_path.md -->

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `paths` | `PathSegment[]` | 짧은 순, 같은 길이면 `hub_score` 낮은 순 |

`PathSegment` 는 `nodes`, `edges`, `length`, `hub_score` 를 담습니다. `hub_score` 는 양 끝점을 뺀 중간 노드의 `log(1+degree)` 합입니다. 값이 크면 아무데나 이어진 허브를 다리로 삼은 경로라 근거로 쓰기 어렵습니다. 판단 기준은 [경로 품질과 hub_score](/query/path-quality)에서 다룹니다.

경로가 없으면 `paths` 가 빈 배열이고 에러가 아닙니다. `from_id` 와 `to_id` 를 같게 주면 `unprocessable` 로 거부합니다.

<!-- @include: ../reference/_generated/requests/get_subgraph.md -->

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `nodes` | `Node[]` | 합쳐진 노드 |
| `edges` | `Edge[]` | 합쳐진 관계 |
| `entry_ids` | `string[]` | 요청한 진입점을 그대로 돌려줍니다 |
| `truncated` | `bool` | `max_nodes` 에 걸려 잘렸으면 `true` |

`max_nodes` 상한이 5000 으로 큽니다. 직렬화 결과가 모델 컨텍스트를 넘으면 부르는 쪽에서 줄입니다.

<!-- @include: ../reference/_generated/requests/find_related.md -->

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `related` | `RelatedNode[]` | 근접 점수 내림차순 |
| `seeds` | `string[]` | 요청한 시드를 그대로 돌려줍니다 |
| `truncated` | `bool` | 후보가 `top_k` 를 넘어 잘렸으면 `true` |

`RelatedNode` 는 `node`, `score`, `distance` 를 담습니다. `score` 는 top-1 이 1.0 이 되도록 정규화한 값이라 절대값이 아니라 이 응답 안에서의 상대 순위로 읽습니다. `distance` 는 어느 시드로부터든 가장 가까운 홉 수이고 1 이상입니다. 시드 자신은 결과에서 빠집니다.

`damping` 은 한 홉 멀어질 때마다 곱하는 감쇠 계수입니다. 0 보다 크고 1 보다 작으며, 작을수록 시드 바로 옆을 선호합니다.

## 공통 모델

<!-- @include: ../reference/_generated/schema-models.md -->

## 같이 보기

- [그래프에 묻기](/query/) — 질문 모양에 따라 도구를 고르는 법
- [적재 도구 참조표](/ingest/tools) — 문서를 넣는 도구 5개
- [REST API](/reference/rest-api) — 같은 7개의 HTTP 주소
