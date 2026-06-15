# PRD 3 — Graph Primitives (REST + MCP)

> 본 문서는 *Opentology 가 외부에 노출하는 모든 호출* 의 완전 명세를 담는다. 표면 결정의 근거는 ADR-0006. 본 문서는 *동작 명세* 만 다룬다.

## 0. 표면 일반

### 0.1 두 통로의 1:1 매핑

Opentology 는 같은 작업을 **REST** 와 **MCP** 양쪽으로 노출한다. 두 통로의 *입출력 스키마는 동일* 하다 — 인코딩 (JSON over HTTP vs JSON-RPC over MCP) 만 다르다.

| Primitive | REST | MCP tool |
|---|---|---|
| `get_schema` | `GET /schema` | `get_schema` |
| `find_entities` | `POST /entities/find` | `find_entities` |
| `get_entity` | `GET /entities/{id}` | `get_entity` |
| `get_neighbors` | `POST /entities/{id}/neighbors` | `get_neighbors` |
| `find_path` | `POST /paths/find` | `find_path` |
| `get_subgraph` | `POST /subgraph` | `get_subgraph` |

### 0.2 인증 / 격리

MVP 는 단일 사용자 단일 환경 (ADR-0002 D2). 인증 없음, 모든 호출이 허용된다. *프로덕션 노출은 신뢰 네트워크 안에서만* 한다는 가정.

post-MVP 에서 인증이 들어올 때 — REST 는 표준 `Authorization` 헤더로, MCP 는 stdio 어댑터의 OS-level 신뢰 + HTTP+SSE 어댑터의 토큰 헤더로 확장. 본 MVP 명세에는 인증 필드 없음.

### 0.3 응답 공통 envelope (REST)

성공 응답:

```json
{ "data": <primitive_specific_payload> }
```

에러 응답:

```json
{ "error": { "code": "...", "message": "...", "details": { ... } } }
```

에러 코드 카탈로그는 [§9](#9-에러-코드-카탈로그).

### 0.4 MCP 응답

MCP tool 호출 결과는 *primitive payload 만* 반환 (MCP SDK 가 자체 envelope 을 처리). 에러는 MCP 의 표준 에러 형식으로 전달.

### 0.5 ID 형식

모든 노드·엣지 ID 는 **ULID** (26 자, base32, 시간 정렬 가능) 형태의 문자열. 예: `01HJZX...` . 외부에서 *opaque string* 으로 다룰 것 — 형식 가정 금지.

---

## 1. 공통 메타데이터 스키마

REST 와 MCP 의 모든 응답에서 노드 / 엣지 / 소스 참조가 등장하면 *반드시 다음 형식* 으로 직렬화된다.

### 1.1 Node

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "title": "Node",
  "required": ["id", "name", "type", "aliases", "source_refs", "created_at", "updated_at"],
  "additionalProperties": false,
  "properties": {
    "id":              { "type": "string", "pattern": "^[0-9A-Z]{26}$" },
    "name":            { "type": "string", "maxLength": 200 },
    "type":            { "type": "string", "maxLength": 64 },
    "aliases":         { "type": "array", "items": { "type": "string" } },
    "description":     { "type": ["string", "null"], "maxLength": 500 },
    "properties":      { "type": "object", "additionalProperties": { "type": ["string", "number", "boolean"] } },
    "source_refs":     { "type": "array", "items": { "$ref": "#/$defs/SourceRef" } },
    "created_at":      { "type": "string", "format": "date-time" },
    "updated_at":      { "type": "string", "format": "date-time" }
  }
}
```

*Node 응답에 `embedding` 필드는 포함하지 않는다.* 임베딩은 내부 저장만, 외부 노출 안 함 (응답 크기 절약 + 비공개 결정 유지).

### 1.2 Edge

```json
{
  "type": "object",
  "title": "Edge",
  "required": ["id", "from", "to", "type", "source_refs", "created_at", "updated_at"],
  "additionalProperties": false,
  "properties": {
    "id":              { "type": "string", "pattern": "^[0-9A-Z]{26}$" },
    "from":            { "type": "string", "pattern": "^[0-9A-Z]{26}$" },
    "to":              { "type": "string", "pattern": "^[0-9A-Z]{26}$" },
    "type":            { "type": "string", "maxLength": 64 },
    "properties":      { "type": "object" },
    "source_refs":     { "type": "array", "items": { "$ref": "#/$defs/SourceRef" } },
    "created_at":      { "type": "string", "format": "date-time" },
    "updated_at":      { "type": "string", "format": "date-time" }
  }
}
```

### 1.3 SourceRef

```json
{
  "type": "object",
  "title": "SourceRef",
  "required": ["source_path"],
  "additionalProperties": false,
  "properties": {
    "source_path":   { "type": "string", "description": "원본 파일의 절대 경로 (ingest 시점 기준)" },
    "chunk_index":   { "type": ["integer", "null"], "minimum": 0 },
    "total_chunks":  { "type": ["integer", "null"], "minimum": 1 }
  }
}
```

`chunk_index` 가 `null` 이면 *분할되지 않은 단일 소스* 에서 추출됐다는 의미.

---

## 2. `get_schema`

그래프의 *모양* (엔티티 타입 / 관계 타입 / 통계) 을 조회. 에이전트가 *어떤 종류의 노드와 엣지가 있는지* 파악하기 위한 첫 호출.

### 2.1 REST

```
GET /schema
```

요청 본문 없음.

### 2.2 MCP tool

```
name: get_schema
description: "Inspect the shape of the knowledge graph — entity types, relation types, counts, and example nodes per type."
input_schema: { "type": "object", "additionalProperties": false, "properties": {} }
```

### 2.3 응답

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["entity_types", "relation_types", "embedding_info"],
  "additionalProperties": false,
  "properties": {
    "entity_types": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "count", "examples"],
        "additionalProperties": false,
        "properties": {
          "type":     { "type": "string" },
          "count":    { "type": "integer", "minimum": 0 },
          "examples": {
            "type": "array",
            "maxItems": 5,
            "items": { "type": "object", "required": ["id", "name"], "properties": { "id": { "type": "string" }, "name": { "type": "string" } } }
          }
        }
      }
    },
    "relation_types": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "count"],
        "additionalProperties": false,
        "properties": {
          "type":  { "type": "string" },
          "count": { "type": "integer", "minimum": 0 },
          "common_pairs": {
            "type": "array",
            "maxItems": 5,
            "items": {
              "type": "object",
              "properties": {
                "from_type": { "type": "string" },
                "to_type":   { "type": "string" },
                "count":     { "type": "integer", "minimum": 0 }
              }
            }
          }
        }
      }
    },
    "embedding_info": {
      "type": "object",
      "required": ["model", "dimension"],
      "additionalProperties": false,
      "properties": {
        "model":     { "type": "string", "description": "임베딩 모델 식별자 (예: openai/text-embedding-3-small)" },
        "dimension": { "type": "integer", "minimum": 1 }
      }
    }
  }
}
```

`embedding_info` 는 *caller 가 호환되는 임베딩으로 같은 시스템에 정렬* 할 수 있게 노출 (ADR-0006 D5 의 future-friendly slot 과 정합).

---

## 3. `find_entities`

자연어 키워드 (anchor) 를 받아 그래프 내 매칭 노드를 *어휘 + dense 하이브리드* 로 반환. ADR-0003 의 진입점 선정 로직이 이 primitive 안에서 캡슐화된다.

### 3.1 REST

```
POST /entities/find
Content-Type: application/json
```

### 3.2 MCP tool

```
name: find_entities
description: "Find graph nodes matching one or more anchor keywords using lexical + dense vector hybrid retrieval. Caller is expected to have extracted these keywords from a user question."
```

### 3.3 입력

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["keywords"],
  "additionalProperties": false,
  "properties": {
    "keywords": {
      "type": "array",
      "minItems": 1,
      "maxItems": 32,
      "items": { "type": "string", "minLength": 1, "maxLength": 200 },
      "description": "Anchor keywords. Each is a canonical name or alias extracted from a user question."
    },
    "types": {
      "type": "array",
      "items": { "type": "string", "minLength": 1, "maxLength": 64 },
      "description": "Optional filter — only return nodes whose type is in this list."
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 50,
      "default": 10
    },
    "include_scores": {
      "type": "boolean",
      "default": false,
      "description": "If true, include raw lexical and dense scores per match for debugging or custom re-ranking."
    }
  }
}
```

### 3.4 출력

```json
{
  "type": "object",
  "required": ["matches"],
  "additionalProperties": false,
  "properties": {
    "matches": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["node", "score", "matched_keyword"],
        "additionalProperties": false,
        "properties": {
          "node":            { "$ref": "#/$defs/Node" },
          "score":           { "type": "number", "minimum": 0, "maximum": 1, "description": "Fused score after Reciprocal Rank Fusion of lexical + dense." },
          "matched_keyword": { "type": "string", "description": "어느 input keyword 가 이 노드를 매칭시켰는지" },
          "scores": {
            "type": "object",
            "description": "Only present if include_scores=true.",
            "properties": {
              "lexical": { "type": "number", "minimum": 0 },
              "dense":   { "type": "number", "minimum": 0, "maximum": 1 }
            }
          }
        }
      }
    }
  }
}
```

### 3.5 매칭 알고리즘 (ADR-0003 D1)

각 keyword 에 대해:

1. **어휘 매칭** — 노드의 `name` 또는 `aliases` 에 대한 BM25 검색 (또는 그래프 DB 의 내장 full-text 인덱스). 결과 top-k.
2. **dense 매칭** — keyword 의 임베딩을 server-side 에서 계산 → 노드 임베딩과 ANN 검색. 결과 top-k.
3. **결합** — 두 결과를 RRF (Reciprocal Rank Fusion, k=60 권장) 로 합쳐 fused score 산출.

여러 keyword 의 결과는 *노드 ID 단위 union* — 같은 노드가 여러 keyword 에서 나왔다면 *가장 높은 점수* 유지, `matched_keyword` 는 가장 높은 점수를 만든 keyword.

---

## 4. `get_entity`

ID 로 단일 노드 상세 조회.

### 4.1 REST

```
GET /entities/{id}
```

### 4.2 MCP tool

```
name: get_entity
description: "Fetch full details of a single node by its ID, including direct edge counts per relation type."
```

### 4.3 입력 (MCP)

```json
{
  "type": "object",
  "required": ["id"],
  "additionalProperties": false,
  "properties": {
    "id": { "type": "string", "pattern": "^[0-9A-Z]{26}$" }
  }
}
```

### 4.4 출력

```json
{
  "type": "object",
  "required": ["node", "edge_counts"],
  "additionalProperties": false,
  "properties": {
    "node": { "$ref": "#/$defs/Node" },
    "edge_counts": {
      "type": "object",
      "description": "이 노드에 연결된 엣지의 *방향 × 관계 타입* 카운트. 에이전트가 get_neighbors 호출 전에 *어느 방향으로 얼마나 확장될지* 가늠 가능.",
      "additionalProperties": false,
      "properties": {
        "outgoing": { "type": "object", "additionalProperties": { "type": "integer", "minimum": 0 } },
        "incoming": { "type": "object", "additionalProperties": { "type": "integer", "minimum": 0 } }
      }
    }
  }
}
```

ID 존재하지 않으면 `error.code = "entity_not_found"`, HTTP 404.

---

## 5. `get_neighbors`

한 노드의 이웃 (1 hop 또는 N hop) 조회. 그래프 traversal 의 기본 단위.

### 5.1 REST

```
POST /entities/{id}/neighbors
Content-Type: application/json
```

### 5.2 MCP tool

```
name: get_neighbors
description: "Get neighbors of a node, optionally filtered by relation type and direction, expanded up to N hops."
```

### 5.3 입력

```json
{
  "type": "object",
  "required": ["id"],
  "additionalProperties": false,
  "properties": {
    "id": { "type": "string", "pattern": "^[0-9A-Z]{26}$" },
    "relation_types": {
      "type": "array",
      "items": { "type": "string", "minLength": 1, "maxLength": 64 },
      "description": "이 타입의 엣지만 따라간다. 비우면 모든 타입."
    },
    "direction": {
      "type": "string",
      "enum": ["outgoing", "incoming", "both"],
      "default": "both"
    },
    "hops": {
      "type": "integer",
      "minimum": 1,
      "maximum": 5,
      "default": 1,
      "description": "확장 hop 수. 2 이상이면 노드 수가 급격히 증가할 수 있으므로 max_nodes 도 함께 설정 권장."
    },
    "max_nodes": {
      "type": "integer",
      "minimum": 1,
      "maximum": 500,
      "default": 100,
      "description": "결과 노드 수 상한. 초과하면 *진입점에서 거리 가까운 순* 으로 잘림."
    }
  }
}
```

### 5.4 출력

```json
{
  "type": "object",
  "required": ["nodes", "edges", "truncated"],
  "additionalProperties": false,
  "properties": {
    "nodes": { "type": "array", "items": { "$ref": "#/$defs/Node" } },
    "edges": { "type": "array", "items": { "$ref": "#/$defs/Edge" } },
    "truncated": {
      "type": "boolean",
      "description": "max_nodes 에 의해 결과가 잘렸는지 여부."
    }
  }
}
```

`nodes` 에는 *진입점 노드 자체도 포함* (caller 가 진입점을 별도 추적할 필요 없게).

---

## 6. `find_path`

두 노드 사이의 관계 경로 탐색. multi-hop 추론의 핵심.

### 6.1 REST

```
POST /paths/find
Content-Type: application/json
```

### 6.2 MCP tool

```
name: find_path
description: "Find paths between two nodes — useful when reasoning about *how* two entities are related (e.g. 'why does coupon X apply to product Y')."
```

### 6.3 입력

```json
{
  "type": "object",
  "required": ["from_id", "to_id"],
  "additionalProperties": false,
  "properties": {
    "from_id":     { "type": "string", "pattern": "^[0-9A-Z]{26}$" },
    "to_id":       { "type": "string", "pattern": "^[0-9A-Z]{26}$" },
    "max_hops":    { "type": "integer", "minimum": 1, "maximum": 6, "default": 4 },
    "max_paths":   { "type": "integer", "minimum": 1, "maximum": 20, "default": 5, "description": "반환할 경로 상한. 짧은 경로 우선." },
    "relation_types": {
      "type": "array",
      "items": { "type": "string", "minLength": 1, "maxLength": 64 },
      "description": "이 타입의 엣지만 통과 허용. 비우면 모든 타입."
    }
  }
}
```

### 6.4 출력

```json
{
  "type": "object",
  "required": ["paths"],
  "additionalProperties": false,
  "properties": {
    "paths": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["nodes", "edges", "length"],
        "additionalProperties": false,
        "properties": {
          "nodes":  { "type": "array", "items": { "$ref": "#/$defs/Node" }, "description": "경로 상의 노드 순서 — index 0 은 from, 마지막은 to." },
          "edges":  { "type": "array", "items": { "$ref": "#/$defs/Edge" }, "description": "경로 상의 엣지 순서 — edges[i] 는 nodes[i] → nodes[i+1]." },
          "length": { "type": "integer", "minimum": 1, "description": "엣지 수 (hop 수)." }
        }
      }
    }
  }
}
```

경로가 없으면 `paths: []` 빈 배열. *에러 아님.*

---

## 7. `get_subgraph`

여러 진입점 노드 주변의 서브그래프를 *한 번에* 추출. `get_neighbors` 를 여러 번 호출하는 패턴의 단축. 측정 하니스 (PRD 4) 가 가장 자주 쓰는 primitive.

### 7.1 REST

```
POST /subgraph
Content-Type: application/json
```

### 7.2 MCP tool

```
name: get_subgraph
description: "Extract a subgraph centered on multiple entry-point nodes, expanded N hops. Returns deduplicated nodes and edges within the radius."
```

### 7.3 입력

```json
{
  "type": "object",
  "required": ["entry_ids"],
  "additionalProperties": false,
  "properties": {
    "entry_ids": {
      "type": "array",
      "minItems": 1,
      "maxItems": 20,
      "items": { "type": "string", "pattern": "^[0-9A-Z]{26}$" }
    },
    "hops": {
      "type": "integer",
      "minimum": 1,
      "maximum": 4,
      "default": 2
    },
    "max_nodes": {
      "type": "integer",
      "minimum": 1,
      "maximum": 1000,
      "default": 200
    },
    "relation_types": {
      "type": "array",
      "items": { "type": "string", "minLength": 1, "maxLength": 64 }
    }
  }
}
```

### 7.4 출력

`get_neighbors` 와 동일 구조.

```json
{
  "type": "object",
  "required": ["nodes", "edges", "entry_ids", "truncated"],
  "additionalProperties": false,
  "properties": {
    "nodes":     { "type": "array", "items": { "$ref": "#/$defs/Node" } },
    "edges":     { "type": "array", "items": { "$ref": "#/$defs/Edge" } },
    "entry_ids": { "type": "array", "items": { "type": "string" }, "description": "echo of input — caller 가 결과 안에서 진입점을 구분할 수 있게." },
    "truncated": { "type": "boolean" }
  }
}
```

`nodes` / `edges` 는 *중복 제거* 된 union. 같은 노드가 여러 진입점에서 도달 가능해도 한 번만 포함.

---

## 8. MCP 어댑터

### 8.1 두 transport

| Transport | 용도 | MVP |
|---|---|---|
| `stdio` | 로컬 에이전트 (Claude Desktop, Cursor 등) | **지원** |
| `HTTP+SSE` | 원격 에이전트 | post-MVP |

### 8.2 stdio 어댑터

설치된 `opentology` CLI 의 서브커맨드.

```
opentology mcp serve --stdio
```

표준 MCP 프로토콜 (JSON-RPC over stdio) 로 위 6 primitive 를 노출.

### 8.3 tool 등록 manifest

MCP 서버가 시작 시 *위 6 tool 의 schema* 를 announce. 각 tool 의 `input_schema` 는 본 PRD 의 §2-7 에 정의된 JSON Schema 와 *완전 동일* . 변경 시 본 PRD 와 코드 모두 갱신해야 한다.

---

## 9. 에러 코드 카탈로그

| HTTP | code | 의미 |
|---|---|---|
| 400 | `invalid_input` | 요청 본문이 스키마와 맞지 않음. `details` 에 위반 필드. |
| 404 | `entity_not_found` | `get_entity` / `get_neighbors` / `find_path` 의 ID 가 그래프에 없음. |
| 422 | `unprocessable` | 스키마는 맞지만 의미적으로 처리 불가 (예: `find_path` 의 from_id == to_id). |
| 429 | `rate_limited` | (post-MVP) 호출 빈도 제한 초과. MVP 에서는 사용 안 함. |
| 500 | `internal_error` | 예기치 못한 서버 오류. `details` 에 trace_id (로그 추적용). |
| 503 | `dependency_unavailable` | 그래프 DB 또는 임베딩 모델이 응답하지 않음. |

MCP 에서는 위 code 를 MCP 표준 에러의 `data` 필드에 포함.

---

## 10. 동작 가정과 한계

### 10.1 일관성 모델

Read primitive (6 개 모두) 는 *최종 일관성* (eventually consistent) 을 가정. ingestion 직후 수 초 이내에 read 호출이 와도 *방금 적재된 노드가 보이지 않을 수 있음* . MVP 에서는 *그래프 DB 의 기본 동작에 의존* — 별도 강한 일관성 보장 안 함.

### 10.2 동시성

ingestion 과 read 가 동시에 일어나도 *치명적이지 않다* — read 가 일부 노드를 못 볼 뿐. write 잠금 없음.

### 10.3 응답 크기 상한

| Primitive | 응답 노드 수 상한 | 응답 엣지 수 상한 |
|---|---|---|
| `find_entities` | 50 (input.limit) | — |
| `get_entity` | 1 | — |
| `get_neighbors` | 500 (input.max_nodes) | ≤ 노드 수 × 5 |
| `find_path` | 경로 × 노드 ≤ 20 × 6 | 경로 × hop ≤ 20 × 6 |
| `get_subgraph` | 1000 (input.max_nodes) | ≤ 노드 수 × 5 |

상한 초과 시 `truncated: true` 반환 + 가까운 노드 우선 잘림.

---

## 11. 미정 결정 (구현 설계 단계)

1. **RRF 의 k 파라미터** — 60 이 표준이지만 도메인별 조정 가능.
2. **`get_neighbors` / `get_subgraph` 에서 "거리 가까운 순" 잘림 알고리즘** — BFS 우선순위 / Personalized PageRank seed 위치 / heuristic 중. 측정 결과 기반 결정.
3. **`find_path` 의 알고리즘** — Dijkstra (모든 엣지 동일 가중치 가정) / k-shortest paths / BFS. 그래프 DB 벤더의 native 지원 여부에 따라.
4. **응답 직렬화에 압축** — gzip / brotli. MCP stdio 에서는 의미 작음, HTTP 에서는 의미 있음.
5. **로그/관찰가능성** — 각 primitive 호출의 trace_id, latency, response size 로깅 형식.

---

## 12. Out of scope (MVP 에서 노출 안 함)

- **write primitives** (create_entity / create_relation / delete_*) — ADR-0006 D3, admin CLI 만 가능.
- **자연어 질의 엔드포인트** (`/query`) — ADR-0006 D1, caller 책임.
- **bulk export / import** — admin 도구로 분리.
- **GraphQL 또는 gRPC 표면** — REST + MCP 로 충분.
- **인증 / RBAC** — ADR-0002 D2.
- **subscription / streaming** — 단발 요청만 (ADR-0001 D3 의 단발 가설).

---

## 참조 ADR

- [ADR-0001 D3 — Opentology 컬럼의 primitives 사용 흐름](../adr/0001-project-identity-and-mvp-validation-hypothesis.md)
- [ADR-0003 D1 — find_entities 의 하이브리드 매칭 알고리즘](../adr/0003-graph-entry-point-strategy-hybrid-lexical-dense.md)
- [ADR-0004 D1 — 그래프 DB 내장 인덱스 (BM25 + vector)](../adr/0004-vector-infra-graph-db-internal-index.md)
- [ADR-0006 — MCP/REST 표면 결정의 본체](../adr/0006-mcp-rest-primitives-surface.md)
