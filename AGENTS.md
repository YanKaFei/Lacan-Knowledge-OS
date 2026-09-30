# AGENTS.md — instructions for AI agents working in this repository

> This file is read by DSH, Codex, Claude Code and similar agents. It exists because the
> single most common first failure here is **"the engine is cloned but there is no corpus"**.

---

## 1. Before doing anything research-shaped: check the corpus

```sh
python3 tools/ensure_corpus.py --status      # exit 0 = ready
python3 tools/ensure_corpus.py --json        # structured status for you to read
```

| Exit | Meaning | What you must do |
|---|---|---|
| `0` | Corpus ready (passages present) | proceed |
| `3` | **Corpus missing or incomplete** | **tell the user**, in their language, and offer the two paths below — do not proceed as if research works |
| `4` | Pack present but hash verification failed | stop; report the mismatch; do not hand-edit files to make it pass |

### If the corpus is missing

This repository ships **no source text** (the seminar corpus is third-party copyrighted and is
deliberately excluded — see `CORPUS.md`). Two legitimate ways to get one:

**A. Install the reference corpus pack** (public repository, research use only)
`https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus`

```sh
curl -sLO https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus/releases/download/corpus-v1/corpus-pack-v1.tar.gz
curl -sLO https://raw.githubusercontent.com/YanKaFei/Lacan-Knowledge-OS-corpus/main/corpus-pack-v1.manifest.json
python3 tools/fetch-corpus.py --pack corpus-pack-v1.tar.gz --manifest corpus-pack-v1.manifest.json --into .
python3 _scripts/_tools/core_freeze.py --verify        # must print SCHOLARLY_CORE_READY
```

The pack is **third-party copyrighted text, published for research access only**. Never copy its
contents into this repository, never mirror or re-package it, and never present it as licensed for
reuse: no commercial use, no redistribution, no re-serving, no training a publicly distributed
model (see `RIGHTS.md`).

**B. Bring your own corpus** (text the user is entitled to use)

```sh
python3 tools/build_demo_corpus.py .                  # public-domain demo (Falret/Binet/Janet)
python3 _scripts/_tools/build_lexical_index.py
python3 _scripts/inventory_corpus.py --help           # ingest your own documents
python3 _scripts/build.py --help
```

Machine-readable details for both paths: [`corpus.json`](corpus.json).

**Say it to the user in one sentence** — for example, in English: *"This engine ships no corpus:
research needs one. I can install the reference corpus (public download, but third-party text —
research use only, no commercial use or redistribution), or we can build a corpus from text you have
the right to use."* Then stop and wait for their choice. Do not silently swap in a smaller corpus, and do not answer research questions
from your own knowledge.

---

## 2. Non-negotiable rules in this repository

1. **Never fabricate an answer.** No invented passage ids, citations, dates, publishers, page
   numbers, translations or metadata. If the corpus cannot support a question, the system
   **abstains** — and that abstention is the correct output. Never paper over it.
2. **The frozen core is not editable here.** 39 components are hash-pinned;
   `python3 _scripts/_tools/core_freeze.py --verify` recomputes them, and
   `freeze_lineage.py --verify` proves zero semantic drift. Semantic change requires a Core
   Change Request (`_core_change_requests/`). Never edit a hash to make a check pass — if the
   data version legitimately changed, rebuild it (`python3 _scripts/build.py`) or re-freeze
   data-version components with `core_freeze.py --build` and record why.
3. **AI output never becomes canonical.** Anything you produce is a candidate or a proposal.
   Promotion to canonical, and any human-review record, is a human act.
4. **Never weaken a test.** Fix the code or record the defect with evidence.
5. **No documentation fiction.** If you document a control, route, status or workflow, it must
   exist. Help text is machine-checked: `python3 _scripts/_tools/build_help.py --check` requires
   42/42 claims verified, 0 pending, 0 broken links. `build_i18n.py --check` must stay clean.
6. **Credentials never flow through the product API** and never into logs, fixtures or docs.
   Never commit a token, and never print one.
7. **Licensing.** Corpus text stays out of this repository. The companion corpus repository is
   public **for research access only** — never mirror or re-package it, never present it as licensed
   for reuse. Public-domain demo sources (`demo-corpus/sources/`) are the only texts shipped here.

---

## 3. Useful entry points

| Task | Command |
|---|---|
| Run the product UI | `python3 -m workspace_ui.server.cli --port 3090` → `/help` is a 13-page Help Centre |
| Corpus status | `python3 tools/ensure_corpus.py --status` |
| Pack a corpus for someone else | `python3 tools/pack-corpus.py --out /tmp/pack` |
| Install a corpus pack | `python3 tools/fetch-corpus.py --pack … --manifest … --into .` |
| Integrity | `core_freeze.py --verify` · `freeze_lineage.py --verify` · `build_i18n.py --check` · `build_help.py --check` |
| Regression | `bash _scripts/run_all_tests.sh` (needs a corpus; `failed=[]` **and** `skipped=[]` required) |
| Install as a DSH plugin | `dsh plugin --profile web add github:YanKaFei/Lacan-Knowledge-OS` (see `docs/DSH_PLUGIN.md`) |

---

## 4. Where things live

```
scholarly_api/     product-boundary API over the frozen core
mcp_server/        the MCP surface (10 tools, stdio) — agents normally enter here
browse_api/        read-only corpus browsing
workspace_ui/      the web product (task-based home, Help Centre, Evidence Inspector)
export_system/     citation + export formats
bibliography/      bibliography registry, review status, import
project_api/       research projects (USER_WORKSPACE)
obsidian_adapter/  Obsidian bridge
_scripts/          builders, validators, runtime launchers, the regression suite
docs/              architecture and model documents (start with ARCHITECTURE.md)
```

Nothing in this repository may be changed in a way that alters *scholarly semantics* — that is
the whole point of the split. Product-layer changes (UI, copy, tooling, docs, tests) are welcome.
