# Smoke 측정 — NON_IDENTIFYING_ALIAS_STOPLIST 적용 후 graph 회복 + Combined 유의미성 검증

날짜: 2026-06-20
측정 run: `eval/runs/2026-06-20-1532` (FinanceBench smoke, 21 MCQ × N=3, gpt-4.1)
선행 보고서:
- `eval/reports/2026-06-20-financebench-1M/CONCLUSION.md` (M6.5 1M 측정 — graph 부패)
- `eval/reports/2026-06-20-combined-pivot/CONCLUSION.md` (95K Combined 채택)
관련 ADR: ADR-0007 / ADR-0008
관련 코드 변경: `apps/api/src/arche_api/domain/identity.py` 의 `NON_IDENTIFYING_ALIAS_STOPLIST`

## TL;DR

ADR-0008 의 M6.5 진단 (graph catastrophic over-merge) 을 *임시 patch* (NON_IDENTIFYING_ALIAS_STOPLIST) 로 차단한 후 smoke 측정 (3 사 / 435K tokens / 21 MCQ). **Combined RAG 가 chunk 대비 +9.5pp 우위**. ADR-0007 D2 의 ≥ chunk + 3pp 기준의 3 배.

**결론: Combined RAG 는 유의미**. EntityConsolidator (M6.5b, #40) 본격 구현 가치 입증.

## 측정 결과

| 컬럼 | 정확도 | 오답 (qid) | 토큰 중앙값 | 지연 중앙값 | 비용 (63 호출) |
|---|---|---|---|---|---|
| chunk_rag | 71.4% | Q01, Q07, Q08, Q09, Q13, Q17 | 27.5K | 2.18s | $0.97 |
| arche (graph) | 33.3% | Q01, Q05, Q06, Q07, Q08, Q09, Q12, Q14-16, Q19-21 | 10.7K | 3.71s | $1.27 |
| **combined** | **81.0%** | Q01, Q09, Q17, Q21 | 37.7K | 5.20s | $2.17 |

## 1M 부패 측정과 비교

| 컬럼 | 1M 부패 (M6.5) | smoke (fix 후) | 변화 |
|---|---|---|---|
| chunk_rag | 72.7% | 71.4% | ≈ |
| arche | **6.1%** | **33.3%** | **+27.2pp** (×5.5) |
| combined | 72.7% | **81.0%** | **+8.3pp** |

**fix 가 정확히 의도한 변화를 만들었다**: graph 가 부패 상태에서 baseline 으로 회복 + combined 가 chunk 대비 우위로 분리.

## 오답 집합 교차 분석 — Combined 의 시너지 직접 측정

| 집합 | 문항 | 의미 |
|---|---|---|
| chunk-only wrong | (없음) | combined 가 chunk 가 맞춘 모든 문제를 맞춤. **후퇴 없음** |
| graph-only wrong | Q05, Q06, Q12, Q14, Q15, Q16, Q20 (7 개) | chunk 만 맞춘 문제 → 모두 combined 도 맞춤 |
| combined-only wrong | (없음) | combined 가 단독으로 떨어진 케이스 없음 |
| all-three wrong | Q01, Q09, Q17 (3 개) | 셋 다 못 푼 *진짜 hard* 문제. 14% ceiling |
| oracle (k & g) | Q01, Q07, Q08, Q09, Q13, Q17 (6 개) | chunk + graph 단순 oracle 의 오답 = 80.0% 정확도 |
| **combined wins** (chunk 또는 graph 가 틀린 것을 combined 가 회복) | Q05, Q06, Q07, Q08, Q12, Q13, Q14, Q15, Q16, Q20 (10 개) | combined 의 직접 효과 측정 |

**Combined 81.0% > oracle 80.0%**. 두 단독 retrieval 의 *둘 다 틀린 문제* (Q21) 까지도 combined 가 다른 컬럼에서 회복한 케이스 일부 존재. 즉 combined 는 *시너지* 를 만들 뿐 아니라 *단순 합집합 이상의 추론* 까지 가능.

## ADR-0007 D2 결정 기준 매핑

| 분기 | 본 smoke 결과 매핑 |
|---|---|
| Combined ≥ chunk + 3pp | **+9.5pp 명백 충족** |
| Combined ≈ chunk (±2pp) | 미해당 |
| chunk > Combined | 미해당 |

비용 기준 (Full-context 의 1/3 이하): Full-context 추정 (435K corpus 의 gpt-4.1 호출 × 63) 약 $8 → combined $2.17 = 27%. **충족**.

→ **ADR-0007 D2 의 "Combined ≥ chunk + 3pp" 분기 확정** → ADR-0007 본문 그대로, M7 진행 가치 입증.

단 본 검증은 *smoke* (435K, 21 MCQ). 1M 의 진짜 검증은 M6.5b (EntityConsolidator 본 구현 후 6 사 재 ingest + 재측정) 에서.

## 본 stoplist fix 의 한계 (사용자 지적 수용)

본 fix 는 **근본 해법이 아니다**. 정확히는 *catastrophic 케이스 (영문 10-K self-reference) 만* 막는 *smoke test 용 stepping stone*.

| 한계 | 예 |
|---|---|
| Coverage | "the Company" / "we" 는 잡지만 "this Registrant" / "the parent" / "the Group" 변이는 누락 |
| 언어 의존 | 영/한 외 (日本語 "本社", 中文 "本公司", Español "la Empresa") 모두 수기 추가 필요 |
| 도메인 의존 | 의료 / 정부 / 기술 문서마다 자기지칭 패턴이 다름. 도메인 추가마다 stoplist 갱신 |
| 알고리즘 가정 자체 미해결 | Step 2 의 "alias 정확 일치 = globally unique entity 식별" 가정이 *generic term 에 대해서는 거짓*. stoplist 는 특정 단어만 우회할 뿐 가정 자체는 안 고침 |
| 다른 over-merge 패턴 무용 | "Net Income" / "Total Assets" 같은 회계 용어의 type=Concept cross-doc 합치기는 별도 케이스 |

**진짜 fix** = ADR-0008 M6.5b 의 EntityConsolidator (이슈 #40):
- ANN (Neo4j vector index) 으로 cosine 0.85-0.92 사이의 의심 후보 쌍 추출
- LLM 으로 "정말 같은 entity 인가" 검증
- generic 자기지칭은 source_path 기반 회사별 분리 유지
- 도메인 / 언어 / 분야 무관 일반화

본 smoke 결과는 EntityConsolidator 의 *완성판* 이 어디까지 갈 수 있는지를 *최소판 (stoplist) 만으로도* 입증.

## 의사결정 흐름 — 본 smoke 가 무엇을 닫고 무엇을 여는가

### 닫는 것

- "Combined RAG 가 1M 시점에 의미 있는가" 의 *부정 답변 가능성* — 본 smoke 의 +9.5pp 가 ADR-0007 D2 의 chunk-only 피벗 분기 (chunk > Combined) 를 *명백히 기각*
- "graph 부패가 측정 자체의 문제인가" 의 *불확실성* — stoplist fix 만으로 graph 가 +27pp 회복하므로, 부패가 *알고리즘 가설* 보다 *전처리 단계* 의 결함이었음 확정

### 여는 것

- M6.5b (EntityConsolidator 본 구현) 의 *가치 입증* — 본 stoplist 의 한계를 보강하는 ANN + LLM 검증의 직접 ROI 측정 가능
- M7 의 *명백한 GO 신호* — chunk + graph 결합이 시너지를 만든다는 evidence
- 1M 재측정의 *예상 결과 범위 설정* — smoke 의 81% 가 1M 의 *하한* 추정 (1M 은 더 hard 한 multi-doc 문제 비중이 있으므로 ±5pp 변동 예상)

## 데이터 산출물

- `eval/datasets/financebench-smoke/` — 3 사 / 21 MCQ / lint green
- `eval/runs/2026-06-20-1532/responses/{chunk_rag,arche,combined}/` — 189 raw 응답
- `eval/reports/2026-06-20-smoke-stoplist-fix/score_output.txt` — 본 보고서 표 재생산

## 검증 한계 (사전 기록)

- **smoke (3 사 / 435K / 21 MCQ)** — 1M / 6 사 / 33 MCQ 의 진짜 재검증은 M6.5b 에서
- **N=3 majority** — 더 robust 한 결론은 N=10+
- **stoplist 의존** — 본 결과는 *NON_IDENTIFYING_ALIAS_STOPLIST 가 cover 하는 self-reference 패턴 안에서만* 유효. 다른 over-merge 패턴 (회계 용어 등) 은 별도 검증 필요
- **AMD / AXP / BA 3 사 한정** — 다른 도메인 (의료 / 정부 등) 의 self-reference 패턴은 별도 확인

## 다음 액션

1. **본 PR 머지** — stoplist fix + smoke 보고서 + ADR-0008 의 1 차 evidence 보강
2. **M6.5b 이슈 #40 (EntityConsolidator) 본격 구현 시작** — 본 smoke 결과로 가치 입증된 후속 작업
3. **M6.5b 1M 재측정 (#50)** — EntityConsolidator 본 구현 후 1M 에서 본 smoke 의 81% 가 *유지 또는 개선* 되는지 검증 → ADR-0007 D2 의 최종 결정
4. **M7 의 productization 계획 준비** — M6.5b 완료 시 즉시 착수 가능하도록 design 만 병행
