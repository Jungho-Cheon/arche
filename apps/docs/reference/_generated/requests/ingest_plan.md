<!-- 이 파일은 `arche docs gen-reference` 가 코드에서 자동 생성합니다. 직접 고치지 마세요 — 코드를 바꾸고 명령을 다시 실행하세요. -->
<!-- source: apps/api/src/arche_api/docs_gen.py (#125) -->

#### ingest_plan

| 요청 필드 | 타입 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- |
| `path` | `string` | (필수) | 최소 1자 | 적재 계획을 세울 파일의 절대 경로 |
| `namespace_id` | `string` | `default` | 최소 1자 | ADR-0015 — 계획이 속한 namespace. 미지정 시 'default' |
| `hints` | `string \| null` | `null` (없으면 키 제외) | 최대 4000자 | 추출 품질을 끌어올리는 선택 입력 — 도메인 용어/약어 풀이, 대상 엔티티 강조 등. max_length 로 프롬프트 예산을 제한한다. |
