# DEMO_CORPUS.md — a public-domain demo corpus (stage 2 complete)

> Goal: let anyone who clones this repository run a **real** research pass without touching
> the copyrighted Lacan corpus. Status: **stage 2 of 2 complete** — the corpus, its index, its
> **ontology layer** and its corpus profile all build from one command, and an example question
> returns `VALIDATED_WITH_QUALIFICATIONS` with citations to real passages.
>
> It ships as a public, **redistributable** pack: `corpus-demo-v1`
> (≈0.3 MB, 42 files, no reference-corpus artifacts).

---

## 1. The sources (all public domain, all verifiable)

Fetched from `fr.wikisource.org` with their real imprint data, and committed under
[`demo-corpus/sources/`](../demo-corpus/sources) so the build works offline:

| File | Work | Imprint | Chars |
|---|---|---|---|
| `falret.txt` | Jules Falret, *Études cliniques sur les maladies mentales et nerveuses* | J. B. Baillière et fils, 1890 | 123,875 |
| `binet.txt` | Alfred Binet, *Les Altérations de la personnalité* | Félix Alcan, 1892 | 19,445 |
| `janet.txt` | Pierre Janet, *Les Névroses* | Ernest Flammarion, 1909 | 89,467 |

Chosen deliberately: this is the French clinical tradition Lacan was trained in and argued
with — Falret's clinical psychiatry, Binet's experimental work on dissociation, Janet's
psychasthenia and the *dissociation des fonctions*. All three authors are long dead and their
works are in the public domain, so this corpus is **redistributable** — which the seminar texts
are not.

## 2. One command builds everything

```sh
python3 tools/build_demo_corpus.py .        # 段落库 → 词法/别名索引 → 语料清单 → 本体层 → 冻结/谱系
```

| Stage | Artifact | Count |
|---|---|---|
| passage store | `_data/passage_store/passages.jsonl` | **183** passages (Falret 99 / Janet 68 / Binet 16) |
| | `witnesses.jsonl` / `seminars.jsonl` / `sessions.jsonl` / `corpus_sources.jsonl` | 3 / 3 / 8 / 3 |
| retrieval | `_data/index/lexical.sqlite`, `alias_index.jsonl`, `INDEX_MANIFEST.json` | FTS index over the demo text |
| inventory | `_data/corpus_inventory.json` | 3 files, 227 KB |
| **ontology** | `_data/ontology/v4a1/` from [`demo-corpus/ontology/spec.json`](../demo-corpus/ontology/spec.json) | **15 entities · 89 evidence rows · 6 fr↔en↔zh mappings · 3 relations** |
| terminology | `_data/terminology_bridge.jsonl` | 6 `equivalent` records (derived from the ontology mappings) |
| freeze | `_data/core_freeze/scholarly_core_freeze_v1.json` | 39 components, profile `unreviewed-corpus` |
| lineage | `_data/core_freeze/freeze_lineage.json` | 8 segments, `semantic=0 / data_version=7` |

The ontology spec is **authored data that ships in this repository** (like the sources): it
declares, for each demo term, which surface forms count as evidence. `build_ontology_v4a1.py`
then recomputes every supporting passage from the demo store — no passage id is hand-copied.
Nothing in it writes a theoretical definition (`definition` is `null` everywhere), and the
machine tokens (passage ids, session ids, API paths) are never translated.

## 3. What works

```sh
python3 tools/build_demo_corpus.py .                 # or install the pack (see §5)
python3 -m workspace_ui.server.cli --port 3090       # → /help, /research, /explore
bash _scripts/runtime/start_lacan_os.sh              # launcher (freeze + lineage gates pass)
```

A research run executes the whole pipeline. The example question — with the mock provider, no
credentials, no network — returns:

```
question:  Comment la suggestion agit-elle dans l'hystérie ?
answer_state = VALIDATED_WITH_QUALIFICATIONS · evidence_state = SUPPORTED
3 validated claims · 3 citations (all ELIGIBLE) · 1 rejected claim
  c1 → passage.S03.unknown.L01.P0010   "J'ai été amené cependant à discuter longuement cette conception…"
  c2 → passage.S02.unknown.L01.P0008   "On ne se doute pas de la faible quantité d'excitation…"
  c3 → passage.S03.unknown.L02.P0017   "En réalité le grand symptôme mental que les études récentes…"
```

Clicking a citation opens the Evidence Inspector on the real demo passage (quoted span,
context, source chain). Explore, the 13-page Help Centre and the bibliography registry all work
on this corpus.

## 4. The honest limits (read this before quoting a demo answer)

1. **No human acceptance evidence.** The reference corpus ships nine *human-acceptance*
   artifacts (review records, adjudication queue, readiness gate, error taxonomy, review schema,
   `gold_v2`, frozen identity). A demo corpus cannot have them, so the freeze declares them
   **absent by declaration** and the status is `CORPUS_HUMAN_REVIEW_NOT_AVAILABLE` — *not*
   `SCHOLARLY_CORE_READY`. Research runs; the answers carry **no human-review endorsement** and
   are not to be presented as accepted scholarly conclusions. `ensure_corpus.py --status`,
   `/api/status` and the UI's System Status all state this explicitly.
2. **The core's source-attribution wording is written for the reference corpus.** The frozen
   synthesis boundary labels L1 evidence as *"在该段（L1 课堂转写）中，拉康：…"* — i.e. it names
   **Lacan**. On this corpus that speaker label **does not apply** (the words are Falret's,
   Binet's, Janet's). The demo therefore promises the chain
   **retrieval → evidence → citation → inspector → ontology resolution**, not a quotable
   academic claim. Fixing the attribution properly means changing a hash-pinned *scholarly
   semantic* component, which this project only does through a Core Change Request.
3. **No vector index.** The retrieval path is lexical (FTS); `VECTOR_INDEX_MANIFEST.json`
   records `status: NOT_BUILT` honestly.

## 5. Install the pack instead of building

```sh
curl -sLO https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus/releases/download/corpus-demo-v1/corpus-demo-v1.tar.gz
curl -sLO https://raw.githubusercontent.com/YanKaFei/Lacan-Knowledge-OS-corpus/main/corpus-demo-v1.manifest.json
python3 tools/fetch-corpus.py --pack corpus-demo-v1.tar.gz \
    --manifest corpus-demo-v1.manifest.json --into . --force
python3 tools/ensure_corpus.py --status      # exit 0, prints corpus_profile=unreviewed-corpus
```

`--force` is required when the clone still holds the engine's **reference** metadata
(`_data/index/INDEX_MANIFEST.json`, `_data/passage_store/_build_meta.json`, `_concept_meta.json`,
and the shipped freeze files). The installer **refuses to mix corpora**: without `--force` it
reports those files and exits 3 rather than silently installing half a corpus.

## 6. Verify it yourself

```sh
python3 _scripts/_tools/demo_corpus_acceptance.py --keep
```

That script is the evidence for everything above: it builds the public edition, runs the full
demo build, packs it, installs it into a *clean* clone, checks `ensure_corpus` / `core_freeze`
/ `freeze_lineage` / the ontology validator / the index manifest, runs the example question
through the MCP tool and asserts `VALIDATED*` with real citations — and asserts the honesty
boundaries (no reference acceptance files in the pack, profile `unreviewed-corpus`, status
`CORPUS_HUMAN_REVIEW_NOT_AVAILABLE`). Report: `_data/daily_use/demo_corpus_acceptance.json`.

## 7. Why this is the honest answer to "download and it's useless"

The alternative — publishing the Lacan corpus — would redistribute three third-party rights
holders' work (a transcription site, a print edition, a community translation) and is not a
licence question that "not using it commercially" resolves. A public-domain demo corpus gives a
downloader something genuinely usable **and** legally distributable, it doubles as a worked
example of building your own corpus, and its limits are printed in the artifacts themselves
rather than left for the user to discover.

See also: [CORPUS.md](../CORPUS.md) · [CORPUS_PACK.md](CORPUS_PACK.md) · [PUBLIC_EDITION.md](PUBLIC_EDITION.md)
