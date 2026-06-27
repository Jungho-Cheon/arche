---
name: reviewable-ingest
description: Use when the user asks to ingest a document or file into the Arche knowledge graph ("이 문서 적재해줘", "이 파일 그래프에 넣어줘", "add this to the knowledge graph"). Drives the plan to preview to confirm to commit ritual via the Arche MCP tools.
---

# Reviewable Ingest

When putting a document into the Arche graph, do not write immediately. Let the human review the delta first, then commit.

## Order (follow exactly)

1. Call `ingest_plan` with the file path. Nothing is written yet. Report the returned `plan_id` and the summary (new nodes / merges / relation counts) to the user in one line.
2. Call `ingest_preview` with that `plan_id`. Present the new nodes, merges (before/after), new relations, and deletion count in a human-readable form.
3. Ask the user "Commit this?" and get explicit confirmation. Flag any questionable merge or odd node first.
4. On confirmation, call `ingest_commit`. Report the result counts.

## Rejection handling

- If `ingest_commit` returns "call ingest_preview before commit", do step 2 first.
- If it returns "plan is stale", the graph changed in between. Start over from `ingest_plan`.

## Do not

- Do not commit without a preview.
- Do not commit without user confirmation.
