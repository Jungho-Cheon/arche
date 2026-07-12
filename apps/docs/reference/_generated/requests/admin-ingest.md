<!-- 이 파일은 `arche docs gen-reference` 가 코드에서 자동 생성합니다. 직접 고치지 마세요 — 코드를 바꾸고 명령을 다시 실행하세요. -->
<!-- source: apps/api/src/arche_api/docs_gen.py (#125) -->

#### admin/ingest

| 요청 필드 | 타입 | 기본값 | 제약 | 설명 |
| --- | --- | --- | --- | --- |
| `directory_path` | `string` | (필수) | 최소 1자 | 디렉토리 절대 경로 (재귀 크롤 대상) |
| `dry_run` | `bool` | `false` | — | True 면 그래프에 쓰지 않고 추출만 수행. |
| `namespace_id` | `string \| null` | `null` (없으면 키 제외) | — | ADR-0015 — entity 의 namespace. 미지정 시 'default' 또는 auth 헤더 추출 |
