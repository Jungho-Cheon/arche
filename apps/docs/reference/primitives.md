# 그래프 조회 연산

그래프 조회 연산 6개와 관리 및 상태 확인 연산의 호출 주소, 요청 필드, 응답 모양을 한자리에 모은 참조표입니다. 개념과 예시 흐름은 [그래프에 질의하기](/guide/query)에서 다루고, 여기서는 필드와 범위만 빠르게 찾아봅니다.

REST 는 성공 응답을 `{ "data": ... }` 봉투에 감싸 돌려줍니다. MCP 어댑터는 같은 payload 를 봉투 없이 그대로 돌려줍니다. 아래 "응답" 칸은 모두 봉투 안 payload 기준입니다. 아래 여섯 조회 연산의 절 제목(`get_schema` 등)이 곧 MCP(Model Context Protocol, AI 에이전트가 도구를 호출하는 규약)에서 부르는 도구 이름입니다. MCP 로 에이전트를 붙이는 법은 [에이전트에 연결하기](/guide/agent-integration)에서 다룹니다.

::: tip 값이 없는 필드는 키가 빠집니다
값이 없는 필드는 `null` 로 실려 오지 않고 응답에서 키 자체가 빠집니다. 조회든 관리든 모든 응답이 이 규칙을 똑같이 따릅니다. 예를 들어 노드에 설명이 없으면 `description` 키가 아예 없고, 작업이 성공하면 상태 응답에 `error` 키가 없습니다. 그래서 어느 연산을 부르든 응답 파싱을 한 방식으로 짜면 됩니다. 아래 표에서 타입에 `| null` 이 붙은 응답 필드는 "값이 없을 수 있다"는 뜻이고, 값이 없을 때는 키가 빠진다고 읽으면 됩니다.
:::

## 그래프 조회 연산 (6개)

`namespace_id` 를 받는 연산은 그 값을 명시하지 않으면 인증 헤더의 namespace 를 쓰고, 그마저 없으면 `default` 로 떨어집니다. 호출 주소는 로컬 API(`http://localhost:8000`) 기준입니다.

MCP 호출에는 HTTP 헤더가 없으므로 조회 도구 6개 모두 `namespace_id` 를 도구 인자로 받습니다(미지정 시 `default`). REST 도 6개 모두 헤더 없이 namespace 를 지정할 수 있습니다. 본문을 받는 네 연산은 본문의 `namespace_id` 로, 본문이 없는 `GET /schema` 와 `GET /entities/{entity_id}` 는 `namespace_id` 질의 변수(query parameter)로 받습니다. 셋의 우선순위는 질의 변수(또는 본문) → 인증 헤더 → `default` 순입니다.

## get_schema

그래프에 담긴 엔티티 타입과 관계 타입을 개수와 함께 돌려줍니다.

| 항목 | 값 |
| --- | --- |
| 메서드 + 주소 | `GET /schema` |
| 요청 | 본문 없음. namespace 는 `?namespace_id=` 질의 변수 → 인증 헤더 → `default` 순으로 결정 |

응답: `{ entity_types[], relation_types[], embedding_info }`

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `entity_types[]` | 객체 목록 | `{ type, count, examples[] }` — `examples` 는 `{ id, name }` 최대 5개 |
| `relation_types[]` | 객체 목록 | `{ type, count, common_pairs[] }` — `common_pairs` 는 `{ from_type, to_type, count }` 최대 5개 |
| `embedding_info` | 객체 | `{ model, dimension }` — 진입점 검색에 쓰는 임베딩 모델과 벡터 차원 |

## find_entities

키워드 목록으로 가장 잘 맞는 노드를 찾습니다.

| 항목 | 값 |
| --- | --- |
| 메서드 + 주소 | `POST /entities/find` |

| 요청 필드 | 타입 | 기본값 | 범위/제약 |
| --- | --- | --- | --- |
| `keywords` | `string[]` | (필수) | 1~32개 |
| `types` | `string[] \| null` | `null` | 결과 노드 타입 필터 |
| `limit` | `int` | `10` | 1~50 |
| `include_scores` | `bool` | `false` | `true` 면 매치마다 원점수 동봉 |
| `namespace_id` | `string \| null` | `null` | 빈 문자열 불가 (최소 1자) |

응답: `{ matches[] }`

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `matches[].node` | `Node` | 찾은 노드 ([공통 모델](#공통-모델)) |
| `matches[].score` | `float` | 0~1 정규화 적합도 |
| `matches[].matched_keyword` | `string` | 이 노드를 끌어올린 입력 키워드 |
| `matches[].scores` | `{ lexical, dense } \| null` | `include_scores=true` 일 때만. `lexical >= 0`, `dense` 는 0~1 |

## get_entity

ID 로 노드 한 개와 타입별 인접 관계 수를 봅니다.

| 항목 | 값 |
| --- | --- |
| 메서드 + 주소 | `GET /entities/{entity_id}` |
| 요청 | 경로 변수 `entity_id`. namespace 는 `?namespace_id=` 질의 변수 → 인증 헤더 → `default` 순으로 결정 |

응답: `{ node, edge_counts }`

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `node` | `Node` | [공통 모델](#공통-모델) |
| `edge_counts.outgoing` | `{ [관계타입]: int }` | 나가는 관계의 타입별 개수 |
| `edge_counts.incoming` | `{ [관계타입]: int }` | 들어오는 관계의 타입별 개수 |

다른 namespace 의 ID 는 `entity_not_found` 404 로 끊습니다.

## get_neighbors

진입점에서 N 단계 안에 닿는 이웃을 펼칩니다.

| 항목 | 값 |
| --- | --- |
| 메서드 + 주소 | `POST /entities/{entity_id}/neighbors` |

| 요청 필드 | 타입 | 기본값 | 범위/제약 |
| --- | --- | --- | --- |
| `id` | `string \| null` | `null` | 26자리 식별자(ULID). 경로 `entity_id` 와 다르면 `invalid_input` |
| `relation_types` | `string[] \| null` | `null` | 따라갈 관계 타입 필터 |
| `direction` | `string` | `both` | `outgoing` \| `incoming` \| `both` |
| `hops` | `int` | `1` | 1~5 |
| `max_nodes` | `int` | `100` | 1~500 |
| `namespace_id` | `string \| null` | `null` | 빈 문자열 불가 |

응답: `{ nodes[], edges[], truncated }`

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `nodes` | `Node[]` | 진입점 노드 포함 |
| `edges` | `Edge[]` | 펼친 관계 |
| `truncated` | `bool` | `max_nodes` 에 걸려 잘렸으면 `true` |

## find_path

두 노드 사이의 짧은 경로 몇 개를 찾습니다.

| 항목 | 값 |
| --- | --- |
| 메서드 + 주소 | `POST /paths/find` |

| 요청 필드 | 타입 | 기본값 | 범위/제약 |
| --- | --- | --- | --- |
| `from_id` | `string` | (필수) | ULID. `to_id` 와 같으면 422 |
| `to_id` | `string` | (필수) | ULID |
| `max_hops` | `int` | `4` | 1~6 |
| `max_paths` | `int` | `5` | 1~20 |
| `relation_types` | `string[] \| null` | `null` | 따라갈 관계 타입 필터 |
| `namespace_id` | `string \| null` | `null` | 빈 문자열 불가 |

응답: `{ paths[] }`

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `paths[].nodes` | `Node[]` | 경로 위 노드 |
| `paths[].edges` | `Edge[]` | 경로 위 관계 |
| `paths[].length` | `int` | 단계 수 (1 이상) |
| `paths[].hub_score` | `float` | 0 이상. 클수록 허브를 다리로 쓴 경로 ([경로 품질과 hub_score](/concepts/path-quality)) |

경로가 없으면 `paths` 가 빈 목록으로 옵니다 (오류 아님).

## get_subgraph

여러 진입점에서 펼친 결과를 하나로 합칩니다.

| 항목 | 값 |
| --- | --- |
| 메서드 + 주소 | `POST /subgraph` |

| 요청 필드 | 타입 | 기본값 | 범위/제약 |
| --- | --- | --- | --- |
| `entry_ids` | `string[]` | (필수) | 1~20개, 각 원소 ULID |
| `hops` | `int` | `2` | 1~4 |
| `max_nodes` | `int` | `200` | 1~5000 |
| `relation_types` | `string[] \| null` | `null` | 따라갈 관계 타입 필터 |
| `namespace_id` | `string \| null` | `null` | 빈 문자열 불가 |

응답: `{ nodes[], edges[], entry_ids[], truncated }`

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `nodes` | `Node[]` | 합쳐진 노드 |
| `edges` | `Edge[]` | 합쳐진 관계 |
| `entry_ids` | `string[]` | 넘긴 진입점을 그대로 되돌림 |
| `truncated` | `bool` | `max_nodes` 에 걸려 잘렸으면 `true` |

## 검토형 적재 연산 (4개)

문서에서 점과 선을 뽑아 그래프에 넣는 적재 도구 네 개입니다. 위 조회 연산과 달리 이 넷은 **MCP 도구로만** 노출되며, 대응하는 REST 주소가 없습니다. 그래서 아래 표에는 "메서드 + 주소" 칸이 없습니다. 정해진 차례(계획 → 미리 보기 → 질문 해소 → 확정)로만 써야 하고, 개념 흐름은 [문서를 그래프에 넣기](/guide/ingest)에서 다룹니다.

이 네 도구는 `arche mcp serve --stdio` 로 띄운 MCP 서버에 조회 도구 여섯 개와 함께 노출됩니다. 하나의 MCP 연결로 이 열 개를 모두 부를 수 있어, 에이전트가 MCP 만으로 문서 적재와 그래프 질의를 둘 다 처리합니다. CLI 의 `arche ingest` 나 REST 의 `/admin/ingest` 는 에이전트 없이 문서를 직접 넣을 때 쓰는 저수준 방법입니다. 아래 표는 도구의 입력과 응답 모양을 정리한 참조용입니다.

응답은 조회 연산과 같은 규칙을 따릅니다. REST 통로는 `{ "data": ... }` 봉투로 감싸지만, MCP 는 그 안 payload 만 봉투 없이 돌려줍니다. 아래 "응답" 칸은 payload 기준입니다.

## ingest_plan

파일 하나를 그래프에 쓰지 않고 추출만 돌려 변경 묶음을 만들고, 이후 호출에 쓸 계획 식별자를 돌려줍니다.

| 요청 필드 | 타입 | 기본값 | 범위/제약 |
| --- | --- | --- | --- |
| `path` | `string` | (필수) | 계획을 세울 파일의 절대 경로 (최소 1자) |
| `namespace_id` | `string` | `default` | 계획이 속한 namespace. 빈 문자열 불가 |
| `hints` | `string \| null` | `null` | 추출 품질을 높이는 선택 입력 (용어/약어 풀이 등). 최대 4000자. 저장된 원문은 바꾸지 않고 추출만 돕습니다 |

응답: `{ plan_id, source_path, entities_created, entities_merged, relations_created, deletion_count, open_questions }`

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `plan_id` | `string` | 이후 preview/resolve/commit 호출에 쓰는 계획 식별자 |
| `source_path` | `string` | 계획을 세운 파일 경로 |
| `entities_created` | `int` | 새로 만들 엔티티 수 |
| `entities_merged` | `int` | 기존 엔티티에 병합할 수 |
| `relations_created` | `int` | 새로 만들 관계 수 |
| `deletion_count` | `int` | 차분으로 삭제/트림될 엔티티나 관계 수 |
| `open_questions` | `int` | 사람 판단을 기다리는 병합 후보 질문 수 (임계 바로 아래 유사도) |

## ingest_preview

계획 식별자로 변경 묶음을 항목 단위로 펼쳐 사람이 검토하게 합니다. 이 호출이 계획을 "미리보기 완료"로 표시해, commit 의 안전 잠금을 풉니다.

| 요청 필드 | 타입 | 기본값 | 범위/제약 |
| --- | --- | --- | --- |
| `plan_id` | `string` | (필수) | ingest_plan 이 돌려준 식별자 (최소 1자) |

응답: `{ new_entities[], merges[], new_relations[], deletion_count, questions[] }`

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `new_entities[]` | 객체 목록 | 새로 만들 엔티티. 각 항목 `{ name, type, aliases[] }` |
| `merges[]` | 객체 목록 | 기존 엔티티 병합. 각 항목 `{ target_id, before_name, after_aliases[] }` — `target_id` 는 살아남는 엔티티 id, `before_name` 은 병합 전 이름(없으면 빈 문자열) |
| `new_relations[]` | 객체 목록 | 새로 만들 관계. 각 항목 `{ from_id, to_id, type }` |
| `deletion_count` | `int` | 삭제/트림될 항목 수 |
| `questions[]` | 객체 목록 | 사람 판단을 기다리는 병합 후보 질문. 비어 있지 않으면 resolve 로 답해야 함. 각 항목 `{ question_id, extracted_name, extracted_type, candidate_id, candidate_name, similarity, kind }` |

`questions[]` 각 항목은 추출된 엔티티(`extracted_name`/`extracted_type`)가 기존 노드(`candidate_id`/`candidate_name`)와 임계 바로 아래 `similarity`(0~1)라 자동 병합되지 못한 경우입니다. `kind` 는 질문 종류를 나타내는 문자열입니다. 현재 버전에서 `kind` 는 `"possible_missed_merge"` 한 가지입니다 — 새 항목이 기존 항목과 비슷해 보여 합쳐야 할지 확인이 필요하다는 뜻입니다. 앞으로 버전이 올라가면 종류가 늘 수 있지만 지금은 이 값 하나뿐입니다.

## ingest_resolve

미리보기가 물은 질문에 사람의 결정을 반영해 같은 `plan_id` 로 계획을 다듬습니다. 이 호출은 안전 잠금을 다시 잠그므로, 이후 ingest_preview 를 한 번 더 불러야 commit 할 수 있습니다.

| 요청 필드 | 타입 | 기본값 | 범위/제약 |
| --- | --- | --- | --- |
| `plan_id` | `string` | (필수) | 다듬을 계획 식별자 (최소 1자) |
| `resolutions[]` | 객체 목록 | (필수) | 질문별 결정. 각 항목 `{ question_id, decision }` — `decision` 은 `merge`(같은 대상) 또는 `keep`(다른 대상) |

응답: ingest_plan 과 같은 모양 `{ plan_id, source_path, entities_created, entities_merged, relations_created, deletion_count, open_questions }` — 다듬은 계획의 요약(남은 질문 수 포함)을 돌려줍니다.

## ingest_commit

미리보기를 거친 계획을 그래프에 실제로 반영합니다. 미리보기 전이면 `unprocessable` 로, 계획을 세운 뒤 그래프가 바뀌어 계획이 어긋났으면 다시 계획하라는 오류로 끊습니다.

| 요청 필드 | 타입 | 기본값 | 범위/제약 |
| --- | --- | --- | --- |
| `plan_id` | `string` | (필수) | 반영할 계획 식별자 (최소 1자) |

응답: `{ entities_created, entities_updated, relations_created, deletions }`

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `entities_created` | `int` | 실제로 만든 엔티티 수 |
| `entities_updated` | `int` | 실제로 고친 엔티티 수 |
| `relations_created` | `int` | 실제로 만든 관계 수 |
| `deletions` | `int` | 실제로 지운 항목 수 |

## 관리 및 운영 연산

healthz 와 admin 엔드포인트는 그래프 조회가 아니라 서버 상태 확인과 적재 관리에 씁니다.

## healthz

서버 생존과 Neo4j 연결을 확인합니다.

| 항목 | 값 |
| --- | --- |
| 메서드 + 주소 | `GET /healthz` |
| 요청 | 없음 |

응답: `{ status, neo4j }` — `neo4j` 는 연결되면 `ok`, 끊겼으면 `down`.

## admin/ingest

디렉토리를 적재하는 비동기 작업을 만듭니다. 상태는 `202 Accepted` 와 함께 옵니다.

| 항목 | 값 |
| --- | --- |
| 메서드 + 주소 | `POST /admin/ingest` |

| 요청 필드 | 타입 | 기본값 | 범위/제약 |
| --- | --- | --- | --- |
| `directory_path` | `string` | (필수) | 디렉토리 절대 경로 (최소 1자) |
| `dry_run` | `bool` | `false` | `true` 면 그래프에 쓰지 않고 추출만 |
| `namespace_id` | `string \| null` | `null` | 적재할 namespace |

응답(202): `{ task_id, status_url }` — `status_url` 로 상태를 조회합니다. 경로가 없으면 `directory_not_found` 422, 파일을 디렉토리로 주면 `not_a_directory` 422.

## admin/ingest/{task_id}/status

적재 작업의 진행 상태를 조회합니다.

| 항목 | 값 |
| --- | --- |
| 메서드 + 주소 | `GET /admin/ingest/{task_id}/status` |
| 요청 | 경로 변수 `task_id` |

응답: `{ task_id, state, progress, metrics, error? }`

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `state` | `string` | 작업 상태 (`running` / `succeeded` / `failed`) |
| `progress` | 객체 | `files_total`, `files_processed`, `files_skipped`, `files_pending_skipped`, `files_unsupported_skipped` |
| `metrics` | 객체 | `entities_created`, `entities_updated`, `relations_created`, `relations_skipped_dangling`, `chunks_total` |
| `error` | `{ code, message } \| null` | 실패 시에만. 성공이면 응답에서 생략 |

없는 `task_id` 는 `task_not_found` 404.

## admin/namespaces

namespace 별 엔티티 수를 봅니다 (운영 가시성).

| 항목 | 값 |
| --- | --- |
| 메서드 + 주소 | `GET /admin/namespaces` |
| 요청 | 없음 |

응답: `{ namespaces[] }` — 각 항목은 `{ namespace_id, entity_count }`, 엔티티 수 내림차순.

## 공통 모델

여러 응답이 같은 `Node` 와 `Edge` 모양을 공유합니다.

### Node

| 필드 | 타입 | 기본값 | 제약 |
| --- | --- | --- | --- |
| `id` | `string` | (필수) | ULID (26자리, 숫자와 대문자) |
| `name` | `string` | (필수) | 최대 200자 |
| `type` | `string` | (필수) | 최대 64자 |
| `aliases` | `string[]` | `[]` | 별칭 목록 |
| `description` | `string \| null` | `null` | 최대 2000자. 값이 없으면 키가 빠집니다 |
| `properties` | `{ [키]: string\|int\|float\|bool }` | `{}` | 속성 |
| `source_refs` | `SourceRef[]` | `[]` | 출처 |
| `created_at` | `string` | (필수) | RFC 3339 시각 |
| `updated_at` | `string` | (필수) | RFC 3339 시각 |

응답 `Node` 에는 임베딩 벡터가 들어가지 않습니다.

### Edge

| 필드 | 타입 | 기본값 | 제약 |
| --- | --- | --- | --- |
| `id` | `string` | (필수) | ULID |
| `from` | `string` | (필수) | ULID. 출발 노드 |
| `to` | `string` | (필수) | ULID. 도착 노드 |
| `type` | `string` | (필수) | 최대 64자 |
| `properties` | `object` | `{}` | 속성 |
| `source_refs` | `SourceRef[]` | `[]` | 출처 |
| `created_at` | `string` | (필수) | RFC 3339 시각 |
| `updated_at` | `string` | (필수) | RFC 3339 시각 |

### SourceRef

| 필드 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `source_path` | `string` | (필수) | 출처 문서 경로 |
| `chunk_index` | `int \| null` | `null` | 청크 순번 |
| `total_chunks` | `int \| null` | `null` | 전체 청크 수 |
