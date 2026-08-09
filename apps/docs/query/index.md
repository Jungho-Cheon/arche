# 그래프에 묻기

Arche 는 한 번에 답을 주는 검색창이 아니에요. 작은 조회 도구 7개를 이어 붙여 답에 필요한 연결을 직접 따라가는 방식이에요.

답을 쓰는 쪽은 Arche 가 아니라 부르는 에이전트예요. Arche 는 매번 작은 사실 조각만 돌려줘요.

## 순서는 늘 같아요

1. **출발점을 잡는다.** 질문의 핵심어로 `find_entities` 를 불러 노드 ID 를 얻어요.
2. **따라간다.** 질문 모양에 맞는 도구로 그 ID 주변을 펼치거나 다른 노드와 이어요.
3. **받은 사실로만 답한다.** 그래프가 안 준 값은 쓰지 않아요.

사용자가 아는 건 "환불 정책" 같은 말이지 26자리 ID 가 아니라서 1번이 늘 먼저예요.

## 질문 모양에 맞는 도구 고르기

| 질문 | 도구 |
| --- | --- |
| "Z 와 관련된 게 또 뭐가 있어?" | `find_related` |
| "X 와 Y 는 어떻게 이어져?" | `find_path` |
| "이 몇 가지 주변을 통째로 보여줘" | `get_subgraph` |
| "X 에 바로 붙어 있는 건?" | `get_neighbors` |
| "X 자체를 자세히" | `get_entity` |
| "그래프에 뭐가 들어 있어?" | `get_schema` |

**`find_related` 를 먼저 떠올리세요.** 여러 홉을 한 번의 호출로 처리해서, `get_neighbors` 로 홉마다 왕복하는 것보다 빠르고 싸요. 시드를 여러 개 주면 여러 시드에 두루 가까운 노드일수록 점수가 높게 나와요.

`get_neighbors` 는 한 노드의 바로 옆만 정확히 보고 싶을 때 써요.

## 출발점을 못 찾을 때

`matches` 가 빈 배열로 오면 에러가 아니라 그 키워드로 걸리는 노드가 없다는 뜻이에요. 세 가지를 시도해요.

**표현을 바꿔요.** 문서가 "반품"이라 쓰는데 "환불"로 물으면 안 걸릴 수 있어요.

**어떤 타입이 있는지 봐요.** `get_schema` 로 타입과 예시 이름을 보고 거기 쓰인 말로 다시 불러요.

**키워드를 늘려요.** `keywords` 는 최대 32개까지 받아요. 질문의 명사를 여러 개 넣으면 그중 하나라도 걸릴 확률이 올라가요.

## 결과가 너무 넓거나 좁을 때

**너무 넓으면** `relation_types` 로 관계 타입을 좁혀요. 찾는 관계 이름을 알고 있을 때 효과가 커요.

**너무 좁으면** `hops` 나 `max_hops` 를 올려요. `get_neighbors` 는 5, `find_path` 는 6, `find_related` 와 `get_subgraph` 는 4 까지 가요.

**상한에 걸려 일부만 왔으면** 응답의 `truncated` 가 `true` 로 와요. `max_nodes` 나 `top_k` 를 올리거나 관계 타입으로 좁혀요.

## 경로를 믿어도 되는지

`find_path` 결과에는 `hub_score` 가 함께 와요. 값이 크면 아무데나 이어진 노드를 다리로 삼은 경로라, 연결은 됐지만 의미 있는 관계가 아닐 수 있어요.

높은 `hub_score` 를 만나면 기대하는 관계 타입을 `relation_types` 에 넣고 다시 불러요. 판단 기준과 값 읽는 법은 [경로 신뢰도와 hub_score](/query/path-quality)에 있어요.

## 답에 출처 달기

노드마다 `source_refs` 가 있어 어느 문서의 몇 번째 조각에서 왔는지 알 수 있어요. 답에 출처를 달 때 써요.

## 그래프에 없으면 없다고 말하기

Arche 가 안 돌려준 값은 답에 쓰지 않아요. 특히 숫자와 날짜, 규정은 받아 온 노드와 관계에 있는 것만 써요. 없으면 없다고 말하는 편이, 그럴듯하게 지어내 사용자가 검증하게 만드는 것보다 나아요.

Claude Code 플러그인의 `arche-query` 스킬이 이 규칙을 강제해요.

## 에이전트 없이 직접 부르기

REST 로 같은 조회를 손으로 부를 수 있어요.

```bash
curl -X POST http://localhost:8000/entities/find \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["환불"], "limit": 3}'
```

받은 `node.id` 를 다음 조회에 넘겨요.

```bash
curl -X POST http://localhost:8000/related/find \
  -H "Content-Type: application/json" \
  -d '{"seeds": ["01J8XR4K9ZQ2N7M3VB0W4D6TYE"], "top_k": 10}'
```

주소와 응답 형식은 [REST API](/reference/rest-api)에 있어요.

## 다음으로

- 도구별 필드와 제약은 [조회 도구 참조표](/query/tools)
- 경로 판단은 [경로 신뢰도와 hub_score](/query/path-quality)
- 그래프가 부실하면 [추출이 빈약할 때](/ingest/quality)
