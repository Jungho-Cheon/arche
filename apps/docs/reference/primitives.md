# 그래프 조회 연산

조회 연산 열 개의 호출 주소, 요청 필드, 응답 모양을 한자리에 모은 참조표입니다. 개념과 예시 흐름은 [그래프에 질의하기](/guide/query)에서 다루고, 여기서는 필드와 범위만 빠르게 찾아봅니다.

REST 는 성공 응답을 `{ "data": ... }` 봉투에 감싸 돌려줍니다. MCP 어댑터는 같은 payload 를 봉투 없이 그대로 돌려줍니다. 아래 "응답" 칸은 모두 봉투 안 payload 기준입니다. MCP(Model Context Protocol, AI 에이전트가 도구를 호출하는 규약)에서 부르는 연산 이름은 각 절 제목 뒤에 적었습니다.

`namespace_id` 를 받는 연산은 그 값을 명시하지 않으면 인증 헤더의 namespace 를 쓰고, 그마저 없으면 `default` 로 떨어집니다. 호출 주소는 로컬 API(`http://localhost:8000`) 기준입니다.

## get_schema

그래프에 담긴 엔티티 타입과 관계 타입을 개수와 함께 돌려줍니다.

| 항목 | 값 |
| --- | --- |
| 메서드 + 주소 | `GET /schema` |
| 요청 본문 | 없음 (namespace 는 인증 헤더에서 결정) |

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
| 요청 | 경로 변수 `entity_id` (namespace 는 인증 헤더에서 결정) |

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
| `id` | `string \| null` | `null` | ULID. 경로 `entity_id` 와 다르면 `invalid_input` |
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
| `description` | `string \| null` | `null` | 최대 2000자, `null` 허용 (find_entities 응답에서는 생략될 수 있음) |
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
