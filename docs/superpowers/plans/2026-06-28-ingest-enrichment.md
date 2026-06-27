# Ingest Context Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let the agent supply source-preserving extraction hints (a glossary / domain notes) that are prepended to the LLM extraction prompt as an `[ENRICHMENT]` block, improving extraction of poorly-structured documents without ever modifying the stored source.

**Architecture:** Add `ExtractContext.enrichment`; render it as `[ENRICHMENT]`; thread plan-time hints through `IngestService` via a transient `self._active_hints` (same pattern as `_active_resolutions`); store hints on `IngestPlan` so resolve preserves them; accept `hints` on `ingest_plan`. The extraction cache key already includes the rendered context, so different hints re-extract and identical hints hit the cache. Provenance (`source_refs`) is built from the original chunk and never from hints.

**Tech Stack:** Python 3.12+, pydantic v2, MCP SDK, pytest.

---

## 사람용 요약 (Korean TL;DR)

원문 불변. 에이전트가 준 메모를 추출 프롬프트 `[ENRICHMENT]` 블록으로만 주입. `_active_hints` 전이 속성(아이디어 2의 `_active_resolutions`와 동일 패턴) + `IngestPlan.hints` + `ingest_plan(hints=)`. 캐시 키가 컨텍스트를 포함하므로 힌트 변경 시 재추출. 태스크 4개, TDD. 코드 주석은 한국어, 문서 산문은 영어.

---

## Global Constraints

- Python 3.12+ / pydantic v2 (response models `extra="forbid"`).
- Hexagonal: `domain/` must not import `adapters/`.
- Emitted source keeps WHY-centric Korean comments at surrounding density.
- No middle-dot ("·") in doc artifacts.
- **Provenance invariant:** hints enter only the LLM prompt; `source_refs` are unchanged. Guard with a test.
- **Normal (non-plan, no-hints) ingest behavior unchanged** — `self._active_hints` defaults None, render omits `[ENRICHMENT]` when empty, so the cache key and writes match pre-feature. Guard with a test.
- Tests green: `cd apps/api && uv run --extra dev pytest -m "not live" -q` (pytest in the dev extra; baseline 323 passed, 21 docker integration errors environmental).

---

### Task 1: ExtractContext.enrichment + render block

**Files:**
- Modify: `apps/api/src/arche_api/domain/extract_context.py` (`ExtractContext.enrichment`; `[ENRICHMENT]` in `render_context_block`; `ExtractContextBuilder.build(enrichment=)`)
- Test: `apps/api/tests/unit/test_extract_context.py` (find the existing test file for this module; create if absent)

**Interfaces — Produces:**
- `ExtractContext.enrichment: str | None = None` (frozen, default None)
- `render_context_block(ctx)` emits an `[ENRICHMENT]` block (after the `[DOC_CONTEXT]` block) ONLY when `ctx.enrichment` is a non-empty string; omitted otherwise.
- `ExtractContextBuilder.build(..., enrichment: str | None = None)` sets it on the returned context.

- [ ] **Step 1: Write failing tests**

```python
# render includes the block verbatim when enrichment present
def test_render_includes_enrichment_block_when_present():
    ctx = ExtractContext(
        doc=DocContext(file_path="/a.md"),
        known_entities=[],
        schema=SchemaSummary(entity_types=[], relation_types=[]),
        enrichment="AmEx = American Express. Treat each table row as a fact.",
    )
    out = render_context_block(ctx)
    assert "[ENRICHMENT]" in out
    assert "AmEx = American Express" in out

# omitted entirely when None/empty (no behavior change / cache key stable)
def test_render_omits_enrichment_when_absent():
    ctx = ExtractContext(
        doc=DocContext(file_path="/a.md"),
        known_entities=[],
        schema=SchemaSummary(entity_types=[], relation_types=[]),
    )
    assert "[ENRICHMENT]" not in render_context_block(ctx)

# builder threads enrichment onto the context
def test_builder_sets_enrichment():
    # build the ExtractContextBuilder with a fake graph (read how existing
    # tests construct it); call build(source_path=..., chunk_text=..., enrichment="X")
    ctx = builder.build(source_path="/a.md", chunk_text="body", enrichment="X")
    assert ctx.enrichment == "X"
```

> Read the existing test for extract_context (search `tests/unit` for it) and reuse its fakes for `ExtractContextBuilder`. If none exists, build a minimal fake graph implementing `find_by_keywords_scored` returning [].

- [ ] **Step 2: Run to fail** — `cd apps/api && uv run --extra dev pytest tests/unit/test_extract_context.py -k enrichment -v` → FAIL.

- [ ] **Step 3: Implement**

Add field to the frozen dataclass:
```python
@dataclass(frozen=True)
class ExtractContext:
    """ADR-0009 D1 의 4 종 컨텍스트 묶음 + (선택) 에이전트 보강 메모."""

    doc: DocContext
    known_entities: list[KnownEntity]
    schema: SchemaSummary
    # WHY enrichment: 원문을 고치지 않고 추출 recall 을 올리기 위한 *에이전트
    # 제공 메모* (용어 풀이/약어/도메인 힌트). LLM 프롬프트 prefix 에만 들어가고
    # 저장 노드의 source_refs 에는 영향이 없다 (provenance 보존). None/빈 문자열
    # 이면 렌더에서 통째로 생략 — 비보강 적재의 캐시 키/동작 불변.
    enrichment: str | None = None
```
In `render_context_block`, after the `[DOC_CONTEXT]` block (and its trailing `lines.append("")`), insert:
```python
    if ctx.enrichment and ctx.enrichment.strip():
        lines.append("[ENRICHMENT]")
        lines.append(ctx.enrichment.strip())
        lines.append("")
```
In `ExtractContextBuilder.build`, add `enrichment: str | None = None` param and pass it into the constructed `ExtractContext(...)`.

- [ ] **Step 4: Run to pass** — `-k enrichment` PASS; then `pytest tests/unit/test_extract_context.py -q` all green.

- [ ] **Step 5: Commit**
```bash
git add apps/api/src/arche_api/domain/extract_context.py apps/api/tests/unit/test_extract_context.py
git commit -m "feat(extract): ExtractContext.enrichment + [ENRICHMENT] 렌더 블록"
```

---

### Task 2: Thread hints through IngestService + plan

**Files:**
- Modify: `apps/api/src/arche_api/domain/ingest.py` (`self._active_hints`; `_build_chunk_context` passes enrichment; `plan_file(path, *, hints=None)`; `resolve_plan` carries `plan.hints`)
- Modify: `apps/api/src/arche_api/domain/ingest_plan.py` (`IngestPlan.hints: str | None = None`)
- Test: `apps/api/tests/unit/test_ingest_plan_commit.py`

**Interfaces:**
- `IngestService.plan_file(path, *, namespace_id="default", hints: str | None = None) -> IngestPlan`
- `IngestPlan.hints: str | None = None`

**Behavior:**
- `__init__`: `self._active_hints: str | None = None`.
- `_build_chunk_context`: pass `enrichment=self._active_hints` to `self._extract_context_builder.build(...)` (only that builder call changes; keep the None-builder branch as-is).
- `plan_file`: set `self._active_hints = hints` before the existing `self._graph` swap / `ingest_file` call, restore to None in the SAME `finally` that restores `_graph`. Put `hints=hints` into the `IngestPlan(...)` construction.
- `resolve_plan`: before its `plan_file` re-run, also set `self._active_hints = plan.hints` (restore in finally). Pass `hints=plan.hints` so the refined plan keeps them. (resolve_plan calls plan_file internally — pass hints through that call: `self.plan_file(Path(plan.source_path), hints=plan.hints)` if plan_file is what it calls; otherwise set `_active_hints` around the call. Read the current resolve_plan to wire it the same way it wires `_active_resolutions`.)
- Normal ingest: `_active_hints` stays None → no `[ENRICHMENT]` → unchanged.

- [ ] **Step 1: Failing tests**

```python
def test_plan_with_hints_reaches_extraction_context(capturing_llm, ...):
    # capturing_llm records the `context` passed to extract(); build the service
    # with an ExtractContextBuilder so context is non-None.
    service.plan_file(doc, hints="GLOSSARY: Acme = Acme Corporation")
    ctx = capturing_llm.last_context
    assert ctx is not None and ctx.enrichment == "GLOSSARY: Acme = Acme Corporation"
    assert service._active_hints is None  # restored after

def test_plan_without_hints_no_enrichment(capturing_llm, ...):
    service.plan_file(doc)
    assert capturing_llm.last_context is None or capturing_llm.last_context.enrichment is None

def test_provenance_unchanged_with_hints(...):
    # plan the same file with and without hints; for a node present in both,
    # its source_refs are identical (hints do not alter provenance).
    p_no = service.plan_file(doc)
    p_hint = service.plan_file(doc, hints="some notes")
    # compare create_entity writes' StoredEntity.source_refs by name
    ...
```

> The `capturing_llm` is a fake LLMProvider whose `extract` stores the last `context` kwarg and returns a deterministic ExtractedGraph. Reuse/extend the fake-LLM from `test_ingest_service`.

- [ ] **Step 2: Run to fail** — `-k hints` FAIL (plan_file has no hints kwarg).

- [ ] **Step 3: Implement** per the interfaces above. Read the current `plan_file` and `resolve_plan` to mirror the `_active_resolutions` set/restore exactly. Add `hints` to `IngestPlan`.

- [ ] **Step 4: Run to pass** — `-k hints` PASS; full not-live suite green.

- [ ] **Step 5: Commit**
```bash
git add apps/api/src/arche_api/domain/ingest.py apps/api/src/arche_api/domain/ingest_plan.py apps/api/tests/unit/test_ingest_plan_commit.py
git commit -m "feat(ingest): plan_file hints -> ExtractContext.enrichment (원문 불변)"
```

---

### Task 3: Service + schema (ingest_plan hints)

**Files:**
- Modify: `apps/api/src/arche_api/api/plan_schemas.py` (`PlanIngestRequest.hints: str | None = None`)
- Modify: `apps/api/src/arche_api/api/services.py` (`plan_ingest` passes `hints` to `plan_file`)
- Test: `apps/api/tests/unit/test_plan_services.py`

**Interfaces:**
- `PlanIngestRequest` gains `hints: str | None = Field(default=None, max_length=4000)` (cap to keep prompt budget sane; `extra="forbid"` retained).
- `plan_ingest(body, *, service, registry)` calls `service.plan_file(Path(body.path), hints=body.hints)`.

- [ ] **Step 1: Failing test**

```python
def test_plan_ingest_forwards_hints_to_service(fake_service_recording, ...):
    body = PlanIngestRequest(path="/a.md", hints="notes")
    services.plan_ingest(body, service=fake_service_recording, registry=PlanRegistry())
    assert fake_service_recording.last_plan_file_hints == "notes"

def test_plan_ingest_without_hints_passes_none(fake_service_recording, ...):
    services.plan_ingest(PlanIngestRequest(path="/a.md"), service=fake_service_recording, registry=PlanRegistry())
    assert fake_service_recording.last_plan_file_hints is None
```

> Extend the conftest `fake_service` (or add a recording variant) whose `plan_file(path, *, namespace_id=..., hints=None)` records `hints` and returns a minimal IngestPlan.

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement** — add the field (read plan_schemas.py to match style + `extra="forbid"`); pass `hints=body.hints` in `plan_ingest` (read current `plan_ingest`).

- [ ] **Step 4: Run to pass** — `pytest tests/unit/test_plan_services.py -v`; full not-live green.

- [ ] **Step 5: Commit**
```bash
git add apps/api/src/arche_api/api/plan_schemas.py apps/api/src/arche_api/api/services.py apps/api/tests/unit/test_plan_services.py apps/api/tests/unit/conftest.py
git commit -m "feat(api): ingest_plan hints 입력 전달"
```

---

### Task 4: MCP ingest_plan hints + skill + README

**Files:**
- Modify: `apps/api/src/arche_api/mcp_server.py` (`ingest_plan` input schema already derives from `PlanIngestRequest` via `_build_input_schema`, so `hints` appears automatically — verify; update the `ingest_plan` description to mention hints)
- Modify: `skills/reviewable-ingest/SKILL.md`, `README.md`
- Test: `apps/api/tests/unit/test_mcp_write_tools.py`

**Interfaces:** `ingest_plan` tool input schema includes optional `hints`. No new tool. Description updated.

**Note:** `ingest_plan` is registered via `_build_input_schema(PlanIngestRequest)`, so adding `hints` to that pydantic model (Task 3) auto-exposes it in the MCP input schema. This task verifies that and updates copy.

- [ ] **Step 1: Failing test**

```python
def test_ingest_plan_input_schema_exposes_hints():
    from arche_api.api.plan_registry import PlanRegistry
    server = build_mcp_server(FakeGraph(), FakeEmbedder(), FakeSettings(),
                              ingest_service=<fake>, plan_registry=PlanRegistry())
    # fetch the ingest_plan tool's inputSchema (reuse _tool_names pattern but
    # return the Tool objects), assert "hints" in properties.
```

> Reuse the list-tools invocation helper from test_mcp_write_tools.py; return the Tool list and find `ingest_plan`, inspect `.inputSchema["properties"]`.

- [ ] **Step 2: Run to fail** (hints not yet in schema if Task 3 not merged on this branch — it is; so this test should pass once the description/verification is in. If it already passes from Task 3, still add the test as a regression lock, and proceed to the copy updates).

- [ ] **Step 3: Implement** — update `_TOOL_DESCRIPTIONS["ingest_plan"]` to append: " Optionally pass `hints` (a glossary or domain notes) to improve extraction of a poorly-structured document; hints never modify the stored source, they only guide extraction." Update `skills/reviewable-ingest/SKILL.md`: add a note that if a preview looks sparse for a content-rich document, the agent may draft hints (glossary, abbreviations, "treat each row as a fact") and call `ingest_plan` again with `hints`, and that the source file is never rewritten. Add one README line. NO middle-dot.

- [ ] **Step 4: Run to pass** — `pytest tests/unit -k mcp -v`; full not-live green; `grep -n "·" skills/reviewable-ingest/SKILL.md README.md` → no output.

- [ ] **Step 5: Commit**
```bash
git add apps/api/src/arche_api/mcp_server.py skills/reviewable-ingest/SKILL.md README.md apps/api/tests/unit/test_mcp_write_tools.py
git commit -m "feat(mcp): ingest_plan hints 노출 + 스킬/README (원문 불변 보강)"
```

---

## Self-Review (author check)

- Spec coverage: §3.1 -> Task 1; §3.2 -> Task 2; §4 service -> Task 3; §4 MCP + §5 skill -> Task 4. All mapped.
- Placeholder scan: tests reference "reuse existing fake/conftest" deliberately; field names/signatures concrete.
- Type consistency: `ExtractContext.enrichment`, `ExtractContextBuilder.build(enrichment=)`, `IngestService._active_hints`, `plan_file(hints=)`, `IngestPlan.hints`, `PlanIngestRequest.hints` consistent across tasks.
- Risk: Task 2 must restore `_active_hints` to None in `finally` (like `_active_resolutions`) so a later non-hinted plan on the same service instance is clean — covered by `test_plan_without_hints_no_enrichment` + the restore assertion.
