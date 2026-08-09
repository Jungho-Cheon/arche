# Repair loop — write-time prevention over read-time diagnosis

Status: in progress (2026-08-09). Covers issues #170, #171, #172, #159.

## 한국어 요약

Arche 사용자는 넣고, 묻고, 고친다. 셋 중 **고치기 고리만 비어 있었다.** 노드를 가르는
도구는 있는데 가를 노드를 찾는 길이 없고, 지우는 길도 없다. #170/#171/#172/#159 는
따로 난 결함이 아니라 이 빈 고리 하나다.

원칙 하나를 먼저 정한다. **읽기에서 사후 진단하지 말고 쓰기에서 막는다.** 실제 MBTI
그래프를 재 보니 정규명 중복 0, 뭉침 0 이었다 — 쓰기 쪽 수정이 이미 막고 있었다. 반면
관계가 하나도 없는 노드 8/123, 이름이 두 대상을 잇는 노드 3 건은 남아 있었고, 둘 다
계획 단계에서 계산할 수 있는데 아무도 말해 주지 않아서 통과한 것이다.

읽기 도구는 늘리지 않는다. 열거는 `find_entities` 의 막힌 구멍을 여는 것으로 풀고,
새 도구는 `graph_health` 하나만 둔다 (검토 없는 적재 경로와 옛 자료 점검용).

## Guarantees

The write path must uphold these regardless of source or form (prose, tables, JSON,
code, chat logs, images). No per-format special casing.

| # | Guarantee | Broken by |
|---|---|---|
| G1 | One node is one real-world thing | table rows, citation lists, JSON arrays |
| G2 | A new node with no relation is surfaced before commit | item lists with no prose |
| G3 | A dropped relation is never silent | chunk boundaries, unresolved endpoints |
| G4 | Ambiguous identity is asked, never guessed | varying surface forms across sources |
| G5 | What was written can be deleted | any source |

G4 already holds (4-step matching + `same_name_different_type` questions).
G1/G2/G3 are the work below. G5 is issue #159.

## Read surface: 7 tools, not 9

`find_entities` was the only way to see nodes, and it required keywords
(`min_length=1`), capped at 50, and never said how many existed. That is why a
16-node type returned 14. Fix the tool, do not add one:

- `keywords` becomes optional. Omitted -> deterministic enumeration ordered by id.
- `total` and `offset` always present, in both modes.
- `EntityMatch.score` / `matched_keyword` become nullable (enumeration has no score).

`get_schema` already reports exact per-type counts; only its `examples` are capped.
So "how many" was never missing — "which ones" was.

One new tool only: `graph_health`. It is a *judgment*, not a projection, so it
cannot fold into a read tool. It exists because unreviewed write paths
(`arche ingest`, `POST /admin/ingest`) bypass preview entirely.

## Shared detector

`domain/graph_health.py::assess_graph_health` takes an iterable of `EntitySurface`
and is called at two moments over the same logic:

- **plan time** — over the plan's pending entities -> `PlanPreview.warnings`
- **read time** — over a stored namespace -> `graph_health` tool

Adapters only supply rows. That is what makes Neo4j and embedded Kuzu agree (#170).

## Work items

- [x] `domain/graph_health.py` — detector (duplicate names, over-merge, isolated)
- [x] `ports.EntitySurface` + `iter_entity_surfaces` + `list_entities`
- [x] Kuzu + Neo4j implementations (Neo4j's old `find_overmerged_entities` was
      namespace-blind and is replaced)
- [x] `PlanningGraphRepository` forwarding
- [x] `find_entities` merge (keywords optional, total, offset)
- [ ] Register + dispatch `graph_health` MCP tool; drop the stale `list_entities`
      description
- [ ] REST route for `graph_health`
- [ ] G1: extraction contract — one entity is one thing
- [ ] G2/G3: `PlanPreview.warnings` (no-relation nodes, joined names, dropped relations)
- [ ] #172: split origin must not re-absorb the old name
- [ ] #159: delete by source, through the same plan/preview/commit ritual
- [ ] Tests: unit + embedded e2e; both stores agree
- [ ] Docs: `apps/docs` repair-loop page, tool reference regen

## Out of scope

#82 (cross-doc identity at extraction) touches the measurement control variables in
ADR-0005 and needs its own decision record.
