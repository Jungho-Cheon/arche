<!-- 이 파일은 `arche docs gen-reference` 가 코드에서 자동 생성합니다. 직접 고치지 마세요 — 코드를 바꾸고 명령을 다시 실행하세요. -->
<!-- source: apps/api/src/arche_api/docs_gen.py (#125) -->

떼어내기 도구 3개입니다.

| 도구 | 하는 일 |
| --- | --- |
| `entity_split_plan` | 서로 다른 둘이 한 노드로 뭉쳤을 때, 둘로 가를 계획을 세운다. 그래프는 아직 그대로다. |
| `entity_split_preview` | 가른 뒤 두 노드가 어떤 모습이 되고 관계가 어디로 가는지 펼친다. |
| `entity_split_commit` | 사람이 확인한 대로 노드를 둘로 가른다. |
