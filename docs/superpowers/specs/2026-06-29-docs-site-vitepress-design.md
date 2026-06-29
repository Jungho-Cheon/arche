# Design — User-facing documentation site (VitePress)

> 한국어 요약: 이슈 #100의 사용 가이드를 단일 `docs/guide.md` 대신 VitePress 정적 사이트(`apps/docs`)로 만든다. 랜딩에서 가치 제안을 두괄식으로 보여주고, 과제 중심 가이드 5장 + 흐름을 끊는 깊은 설명을 담는 개념 페이지로 나눈다. pnpm 전용, 로컬 빌드까지만(배포는 별도 이슈). 영어 추가를 대비해 VitePress i18n 구조를 처음부터 깔되 콘텐츠는 한국어만. 모든 curl 예시는 실제 코드와 대조해 정확성을 보장한다.

- Date: 2026-06-29
- Issue: #100 (사용자 사용 가이드 문서)
- Status: design approved, pending spec review

## 1. Goal

Give a newcomer a single place that (a) explains what Arche does and why, leading with capability and value, and (b) walks them end-to-end through real usage: install → ingest (text/PDF/images) → query → team isolation (namespace) → model swap.

This supersedes the original single-file `docs/guide.md` scope from issue #100 with a small static documentation site, because the content benefits from task-oriented navigation, callouts, and separate concept pages for deep explanations that would otherwise break reading flow.

## 2. Scope

In scope:
- New `apps/docs` VitePress site (Korean only).
- Landing page with value proposition (capability-first), guide chapters, separate concept pages.
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
    getting-started.md        # docker compose, .env (OPENAI_API_KEY), first ingest
    ingest.md                 # text/PDF/image ingest; quick vs reviewable ingest; hints
    query.md                  # 6 primitives, each with real curl + response; multi-hop composition
    namespace.md              # Bearer ns:<name>, isolation scope, default fallback, partial-share not supported
    models.md                 # provider prefixes (openai/ anthropic/ claude-code/ voyage/) + required keys
  concepts/
    why-graph.md              # why a graph KB (agent token/latency value)
    primitives.md             # conceptual overview of the 6 primitives
    namespace-model.md        # deep explanation of namespace isolation model
```

Navigation principle: the `guide/` chapters stay task-oriented and unbroken. Any explanation that interrupts the doing-flow moves to a `concepts/` page and is referenced via callout/link from the guide.

## 4. Toolchain & repo integration

- Package manager: **pnpm** (repo convention for `apps/` frontends). Add `pnpm-workspace.yaml` at root listing `apps/docs`.
- Dependency: `vitepress` only (Vue bundled), devDependency. Static build, no runtime server.
- Scripts: `pnpm dev` (preview server), `pnpm build` (static output to `.vitepress/dist`), `pnpm preview`.
- `.gitignore`: add `apps/docs/node_modules`, `apps/docs/.vitepress/dist`, `apps/docs/.vitepress/cache`.
- Python `uv` toolchain untouched; the two ecosystems are fully separate.

## 5. i18n readiness (Korean now, English later)

- `.vitepress/config.ts` uses the `locales` structure from the start: Korean as root (`/`), English slot (`/en/`) present but commented out.
- Korean content lives at the root (`guide/`, `concepts/`). Adding English later means creating `en/guide/` mirrors and uncommenting the `locales.en` block — existing Korean paths do not move.
- Sidebar and nav authored so per-locale variants are a config edit, not a content reshuffle.

## 6. Content accuracy (issue #100 completion criteria)

Every code-touching claim is verified against source before writing:
- curl endpoints, request fields, response shapes ↔ `apps/api` `routers.py`, `schemas.py`, `responses.py`, `domain/models.py`.
- namespace: `Authorization: Bearer ns:<name>` + body override + default fallback, per code.
- reviewable ingest flow ↔ `skills/reviewable-ingest/SKILL.md` order (plan → preview → resolve → commit).
- model provider prefixes ↔ `apps/api/adapters`.

## 7. Tone

Korean prose follows the humanizer principles (comma restraint, no translation-ese, varied rhythm). Asides use VitePress callout containers (`::: tip`, `::: warning`, `::: details`). Every page must be approachable to a first-time reader.

## 8. Verification

- `pnpm build` succeeds with no dead links (VitePress treats dead internal links as build errors) — primary pass gate.
- Pure docs / new-directory work; no impact on Python tests — confirm existing pytest stays green, no new failures introduced.
- README entry-point table links to the new site.

## 9. Risks / trade-offs

- Introduces a Node/pnpm toolchain into a previously Python-only repo. Mitigated by full ecosystem separation and devDependency-only footprint.
- Scope grows beyond the original single-file issue. Mitigated by deferring deployment and English to later, keeping initial content to the five guide chapters + landing + three concept pages.
