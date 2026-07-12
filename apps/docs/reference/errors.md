# 에러 코드

호출이 실패하면 응답은 `error` 봉투에 코드와 메시지를 담아 옵니다. 에러 코드는 정해진 목록으로 고정돼 있어, 프로그램이 코드 값만 보고 분기할 수 있습니다.

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

<!-- @include: ./_generated/error-catalog.md -->

위 표는 코드의 에러 코드 정의에서 자동 생성됩니다(코드/HTTP/뜻이 언제나 실제 코드와 일치). `unprocessable` 과 `unsupported_file_type` 은 형식 검증(`invalid_input`)을 통과한 뒤 의미 단계에서 걸리는 코드라, 나머지와 같은 `error` 봉투로 똑같이 옵니다. MCP 로 부를 때도 `data.code` 에 같은 값이 실립니다.

지금 버전에는 자체 인증이 없습니다. 그래서 `not_authorized`(401)와 `permission_denied`(403)는 보통 Arche 자체에서 나오지 않습니다. Arche 를 인증 프록시 뒤에 두거나 나중에 인증 계층을 붙일 때를 위해 코드만 미리 정해 둔 것입니다.

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
