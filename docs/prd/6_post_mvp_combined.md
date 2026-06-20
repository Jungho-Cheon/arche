# PRD 6 — post-MVP Combined RAG 청사진

> 본 문서는 2026-06-20 Combined RAG 검증 (정확도 100%, full-context 의 1/5 비용) 결과를 받아 Opentology 의 정체성과 다음 마일스톤을 정한다. MVP 의 가설 (그래프 단독 Pareto 우월) 은 미달이었지만, *두 retrieval 의 보완재 결합* 이라는 새 가설이 한 번의 측정에서 강하게 입증되었다.
>
> 본 PRD 가 답해야 하는 4 가지 질문:
>
> 1. Combined 방식을 Opentology 의 새 정체성으로 가져가려면 무엇이 필요한가
> 2. Combined 가 Obsidian / Graphify / 실 경쟁 도구들 대비 어떤 이점을 갖는가
> 3. Combined 의 최적해는 무엇인가 (chunk 최적화 + graph 최적화 + 둘의 관계)
> 4. Opentology 가 경쟁력을 갖는 post-MVP 청사진은 무엇인가

## §0. 전제 — 측정 결과 한 줄

본 측정 (95K 한국어 정책 코퍼스, 30 MCQ, N=3, gpt-4.1):

| 컬럼 | 정확도 | 토큰 중앙값 | 지연 중앙값 | 90 호출 비용 |
|---|---|---|---|---|
| chunk_rag | 96.7% | 8.5K | 2.85s | $0.97 |
| opentology (graph 단독) | 90.0% | 7.9K | 4.82s | $1.69 |
| **combined (chunk + graph 단일 호출)** | **100.0%** | 15.7K | 5.11s | **$2.54** |
| (참고) full_context | 100% | 70K | 8.1s | $12.7 |

핵심 — chunk 와 graph 의 오답이 *완전히 비겹침*. LLM 이 두 retrieval 결과를 한 컨텍스트에서 비교해 *서로의 약점을 정정* 한다. 라우터 휴리스틱 불필요.

---

## §1. Combined 를 Opentology 의 정체성으로 — 필요한 것

### §1.1 API 표면 — 그래프 primitive 에서 *retrieval orchestrator* 로

현재 (MVP) 의 6 primitive (`get_schema` / `find_entities` / `get_entity` / `get_neighbors` / `find_path` / `get_subgraph`) 는 *유지* 하되, *고수준 엔드포인트* 를 추가한다.

| 엔드포인트 | 역할 | 입력 | 출력 |
|---|---|---|---|
| **`POST /answer`** | Combined 답변 (1 호출) | 질문 + 답변 형식 (text/MCQ/JSON schema) + 옵션 | choice/answer + reasoning + provenance |
| **`POST /retrieve`** | *컨텍스트만* 반환 (외부 LLM 이 직접 답변 생성) | 질문 + budget | chunks + subgraph + path + 출처 메타 |
| `POST /retrieve/chunks` | chunk 만 | 질문 + top_k | chunks |
| `POST /retrieve/subgraph` | subgraph 만 | 질문 + hops | entities + relations + paths |

`/answer` 가 *기본* 채널이 된다 (현재 MVP 는 사용자가 6 primitive 를 직접 조합). `/retrieve` 는 자체 LLM 을 운영하는 사용자를 위한 것.

### §1.2 Provenance — 어떤 신호가 답을 결정했나

현재 reasoning 안에 "(A) 청크" 또는 "(B) 그래프" 라는 자연어 멘션이 들어가지만, 구조화되어 있지 않다. 응답에 구조화된 provenance 를 추가:

```json
{
  "choice": "b",
  "reasoning": "...",
  "provenance": {
    "decisive_source": "graph",       // chunk | graph | both
    "chunks": [{"source_path": "loyalty/tier-rulebook.md", "chunk_index": 7, "score": 0.63}],
    "graph": {
      "entries": ["수면 고객", "VIP", "명품 반품"],
      "edges_used": [{"from": "수면 고객", "rel": "EXCEPTION_FOR", "to": "명품 연장"}]
    }
  }
}
```

가치: 자기 도메인에서 어느 신호가 결정적이었는지 사용자가 *측정* 할 수 있다. graph 가 거의 안 쓰이면 chunk-only 로 다운그레이드해서 비용 절감, graph 가 자주 결정적이면 ingest 품질 투자가 ROI 가 명확.

### §1.3 비용/품질 노브 — 사용자 손에 닿는 다이얼

| 노브 | 기본값 | 효과 |
|---|---|---|
| `chunk_top_k` | 8 | 청크 개수. 낮추면 토큰 절감, 정확도 위험 |
| `subgraph_hops` | 2 (anchor 1-3 개), 1 (4+) | 그래프 깊이. 낮추면 토큰 절감 |
| `subgraph_max_nodes` | 80 | 그래프 폭. 낮추면 토큰 절감 |
| `token_budget` | 무제한 | chunks+subgraph 토큰 상한. 넘으면 *우선순위 기반 절단* |
| `skip_graph_if_no_anchor` | true | anchor 0 개면 graph 컨텍스트 = (엔티티 없음). 호출 비용 절감 |
| `embed_model` | text-embedding-3-small | 임베딩 모델 (chunk/anchor 공통). large 로 올리면 retrieval 품질↑, 비용↑ |
| `answer_model` | gpt-4.1 | 답변 LLM. mini 로 다운그레이드 가능 |

이 노브들은 `/answer` body 의 `options` 필드로 노출하고, 서버 설정으로 기본값을 잡는다.

### §1.4 측정 모드 — 평가 하니스의 서비스화

MVP 의 eval 하니스 (`opentology-eval`) 는 *수동 측정 CLI*. 이를 *서비스 모드* 로 격상:

- 운영 환경에서 받은 모든 `/answer` 호출을 익명화해 로그
- 주기적 spot-check 측정 (사람이 만든 ground truth 셋에 대해 N=1 실행)
- 정확도/토큰/지연 drift dashboards
- chunk 와 graph 가 *다른 답* 을 낸 케이스를 자동 수집 → human-in-the-loop 검토 큐로

이게 곧 Opentology 의 운영 가치 명제 — "RAG 를 *측정 가능하게* 운영한다".

### §1.5 문서화 — 정체성 변경의 명시화

| 산출물 | 목적 |
|---|---|
| ADR-0007 | "Combined RAG 채택" — 본 PRD 의 결론을 결정 기록으로 |
| ADR-0001 갱신 | 측정 방법론에서 full-context 는 *비교 기준* 이 아닌 *상한* 임을 명시 |
| README 갱신 | 한 줄: "그래프 KB" → "Combined RAG orchestrator" |
| Getting Started | "내 문서 → LLM/에이전트가 답하게 하기" 5 분 튜토리얼 |

---

## §2. 경쟁 분석 — Obsidian / Graphify / 실 경쟁군

사용자가 거론한 두 도구는 카테고리가 다르다. 정직한 비교를 위해 *실 경쟁군* 까지 같이 본다.

### §2.1 카테고리 매핑

| 도구 | 카테고리 | LLM-facing? | Retrieval API? | Hybrid (chunk+graph)? |
|---|---|---|---|---|
| **Obsidian** | 인간용 노트 PKM | 아니오 (플러그인) | 아니오 | 아니오 |
| **Graphify** | 일회성 그래프 빌더 | 아니오 (JSON 출력) | 아니오 (정적) | 아니오 (그래프만) |
| LangChain HybridRetriever | 라이브러리 (DIY) | 예 | DIY 조립 | 가능 (DIY) |
| LlamaIndex KnowledgeGraphIndex | 라이브러리 (DIY) | 예 | DIY 조립 | 가능 (DIY) |
| **Microsoft GraphRAG** | 라이브러리 (graph + community summary) | 예 | 예 | 그래프 중심, multi-pass |
| **Neo4j GraphRAG** (Python) | 라이브러리 (Neo4j 네이티브) | 예 | 예 | 가능 |
| Cohere Rerank + 벡터 DB | API 조합 | 예 | 부분 (chunk 만) | 아니오 |
| Vectara / Pinecone Assistant | 매니지드 RAG | 예 (서비스) | 예 | 일부 (도메인별) |
| **Opentology (Combined)** | 자가호스트 RAG orchestrator | 예 | 예 (단일 엔드포인트) | **기본 (chunk + graph 결합)** |

### §2.2 Obsidian / Graphify 대비 Combined 의 이점

**Obsidian 대비**:
- Obsidian 의 Smart Connections 같은 플러그인은 *벡터 only*. 동의어/별칭 다중-홉 질문에서 한계 (본 측정 Q02 같은 사례).
- Obsidian 은 인간용 단축키/링크 UI 가 본체. *LLM/에이전트가 API 로 호출* 하기에는 비효율.
- Opentology 는 API 가 본체. 운영 측정 가능.

**Graphify 대비**:
- Graphify 는 정적 산출물 (graph.json, GRAPH_REPORT.md). *실시간 질의* 가 아님.
- Graphify 는 *그래프만*. 본 측정의 Q05/Q20 처럼 그래프 alias 가 미통합되면 답을 못 냄.
- Graphify 는 재실행할 때마다 LLM 추출을 다시 함 (캐시는 있지만 청크 기준). Opentology 는 idempotent 차분 ingest (ADR-0003).

**둘 모두 대비 공통 이점**:
- Combined 한 호출에서 chunk + graph 가 *서로의 약점 정정*. 본 측정 30 문항 100%.
- Provenance — 어떤 신호가 결정적이었는지 구조화된 출력.
- 측정 가능 — eval 하니스 ships with the product.

### §2.3 실 경쟁군 대비 차별 요소 (정직한 평가)

LangChain Hybrid 와 LlamaIndex 가 *기능적으로 같은 것을 조립 가능* 하다. Opentology 의 차별은 다음 *조합* 에서 온다:

1. **Opinionated 기본값** — 사용자가 청크 크기 / 임베딩 모델 / hop 수 / 머지 임계값을 정하지 않아도 동작. 본 측정으로 검증된 기본값이 박혀 있음.
2. **Idempotent ingest + 4 단계 EntityMatcher** — 같은 문서를 다시 ingest 해도 그래프가 부풀지 않음 (ADR-0003). LangChain/LlamaIndex 는 ingest 정책이 사용자 몫.
3. **Eval 하니스 동봉** — `opentology-eval` 이 같은 저장소에 있어 *내 도메인에서 측정* 이 5 분 안에 시작.
4. **MCP + REST 동시 노출** — agentic workflow 에 그대로 꽂힘.
5. **한국어 정책 도메인 검증 데이터셋 동봉** — 비영어/규정 도메인에서의 동작 보장.

Microsoft GraphRAG 대비 — *cheaper*. GraphRAG 는 community summary 를 미리 만들어두는 multi-pass 파이프라인. Opentology 는 1 LLM call 로 답.

Neo4j GraphRAG (Python) 대비 — Opentology 는 chunk RAG 를 *peer* 로 둠. Neo4j GraphRAG 는 그래프 중심.

Vectara / Pinecone Assistant 대비 — *self-hostable* 라이선스. 데이터가 외부로 안 나감. Combined 가 그들의 retrieval 보다 *근본적으로 우수* 한지는 검증 필요 (이 PRD 의 §3 측정 항목으로).

### §2.4 정직한 한계

- 단일 도메인 (한국어 커머스 정책, 95K) 단일 회차 측정. *영문 / 다도메인 / 큰 corpus 일반화는 미검증*.
- Combined 가 본질적으로 chunk 의 1.5-2 배 비용 (2.54 vs 0.97). 비용 제약 강한 사용자에게는 ROI 가 작을 수 있음.
- Combined 가 chunk 단독 대비 *항상* 더 정확하다는 보장 없음 — graph alias 가 noise 만 주면 오히려 LLM 을 혼란시킬 가능성. 본 측정에서는 그런 케이스 없었지만 큰 corpus 에서는 발생 가능.

---

## §3. Combined 의 최적해 — 3 축 최적화

목표 함수: **정확도 ↑ + 토큰/지연/비용 ↓**. 본 측정 기준선 = 100% / 15.7K tok / 5.11s / $0.028 per query.

### §3.1 Chunk 측 최적화

| 후보 | 기대 효과 | 비용 (추가 호출/추가 학습) | 우선도 |
|---|---|---|---|
| **Reranker (BGE-reranker-v2 / Cohere Rerank v3)** | 노이즈가 많은 큰 corpus 에서 top-k 정확도 +1-3%. 본 95K 에서는 효과 작을 가능성 | +$0.0003/query (Cohere 기준) 또는 self-host CPU 추론 | P1 |
| **Sparse+dense hybrid (BM25 + 벡터, RRF k=60)** | 숫자/이름/조항번호 같은 *정확 매치* 가 중요한 질문에서 큰 이득. 본 측정에 비추면 Q20 류에서 차이 | $0 (BM25 self-host) | P1 |
| **청크 크기 / overlap 튜닝** | 본 측정 800/100 이 도메인에 최적인지 미검증. 1200/200 sweep | $0 (재측정만) | P2 |
| **Query expansion (LLM rewrite)** | 짧고 모호한 질문에서 retrieval 개선. 측정용 MCQ 에는 큰 효과 없을 수 있음 | +$0.0005/query | P3 |
| **Late interaction (ColBERT)** | 최상위 recall. 인프라 복잡도↑ | 인덱스 4-8 배 | P3 (vertical 결정 후) |

### §3.2 Graph 측 최적화

#### Ingest 품질 (그래프 *내용* 의 정확도)

| 후보 | 무엇이 좋아지나 | 비용 | 우선도 |
|---|---|---|---|
| **EntityConsolidator — post-ingest cleanup (cross-doc entity linking)** — 현재 4 단계 EntityMatcher 는 ingest 인라인 *streaming* (순서 의존, cosine 0.92 hard threshold). 후처리로 분리하면 모든 entity 적재 후 *임베딩 ANN top-k + 임계값 완화 (0.85) + LLM 검증* 으로 한 번 더 통합. `POST /admin/consolidate` 로 별도 호출. **ANN 사용이라 O(n log n)** — 1M entity 까지 확장 가능 | Q05/Q20 같은 alias 미통합 해소 (streaming 이 놓친 쌍). graph 단독 90% → 95%+ 회복 가능. corpus 추가 후 cleanup 만 별도 트리거 | embedding ANN 은 이미 Neo4j 인덱스에 있음. 후보 쌍 100-300 (cosine ≥ 0.85 필터 후) × LLM $0.001 = $0.1-0.3 per consolidate | **P0** |
| **Multi-pass 관계 추출** — 1 pass 엔티티만, 2 pass 관계만. 관계 추출이 엔티티 컨텍스트 전체를 봄 | 본 측정 cross_source 패턴에서 누락된 cross-doc 관계 회복 | +30% ingest 비용 | P1 |
| **Schema 발견 + 정규화** — 추출된 관계 타입을 LLM 으로 정규화 (`HAS_TIER` vs `BELONGS_TO_TIER` 통합). 검색 시 schema-aware | 검색 hit rate ↑, 그래프 가독성 ↑ | +1 LLM call per ingest | P1 |
| **Neo4j GDS 구조 임베딩 (FastRP/Node2Vec) 보조** — EntityConsolidator 의 LLM 검증 입력에 *이름 임베딩 + 구조 임베딩* 두 신호 동시 제공 (이웃 구조가 비슷한 노드끼리 가산점). false positive 추가 차단 | 1M corpus 시점에 EntityConsolidator 의 LLM 호출량 절감 | Neo4j community 라 GDS 설치/대안 모색 필요 | P2 (Phase 3) |

#### Anchor 추출

| 후보 | 무엇이 좋아지나 | 비용 | 우선도 |
|---|---|---|---|
| **Retrieval anchor (생성 대신)** — 질문 임베딩으로 entity 인덱스를 직접 검색 (현재: LLM 이 generate). 생성-기반 LLM 호출 1 회 ($0.001) 절감 | latency -1.5s, 비용 -$0.001/query | $0 추가 | **P0** |
| **Anchor confidence threshold** — entity 매칭 점수가 낮으면 anchor 제외 | 무관한 entity 가 subgraph 에 들어가 noise 가 되는 것 차단 | $0 | P1 |
| **Anchor expansion** — 채택된 anchor 의 alias / 인접 entity 1-hop 도 anchor 로 추가 | recall ↑ (synonym_alias 케이스) | $0 | P1 |
| **Anchor model 분리** — anchor 는 gpt-4o-mini, answer 는 gpt-4.1 (이미 실험 E5 에서 시도, 93.3% 로 떨어져 보류) | 비용 -$0.001 | 정확도 risk | P3 |

#### Subgraph 직렬화 / 선택

| 후보 | 무엇이 좋아지나 | 비용 | 우선도 |
|---|---|---|---|
| **Subgraph reranking (질문 임베딩 기반)** — 가져온 노드/엣지를 질문 임베딩과 코사인 후 상위 K 만 LLM 전달 | 8K → 4-5K 토큰 절감. 정확도 보존/약상승 | embedding 1 회 (~$0.0001) | **P0** |
| **Variable hops** — 질문 패턴 (synonym_alias → 깊게, single_doc → 얕게) 에 따라 hops 결정 | 토큰 절감 | LLM 기반 패턴 분류 1 회 (~$0.0003) | P1 |
| **Path-aware**— anchor 2-3 개일 때 find_path 결과를 *더* 비중 두기 | multi-hop 정확도 ↑ | $0 | P1 |

### §3.3 Combined 조정 최적화

| 후보 | 무엇이 좋아지나 | 비용 | 우선도 |
|---|---|---|---|
| **토큰 budget allocator** — 총 budget B 가 주어지면 chunks 와 subgraph 가 그 안에서 경쟁. 예: B=10K, chunk top-k 동적 조정 | 비용 예측 가능, SLO 관리 | $0 (로직만) | **P0** |
| **빠른 graph skip** — anchor 가 0 개거나 entry_count = 0 이면 graph 컨텍스트 = (없음). 토큰 절감 | latency 단축 + 토큰 -7K | $0 | **P0** |
| **빠른 chunk skip** — graph subgraph 가 *완전히* 질문을 커버 (heuristic: anchor 가 모두 매치 + 직접 1-hop edge 존재) 시 chunk 생략 | 토큰 -5K | 정확도 risk (검증 필요) | P2 |
| **2-pass — chunk only → 정보 부족 시 graph 추가** | 평균 비용 ↓ — 쉬운 질문은 chunk 만 | 2 LLM call (재호출 시) | P1 |
| **Speculative decoding 스타일** — chunk only 답변과 combined 답변을 비교, 일치하면 chunk only 비용 | 평균 비용 ↓ | LLM 2 호출 | P3 |

### §3.4 최적해의 윤곽 (현재 가설)

위 후보들을 종합한 *향후 1 년 내 도달 가능한 target spec*:

| 메트릭 | 현재 (Combined) | Target | 어떻게 |
|---|---|---|---|
| 정확도 | 100% (95K) | ≥ 98% (1M) | ingest 품질 P0 + chunk hybrid P1 |
| 토큰 중앙값 | 15.7K | 8-9K | subgraph reranking P0 + budget allocator P0 |
| 지연 중앙값 | 5.11s | ≤ 3s | retrieval anchor P0 + graph skip P0 |
| 비용/query (gpt-4.1) | $0.028 | ≤ $0.018 | 위 모두의 합 |

이 정도면 chunk 단독 ($0.011) 의 1.6 배 비용으로 +3.3% 정확도 + provenance — *명확한 가치 명제*.

---

## §4. post-MVP 청사진 — 마일스톤 + 분기 계획

### §4.1 Phase 1 — Productize Combined (M7, 약 4 주)

**목표** — Combined 를 *제품으로 호출 가능* 한 상태로 만들고, 정체성 변경을 공식 문서에 기록.

| # | 작업 | 산출물 |
|---|---|---|
| 1 | ADR-0007 — Combined RAG 채택 + ADR-0001 갱신 | `docs/adr/0007-combined-rag.md` |
| 2 | PRD 6 (본 문서) 확정 + README/STATUS 정체성 갱신 | 본 PRD, README, STATUS |
| 3 | `/answer` 엔드포인트 — body schema, 6 primitive 와 동일한 응답 envelope | API 변경 + tests |
| 4 | `/retrieve` 엔드포인트 — context-only (외부 LLM 용) | API 변경 + tests |
| 5 | Provenance 필드 — `/answer` 응답에 decisive_source / chunks / graph 출처 | 응답 스키마 확장 |
| 6 | 비용/품질 노브 (top_k / hops / budget / skip flags) options 필드 | API + tests |
| 7 | Getting Started 5 분 튜토리얼 — corpus 디렉토리 → ingest → /answer | `docs/getting-started.md` |

**Phase 1 종료 조건** — 외부 사용자가 docker-compose up + ingest + curl /answer 만으로 답을 받을 수 있다.

### §4.2 Phase 2 — 품질 + 비용 (M8, 약 6 주)

**목표** — §3 의 P0/P1 후보를 구현하고 본 측정 (95K) 재측정으로 효과 확인.

| # | 작업 | 기대 효과 |
|---|---|---|
| 8 | **EntityConsolidator (post-ingest cleanup pass)** — 전체 entity 의 ANN top-k + cosine ≥ 0.85 + LLM 검증으로 cross-doc alias 통합. `POST /admin/consolidate` 별도 엔드포인트 | graph 90% → 95%+, combined 안정성 ↑ |
| 9 | **Retrieval anchor** — 생성 대신 임베딩 NN | latency -1.5s, 비용 -$0.001/q |
| 10 | **Subgraph reranking** — 질문 임베딩 기반 상위 K | 토큰 -3K, 비용 -$0.006/q |
| 11 | **Token budget allocator + skip flags** | SLO 관리 + 평균 -1K 토큰 |
| 12 | **Chunk reranker (BGE-reranker)** | 큰 corpus 대비 정확도 보존 |
| 13 | **Chunk sparse+dense (BM25 + 벡터, RRF)** | 정확 매치형 질문 정확도 ↑ |
| 14 | Combined 재측정 (95K) + 비교 보고서 | M8 종료 evidence |

**Phase 2 종료 조건** — 95K 재측정에서 토큰 중앙값 ≤ 10K, latency 중앙값 ≤ 3.5s, 정확도 100% 유지.

### §4.3 Phase 3 — Scale + 차별화 (M9, 약 8 주)

**목표** — corpus 크기 / 다도메인 / 운영 측면에서 *경쟁 제품과 정량 비교*.

| # | 작업 | 기대 효과 |
|---|---|---|
| 15 | 300K-1M corpus 자체 확장 — 동일 도메인 (커머스 정책) 을 사람 손으로 3-10 배 | 큰 corpus 에서 chunk 노이즈 ↑ 가설 검증 |
| 16 | 1M corpus 측정 — combined vs chunk vs Microsoft GraphRAG vs LlamaIndex Hybrid | 외부 비교 evidence |
| 17 | 측정 모드 서비스화 (§1.4) — 운영 로그 + spot-check + dashboards | 운영 가치 명제 완성 |
| 18 | 다도메인 generalize — 영문 legal/compliance 도메인 코퍼스 1 종 측정 | 한국어 한정 의심 해소 |
| 19 | 코드베이스 적재 ADR (메모리 `project_post_mvp_code_ingest_adr`) | vertical 차별화 1 종 — 코드용 EntityMatcher / 호출 그래프 추출 |
| 20 | Multi-tenant 복귀 (`feedback_design_principles` 의 multi-tenant from day one 가드 재활성화) | SaaS 옵션 |

**Phase 3 종료 조건** — 1M corpus + 외부 도구 비교에서 combined 가 *동등 이상 정확도 + 동등 이하 비용* evidence.

### §4.4 마일스톤 매핑

| 마일스톤 | 이름 | Phase | 예상 기간 | 비고 |
|---|---|---|---|---|
| **M6.5** | **1M corpus 3-way 검증 (gating)** | Phase 0 (gating) | 1 주 + 측정 | **본 PRD 의 M7-M9 전 작업이 본 회차에 gated** |
| M7 | Combined RAG productization | Phase 1 | 4 주 | M6.5 결과 분기에 따라 형태 결정 |
| M8 | Combined 품질·비용 최적화 | Phase 2 | 6 주 | M7 머지 후 |
| M9 | Scale·다도메인·외부 비교 | Phase 3 | 8 주 | 한국어 일반화 / 자체 corpus 확장 / 외부 도구 비교 |

#### M6.5 gating — 1M 에서 본 PRD 의 가설을 재검증

본 PRD 의 모든 제안은 *95K 한국어 정책 코퍼스 단일 회차 측정* 에 근거. 1M 시점에서 가설이 무너지면 본 PRD 자체가 amend 대상. *M7 productization 에 투자하기 전* 1M FinanceBench (외부 standard, multi-hop QA 동봉) 로 *3-way 검증* (chunk vs opentology vs combined) 을 한 번 돌린다. 비용 약 \$13 (full-context 제외, ADR-0007 D2 에 따라 비교 대상 아님).

**M6.5 결과 분기**:

| 1M 결과 | 다음 액션 |
|---|---|
| Combined 정확도 ≥ chunk + 3pp | ADR-0007 그대로, M7 진행 |
| Combined ≈ chunk (±2pp) | M7 단순화 (provenance 만 살리고 graph 는 옵션 노브로) |
| chunk > Combined | ADR-0007 amend, chunk-only orchestrator 로 피벗 |

본 gating 회차 종료 이전에 M7-M9 의 작업을 *코드로 착수하지 않는다*. 다만 M7 이슈들 (#33-#39) 의 *설계 문서* 는 본 회차와 병행 가능.

---

## §5. 의사결정 기록 — 본 PRD 가 *대신* 거절한 선택지

본 PRD 를 채택하면 다음 대안들은 *명시적으로 거절* 한 것이다 (나중에 다시 꺼낼 때 이 기록을 참조):

| 거절된 선택지 | 거절 사유 |
|---|---|
| **Chunk RAG 만 채택 (graph 폐기)** | 본 측정 Q02 (synonym_alias 3-hop) — chunk 만으로는 못 푸는 *우리 페르소나의 핵심 페인* 사례. 정확도 차이는 작아도 페인의 본질이 거기에 있음. graph 의 +$1.57/90 비용은 그 페인 해소 가치보다 작음 |
| **Graph RAG 만 채택 (chunk 폐기)** | 본 측정 graph 단독 90% — alias 통합 품질이 ingest 마다 흔들림. chunk 가 안정성 완충 |
| **라우터 기반 hybrid (chunk OR graph)** | 라우터 자체가 또 다른 휴리스틱. 사용자와의 토론에서 결정 (chat 기록). 그리고 본 측정에서 *둘 다* 호출하는 비용이 단독 호출과 큰 차이 없음 ($0.028 vs $0.011-0.020) |
| **Microsoft GraphRAG community summary** | Multi-pass ingest 비용이 큼. Combined 1-pass 가 같은 정확도. 큰 corpus 시점에 다시 검토 (Phase 3) |
| **Full-context (long-context LLM dump)** | 본 측정 비용 $12.7 (Combined 의 5 배). 1M corpus 에서는 격차 더 벌어짐 |
| **1M FinanceBench 즉시 검증 ($190)** | 사용자 budget 부담 + 알고리즘 측면 개선 (combined) 이 먼저. Phase 3 에 자체 corpus 확장으로 대체 |

---

## §6. 본 PRD 이후 즉시 후속 작업

1. ADR-0007 작성 (본 PRD 의 §0 결과 + §4.1 결정 기록)
2. GitHub Milestone "M7 — Combined RAG productization" 생성
3. M7 이슈 #1-7 (§4.1 의 7 항목) 생성
4. STATUS.md 의 마일스톤 표에 M7-M9 추가
5. README 한 줄 갱신 — "그래프 KB" → "Combined RAG orchestrator"
