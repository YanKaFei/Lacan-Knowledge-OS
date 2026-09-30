# Lacan Knowledge OS · 日用操作手册

> 面向**日常使用**，不是开发文档。
> 中文为主；界面、状态值、字段名一律**原样保留英文**。
> 本手册里的每个数字都从本仓库实际读出，读法写在 [附录 A](#附录-a--引文常见问题) 第 5 节。

**目录**

0. [第一次使用：从这里开始](#0-第一次使用从这里开始)（**新增**：任务型首页 + Help Center）
1. [一键启动](#1-一键启动)
2. [Research](#2-research)
3. [Explore](#3-explore)
4. [Projects](#4-projects)
5. [Bibliography](#5-bibliography)
6. [Zotero Import](#6-zotero-import)
7. [Obsidian](#7-obsidian)
8. [Export](#8-export)
9. [一键停止](#9-一键停止)
10. [故障排查](#10-故障排查)
11. [Help Center（帮助中心）](#11-help-center帮助中心)

---

## 0. 第一次使用：从这里开始

**打开系统时你看到的是「首页」，不是提问框**（P5D-005 之后默认如此）。
首页只回答两件事：**这是什么**、**我现在可以用它做什么**。

- **Hero**：`Lacan Knowledge OS` + 一句定位 + 两个按钮 ——
  `开始一次研究`（→ `/research`）、`第一次使用？`（→ `/help/getting-started`）。
- **你想做什么？**：6 张任务卡，每张都是**真链接**（可以右键「在新标签页打开」）：
  问一个拉康问题 / 寻找原文与出处 / 研究一个概念 / 研究人物与个案 /
  建立长期研究项目 / 管理文献与引用。
- **一次完整研究如何进行**：6 步流程（提出问题 → 查看支持证据 → 深入原文 →
  保存研究材料 → 整理来源 → 形成自己的知识），每一步都可点。
- **第一次使用？5 分钟完成第一次研究**：6 步清单 + 「查看完整教程」。
- 再往下才是 **System Status**（8 层状态，折叠着）与 **Recent**（最近研究/项目）。

**地址栏就是真路由**（P5D-005 起）：`/research`、`/explore`、`/projects`、
`/bibliography`、`/persons`、`/cases`、`/zotero`、`/help`、`/help/<主题>` 都可以直接打开、
收藏、分享；旧的 `?view=...` 深链**仍然有效**。

**每个模块右上角都有 `? Help`**，点它进的是**该模块专属**的帮助页
（Research\(\to\)`/help/research`、Explore\(\to\)`/help/explore`、Projects\(\to\)`/help/projects`、
Bibliography\(\to\)`/help/bibliography`、Persons/Cases\(\to\)`/help/persons-cases`、
Zotero\(\to\)`/help/zotero`）—— **不是**笼统的帮助首页。

---

## 11. Help Center（帮助中心）

`/help` 是真正的帮助中心：**左侧目录 + 正文 + 锚点 + Previous/Next + 返回模块**，
13 个主题，全部随界面语言即时切换（不刷新页面）：

| 主题 | 内容要点 |
|---|---|
| `/help/getting-started` | 5 分钟快速开始（用真实示例问题走完 Research→证据→原文→保存）|
| `/help/research` | Research 是什么 / 怎么问 / 控件 / 答案状态 / 弃权 / provider 不可用 |
| `/help/explore` | Explore 是什么 / 能浏览什么 / 什么时候该用它 |
| `/help/research-vs-explore` | **三者区别**：Research 从问题、Explore 从材料、Projects 长期课题 |
| `/help/projects` | Project 能装什么；**Project 内容不是 corpus evidence** |
| `/help/evidence` | **核心页**：Answer→Claim→Passage→Session→Seminar→Witness；Evidence Inspector |
| `/help/persons-cases` | Person ≠ Case；为什么不自动做影响推断 |
| `/help/bibliography` | reviewed ≠ metadata complete；candidate ≠ citable；逐样式可用性与原因 |
| `/help/zotero` | 支持 CSL JSON / Better BibTeX JSON；导入后**永远是 candidate** |
| `/help/obsidian` | 分工：证据/校验在这里，个人理解/写作在 Obsidian；**不是底层数据库** |
| `/help/languages` | 界面语言 vs 研究语言（`界面=中文 + 研究语言=Français` 合法）|
| `/help/statuses` | 状态速查：什么意思 / 为什么 / 该做什么 / 算不算错误 |
| `/help/troubleshooting` | 六类真实问题（Research 不通但 Explore 可用、引用不可用、中文来源 SOURCE_TRACE…）|

**两条纪律**（有自动化守着，见 `HELP_LINK_REPORT.json` / `HELP_CLAIM_VERIFICATION.json`）：

1. **UI 名称不写死**：帮助正文里引用控件时写的是产品词典的 key，
   渲染时取**当前界面语言下的真实标签** —— 帮助里不可能出现一个系统里不存在的按钮名。
2. **不虚构能力**：每条功能性断言都有机器可核的检验方式（真实浏览器 / API / 源码），
   `documentation_fiction = 0`、`pending = 0` 才算通过。

找东西的两条路：左侧目录（按 Start here / Modules / Reference / Troubleshooting 分组）
或目录上方的**搜索框**（按标题与摘要过滤主题）。

## 1. 一键启动

**你不需要命令行。双击就行。** 仓库根目录有三个文件：

| 文件 | 作用 |
|---|---|
| `Start Lacan Knowledge OS.command` | 启动 |
| `Stop Lacan Knowledge OS.command` | 停止 |
| `Check Lacan Knowledge OS.command` | 体检（**只读**，不会 kill 任何东西） |

它们是薄壳，实际执行 `_scripts/runtime/` 下的脚本：

```
_scripts/runtime/start_lacan_os.sh
_scripts/runtime/stop_lacan_os.sh
_scripts/runtime/check_lacan_os.sh
```

### 双击 Start 之后

- **只启动 UI 一个进程**；MCP 由 UI 自己 spawn。
- 默认自动打开浏览器到 `http://127.0.0.1:3090/`。
- **不联网、不调用 LLM、不重建语料或向量、不访问 Zotero 网络。**

**幂等** —— 已经在跑的时候再双击，不会起第二个进程：

```
ALREADY_RUNNING pid=<pid> url=http://127.0.0.1:3090/（未 spawn 任何进程）
```

**陈旧 PID 自动恢复**（记录还在但进程已死，或 PID 被别人复用了）：

```
STALE_PID_RECOVERED pid=<pid> reason=process_dead
STALE_PID_RECOVERED pid=<pid> reason=identity_mismatch
```

`identity_mismatch` 的意思是：这个 PID 活着，但**不是**我们的 UI 进程 ——
系统**不会动它**，只清理自己的记录然后正常启动。

**端口被外人占用时会明确拒绝，不做任何 kill：**

```
端口 3090 已被占用且**不是**我们的 UI（holder=<pid>）—— 未做任何 kill；请先处理该进程
```

### 换端口 / 换地址 / 不自动开浏览器

```bash
LACAN_NO_OPEN=1 _scripts/runtime/start_lacan_os.sh
LACAN_UI_PORT=3091 _scripts/runtime/start_lacan_os.sh
LACAN_UI_HOST=0.0.0.0 _scripts/runtime/start_lacan_os.sh
```

### 首页的 System Status：**8 层**

打开页面就是 **Home**（刻意不做 dashboard —— 只给入口、Recent、System Status、Help）。
其中 System Status 列出 **8 层**：

| 层 key | 界面标签 | 含义 |
|---|---|---|
| `core` | Scholarly Core | 冻结核心。`READY` / `UNAVAILABLE` |
| `mcp` | MCP | 检索服务连接。`READY` / `UNAVAILABLE` |
| `corpus` | Corpus | 语料层 |
| `workspace` | Workspace | 工作区 |
| `explorer` | Explorer | 浏览器 |
| `obsidian` | Obsidian | 写作区 |
| `bibliography` | Bibliography Registry | 书目登记表（附 `items / reviewed / candidates / editions / works` 计数） |
| `provider` | Real LLM Provider | 真实 LLM 通道。`READY` / `DEGRADED` |

> ⚠️ 「8 层」是**首页 System Status** 的口径（`/api/status`）。
> `_scripts/_tools/product_health.py` 是另一个独立的体检 CLI，它有 **9 层**
> （core / corpus_store / browse / mcp / workspace / obsidian / exports / projects / provider）。
> **两者不是同一个东西，别混。**

卡右下的 `Refresh` 按钮重新拉一次 `/api/status`。

### 首页五个入口按钮

| 按钮 | 去哪 |
|---|---|
| **Research** | 研究主界面（默认视图） |
| **Explore** | 只读浏览器首页（见 §3） |
| **Projects** | 研究项目列表（见 §4） |
| **Bibliography** | 书目浏览器（见 §5） |
| **Open Obsidian** | 打开 Obsidian 工作区（`obsidian://` URI，或提示直接打开文件夹） |

### 体检：双击 Check

输出的**前 9 行**是规范块（§38），下面才是详情；`<...>` 是随环境变化的字段：

```
Lacan Knowledge OS

Core          READY
Freeze        PASS
MCP           READY
Corpus        READY
Workspace     READY
Explorer      READY
Bibliography  READY   registry=READY items=7 reviewed=4 candidates=3 editions=1 works=4
Obsidian      READY
Provider      READY

—— 详情（<时间戳>）——
  repo            : <仓库路径>
  url             : http://127.0.0.1:3090/
  status          : RUNNING|NOT_RUNNING|PARTIAL
  ui pid          : <pid>  alive=yes  identity_ok=yes
  mcp child(ren)  : <pid>（本实例：<pid> 的子进程）
  mcp (repo-wide) : <pid>（同仓库全量，可能含并发会话）
  port listening  : yes  holder=<pid>
  http /api/status: code=200
  http bibliography_health: code=200  registry=READY items=7 reviewed=4 candidates=3 editions=1 works=4
  core freeze verify  : rc=0  <一行摘要>
  freeze lineage verify: rc=0  <一行摘要>
  core_freeze_verified : True
  mcp_connected        : True
  research_disabled    : False
  provider             : READY|DEGRADED
  degraded layers      : none
  layers (8/8 READY):
    - core=READY  - mcp=READY  - corpus=READY  - workspace=READY
    - explorer=READY  - obsidian=READY  - bibliography=READY  - provider=READY
  recent log lines (12):
    | ...
  verdict         : HEALTHY (exit=0)
```

> `items=7` = reviewed 4 + candidate 3。这是**客观计数**；系统不会给出任何「完整度百分比」。

**退出码规则：** 端口在听 ∧ UI 是我们的 ∧ `core=READY` → `exit=0`（`HEALTHY`）；否则 `NOT_HEALTHY`。

体检脚本**只打印白名单字段**，不会打印任何密钥或环境变量值。

**日志与 PID：**

```
_workspace/runtime/logs/ui-YYYYMMDD.log   # 按天分文件，启动时自动轮转
_workspace/runtime/ui.pid
```

**想知道运行时脚本本身没坏：**

```bash
_scripts/runtime/selftest_runtime.sh
```

---

## 2. Research

提问前有三个控件：**Mode**、**Provider**、**Research language**（P5D-004 修复后改名，见下）。

**Mode** 默认 `Scholarly`；另有 `Quick`、`Auto`，以及 Advanced 组：
`Concept` / `Relation` / `Comparison` / `Diachronic` / `Seminar-specific` / `Translation` /
`Formalism` / `Case`。

**Provider** 默认 `Offline / Mock`；另一个是 `Real LLM (explicit)` —— **必须你自己显式选**。

**Language（界面语言）** 是真正的界面切换：选 `中文` / `English` 后界面文案**立即**变化
（导航、按钮、标签、状态、帮助、空状态、表单、表头、错误提示），**不需要刷新页面**；
选择记在浏览器里，刷新/重开标签页都保持，`<html lang>` 同步为 `zh-CN` / `en`。
切换语言**绝不改动任何学术内容**（Lacan 原文、passage、引文、provenance、书目 metadata、你的笔记都不变）。

> 支持深链覆盖：`?uiLocale=zh` / `?uiLocale=en`（优先级最高，便于分享与自动化）。

**Research language（研究语言）** 是另一件事：默认 `Auto`，可指定 `中文` / `Français` / `English`。
它作为 **question language 随研究请求发送**，选完你能在控件旁看到状态行、答案头部显示
`question language: zh`；它**不翻译界面**，也**不改变**语料检索结果（检索语义是冻结的）。
想按语言筛选**段落**，用 Explorer 的 passage 搜索自带语言过滤器。

### 六种答案状态

每次回答都带一个状态。**请按字面读它**：

| 状态 | 界面文案 | 意思 |
|---|---|---|
| `VALIDATED` | Validated | 通过证据校验 |
| `VALIDATED_WITH_QUALIFICATIONS` | Validated with qualifications | 通过，但带限定条件 |
| `PARTIALLY_SUPPORTED` | Partially supported — not a fully validated answer | **不是**完整验证的答案 |
| `VALIDATION_FAILED` | Validation failed — the core could not validate this answer | 核心没能验证它 |
| `INSUFFICIENT_EVIDENCE` | Insufficient evidence | 语料不足以支撑 |
| `ABSTAINED` | Abstained | **拒答**（下详） |

另有 `STRUCTURALLY_UNAVAILABLE`（结构性不可用）与 `UNKNOWN`（未知状态）。

### `ABSTAINED` 不是错误

**拒答是一个正常、正确的输出。** 语料撑不住时，系统宁可不答。
界面标题写的就是 `Current corpus cannot support a reliable answer`。

拒答的解释放在答案的 `abstention` 块里 —— 所以 `ABSTAINED` 答案的 `source_limitations`
**本来就允许为空**，那不是缺字段。

允许拒答的权限枚举值是 `ABSTAIN`（不是 `ABSTENTION`）。

### 等一次研究的时候会发生什么（P5D-005）

一次研究是**一次阻塞往返**：核心只在返回后才有审计数据，中途没有进度可读。
所以界面只报**真实可观测**的东西，不编造百分比进度：

- 研究按钮右侧显示**真实秒数**（`Working… 12s · corpus retrieval → evidence contract
  (model synthesis only if the evidence is sufficient)`）。
  这句话只是**顺序说明**，不是进度条 —— 没有"第 2/5 步"这种字段可读。
- **Stop waiting** 只停止**等待**；后端作业可能仍在跑（文案如实这么写）。
  选 `Real LLM` 时请求走**作业化**路径（`POST /api/research/job`），
  提交立刻返回、页面每秒更新真实耗时，不会整页假死。
- 勾选 **Ignore cache (recompute)** 会真的一次重算（`fresh: true`），
  答案头部的溯源会写 `forced recompute`；不勾时命中缓存会写 `served from cache`。

### 答案头部的溯源：谁回答的、等了多久

每个答案头部有一行**产品层实测**的溯源（不是核心的学术判定）：

```
mock adapter (no model call) · 16.7s · computed now
llm: deepseek-chat · 44.6s · computed now · attempts: 2 (after PROVIDER_UNAVAILABLE)
```

- `mock adapter (no model call)` = 这次**没有**调用任何模型（确定性 mock）。
  `llm: <model>` 里的模型名来自你配置的 provider 设置。
- 秒数是**墙钟**（产品层计时），`Attempts` 是**真实发送次数**。
- `attempts: 2` 只在**基础设施类**失败（端点连不上 / 调用失败）后出现 ——
  学术判定类结果（`VALIDATION_FAILED`、`ABSTAINED`…）**永不重试**：
  重发一次不会让一个结论变成证据。

### Model provider settings（换模型 / 看凭据 / 测连通）

提问框下方的 **Model provider settings** 折叠面板（P5D-005 新增）：

- **Model / Base URL**：可以改，改完点 **Save settings**，下一次研究生效
  （产品层写 `_workspace/settings/provider.json` + 重启共享 MCP 子进程，
  所以子进程能继承新环境变量）。
- **凭据**：只显示**有没有**、从哪来（`DSH_SYNTHESIS_API_KEY` 或
  `~/.dsh/.credentials.yaml`）。**密钥永不经过产品 API** —— 不接受前端输入，也不回显。
- **Per-call cap: 120s** 是**只读**信息：单次模型调用上限由冻结核心写死，产品层改不了；
  单次研究请求的 MCP 上限是 900s。
- **Test connection**：真的发一次极小请求（`max_tokens=4`）看端点通不通，
  只报 HTTP 状态 / 耗时 / 端点返回的模型名；失败只报**类型**，不打印密钥。
- 端点不可达时，错误卡会给出两个**真动作**：**Retry once**、
  **Open provider settings**（点了会打开上面的面板并拉取当前设置）。

### Provider 不可用**不**阻塞本地使用

- `provider` 层的 `DEGRADED` 表示**没有配置真实 LLM 凭据**（`credentials_present = false`）。
  **这是配置状态，不是产品故障** —— 离线 / mock 研究完全可用。
- 只有**离线也做不了事**时才算产品级禁用：

  ```
  research_disabled = (not mcp_connected) or (not core_freeze_verified)
  ```

  provider **不在**这个判断里。
- 系统**不会**用模型知识兜底。没有凭据就是没有凭据 —— 降级，而不是编造。

### 答案上的动作

答案下方有动作条：

- **Save to Obsidian** → 见 §7
- **Add to Project** → 见 §4
- **Export**（Markdown / JSON / HTML / Bundle）与 **Preview** → 见 §8
- 保存成功后出现 **Open in Obsidian** 链接

### 看答案时的分层纪律

呈现层把内容分成四类，各走各的通道：

```
SCHOLARLY_CONTENT      → 正文、笔记、导出
SCHOLARLY_LIMITATION   → 答案里如实标注的局限
AUDIT_DIAGNOSTIC       → 只进 Advanced/Audit 与 Audit Bundle，**不进**默认答案/笔记/导出
OPERATIONAL_ERROR      → 运维错误
```

校验器诊断属于 `AUDIT_DIAGNOSTIC` —— 它不会混进你的答案正文。

---

## 3. Explore

Explore 首页写着 `Read-only browse over the local corpus and registries.`
七个入口：

| 按钮 | 去哪 |
|---|---|
| **Concepts** | 概念浏览器 |
| **Persons** | 人物登记表（`?view=entities&kind=person`） |
| **Cases** | 个案登记表（`?view=entities&kind=case`） |
| **Seminars** | 研讨班 |
| **Passages** | 段落（可直接定位到 passage_id） |
| **Terminology** | 术语 |
| **Bibliography** | 书目浏览器（见 §5） |

### 登记表是「确定性匹配」的产物，**不是 NER**

人物/个案登记表由 `_scripts/_tools/build_entity_registries.py` 生成，其头部铁律写明：

> **禁止自动全库 NER promotion**：本工具不做命名实体识别。
> 它只对**显式声明**的控制对象做**确定性字符串匹配**。

登记表里记的 `method` 是 `DETERMINISTIC_ALIAS_MATCH`，`no_automatic_ner_promotion = true`，
最小提及阈值 `min_mentions_threshold = 3`。

**当前规模：**

| 项 | 值 |
|---|---|
| 扫描段落 | 249,105 |
| 人工声明的种子实体 | 12 |
| 进入 `reviewed` 登记表的人物 | 7 |
| 进入 `reviewed` 登记表的个案 | 5 |
| 未晋级的候选 | 0 |
| mention 索引行数 | 7,684 |
| mention 索引被截断的实体 | `person.freud`（上限 4,000，如实标 `truncated`） |

**因此：没被登记 ≠ 不存在。** 登记表只收录**显式声明 + 过阈值**的实体 ——
它是一张受控清单，**不是全集**。

### 四条不能越过的边界

登记表 `rules` 与 manifest 的 `separation_invariants` 把边界写死了（全部为 `true`）：

| 不变式 | 人话 |
|---|---|
| `person_and_case_are_distinct_namespaces` | `person.X` 与 `case.X` 是**两个不同的实体**，`person.schreber != case.schreber` |
| `person_never_auto_collapses_into_case` | 禁止把人物自动折叠成个案（`project_api/entities.py`：禁止把 `person.X` 当作 `case.X`） |
| `mention_never_implies_influence` | **提及 ≠ 影响**。所有登记的 `asserts_influence` 一律 `false`，`evidence_kind` 是 `MENTION_ONLY` |
| `case_mention_never_implies_case_analysis` | **个案提及 ≠ 个案分析**。`asserts_case_analysis` 一律 `false` |

另外两条也一律 `false`：`asserts_theoretical_relation`（共现 ≠ 理论关系）、
`alias_never_implies_conceptual_synonym`（别名 ≠ 概念同义）。

**「Case → Subject Person」的连线只在有证据时建立。** 例如 Schreber：
`case.schreber` 与 `person.schreber` 是两个不同 ID，连线靠
`link_evidence_n = 10` 条证据成立（`subject_person_link_asserted = true`）。
没有证据的实体，这个字段就是 `null` —— 系统**不会**替你连。

### 一个真实的数字长什么样

`case.schreber` 的登记项：

```
mention_count = 614      by_authority_level = {L1: 303, L2: 311}
by_language = {fr: 303, zh: 311}
case_marker_hits = 223   evidence_kind = MENTION_ONLY
asserts_case_analysis = false   asserts_influence = false
asserts_theoretical_relation = false
```

注意 `case_marker_hits = 223` 与 `asserts_case_analysis = false` **同时存在** ——
即使个案标记语言命中 223 次，系统仍然**不**声称做过个案分析。这就是纪律。

### 首页 Help 写着的两个工作流

首页 **How to work here** 给了两条固定动线，照着走就不会乱：

```
Explore → Research → Inspect Evidence → Add to Project → Save to Obsidian
Bibliography → Inspect Metadata → Check Citation Availability → Add to Project
```

另一张卡片写着一句要记住的话：

> Formal bibliographic citations (Chicago/APA/MLA/BibTeX) are offered only when
> verified publication metadata exists. **Nothing is invented.**
> （正式书目引文只在**已核实的出版信息确实存在**时才提供。**不编造任何东西。**）

---

## 4. Projects

### Project 是工作区对象，**不是证据**

**Project 属于 `USER_WORKSPACE`，它永远不是 evidence。**
项目里的任何东西都不能当作语料依据 —— 它只是你的工作台。

Project 与书目之间有一条硬规矩：**candidate 不得挂到项目上**。服务端直接拒绝：

```
candidate item 不得挂到项目（§12/§33）：<bibliographic_id>
```

只有 `reviewed` 条目才挂得上去（见 §5）。

### 项目书目分三组

Project 详情页的书目区分成**三个组**，而不是一锅：

| 组 | 字段 | 内容 |
|---|---|---|
| ① 已挂的登记表条目 | `project_bibliography_refs` | 你从 registry 显式挂上去的 reviewed 条目 |
| ② 你手填的参考 | `legacy_user_supplied_refs` | 你自己写的自由文本参考 |
| ③ 不可挂的候选 | `bibliography_candidates_not_linkable` | 候选条目，**明说不能挂** |

第 ③ 组的理由字段写的就是：

```
candidate — needs review before it can be referenced
```

**为什么要单列第 ③ 组？** 因为沉默最糟。候选就在库里，用户会想问「为什么它挂不上」——
系统直接把它们列出来并说明原因，而不是让它们凭空消失。

第 ② 组带一个 `legacy_adapter` 说明：旧格式是**以只读方式适配呈现**的。

### 关联是显式动作

从「你手填的参考」升级成「登记表条目」，靠的是**你点** `Link`：

```
project_link_legacy_ref(project_id, expected_revision, ref_id, bibliographic_id)
```

代码注释写得很直接：

> 显式关联（用户确认的动作）；**不迁移、不删除** legacy 记录（§46）

**旧记录一律保留、不重写、不迁移。** 系统不会「顺手帮你规范化」你以前写的东西。

`expected_revision` 是并发保护：你手里的版本号和服务器不一致时，写入会被拒 ——
**不会**悄悄覆盖别的窗口的改动。

### 项目还能做什么

- **Add to Project**（研究答案动作条上）：把一次研究挂进项目。
- **Export manifest**：`/api/projects/manifest` 导出项目清单（见 §8）。
- **Obsidian sync**：`/api/projects/obsidian_sync` 生成/刷新项目笔记（见 §7）。
- 项目笔记写在 `_workspace/obsidian_vault/Projects/`。
  当前工作区里已经有一份：`拉康欲望理论研究.md`。

---

## 5. Bibliography

### reviewed 与 candidate 是两种东西

| | reviewed | candidate |
|---|---|---|
| 进 `items` 登记表 | ✅ | ❌（进 `candidates`） |
| 可被引用 | ✅（满足条件时） | ❌ **永远不可引用** |
| 可挂到 Project | ✅ | ❌（明确拒绝） |
| 当前 `review_basis` | `HUMAN_VAULT_REVIEW` 或 `MACHINE_VERIFIED_DERIVATION` | `PENDING_HUMAN_REVIEW` |
| 当前 `review_status` | `reviewed` | `needs_review` |

**当前实际分布（4 条 reviewed + 3 条 candidate）：**

reviewed：

| ID | review_basis | metadata_completeness |
|---|---|---|
| `bib.doc.lacan.seminar-3` | `HUMAN_VAULT_REVIEW` | `PARTIAL` |
| `bib.witness.seuil-pdf` | `MACHINE_VERIFIED_DERIVATION` | `INTERNAL_ONLY` |
| `bib.witness.staferla` | `MACHINE_VERIFIED_DERIVATION` | `INTERNAL_ONLY` |
| `bib.witness.translation-project` | `MACHINE_VERIFIED_DERIVATION` | `INTERNAL_ONLY` |

candidate（3 条，全部 `PENDING_HUMAN_REVIEW` / `needs_review`）：

```
bib.doc.arcachon.2001         PARTIAL
bib.doc.bourbon.presentation  INTERNAL_ONLY
bib.doc.lacan.seminar-23      PARTIAL
```

> **`MACHINE_VERIFIED_DERIVATION` 是什么意思？**
> 它是**确定性推导**：这条 witness 记录是从 vault 里的语料机械算出来的，可复核、可重跑。
> 它**不是**人类阅读后确认的学术结论。底下对应的 `corpus_source` 行仍然是 `needs_review` ——
> 未经 source linking 与人工审核，**不得升级为 canonical**。

界面还会额外提示候选的性质，免得你以为是 bug：

```
NOT CITABLE — candidate record (never canonicalized automatically).
```

### 链条视图：五层，缺一层就写 `Not linked`

书目详情页展示完整链条：

```
Passage → Witness → Edition → BibliographicItem → CorpusSource
```

**缺的层不会被隐藏** —— 一律显示 `Not linked`，并且说明为什么。
这是刻意的：`Not linked` **本身就是信息**。

### 三个真实的走走看

**① Seuil PDF：0 段**

`bib.witness.seuil-pdf` → `witness.fr.seuil-pdf`，链条是完整的：
它挂着 `edition.seuil-pdf`，`corpus_source_id = corpus-source.seuil-print`（kind = `print_edition`）。

但它的 `passage_count = 0`。界面显示：

```
Not linked (0 passages from this witness)
```

注意这里的细节：**edition 层是真的有页码的** ——
`edition.seuil-pdf` 记着 `page_locator_available = true`、`page_locator_kind = page`，
它的 `why_publisher_null` 写得很清楚：

> 仓库未记录出版社字段（§8：不得据模型知识补）

所以这不是「缺页」，而是：**这个 witness 在本地语料里没有实现出任何段落**，
于是段落级的引用**没有东西可指**。edition 上写着有页码，和 witness 上有 0 段，
**两件事都成立，不矛盾**。

**② Staferla：166,527 段**

`bib.witness.staferla` → `witness.fr.staferla`：

```
passage_count = 166527
edition_id = null
edition_not_linked_reason = working transcription（非瑟伊版定本）
corpus_source_id = corpus-source.staferla   (kind = transcription_site)
```

它是**工作转录**，不是瑟伊版定本，所以 `edition_id` 就是 `null` ——
系统**不会**随便挂一个版本上去。链条里 Edition 层显示 `Not linked`。

引用它时必须带限定：

> Document de travail (transcription STAFERLA) — texte non établi
> 引用必须标注「工作转录，非瑟伊版定本」

**③ 中文回译项目：`SOURCE_TRACE_INCOMPLETE`**

`bib.witness.translation-project` → `witness.zh.translation-project`：

```
passage_count = 82578
edition_id = null
edition_not_linked_reason = translation project with SOURCE_TRACE_INCOMPLETE（上游源目录已消失）
corpus_source_id = corpus-source.zh-translation-project  (kind = translation_project)
```

`corpus-source.zh-translation-project` 的 note：

> 社区中译项目。**上游源目录已消失** —— 现存 jsonl 是唯一副本（见 BACKUP_MANIFEST）。
> 未经 source linking 与人工审核，不得升级为 canonical。

**`SOURCE_TRACE_INCOMPLETE` 不是故障。** 界面用的是这段固定说明：

> 当前文本可在 recovered corpus 中验证，但无法完整追溯到原始物理来源。
> 这是 source limitation，不是系统故障。

对应地，它的 `edition_id` 就是 `null`，并且会**一直**是 `null`。

### 为什么 Chicago / APA 可能不可用

> **原文口径：** Because the current corpus may lack verified publication metadata.
> The system will not invent publisher, year, ISBN, or page numbers.
> （因为当前语料可能缺少**已核实**的出版元数据。系统**不会**编造出版社、年份、ISBN 或页码。）

具体到当前状态：**因为系统没有已核实的出版社和年份，而它不会猜。**

每条条目的 `style_reasons` 都写着缺哪些字段，而这些字段在登记表里就是 `null`：

```
publisher        = null
publication_year = null
isbn             = null
```

系统**不会**：

- 拿模型记忆里的出版社填进去
- 拿一个「大概是这一年」的年份填进去
- 拿一个看着像 ISBN 的字符串填进去

`edition.seuil-pdf` 把这层意思直接写进字段里：

> `why_publisher_null`: 仓库未记录出版社字段（§8：不得据模型知识补）

**所以 `UNAVAILABLE` 是一个诚实的答案，不是待办事项。** 它是终态，不是「以后会填上」。

### 三类引用

引用分**三类**，指向的东西完全不同：

| 类别 | 样式 | 层级 | 需要什么 |
|---|---|---|---|
| **Internal Citation** | `internal_short`、`internal_full` | passage-level | 一个**已连上的 PassageRealization**（`passage_id`） |
| **Provenance Citation** | `provenance` | passage-level | 同上（指向来源链与层级，而非出版信息） |
| **Formal Bibliographic Citation** | `Chicago`、`APA`、`MLA`、`BibTeX` | bibliographic-level | 已核实的出版信息（作者 / 出版社 / 年份 / ISBN …） |

**差别在「指向什么」**：

- **Internal / Provenance** 指向**语料里的一段话**（`passage_id` → seminar → source layer → witness → provenance）。
- **Formal Bibliographic** 指向**一份出版物**。

**两者不能互相代替。** 段落级要 `passage_id`，书目级要出版元数据。

### 逐样式可用性 —— **一定给原因**

书目浏览器的每条样式都显示 `READY` 或 `UNAVAILABLE`，**并且给理由**。
系统不会只把按钮打灰然后不说为什么。

当前五个取样条目的能力矩阵完全一致：

```
internal_short = true    internal_full = true    provenance = true
chicago = false   apa = false   mla = false   bibtex = false
internal_citation_ready = true
bibliographic_citation_ready = false
bibtex_ready = false
missing_fields = [authors, page_locator, publication_year, publisher]
```

每个样式的理由字段（`style_reasons`）写的是同一类话：

```
chicago : Missing verified metadata: author, publisher, publication year
apa     : Missing verified metadata: author, publication year, publisher
mla     : Missing verified metadata: author, publisher, publication year
bibtex  : Missing verified metadata: author, publication year
```

> ⚠️ 上表是**条目级能力矩阵**（`capability_matrix`）：回答「**这类**记录是否支持该样式」。
> 段落级样式最终是否可用，还要看**是否真的存在 PassageRealization**。
> 例：Seuil 的 `internal_short` 在矩阵里是 `true`，但 UI 的 Citation Availability 显示
> `Internal Short — UNAVAILABLE · why: no PassageRealization linked: Passage Realizations = 0`
> —— 因为该 witness 在 canonical passage store 里**没有产出任何段落**，段落级引用没有东西可指。
> 卡片里同时会显示 `Passage Realizations: 0`，这是同一件事的两种呈现，**不是** bug。

还有一个 `soft_missing` 概念：`page_locator` **不是**所有样式都需要，
但**确实没有已核实的值** —— 所以它单列，并附 `soft_missing_note`：

```
Not required for the style, but no verified value exists: page_locator
```

### ⚠️ Reviewed does **NOT** mean bibliographically complete

**这是最容易误读的地方，单列一段。**

`review_status = reviewed` 只说明「这条记录**经得起复核**」，**不说明**它的书目信息完整。

事实上当前**没有任何一条 reviewed 条目**能生成完整的 Chicago / APA / MLA / BibTeX ——
它们的 `publisher` / `publication_year` / `isbn` 全部是 `null`。

**这是两个独立的问题：**

| | 回答的问题 |
|---|---|
| **review_status** | 这条记录**能不能被采信为一条记录**？（从哪来？谁推导的？canonical 吗？可复核吗？） |
| **bibliographic completeness** | 这条记录**有没有足够信息排出一条正式引文**？（作者？出版社？年份？ISBN？） |

**这两个问题完全独立：**

- 一条记录可以是 `reviewed` 但 metadata 只到 `INTERNAL_ONLY` —— 当前**全部**如此。
- 一条记录 metadata 凑齐了也可能还不是 reviewed。
- 当前状态是：**4 条 reviewed，0 条 `PUBLISHABLE`** ——
  其中 3 条是 `INTERNAL_ONLY`（三个 witness），1 条是 `PARTIAL`（`bib.doc.lacan.seminar-3`）。

metadata completeness 的三档是 `INTERNAL_ONLY` / `PARTIAL` / `PUBLISHABLE`。
**当前没有任何一条是 `PUBLISHABLE`。**

**务实结论：** 现在能用的引文是**段落级的 Internal 与 Provenance**。
正式书目引文要等到有人把出版信息核实进 vault —— 那是**人类动作**，系统不会代劳。

### candidate 永远不可引用

这一条是硬的。`candidate` 记录**不会**显示任何引用按钮。

服务端在可用性判定里写死：

```
available = bool(capability_ok and not is_candidate)
note      = "candidate record — not citable"   # 当它是 candidate 时
```

> ⚠️ **注意一个容易看错的地方**：candidate 条目的**原始能力矩阵**里
> `internal_citation_ready` 仍然可能是 `true`（那只反映元数据形态）。
> **能不能引用**是能力矩阵**之外**再加的一道判定 —— 必须 `review_status == reviewed`。
> 所以「矩阵说 true」**不等于**「可以引」。

另外，即使条目是 reviewed，段落级引用**还需要一个 `passage_id`**：
没给的话返回 `PASSAGE_REQUIRED_FOR_INTERNAL_STYLE`。

### 一个 renderer，四处分发

**同一条目 + 同一样式，在 UI 复制、Export、Obsidian 笔记、Project 里必须是同一段文字。**

因为它们走的是**同一个 renderer**，而且每条引文都带 `identity_hash`。
如果两个地方显示的文字不一样，那是 bug，不是「显示偏好」。

---

## 6. Zotero Import

### 只支持两种文件格式

书目页里有个折叠面板 **Import (Zotero / CSL JSON)**，界面原文：

> Supported: CSL JSON, Better BibTeX JSON. Imported items are always candidates —
> there is no "approve all" step.

| 控件 | id |
|---|---|
| 文件选择 | `bib-import-file`（accept `.json,.bibtex,.bib,application/json`） |
| 格式下拉 | `bib-import-source` → `CSL JSON` / `Better BibTeX JSON` |
| 预览按钮 | `bib-import-preview`，文案 `Preview` |
| 提交按钮 | `bib-import-commit`，文案 **`Import as candidate`** |

**没有 XML / EndNote / RIS 支持。** 传错格式会 fail closed 到 `rejected`。

### 导入的东西**永远是 candidate**

**没有「Import & Approve All」，也没有任何一键批准。**
提交按钮的文案本身就是 `Import as candidate`；成功后界面显示：

> Imported as candidate. Not automatically canonicalized.

而且这是**文件导入 / 导出**，不是同步：
**没有 Zotero API 调用，没有网络请求。** 你从 Zotero 导出文件，再把文件交给这里。

流程永远是**两步**：先 `Preview`，看清楚，再 `Import as candidate`。

### 预览里能看到什么

预览表每行是：

```
Title / Author / Year / Identifier / Duplicate / Conflict
```

并给出四个计数：

```
candidates=N · duplicates=N · conflicts=N · rejected=N
```

**大小上限**：单文件 8 MiB，最多 5,000 条。超限返回 `IMPORT_TOO_LARGE`。

### 去重：强 / 弱两档

| 档 | 依据 | 界面文案 |
|---|---|---|
| **强** | DOI / ISBN / Zotero key 完全命中 | `Strong duplicate` |
| **弱** | 标题 + 作者 + 年份 相近 | `Possible duplicate` |

**关键：去重从不自动合并。** 每条都带 `auto_merged` 字段，你可以自己看：

```
Strong duplicate (doi)      — auto_merged=False
Possible duplicate (title_author_year) — auto_merged=False
```

### 冲突只显示，不裁决

导入时若同一字段出现不同值，会列成冲突项，带 `code`、字段名、
各值及其候选 ID、`resolution`，以及：

```
auto_overwrite=False
```

**冲突是 display-only。** 系统不会替你选一个「更对」的值覆盖另一个。

导入完成后冲突库可通过 `/api/explore/bibliography_conflicts` 查看
（当前 `conflicts = 0`）。

格式错误、URL 不安全等一律**fail closed**：条目进 `rejected` 并带错误码
（例如 `UNSAFE_URL_SCHEME`），**不会静默丢弃，也不会带病入库**。

---

## 7. Obsidian

### 唯一的 Source of Truth 就是这个仓库

仓库根目录**就是**那个 Obsidian vault：`.obsidian` 在，17 个 canonical 分区齐备。

```
00_System  01_Sources  02_Lacan_Seminars  03_Ecrits  04_Concepts
05_Terminology  06_Clinical  07_Cases  08_Topology_Mathemes
09_Philosophy  10_Freud  11_Thinkers  12_Schools_Debates
13_Reading_Notes  14_Synthesis  15_Questions  16_Research_Projects
```

而**产品写入区**是另一个地方 —— `_workspace/obsidian_vault/`（登记为 `USER_WORKSPACE`）：

```
Research/    Passages/    Concepts/    Seminars/    Projects/    Sources/    _System/
```

**AI 产出永不自动成为 canonical。** 研究结果、派生笔记都写到上面这个工作区；
要进 canonical 分区，必须是**人类显式动作**。

### 两种打开方式

- **Home → Open Obsidian**：读 `/api/obsidian/status`，走 `obsidian://` URI 打开；
  没配 URI 时会提示直接打开文件夹。
- 左侧导航里也有一个 `Obsidian` 按钮 —— **但当前构建里它没有绑定任何视图**
  （其他导航项都带 `data-view`，它没有）。请用 Home 的按钮，
  或在答案/项目上的保存结果里点 **Open in Obsidian**。

### 会生成哪几种笔记

四种 artifact（`obsidian-adapter/v1`）：Research Note / Saved Passage Note /
Concept Reference Note / Seminar Note。此外项目侧还有一个 Project Note：

| 笔记 | 写在哪 | 什么时候生成 |
|---|---|---|
| **Research Note** | `Research/` | 你在答案上点 **Save to Obsidian** |
| **Saved Passage Note** | `Passages/` | 只为**被实际引用**的段落生成 |
| **Concept Reference Note** | `Concepts/` | 随研究一起，最多 8 个概念链接 |
| **Seminar Note** | `Seminars/` | 随引用到的研讨班一起 |
| **Project Note** | `Projects/` | 项目侧生成/同步 |

Research Note 的文件名是 `YYYY-MM-DD - <问题 slug>.md`。

### 五条写作纪律

1. **答案原样保存，不重新总结。**
   Research Note 里保存的是**已验证的最终学术答案** —— 系统**不会**再让 LLM 压缩一遍。
2. **研究答案绝不写成概念定义。**
   它只进 **Related Research** 区块，不会被塞进 concept 笔记当定义。
3. **段落只在被实际引用时才 materialize。** 有硬上限，不会把全库铺开。
4. **用户区永不被覆盖。**
   `## My Notes` 以及 managed 区块**之外**的文本**逐字节保留**。
   已存在的、非本系统管理的文件**绝不重写**。
5. **一切写入走 `scholarly_api.policy` 闸门** —— 只可能落在 `USER_WORKSPACE`。

### managed 区块与「你改过没有」

系统生成的正文包在一对标记里：

```
<!-- LACAN-OS:GENERATED:START -->
...
<!-- LACAN-OS:GENERATED:END -->
```

**标记之外是你的地盘。** 系统重新生成时只替换标记之间的内容。

系统也记着生成正文的哈希，用来判断笔记状态：

| 状态 | 意思 |
|---|---|
| `VERIFIED` | 生成内容与记录一致 |
| `MODIFIED_BY_USER` | 你在生成区里动过手 |
| `UNKNOWN` | 无法判定 |

### 保存是事务性的，也是幂等的

- **事务性**：先预检全部路径 → 全部写 temp → 原子 rename；失败**回滚**，不留半成品。
- **幂等**：同一 `research_id` 已经存过 → 返回 `already_saved`，
  **不会静默覆盖**。界面上会显示 `(already saved)`。

保存结果卡片还会告诉你这次顺带生成了什么：

```
Saved to Obsidian   Research/2026-09-27 - ....md
linked: 6 passages · 3 concepts · 2 seminars
```

### 两个要注意的细节

**① 语料里的图片嵌入会变成纯文本。**

corpus 里的 `![[…/image21.jpeg|200]]` 会被转成：

```
`[asset: …/image21.jpeg]`
```

**为什么？** 因为 **corpus 是只读的，工作区不复制原始材料**。
所以 corpus 相对路径的 embed 在 Obsidian 里**必然是破图**（悬空嵌入）。
系统保留路径本身（可回查），只去掉 embed 语法 —— **信息不丢，链接不悬空**。

**② 溯源不完整的文本会带一句固定说明。**

```
**Source trace incomplete** — 当前 recovered 文本可验证，但来源链未闭合到原始物理文件。
```

这不是错误提示，是**来源限制的如实标注**（见 §5 的 `SOURCE_TRACE_INCOMPLETE`）。

### 当前工作区的真实状态

```
active_root  = _workspace/obsidian_vault/       root_kind = project-workspace
counts       = research 0 · passages 0 · concepts 0 · seminars 0 · projects 1 · sources 0
```

也就是说：工作区**几乎是空的**，目前只有一份项目笔记 `Projects/拉康欲望理论研究.md`。
canonical 分区一个没动。这是**如实状态**，不是故障。

---

## 8. Export

### 四种格式

答案上的 **Export** 菜单只有**已实现**的格式：

| 格式 | 标签 | 扩展名 |
|---|---|---|
| `markdown` | Markdown | `.md` |
| `json` | JSON | `.json` |
| `html` | HTML | `.html` |
| `bundle` | **Research Bundle** | 目录（+ ZIP） |

### 只写一个地方

所有导出**只落 export root**：

```
_workspace/exports/          （USER_WORKSPACE）
```

写入一律经 `export_system.policy` 闸门 —— 越界会被拒。

导出审计记录追加在：

```
_workspace/exports/audit.jsonl
```

导出列表页（左侧导航 **Exports**）会显示：

```
Exports (20)
Root: _workspace/exports（USER_WORKSPACE）
```

每项标 `file` 或 `bundle`。**bundle 带一个 `verify` 按钮**，点一下告诉你它的状态。

### Preview 不是另写一份摘要

```
Preview renders the ExportDocument itself — no extra summary is generated.
```

**预览只能是后端 ExportDocument 的渲染结果** —— 前端不允许
「临时再生成一份摘要」。所以你看到的预览和导出的文件是同一份东西。

### 导出菜单里的引文样式

导出菜单里的 citation styles 与 §5 的三类引用一致：

```
可用    ： internal-short / internal-full / provenance
不可用   ： chicago / mla / apa / bibtex
理由     ： requires complete bibliographic metadata
```

系统对不可用样式的做法是**广而告之但默认关闭**：

> Bibliographic styles are advertised but only enabled when the metadata really
> exists.（书目样式会列出来，但只在元数据**确实存在**时才启用。）

界面上，**不可用的样式不显示按钮**，只显示原因。原因就是
`BIBLIOGRAPHIC_METADATA_INCOMPLETE`（见 §5 的 §34 口径）。

### Research Bundle 里有什么

```
bundle/
    README.md
    manifest.json
    research/<run_id>.md | .json
    claims/claims.json
    citations/citations.json
    passages/<passage_id>.json
    provenance/provenance.json
    project/project.json
    bibliography/bibliography.json
```

**两条硬门禁：**

1. **不得 materialize 全库** —— 只导出**被引用 / 被保存 / 显式选择**的 passage。
2. **流程固定**：`build temp → validate → hash → manifest → verify → atomic finalize`。
   **失败不留半成品**；ZIP 在目录 verify **之后**才压缩，并且防 zip slip。

### verify 会检查什么

bundle 的 `verify` 返回三种状态：

| 状态 | 意思 |
|---|---|
| `VERIFIED` | 全部检查通过 |
| `MODIFIED` | 内容与 manifest 对不上（哈希不符、多出未登记文件、文件数不符…） |
| `BROKEN` | 缺文件 / 引文无法解析 / schema 不过 |

具体检查项：

- `manifest.json` 在、是合法 JSON、过 schema
- 每个登记文件**存在**且 **sha256 与 manifest 一致**
- **没有未登记的多余文件**
- `file_count` 与 `bundle_hash` 自洽
- 每条 citation 的 `passage_id` **能在语料里解析出来**
- `provenance/provenance.json` 在

**当前实际状态：导出根下共 20 项，其中 5 个 bundle —— 5 个全部 `VERIFIED`。**

### Audit Bundle 要**显式**点

校验器诊断属于审计内容。**标准导出默认不含审计内容**；
要拿 Audit Bundle，必须点那个单独的 `Export Audit Bundle` 按钮
（后端 `include_audit = True`）。

同理，Obsidian 保存也只有在显式选择时才另存审计工件 ——
**标准笔记不变**。

### 导出可能报的错

| 错误码 | 常见含义 |
|---|---|
| `BIBLIOGRAPHIC_METADATA_INCOMPLETE` | 你要的样式缺已核实的出版信息（见 §5） |
| `UNSUPPORTED_FORMAT` | 格式不在四种之内 |
| `EXPORT_POLICY_DENIED` | 落点越界（只许 `_workspace/exports/**`） |
| `EXPORT_SOURCE_NOT_FOUND` | 源对象不存在 |
| `EXPORT_SOURCE_MODIFIED` | 源在你操作期间被改过 —— 保护你，不是 bug |
| `BROKEN_REFERENCE` | 引文断链 |
| `SCHEMA_VALIDATION_FAILED` | 结构不合格 |
| `EXPORT_WRITE_FAILED` | 落盘失败 |

---

## 9. 一键停止

双击 `Stop Lacan Knowledge OS.command`（或跑 `_scripts/runtime/stop_lacan_os.sh`）。

**幂等** —— 没在跑也返回成功：

```
NOT_RUNNING（无 PID 记录）
```

停止时**只杀身份通过的 PID** 及其 MCP 子进程，先 `TERM`，10 秒不退再 `KILL`。

若记录的 PID 身份不符，会明确跳过 —— **这是保护，不是失败**：

```
SKIPPED pid=<pid> 身份不符（不是 workspace_ui.server.cli）—— **未发送任何信号**
```

若 PID 记录是陈旧的（进程已死），会自动清理：

```
STALE_PID_RECOVERED pid=<pid> reason=process_dead（stop）
NOT_RUNNING（陈旧记录已清理）
```

正常结束会打两行收尾：

```
端口 3090 已释放
STOPPED pid=<pid>
```

**若端口仍被监听但持有者不是我们**，它只报告、**不动手**：

```
端口 3090 仍在监听（holder=<pid>）—— 未做任何 kill
```

---

## 10. 故障排查

### 先跑体检

```bash
_scripts/runtime/check_lacan_os.sh
```

或者双击 `Check Lacan Knowledge OS.command`。**它是只读的**，不会 kill 任何东西。

### 症状对照表

| 症状 | 怎么做 |
|---|---|
| 双击 Start 没反应 / 页面没开 | 再双击一次；若输出 `ALREADY_RUNNING`，复制那个 URL 手动打开 |
| `STALE_PID_RECOVERED` | **正常自愈**，不用管；清理记录后正常启动 |
| 提示端口被占用且不是我们的 UI | 按提示先处理那个进程；系统**不会**替你 kill |
| 浏览器没自动打开 | `open` 失败或 `LACAN_NO_OPEN=1` 都不影响服务，手动开 `http://127.0.0.1:3090/` |
| `verdict: NOT_HEALTHY (exit=1)` | 看 `layers (8)` 哪一层不是 READY，再看日志尾部 |
| `core=UNAVAILABLE` | 冻结核心校验没过 —— **这是真问题**，`research_disabled` 会是 `True` |
| `mcp=UNAVAILABLE` | 检索服务没连上。`research_disabled` 会是 `True`；重启一次通常能恢复 |
| `provider=DEGRADED` | **不是故障。** 没配 LLM 凭据而已，离线研究照常（见 §2） |
| 答案是 `ABSTAINED` | **不是错误。** 语料撑不住时拒答是正确的（见 §2） |
| 引文按钮是灰的 / 没有按钮 | 见 §5：缺已核实的出版信息，或这条记录是 candidate |
| 「这个候选为什么挂不到项目上」 | 见 §4：candidate 不得挂到项目，第 ③ 组会列出它们 |
| 导入的文件被 `rejected` | 见 §6：只支持 CSL JSON / Better BibTeX JSON；别的格式 fail closed |
| 导出报 `EXPORT_SOURCE_MODIFIED` | 见 §8：源在你操作期间被改过，重跑一次 |
| bundle `verify` = `MODIFIED` / `BROKEN` | 见 §8：有人动过文件，或引文断链 |
| 停不掉 | 再双击 Stop；`SKIPPED … 身份不符` 表示它**刻意**没动那个 PID |
| 日志在哪 | `_workspace/runtime/logs/ui-YYYYMMDD.log` |
| 想换端口 | `LACAN_UI_PORT=3091 _scripts/runtime/start_lacan_os.sh` |

### 已确认的事实（**不是缺陷，也不是待办**）

下面 8 条是这套系统**当前的真实状态**。它们是被**刻意设计**成这样的，
不是「还没做完」，也不是「以后会自动补上」。请不要把它们当成 bug 报。

1. **没有任何 reviewed 条目能生成完整的 Chicago / APA / MLA / BibTeX。**
   `publisher` / `publication_year` / `isbn` 一律 `null` —— 因为系统不猜。
2. **`witness.fr.seuil-pdf` 的 PassageRealization 是 0。**
   edition 层确实有页码，但这个 witness 在本地语料里没有实现出任何段落。
3. **Staferla 没有出版社 / ISBN / 页码。**
   它是工作转录（非瑟伊版定本），所以 `edition_id = null`，不挂版本。
4. **中文回译项目保持 `SOURCE_TRACE_INCOMPLETE`，且 `edition_id = null`。**
   上游源目录已消失；现存 jsonl 是唯一副本。未经 source linking 与人工审核不得升级为 canonical。
5. **Work 层只是确定性映射。**
   `work.<slug>` 只由 `canonical_name` 逐字 + 确定性 id 规则建立，**不是**语义推断或文本考据结论。
6. **CSL 输出对未拆分姓名使用 `literal`。**
   真实数据里姓名常是整串（无 family/given 拆分），所以用 `literal` 保真，
   **不做**猜测式切分。
7. **Zotero 只有文件导入 / 导出。**
   没有 API 调用，没有网络请求。
8. **当前不存在人类学术审核者。**
   验收走 AI-only 协议（`AI_MULTI_AGENT_BLIND_REVIEW_V1`）。
   这不是「审核未完成」，而是「按设计以 AI-only 协议接受」。

### 系统不声称什么

这一节抄自 `_data/releases/product_rc_v1_2.json` 的 `honesty_notes`
与 `scholarly_review_assurance`，**不是**我的判断：

1. **没有经过外部人类同行评审。**
   学术输出是语料锚定 + 自动证据检查 + 独立 AI 复核，**未**经外部人类同行评审认证。
2. **本项目当前不存在可执行的人类学术 reviewer。**
   接受模型 = `AI_MULTI_AGENT_BLIND_REVIEW` + `DETERMINISTIC_EVIDENCE_VALIDATION` + `FROZEN_MACHINE_GATES`。
3. **AI 盲审的各 lane 只共享单一 provider / 模型家族。**
   lane 之间只有角色、prompt、fresh session、题目顺序不同，**不是**不同模型。
   所以它是「独立复核」，**不是**「多模型共识」。
4. **确定性证据审计证明不了理论主张。**
   它只能证明「引用可解析 / 引文逐字命中 / 层级标注一致」。
5. **AI 判定 ≠ 人类同行评审。** 本轮已记录 reviewer false positive 13 条（含理由）。
6. **没有书目完整性。** 当前没有任何 reviewed 条目能排出完整 Chicago/APA/MLA/BibTeX。
7. **没有页定位器，除非那份 edition 真的有。**
   只有 `page_locator_kind == page` 才允许渲染成页码；其余是
   `section` / `session` / `passage_id` / `folio` / `digital_location`。
8. **Project 是 `USER_WORKSPACE` 对象，永远不是 evidence。**

**另外两条要记住的：**

- **candidate 永远不可引用。**
- **reviewed ≠ bibliographically complete。**（见 §5）

### 发布口径

```
RELEASE_CANDIDATE = RC1.2
review_assurance  = AI_ONLY        human_review = false
not_equivalent_to_human_peer_review = true
protocol          = AI_MULTI_AGENT_BLIND_REVIEW_V1
CCR-0001          = RESOLVED（Phase 4E）
```

---

## 附录 A · 引文常见问题

### 1. 为什么可用性是「带理由」的，而不是只把按钮打灰？

因为「不能用」有**很多种不同的原因**，而它们对应完全不同的处置方式：

- 缺作者 → 要去核实作者
- 缺出版社 / 年份 → 要去核实出版信息（**当前全部条目的情况**）
- 条目是 candidate → 要先去复核这条记录本身
- 缺 `passage_id` → 要先去找到对应的段落

把四种情况都显示成「灰按钮」，用户学不到任何东西，也无法知道下一步该做什么。
所以系统为每个样式给出 `status`（`READY` / `UNAVAILABLE`）**加上 `reason`**，
并且区分 `style_missing`（这个样式缺什么）与 `soft_missing`（样式不要求、但确实没有值）。

### 2. 为什么 candidate 连段落级引文都不给？

因为**段落级引文也需要一条被采信的记录才能指向**。

Internal / Provenance 引文指向的是「某个 witness 里的某一段」。
如果这条 witness 记录本身还是 `needs_review`，那指向它的引文就是在**引用一条未复核的记录** ——
那正是这套系统最不想做的事。

所以判定是两段的：

```
第一段：能力矩阵说这个样式在元数据上可行吗？
第二段：这条记录 review_status == reviewed 吗？
两者都成立 → available = true
```

界面还会额外说明，免得用户以为是 bug：

```
candidate record — not citable
```

### 3. 为什么同一条目 + 同一样式，到处都得是同一段文字？

因为**引用一旦不一致，你就没法知道自己在引什么。**

系统的做法是：UI 的 Copy Citation、Export、Obsidian 笔记、Project 里的引文
**全部走同一个 renderer**，并且每条引文带一个 `identity_hash`。

这带来一个可检验的性质：如果同一 `(item, style)` 在两处显示不同文字，
那就是**渲染一致性被破坏了** —— 是缺陷，不是「格式偏好」。

（顺带：`render()` 是唯一入口，所以不存在「UI 一套、导出另一套」的漂移空间。）

### 4. 为什么宁可显示 `UNAVAILABLE`，也不给你一个「大概对」的值？

因为**一个错的引文比没有引文危害大得多**。

没有引文时，你知道自己缺东西，会去找。
有一个看起来对的引文时，你会直接用它 —— 然后它可能带着一个错年份或错出版社进入你的稿子，
而且**你没有任何线索发现它是错的**。

所以系统在这里是刻意保守的：

```
publisher        = null
publication_year = null
isbn             = null
→ chicago / apa / mla / bibtex = UNAVAILABLE
```

`edition.seuil-pdf` 把这个决定写进字段里：`why_publisher_null`
——「仓库未记录出版社字段（§8：不得据模型知识补）」。

**注意 `UNAVAILABLE` 是终态，不是待办。** 它不会「以后自动补上」——
补上它需要有人把核实的出版信息写进 vault，那是一个**人类动作**。

### 5. 这些数字我是怎么读出来的

每条都能自己重跑。在仓库根目录执行：

**书目登记表计数**

```bash
python3 -c "import json;m=json.load(open('_data/bibliography/manifest.json'));print(m['counts'],m['freeze_class'])"
# {'candidates': 3, 'conflicts': 0, 'editions': 1, 'items': 4, 'mappings': 10, 'works': 4} CANONICAL_KNOWLEDGE
```

**reviewed / candidate 名单与 review_basis**

```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from bibliography import registry as R
for i in R.items():      print('reviewed ', i['bibliographic_id'], i['review_basis'], i['metadata_completeness'])
for i in R.candidates(): print('candidate', i['bibliographic_id'], i['review_basis'], i['metadata_completeness'])
"
```

**witness 段落数（§5 三个走走看的数字）**

```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from bibliography import registry as R
for m in R.mappings():
    if m.get('witness_id'): print(m['witness_id'], m.get('passage_count'), m.get('edition_id'))
"
# witness.fr.seuil-pdf 0 edition.seuil-pdf
# witness.fr.staferla 166527 None
# witness.zh.translation-project 82578 None
```

**能力矩阵（缺哪些字段、每个样式为什么不可用）**

```bash
python3 -c "
import sys, json; sys.path.insert(0,'.')
from bibliography import registry as R
from bibliography import render as RD
for i in R.items():
    print(i['bibliographic_id'], json.dumps(RD.capability_matrix(i), ensure_ascii=False))
"
```

**实体登记表规模与不变式（§3）**

```bash
cat _data/entities/registry_manifest.json
# passages_scanned=249105  mention_index_rows=7684
# persons_reviewed=7  cases_reviewed=5  candidates_not_promoted=0
# no_automatic_ner_promotion=true  method=DETERMINISTIC_ALIAS_MATCH
```

**导出清单与 bundle 校验（§8）**

```bash
python3 -c "
import sys, os; sys.path.insert(0,'.')
import export_system as EX
from export_system import policy as P, manifest as M
d = EX.list_exports('default'); print('total =', d['total'], '| path =', d['path'])
for n in sorted(os.listdir(P.DEFAULT_EXPORT_ROOT)):
    p = os.path.join(P.DEFAULT_EXPORT_ROOT, n)
    if os.path.isdir(p): print(n, '->', M.verify_bundle(p)['status'])
"
# total = 20 | path = _workspace/exports
# 5 个 bundle → 全部 VERIFIED
```

**Obsidian 工作区状态（§7）**

```bash
python3 -c "
import sys, json; sys.path.insert(0,'.')
from obsidian_adapter import adapter as OA
d = OA.vault_status()
print(d['active_root'], d['root_kind']); print(d['counts'])
"
# <HOME> project-workspace
# {'research': 0, 'passages': 0, 'concepts': 0, 'seminars': 0, 'projects': 1, 'sources': 0}
```

**vault 检测（确认根目录就是那个 Obsidian vault）**

```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from obsidian_adapter import vault as V
d = V.detect(); print(d['is_obsidian_vault'], len(d['canonical_partitions_present']), d['default_workspace_root'])
"
# True 17 <REPO>/_workspace/obsidian_vault
```

**发布口径（§10 的引用来源）**

```bash
cat _data/releases/product_rc_v1_2.json
```

---

最后更新：2026-09-27T17:55:43Z
