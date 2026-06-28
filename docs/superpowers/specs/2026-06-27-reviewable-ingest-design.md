# Reviewable Ingest — Design Spec

Date: 2026-06-27
Status: approved (design); implementation plan written

---

## 사람용 요약 (Korean TL;DR)

적재(문서를 그래프로 저장)를 한 번에 끝내지 않고 `계획 → 미리보기 → 확정` 세 박자로 나눠, 저장 전에 사람이 변경 델타를 검토한다. 핵심 트릭: 검증된 적재 루프를 고치지 않고, 쓰기를 가로채 기록만 하는 그래프 데코레이터로 "쓰지 않는 계획"을 얻은 뒤 확정 때 재생한다. MCP 도구 3개 + 에이전트 스킬로 노출하며, stdio라 로컬 전용이라 인증 본체는 1차에서 불필요. 1차는 단일 파일, 생성·병합·관계 미리보기까지(삭제는 개수만). 본문(영어)이 에이전트 인수인계용 정본이다.

---

## 1. Context

Ingestion currently runs end-to-end: extract → identity-resolve → write to graph, with no human checkpoint. Two problems:

1. Extraction and identity resolution rely on LLM judgment and can be wrong. Bad merges or hallucinated nodes/edges land in the graph and poison downstream agents.
2. To become an agent-driven tool, the agent needs a "here is what I will change, confirm?" step before writing. None exists today.

This design splits ingest into `plan → preview → commit` so the delta is reviewed before it is written. It is also the container for later features (ask-human on ambiguity; document enrichment), which plug into the same plan.

### Existing assets

- `IngestService._dry_run_file` (ingest.py:337) — extracts without writing, but only counts; it does not resolve identity, so it cannot show merges. This design supersedes it with a full mutation plan.
- `IngestTaskRegistry` (admin_tasks.py) — `task_id → state` in-memory pattern, reused for the plan registry.
- `mcp_server.py` — 6 read-only tools. This design adds the first write tools.
- MCP serve path (`cli.py mcp_serve`, `run_stdio_server`) currently wires graph + embedder only, no LLM. Write tools need extraction, so serve must also build the LLM provider + `IngestService` + plan registry.

## 2. Scope

In scope (slice 1):

- `PlanningGraphRepository`: a `GraphRepository` decorator that records writes instead of executing them (record/replay), reusing the existing ingest logic unchanged.
- Three MCP tools: `ingest_plan` / `ingest_preview` / `ingest_commit`.
- In-memory `PlanRegistry`.
- Safety latch at commit: only `previewed=True` plans, and only non-stale plans.
- Orchestration guidance: tool descriptions + server `instructions`.
- Bundled agent skill (`SKILL.md`).
- MCP serve wiring: build LLM provider + `IngestService` + `PlanRegistry` at the serve entrypoint.

Out of scope (later slices):

- Itemized deletion/trim preview (re-ingest only; adapter couples read+write). Slice 1 reports a deletion count and still performs deletions at commit.
- In-plan dedup via Step 3 (embedding) matching — see Limitations.
- Directory (multi-file) plan, ask-human-on-ambiguity, document enrichment, real auth.

## 3. Architecture — write-intercepting plan decorator (record/replay)

The core loop (`_upsert_entities`, ingest.py:900) interleaves decide (matcher reads graph to find a merge target) and do (writes to graph) per entity. In multi-chunk documents, chunk N's decision depends on what chunk N-1 just wrote. So "just skip writes" produces duplicate nodes and breaks correctness.

Instead of rewriting the loop, introduce `PlanningGraphRepository` (implements the `GraphRepository` port, wraps a real one):

- Read methods: delegate to the real graph. Exception: `find_by_normalized_name` and `find_entity_id_by_normalized_name` also consult pending entities created earlier in this plan (read overlay), so repeated normalized names within a document merge correctly inside the plan.
- Write methods (`create_entity`, `apply_merge_mutation`, `upsert_relation`, `create_ingestion_run`, `mark_entity_emitted`, `mark_relation_emitted`, `finalize_run`, `apply_entity_diff`, `apply_relation_diff`, `append_emitted_relations`): record the call intent in order; do not execute. `create_entity` also adds to the pending normalized-name index. `apply_merge_mutation` snapshots the target's current state (`get_stored_entity`) as `before` for preview.

Then:

- `ingest_plan` = run the unchanged `ingest_file` with the decorator swapped in for `self._graph`. The recorded writes are the `IngestPlan`. Nothing is written.
- `ingest_commit` = replay the recorded writes against the real graph, in order.

Why this wins: the validated extraction / identity / relation logic is untouched. The expensive steps (LLM extraction + embedding) run once at plan time and their outputs (including embeddings) live in the plan, so commit calls neither the LLM nor the embedder. What the human sees equals what gets stored.

### Data structures

| Type | Fields |
|---|---|
| `RecordedWrite` (frozen) | `method: str`, `kwargs: dict`, `before: StoredEntity \| None = None` |
| `IngestPlan` | `plan_id, source_path, source_hash, extractor_version, created_at, previewed: bool, writes: list[RecordedWrite], result: IngestResult, depends_on_entity_ids: list[str]` |

## 4. MCP tools

| Tool | Input | Action | Returns |
|---|---|---|---|
| `ingest_plan` | `{ path }` | decorator-driven extract+resolve (no writes), store plan | `{ plan_id, summary }` |
| `ingest_preview` | `{ plan_id }` | serialize delta for human review; set `previewed=True` | `{ new_entities, merges(before/after), new_relations, deletion_count }` |
| `ingest_commit` | `{ plan_id }` | replay reviewed plan | `{ entities_created, entities_updated, relations_created, deletions, ... }` |

These are the first write tools on MCP. stdio MCP has no network surface, so the "read-only over network" invariant holds without real auth; the existing REST admin write surface is not expanded. In `mcp_server.py`, `WRITE_TOOL_NAMES_EXCLUDED` keeps blocking `create_entity` etc.; the three new tools are intentionally registered (not in that set).

## 5. Safety latch

1. Preview-before-commit: `ingest_commit` passes only if `previewed == True`, else `unprocessable` with "call ingest_preview before commit". `ingest_preview` sets the flag.
2. Optimistic stale check: at commit, verify each id in `depends_on_entity_ids` still exists; if any is gone, reject with "plan is stale; re-plan". Full multi-write atomicity is out of scope (local single user) — see Limitations.

## 6. Plan state

`plan_id → IngestPlan` in an in-memory `PlanRegistry` (same pattern as `IngestTaskRegistry`; created once at serve/app startup and shared). Volatile across restart — acceptable under the local single-user assumption.

## 7. Orchestration

Order lives in guidance, not in a mega-tool (preserves the primitive philosophy and room for mid-flow intervention):

- Tool descriptions: `ingest_plan` ends with "after planning you MUST call ingest_preview, show the human the delta, then commit only after they confirm"; `ingest_commit` says "do not call without a prior ingest_preview".
- Server `instructions`: add one paragraph describing the ingest ritual.

## 8. Agent skill (SKILL.md)

A bundled skill so "ingest this document" triggers the ritual even if the agent does not know the tools exist.

- Triggers: "이 문서 적재", "이 파일 넣어줘", "add this to the knowledge graph".
- Body: ① `ingest_plan` → ② report summary → ③ `ingest_preview` and present delta → ④ commit after human confirmation → ⑤ report result. Includes handling for not-previewed and stale rejections.
- Location: skill dir in the repo + one line in README "직접 해보기".

## 9. Limitations / follow-ups

- Step 3 (embedding) in-plan dedup: the overlay only sees pending entities by exact normalized name. Two surface forms in one document that would merge only via embedding similarity may appear as two separate new nodes in the plan. Rare; visible to the human in preview; self-heals on re-ingest. Vector overlay is a follow-up.
- No itemized deletion preview: slice 1 reports a count; commit still performs deletions.
- No full atomicity: commit's multiple writes are not a single transaction (no contention under local single user). Strengthen via staging-subgraph promote or single transaction when multi-user/networked.
- Plan volatility, single-file only, no auth: intended slice-1 boundaries.
- ~~Whole plan path is `default`-namespace only: `IngestPlan` did not carry a namespace, so plan/resolve always ran under `default`.~~ **Resolved (issue #92):** `IngestPlan` carries `namespace_id`; `plan_file` records the namespace it received, `resolve_plan` re-plans under `plan.namespace_id`, and the `ingest_plan` entry point forwards a request-level `namespace_id` (default `"default"`) instead of hardcoding. Note: candidate *matching* is still not namespace-scoped at the matcher/repo layer — that isolation is a separate follow-up (issue #94).

## 10. Test strategy

- Plan does not write: run `plan_file` with a fake graph, assert zero real write calls.
- Equivalence: `plan` + `commit` equals direct `ingest_file` (created/merged/relation counts).
- Multi-chunk normalized merge: two chunks emitting the same normalized name merge to one node in the plan (overlay).
- Merge preview accuracy: before/after matches the actual merge for a node that joins an existing one.
- Safety latch: (a) commit without preview is rejected; (b) commit after a dependency is deleted is stale-rejected.
- MCP contract: three new tools exposed with correct input schema; the six read tools are unchanged.

## 11. Task breakdown (detailed in the plan)

1. `RecordedWrite` / `IngestPlan` models + `PlanRegistry`.
2. `PlanningGraphRepository` (write recording + normalized-name read overlay).
3. `IngestService.plan_file()` + `commit_plan()`.
4. Preview serialization + plan/preview/commit service functions (safety latch).
5. MCP serve wiring + three tools + descriptions + instructions.
6. Agent skill (SKILL.md) + README line.
