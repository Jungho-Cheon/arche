---
name: arche-query
description: Use when answering a question that could be grounded in an Arche knowledge graph — domain facts, "how are X and Y related", "what else relates to Z", business rules, or anything previously ingested into Arche. Drives the Arche MCP read primitives (find_entities, get_neighbors, find_related, find_path, get_subgraph, get_schema) in the intended order so answers come from graph facts, not guesses. 그래프에 적재된 지식으로 질문에 답할 때.
---

# Answering from the Arche graph

Arche is a graph knowledge base. The answer LLM lives **outside** Arche — Arche returns structured facts, you write the answer. Follow this loop; do not invent facts the graph does not contain.

## When this applies

The user asks something that could be grounded in ingested knowledge: a domain rule, "why does X apply to Y", "what is related to Z", a definition, a policy. If nothing has been ingested yet, use `arche-ingest` first.

## The loop

1. **Orient once (optional).** If you do not know the graph's shape, call `get_schema` to see entity types, relation types, and counts. Skip if you already know it this session.

2. **Anchor.** Pull the key nouns from the question and call `find_entities` with them as `keywords`. This returns candidate entry nodes with IDs and scores. Pick the best-matching node IDs. Almost every query starts here.

3. **Traverse from the anchors** — choose the primitive by the question shape:
   - "What else is related to these?" / gather the neighborhood in one shot → **`find_related`** with the anchor IDs as `seeds`. It folds a multi-hop walk into one call; prefer it over stepping `get_neighbors` hop by hop.
   - "How are X and Y connected?" → **`find_path`** between the two node IDs. Read `hub_score`: a HIGH hub_score means the path leans on a promiscuous hub ("connected but not meaningfully related") — do not trust it as evidence; re-call with `relation_types` set to the specific relation you expect.
   - "Everything around a few anchors" → **`get_subgraph`** with multiple `entry_ids`.
   - One node's immediate ties → **`get_neighbors`**.
   - Full detail + edge counts of one node → **`get_entity`**.

4. **Answer from what the graph returned.** Ground every claim in the nodes/edges you retrieved. Each node carries `source_refs` (origin file/label) — cite them when useful. If the graph does not contain the answer, say so plainly and do not fill the gap with outside knowledge.

## Guardrails

- Do not answer domain questions from memory when Arche could ground them — anchor and traverse first.
- Numbers, dates, and rules must come from graph facts. If a value is not in the retrieved subgraph, do not state it.
- Reach farther by raising `hops`/`max_hops`; narrow noise with `relation_types`.

## 한국어 요약

Arche 그래프로 질문에 답하는 순서 규정. (1) 모르면 get_schema 로 그래프 모양 파악, (2) 질문의 핵심어로 find_entities 진입점 확보, (3) 질문 형태에 맞는 프리미티브로 순회 — "관련된 것 다" 는 find_related, "어떻게 연결" 은 find_path(hub_score 높으면 의심), (4) **그래프가 준 사실로만** 답하고 없으면 없다고 말한다. 지어내지 않는다.
