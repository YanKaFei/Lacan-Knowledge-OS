# Phase 5A — Scholarly Product Hardening

> **阶段**：Phase 5A — Scholarly Product Hardening（**不扩大知识范围**）
> **基线**：`SCHOLARLY_CORE_READY` · `PRODUCT_READY` · RC1.1 ·
> `PHASE_4E = COMPLETE`（Gate E1–E17 全 PASS；技术修复 COMPLETE）·
> `CCR-0001 = ACCEPTED_FOR_REMEDIATION`（**E14 的人工复核义务仍 `PENDING`** ——
> 冻结 Gate E14 逐字要求 `human spot review`，Phase 4E 期间的 agent 预审
> **不构成** E14 证据；材料包见 `_data/phase4e/human_review_packet/`）
> **最终判定**：`<<<DECISION>>>`
> **最终验收 run**：`<<<ACC_RUN>>>`
> **Hardening Gate v2**：`<<<GATE_HASH>>>`（冻结于 `<<<GATE_FROZEN_AT>>>`，**早于**本次验收 run）
> **Historical Gate v1**：`66b59165c7b68be5fc69…`（11/14 PASS，`PHASE_5A_BLOCKED`，**永久保留、不可修改**）
> **产品缺陷记录**：`PDR-0001`（P5A-001；判定为**非**核心变更，故未开 CCR-0002）

一句话：把 RC1.1 从「功能完整且通过验收」提升为「适合长期日常研究使用」——
**清理已确认的产品呈现层、可访问性与运行接口缺陷**，不动任何 scholarly 语义。

---

## 1. Status

```text
<<<STATUS_BLOCK>>>
```

| 项 | 值 |
|---|---|
| 判定 | `<<<DECISION>>>` |
| Gate | `<<<GATE_ID>>>`（`<<<GATE_CRITERIA_N>>>` 条判据，`<<<GATE_PASS_N>>>/<<<GATE_CRITERIA_N>>>` PASS） |
| 未通过判据 | `<<<FAILED>>>` |
| 阻塞根因 | `<<<BLOCK_REASON>>>` |
| 发布候选 | `<<<RC>>>` |

**边界**：本阶段**没有**新增功能、没有新语料、没有 person/case explorer、没有 Zotero / 云 / 多用户 /
协作；也没有修改 ResearchContract / retrieval / evidence sufficiency / synthesis prompt / judge prompt /
ClaimAtom / entailment / repair / citation / source-role / abstention / Gate13-21 / Gold /
Human Review / D2 / Phase4E 封存 run / Scholarly Readiness Gate。

---

## 2. Baseline

| 项 | 值 |
|---|---|
| RC1.1 | `_data/releases/product_rc_v1_1.json` |
| 4D.7 验收 run | `4d7_acceptance_20260926T041607Z_0c642385`（PRODUCT_READY，未改动） |
| 4E 验收 run | `4e_acceptance_20260926T145239Z_dbd37bd0`（PHASE_4E_COMPLETE） |
| 4E 真实 provider run | `phase4e_real_llm_20260926T115518Z_1c8e1efc`（sealed，未改动） |
| 冻结 | `scholarly_core_freeze_v1` + lineage **7 段**（末段 = P5A-006 数据版本分离） |
| 能力 | mock/real LLM research、browse、evidence/provenance、Obsidian、Projects、Export 全 READY |

---

## 3. Issue Registry

`_data/phase5a/issues.json`（6 项；5 项来自 Phase 4D.7/4E 的既有发现，1 项在本阶段验收中暴露）：

`<<<ISSUES_TABLE>>>`

---

## 4. F-1 Root Cause（P5A-001）

完整根因见 `PHASE5A_F1_ROOT_CAUSE.md`。结论：

* **污染发生在 `FinalScholarlyAnswer` 构造层**（产品边界 `scholarly_api/core.py::_final_answer`）：
  冻结渲染器把校验器诊断**合并进** `sections["limitations"]`（`synthesis_validation.py:165-172`），
  产品边界又把它逐字投影进用户可见 payload；
* 因此**不能只在 UI 隐藏**：MCP / Obsidian / Export / Project snapshot / API 消费者都会收到同一段文本
  （实测：`_workspace/exports/exp_research_20260925T211020Z_023db8f0.md` 内含 `NOT_ENTAILED`）；
* **结构化副本本来就在**：`answer["rejected_claims"]`（claim_id / claim_text / status / reason）
  → 所以摘除按**结构化重建 + 行级精确比对**，不写脆弱正则；重建格式漂移即测试红（fail-soft 不误删学术内容）；
* **不删除**：诊断 100% 转入 `audit_diagnostics` 与 Audit 面（§4 要求）。

---

## 5. Scholarly vs Audit Boundary

| 内容 | 类别 | 默认去向 |
|---|---|---|
| 语料支持的学术内容（working definition / relation / formalism…） | `SCHOLARLY_CONTENT` | 用户可见 |
| 关于证据本身的限制（仅 L2 / 无 S20 L1 / `SOURCE_TRACE_INCOMPLETE` / 无法建立历时转变） | `SCHOLARLY_LIMITATION` | 用户可见 |
| claim 生成/修复/剔除、entailment 判定、repair trace、验证计量摘要 | `AUDIT_DIAGNOSTIC` | Advanced / Audit / Audit Bundle（**保留 100%**） |
| `PROVIDER_UNAVAILABLE` / `CORE_FROZEN_MISMATCH` / `WORKSPACE_CONFLICT` | `OPERATIONAL_ERROR` | 错误通道（不进答案正文） |
| `ABSTAINED` / `VALIDATED_WITH_QUALIFICATIONS` / `VALIDATION_FAILED` … | **学术结果状态** | 按状态呈现（**不是**错误） |

---

## 6. Presentation Taxonomy

`_data/product/presentation_taxonomy_v1.json`（冻结，`frozen: true`）：
四类语义 + 判定优先级 + 禁止手段（不得按关键词猜语义、不得用 LLM 判定、不得静默丢弃）。
落地实现唯一入口：`workspace_ui/server/presentation.py`（确定性、无网络、无 LLM）。

---

## 7. UserFacingAnswerView

`presentation.user_facing_view(payload)`：

* **新答案（schema v1.1）**：`sections` 已由边界层清洗；分类按结构化字段判定；
* **RC1.1 历史载荷（v1）**：**不改写**，按 legacy 规则（section id + 冻结工程文本特征）在**呈现时**路由；
* 学术载荷（claims / citations / answer_state / source_limitations）**原样返回**（§58：呈现更干净 ≠ 学术答案变了）。

`<<<USERVIEW_SAMPLE>>>`

---

## 8. Audit View

`presentation.audit_view(payload)`：

* 新答案：直接取 `audit_diagnostics`（`generated/validated/repaired/rejected`、
  逐条 rejected（含 reason）、repaired、prevalidation/c_stage dropped、quote fixes、
  计量摘要原文 `brief_answer_verbatim`、`routed_sections` 记录）；
* 历史载荷：`derived_from_legacy = true`，并保留 `legacy_routed_text`（**内容可取回**）；
* UI：Advanced / Audit 面板显示计量与逐条拒绝理由，**措辞中性**（“Validator record … not an error”），
  不写成 ERROR（§14）。

`<<<AUDIT_SAMPLE>>>`

---

## 9. Export Behavior

| 出口 | 标准 | Audit |
|---|---|---|
| Markdown / JSON / HTML | 只含用户可见面；`NOT_ENTAILED` / `已剔除` / 计量摘要 = **0** | — |
| Bundle | 同上；`manifest.export_options.include_audit=false` | **Audit Bundle**（`include_audit=true`）：`audit/rejected_claims.json`、`audit/validation_trace.json`、`audit/answer_audit_diagnostics.json`，全部进入 `bundle_hash`（可验证、可篡改检测） |
| UI | Export 菜单新增 **Audit Bundle** 按钮（显式 opt-in） | 同上 |

`<<<EXPORT_QA>>>`

---

## 10. Obsidian Behavior

* 标准 Research Note：**不含** validator trace（adapter 早已跳过 `internal` 段落，5A 起新答案的
  `sections` 本身也干净）；
* `include_audit=True` 时另存 `_System/audit/research-<id>.json`（审计工件，显式 opt-in）；
* **用户区 `## My Notes` 逐字节保留**（重新保存同一研究后比对）。

`<<<OBSIDIAN_QA>>>`

---

## 11. Project Compatibility

* 新 run：`sections` 干净、报告 `audit_artifact`；快照 `source_answer_hash` 与核心答案身份一致；
* 旧 run：**不 mutation**（逐字节未变），打开时由 presentation 层按 legacy 规则呈现；
* 旧 Project / History / Export 工件**全部可读**（H6 用真实 RC1.1 工件验证）。

`<<<PROJECT_QA>>>`

---

## 12. insufficient_unanswerable（P5A-004）

**分析**（§19–§22）：

1. `insufficient_unanswerable` 是**核心 task_type**（`_scripts/_tools/research_contract.py:1738` → `class AbstentionResearchContract`；
   `_scripts/_tools/synthesis_contract.py:179` → `"insufficient_unanswerable": "ABSTENTION"`）；
2. 产品 `mode` 枚举（`mcp_server/schemas.py:36-40`，12 值 + null）**不含**它；
   `scholarly_api/core.py:51` 的 `MODE_TO_TASK_TYPE` 也不映射到它；
3. **但产品的弃权不依赖它**：弃权由**证据充分性**阶段决定 —— 实测同题在 `mode=scholarly` 下
   仍返回 `ABSTAINED`（4D.7 D1、4E rt-J01/J02/J03 均如此）；
4. 因此缺的不是"能力"，而是**透明度**：用户看不出"为什么这个答案是弃权/受限"。

**处置（在范围内、最小）**：

* **不新增**"Unanswerable Mode"（§21 明确反对）；
* **不改** `ResearchContract` 路由语义（§22）；
* UI Advanced 面板新增 `answer_state` / `answer_permission` / `evidence_state` / `execution_state`
  与一句说明（`presentation_note`：弃权是**证据驱动**的学术结果，不是错误）→ 用户可核对
  "为什么是这个状态"；
* 文档（USER_GUIDE）写明：**用户 Mode ≠ 核心 task_type**，Auto/Scholarly 都可能产出弃权。

**保留的诚实限制**：产品接口仍**无法显式要求**该冻结 task_type（Phase 4E §11 的 3/14 题即以代理 mode 执行）；
这属既有接口限制，若要做需单独的产品维护项 + 决策（见 §24）。

---

## 13. Accessibility（P5A-002 / P5A-003）

`<<<A11Y_TABLE>>>`

* **P5A-002 标题层级**：视图 h1 → 卡片 h2 → 卡片内 h3；`render.js` / `explorer.js` / `project.js`
  全部改齐（含 4D.7 报出的 `h1→h3`、`h1→h4` 跳级）；
* **P5A-003 可访问名**：概念检索框改为 `label[for] + aria-labelledby`（视觉隐藏 label）；
  扩展覆盖又发现并修好 **项目创建表单 3 个输入框**（`project-title/desc/tags`）；
* 焦点可见（`:focus-visible`）与 skip-link 既存且保留。

证据：`_data/phase5a/accessibility_audit_5a.json`（9 个视图：Research / Research answer /
Explorer 列表 / 概念详情 / Terminology / Seminars / Projects / Exports / Evidence Inspector）。

---

## 14. Keyboard Navigation

`<<<KEYBOARD_TABLE>>>`

**诚实边界**：本机没有 puppeteer/playwright；手写 CDP 的 `Input.dispatchKeyEvent`（真·硬件按键）
在本环境不稳定，**未**作为验收依据。验收用两条可靠证据：

1. **行为**：在真实 Chrome 里派发 `KeyboardEvent`，验证产品**声明的键盘契约**真的响应
   （`Ctrl/Cmd+Enter` 提交、Esc 关闭 Inspector 并交还焦点、Explorer 表单 Enter 提交）；
2. **可达性**：原生可聚焦控件、无正 tabindex、`a.skip-link` 存在、`:focus-visible` 样式存在、
   交互控件都有可访问名；citation 控件是**原生 `<button type=button>`**（Enter/Space 激活由浏览器保证）。

---

## 15. Error Classification（P5A-005）

* **运行态错误**只走错误通道：`PROVIDER_UNAVAILABLE` / `CORE_FROZEN_MISMATCH` /
  `WORKSPACE_CONFLICT` / `INVALID_REQUEST`（`config.ERROR_UX`）；
* **学术限制**（`SOURCE_TRACE_INCOMPLETE`、仅 L2 证据…）保持 `SCHOLARLY_LIMITATION`，用户可见；
* **校验器诊断**归 `AUDIT_DIAGNOSTIC`，默认不可见、Audit 可取；
* 判定为确定性的（H9 直接断言三类分类结果）。

### 15.1 P5A-007：研究被禁用时的错误翻译（本阶段验收发现并修复）

**缺陷**：只要 MCP 不可用，UI 一律报 `INDEX_UNAVAILABLE`，用户读到
「检索索引不可用，可从语料重建」并被告知「启动 mcp_server/server.py」——
而真因是 `FREEZE_DRIFT`（冻结核心哈希不符）。**真因就在手边**：
`status()["core_freeze"]["reason"]`。

**证据（验收 run 的键盘工件原文）**：

```text
修复前：INDEX_UNAVAILABLE / The search index is unavailable. / …Next: 启动 mc…
修复后：CORE_FROZEN_MISMATCH / Scholarly Core integrity verification failed. /
        The frozen core hashes no longer match the freeze manifest, so research
        has been disabled. …
```

**修复**：`workspace_ui/server/api.py::_unavailable_reason()` —— 只用**已知结构化状态**
判定（`core_freeze_verified` / `core_freeze.reason`），冻结不符 → `CORE_FROZEN_MISMATCH`
（`config.ERROR_UX` 里本就有正确文案），仅 MCP 真离线时才用 `INDEX_UNAVAILABLE`。
`research()` 的 fail-closed 分支同样如实区分。回归测试：
`_scripts/_tests/test_phase5a_error_translation.py`（5 项）。

---

## 16. Provider Status（§41/§42）

`status_view` 现在返回**分层**状态：

```
core / mcp / workspace / provider  ∈ {READY, DEGRADED, UNAVAILABLE}
```

* provider 是**独立一层**：无凭据 = `DEGRADED`（离线/mock 完全可用，**不是**产品故障）；
* 只有 `core`/`mcp` 不可用才 `research_disabled = true`；
* 状态栏新增 `provider:` 文本（`PROVIDER_UNAVAILABLE` 只说 provider 不可用，不写成整机 BLOCKED）；
* **启动不发 LLM 请求**：boot 只做 `status`（含凭据能力检查，纯本地）+ 需要时才取 history（§43）。

### 16.1 P5A-008：凭据探测的「两个真相源」（本阶段验收发现并修复）

**缺陷**：`product_health.py` 探的是 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` /
`ANTHROPIC_API_KEY` 三个**冻结核心根本不读**的环境变量；UI 探的是核心真正读的
`DSH_SYNTHESIS_API_KEY` / `~/.dsh/.credentials.yaml`。本机凭据存在 →
**UI 报 READY、健康检查报 DEGRADED**，同一事实两个相反结论。
`USER_GUIDE` 还写着「provider DEGRADED 正常」，等于把假阴性写成常态。
（讽刺的是 `api.py` 的注释本身就记录了 4D.7 修过同一个缺陷 —— 但只修了产品层。）

**修复**：`product_health.py` **复用**产品层同一个探针
`workspace_ui.server.api._provider_credentials_present`（单一真相源），
仅在其不可导入时回退到等价判断；`USER_GUIDE` 同步订正。

---

## 17. Security（§45/§68）

* `phase4e_secret_audit.py` 扩展扫描面后（含 5A 工件/导出/笔记）→ `<<<SECRET>>>`；
* 策略负例（path traversal / absolute root / core write）全部被拒（H10）；
* **日志硬化**：新增 `LACAN_AUDIT_LOG_QUESTION`（默认 1 保留全文；设 0 → 只记问题 sha256 前缀），
  使"问题全文日志"成为**可配置**项；API key 从不进日志/响应/工件（脱敏 + 审计）。

---

## 18. Browser QA（§54 A–G）

`<<<BROWSER_QA>>>`

---

## 19. Export QA（§55）

`<<<EXPORT_QA2>>>`

---

## 20. Backward Compatibility（§37–§39）

`<<<BACKCOMPAT>>>`

---

## 21. Regression（§59/§61）

`<<<REGRESSION>>>`

### 21.1 失败归因（逐项，不假设）

<<<REGRESSION_ATTRIBUTION>>>

### 21.2 归因更正：三个被掩盖的**真实缺陷**（P5A-009 / 010 / 011）

> **必须先说清楚**：Gate v1 run 的 §21.1 曾把 41 项失败整体归因为「P5A-006 冻结级联」。
> 在 P5A-006 按方案 A 修好、冻结恢复有效之后，那条归因被证明**不完整且误导**：
> 同类失败**依然存在**。逐项排查后找到三个真实缺陷（均与学术语义无关）：

| 缺陷 | 严重度 | 组件 | 影响 | 修复 |
|---|---|---|---|---|
| **P5A-009** | **CRITICAL** | `mcp_server/tools.py` | `call_tool` 的函数体被误置于其后插入的 `_sha256_prefix()` 之内 → 成为**不可达死代码** → `call_tool` 隐式返回 `None` → `serializers.tool_response(None)` 抛 `AttributeError` → **所有 MCP 工具调用**返回 JSON-RPC `-32603` | `_sha256_prefix` 提升为模块级；`call_tool` 主体还原 |
| **P5A-010** | HIGH | `mcp_server/audit.py` | 调用点传 `question_sha256=`，而 `record()` 从未接受该参数 → **带审计的每次调用**都 `TypeError` | 补齐签名（默认仍不落问题原文） |
| **P5A-011** | HIGH | `_scripts/_tests/_mcp_testlib.py`、`_project_testlib.py` | 测试缓存只按 `(question, options)` 取 key → schema v1→v1.1 后仍读**上一代 payload** → 跨层同一性/导出逐字类套件**假红** | key 纳入答案 schema + 冻结身份；清陈旧缓存 |

**证据（修复前 / 修复后）**：

```text
stdio 探针（修复前）：initialize OK / tools/list OK
                       6×lacan.research + lacan.get_context → 全部 -32603 INTERNAL_ERROR
stderr（修复前）：     tools.py:339 TypeError: record() got an unexpected keyword
                       argument 'question_sha256'
                       serializers.py:56 AttributeError: 'NoneType' object has no attribute 'get'
stdio 单调用（修复后）：{"jsonrpc":"2.0","id":2,"result":{... "ok": true ...}}，stderr 无 crash
```

**修复后**：`test_phase4d1_mcp_*`（10 套）、`test_phase4d2_ui_*`、`test_phase4d3_*`、
`test_phase4d4_*`、`test_phase4d5_*`、`test_phase4d6_*` 全部转绿（见 §21.3）。

**纪律反思（写进报告，不粉饰）**：

1. 「同时存在一个已知大问题」**不是**把其它失败一并挂上去的理由；归因必须逐项对证据。
2. `call_tool` 的损坏在**进程内 + `audit=False`** 时不可见（测试默认如此），
   只有走 **stdio / 开启审计** 的真实链路才暴露 —— 这恰好说明为什么必须跑端到端回归，
   而不能只信「自己的套件全绿」。
3. 因此本报告**撤回**先前版本中「产品侧没有发现未解决的缺陷」这一结论。

### 21.3 最终正式回归

正式验收使用的回归工件：<<<REGRESSION_FINAL>>>

真实缺陷修复清单与归因更正记录：`_data/phase5a/REGRESSION_DEFECTS_AND_CORRECTIONS.json`

---

## 22. Timing（§60）

`<<<TIMING>>>`

（只测量与分类；`hang / deadlock / 无界重试` 才阻塞，本轮未出现。）

---

## 23. Freeze Verification（§62）

`<<<FREEZE>>>`

---

## 24. Remaining Limitations

### 24.1 语料数据版本 vs 学术语义（P5A-006 —— **已解决**，见 §26–§32）

> 此项曾是本阶段唯一阻塞根因；按 **DECISION_1 = 方案 A** 修复后已解决。
> 保留原文以便追溯修复前后的差异。

1. **语料数据版本与学术语义未在策略上分离**（P5A-006，曾为阻塞根因）：
   冻结 manifest 钉住 `corpus_inventory_hash`；语料被合法新增文件后 `core_freeze --verify` FAIL、
   MCP fail-closed。而 lineage 规则要求每段 `scholarly_semantic_changes == 0`，
   该组件又不在 `PRODUCT_BOUNDARY_KEYS` 里 → **无法在不记录"语义变化"的前提下重建基线**。
   需要一次策略决策（见 `_data/phase5a/DECISION_REQUEST_corpus_drift.md`）。
2. 产品接口仍无法显式表达冻结 task_type `insufficient_unanswerable`（P5A-004 只解决透明度）。
3. 真实硬件按键的端到端遍历未自动化（§14 的诚实边界）。
4. 未做像素级对比度测量（无对比度度量运行时）与屏幕阅读器实测。
5. 真实 provider 的延迟/配额由 provider 侧决定（4E §26 既有）。
6. 既有 13 项产品限制（书目元数据、无自动对齐翻译、无人物/个案 Explorer、形式化白名单检索、
   无全图 Explorer、无本体编辑、无笔记自动刷新、dense 不可用、MCP 仅 stdio、
   DOCX/PDF 未实现、`USER_EDITED_DOCUMENT` 未实现、`unknown` 归属不可补全）**继续保留**。
7. **验收工具自身的两个缺陷（本阶段发现并修复，但必须留痕）**：
   * **H2 判据取数字段错**（`P5A-ACC-DEFECT-001`）：fixture 读的是
     `len(audit["rejected"])`，而 legacy（v1）载荷**结构上没有** `audit_diagnostics`，
     该字段恒为 0 —— 与产品正确性无关。权威计量是载荷自带的
     `summary.rejected_claims_n`（5/5 与封存 run 精确相等：3/5/4/1/4）。
     **Gate 判据文本未改**，只是把实现修对，并**加强**为「权威计量一致 + legacy 行级零丢失」。
     记录：`_data/phase5a/ACCEPTANCE_DEFECT_H2.json`。
   * **QA 隔离根放错**：export/obsidian QA 曾把工件写进 `_data/phase5a/<run>/`，
     被**写闸门正确拒绝**（`CoreMutationError`）。那是产品做对了、验收脚本放错了地方。
     已改到 `_workspace/acceptance/<run>/`。
8. **Gate v1 的判据覆盖缺口 —— 已由 Gate v2 关闭**（详见 §27/§28）：
   v1 的 H1–H14 不含 browser / export / obsidian / project QA 作为阻塞判据；
   **Gate v2** 把它们升为阻塞判据 **H15–H18**（加严，未放松任何 v1 判据）。
   v1 与其 11/14 失败结果**永久保留且不可修改**。
9. **冻结策略的数据版本缺口**：见 §24.1。

---

## 25. Final Decision

```text
<<<FINAL_BLOCK>>>
```

**停止**：不自动进入 Phase 5B（Person / Case Explorer）等后续阶段；等待确认。

---

## 26. P5A-006 Data Version / Semantic Freeze Separation（根因与最终判定）

### 26.1 根因（最终表述）

```text
core_freeze.py 的 SPEC 早就用注释块「# ── 数据版本」把 6 个组件标成数据版本；
但那**只是注释**：freeze_lineage.py 的判定是

    semantic = [k for k in changed if k not in PRODUCT_BOUNDARY_KEYS]

即只认识两类（产品边界 / 其余皆为学术语义）。于是

    外部语料清单长大一个文件
      → corpus_inventory_hash 变化
      → 被计入 scholarly_semantic_changes
      → lineage 必然 FAIL
    而如实重建基线同样会让 FAIL 发生

两个方向都被策略堵死。这是**分类实现缺陷**（SPEC 声明了三类、实现只认两类），
不是 scholarly core semantics drift。
```

### 26.2 精确改动（`freeze_lineage` 的分类实现）

`<<<P6_CLASSIFICATION_CHANGE>>>`

### 26.3 最终判定

```text
<<<P6_VERDICT>>>
```

---

## 27. Gate v1 Historical Failure（永久保留，不可变）

`<<<GATE_V1_HISTORY>>>`

---

## 28. Gate v2 Coverage Upgrade（更严的继任者）

`<<<GATE_V2_TABLE>>>`

**措辞（§23，逐字）**：

```text
Gate v1 remains historical and immutable.

Gate v2 is a stricter successor created
after a coverage gap was discovered.

No v1 criterion was relaxed.
Four product QA checks were promoted
from diagnostic evidence to blocking criteria.
```

---

## 29. Data Version Diff

`<<<CORPUS_DIFF_TABLE>>>`

`<<<CORPUS_DIFF_DETAIL>>>`

---

## 30. Corpus Inventory 143→144

`<<<CORPUS_143_144>>>`

---

## 31. Canonical Corpus Ingestion Status

`<<<INGESTION_STATUS>>>`

> **产品措辞纪律**：`0926 卡特尔 下.docx` 目前**不**可被 Research Core 检索；
> 任何界面/文档/报告都不得宣称相反。

---

## 32. Derived Index Consistency

`<<<DERIVED_INDEX_CONSISTENCY>>>`

---

## 33. Freeze Identity 推进（parent → new，不覆盖）

`<<<FREEZE_IDENTITY>>>`

`<<<LINEAGE_SEGMENT>>>`

---

## 34. Timing Report

`<<<TIMING_REPORT>>>`

---

## 35. Release Candidate 状态（与 E14 独立）

`<<<RC_STATUS>>>`
