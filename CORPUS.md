# CORPUS.md — bringing your own corpus

> **This public repository ships the engine, not the corpus.**
> Nothing here is a research-grade corpus, and no source text of any third-party work
> is distributed. This file explains what that means and how to supply your own material
> **legally and reproducibly**.

---

## 1. Why the corpus is not here

| Excluded from this repository | Approximate size in the reference vault | Why excluded |
|---|---|---|
| Seminar / écrits full text (fr + zh) | 92 MB, 1,979 files | Copyright of the rights holders |
| `_data/passage_store/passages.jsonl` | ~384 MB, 249,105 records | Corpus text |
| `passage_realizations.jsonl` + `passage_witnesses.jsonl` | ~152 MB | Corpus text |
| `_index/*.sqlite`, `_data/index/vector/*.npy` | ~550 MB | Large, fully rebuildable |
| Your research workspace, history, exports | — | Private working data |

### Shipping a corpus to someone else

The lawful way to hand over a **working** installation is a **corpus pack** (one hash-manifested
archive) sent through a channel you control — typically a private repository's release asset.
See [docs/CORPUS_PACK.md](docs/CORPUS_PACK.md):

```sh
python3 tools/pack-corpus.py --out /tmp/corpus-pack          # on the machine holding the corpus
python3 tools/fetch-corpus.py --pack … --manifest … --into .  # on the receiving machine
```

The public edition is produced by
[`_scripts/_tools/build_public_edition.py`](../_scripts/_tools/build_public_edition.py)
and then **negatively verified**: corpus N-gram probes (real text fragments must be absent),
a secret scan, an absolute-path scan and size gates. See
[PUBLIC_EDITION.md](PUBLIC_EDITION.md).

---

## 2. What you may ingest

You are responsible for the rights. Workable sources, in rough order of friction:

| Source | Notes |
|---|---|
| **Public-domain editions** (e.g. pre-1929 Freud texts, public-domain philosophy) | Cleanest case. Keep the edition notice in `NOTICE`. |
| **Your own scans / OCR of books you own** | Private research use in most jurisdictions; redistribution is a separate question. |
| **Licensed digital editions** (publisher or library licence) | Check whether the licence permits derived text stores; keep the licence text. |
| **Your own translations** | You hold the translation rights; the underlying work's rights still apply. |
| **Openly licensed corpora** (CC-BY, CC-BY-SA, CC0) | Attribute per the licence; note share-alike implications for derived files. |

> ⚠️ Ingesting does **not** launder rights. A derived passage store, an embedding index, or an
> exported bundle still contains the source text and inherits its constraints.

---

## 3. The pipeline (what the engine expects)

The engine is corpus-agnostic: it needs **a canonical source layer** plus **manifests**, and it
derives everything else. The builders and validators are all in this repository.

```
your text files (md / txt / json)
        │
        │  1. inventory            python3 _scripts/inventory_corpus.py
        ▼
canonical inventory + sha256 per source        _data/corpus_inventory.json
        │
        │  2. build                python3 _scripts/build.py
        ▼
passage store (passages / realizations / witnesses)   _data/passage_store/*
        │
        │  3. index                lexical · optional vector
        ▼
retrieval indexes + manifests                 _data/index/*
        │
        │  4. verify
        ▼
python3 _scripts/_tools/core_freeze.py --verify     # 39 scholarly components
python3 _scripts/_tools/freeze_lineage.py --verify  # semantic lineage
bash _scripts/run_all_tests.sh                      # full regression
```

```bash
# discover the exact flags on your checkout:
python3 _scripts/build.py --help
python3 _scripts/inventory_corpus.py --help
python3 _scripts/build.py --only 1        # inventory only (fast, no passage build)
```

**Two integrity rules the tooling enforces:**

1. **The vault is the source of truth.** Manifests pin source hashes; indexes can be deleted
   and rebuilt. If a manifest no longer matches the canonical layer, verification fails loudly.
2. **The scholarly core is frozen.** Corrupting or interleaving a build can leave a wall-clock
   timestamp in an inventory, which `core_freeze.py --verify` reports as a data-version drift.
   Recovery is a deterministic rebuild (`python3 _scripts/build.py --only 1`), not a hash edit.

---

## 4. What you get before adding any corpus

The interface is fully usable with **zero** corpus files:

```bash
python3 -m workspace_ui.server.cli --port 3090
curl -s localhost:3090/api/help/content | head -c 200      # 13 Help pages
curl -s localhost:3090/api/status                          # layer status
curl -s localhost:3090/api/provider/settings               # provider configuration
```

Verified on a clean clone: `/help`, `/research`, `/api/help/content`, `/api/status` and
`/api/provider/settings` all answer **200** without any corpus present. Research runs will
report the corpus layer as unavailable rather than inventing an answer — which is the designed
behaviour, not a bug.

---

## 5. Minimum viable corpus

To exercise the whole pipeline end to end you need:

| Layer | Minimum | Purpose |
|---|---|---|
| Source files | a handful of text documents with stable ids | canonical text |
| Passages | ≥ 1 passage per document, with `passage_id` + locator | retrievable evidence |
| Witnesses | 1 witness per source | provenance chain |
| Lemma / term layer | optional | terminology explorer |
| Ontology entities | optional | concept & person pages |

Start with lexical retrieval only (no embedding extras). Add the vector index once lexical
retrieval behaves — it is a strictly optional accelerator.
