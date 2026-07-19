# ADR-0006: MCP/REST 표면 — Graph Primitives, 자연어 미수용

Status: accepted
Date: 2026-06-15

> **Amendment (#140, 2026-07-19)**: 조회 표면에 7번째 read primitive `find_related` 를 더한다. 시드 노드 집합에서 구조적으로 가까운 관련 노드를 근접 순위로 한 번에 회수하는 원자적 순회다 (HippoRAG 의 Personalized PageRank 착상). 답변 생성이 아니라 구조 순회이므로 본 ADR 의 "원자적 graph primitive 만 노출, 자연어 미수용" 원칙에 부합한다. 구현은 기존 get_subgraph 순회 위에 근접 점수를 얹어 저장소 백엔드(Neo4j/Kuzu)와 무관하게 동작하며 새 저장소 기능을 요구하지 않는다. 요약/답변은 여전히 caller(외부 LLM)의 몫이다.
>
> **Amendment (#155, 2026-07-19)**: 검토형 적재 표면에 `ingest_content` 를 더한다. 기존 적재 도구 `ingest_plan` 은 파일 경로만 받았는데, 에이전트가 외부 소스(Jira/Confluence 등)를 자기 MCP 로 읽어와 그 텍스트를 파일 없이 곧장 적재하려면 콘텐츠를 직접 받는 입력이 필요하다. `ingest_content` 는 `{content, source_id}` 를 받아 기존 청크→추출→병합 코어와 plan/preview/commit 사람 검토 게이트를 그대로 재사용한다. 직접 그래프 쓰기를 막는 ADR-0006 D3 는 유지된다 — 콘텐츠 입력도 사람 확인 후에만 커밋되므로 정책 변경이 아니라 입력 모양의 확장(파일과 텍스트)이다. `source_id` 는 파일 경로 자리를 대신하는 논리적 출처 라벨로 idempotent 재적재/차분의 기준이 된다.

## TL;DR

Arche 는 MCP 와 REST API 모두에서 **graph primitives** — `find_entities`, `get_entity`, `get_neighbors`, `find_path`, `get_subgraph`, `get_schema` — 만 노출한다. *자연어 질문 엔드포인트는 두지 않는다.* caller (에이전트 또는 벤치마크 하니스) 가 자체 LLM 사이클로 질문에서 anchor 키워드를 추출한 뒤 primitives 를 호출한다. 이 분리는 (1) MCP 의 통상 패턴과 정렬, (2) Arche 코어에서 쿼리 시점 LLM 의존성 제거, (3) Pareto 우월 가설 (ADR-0001) 의 토큰 회계를 caller 쪽으로 정직하게 이전 — 세 효과가 있다.

> **MCP (Model Context Protocol)** — AI 에이전트가 외부 도구를 표준화된 방식으로 호출하는 프로토콜. 도구는 보통 *원자적 primitives* 로 구성되고, 에이전트가 LLM 사이클로 *어떤 primitive 를 어떤 인자로 부를지* 결정한다.
>
> **primitive** — 추가 분해되지 않는 원자적 작업. 자연어 처리·의도 해석·결과 합성을 포함하지 않는다.

## 이 ADR 을 읽는 이유

- Arche 가 *어떤 표면* 으로 외부와 만나는지 알고 싶다면
- "왜 `/query` 같은 자연어 엔드포인트가 없는가" 가 궁금하다면
- Neo4j MCP 가 이미 존재하는데 *왜 Arche MCP 를 따로 만드는지*
- post-MVP 에서 채팅 기능이 들어올 때 *Arche 의 표면이 어떻게 진화할지*

## 읽기 전 권장 배경

- [ADR-0001 — 프로젝트 정체성과 MVP 검증 가설](./0001-project-identity-and-mvp-validation-hypothesis.md) — Pareto 우월 가설의 토큰 회계 맥락.
- [ADR-0003 — 그래프 진입점 선정 전략](./0003-graph-entry-point-strategy-hybrid-lexical-dense.md) — 본 ADR 이 *어떤 retrieval 동작을 primitive 로 노출할지* 의 근거.

## Context — 왜 이 결정이 필요했나

ADR-0003 의 초기 안은 *"Arche 가 자연어 질문을 받아 내부에서 LLM 으로 anchor 를 추출"* 하는 모델이었다. 이는 두 가지 부담을 만든다.

1. **쿼리 시점 LLM 컴포넌트** — Arche 코어가 쿼리마다 LLM API 를 호출. 추가 의존성·비용·지연.
2. **에이전트와의 중복** — 에이전트는 어차피 자체 LLM 사이클로 *어떤 정보가 필요한지* 를 정한다. 그 결정을 자연어 문장으로 다시 묶어 Arche 에 넘기면, Arche 가 *같은 LLM 사이클을 한 번 더 돈다* . 이중 작업.

또한 **2026 년의 MCP 생태계 통상 패턴은 *primitives 노출*** 이다. 성숙한 MCP 서버들 — GitHub MCP (`list_issues` / `get_issue` / `search_code`), Slack MCP (`list_channels` / `send_message`), Filesystem MCP (`read_file` / `grep`) — 은 모두 자연어가 아닌 *원자적 작업* 을 노출한다. 자연어 해석은 *MCP 의 책임이 아니라 에이전트의 책임* 이라는 분리가 정착되어 있다.

### Neo4j MCP 의 존재가 주는 시사점

Neo4j 도 자체 MCP 서버를 제공한다 ([neo4j.com/docs/mcp](https://neo4j.com/docs/mcp/current/)). 노출되는 도구는 다음 네 가지.

- `get-schema` — 라벨·관계 타입·속성 키 introspection
- `read-cypher` — read-only Cypher 실행
- `write-cypher` — write/schema 변경 Cypher (admin 경고 동반)
- `list-gds-procedures` — Graph Data Science 프로시저 목록

이는 *generic database MCP* 패턴이다. 에이전트가 Cypher 를 *직접 작성* 해 임의의 그래프 작업을 수행할 수 있게 한다. 강력하지만 두 가지 문제가 있다.

1. **에이전트 부담** — 에이전트가 *Cypher 문법 + Arche 의 정확한 스키마 + 하이브리드 매칭 (어휘 + 벡터) 작성법* 을 모두 알아야 한다. `find_entities(["쿠폰"])` 한 줄로 가능한 일을 *full-text index 호출 + vector index 호출 + RRF 결합* Cypher 로 표현하라고 시키는 셈.
2. **안전성** — `write-cypher` 가 노출되면 에이전트가 *우발적 destructive 작업* (예: `MATCH (n) DETACH DELETE n`) 을 할 위험. Neo4j 문서도 "Use only in development environments" 경고.

Arche 가 자체 MCP 를 가져야 하는 이유는 *Neo4j MCP 의 대체* 가 아니라 *그 위의 semantic abstraction layer* 가 필요하기 때문이다. 두 MCP 는 *같은 그래프 DB 인스턴스* 에 동시에 붙을 수 있어 (Neo4j MCP = power user / 디버깅용, Arche MCP = 에이전트의 일상 사용) *경쟁이 아니라 보완* 관계다.

## Decision — 무엇을 결정했나

### D1. MCP 와 REST 모두 graph primitives 만 노출

자연어 엔드포인트 (`/query`, `query_natural_language` MCP tool 등) 는 *MVP 에서 두지 않는다.* caller (에이전트 또는 벤치마크 하니스) 가 자체 LLM 사이클로 의도 해석을 수행하고, 그 결과를 *구조화된 인자* 로 primitives 에 넘긴다.

이 결정은 *MCP 와 REST 양쪽 동일* 하다. REST 의 사람 사용자도 직접 keyword 를 구성한다. *MVP 의 사용자는 본인 (직접 운영자) + 벤치마크 하니스* 이므로 둘 다 primitives 로 충분.

### D2. Primitives 집합 (MVP)

| Primitive | 입력 | 출력 | 용도 |
|---|---|---|---|
| `get_schema()` | (없음) | 엔티티 타입 목록 + 관계 타입 목록 + 타입별 샘플 N 개 | 에이전트가 그래프의 *모양* 을 파악. Neo4j MCP `get-schema` 와 유사한 역할이지만 Arche 의미론 (엔티티/관계/소스) 로 노출 |
| `find_entities(keywords, limit?, types?)` | anchor 키워드 목록, 최대 결과 수, 엔티티 타입 필터 | 매칭 노드 목록 (id, name, aliases, type, score, source_refs) | 진입점 검색. 어휘 + dense 하이브리드 (ADR-0003) 를 *한 호출로 캡슐화* |
| `get_entity(id)` | 노드 id | 노드 속성 전체 + 직접 연결된 엣지 카운트 | 단일 노드 상세 조회 |
| `get_neighbors(id, relation_type?, direction?, hops?)` | 노드 id, 관계 타입 필터, 방향 (in/out/both), hop 수 (기본 1) | 이웃 노드 + 엣지 목록 | 그래프 traversal 의 기본 단위 |
| `find_path(from_id, to_id, max_hops?)` | 출발/도착 노드 id, 최대 hop | 경로 목록 (각 경로는 노드/엣지의 순서) | 두 엔티티 사이 관계 탐색 |
| `get_subgraph(ids, hops?)` | 진입점 노드 id 들, 확장 hop 수 | 진입점들 주변 서브그래프 (노드/엣지 집합) | 진입점 다수에서 *한 번에* 서브그래프 추출 (성능) |

**모든 read primitive 응답은 공통 메타데이터를 포함** — 노드/엣지의 *원본 소스* (파일 경로, 추출 위치), *추가일·수정일 timestamp* . 이는 traversal 결과를 caller 가 LLM 컨텍스트에 넘길 때 *출처 추적* 의 근거가 된다.

### D3. Write 작업은 MCP 에 노출하지 않음

소스 ingest, 그래프 수정, schema 변경 등 *상태를 바꾸는 작업* 은 MCP 에 노출하지 않는다. 이는 다음 경로로 수행된다.

- **CLI / admin REST 엔드포인트** — `arche ingest <directory>` 같은 명령. 본인 (운영자) 만 사용.
- **Neo4j MCP 직접 사용** — 정말 자유로운 Cypher 가 필요하면 power user 가 Neo4j MCP 를 *같은 DB 에 추가로* 붙여 사용 (escape hatch).

이 결정의 근거 — Neo4j 문서도 경고하듯 *LLM 이 만든 write Cypher 는 위험* 하다. MVP 의 단일 환경에서 *에이전트가 본인의 그래프를 부수는 시나리오* 를 원천 차단.

### D4. Caller 의 책임 — 의도 해석과 합성

primitives 가 노출되면 caller 의 일반적인 흐름은 다음과 같다.

```
[자연어 질문] → caller LLM 으로 anchor 키워드 + 의도 해석 →
  find_entities(keywords) → 진입점 노드 N 개 →
  get_neighbors / find_path / get_subgraph 로 traversal →
  결과 서브그래프 →
  caller LLM 으로 최종 답변 생성
```

벤치마크 하니스 (ADR-0001 의 (3) 컬럼 측정) 도 같은 흐름. 즉 **anchor 추출과 답변 생성 두 LLM 호출은 caller 쪽에서 발생** 하고, Arche 는 그 사이의 retrieval 만 책임진다.

토큰 회계 (ADR-0005 D6) 는 *system 전체* 의 토큰을 계산하므로 caller 의 두 LLM 호출도 *Arche 컬럼* 의 토큰으로 합산된다. 즉 *책임 위치만 바뀌고 토큰 합계는 동일* . Pareto 우월 가설 검증에는 영향 없음.

### D5. Post-MVP — 자연어 wrapper 의 진화 경로

MVP 종료 후 *외부 사용자* (본인 외) 가 등장하거나 *Arche 자체가 채팅 기능* 을 제공하게 되면 자연어 입력 수요가 생긴다. 그때의 진화 경로는 **얇은 wrapper 추가** 다.

```
[자연어 질문] → arche 의 chat layer (별도 컴포넌트) →
  LLM 으로 anchor 추출 → 내부적으로 primitives 호출 → 결과 →
  LLM 으로 답변 생성 → [자연어 답변]
```

핵심은 **chat layer 가 Arche 코어와 분리된다** 는 것. 코어는 여전히 graph primitives 만 노출. wrapper 는 *post-MVP 의 별도 컴포넌트* 로 정당화되고 (그때는 채팅이 product surface 이므로), 코어에 LLM 의존성을 끌어들이지 않는다.

이 분리가 *지금 결정* 의 가장 큰 효용 — 미래에 추가될 chat layer 가 *코어의 변경 없이 위에 얹히는* 형태로 진화한다.

### D6. Neo4j MCP 와의 공존 가이드

Arche MCP 와 Neo4j MCP 는 *같은 DB 인스턴스에 동시 attach 가능* . 권장 사용 분리:

| 시나리오 | 권장 도구 |
|---|---|
| 에이전트가 도메인 답을 만들기 위해 그래프를 조회 | **Arche MCP** (semantic primitives) |
| 그래프 schema 디버깅, ad-hoc 분석, GDS 알고리즘 실행 | **Neo4j MCP** (raw Cypher) |
| 데이터 백업/관리/마이그레이션 | Neo4j MCP 또는 직접 Cypher |
| 에이전트의 일상 read 작업 | Arche MCP (안전, 추상화) |
| 에이전트의 write 작업 | *둘 다 권장 안 함* — 운영자 CLI 사용 |

## Considered Options

### 옵션 1 — 자연어 엔드포인트 (`/query`) 만 노출, primitives 숨김

거부. **(a) 에이전트 워크플로와 어긋난다 + (b) 코어에 query-time LLM 의존성을 끌어들인다 + (c) 토큰 이중 계산이 발생한다** . 에이전트는 자체 LLM 으로 *반복적인 탐색 결정* (한 번 검색 → 결과 보고 다음 검색) 을 하는데, 자연어 입출력만 노출되면 그 *결정 사이클이 Arche 의 자연어 처리로 한 번 더 wrap 됨* . 토큰·지연이 누적.

만약 이걸 택했다면, Arche 의 컴포넌트 다이어그램에 *쿼리 시점 LLM* 박스가 영구히 들어왔을 것이고, post-MVP 의 chat 기능이 *이 LLM 박스를 재사용할지 새로 둘지* 가 또 고민거리가 됐을 것이다.

### 옵션 2 — 자연어와 primitives 둘 다 노출 (옵션 Q)

거부. *MVP 단계에서 두 표면을 모두 유지하는 비용이 정당화되지 않는다* . MVP 사용자는 본인 + 벤치마크 하니스뿐이고, 둘 다 primitives 로 충분. 두 표면이 있으면 *문서·테스트·예제* 가 두 배가 되고 *어느 쪽을 쓰는 게 권장인지* 의 결정도 사용자에게 떠넘겨진다.

만약 이걸 택했다면, MVP 종료까지 *자연어 엔드포인트의 품질도 챙겨야* 하는 부담이 추가됐을 것이다. post-MVP 에서 자연어가 필요해질 때 옵션 Q 형태의 wrapper 를 *그때 추가* 하는 게 더 깨끗.

### 옵션 3 — Neo4j MCP 를 그대로 쓰고 Arche MCP 안 만들기

거부. *에이전트의 부담이 너무 크고, 안전성이 떨어진다.* Cypher 작성을 에이전트에게 떠넘기면 (a) *Arche 의 정확한 스키마* (엔티티 타입·관계 타입·속성 명) 를 매번 LLM 컨텍스트에 넣어야 하고, (b) 하이브리드 매칭 (어휘 + 벡터) 같은 *Arche 의 고유 의미론* 을 Cypher 로 표현하라고 시켜야 한다. 또한 write Cypher 노출은 *에이전트가 그래프를 부술 수 있는* 시나리오를 만든다.

Neo4j MCP 는 *power user / 디버깅* 용도로 *공존* 시키는 게 정답이다 (D6).

만약 이걸 택했다면, 에이전트의 매 호출이 *수백 토큰 분량의 Cypher 작성 사고 사슬* 을 동반해, Pareto 우월 가설의 토큰 메트릭이 의미 있게 악화됐을 것이다.

### 옵션 4 — Primitives 노출하되 `find_entities` 는 빼고 *벡터 검색 + 어휘 검색 두 개로 분리*

거부. *에이전트에게 결합 로직을 떠넘기는 셈* . 하이브리드 매칭은 *Arche 의 retrieval 결정* (ADR-0003) 이므로 *한 primitive 안에서 결정* 되는 게 맞다. 에이전트가 *어휘 점수와 벡터 점수를 받아 RRF 로 결합* 하는 건 *재발명* 이다. 단, 정말 *분리된 신호가 필요한* 경우를 위해 `find_entities` 의 응답에 *각 신호의 raw 점수* 를 부록으로 포함시킬 수는 있다 (구현 단계 결정).

## Consequences

### 즉시 영향

- **ADR-0003 D1 step 1** (LLM anchor 추출) 의 책임 주체가 *Arche → caller* 로 이전됨. ADR-0003 본문 갱신 필요.
- **ADR-0001 D3 (3) Arche flow** 가 *caller 의 두 LLM 호출 + Arche 의 primitives 호출* 로 분리됨. ADR-0001 본문 갱신 필요.
- **ADR-0001 컴포넌트 #2** (멀티모달 LLM) 의 *쿼리 시점 멘션 추출* 용도가 제거됨. 컴포넌트 목록 갱신.
- **PRD 의 "쿼리" 섹션** 이 자연어 입력 가정에서 primitives 노출로 재작성.
- **벤치마크 하니스 (ADR-0001 의 (3) 컬럼)** 가 anchor 추출 → primitives 호출 → LLM 답변 생성을 자체 구현. Arche 본체에 없는 코드.

### 코드 작업 시 기억할 점

- Primitives 의 응답 스키마는 *공개 계약* . OpenAPI / MCP tool schema 로 명세화하고 *호환 깨는 변경* 은 별도 ADR.
- Write 작업이 MCP 에 *우발적으로* 노출되지 않게 코드 레벨에서 차단. write 가 필요한 admin 엔드포인트는 *MCP 가 아닌* CLI/REST 로만.
- `get_schema()` 응답에 *embedding 차원, 임베딩 모델 식별자* 같은 메타도 포함하면 에이전트가 *호환되는 임베딩 사용* 을 결정하는 데 도움 (post-MVP 의 멀티 모델 시나리오 대비).
- Neo4j MCP 가 같은 DB 에 attach 됐을 때 *상호 간섭* 없음을 보장 — Arche 가 사용하는 인덱스명·라벨에 충돌 없는 prefix 권장 (`opt_*` 등).
- 토큰 측정 (ADR-0005 D6) 에서 *Arche 컬럼* 의 토큰은 *caller 의 두 LLM 호출 + Arche primitives 호출 시 발생하는 embedding 호출* 의 합. 명세 명확히.

### Post-MVP 진화

- 외부 사용자가 등장하거나 채팅 기능이 필요해지면 *chat layer* (별도 컴포넌트) 를 위에 얹는다. 코어는 변경 없음.
- 다중 테넌트 (ADR-0002 D2 의 복귀 1순위) 가 들어오면 *primitives 의 인자에 workspace_id 가 추가* 되는 형태가 자연스러움. 표면 자체는 깨지지 않음.
- 더 복잡한 traversal 패턴 (Personalized PageRank, PathRAG 류) 이 필요해지면 *새 primitive 추가* (예: `find_central_subgraph`). 기존 primitives 는 그대로.

## Related

- [ADR-0001 — 프로젝트 정체성과 MVP 검증 가설](./0001-project-identity-and-mvp-validation-hypothesis.md) — 토큰 회계의 caller-system 분리 근거.
- [ADR-0003 — 그래프 진입점 선정 전략](./0003-graph-entry-point-strategy-hybrid-lexical-dense.md) — 본 ADR 의 `find_entities` primitive 가 내부에서 수행하는 하이브리드 매칭의 근거.
- [ADR-0005 — 측정 방법론](./0005-measurement-methodology-accuracy-tokens-latency.md) — Arche 컬럼의 토큰 합산 규칙.

### 외부 참고 자료

- [Neo4j MCP Server Documentation](https://neo4j.com/docs/mcp/current/) — generic Cypher MCP. 본 ADR 이 *그 위의 semantic layer* 로 위치하는 근거.
- [Neo4j MCP Tools](https://neo4j.com/docs/mcp/current/tools/) — Neo4j MCP 가 노출하는 4 도구 (`get-schema` / `read-cypher` / `write-cypher` / `list-gds-procedures`) 의 명세.
- [Model Context Protocol Specification](https://modelcontextprotocol.io/) — MCP 의 *primitives 노출* 패턴이 표준화된 출처.
