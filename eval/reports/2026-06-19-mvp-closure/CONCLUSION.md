# MVP 종료 결론 — 2026-06-19

> 본 문서는 PRD 4 의 1 회 측정 결과에 대한 *사람의 해석*. 자동 채점 보고서는 `report.md`.

## 가설 (ADR-0001)

LLM 과 AI 에이전트가 도메인 지식의 *관계* 를 활용할 때, 그래프 기반 도구 (Arche) 가 베이스라인 (full-context, chunk RAG) 대비 **정확도, 토큰, 지연** 세 축 중 어느 축에서도 후퇴 없이 한 축에서 우위 (Pareto 우월) 를 가진다.

## 결과 한 줄

**미달**. 본 측정 도메인 (95K 토큰, 30 MCQ, multi-hop 중심) 에서 Arche 컬럼은 어느 축에서도 우위를 잡지 못했다.

## 수치

| 컬럼 | Accuracy | Tokens(중간값) | Latency(중간값) | 비용 |
|---|---|---|---|---|
| Full-context (gpt-4.1) | **100.0%** | 69K | 8.1초 | $12.7 |
| Chunk RAG | 96.7% | **4.7K** | **2.8초** | $1.6 |
| Arche | 96.7% | 8.3K | 5.8초 | $1.8 |

Pareto 판정 — 세 축 NG.

## 해석

1. **Corpus 규모가 작다 (95K)**. gpt-4.1 의 강력한 long-context 추론력이 전체 코퍼스를 한 번에 처리해 multi-hop 도 자체 추론으로 해결. 그래프 도구의 차별점이 묻혔다.
2. **Chunk RAG 가 의외로 강함**. top-k=8 청크면 95K 코퍼스의 multi-hop 한쪽은 충분히 잡혔다. 도메인이 *충분히 큰* 환경에서만 chunk RAG 의 한계가 드러난다는 가설을 본 측정이 확인했다.
3. **Arche 의 지연 5.8초**. anchor 추출 (LLM 1 회) + find_entities + subgraph 호출이 직렬화돼 누적. chunk RAG 의 2.8초 (벡터 검색 + LLM 1 회) 대비 2 배. primitive 호출 캐싱이나 anchor 모델 분리가 후속 ADR 의 시작점.
4. **Arche 의 wrong_choice 3 건**. anchor LLM 이 옳은 ULID 진입점을 못 잡는 경우. 본 회차에선 본 코퍼스의 별칭 (예: VIP = 프리미엄 멤버 = 골드 등급 = V 회원) 이 anchor 추출 단계에서 환원되지 못해 find_entities 가 빈 결과를 반환하는 경로가 신호.

## Post-MVP 1순위

1. **더 큰 corpus + 깊은 multi-hop 도메인** 으로 재측정 — gpt-4.1 long-context 가 한계를 보이는 영역에서 그래프 도구의 우위 확인.
2. **anchor 추출 정확도** 개선 — 별칭 환원 + ULID 매칭 신호 강화.
3. **Arche latency 단축** — primitive 호출 사전 캐싱과 병렬화.
4. **코드베이스 적재 ADR** (post-MVP 1순위) — AST + LLM 결합 그래프 추출. 본 측정의 자연어 corpus 와 별개 도메인 검증.

## 측정 데이터 소재

- 원본 raw: `eval/runs/2026-06-19-2126/` (gitignore 됨 — 로컬 한정)
- 영구 산출물 사본: `eval/reports/2026-06-19-mvp-closure/`
  - `report.md` — 자동 채점 보고서 (PRD 4 §8 형식)
  - `report_data.json` — 보고서 데이터 (JSON)
  - `meta.yaml` — 측정 제원 (모델, hash, hyperparams)
  - `judge_mapping.json` — 컬럼 익명화 매핑 (judge 편향 제거 검증용)
  - `CONCLUSION.md` — 본 문서

## 측정 제원 요약

- 모델 (답변): openai/gpt-4.1
- 모델 (judge): openai/gpt-4o
- 모델 (ingest 시 엔티티 추출): openai/gpt-4o-mini
- 임베딩: openai/text-embedding-3-small (1536d)
- N (질문당 반복): 3
- 코퍼스: `eval/datasets/commerce-verbose-20260618/` — 33 파일 (md 20 / pdf 10 / png 3), 95K 토큰
- 질문: 30 MCQ — multi_hop 9 / single_doc 8 / synonym_alias 7 / cross_source 6
- 그래프: Neo4j 5.15-community, 930 엔티티 / 33 ingestion runs
- Spot-check overrides: 0 건 (자동 채점만)
