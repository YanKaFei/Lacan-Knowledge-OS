# Lacan Knowledge OS — 用户指南

> 本文件面向**使用者**（研究者 / 学习者），不是开发文档。
> 开发、审计、冻结与验收流程见 `DEVELOPER_AUDIT_GUIDE.md`。
> 本指南只描述**已经实现并且通过验收**的能力；没有实现的一律写在 §9「已知限制」。

---

## 1. 这个系统是什么

Lacan Knowledge OS 是一个**证据受限**的拉康研究工具。它把你的本地语料
（Seminar / Écrits / 中文与法文材料）当作**唯一证据来源**，做四件事：

1. **Research**：就一个问题给出**带出处**的答案，或**如实弃权**；
2. **Explorer**：按概念 / 论文段 / 术语 / 期数**只读**浏览语料，不看全文库也能定位；
3. **Projects**：把研究、段落、概念**收集进一个研究项目**，可复查、可续做；
4. **Export**：把研究结果导出成 Markdown / JSON / HTML / 证据包（bundle），带引文与来源链。

外加 **Obsidian 集成**：把研究、段落、概念、项目写成你仓库里的笔记
（生成区受管，你自己的笔记区永不覆盖）。

### 它**不是**什么（重要）

* **不是**「问拉康什么都能答」的聊天机器人。语料里没有的东西，它会说没有，
  并且**不会**用模型自身知识补一段上去。
* **不是**拉康理论权威。它给的是**语料里的证据**与**可回查的段号**；
  学术判断仍然由你来做。
* **不是**自动翻译器，也**不是**完整知识图谱。见 §9。
* **不会**替你改语料、改概念本体、改 Gold / 评审记录。这些是冻结工件。

---

## 2. 唯一真相与目录：哪些能改、哪些不能

| 分类 | 位置 | 你能否改 | 说明 |
|---|---|---|---|
| **原始语料（只读）** | `<HOME>` | ❌ 只读 | 材料本体，系统从不写 |
| **canonical 知识** | `_data/ontology/`、`_data/passage_store/`、`_data/eval/` | ⚠️ 只能走评审 | 概念 / 关系 / 段落 / 见证 / 术语映射 / Gold |
| **冻结核心** | `scholarly_api/core.py`、`synthesis_*`、`_data/core_freeze/` | ❌ 禁止直接改 | 改动必须走 `_core_change_requests/`（见开发文档） |
| **可重建索引** | `_index/`、`_data/index/` | ✅ 可重建 | 删掉能按脚本重算 |
| **你的工作区** | `_workspace/**`（history / projects / exports / obsidian_vault） | ✅ 随便改 | 产品只写这里 |
| **Obsidian 笔记** | `_workspace/obsidian_vault/**` | ✅ 你的区随便改 | 生成区见 §7 |

**一句话**：Markdown/Obsidian 是唯一真相；索引都是派生物，删了能重建。
产品**永远**不写原始语料、不写 canonical、不写冻结核心。

---

## 3. 启动与自检

```bash
cd <REPO>

# 1) 健康检查（最先跑这个）
python3 _scripts/_tools/product_health.py          # 人类可读；--json 给机器
#   exit 0 = READY，1 = DEGRADED（不阻塞），2 = BLOCKED（要处理）

# 2) 启动 Workspace（浏览器 UI + API）
python3 -m workspace_ui.server.cli                 # 默认 http://127.0.0.1:3090

#    换端口 / 换地址：
LACAN_UI_PORT=3091 python3 -m workspace_ui.server.cli

# 3) 只做自检不启动（冻结校验失败时退出码 3）
python3 -m workspace_ui.server.cli --selftest
```

打开 `http://127.0.0.1:3090` 后，左下角状态栏应显示：

```
● MCP Connected    Core Freeze verified - scholarly_core_freeze_v1     lacan-research 1.0.0
```

**这两个灯是硬门**：

* `MCP Connected` 不亮 → 研究接口离线（仍可浏览 History）；
* `Core Freeze verified` 不亮 → 冻结核心哈希对不上，**研究会被禁用**，
  已保存的历史仍然可看。此时不要「想办法绕过」，而应先查为什么对不上。

### 健康检查的分层含义

`product_health.py` 把可用性拆成 9 层（core / corpus_store / browse / mcp /
workspace / obsidian / exports / projects / provider）。

* `provider = DEGRADED` **是正常的**：没配真实 LLM 凭据时，离线 / mock 研究
  完全可用，系统也**不会**用模型知识兜底。
* 只有出现 `BLOCKED`（含 `blocking_layers`）才算不可用。

---

## 4. 五个入口怎么用

### 4.1 Research（研究）

1. 在问题框输入问题（≥ 4 字符，**不会**被静默截断；超长会明确报错）；
2. 选 Mode：`Scholarly`（默认）/ `Quick` / `Auto`，或 Advanced 里的 10 种任务类型
   （概念定义、概念关系、比较、历时、Seminar 专指、个案、弗洛伊德→拉康、
   哲学→拉康、拓扑/数学型、翻译术语）；
3. 选 Provider：`Offline / Mock`（默认，离线可复现）或 `Real LLM (explicit)`（见 §6）；
4. 点 **Research corpus**。

结果区永远包含：答案状态、每一条 claim 的**证据段**、citation（可点开
Evidence Inspector 看上下文与来源链）、以及 limitations。

**没有任何结果时**，你会看到明确的**弃权**语，而不是一段像样的猜测：

* `ABSTAINED` / 「当前语料无法支持可靠回答」；
* `INSUFFICIENT_EVIDENCE`、`PARTIALLY_SUPPORTED`、`VALIDATION_FAILED`
  —— 措辞会直说「**不是**一个完整验证过的答案」。

### 4.2 Explorer（只读浏览）

| 子视图 | 用途 |
|---|---|
| Concepts | 概念检索 → 概念详情（canonical 定义 / 关系 / 语料佐证 / Seminar 分布 / 历时） |
| Passages | 段落检索（分层过滤 + 游标分页，服务端硬上限 50/页） |
| Seminars | Seminar 总览 → sessions → **阅读模式**（三个动作：从该段研究 / 保存到 Obsidian / 加入项目） |
| Terminology | 术语三区（Mapping / Attestation / Interpretation），含**零语料佐证**的如实显示 |

Explorer 是**只读**的：它不写任何语料。分页是强制的 —— 249,105 段语料
绝不会被塞进浏览器。

### 4.3 Projects（研究项目）

* 新建项目 → 把研究 run / 段落 / 概念加进去（只存**稳定 id**，不复制正文）；
* run 快照带 `source_answer_hash`，与核心答案身份一致，可复查；
* 弃权答案里的「缺什么信息」可以变成项目的 **Open Question**（来源可追）；
* 并发编辑有 **revision 冲突保护**（不是 last-write-win）。

项目内容属于你的工作区，**不会**混进 EvidencePacket，也**不会**被当成语料证据。

### 4.4 Export（导出与引文）

四种格式，**同一个 `ExportDocument`**，所以格式之间不会互相矛盾：

| 格式 | 用途 |
|---|---|
| Markdown | 写进笔记 / 文档 |
| JSON | 机器可读（`export_document_v1`） |
| HTML | 独立分享页（无脚本、无外链脚本） |
| Bundle | 证据包（zip + manifest + `bundle_hash`，可离线自检） |

引文样式：`internal-short` / `internal-full` / `provenance` **永远可用**；
`chicago` / `mla` / `apa` / `bibtex` **只在书目元数据齐全时**才给 ——
不齐时显式返回 `BIBLIOGRAPHIC_METADATA_INCOMPLETE`，**不会**编造出版信息。

自检一个 bundle：

```bash
python3 - <<'PY'
import export_system as EX
print(EX.verify_bundle("_workspace/exports/<你的 bundle 目录>"))
PY
```

导出记录（审计）：`_workspace/exports/audit.jsonl`。

### 4.5 Obsidian

把项目根（`Lacan-Knowledge-OS/`）作为仓库打开即可 —— 它本身就是一个 Obsidian vault。
产品生成的笔记落在**受管工作区**：

```
_workspace/obsidian_vault/
├── Research/  Concepts/  Seminars/  Passages/  Projects/  Sources/
└── _System/mappings/{entity_note_map.json, project_note_map.json}
```

要让笔记落到别的仓库，用环境变量指过去（路径必须在该 vault 内）：

```bash
OBSIDIAN_VAULT_PATH=/绝对/路径/我的仓库 python3 -m workspace_ui.server.cli
```

**映射文件是权威**：它登记「哪个实体 → 哪个笔记文件」。
已有**非受管**文件不会被改写，只会被登记（`managed: false`）。

---

## 5. 证据语言（读懂系统在说什么）

| 记号 | 含义 |
|---|---|
| `passage.S11.unknown.L05.P0056` | 稳定段号：Seminar / 场次 / 段序号。所有引用都用它 |
| **L1** | 一手见证（原文语料） |
| **L2** | 二手/中介材料（译本、转述、后人整理） |
| `unknown` | 该片段的**归属或来源未确定** —— 系统如实写，不猜 |
| `SOURCE_TRACE_INCOMPLETE` | **来源链不完整**：能给你这一段，但无法把它的出身追到底 |
| `zero corpus attestation` | 语料中**查无此词**（例：`原乐`）。这是结果，不是错误 |
| 答案状态 | `VALIDATED` / `VALIDATED_WITH_QUALIFICATIONS` / `PARTIALLY_SUPPORTED` / `VALIDATION_FAILED` / `INSUFFICIENT_EVIDENCE` / `ABSTAINED` |

三条纪律：

1. **`SOURCE_TRACE_INCOMPLETE` 不是免责声明**，是证据状态。它会一路带到
   Obsidian 笔记、项目、以及三种导出格式里 —— 不会在中间某一层被抹掉。
2. **零结果就是零结果**。「查无此词」不会显示成「没有相关讨论」这种模糊说法。
3. **限定词不是装饰**。`PARTIALLY_SUPPORTED` 明确表示「不是完整验证过的答案」；
   导出与 UI 里的措辞一致。

### 5.1 学术限制 vs 审计诊断（Phase 5A 起）

系统里**看起来都像"没做到"的话**，其实分四类，去向完全不同（`presentation_taxonomy_v1`）：

| 类别 | 例子 | 你默认看得到吗 |
|---|---|---|
| **学术内容** | working definition、关系、术语对应 | ✅ 答案正文 |
| **学术限制** | `SOURCE_TRACE_INCOMPLETE`；"本条只有 L2 中介材料，没有 L1 原文"；"语料不足以建立历时转变" | ✅ 答案正文的「限制」区 —— **这是关于证据的结论，你应该看到** |
| **审计诊断** | "已剔除未通过蕴含验证的断言：…（`NOT_ENTAILED`）"、`generated/validated/repaired/rejected` 计量 | ❌ 默认不进答案正文；在 **Advanced / Audit** 面板与 **Audit Bundle** 里 100% 保留 |
| **运行错误** | `PROVIDER_UNAVAILABLE`、`CORE_FROZEN_MISMATCH`、`WORKSPACE_CONFLICT`、`INVALID_REQUEST` | 走错误通道，**不会**混进答案正文 |

**为什么把"已剔除某条断言"从答案正文里拿走？**

因为那句话是**工程日志**，不是学术限制：它描述的是系统内部校验器做了什么，而不是
"关于拉康我们能证明到哪一步"。它出现在用户读的答案里会造成两个误导 ——
(a) 让人以为答案是"残缺的"，其实被剔除的断言**本来就不该进答案**；
(b) 让答案正文混入只有审计者看得懂的术语。

**它没有被删掉。** 同一批信息在三个地方完整保留：

* UI 的 **Advanced → Audit** 面板（计量 + 逐条被拒断言 + 理由 + 修复记录）；
* `sections["audit_diagnostics"]`（API / MCP `meta.audit_diagnostics`）；
* **Audit Bundle**（导出时显式勾选，或点 Export 里的 *Audit Bundle* 按钮）。

> ⚠ **重要**：呈现变干净 **不等于** 学术答案变了。claim、citation、答案状态、
> `source_limitations` 一字未改；§58 的一致性检查每次验收都跑（见
> `DEVELOPER_AUDIT_GUIDE.md` §5.5）。**RC1.1 之前生成的历史答案不被改写** ——
> 它们在**呈现时**按同一套规则拆分为"用户面 / 审计面"，原始载荷原样保存在
> History 与 Project 快照里。

**答案状态不是错误。** `ABSTAINED` / `INSUFFICIENT_EVIDENCE` / `VALIDATION_FAILED`
是**学术结果状态**（"证据不足，因此不回答"是正确行为），UI 不会把它们画成
红色 ERROR。想知道**为什么**是这个状态，展开 Advanced 面板：
`answer_state` / `answer_permission` / `evidence_state` / `execution_state` 都在那儿。

### 5.2 我的 Mode ≠ 核心 task_type（P5A-004）

产品界面上的 Mode（Auto / Scholarly / …）**不是**核心契约里的 `task_type`。
核心的任务类型里有一个冻结的 `insufficient_unanswerable`（"这个问题不可回答"），
**产品接口不允许显式选择它**。这不影响你拿到诚实的弃权答案 ——
弃权由**证据充分性**阶段独立决定，任何 Mode 都可能产出 `ABSTAINED`。
差别只在**可核对性**：现在 Advanced 面板会把四个状态字段摊开给你看。

---

## 6. Provider 模式（离线 / 真实 LLM）

* **Offline / Mock（默认）**：不联网、可复现（同一问题同一结果），
  用于日常检索与研究流程。
* **Real LLM (explicit)**：需要核心能解析到凭据
  （`DSH_SYNTHESIS_API_KEY` 环境变量，或 `~/.dsh/.credentials.yaml` 里的
  `DEEPSEEK_API_KEY:` 行）。

**状态**：真实 LLM 研究路径**可用**（`CCR-0001` 的**技术修复**已在 Phase 4E 完成：
产品边界现在经既有工厂 `make_adapter` 把 completion provider **包进**
`ScholarlySynthesisAdapter`，与 4C.1-D/D2 验证过的结构一致；详见
`PHASE4E_REAL_PROVIDER_REMEDIATION_REPORT.md`）。

* **延迟预期**：单题真实研究会调用 provider 多次（综合 + 逐条蕴含裁判），
  实测约 **几十秒到数分钟**（本机 14 题中位约 3–4 分钟/题）。
* **凭据缺失 / provider 故障**时**如实报错**，绝不 fallback：

```
Real LLM provider is unavailable.
The Scholarly Core needs an explicitly configured provider credential for
real-LLM research. It will not answer from model knowledge instead.
```

**它绝不会**退回 mock 结果冒充真实回答，也**绝不会**用模型知识补答。
修复必须走核心变更请求（见 `DEVELOPER_AUDIT_GUIDE.md` §8），产品层无权改核心。

### 6.1 状态是分层的（Phase 5A 起）

状态栏不再只有一个总灯，而是四层各自报：

```
core: READY | mcp: READY | workspace: READY | provider: DEGRADED
```

* **provider 是独立一层**：没有凭据 = `DEGRADED`，这**不是**产品故障 ——
  离线 / mock 研究、浏览、项目、导出、Obsidian **全部照常可用**；
* 只有 `core` 或 `mcp` 不可用时，研究才会真的被禁用（`research_disabled = true`）；
* 状态栏会写 `provider:` 的当前值。看到 `PROVIDER_UNAVAILABLE` 时请读成
  "真实 LLM 这一条路不可用"，而不是"整台机器坏了"。

---

## 6.2 这些答案有没有经过**人类**评审？（重要且有边界）

> **Scholarly outputs are corpus-grounded and validated through automated evidence checks and
> independent AI review. They have not been certified through external human peer review.**
>
> 中文：**系统的学术输出以语料为依据，并通过自动化证据校验与独立 AI 评审；它们
> 没有经过外部人类同行评审的认证。**

具体说明（请按字面理解，不要过度解读）：

* 每条回答都经过**自动化证据校验**（引用可解析、引文逐字命中语料、来源层级一致、
  蕴含验证、弃权纪律），这部分是**确定性**的、可复算的。
* Phase 4E 起，验收还包含一次**独立 AI 多代理盲审**（`AI_MULTI_AGENT_BLIND_REVIEW_V1`）：
  学术审查、对抗性证伪、确定性证据审计三个相互独立的 lane，分歧时由第四个裁决 lane 裁定。
* **本项目当前没有可执行的人类学术 reviewer**，因此**没有**、也不会伪造人类评审记录。
  发布候选 RC1.2 的 `review_assurance = AI_ONLY`、`human_review = false`。
* 因此：**AI 盲审 ≠ 人类同行评审**。若你的用途需要人类专家背书（发表、临床、正式引用），
  请自行安排外部评审；本系统**不会**替你宣称已有人类认证。
* 已知限制：单一模型家族（lane 之间的差异来自角色/prompt/会话，不是不同模型）；
  确定性审计只能证明"引用与层级没问题"，**不能**证明"理论主张成立"。

---

---

## 7. 笔记的「生成区」与「你的区」

产品写进笔记时**只动生成区**：

```markdown
---
（受控 YAML：由 dump_frontmatter 生成，字段固定）
---

<!-- LACAN-OS:GENERATED:START -->
（生成区：可被下一次同步整体刷新）
<!-- LACAN-OS:GENERATED:END -->

## My Notes

（你的区：**逐字节保留**，任何同步都不会覆盖）
```

规则：

* 在 `## My Notes` 里随便写 —— 重新保存同一条研究/段落，你的文字**一字不动**；
* 不要在生成区里写东西（会被刷新掉）；
* `_System/mappings/*.json` 请不要手工改名/删除 —— 它是「实体 ↔ 笔记」的账本。

---

## 8. 常见故障与处置

| 现象 | 含义 | 处置 |
|---|---|---|
| `MCP Connected` 不亮 | MCP 研究接口离线 | 确认 `python3 mcp_server/server.py --selftest` 能跑；仍可浏览 History |
| `Core Freeze verified` 不亮（研究被禁用） | 冻结核心哈希对不上 | **不要**改哈希；先查 `core_freeze.py --verify` 的差异，改核心要走 CCR |
| `Real LLM provider is unavailable` | 凭据缺失，或核心 provider 路径缺陷 | 见 §6 / `CCR-0001`；日常用 Offline / Mock |
| `The research call timed out` | 研究超时；**停止等待不会杀后端** | 稍后从 History 取结果 |
| 浏览器里看到 error card | 产品**故意**不显示 traceback | 结构化错误在 Advanced / Audit |
| `SOURCE_TRACE_INCOMPLETE` | 来源链不完整（如实） | 按提示去看可追到的那一段；不要当作「已验证」 |
| 答案正文里**看不到**「已剔除某条断言」 | 这是 Phase 5A 的**故意**行为（工程日志不进答案正文） | 去 Advanced → Audit 面板，或导出时选 **Audit Bundle** |
| Audit 面板写 `NOT_ENTAILED` / `rejected` | **不是错误**，是校验器记录 | 想复现完整过程就用 Audit Bundle |
| `provider: DEGRADED` | 真实 LLM 不可用（**无凭据**；探测源与核心一致） | 用 Offline / Mock；其余功能不受影响。有凭据时应显示 READY |
| 研究被禁用（`research_disabled`） | `core` 或 `mcp` 不可用 | 先跑 `product_health.py` 看是哪一层 |
| 想批量校验 vault 结构 | — | `python3 _scripts/_tools/validate_vault.py` |

---

## 9. 已知限制（不要当成能力宣传）

1. **没有完整书目引文**：无出版元数据时只能给 internal / provenance 样式，
   并明确标注 `BIBLIOGRAPHIC_METADATA_INCOMPLETE`。
2. **没有自动对齐翻译**：中文/法文之间的对应关系由语料与术语映射决定，
   系统不做机器翻译，也不假造对应。
3. **没有人物 / 个案图谱**；`06_Clinical`、`07_Cases` 的浏览能力有限。
4. **形式化（拓扑/数学型）检索是白名单 + 正则**，不是完整解析器；
   语料里的形式写法可能漏检。
5. **没有全图 Explorer**：概念图只呈现已存在的关系，candidate 关系单独列出。
6. **不能在产品里直接编辑 canonical 本体**（这是设计决定，不是缺陷）。
7. **没有自动刷新机制**：笔记不会在你改语料后自动重算。
8. **真实 LLM provider 需要显式凭据**（`DSH_SYNTHESIS_API_KEY` 或 `~/.dsh/.credentials.yaml`）；离线 / mock 无需凭据且完全可用。真实 provider 的延迟与配额由 provider 侧决定。
9. **dense / 向量检索不可用**（本机无 numpy/向量索引运行时）：只用词法检索，
   浏览器会如实提示 `dense=False`。
10. **MCP 仅 stdio**；没有 HTTP/SSE 传输。
11. **DOCX / PDF 导出未实现**；只有 Markdown / JSON / HTML / bundle。
12. **`USER_EDITED_DOCUMENT` 导出入口未实现**（导出永远是原样快照）。
13. 语料里归属为 `unknown` 的场次/来源**无法**被系统补全 —— 这是语料的客观状态。
14. **语料"数据版本"与"学术语义"已分开判定**（`P5A-006`，Phase 5A 已解决）：
    冻结清单区分三类组件 —— 学术语义（变了就**硬失败**）、产品边界（记为运行态变化）、
    **数据版本**（语料清单 / 段落库 / 索引 / 本体：变化必须**被声明**且依赖构件状态一致）。
    两点仍然要记住：
    * 你**新增一份文档**到语料目录后，`core_freeze --verify` 仍会 FAIL 并暂停研究 ——
      这是刻意的：系统不会假装"什么都没变"。但现在的提示会**说清是哪一类漂移**，
      处置是一步**声明式**推进（`phase5a_corpus_diff.py` → `phase5a_declare_data_version.py`
      → 重建 → 复验），而不是过去那种"看不出到底什么变了"的死结；
    * **永远不要手工只改哈希**：那会把真正的语义漂移一起掩盖掉。
    * **新增文档不等于可检索**：`0926 卡特尔 下.docx` 目前只是**语料清单**里的文件，
      尚未进入可研究语料（`SOURCE_INVENTORY_ONLY`）—— 系统不会宣称它能被检索，
      要进可研究语料必须走既有的 ingestion / rebuild 流程。
15. **答案状态的可核对字段**在 Advanced 面板里，但产品界面**仍然无法显式要求**
    核心的 `insufficient_unanswerable` task_type（见 §5.2）；这是接口层限制。
16. **键盘操作**已按声明的契约验证（`Ctrl/Cmd+Enter` 提交、`Esc` 关 Inspector、
    Explorer 表单 `Enter` 提交），但本机没有自动化"真实硬件按键全遍历"能力，
    如实记录在 `_data/phase5a/keyboard_flows.json`。

---

## 10. 数据位置速查

| 内容 | 路径 |
|---|---|
| 研究历史 | `_workspace/history/` |
| 研究项目 | `_workspace/projects/` |
| 导出与 bundle | `_workspace/exports/`（+ `audit.jsonl`） |
| 生成的 Obsidian 笔记 | `_workspace/obsidian_vault/` |
| 冻结清单 | `_data/core_freeze/scholarly_core_freeze_v1.json`（39 个语义单元） |
| 冻结谱系 | `_data/core_freeze/freeze_lineage.json` |
| 冻结修复记录（5A） | `_data/phase5a/freeze_remediation.json` |
| 呈现分类法（5A） | `_data/product/presentation_taxonomy_v1.json` |
| 5A 产品缺陷与决策 | `_data/phase5a/issues.json`、`_data/phase5a/PDR-0001.json`、`_data/phase5a/DECISION_REQUEST_corpus_drift.md` |
| 5A 验收与 Gate | `_data/phase5a/phase5a_hardening_gate_v1.json`、`_data/phase5a/5a_acceptance_*.json` |
| 核心变更请求 | `_core_change_requests/requests/` |
| 测试记录 | `_data/index/TEST_RUN.json` |
| 验收工件 | `_data/product_acceptance/<run_id>/` |

---

## 11. 最短上手路径

```bash
cd <REPO>
python3 _scripts/_tools/product_health.py            # 看 9 层状态（provider 按凭据如实报 READY / DEGRADED）
python3 -m workspace_ui.server.cli                    # 起 UI
# 浏览器打开 http://127.0.0.1:3090
```

然后在 UI 里做一遍：

1. Research：`Seminar XI 中 gaze 与 objet a 是什么关系？`（Mock）→ 看 claim 的证据段；
2. 点 citation → 看 Evidence Inspector 的上下文与 `Trace source`；
3. Explorer → Concepts → 查 `objet petit a` → 看 canonical / 关系 / 语料佐证；
4. Passages → 找一段带 `SOURCE_TRACE_INCOMPLETE` 的 → 看它如何如实显示；
5. 把这次研究加入一个 Project → 在项目里复查 run 快照；
6. 导出 Markdown + bundle → 跑一次 `verify_bundle`；
7. Obsidian 里打开生成的笔记 → 在 `## My Notes` 写一行 → 再保存一次同样的研究
   → 确认你写的那行**一字未动**。
