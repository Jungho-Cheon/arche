# Ingest Disambiguation (ask-human-on-ambiguity) — Design Spec

Date: 2026-06-27
Status: approved-by-delegation (user delegated design judgment; no interactive brainstorm)

---

## 사람용 요약 (Korean TL;DR)

검토 가능한 적재(plan → preview → commit) 위에 "애매하면 사람에게 질문"을 얹는다. 계획 단계에서 같은 대상일 수도 있는데 임계 바로 아래라 새 점으로 떨어진 엔티티를 *놓친 병합 후보 질문*으로 surface한다. 에이전트는 미리보기에서 그 질문들을 사람에게 묻고, 답을 `ingest_resolve`로 넣으면 계획을 다시 푼다(추출은 캐시 적중이라 LLM 재호출 없음). 미해소 질문은 보수적 기본값(새 점 생성)으로 두므로 자율 에이전트도 막히지 않는다. 1차는 "놓친 병합" 질문만, 결정 영속화는 후속. 본문(영어)이 정본.

---

## 1. Context

The reviewable-ingest container (`plan → preview → commit`) is merged. It surfaces *what will change* but treats every identity decision as final: the 4-step matcher either merges (Steps 1-3) or creates a new node (Step 4), with no way to flag "this is a close call." The highest-value ambiguity is a **missed merge**: an extracted entity whose closest existing node sits just *below* the embedding match threshold (0.92), so it becomes a new node when it may be the same real-world entity phrased differently. This slice surfaces those close calls as questions the agent asks the human, and lets the human's answer refine the plan before commit.

This is idea 2 from the reviewable-ingest roadmap. It plugs into the existing plan container; it does not change normal (non-plan) ingest behavior.

### Verified assumptions (read before implementing)

- **Extraction is content-keyed and disk-cached** (`adapters/extract_cache.py`: `ExtractionCacheKey` = chunk/context/system-prompt/model shas; `IngestService._extract_with_cache`). Re-running `plan_file` on the same file is a cache hit — no LLM re-call. This makes "re-plan with resolutions" cheap. (Embeddings are still recomputed; acceptable.)
- **The matcher already computes sub-threshold candidates.** `EntityMatcher.match` (domain/identity.py) Step 3 does `vector_search(top_k=5)` and merges on cosine ≥ `EMBEDDING_MATCH_THRESHOLD` (0.92). The best candidate in a band just below threshold is the missed-merge signal.
- **Resolutions reuse the existing forced-match path.** `ExtractedEntity.matched_existing_id` (ADR-0009 D2) already lets `_upsert_entities` skip the matcher and merge into a given id. A "merge" resolution sets that id; a "keep" resolution forces create-new and suppresses re-asking.

## 2. Scope

In scope (slice 1):

- Detect missed-merge ambiguities during planning: Step-3 best candidate with cosine in `[AMBIGUITY_BAND_LOW, EMBEDDING_MATCH_THRESHOLD)` while the decision is create-new.
- Carry them in the plan as `open_questions` (capped + prioritized).
- `ingest_preview` exposes the questions; `ingest_resolve(plan_id, resolutions)` re-plans with the human's answers (cache-served extraction) and returns the refined plan.
- Unresolved questions default to create-new (conservative, non-blocking) — autonomous fallback.
- Update the agent skill to walk the human through the questions.

Out of scope (later):

- Cross-session/re-ingest **decision persistence** (a resolved answer is remembered only within the plan; re-ingest re-asks). Follow-up.
- Low-confidence *merge* questions (cosine just above threshold). Slice 1 covers missed-merge only.
- "Merge into an arbitrary other id" (slice 1 offers only merge-into-the-suggested-candidate or keep-new).
- Vector overlay for pending same-plan entities (inherited limitation).

## 3. Architecture

### 3.1 Ambiguity detection (planning)

- `MatchResult` gains `near_miss: tuple[StoredEntity, float] | None` (candidate + cosine), populated by Step 3 when the best candidate's cosine is in `[AMBIGUITY_BAND_LOW, EMBEDDING_MATCH_THRESHOLD)` and no merge happened.
- `_upsert_entities`, when it creates a new node AND `result.near_miss` is set AND the entity's signature is not force-resolved to keep, records an `AmbiguousMatch`. These bubble up via a new `IngestResult.ambiguities: list[AmbiguousMatch]`.
- `plan_file` reads `result.ambiguities`, assigns stable `question_id`s, caps to `MAX_OPEN_QUESTIONS` (prioritized by similarity desc), and stores them on `IngestPlan.open_questions`.
- Normal (non-plan) ingest also populates `ambiguities` but ignores them — **zero behavior change** to existing ingest.

### 3.2 Resolution (re-plan with hints)

- `IngestService.resolve_plan(plan, resolutions)`:
  - Builds a signature→decision map (`"<normalized_name>\x00<type>" → "merge:<candidate_id>" | "keep"`).
  - Sets a transient `self._active_resolutions` (same swap/restore pattern as the `self._graph` swap in `plan_file`), then calls `plan_file` again. Extraction is cache-served.
  - In `_upsert_entities`, for each extracted entity: if its signature maps to `merge:<id>`, set `matched_existing_id=<id>` (reuse ADR-0009 path); if `keep`, force create-new and suppress near-miss recording for that signature.
  - The refined plan replaces the stored one under the **same `plan_id`** with `previewed=False` (the human must re-preview the new delta before commit).
- Resolutions are accumulated across `ingest_resolve` calls (later answers merge with earlier), so the agent can resolve in batches.

### 3.3 Data structures

| Type | Fields |
|---|---|
| `AmbiguousMatch` (frozen) | `question_id: str`, `extracted_name: str`, `extracted_type: str`, `candidate_id: str`, `candidate_name: str`, `similarity: float`, `kind: str = "possible_missed_merge"` |
| `IngestResult` (+field) | `ambiguities: list[AmbiguousMatch] = []` |
| `IngestPlan` (+field) | `open_questions: list[AmbiguousMatch] = []` |
| Resolution input | `{question_id: str, decision: "merge" | "keep"}` ("merge" = into that question's candidate) |

## 4. MCP / agent surface

| Tool | Change |
|---|---|
| `ingest_plan` | summary gains `open_questions: int` |
| `ingest_preview` | response gains `questions: [{question_id, extracted_name, extracted_type, candidate_id, candidate_name, similarity, kind}]` |
| `ingest_resolve` (NEW) | input `{plan_id, resolutions: [{question_id, decision}]}`; re-plans; returns refined summary + remaining `questions`; sets `previewed=False` |
| `ingest_commit` | unchanged; unresolved questions already defaulted to create-new in the plan |

Registered only when ingest_service + plan_registry are injected (same gating as the other write tools). Not in `WRITE_TOOL_NAMES_EXCLUDED`.

### Agent loop (the interaction this optimizes)

`ingest_plan` → `ingest_preview` (shows delta + questions) → if questions: agent asks the human each ("'X' looks close to existing 'Y' (87%) — same thing, or new?"), collects answers → `ingest_resolve` → `ingest_preview` again (refined) → on human confirm → `ingest_commit`. Unanswered questions are safe (create-new).

## 5. Orchestration / skill

- Tool descriptions: `ingest_preview` notes "if `questions` is non-empty, ask the human about each before commit"; `ingest_resolve` notes "feed the human's answers, then preview again."
- Server `instructions`: extend the ritual to "plan → preview → (resolve questions) → confirm → commit."
- `skills/reviewable-ingest/SKILL.md`: add a step for handling `questions` (ask human, `ingest_resolve`, re-preview).

## 6. Constants / tunables

- `EMBEDDING_AMBIGUITY_BAND_LOW = 0.82` (new, identity.py). Band is `[0.82, 0.92)`.
- `MAX_OPEN_QUESTIONS = 12` (cap; prioritize by similarity desc).

## 7. Limitations / follow-ups

- No cross-session/re-ingest decision persistence (in-plan only) — follow-up issue.
- Missed-merge only (no low-confidence-merge questions, no arbitrary-target merge).
- Near-miss against a same-plan pending entity is not detected (vector overlay deferred, inherited).
- `resolve_plan` re-embeds (extraction cached, embeddings not) — acceptable for slice-1 doc sizes.

## 8. Test strategy

- Matcher: a candidate with cosine in [0.82, 0.92) yields `MatchResult(existing=None, step=4, near_miss=(cand, sim))`; ≥0.92 still merges (near_miss None); <0.82 yields no near_miss.
- Plan: a doc whose entity near-misses an existing node produces one `open_question` with the right candidate + similarity; cap + priority honored.
- Resolve "merge": re-plan turns the create-new into a merge into the candidate (plan now has an `apply_merge_mutation`, no `create_entity` for it); `previewed` reset to False; no LLM re-call (assert via a counting fake LLM).
- Resolve "keep": entity stays new, question removed from `open_questions`.
- Autonomous fallback: commit with unresolved questions applies create-new (equivalence with plain plan+commit).
- Normal ingest unchanged: `ambiguities` populated but graph writes identical to before (regression guard).
- MCP: `ingest_resolve` registered with service; preview exposes `questions`; 6 read tools + commit unchanged.

## 9. Task breakdown (detailed in the plan)

1. Ambiguity detection: `AMBIGUITY_BAND_LOW`, `MatchResult.near_miss`, `AmbiguousMatch`, `IngestResult.ambiguities`, `_upsert_entities` recording.
2. Plan wiring: `IngestPlan.open_questions`, `plan_file` populates (cap + priority + question_id).
3. Resolution engine: `self._active_resolutions` + `_upsert_entities` forced-match/keep, `IngestService.resolve_plan` (re-plan, same plan_id, previewed=False).
4. Service + schemas: `ingest_resolve` service fn, preview `questions`, plan summary `open_questions`.
5. MCP tool `ingest_resolve` + descriptions + instructions; skill + README.
