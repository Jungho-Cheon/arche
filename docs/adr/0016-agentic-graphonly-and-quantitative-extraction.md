# ADR-0016: 제품 방향 — 에이전트 반복 graph-only + 정량-aware 추출, 다음 레버는 문서 간 엔티티 동일성 해소

Status: proposed (RFC)
Date: 2026-06-23
Phase: 측정 기반 방향 확정 (M7-D 직후)
Requires: [ADR-0009](./0009-context-aware-extraction.md), [ADR-0013](./0013-agent-friendly-api-contract.md), [ADR-0014](./0014-mcp-http-transport.md)

## 용어 한 줄 풀이 (처음 등장)

- **graph-only**: 원본 문서를 다시 읽지 않고 *그래프만* 으로 질문에 답하는 방식.
- **에이전트 반복 (agentic)**: 답변 LLM 이 그래프 API 를 *한 번이 아니라 여러 번* 호출해
  스스로 좁혀가며 답을 찾는 방식. (대비: 단발 = 한 번 검색 후 바로 답.)
- **graphify**: 비교 기준이 되는 외부 그래프 도구. 문서마다 그래프를 만들고 에이전트가
  그 위를 질의한다.
- **grep**: 적재 없이 원본 텍스트를 단어로 직접 검색하는 가장 단순한 기준선.
- **MCQ**: 객관식 문항 (multiple-choice question).
- **정량 추출 (quantitative extraction)**: 수치/표/시계열을 값·기간·단위까지 *별도 엔티티
  노드* 로 그래프에 담는 추출.
- **엔티티 동일성 해소 (entity resolution)**: 여러 문서에 흩어진 *같은 대상* (같은 단백질,
  같은 회사 항목) 을 하나의 노드로 병합하는 것.

## TL;DR

2026-06-22~23 측정으로 제품 방향을 확정한다.

1. **소비 방식**: 질의 LLM 을 코어에 내재화한 *단발* 파이프라인을 버리고, **답변 LLM 을
   외부(MCP/REST)로 두고 그래프 프리미티브를 반복 호출** 하는 방식을 제품 기본으로 한다.
   같은 그래프에서 단발 graph-only 45.5% → 에이전트 반복 graph-only 94-97% (FinanceBench
   33-MCQ).
2. **추출 방식**: ingest 가 **수치/표를 값·기간·단위까지 별도 엔티티로** 추출한다 (정량-aware).
   이 한 가지가 graphify(범용 추출, 57.6%)와 우리(94-97%)를 가른 핵심이다.
3. **다음 레버**: 두 도메인(finance 정량 / biomedical 관계) 측정이 일관되게 가리키는
   다음 개선은 **문서 간 엔티티 동일성 해소 강화** 다. 관계-사슬 도메인의 천장(30%)이
   여기서 막힌다.

## 이 ADR 을 읽는 이유

- 초기 설계는 LLM 을 포함하지 않았고, ingest/query 성능을 위해 LLM 을 *내재화* 했으나
  성능이 떨어졌다. 이 ADR 은 그 방향을 데이터로 뒤집는다.
- "graph-only 가 graphify 를 넘는다" 는 MVP 성공 조건이 *실제로 달성됐는지*, 그리고
  무엇 때문에 달성됐는지의 단일 기록.
- 다음 ingest 작업(엔티티 동일성 해소)의 근거.

## Context — 측정 사실 (재현 포함)

### FinanceBench 33-MCQ (정량 도메인)

| 방식 | 정답률 |
|---|---|
| graphify graph-only (에이전트 반복) | 57.6% |
| opentology graph-only (단발 내재화) | 45.5% |
| **opentology graph-only (에이전트 반복, source 미사용)** | **94-97%** (독립 2회: 97.0%, 93.9%) |

- 인용 수치가 그래프 노드에 실재함을 직접 질의로 확인 (환각 아님).
- 두 run 의 오답은 *추출 공백* (대차대조표 합계 미추출 등) — retrieval 실패 아님.

### MedHop 10-MCQ (biomedical 관계 도메인, 일반화 검증)

| 도구 | 정답률 |
|---|---|
| **opentology graph-only** | **30%** |
| graphify graph-only | 10% |
| grep | 0% |

동일 코퍼스(289 PubMed abstract), 동일 gpt-4.1, 동일 에이전트 조건. 순위 일관
(opentology > graphify > grep). grep 0% 는 "공동출현 ≠ 명시 관계" — lexical 검색이
관계 사슬에서 구조적으로 실패함을 입증.

### 왜 opentology 가 graphify 를 이기나 (정량 근거)

| | 문서 간 엔티티 연결 |
|---|---|
| graphify | cross-abstract 엣지 3 / 1,414 (0.2%) — 문서마다 고립된 섬 |
| opentology | 423 엔티티(3,508 중 12%)가 여러 문서에 걸쳐 병합 (ADR-0009 context-aware 매칭) |

graphify 는 abstract 를 잇지 못해 multi-hop 사슬이 끊긴다. opentology 는 ADR-0009 으로
일부 병합해 사슬을 잇는다. **이 cross-doc 병합 유무가 우열을 가른다.**

## Decision

### D1. 에이전트 반복 graph-only 를 제품 기본 소비 방식으로 채택

답변 LLM 을 코어 밖(MCP/REST 클라이언트)에 두고 프리미티브(`find_entities`,
`get_subgraph`, `get_neighbors`, `find_path`)를 반복 호출한다. 코어는 *그래프 접근* 만
책임지고 *답변 합성* 은 외부 에이전트가 한다. 내재화 단발 파이프라인(combined 컬럼 등)은
측정 baseline 으로만 유지한다.

근거: 같은 그래프에서 단발 45.5% → 반복 94-97%. 병목은 그래프 내용이 아니라 *소비 방식*
이었다. 외부화는 ADR-0014(MCP HTTP transport)와 정합.

### D2. 정량-aware 추출을 ingest 의 정식 동작으로 유지

수치/표/시계열을 값·기간·단위 포함 별도 엔티티로 추출한다 (도메인 일반 원칙 — 특정
도메인 항목을 프롬프트에 박지 않음). 이것이 graphify 대비 moat.

가드(체리피킹 방지): 추출 프롬프트에 도메인별 항목명을 넣지 않는다. "표/수치를 완전히
보존" 같은 *도메인 일반* 지시만.

### D3. get_subgraph 견고성 — 읽기 경계 clamp 유지

조밀 그래프에서 모델 상한 초과 문자열(64자 초과 관계 라벨 등) 하나가 서브그래프 응답
전체를 500 으로 죽이던 회귀를 읽기 경계 clamp 로 수정 (`adapters/graph.py` `_clamp`).
max_nodes 상한 1000 → 5000 (큰 컨텍스트 모델에서 recall 회복).

### D4. 다음 ingest 레버 = 문서 간 엔티티 동일성 해소 (별도 작업으로 분리)

관계-사슬 도메인 천장(30%)의 원인은 같은 대상이 문서마다 별도 노드로 남는 것. ADR-0009
의 매칭을 강화(같은 단백질/항목의 cross-doc 병합률 ↑)하는 것이 다음 개선. 본 ADR 은
*방향만* 기록하고 구체 설계는 후속 ADR/spec 으로.

## 정직한 한계 (과대주장 방지)

1. **MedHop n=10** — 순위는 일관되나 통계적 신뢰구간 넓음. 확정 수치 아님.
2. **그래프 *절대* 정답률은 도메인 일반화 안 됨** — finance 97% vs biomedical 30%.
   *우위*(graph > graphify > grep)는 일반화하나 절대값은 추출 완전성에 좌우된다.
3. **서브에이전트 측정** — 결정적 하니스 컬럼으로 고정 필요(후속).
4. **부산물**: ingest 가 "작은 파일 다수"(1,217 abstract)에 처리량이 약함(직렬 persistence
   + 매칭). 상용화 전 개선 후보.

## 상용화 함의

- 가치 제안 = *amortization* — 그래프 1회 빌드 후 저비용 반복 질의. 빌드 비용은 질의량으로
  분산.
- 차별점 = 정량-aware 추출 + 문서 간 엔티티 병합 (graphify 가 둘 다 약함).
- 부속 측정: `eval/reports/2026-06-22-graphify-mcq-baseline/` (BREAKTHROUGH-AGENTIC-GRAPHONLY.md,
  GENERALIZATION-MEDHOP.md, SCALE-IS-THE-VARIABLE.md, AUG-AGENTIC.md).
