# `mcp_server` — Phase 4D.1 Scholarly Research MCP Service

```
DeepSeek Harness / Agent / UI / Obsidian
        ↓  MCP（JSON-RPC 2.0 over stdio）
  mcp_server/        ← 本包：transport + schema 校验 + 编排 + 审计
        ↓  只允许 import scholarly_api
  scholarly_api v1   ← Phase 4D.0 冻结的稳定访问层
        ↓
  FROZEN SCHOLARLY CORE（_data/core_freeze/scholarly_core_freeze_v1.json）
```

MCP 层**不是**研究引擎：它不重写、不摘要、不改写任何 scholarly 内容。
实证不变式（测试守着）：`core final answer == api final answer == MCP result`。

## 运行

```bash
python3 mcp_server/server.py              # stdio server（给 MCP client 用）
python3 mcp_server/server.py --selftest   # 打印工具清单 + core freeze 校验
python3 _scripts/_tools/check_mcp_contract.py   # 只读契约自检（套件也用它）
```

MCP client 配置（Claude Desktop / Cursor / DSH）：

```json
{"mcpServers": {"lacan-research": {
  "command": "python3",
  "args": ["<REPO>/mcp_server/server.py"]}}}
```

## 工具（v1，10 个，全部只读）

| 工具 | 返回 |
|---|---|
| `lacan.research` | `FinalScholarlyAnswer`（默认 `provider="mock"`，确定性、离线） |
| `lacan.search_passages` | `PassageSearchResult`（词法为主；`meta.dense_available` 如实报告） |
| `lacan.get_passage` | `PassageRecord` |
| `lacan.get_context` | `PassageContext`（before/after ≤ 20） |
| `lacan.get_concept` | `ConceptRecord`（canonical ontology 只读） |
| `lacan.get_seminar` | `SeminarRecord` |
| `lacan.trace_source` | `ProvenanceRecord`（`SOURCE_TRACE_INCOMPLETE` 原样保留） |
| `lacan.compare_terms` / `lacan.research_diachronic` / `lacan.research_translation` | `FinalScholarlyAnswer`（specialized ResearchRequest → `scholarly_api`，**不另写引擎**） |

信封：`{ok:true, result:<scholarly payload>, meta:{...}}` 或
`{ok:false, error:{code,message,detail,resolution}, meta:{...}}`。
工具级错误码：`INVALID_REQUEST / NOT_FOUND / SCHEMA_VALIDATION_FAILED /
PROVIDER_UNAVAILABLE / CORE_FROZEN_MISMATCH / INDEX_UNAVAILABLE / POLICY_DENIED /
INTERNAL_ERROR / TIMEOUT`。**永不返回 traceback。**

## 纪律

* **弃权原样传播**：核心 `ABSTAINED` → MCP `ABSTAINED`；任何 wrapper / Agent 都不得补答。
* **provider**：默认 `mock`；`llm` 必须显式请求，凭据缺失 → `PROVIDER_UNAVAILABLE`。
* **core freeze guard**：启动即校验（子进程跑 `core_freeze.py --verify`）；漂移 → 所有
  工具 `CORE_FROZEN_MISMATCH`（fail closed），不在漂移状态下服务。
* **安全**：只接受领域参数（`passage_id`/`concept_id`/`seminar_id`/`query`/过滤器），
  拒绝路径穿越、绝对路径、命令拼接（`$( )`/反引号/`&&`/`||`）、SQL 样式串、控制字符、
  未声明字段；schema 错误**不回显**用户输入。
* **审计**：`_data/product_audit/mcp/audit-YYYY-MM.jsonl`，默认记 `question_hash`
  （`LACAN_MCP_AUDIT_QUESTION=1` 才记全文），永不记凭据。
* **超时**：分类超时（lookup 30s / search 60s / research mock 300s / llm 1800s，可用
  `LACAN_MCP_*_TIMEOUT_S` 覆盖）；串行执行，不杀线程（超时如实返回 `TIMEOUT`）。
* **只读**：本阶段 MCP 不实现任何 canonical 写操作（改 ontology / Gold / mapping 需
  另行设计 review workflow）。

## 环境变量

| 变量 | 作用 |
|---|---|
| `LACAN_MCP_FREEZE_GUARD=0` | 关闭启动期冻结校验（**仅测试**） |
| `LACAN_MCP_AUDIT=0` | 关闭审计 |
| `LACAN_MCP_AUDIT_QUESTION=1` | 审计记录问题全文（默认只记 hash） |
| `LACAN_MCP_LOOKUP_TIMEOUT_S` / `SEARCH` / `RESEARCH_TIMEOUT_MOCK_S` / `RESEARCH_TIMEOUT_LLM_S` | 分类超时 |
