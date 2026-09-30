# Add YanKaFei/Lacan-Knowledge-OS

One file: `data/plugins/YanKaFei__Lacan-Knowledge-OS.yml`.

**What it is.** A research environment for Lacanian psychoanalysis that exposes its corpus
through MCP. The plugin installs as a DSH bundle whose single inserted row mounts the shipped
`@deepseek-ai/dsh-mcp-client` against the repository's own MCP server
(`_scripts/_tools/lacan-kb-mcp`). It contributes **10 tools**:

`search_passages`, `get_passage`, `get_context`, `resolve_entity`, `list_concepts`,
`search_terminology`, `compare_concepts`, `find_relation`, `list_seminars`, `get_sources`.

**Install.**

```sh
dsh plugin --profile web add github:YanKaFei/Lacan-Knowledge-OS
# then bind the server path for this clone (one command, idempotent):
python3 tools/install-dsh-row.py --profile web
```

The bundle row uses `cwd: .` plus a repository-relative server path so no absolute paths ship in
the package; `tools/install-dsh-row.py` writes the absolute-path variant when DSH is launched
from elsewhere. Both forms are in
[`docs/DSH_PLUGIN.md`](https://github.com/YanKaFei/Lacan-Knowledge-OS/blob/main/docs/DSH_PLUGIN.md).

**What the claims rest on.**

- `package.json` declares `dsh.bundle.patch`; `cordis.patch.yml` inserts the row. Verified by an
  isolated-HOME plug-in drive: install → patch → boot → uninstall all pass.
- The MCP contract is proven with DSH's own SDK (the copy inside DSH's `node_modules`), 14/14
  checks recorded in `_data/mcp/DSH_CLIENT_PROOF.json`: stdio handshake, 10 tools with schemas,
  `mcp__lacan-kb__<tool>` naming, structured evidence returns, independent re-verification of
  returned passage ids, and a protocol error (`-32602`) rather than a crash for unknown tools.
- The row needs **no isolate realm**: `dsh-mcp-client` provides no service, it only calls
  `ctx.tools.register`.

**Scope note (deliberate).** The repository ships the engine, contracts, UI, tests and docs —
**not** any source text. Lacan's seminars and everything derived from them are copyrighted and
are not distributed; users bring their own corpus
([`CORPUS.md`](https://github.com/YanKaFei/Lacan-Knowledge-OS/blob/main/CORPUS.md)). Without a
corpus the UI, the 13-page Help Centre and all contracts work; tool calls that need passages
report the corpus layer as unavailable instead of inventing an answer.

The web surface is optional for this listing — the reason it belongs on this list is the MCP
tool surface, so `category: tools`.
