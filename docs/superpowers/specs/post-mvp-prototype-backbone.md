# post-MVP — 시제품 backbone 구현 계획

날짜: 2026-06-21
관련 결정: ADR-0007 (Combined RAG 채택), ADR-0008 (EntityConsolidator gating),
PRD 6 §0.1 (default = combined 확정), `eval/reports/2026-06-21-variance-decision/`

## 본 spec 이 정의하는 것

variance 결정을 코드에 반영해 *외부 사용자가 corpus 던지고 답을 받을 수 있는* 시제품 수준까지 끌어올리는 PR 분할안. 시제품 정의:

1. `docker compose up` 한 줄로 환경 기동
2. `opentology ingest <dir>` 으로 자기 corpus 적재
3. `POST /answer` 한 호출로 답 + provenance 회수
4. 외부 LLM 운영자는 `POST /retrieve` 로 컨텍스트만 회수 가능
5. 5 분 가이드 (README + Getting Started) 가 위 4 단계를 그대로 안내

본 spec 이 *정의하지 않는* 것: 측정 모드 서비스화 (PRD 6 §1.4), 운영 dashboard, multi-tenant. 이들은 시제품 이후 단계.

## PR 분할안 (5 개)

### PR 1 — variance 결정 + spec amend (현재 PR #53)

| 항목 | 산출물 |
|---|---|
| variance 보고서 | `eval/reports/2026-06-21-variance-decision/CONCLUSION.md` |
| aug 우월성 검증 보고서 | `eval/reports/2026-06-20-aug-superiority/CONCLUSION.md` (PR #53 이미 포함) |
| PRD 6 §0.1 amend | default = combined 명시, `mode` 옵션 spec |
| 본 spec | `docs/superpowers/specs/post-mvp-prototype-backbone.md` |

상태: 진행 중 (본 PR).

### PR 2 — `/answer` + `/retrieve` 엔드포인트 (시제품 backbone)

가장 큰 PR. 기능 분리해 review 가능성 우선.

**구조**:

- 새 모듈 `apps/api/src/opentology_api/answer/`
  - `chunks.py` — chunk 저장 + retrieval (1차 결정: §"chunk 저장 결정")
  - `anchor.py` — anchor 추출 LLM 호출 (eval 의 `ANCHOR_EXTRACTION_SYSTEM` 동일 프롬프트)
  - `combined.py` — eval 의 `CombinedRunner.ask` 를 서비스화. chunk + subgraph + LLM 답변
  - `aug.py` — eval 의 `OpentologyAugRunner` 를 서비스화 (mode="aug" 일 때)
  - `service.py` — 통합 진입점, mode 분기
  - `prompts.py` — `COMBINED_SYSTEM`, `build_combined_user`, `RESPONSE_FORMAT_*` 복사 (eval 과 동기)

- 새 router `apps/api/src/opentology_api/api/answer_router.py`
  - `POST /answer` — 답변 + provenance
  - `POST /retrieve` — chunks + subgraph + 메타 (LLM 호출 없음)
  - `POST /retrieve/chunks` — chunks 만
  - `POST /retrieve/subgraph` — subgraph 만

**`/answer` request/response 명세**:

```http
POST /answer
Content-Type: application/json

{
  "question": "수면 고객의 명품 반품 정책은?",
  "options": [                       // 선택 (MCQ 일 때만)
    {"id": "a", "text": "..."}, ...
  ],
  "mode": "combined",                // optional. "combined" (default) | "aug" | "chunks"
  "chunk_top_k": 8,                  // optional
  "subgraph_hops": null,             // optional. null 이면 anchor 수에 따라 자동 (eval 과 동일)
  "subgraph_max_nodes": 80,
  "token_budget": null,
  "skip_graph_if_no_anchor": true,
  "answer_model": null               // null 이면 서버 default
}
```

응답 envelope:

```json
{
  "data": {
    "answer": "수면 고객도 반품 가능. 단 명품은 90일 이내.",
    "choice": "b",
    "reasoning": "...",
    "provenance": {
      "decisive_source": "graph",
      "mode_used": "combined",
      "chunks": [
        {"source_path": "loyalty/tier-rulebook.md", "chunk_index": 7, "score": 0.63}
      ],
      "graph": {
        "entries": ["수면 고객", "VIP"],
        "edges_used": [
          {"from_id": "...", "rel_type": "EXCEPTION_FOR", "to_id": "..."}
        ],
        "subgraph_node_count": 23,
        "subgraph_edge_count": 41
      }
    },
    "usage": {
      "input_tokens": 14200,
      "output_tokens": 320,
      "embedding_tokens": 850,
      "latency_ms": 4980,
      "answer_model": "gpt-4.1"
    }
  }
}
```

**`/retrieve` response (LLM 호출 없음)**:

```json
{
  "data": {
    "chunks": [...],
    "subgraph": {"entities": [...], "relations": [...]},
    "paths": [...],
    "provenance": { /* answer 와 동일 구조의 retrieval 메타 */ },
    "usage": {"embedding_tokens": 850, "latency_ms": 1230}
  }
}
```

**provenance.decisive_source 결정 규칙**:

LLM 의 reasoning 에 어떤 source 가 인용됐는지 추론 (heuristic, 1차):
- chunk 의 `source_path:chunk_index` 가 reasoning 에 인용되면 "chunk"
- graph entity id / name 이 reasoning 에 인용되면 "graph"
- 둘 다면 "both", 둘 다 아니면 "none"

정밀도가 낮으면 (다음 PR) reasoning 을 별도 LLM 호출로 attribution 시킬 수 있으나 토큰 비용 발생. 시제품 단계는 heuristic 로 시작.

### PR 3 — chunk 저장 + retrieval 인프라

PR 2 와 의존 관계가 있어 *우선 처리*. PR 2 의 `chunks.py` 가 실제로 호출하는 storage.

**1차 결정**: chunk 를 어디에 저장하는가.

| 옵션 | 장점 | 단점 |
|---|---|---|
| A. Neo4j (:Chunk) 노드 + vector index | 인프라 1 곳, ingest 와 동일 트랜잭션 | (:Chunk) 노드 add → 그래프 크기 ↑ |
| B. SQLite + FAISS | Neo4j 부담 ↓ | 인프라 2 곳, sync 부담 |
| C. 호출별 in-memory build (eval 방식) | 구현 1 일 | 매 호출 코퍼스 전체 embed → 시제품 안 됨 |

**결정**: **A (Neo4j (:Chunk))**. 이유:
- 인프라 단일화 — 시제품 사용자가 Neo4j 하나만 띄우면 끝
- ingest 와 동일 트랜잭션 — chunk 와 entity 가 같은 IngestionRun 으로 묶임
- Neo4j 5.x vector index 는 이미 Entity 에 쓰고 있음. 동일 패턴
- 향후 (:Chunk)-[:MENTIONS]->(:Entity) 같은 정설적 정합 가능

**스키마**:

```cypher
(:Chunk {
  id: "<source_path>:<chunk_index>",
  source_path: "loyalty/tier-rulebook.md",
  chunk_index: 7,
  text: "...",
  token_count: 420,
  embedding: [...],
  ingestion_run_id: "..."
})

(:Chunk)-[:EMITTED_IN]->(:IngestionRun)
```

vector index: `CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS FOR (c:Chunk) ON c.embedding`.

UNIQUE constraint: `(c:Chunk) REQUIRE c.id IS UNIQUE`.

ingest 흐름에 `_index_chunks(chunks, run_id)` 단계 추가. PRD 2 § ingest 흐름에 명시.

### PR 4 — Getting Started + docker-compose

| 산출물 | 내용 |
|---|---|
| `docker-compose.yml` | Neo4j + apps/api 2 컨테이너. env 1 개 (`OPENAI_API_KEY`) 만 받음 |
| `docs/getting-started.md` | 1) `docker compose up` 2) `opentology ingest ./my-docs` 3) `curl POST /answer` 의 5 분 가이드. 각 step 화면 출력 예시 포함 |
| `README.md` 갱신 | 한 줄: "graph KB" → "Combined RAG orchestrator". Getting Started 링크 |
| `.env.example` | `OPENAI_API_KEY` 만 |

본 PR 이 머지되면 외부인이 *처음* 시제품을 띄울 수 있다.

### PR 5 — EntityConsolidator (M6.5b #40)

별도 spec (ADR-0008 + PRD 6 §3.A). 본 시제품 backbone 과 *독립*. variance 의 *근본* 해소 → 시제품의 robustness 한 단계 상승.

머지 후 1M 재측정으로 default = combined 결정의 strict evidence 완성.

## 호환성 / 회귀 위험

- 기존 6 primitive 엔드포인트는 *그대로 유지*. 새 router 만 추가.
- eval 의 `combined.py` / `opentology_aug.py` 는 *그대로 유지*. 측정 통제 변수 명확화를 위해 service 와 eval 코드가 *코드 공유* 하지 않고 *동일 prompt + 동일 로직* 으로 *분리 운영*. 향후 (PR 6+) 공유 라이브러리화 검토.
- Neo4j 스키마에 `:Chunk` 추가 → 기존 ingest 데이터에는 영향 없음 (새 ingest 부터 chunks 저장). 옛 ingest 만 있는 환경은 `/retrieve` 시 `chunks` 가 빈 배열.

## 통합 테스트 전략

PR 2/3 머지 시 추가:

- `apps/api/tests/integration/test_answer_flow.py` — financebench-smoke 의 1 question 을 /answer 로 처리, 응답 schema 정합 + non-empty answer 확인. 실제 LLM 호출은 `pytest -m live` 게이트.
- `apps/api/tests/unit/test_answer_router.py` — request validation, mode 분기, knob 기본값 확인 (mock LLM/graph).
- 회귀 — 기존 6 primitive 테스트 (`test_routers.py`) green 유지.

## 후속 작업 (시제품 후)

- 측정 모드 서비스화 (PRD 6 §1.4)
- multi-tenant + 인증 (post-MVP FE 복귀 시점)
- HTTP+SSE MCP (PRD 3 §8.1)
- 코드베이스 적재 ADR (memory `project_post_mvp_code_ingest_adr` — graphify 직접 사용 경험 기반)

## 추적

GitHub issues 신설:
- PR 2/3 → issue "시제품 backbone: /answer + chunk storage"
- PR 4 → issue "Getting Started + docker-compose"
- PR 5 → 기존 issue #40 (EntityConsolidator)
