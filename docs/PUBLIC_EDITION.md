# PUBLIC_EDITION.md — how this repository is derived and verified

> This repository is a **derived public edition** of a larger private research vault.
> It is produced by script and then verified **negatively** — the interesting claims are
> the things that must *not* be present.

---

## 1. Why an edition step exists

The reference vault contains, besides all the engine code:

| Private material | Size |
|---|---|
| Full seminar / écrits text (fr + zh) | 92 MB · 1,979 files |
| Passage store and witness realizations | ~152 MB |
| Retrieval indexes (SQLite, `*.npy`) | ~550 MB |
| Research workspace, history, exports, screenshots | ~28 MB |
| Local virtualenv and wheelhouse | ~60 MB |

Publishing all of that would redistribute copyrighted text and a private working history.
So the public edition is built from an **allow-list**, never by "excluding the big files".

```bash
python3 _scripts/_tools/build_public_edition.py --out /tmp/lacan-os-public
python3 _scripts/_tools/build_public_edition.py --verify-only /tmp/lacan-os-public
```

## 2. What is included

| Included | Contents |
|---|---|
| Engine packages | `scholarly_api/`, `mcp_server/`, `browse_api/`, `project_api/`, `export_system/`, `bibliography/`, `obsidian_adapter/`, `workspace_ui/`, `entity_browse_api.py` |
| Tooling and tests | `_scripts/` (builders, validators, runtime launchers, the whole regression suite) |
| Contracts | `_data/core_freeze/*`, MCP tool schemas, index manifests, passage-store meta, gate files, i18n catalog, Help content |
| Documentation | the curated `docs/` set plus the six-language READMEs |

## 3. What is excluded (and how it is enforced)

`DENY_DIRS` removes the corpus and private trees outright:

```
.git  .obsidian  .venv-embedding  _attachments  _index  _workspace  wheelhouse
00_System … 16_Research_Projects            (all vault note directories)
```

`DENY_SUFFIX` removes binary/derived artifacts (`.sqlite`, `.npy`, `.so`, `.whl`, images, PDFs).
`DENY_REL` removes corpus text by path — every `_data/passage_store/*.jsonl`,
`render_normalization.jsonl`, `terminology_bridge.jsonl`, `_data/ontology/**/*.jsonl`,
`_data/eval/**/*.jsonl`.

Inside `_data/`, only explicitly allow-listed contract files survive (`DATA_ALLOW`).

## 4. The verification pass (this is the point)

`--verify-only` fails the build unless **all** of the following hold:

| Check | Rule | Reference result |
|---|---|---|
| Denied paths | none present | 0 |
| File size | no file > 2 MB | 0 over |
| **Corpus leak** | N-gram probes taken from real private corpus text must be **absent** everywhere | 6 probes / 0 hits |
| **Secrets** | no personal-access-token prefixes, no `sk-`-style API keys, no cloud API keys, no private-key headers, no bearer authorization headers, no provider key assignments | 0 hits (a handful of test/audit files are allow-listed — they *define* these patterns in order to assert on them) |
| **Local paths** | no `<HOME>`, no private workspace directory name | 0 hits (the builder itself skips its own pattern strings) |

The corpus probes are the strongest evidence: the build extracts distinctive fragments from the
private seminar files and from the 249k-record passage store, then greps the whole public tree
for them. If any fragment appears, the edition is rejected.

## 5. Reference numbers for this edition

```
files                      539
size                       6.4 MB
copy allow-list            539 files
denied by policy           1,433 files
absolute paths rewritten   49 files
verification problems      0
```

Compare: the private vault is 2.5 GB with 2,972 tracked-plus-untracked artefacts of interest.
The public edition is **~0.26 %** of it by size — engine, contracts, docs and tests only.

## 6. Sanitisation

Every text file in the edition is passed through a rewrite step that replaces the author's
absolute vault path with `<REPO>`, any `<HOME>` path with `<HOME>`, and the private
workspace directory name with `<WORKSPACE>`. This keeps the published tree reproducible on
someone else's machine and avoids leaking a local directory layout.

## 7. Reproducing for your own fork

If you fork this project and accumulate your own private corpus:

```bash
python3 _scripts/_tools/build_public_edition.py --out /tmp/my-public
python3 _scripts/_tools/build_public_edition.py --verify-only /tmp/my-public
```

Adjust `DOCS_KEEP`, `DENY_REL` and `DATA_ALLOW` to your layout. Keep the negative checks —
they are what makes the claim "we do not ship source text" checkable rather than rhetorical.
