# PRD 2 — 소스 입력과 그래프 적재

> 본 문서는 *동작 명세* 만 다룬다. 결정의 근거 (왜 이렇게 정했는가) 는 ADR-0001, ADR-0003, ADR-0004 를 참조한다.

## 0. 책임 분리

Ingest 흐름은 두 계층으로 나뉜다.

| 계층 | 책임 | 호출 시점 |
|---|---|---|
| **Arche Ingest Service** | 소스 → 엔티티/관계 추출 → 그래프 적재 → 노드 임베딩 생성 | 사용자가 명령으로 트리거 |
| **사용자** | 소스 디렉토리 준비, ingestion 명령 호출, 결과 확인 | CLI 또는 admin REST |

Ingest 는 *MVP 단계에서 단일 사용자가 자신의 환경에서 운영* 한다 (ADR-0002 D2). 다중 사용자·권한·테넌트 분리 없음.

---

## 1. 입력 인터페이스

### 1.1 CLI

사용자가 가장 자주 쓰는 진입점.

```
arche ingest <directory_path> [--watch] [--dry-run]
```

| 옵션 | 의미 | MVP 기본 |
|---|---|---|
| `<directory_path>` | 크롤 대상 디렉토리의 절대 경로 | 필수 |
| `--watch` | 디렉토리 변경 감지 후 자동 재 ingest | MVP 미지원 (post-MVP) |
| `--dry-run` | 그래프에 쓰지 않고 추출 결과만 출력 | MVP 지원 |

### 1.2 Admin REST 엔드포인트

CLI 와 동일 흐름의 HTTP 호출.

```
POST /admin/ingest
Content-Type: application/json

{ "directory_path": "/abs/path", "dry_run": false }
```

응답은 *비동기 작업 ID* 와 polling URL.

```
202 Accepted
{ "task_id": "ing_01H...", "status_url": "/admin/ingest/ing_01H.../status" }
```

`/admin/*` 경로는 MCP 에 노출되지 않는다 (ADR-0006 D3). CLI 와 admin REST 모두 *사용자 본인의 호출* 이라고 가정.

### 1.3 작업 상태 조회

```
GET /admin/ingest/{task_id}/status

200 OK
{
  "task_id": "ing_01H...",
  "state": "running" | "succeeded" | "failed",
  "progress": { "files_total": 42, "files_processed": 17 },
  "metrics": { "entities_created": 0, "entities_updated": 0, "relations_created": 0, ... },
  "error": null | { "code": "...", "message": "..." }
}
```

---

## 2. 디렉토리 크롤

### 2.1 지원 파일 포맷 (MVP)

| 그룹 | 확장자 | 처리 방식 |
|---|---|---|
| 텍스트 | `.txt`, `.md` | UTF-8 디코드 후 그대로 LLM 입력 |
| 문서 | `.pdf` | 텍스트 추출 (예: `pypdf` 또는 동등 라이브러리). 이미지 페이지가 섞인 경우 페이지 단위로 텍스트 + 이미지 분리 |
| 이미지 | `.jpg`, `.jpeg`, `.png`, `.webp` | base64 인코딩 후 멀티모달 LLM 에 직접 전달 |

이 외 확장자는 *조용히 건너뛴다* (warning 로그). 사용자가 의도적으로 두는 README 등.

### 2.2 재귀 규칙

- 디폴트 depth 제한 없음. 디렉토리 안의 모든 하위 디렉토리 재귀.
- 자동 제외 패턴:
  - 도트 디렉토리 (`.git/`, `.cache/`, `.DS_Store` 등)
  - `node_modules/`, `__pycache__/`, `venv/`, `.venv/`
- 사용자 정의 제외 — `.archeignore` 파일이 디렉토리 루트에 있으면 gitignore 문법으로 적용.

### 2.3 파일 변경 감지

같은 디렉토리에 ingestion 을 두 번 돌렸을 때 *변경되지 않은 파일은 재처리하지 않는다* . 변경 감지 키 — `(absolute_path, sha256_hash)` . 메타데이터는 `IngestRecord` 라는 별도 컬렉션 / 테이블에 저장.

| 필드 | 의미 |
|---|---|
| `source_path` | 절대 경로 |
| `source_hash` | 파일 내용의 sha256 |
| `last_ingested_at` | 마지막 처리 시각 |
| `entities_emitted` | 이 소스가 만들어낸 노드 ID 목록 |
| `relations_emitted` | 이 소스가 만들어낸 엣지 ID 목록 |

같은 파일이 *수정* 되면 (해시 변경): 이전 ingestion 의 `entities_emitted` / `relations_emitted` 를 *비교 후 차분 적용* — 사라진 엣지는 삭제, 새 엣지는 추가. 이 차분 알고리즘은 [§4.4 idempotent 보장](#44-idempotent-보장) 에서 자세히.

---

## 3. 청크 전략

### 3.1 트리거 조건

청크 분할은 *LLM 컨텍스트 윈도우 초과 시에만* 수행한다 (ADR-0001 D6 의 idempotent 약속과 정합). 측정값:

- 한 소스의 토큰 수 < 모델 컨텍스트의 70% — 청크 분할 *없음*
- 한 소스의 토큰 수 ≥ 70% — 청크 분할 *수행*

토큰 수 측정은 LLM provider 가 제공하는 토크나이저 (예: `tiktoken`) 로 사전 계산.

### 3.2 분할 단위

분할 시 우선 순위 (앞이 더 큰 단위):

1. **Heading 단위** — Markdown 의 `#`, `##` 또는 PDF 의 챕터/섹션 헤딩.
2. **Paragraph 단위** — 빈 줄로 분리된 문단.
3. **Sentence 단위** — 위 두 단위로도 청크가 컨텍스트 초과 시.

### 3.3 관계 유실 방지

분할 시 *인접 청크 간 overlap* 을 둔다. overlap 크기는 *직전 청크의 마지막 N 토큰* 을 다음 청크의 앞에 prepend. N 의 기본값은 *해당 단위 평균 길이의 20%* . 이는 한 문서 안의 *cross-청크 참조* (예: "위에서 언급한 X") 가 추출 단계에서 끊기지 않도록.

청크 메타데이터 — 각 청크에 `chunk_index`, `total_chunks`, `source_path` 를 포함. 추출 결과의 엔티티에 *어느 청크에서 나왔는지* 가 기록되어 출처 추적이 가능.

### 3.4 이미지 처리

이미지 파일은 분할하지 않는다 — 한 이미지 = 한 LLM 호출. PDF 안의 이미지 페이지도 페이지 단위로 한 호출.

---

## 4. 멀티모달 LLM 호출

### 4.1 호출 구조

각 (청크 또는 단일 소스) 에 대해 LLM 을 한 번 호출. 입력은 *시스템 프롬프트 + 사용자 프롬프트 (= 청크 본문 또는 이미지)* . 출력은 *strict JSON* .

### 4.2 시스템 프롬프트 패턴

```
당신은 도메인 문서에서 엔티티와 관계를 추출하는 도구입니다.

주어진 텍스트나 이미지에서 다음을 식별하세요.
- 엔티티: 사물·개념·사람·시스템·정책·규칙 등의 식별 가능한 단위.
- 관계: 두 엔티티 사이의 의미 있는 연결.
- 별칭: 같은 엔티티가 본문에서 다른 표현으로 등장하는 경우 모두 나열.

원칙:
1. 본문에 명시적으로 등장하는 정보만 추출. 추론·확장 금지.
2. 엔티티 이름은 본문 표기 그대로. 정규화는 별칭 필드로.
3. 관계는 능동형 동사구로 ("적용된다", "포함한다", "대체한다" 등).
4. 같은 엔티티가 본문에 여러 번 나오면 한 번만 추출하고 별칭을 모음.

결과는 반드시 다음 JSON 스키마로 응답하세요.
```

JSON 스키마는 [§4.3](#43-결과-json-스키마) 에 명시.

### 4.3 결과 JSON 스키마

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["entities", "relations"],
  "additionalProperties": false,
  "properties": {
    "entities": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "type"],
        "additionalProperties": false,
        "properties": {
          "name": { "type": "string", "minLength": 1, "maxLength": 200 },
          "type": { "type": "string", "minLength": 1, "maxLength": 64 },
          "aliases": {
            "type": "array",
            "items": { "type": "string", "minLength": 1, "maxLength": 200 },
            "default": []
          },
          "description": { "type": "string", "maxLength": 500 },
          "properties": {
            "type": "object",
            "additionalProperties": { "type": ["string", "number", "boolean"] }
          }
        }
      }
    },
    "relations": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["from", "to", "type"],
        "additionalProperties": false,
        "properties": {
          "from": { "type": "string", "description": "출발 엔티티의 name" },
          "to": { "type": "string", "description": "도착 엔티티의 name" },
          "type": { "type": "string", "minLength": 1, "maxLength": 64, "description": "관계 종류 (예: applies_to, contains, replaces)" },
          "properties": {
            "type": "object",
            "additionalProperties": { "type": ["string", "number", "boolean"] }
          }
        }
      }
    }
  }
}
```

LLM provider 의 *structured output* 기능 (예: OpenAI strict mode, Anthropic tool use) 으로 스키마를 강제. 파싱 실패 시 *동일 입력 재시도* 1 회, 그 다음에도 실패하면 해당 청크는 skip + 에러 로그.

### 4.4 결정성 보장

- `temperature = 0`
- 가능하면 `seed` 고정 (provider 가 지원하는 경우)
- LLM 응답이 비결정적이라도 *그래프 적재 단계의 idempotent* 가 영향을 흡수 (§5.4 참조)

---

## 5. 그래프 적재

### 5.1 엔티티 동일성 판단 알고리즘

새로 추출된 엔티티 `e_new` 가 그래프에 이미 있는지 판단하는 절차.

```
function match_entity(e_new):
  # Step 1 — 정규화된 이름의 정확 일치
  normalized = normalize(e_new.name)
  existing = graph.find_by_normalized_name(normalized, type=e_new.type)
  if existing: return existing

  # Step 2 — 별칭 매칭
  for alias in e_new.aliases:
    existing = graph.find_by_normalized_name(normalize(alias), type=e_new.type)
    if existing: return existing

  # Step 3 — 임베딩 유사도 (cosine ≥ 0.92 threshold)
  embedding = embed(e_new.name)
  candidates = graph.vector_search(embedding, top_k=5, type=e_new.type)
  for c in candidates:
    if cosine(c.embedding, embedding) >= 0.92:
      return c

  # Step 4 — 일치 없음 → 새 노드
  return None

function normalize(s):
  # 공백 정규화 + 대소문자 통일 + 흔한 구두점 제거
  return s.strip().lower().replace(...)
```

임베딩 유사도 threshold 0.92 는 *경험적 기본값* 이고, 측정 보고서에서 *오·과 병합* 사례가 보이면 *측정 직후 조정* . 변경 시 ADR 또는 본 PRD 의 amend 로 기록.

### 5.2 신규 엔티티 처리

`match_entity` 가 `None` 을 반환하면 새 노드 생성. 노드 속성:

| 필드 | 값 |
|---|---|
| `id` | ULID (정렬 가능한 시간 기반 ID) |
| `name` | `e_new.name` (본문 표기) |
| `normalized_name` | `normalize(e_new.name)` |
| `type` | `e_new.type` |
| `aliases` | `e_new.aliases` |
| `description` | `e_new.description` (있으면) |
| `properties` | `e_new.properties` |
| `embedding` | `embed(e_new.name)` (또는 §5.6 의 임베딩 대상 결정에 따라) |
| `source_refs` | `[ {source_path, chunk_index} ]` |
| `created_at`, `updated_at` | 현재 시각 |

### 5.3 기존 엔티티 처리 (속성 병합)

`match_entity` 가 기존 노드 `e_existing` 을 반환하면 *병합* :

| 필드 | 병합 규칙 |
|---|---|
| `aliases` | `union(e_existing.aliases, e_new.aliases)` |
| `description` | 더 긴 쪽을 유지 (짧은 쪽이 *축약본* 인 경우가 많음) |
| `properties` | key 단위 merge. 동일 key 면 *기존 값 유지* (LLM 의 변동 반영 안 함) |
| `source_refs` | `union(e_existing.source_refs, [new_ref])` |
| `embedding` | 변경 없음 (재계산 비용 회피) |
| `updated_at` | 현재 시각 |

### 5.4 idempotent 보장

*같은 소스를 두 번 넣어도 같은 그래프* 가 나와야 한다 (ADR-0001 D6).

보장 메커니즘:

1. **같은 source_path + 같은 source_hash** → 재처리하지 않음 (§2.3 의 변경 감지).
2. **소스가 *수정* 되어 재처리되는 경우** — 다음 절차로 차분 적용.
   - 이전 ingestion 의 `entities_emitted` 와 새 ingestion 의 결과를 비교.
   - 사라진 엔티티/관계 — 그 소스에서만 나왔던 것은 *삭제*, 다른 소스와 공유된 것은 *해당 source_ref 만 제거* .
   - 새로 추가된 엔티티/관계 — 정상 적재.
   - 양쪽에 있는 엔티티/관계 — 속성 병합 규칙 (§5.3) 적용.
3. **LLM 응답의 미세한 비결정성** — `match_entity` 가 정규화 + 별칭 + 임베딩 유사도로 흡수. 결과적으로 *그래프 상의 최종 상태는 동일* .

### 5.5 관계 적재

관계는 `(from_entity_id, to_entity_id, type)` 의 3-튜플이 *유일 키* . 같은 튜플이 이미 있으면 *속성 merge* 만 수행, 새 엣지 생성 안 함.

`from` 또는 `to` 가 그래프에 없는 엔티티를 가리키면 — 같은 추출 결과에서 *함께 정의된* 경우가 대부분이므로 [§6](#6-처리-순서) 의 처리 순서가 이를 보장. 그래도 dangling 이 발생하면 *해당 관계는 skip + warning 로그* .

### 5.6 노드 임베딩 생성

엔티티 노드의 `embedding` 필드를 어떻게 채울지.

**임베딩 대상 텍스트 (MVP 기본)**: `f"{name}. {description if description else ''}. aliases: {', '.join(aliases)}"`. 짧은 이름만으로는 의미 변별이 약하므로 *description 과 alias 를 포함* 해 임베딩 품질을 올린다.

**임베딩 모델**: ADR-0001 D3 의 통제 변수 — *청크 벡터 RAG 베이스라인과 동일 모델* . 구체 모델은 측정 직전 결정. PRD 5 의 `5_data_format.md` 에 *측정 회차마다 모델 식별자* 기록 강제.

**임베딩 호출 시점**: 노드 생성 시 (§5.2). 노드 수정 시 (§5.3) 에는 *재계산 안 함* — 비용 회피, 측정 통제 변수 보존.

---

## 6. 처리 순서

한 ingestion 호출 내의 흐름.

```
for each file in crawl(directory_path):
  if not changed(file): skip
  chunks = chunk(file) if too_large(file) else [file]
  for each chunk in chunks:
    raw = llm_extract(chunk)             # §4
    parsed = parse_json(raw)             # 실패 시 1 회 재시도
    if parsed is None: log_error; skip
    upsert_entities(parsed.entities)     # §5.1 ~ 5.3
    upsert_relations(parsed.relations)   # §5.5
  update_ingest_record(file)             # §2.3
emit_summary(metrics)
```

병렬화 — 파일 단위 병렬은 *MVP 에서 지원하지 않음* . 직렬 처리 — idempotent 보장의 디버깅 가능성 우선. post-MVP 에서 도입 검토.

---

## 7. 관찰가능성

### 7.1 Structured Log

각 LLM 호출마다 한 줄 JSON 로그.

```json
{
  "ts": "2026-06-15T22:30:01.234Z",
  "event": "llm_extract",
  "source_path": "/abs/path/doc.md",
  "chunk_index": 0,
  "total_chunks": 1,
  "input_tokens": 1240,
  "output_tokens": 380,
  "duration_ms": 4210,
  "model": "gpt-4.1-mini-2025-...",
  "entities_extracted": 7,
  "relations_extracted": 9,
  "success": true,
  "error": null
}
```

### 7.2 Per-source 메트릭

ingestion 종료 시 *소스별 요약* 을 작업 상태 응답 (§1.3) 의 `metrics` 에 포함.

| 메트릭 | 의미 |
|---|---|
| `files_total` / `files_processed` / `files_skipped` | 크롤 통계 |
| `chunks_total` | 분할 후 청크 수 |
| `entities_created` / `entities_updated` | 그래프 변화 |
| `relations_created` / `relations_skipped_dangling` | 그래프 변화 |
| `llm_calls` / `llm_input_tokens` / `llm_output_tokens` | LLM 비용 추적 |
| `embed_calls` / `embed_tokens` | 임베딩 비용 추적 |
| `duration_ms` | 전체 wall-clock |

### 7.3 사람용 stdout (CLI)

CLI 호출 시 *진행률 + 마지막 요약* 을 stdout 에 표시. 예:

```
[1/42] doc/policy/refund.md ......... 5e 7r in 3.2s
[2/42] doc/policy/coupon.md ......... 12e 18r in 5.1s
...
[42/42] doc/image/diagram.png ........ 4e 3r in 7.8s

ingest summary:
  files: 42 processed, 0 skipped
  graph: +127 entities, +203 relations (idempotent: same hash → no-op for 0 files)
  llm:   42 calls, 38,400 input + 14,200 output tokens
  time:  142 seconds
```

---

## 8. 에러 시나리오

| 시나리오 | 동작 |
|---|---|
| 디렉토리 미존재 | 명령 즉시 종료, exit code 2, "directory not found" |
| 파일 읽기 실패 (권한 등) | 해당 파일 skip + warning 로그, 나머지 진행 |
| PDF 파싱 실패 | 해당 파일 skip + warning 로그, 나머지 진행 |
| LLM 호출 timeout | 1 회 재시도 (지수 백오프). 그 다음 실패 시 해당 청크 skip + error 로그 |
| LLM 응답 JSON 파싱 실패 | 1 회 재시도 (same input). 실패 시 청크 skip + error 로그 |
| 그래프 DB 연결 끊김 | 전체 ingestion 중단, exit code 1, "graph db unavailable" |
| 임베딩 호출 실패 | 1 회 재시도. 실패 시 *해당 노드의 embedding 만 null 로 적재* + warning 로그 (post-MVP 백필 가능하도록) |

전체 ingestion 이 *부분 실패* 로 끝난 경우 — 종료 시점 status = `partial`, 처리된 파일은 그래프에 정상 반영, 실패 파일 목록을 응답에 포함.

---

## 9. 미정 결정 (구현 설계 단계)

본 PRD 가 *명시적으로 미루는* 결정. 구현 시점에 본 PRD 또는 별도 ADR 로 채워진다.

1. **PDF 추출 라이브러리** — `pypdf` / `pdfplumber` / `pymupdf` 중 선택. 이미지 추출 품질로 결정.
2. **`arche` CLI 의 패키징** — 별도 binary / `uvx` / Docker subcommand 중. 사용자 셋업 편의로 결정.
3. **그래프 DB 벤더 선택** — Neo4j 5.13+ / ArangoDB / pgvector+AGE 등 (ADR-0004 D1). 셋업 무게 + 운영 친화도로 결정.
4. **임베딩 어댑터 구현 형태** — `LiteLLM` 같은 통합 라이브러리 / provider 별 직접 호출 중. 측정 통제 변수의 명료성으로 결정.
5. **task queue** — Ingestion 작업의 background 실행 방식 (in-process / arq / celery 등). MVP 동시성 요구가 낮으므로 *in-process asyncio* 가 첫 시도.
6. **임베딩 유사도 threshold (0.92)** 와 청크 overlap 비율 (20%) — 측정 후 조정 가능. 본 PRD 의 값은 *합리적 기본값* 이지 *고정 결정* 이 아님.

---

## 10. Out of scope (MVP 에서 안 만드는 ingest 기능)

- 디렉토리 변경 실시간 감지 (`--watch`) — post-MVP.
- 비텍스트 멀티모달 (오디오·동영상) — post-MVP.
- 같은 소스의 *부분 재 ingest* (특정 청크만) — 전체 차분 알고리즘으로 충분.
- 권한·테넌트별 격리 ingestion — ADR-0002 D2 (단일 환경 가정).
- ingestion 결과의 UI 검수 흐름 — ADR-0002 D1 (FE out of scope).
- 외부 소스 어댑터 (Notion / Confluence / GitHub 등) — post-MVP.

---

## 참조 ADR

- [ADR-0001 D6 — idempotent ingestion 약속](../adr/0001-project-identity-and-mvp-validation-hypothesis.md)
- [ADR-0003 D3 — 별칭 정규화는 ingest + query 둘 다](../adr/0003-graph-entry-point-strategy-hybrid-lexical-dense.md)
- [ADR-0004 D1 — 그래프 DB 내장 인덱스](../adr/0004-vector-infra-graph-db-internal-index.md)
- [ADR-0006 D3 — write 작업은 MCP 비노출](../adr/0006-mcp-rest-primitives-surface.md)
