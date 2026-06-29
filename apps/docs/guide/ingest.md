# 문서를 그래프에 넣기

문서를 그래프에 넣는다는 건, 글에서 점(엔티티)과 선(관계)을 뽑아 그래프 DB 에 저장한다는 뜻입니다. Arche 는 같은 일을 세 가지 길로 열어 둡니다. 혼자 로컬 파일을 빠르게 넣을 때, HTTP 로 띄워 두고 진행 상황을 지켜볼 때, 사람이 결과를 먼저 검토하고 확정할 때입니다. 상황에 맞는 길을 고르면 됩니다.

| 길 | 언제 쓰나 | 진행 확인 | 사람 검토 |
| --- | --- | --- | --- |
| CLI 빠른 적재 | 혼자, 로컬 파일을 바로 넣을 때 | 한 줄씩 즉시 출력 | 없음 |
| REST 비동기 적재 | HTTP 로 띄워 두고 진행을 지켜볼 때 | 상태를 따로 조회 | 없음 |
| 검토형 적재 (MCP) | 그래프에 쓰기 전에 사람이 변화를 승인할 때 | 미리 보기로 확인 | 있음 |

## CLI 빠른 적재

가장 단순한 길입니다. API 를 띄우지 않아도 명령 하나로 폴더를 통째로 넣을 수 있어, 혼자 로컬 파일을 다룰 때 잘 맞습니다.

```bash
uv run --project apps/api arche ingest ./내문서폴더
```

경로 자리에는 폴더와 단일 파일을 모두 넣을 수 있습니다. 폴더를 주면 그 아래를 재귀로 훑고, 파일 하나를 주면 그 파일만 넣습니다. 받는 형식은 세 가지입니다.

- **글 파일** — `.txt`, `.md`
- **PDF** — 페이지의 글과 페이지 안에 박힌 이미지를 함께 읽습니다.
- **이미지 파일** — `.jpg`, `.jpeg`, `.png`, `.webp`. 그림 한 장에서 바로 점과 선을 뽑습니다.

폴더를 훑을 때 `.git`, `node_modules`, `.venv` 같은 환경 폴더와 점으로 시작하는 폴더는 자동으로 건너뜁니다. 폴더 맨 위에 `.archeignore` 파일을 두면 `.gitignore` 와 같은 문법으로 제외 규칙을 더 줄 수 있습니다.

한 파일을 읽다 실패해도 그 파일만 건너뛰고 경고를 남긴 뒤 나머지를 계속 처리합니다. 깨진 PDF 하나 때문에 폴더 전체가 멈추지 않습니다.

실행하면 파일마다 한 줄씩 찍고 마지막에 요약을 보여 줍니다.

```text
[1/3] /docs/pricing.md (2 chunks) ... 12e 9r in 3.4s
[2/3] /docs/policy.pdf ... 7e 5r in 2.1s
[3/3] /docs/diagram.png ... 4e 3r in 1.8s

ingest summary:
  files: 3 processed, 0 skipped (of 3 total)
  graph: +23 entities, +17 relations (chunks: 5)
```

한 줄의 `12e 9r` 은 그 파일에서 점 12 개와 선 9 개를 뽑았다는 뜻이고, `3.4s` 는 걸린 시간입니다. 같은 폴더를 다시 넣으면 바뀐 부분만 갱신합니다.

::: tip 그래프에 쓰지 않고 먼저 보기
`--dry-run` 을 붙이면 추출만 하고 그래프에는 쓰지 않습니다. 점과 선이 몇 개나 나올지, 모양이 어떻게 잡힐지 비용 없이 미리 가늠할 때 씁니다.

```bash
uv run --project apps/api arche ingest ./내문서폴더 --dry-run
```
:::

## REST 비동기 적재

API 를 띄워 두고 HTTP 로 넣는 길입니다. 적재는 시간이 걸리는 작업이라, 요청을 받으면 바로 작업을 만들어 돌려주고 진행 상황은 따로 조회하게 했습니다. 폴더가 크거나 적재를 다른 시스템에서 걸어 두고 진행을 지켜보고 싶을 때 잘 맞습니다.

먼저 적재를 요청합니다. 성공하면 `202` 와 함께 작업 번호(`task_id`)와 상태를 조회할 주소(`status_url`)를 받습니다. 모든 성공 응답은 `{"data": ...}` 로 감쌉니다.

```bash
curl -X POST http://localhost:8000/admin/ingest \
  -H "Content-Type: application/json" \
  -d '{"directory_path": "/abs/path/to/docs", "dry_run": false}'
```

```json
{
  "data": {
    "task_id": "a1b2c3",
    "status_url": "/admin/ingest/a1b2c3/status"
  }
}
```

받은 주소로 상태를 조회합니다. 끝날 때까지 짧은 간격을 두고 몇 번 다시 부르면 됩니다.

```bash
curl http://localhost:8000/admin/ingest/a1b2c3/status
```

```json
{
  "data": {
    "task_id": "a1b2c3",
    "state": "running",
    "progress": {
      "files_total": 12,
      "files_processed": 5,
      "files_skipped": 0,
      "files_pending_skipped": 0,
      "files_unsupported_skipped": 1
    },
    "metrics": {
      "entities_created": 48,
      "entities_updated": 6,
      "relations_created": 31,
      "relations_skipped_dangling": 2,
      "chunks_total": 14
    },
    "error": null
  }
}
```

`state` 는 작업이 어디까지 왔는지 알려 줍니다. 도는 중이면 `running`, 끝나면 `succeeded`, 도중에 멈추면 `failed` 입니다. `failed` 일 때만 `error` 에 까닭이 담기고, 그 외에는 `null` 입니다.

`progress` 는 파일을 얼마나 처리했는지 보여 줍니다.

| 필드 | 뜻 |
| --- | --- |
| `files_total` | 훑어서 처리 대상으로 잡은 파일 수 |
| `files_processed` | 그래프에 반영을 끝낸 파일 수 |
| `files_skipped` | 처리 중 건너뛴 파일 수 |
| `files_pending_skipped` | 아직 받을 수 없는 형식이라 건너뛴 파일 수 |
| `files_unsupported_skipped` | 지원하지 않는 확장자라 건너뛴 파일 수 |

`metrics` 는 그래프가 얼마나 채워졌는지 보여 줍니다.

| 필드 | 뜻 |
| --- | --- |
| `entities_created` | 새로 만든 점(엔티티) 수 |
| `entities_updated` | 이미 있던 점에 정보를 더해 갱신한 수 |
| `relations_created` | 새로 만든 선(관계) 수 |
| `relations_skipped_dangling` | 양 끝 중 한쪽 점이 없어 잇지 못하고 건너뛴 선 수 |
| `chunks_total` | 문서를 나눠 처리한 조각 수 |

::: tip 그래프에 쓰지 않고 먼저 보기
요청 본문에 `"dry_run": true` 를 주면 추출만 하고 그래프에는 쓰지 않습니다. 같은 상태 조회로 점과 선이 몇 개나 나올지 비용 없이 미리 봅니다.
:::

::: warning directory_path 는 실재하는 절대 경로여야 합니다
`directory_path` 가 절대 경로가 아니거나 그 경로에 폴더가 없으면 `422` 로 막힙니다. 경로 자체가 없으면 `directory_not_found`, 경로는 있는데 폴더가 아니라 파일이면 `not_a_directory` 가 돌아옵니다. 에러 코드는 [에러 코드](/reference/errors)에 정리돼 있습니다.
:::

여러 팀이나 프로젝트의 지식을 한 그래프 DB 안에서 나눠 담고 싶다면 본문에 `namespace_id` 를 더해 어느 칸에 담을지 정합니다. 자세한 내용은 [팀별 지식 격리 (namespace)](/guide/namespace)에 있습니다.

## 검토형 적재 (MCP)

그래프에 바로 쓰지 않고, 사람이 무엇이 바뀌는지 먼저 보고 승인한 뒤 확정하는 길입니다. 잘못 합쳐진 점이나 엉뚱한 선이 소리 없이 들어가면 곤란한 자리에서 씁니다. AI 에이전트가 Arche 의 MCP 도구를 차례로 부르고, 사람은 중간에서 검토만 합니다. MCP 는 에이전트가 외부 도구를 표준 방식으로 부르게 하는 규약(Model Context Protocol)입니다.

순서는 정해져 있습니다. 아래 차례를 그대로 따릅니다.

1. **`ingest_plan`** — 파일 경로를 주고 계획을 짭니다. 아직 아무것도 쓰지 않습니다. 새로 생길 점, 합쳐질 점, 새로 생길 선의 개수를 요약해 돌려줍니다.
2. **`ingest_preview`** — 짠 계획을 사람이 읽을 수 있게 펼쳐 봅니다. 새 점, 합쳐지는 점의 합치기 전과 후, 새 선, 지워질 개수를 보여 줍니다.
3. **`ingest_resolve`** — 미리 보기에 확인할 질문(`questions`)이 딸려 오면 먼저 풉니다. 질문 하나하나에 결정을 모아 `ingest_resolve` 로 넘긴 뒤 다시 미리 보기로 돌아갑니다. 질문이 없으면 이 단계는 건너뜁니다.
4. **확정 여부 묻기** — 사람에게 "이대로 반영할까요?" 라고 묻고 분명한 동의를 받습니다. 미심쩍게 합쳐진 점이나 이상한 점이 있으면 먼저 짚어 줍니다.
5. **`ingest_commit`** — 동의를 받으면 그제야 그래프에 씁니다. 반영된 개수를 보고합니다.

여기서 질문(`questions`)이란, 새로 뽑힌 점이 이미 있던 점과 닮았지만 자동으로 합치기엔 애매한 경우를 말합니다. 도구는 사람에게 이렇게 묻습니다. "새로 나온 'X' 가 기존 'Y' 와 NN% 닮았습니다. 같은 대상인가요, 새로운 대상인가요?" 같은 대상이면 합치고, 정말 다른 대상이면 따로 둡니다. 미리 보기에 질문이 하나라도 남아 있으면 확정하지 않습니다.

### 미리 보기가 빈약할 때: hints

내용이 빽빽한 문서인데 미리 보기에 점과 선이 너무 적게 잡힐 때가 있습니다. 표가 많거나 용어가 촘촘해 추출이 놓친 사실이 많은 경우입니다. 이럴 때는 `ingest_plan` 에 `hints` 를 함께 줘서 추출을 거들 수 있습니다. 추출기가 원문을 더 잘 읽도록 돕는 짧은 메모입니다. 용어 풀이, 줄임말 목록, "각 행을 하나의 사실로 다뤄라" 같은 지시, 비슷한 용어를 구분하는 설명 따위를 적습니다. 그런 다음 `ingest_plan` 을 다시 부르고 1 번 순서부터 새로 시작합니다.

::: warning hints 는 추출만 거들 뿐, 원문을 고치지 않습니다
`hints` 는 계획이 제안하는 그래프의 모양에만 영향을 줍니다. 디스크에 있는 원본 파일도, 저장된 원문도 적힌 그대로 보존되며 절대 다시 쓰이지 않습니다.
:::
