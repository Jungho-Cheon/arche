# CLI 명령

`arche` 명령 다섯 개의 인자와 동작을 모은 참조표입니다. 서버를 띄우지 않고 폴더를 적재하거나, 에이전트가 붙을 MCP 서버를 띄울 때 씁니다.

## 최소 예시

```bash
arche ingest ./내문서폴더
```

```text
[1/3] /docs/pricing.md (2 chunks) ... 12e 9r in 3.4s
[2/3] /docs/policy.pdf ... 7e 5r in 2.1s
[3/3] /docs/diagram.png ... 4e 3r in 1.8s

ingest summary:
  files: 3 processed, 0 skipped (of 3 total)
  graph: +23 entities, +17 relations (chunks: 5)
```

## 설치

저장소를 받은 자리에서 실행하려면 `uv run` 을 앞에 붙입니다.

```bash
uv run --project apps/api arche ingest ./내문서폴더
```

`arche` 를 어디서나 부르려면 도구로 설치합니다. MCP 클라이언트 설정에 `"command": "arche"` 를 적으려면 이쪽이 필요합니다.

```bash
uv tool install ./apps/api
arche version
```

## 명령 목록

| 명령 | 하는 일 |
| --- | --- |
| `arche ingest <경로>` | 폴더나 파일을 그래프에 적재 |
| `arche mcp serve --stdio` | 에이전트가 붙을 MCP 서버를 stdio 로 띄움 |
| `arche reindex` | 벡터 색인을 현재 임베딩 차원으로 다시 생성 |
| `arche docs gen-reference` | 참조표를 코드 스키마에서 생성 |
| `arche version` | 패키지 버전 출력 |

모든 명령은 실행 자리의 `.env` 를 읽습니다. 어떤 값을 채우는지는 [환경 변수](/reference/configuration)에 있습니다.

## arche ingest

```bash
arche ingest <경로> [--dry-run]
```

| 인자 | 설명 |
| --- | --- |
| `<경로>` | 폴더 또는 파일 하나. 폴더면 아래를 재귀로 훑습니다 |
| `--dry-run` | 그래프에 쓰지 않고 추출 결과만 출력 |

받는 확장자는 `.txt`, `.md`, `.pdf`, `.jpg`, `.jpeg`, `.png`, `.webp` 입니다. 그 밖의 확장자는 건너뛰고 요약의 skipped 로 셉니다.

훑을 때 `node_modules`, `__pycache__`, `venv`, `.venv`, `.cache`, `.git` 과 점으로 시작하는 폴더는 자동으로 제외합니다. 폴더 맨 위에 `.archeignore` 를 두면 `.gitignore` 문법으로 규칙을 더할 수 있습니다.

한 파일을 읽다 실패해도 그 파일만 건너뛰고 경고를 남긴 뒤 나머지를 이어서 처리합니다.

출력 한 줄의 `12e 9r` 은 그 파일에서 노드 12개와 관계 9개를 뽑았다는 뜻이고, `3.4s` 는 걸린 시간입니다.

**같은 폴더를 다시 넣으면** 내용이 안 바뀐 파일은 다시 뽑지 않고 건너뜁니다. 요약의 `processed` 가 0 이고 `skipped` 가 올라가는 건 정상입니다.

**빈 결과가 나올 때.** `0 processed (of 0 total)` 이면 그 폴더에서 받는 확장자를 하나도 못 찾은 것입니다. 경로를 다시 확인하세요.

**추출 결과는 캐시에 남습니다.** 같은 내용을 같은 모델로 다시 뽑지 않도록 `.arche-cache/extract` 에 쌓입니다. 지워도 안전하고, 지우면 다음 적재에서 다시 뽑습니다.

이 명령은 그래프 저장소에 직접 붙습니다. API 서버가 떠 있을 필요는 없습니다.

## arche mcp serve

```bash
arche mcp serve --stdio
```

조회 도구 7개와 검토형 적재 도구 5개를 MCP 표준 도구로 노출합니다. 에이전트와 Arche 가 같은 기계에 있을 때 쓰는 전송 방식입니다.

MCP 클라이언트에 이렇게 등록합니다.

```json
{
  "mcpServers": {
    "arche": {
      "command": "arche",
      "args": ["mcp", "serve", "--stdio"]
    }
  }
}
```

`--no-stdio` 는 받지 않습니다. 넣으면 종료 코드 2 로 끝나며 다음 메시지를 냅니다.

```text
[error] `arche mcp serve` 는 stdio 전송 전용입니다. HTTP(SSE) 로 붙이려면 API 서버를 띄우세요: `uvicorn arche_api.main:app` → /mcp/v1.
```

네트워크 너머 원격 에이전트를 붙이는 방법은 [에이전트에 붙이기](/integrate/agent)에서 다룹니다.

기동할 때 색인 생성에 실패해도 서버는 뜹니다. 다음 경고만 남기고 넘어가며, 조회 요청이 실제로 막히면 그때 `dependency_unavailable` 로 드러납니다.

```text
[warn] ensure_indexes failed: ...
```

## arche reindex

```bash
arche reindex
```

벡터 색인을 지금 설정한 임베딩 차원으로 다시 만듭니다. 임베딩 모델을 바꾸면 벡터 차원이 달라지는데, 기동 시의 색인 생성은 이미 있는 색인을 그대로 두어 차원 변경을 반영하지 못합니다.

```text
reindex: rebuilt vector index 'entity_embedding_idx' at dimension 1024
  note: stored node embeddings are NOT recomputed; reingest documents to refill vectors at the new dimension.
```

**색인 구조만 다시 만들고 이미 저장된 노드의 벡터 값은 다시 계산하지 않습니다.** 모델을 바꿨다면 문서를 다시 적재해야 새 차원의 벡터가 채워집니다. 전체 절차는 [모델 갈아끼우기](/operate/models)에 있습니다.

## arche docs gen-reference

```bash
arche docs gen-reference [--check]
```

참조표의 필드 표를 코드의 스키마에서 생성해 `apps/docs/reference/_generated/` 에 씁니다. 문서는 이 파일을 `<!-- @include: -->` 로 끼워 넣으므로, 모델을 바꾸고 이 명령을 다시 실행하면 문서가 따라옵니다.

`--check` 는 생성만 하고 쓰지 않습니다. 커밋된 파일이 코드 스키마와 어긋나면 종료 코드 1 로 알립니다. CI 나 pre-commit 에서 씁니다.

## arche version

```bash
arche version
```

패키지 버전을 출력합니다. `uv tool install` 이 제대로 됐는지 확인할 때 씁니다.

## 같이 보기

- [환경 변수](/reference/configuration) — `.env` 에 채우는 값
- [문서를 그래프에 넣기](/ingest/) — 적재 방식 고르기
- [에이전트에 붙이기](/integrate/agent) — MCP 전송 방식 고르기
