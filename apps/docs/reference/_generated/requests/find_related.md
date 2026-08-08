<!-- 이 파일은 `arche docs gen-reference` 가 코드에서 자동 생성합니다. 직접 고치지 마세요 — 코드를 바꾸고 명령을 다시 실행하세요. -->
<!-- source: apps/api/src/arche_api/docs_gen.py (#125) -->

### find_related

| 요청 필드 | 타입 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- |
| `seeds` | `string[]` | (필수) | 최대 20개, 최소 1개 | — |
| `top_k` | `int` | `10` | 1 이상, 100 이하 | — |
| `max_hops` | `int` | `2` | 1 이상, 4 이하 | — |
| `damping` | `float` | `0.5` | — | — |
| `relation_types` | `string[] \| null` | `null` (없으면 키 제외) | — | — |
| `namespace_id` | `string \| null` | `null` (없으면 키 제외) | 최소 1자 | — |
