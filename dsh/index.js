// dsh/index.js — DSH bundle entry for Lacan Knowledge OS.
//
// This bundle contributes **no service and no tool of its own**. It exists so a
// DeepSeek Harness profile can install the Lacan Knowledge OS MCP surface with a
// single command:
//
//     dsh plugin --profile web add github:YanKaFei/Lacan-Knowledge-OS
//
// The capability comes from the row inserted by ./cordis.patch.yml, which mounts
// the shipped `@deepseek-ai/dsh-mcp-client` against this repository's own MCP
// server (`_scripts/_tools/lacan-kb-mcp`). That row only calls `ctx.tools.register`
// and provides nothing, so it needs no isolate realm.
//
// Kept intentionally empty: a bundle whose whole contribution is a composition
// patch. (`@deepseek-ai/dsh-base` does the same.)
export {};
