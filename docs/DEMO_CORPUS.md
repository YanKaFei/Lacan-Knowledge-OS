# DEMO_CORPUS.md — a public-domain demo corpus (work in progress)

> Goal: let anyone who clones this repository run a **real** research pass without touching
> the copyrighted Lacan corpus. Status: **stage 1 of 2 complete** — the corpus builds, the
> retrieval path works, and the core answers honestly (it abstains, with a reason). It does
> **not** yet produce a `VALIDATED` answer, because the demo has no ontology layer.

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

## 2. What the builder produces

```sh
python3 tools/build_demo_corpus.py .        # writes into _data/passage_store/
python3 _scripts/_tools/build_lexical_index.py
```

Result (verified on a clean clone):

| Artifact | Count |
|---|---|
| `_data/passage_store/passages.jsonl` | **183** passages (Falret 99 / Janet 68 / Binet 16) |
| `passage_realizations.jsonl`, `passage_witnesses.jsonl` | 183 each |
| `witnesses.jsonl` | 3 (one per source, `witness_kind: edition_extract`) |
| `seminars.jsonl` / `sessions.jsonl` | 3 / 8 |
| `corpus_sources.jsonl` | 3 (`kind: print_edition`, real publisher + year in the name) |
| `_data/index/lexical.sqlite` | FTS index, 585 KB |

Passages carry honest provenance: source URL, file sha256, and an `edition` string built from
the actual title page. `trace_status` is `COMPLETE` (the imprint is documented) rather than the
`SOURCE_TRACE_INCOMPLETE` the reference corpus has to use.

## 3. What works today

```sh
python3 tools/build_demo_corpus.py .
python3 _scripts/_tools/build_lexical_index.py
python3 -m workspace_ui.server.cli --port 3090
```

- The UI, the 13-page Help Centre, Explore and the Evidence Inspector all work.
- A research run executes the whole pipeline: retrieval → evidence contract → **abstention**.
  The abstention is a real judgement with a reason (`ONTOLOGY_GAP`), not a crash and not an
  invented answer — which is exactly the behaviour the system promises.

## 4. What is still missing (stage 2)

**The ontology layer.** The sufficiency stage needs ontological bindings for the question's
concepts; with an empty `_data/ontology/v4a1/`, every question lands on `ONTOLOGY_GAP` and
abstains. To reach `VALIDATED` / `VALIDATED_WITH_QUALIFICATIONS` on the demo corpus, stage 2 must:

1. author a small `_data/ontology/v4a1/entities.jsonl` for the demo's clinical terms
   (`hystérie`, `dissociation`, `dédoublement de la personnalité`, `subconscient`,
   `psychasthénie`, `folie raisonnante`, …) with `passage_evidence_n` and `passages` pointing at
   real demo passage ids;
2. author a matching `relations.jsonl` (each relation needs `evidence.must_have_passage` with real
   passage ids) and `term_mappings.jsonl` for the French↔English forms;
3. re-run the demo build, then check that at least one demo question reaches a validated state;
4. only then pack it (`tools/pack-corpus.py --vault <demo vault>`) and publish the pack as a
   **public** release asset, so `fetch-corpus.py --url …` gives anyone a working corpus.

Nothing in that list touches the frozen scholarly core: it is a *new corpus*, so its ontology and
its data-version inputs are new data. The frozen 30 semantic components are code-level and stay
untouched; `core_freeze.py --build` is the supported way to pin a new corpus (see
[CORPUS.md](../CORPUS.md) and [CORPUS_PACK.md](CORPUS_PACK.md)).

## 5. Why this is the honest answer to "download and it's useless"

The alternative — publishing the Lacan corpus — would redistribute three third-party rights
holders' work (a transcription site, a print edition, a community translation) and is not a
licence question that "not using it commercially" resolves. A public-domain demo corpus gives a
downloader something that is genuinely usable **and** legally distributable, and it doubles as a
worked example of building your own corpus.

See also: [CORPUS.md](../CORPUS.md) · [CORPUS_PACK.md](CORPUS_PACK.md) · [PUBLIC_EDITION.md](PUBLIC_EDITION.md)
