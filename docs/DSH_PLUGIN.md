# DSH_PLUGIN.md — using Lacan Knowledge OS from DeepSeek Harness

> This repository **is** a DSH plugin target: it ships an MCP server, a portable composition
> row, an installable bundle, and a proof file produced with DSH's own MCP SDK.

---

## 1. Three ways in

### A. Install as a DSH bundle (one command)

```bash
dsh plugin --profile web add github:YanKaFei/Lacan-Knowledge-OS
dsh --profile web          # restart the profile so the row activates
```

The bundle (`package.json` → `dsh.bundle.patch` → `cordis.patch.yml`) inserts **one row**
that mounts the shipped `@deepseek-ai/dsh-mcp-client` against this repository's MCP server.
Your tools then list as:

```
mcp__lacan-kb__search_passages     mcp__lacan-kb__get_passage
mcp__lacan-kb__get_context         mcp__lacan-kb__resolve_entity
mcp__lacan-kb__list_concepts       mcp__lacan-kb__search_terminology
mcp__lacan-kb__compare_concepts    mcp__lacan-kb__find_relation
mcp__lacan-kb__list_seminars       mcp__lacan-kb__get_sources
```

> **Path note.** The bundle row uses `cwd: .` plus a repository-relative server path, so it
> carries nobody's absolute paths. Launch DSH from the cloned repository. If you launch it
> elsewhere, use option B or C below.

### B. Write the row with your clone's absolute path

```bash
python3 tools/install-dsh-row.py --profile web          # install / update (idempotent)
python3 tools/install-dsh-row.py --profile web --print   # just show the block
python3 tools/install-dsh-row.py --profile web --remove  # clean uninstall
```

It writes one clearly delimited block into
`${DSH_HOME:-~/.dsh}/profiles/<profile>/cordis.patch.yml` and never touches a shipped preset
or the host composition.

### C. Plain MCP client (no DSH)

```bash
python3 _scripts/_tools/lacan-kb-mcp          # stdio MCP server
```

Ready-made configs: [`integrations/`](../integrations) — Claude Desktop JSON, Codex TOML,
and the DSH row YAML.

---

## 2. Why this row needs no isolate realm

A composition rule in this harness: **a row that publishes a service must sit behind an
isolate realm** (otherwise a second session mounting the same preset collides in the
process-global realm). `@deepseek-ai/dsh-mcp-client` **provides no service** — it only calls
`ctx.tools.register` to contribute tools. So the row sits loose in the agent-preset plane,
exactly like the harness's own `tool-bash` / `tool-goals` rows, and no realm is required.

If a future version of the MCP client starts providing a service, the mount will reject the
composition loudly (`row(s) published process-global service(s) […]`) rather than failing
silently later. The fix then is an `isolate` group around the provider *and* its consumers.

---

## 3. What has been proven (not asserted)

`_data/mcp/DSH_CLIENT_PROOF.json` records **14/14** checks run with DSH's own MCP SDK
(`@modelcontextprotocol/sdk`, the copy inside DSH's `node_modules`):

| # | Check | Result |
|---|---|---|
| 1 | SDK version matches DSH's | `1.30.0` |
| 2 | stdio handshake | `serverInfo={"name":"lacan-kb","version":"0.1.0"}` |
| 3 | protocol version supported by DSH's SDK | server declares `2025-11-25`; SDK `LATEST=2025-11-25` |
| 4 | capabilities contain only `tools` | `{"tools":{"listChanged":false}}` |
| 5–7 | `tools/list` returns 10 contract-named tools, each with `inputSchema` | 10/10 |
| 8 | DSH-side naming shape | `mcp__lacan-kb__search_passages` |
| 9–11 | `tools/call` returns structured evidence + text fallback + legal `evidence_state` | 8/8 blocks |
| 12 | returned `passage_id` independently re-verified against the canonical store | 3/3 |
| 13 | a second tool callable | `resolve_entity("Symbolic") → concept.le-symbolique` |
| 14 | unknown tool → protocol error, not a crash | `MCP error -32602` |

Startup cost measured: process start + `initialize` + `tools/list` + one `search_passages`
= **1.24 s** (system python3, vector path not loaded).

Reproduce (requires Node and this repository; a corpus is needed for check 12):

```bash
node _scripts/_tools/mcp_client_proof.mjs
```

---

## 4. Without a corpus

The MCP server starts and advertises its tools regardless of corpus state; tool calls that
need passages will report the corpus layer as unavailable rather than inventing an answer.
That is the designed behaviour — see [`../CORPUS.md`](../CORPUS.md).

The web surface is fully usable with no corpus at all:

```bash
python3 -m workspace_ui.server.cli --port 3090
# → http://127.0.0.1:3090/help      (13-page Help Center)
# → /api/status, /api/help/content, /api/provider/settings all answer 200
```

---

## 5. Uninstall

```bash
dsh plugin --profile web remove dsh-lacan-knowledge-os     # bundle route
python3 tools/install-dsh-row.py --profile web --remove     # row route
```

Neither touches your corpus, your projects, or the frozen core.
