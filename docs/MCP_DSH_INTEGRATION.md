# MCP DSH 集成与客户端接入（Phase 4A §19）

> 本文件给出**可核验的**接入方式与证明。
> 协议与架构见 `MCP_ARCHITECTURE.md`；tool 契约见 `MCP_TOOL_CONTRACTS.md`。

---

## 1. 被证明的事实（不是配置意愿）

`_data/mcp/DSH_CLIENT_PROOF.json` 记录了 **14/14** 项检查，由
`_scripts/_tools/mcp_client_proof.mjs` 用 **DSH 自己那套 MCP SDK** 真实跑出来：

| # | 检查 | 结果 |
|---|---|---|
| 1 | SDK 版本与 DSH 一致 | `@modelcontextprotocol/sdk@1.30.0`（DSH 的 `node_modules` 里那一份） |
| 2 | stdio 握手成功 | `serverInfo={"name":"lacan-kb","version":"0.1.0"}` |
| 3 | server 声明的协议版本被 DSH 的 SDK 支持 | `lacan-kb` 声明 `2025-11-25`；SDK `LATEST=2025-11-25`；支持列表 `[2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05, 2024-10-07]` |
| 4 | capabilities 只含 `tools` | `{"tools":{"listChanged":false}}` |
| 5–7 | `tools/list` 返回 10 个 tool，名字与契约一致，每个都带 `inputSchema` | 10/10 |
| 8 | DSH 侧命名形状 | `mcp__lacan-kb__search_passages` |
| 9–11 | `tools/call` 返回 8 段结构化证据 + `content` 文本兜底 + `evidence_state` 合法 | 8/8 段 |
| 12 | 返回的 `passage_id` **独立复核**存在于 canonical store | 3/3（store 内 249,105 条） |
| 13 | 第二个 tool 也可调用 | `resolve_entity("Symbolic") → concept.le-symbolique` |
| 14 | 未知 tool → 协议错误（不崩、不静默） | `MCP error -32602: unknown tool: 'write_canonical_truth'` |

复现：

```bash
node _scripts/_tools/mcp_client_proof.mjs
```

启动开销（实测）：进程启动 + `initialize` + `tools/list` + 一次 `search_passages`
**共 1.24 s**（系统 python3，向量路径不加载）。日志走 stderr：
`[lacan-kb-mcp] ready (protocol=2025-11-25, tools=10, vector=None)`。

---

## 2. 接入 DSH

### 2.1 行（row）

`dsh-mcp-client` 每个 server 一行；它的工具会以 `mcp__<serverName>__<tool>` 出现：

```yaml
# integrations/lacan-kb-mcp.row.yml 的内容（可直接粘贴）
- id: mcp-lacan-kb
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: lacan-kb            # → 工具名 mcp__lacan-kb__search_passages …
    transport: stdio
    command: python3
    args:
      - <REPO>/_scripts/_tools/lacan-kb-mcp
    cwd: <REPO>
    toolCallTimeoutMs: 120000       # 默认 60000；全库检索在冷启动时更慢，留足余量
    failOnStartupError: true        # 起不来就明确失败，而不是「工具神秘消失」
```

**为什么不需要 `isolate` realm**：`dsh-mcp-client` **不提供**任何 service ——
它只调用 `ctx.tools.register`，向 host 的 `tools` registry 注册工具（在
`node_modules/@deepseek-ai/dsh-mcp-client/lib/index.js` 里 grep 不到 `provide(`）。
按 Cordis 的平面规则，**只消费不提供的行必须待在 realm 之外**，
否则它解析不到 host 的那份 registry，就会「挂载了但什么都没贡献」。

### 2.2 装到哪个 preset

这一行属于 **agent preset 平面**（它为**一个会话**贡献工具）。
⚠️ **不要改 shipped preset**（`standard` / `ptc` / `minimal` / `cordis`）——
升级会覆盖它，而改坏 `cordis` 会让 preset authoring 本身失效。

推荐做法：**复制一份再改**。

在带有 preset authoring 能力的会话（例如 `cordis` 预设）里，用 roster 的 `copy`：

```js
// 挂一个临时 probe 插件，注入 agentPresets
await ctx.agentPresets.copy('standard', 'lacan-kb', '拉康知识库')
// → 在新 preset 的 agent.cordis.yml 末尾加上 §2.1 的那一行
await ctx.agentPresets.standingKeyFor('lacan-kb')   // 挂载校验
```

或手工建目录（本地 preset 归你所有，可以随意改）：

```bash
mkdir -p "${DSH_HOME:-$HOME/.dsh}/.agent-presets/lacan-kb"
# 把一份 standard 的 agent.cordis.yml 拷进去，追加 §2.1 的 row，
# 并写一个 preset.yml：
cat > "${DSH_HOME:-$HOME/.dsh}/.agent-presets/lacan-kb/preset.yml" <<'YML'
name: 拉康知识库
description: 标准模式 + lacan-kb MCP（只读知识访问层：证据、概念、溯源、缺口）
YML
```

然后**挂载校验**（这一步才叫验证，`list()` 的 `broken` 字段只是文件形状检查）：

```js
await ctx.agentPresets.standingKeyFor('lacan-kb')   // 正常返回 = 能挂载
```

最后请**用真实会话**确认工具列表里出现 `mcp__lacan-kb__*` ——
preset 决定工具 schema，只有真会话才能显示它产出的 agent。

### 2.3 用起来是什么样

模型看到 10 个工具：

```
mcp__lacan-kb__search_passages       mcp__lacan-kb__get_passage
mcp__lacan-kb__get_context           mcp__lacan-kb__resolve_entity
mcp__lacan-kb__get_concept           mcp__lacan-kb__find_concept_evidence
mcp__lacan-kb__trace_concept         mcp__lacan-kb__compare_concepts
mcp__lacan-kb__trace_source          mcp__lacan-kb__terminology_lookup
```

每次返回都是那 8 段：`request / resolution / retrieval / evidence / coverage /
provenance / warnings / evidence_state`。**答案由调用它的模型写**，
`citable_passages` 是唯一可引用的 id 白名单。

---

## 3. 接入 Codex

Codex 用一个 `[mcp_servers.*]` 表（`~/.codex/config.toml`）：

```toml
# integrations/codex-config.toml
[mcp_servers.lacan-kb]
command = "python3"
args = ["<REPO>/_scripts/_tools/lacan-kb-mcp"]
cwd = "<REPO>"
startup_timeout_sec = 20
```

Codex 侧工具名形状与 DSH 相同：`mcp__lacan-kb__<tool>`。

**校验方式**（不要只看配置文件写没写对）：

```bash
# 1. server 自身能起来并自检
python3 _scripts/_tools/lacan-kb-mcp --selftest        # 34/34 passed

# 2. 用真实 MCP 客户端握手一次（同一个 SDK）
node _scripts/_tools/mcp_client_proof.mjs              # 14/14 passed

# 3. 启动 Codex 后确认工具列表里有 mcp__lacan-kb__search_passages
```

> 具体字段名（`startup_timeout_sec` 等）随 Codex 版本可能变化 ——
> 以本机 `codex --help` / 该版本文档为准。上面 §1 的 SDK 级证明不依赖 Codex 的配置方言：
> 它证明的是**协议层面**这个 server 能被同样的客户端驱动。

---

## 4. 接入 Claude Desktop / 其它 MCP 客户端

```json
{
  "mcpServers": {
    "lacan-kb": {
      "command": "python3",
      "args": ["<REPO>/_scripts/_tools/lacan-kb-mcp"],
      "cwd": "<REPO>"
    }
  }
}
```

---

## 5. 排错

| 症状 | 原因 | 处理 |
|---|---|---|
| 工具列表里没有 `mcp__lacan-kb__*` | 进程起不来（装在哪台机器、python3 路径、`cwd` 不对） | 手动跑 `python3 _scripts/_tools/lacan-kb-mcp --selftest`；把 `failOnStartupError` 打开，让错误显式暴露 |
| 客户端解析响应失败 | 有东西往 **stdout** 写了非 JSON-RPC 内容 | 本 server 日志一律走 stderr；`test_14` 断言 stdout 行数 == 响应数 |
| `tools/call` 超时 | 全库检索冷启动（首次触碰 sqlite / 向量索引） | 调大 `toolCallTimeoutMs`（示例用 120000）；DSH 默认 60000 |
| `evidence` 为空 | 语料里确实没有该写法 | 看 `warnings` 里的 `NO_VOCABULARY_HIT` / `TERMS_NOT_IN_CORPUS` / `CONSTRAINT_RETURNED_NOTHING` —— 这三种**含义不同**，不要混着读 |
| 报 `-32602 invalid arguments` | 参数不合 schema（含**未声明**的参数） | 这是协议错误，不是「查不到」；契约见 `MCP_TOOL_CONTRACTS.md` |
| 向量路径不可用告警 | 运行在系统 python3（无 numpy） | 只影响辅助语义召回；`vector_enabled=false` + `VECTOR_UNAVAILABLE` 会如实上报，词法路径仍完整可用 |

---

## 6. 一个必须说清的边界

接进 DSH / Codex 之后，**模型看到的仍然是证据，不是结论**。
本层不会替模型下理论判断，也不会因为某条证据「看起来更相关」就把它标成更权威 ——
权威层级来自知识库自己的 `authority_level`（L0–L4），
而 `L4`（AI 生成）**永远不可能**是 `canonical`。
