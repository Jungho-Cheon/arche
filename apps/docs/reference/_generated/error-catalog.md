<!-- 이 파일은 `arche docs gen-reference` 가 코드에서 자동 생성합니다. 직접 고치지 마세요 — 코드를 바꾸고 명령을 다시 실행하세요. -->
<!-- source: apps/api/src/arche_api/docs_gen.py (#125) -->


| 코드 | HTTP | 뜻 |
| --- | --- | --- |
| `invalid_input` | 422 | 필드 형식이 틀렸거나 누락 |
| `unprocessable` | 422 | 형식은 맞지만 의미상 처리할 수 없음. 예: find_path 에 from_id 와 to_id 를 같게 준 경우, 미리 보기를 거치지 않은 ingest_commit, 계획이 어긋난(stale) 경우 |
| `unsupported_file_type` | 400 | 받지 않는 형식의 파일을 적재하려 함 |
| `entity_not_found` | 404 | 해당 ID 의 노드가 없음 |
| `task_not_found` | 404 | 해당 task_id 의 작업이 없음 |
| `not_authorized` | 401 | 인증 헤더가 없거나 잘못됨 |
| `permission_denied` | 403 | namespace 나 리소스 권한 없음 |
| `rate_limited` | 429 | 호출 한도 초과 |
| `conflict` | 409 | 동시 적재 등 충돌 |
| `directory_not_found` | 422 | 적재 디렉토리가 없음 |
| `not_a_directory` | 422 | 파일을 디렉토리로 줌 |
| `dependency_unavailable` | 503 | 그래프 백엔드나 LLM provider 가 내려감 |
| `extraction_failed` | 500 | LLM 응답 파싱 실패 등 |
| `internal_error` | 500 | 알려지지 않은 예외 |
| `timeout` | 504 | 백엔드 timeout |
