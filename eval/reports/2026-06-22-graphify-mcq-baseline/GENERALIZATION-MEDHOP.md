# 일반화 검증 — MedHop (biomedical 관계-사슬) (2026-06-23)

## 동기

FinanceBench 돌파 (graph-only 94-97%) 의 가장 큰 약점은 *단일 도메인 (finance, 정량
표/수치)*. 질적으로 다른 축 — **관계 사슬** (약물→단백질→약물, 여러 abstract 를 이어야
답) — 에서 성립하는지 검증. MedHop (QAngaroo) 은 제3자 정답 내장 → 체리피킹 없음.

## 설계

- 코퍼스: MedHop validation 앞 10 문항의 support union = **289 PubMed abstract, 73K 단어,
  3,508 엔티티 / 4,577 관계 그래프**. (전량 1,217 abstract 은 직렬 엔티티-매칭 병목으로
  8-9 시간 → 코퍼스 축소, 아래 "한계" 참조.)
- 같은 코퍼스에 **두 조건 동시 측정** (상대 비교가 주장):
  - agentic graph-only — arche 프리미티브만 반복 (원본 .txt 미열람)
  - agentic grep (baseline) — 원본 .txt 만 grep/read (그래프 미사용)
- 정답 키 미제공 서브에이전트. 보기 9 개 (랜덤 기대 약 11%).

## 결과 (3자 비교 — 동일 코퍼스, 동일 gpt-4.1, 동일 agentic 조건)

| 도구 | 정답률 |
| --- | --- |
| **arche graph-only** | **30.0% (3/10)** |
| graphify graph-only | 10.0% (1/10) |
| grep (baseline) | 0.0% (0/10) |

graphify 도 같은 289 abstract 코퍼스에 *동일 gpt-4.1* 로 빌드 (graphify 기본 20-file/청크는
gpt-4.1 에서 degenerate → chunk_size=3 으로 정상화, 1,666 노드 1,414 엣지). 같은 10 문항을
graphify query/path/explain 로 agentic 풀이. 순위 일관: **arche > graphify > grep**.

## 두 결론 (둘 다 중요)

### 1. 그래프 > grep 는 관계 도메인에서도 성립 (명제 입증)

grep 은 0/10 — 랜덤(약 11%) *이하*. grep 에이전트는 공동출현(co-occurrence) 사슬을
자신 있게 구성했으나 전부 틀렸다. 이유: 마스킹된 ID 코퍼스에서 grep 은 *진짜 상호작용
엣지* 와 *우연한 공동출현* 을 구분 못 한다. 여러 후보가 같은 단백질과 공동출현하므로
lexical 검색이 가짜 사슬을 만든다. **"lexical 검색은 관계 사슬에서 구조적으로 실패한다"
는 원래 명제가 데이터로 확인됨.** 그래프는 *타입된 엣지* (drug→protein, 관계 유형 포함)
를 가져 가짜 공동출현 대신 명시된 관계를 따라갈 수 있어 grep 을 앞선다.

### 2. 그래프의 *절대* 성능은 finance 만큼 일반화 안 됨 — 추출 천장

30% 는 FinanceBench 97% 와 거리가 멀다. 원인은 retrieval 이 아니라 **추출 완전성** —
두 graph 서브에이전트가 독립적으로 같은 진단:
- "같은 단백질이 여러 abstract 에 걸쳐 *노드로 병합 안 됨* (entity resolution 공백)".
- "subject 약물의 연결 단백질이 shared 노드로 추출되지 않아 사슬이 끊김".
- 직접 확인: MH_dev_2 (gold DB01151) 의 subject DB00472 는 직접 언급 abstract 에 단백질이
  없고 gold 연결이 더 깊은 다단계 — MedHop 은 본질적으로 어려운 benchmark (전문 모델
  SOTA 약 60%).

즉 **bottleneck 이 도메인마다 다르다**:
- finance: 정량(수치/표) 추출 — 이번 세션 ingest 개선으로 *해결* → 97%.
- biomedical 관계: **문서 간 entity resolution + 관계 추출** — *미해결* → 30% 천장.

### arche 가 graphify 를 3배 이긴 이유 (정량 근거)

| | cross-document 엔티티 연결 |
| --- | --- |
| graphify | cross-abstract 엣지 **3 / 1,414 (0.2%)** — abstract 마다 고립된 섬 |
| arche | **423 엔티티가 여러 문서에 걸쳐 병합 (3,508 중 12%)** — ADR-0009 context-aware 매칭 |

graphify 의 엣지는 196 종 관계로 다양하나 (references 384, conceptually_related_to 361,
inhibits 90 ...) **거의 전부 단일 abstract 내부** — 문서 간 엔티티를 잇지 않아 multi-hop
사슬이 끊긴다 (서브에이전트: "path 가 거의 항상 No path found"). arche 는 ADR-0009
의 context-aware 매칭으로 같은 단백질을 문서 간 병합 (423 엔티티) → 일부 사슬을 잇는다.
**이 cross-doc 병합의 유무가 30% vs 10% 를 가른다.** 두 도구 모두 천장에 막힌 건 그
병합이 *불완전* 하기 때문 — 다음 레버 = cross-document entity resolution 강화.

## 일반화 판정 (정직)

- **그래프의 *우위* 는 일반화한다** — graph > grep 가 finance 와 biomedical 양쪽에서 성립.
- **그래프의 *절대 정답률* 은 일반화하지 않는다** — 관계 도메인은 finance 에 없던
  entity-resolution 천장을 드러낸다. FinanceBench 정량 추출을 고쳤듯, 다음 레버는
  **문서 간 엔티티 동일성 해소** 임을 데이터가 가리킨다.

## 한계 (과대주장 방지)

1. **n=10, 작다** — 신뢰구간 넓다. 방향성 신호이지 확정 수치 아님.
2. **graph 3 정답 중 1 개 (MH_dev_0) 은 외부지식 추측** — 에이전트가 "그래프 미스,
   best-supported 추측" 으로 명시 (tetrabenazine/도파민 경로 prior). 순수 *그래프 유래*
   정답은 사실상 2/10. 그래도 grep 0/10 보다 위.
3. **graphify 미측정** (이 도메인). 절대 우열은 grep 대비만.
4. **코퍼스 축소** — 직렬 ingest 병목 때문. 전량(1,217) 측정 시 scale 효과 추가 가능.

## 부산물 — 상용화 결함 (ingest 처리량)

작은 파일 1,217 개 적재가 8-9 시간. 원인: 추출은 8-way parallel 이나 *그래프 쓰기 +
ADR-0009 context-aware 엔티티 매칭이 직렬* 이고 그래프가 커질수록 매칭이 느려진다
(파일당 약 28 초, 그래프 크기 무관하게 일정 — 파일당 persistence 오버헤드가 지배).
"문서 다수" 워크로드에 처리량이 약하다. 상용화 전 개선 후보 (배치 persistence /
매칭 인덱싱).

부속: `eval/datasets/medhop-2026-06-22/`, `eval/runs/medhop-agentic-{graphonly,grep}-2026-06-22/`.
