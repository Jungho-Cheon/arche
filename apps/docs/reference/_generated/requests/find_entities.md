<!-- 이 파일은 `arche docs gen-reference` 가 코드에서 자동 생성합니다. 직접 고치지 마세요 — 코드를 바꾸고 명령을 다시 실행하세요. -->
<!-- source: apps/api/src/arche_api/docs_gen.py (#125) -->

### find_entities

| 요청 필드 | 타입 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- |
| `keywords` | `string[] \| null` | `null` (없으면 키 제외) | 최대 32개, 최소 1개 | 앵커 키워드. 주면 유사도 상위를 돌려준다. 필드를 생략하면 검색이 아니라 *열거* 가 되어 types/namespace 조건에 맞는 노드를 id 순으로 전량 훑는다. |
| `types` | `string[] \| null` | `null` (없으면 키 제외) | — | 필터 — 결과 노드의 type 이 이 리스트에 포함된 것만 반환. |
| `limit` | `int` | `10` | 1 이상, 200 이하 | — |
| `offset` | `int` | `0` | 0 이상 | 이 개수만큼 건너뛴 다음부터. total 과 함께 쪽수를 넘길 때 쓴다. |
| `include_scores` | `bool` | `false` | — | True 이면 매치마다 lexical/dense 원점수를 응답에 함께 담는다 (디버깅, 직접 재정렬용). |
| `namespace_id` | `string \| null` | `null` (없으면 키 제외) | 최소 1자 | 질의할 namespace. 미지정 시 auth 헤더 또는 'default' |
