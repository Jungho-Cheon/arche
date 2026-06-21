# M6.5b — EntityConsolidator 적용 + 1M 재측정 protocol

본 보고서는 ADR-0008 D2 (EntityConsolidator gating) 의 *적용 protocol* 을 정의한다. *실측정 결과* 는 본 protocol 을 1 회 수행한 뒤 별도 CONCLUSION.md 에 기록된다.

## 종료 조건 (ADR-0008 D2 재인용)

- **(a) post-ingest 절차 구현** — ANN (Neo4j vector index) cosine 0.85-0.92 후보 + LLM 동일성 검증 + generic 자기지칭 source_path 분리 정책.
- **(b) 1M corpus 재 ingest + EntityConsolidator 적용 후 over-merge 가 *수치적으로 감소*** — 예: aliases≥5 entity 수 감소.
- **(c) opentology + combined N=3 재측정** — chunk_rag 는 2026-06-20 회차 (`eval/runs/2026-06-20-1426/responses/chunk_rag/`) 그대로 재사용.

## (a) 구현 산출물

- `apps/api/src/opentology_api/domain/consolidate.py` — `EntityConsolidator` + `ConsolidationLLM` ABC + `ConsolidationReport`.
- `apps/api/src/opentology_api/adapters/consolidation_llm.py` — `LLMBackedConsolidationLLM` (`AnswerLLM` 위 thin wrapper, strict JSON schema).
- `apps/api/src/opentology_api/adapters/graph.py` — `iterate_entities` / `neighbor_names` / `transfer_relations_to_survivor` / `delete_entity` / `count_entities` / `count_entities_with_alias_count_gte` 6 신규 메서드.
- `apps/api/src/opentology_api/domain/identity.py` — `EntityMerger.merge_loser_entity` (consolidator 가 사용하는 두 기존 노드 병합 규칙).
- `apps/api/src/opentology_api/api/admin_consolidate.py` + `routers.py` + `schemas.py` — `POST /admin/consolidate` 비동기 작업 + `GET /admin/consolidate/{task_id}/status`.
- 단위 테스트 9 (도메인) + 5 (라우터) = 14 추가, 회귀 0.

알고리즘 요지:

1. 전체 entity stream — `iterate_entities` (page size 200).
2. 각 entity 에 대해 vector ANN top_k=8 후보.
3. cosine ∈ [0.85, 0.92) 인 쌍만 후보 큐 (>=0.92 는 streaming matcher 가 이미 합쳤음).
4. *generic 자기지칭 separation* — `NON_IDENTIFYING_ALIAS_STOPLIST` 의 name 이 한쪽에라도 있으면서 두 entity 의 `source_paths` 가 disjoint 면 LLM 호출 없이 분리 유지.
5. 나머지 후보는 LLM 검증 — system message 가 "같은 일반어라도 다른 문서의 자기지칭이면 다른 entity" 를 명시. confidence ≥ 0.8 일 때만 merge.
6. merge 는 `survivor (= created_at 빠른 쪽)` 의 `apply_merge_mutation` + loser 의 in/out 관계 `transfer_relations_to_survivor` + `delete_entity` 3 단계.

## (b)(c) 실측 protocol

본 protocol 은 `eval/scripts/m65b_consolidate_and_remeasure.py` 한 스크립트로 수행 가능.

```bash
# 사전: docker compose up -d (neo4j + api) + OPENAI_API_KEY 설정

uv run python eval/scripts/m65b_consolidate_and_remeasure.py \
  --corpus eval/datasets/financebench-2026-06-20/corpus \
  --questions eval/datasets/financebench-2026-06-20/questions.yaml \
  --output eval/runs/$(date +%Y-%m-%d-%H%M)/responses \
  --api-url http://localhost:8000 \
  --runs 3 \
  --from-step 0
```

### Step 단계 분해

| Step | 동작 | 산출물 |
|---|---|---|
| 0 | `MATCH (n) DETACH DELETE n` (cypher-shell via docker exec) | (Neo4j 비움) |
| 1 | `POST /admin/ingest` (admin/ingest) 후 polling | `progress.entities_created`, `metrics.relations_created` |
| 2 | `POST /admin/consolidate` 후 polling | `consolidate_report.json` (merged / rejected / similarity / confidence) |
| 3 | `MATCH (e:Entity) RETURN size(coalesce(e.aliases,[])) AS aliases_count, count(*) ORDER BY aliases_count DESC LIMIT 20` | `alias_count_distribution.txt` (=evidence) |
| 4 | `eval/scripts/run_triple_poc.py --runs 3` | `opentology/<question_id>_run0..2.json` |

### 측정 후 채울 표 (CONCLUSION.md 의 형식)

| 컬럼 | floor (N=3 min) | ceiling (N=3 max) | variance range | 비고 |
|---|---|---|---|---|
| chunk_rag (재사용) | 72.7% | 72.7% | 0pp | 2026-06-20 회차 결과 |
| opentology (post-consolidate) | TBD | TBD | TBD | M6.5b 측정 |
| combined (post-consolidate) | TBD | TBD | TBD | M6.5b 측정 |

`aliases_count >= 5` 가 본 회차에서 *감소* 했음을 확인한 cypher 결과 한 줄 첨부.

### 분기 결정 (ADR-0007 D2 의 진짜 분기)

- **combined ≥ chunk + 3pp** → ADR-0007 D1 (combined 우월) 유지, M7 productization.
- **combined ≈ chunk (±2pp)** → ADR-0007 D6 (provenance) 만 살리고 M7 단순화 (chunk-only 디폴트). graph 는 opt-in.
- **chunk > combined** → graph 를 비공식 옵션으로, chunk-only 로 피벗.

## 비용 / 시간 예상

| 단계 | 예상 시간 | 예상 비용 (OpenAI) |
|---|---|---|
| Step 1 재 ingest | 20-30 분 (33 파일 1M 토큰) | $5-10 (entity extraction + embedding) |
| Step 2 consolidate | 1-3 분 (후보 100-300 쌍 가정) | $0.1-0.5 |
| Step 4 N=3 측정 (opentology + combined) | 30-50 분 | $5-15 |
| **합계** | **~1.5 시간** | **~$15-25** |

## 본 commit 시점 상태

- (a) 구현 — *완료* . 단위 테스트 14 추가 (202 passed).
- (b) 1M 적용 — *미실행* . Docker daemon + OPENAI_API_KEY 가 필요한 사용자 trigger 단계.
- (c) N=3 재측정 — *미실행* . (b) 종료 후 자동 진행.

실행 후 CONCLUSION.md 생성 + ADR-0008 본문 표 (정확도 / 토큰 / 지연 / 비용) 갱신 + ADR-0007 D2 의 *진짜 분기* 결정 commit.
