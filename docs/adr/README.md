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
| 7 | [ADR-0007 — Combined RAG 채택 (정체성 피벗)](./0007-combined-rag-pivot.md) | ~~chunk + graph 결합 100%, 정체성을 retrieval orchestrator 로~~ **superseded by ADR-0016** — 에이전트 반복 graph-only 가 압도, 정체성은 그래프 KB 로 회귀 |
| 8 | [ADR-0008 — EntityConsolidator gating (M6.5 1M 결과)](./0008-entity-consolidator-gating.md) | ~~over-merge 발견 → EntityConsolidator 를 M7 gating~~ **superseded by ADR-0016/0017** — Combined 분기와 Consolidator gating 폐기, 동일성은 추출단계+정밀도로 |
| 9 | [ADR-0009 — Context-aware extraction (RFC)](./0009-context-aware-extraction.md) | 추출 단계에 문서 메타 + 기존 graph 동봉, `matched_existing_id` 로 매칭을 *예방* 으로 전환. ADR-0008 의 증상 가림을 root-cause 해법으로. |
| 10 | [ADR-0010 — Multi-agent parallel + cache (RFC)](./0010-multi-agent-parallel-and-cache.md) | 청크 호출 batch parallel + sha256 캐시. graphify Part B 패턴 채택. 1M ingest 30 분 → 8 분 목표. |
| 11 | [ADR-0011 — Step 3 cosine opt-in (RFC)](./0011-step3-cosine-opt-in.md) | Step 3 cosine 매칭 default off. STOPLIST + Consolidator 의 단계별 deprecation 경로. |
| 13 | [ADR-0013 — Agent 친화 API contract (RFC)](./0013-agent-friendly-api-contract.md) | DataEnvelope 통일, 표준 에러 코드, OpenAPI 깊이, idempotency, latency budget, next-action hints. *MVP 조건 (2)*. |
| 14 | [ADR-0014 — MCP HTTP transport (RFC)](./0014-mcp-http-transport.md) | Streamable HTTP transport 추가 + stdio 코드 공유. 사내 인프라 + 외부 agent 양쪽 노출. *MVP 조건 (3)*. |
| 15 | [ADR-0015 — 공유 KB 운영 모델 (RFC)](./0015-shared-kb-operating-model.md) | 단일 KB + namespace 부분 공유. 다회사 개인 KB 시나리오 자연 흡수. *MVP 조건 (4)*. |
| 16 | [ADR-0016 — 에이전트 반복 graph-only + 정량 추출 (accepted)](./0016-agentic-graphonly-and-quantitative-extraction.md) | 측정으로 제품 방향 확정. graph-only 가 graphify 를 압도(FinanceBench 94-97% vs 57.6%, MedHop 30% vs 10%). 답변 LLM 외부화 + 정량-aware 추출 채택. 다음 레버 = 문서 간 엔티티 동일성 해소 (ADR-0017 이 정밀도로 교정). *MVP 조건 (1)*. |
| 17 | [ADR-0017 — 허브 인지 경로 점수](./0017-hub-aware-path-scoring.md) | MedHop 30% 천장의 다수는 병합 부족이 아니라 *정밀도* — promiscuous 허브를 다리로 쓴 가짜 경로. find_path 가 같은 길이면 허브를 덜 거치는 구체적 경로를 우선하고 hub_score 를 노출(끝점 제외 → 금융 무회귀). RELATES_TO 경로 제한으로 출처 노드 경유 크래시/가짜 다리 제거. ADR-0016 D4 교정. |
| 18 | [ADR-0018 — monorepo 구조 + agnostic 경계](./0018-monorepo-and-agnostic-boundaries.md) | 검증 안정화 후 구조 확정. monorepo (apps/api, docs, web-ui + packages 공유 클라이언트), 기업 web-ui 는 OSS/상용 경계 구체화 시 분리. apps/api 의 agnostic 이음매를 코드로: GraphRepository 를 능력별 포트(GraphStore/VectorIndex/LexicalIndex)로 분리, 추출 계약을 도메인으로 끌어올림. 소비 표면은 이미 Agent-agnostic(REST+MCP), 워크스페이스=namespace, auth seam=SSO 대비. |
| 19 | [ADR-0019 — 모델 provider 팩토리 + Anthropic/Voyage 어댑터](./0019-multi-provider-factory.md) | ADR-0018 D3 의 LLM-agnostic 이음매를 두 번째 구현으로 실증. 모델 식별자 접두사(openai/anthropic/voyage)로 어댑터를 고르는 팩토리. Anthropic 추출(중립 계약을 tool-use 로 번역) + Voyage 임베딩(Anthropic 은 임베딩 API 없음). 설정만으로 provider 교체 = OpenAI-free 경로. SDK 는 선택적 의존성 + 지연 import. |
| 20 | [ADR-0020 — 투 트랙 저장소 (임베디드 Kuzu + Neo4j)](./0020-two-track-storage-embedded-kuzu-neo4j.md) | ADR-0004 amend. 내장 인덱스를 담는 컴포넌트를 두 갈래로: 체험/단일 사용자는 임베디드(Kuzu, 서버 없이 pip install), 프로덕션(동시성/namespace 공유/규모)은 Neo4j. 능력별 포트(ADR-0018)로 어댑터 추가만 하면 됨. Kuzu 는 유일하게 진짜 in-process + 그래프/벡터/풀텍스트/경로를 한 컴포넌트로 충족(단 upstream 아카이브 → 0.11.3 고정 + 포크 경로). "설정만 교체" 는 포트 계약 수준이고 어댑터/질의는 백엔드별 별개. #146 unblock. |
| 21 | [ADR-0021 — bi-temporal 유효기간 데이터 모델 (경계 확정)](./0021-bitemporal-validity-boundary.md) | 유효 시각(도메인 사실이 참인 구간)을 트랜잭션 시각(`created_at`/`updated_at`)과 audit(ADR-0002 D5 미도입)에서 가른다. MVP 슬라이스 = `Edge.properties` 예약 키 `valid_from`/`valid_to`(RFC3339) 규약만 — 스키마/질의/무효화 변경 0, 전방호환 훅. 정식 필드 승격 / `as_of` 시점 질의 / 삭제 대신 무효화는 post-MVP(코드 적재 ADR 과 묶음)로 미룸. #141. |
| 22 | [ADR-0022 — 전역/주제 질문 지원 경계 (탐지-only 방향 확정)](./0022-global-query-community-detection-boundary.md) | "코퍼스 전체 주제/패턴" 같은 전역 질문은 MVP 미지원. 나중에 지원하면 형태는 커뮤니티 탐지-only — 어떤 노드가 한 군집인지 구조 정보만 프리미티브로, 요약은 에이전트가 서브그래프로 직접(ADR-0016 답변 외부화 유지). GraphRAG 식 커뮤니티 요약 사전 생성은 정체성 위반이라 영구 제외. 재빌드 비용/idempotent 상호작용은 지원 확정 시점 후속 ADR 로. #143. |
| 23 | [ADR-0023 — 임베디드 기본, 공유 서버가 목적지 (보존 이음매 계약)](./0023-embedded-default-shared-destination.md) | 개인은 서버 없는 임베디드(Kuzu)로 바로 쓰고, 목적지는 사내 공유 세컨드브레인(ADR-0015)이다. 둘은 같은 코어의 두 토폴로지라 임베디드 기본이 공유를 닫지 않는다. 보존할 이음매 셋: GraphRepository 포트, `namespace_id` 테넌시, 교체 가능한 MCP 전송(stdio↔HTTP). 서버 이미지 배포/인증/SSO/어드민은 미룸(닫는 게 아니라 나중에 여는 것). 문서도 임베디드 우선으로 재배치. |

---

## 토픽별 인덱스

### 가설과 범위

- [ADR-0001 — 프로젝트 정체성과 MVP 검증 가설](./0001-project-identity-and-mvp-validation-hypothesis.md)
- [ADR-0002 — MVP 범위 경계](./0002-mvp-scope-boundaries.md)
- [ADR-0021 — bi-temporal 유효기간 데이터 모델 (경계 확정)](./0021-bitemporal-validity-boundary.md) — 유효 시각을 audit/트랜잭션 시각과 가름. MVP 는 예약 키 규약만, 정식 필드 승격 / `as_of` / 무효화는 post-MVP
- [ADR-0007 — Combined RAG 채택 (정체성 피벗)](./0007-combined-rag-pivot.md) — **superseded by ADR-0016**. 역사적 기록 (chunk 와 graph 오답 비중첩 측정)
- [ADR-0008 — EntityConsolidator gating (M6.5 1M 결과)](./0008-entity-consolidator-gating.md) — **superseded by ADR-0016/0017**. 역사적 기록 (1M over-merge 진단)
- [ADR-0016 — 에이전트 반복 graph-only + 정량 추출](./0016-agentic-graphonly-and-quantitative-extraction.md) — **현재 제품 방향 (accepted)**. graph-only 가 graphify 압도, 답변 LLM 외부화, 정체성=그래프 KB

### Retrieval / 인덱싱

- [ADR-0003 — 그래프 진입점 선정 전략](./0003-graph-entry-point-strategy-hybrid-lexical-dense.md)
- [ADR-0020 — 투 트랙 저장소 (임베디드 Kuzu + Neo4j)](./0020-two-track-storage-embedded-kuzu-neo4j.md) — ADR-0004 amend. 임베디드 기본값 + Neo4j 프로덕션 이중 트랙
- [ADR-0023 — 임베디드 기본, 공유 서버가 목적지](./0023-embedded-default-shared-destination.md) — 개인 임베디드 기본과 팀 공유 서버는 같은 코어의 두 토폴로지. 보존 이음매(포트/namespace/MCP 전송) 명시, 서버 배포/인증은 미룸
- [ADR-0004 — 벡터 인프라 결정](./0004-vector-infra-graph-db-internal-index.md)

### 측정 / 평가

- [ADR-0005 — 측정 방법론](./0005-measurement-methodology-accuracy-tokens-latency.md)

### 외부 표면 (API / MCP)

- [ADR-0006 — MCP/REST 표면](./0006-mcp-rest-primitives-surface.md)
- [ADR-0022 — 전역/주제 질문 지원 경계](./0022-global-query-community-detection-boundary.md) — 전역 질문 MVP 미지원. 지원 시 커뮤니티 탐지-only(요약은 에이전트), GraphRAG 식 요약 사전 생성은 영구 제외

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
- LLM, 임베딩, BM25 등 자주 등장하는 기술 jargon 은 *처음 등장하는 자리* 에서 inline blockquote 으로 풀이.
- 각 ADR 끝의 "코드 작업 시 기억할 점" 은 그 ADR 이 *실제 코드에 닿는 지점* 을 체크리스트로 정리.

이 톤이 시간이 지나며 *코드 자체가 답하지 못하는* 결정의 이유를 살아 있게 한다.
