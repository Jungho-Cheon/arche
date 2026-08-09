# 에러 코드

Arche 가 돌려주는 오류 코드와 HTTP 상태 코드를 모은 참조표입니다. REST 와 MCP 가 같은 코드를 씁니다.

## 응답 모양

REST 는 오류를 이렇게 돌려줍니다.

```json
{
  "error": {
    "code": "entity_not_found",
    "message": "entity 01J8XR4K9ZQ2N7M3VB0W4D6TYE not found",
    "details": {}
  }
}
```

MCP 는 같은 본문에 `isError: true` 를 함께 세웁니다. 부르는 쪽은 `isError` 로 갈라 본문을 JSON 으로 읽습니다.

`code` 는 프로그램이 갈라 쓰라고 있는 값이고, `message` 는 사람이 읽는 설명입니다. `details` 는 코드마다 다른 부가 정보를 담습니다.

## 코드 목록

<!-- @include: ./_generated/error-catalog.md -->

## 자주 만나는 코드

### invalid_input

필드 형식이 어긋났거나 빠졌습니다. `details.errors[]` 에 어느 필드가 왜 걸렸는지 목록으로 담깁니다.

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

`loc` 은 점으로 이은 필드 위치입니다. ID 를 넘기는 자리에 26자리 ULID 가 아닌 값을 주면 대부분 이 코드가 납니다.

### unprocessable

형식은 맞지만 의미상 처리할 수 없습니다. 세 경우가 흔합니다.

- `find_path` 에 `from_id` 와 `to_id` 를 같게 준 경우
- `ingest_preview` 를 거치지 않고 `ingest_commit` 을 부른 경우
- 계획을 세운 뒤 그래프가 바뀌어 계획이 어긋난 경우

마지막 경우는 `ingest_plan` 이나 `ingest_content` 부터 다시 부르면 풀립니다.

### entity_not_found

그 ID 의 노드가 없습니다. namespace 를 잘못 짚었을 때도 이 코드가 나옵니다. 다른 namespace 의 노드는 조회 자체가 안 보이기 때문입니다.

### dependency_unavailable

그래프 백엔드나 AI 공급자에 닿지 못했습니다. Neo4j 를 쓰는데 아직 부팅 중이거나, 접속 정보가 틀렸거나, 네트워크가 막힌 경우입니다. API 키가 비어 있거나 모델 접두사가 잘못됐을 때도 이 코드로 나옵니다.

`GET /healthz` 의 `graph` 값이 `"down"` 인지 먼저 확인하세요.

### unsupported_file_type

받지 않는 확장자의 파일을 넣으려 했습니다. 받는 확장자는 `.txt`, `.md`, `.pdf`, `.jpg`, `.jpeg`, `.png`, `.webp` 입니다.

폴더를 적재할 때는 오류가 아니라 조용히 건너뛰고 `files_unsupported_skipped` 로 셉니다.

### extraction_failed

문서에서 노드와 관계를 뽑는 단계가 실패했습니다. AI 공급자의 응답을 읽지 못했을 때 납니다. 같은 파일이 계속 실패하면 `--dry-run` 으로 추출만 돌려 어디서 걸리는지 좁힙니다.

## 코드가 아닌 실패

키가 없거나 크레딧이 모자라면 AI 공급자 쪽 메시지가 그대로 올라옵니다. 다음 문장이 보이면 OpenAI 계정에 결제 수단과 크레딧이 있는지 확인하세요.

```text
insufficient_quota
```

## 같이 보기

- [REST API](/reference/rest-api) — 엔드포인트별 응답 모양
- [조회 도구 참조표](/query/tools) — 도구별 요청 필드와 제약
