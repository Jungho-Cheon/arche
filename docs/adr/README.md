# Architecture Decision Records (ADR)

이 디렉토리는 Arche 의 *주요 의사결정* 을 시간 순으로 기록한다. ADR 은 코드 자체에서 *읽어낼 수 없는* 정보 — **"왜 이렇게 만들었는가"** — 를 담는 단일 진실의 원천이다.

처음 들어온 빌더/컨트리뷰터를 위한 가이드.

---

## ADR 이 무엇인가

**ADR (Architecture Decision Record)** — 프로젝트의 중요한 의사결정 하나당 *한 파일* 로 기록한 문서. 각 ADR 은 다음을 담는다.

- **Context** — 왜 이 결정이 필요했는가, 어떤 제약과 요구가 있었나.
- **Decision** — 무엇을 선택했는가.
- **Considered Options** — 다른 후보는 무엇이었고 왜 거부됐는가.
- **Consequences** — 이 결정이 코드와 운영에 어떤 영향을 주는가.

ADR 은 *불변에 가깝게* 다룬다. 결정이 바뀌면 *기존 ADR 을 수정* 하는 대신, *새 ADR 로 amend* 또는 *교체* 한다.

---

## 처음 들어왔다면 — 0001 부터 순서대로

현재 ADR 6 개는 의도적으로 *순서대로 읽으면 한 묶음* 이 되도록 구성됐다. 0001 이 가설을 세우고, 0002 가 범위를 좁히고, 0003-0004 가 retrieval 기술 결정, 0005 가 가설 측정 방법, 0006 이 외부 표면 (MCP/REST) 의 모양을 정한다.

| 순서 | ADR | 한 줄 |
|---|---|---|
| 1 | [ADR-0001 — 프로젝트 정체성과 MVP 검증 가설](./0001-project-identity-and-mvp-validation-hypothesis.md) | 왜 이 프로젝트가 존재하는가, MVP 가 무엇을 어떻게 검증하는가 (Pareto 우월 가설) |
| 2 | [ADR-0002 — MVP 범위 경계](./0002-mvp-scope-boundaries.md) | 무엇을 의도적으로 미루는가, post-MVP 복귀 우선순위 |
| 3 | [ADR-0003 — 그래프 진입점 선정 전략](./0003-graph-entry-point-strategy-hybrid-lexical-dense.md) | caller 의 anchor 추출 + Arche 의 어휘 + dense 하이브리드 매칭 |
| 4 | [ADR-0004 — 벡터 인프라 결정](./0004-vector-infra-graph-db-internal-index.md) | 별도 벡터 DB 서비스 미도입, 그래프 DB 내장 인덱스 |
| 5 | [ADR-0005 — 측정 방법론](./0005-measurement-methodology-accuracy-tokens-latency.md) | MCQ + 이유 서술, 정확도/토큰/지연 3 메트릭, 하이브리드 judge |
| 6 | [ADR-0006 — MCP/REST 표면](./0006-mcp-rest-primitives-surface.md) | graph primitives 만 노출, 자연어 미수용, Neo4j MCP 와 공존 |
| 7 | [ADR-0007 — Combined RAG 채택 (정체성 피벗)](./0007-combined-rag-pivot.md) | MVP 가설 미달 후 chunk + graph 결합으로 100% 달성, 정체성을 retrieval orchestrator 로 |
| 8 | [ADR-0008 — EntityConsolidator gating (M6.5 1M 결과)](./0008-entity-consolidator-gating.md) | 1M 측정에서 catastrophic over-merge 발견 → ADR-0007 D2 결정 보류, EntityConsolidator 를 M7 gating 으로 격상 |
| 9 | [ADR-0009 — Context-aware extraction (RFC)](./0009-context-aware-extraction.md) | 추출 단계에 문서 메타 + 기존 graph 동봉, `matched_existing_id` 로 매칭을 *예방* 으로 전환. ADR-0008 의 증상 가림을 root-cause 해법으로. |
| 10 | [ADR-0010 — Multi-agent parallel + cache (RFC)](./0010-multi-agent-parallel-and-cache.md) | 청크 호출 batch parallel + sha256 캐시. graphify Part B 패턴 채택. 1M ingest 30 분 → 8 분 목표. |
| 11 | [ADR-0011 — Step 3 cosine opt-in (RFC)](./0011-step3-cosine-opt-in.md) | Step 3 cosine 매칭 default off. STOPLIST + Consolidator 의 단계별 deprecation 경로. |
| 13 | [ADR-0013 — Agent 친화 API contract (RFC)](./0013-agent-friendly-api-contract.md) | DataEnvelope 통일, 표준 에러 코드, OpenAPI 깊이, idempotency, latency budget, next-action hints. *MVP 조건 (2)*. |
| 14 | [ADR-0014 — MCP HTTP transport (RFC)](./0014-mcp-http-transport.md) | Streamable HTTP transport 추가 + stdio 코드 공유. 사내 인프라 + 외부 agent 양쪽 노출. *MVP 조건 (3)*. |
| 15 | [ADR-0015 — 공유 KB 운영 모델 (RFC)](./0015-shared-kb-operating-model.md) | 단일 KB + namespace 부분 공유. 다회사 개인 KB 시나리오 자연 흡수. *MVP 조건 (4)*. |
| 16 | [ADR-0016 — 에이전트 반복 graph-only + 정량 추출 (RFC)](./0016-agentic-graphonly-and-quantitative-extraction.md) | 측정으로 제품 방향 확정. graph-only 가 graphify 를 압도(FinanceBench 94-97% vs 57.6%, MedHop 30% vs 10%). 답변 LLM 외부화 + 정량-aware 추출 채택. 다음 레버 = 문서 간 엔티티 동일성 해소 (ADR-0017 이 정밀도로 교정). *MVP 조건 (1)*. |
| 17 | [ADR-0017 — 허브 인지 경로 점수](./0017-hub-aware-path-scoring.md) | MedHop 30% 천장의 다수는 병합 부족이 아니라 *정밀도* — promiscuous 허브를 다리로 쓴 가짜 경로. find_path 가 같은 길이면 허브를 덜 거치는 구체적 경로를 우선하고 hub_score 를 노출(끝점 제외 → 금융 무회귀). RELATES_TO 경로 제한으로 출처 노드 경유 크래시/가짜 다리 제거. ADR-0016 D4 교정. |
| 18 | [ADR-0018 — monorepo 구조 + agnostic 경계](./0018-monorepo-and-agnostic-boundaries.md) | 검증 안정화 후 구조 확정. monorepo (apps/api·docs·web-ui + packages 공유 클라이언트), 기업 web-ui 는 OSS/상용 경계 구체화 시 분리. apps/api 의 agnostic 이음매를 코드로: GraphRepository 를 능력별 포트(GraphStore/VectorIndex/LexicalIndex)로 분리, 추출 계약을 도메인으로 끌어올림. 소비 표면은 이미 Agent-agnostic(REST+MCP), 워크스페이스=namespace, auth seam=SSO 대비. |
| 19 | [ADR-0019 — 모델 provider 팩토리 + Anthropic/Voyage 어댑터](./0019-multi-provider-factory.md) | ADR-0018 D3 의 LLM-agnostic 이음매를 두 번째 구현으로 실증. 모델 식별자 접두사(openai/anthropic/voyage)로 어댑터를 고르는 팩토리. Anthropic 추출(중립 계약을 tool-use 로 번역) + Voyage 임베딩(Anthropic 은 임베딩 API 없음). 설정만으로 provider 교체 = OpenAI-free 경로. SDK 는 선택적 의존성 + 지연 import. |

---

## 토픽별 인덱스

### 가설과 범위

- [ADR-0001 — 프로젝트 정체성과 MVP 검증 가설](./0001-project-identity-and-mvp-validation-hypothesis.md)
- [ADR-0002 — MVP 범위 경계](./0002-mvp-scope-boundaries.md)
- [ADR-0007 — Combined RAG 채택 (정체성 피벗)](./0007-combined-rag-pivot.md) — ADR-0001 의 가설 미달 후 정체성 갱신 (ADR-0008 로 amend)
- [ADR-0008 — EntityConsolidator gating (M6.5 1M 결과)](./0008-entity-consolidator-gating.md) — ADR-0007 D2 의 결정 시점 지연, EntityConsolidator 를 M7 gating 으로 격상

### Retrieval / 인덱싱

- [ADR-0003 — 그래프 진입점 선정 전략](./0003-graph-entry-point-strategy-hybrid-lexical-dense.md)
- [ADR-0004 — 벡터 인프라 결정](./0004-vector-infra-graph-db-internal-index.md)

### 측정 / 평가

- [ADR-0005 — 측정 방법론](./0005-measurement-methodology-accuracy-tokens-latency.md)

### 외부 표면 (API / MCP)

- [ADR-0006 — MCP/REST 표면](./0006-mcp-rest-primitives-surface.md)

---

## ADR 작성 규칙

새 ADR 을 추가하려면.

1. 다음 번호로 파일 생성 — `docs/adr/00NN-짧은-제목.md`.
2. 기존 ADR 의 구조를 참고.
   - `# ADR-00NN: 제목`
   - `Status: proposed | accepted | superseded | amended`
   - `Date: YYYY-MM-DD`
   - TL;DR (한 문단 요약 + 필요한 용어 인라인 blockquote).
   - 이 ADR 을 읽는 이유 (선택, 의문 형식으로).
   - 읽기 전 권장 배경 (선택, 선행 ADR 링크).
   - Context — 왜 이 결정이 필요했나.
   - Decision — 무엇을 결정했나.
   - Considered Options — 거부 옵션은 "만약 이걸 택했다면 ___ 문제가 왔을 것" 반사실 추가.
   - Consequences — 즉시 영향 + 코드 작업 시 기억할 점.
   - Related — 연결된 ADR.
3. 기존 ADR 을 *수정* 하지 않는다. 결정이 바뀌면 *새 ADR 로 amend* 또는 *교체* (superseded 표시).
4. amend 된 옛 ADR 상단에 명시적 `> **Amendment (ADR-00MM, YYYY-MM-DD)**: ...` 박스를 추가.

---

## 메타: ADR 톤과 분량

이 디렉토리의 ADR 은 *처음 읽는 빌더/컨트리뷰터* 가 이해할 수 있도록 verbose 하게 작성됐다. 결과적으로 분량이 길지만, 다음을 의도한다.

- *왜* 결정했는가가 *무엇을* 결정했는가만큼 비중을 갖는다.
- 거부된 옵션은 단순한 "거부" 가 아니라 "만약 택했다면 어떤 문제가 왔을지" 를 풀어쓴다.
- LLM·임베딩·BM25 등 자주 등장하는 기술 jargon 은 *처음 등장하는 자리* 에서 inline blockquote 으로 풀이.
- 각 ADR 끝의 "코드 작업 시 기억할 점" 은 그 ADR 이 *실제 코드에 닿는 지점* 을 체크리스트로 정리.

이 톤이 시간이 지나며 *코드 자체가 답하지 못하는* 결정의 이유를 살아 있게 한다.
