# Ingest Context Enrichment (hints, source-preserving) — Design Spec

Date: 2026-06-28
Status: approved-by-delegation (user delegated design judgment; no interactive brainstorm)

---

## 사람용 요약 (Korean TL;DR)

원문을 절대 고치지 않고, 에이전트가 만든 보조 메모(용어 풀이, 약어, "표의 각 행을 사실로 취급" 같은 도메인 힌트)를 추출 프롬프트의 `ExtractContext`에 `[ENRICHMENT]` 블록으로 끼워 넣어 추출 recall을 올린다. 힌트는 LLM 입력에만 들어가고 저장되는 노드/관계의 출처(source_refs)는 원문 그대로다(provenance 보존). `ingest_plan(path, hints)`로 받아 계획에 싣고, 캐시 키가 힌트를 포함하므로 힌트가 바뀌면 재추출된다. 로드맵의 마지막 슬라이스(아이디어 1). 본문(영어)이 정본.

---

## 1. Context

This is idea 1 of the reviewable-ingest roadmap, in its safe form. The original idea ("rewrite poorly-written documents so entities/relations extract better") is rejected because rewriting the source breaks provenance: every stored node/edge traces to a `source_ref` (file + chunk), and if the agent rewrites the text, those refs point to sentences the author never wrote — hallucination moves upstream and becomes invisible.

The safe form: leave the source untouched and let the agent supply **extraction context** — a glossary, alias/abbreviation notes, domain priors ("each table row is a fact", "AmEx = American Express") — that is prepended to the LLM extraction prompt only. The codebase already prepends an `ExtractContext` (ADR-0009: DOC_CONTEXT / KNOWN_ENTITIES / SCHEMA blocks) to the extraction call. This slice adds one more block, `[ENRICHMENT]`, carrying the agent's notes, without ever mutating the stored chunk text.

### Verified integration points

- `ExtractContext` (domain/extract_context.py) is a frozen dataclass `{doc, known_entities, schema}`; `render_context_block` serializes it to the prompt prefix.
- `_build_chunk_context` (domain/ingest.py) builds it via `ExtractContextBuilder.build(...)` per chunk.
- The extraction cache key (`adapters/extract_cache.py`) includes `context_sha = sha256(render_context_block(...))`. So adding enrichment to the rendered block makes the cache key change when hints change — different hints force re-extraction; identical hints hit the cache. Correct by construction.
- The transient-attribute pattern (`self._active_resolutions`, set/restored around `plan_file`) from idea 2 is reused for `self._active_hints`.

## 2. Scope

In scope (slice 1):

- `ExtractContext.enrichment: str | None` + `[ENRICHMENT]` block in `render_context_block` + `ExtractContextBuilder.build(enrichment=...)`.
- Thread hints through `IngestService`: `self._active_hints`, `_build_chunk_context` passes enrichment, `plan_file(path, *, hints=None)` set/restore, `IngestPlan.hints`, `resolve_plan` carries `plan.hints`.
- `ingest_plan` accepts optional `hints: str` (service + MCP tool).
- Skill guidance: when a content-rich doc yields sparse extraction, add hints and re-plan; emphasize the source is never modified.

Out of scope (later):

- Re-enriching an **already-committed identical file**: `ingest_file`'s short-circuit (same path+hash+extractor_version) returns the prior run without re-extracting, so new hints are ignored on that path. New/uncommitted files (the dominant plan case) are unaffected. Follow-up.
- Agent-generated hints automation (the agent composing hints from a low-yield preview is skill behavior, not API).
- Structured hints (glossary as typed entries). Slice 1 takes a free-text `hints` string.

## 3. Architecture

### 3.1 Enrichment in the extraction context

- `ExtractContext` gains `enrichment: str | None = None` (frozen, default keeps every existing constructor valid).
- `render_context_block` emits an `[ENRICHMENT]` block near the top (after DOC_CONTEXT) when `enrichment` is non-empty: a labeled, verbatim copy of the agent's notes. Omitted entirely when None/empty (so the cache key and existing behavior are unchanged for non-hinted ingest).
- `ExtractContextBuilder.build` accepts `enrichment: str | None = None` and sets it on the returned `ExtractContext`.

### 3.2 Threading hints (transient, plan-scoped)

- `IngestService.__init__` adds `self._active_hints: str | None = None`.
- `_build_chunk_context` passes `enrichment=self._active_hints` into `ExtractContextBuilder.build`.
- `plan_file(path, *, hints=None)`: set `self._active_hints = hints`, call `ingest_file`, restore in `finally` (mirrors the `_graph` / `_active_resolutions` swaps). `IngestPlan` stores `hints`.
- `resolve_plan`: set `self._active_hints = plan.hints` for the re-plan, so resolution preserves enrichment.
- Normal (non-plan) ingest: `self._active_hints` stays None → zero behavior change.

### 3.3 Provenance invariant

Hints enter only the LLM prompt prefix. `SourceRef`s are built from the original chunk text/index and are never derived from the enrichment. A regression test asserts that two plans of the same file (with vs without hints) produce identical `source_refs` for any node that appears in both (the source-of-truth is unchanged; only what the LLM extracts may differ).

## 4. MCP / agent surface

| Tool | Change |
|---|---|
| `ingest_plan` | input gains optional `hints: str`; threaded into extraction context |
| `ingest_preview` / `ingest_resolve` / `ingest_commit` | unchanged (resolve re-applies the plan's stored hints) |

`PlanIngestRequest` gains `hints: str | None = None`. `plan_ingest` passes it to `service.plan_file(..., hints=body.hints)`.

### Agent interaction

When `ingest_preview` shows few entities/relations for a content-rich document, the agent composes hints (glossary, abbreviations, "treat each row/line as a fact", disambiguation) and calls `ingest_plan` again with `hints=...`. The original document is never altered; only extraction improves. The questions loop (idea 2) and the preview/commit safety are unchanged.

## 5. Orchestration / skill

- `ingest_plan` description: "optionally pass `hints` — a glossary or domain notes — to improve extraction of a poorly-structured document. Hints never modify the stored source; they only guide extraction."
- `skills/reviewable-ingest/SKILL.md`: add guidance — if a preview looks sparse for a rich document, draft hints and re-plan; state explicitly that the source file is never rewritten.

## 6. Limitations / follow-ups

- Short-circuit ignores new hints for an already-committed identical file (slice-1 limitation; follow-up).
- Free-text hints only (no structured glossary).
- If `ExtractContextBuilder` is absent (no ADR-0009 context path), hints are dropped — but the plan/MCP path always constructs it (deps wiring), so this only affects bare test doubles.

## 7. Test strategy

- Render: `render_context_block` includes an `[ENRICHMENT]` block iff enrichment is non-empty; omitted when None.
- Cache-key sensitivity: different hints change `context_sha` (so re-extraction happens); identical hints reuse the cache (counting fake LLM).
- Threading: `plan_file(path, hints="...")` makes the LLM receive a context whose rendered block contains the hints (assert via a fake LLM that captures the context); `self._active_hints` restored to None after.
- Provenance invariant: node source_refs identical with vs without hints.
- Normal ingest unchanged: hints None → identical writes/cache key to pre-feature.
- resolve preserves hints: a plan created with hints, after resolve, still extracts with those hints (no LLM re-call when content+hints unchanged).
- MCP: `ingest_plan` input schema exposes `hints`; passing it reaches `plan_ingest`; other tools unchanged.

## 8. Task breakdown (detailed in the plan)

1. `ExtractContext.enrichment` + `[ENRICHMENT]` render block + `ExtractContextBuilder.build(enrichment=)`.
2. Thread hints in IngestService (`_active_hints`, `_build_chunk_context`, `plan_file(hints=)`, `IngestPlan.hints`, `resolve_plan`).
3. Service + schema (`PlanIngestRequest.hints`, `plan_ingest` passes through).
4. MCP `ingest_plan` hints input + skill + README.
