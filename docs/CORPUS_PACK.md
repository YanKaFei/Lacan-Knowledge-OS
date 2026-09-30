# CORPUS_PACK.md — shipping a corpus without publishing it

> The engine is public. The corpus is not, because it is **other people's text**.
> This page describes the lawful way to hand someone a working system.

---

## 1. Why the corpus cannot be a public download

The reference corpus is three third-party sources (registered in
`_data/passage_store/corpus_sources.jsonl`):

| Source | What it is | Status |
|---|---|---|
| `corpus-source.staferla` | a public French working-transcription site (S1–S27) | readable online ≠ licensed to redistribute |
| `corpus-source.seuil-print` | text extracted from the **Seuil** print edition (S1–S5), with page numbers | in-copyright commercial edition |
| `corpus-source.zh-translation-project` | a community Chinese translation project | a translation is a derivative work; the translation rights are not ours to grant |

Lacan's own text is in copyright (France/EU: 70 years post mortem). So the public repository
ships **engine, contracts, tooling, tests and documentation** and no source text at all —
verified by N-gram probes against the reference corpus (see
[PUBLIC_EDITION.md](PUBLIC_EDITION.md)).

## 2. What to ship instead: a corpus pack

A corpus pack is one compressed, hash-manifested archive that restores a complete working
corpus into any clone. It travels through **a channel you control** — a GitHub release asset
(public or private), your own server, or a USB stick. The reference corpus uses exactly this
mechanism: a public repository serving a hash-manifested pack.

```sh
# on the machine that holds the corpus
python3 tools/pack-corpus.py --out /tmp/corpus-pack              # 2,017 files → ~215 MB
python3 tools/pack-corpus.py --out /tmp/corpus-pack --with-vector # + vector index (+365 MB)

# on the receiving machine
git clone https://github.com/YanKaFei/Lacan-Knowledge-OS.git && cd Lacan-Knowledge-OS
python3 tools/fetch-corpus.py --pack corpus-pack-v1.tar.gz \
    --manifest corpus-pack-v1.manifest.json --into .
python3 -m workspace_ui.server.cli --port 3090
```

### What the pack contains

| Included | Why |
|---|---|
| `02_Lacan_Seminars/**` | the seminar texts the system cites |
| `_data/passage_store/*.jsonl` | the passage store (`raw_text` / `normalized_text`), witnesses, realizations, sessions, concepts, corpus sources |
| `_data/render_normalization.jsonl`, `_data/terminology_bridge.jsonl` | derived tables the UI reads |
| `_data/ontology/**`, `_data/entities/**`, `_data/bibliography/**` | canonical ontology, person/case registry, bibliography registry |
| `_data/index/lexical.sqlite`, `_index/passage_store.sqlite` | ready-to-run stores, so no rebuild is needed |
| `--with-vector` → `_data/index/vector/**` | optional semantic retrieval |

**Never in a pack:** `_workspace/` (your private research workspace), `wheelhouse/`, virtualenvs,
model caches.

### What a pack must contain (learned by running a fresh install)

Restoring the corpus text alone is **not** enough — the engine reads more than the text. A pack
that ships only `02_Lacan_Seminars/` + `passage_store/` fails on a clean machine in two ways:

| Missing piece | Symptom on a fresh install |
|---|---|
| data-version inputs (`_data/corpus_inventory.json`, `_data/index/INDEX_MANIFEST.json`, `_data/index/vector/VECTOR_INDEX_MANIFEST.json`) | `core_freeze.py --verify` reports data-version drift → the launcher refuses to start |
| scholarly review artifacts (`_data/eval/research_human_review*.jsonl`, `human_adjudication_queue.jsonl`, `scholarly_readiness_gate_v1.json`, `round2_*.json`, `gold_v2/**`, `phase4c1d2_frozen_identity.json`) | on a **non-reference** corpus: `--verify` reports unresolved components → the launcher refuses to start. Declare the corpus profile instead (`core_freeze.py --build --profile unreviewed-corpus`) — see §4 |
| small retrieval inputs (`_data/index/alias_index.jsonl`, evaluation pools, reference vectors, …) | `CORE_EXECUTION_FAILED: No such file or directory: …/alias_index.jsonl` on the first research run |

`tools/pack-corpus.py` therefore **derives its file list from the engine's own code**: it scans
`scholarly_api/`, `mcp_server/`, `browse_api/`, `workspace_ui/`, `export_system/`,
`bibliography/`, `project_api/`, `obsidian_adapter/` and `_scripts/` for `_data/**` and
`_index/**` path literals and includes every referenced file it finds. Hand-maintained lists
drift; this one cannot silently miss a retrieval input.

Verify a pack the way this page was verified — restore it into a clean clone, then:

```sh
python3 _scripts/_tools/core_freeze.py --verify                 # SCHOLARLY_CORE_READY
python3 _scripts/_tools/freeze_lineage.py --verify              # semantic=0
python3 -m workspace_ui.server.cli --port 3090 &
curl -s localhost:3090/api/status | grep -o '"core": "[A-Z]*"'  # READY
```

### Why packs rather than a `git push`

- **One artifact, one hash.** `fetch-corpus.py` verifies the pack hash *and* every file hash and
  refuses to install on any mismatch — a partial download cannot silently corrupt the corpus.
- **Path-safe.** The extractor only accepts members under `02_Lacan_Seminars/`, `_data/`,
  `_index/` and rejects absolute paths or `..` traversal.
- **Size-appropriate.** 1.4 GB uncompressed becomes ~215 MB; git history of the same content
  would be far larger and impossible to retract once pushed.
- **Separable rights.** The engine can be Apache-2.0 and public while the text keeps its own
  boundary — the two never mix inside one repository.

## 3. Sharing with someone

1. For the **reference corpus**, point them at
   [`YanKaFei/Lacan-Knowledge-OS-corpus`](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus):
   the pack is a public download, and its README states the boundary (research and study only).
2. For **your own** corpus, send the pack over a channel you control and hand over the manifest —
   it is what makes the archive verifiable.
3. Either way, the receiving side runs `fetch-corpus.py`, which verifies the pack hash and then
   every file hash, and refuses to install on any mismatch.

> ⚠️ **Never** commit a pack into the public engine repository, and never re-package or mirror the
> reference corpus pack. If you want a pack you can publish freely, build a corpus from material you
> own or from public-domain sources — not from the seminar texts (see
> [`DEMO_CORPUS.md`](DEMO_CORPUS.md)).

## 4. Making the public repo demo-able without the corpus

Four lawful options, in increasing effort:

| Option | What a downloader gets |
|---|---|
| **Interface only** (default) | the full UI, the 13-page Help Centre, every contract and gate — research runs report the corpus layer as unavailable: `/help`, `/research`, `/api/help/content`, `/api/status` all answer 200 with no corpus at all |
| **The demo corpus pack** (`--kind demo`, shipped as `corpus-demo-v1`) | a complete research run on public-domain clinical texts: retrieval → evidence → claims → citations → inspector, plus a 15-entity ontology layer. ~0.3 MB, **redistributable** |
| **Their own text** | `_scripts/inventory_corpus.py` + `_scripts/build.py` ingest a folder of their own documents into a passage store ([CORPUS.md](../CORPUS.md)) |
| **A publicly licensed sample of your own** | if you hold rights to some text, pack just that and ship it publicly |

The demo is the honest way to answer "I downloaded it and there was nothing to research": a
small, clearly-labelled, **public-domain** corpus that exercises the whole chain, with no
third-party text in it.

### Corpus profiles (why a demo pack cannot say `SCHOLARLY_CORE_READY`)

`core_freeze.py` pins 39 components, and **nine of them are the reference corpus's human
acceptance artifacts** (review rounds, adjudication queue, readiness gate, error taxonomy,
review schema, `gold_v2`, frozen identity). No other corpus can have them. Two profiles exist:

| Profile | Built with | `scholarly_status` | Meaning |
|---|---|---|---|
| `reference` | `core_freeze.py --build` | `SCHOLARLY_CORE_READY` | all 39 components present and matching — **human acceptance exists** |
| `unreviewed-corpus` | `core_freeze.py --build --profile unreviewed-corpus` | `CORPUS_HUMAN_REVIEW_NOT_AVAILABLE` | the nine artifacts are listed in `absent_components`; everything else (all 30 semantic code units, all data-version components) must still match. Research runs, **without human-review endorsement** |

`--verify` refuses any *undeclared* absence, any absent component outside the human-acceptance
group, and any "declared absent but present" (i.e. quietly swapping in other acceptance
evidence). `freeze_lineage.py` records such absences as `absent_by_declaration` so they are not
counted as `scholarly_semantic_changes`; the reference corpus is unchanged — a semantic change
there is still `SEMANTIC_DRIFT`, hard fail.

> The frozen core's **source-attribution wording** (the speaker named in synthesized claim text)
> was written for the reference corpus and does **not** apply to another corpus. That is why the
> demo documents its scope as retrieval / evidence / citation / inspector / ontology resolution,
> and why fixing it properly is a Core Change Request (a hash-pinned semantic component), not a
> documentation edit.
