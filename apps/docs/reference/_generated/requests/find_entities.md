<!-- 이 파일은 `arche docs gen-reference` 가 코드에서 자동 생성합니다. 직접 고치지 마세요 — 코드를 바꾸고 명령을 다시 실행하세요. -->
<!-- source: apps/api/src/arche_api/docs_gen.py (#125) -->

#### find_entities

| 요청 필드 | 타입 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- |
| `keywords` | `string[]` | (필수) | 최대 32개, 최소 1개 | — |
| `types` | `string[] \| null` | `null` (없으면 키 제외) | — | 필터 — 결과 노드의 type 이 이 리스트에 포함된 것만 반환. |
| `limit` | `int` | `10` | 1 이상, 50 이하 | — |
| `include_scores` | `bool` | `false` | — | True 이면 매치별 raw lexical/dense 점수 동봉 (디버깅 / 커스텀 re-rank). |
| `namespace_id` | `string \| null` | `null` (없으면 키 제외) | 최소 1자 | 질의할 namespace. 미지정 시 auth 헤더 또는 'default' |
