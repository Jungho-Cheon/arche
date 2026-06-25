# arche vs graphify — 그래프 단독 + 제품 비교 (FinanceBench 1M, 2026-06-22)

## 한 줄 요약 (불편하지만 정직한 결론)

동일 코퍼스(FinanceBench 1M, 6개 회사 10-K)에서 같은 33문항을 풀게 했을 때:

- **그래프 단독 비교(MVP 핵심 조건 "graphify 보다 우월한 그래프"): arche 21.2%
  로 graphify 57.6% 에 크게 못 미친다.** 현재 시점에서 arche 의 *그래프 생성*
  은 graphify 보다 우월하지 않다 — 오히려 열위다.
- **제품 전체(Combined RAG)로는 arche 75.8% 로 graphify 57.6% 를 앞선다.** 단
  이 우위는 그래프가 아니라 *청크 검색(원문 텍스트)* 이 만든 것이다.

즉, arche 는 "제품" 으로는 이기지만 "그래프 생성기" 로는 진다. MVP 가 명시한
성공 조건이 *그래프 생성 우위* 이므로, 이 결과는 파괴적 개선이 필요한 지점을 정확히
가리킨다.

## 비교 설계 (3-way, 통제 변수 동일)

| 컬럼 | 정보원 | graphify 대비 |
| --- | --- | --- |
| graphify (graph-only) | graphify 그래프만 (`graphify query`) | 기준선 |
| arche (graph-only) | arche 그래프 프리미티브만 (find_entities → get_subgraph) | 그래프 직접 비교 |
| combined (chunk+graph) | 청크 RAG 발췌 + arche 서브그래프를 단일 LLM 호출에 합침 | 제품 풀 역량 |

- 코퍼스/문항/정답 키 동일. 답변 모델 gpt-4.1, 임베딩 text-embedding-3-small 동일.
- graphify 측은 새 컨텍스트 서브에이전트 3개가 원문 없이 그래프만으로 답(별도 측정,
  같은 정답 키). arche/combined 는 `arche-eval run` N=1.
- arche 그래프는 2026-06-21 M7-D 1M 검증 적재본을 재사용(`--skip-setup`).

## 결과

| 지표 | graphify (graph) | arche (graph) | combined |
| --- | --- | --- | --- |
| 정답률 | **19/33 = 57.6%** | **7/33 = 21.2%** | **25/33 = 75.8%** |
| "정보 부족(e)" 회피 | 14/33 | **26/33** | 5/33 |
| 커밋했을 때 정답 | 14/19 commit | 7/7 commit | 25/28 commit |
| 평균 토큰/문항 | (서브에이전트, 별도) | 8,038 | **44,938** |
| 평균 지연(ms) | (서브에이전트, 별도) | 4,644 | 5,974 |

### domain_pattern 별

| 유형 | graphify | arche | combined |
| --- | --- | --- | --- |
| single_doc | 9/11 | 5/11 | 9/11 |
| cross_source | 6/9 | 1/9 | 8/9 |
| multi_hop | 4/13 | 1/13 | 8/13 |

## 왜 arche 그래프 단독이 이렇게 낮은가 (응답 원문 진단)

회피한 26문항 중 다수는 *관련 엔티티를 실제로 검색해 놓고도* "명시적으로 안 적혀
있다" 며 'e' 를 골랐다. 예:

- **Q13 (Amex 사업 지역)**: 서브그래프에 사업 부문(U.S. Consumer Services, Commercial
  Services, International Card Services 등)이 *나열되어 있었다*. 그런데 "각 부문이 어떤
  지역을 포괄하는지 설명이 없다" 며 회피. graphify 는 같은 수준의 노드에서 답을 추론해
  정답.
- **Q23 (Boeing 경기순환성)**: BCA/BDS/BGS 부문이 그래프에 있었으나 "경기순환적인지
  설명이 없다" 며 회피. graphify 는 BCA(상업 항공기) 노드로부터 경기순환 노출을 추론해
  정답.

원인은 두 가지가 겹친다:

1. **답변 흐름의 과보수성** — arche 답변 프롬프트가 "그래프에 직접 적힌 것만"
   강하게 요구해, 검색된 엔티티로부터의 *상식적 추론* 을 거부한다. 회피율 26/33 (79%)
   은 graphify 14/33 의 거의 두 배다. 커밋했을 때는 7/7 전부 정답 — 분별력 자체는 높다.
2. **노드 서술의 빈약함** — graphify 노드 라벨은 정량 맥락을 라벨에 직접 담는다
   ("Flexibles Segment (~76% net sales FY2023)"). arche 는 name/description 을
   분리하고 직렬화 시 그 맥락이 충분히 전달되지 않는 경우가 있다.

## 공통 한계 (양쪽 그래프 모두)

순수 수치 문항(Q01 quick ratio, Q05, Q28 재고회전율 등)은 graphify·arche 그래프
*둘 다* 실패한다. 두 그래프 모두 재무제표 라인 항목을 노드로 추출하지 않기 때문이다.
combined 가 이 문항들을 푸는 것은 *청크 RAG 가 원문에서 숫자를 직접 끌어오기* 때문이며,
그래프 기여가 아니다.

## 비용 경고 (가치 제안 "최소 토큰" 과 충돌)

combined 는 문항당 평균 44,938 토큰으로 arche 그래프 단독(8,038)의 5.6배다. 청크
stuffing 이 정확도를 끌어올리지만, arche 가 내세우는 "최소 토큰으로 관계 활용"
가치와 정면으로 충돌한다. 정확도를 그래프 쪽으로 끌어와 토큰을 줄이는 것이 제품의
정체성과 일치한다.

## 파괴적 개선 방향 (이 측정이 가리키는 것)

1. **그래프 단독 정답률을 graphify 수준(57.6%)으로 끌어올리기** — 최우선. 두 축:
   - 답변 흐름의 과보수성 완화: 검색된 엔티티로부터의 추론 허용(여전히 환각은 금지하되
     "나열된 부문 → 사업 성격" 같은 상식 추론은 허용).
   - 서브그래프 직렬화에 description/정량 맥락을 포함해 노드가 graphify 라벨만큼 자기
     설명적이 되도록.
2. **재무 수치 노드화** — 양쪽 공통 약점. quick ratio 류 라인 항목을 검색 가능한 노드/
   속성으로 추출하면 그래프 단독으로도 multi_hop 수치 문항을 풀 수 있다.
3. **회사 간 엔티티 동일성** — graphify 는 회사 간 엣지 0(파일 경로 단위 정체성).
   arche ADR-0009 `matched_existing_id` 는 이를 겨냥하나, 이번 33문항은 정답 출처가
   모두 단일 회사라 이 강점이 점수로 드러나지 않았다. 회사 간 비교 문항을 데이터셋에
   추가해야 이 우위가 측정된다.

## 재현 / 부속 자료

- arche/combined 응답: `eval/runs/2026-06-22-mcq-compare/responses/{arche,combined}/`
- 3-way 채점기: `eval/runs/2026-06-22-mcq-compare/grade.py`
- graphify 응답 + 채점기: `eval/runs/graphify-mcq-2026-06-22/`
- graphify 기준선 그래프 보존본: `eval/external/graphify-bench/financebench-2026-06-21/`
- 다음: arche 그래프 개선 후 재측정 + N≥3 분산 확인 + 회사 간 비교 문항 추가.
