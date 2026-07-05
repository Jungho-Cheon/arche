# Arche Documentation Site (VitePress) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a rich Korean documentation site under `apps/docs` (VitePress) that leads with Arche's value, walks a newcomer end-to-end (install → ingest → query → namespace → model swap), and offers concept + reference sections for lookup — all curl examples grounded in actual `apps/api` code.

**Architecture:** A standalone VitePress static site in `apps/docs`, wired into a new root pnpm workspace, fully separate from the Python `uv` toolchain. Content is split into three trees — task-oriented `guide/`, conceptual `concepts/`, lookup `reference/` — with an i18n-ready config (Korean at root, English slot pre-stubbed but commented). Build green (no dead links) is the automated gate; per-claim source citations are the accuracy gate.

**Tech Stack:** VitePress 1.x (Vue/Vite, bundled), pnpm, Node 18+, Markdown.

## Global Constraints

- Korean content only. English is config scaffolding (commented `locales.en` block); do not write English pages.
- Package manager is **pnpm** only. Never run `npm`/`yarn` in `apps/docs`.
- Dependency footprint: `vitepress` as the only devDependency. No theme plugins, no extra libraries.
- Local build only. Do NOT add deployment, GitHub Pages, or CI config.
- Do NOT modify any file under `apps/api` (Python). This is a docs-only change.
- Every response envelope in examples is `{"data": <payload>}`; every error is `{"error": {"code", "message", "details"}}`.
- All entity/edge IDs are ULID (26-char, `^[0-9A-Z]{26}$`). In examples use a realistic placeholder like `01J8XR4K9ZQ2N7M3VB0W4D6TYE`.
- namespace resolution order on body-bearing endpoints: **body `namespace_id` > `Authorization: Bearer ns:<name>` header > `"default"`**.
- Tone: apply `/humanizer` principles to every page's prose (comma restraint, no translation-ese, varied rhythm). Use `::: tip` / `::: warning` / `::: details` callouts for asides instead of inlining them.
- After every content task, `pnpm --dir apps/docs build` must succeed with zero dead links before commit.

---

### Task 1: Scaffold pnpm workspace + VitePress app with stub pages

**Files:**
- Create: `pnpm-workspace.yaml`
- Create: `apps/docs/package.json`
- Create: `apps/docs/.vitepress/config.ts`
- Create: `apps/docs/index.md` (stub)
- Create: `apps/docs/guide/{getting-started,ingest,query,namespace,models}.md` (stubs)
- Create: `apps/docs/concepts/{why-graph,namespace-model,path-quality}.md` (stubs)
- Create: `apps/docs/reference/{primitives,errors,configuration}.md` (stubs)
- Modify: `.gitignore` (append docs build artifacts)

**Interfaces:**
- Produces: a buildable VitePress site whose sidebar/nav reference every page path below. Later tasks only fill page bodies; they do not touch `config.ts` except Task 10 (README link is outside config).

- [ ] **Step 1: Create the root workspace file**

`pnpm-workspace.yaml`:
```yaml
packages:
  - "apps/docs"
```

- [ ] **Step 2: Create `apps/docs/package.json`**

```json
{
  "name": "@arche/docs",
  "version": "0.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vitepress dev",
    "build": "vitepress build",
    "preview": "vitepress preview"
  },
  "devDependencies": {
    "vitepress": "^1"
  }
}
```

- [ ] **Step 3: Install (resolves the exact vitepress 1.x version into a lockfile)**

Run: `pnpm --dir apps/docs install`
Expected: creates `apps/docs/node_modules` and a `pnpm-lock.yaml` at repo root. No errors.

- [ ] **Step 4: Create `apps/docs/.vitepress/config.ts`**

```ts
import { defineConfig } from "vitepress";

// 한국어를 루트(/)에 둔다. 영어는 나중에 locales.en 주석을 풀고 en/ 미러를 추가하면 된다.
export default defineConfig({
  title: "Arche",
  description:
    "흩어진 문서를 관계 그래프로 바꿔, AI 에이전트가 적은 비용으로 정확히 답하게 하는 지식 베이스 도구",
  lang: "ko-KR",
  cleanUrls: true,
  lastUpdated: true,
  themeConfig: {
    socialLinks: [
      { icon: "github", link: "https://github.com/Jungho-Cheon/arche" },
    ],
  },
  locales: {
    root: {
      label: "한국어",
      lang: "ko-KR",
      themeConfig: {
        nav: [
          { text: "가이드", link: "/guide/getting-started" },
          { text: "개념", link: "/concepts/why-graph" },
          { text: "레퍼런스", link: "/reference/primitives" },
        ],
        sidebar: {
          "/guide/": [
            {
              text: "사용 가이드",
              items: [
                { text: "시작하기", link: "/guide/getting-started" },
                { text: "문서를 그래프에 넣기", link: "/guide/ingest" },
                { text: "그래프에 질의하기", link: "/guide/query" },
                { text: "팀별 지식 격리 (namespace)", link: "/guide/namespace" },
                { text: "모델 갈아끼우기", link: "/guide/models" },
              ],
            },
          ],
          "/concepts/": [
            {
              text: "개념",
              items: [
                { text: "왜 그래프인가", link: "/concepts/why-graph" },
                { text: "namespace 격리 모델", link: "/concepts/namespace-model" },
                { text: "경로 품질과 hub_score", link: "/concepts/path-quality" },
              ],
            },
          ],
          "/reference/": [
            {
              text: "레퍼런스",
              items: [
                { text: "그래프 프리미티브", link: "/reference/primitives" },
                { text: "에러 코드", link: "/reference/errors" },
                { text: "환경 변수", link: "/reference/configuration" },
              ],
            },
          ],
        },
      },
    },
    // 영어 추가 시: 아래 블록 주석을 풀고 en/ 아래에 미러 페이지를 만든다.
    // en: {
    //   label: "English",
    //   lang: "en-US",
    //   link: "/en/",
    //   themeConfig: { nav: [], sidebar: {} },
    // },
  },
});
```

- [ ] **Step 5: Create every page as a minimal stub so the build has no dead links**

Each stub file is frontmatter-free except the landing. Use exactly this body, substituting the title per file:

`apps/docs/index.md`:
```markdown
---
layout: home
hero:
  name: Arche
  text: 문서를 관계 그래프로
  tagline: 작성 예정
---
```

Every other stub (example for `apps/docs/guide/getting-started.md`, repeat with the matching H1 for each path):
```markdown
# 시작하기

작성 예정.
```
H1 per stub: getting-started → "시작하기", ingest → "문서를 그래프에 넣기", query → "그래프에 질의하기", namespace → "팀별 지식 격리 (namespace)", models → "모델 갈아끼우기", why-graph → "왜 그래프인가", namespace-model → "namespace 격리 모델", path-quality → "경로 품질과 hub_score", primitives → "그래프 프리미티브", errors → "에러 코드", configuration → "환경 변수".

- [ ] **Step 6: Append docs build artifacts to `.gitignore`**

Add these lines to the repo-root `.gitignore`:
```
# VitePress docs site
apps/docs/node_modules
apps/docs/.vitepress/dist
apps/docs/.vitepress/cache
```

- [ ] **Step 7: Verify the site builds with no dead links**

Run: `pnpm --dir apps/docs build`
Expected: "build complete" with no "dead link" errors. A `apps/docs/.vitepress/dist` directory is produced (and is gitignored).

- [ ] **Step 8: Commit**

```bash
git add pnpm-workspace.yaml pnpm-lock.yaml apps/docs/package.json apps/docs/.vitepress/config.ts apps/docs/index.md apps/docs/guide apps/docs/concepts apps/docs/reference .gitignore
git commit -m "docs(site): VitePress 스캐폴드 + 스텁 페이지 (#100)"
```

---

### Task 2: Landing page (`apps/docs/index.md`)

**Files:**
- Modify: `apps/docs/index.md`

**Content spec** (lead with capability, then the idea, then value — 두괄식):
- VitePress `home` layout `hero` with `name: Arche`, a one-line `text` capability statement, a `tagline`, and `actions` (primary → `/guide/getting-started`, secondary → `/concepts/why-graph`).
- `features` list (3 cards): "문서를 관계 그래프로 적재", "6개 그래프 프리미티브로 질의 (REST + MCP)", "어떤 AI 모델이든 갈아끼움".
- Below the hero, a short prose section grounded in `README.md`'s "왜 Arche 인가" + "검증된 가치": the two-weakness framing (full-context = 비싸고 느림, chunk RAG = 관계를 못 이음) and the FinanceBench result (graph-only **94-97%** vs chunk 도구 **57.6%**, ADR-0016). Keep the honest-limitation note: 절대값은 도메인마다 다르고 변하지 않는 것은 순위.
- Link out to `docs/overview.md` (repo) for the non-technical introduction and to the guide for hands-on.

**Source to ground against:** `README.md` (왜/검증된 가치 sections), `docs/adr/0016-agentic-graphonly-and-quantitative-extraction.md`.

- [ ] **Step 1: Write the landing content** per the spec above using the VitePress home-layout frontmatter (`hero`, `features`) plus a prose block.
- [ ] **Step 2: Apply `/humanizer`** to the prose block.
- [ ] **Step 3: Build & dead-link check** — `pnpm --dir apps/docs build` → success.
- [ ] **Step 4: Commit** — `git add apps/docs/index.md && git commit -m "docs(site): 랜딩 가치 제안 (#100)"`

---

### Task 3: Getting started (`apps/docs/guide/getting-started.md`)

**Files:**
- Modify: `apps/docs/guide/getting-started.md`

**Content spec** (mirror and expand `README.md` "직접 해보기", verified against `config.py` + `docker-compose.yml`):
- Prerequisites callout: Docker + one AI model API key. Default uses a single `OPENAI_API_KEY` for both extraction and embedding.
- Step 1 — clone, `cp .env.example .env`, fill `OPENAI_API_KEY`.
- Step 2 — `docker compose up -d`; note API at `http://localhost:8000/docs` (Swagger), Neo4j browser at `http://localhost:7474` (user `neo4j`, password from `.env` `NEO4J_PASSWORD`, default `arche`).
- Step 3 — liveness check:
  ```bash
  curl http://localhost:8000/healthz
  # {"status":"ok","neo4j":"ok"}
  ```
  `::: tip` explaining `neo4j` can read `"down"` if the DB is still starting.
- Step 4 — first ingest of a small folder:
  ```bash
  uv run --project apps/api arche ingest ./내문서폴더
  ```
- Step 5 — pointer to the three next chapters (ingest / query / namespace) with links.

**Source to ground against:** `README.md`, `docker-compose.yml`, `config.py` (`NEO4J_PASSWORD` default `arche`), `api/routers.py` (`/healthz` → `HealthzResponse{status, neo4j}`).

- [ ] **Step 1: Write the chapter** per spec, with real commands and the `/healthz` response shape exactly as `HealthzResponse`.
- [ ] **Step 2: Apply `/humanizer`** to prose.
- [ ] **Step 3: Build & dead-link check** — `pnpm --dir apps/docs build` → success.
- [ ] **Step 4: Commit** — `git commit -m "docs(site): 시작하기 (#100)"`

---

### Task 4: Ingest (`apps/docs/guide/ingest.md`)

**Files:**
- Modify: `apps/docs/guide/ingest.md`

**Content spec** — three ways to ingest, each with when-to-use:
1. **CLI quick ingest** (single dev, local files): `uv run --project apps/api arche ingest <dir>`. Mention it accepts a directory or a single file; supports `.txt`/`.md`, PDF (page text + embedded images), and single image files (multimodal). Per-file failure isolation.
2. **REST async ingest** (HTTP, watch progress):
   ```bash
   curl -X POST http://localhost:8000/admin/ingest \
     -H "Content-Type: application/json" \
     -d '{"directory_path": "/abs/path/to/docs", "dry_run": false}'
   # 202 {"data":{"task_id":"...","status_url":"/admin/ingest/<task_id>/status"}}
   ```
   then poll:
   ```bash
   curl http://localhost:8000/admin/ingest/<task_id>/status
   # {"data":{"task_id":"...","state":"running","progress":{"files_total":..,"files_processed":..,"files_skipped":..,"files_pending_skipped":..,"files_unsupported_skipped":..},"metrics":{"entities_created":..,"entities_updated":..,"relations_created":..,"relations_skipped_dangling":..,"chunks_total":..},"error":null}}
   ```
   `::: tip` on `dry_run: true` — extracts without writing to the graph (preview cost/shape).
   `::: warning` — `directory_path` must be an absolute path that exists, else `422` with `directory_not_found` / `not_a_directory` (link to `/reference/errors`).
3. **Reviewable ingest via an agent (MCP)** — for when a human should approve the delta. Order exactly per `skills/reviewable-ingest/SKILL.md`: `ingest_plan` → `ingest_preview` → (`ingest_resolve` if the preview carries `questions`) → confirm → `ingest_commit`. Explain `questions` = near-duplicate entities needing a same/new decision.
- **Hints** subsection: if a preview looks sparse for a content-rich doc, pass `hints` (glossary, abbreviations, "treat each row as a fact") to `ingest_plan` and restart. `::: warning` — hints steer extraction only; the source file and stored original are never rewritten.

**Source to ground against:** `README.md`, `api/routers.py` (`admin_ingest`, `admin_ingest_status`), `api/schemas.py` (`AdminIngestRequest`, `AdminIngestResponse`, `AdminIngestProgress`, `AdminIngestMetrics`), `skills/reviewable-ingest/SKILL.md`, `cli.py` (ingest command).

- [ ] **Step 1: Confirm CLI flags & supported file types** by reading `apps/api/src/arche_api/cli.py` and the ingest domain; adjust the CLI subsection to match actual flags.
- [ ] **Step 2: Write the chapter** per spec with the exact 202 + status envelopes above.
- [ ] **Step 3: Apply `/humanizer`** to prose.
- [ ] **Step 4: Build & dead-link check** — success.
- [ ] **Step 5: Commit** — `git commit -m "docs(site): 적재 가이드 (CLI/REST/검토형) (#100)"`

---

### Task 5: Query (`apps/docs/guide/query.md`)

**Files:**
- Modify: `apps/docs/guide/query.md`

**Content spec** — the core hands-on chapter:
- **응답 봉투** intro: every success is `{"data": ...}`, every error is `{"error": {...}}` (link to `/reference/errors`). Show it once up front.
- **엔티티 ID 얻기**: IDs are ULID. You almost always start with `find_entities` to turn keywords into IDs, then feed an ID to the other primitives. Make this the spine of the chapter.
- The 6 primitives, each: one-line purpose, a real curl, and a trimmed response. Use base `http://localhost:8000` and the placeholder ULID `01J8XR4K9ZQ2N7M3VB0W4D6TYE`.

  - `get_schema` — graph shape:
    ```bash
    curl http://localhost:8000/schema
    # {"data":{"entity_types":[{"type":"Policy","count":12,"examples":[{"id":"01J...","name":"환불 정책"}]}],"relation_types":[{"type":"APPLIES_TO","count":8,"common_pairs":[{"from_type":"Policy","to_type":"Product","count":5}]}],"embedding_info":{"model":"text-embedding-3-small","dimension":1536}}}
    ```
  - `find_entities` — keywords → matches (note field is `keywords`, a list; `limit` not `top_k`):
    ```bash
    curl -X POST http://localhost:8000/entities/find \
      -H "Content-Type: application/json" \
      -d '{"keywords": ["환불", "정책"], "limit": 5}'
    # {"data":{"matches":[{"node":{"id":"01J8XR4K9ZQ2N7M3VB0W4D6TYE","name":"환불 정책","type":"Policy","aliases":[],"properties":{},"source_refs":[{"source_path":"policies/refund.md"}],"created_at":"2026-06-29T10:00:00Z","updated_at":"2026-06-29T10:00:00Z"},"score":1.0,"matched_keyword":"환불"}]}}
    ```
    `::: tip` on `include_scores: true` returning raw `scores: {lexical, dense}` per match for custom re-rank/debugging.
  - `get_entity` — one node + edge type counts:
    ```bash
    curl http://localhost:8000/entities/01J8XR4K9ZQ2N7M3VB0W4D6TYE
    # {"data":{"node":{...},"edge_counts":{"outgoing":{"APPLIES_TO":3},"incoming":{"REFERS_TO":1}}}}
    ```
  - `get_neighbors` — N-hop neighbors (POST, body fields `hops`/`direction`/`max_nodes`):
    ```bash
    curl -X POST http://localhost:8000/entities/01J8XR4K9ZQ2N7M3VB0W4D6TYE/neighbors \
      -H "Content-Type: application/json" \
      -d '{"hops": 1, "direction": "both", "max_nodes": 50}'
    # {"data":{"nodes":[...],"edges":[...],"truncated":false}}
    ```
  - `find_path` — k-shortest paths between two IDs (`from_id`/`to_id`):
    ```bash
    curl -X POST http://localhost:8000/paths/find \
      -H "Content-Type: application/json" \
      -d '{"from_id": "01J8XR4K9ZQ2N7M3VB0W4D6TYE", "to_id": "01J8YS5M0AB3P8N4WC1XE7FZGH", "max_hops": 4}'
    # {"data":{"paths":[{"nodes":[...],"edges":[...],"length":2,"hub_score":0.0}]}}
    ```
    `::: tip` linking to `/concepts/path-quality` for what `hub_score` means and when to distrust a path.
  - `get_subgraph` — union N-hop from multiple entry points (`entry_ids`):
    ```bash
    curl -X POST http://localhost:8000/subgraph \
      -H "Content-Type: application/json" \
      -d '{"entry_ids": ["01J8XR4K9ZQ2N7M3VB0W4D6TYE"], "hops": 2, "max_nodes": 200}'
    # {"data":{"nodes":[...],"edges":[...],"entry_ids":["01J8XR4K9ZQ2N7M3VB0W4D6TYE"],"truncated":false}}
    ```
- **Multi-hop 조합 패턴**: a worked example answering a cross-document question by chaining `find_entities` → `find_path` (or `get_neighbors`/`get_subgraph`) → reading the returned nodes/edges. Emphasize the agent composes primitives; Arche returns atomic results.
- Pointer: full field reference in `/reference/primitives`.

**Source to ground against:** `api/routers.py`, `api/schemas.py` (`FindEntitiesRequest/Response`, `MatchScores`), `api/responses.py` (all primitive request/response models), `domain/models.py` (`Node`/`Edge`/`SourceRef` shape — Node has no `embedding`; Edge serializes `from`/`to`).

- [ ] **Step 1: Resolve the search-scoring contradiction (spec §6.1)** — read `api/services.py` `find_entities` (and run the server if available) to confirm whether scoring is hybrid (lexical+dense RRF) or lexical-only. Write the `find_entities` description to match reality; if unverifiable, describe only the response *shape* and add a `::: warning` to check fusion detail against the running version. Do not assert an algorithm you did not verify.
- [ ] **Step 2: Write the chapter** with all six curl blocks and response shapes exactly matching the Pydantic models.
- [ ] **Step 3: Apply `/humanizer`** to prose.
- [ ] **Step 4: Build & dead-link check** — success (the `/concepts/path-quality` and `/reference/*` links resolve to Task 1 stubs).
- [ ] **Step 5: Commit** — `git commit -m "docs(site): 질의 가이드 (6 프리미티브 + multi-hop) (#100)"`

---

### Task 6: Namespace (`apps/docs/guide/namespace.md`)

**Files:**
- Modify: `apps/docs/guide/namespace.md`

**Content spec:**
- What a namespace is (one line): a logical partition so multiple teams' knowledge can share one graph without leaking across.
- How to set it: `Authorization: Bearer ns:<name>` header. Show an ingest and a query with the header:
  ```bash
  curl -X POST http://localhost:8000/entities/find \
    -H "Authorization: Bearer ns:work-a" \
    -H "Content-Type: application/json" \
    -d '{"keywords": ["환불"]}'
  ```
- Resolution order (`::: tip`): body `namespace_id` > `Bearer ns:` header > `"default"`. No header → everything goes to `default`.
- Isolation scope: ingest writes, identity matching/merge, and all read primitives are scoped to the namespace (issues #92/#94/#98). Cross-namespace ID lookup returns `404` (no leak via guessing IDs).
- Visibility: list namespaces and their entity counts:
  ```bash
  curl http://localhost:8000/admin/namespaces
  # {"data":{"namespaces":[{"namespace_id":"work-a","entity_count":128},{"namespace_id":"default","entity_count":12}]}}
  ```
- `::: warning` Not yet supported: partial sharing (one query seeing several namespaces at once). A namespace is a hard boundary today. Link to `/concepts/namespace-model` for the model.

**Source to ground against:** `api/auth.py` (`Bearer ns:` parsing, `DEFAULT_NAMESPACE`), `api/routers.py` (`body.namespace_id or auth.namespace_id`; `get_entity` 404 cross-namespace), `api/schemas.py` (`AdminNamespacesResponse`, `NamespaceSummary`), ADR-0015.

- [ ] **Step 1: Write the chapter** per spec.
- [ ] **Step 2: Apply `/humanizer`** to prose.
- [ ] **Step 3: Build & dead-link check** — success.
- [ ] **Step 4: Commit** — `git commit -m "docs(site): namespace 가이드 (#100)"`

---

### Task 7: Models (`apps/docs/guide/models.md`)

**Files:**
- Modify: `apps/docs/guide/models.md`

**Content spec:**
- The idea: pick a provider by the `provider/model` prefix of two env vars — `ARCHE_API_LLM_MODEL` (extraction) and `ARCHE_API_EMBEDDING_MODEL` (embedding). The factory routes on the prefix (ADR-0019).
- Supported prefixes table:
  - LLM: `openai/` (needs `OPENAI_API_KEY`), `anthropic/` (needs `ANTHROPIC_API_KEY`), `claude-code/` (no key — uses local Claude Code subscription auth).
  - Embedding: `openai/` (needs `OPENAI_API_KEY`), `voyage/` (needs `VOYAGE_API_KEY`).
- Defaults: `openai/gpt-4.1` + `openai/text-embedding-3-small` (dim 1536).
- Example `.env` swap to Claude + Voyage:
  ```bash
  ARCHE_API_LLM_MODEL=anthropic/claude-sonnet-4-6
  ARCHE_API_EMBEDDING_MODEL=voyage/voyage-3
  ANTHROPIC_API_KEY=...
  VOYAGE_API_KEY=...
  ```
- `::: warning` Two gotchas: (1) non-default provider SDKs are lazy-imported — install them with `uv sync --extra providers` before selecting that provider, or you get an import error at call time. (2) Changing the embedding model changes the vector dimension — set `ARCHE_API_EMBEDDING_DIMENSION` to match and rebuild the index (link to `/reference/configuration`).

**Source to ground against:** `adapters/providers.py` (`_LLM_BUILDERS`, `_EMBED_BUILDERS`, lazy-import note, `claude-code` no-key), `config.py` (defaults, `EMBEDDING_DIMENSION`, env aliases), ADR-0019.

- [ ] **Step 1: Confirm a current Anthropic/Voyage model id** to use in the example (read `adapters/llm.py` / `adapters/embedding.py` or `.env.example`); use a real, current identifier.
- [ ] **Step 2: Write the chapter** per spec with the provider/key table.
- [ ] **Step 3: Apply `/humanizer`** to prose.
- [ ] **Step 4: Build & dead-link check** — success.
- [ ] **Step 5: Commit** — `git commit -m "docs(site): 모델 교체 가이드 (#100)"`

---

### Task 8: Concept pages (`apps/docs/concepts/*`)

**Files:**
- Modify: `apps/docs/concepts/why-graph.md`
- Modify: `apps/docs/concepts/namespace-model.md`
- Modify: `apps/docs/concepts/path-quality.md`

**Content spec:**
- `why-graph.md` — why a graph KB beats full-context and chunk RAG for cross-document, relational, table-numeric questions; the "extraction completeness is the lever, not model size" point. Ground in `README.md` + ADR-0016. Keep it conceptual (no curl).
- `namespace-model.md` — the isolation model in depth: namespace as a property on every node, write/match/read all scoped, `default` for legacy/no-header, cross-namespace sharing as an explicit future opt-in (not built). Ground in ADR-0015 + `domain/models.py` `StoredEntity.namespace_id`.
- `path-quality.md` — `hub_score`: each `find_path` segment carries `hub_score` = sum of `log(1+degree)` over *intermediate* nodes (endpoints excluded). `0.0` = most specific (unique intermediates or a direct 1-hop). Higher = the path bridges through a promiscuous hub (a shared/extraction-artifact node touching many entities), so the connection may be "reachable but weak". Among same-length paths the adapter returns lower `hub_score` first; a consuming agent should distrust a high-`hub_score` path before citing it. Ground in `api/responses.py:181-187` (`PathSegment.hub_score`) + ADR-0017.

**Source to ground against:** `README.md`, ADR-0015, ADR-0016, ADR-0017, `api/responses.py`, `domain/models.py`.

- [ ] **Step 1: Write `why-graph.md`** per spec.
- [ ] **Step 2: Write `namespace-model.md`** per spec.
- [ ] **Step 3: Write `path-quality.md`** per spec.
- [ ] **Step 4: Apply `/humanizer`** to all three.
- [ ] **Step 5: Build & dead-link check** — success.
- [ ] **Step 6: Commit** — `git commit -m "docs(site): 개념 페이지 (그래프/namespace/경로품질) (#100)"`

---

### Task 9: Reference pages (`apps/docs/reference/*`)

**Files:**
- Modify: `apps/docs/reference/primitives.md`
- Modify: `apps/docs/reference/errors.md`
- Modify: `apps/docs/reference/configuration.md`

**Content spec:**
- `primitives.md` — a lookup table per primitive: method + path, request fields (name, type, default, range), and response shape. Cover all of `get_schema`, `find_entities`, `get_entity`, `get_neighbors`, `find_path`, `get_subgraph`, plus `healthz`, `admin/ingest`, `admin/ingest/{id}/status`, `admin/namespaces`. Use the exact fields and ranges from spec §6 (e.g. `find_entities.limit` 1-50 default 10; `get_neighbors.hops` 1-5 default 1; `find_path.max_hops` 1-6 default 4; `get_subgraph.entry_ids` 1-20, `max_nodes` 1-5000 default 200). Note REST envelope `{data:...}` and MCP returns the same payload unwrapped.
- `errors.md` — the error envelope `{"error":{"code","message","details"}}` and the full closed code catalog with HTTP status from `api/error_codes.py`: `invalid_input` 422, `entity_not_found` 404, `task_not_found` 404, `not_authorized` 401, `permission_denied` 403, `rate_limited` 429, `conflict` 409, `directory_not_found` 422, `not_a_directory` 422, `dependency_unavailable` 503, `extraction_failed` 500, `internal_error` 500, `timeout` 504. Explain validation errors flatten to `details.errors[]{loc, type, msg}`. Show one example error body.
- `configuration.md` — env var table from `config.py`: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `ARCHE_API_LLM_MODEL` (default `openai/gpt-4.1`), `ARCHE_API_EMBEDDING_MODEL` (default `openai/text-embedding-3-small`), `ARCHE_API_EMBEDDING_DIMENSION` (1536), `ARCHE_API_LLM_MODEL_CONTEXT_TOKENS` (128000), `NEO4J_URI` (`bolt://localhost:7687`), `NEO4J_USER` (`neo4j`), `NEO4J_PASSWORD` (`arche`). For each: purpose + default.

**Source to ground against:** `api/responses.py`, `api/schemas.py`, `api/routers.py`, `api/error_codes.py`, `config.py`, `.env.example`.

- [ ] **Step 1: Write `primitives.md`** lookup tables per spec.
- [ ] **Step 2: Write `errors.md`** per spec.
- [ ] **Step 3: Write `configuration.md`** per spec (cross-check defaults against `.env.example`).
- [ ] **Step 4: Apply `/humanizer`** to any prose (tables stay terse).
- [ ] **Step 5: Build & dead-link check** — success.
- [ ] **Step 6: Commit** — `git commit -m "docs(site): 레퍼런스 (프리미티브/에러/환경변수) (#100)"`

---

### Task 10: README link + final verification

**Files:**
- Modify: `README.md` (entry-point links near the top)

**Content spec:** Add the docs site to README's top entry-point row (the `소개 • 직접 해보기 • 아키텍처 • 결정 기록` line) as a "사용 가이드" link pointing to `apps/docs/` (note: local site, run `pnpm --dir apps/docs dev`). Add one line in the README body pointing readers to the guide for the end-to-end walkthrough.

- [ ] **Step 1: Add the README entry-point link** to `apps/docs/` with a one-line "로컬에서 `pnpm --dir apps/docs dev` 로 띄운다" note.
- [ ] **Step 2: Full build** — `pnpm --dir apps/docs build` → success, zero dead links.
- [ ] **Step 3: Confirm Python tests untouched/green** — `cd apps/api && uv run pytest -q` → all pass (we changed no Python; this confirms no accidental breakage). Quote the summary line.
- [ ] **Step 4: Commit** — `git commit -m "docs(site): README 진입점에 사용 가이드 연결 (#100)"`
- [ ] **Step 5: Open PR** with `Closes #100`, using the `create-pr` skill template.

---

## Self-Review

**Spec coverage:** landing (Task 2), getting-started/ingest/query/namespace/models (Tasks 3-7), concepts incl. hub_score (Task 8), reference incl. errors+config (Task 9), README link (Task 10), pnpm+i18n scaffold (Task 1). All spec §3 pages and §6 facts have an owning task. The §6.1 search-scoring contradiction is owned by Task 5 Step 1.

**Placeholder scan:** stubs in Task 1 are intentional and replaced by Tasks 2-9; no "TBD" survives past its task. Curl bodies and response shapes are concrete.

**Type consistency:** field names (`keywords`, `limit`, `from_id`/`to_id`, `entry_ids`, `hops`, `max_nodes`, `direction`), envelope (`{data}`/`{error}`), and ULID pattern are used identically across query (Task 5), primitives reference (Task 9), and namespace (Task 6).
