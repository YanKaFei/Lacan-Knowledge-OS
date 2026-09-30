# Lacan Knowledge OS — 开发与审计指南

> 面向**开发者 / 审计者**：架构边界、冻结纪律、写边界、测试与验收怎么跑、
> 缺陷该往哪里提。使用者文档见 `USER_GUIDE.md`。
>
> 本文件描述的是**仓库现状**；每条命令都在本机验证过。凡未实现的能力都写明。

---

## 1. 一句话架构

```
PRODUCT 层（可演化）
  workspace_ui/    浏览器 UI + 本地 HTTP API（stdlib http.server）
  mcp_server/      MCP stdio 适配器（10 个工具）
  obsidian_adapter/ 受管笔记写入
  browse_api/      只读浏览（概念/段落/术语/期数）
  project_api/     研究项目（USER_WORKSPACE）
  export_system/   导出与引文（四格式 + bundle）
        │  只允许经下面这 4 个产品侧门面访问核心
        ▼
PRODUCT-SIDE FACADE
  scholarly_api/   objects / policy / core（研究调用入口）
        │
        ▼
FROZEN SCHOLARLY CORE（冻结：语义不得由产品改动）
  scholarly_api/core.py、synthesis_*、research_*、eval_*、lacan_search …
```

**硬规则**：产品层**不许**直接 import 核心内部模块。
`check_project.py` / `check_export.py` 用 AST 扫描产品模块的 import，
命中 `BANNED_MODULES`（`knowledge_api`、`research_answer`、`research_contract`、
`research_execution`、`synthesis_*`、`eval_integrity`、`hybrid_retrieve`、
`lacan_search`）即失败。加产品功能时若需要核心数据，**加门面方法**，不要穿透。

---

## 2. 冻结核心（frozen core）

### 2.1 冻结了什么

`_data/core_freeze/scholarly_core_freeze_v1.json` 用 sha256 钉住 **39 个语义单元**
（研究契约、执行调度、充分性、综合边界、claim 原子化、蕴含校验、修复规则、
引用策略、来源角色、弃权策略、Gate 13/19/20/21、检索通道、本体、Gold …）。

```bash
python3 _scripts/_tools/core_freeze.py --verify     # 39/39
python3 _scripts/_tools/core_freeze.py --show       # 看清单
python3 _scripts/_tools/freeze_lineage.py --verify  # 4 段谱系，核心语义变化 = 0
python3 _scripts/_tools/freeze_lineage.py --show
```

`freeze_lineage.json` 记录 4D.0 → 4D.1 → 4D.2 → … 的冻结谱系，其中
`scholarly_semantic_changes == 0`：**产品阶段没有动过核心语义**。

### 2.2 冻结失败的处置

冻结校验失败 = 有人改了核心（或改了清单）。**不要**重新生成清单来「修好」它。
正确顺序：

1. `core_freeze.py --show` 定位哪些单元哈希变了；
2. 判断是不是**产品该做**的改动（几乎总是「不是」）；
3. 是核心缺陷 → 走 §8 的核心变更请求；
4. 只有进入新的 Scholarly Remediation Phase、并完成学术复评（Gate / Human Review）
   才允许升版本重建清单。

---

## 3. 写边界（write policy）

`scholarly_api/policy.py` 把所有路径分成 5 类，任何写入都要过闸门：

| 类 | 含义 | 允许产品写 |
|---|---|---|
| `IMMUTABLE_CORE` | 冻结核心源码 / 清单 | ❌ 直接拒绝（`CoreMutationError`） |
| `REBUILDABLE_MACHINE` | 索引、缓存 | ✅ 可重建 |
| `CANONICAL_KNOWLEDGE` | 本体 / passage store / Gold / 评测 | ⚠️ 必须带 `review_token` |
| `USER_WORKSPACE` | `_workspace/**`（history/projects/exports/notes） | ✅ 自由 |
| `UNKNOWN` | 其他 | ❌ 拒绝 |

```python
from scholarly_api import policy as POL
POL.classify("_workspace/exports/x.md")            # → 'user_workspace'
POL.assert_writable("_data/ontology/v4a1/entities.jsonl")   # → CoreMutationError
POL.write_json("_workspace/history/x.json", {...})          # 唯一推荐写入口
```

产品侧**只**用 `assert_writable` / `write_text` / `write_json`；不要直接 `open(...,'w')`
写核心路径。原始语料目录（`<HOME>`）在任何分类下都只读。

---

## 4. 测试与检查器

### 4.1 一键全量

```bash
bash _scripts/run_all_tests.sh           # 完整（约 30 分钟空载；高负载时会显著变长）
bash _scripts/run_all_tests.sh --quick   # 跳过慢套件（会出现 SKIP，不得据此判 green）
```

* 套件**自动发现**：`_scripts/_tests/test_*.py`（清单写死会漂移，实测踩过）；
* 退出码 0 且 `failed_suites == []` 才算全绿；
* 结果落盘 `_data/index/TEST_RUN.json`（`suites` / `checks` / `failed_suites` /
  `skipped` / `recorded_at`），这是**可核记录**，不是一句「测试通过」；
* 逐套件耗时：`run_all_tests.sh` **不**落盘 timing 文件；unittest 的
  `Ran N tests in X.XXXs` 走 stderr，所以把两个流合并重定向即可事后确定性还原：

  ```bash
  bash _scripts/run_all_tests.sh > /tmp/reg.log 2>&1
  python3 _scripts/_tools/summarize_regression_timing.py /tmp/reg.log out.tsv
  ```
* `--quick` 的 SKIP 会进 `skipped`，验收要求 `skipped == []`。

### 4.2 契约检查器（每个阶段一个）

| 检查器 | 守什么 |
|---|---|
| `check_mcp_contract.py` | 10 工具、严格 schema、错误信封、fail closed、审计、freeze 门 |
| `check_workspace_ui.py` | 状态视图、静态资源、写入边界、无 `innerHTML` |
| `check_obsidian_integration.py` | vault 复用、工作区隔离、wikilink、冻结不变 |
| `check_explorer.py` | browse 只读、分层、ESM 语法、分页、冻结 |
| `check_project.py` | USER_WORKSPACE、项目内容不进 evidence、revision 冲突、冻结 |
| `check_export.py` | 四格式身份一致、bundle 自检、citation 能力、冻结 |
| `check_core_change_requests.py` | CCR schema / 唯一性 / 状态机 |
| `validate_vault.py` | vault 结构与来源可回查 |
| `check_accessibility.py`（4D.7，**不进 Gate**） | §72 无障碍：lang / viewport / skip-link / 可访问名 / 标题层级 / 无内联处理器 |
| `summarize_regression_timing.py`（4D.7，**不进 Gate**） | 从完整回归日志确定性还原逐套件耗时 |
| `phase4e_real_provider_run.py` | 14 题真实 provider 回归（sealed；Gate20/21 复算、D2 对照） |
| `phase4e_product_delta.py` | 真实 provider 的产品 delta 验证（A/D/F + 四格式 + Project + Obsidian） |
| `phase4e_freeze_record.py` | 冻结修复记录（父/新 hash、变化组件、语义影响、CCR） |
| `phase4e_acceptance.py` | Phase 4E Remediation Gate v1 的冻结与判定（E1–E17） |
| `phase4e_secret_audit.py` | 运行工件凭据泄漏审计（§68） |
| `phase4e_regression.py` | 全量回归 + `_data/phase4e/regression.json` |
| `phase4e_spot_review_packet.py` | 人工抽查的输入材料（只读，不评分） |

这些检查器**同时**被 `run_all_tests.sh` 调用（它的 `checks` 计数就是它们）。

### 4.3 套件规格（阶段 → 规模）

| 阶段 | 套件 / 断言 |
|---|---|
| 4D.3 Obsidian | 16 套件 / 101 |
| 4D.4 Explorer | 15 / 112 |
| 4D.5 Projects | 16 / 116 |
| 4D.6 Export & Citation | 19 / 165 |
| 4D.7 验收 | `product_acceptance.py`（见 §5） |

共享测试库：`_ui_testlib.py`（Chrome 渲染 + 本地 HTTP 客户端）、
`_obsidian_testlib.py`、`_explorer_testlib.py`、`_project_testlib.py`、
`_export_testlib.py`。

**浏览器渲染的已知坑（务必照抄现有写法）**：

* 本机 Chrome 写完 `--dump-dom` / `--screenshot` **不会自己退出** →
  `_ui_testlib.chrome_render` 用「轮询产物 + 稳定 1s + kill」看门狗；
* 只有当看门狗是**超时**退出才允许 `retries=1`，这是对浏览器卡住的容忍，
  **不是**对断言失败的重试；
* URL 组装：调用方带不带前导 `?` 都要能落到 `/?q=...`。写成 `??q=...` 时
  `URLSearchParams` 会把键解析成 `?q`，autorun 深链静默不执行，
  表现为「页面是空壳」的假红（4D.7 实测踩过，已在 `Runner.dom` 统一修掉）。

---

## 5. 产品验收（Phase 4D.7）

### 5.1 工具

```bash
python3 _scripts/_tools/product_health.py            # 9 层健康（core/corpus/browse/mcp/
                                                     # workspace/obsidian/exports/projects/provider）
python3 _scripts/_tools/product_acceptance.py --preflight    # 健康 + fixture，不跑场景
python3 _scripts/_tools/product_acceptance.py --scenarios    # 场景 A–F + 指标（不含长回归）
python3 _scripts/_tools/product_acceptance.py --full         # 完整验收（含 run_all_tests.sh）
```

### 5.2 Gate 与纪律

* Gate 冻结在 `_data/product_acceptance/product_acceptance_gate_v1.json`
  （12 条判据 A1–A12；`frozen: true`，`frozen_before_final_run: true`）。
  **冻结之后不得修改判据、场景或阈值**。
* 判定只有两个值：`PRODUCT_READY` / `PRODUCT_NOT_READY`。
  它**不**重判 `SCHOLARLY_CORE_READY`（`not_rejudged` 字段明写）。
* 未解决的 BLOCKER 或 MAJOR → `PRODUCT_NOT_READY`；MINOR 可以留，但必须列进
  报告的限制清单。
* 一次 run 发现缺陷 → 该 run 记 `FAILED`，修完**新开一个 run**，
  **绝不**把旧 run 改成 PASS。

### 5.3 工件

每次 run 落在 `_data/product_acceptance/<run_id>/`：

```
manifest.json        run_id / head / gate + gate_hash / 冻结哈希 / 环境
matrix.json          40 条步骤的 expected/observed/status/blocking
metrics.json         健康 9 层 + canonical 未变 + 用户区保留
timing.json          逐操作耗时 + 分类 + 浏览器重试记录 + 回归逐套件耗时
final_decision.json  A1–A12 + 最终判定
screenshots/         场景截图（A–F）
logs/                回归日志、DOM 转储、逐套件 timing.tsv
```

隔离：`make_fixture(run_id)` + `isolate()` 把 `OBSIDIAN_VAULT_PATH`、
`export_system.policy.EXPORT_ROOTS["default"]`、`project_api.store.PROJECTS_DIR`、
`workspace_ui.server.config.HISTORY_DIR` 指向 `_workspace/acceptance/<run_id>/`，
跑完恢复。**验收绝不污染真实 vault / 用户工作区**。

> 读隔离后的真实根目录要用 `project_api.store.PROJECTS_DIR`；
> 包级 `PA.PROJECTS_DIR` 是导入时快照，直接读会报出错的路径（实测踩过）。

### 5.4 时间与性能

只**测量 + 分类**（`interactive-fast` < 1.5s / `interactive-wait` 1.5–30s /
`provider-bound` 30–300s / `batch` > 300s），**不设**拍脑袋阈值。
机器高负载只解释「为什么慢」，不作为产品缺陷。

### 5.5 Phase 5A 呈现边界（presentation boundary）

Phase 5A 只做**产品呈现层 / 可访问性 / 运行接口**的加固，**不动学术语义**。

**分词法**（`_data/product/presentation_taxonomy_v1.json`，冻结）：

| 类别 | 判定依据（确定性，禁止猜） | 默认出口 |
|---|---|---|
| `SCHOLARLY_CONTENT` | 已通过验证的学术断言 / 结构 | 用户面 |
| `SCHOLARLY_LIMITATION` | 关于**证据本身**成立的结论（L2-only、`SOURCE_TRACE_INCOMPLETE`、无法建立历时转变） | 用户面 |
| `AUDIT_DIAGNOSTIC` | 校验器 / 修复器 / 生成器的**工程记录**（逐条 rejected、entailment 判定、计量摘要） | Audit 面（**100% 保留**） |
| `OPERATIONAL_ERROR` | `PROVIDER_UNAVAILABLE` / `CORE_FROZEN_MISMATCH` / `WORKSPACE_CONFLICT` / `INVALID_REQUEST` | 错误通道 |

**唯一实现入口**：`workspace_ui/server/presentation.py`（纯函数、无网络、无 LLM、
不依赖关键词猜测）。**禁止**用正则或 LLM 重新判定语义类别。

**为什么清洗发生在 `scholarly_api/core.py::_final_answer` 而不是 UI**：
如果只在 UI 隐藏，MCP / Obsidian / Export / Project 快照 / API 消费者**都会收到**
同一段工程文本（实测 `_workspace/exports/exp_research_20260925T211020Z_023db8f0.md`
内含 `NOT_ENTAILED`）。清洗必须在**产品边界的出口**，且**按结构化字段重建 + 行级
精确比对**（对照 `answer["rejected_claims"]`），**不写脆弱正则**；重建格式一旦漂移，
测试立刻变红（fail-soft，宁可少删也不误删学术内容）。

**向后兼容（必须守住）**：RC1.1 之前的历史答案是 schema `v1`（没有 `audit_diagnostics`）。
它们**不被改写**：快照与项目里保持原样，`UserFacingAnswerView` 在**呈现时**按 legacy
规则路由，`AuditAnswerView` 标 `derived_from_legacy: true` 并保留
`legacy_routed_text`（**内容永不丢失**）。

**schema 版本纪律**：`FinalScholarlyAnswer` 加字段 ⇒ 版本号必须升
（`final-scholarly-answer/v1` → `v1.1`），`ANSWER_SCHEMA_VERSIONS_SUPPORTED`
两个都接受，`$id` 跟随版本。新增字段**不得**改变既有字段的值。

**验证（每次验收都跑）**：

```bash
python3 -m unittest discover -s _scripts/_tests -p "test_phase5a_*.py"
python3 _scripts/_tools/phase5a_acceptance.py --run          # H1–H14
python3 _scripts/_tools/phase5a_acceptance.py --freeze-gate  # Gate 未被事后改动
python3 _scripts/_tools/phase5a_freeze_record.py --check     # 冻结段与自身快照一致
python3 _scripts/_tools/check_accessibility.py               # 9 视图
```

**§58 一致性铁律**：呈现更干净 **≠** 学术答案变了。每次验收都断言
`user_facing_view(payload)` 的 `claims / citations / answer_state / source_limitations`
与核心载荷**逐字段相等**；不等就是 BUG，不是"优化"。

### 5.6 冻结的三类变化：学术语义 / 产品边界 / 数据版本（P5A-006 已解决）

**冻结 SPEC 声明三类组件**（`core_freeze.py::component_classes`，写进 manifest）：

| 类 | 成员数 | 变化后果 |
|---|---|---|
| `scholarly_semantic` | 30 | **硬失败** `SEMANTIC_DRIFT`（prompt / judge / contract / retrieval / sufficiency / ClaimAtom / entailment / repair / citation / source-role / abstention / Gate13·19·20·21 / Gold / Human Review / readiness gate / D2 identity） |
| `product_boundary` | 3 | 记为 `product_runtime_changes`（**不失败**）：`scholarly_api_{core,objects,policy}_hash` |
| `data_version` | 6 | 必须**逐条声明且依赖构件状态一致**：`corpus_inventory_hash` / `passage_store_version` / `passage_store_passages_sha256` / `retrieval_index_lexical` / `retrieval_index_vector` / `ontology_version` |

**根因（曾经的 P5A-006）**：`core_freeze.py` 早就用注释块「# ── 数据版本」标出这 6 个组件，
但 `freeze_lineage.py` 只认识两类（`PRODUCT_BOUNDARY_KEYS` / 其余皆为语义），于是
「语料清单长大一个文件」被算成**学术语义变化** → 谱系必然 FAIL；而如实重建基线同样 FAIL。
**分类实现缺陷**，不是语义漂移。现在按 `core_freeze.component_class()` 判定。

**`freeze_lineage` 的四种结果**：

```text
语义哈希变化                        → FAIL  SEMANTIC_DRIFT
已声明且一致的 data_version 变化     → PASS  semantic=0, data_version=N
无法定位组件类的哈希变化             → FAIL  UNCLASSIFIED_DRIFT
data 变化但依赖构件状态不一致         → FAIL  DATA_VERSION_INCONSISTENT
data_version 组件变化但没有声明       → FAIL  UNDECLARED_DATA_DRIFT
```

**没有 wildcard 豁免**：不允许 `if hash_changed and not semantic: allow`，也不允许把
`_data/**`、`corpus/**` 整片当数据版本。**只有 SPEC 明确声明的组件**才可能被判为 data_version。

**数据版本的声明怎么写**（`_data/core_freeze/data_version_declarations.json`，由
`phase5a_declare_data_version.py` 依据真实差异审计生成，字段不得留空）：

```json
{"component":"corpus_inventory_hash",
 "before_hash":"…","after_hash":"…",
 "reason":"外部语料目录新增 1 个文件；学术语义组件全部未变",
 "source_diff":{"added":1,"removed":0,"modified":0,"unchanged":143,
                "audit_artifact":"_data/phase5a/corpus_diff_audit.json"},
 "ingestion_status":"SOURCE_INVENTORY_ONLY",
 "canonical_passage_store_changed":false,
 "dependent_artifacts":{"passage_store":"UNCHANGED_BY_DESIGN","lexical_index":"UNCHANGED_BY_DESIGN",
                        "vector_index":"UNCHANGED_BY_DESIGN","graph_cache":"UNCHANGED_BY_DESIGN",
                        "corpus_inventory":"CHANGED"},
 "verified_at":"…","scholarly_semantic_hashes_unchanged":true}
```

依赖构件状态只能取 `CHANGED` / `REBUILT` / `UNCHANGED_BY_DESIGN` / `UNAVAILABLE`；
一致性规则（不一致即 `DATA_VERSION_INCONSISTENT`）：

* `passage_store` ∈ {CHANGED, REBUILT} ⇔ `passage_store_version` 与 `passage_store_passages_sha256` **都变**；
  若为 UNCHANGED_BY_DESIGN / UNAVAILABLE 则**都不得变**（防 `inventory=新 / index=旧`）；
* `lexical_index` ⇔ `retrieval_index_lexical`；`vector_index` ⇔ `retrieval_index_vector`；`corpus_inventory` ⇔ `corpus_inventory_hash`；
* `ingestion_status == "INGESTED"` ⟹ passage store 必须真的变过（否则是在宣称检索能力）。

**推进冻结的正确流程**（顺序固定，且**绝不覆盖**旧段）：

```bash
# 1) 真实差异审计（基线 = manifest 钉住的那份 inventory，哈希核对不过就拒绝运行）
python3 _scripts/_tools/phase5a_corpus_diff.py
# 2) 生成声明（只有 SPEC 声明为 data_version 的组件才能声明）
python3 _scripts/_tools/phase5a_declare_data_version.py
# 3) 重建 manifest（记录 component_classes + 声明）
python3 _scripts/_tools/core_freeze.py --build
# 4) 把新字节快照进 history/（旧段字节原样保留）
cp _data/core_freeze/scholarly_core_freeze_v1.json \
   _data/core_freeze/history/scholarly_core_freeze_v1.<new-segment>.json
# 5) 谱系新增一段 + 复验
python3 _scripts/_tools/phase5a_freeze_record.py --segment <new-segment> --record-only
python3 _scripts/_tools/freeze_lineage.py --build && python3 _scripts/_tools/freeze_lineage.py --verify
python3 _scripts/_tools/core_freeze.py --verify
```

**验证**：

```bash
python3 -m unittest discover -s _scripts/_tests -p "test_phase5a_lineage_classification.py"
#   含 test_lineage_semantic_change_fails / _declared_data_version_change_passes /
#      _unknown_change_fails / _data_change_without_manifest_fails /
#      _data_change_with_stale_index_fails / _product_runtime_change_classified
#   以及真实 fixture：语料 143 → 144（semantic=0 / data_version>0）
python3 _scripts/_tools/phase5a_corpus_diff.py            # exit 3 = 存在未解释变化
python3 _scripts/_tools/phase5a_declare_data_version.py --check
```

---

## 6. 导出与引文怎么核验

* 三层哈希：`source_answer_hash`（核心载荷身份）、`export_payload_hash`
  （规范化文档身份，**与格式无关**）、`content_hash`（该文件内容）。
  同一份 `ExportDocument` 渲染成四种格式时，`export_payload_hash` 必须相同。
* 三个 schema：`export_document_v1` / `research_bundle_manifest_v1` /
  `citation_record_v1`，全部 `additionalProperties: false`。
* Bundle 自检：

```bash
python3 - <<'PY'
import export_system as EX
print(EX.verify_bundle("_workspace/exports/<bundle 目录>"))   # status == 'VERIFIED'
PY
```

`bundle_hash` 覆盖 manifest 里除 `bundle_hash` / `zip` 之外的全部字段；
被篡改的 bundle 必须**验证失败**，不允许「验证通过但内容是坏的」。

* 引文：`internal-short|internal-full|provenance` 恒可用；
  `chicago|mla|apa|bibtex` 仅在书目元数据齐全时可用，否则
  `BIBLIOGRAPHIC_METADATA_INCOMPLETE`（**不许编造**）。
* 审计：`_workspace/exports/audit.jsonl`。

---

## 7. Obsidian 适配器

* 受管根：`_workspace/obsidian_vault`（可用 `OBSIDIAN_VAULT_PATH` 覆盖，
  相对路径按项目根解析）。
* 生成区：`<!-- LACAN-OS:GENERATED:START --> … <!-- LACAN-OS:GENERATED:END -->`；
  `## My Notes` 之外的用户区**逐字节保留**（每次写入前后比对）。
* 受控 YAML：只经 `dump_frontmatter` 输出，字段固定。
* 映射账本：`_System/mappings/entity_note_map.json`、`project_note_map.json`
  是「实体 ↔ 文件」的权威；已存在的**非受管**文件只登记不重写
  （`managed: false`, `reason: existing_unmanaged`）。
* 同标题冲突：`<title> (2).md`，**不**接管别人的 hub。

---

## 8. 核心缺陷 → CORE_CHANGE_REQUEST（不许直接改核心）

```
PRODUCT ISSUE → _core_change_requests/requests/CCR-XXXX.json
             → 三方分诊（产品 / 学术 / 工程）
             → 只有新开 Scholarly Remediation Phase 才允许改核心
```

```bash
cp _core_change_requests/TEMPLATE.json _core_change_requests/requests/CCR-0002.json
python3 _scripts/_tools/check_core_change_requests.py --verify
```

状态机：`OPEN → TRIAGED → {ACCEPTED_FOR_REMEDIATION | REJECTED | DEFERRED}`，以及 `ACCEPTED_FOR_REMEDIATION → RESOLVED`（**只有在 Gate 的****全部判据——含 E14 的真实人工复核——PASS 后**才允许 RESOLVED）。
任何情况下都**不得**改已封存 run、Human Review 记录、Gold 基线、
Scholarly Readiness Gate v1 规则。

**已登记的核心缺陷**：

* `CCR-0001`（`S1_CORRECTNESS`，**技术修复 COMPLETE / 状态 ACCEPTED_FOR_REMEDIATION**，resolution_phase = Phase 4E）：
  > **acceptance semantics audit（2026-09-26）**：冻结 Gate 的 **E14 逐字要求 `human spot review`**，而本阶段实际完成的是 **agent-mediated 预审**（`_data/phase4e/agent_pre_review.jsonl`）——**不构成** E14 证据。因此 `CCR-0001` 在人工复核闭合前**不得 RESOLVED**；材料包 `_data/phase4e/human_review_packet/`，闭合评估 `_scripts/_tools/phase4e_human_closure.py`。以下为**技术**修复摘要：
  `provider=llm` 时产品门面把低层 completion provider（只有 `complete()`）当成
  synthesis adapter 使用，必然抛 `AttributeError: … has no attribute 'synthesize'`。
  **修复方式 = reuse 既有实现**：`scholarly_api/core.py` 的 llm/mock 分支改经
  `synthesis_adapters.make_adapter()` 选择 adapter（真 provider 被**包进**
  `ScholarlySynthesisAdapter`）；provider 失败的错误翻译 + 内部子分类 + 凭据脱敏；
  冻结的 D2 验证 engine（`synthesis_adapters.py` / `synthesis_contract.py` …）
  **逐字节未改**。冻结谱系新增第 5 段（`phase=4E, ccr=CCR-0001`），
  39 个组件里只有 `scholarly_api_core_hash` 变化（产品边界）。

### 8.1 real provider wiring 纪律（Phase 4E 之后）

1. **completion provider ≠ synthesis adapter**：只有 `complete(system, user, schema)`
   的对象**不能**交给 synthesis boundary；必须经 `make_adapter(name, provider)`
   得到 `synthesize()` + `.provider` 都齐的 adapter。
2. 选择点只有一个：`synthesis_adapters.make_adapter()`。禁止在别处 `if provider:`
   直接构造并调用。
3. 凭据只认核心读的那两处：`DSH_SYNTHESIS_API_KEY` 或
   `~/.dsh/.credentials.yaml` 的 `DEEPSEEK_API_KEY:` 行；不要臆测别的环境变量。
4. provider 失败**保持公开错误码稳定**（`PROVIDER_CALL_FAILED` /
   `PROVIDER_UNAVAILABLE`），子分类放内部 `detail.provider_diagnostic`
   （AUTH / RATE_LIMITED / TIMEOUT / BAD_RESPONSE / CONNECTION / ADAPTER_ERROR）。
5. 对外文本一律过 `_redact_secrets()`（key / `Authorization: Bearer` / `sk-…`）。
6. **拒绝 fallback**：无凭据或 provider 故障时返回错误，绝不用 mock 或模型知识补答。

---

## 8.2 验收模型：AI-only 多代理盲审（acceptance-policy v2）

> 这是**策略版本变更**，不是对历史 Gate 的改写。

### 为什么 human review 不再是 release blocker

项目所有者已正式决定：**当前项目不存在可执行的人类学术 reviewer**。因此停止等待
human spot review，并且**不允许**伪造、模拟、或把 AI reviewer 标记为 human。Phase 4E 改用
明确标注为 AI-only 的独立多代理学术验收协议（`AI_MULTI_AGENT_BLIND_REVIEW_V1`）。

历史事实**永久保留**：`_data/phase4e/phase4e_remediation_gate_v1.json` 的
`E14 = human spot review FAIL = 0` 状态永远是 `PENDING`
（`reason = NO_HUMAN_REVIEWER_AVAILABLE`），不得改成 PASS、不得改名、不得伪造
`reviewer_name`/`reviewed_at`。Gate v2 只**替换 E14 的证据类型**，E1–E13/E15–E17
逐字不变，阈值未降低。**`human_review_performed = false` 永久保留。**

### 协议与 lane 独立性

| lane | 角色 | 输入 | 独立性 |
|---|---|---|---|
| A | Lacanian scholarly reviewer | **只**盲审包 | fresh session，不读其它 lane |
| B | adversarial falsification reviewer | **只**盲审包 | fresh session，不读其它 lane |
| C | evidence auditor（**确定性**） | 盲审包 + 语料 | 纯代码，无 LLM |
| D | adjudicator（仅在分歧时启动） | 原包 + A/B/C findings | **隐藏期望结果** |

盲审包字段白名单：`question / answer_state / answer_permission / claims / citations /
evidence / source_limitations / abstention / （用户可见）sections`。构造时机器校验禁止
子串（`agent_pre_review`、`round1/2`、`d2_`、`expected`、`gate_result`、repair/reject 记录…），
并**用用户可见 sections**（避免 v1 载荷里的校验器日志泄漏"哪些断言被剔除"）。

**已知限制（必须写明，不得粉饰）**：本项目只有一个 provider / 一个模型家族。lane 之间
只有角色、prompt、fresh session、题目顺序不同，**不是**不同模型。**不得伪称模型独立性**，
也**不得**声称 AI 盲审等价于人类同行评审。

### deterministic vs interpretive（两者不可互相替代）

* **Lane C（确定性）能证明**：`passage_id` 可解析；`quoted_span` 在原文逐字命中；
  `source_layer` 与记录一致；`provenance_status` 不与 `trace_status` 矛盾；
  `evidence_ids` 落在 input contract 的 usable evidence 内。
* **Lane C 不能证明**："这条理论主张是否成立"。
* §13 冲突规则：若 AI lane 说 "citation mismatch"，而确定性审计显示引用可解析、引文逐字命中，
  则标 `REVIEWER_FALSE_POSITIVE`（记录理由），**不采信 AI 的该条指控**；反之亦然 ——
  结构验证通过也不等于理论主张成立。

### 共识规则（禁止简单多数投票掩盖严重问题）

```text
FAIL         任何 lane 报 evidence_failure / adapter_induced / SCHOLARLY_INTEGRITY_FAILURE
             **且经确定性审计验证成立**
WITH_CONCERN 仅 existing_scholarly_limitation / presentation_only（必须记录）
PASS         0 lane FAIL、0 未决证据失败、0 adapter-induced concern
分歧         → 启动 Lane D 裁决（不看期望结果、不按多数、不迁就最严 lane）
```

**不得**把 sparse evidence / L2-only 覆盖 / `SOURCE_TRACE_INCOMPLETE` 自动判成 adapter regression：
adapter regression 需要证据表明**流水线改动了、压制了、或误述了它本来拿到的材料**。

### 硬失败定义（§10）

claim unsupported by cited evidence · citation points to wrong passage ·
source layer falsely represented · L2 represented as L1 · mapping represented as attestation ·
abstention supplemented with unsupported knowledge · broken evidence reference ·
adapter-induced scholarly regression。

### 怎么审计（命令与工件）

```bash
python3 _scripts/_tools/phase4e_ai_review.py --check-v1      # Gate v1 历史完整性（E14 仍是 human）
python3 _scripts/_tools/phase4e_ai_review.py --freeze-gate   # 冻结 Gate v2（先冻结后评审）
python3 _scripts/_tools/phase4e_ai_review.py --packets       # 生成盲审包（字段白名单 + 泄漏校验）
python3 _scripts/_tools/phase4e_ai_review.py --lane-c        # 确定性证据审计
python3 _scripts/_tools/phase4e_ai_review.py --adjudication-dossiers
python3 _scripts/_tools/phase4e_ai_review.py --collect       # consensus + E14-v2 判定
python3 _scripts/_tools/phase4e_ai_review.py --run           # 4e_ai_closure_<ts>_<id>（immutable）
```

工件：`_data/phase4e/ai_scholarly_review_v2/`（`manifest.json` / `lane_a.jsonl` /
`lane_b/` / `lane_c.jsonl` / `lane_d/` / `adjudications.jsonl` / `task_consensus.jsonl` /
`final_summary.json`），以及 `_data/phase4e/4e_ai_closure_<ts>_<id>/`。

**审计 reviewer 分歧**：看 `task_consensus.jsonl` 的 `adjudicated` / `adjudicator_verdict` /
`ai_citation_claims`（含 `resolution`），以及 `lane_d/*.json` 的 `reviewer_false_positives`；
`final_summary.json` 的 `conditions` 逐条给出 E14-v2 的通过条件。

### 默认验收模型（从 RC1.2 起）

```text
AI_MULTI_AGENT_BLIND_REVIEW
+ DETERMINISTIC_EVIDENCE_VALIDATION
+ FROZEN_MACHINE_GATES
```

除非项目所有者**重新启用** `HUMAN_REVIEW_REQUIRED`，否则不再阻塞于"缺真人"。

---

## 9. 可复现性规则（踩过的坑）

1. **不要用内置 `hash()`** 生成 id（跨进程随 `PYTHONHASHSEED` 变化）——
   用 sha1 / 稳定序号。
2. 排序要**显式**（`sort_keys=True` / `sorted(...)`），不要依赖 dict 顺序或文件系统顺序。
3. 实体顺序：passage_meta 缺 `sequence_in_session` 时按 **id 字典序**，不要按出现顺序。
4. 翻译关联：witness → translation join 用 id；`provenance_note` 只在 canonical JSONL 里，
   派生 sqlite 里没有 —— 需要它就读那小份 JSONL。
5. mock 研究很慢（≈14s/次），跨进程缓存放 `_workspace/test_cache/answer-<hash>.json`；
   浏览器截图前**必须预热**，且预热参数要与 UI 实际发送的一致
   （含 `language="any"`），否则缓存键不同 → 浏览器重跑 → 截图里没有答案。
6. 时间/日期不许编造；拿不到就写 `unknown`。
7. 测试**不要**写进真实 vault：用 `_export_testlib.export_root` /
   `_obsidian_testlib` 的隔离 vault。

---

## 10. 复现一次完整验收（最短路径）

```bash
cd <REPO>

git rev-parse HEAD                                   # 记录 HEAD
python3 _scripts/_tools/core_freeze.py --verify      # 39/39
python3 _scripts/_tools/freeze_lineage.py --verify   # 核心语义变化 = 0
python3 _scripts/_tools/product_health.py            # 9 层（provider DEGRADED 正常）
python3 _scripts/_tools/product_acceptance.py --full # 场景 A–F + 完整回归
python3 _scripts/_tools/phase5a_acceptance.py --run  # Phase 5A H1–H14（含浏览器/导出/Obsidian/项目 QA）
python3 _scripts/_tools/check_core_change_requests.py --verify
```

然后读 `_data/product_acceptance/<run_id>/final_decision.json`、
`_data/phase5a/5a_acceptance_<ts>_<id>.json` 与 `PHASE4D7_PRODUCT_ACCEPTANCE_REPORT.md`
/ `PHASE5A_SCHOLARLY_PRODUCT_HARDENING_REPORT.md`。

---

## 11. 审计记录都在哪

| 记录 | 路径 |
|---|---|
| 测试结果（可核） | `_data/index/TEST_RUN.json` |
| 冻结清单 / 谱系 | `_data/core_freeze/` |
| 验收 run（含矩阵、计时、截图、日志） | `_data/product_acceptance/<run_id>/` |
| Phase 5A 问题登记 | `_data/phase5a/issues.json` |
| Phase 5A 产品缺陷记录 | `_data/phase5a/PDR-0001.json` |
| Phase 5A 冻结修复记录 | `_data/phase5a/freeze_remediation.json` |
| Phase 5A Hardening Gate v1 | `_data/phase5a/phase5a_hardening_gate_v1.json` |
| Phase 5A 验收 run | `_data/phase5a/5a_acceptance_<ts>_<id>.json` |
| Phase 5A 可访问性 / 键盘证据 | `_data/phase5a/accessibility_audit_5a.json`、`_data/phase5a/keyboard_flows.json` |
| 呈现分类法（冻结） | `_data/product/presentation_taxonomy_v1.json` |
| 核心变更请求 | `_core_change_requests/requests/` |
| 导出审计 | `_workspace/exports/audit.jsonl` |
| 各阶段报告 | `PHASE4D*_*.md`、`PHASE4C1_*`、`PHASE4E_*`、`PHASE5A_*` 等仓库根目录 |
| 研究历史（含答案快照） | `_workspace/history/` |
