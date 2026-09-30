<div align="center">

# Lacan Knowledge OS

**A corpus-grounded research environment for Lacanian psychoanalysis.**
Evidence first. Interpretation second. Fabrication never.

[**English**](README.md) · [中文](README.zh.md) · [日本語](README.ja.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Italiano](README.it.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-6b4c2f?style=flat-square)](LICENSE)
[![Core](https://img.shields.io/badge/scholarly%20core-frozen%20%C2%B7%2039%20components-43403b?style=flat-square)](docs/ARCHITECTURE.md)
[![Tests](https://img.shields.io/badge/regression-146%20suites%20%C2%B7%200%20failed-3f6b4a?style=flat-square)](docs/SCHOLARLY_REGRESSION_SPEC_V1.md)
[![MCP](https://img.shields.io/badge/MCP-10%20tools%20%C2%B7%202025--11--25-6b4c2f?style=flat-square)](docs/MCP_TOOL_CONTRACTS.md)
[![Corpus](https://img.shields.io/badge/corpus-companion%20repository%20%C2%B7%20research%20use-8a6d1f?style=flat-square)](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus)

</div>

---

> ### The one rule this system is built around
>
> *Every claim must land on a passage number.*
>
> If the corpus cannot support a question, the system **abstains** — it does not answer from
> model knowledge. **An abstention is a result, not an error.**

---

> ## ⚠️ Rights notice — read before installing the corpus
>
> **The engine is open source. The corpus is not.** Two different things, two different rules:
>
> | | License / status |
> |---|---|
> | **Engine source code** (this repository) | Apache-2.0 — use, modify, redistribute, build on it |
> | **Reference corpus** ([companion repo](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus)) | **third-party copyrighted texts.** Publicly readable **for research and study only**; public visibility is not a licence — **not** licensed for commercial use, redistribution or re-serving. |
> | **Public-domain demo corpus** ([`corpus-demo-v1`](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus/releases/tag/corpus-demo-v1) · [`demo-corpus/`](demo-corpus)) | public domain (Falret 1890 · Binet 1892 · Janet 1909) — freely redistributable; ~0.3 MB, one command installs a **complete research run** |
>
> **In plain terms.** The corpus repository contains French working transcriptions of Lacan's
> seminars, a text extraction from the Seuil print edition, and a community Chinese translation
> project. None of these rights belong to this project. It is published openly so that researchers can obtain it, and **public availability is not a
> licence**: it does not permit commercial use, redistribution, mirroring, repackaging, or serving
> the text to others. If you are unsure whether your intended use is lawful, that question is yours to answer —
> this project cannot answer it for you. **The full analysis is in [`RIGHTS.md`](RIGHTS.md).**
>
> **If you need something you can publish, share or ship commercially, use the engine with a
> corpus you have the right to use** — the public-domain demo, your own texts, or a licensed
> edition. That path is fully supported: [`CORPUS.md`](CORPUS.md) ·
> [`docs/DEMO_CORPUS.md`](docs/DEMO_CORPUS.md).

---

## What it is

**Lacan Knowledge OS** turns a corpus of seminar and écrits text into a **citable evidence store**,
and puts a **frozen scholarly core** between your question and any answer.

<img src="assets/diagrams/architecture.svg" alt="Architecture: agents enter over MCP; a product layer sits above a frozen 39-component scholarly core; the corpus is supplied separately and is not part of the open-source engine." width="100%">

| | Capability | What it gives you |
|---|---|---|
| 🔎 | **Research** | Ask a question → the core retrieves passages, builds an evidence contract, and only then synthesises an answer whose every claim survives citation + entailment validation |
| 📖 | **Explore** | Read the corpus directly: passages, sessions, seminars, concepts, terminology — no model involved |
| 🔬 | **Evidence Inspector** | `Answer → Claim → Passage → Session → Seminar → Witness/Source`, with the exact quoted span and its context window |
| 🗂️ | **Research Projects** | Turn repeated runs into a long-term topic (questions, hypotheses, passages, persons, cases, bibliography) |
| 📚 | **Bibliography & citations** | Review status, metadata completeness, per-style citation availability **with the reason it is unavailable** |
| ✍️ | **Obsidian bridge** | Evidence and validation stay here; your understanding, notes and writing live in your vault |

### The chain you can always audit

<img src="assets/diagrams/evidence-chain.svg" alt="Evidence chain: answer → claim → passage → session → seminar/document → witness/source, and the Evidence Inspector that shows the quoted span, context and source chain." width="100%">

## What it refuses to do

These refusals are the design, not limitations:

| Refusal | Why |
|---|---|
| **No answering from model knowledge** | The synthesis step may only use retrieved evidence. Insufficient contract → `ABSTAINED`. |
| **No silent repair of sources** | `SOURCE_TRACE_INCOMPLETE` stays visible; hiding it would misrepresent the source. |
| **No invented bibliographic data** | Publisher, year, ISBN, page numbers are never guessed. A style that cannot be produced says why. |
| **No auto-promotion to canonical** | Imported or AI-produced material enters as a *candidate* and stays one until a human promotes it. |
| **No undeclared semantics** | The 39 scholarly components are hash-pinned; an undeclared change fails the freeze check and the launcher **refuses to start**. |

---

## Get started

**Are you an AI agent?** Run this first and follow what it prints — it decides whether research can
run at all:

```sh
python3 tools/ensure_corpus.py --status      # exit 0 = corpus ready · exit 3 = tell the user
python3 tools/ensure_corpus.py --json        # machine-readable status
```

### 1 · Clone the engine

```sh
git clone https://github.com/YanKaFei/Lacan-Knowledge-OS.git
cd Lacan-Knowledge-OS
python3 -m workspace_ui.server.cli --port 3090
# → http://127.0.0.1:3090/help    (13-page Help Centre — fully usable with no corpus)
```

### 2 · Give it a corpus — one of three paths

| Path | What you get | How |
|---|---|---|
| **A. Reference corpus** (public download, research use only) | the full Lacan seminar corpus: 1,979 files · 249,105 passages · indexes ready to run | [`YanKaFei/Lacan-Knowledge-OS-corpus`](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus) → `python3 tools/ensure_corpus.py --install --pack corpus-pack-v1.tar.gz --manifest corpus-pack-v1.manifest.json` |
| **B. Public-domain demo** | 19th-century French clinical sources (Falret · Binet · Janet) — redistributable | `python3 tools/build_demo_corpus.py . && python3 _scripts/_tools/build_lexical_index.py` |
| **C. Your own text** | anything you are entitled to use, ingested by the engine's own builders | [`CORPUS.md`](CORPUS.md) · `python3 _scripts/inventory_corpus.py --help` |

**Path A in full.** The companion repository is public, so the pack downloads without a token —
but it is **third-party copyrighted text: research and study only** ([`RIGHTS.md`](RIGHTS.md)).
It holds a **corpus pack**: one hash-manifested archive
that `tools/fetch-corpus.py` verifies file by file before installing — a partial or altered
download cannot silently corrupt the corpus.

```sh
curl -sLO https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus/releases/download/corpus-v1/corpus-pack-v1.tar.gz
curl -sLO https://raw.githubusercontent.com/YanKaFei/Lacan-Knowledge-OS-corpus/main/corpus-pack-v1.manifest.json
python3 tools/fetch-corpus.py --pack corpus-pack-v1.tar.gz \
    --manifest corpus-pack-v1.manifest.json --into .
python3 _scripts/_tools/core_freeze.py --verify      # → SCHOLARLY_CORE_READY
python3 -m workspace_ui.server.cli --port 3090       # research now answers
```

Path A is a plain public download and is **for research use only** — no commercial use, no
redistribution, no re-serving ([`RIGHTS.md`](RIGHTS.md)). Paths B and C need no access at all.
Pack mechanics (handing a corpus to a colleague without publishing it):
[`docs/CORPUS_PACK.md`](docs/CORPUS_PACK.md).

### 3 · Verify the contract (this is the point of the project)

```sh
python3 _scripts/_tools/core_freeze.py --verify      # 39 scholarly components
python3 _scripts/_tools/freeze_lineage.py --verify   # zero semantic drift across 7 segments
python3 _scripts/_tools/build_i18n.py --check        # UI copy ↔ dictionary ↔ call sites
python3 _scripts/_tools/build_help.py --check        # Help links, anchors, 0 fiction
bash _scripts/run_all_tests.sh                       # 146 suites · 78 validators
```

**Requirements:** Python 3.9+ (standard library covers the core path) and a modern browser.
No bundler, no build step — `index.html` loads ES modules directly. Vector retrieval and real
LLM synthesis are optional extras ([`docs/EMBEDDING_PROVIDER.md`](docs/EMBEDDING_PROVIDER.md)).

---

## How to use it

<img src="assets/diagrams/workflow.svg" alt="One research task: ask, check evidence, read the original, save the material, sort sources, form your own knowledge — with abstention as a first-class outcome." width="100%">

1. **Ask** — one question per run.
2. **Read the state** — `VALIDATED`, `VALIDATED_WITH_QUALIFICATIONS`, `PARTIALLY_SUPPORTED`,
   `VALIDATION_FAILED`, `INSUFFICIENT_EVIDENCE`, `ABSTAINED`. Read it literally.
3. **Verify** — click a citation chip; the Evidence Inspector shows the quoted span, its context
   window and the source chain. *The answer is what the core concluded; the inspector is what the
   corpus actually says.*
4. **Go deeper** — open the same passage in Explore and read around it.
5. **Keep it** — `Add to Project`, or `Save to Obsidian`.

### The interface

| Where | What |
|---|---|
| **Home** | task-based: *what do you want to do?* — six task cards, the six-step workflow (with a diagram of one run end to end), a five-minute quick start. Every entry is a real link. |
| **Research** | question box, mode / provider / research-language, and measured provenance on every answer (`provider · model · wall-clock · cached · attempts`) |
| **Explore** | passages, sessions, seminars, concepts, terminology, persons, cases — read-only |
| **Evidence Inspector** | the right-hand panel: original passage, quoted span, context controls, source chain, translation |
| **Help Centre** | `/help` — 13 topics, sidebar, anchors, previous/next, topic search, instant language switch, and three in-product diagrams (system layers · evidence chain · one research task) drawn as inline SVG, so their labels follow the interface language |
| **Languages** | interface language (EN/中文) and *research language* are independent settings |

Every control name inside Help is rendered from the real interface, and every functional claim is
machine-checked: **45/45 claims verified · 0 documentation fiction · 0 broken links**.

---

## Use it from DSH / any MCP client

This repository **is** a [DeepSeek Harness](https://github.com/deepseek-ai) plugin target: it ships
an MCP server, a portable composition row, an installable bundle and an idempotent installer.

```sh
dsh plugin --profile web add github:YanKaFei/Lacan-Knowledge-OS
python3 tools/install-dsh-row.py --profile web     # bind the server path for your clone
python3 _scripts/_tools/lacan-kb-mcp               # or run the MCP server standalone
```

Tools appear as `mcp__lacan-kb__search_passages`, `…get_passage`, `…get_context`,
`…resolve_entity`, `…list_concepts`, `…search_terminology`, `…compare_concepts`,
`…find_relation`, `…list_seminars`, `…get_sources` — **10 tools**, protocol `2025-11-25`.
Proven with DSH's own MCP SDK (`_data/mcp/DSH_CLIENT_PROOF.json`, **14/14 checks**).
See [`docs/DSH_PLUGIN.md`](docs/DSH_PLUGIN.md).

---

## Advantages and disadvantages

<table>
<tr><th width="50%">✅ Advantages</th><th width="50%">⚠️ Disadvantages / limits</th></tr>
<tr valign="top"><td>

**Verifiability over fluency.** Every claim ties to a passage id; you can audit the chain by hand.

**Honest failure.** Abstention, `INSUFFICIENT_EVIDENCE` and explicit unavailability are first-class
outputs. No hallucinated filler.

**An executable contract.** The 39-component freeze and the seven-segment lineage are checked by
code, not by a promise in a document.

**Offline-first.** `Offline / Mock` produces deterministic answers with no credentials, no network.

**One contract, many clients.** The same MCP surface serves the web UI, DSH, and any editor with
an MCP client.

**Auditable history.** Every run is an immutable snapshot; re-asking creates a new item instead of
overwriting the old one.

**Corpus is separable.** Engine public (Apache-2.0), corpus third-party with its own boundary or
bring your own — the two never mix in one repository.

</td><td>

**It needs a corpus you have the right to use.** Out of the box it shows its interface, Help Centre
and contracts; it answers only once a corpus is installed. The reference pack is public to download
but **research-use-only** material.

**The reference corpus is research material, not a product asset.** No commercial use, no
redistribution — see [`RIGHTS.md`](RIGHTS.md).

**It is opinionated about scope.** It answers *about a corpus*. Questions about publication
history, attendees or dates abstain, because the corpus does not carry that metadata.

**No quality score.** There is no “confidence %” anywhere; interpretation quality remains your
judgement.

**Heavy at laptop scale.** The reference corpus is ~2.5 GB on disk including derived indexes.

**Vector retrieval is optional.** Without the embedding extras, retrieval falls back to lexical
matching (the UI says which is active).

**Real-LLM synthesis is a single blocking call.** Long runs take 45–60 s; the UI shows real
elapsed time, and “stop waiting” does not cancel the backend job.

**Fast product layer, frozen scholarly layer.** Convenience features change often; changing the
*semantics* requires a formal Core Change Request.

**Presupposes familiarity with the domain.** It will not teach you Lacan.

</td></tr>
</table>

---

## Documentation map

| Document | Contents |
|---|---|
| [`RIGHTS.md`](RIGHTS.md) | **rights and permitted use, in full** — engine vs corpus, what access does and does not grant |
| [`NOTICE`](NOTICE) | the same boundary in the form a distributor needs |
| [`AGENTS.md`](AGENTS.md) | the rules an AI agent must follow here — starting with the corpus check |
| [`corpus.json`](corpus.json) | machine-readable corpus reference: where it lives, how to install it, what to do if it is missing |
| [`CORPUS.md`](CORPUS.md) | bringing your own corpus; what the builders expect |
| [`docs/DEMO_CORPUS.md`](docs/DEMO_CORPUS.md) | the public-domain demo corpus: one command builds it (corpus → index → ontology → freeze), and `corpus-demo-v1` installs a complete research run |
| [`docs/CORPUS_PACK.md`](docs/CORPUS_PACK.md) | packing and shipping a corpus without publishing it |
| [`docs/PUBLIC_EDITION.md`](docs/PUBLIC_EDITION.md) | how this repository is derived and negatively verified |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/MCP_ARCHITECTURE.md`](docs/MCP_ARCHITECTURE.md) | the layering and the MCP surface |
| [`DAILY_USE_GUIDE.md`](docs/DAILY_USE_GUIDE.md) · [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | day-to-day operation |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md) · [`CHANGELOG.md`](CHANGELOG.md) | how to help, credential discipline, history |

## Status

- **Scholarly core:** frozen v1 — `SCHOLARLY_CORE_READY`, 39 hash-pinned components, semantic drift **0**.
- **Product layer:** complete for daily use; last acceptance run **20/20 blocking gate items**,
  **146 regression suites / 78 validators / 0 failed / 0 skipped**.
- **Distribution:** engine public (Apache-2.0) · reference corpus public, **research use only** ·
  public-domain demo corpus **published** (`corpus-demo-v1`, redistributable).
- **Corpus profiles:** `reference` → `SCHOLARLY_CORE_READY` (human-reviewed); any other corpus →
  `CORPUS_HUMAN_REVIEW_NOT_AVAILABLE` (research runs, no human-review endorsement).
- **Roadmap:** [`docs/ROADMAP.md`](docs/ROADMAP.md).

<div align="center">

Code: [Apache-2.0](LICENSE) · Source texts: **not distributed, not licensed for commercial use** ([`RIGHTS.md`](RIGHTS.md))

*If this system saves you a week of citation checking, it did its job.*

</div>
