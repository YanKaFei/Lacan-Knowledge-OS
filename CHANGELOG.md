# Changelog

All notable changes to the **product layer** are recorded here. The **scholarly core** is
versioned by *freeze segment* instead of releases — see `docs/ARCHITECTURE.md` and
`_scripts/_tools/freeze_lineage.py`. A semantic change is never a "fix"; it is a Core Change
Request recorded as a new lineage segment.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/), and this project
adheres to semantic versioning for the product layer.

---

## [1.0.0] — 2026-09-30

First public release: the engine edition (no corpus). Scope of this release.

### Added — product layer

- **Task-based home page.** Hero with two primary actions, six task cards, a six-step research
  workflow, and a five-minute quick start. Every entry is a *real link*
  (`/research`, `/explore`, `/projects`, `/bibliography`, `/persons`, `/cases`, `/zotero`, `/help/...`).
- **Help Center** at `/help` with 13 topics, sidebar table of contents, anchors,
  previous/next, "back to module", topic search, and instant language switching (no reload).
  Content lives in `_data/daily_use/help/help_content.json`; every cited control name is
  rendered from the real product dictionary, and every functional claim is machine-checked
  (`HELP_CLAIM_VERIFICATION.json`: 45/45 verified, 0 fiction, 0 pending).
- **In-product diagrams.** Three diagrams are drawn as **inline SVG** (`workspace_ui/static/src/diagrams.js`)
  rather than shipped images, so their labels follow the interface language instantly and their
  colours come from the same theme variables as the text: *one research task end to end* (home hero),
  *the system layers* (`/help`), and *the evidence chain* (`/help/evidence`). Machine tokens
  (passage ids, session ids, witness ids, API paths, state names) are marked
  `intentional_source_text` and are never translated.
- **Real product routes.** `/research`, `/explore`, `/projects`, `/bibliography`, `/persons`,
  `/cases`, `/zotero`, `/help`, `/help/<topic>` are served as SPA routes. Legacy `?view=…`
  deep links keep working; navigation items became genuine links.
- **Contextual help** in every module (`? Help` → the module's own Help page, never a generic one).
- **Teaching empty states** for projects, zero-result browse, history and bibliography:
  what this is, plus two real next actions.
- **Model provider settings** panel: model, base URL, credential *presence* (never the value),
  read-only call cap, and a real connection self-test.
- **Job-mode research** for long runs: submit returns immediately, the UI shows real elapsed
  time, and "stop waiting" is honest about the backend still running.
- **Measured provenance** on every answer: provider, model, wall-clock, cache hit, attempt count.
- **Bounded retry** for infrastructure failures only — never for scholarly verdicts.
- **Six-language documentation** (EN · ZH · FR · JA · DE · IT) with advantages/disadvantages stated.
- **DSH plugin packaging**: MCP server (10 tools), portable composition row, installable bundle,
  and an idempotent row installer.

### Added — engine and contracts

- **Frozen scholarly core v1** — 39 hash-pinned components (30 scholarly-semantic,
  3 product-boundary, 6 data-version) with a seven-segment lineage proving zero semantic drift.
- **Executable gates** (`daily_use_gate_v1/v2/v3`, 20/20 blocking items) plus the regression
  runner: 146 suites and 78 validators, `failed=[]` **and** `skipped=[]` required.
- **Corpus builders and validators** — inventory with source hashes, passage store, witnesses,
  lexical index, optional vector index, ontology resolvers, terminology bridge.
- **Public-edition builder** with negative verification (corpus N-gram probes, secret scan,
  absolute-path scan, size gates) — see `docs/PUBLIC_EDITION.md`.

### Changed

- The interface no longer opens on the research form; the task-based home page is the entry point.
- Answer headers carry measured provenance; the Advanced/Audit fold keeps raw core diagnostics.
- Navigation, task cards and workflow steps are links, so middle-click and "open in new tab" work.

### Fixed

- `/api/obsidian/status` never returned an open URI, so the home "Open Obsidian" action always
  fell into its "not configured" branch and printed `unknown`. It now returns
  `obsidian://open?vault=<active root>` built from the existing adapter's naming rule.
- Router dropped its own sub-view parameter: navigating to a concepts search rewrote the URL to
  `/explore?…` without `?view=concepts`, so results never rendered.
- Empty states that leaked an i18n key as visible text (`projects.no-projects-yet`).
- Narrow viewports (430 px) had horizontal overflow from the top bar (860 px content in a 500 px
  viewport); the controls now wrap.
- Accessibility: the new onboarding controls had no accessible name (caught by the project's own
  accessibility audit); they now carry `aria-label` wired to the dictionary.

### Security

- Credentials never pass through the product API, are never echoed, and are never written to the
  persisted provider settings; run artifacts are scanned for key-like patterns as a gate item.

### Not included (by design)

- Any third-party source text, passage store, witness realizations or index derived from them.
  See [CORPUS.md](CORPUS.md) and [NOTICE](NOTICE).

---

## How to read versions

| Layer | Versioning |
|---|---|
| **Scholarly core** | freeze segment (`scholarly_core_freeze_v1`) + lineage append; never a silent edit |
| **Product layer** | semantic versioning in `package.json` / this changelog |
| **Contracts** (`scholarly_api v1`, MCP tool schemas) | additive-only within a major version; breaking change ⇒ new major |
