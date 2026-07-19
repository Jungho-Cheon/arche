---
name: arche-ingest
description: Use when the user wants to load documents or pages into Arche — local files, or external sources (Confluence/Jira pages, URLs, another tool's output) the agent fetched itself. Drives the reviewable ingest flow (ingest_content / ingest_plan → ingest_preview → ingest_resolve → ingest_commit) so nothing is written to the graph without a human review. 문서/외부 소스를 Arche 그래프에 적재할 때.
---

# Loading sources into Arche

Ingestion is **review-gated**: extraction never touches the graph until the human confirms. Never plan and commit in one breath. Follow the flow end to end.

## Pick the entry by where the content is

- **Content you fetched yourself** (a Confluence/Jira page read via another MCP, a URL, text already in context) → **`ingest_content`** with `{ content, source_id }`. Do NOT write it to a temp file first — hand the text directly. Choose a **stable `source_id`** that stands in for a file path, e.g. `confluence:PAGE-123` or the document URL. Re-ingesting the same source with an updated body MUST reuse the same `source_id` so Arche diffs instead of duplicating.
- **A local file on disk** → **`ingest_plan`** with `{ path }` (absolute path).

Both return a `plan_id` and a count summary. They do not write anything yet.

## Then always review before committing

1. **Preview.** Call `ingest_preview` with the `plan_id`. Show the human the delta: new entities, merges into existing entities, new relations, deletions.

2. **Resolve near-misses.** If the preview carries `questions`, the extractor found new entities that look close to existing ones but not close enough to merge automatically. Ask the human about **each** one, then call `ingest_resolve` with their decisions (`merge` = same entity, `keep` = distinct). Then `ingest_preview` again and review any remaining questions.

3. **Commit only after the human confirms.** Call `ingest_commit` with the `plan_id`. It is rejected unless the plan was previewed, and rejected if the graph drifted (re-plan then).

## Guardrails

- Never call `ingest_commit` without a prior `ingest_preview` on that `plan_id`, and never without an explicit human "go ahead".
- Reuse `source_id` for the same source; a fresh label each time creates duplicates instead of updating.
- Pass optional `hints` (a glossary or domain notes) when a document is poorly structured — it guides extraction without modifying the stored source.
- Ingesting sends the content to the configured AI provider for extraction and embedding. If a source must not leave the boundary, do not ingest it.

## 한국어 요약

적재는 사람 검토 게이트다 — 확인 전엔 그래프에 안 쓴다. 에이전트가 읽어온 내용(Confluence/URL)은 파일로 떨구지 말고 `ingest_content(content, source_id)` 로 바로. 로컬 파일은 `ingest_plan(path)`. 그다음 반드시 `ingest_preview` 로 델타를 사람에게 보이고, near-miss `questions` 는 사람에게 물어 `ingest_resolve`, 사람이 "진행" 한 뒤에만 `ingest_commit`. source_id 는 같은 소스에 같은 값을 재사용해야 중복이 안 생긴다.
