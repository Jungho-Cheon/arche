<!-- 이 파일은 `arche docs gen-reference` 가 코드에서 자동 생성합니다. 직접 고치지 마세요 — 코드를 바꾸고 명령을 다시 실행하세요. -->
<!-- source: apps/api/src/arche_api/docs_gen.py (#125) -->

### entity_split_plan

| 요청 필드 | 타입 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- |
| `entity_id` | `string` | (필수) | 최소 1자 | 둘로 가를 노드의 id |
| `new_name` | `string` | (필수) | 최대 200자, 최소 1자 | 떼어낸 노드의 이름. 보통 원래 노드의 별칭 중 하나 |
| `move_aliases` | `string[]` | `[]` | — | 떼어낸 노드로 옮길 별칭. 원래 노드에 있는 별칭이어야 한다 |
| `move_source_paths` | `string[]` | `[]` | — | 떼어낸 노드로 옮길 출처. 관계를 어느 쪽에 붙일지도 이 목록으로 갈린다. 비워 두면 모든 관계가 사람 판단 항목으로 올라온다 |
| `relation_decisions` | `object` | `{}` | — | 출처로 갈리지 않는 관계에 대한 사람의 결정. {관계 id: keep\|move}. 미리 보기가 물은 것을 여기 담아 다시 계획한다 |
| `new_description` | `string \| null` | `null` (없으면 키 제외) | 최대 2000자 | 떼어낸 노드의 설명. 주지 않으면 원래 노드의 설명을 물려받는다 |
| `namespace_id` | `string` | `default` | 최소 1자 | 대상 노드가 속한 namespace |
