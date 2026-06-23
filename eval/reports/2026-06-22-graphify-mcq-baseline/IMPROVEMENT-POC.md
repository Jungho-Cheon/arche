# 파괴적 개선 PoC — 그래프 단독 정답률 끌어올리기 (2026-06-22)

graphify 비교 측정(opentology 그래프 단독 21.2% << graphify 57.6%)을 받아, "graphify
를 훨씬 상회하는 그래프 단독" 을 목표로 *도메인 무관* 개선을 적용하고 Amcor 단일 회사로
개념 증명한 기록. 모든 변경은 특정 벤치마크에 과적합되지 않는 일반 규칙으로 작성했다.

## 적용한 일반 개선 4가지 (전부 도메인 무관, 유닛 테스트 green)

| # | 변경 | 파일 | 효과 |
| --- | --- | --- | --- |
| 1 | 답변 흐름 과보수성 완화 — 검색된 엔티티로부터의 상식 추론 허용(환각·수치 날조는 계속 금지) | `eval/.../prompts.py` OPENTOLOGY_ANSWER_SYSTEM | 전체 33문항 graph-only 21.2% → 33.3% (회피 'e' 26→22) |
| 2 | 정량 사실·표 완전 추출 — 측정값/표를 요약·누락 없이 구조화 추출, 수치 엔티티 name 에 소속 대상 포함(cross-company 오염 차단) | `apps/api/.../llm.py` SYSTEM_PROMPT 원칙 5·6 | 재무 수치가 그래프에 들어옴 (이전엔 전무) |
| 3 | 추출 청크 크기를 모델 컨텍스트(~90K 토큰)에서 분리해 작게(4K) | `apps/api/.../chunking.py` budget_tokens, `ingest.py` extraction_chunk_tokens | Amcor 2청크 → 30청크, 엔티티 80 → 799 (약 10배) |
| 4 | anchor 추출이 파생 지표(비율·마진·증가율)를 구성 입력 항목으로 분해 | `eval/.../prompts.py` ANCHOR_EXTRACTION_SYSTEM 원칙 3 | Q01 anchor 가 유동자산·유동부채·재고로 분해되어 해당 노드 검색 성공 |

## Amcor 개념 증명 (graph-only, Q01-Q04)

| 단계 | 정답 | 비고 |
| --- | --- | --- |
| 기준선 (옛 그래프, v1 프롬프트) | 1/4 | Q03 만. 수치 문항 전부 'e' |
| + 정량 추출 (큰 청크) | 2/4 | **Q04(수치 multi_hop) e→정답** — gross margin 직접 계산 |
| + 작은 청크(4K) | 2/4 | 799 엔티티, "Total current liabilities" 등 노드 등장 |
| + anchor 분해 | 2/4 | Q01 이 구성 항목 노드를 검색까지 도달 (추출 완성도에서 막힘) |

**핵심 성과**: graphify 와 옛 opentology 가 *둘 다 틀렸던* 수치 multi_hop(Q04)을, 도메인
하드코딩 없이 그래프 단독·저토큰(약 3.2K 토큰)으로 풀었다. 숫자를 그래프에 넣는 접근이
"graphify 가 구조적으로 못 푸는 영역"을 여는 것을 실증.

## 남은 병목 (정밀 진단)

1. **granular 표 추출 완성도** — Q01(quick ratio)은 유동자산·유동부채·재고 *구성값* 6개
   (2개 연도)와 산술이 필요. 30청크에서도 재고 note 의 원재료/재공품/완제품 분해값이
   완전히 안 잡힘. Neo4j 레퍼런스(SimpleKGPipeline)는 청크 256-1024 토큰을 쓴다 — 우리
   4K 를 더 줄일 여지.
2. **서사적 사실 recall** — Q02(인수 내역)은 "targeted acquisitions" 개념은 잡혔으나
   구체 인수 대상(체코·상하이·뉴질랜드)이 엔티티화되지 않음. 수치 외 narrative 추출 recall.
3. **description 라벨 정확도** — 일부 노드가 "Total current liabilities" 인데 description
   에 "non-current" 로 잘못 기재. 작은 청크에서 표 헤더 맥락이 끊겨 생기는 라벨 혼동.

## Neo4j 공식 스킬 교차 검증 (github.com/neo4j-contrib/neo4j-skills)

- **neo4j-modeling-skill**: 시계열·반복 측정은 *Bucket Pattern* (기간별 중간 노드)으로
  분리 권장 — supernode 회피. 우리 PoC 의 "값을 description 텍스트로" 는 안티패턴이며,
  *관측(observation) 노드* 로 격상하는 것이 정석 (사용자 지적과 일치).
- **neo4j-document-import-skill**: 청크 `FixedSizeSplitter(chunk_size=300)` — 우리의
  작은-청크 방향을 독립 검증(오히려 더 작음). 스키마 유도 추출 권장(개방 추출은 noisier).

## 다음 단계 (목표 "graph-only >> 57.6%" 완수까지)

1. **관측 노드 모델 격상** — 시계열 수치를 (지표 노드)-(기간별 관측 노드 {period,value,unit})
   로. Neo4j Bucket Pattern + 사용자 요청. 결정론적 계산·회사 간/기간 간 질의 가능.
2. **추출 청크 추가 축소(256-1024) + 표 헤더 맥락 보존** — granular 라인 항목 완성도.
3. **narrative recall 보강** — 수치 외 사건/관계 추출.
4. **전체 6개 회사 재적재 + 33문항 graph-only 재측정** — 집계 효과 확정. 비용 주의(작은
   청크 → 약 180 청크 추출). 이 측정으로 graphify 57.6% 대비 우열을 최종 판정.

부속: Amcor 응답 `eval/runs/poc-amcor-{numeric,general,smallchunk,anchor}/`, 코드 변경은
`apps/api/.../{llm,chunking,ingest}.py` + `eval/.../prompts.py`.

---

## 전체 6개 회사 재측정 — 정직한 부정적 결과 (2026-06-22 추가)

검증된 개선(정량 추출 + 작은 청크 4K + 답변 프롬프트 + anchor 분해 + Lucene 예약어
버그 수정)을 전부 반영해 **6개 회사 전체를 재적재**(5,654 엔티티 / 7,103 관계 / 236
청크 — 원본의 약 10배 밀도)한 뒤 33문항 graph-only 를 측정했다.

| 구성 | 정답률 |
| --- | --- |
| opentology v1 (원본 그래프, 과보수 프롬프트) | 21.2% |
| opentology v2 (원본 그래프 + 개선 답변 프롬프트) | **33.3%** |
| **opentology v3 (조밀한 새 그래프 + 개선 프롬프트 + anchor 분해)** | **21.2%** (회피 e=24) |
| graphify (기준선) | 57.6% |

**핵심: 추출을 늘렸더니 오히려 후퇴했다 (v2 33.3% → v3 21.2%).** Amcor 단일 회사
PoC 에서 통한 개선이 6개 회사 전체에서는 역효과.

### 원인 (응답·primitive 진단)

`get_subgraph` 가 `max_nodes=80` 상한에서 **truncated=True** (직렬화 50-56K 자).
그래프가 5,654 노드로 조밀해지자 진입점 2-hop 이웃이 80 노드를 크게 초과 →
*정답에 필요한 노드가 잘려나가고* 무관한 financial_metric 노드가 창을 채운다.
신호 대 잡음비가 붕괴. 원본 sparse 그래프(~수백 노드)에서 80-node 창이 충분했던
하이퍼파라미터가 조밀한 그래프에는 맞지 않는다.

### 교훈 — 병목이 추출에서 검색으로 이동

"더 많이 추출하면 그래프 단독이 좋아진다"는 단순 가정은 *틀렸다*. 노드를 늘리면
고정 retrieval 창(80 노드, 2 hop)이 더 작은 *비율* 만 담아 오히려 신호가 희석된다.
opentology 가 graphify 를 넘으려면 다음 *검색 측* 개선이 선행되어야 한다.

1. **namespace 회사 단위 스코핑 (ADR-0015)** — 진입점·서브그래프 검색을 질문 대상
   회사로 한정해 cross-company 노이즈 제거. (현재 6개 회사가 모두 default namespace
   에 섞여 있다.)
2. **적응형 서브그래프 선택** — 고정 80 노드 대신, 진입점 관련도 순 정렬 + 관련
   노드 우선 포함. 단순 N-hop BFS 가 아니라 점수 기반 절단.
3. **진입점 정밀도** — anchor 분해가 키워드를 늘리면 진입점이 diffuse 해진다.
   회사 + 핵심 지표로 좁히는 ranking 필요.

### 결론

정량 인식 추출·작은 청크·answer 프롬프트·anchor 분해·Lucene 버그 수정은 모두
유효한 일반 개선(단일 회사에서 입증)이지만, *조밀한 멀티 회사 그래프에서 그래프
단독이 graphify 를 넘으려면 retrieval 의 회사 스코핑 + 적응형 절단이 필수 선행 조건*
이다. 이번 측정은 그 사실을 데이터로 확정했다 — 다음 작업의 방향을 retrieval 로
재설정한다.

### 검증: truncation 가설 확정 (max_nodes 80 → 300)

재적재 없이 서브그래프 노드 상한만 80 → 300 으로 올려 33문항 재측정:

| 구성 | 정답률 |
| --- | --- |
| v3 (조밀 그래프, max_nodes=80) | 21.2% (회피 24) |
| **v4 (조밀 그래프, max_nodes=300)** | **30.3% (회피 21)** |

상한을 올리자 +9.1pp 회복 → *truncation 이 v3 후퇴의 주원인임을 확정*. 그러나 여전히
v2(33.3%, 옛 sparse 그래프)와 graphify(57.6%)에 못 미친다. 300 노드 창에 6개 회사의
지표가 혼재해 답변 신호가 희석되기 때문 — *남은 병목은 retrieval 의 회사 스코핑 부재*.

### 최종 결론 (이번 세션)

목표 "graph-only >> graphify 57.6%" 는 *이번 세션에서 미달*. 그러나 데이터로 확정한
사실:

1. 추출 개선(정량·작은 청크·anchor 분해)은 단일 회사에서 유효하나, *멀티 회사 그래프
   에서는 retrieval 스코핑 없이는 net-negative* (노드 밀도 ↑ → 고정 창이 신호 희석).
2. retrieval 창 확대만으로 일부(+9pp) 회복하나 graphify 를 넘기엔 부족.
3. **선결 조건 = 회사 단위 namespace 스코핑 검색** (ADR-0015). 진입점·서브그래프를
   질문 대상 회사로 한정해야 조밀 그래프의 cross-company 노이즈가 제거된다. 이는
   per-company namespace 로 재적재 + 검색 경로의 namespace 필터 배선이 필요 (다음 작업).

검증 코드 변경(전부 유닛 테스트 green, 미커밋): `apps/api/.../llm.py`(정량·표 추출
원칙), `chunking.py`+`ingest.py`(추출 청크 분리), `graph.py`(Lucene 예약어 버그 수정),
`eval/.../prompts.py`(답변·anchor 프롬프트), `eval/.../columns/opentology.py`(max_nodes).
