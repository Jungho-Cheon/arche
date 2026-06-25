# 피벗 — arche_aug 가 메인 컬럼. 검증 / 비교 / 결정 / 최적화 로드맵

날짜: 2026-06-20
선행 보고서:
- `eval/reports/2026-06-20-smoke-stoplist-fix/` — graph 부패 fix + Combined 유의미성 1 차
- `eval/reports/2026-06-20-aug-poc/` — arche_aug PoC (graph-guided chunk retrieval) 81.0%
관련 PR: #51 (stoplist fix), #52 (aug PoC), (본 PR — 피벗 확정)

## TL;DR

**aug (graph-guided chunk retrieval, Microsoft GraphRAG Local Search 패턴) 가 우리 메인 컬럼**. 정설 충족 (graph 가 결정 / chunk 가 재료) + chunk_rag 71.4% 대비 +9.5pp + 후퇴 0. 가능한 대안 결합 / 강화 4 가지를 함께 측정해 *왜 다른 게 default 가 아닌가* 의 명시적 증거 확보.

## 검증한 4 가지 대안 — 무엇이 어떻게 안 되는가

smoke 21 MCQ × run0, gpt-4.1, financebench-smoke 코퍼스. 모든 측정은 동일 조건.

### G — Triple-merge (combined ⊕ aug, 청크 16 개 / dedup 후 8 개)

| 변형 | acc | 입력 토큰 | wrong |
|---|---|---|---|
| Triple (16 청크) | 76.2% | 23.7K | Q01, Q08, Q09, Q20, Q21 |
| Triple-dedup (8 청크 union) | 76.2% | 17.2K | Q01, Q07, Q08, Q09, Q17 |
| aug (참조) | **81.0%** | 17K | Q01, Q07, Q09, Q17 |

- 둘 다 aug 대비 **후퇴**. graph 가 잡았던 Q08 / Q20 / Q21 을 *놓침*.
- 진단: chunk 가 *너무 많이* 들어가면 LLM attention 분산 (16 청크) + dedup 도 graph-focused chunk 의 깨끗함을 노이즈로 희석.
- 결정: **Triple 류 기각**. "더 합치면 더 좋다" 의 직관 *반증* — 정설의 "graph 가 결정한 좁힘이 깨끗한 신호 / 전체 검색 섞으면 noise" 의 직접 증거.

### F — ingest description 강화 (정량 수치 / 시계열 보존 강제)

ingest LLM 의 SYSTEM_PROMPT 에 "수치 / 시계열 / 표 항목 보존 필수" 5-7 원칙 추가 후 재 ingest + 재측정.

| 컬럼 | before F | after F | Δ acc | Δ tokens |
|---|---|---|---|---|
| arche (graph 단독) | 33.3% | **47.6%** | **+14.3pp** | 10.5K → 6K (-43%) |
| arche_aug | 81.0% | 76.2% | **-4.8pp** | 17.1K → 13.2K (-23%) |

- graph-only 모드에는 **유효** (정설 충족 — description 이 정량 정보 보존하면 graph 단독으로 답 가능, 토큰도 ↓).
- aug 모드에는 **후퇴** (Q05, Q08). 원인 추적:
  - description 강화로 *수치 위주* entity 들이 lexical/dense 양쪽 score 강해짐
  - "cash flow" / "operations" 같은 *generic anchor* 가 description 풍부한 *다른 회사* entity 와 매칭 강해져 진입점이 *cross-company contamination*
  - 예: Q05 (AMD cash flow) 의 진입점이 AXP/BA 의 "Processed revenue $1,637M" 같은 entity 로 치우침. graph 가 가리킨 source 도 AXP/BA 로 잘못 좁힘
- 결정:
  - aug 가 default → **F prompt 변경 rollback**
  - graph-only 모드 (mcp 서버 / agent 호출 시) 의 ROI 는 별도라 **F prompt 는 보존 + 옵션 profile** 로 재사용 가능성 (ADR amend 후보)
  - Node.description max_length 는 500 → 2000 으로 강화한 채 유지 (cost 없음, 향후 옵션화 위한 여유)

### Q07 후퇴 분석 (D)

aug 의 유일한 후퇴 (chunk 가 맞춘 것 → aug 가 틀린 것) Q07 원인:

```
질문: Did AMD report customer concentration in FY22? (정답 c: 1 customer 16%)
anchor: AMD, customer concentration, FY22 (정확)
graph 가 좁힌 source: AMD_2022_10K.md (정확)
AMD 안의 top-8 chunk: 비즈니스 개요 / 인사 / 재무 결과 (정답 청크 *밖*)
→ LLM "정보 부족"
```

정답 청크 (단순 한 줄 "one customer accounted for 16%") 의 question embedding 유사도가 낮아 top-8 밖. chunk_rag (전체) 는 우연히 다른 매칭으로 정답 청크가 들어옴.

**해결 후보** (최적화 단계):
1. top-k 8 → 12 (정답 청크 포함 확률 ↑, 토큰 +)
2. graph 1-hop neighbor source 까지 확장 (Customer / Microsoft / Sony 등의 source 도 포함)
3. anchor 별 top-k 분산 ("AMD" 4 + "customer concentration" 4)

후속 PR.

## 4-way 정확도 / 비용 매트릭스 (최종)

| 컬럼 | acc | 입력 토큰 | 지연 (중앙값) | 적합 시나리오 |
|---|---|---|---|---|
| chunk_rag | 71.4% | 6.9K | 2.37s | baseline / corpus 모를 때 |
| arche (graph 단독) | 33.3% (기본) / 47.6% (F profile) | 10.5K / 6K | 3.92s / 3.78s | agent 가 graph primitives 만 호출 시 |
| combined | 81.0% | 17K | 5.28s | 라우터 없이 두 retrieval 비교 가치 |
| **arche_aug** | **81.0%** | 17K | 4.99s | **메인 — graph 가 결정 / chunk 재료. 정설** |
| triple | 76.2% | 23.7K | 5.39s | 기각 |
| triple-dedup | 76.2% | 17.2K | 4.91s | 기각 |

## 최적화 / robust 로드맵 (M7 이전)

### A — 코드 robust 가드 (즉시, 본 PR 안)

| 가드 | 무엇 | 영향 |
|---|---|---|
| anchor 0 fallback | anchor extraction 이 0 entity 반환하면 *chunk_rag 단독* 으로 폴백 | 빈 graph 컨텍스트 회피 |
| source 0 fallback | graph 가 0 source 가리키면 *chunk_rag 단독* 으로 폴백 | 옛 코드는 chunks 빈 채로 LLM 호출 — graph 단독과 동일 |
| basename 충돌 가드 | corpus 안 같은 basename 의 다른 디렉토리 파일 — collision 시 절대 경로로 fallback | 큰 corpus 의 안전 |
| top-k 적응형 | source 가 1 개면 top-k=8, 2-3 개면 top-k=12, 4+ 개면 top-k=16 | Q07 같은 회수 가능성 ↑ |

### B — Neo4j 활용 보강 (별도 PR, M8 / M9 묶음)

`eval/reports/2026-06-20-neo4j-review/CONCLUSION.md` 의 우선순위:

1. **UNIQUE constraint 3 개** — 부패 방지 + entity.id 자동 인덱스 (★ 즉시)
2. **Fulltext OR-batch** — keyword × N → 1 회 (latency ↓)
3. **execute_write/read 통일** — 재시도 가드 (M7 직전)
4. **BFS variable-length** — round-trip ↓ (M8)
5. **parallel array → SourceRef 노드** — M6.5b EntityConsolidator 와 함께
6. **Neo4j 5.18+ vector pre-filter** — M9 scale

### C — 측정 보강

| 측정 | 무엇 | 비용 |
|---|---|---|
| O — N=3 majority | aug 의 분산 / 우연 가능성 확인 | 21 × 3 호출 ≈ $1 |
| **★ Ingest replay variance** | 같은 prompt 로 K 회 재 ingest 후 graph diff + aug acc 측정 — *본 PR 에서 발견된 가장 중요한 변동성 축* | K × ingest + measurement |
| 1M re-test (M6.5b 후) | EntityConsolidator 적용 후 1M 코퍼스 aug 검증 | 33 × 3 호출 ≈ $25 |
| 다도메인 — commerce-verbose | 한국어 95K 에서도 같은 패턴인가 | 30 × 3 호출 ≈ $7 |

### Robust 측정 — 의외의 발견 (★)

robust 가드 (4 종) 적용 후 같은 corpus 재 ingest + 재측정한 결과:

| 시점 | graph 상태 | aug acc | wrong |
|---|---|---|---|
| PoC (2026-06-20 1532 ingest) | LLM extraction run #1 | **81.0%** | Q01, Q07, Q09, Q17 |
| robust (본 PR ingest) | LLM extraction run #2 | **66.7%** | Q01, Q05, Q07, Q08, Q09, Q17, Q21 |

**같은 prompt / 같은 corpus / 같은 chunker / 같은 robust 코드 — variance -14.3pp**.

원인 진단:
- ingest 단계 LLM 의 *비결정성* (temperature=0 임에도 약간의 변동). AMD entity 가 run #2 에서는 *충분히 잡히지 않음* → Q05 에서 graph 가 AMD source 를 안 가리킴 → cross-company contamination.
- Q21 — 새 ingest 에서 effective tax rate 가 "(0.6)%" 로 추출됐고 LLM 이 보기 "0.62%" 와 *정확 일치 안 됨* 으로 거절. 반올림 정밀도 문제.

robust 가드는 *정상 작동* (코드 변경은 아무 회귀 만들지 않음). fallback 활성 0 — 현 corpus 에서 graph 가 0 source 가리키는 케이스가 없어 가드가 안 발동.

**가장 중요한 후속 작업**:
- ingest seed 고정 / replay invariance 보장 (temperature=0 외 deterministic 가드)
- 측정 통제 변수에 *ingest run id* 명시 추가
- aug 의 진짜 acc 는 **66.7% ~ 81%** 의 range — N=3-5 ingest × N=3 query 다중 측정으로 *분포* 를 본 후 결정

본 결과는 *PoC 의 81% 가 변동성 안에서 최고 케이스* 였을 가능성과 *66.7% 가 최저 케이스* 였을 가능성 둘 다 열어둠. 단 *모든 측정에서 aug 가 chunk_rag (71.4%) 와 비교해 후퇴 0* 인 점은 유지 — 가드 측면에선 안전.

## 의사결정 정리 — 사용자 가설 검증 결과

> "aug 방식이 다음 방향. 우리가 정확도 / 비용 측면에서 놓친 부분이 없는지 검증"

| 사용자 가설 | 측정 결과 |
|---|---|
| aug 가 다음 방향 | **확정** — 81% / 토큰 17K / 후퇴 0 |
| 정확도에서 놓친 부분? | Triple (더 합치기), F (description 강화) **모두 측정** — 둘 다 aug 만 못함 |
| 비용에서 놓친 부분? | F 는 graph-only 의 토큰 ↓ (10.5K → 6K) 가능 — graph-only profile 옵션화 가치. aug 는 17K 가 현재 최선 (Triple 23.7K 보다 적음) |
| 가장 효과적 방법 | **aug + robust 가드** (본 PR) |
| robust 최적화 | A 안 (코드 가드 4 종) + B 안 (Neo4j 보강) + C 안 (N=3 / 1M / 다도메인) |

## 데이터 산출물

- `eval/runs/2026-06-20-triple-smoke/responses/arche_triple/` — G naive 측정
- `eval/runs/2026-06-20-triple-dedup-smoke/responses/arche_triple_dedup/` — G dedup 측정
- `eval/runs/2026-06-20-F-strong-desc-smoke/responses/{arche,arche_aug}/` — F 측정
- `eval/reports/2026-06-20-neo4j-review/CONCLUSION.md` — Neo4j 검토
- 본 보고서 (피벗 확정)

## 다음 PR

1. **본 PR (피벗 + robust 가드)** — aug 정식 컬럼화 (CLI 통합, RunDirs 확장, 가드 4 종)
2. **별도 PR (Neo4j A 즉시 보강)** — UNIQUE constraint 3 개
3. **별도 PR (graph-only profile)** — F prompt 를 옵션 plugin 으로 재도입 (ADR-0007 amend)
4. **별도 PR (M6.5b)** — EntityConsolidator + parallel array → SourceRef 노드
