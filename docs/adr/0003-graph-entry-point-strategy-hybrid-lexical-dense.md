# ADR-0003: 그래프 진입점 선정 전략 — 어휘 매칭 + dense 임베딩 하이브리드

Status: accepted
Date: 2026-06-15

## TL;DR

진입점 선정은 두 책임으로 분리된다. **(1) caller 가 자체 LLM 사이클로 질문에서 anchor 키워드 (정규명 + 별칭) 를 추출** 하고, **(2) Opentology 가 받은 키워드를 그래프 내 엔티티에 *어휘 매칭 (BM25 류) + 노드 단위 dense 임베딩 유사도* 두 신호를 결합해 매칭** 한다. (1) 이 caller 책임인 근거는 ADR-0006 (MCP/REST 표면) 참조. (2) 가 어휘 단독·dense 단독이 아닌 *하이브리드* 인 이유는 (a) 2025-2026 벤치에서 두 신호의 결합이 단독 대비 일관되게 우월하고, (b) 본인의 dogfooding 도메인 (상거래) 은 식별자 중심이라 BM25 가 강한 영역이지만, (c) 범용성 확장 시 dense 가 흡수해야 할 별칭/의역 케이스가 있기 때문이다.

> **BM25** — 1990 년대부터 검색엔진의 디폴트 어휘 매칭 알고리즘. 단어 빈도와 문서 길이를 함께 고려하는 *통계적 어휘 점수* . 임베딩이 아니라 *단어 자체* 의 일치를 본다.
>
> **dense 임베딩 / dense 벡터** — 텍스트를 고정 차원 (예: 1024) 의 실수 벡터로 변환한 결과. 코사인 유사도가 *의미 유사도* 와 대략 일치한다.
>
> **anchor / 진입점 노드** — 그래프 traversal 의 시작 노드. 질문이 묻는 엔티티에 대응하는 그래프 내 노드들.

## 이 ADR 을 읽는 이유

- Opentology 의 (3) 컬럼 — 그래프 노드 RAG + 탐색 — 이 *질문 → 진입점* 단계를 어떻게 푸는지 알고 싶다면
- "왜 dense 임베딩 만 쓰지 않는가" 또는 "왜 BM25 만 쓰지 않는가" 가 궁금하다면
- 본인의 도메인이 상거래가 아닐 때 (생물학·연구 문헌 등) 진입점 전략이 어떻게 바뀔 여지가 있는지

## 읽기 전 권장 배경

- [ADR-0001 — 프로젝트 정체성과 MVP 검증 가설](./0001-project-identity-and-mvp-validation-hypothesis.md) 이 *왜 진입점이 중요한가* 의 가설 맥락을 제공.

## Context — 왜 이 결정이 필요했나

그래프 노드 RAG (ADR-0001 의 (3) 컬럼) 의 정확도는 두 단계의 곱으로 결정된다.

1. **진입점 선정** — 질문에서 어떤 노드들을 *시작점* 으로 잡는가.
2. **Traversal** — 진입점에서 출발해 그래프를 어떻게 순회하는가.

(2) 는 정교한 알고리즘 (Personalized PageRank, 관계 경로 prune 등) 이 있어도, (1) 이 틀린 노드를 잡으면 *전체가 실패한다* . 그래서 (1) 의 품질이 (3) 컬럼 전체 정확도의 상한을 정한다.

진입점 선정의 후보 전략은 2025-2026 시점에 네 갈래로 정리됐다.

### (a) 어휘 매칭 (BM25 / 희소 검색)

옛 검색엔진 알고리즘. *식별자 중심 도메인* 에서 놀라울 정도로 강하다. 2026 년 한 금융 문서 벤치에서 BM25 가 OpenAI 의 최신 text-embedding-3-large 보다 거의 모든 메트릭에서 더 우수했다 — 회사명·SKU·티커·법령 조항 번호 같은 *정확히 같은 단어가 매칭되어야 하는* 도메인 특성 때문. 인프라 비용은 가장 낮다. 단점은 *동의어/의역* 에 약함.

### (b) 밀집 벡터 (dense 단독)

지금까지 RAG 의 디폴트. 동의어·의역에 강하다 ("주문 취소" 와 "결제 환불"). 단점은 (1) 식별자에 약함, (2) 임베딩 인프라가 무거움, (3) *식별자가 본문에 그대로 등장하는* 도메인에서는 BM25 보다 떨어질 수 있음.

### (c) 하이브리드 (BM25 + 밀집)

두 결과를 Reciprocal Rank Fusion (RRF) 같은 방식으로 결합. 2025-2026 벤치에서 *BM25 단독 또는 dense 단독 대비 15-30% recall 향상* 이 일관되게 보고된다. 인프라 비용은 두 인덱스를 다 운영하는 만큼 증가하지만, 그래프 DB 가 두 인덱스를 모두 내장 제공하면 (ADR-0004 참고) *서비스 수* 는 늘지 않는다.

### (d) LLM 기반 anchor 추출 → 그래프 직접 매칭

2025 년 등장한 BYOKG-RAG, AnchorRAG 가 대표. 핵심 아이디어 — *진입점을 검색으로 찾지 말고, LLM 에 질문을 한 번 더 통과시켜 "이 질문이 언급한 엔티티는 X, Y, Z 다" 라는 답을 받은 뒤 그 이름들을 그래프 노드 이름에 직접 매칭* . 매칭은 (1) 정확 / fuzzy 문자열, (2) 노드 *이름만* 대상의 dense 임베딩 인덱스, (3) 둘의 union — 셋 중 하나로. 이 접근은 *그래프의 모든 노드를 임베딩하지 않아도* 진입점을 잡을 수 있게 한다.

### Traversal 측면의 동시 진화

같은 시기에 traversal 도 진화했다 — HippoRAG2 (ICML 2025) 의 Personalized PageRank, PathRAG (2025) 의 관계 경로 pruning, LightRAG 의 이원화 인덱스. 한 2026 비교 연구의 의료 도메인 다중 hop 정확도: HippoRAG2 66.28 / LightRAG 63.32 / HippoRAG 56.14 / MS GraphRAG (local) 38.63. *진입점 품질이 충분히 좋으면 traversal 알고리즘이 다양해도 비슷한 정확도에 수렴* 하는 패턴이 관찰된다.

## Decision — 무엇을 결정했나

### D1. 진입점 선정 = (caller 의 anchor 추출) + (Opentology 의 하이브리드 매칭)

질문 → 진입점 노드의 흐름을 두 책임으로 분리한다.

**caller 책임** (Opentology 의 컴포넌트가 아님):

1. **LLM anchor 추출** — caller (에이전트 또는 벤치마크 하니스) 가 자체 LLM 사이클로 질문에서 *언급된 엔티티의 정규명 + 가능한 별칭* 을 추출한다. 권장은 LLM 에 정규명·별칭을 JSON 으로 함께 반환하라고 시키는 것. 자세한 분리 근거는 ADR-0006 참조.

**Opentology 책임** (`find_entities(keywords, ...)` primitive 안에서 일어남):

2. **어휘 매칭** — caller 가 보낸 키워드 (anchor 정규명·별칭) 를 그래프 내 엔티티 이름·별칭에 *정확 / fuzzy 문자열 매칭* (BM25 류). 식별자 중심 도메인 (상거래) 에서 강한 신호.
3. **dense 임베딩 유사도** — Opentology 가 받은 키워드를 *server-side 에서 임베딩* 한 뒤, 노드 단위로 저장된 임베딩과의 유사도를 ANN 인덱스로 조회. 어휘가 놓치는 동의어/의역 케이스를 흡수.

두 신호 (2), (3) 을 Reciprocal Rank Fusion 또는 유사한 결합 함수로 합쳐 진입점 top-k 를 결정한다. 결합 함수의 구체 선택과 k 값은 *구현 설계 단계* 에서 결정. *각 신호의 raw 점수를 응답 부록으로 노출* 할지도 구현 단계 결정 (ADR-0006 옵션 4 거부 사유 참조).

### D2. 노드 단위 임베딩 — *청크가 아닌* 엔티티 노드

dense 임베딩은 *엔티티 노드 단위* 에 둔다. 노드의 어떤 속성 (이름만 / 이름 + 별칭 / 이름 + 별칭 + 짧은 설명) 을 임베딩할지는 구현 설계 단계 결정.

이 결정의 의미는 두 가지다.

- **인덱스 크기 최소화** — 노드 이름은 짧으므로 임베딩 인덱스가 청크 임베딩 인덱스보다 한참 작다. 그래프 노드가 100만 개여도 인덱스 크기는 일반 RAG 의 청크 임베딩보다 작다.
- **검증 가설 (ADR-0001 D2) 의 통제 변수와 정합** — 비교 대상인 청크 벡터 RAG 가 *청크 임베딩* 을 쓰고, Opentology 가 *노드 임베딩* 을 쓴다. 정확도 차이의 원인이 *retrieval 단위* 에서 비롯됨을 보장.

### D3. 별칭 정규화는 ingest 단계 (Opentology) + query 단계 (caller) 둘 다

별칭 처리는 두 시점에 들어가는데, *책임 위치가 다르다* .

- **Ingest 시 (Opentology 책임)** — LLM 이 소스에서 엔티티를 추출할 때 *정규명 + 본문에 등장하는 변형 표현* 을 별칭 속성으로 함께 저장. 그래프 자체가 별칭 사전을 가진다.
- **Query 시 (caller 책임)** — caller 의 LLM 이 질문에서 anchor 를 추출할 때 *정규명 + 가능한 별칭* 을 함께 반환. 둘 다를 `find_entities(keywords)` 의 keywords 인자에 포함.

이 이중 정규화가 식별자 중심 도메인 (상거래) 의 BM25 우월성을 *별칭이 있는 영역에서도* 유지하게 한다.

### D4. Traversal 알고리즘은 ADR 레벨에서 결정하지 않음

진입점 *이후* 의 traversal 전략 (PPR, 관계 경로 prune, k-hop expansion 등) 은 *구현 설계 단계* 에서 결정한다. ADR-0003 은 *진입점 선정* 만 다룬다. 이 분리의 이유 두 가지:

- 진입점 선정은 *전체 정확도의 상한* 을 정하므로 ADR 수준에서 명시할 가치가 있다.
- Traversal 은 *상한 안에서의 정확도-비용 트레이드오프* 이므로 측정 결과를 보고 조정한다.

## Considered Options

### 옵션 1 — dense 단독

거부. *식별자 중심 도메인에서 BM25 보다 약하다* . 2026 금융 벤치 결과가 이를 명확히 보여줬다. 상거래 검증 도메인은 SKU · 쿠폰 코드 · 카테고리명 같은 식별자가 본문에 그대로 등장하므로 dense 단독은 *불필요하게 약한 신호* 가 된다.

만약 이걸 택했다면, 상거래 검증 도메인에서 그래프 노드 RAG (3) 가 청크 벡터 RAG (2) 를 명확히 이기지 못해 *가설이 검증되지 않은 채* MVP 가 종료됐을 가능성이 있다.

### 옵션 2 — BM25 단독 + 노드 임베딩 없음

거부. *범용성을 잃는다* . 상거래에서는 충분하지만 사내 위키 ("그 배포하는 거" → "deployment system") 나 연구 문헌 (별칭 폭발) 으로 확장 시 동의어/의역을 잡지 못한다. dense 임베딩을 처음부터 두면 도메인 확장 시 *코드 변경 없이* 동일 시스템이 작동.

또한 ADR-0001 의 검증 통제 변수 — *동일 임베딩 모델* 이 청크 RAG 와 Opentology 양쪽에 적용 — 가 무너진다. Opentology 가 임베딩을 쓰지 않으면 두 시스템의 인프라가 *너무 달라져* 비교의 통제가 어려워진다.

만약 이걸 택했다면, MVP 검증 자체는 가능했겠지만 *상거래에서 잘 됐다는 결과* 가 다른 도메인으로 일반화되지 않아 *post-MVP 시작 시* 진입점 전략을 갈아엎어야 했을 것이다.

### 옵션 3 — LLM anchor 추출 없이 직접 hybrid 검색

거부. *anchor 추출이 정확도를 의미 있게 올린다* . 2025 BYOKG-RAG / AnchorRAG 결과가 이를 보여준다. 추출 단계의 추가 LLM 호출 비용은 있지만, 한 번의 호출로 *검색 공간을 그래프 전체에서 추출된 멘션 주변으로* 좁히는 효과가 크다. *anchor 가 그래프의 어떤 노드에 매칭되는지* 는 어휘+dense 하이브리드로 빠르게 풀린다.

만약 이걸 택했다면, hybrid 검색이 *질문 전체에 대해* 그래프 전체를 훑게 되어 (a) 검색 비용 증가, (b) 노이즈 진입점이 많아짐.

### 옵션 4 — Microsoft GraphRAG 스타일 community 요약 진입

거부. *MVP 규모에서 과잉* . MS GraphRAG 의 community summarization 은 *전체 코퍼스 단위* 의 Leiden 클러스터링 + LLM 요약을 미리 계산한다. 비용이 크고 *코퍼스가 자주 갱신되는* 시나리오에 부적합. MVP 의 검증 셋 규모 (30 개 질문 + 작은 소스 셋) 에서는 효용 없음.

만약 이걸 택했다면, MVP ingestion 비용이 폭발하고 *idempotent 동작 (ADR-0001 D6)* 보장도 어려워졌을 것이다 (community 요약이 LLM 비결정성에 영향을 받음).

## Consequences

### 즉시 영향

- 그래프 DB 가 *어휘 인덱스 + 벡터 인덱스 둘 다* 내장 제공해야 한다. 이 제약은 ADR-0004 에서 다룬다.
- Opentology 코어는 *ingest 시점에만 LLM 을 호출* . query 시점 LLM 호출은 caller (ADR-0006). 코어의 외부 의존성이 줄어듦.
- query 시 Opentology 가 *embedding 모델은 호출* . caller 가 보낸 키워드를 server-side 에서 임베딩하기 위함. (LLM 호출과 embedding 호출은 다르다 — embedding 은 훨씬 싸고 빠르며 동일성도 강함.)
- 청크 벡터 RAG 베이스라인 (ADR-0001 의 (2) 컬럼) 과 *동일한 임베딩 모델* 을 노드 임베딩에 사용. 측정 직전에 모델 고정.

### 코드 작업 시 기억할 점

- 노드 스키마에 `name`, `aliases[]`, `embedding` 세 필드는 *진입점 선정의 기본 단위* 다. 마이그레이션 시 이 필드 손상 주의.
- `find_entities` primitive 가 받는 `keywords` 인자는 *이미 caller 가 추출한 anchor* 라고 가정. Opentology 가 *그 키워드에서 다시 LLM 으로 별칭을 추출하지 않음* (분리 원칙).
- 어휘 매칭과 dense 매칭의 결합 함수 (RRF 등) 는 구현 설계 단계 결정. *둘의 가중치를 실험적으로 조정* 할 수 있는 형태로 빠져있어야 한다.
- 진입점 top-k 의 k 값과 임계값은 도메인마다 다를 수 있다. MVP 의 상거래 검증 도메인에서 *적절한 값* 을 측정 보고서에 기록.
- 권장 caller 프롬프트 패턴 — *정규명 + 별칭을 JSON 으로 함께 반환* . 이는 ADR-0006 D4 의 caller 흐름의 일부로 벤치마크 하니스 코드에 포함된다.

### 도메인 확장 시 영향

본 ADR 의 결정은 *상거래 외 도메인* 으로 확장할 때 다음과 같이 작동한다.

- **사내 위키** — anchor 추출이 *암묵 표현* ("그 배포하는 거") 을 정규명 ("deployment system") 으로 매핑하는 능력이 핵심. LLM 의 도메인 사전 지식에 의존.
- **생물학 / 의학** — 별칭이 폭발하는 영역. ingest 시점 별칭 추출만으로는 부족할 수 있어 *외부 ontology (UMLS, MeSH 등) 통합* 이 후속 결정 후보.
- **AI 연구 문헌** — 신조어가 매 논문마다 새로 생긴다. ingest 시점에 *해당 신조어가 본문에 등장한 위치 자체* 를 별칭으로 박는 게 중요.

이 확장 시나리오들은 *post-MVP 결정* 이므로 본 ADR 에서는 약속하지 않는다.

## Related

- [ADR-0001 — 프로젝트 정체성과 MVP 검증 가설](./0001-project-identity-and-mvp-validation-hypothesis.md) — 진입점 품질이 가설 검증 결과에 미치는 영향.
- [ADR-0004 — 벡터 인프라 결정](./0004-vector-infra-graph-db-internal-index.md) — 본 ADR 의 dense 임베딩이 *어디에 저장되는가* .
- [ADR-0006 — MCP/REST 표면](./0006-mcp-rest-primitives-surface.md) — anchor 추출이 *caller 책임* 인 근거. 본 ADR D1 의 책임 분리는 이 표면 결정의 결과.

### 외부 참고 자료

본 ADR 의 결정은 다음 2024-2026 연구를 참고했다.

- [A Survey of Graph Retrieval-Augmented Generation for Customized LLMs (arXiv 2501.13958)](https://arxiv.org/pdf/2501.13958) — 진입점 선정 6 분류 (string / semantic / logical / LLM / RL / GNN).
- [BYOKG-RAG: Multi-Strategy Graph Retrieval for KGQA (arXiv 2507.04127)](https://arxiv.org/pdf/2507.04127) — LLM anchor 추출 + fuzzy + node embedding 의 union 패턴.
- [AnchorRAG: Open-World KG-RAG Multi-Agent (arXiv 2509.01238)](https://arxiv.org/pdf/2509.01238) — anchor 식별의 predictor agent 패턴.
- [PathRAG: Pruning Graph-based RAG with Relational Paths (arXiv 2502.14902)](https://arxiv.org/pdf/2502.14902) — 진입점 *사이* 경로 prune 으로 토큰 44% 절감.
- [Paths-over-Graph (WWW 2025, ACM)](https://dl.acm.org/doi/10.1145/3696410.3714892) — 동적 다중 hop 경로 탐색 + 3-step pruning. ToG 대비 18.9% 향상.
- [From BM25 to Corrective RAG: Benchmarking Retrieval (arXiv 2604.01733)](https://arxiv.org/html/2604.01733v1) — 금융 도메인 BM25 가 text-embedding-3-large 보다 우수.
- [Hybrid RAG: Graphs, BM25, and the End of Black-Box Retrieval (NetApp)](https://community.netapp.com/t5/Tech-ONTAP-Blogs/Hybrid-RAG-in-the-Real-World-Graphs-BM25-and-the-End-of-Black-Box-Retrieval/ba-p/464834) — 식별자 중심 도메인의 BM25 강세 사례.
- [GraphRAG vs HippoRAG vs PathRAG vs OG-RAG (Graph Praxis, Medium)](https://medium.com/graph-praxis/graphrag-vs-hipporag-vs-pathrag-vs-og-rag-choosing-the-right-architecture-for-your-knowledge-graph-a4745e8b125f) — 진입점-traversal 결합 패턴 비교.
- [Less is More: Denoising Knowledge Graphs for RAG (arXiv 2510.14271)](https://arxiv.org/pdf/2510.14271) — LightRAG / HippoRAG / GraphRAG 의 인덱싱 구성 차이.
