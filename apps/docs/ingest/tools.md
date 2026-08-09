# 적재 도구 참조표

그래프를 바꾸는 도구 9개의 요청 필드와 응답 필드를 모은 참조표입니다. 문서를 넣고 지우는 6개와 잘못 합친 노드를 가르는 3개이고, 둘 다 계획, 미리 보기, 확정 순서로 이어져 확정 전까지 그래프에는 아무것도 쓰지 않습니다. 실제 진행 순서는 [문서를 그래프에 넣기](/ingest/)와 [잘못 합친 노드 떼어내기](/ingest/split)에서 다룹니다.

아홉 도구 모두 MCP 와 REST 양쪽에 같은 스키마로 올라옵니다. REST 주소는 [REST API](/reference/rest-api)에 있습니다. 검토 단계가 없는 `POST /admin/ingest` 는 폴더를 통째로 넣는 별도 경로입니다.

## 최소 예시

에이전트가 읽어온 텍스트로 계획을 세웁니다.

```json
{ "content": "환불은 수령 후 7일 이내에...", "source_id": "confluence:PAGE-123" }
```

```json
{
  "plan_id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE",
  "source_path": "confluence:PAGE-123",
  "entities_created": 4,
  "entities_merged": 1,
  "relations_created": 3,
  "deletion_count": 0,
  "open_questions": 1
}
```

돌아온 `plan_id` 를 `ingest_preview` 에 넘겨 무엇이 바뀔지 확인한 뒤, `ingest_commit` 으로 확정합니다.

## 도구 목록

<!-- @include: ../reference/_generated/tool-catalog-ingest.md -->

## 공통 규약

**응답 형식.** MCP 는 payload 를 그대로 돌려줍니다. 실패는 `isError: true` 와 함께 `{ "error": { "code", "message", "details" } }` 로 옵니다. 코드 목록은 [에러 코드](/reference/errors)에 있습니다.

**출처 라벨.** 같은 출처를 다시 넣을 때는 같은 `source_id`(또는 같은 `path`)를 써야 바뀐 부분만 갱신됩니다. 매번 다른 값을 주면 같은 내용이 중복으로 쌓입니다.

**내용이 외부로 나갑니다.** 계획 단계에서 본문이 설정한 AI 공급자로 전송돼 노드와 관계를 뽑습니다. 밖으로 내보내면 안 되는 문서는 넣지 않습니다.

## 도구별 상세

<!-- @include: ../reference/_generated/requests/ingest_plan.md -->

로컬 파일 하나의 변화를 계획합니다. 응답은 `PlanSummary` 입니다.

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `plan_id` | `string` | 이후 호출에 넘길 계획 식별자 |
| `source_path` | `string` | 계획의 출처 |
| `entities_created` | `int` | 새로 만들 노드 수 |
| `entities_merged` | `int` | 기존 노드에 병합할 수 |
| `relations_created` | `int` | 새로 만들 관계 수 |
| `deletion_count` | `int` | 바뀐 부분을 반영하며 지워지거나 줄어들 항목 수 |
| `open_questions` | `int` | 사람 판단이 필요한 질문 수 |

`path` 는 절대 경로여야 하고, 폴더가 아니라 파일 하나를 가리켜야 합니다. 폴더를 통째로 넣는 건 [CLI 명령](/reference/cli)의 `arche ingest` 나 `POST /admin/ingest` 쪽입니다.

<!-- @include: ../reference/_generated/requests/ingest_content.md -->

파일 대신 넘긴 텍스트로 계획을 세웁니다. 다른 도구로 읽어온 페이지를 임시 파일로 저장하지 않고 바로 넣을 때 씁니다. 응답은 `ingest_plan` 과 같은 `PlanSummary` 입니다.

`source_id` 는 파일 경로를 대신해 같은 출처임을 알아보는 값입니다. `confluence:PAGE-123` 이나 문서 URL 처럼 그 출처를 계속 가리킬 값을 씁니다.

<!-- @include: ../reference/_generated/requests/ingest_delete.md -->

한 출처가 넣은 것을 걷어내는 계획을 세웁니다. `source_path` 는 파일로 넣었으면 그 절대 경로, `ingest_content` 로 넣었으면 그때 준 `source_id` 입니다. 응답은 `PlanSummary` 이고, 이후 `ingest_preview` 와 `ingest_commit` 은 적재와 같은 흐름입니다.

노드마다 결과가 갈립니다. 다른 출처도 그 노드를 만들었으면 그 노드에서 이 출처만 떨어지고 남습니다. 이 출처만 만든 노드는 붙어 있던 관계와 함께 사라집니다.

넣은 적 없는 출처를 주면 `invalid_input` 으로 거부합니다.

::: warning 되돌릴 수 없습니다
확정한 삭제를 되돌리는 연산은 없습니다. 같은 문서를 다시 넣어 채우는 것이 유일한 복구이고, 그 사이 다른 문서가 만든 관계는 돌아오지 않습니다. `ingest_preview` 를 반드시 읽으십시오.
:::

<!-- @include: ../reference/_generated/requests/ingest_preview.md -->

계획으로 무엇이 바뀔지 항목별로 펼칩니다.

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `new_entities` | `NewEntityView[]` | `id`, `name`, `type`, `aliases` |
| `merges` | `MergeView[]` | `target_id`, `before_name`, `after_aliases`, `target_blocked_aliases` |
| `new_relations` | `RelationView[]` | `from_id`, `to_id`, `type`, `from_name`, `to_name` |
| `deletion_count` | `int` | 지워지거나 줄어들 항목 수 |
| `questions` | `QuestionView[]` | 사람 판단이 필요한 항목 |
| `warnings` | `PlanWarning[]` | 확정을 막지 않는 품질 신호 |

`QuestionView` 는 `question_id`, `extracted_name`, `extracted_type`, `candidate_id`, `candidate_name`, `similarity`, `kind` 를 담습니다. 새로 뽑은 노드가 기존 노드와 닮았지만 자동으로 합칠 만큼은 아닐 때 나옵니다.

`MergeView` 의 `target_blocked_aliases` 가 비어 있지 않으면 그 병합 대상은 전에 둘로 갈린 적이 있습니다. 거기 적힌 이름은 그때 떼어낸 쪽으로 간 것입니다. 지금 합치려는 내용이 그쪽 이야기라면 합치면 안 됩니다.

`warnings` 는 확정을 막지 않습니다. `PlanWarning` 은 `kind`, `message`, `entity_ids`, `count` 를 담고, 지금은 `relation_dropped` 한 종류입니다. 관계를 뽑았는데 끝점 노드를 못 찾아 버렸다는 뜻이라, 끝점이 다른 문서에 있으면 그 문서를 먼저 넣고 다시 계획합니다. 버려진 관계는 미리 보기 어디에도 안 나오므로 이 경고가 유일한 신호입니다.

<!-- @include: ../reference/_generated/requests/ingest_resolve.md -->

미리 보기가 물은 질문에 사람의 결정을 반영합니다. `resolutions` 의 각 항목은 `question_id` 와 `decision` 을 담고, `decision` 은 `merge`(같은 대상) 또는 `keep`(다른 대상)입니다. 응답은 갱신된 계획 요약이라 남은 질문을 이어서 확인합니다.

::: warning `open_questions: 0` 은 확정해도 된다는 뜻이 아닙니다
이 호출은 계획을 다시 세우면서 미리 보기 표시를 지웁니다. 응답이 계획을 처음 세웠을 때와 같은 모양이라 "질문도 없고 다 됐다" 로 읽히기 쉽습니다. `previewed` 를 보십시오. 이 호출 뒤에는 `false` 이고, `ingest_preview` 를 다시 부르기 전까지 확정은 거부됩니다.
:::

<!-- @include: ../reference/_generated/requests/ingest_commit.md -->

사람이 확인한 계획을 그래프에 반영합니다. 미리 보기를 거치지 않았거나 답하지 않은 질문이 남아 있으면 `unprocessable` 로 거부합니다. 전부 따로 두고 싶다면 `ingest_resolve` 에 `keep` 을 실어 한 번 부르면 됩니다.

| 응답 필드 | 타입 |
| --- | --- |
| `entities_created` | `int` |
| `entities_updated` | `int` |
| `relations_created` | `int` |
| `deletions` | `int` |

같은 `plan_id` 로 `ingest_preview` 를 먼저 부르지 않았으면 `unprocessable` 로 거부합니다. 계획을 세운 뒤 그래프가 바뀌어 계획이 어긋난 경우에도 같은 코드로 거부하므로, 그때는 `ingest_plan` 이나 `ingest_content` 부터 다시 부릅니다.

## 잘못 합친 노드 떼어내기

<!-- @include: ../reference/_generated/tool-catalog-split.md -->

서로 다른 둘이 한 노드로 뭉쳤을 때 두 노드로 가릅니다. 언제 왜 쓰는지는 [잘못 합친 노드 떼어내기](/ingest/split)에 있습니다.

<!-- @include: ../reference/_generated/requests/entity_split_plan.md -->

`move_aliases` 와 `move_source_paths` 중 적어도 하나는 있어야 합니다. `new_name` 이 원래 노드의 별칭이면 `move_aliases` 에 적지 않아도 함께 옮겨집니다.

관계는 `move_source_paths` 를 기준으로 자동 배분됩니다. 출처가 떼어내는 쪽에만 있으면 `move`, 남는 쪽에만 있으면 `keep`, 양쪽에 걸치거나 출처가 없으면 `ask` 입니다. `move_source_paths` 가 비면 판단 근거가 없어 모든 관계가 `ask` 가 됩니다.

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `plan_id` | `string` | 이후 preview/commit 에 쓰는 계획 식별자 |
| `origin_id` | `string` | 남는 쪽 노드 id |
| `origin_name` | `string` | 남는 쪽 노드 이름 |
| `new_name` | `string` | 떼어낸 노드 이름 |
| `aliases_moved` | `int` | 떼어낸 노드로 갈 별칭 수 |
| `aliases_kept` | `int` | 남을 별칭 수 |
| `source_refs_moved` | `int` | 떼어낸 노드로 갈 출처 수 |
| `source_refs_kept` | `int` | 남을 출처 수 |
| `relations_moved` | `int` | 떼어낸 노드로 갈 관계 수 |
| `relations_kept` | `int` | 남을 관계 수 |
| `open_questions` | `int` | 사람이 정해야 하는 관계 수 |

거절되는 입력은 다음과 같습니다. 모두 `invalid_input` 입니다.

| 입력 | 거절하는 이유 |
| --- | --- |
| `move_aliases` 와 `move_source_paths` 가 둘 다 빔 | 무엇을 떼어낼지 알 수 없음 |
| `new_name` 이 빈 문자열 | 이름 없는 노드는 만들지 않음 |
| `new_name` 이 원래 노드 이름과 같음 | 가르는 것이 아님 |
| 그 이름의 노드가 같은 타입에 이미 있음 | 새로 만들 것이 아니라 그쪽으로 옮길 일 |
| 원래 노드에 없는 별칭이나 출처를 지목 | 없는 것을 옮길 수 없음 |
| 출처를 전부 옮김 | 원래 노드가 빈 껍데기로 남음 |
| `relation_decisions` 에 그 노드에 안 붙은 관계 id | 정할 대상이 아님 |

<!-- @include: ../reference/_generated/requests/entity_split_preview.md -->

가른 뒤 두 노드의 모습과 관계별 행선지를 펼칩니다. 이 호출이 확정의 안전 장치를 겁니다.

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `plan_id` | `string` | 계획 식별자 |
| `origin` | `SplitEntityView` | 남는 쪽의 최종 모습 |
| `new_entity` | `SplitEntityView` | 떼어낸 쪽의 최종 모습 |
| `relations` | `SplitRelationView[]` | 관계 전체와 각각의 행선지 |
| `questions` | `SplitRelationView[]` | `decision` 이 `ask` 인 것만 추린 목록 |

`SplitEntityView` 는 `id`, `name`, `type`, `aliases`, `description`, `description_inherited`, `source_paths` 를 담습니다. `description_inherited` 가 `true` 면 그 설명을 원래 노드에서 그대로 물려받았다는 뜻이라, 떼어낸 노드에는 맞지 않을 수 있습니다. `SplitRelationView` 는 `relation_id`, `type`, `direction`, `other_id`, `other_name`, `source_paths`, `decision`, `reason` 을 담고, `reason` 은 왜 그렇게 갈렸는지 한 줄로 설명합니다.

`questions` 가 비어 있지 않으면 확정이 거부됩니다. 결정을 `entity_split_plan` 의 `relation_decisions` 에 담아 다시 계획합니다.

<!-- @include: ../reference/_generated/requests/entity_split_commit.md -->

미리 보기를 거치고 판단이 끝난 계획을 그래프에 반영합니다.

| 응답 필드 | 타입 |
| --- | --- |
| `origin_id` | `string` |
| `new_entity_id` | `string` |
| `aliases_moved` | `int` |
| `source_refs_moved` | `int` |
| `relations_moved` | `int` |
| `relations_kept` | `int` |

`unprocessable` 로 거부되는 경우가 셋입니다. 같은 `plan_id` 로 `entity_split_preview` 를 먼저 부르지 않았을 때, 정하지 않은 관계가 남아 있을 때, 계획을 세운 뒤 원래 노드가 사라졌을 때입니다.

확정 뒤 두 노드는 서로의 이름을 다시 흡수하지 않습니다. 같은 문서를 다시 적재해도 합쳐지지 않습니다.

## 같이 보기

- [문서를 그래프에 넣기](/ingest/) — 적재 도구를 순서대로 쓰는 법
- [잘못 합친 노드 떼어내기](/ingest/split) — 떼어내기 세 도구를 쓰는 법
- [추출이 빈약할 때](/ingest/quality) — `hints` 로 추출을 보강하는 법
- [조회 도구 참조표](/query/tools) — 넣은 그래프를 읽는 도구 8개
