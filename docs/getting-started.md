# 5 분 시작 가이드 — Opentology

자기 도메인 문서를 그래프 KB 로 만들고, `POST /answer` 한 호출로 질문에 답을 받는 가장 짧은 경로.

## 준비물

- **Docker Desktop** (Docker Engine 20.10+ / Docker Compose v2)
- **OpenAI API key** — entity 추출 + 답변 생성 + chunk embedding 에 모두 사용
- 자기 문서 디렉토리 — `.md`, `.txt`, `.pdf` 파일

## 1. 저장소 받기 + 환경 설정 (30 초)

```bash
git clone https://github.com/Jungho-Cheon/opentology
cd opentology

# .env 만들고 OPENAI_API_KEY 입력
cp .env.example .env
$EDITOR .env  # OPENAI_API_KEY=sk-... 채우기
```

`.env` 의 다른 값 (NEO4J_PASSWORD, 모델 ID) 은 시제품 단계에서 디폴트 그대로 OK.

## 2. 서비스 띄우기 (1 분)

```bash
docker compose up -d
```

두 컨테이너가 뜬다:

- `opentology-neo4j` — graph DB. 첫 부팅 시 vector + fulltext + UNIQUE constraint 자동 마이그레이션.
- `opentology-api` — FastAPI. `http://localhost:8000` 노출.

healthcheck 가 통과할 때까지 기다리려면:

```bash
docker compose ps   # opentology-api 가 (healthy) 가 될 때까지 5-15 초
curl http://localhost:8000/healthz
# {"status":"ok","neo4j":"ok"}
```

OpenAPI 스펙은 `http://localhost:8000/docs` 에서 직접 탐색.

## 3. 자기 문서 ingest (2-5 분)

자기 도메인 디렉토리를 ingest 한다. *컨테이너 안에 같은 경로* 가 보여야 하므로 docker-compose 의 volume 마운트를 활용하거나, `opentology` CLI 의 호스트 모드로 호출.

가장 간단한 두 가지 path:

### 옵션 A — CLI (호스트에서 직접 실행)

호스트에서 직접 ingest (Neo4j 만 컨테이너로). Python 3.12 + `uv` 가 있어야 함:

```bash
uv sync --package opentology-api
uv run --package opentology-api opentology ingest ./my-docs
```

`opentology` CLI 가 디렉토리를 재귀 크롤 (`.opentologyignore` 무시 패턴 지원) 후 `.md` / `.txt` / `.pdf` / 이미지 파일을 LLM 추출 → 그래프 적재 + chunk embedding.

### 옵션 B — REST 로 ingest 호출

```bash
# docker-compose.yml 의 volumes 에 자기 디렉토리를 추가하거나
# (기본) eval/datasets/ 만 마운트됨. 자기 도메인은 호스트 path 그대로 컨테이너에
# 도 같은 path 로 mount 추가:
#
#   services:
#     opentology-api:
#       volumes:
#         - ./eval/datasets:/Users/.../eval/datasets:ro
#         - /Users/me/my-docs:/Users/me/my-docs:ro   # ← 추가
#
# 그 다음:
curl -X POST http://localhost:8000/admin/ingest \
  -H "Content-Type: application/json" \
  -d '{"directory_path": "/Users/me/my-docs"}'
# {"data":{"task_id":"01J...","status_url":"/admin/ingest/01J.../status"}}

# 진행도 polling
curl http://localhost:8000/admin/ingest/01J.../status
```

옵션 A 가 시제품 단계 시작에 가장 단순.

## 4. 질문하기 — `POST /answer`

```bash
curl -X POST http://localhost:8000/answer \
  -H "Content-Type: application/json" \
  -d '{
    "question": "수면 고객의 명품 반품 정책은 어떻게 적용되나?"
  }' | jq
```

응답:

```json
{
  "data": {
    "answer": "수면 고객도 반품 가능. 단 명품 카테고리는 90일 이내 한정.",
    "choice": null,
    "reasoning": "(B) 그래프의 (수면 고객)--EXCEPTION_FOR-->(명품 반품 연장) 관계와 (A) 청크 7 의 운영 정책 본문이 일치.",
    "provenance": {
      "decisive_source": "both",
      "mode_used": "combined",
      "chunks": [
        {"source_path": "loyalty/tier-rulebook.md", "chunk_index": 7, "score": 0.63}
      ],
      "graph": {
        "entries": ["수면 고객", "VIP", "명품 반품"],
        "edges_used": [
          {"from_id": "01J...", "rel_type": "EXCEPTION_FOR", "to_id": "01J..."}
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

MCQ 답변 (5 지선다) 이 필요하면 `options` 필드 동봉:

```json
{
  "question": "...",
  "options": [
    {"id": "a", "text": "..."}, {"id": "b", "text": "..."},
    {"id": "c", "text": "..."}, {"id": "d", "text": "..."},
    {"id": "e", "text": "정보 부족"}
  ]
}
```

응답의 `choice` 가 `"a"|"b"|"c"|"d"|"e"` 중 하나.

## 5. 옵션 — 자체 LLM 운영자

LLM 답변 단계를 *직접* 만들려면 `POST /retrieve` 로 컨텍스트만 회수:

```bash
curl -X POST http://localhost:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"question": "..."}' | jq
# chunks + subgraph + serialized_text 만 (LLM 호출 없음)
```

chunks 만이면 `/retrieve/chunks`, subgraph 만이면 `/retrieve/subgraph`.

## 6. 노브 — 비용 / 정확도 트레이드오프

`POST /answer` body 에 옵션 동봉 (자세한 의미는 [PRD 6 §1.3](./prd/6_post_mvp_combined.md)):

| 옵션 | 기본 | 효과 |
|---|---|---|
| `mode` | `"combined"` | `"chunks"` 로 바꾸면 graph 호출 0, 토큰 절반. multi-hop hint 일 땐 `"aug"` (후속 PR 에서) |
| `chunk_top_k` | 8 | 청크 개수. 낮추면 토큰 절감 |
| `subgraph_hops` | auto (anchor 1-3 → 2 hops, 4+ → 1 hop) | 그래프 깊이 |
| `subgraph_max_nodes` | 80 | 그래프 폭 |
| `skip_graph_if_no_anchor` | true | anchor 0 이면 graph 호출 자체 skip |
| `answer_model` | server default | LLM 모델 ID 오버라이드 |

## 다음 단계

- [PRD 6 §0.1](./prd/6_post_mvp_combined.md) — variance 분석에서 도출한 default 결정 근거
- [variance 결정 보고서](../eval/reports/2026-06-21-variance-decision/CONCLUSION.md) — 왜 default = combined 인가
- [시제품 backbone spec](./superpowers/specs/post-mvp-prototype-backbone.md) — 본 가이드의 산출물이 어떤 5 단계 PR 의 결과인지
- 코드베이스 파악 — `graphify-out/GRAPH_REPORT.md`
