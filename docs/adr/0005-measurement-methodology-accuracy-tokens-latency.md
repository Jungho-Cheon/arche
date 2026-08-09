# ADR-0005: MVP 측정 방법론 — 정확도, 토큰, 지연

Status: accepted
Date: 2026-06-15

## TL;DR

ADR-0001 의 Pareto 우월 가설은 **정확도 + 토큰 비용 + 응답 지연** 세 축에서 동시에 측정해야 검증된다. 측정 방식을 다음과 같이 확정한다.

- **질문 형식** — 30 개 **MCQ + 이유 서술** . 각 질문은 4-5 지선다 (정답 1개 + "정보 부족" 옵션 포함) + 시스템이 *왜 그 선택지를 골랐는지* 이유 서술 강제.
- **정확도 채점** — Correctness (0/1, MCQ 자동) + Reasoning quality (0-2, LLM judge + spot-check) + Faithfulness (0-1, LLM judge + spot-check). 문항당 0-4 점.
- **토큰** — 컬럼별, 질문별, LLM 호출별 입출력 토큰 합계. Arche 는 anchor 추출 + 답변 생성 두 호출 모두 계산. ingestion 토큰은 별도 계산.
- **지연** — 질문당 wall-clock. 중간값 + p95.
- **재현성** — N=3 회 측정, 중간값 보고, 전체 prompt/response/timing 로그 보존.
- **보고서** — 한 장. *3 컬럼 × 3 메트릭 = 9 칸 표* + failure mode breakdown + 한 단락 해석.

> **MCQ (Multiple Choice Question)** — 객관식 문항. 정해진 선택지 중 하나를 고르게 하는 형태. 자유 서술 (free-form) 의 *주관 채점* 부담을 제거하면서, *어떤 실패 모드로 틀렸는지* 를 distractor 설계로 추적할 수 있다.
>
> **LLM-as-judge** — LLM 에게 *(질문, 정답, 시스템 답변)* 을 보여주고 rubric 기준으로 채점시키는 방식. 2024-2026 의 RAG 평가에서 표준화된 접근.

## 이 ADR 을 읽는 이유

- ADR-0001 의 Pareto 가설을 *실제로 어떻게 잴 것인가* 가 궁금하다면
- "정확도 점수가 0.78 vs 0.81" 같은 보고서 숫자가 *어떻게 산출되었는지* 추적하고 싶다면
- 본인 도메인에 같은 측정 방법론을 옮길 때 무엇을 통제해야 하는지

## 읽기 전 권장 배경

- [ADR-0001 — 프로젝트 정체성과 MVP 검증 가설](./0001-project-identity-and-mvp-validation-hypothesis.md) — *왜* 측정이 정확도/토큰/지연 세 축인가의 가설 맥락.

## Context — 왜 이 결정이 필요했나

ADR-0001 D2 의 가설은 *Pareto 우월* — Arche 가 두 대안 (full-context LLM, 청크 벡터 RAG) 에 대해 *한 축에서 동등하면서 다른 축에서 우월* — 을 주장한다. 이 주장은 두 축 (정확도, 비용) 모두에서 측정 결과가 있어야 검증된다. *한 축만 측정* 하면 가설의 절반만 답하게 된다.

또한 *측정 방식이 모호하면 결과 해석이 갈린다* . "정확도가 0.78 이다" 라는 숫자가 어떻게 산출되었는지가 명확하지 않으면, 보고서를 6 개월 뒤 다시 봤을 때 *그 숫자가 무엇을 의미했는지* 를 재구성할 수 없다.

MVP 측정은 *한 번* 일어난다 (ADR-0002 D6 에 따라 자동화 평가 파이프라인은 out of scope). 그래서 *이 한 번* 의 측정이 *재현 가능하고 해석 가능* 해야 한다. 자동화는 없지만 *명세는 자동화 가능한 수준의 정밀도* 로 기술한다 — 그래야 post-MVP 에서 자동화 평가가 들어올 때 본 ADR 을 옮겨와 그대로 쓸 수 있다.

마지막으로 *2024-2026 RAG 평가 분야의 진화* 가 본 ADR 의 선택을 뒷받침한다. free-form 답변을 LLM-as-judge 로 채점하는 방식은 *position bias, length bias, format bias 등 judge 자체 편향* 이 알려져 있다. 본 ADR 은 *MCQ + 이유 서술 + 하이브리드 spot-check* 의 결합으로 이 편향들을 우회한다.

## Decision — 무엇을 결정했나

### D1. 질문 형식 — MCQ + 이유 서술

각 평가 질문은 다음 구조를 따른다.

```yaml
id: Q01
domain_pattern: multi-hop      # multi-hop / synonym / cross-source 등
hops_required: 3                # 그래프 traversal hop 수
question: "쿠폰 X 가 어떤 상품에 적용되나요?"
options:
  - id: a
    text: "상품 A"
    is_correct: true
    failure_mode_tested: null   # 정답에는 failure mode 없음
  - id: b
    text: "상품 B"
    is_correct: false
    failure_mode_tested: "missed_category_hop"  # 카테고리 제약을 놓침
  - id: c
    text: "상품 A 와 B"
    is_correct: false
    failure_mode_tested: "missed_promotion_filter"  # 프로모션 조건을 놓침
  - id: d
    text: "정보 부족 / 알 수 없음"
    is_correct: false
    failure_mode_tested: "retrieval_failure"  # retrieval 자체 실패한 honest 답
reference_reasoning: |
  쿠폰 X 는 프로모션 P 에 속하고, P 는 카테고리 C 에만 적용되며,
  C 에는 상품 A 만 있으므로 정답은 (a) 상품 A.
```

핵심 규칙.

- **선택지 개수** — 4 지선다 + "정보 부족 / 알 수 없음" = 5 개가 디폴트. 도메인 특성상 5 개가 부자연스러우면 4 개도 허용 (단, "정보 부족" 옵션은 반드시 포함).
- **정답은 1 개** — 복수 정답은 채점을 복잡하게 한다.
- **distractor 의 failure mode 명시** — 각 오답이 *어떤 실패 모드를 테스트하는지* 메타데이터로 기록. 보고서의 *failure mode breakdown* 분석의 근거가 된다.
- **reference reasoning** — 정답으로 가는 경로를 본인이 미리 작성. *Reasoning quality 채점* 의 비교 기준.

### D2. 시스템 응답 형식 — 강제 JSON

세 컬럼 모두 답변을 동일한 JSON 으로 받는다.

```json
{
  "choice": "a",
  "reasoning": "쿠폰 X 는 프로모션 P 에 속하고, P 는 카테고리 C 에만 적용 가능하며, C 에 속한 상품은 A 뿐이므로 정답은 상품 A 입니다."
}
```

프롬프트에 *반드시 위 JSON 스키마로 응답* 임을 명시. 출력 파싱 실패는 *Correctness 0, Reasoning 0, Faithfulness 0* 으로 처리 (시스템이 형식을 못 맞춘 것도 실력의 일부).

### D3. 정확도 채점 — 3 차원, 총 0-4 점

각 답변에 세 점수를 매긴다.

| 차원 | 만점 | 채점 방식 | 비고 |
|---|---|---|---|
| **Correctness** | 1 | `choice` 가 `is_correct: true` 인 옵션과 일치하면 1, 아니면 0 | *자동 채점, judge 불필요* |
| **Reasoning quality** | 2 | LLM judge 가 *reference_reasoning* 과 시스템의 `reasoning` 을 비교. 정답 경로의 *핵심 hop 들이 식별되었는가* . 2점 = 모든 핵심 hop 식별, 1점 = 일부 hop 식별, 0점 = 핵심 hop 누락 또는 잘못된 경로 | LLM judge 1차 + spot-check |
| **Faithfulness** | 1 | LLM judge 가 `reasoning` 의 모든 주장이 *제공된 컨텍스트* (full-context 의 코퍼스 / chunk RAG 의 청크 / Arche 의 서브그래프) 로 뒷받침되는지 확인. hallucination 없으면 1, 있으면 0 | LLM judge 1차 + spot-check |

문항당 0-4 점. 30 문항 합계 / 30 = 컬럼 평균 (0-4 스케일).

### D4. LLM-as-judge 구성

- **Judge 모델** — 시스템 답변 생성에 쓰는 LLM 과 *다른 계열* 의 모델 사용. 예: 시스템이 GPT-4 면 judge 는 Claude 또는 Gemini. 자기 편향 (self-preference bias) 회피.
- **Judge 프롬프트** — Reasoning quality 와 Faithfulness 각각 별도 프롬프트. 각 프롬프트는 *rubric* + *판단 근거 서술 강제* + JSON 출력 강제.
- **순서 무작위** — judge 에 답변을 보여줄 때 컬럼 순서를 *질문마다 무작위* 로. position bias 회피.
- **컬럼 익명화** — judge 에게 *"답변 A / B / C"* 로 보여주고 (1) full-context / (2) chunk RAG / (3) Arche 라벨을 숨김.

### D5. Spot-check — 본인 직접 검증 트리거

LLM judge 의 결과 중 다음 케이스를 본인이 직접 재검토.

1. **Correctness = 1 인데 Reasoning quality = 0** → "우연히 맞춤" 후보. 본인 확인.
2. **Faithfulness = 0 인 모든 케이스** → hallucination 은 중요하므로 전수 확인.
3. **컬럼 간 순위가 도메인 직관과 어긋나는 케이스** → 예: 도메인 직관상 명확히 Arche 가 유리한 질문인데 chunk RAG 가 더 높은 점수 받은 경우.

경험적으로 spot-check 대상은 전체의 *10-20%* (3 차원 × 30 문항 × 3 컬럼 = 270 점수 중 30-50 개). 본인 시간 *30 분 ~ 1 시간*.

본인 판정이 judge 와 다르면 *본인 판정으로 덮어쓰기* . 보고서에 *spot-check 으로 덮어쓴 케이스 수* 를 부록으로 기록.

### D6. 토큰 측정

각 컬럼과 각 질문에서 *모든 LLM 호출* 의 입출력 토큰을 합산.

| 컬럼 | LLM 호출 수 (질문당) | 토큰 합계 = |
|---|---|---|
| Full-context LLM | 1 | (전체 코퍼스 + 질문) input + 답변 output |
| Chunk vector RAG | 1 | (top-k 청크 + 질문) input + 답변 output |
| Arche | 2 | (질문) input + (anchor JSON) output + (서브그래프 + 질문) input + 답변 output |

**Arche 의 두 호출을 모두 계산하는 게 중요하다** — anchor 추출 비용을 숨기면 가설 검증이 부정직해진다.

**Ingestion 토큰은 별도 계산** — 컬럼별로 *코퍼스 → 인덱스/그래프* 구축에 쓰인 LLM 토큰을 한 번 합산. 보고서에 *ingestion 비용 (1회성)* + *질의 평균 비용 (반복성)* 두 줄로 기록.

토큰 카운트는 *LLM provider 의 usage 응답* 을 그대로 사용. 자체 토큰 추정 (tiktoken 등) 은 백업.

### D7. 지연 측정

각 컬럼과 각 질문에서 *질문 전송 → 최종 답변 수신* 까지의 wall-clock time 을 ms 단위로 기록.

- 컬럼별 30 개 측정값 → 중간값 + p95 보고.
- 통제: *같은 시간대* (같은 날 연속 측정), *같은 네트워크 조건* (같은 머신/연결), *순차 실행* (병렬 실행 시 API rate limit / 서버 부하 변동이 결과를 흐림).
- Arche 는 *anchor 추출 + 그래프 traversal + 답변 생성* 의 합. 각 단계도 별도 기록.

### D8. 재현성 — N=3 회 측정

API 응답의 비결정성 (특히 LLM) 을 완화하기 위해 *전체 측정 절차를 3 회 반복* . 컬럼별 평균값 (정확도) / 중간값 (토큰, 지연) 을 보고. *3 회 모두의 raw 데이터* 를 로그로 보존.

LLM 호출의 `temperature` 는 *0 또는 최저값* 으로 고정. seed 가 지원되는 모델은 동일 seed 사용.

### D9. 로그 보존

측정 한 번에 다음을 *전체 보존* .

- 30 개 질문의 정의 (YAML)
- 각 컬럼, 각 질문, 각 회차의 raw input prompt, raw output response, latency
- LLM judge 의 raw input/output
- Spot-check 으로 덮어쓴 항목과 본인 판정 근거

저장 위치는 `eval/runs/YYYY-MM-DD/` (구현 단계 결정 가능). git LFS 또는 별도 스토리지 검토.

### D10. 보고서 형식 — 한 장

MVP 종료 시점에 보고서 한 장을 다음 구조로 작성한다.

```
# Arche MVP 측정 보고서
Date: YYYY-MM-DD | Domain: 상거래 비즈니스 규칙 | N: 30 questions × 3 runs

## 핵심 표
                     | Accuracy (0-4) | Tokens/Q (median) | Latency/Q (median, p95)
Full-context LLM     |  X.XX ± SD     |  X,XXX,XXX        |  XX,XXX ms / XX,XXX ms
Chunk vector RAG     |  X.XX ± SD     |    X,XXX          |     X,XXX ms /  X,XXX ms
Arche           |  X.XX ± SD     |    X,XXX          |     X,XXX ms /  X,XXX ms

Ingestion cost (one-time): Full-context X | Chunk RAG XX,XXX tokens | Arche XX,XXX tokens

## Pareto 우월 검증
- vs Full-context: 정확도 차이 ΔX.XX, 토큰 비율 1:XX. → [Pass / Fail / Partial]
- vs Chunk RAG: 정확도 차이 ΔX.XX, 토큰 비율 1:X. → [Pass / Fail / Partial]

## Failure mode breakdown (오답 distribution)
                     | missed_hop | wrong_relation | retrieval_fail | other
Full-context LLM     |    X       |       X        |       X        |   X
Chunk vector RAG     |    X       |       X        |       X        |   X
Arche           |    X       |       X        |       X        |   X

## 한 단락 해석
[결과의 의미. 가설이 검증됐는가, 부분 검증인가, 거부됐는가. 다음 행동 한 줄.]

## 부록
- Spot-check 으로 덮어쓴 케이스 수와 사유
- 사용한 모델 버전 (시스템 LLM / judge LLM / 임베딩 모델)
- 측정 환경 (네트워크, 머신)
```

## Considered Options

### 옵션 1 — Free-form 답변 + LLM-as-judge 단독

거부. *주관 편향이 들어간다* . 자유 서술 답변을 judge 가 채점하면 (a) length bias (긴 답변 선호), (b) format bias (구조화된 답변 선호), (c) position bias (먼저 보여준 답변 선호) 가 모두 작동한다. 본 ADR 의 D4 무작위/익명화로 일부 완화되지만, *MCQ 정답 일치는 자동 채점이라 편향 자체가 없다* 는 점이 결정적으로 우월하다.

또한 free-form 은 *우연 정답* (틀린 이유로 맞은 답) 을 잡지 못한다. MCQ + 이유 서술은 두 차원을 분리해 잡는다.

만약 이걸 택했다면, 보고서의 정확도 점수가 *어느 정도까지 judge 편향 때문인지* 가 불투명해져 가설 검증의 신뢰도가 떨어졌을 것이다.

### 옵션 2 — MCQ 만 (이유 서술 없음)

거부. *우연 정답을 못 잡고 hallucination 도 못 잡는다* . 정답을 *왜* 골랐는지 모르면, 시스템이 진짜로 hop 을 따라간 건지 추측한 건지 구분 못 한다. 또한 답변에 hallucination 이 있어도 (예: 정답을 골랐지만 이유에 *존재하지 않는 관계* 를 인용) 잡지 못한다.

만약 이걸 택했다면, *우연 맞춤이 많은 시스템* 이 *진짜로 잘하는 시스템* 으로 잘못 평가됐을 가능성이 있다.

### 옵션 3 — 본인 직접 채점 only (LLM judge 없음)

거부. *MVP 한 번에는 가능하지만 재현이 안 된다* . 본인이 90 개 답변을 1-2 시간 안에 채점하는 건 가능하지만, *같은 측정을 6 개월 뒤 다시 할 때* 본인의 채점 기준이 *드리프트* 된다. LLM judge 가 있으면 *rubric 이 코드로 보존* 되어 재실행 시 같은 기준이 작동한다.

또한 *spot-check 만* 으로도 본인 판단이 측정에 들어오므로, 본인 시간을 *전수 채점* 에 쓰지 않고 *판단이 갈리는 곳* 에만 집중할 수 있다.

만약 이걸 택했다면, MVP 측정은 한 번 가능했겠지만 post-MVP 의 회귀 측정 / 다른 도메인 측정에 같은 방법론을 옮기기 어려웠을 것이다.

### 옵션 4 — N=1 회 측정

거부. *LLM API 응답의 비결정성이 결과를 흐린다* . 같은 프롬프트라도 LLM 응답은 *temperature 0 에서도* 약간씩 다르다. N=1 측정에서 한 컬럼이 한 질문에서 우연히 잘 답했다는 이유로 *Pareto 우월* 결론이 뒤집힐 수 있다. N=3 은 *중간값* 으로 이 노이즈를 흡수한다. N=5+ 가 더 안전하지만 측정 비용이 비례 증가 — N=3 이 *최소 합리적 N* 이라는 RAG 평가 분야 통념을 따른다.

### 옵션 5 — Distractor 의 failure mode 메타데이터 생략

거부. *보고서가 "어디서 실패하는가" 를 짚지 못한다* . 정확도 점수만 있고 *왜 틀렸는지* 의 정보가 없으면 보고서가 "Arche 가 0.81, chunk RAG 가 0.78" 같은 *단일 숫자 비교* 로 끝난다. failure mode breakdown 이 있으면 "chunk RAG 는 missed_hop 실패가 많고 Arche 는 retrieval_failure 가 많다" 같은 *원인 분석* 이 가능해진다 — 이게 *post-MVP 의 다음 행동* 을 결정하는 핵심 정보다.

만약 이걸 택했다면, MVP 종료 후 *다음 무엇을 개선할지* 가 보고서에서 도출되지 않아 별도 분석 작업이 필요했을 것이다.

## Consequences

### 즉시 영향

- 30 개 MCQ 질문 설계가 *상거래 검증 데이터 준비* 의 일부가 된다. 각 질문에 정답, distractor, failure mode, reference reasoning 4 가지 메타데이터를 본인이 작성해야 한다 — 자유 서술 30 개보다 *작성 시간이 1.5-2 배* 들지만 채점 시간이 *수배 줄어든다* .
- 측정 코드는 *비교 하니스* (`eval/` 디렉토리, 구현 단계 결정) 에 들어간다. Arche 본체에 포함되지 않는다.
- LLM judge 비용이 측정 예산에 추가 (전형적으로 $5-20 수준).
- 본인 spot-check 시간 30 분-1 시간이 *MVP 종료 작업의 일부* .

### 코드 작업 시 기억할 점

- LLM 호출 어디서든 *usage (input tokens / output tokens)* 응답을 *모두 로깅* . 토큰 카운트는 사후에 못 만든다.
- Arche 의 *anchor 추출 호출과 답변 생성 호출* 을 별도 로깅. 합산이 보고서의 *Arche 토큰* 컬럼이 된다.
- Judge LLM 호출 시 *답변 익명화 (A/B/C)* 와 *순서 무작위* 를 코드에서 강제. 사람 실수 여지 없게.
- 측정 N=3 회. 한 회차 실패 시 *그 회차만 재실행*, 모든 회차 다시 하지 않음 (단 raw 데이터에 회차 식별자 명시).
- `temperature = 0` (또는 최저값) 고정. 변경 시 *측정 무효* — 코드에 상수로 박고 변경 차단.

### 운영자 평가 게이트와의 관계

본 ADR 은 *MVP 종료 시점 1 회 측정* 의 방법론이다. *자동화 평가 파이프라인 / CI 통합 / 회귀 게이트* 는 ADR-0002 D6 에 따라 out of scope. 단 본 ADR 의 명세가 자동화 가능한 정밀도로 기술되어 있어, post-MVP 에서 자동화 평가가 들어올 때 *본 ADR 을 옮겨와 그대로 사용* 가능.

## Related

- [ADR-0001 — 프로젝트 정체성과 MVP 검증 가설](./0001-project-identity-and-mvp-validation-hypothesis.md) — *왜* 정확도/토큰/지연 세 축인가의 가설 맥락.
- [ADR-0002 — MVP 범위 경계](./0002-mvp-scope-boundaries.md) — 자동화 평가 파이프라인의 out of scope 위치.

### 외부 참고 자료

본 ADR 의 결정은 다음 2024-2026 자료를 참고했다.

- [Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena (arXiv 2306.05685)](https://arxiv.org/abs/2306.05685) — LLM judge 의 position/length/self-preference bias 정량화.
- [Lost in the Middle: How Language Models Use Long Contexts (Liu et al., TACL 2024)](https://arxiv.org/abs/2307.03172) — long context 정확도 감쇠 현상. full-context 컬럼 해석의 근거.
- [HELM Lite: A lightweight benchmark for evaluating language models (Stanford CRFM, 2024)](https://crfm.stanford.edu/helm/lite/latest/) — MCQ 평가의 표준 rubric.
- [RAGAS: Automated Evaluation of Retrieval Augmented Generation (arXiv 2309.15217)](https://arxiv.org/abs/2309.15217) — Faithfulness 메트릭의 표준 정의.
