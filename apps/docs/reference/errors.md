# 에러 코드

호출이 실패하면 응답은 `error` 봉투에 코드와 메시지를 담아 옵니다. 코드 집합은 닫혀 있어서, 에이전트가 코드 값만 보고 분기할 수 있습니다. 새 코드를 더하려면 결정 기록(ADR)을 고쳐야 합니다.

## 에러 봉투

```json
{
  "error": {
    "code": "entity_not_found",
    "message": "entity not found: 01J8XR4K9ZQ2N7M3VB0W4D6TYE",
    "details": {}
  }
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `code` | `string` | 아래 카탈로그의 코드 중 하나 |
| `message` | `string` | 사람이 읽는 설명 |
| `details` | `object` | 코드별 부가 정보. 기본은 빈 객체 |

## 코드 카탈로그

| 코드 | HTTP | 뜻 |
| --- | --- | --- |
| `invalid_input` | 422 | 필드 형식이 틀렸거나 누락 |
| `entity_not_found` | 404 | 해당 ID 의 노드가 없음 |
| `task_not_found` | 404 | 해당 `task_id` 의 작업이 없음 |
| `not_authorized` | 401 | 인증 헤더가 없거나 잘못됨 |
| `permission_denied` | 403 | namespace 나 리소스 권한 없음 |
| `rate_limited` | 429 | 호출 한도 초과 |
| `conflict` | 409 | 동시 적재 등 충돌 |
| `directory_not_found` | 422 | 적재 디렉토리가 없음 |
| `not_a_directory` | 422 | 파일을 디렉토리로 줌 |
| `dependency_unavailable` | 503 | Neo4j 나 LLM provider 가 내려감 |
| `extraction_failed` | 500 | LLM 응답 파싱 실패 등 |
| `internal_error` | 500 | 알려지지 않은 예외 |
| `timeout` | 504 | 백엔드 timeout |

## 검증 오류의 details

`invalid_input` 처럼 필드 검증에서 막힌 오류는 위반 내역을 `details.errors[]` 로 평탄하게 펴서 줍니다. 각 항목은 정확히 세 키만 담습니다.

| 키 | 설명 |
| --- | --- |
| `loc` | 위반 필드를 점으로 이은 경로 (예: `body.keywords`, `body.from_id`) |
| `type` | 위반 종류 (예: `too_short`, `less_than_equal`, `string_pattern_mismatch`) |
| `msg` | 사람이 읽는 설명 |

```json
{
  "error": {
    "code": "invalid_input",
    "message": "request validation failed",
    "details": {
      "errors": [
        { "loc": "body.keywords", "type": "too_short", "msg": "List should have at least 1 item after validation, not 0" }
      ]
    }
  }
}
```

## 다음으로

- [그래프에 질의하기](/guide/query) — 연산별 요청 필드와 오류가 발생하는 조건.
