# 검증 — 외부 에이전트 반복 + graph-guided source 근거 (2026-06-22)

사용자 제안("graphify 골격에 chunk RAG 도입, LLM 을 외부화해 여러 번 호출")을 *조밀한
그래프(5,654 노드) 위에서* 직접 측정. graph-only 가 density 때문에 21-30% 로 후퇴했던
바로 그 그래프를 시험대로 사용 — density 를 먼저 고치지 않은 채 대조.

## 측정 설계

새 컨텍스트 서브에이전트 3개(배치 11문항씩, 정답 키 없음)에게:
1. arche 프리미티브(REST `/entities/find`, `/subgraph`, `/neighbors`)를 **반복**
   호출해 관련 엔티티 + 그 노드의 `source_path`(어느 회사 문서인지)를 찾고,
2. 그 source 파일을 **grep 으로 좁혀** 정확한 수치/사실을 확인,
3. 빗나가면 재질의(파생 지표는 구성 항목으로 분해)하도록 허용.

## 결과 (동일 33문항)

| 방식 | 정답률 |
| --- | --- |
| arche graph-only (단발, 옛 그래프) | 21.2% |
| arche graph-only + 프롬프트 개선 | 33.3% |
| arche graph-only (조밀 그래프, 300노드) | 30.3% |
| graphify (graph-only, 에이전트 반복) | 57.6% |
| combined (chunk+graph 단발 내재화) | 75.8% |
| **AUG-AGENTIC (graph navigation + source 근거 + 반복)** | **97.0% (32/33)** |

domain_pattern: single_doc 11/11, cross_source 9/9, **multi_hop 12/13** (가장 어려운
수치 추론 범주가 거의 만점 — source 근거로 정확한 figure 확보).

비용: 33문항에 graph API 호출 36회 + source grep 34회 ≈ 문항당 graph 1회 + grep 1회.
서브에이전트 토큰 약 6-7K/문항 — combined(45K/문항)의 1/7 수준.

## density 질문에 대한 답 (데이터)

density 를 *고치지 않은* 조밀 그래프에서 97% 가 나왔다. graph-only 를 망쳤던 "서브그래프
300노드 통째 stuffing → 노이즈 희석" 문제가 이 방식에는 없다 — 그래프를 *답변 본문이
아니라 위치 안내자* 로만 쓰고, 정작 답은 좁혀 읽은 source 에서 나오기 때문. 즉
**density 는 graph-only 직렬화 프레임의 부작용이었지 근본 결함이 아니었음이 확정**.

## 정직한 단서 — 이 97% 에서 "그래프" 의 몫은 작다

`grounded_in` 분포: **source 31 / graph 1 / both 1**. 31/33 답이 source grep 에서
나왔고, 그래프는 주로 "어느 회사 문서인지" 를 확인하는 데 쓰였다. 그런데 **질문이 이미
회사 이름을 명시**한다(예: "Has AMCOR's quick ratio..."). 따라서 이 벤치마크에서 그래프의
*증분 기여* 는 분리되지 않는다 — 사실상 "에이전트가 회사 source 파일을 targeted grep
+ 반복 추론" 에 가깝다.

결론적으로 이번 측정이 강하게 입증한 것은:
1. **프레임의 우위** — 외부 에이전트 + 반복 + source 근거 = 단발 내재화(graph-only/
   combined)를 압도(97% vs 30-76%). 사용자의 아키텍처 방향이 옳다.
2. **density 비결함** — 조밀 그래프에서도 무너지지 않음.

분리되지 *않은* 것:
3. **그래프 자체의 증분 가치** — 33문항이 모두 단일 회사 답이고 질문이 회사를 명시하므로,
   그래프 없이 grep 만 해도 비슷할 가능성. 그래프의 진짜 값(관계 순회·문서 간 연결)은
   *cross-company 비교 문항* 에서만 드러나는데 이 데이터셋엔 없다.

## 다음 (그래프가 제 값을 하는지 분리하려면)

1. **ablation**: 같은 에이전트에게 그래프 없이 source grep 만 허용 → 그래프 유무 차이 측정.
2. **cross-company 비교 문항 추가**: "A 와 B 회사의 X 를 비교" 류. 여기서 그래프의 관계
   순회가 grep 단독을 넘는지 본다. (ADR-0009 cross-doc 동일성의 진짜 시험대.)
3. **아키텍처 결정 ADR**: "LLM 외부화 + 에이전트 반복 + graph-as-navigation + source
   근거" 를 product 방향으로 채택할지. combined(내재화 단발) 대비 정확도 +21pp, 토큰
   1/7 — 강한 채택 근거.

부속: 응답 `eval/runs/oto-aug-agentic-2026-06-22/result_batch_*.json`.
