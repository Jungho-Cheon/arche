# Fixing what got in wrong — write-time prevention over read-time diagnosis

Status: design settled for the remaining items (2026-08-09). Covers #171, #170 (done),
#172, #159, and the extraction contract. Written before implementation, not after.

## 한국어 요약

Arche 사용자는 자료를 넣고, 묻고, 잘못 들어간 것을 고친다. 셋 중 고치는 쪽만 비어
있었다. #170/#171/#172/#159 는 따로 난 결함이 아니라 전부 여기서 나온다.

원칙 하나를 먼저 정한다. **읽기에서 사후 진단하지 말고 쓰기에서 막는다.** 실제 MBTI
그래프(123 노드)를 재 보니 정규명 중복 0, 두 대상이 한 노드에 든 것 0 이었다. 쓰기 쪽
수정이 이미 막고 있다는 뜻이다. 반면 관계가 하나도 없는 노드 8 건과 이름이 두 대상을
잇는 노드 3 건은 남아 있었고, 둘 다 계획 단계에서 계산할 수 있는데 아무도 말해 주지
않아서 통과한 것이다.

읽기 도구는 늘리지 않는다. 전량 열거는 `find_entities` 의 `keywords` 를 선택으로 바꿔
풀고, 새 도구는 `graph_health` 하나만 둔다.

## Guarantees

The write path upholds these regardless of source or form (prose, tables, JSON, code,
chat logs, images). No per-format special casing.

| # | Guarantee | Broken by | State |
|---|---|---|---|
| G1 | One node is one real-world thing | table rows, citation lists, JSON arrays | to do |
| G2 | A new node with no relation is surfaced before commit | item lists with no prose | to do |
| G3 | A dropped relation is never silent | chunk boundaries, unresolved endpoints | to do |
| G4 | Ambiguous identity is asked, never guessed | varying surface forms across sources | holds, one gap (#172) |
| G5 | What was written can be deleted | any source | to do (#159) |

## Done

`find_entities` now enumerates when `keywords` is omitted, and reports `total` and
`offset` in both modes. `graph_health` counts three signals over `EntitySurface` rows
supplied by the adapters, so Neo4j and embedded Kuzu agree by construction. Details in
`apps/api/src/arche_api/domain/README.md`.

---

## Where the line sits

Arche gives the agent primitives and guarantees; the agent supplies judgment
(ADR-0006, ADR-0016). Two rules follow, and they decide what belongs in the code.

**Expose what the caller cannot see; do not compute what it already has.** A plan
preview already lists `new_entities` with ids and `new_relations` with endpoints, so
"which new node has no relation" is a set difference the caller can do. Arche does not
compute it. A dropped relation appears nowhere in the preview, so Arche must report it.

**Four things stay with Arche because they are guarantees, not judgments.**
Reproducibility (`normalize` and the thresholds are ADR-0005 control variables; an LLM
deciding each time makes the same input produce different graphs), namespace isolation,
provenance, and not silently undoing a decision a human already made.

## A. #172 — a split node's name stays ambiguous

### What actually happens now

Splitting sets `blocked_aliases` on both nodes: the new node blocks the origin's
normalized name, the origin blocks the new node's. `EntityMatcher` Step 3 and
`EntityMerger` honour it (`identity.py:325`, `:390`).

The gap is Step 1. It matches on the node's **own** `normalized_name`, and a node never
blocks its own name — it cannot, or re-ingesting the origin's own source would stop
merging. So a later document that calls the split-off thing by the origin's name lands
back on the origin, silently.

### Why it cannot be resolved automatically

The name is genuinely ambiguous: the same string legitimately means the origin in one
document and the split-off node in another. Any automatic rule is wrong half the time.
G4 says ask.

### Design

Make the split visible; do not decide for the caller.

`StoredEntity.blocked_aliases` records the split, but it appears in no read response —
not in `Node`, not in `MergeView`. So an agent reviewing a plan that merges into a
previously split node has no way to know the name is contested. It would have judged
correctly with that fact; it never had it.

`MergeView` gains `target_blocked_aliases: list[str]`, non-empty exactly when the target
has been split. The agent reads the preview, sees which merge lands on a contested name,
and decides: commit as planned, re-plan with `hints`, ask the human, or split again
afterwards.

No new question kind, no `resolve` path, no commit latch change. One field.

### Why not raise a question instead

A question forces one resolution procedure on every caller and blocks commit until
answered. That is Arche deciding how the judgment gets made. The split fact is what the
agent lacks; the judgment is already its job.

### Verification

End to end: ingest a document producing one node, split it, re-ingest a document using
the origin's old name, assert a question appears instead of an automatic merge, answer
`keep`, assert two nodes remain.

---

## B. #159 — delete by source

### What already exists

`apply_entity_diff(entity_id, source_path, run_id)` deletes a node when that source is
its only source, and otherwise removes just that source from it. `apply_relation_diff`
does the same for relations. `_diff_previous` (`ingest.py:1275`) walks a prior run's
emitted ids and applies both, relations first so cascade deletes do not misreport.

`PlanningGraphRepository` already records both as writes, so they pass through the
planning wrapper untouched.

### Design

Delete is re-ingesting the source as empty. `delete_source(source_path)` calls
`_diff_previous` with empty new-id sets against the latest succeeded run for that
source. No new storage primitive.

This gets the hard part right for free: a node cited by three documents loses one
source and survives; a node cited only by the deleted document goes away with its
relations.

It goes through plan, preview, commit like every other write, because it cannot be
undone. `ingest_delete_plan` returns counts, preview lists what disappears versus what
merely loses a source, commit applies it.

### Open choice — what identifies the thing to delete

| Option | Fits |
|---|---|
| (a) `source_path` only | matches how the graph records provenance; one call per document |
| (b) `source_path` and `entity_id` | also allows deleting one node the extractor invented |

Recommendation: **(a) first**. Node-level delete is a different question — a node has no
single owner, so deleting one by id would strand its sources. If it turns out to be
needed, the split tools plus a source delete already cover most of it.

### Verification

Ingest two documents sharing an entity, delete one source, assert the shared node
survives with one fewer source and the exclusive nodes are gone. Restart the process in
between, on the embedded store.

---

## C. G1, G2, G3 — the plan says what is wrong before commit

### G1 — one node is one thing

`extraction_contract.py` has no rule against joining two things into one name. Observed:
`Wikipedia, Myers-Briggs Type Indicator` and `MBTI Manual 3rd edition, CAPT 자료`.

Add one principle to the contract: an entity name names exactly one thing; do not join
several with a comma, slash, or `및`. Changing the contract changes
`extraction_fingerprint`, so stored documents re-extract on their next ingest. That is
what the fingerprint is for.

### G2 — a node with no relation is surfaced

The plan already knows every new entity and every new relation. A new entity that
appears in no relation is computable at that moment with no extra call.

### G3 — a dropped relation is never silent

`IngestFileResult.relations_skipped_dangling` is already counted (`ingest.py:70`) and
never leaves the domain. It appears in neither `PlanSummary` nor `PlanPreview`. This is
the most likely cause of the 8 unconnected nodes.

### Design

One field on `PlanPreview`: `warnings: list[PlanWarning]`, each with `kind`, `message`,
and the ids involved. Three kinds to start — `entity_without_relation`,
`name_joins_two_things`, `relation_dropped_dangling`.

Warnings do not block commit. Questions block because they are decisions only a human
can make; warnings are quality signals the human may accept. Blocking on them would
make the ritual unusable on messy sources, and people would stop reviewing.

### The unreviewed write paths

`arche ingest` and `POST /admin/ingest` never build a plan, so they never reach
`PlanPreview`. They are where volume will be. The same warnings go into the CLI summary
and the REST status response, computed from the same code.

### Verification

Ingest a document that names an entity nobody relates to, assert the warning appears and
commit still succeeds. Ingest through the CLI and assert the same count appears in its
summary.

---

## D. ADR entry point

The premise in issue #171's neighbourhood was partly wrong: ADR-0007 and ADR-0008 do
carry `Status: superseded` both in-file and in the index. What is actually missing is the
other direction — a new session is told by `CLAUDE.md` to read ADR-0001 through ADR-0006
as its entry point, and nothing in those six says a later ADR corrected them.

Two concrete edits, no rewriting:

1. Each entry-point ADR gets one line under `Status` naming the later ADR that amended
   it, if any (0004 by 0020, 0006 by the MCP-primary decision and the tool count).
2. `CLAUDE.md` reading order names the later ADRs that must be read with them.

The MCP-primary positioning (2026-07-05) is currently recorded only in memory, not in any
ADR. Whether to write it up is the user's call, not part of this work.

---

## Order

1. C (G1, G2, G3) — prevention first, since it decides what the read side never has to
   report.
2. A (#172) — smallest, and it closes the last hole in G4.
3. B (#159) — largest, and it benefits from C being in place.
4. D — documentation only.

## Out of scope

#82 (cross-doc identity thresholds) touches the measurement control variables in
ADR-0005. Its practical half is G1 above; the rest needs its own decision record.
