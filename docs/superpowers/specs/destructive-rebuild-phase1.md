# Phase 1 — Destructive rebuild (graphify parity 회복)

> Goal: arche 의 *그래프 생성 자체* 를 graphify 와 동등 이상으로 만들고, ADR-0008 의 증상 가림 가드 (STOPLIST + Consolidator) 의 deprecation 경로를 시작한다.

## Phase 1 의 ADR 묶음

| ADR | 내용 |
|---|---|
| [ADR-0009](../../adr/0009-context-aware-extraction.md) | 추출 단계에 문서 메타 + 기존 graph KNOWN_ENTITIES + schema summary 동봉. `matched_existing_id` 로 매칭을 *예방* 으로 전환. |
| [ADR-0010](../../adr/0010-multi-agent-parallel-and-cache.md) | 추출 호출 batch parallel + 청크 해시 캐시. 30 분 → 8 분 목표. |
| [ADR-0011](../../adr/0011-step3-cosine-opt-in.md) | Step 3 cosine 매칭 default off. STOPLIST + Consolidator 단계별 deprecation. |

## Phase 1 의 PR 분할

5 PR. 순서대로 stack 하되 *PR A 머지 후 나머지 병렬* 가능.

### PR A — ADR 묶음 + spec (본 PR, 머지 시 RFC 종료)

- **산출물**: ADR-0009, 0010, 0011 + 본 spec
- **머지 조건**: 사용자 합의 ("Open Questions" 4 종 채워짐)
- **종료 조건**: ADR Status = accepted
- **위험**: 사용자가 *공유 KB / 사내 인프라* 의 형태 (Phase 3) 를 먼저 결정하면 본 ADR 의 Open Questions 일부 답이 더 명확해질 수 있음

### PR B — Extraction context builder + KNOWN_ENTITIES 동봉 (ADR-0009 D1, D4)

- **변경 파일**:
  - `apps/api/src/arche_api/domain/extract_context.py` (신규) — 청크 + graph → context block 생성
  - `apps/api/src/arche_api/adapters/llm.py` — `extract` 시그니처에 `context: ExtractContext` 인자 추가
  - `apps/api/src/arche_api/domain/ingest.py` — context 생성 후 extract 호출
  - `apps/api/src/arche_api/domain/models.py` — `ExtractedEntity` 에 `matched_existing_id: str | None` 추가
- **테스트**:
  - `tests/unit/test_extract_context.py` — KNOWN_ENTITIES 후보 선정 (hybrid 검색 stub)
  - `tests/unit/test_ingest_service.py` — matched_existing_id 처리 path
- **머지 조건**: 단위 테스트 + integration smoke (10 entity corpus)
- **PR B 의 핵심 결정**: 2nd pass (ADR-0009 D3) 는 PR C 에 분리

### PR C — 2nd pass 주 entity 식별 (ADR-0009 D3)

- **변경 파일**:
  - `apps/api/src/arche_api/domain/main_entity.py` (신규) — 파일 첫 N 줄 → main_entity LLM 호출
  - `apps/api/src/arche_api/domain/ingest.py` — `_main_entity_pass` 호출 + DOC_CONTEXT 주입
- **테스트**:
  - `tests/unit/test_main_entity.py` — 다양한 문서 (10-K, 학술 논문, 일기) fixture 로 추출 정확도
- **머지 조건**: 30 fixture 중 90% 이상 정확한 main_entity 추출

### PR D — Multi-agent parallel + 청크 캐시 (ADR-0010)

- **변경 파일**:
  - `apps/api/src/arche_api/adapters/extract_cache.py` (신규) — sha256 키 + JSON 저장
  - `apps/api/src/arche_api/domain/ingest.py` — batch parallel (asyncio.gather), cache check 우선
  - `apps/api/src/arche_api/config.py` — `INGEST_BATCH_SIZE=8`, `INGEST_CACHE_DIR`
  - `.gitignore` — `.arche-cache/`
- **테스트**:
  - `tests/unit/test_extract_cache.py` — 같은 키 hit, 다른 키 miss, version invalidation
  - `tests/integration/test_ingest_parallel.py` — 1M smoke fixture 로 시간 측정
- **머지 조건**: 100 청크 batch=8 ingest 시간이 batch=1 대비 5x 이상 단축

### PR E — vs graphify 벤치마크 + ADR 종료 조건 (ADR-0009/10/11 종료)

- **변경 파일**:
  - `eval/scripts/bench_vs_graphify.py` (신규) — 동일 corpus 를 graphify CLI + arche 양쪽 ingest → 두 graph 비교
  - `eval/reports/2026-06-22-vs-graphify/CONCLUSION.md` (신규)
- **벤치 항목**:
  | 항목 | arche | graphify | 우월 판정 |
  |---|---|---|---|
  | ingest 시간 (1M corpus) | 측정 | 측정 | 동등 (±20%) |
  | ingest 비용 | 측정 | 측정 | 동등 (±20%) |
  | over-merge entity 수 | 측정 (목표 0) | 측정 (기대 0) | 동등 |
  | cross-doc INFERRED edge | 측정 | 측정 | arche ≥ graphify |
  | multi-hop 질문 정확도 (FinanceBench 33 MCQ) | 측정 | 측정 | arche > graphify |
- **머지 조건**: 위 표의 마지막 두 행에서 arche 가 *우월* 임이 evidence 와 함께 commit
- **ADR Status 갱신**: 0009/0010/0011 모두 accepted → applied

## 일정 추정

| PR | 코드 라인 | 측정 회차 | 추정 |
|---|---|---|---|
| A | 0 (docs only) | 0 | 사용자 합의 대기 |
| B | ~500 | smoke 1 회 | 0.5-1 일 |
| C | ~300 | smoke 1 회 | 0.5 일 |
| D | ~600 | 1M smoke + 1M 본 회차 | 1 일 |
| E | ~400 + 벤치 회차 | graphify 비교 회차 (1 회) | 1-1.5 일 |

총 3-4 일 (사용자 합의 후).

## 후속 Phase 와의 연결

본 spec 종료 후:

- **Phase 2 — Agent API + MCP HTTP**
  - ADR-0013 — Agent API design contract (응답 envelope, 에러 일관성, latency budget)
  - ADR-0014 — MCP HTTP transport (현 stdio 위에 HTTP+SSE 또는 streamable HTTP)
- **Phase 3 — 공유 KB 운영 모델**
  - ADR-0015 — 공유 KB 정의 (단일 KB 사내 공유 vs multi-tenant). 사용자의 *사내 인프라* 정의 합의 필요.
  - ADR-0016 — Auth + multi-tenant + namespace (다회사 개인 KB 시나리오)

Phase 2-3 의 ADR 은 *별도 spec* 으로 작성.

## 본 spec 의 Open Questions (사용자 합의 필요)

ADR Open Questions 의 합본:

1. **ADR-0009 의 2nd pass 형태** — 명시적 vs 첫 청크 동시.
2. **KNOWN_ENTITIES 후보 수 N** — default 10 적정?
3. **`matched_existing_id` 잘못 결정 가드** — confidence threshold?
4. **ADR-0009 점진 도입 vs 한 번에 교체** — 점진 (matched_existing_id 부재 시 기존 매처) 권장.
5. **ADR-0010 batch 크기 default** — 8 vs 16. OpenAI Tier 의존.
6. **ADR-0010 캐시 저장소** — 로컬 vs Redis vs S3. Phase 3 사내 인프라와 연계.
7. **ADR-0011 Step 3 *완전 삭제* 시점의 numerical threshold** — Phase 3 의 어떤 측정 결과가 "삭제 가능" 판정?

Phase 2-3 와 직접 연계되는 *큰 결정* (사용자만 가능):

8. **사내 인프라가 무엇인가** — 사내 LLM provider? 사내 Neo4j? 사내 auth (SSO)? 사내 storage?
9. **공유 KB 의 의미** — 단일 KB 를 여러 사용자가 공유 vs multi-tenant 분리 vs namespace 기반 cross-tenant 부분 공유.
10. **다회사 개인 KB 시나리오** — namespace 가 source-tree 기반 자동인가, 사용자 명시인가, 그 둘 모두 지원인가.

## 검증 사이클

본 spec 의 *측정 회차* 는 모두 *기존 corpus 재사용* 으로 비용 통제:

- FinanceBench 1M (2026-06-20 + 2026-06-21 회차) — *baseline*
- commerce-verbose 95K — *다도메인 회귀 확인*
- (Phase 3) 한국어 95K 또는 사용자 사내 corpus — *공유 KB 시나리오*

각 PR 의 머지 직후 *Spec 의 PR 표* 의 해당 행에 측정 evidence URL 을 inline 채운다.
