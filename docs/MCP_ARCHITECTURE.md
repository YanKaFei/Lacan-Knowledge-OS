# MCP Architecture — Lacanian Knowledge OS（Phase 4A）

> 本文件说明 **Knowledge Access Layer** 的架构、边界与依赖。
> Tool 契约见 `MCP_TOOL_CONTRACTS.md`（由 `render_contracts.py` 从 `schemas.py` 渲染）。
> 接入方法见 `MCP_DSH_INTEGRATION.md`。

---

## 1. 这一层是什么，不是什么（§1）

**是** Knowledge Access Layer：把研究问题变成**结构化证据**。
**不是** Answer Generator：它**不写答案**，也不判断哪个理论解释正确。

```
        ┌──────────────────────────────────────────────────────────┐
        │ 调用方：DSH Agent / Codex / Claude Desktop / 人            │
        │   —— 它们负责「组织答案」                                  │
        └───────────────┬──────────────────────────────────────────┘
                        │  MCP（stdio, JSON-RPC）
        ┌───────────────▼──────────────────────────────────────────┐
        │ lacan-kb-mcp  ·  Knowledge Access Layer                   │
        │                                                           │
        │  schemas.py ─── 10 个 tool 的契约（唯一来源）              │
        │  server.py  ─── JSON-RPC / stdio framing / 错误分级        │
        │  argcheck.py ── 零依赖 JSON-Schema 子集校验                │
        │  knowledge_api.py ── 10 个 tool 的实现（**不重写检索**）    │
        │  query_terms.py ── 确定性查询规划（访问层新增）             │
        │  evidence_sufficiency.py ── 结构性证据判定（不看余弦）      │
        │  research_agent.py ── 只读多步研究（证据包 + trace）        │
        │  ontology_gaps.py ── 缺口**候选**队列（只发现，不修）       │
        │  citations.py ── 引用契约                                  │
        │  validate.py / selftest.py ── 独立校验与自检                │
        └───────────────┬──────────────────────────────────────────┘
                        │  只读调用
        ┌───────────────▼──────────────────────────────────────────┐
        │ Phase 3 检索层（**原样复用，不改一行**）                    │
        │  query_router · query_routing_policy · entity_resolution   │
        │  lacanian_semantic_guard · terminology_bridge              │
        │  lacan_search(FTS5) · full_corpus_retrieval(RRF k=60)      │
        │  MiniLM 向量索引（辅助，**不得强制启用**）                   │
        └───────────────┬──────────────────────────────────────────┘
                        │
        ┌───────────────▼──────────────────────────────────────────┐
        │ 唯一事实来源：Markdown/Obsidian Vault + canonical store    │
        │  _data/passage_store/*.jsonl（249,105 段，只读）            │
        │  _data/index/*（可重建的派生索引）                          │
        └──────────────────────────────────────────────────────────┘
```

**关键分工**：`knowledge_api` 不重新实现检索 —— 每个 tool 都调用 Phase 3 已验证的组件。
Phase 4A 只新增三件事：

1. **查询规划**（`query_terms.py`）：把自然语言问题变成「语料里真实存在的词」；
2. **证据判定**（`evidence_sufficiency.py`）：结构性判断「知识库是否支持这次研究操作」；
3. **多步研究**（`research_agent.py`）：按问题类别选工具、必要时重试、汇总证据包。

---

## 2. 传输与协议（§3）

| 项 | 值 |
|---|---|
| 传输 | **stdio 优先**（`lacan-kb-mcp`）；streamable-http 留待将来 |
| 协议版本 | `2025-11-25`（∈ DSH 的 `SUPPORTED_PROTOCOL_VERSIONS`） |
| framing | **换行分隔 JSON**（MCP stdio 规定），不是 LSP 的 Content-Length |
| capabilities | **只声明 `tools`** —— 不声明 resources/prompts（我们没实现，声明就是骗客户端） |
| stdout | **只能写 JSON-RPC**；所有日志走 stderr |
| tool 命名 | DSH 侧为 `mcp__lacan-kb__<tool>` |

`serve()` 返回处理过的输入行数，`test_14` 断言「stdout 行数 == 响应数」——
往 stdout 打一行日志就会毁掉协议，这条测试守着它。

---

## 3. 错误分级（MCP 规范）

错误分两类，**不能混**：

| 类别 | 例子 | 表现 |
|---|---|---|
| **协议错误** | 未知 tool、参数不合 schema、缺必填参数 | JSON-RPC `error`，code `-32602` |
| **执行结果** | 查不到证据、`PASSAGE_NOT_FOUND`、约束下为空 | 正常 `result`：`warnings` + `evidence_state` |

为什么必须分：把「你调错了」和「查了但没查到」混成一个 `isError: true`，
调用方就再也无法区分 —— 而这恰恰是 §7 要判的那件事。

---

## 4. 输出契约（§6）

每个 tool 都返回**同一套 8 段**（顺序固定）：

```
request · resolution · retrieval · evidence · coverage · provenance · warnings · evidence_state
```

`structuredContent` 装这 8 段；`content[0].text` 是同一份 JSON 的文本兜底
（不声明 `outputSchema`：嵌套结构声明成协议级 schema 只会让客户端因为小差异拒收）。

**不变量**（`validate.py` 独立复核，不看 tool 自报）：

* `evidence[].passage_id` **必须**存在于 canonical store —— 否则直接判 `FABRICATED`；
* `warnings` 不得为空时省略（无告警必须是 `[]`）；
* `evidence_state.method` 固定为 `structural_only_no_cosine_threshold`；
* 响应里不得出现 `mutations` / `writes`。

---

## 5. 三个「看起来都像检索」的 tool（§5）

这是本层最容易做错的地方 —— 三个 tool 若互为别名，就等于只有一个 tool：

| tool | 研究操作 | 实体约束 | 每概念 lane | 历时分组 |
|---|---|---|---|---|
| `search_passages` | 「这个**问题**在语料里有什么」 | 否（按 route 决定） | 按 route | 否 |
| `find_concept_evidence` | 「**这个概念**的证据在哪」 | 是 | 1 | 否 |
| `trace_concept` | 「这个概念的**历时**状态」 | 是 | 按 period 分组 | **是** |

三者由 `test_phase4a_mcp.py::test_03` 与 `RESPONSIBILITY_MATRIX` 断言，不允许合并。

---

## 6. 只读保证（§2/§21）

* **静态**：任何 tool 的参数名里出现 `set/write/update/delete/…` 都直接失败
  （`FORBIDDEN_PARAM_PATTERNS`，`test_09` + `selftest` 第 18 项）；
* **动态**：`check_phase4a_readonly.py` 跑完全部 10 个 tool + 多轮 Research Agent，
  对 19 个受监控文件（canonical store + **concept/relation 文件** + 索引 + 原始语料）
  做**逐字节哈希**前后比对；
* 唯一会落盘的是 `_data/ontology_gap_queue.jsonl`（派生发现记录，§22），
  且只在 `record_gaps=True` 时追加，每行都是 `status: candidate`。

**§27 的 11 项硬门禁**（`check_phase4a_hard_gates.py`）把这一层新增的风险面逐条钉死：
参数/名字含写入词根、canonical/索引/原始语料被改、编造 `passage_id`、
`L4 → canonical` 写入路径、缺口队列状态、未声明参数被静默接受、
`evidence_state` 含 confidence/cosine、自动修复缺口的代码路径 —— 全部必须为 **0**。

最近一次结果：`_data/index/READONLY_GATE.json`（10/10 passed，11.22 s）、
`_data/index/PHASE4A_HARD_GATES.json`（11/11 gates = 0）。

---

## 7. 确定性

* 查询规划是**规则式**的（删疑问片段 → 取别名/词 → 探测词表），没有随机、没有模型调用；
* 证据判定只读结构性信号，没有阈值拟合；
* `render_contracts.py --check` 保证文档与 `schemas.py` 不漂移；
* Research Agent 的 trace 由 `_data/eval/research_traces/` 落盘，可逐条核对。

---

## 8. 部署与运行

```bash
# 以 stdio 提供 MCP（给 DSH / Codex / Claude Desktop）
python3 _scripts/_tools/lacan-kb-mcp

# 自检（34 项确定性契约检查，不连网络、不写 canonical）
python3 _scripts/_tools/lacan-kb-mcp --selftest
python3 _scripts/_tools/lacan-kb mcp-tools        # 打印 10 个 tool 契约摘要

# 完整验收
python3 _scripts/_tools/check_phase4a_readonly.py       # 只读硬门
python3 _scripts/_tools/render_contracts.py --check     # 文档同步
python3 _scripts/_tools/check_phase4a_completion.py     # §28 20 条判据
```

运行时依赖：**只需标准库 + numpy/onnxruntime（向量路径可选）**。
无 `mcp` Python SDK 依赖 —— server 是手写的零依赖实现（见 `PHASE4A_FINDINGS.md` §0）。
