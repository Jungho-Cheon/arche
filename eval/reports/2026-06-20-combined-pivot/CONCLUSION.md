# Combined RAG 검증 결과 + MVP 피벗 방향

날짜: 2026-06-20
측정 run: `eval/runs/2026-06-20-0923` (corpus 재ingest 후 opentology + combined N=3, chunk_rag 는 2126 본 측정 결과를 복사하여 동일 dataset 기준 비교)

## TL;DR

| 컬럼 | 정확도 | 오답 질문 | 토큰 중앙값 | 지연 중앙값 | 비용 (gpt-4.1) |
|---|---|---|---|---|---|
| chunk_rag | 96.7% | Q02 | 8.5K | 2.85s | $0.97 |
| opentology (graph 단독) | 90.0% | Q05, Q20, Q25 | 7.9K | 4.82s | $1.69 |
| **combined (chunk + graph 단일 호출)** | **100.0%** | **없음** | 15.7K | 5.11s | $2.54 |

기준 참고 (2126 본 측정): full_context (gpt-4.1, 코퍼스 전체 dump) = 100%, 70K tokens, 8.08s, $12.69.

## 무엇이 일어났나

Combined 는 chunk RAG 의 top-k 청크와 opentology 의 anchor → subgraph 를 *한 LLM 호출의 컨텍스트* 에 같이 넣고 답변시킨다. 라우터 없음, 두 retrieval 모두 매번 수행.

3 가지 실패 패턴이 combined 안에서 *모두* 회복됨:

1. **Q02 (synonym_alias, 3-hop)** — chunk 단독 실패 → combined 정답.
   - chunk RAG 가 "골드 등급" 과 "비활성 등급" 의 alias 를 못 잡아 잘못된 a 선택.
   - subgraph 안에 명시된 "수면 고객 → V 회원 복귀 30 일 이내 명품 연장 미적용" edge 가 답을 b 로 고정.

2. **Q05 (synonym_alias, 2-hop) / Q20 (single_doc, 1-hop)** — graph 단독 실패 → combined 정답.
   - 새 ingest 의 자동 EntityMatcher 가 "다이아 등급 ↔ VVIP" alias 를 통합 못해 빈 서브그래프 + "정보 부족 (e)" 선택.
   - chunk RAG 의 발췌가 alias 두 표현을 한 청크에 같이 보여줘 LLM 이 정답을 a 로 고정.

3. **Q25 (cross_source, 2-hop)** — graph 단독 실패 → combined 정답.
   - 그래프 안의 edge 가 misleading 한 결론으로 유도 (c).
   - chunk 의 정확한 인용이 결정적이 되어 a 선택.

요컨대 *그래프는 chunk 의 synonym 약점을, chunk 는 그래프의 alias-미통합 약점을 보완* 한다. LLM 은 두 신호를 비교해서 신뢰성 높은 쪽을 선택한다 — 라우터 휴리스틱 불필요.

## 가설 정합

| 가설 | 결과 |
|---|---|
| H0: graph 단독으로 chunk 보다 Pareto 우월 | **미달** (95K corpus 본 측정에서 H0 이미 미달, 본 회차에서 graph 90% < chunk 96.7%) |
| H1: oracle hybrid (max(chunk, graph)) = 100% | **충족** (zero-overlap 오답) |
| H2: combined (chunk+graph 단일 호출) ≥ max(chunk, graph) | **충족 — 100%** |
| H3: combined < 2× chunk 비용 | **2.6× chunk 비용** (긴 컨텍스트 때문) — 미충족이지만 가격 대 정확도 trade-off 합리적 |

## MVP 피벗 방향: **Combined RAG (Chunk + Graph in single LLM call)**

### 왜 Combined 인가

1. **정확도 = 100%** — full-context 와 동률.
2. **비용 = full-context 의 1/5** ($2.54 vs $12.69) — 1M 코퍼스로 가면 격차가 더 벌어진다 (chunk + subgraph 컨텍스트는 corpus 크기에 거의 선형 비례하지 않음).
3. **단일 도구로 두 약점 회복** — chunk synonym 실패와 graph alias-미통합 실패가 *서로를 정정*.
4. **라우터 없음** — LLM 이 컨텍스트 안에서 두 신호를 자동 비교. 휴리스틱 임계값 튜닝 불필요.

### Chunk RAG 만 선택하지 않는 이유

Chunk 단독 (96.7%) 도 가성비는 좋다 ($0.97). 하지만:
- 본 corpus 의 30 문항 중 *명시적으로 chunk 만 실패하는* 1 문항 (Q02) 이 synonym_alias 패턴 — *우리 페르소나의 핵심 페인 사례* 와 동일 종류. 1/30 이 작아 보여도, 페인의 본질이 거기에 있다.
- Combined 의 +$1.57/30 (호출당 +$0.05) 추가 비용은 페인 해소 가치보다 작다.

### Graph RAG 만 선택하지 않는 이유

- 본 회차에서 graph 단독 90% — 자동 EntityMatcher 의 alias 통합이 *충분하지 않다*. 이는 매번 ingest 마다 발생할 수 있는 *불안정한 그래프 품질* 의 신호.
- Graph 의 품질 변동성을 chunk 가 완충하는 것이 안전. 단독 운영은 graph 품질 보장 추가 비용 (수동 머지·alias 사전 등) 을 요구함.

### Pivot 후 Opentology 의 정체성

"Opentology = 그래프 KB" 에서 → **"Opentology = chunk 와 graph 신호를 결합해 LLM/에이전트에 단일 컨텍스트로 제공하는 retrieval orchestrator"**.

- graph 는 *제거하지 않음* — chunk 가 못 잡는 synonym/alias 다중-홉 질의에서 결정적 신호 제공.
- chunk 는 *제거하지 않음* — graph 품질 변동을 완충, 명시적 사실 인용에 강함.
- 두 신호를 결합해 단일 LLM 호출로 답변 → 외부 시스템은 "Opentology API" 하나만 호출.

## Post-MVP 우선순위 재정렬

| 우선순위 | 작업 | 이유 |
|---|---|---|
| **P0** | ADR-0007: Combined RAG 채택 + 본 측정 결과 반영. ADR-0001 Pareto 정의 갱신 (full-context 가 비교 기준이 아니라 *상한* 임을 명시) | 본 보고서 직접 후속 |
| **P0** | API 컬럼 정리 — `/answer` 엔드포인트가 combined 흐름을 기본으로. 기존 chunk-only / graph-only 는 baseline 모드로 보존 (측정 가능성) | 제품 정체성 변경 반영 |
| P1 | 코드베이스 적재 ADR — graphify 직접 사용 경험 정리 (메모리 `project_post_mvp_code_ingest_adr` 참조) | MVP 종료 전 결정된 다음 큰 방향 |
| P1 | 큰 corpus (300K-1M) 재측정 — combined 의 우월성이 corpus 크기에서 유지되는지 확인 | 현 결론은 95K 한정. corpus 가 커지면 chunk 의 retrieval 노이즈가 늘어 graph 의 보완 가치가 더 커질 가능성 |
| P2 | EntityMatcher 강화 — Q05 / Q20 같은 alias 미통합 사례를 줄이면 graph 단독 정확도 회복 → combined 의 안정성 더 올라감 | 본 회차에서 발견된 graph 품질 변동성 직접 대응 |
| P2 | Combined 비용 최적화 — subgraph 가 7K-8K 토큰까지 길어짐. 질문 임베딩 기반 reranking 으로 상위 K 만 LLM 전달하면 토큰 절감 가능 (H4 가설, 이전 토론) | 비용/지연 격차 좁히기 |

## 데이터 산출물

- `eval/runs/2026-06-20-0923/responses/{chunk_rag,opentology,combined}/` — 270 raw 응답 (chunk_rag 는 2126 회차 복사본)
- `eval/scripts/score_combined.py` — 본 보고서의 표를 재생산하는 스코어링 스크립트
- `eval/reports/2026-06-20-mvp-closure/` — 2126 본 측정 보고서 (Pareto NG 결론) — 본 보고서가 그 *후속 검증* 이며 결론을 갱신한다

## 검증 한계

- corpus 95K. 1M 검증은 별건 (P1).
- N=3 majority. 더 robust 한 결론은 N=10 이상 필요. 다만 본 회차의 zero-overlap 패턴은 충분히 강한 신호.
- 한국어 커머스 정책 단일 도메인. 다도메인 일반화는 별건.
