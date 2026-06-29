# Design — User-facing documentation site (VitePress)

> 한국어 요약: 이슈 #100의 사용 가이드를 단일 `docs/guide.md` 대신 VitePress 정적 사이트(`apps/docs`)로 만든다. 랜딩에서 가치 제안을 두괄식으로 보여주고, 과제 중심 가이드(시작/적재/질의/namespace/모델) + 흐름을 끊는 깊은 설명을 담는 개념 페이지 + 찾아보기용 reference 섹션으로 나눈다. pnpm 전용, 로컬 빌드까지만(배포는 별도 이슈). 영어 추가를 대비해 VitePress i18n 구조를 처음부터 깔되 콘텐츠는 한국어만. 모든 curl 예시는 실제 코드와 대조해 정확성을 보장한다. 사용자가 개발을 시작하고 궁금증을 해소하러 방문하는 풍부한 사이트가 목표 — 범위를 최소 5장으로 제한하지 않는다.

- Date: 2026-06-29
- Issue: #100 (사용자 사용 가이드 문서)
- Status: design approved (expanded after code review), pending spec review

## 1. Goal

Give a newcomer a single place that (a) explains what Arche does and why, leading with capability and value, and (b) walks them end-to-end through real usage: install → ingest (text/PDF/images) → query → team isolation (namespace) → model swap. Beyond the task flow, provide a lookup-oriented reference section so a developer who is already building can return to find exact request fields, response shapes, error codes, and config knobs without re-reading prose.

This supersedes the original single-file `docs/guide.md` scope from issue #100 with a small static documentation site, because the content benefits from task-oriented navigation, callouts, and separate concept/reference pages for material that would otherwise break reading flow.

## 2. Scope

In scope:
- New `apps/docs` VitePress site (Korean only).
- Landing page with value proposition (capability-first), task-oriented guide chapters, concept pages, and a reference section.
- pnpm workspace setup at repo root (none exists today).
- Local dev/build only (`pnpm dev`, `pnpm build`).
- i18n-ready config so an English mirror can be added later without moving Korean content.
- README entry-point table link to the site.

Out of scope (explicitly deferred):
- Deployment (GitHub Pages / CI) — separate future issue.
- English content — config scaffolding only.
- Biome/lint for the docs app — markdown-only, revisit if code grows.
- Any change to `apps/api` Python code.

## 3. Site structure

```
apps/docs/
  package.json                # vitepress devDependency, dev/build/preview scripts
  .vitepress/
    config.ts                 # locales (ko root, en placeholder commented), nav, sidebar
  index.md                    # landing: value prop (capability → idea → value), 두괄식
  guide/
    getting-started.md        # docker compose, .env, healthz check, first ingest
    ingest.md                 # CLI quick ingest; REST async admin ingest (202+polling, dry_run); reviewable ingest (MCP plan/preview/resolve/commit); hints; text/PDF/image
    query.md                  # response envelope; how to get an entity ID; 6 primitives each with real curl+response; multi-hop composition
    namespace.md              # Bearer ns:<name>; override order; isolation scope; admin/namespaces visibility; default fallback; partial-share not supported
    models.md                 # provider prefixes; required keys; uv sync --extra providers; claude-code needs no key
  concepts/
    why-graph.md              # why a graph KB (agent token/latency value)
    namespace-model.md        # deep explanation of the namespace isolation model
    path-quality.md           # hub_score / path precision (ADR-0017) — when to distrust a path
  reference/
    primitives.md             # lookup table: each primitive's endpoint, exact request fields, response shape
    errors.md                 # error envelope + full error code catalog with HTTP status
    configuration.md          # environment variable reference (models, keys, Neo4j, dimensions)
```

Navigation principle: `guide/` chapters stay task-oriented and unbroken. Deep conceptual material moves to `concepts/`; factual lookup material moves to `reference/`. Both are reached via callout/link from the guide, never inlined where they would break the doing-flow.

## 4. Toolchain & repo integration

- Package manager: **pnpm** (repo convention for `apps/` frontends). Add `pnpm-workspace.yaml` at root listing `apps/docs`.
- Dependency: `vitepress` only (Vue bundled), devDependency. Static build, no runtime server.
- Scripts: `pnpm dev` (preview server), `pnpm build` (static output to `.vitepress/dist`), `pnpm preview`.
- `.gitignore`: add `apps/docs/node_modules`, `apps/docs/.vitepress/dist`, `apps/docs/.vitepress/cache`.
- Python `uv` toolchain untouched; the two ecosystems are fully separate.

## 5. i18n readiness (Korean now, English later)

- `.vitepress/config.ts` uses the `locales` structure from the start: Korean as root (`/`), English slot (`/en/`) present but commented out.
- Korean content lives at the root (`guide/`, `concepts/`, `reference/`). Adding English later means creating `en/` mirrors and uncommenting the `locales.en` block — existing Korean paths do not move.
- Sidebar and nav authored so per-locale variants are a config edit, not a content reshuffle.

## 6. Content accuracy (issue #100 completion criteria + code-grounded facts)

Every code-touching claim is verified against source before writing. Confirmed facts from the read of `apps/api`:

- **Response envelope**: every success response is wrapped `{"data": <payload>}` (`api/responses.py` `DataEnvelope`). Error responses are `{"error": {"code", "message", "details"}}` (`ErrorBody`/`ErrorEnvelope`).
- **IDs are ULID** (26-char `^[0-9A-Z]{26}$`) on `Node`/`Edge` (`domain/models.py`). Entity IDs are obtained via `find_entities` first, then fed to `get_entity`/`get_neighbors`/`find_path`/`get_subgraph`.
- **Primitive endpoints + exact request fields** (`api/routers.py`, `api/schemas.py`, `api/responses.py`):
  - `GET /schema` → `{entity_types[], relation_types[], embedding_info{model, dimension}}`
  - `POST /entities/find` → body `{keywords[] (1-32), types?, limit (1-50, default 10), include_scores (default false), namespace_id?}`; response `{matches[]{node, score, matched_keyword, scores?{lexical,dense}}}`
  - `GET /entities/{entity_id}` → `{node, edge_counts{outgoing{}, incoming{}}}`
  - `POST /entities/{entity_id}/neighbors` → body `{id?, relation_types?, direction (outgoing|incoming|both, default both), hops (1-5, default 1), max_nodes (1-500, default 100), namespace_id?}`; response `{nodes[], edges[], truncated}`
  - `POST /paths/find` → body `{from_id, to_id, max_hops (1-6, default 4), max_paths (1-20, default 5), relation_types?, namespace_id?}`; response `{paths[]{nodes, edges, length, hub_score}}`
  - `POST /subgraph` → body `{entry_ids[] (1-20), hops (1-4, default 2), max_nodes (1-5000, default 200), relation_types?, namespace_id?}`; response `{nodes[], edges[], entry_ids[], truncated}`
  - `GET /healthz` → `{status, neo4j}`
  - `POST /admin/ingest` → 202 `{task_id, status_url}`; body `{directory_path, dry_run (default false), namespace_id?}`
  - `GET /admin/ingest/{task_id}/status` → `{task_id, state, progress{...}, metrics{...}, error?}`
  - `GET /admin/namespaces` → `{namespaces[]{namespace_id, entity_count}}`
- **Node shape** (`domain/models.py` `Node`): `id, name, type, aliases[], description?, properties{}, source_refs[]{source_path, chunk_index?, total_chunks?}, created_at, updated_at`. `Edge` adds `from` (serialized as `from`, not `from_`), `to`. Node never exposes `embedding`.
- **namespace**: `Authorization: Bearer ns:<name>`; resolution order is **body `namespace_id` > auth header > `"default"`** for body-bearing endpoints; header-only for `get_schema`/`get_entity` (`api/auth.py`, `api/routers.py`). Missing header → `default`. Cross-namespace id lookup returns 404.
- **reviewable ingest** order ↔ `skills/reviewable-ingest/SKILL.md`: `ingest_plan` → `ingest_preview` → (`ingest_resolve` if questions) → confirm → `ingest_commit`. Hints steer extraction only; source file is never rewritten.
- **model providers** (`adapters/providers.py`): LLM `{openai, anthropic, claude-code}`, embedding `{openai, voyage}`. Selected by the `provider/` prefix of `ARCHE_API_LLM_MODEL` / `ARCHE_API_EMBEDDING_MODEL`. `claude-code` uses local Claude Code subscription auth — no API key. Non-default provider SDKs are lazy-imported and require `uv sync --extra providers`.
- **error code catalog** (`api/error_codes.py`): closed enum with HTTP mapping — `invalid_input` (422), `entity_not_found` (404), `task_not_found` (404), `not_authorized` (401), `permission_denied` (403), `rate_limited` (429), `conflict` (409), `directory_not_found` (422), `not_a_directory` (422), `dependency_unavailable` (503), `extraction_failed` (500), `internal_error` (500), `timeout` (504). Validation errors flatten to `details.errors[]{loc, type, msg}` (`flatten_validation_errors`).
- **config defaults** (`config.py`): `ARCHE_API_LLM_MODEL=openai/gpt-4.1`, `ARCHE_API_EMBEDDING_MODEL=openai/text-embedding-3-small`, `ARCHE_API_EMBEDDING_DIMENSION=1536`, `NEO4J_URI=bolt://localhost:7687`, `NEO4J_USER=neo4j`, `NEO4J_PASSWORD=arche`. Keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`.

### 6.1 Known contradiction to resolve before writing (search scoring)

`STATUS.md` claims hybrid search (lexical + dense, RRF k=60) is complete, but `api/schemas.py` comments describe a walking skeleton that is **lexical-only** (`dense` forced to `0.0`, `score` = max-normalized fulltext). These conflict. The implementer MUST confirm the live behavior (run the server, or read the current `services.find_entities` implementation) before describing `find_entities` scoring. Do not copy either source verbatim. If unverifiable in this environment, describe the response *shape* (the `scores{lexical, dense}` fields exist) and add a `::: warning` that the fusion/scoring detail should be checked against the running version, rather than asserting a specific algorithm.

## 7. Tone

Korean prose follows the humanizer principles (comma restraint, no translation-ese, varied rhythm). Asides use VitePress callout containers (`::: tip`, `::: warning`, `::: details`). Every page must be approachable to a first-time reader. Apply the `/humanizer` pass to each page's prose before considering it done.

## 8. Verification

- `pnpm build` succeeds with no dead links (VitePress treats dead internal links as build errors) — primary automated gate, run after every content task.
- Each curl example's endpoint, request fields, and response shape cross-checked against the source files named in §6 (mandatory). Where a live server is available (docker compose + Neo4j + API key), capture real responses; otherwise render response examples from the Pydantic models in §6 and mark any runtime-dependent value (e.g. fusion score) per §6.1.
- Pure docs / new-directory work; no impact on Python tests — confirm existing pytest stays green, no new failures introduced.
- README entry-point table links to the new site.

## 9. Risks / trade-offs

- Introduces a Node/pnpm toolchain into a previously Python-only repo. Mitigated by full ecosystem separation and devDependency-only footprint.
- Scope grows well beyond the original single-file issue (the user explicitly asked for a rich, lookup-friendly site). Mitigated by deferring deployment and English, and by grounding every factual page in named source files so breadth does not cost accuracy.
- Docs can drift from code. Mitigated by §6 source citations per claim and the §6.1 verification gate for the one known contradiction.
