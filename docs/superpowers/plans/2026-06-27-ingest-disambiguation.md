# Ingest Disambiguation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** On top of reviewable ingest, surface missed-merge ambiguities as questions the agent asks the human, and let the human's answers refine the plan via a new `ingest_resolve` tool — before commit.

**Architecture:** Detect Step-3 near-misses (cosine in `[0.82, 0.92)`) during planning and carry them as `IngestPlan.open_questions`. Resolution re-runs `plan_file` with forced-match hints (reusing the ADR-0009 `matched_existing_id` path); extraction is served from the content-keyed disk cache, so no LLM re-call. Unresolved questions default to create-new (conservative, non-blocking).

**Tech Stack:** Python 3.12+, pydantic v2, MCP SDK, Neo4j adapter, pytest.

---

## 사람용 요약 (Korean TL;DR)

매처 Step 3에서 임계(0.92) 바로 아래 [0.82,0.92) 후보가 있는데 새 점으로 떨어진 경우를 "놓친 병합 후보 질문"으로 계획에 싣는다. `ingest_resolve`가 사람 답(merge/keep)을 받아 강제 매칭 힌트로 plan_file을 재실행(추출은 캐시 적중, LLM 재호출 없음). 미해소 질문은 새 점 생성(보수적 기본값)이라 자율 에이전트도 안 막힌다. 태스크 5개. 코드 주석은 저장소 관행대로 한국어, 문서 산문은 영어.

---

## Global Constraints

- Python 3.12+ / pydantic v2 (response models `extra="forbid"`).
- Hexagonal: `domain/` must not import `adapters/`.
- Emitted source keeps WHY-centric Korean comments at surrounding density.
- No middle-dot ("·") in doc artifacts.
- **Normal (non-plan) ingest behavior must not change** — `ambiguities` is populated but never alters which nodes are created/merged. Guard with a regression test.
- Tests green under `cd apps/api && uv run --extra dev pytest -m "not live" -q` (pytest is in the dev extra; baseline 310 passed, 21 docker integration errors are environmental).
- The 6 MCP read tools + existing 3 ingest tools stay unchanged except the additive `questions` field and the new `ingest_resolve` tool.

---

### Task 1: Near-miss detection in the matcher

**Files:**
- Modify: `apps/api/src/arche_api/domain/identity.py` (add band constant; `MatchResult.near_miss`; Step 3 records best sub-threshold candidate)
- Test: `apps/api/tests/unit/test_identity.py` (or the existing matcher test file — find it first)

**Interfaces — Produces:**
- `EMBEDDING_AMBIGUITY_BAND_LOW = 0.82` (module constant near `EMBEDDING_MATCH_THRESHOLD`)
- `MatchResult` gains `near_miss: tuple[StoredEntity, float] | None = None`

**Behavior:** In `EntityMatcher.match` Step 3, after computing cosine for each candidate: if no candidate reaches `EMBEDDING_MATCH_THRESHOLD`, find the single best candidate whose cosine is in `[EMBEDDING_AMBIGUITY_BAND_LOW, EMBEDDING_MATCH_THRESHOLD)` and return `MatchResult(existing=None, step=4, near_miss=(best_cand, best_sim))`. If none in band, return `MatchResult(existing=None, step=4)` (near_miss None). A real merge (≥ threshold) returns near_miss None.

- [ ] **Step 1: Write the failing test**

First locate the existing matcher unit test (e.g. `apps/api/tests/unit/test_identity.py`); add tests there reusing its fake repo/embedder pattern. The test must control `vector_search` to return a candidate at a chosen cosine.

```python
# near-miss in band -> create-new WITH near_miss
def test_step3_near_miss_in_band_reports_candidate():
    # build a matcher whose embedder + vector_search yield a single candidate
    # with cosine ~0.87 (in [0.82, 0.92)). Construct candidate embedding so
    # _cosine(query, cand.embedding) lands in band (e.g. identical vectors
    # scaled, or reuse the existing test's helper for controlled similarity).
    result = matcher.match(ExtractedEntity(name="Acme Inc", type="Org"))
    assert result.existing is None and result.step == 4
    assert result.near_miss is not None
    cand, sim = result.near_miss
    assert 0.82 <= sim < 0.92

# above threshold -> merge, no near_miss
def test_step3_above_threshold_merges_no_near_miss():
    result = matcher.match(...)  # candidate cosine >= 0.92
    assert result.existing is not None and result.step == 3
    assert result.near_miss is None

# below band -> create-new, no near_miss
def test_step3_below_band_no_near_miss():
    result = matcher.match(...)  # candidate cosine < 0.82
    assert result.existing is None and result.step == 4
    assert result.near_miss is None
```

> Read how the existing matcher test fabricates controlled cosine similarity and reuse it exactly (do not invent a new fake). If the test file builds embeddings to hit 0.92, mirror that to hit ~0.87 and ~0.75.

- [ ] **Step 2: Run to verify fail**

Run: `cd apps/api && uv run --extra dev pytest tests/unit/test_identity.py -k near_miss -v` → FAIL (near_miss attr missing).

- [ ] **Step 3: Implement**

In identity.py: add `EMBEDDING_AMBIGUITY_BAND_LOW = 0.82` next to `EMBEDDING_MATCH_THRESHOLD`. Add `near_miss: tuple[StoredEntity, float] | None = None` to `MatchResult`. In `match`, Step 3, track the best sub-threshold candidate:

```python
        embedding = self._embedder.embed([e_new.name])
        if not embedding or not embedding[0]:
            return MatchResult(existing=None, step=4)
        query_vec = embedding[0]
        candidates = self._repo.vector_search(
            embedding=query_vec, top_k=5, type_=e_new.type
        )
        best_near: tuple[StoredEntity, float] | None = None
        for cand in candidates:
            sim = _cosine(query_vec, cand.embedding)
            if sim >= EMBEDDING_MATCH_THRESHOLD:
                return MatchResult(existing=cand, step=3)
            # 임계 바로 아래 밴드 [LOW, THRESHOLD) 의 최상위 후보를 놓친 병합
            # 후보로 보고한다 (사람 확인 대상). 밴드 밖은 무시.
            if sim >= EMBEDDING_AMBIGUITY_BAND_LOW and (
                best_near is None or sim > best_near[1]
            ):
                best_near = (cand, sim)

        # Step 4 — miss. 밴드 내 근접 후보가 있으면 near_miss 로 surface.
        return MatchResult(existing=None, step=4, near_miss=best_near)
```

- [ ] **Step 4: Run to verify pass** — `... -k near_miss -v` PASS; then `pytest tests/unit/test_identity.py -q` all green.

- [ ] **Step 5: Commit**
```bash
git add apps/api/src/arche_api/domain/identity.py apps/api/tests/unit/test_identity.py
git commit -m "feat(identity): Step3 near-miss 후보 보고 (놓친 병합 감지)"
```

---

### Task 2: AmbiguousMatch + carry through IngestResult and plan

**Files:**
- Modify: `apps/api/src/arche_api/domain/ingest_plan.py` (add `AmbiguousMatch`; `IngestPlan.open_questions`)
- Modify: `apps/api/src/arche_api/domain/ingest.py` (`IngestResult.ambiguities`; `_upsert_entities` records near-misses; `plan_file` populates `open_questions`)
- Modify: `apps/api/src/arche_api/domain/identity.py` constant `MAX_OPEN_QUESTIONS = 12` (or put in ingest.py)
- Test: `apps/api/tests/unit/test_ingest_plan_commit.py`

**Interfaces — Produces:**
- `AmbiguousMatch(question_id, extracted_name, extracted_type, candidate_id, candidate_name, similarity, kind="possible_missed_merge")` frozen dataclass in `ingest_plan.py`.
- `IngestResult.ambiguities: list[AmbiguousMatch] = field(default_factory=list)` (question_id left "" at this layer; assigned in plan_file).
- `IngestPlan.open_questions: list[AmbiguousMatch] = field(default_factory=list)`.

**Behavior:**
- `_upsert_entities`: when an entity goes to create-new (Step 4) AND `result.near_miss` is set, append an `AmbiguousMatch` (question_id="") to a per-call list; return it alongside the existing return so `ingest_file` can aggregate into `IngestResult.ambiguities`. (The ADR-0009 `matched_existing_id` fast-path and Steps 1-3 never produce near-misses.)
- `plan_file`: take `result.ambiguities`, sort by `similarity` desc, cap to `MAX_OPEN_QUESTIONS`, assign stable `question_id = f"q{i+1}"`, store on `IngestPlan.open_questions`.
- Normal ingest: `ambiguities` is populated but unused — assert no write-behavior change.

- [ ] **Step 1: Failing test**

```python
def test_plan_surfaces_missed_merge_question(...):
    # graph has an existing Org "Acme Corporation"; doc mentions "Acme Inc"
    # whose embedding near-misses (in band) -> create-new + 1 open_question.
    plan = service.plan_file(doc)
    assert len(plan.open_questions) == 1
    q = plan.open_questions[0]
    assert q.question_id == "q1"
    assert q.candidate_name == "Acme Corporation"
    assert 0.82 <= q.similarity < 0.92

def test_normal_ingest_behavior_unchanged_with_ambiguity(...):
    # same near-miss doc via ingest_file (not plan): still creates the new node
    # (no merge), entities_created unchanged vs a pre-feature baseline count.
    r = service.ingest_file(doc)
    assert r.entities_created == EXPECTED_CREATED  # near-miss did NOT auto-merge
```

> Reuse the `FakeGraph`/`FakeEmbedder`/fake-LLM assembly from `test_ingest_service` (the one that stores entities + supports vector_search). You will need the fake `vector_search` to return a candidate whose `_cosine` to the query lands in band. Follow how Task 1's matcher test controls similarity.

- [ ] **Step 2: Run to fail** — `cd apps/api && uv run --extra dev pytest tests/unit/test_ingest_plan_commit.py -k question -v` → FAIL.

- [ ] **Step 3: Implement**

`ingest_plan.py`:
```python
@dataclass(frozen=True)
class AmbiguousMatch:
    """계획 단계에서 발견한 '놓친 병합 후보' 질문 한 건.

    추출된 엔티티(extracted_*)가 기존 노드(candidate_*)와 임계 바로 아래
    유사도(similarity)라 새 점으로 떨어졌다 — 같은 대상인지 사람에게 묻는다.
    question_id 는 plan_file 이 부여한다(레이어 하단에선 "").
    """
    question_id: str
    extracted_name: str
    extracted_type: str
    candidate_id: str
    candidate_name: str
    similarity: float
    kind: str = "possible_missed_merge"
```
Add `open_questions: list[AmbiguousMatch] = field(default_factory=list)` to `IngestPlan`.

`ingest.py`: add `ambiguities: list[AmbiguousMatch] = field(default_factory=list)` to `IngestResult` (after the existing fields). In `_upsert_entities`, collect near-miss matches into a local list and return it (extend the return tuple or attach to the metrics dict — match the existing signature shape; read the current `_upsert_entities` return and thread it minimally). Aggregate across chunks into `IngestResult.ambiguities` at the `ingest_file` success return. In `plan_file`, after getting `result`:
```python
        ambiguities = sorted(
            result.ambiguities, key=lambda a: a.similarity, reverse=True
        )[:MAX_OPEN_QUESTIONS]
        open_questions = [
            replace(a, question_id=f"q{i + 1}")
            for i, a in enumerate(ambiguities)
        ]
        # ... include open_questions=open_questions in the IngestPlan(...) construction
```
Define `MAX_OPEN_QUESTIONS = 12` near the top of ingest.py.

- [ ] **Step 4: Run to pass** — `-k question` PASS; then full not-live suite green (`cd apps/api && uv run --extra dev pytest -m "not live" -q`).

- [ ] **Step 5: Commit**
```bash
git add apps/api/src/arche_api/domain/ingest_plan.py apps/api/src/arche_api/domain/ingest.py apps/api/tests/unit/test_ingest_plan_commit.py
git commit -m "feat(ingest): 놓친 병합 후보를 IngestPlan.open_questions 로 surface"
```

---

### Task 3: Resolution engine (re-plan with forced-match hints)

**Files:**
- Modify: `apps/api/src/arche_api/domain/ingest.py` (`self._active_resolutions`; `_upsert_entities` applies it; `IngestService.resolve_plan`)
- Test: `apps/api/tests/unit/test_ingest_plan_commit.py`

**Interfaces — Produces:**
- `IngestService.resolve_plan(plan: IngestPlan, resolutions: dict[str, str]) -> IngestPlan` where `resolutions` maps `question_id -> "merge" | "keep"`. Returns a refined `IngestPlan` with the SAME `plan_id`, `previewed=False`, recomputed `writes`/`result`/`open_questions`.

**Behavior:**
- `resolve_plan` translates `{question_id: decision}` against `plan.open_questions` into a signature map `{"<normalized_name>\x00<type>": "merge:<candidate_id>" | "keep"}`. It MERGES with any resolutions already applied to this plan (store the accumulated signature map on the plan, e.g. a new private field `IngestPlan.resolved: dict[str,str] = {}`, or recompute from a registry-held map — keep it on the plan).
- Set `self._active_resolutions = signature_map`, call `plan_file(Path(plan.source_path))`, restore `self._active_resolutions = {}` in `finally`. Extraction is cache-served (assert no LLM re-call via a counting fake).
- In `_upsert_entities`, before matching each `e_new`: compute `sig = normalize(e_new.name) + "\x00" + e_new.type`. If `self._active_resolutions.get(sig)` startswith `"merge:"`, set `e_new = replace(e_new, matched_existing_id=<id>)` (reuse the existing ADR-0009 fast-path). If `== "keep"`, set a local flag to force create-new AND suppress near-miss recording for this entity.
- The refined plan keeps `plan_id` (override the freshly generated one) and carries the accumulated `resolved` map so a second `resolve_plan` adds to it.

- [ ] **Step 1: Failing test**

```python
def test_resolve_merge_turns_create_into_merge_without_llm(counting_llm, ...):
    plan = service.plan_file(doc)              # 1 open_question q1 (create-new)
    calls_after_plan = counting_llm.extract_calls
    resolved = service.resolve_plan(plan, {"q1": "merge"})
    # extraction served from cache -> no new LLM extract calls
    assert counting_llm.extract_calls == calls_after_plan
    # the entity is now merged into the candidate: a merge write exists, the
    # create_entity for that name is gone, previewed reset, question cleared
    assert resolved.plan_id == plan.plan_id
    assert resolved.previewed is False
    assert resolved.open_questions == []
    assert any(w.method == "apply_merge_mutation" for w in resolved.writes)

def test_resolve_keep_leaves_new_and_clears_question(...):
    plan = service.plan_file(doc)
    resolved = service.resolve_plan(plan, {"q1": "keep"})
    assert resolved.open_questions == []
    assert any(w.method == "create_entity" for w in resolved.writes)
```

> Build a `counting_llm` wrapping the fake LLM that increments on each `extract`. Confirm `plan_file` populated the cache (the IngestService must be constructed with an `ExtractionCache` pointing at a tmp dir) so re-plan hits it.

- [ ] **Step 2: Run to fail** — `-k resolve` FAIL (resolve_plan missing).

- [ ] **Step 3: Implement** — add `_active_resolutions: dict[str,str]` init `{}` in `__init__`; apply in `_upsert_entities` (read current code, inject before the match call, mirror the existing `matched_existing_id` branch for "merge", add a keep-flag path); add `resolve_plan`. Keep the accumulated map on `IngestPlan.resolved` (add field `resolved: dict[str, str] = field(default_factory=dict)`).

- [ ] **Step 4: Run to pass** — `-k resolve` PASS; full not-live suite green.

- [ ] **Step 5: Commit**
```bash
git add apps/api/src/arche_api/domain/ingest.py apps/api/src/arche_api/domain/ingest_plan.py apps/api/tests/unit/test_ingest_plan_commit.py
git commit -m "feat(ingest): resolve_plan — 강제 매칭 힌트로 재계획(캐시 적중)"
```

---

### Task 4: Service functions + schemas (ingest_resolve + questions in preview)

**Files:**
- Modify: `apps/api/src/arche_api/api/plan_schemas.py` (add `QuestionView`; `PlanPreview.questions`; `PlanSummary.open_questions`; `ResolveRequest`; `ResolutionItem`)
- Modify: `apps/api/src/arche_api/api/services.py` (`preview_plan` emits questions; `plan_ingest` summary `open_questions`; new `resolve_plan` service fn)
- Test: `apps/api/tests/unit/test_plan_services.py`

**Interfaces — Produces (pydantic, `extra="forbid"`):**
- `QuestionView{ question_id, extracted_name, extracted_type, candidate_id, candidate_name, similarity, kind }`
- `PlanPreview` gains `questions: list[QuestionView] = []`
- `PlanSummary` gains `open_questions: int = 0`
- `ResolutionItem{ question_id: str, decision: Literal["merge","keep"] }`
- `ResolveRequest{ plan_id: str, resolutions: list[ResolutionItem] }`
- Service: `resolve_ingest(body: ResolveRequest, *, service, registry) -> PlanSummary` — looks up plan (missing -> InvalidInputError), calls `service.resolve_plan(plan, {r.question_id: r.decision})`, stores the refined plan under the same plan_id, returns its summary (with `open_questions` count).

**Behavior:** `preview_plan` maps `plan.open_questions -> questions`. `plan_ingest` summary sets `open_questions=len(plan.open_questions)`. Validate unknown question_ids in `resolve_ingest` -> `InvalidInputError`.

- [ ] **Step 1: Failing tests** (cover: preview exposes a question; resolve merges & returns updated summary with fewer questions; unknown question_id -> InvalidInputError). Reuse the conftest `make_plan`/`fake_service`; extend `make_plan` to accept `open_questions=` and `fake_service.resolve_plan` to return a plan with the question cleared.

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement** the schemas + three service edits, following the existing service-function shape from the reviewable-ingest tasks (read `services.py` plan_ingest/preview_plan/commit_plan first and match style).

- [ ] **Step 4: Run to pass** — `pytest tests/unit/test_plan_services.py -v`; full not-live suite green.

- [ ] **Step 5: Commit**
```bash
git add apps/api/src/arche_api/api/plan_schemas.py apps/api/src/arche_api/api/services.py apps/api/tests/unit/test_plan_services.py apps/api/tests/unit/conftest.py
git commit -m "feat(api): ingest_resolve 서비스 + preview questions"
```

---

### Task 5: MCP tool ingest_resolve + skill + README

**Files:**
- Modify: `apps/api/src/arche_api/mcp_server.py` (register `ingest_resolve`; dispatch; descriptions; instructions; `INGEST_TOOL_NAMES` += "ingest_resolve")
- Modify: `skills/reviewable-ingest/SKILL.md` (handle questions), `README.md` (note)
- Test: `apps/api/tests/unit/test_mcp_write_tools.py`

**Interfaces:** `ingest_resolve` input schema from `ResolveRequest`; registered only when ingest_service+plan_registry present; dispatched to `services.resolve_ingest`. Add to `INGEST_TOOL_NAMES`. Preview tool description: "if `questions` is non-empty, ask the human about each and call `ingest_resolve` before commit." Extend server `instructions` ritual to include resolve.

- [ ] **Step 1: Failing test** — extend `test_server_with_service_exposes_three_write_tools` (or add one) to assert `ingest_resolve` is registered when service present, and NOT present on the read-only server; still no overlap with `WRITE_TOOL_NAMES_EXCLUDED`.

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement** — mirror the existing ingest-tool registration/dispatch exactly (read mcp_server.py's `_build_ingest_tools` / `_dispatch_tool` ingest branches and add a parallel `ingest_resolve` path). Update SKILL.md: after preview, "if questions: ask the human each ('X looks close to Y at NN% — same entity, or new?'), then call ingest_resolve with their answers and preview again before commit." Add one README line. Verify no "·" via `grep -n "·" skills/reviewable-ingest/SKILL.md README.md`.

- [ ] **Step 4: Run to pass** — `pytest tests/unit -k "mcp" -v`; full not-live suite green; grep clean.

- [ ] **Step 5: Commit**
```bash
git add apps/api/src/arche_api/mcp_server.py skills/reviewable-ingest/SKILL.md README.md apps/api/tests/unit/test_mcp_write_tools.py
git commit -m "feat(mcp): ingest_resolve 도구 + 스킬/README (질문 해소 루프)"
```

---

## Self-Review (author check)

- Spec coverage: §3.1 detection -> Tasks 1-2; §3.2 resolution -> Task 3; §4 surface -> Tasks 4-5; §5 skill -> Task 5. All mapped.
- Placeholder scan: test bodies reference "reuse existing fake/conftest" deliberately (the worker fills from existing patterns); constants/signatures are concrete.
- Type consistency: `AmbiguousMatch` fields, `MatchResult.near_miss`, `IngestResult.ambiguities`, `IngestPlan.open_questions/resolved`, `resolve_plan(plan, dict[str,str])` consistent across tasks.
- Risk: Task 3's `_upsert_entities` injection must not change normal-ingest behavior when `_active_resolutions` is empty — covered by the Task 2 normal-ingest regression test plus a clean full-suite run each task.
