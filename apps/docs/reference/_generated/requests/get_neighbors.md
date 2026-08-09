<!-- 이 파일은 `arche docs gen-reference` 가 코드에서 자동 생성합니다. 직접 고치지 마세요 — 코드를 바꾸고 명령을 다시 실행하세요. -->
<!-- source: apps/api/src/arche_api/docs_gen.py (#125) -->

### get_neighbors

| 요청 필드 | 타입 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- |
| `id` | `string \| null` | `null` (없으면 키 제외) | pattern `^[0-9A-Z]{26}$` | — |
| `relation_types` | `string[] \| null` | `null` (없으면 키 제외) | — | — |
| `direction` | `string` | `both` | pattern `^(outgoing\|incoming\|both)$` | — |
| `hops` | `int` | `1` | 1 이상, 5 이하 | — |
| `max_nodes` | `int` | `100` | 1 이상, 500 이하 | — |
| `namespace_id` | `string \| null` | `null` (없으면 키 제외) | 최소 1자 | — |
