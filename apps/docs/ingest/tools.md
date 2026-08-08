# 적재 도구 참조표

문서를 그래프에 넣는 MCP 도구 5개의 요청 필드와 응답 필드를 모은 참조표입니다. 다섯 도구는 계획, 미리 보기, 질문 해소, 확정 순서로 이어지고, 확정 전까지 그래프에는 아무것도 쓰지 않습니다. 실제 진행 순서는 [문서를 그래프에 넣기](/ingest/)에서 다룹니다.

이 5개는 MCP 에만 있습니다. 대응하는 REST 주소는 없고, REST 로 문서를 넣는 길은 검토 단계가 없는 `POST /admin/ingest` 라는 별도 경로입니다.

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

**응답 봉투.** MCP 는 payload 를 그대로 돌려줍니다. 실패는 `isError: true` 와 함께 `{ "error": { "code", "message", "details" } }` 로 옵니다. 코드 목록은 [에러 코드](/reference/errors)에 있습니다.

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
| `deletion_count` | `int` | 차분으로 지워지거나 잘릴 수 |
| `open_questions` | `int` | 사람 판단이 필요한 질문 수 |

`path` 는 절대 경로여야 하고, 폴더가 아니라 파일 하나를 가리켜야 합니다. 폴더를 통째로 넣는 건 [CLI 명령](/reference/cli)의 `arche ingest` 나 `POST /admin/ingest` 쪽입니다.

<!-- @include: ../reference/_generated/requests/ingest_content.md -->

파일 대신 넘긴 텍스트로 계획을 세웁니다. 다른 도구로 읽어온 페이지를 임시 파일로 떨구지 않고 바로 넣을 때 씁니다. 응답은 `ingest_plan` 과 같은 `PlanSummary` 입니다.

`source_id` 는 파일 경로를 대신하는 차분 기준입니다. `confluence:PAGE-123` 이나 문서 URL 처럼 그 출처를 계속 가리킬 값을 씁니다.

<!-- @include: ../reference/_generated/requests/ingest_preview.md -->

계획으로 무엇이 바뀔지 항목별로 펼칩니다.

| 응답 필드 | 타입 | 설명 |
| --- | --- | --- |
| `new_entities` | `NewEntityView[]` | `name`, `type`, `aliases` |
| `merges` | `MergeView[]` | `target_id`, `before_name`, `after_aliases` |
| `new_relations` | `RelationView[]` | `from_id`, `to_id`, `type` |
| `deletion_count` | `int` | 지워지거나 잘릴 수 |
| `questions` | `QuestionView[]` | 사람 판단이 필요한 항목 |

`QuestionView` 는 `question_id`, `extracted_name`, `extracted_type`, `candidate_id`, `candidate_name`, `similarity`, `kind` 를 담습니다. 새로 뽑은 노드가 기존 노드와 닮았지만 자동으로 합칠 만큼은 아닐 때 실립니다.

<!-- @include: ../reference/_generated/requests/ingest_resolve.md -->

미리 보기가 물은 질문에 사람의 결정을 반영합니다. `resolutions` 의 각 항목은 `question_id` 와 `decision` 을 담고, `decision` 은 `merge`(같은 대상) 또는 `keep`(다른 대상)입니다. 응답은 갱신된 미리 보기라 남은 질문을 이어서 확인합니다.

<!-- @include: ../reference/_generated/requests/ingest_commit.md -->

사람이 확인한 계획을 그래프에 반영합니다.

| 응답 필드 | 타입 |
| --- | --- |
| `entities_created` | `int` |
| `entities_updated` | `int` |
| `relations_created` | `int` |
| `deletions` | `int` |

같은 `plan_id` 로 `ingest_preview` 를 먼저 부르지 않았으면 `unprocessable` 로 거부합니다. 계획을 세운 뒤 그래프가 바뀌어 계획이 어긋난 경우에도 같은 코드로 거부하므로, 그때는 `ingest_plan` 이나 `ingest_content` 부터 다시 부릅니다.

## 같이 보기

- [문서를 그래프에 넣기](/ingest/) — 다섯 도구를 순서대로 쓰는 법
- [추출이 빈약할 때](/ingest/quality) — `hints` 로 추출을 보강하는 법
- [조회 도구 참조표](/query/tools) — 넣은 그래프를 읽는 도구 7개
