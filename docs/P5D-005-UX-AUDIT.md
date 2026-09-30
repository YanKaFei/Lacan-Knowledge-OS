# P5D-005-UX-AUDIT — Lacan Knowledge OS 日常使用体验审计

> 阶段：**P5D-005 — DAILY_USE_ONBOARDING_AND_HELP**
> 视角：**第一次打开 Lacan Knowledge OS 的研究者**（不知道内部架构、不知道 route、没读过 README）
> 方法：真实 production UI，不读源码猜结论
> 日期：2026-09-29/30 · HEAD `f70402e5b852923028283c93f81dbfb12f1911f4`
> 证据：`/tmp/p5d005/audit_before.json`、`/tmp/p5d005/audit_before2.json`（CDP 抓取的 DOM / 路由 / 溢出实测）

## 0. 审计环境

| 项 | 值 |
|---|---|
| 入口 | `http://127.0.0.1:3090/`（launcher 启动的真实实例，UI + MCP 各 1 个进程）|
| 视口 | desktop `1500×1100`、narrow `430×900`（真 Chrome，CDP）|
| 语言 | 浏览器语言 = zh-CN → 首屏实际是**中文界面**（`detectInitialLocale()` 的结果）|
| 状态 | 8 层全 READY（core/mcp/corpus/workspace/explorer/obsidian/bibliography/provider）|
| 探针 | `GET /help`、`/research`、`/explore`、`/projects`、`/bibliography`、`/persons`、`/cases`、`/zotero` 全部 **404**；只有 `/?view=...` 可用 |

**ID 说明**：本会话早些时候已完成的「真实 LLM 接口可用性」片记为 **P5D-005-L1**
（`P5D-005-LLM-UX-REPRODUCTION.md` / `_data/daily_use/defects/P5D-005_llm_interface_usability.md`）。
本文件是 **P5D-005-L2 = DAILY_USE_ONBOARDING_AND_HELP**。历史报告一律不改写。

---

## 1. 十个问题逐条回答

### Q1 首页是否告诉用户这个系统是什么？

**PARTIAL。** 首页确实有一个标题与一句副标题
（`Lacan Knowledge OS` / `Corpus-grounded Scholarly Research Workspace` = 中文「基于语料的学术研究工作区」），
但没有一句话说明：它**只依据本地语料**作答、**不凭模型知识**、**弃权是正常结果**。
更关键的是：**打开系统时看到的根本不是首页** —— 首屏是 Research 表单（`#ask-view`，
`#home-view` 是 `hidden`），新用户第一眼看到的是一个「向冻结的学术内核提问」的输入框。

### Q2 用户能否在 30 秒内知道 Research / Explore / Projects 的区别？

**FAIL。** 首页只有 5 个按钮（研究 / 探索 / 项目 / 文献 / 打开 Obsidian），
外加一句箭头链 `Explore → Research → Inspect Evidence → Add to Project → Save to Obsidian`
和一句文献说明。没有任何地方写清：
Research = 从**问题**出发；Explore = 从**材料**出发；Projects = 把一次次研究变成**长期课题**。
导航里唯一有解释性文字的是 Explore 分组的一行 note（`Browse ≠ research…`），
而 Projects / Research 没有对应解释。

### Q3 用户是否知道怎样查原文？

**PARTIAL。** 只能靠导航里那行 Explore note（"Corpus-driven browsing"）间接推断。
首页没有「寻找原文与出处」这样的任务入口，也没有从答案跳到原文的说明。

### Q4 用户是否知道怎样查看 AI 回答的 evidence？

**FAIL。** 首页无任何 mention；唯一线索是同一条箭头链里的 `Inspect Evidence` 两个词。
没有说明 Evidence Inspector 是什么、点 citation 会发生什么、`Answer → Claim → Passage → Source` 的层级。

### Q5 用户是否知道怎样把研究结果保存到 Project？

**FAIL。** 箭头链里有 `Add to Project`，但动作条上的按钮叫 **Add to Project**（英文界面）
/ 中文界面另有译名 —— 用户无法确定两者是同一个东西；也没有说明「Project 内容不是 corpus evidence」。

### Q6 用户是否知道 Bibliography 为什么有些条目不能引用？

**FAIL。** 界面在条目上直接打 `[NEEDS REVIEW · NOT CITABLE]`、`SOURCE_TRACE_INCOMPLETE`
（`bibliography.js:74`、`explorer.js:596`），但**全站没有任何一处解释这些 token 的意思**。
首页那句 `Formal bibliographic citations … are offered only when verified publication metadata exists`
方向正确，但它只说了「有元数据才给」，没说 **reviewed ≠ metadata complete**、**candidate ≠ citable**。

### Q7 用户是否知道 Obsidian 在整个系统中的角色？

**FAIL。** 首页有 `Open Obsidian` 按钮，导航也有 `Obsidian` 项，但没有任何文字说明
「证据/检索/校验/bibliography 在 Knowledge OS，个人理解/长期写作/概念网络在 Obsidian，
Obsidian 不是底层数据库」。

### Q8 用户是否知道 UI Language 和 Research Language 是两个不同概念？

**PARTIAL。** 顶栏有两个下拉（`Language` / `Research language`）与一行状态文字
（`Research language: … — sent as the question language with research requests; the interface copy is not translated.`）。
这行字是对的，但它只解释了 **Research language**；没有任何地方用对照例子说明
「界面 = 中文、研究语言 = Français」是合法的，也没有 Help 页可去。

### Q9 用户遇到 `ABSTAINED` / `SOURCE_TRACE_INCOMPLETE` / `NOT CITABLE` 时，是否知道是什么意思？

**FAIL。** `ABSTAINED` 有答案卡片上的状态标签与一段 abstention 说明（这层做得对），
但 `SOURCE_TRACE_INCOMPLETE` / `NEEDS REVIEW · NOT CITABLE` / `METADATA_INCOMPLETE` /
`UNRESOLVED` 只作为 token 出现，**没有状态词典**。

### Q10 当前 Help 页面是否真的能够指导完成上述任务？

**FAIL（BLOCKING）。** 系统里**不存在 Help 页面**：

```
GET /help                 → 404
GET /help/getting-started → 404
GET /research /explore /projects /bibliography /persons /cases /zotero → 全部 404
```

「Help」目前只是首页第三张卡片（`#home-help`，标题「How to work here / 使用方式」）里的
**三句话**。四个 Help 关键词（`HELP_PAGES`）当前为 **0**，`/help` 路由不存在，
也没有左侧目录、anchor、Previous/Next、模块 deep link、contextual help。

---

## 2. 发现清单（FINDING / SEVERITY / USER IMPACT / CURRENT PATH / RECOMMENDED PATH）

| ID | FINDING | SEVERITY | USER IMPACT | CURRENT PATH | RECOMMENDED PATH |
|---|---|---|---|---|---|
| **A1** | 首屏落在 Research 表单，`#home-view` 默认 `hidden`；新用户第一眼没有「这是什么/从哪开始」 | **BLOCKING** | 打开即懵；把「提问框」误当成全部能力 | 浏览器打开 `/` → 直接是 `#ask-view` | `/` 先渲染**任务型首页**（Hero + 你想做什么 + workflow + Quick Start），Research 作为其中一个任务入口 |
| **A2** | 不存在 Help Center（`/help*` 全部 404，Help 仅首页三句话） | **BLOCKING** | 遇到 `ABSTAINED`/`NOT CITABLE`/语言概念时无处可查 | 无 | `/help` + 13 个 Help 页（目录 / anchor / prev-next / deep link / topic nav）|
| **A3** | 路由只有 query 参数，产品级路径全部 404（`/research`、`/explore`、`/projects`、`/bibliography`…）| **HIGH** | 不能分享/收藏真实链接，不能新标签打开，Help 无法 deep-link 到模块 | `/?view=projects` | 服务端识别产品路径并把 SPA 交给前端；`?view=` 保持向后兼容 |
| **A4** | 首页第一个卡片是 **System Status**（8 层内部状态），信息架构按内部模块组织 | **HIGH** | 新用户先看到 `MCP / Core Freeze / Corpus` 这类内部词汇，学不到「我能做什么」 | Home → System Status 卡片在最上 | 首页第一屏 = Hero + 6 张任务卡；System Status 下移并折叠 |
| **A5** | 首页**没有真实链接**：`<a>` 数量 = **0**，全部是 `onclick` 按钮 | **HIGH** | 无法新标签打开、无法复制链接、右键菜单无「在新标签页打开」 | 5 个 `<button>` | 任务卡与 workflow 步骤用真 `<a href="/…">`，键盘/中键/复制均可用 |
| **A6** | `Research / Explore / Projects` 三者的区别全站无一处说明 | **HIGH** | 用户凭猜选择，容易用错模块（尤其「只想查原文却去提问」）| 无 | 新增 `/help/research-vs-explore` + 首页任务卡说明 + Explore 页 contextual help |
| **A7** | 状态词典缺失：`SOURCE_TRACE_INCOMPLETE` / `NOT CITABLE` / `NEEDS REVIEW` / `UNRESOLVED` / `DEGRADED` 只作为 token 出现 | **HIGH** | 用户把「学术限制」误读成「系统 bug」，或以为条目坏了 | 条目上的 token | `/help/statuses`：每个状态写「什么意思 / 为什么出现 / 我要做什么 / 是否错误」|
| **A8** | Evidence 路径未教学：`Answer → Claim → Passage → Session → Witness/Source` 与 Evidence Inspector 无说明 | **HIGH** | 「AI 说了什么」被当成「拉康原文证明了什么」 | 仅箭头链里的 `Inspect Evidence` | `/help/evidence`（核心文档）+ 答案/侧栏 contextual help |
| **A9** | 语言双概念只解释了一半（没有对照例子、没有 Help 页）| **MEDIUM** | 用户以为切换界面语言会改变检索语言，或反之 | 顶栏一行状态文字 | `/help/languages`：`界面 zh + 研究语言 fr` 明确合法；两控件互相独立 |
| **A10** | Obsidian 的角色无说明（只有按钮）| **MEDIUM** | 用户不知道该在哪里做笔记/写作，可能试图把 Obsidian 当数据库 | `Open Obsidian` 按钮 | `/help/obsidian`：分工说明 + 如何打开 + 「不是底层数据库」|
| **A11** | 窄视口（430px）横向溢出：`.topbar-controls` 实测宽 652px，`scrollWidth 860 > clientWidth 500` | **MEDIUM** | 手机上必须横向滚动才能碰到语言/Provider 控件 | `.topbar-controls` 单行不换行 | 窄屏改为可换行/可横向滚动容器；`broken_layout=false` 纳入 F20 |
| **A12** | 空状态只报事实、不给下一步（Projects：`No projects yet.`；Recent：`No research yet.`）| **MEDIUM** | 用户看到「没有」就停住，不知道该怎么开始 | 一行 muted 文字 | 空状态 = 说明 + 两个动作（`[创建第一个 Project]` / `[了解 Projects]`）|
| **A13** | 全站 **0** 个 module contextual help（Research/Explore/Projects/Bibliography/Persons/Cases/Zotero 都没有 `?`/Help 入口）| **HIGH** | 用户在具体模块里卡住时无法就近获得帮助，只能回首页猜 | 无 | 每个模块一个 `? Help` → 对应 `/help/<module>`（**不得**全指 `/help`）|
| **A14** | Zotero 导入埋在 Bibliography 的 `<details>` 里，且 candidate 语义无解释 | **MEDIUM** | 导入后看到 `NEEDS REVIEW · NOT CITABLE` 会以为导入失败 | Bibliography → `Import (Zotero / CSL JSON)` | `/help/zotero` + Bibliography 页内 contextual help；明确不自动 canonicalize |
| **A15** | Recent 列表产出重复/空 DOM id（`recent-item-` ×5，同一问题出现两次）| **LOW** | 锚点/自动化定位不稳；批量截图与无障碍工具会报重复 id | `home.js` 用 `it.id`（历史条目的字段不叫 id）| 用稳定的 `history file` 作为 id 后缀；同一问题多次运行按时间区分 |
| **A16** | Help 文档若凭空描述能力将无法被验证 | **BLOCKING（纪律）** | 文档变成 fiction，用户按文档操作会撞空 | 无 | `HELP_CLAIM_VERIFICATION.json`：每条功能 claim 必须 browser/API/source 三选一验证通过 |

---

## 3. 由此确定的建设范围（对应 spec 章节）

| spec | 交付 |
|---|---|
| §2–§6 | 任务型首页：Hero（两个主按钮）+ 6 张任务卡（真链接）+ 6 步 workflow（每步可点）+ Quick Start |
| §7–§8 | `/help` + 13 个 Help 页；左侧目录、anchor、Previous/Next、Back to Help、Back to module、topic navigation、responsive |
| §9 | 6 个模块 contextual help（Research / Explore / Projects / Bibliography / Persons-Cases / Zotero）|
| §10 | 教学型空状态（Projects / Bibliography / Search / History / Explorer）|
| §11 | `HELP_CLAIM_VERIFICATION.json`（0 fiction）|
| §12 | `HELP_LINK_REPORT.json` + 自动 link/anchor checker（0 broken）|
| §13–§16 | 8 个 first-time-user 任务（真实浏览器）+ findability 指标 |
| §17 | Help 走既有 `i18n.js`（不建第二套 locale）；原文/引文/书目 metadata 不翻译 |
| §18 | 真实 Chrome：desktop + narrow，完整点击链，无 console error |
| §19–§22 | 全量回归 + Gate v3（F1–F20，F20 HELP_SYSTEM_EFFECTIVE），历史 Gate v1/v2 不改 |

## 4. 明确不做（边界）

- 不改 corpus / canonical ontology / passage / retrieval / EvidencePacket / synthesis /
  bibliography canonical review state / citation integrity / Person-Case canonical data /
  Project scholarly data model / MCP scholarly protocol / provider 行为。
- 不为了让文档"成立"而**新造**学术能力；发现文档与实现不符时，**改文档或登记缺陷**。
- 不引入第二套 locale 状态；Help 语言跟随全站 locale，且原文类内容**永不翻译**。
- 不改写历史报告与历史 Gate（v1 18/18、v2 19/19 原样保留）。

---

## 5. 修后核对（同一审计视角复查）

修复完成后，用**同一批探针**在同一个真实实例上复查（细节见
`HELP_TASK_COMPLETION_REPORT.md`）：

| # | 审计问题 | 修前 | 修后（实测） |
|---|---|---|---|
| Q1 | 首屏是否说明这是什么 | 首屏是提问框（`#home-view` 隐藏）| `/` 是任务型首页：Hero + 定位句 + 两个主按钮（`hero-start-research` / `hero-first-time`）|
| Q2 | 30 秒内能否分清 Research/Explore/Projects | 只有 5 个按钮 | 6 张任务卡 + `/help/research-vs-explore`（`starts from a question` / `starts from the material` / `turns runs into a topic`）|
| Q3 | 会不会查原文 | 只能靠导航 note 推断 | 卡片 `寻找原文与出处` → `/explore`（7 个入口）；Help 有 `Explore` 页 |
| Q4 | 会不会看 evidence | 无 | `/help/evidence`（核心页）+ 答案/检查器 contextual help |
| Q5 | 会不会存进 Project | 无 | 首页卡片 + `/help/projects`；空状态给出 `了解 Projects` |
| Q6 | 懂不懂 Bibliography 规则 | 只有 token | `/help/bibliography` 明写 `reviewed ≠ complete`、`candidate ≠ citable` |
| Q7 | 懂不懂 Obsidian 的角色 | 只有一个按钮 | `/help/obsidian` 分工说明；`Open Obsidian` 现在**真的**能用（P5D-005-T2）|
| Q8 | 两个语言概念 | 顶栏一行说明 | `/help/languages`（`界面=中文 + 研究语言=Français` 合法，两者独立）|
| Q9 | 遇到状态是否知道含义 | 无词典 | `/help/statuses`（11 个状态：含义/原因/该做什么/是否错误）|
| Q10 | Help 能否指导完成任务 | **不存在**（`/help` 404）| 13 页 Help + 8/8 首用者任务通过（只靠首页与 Help）|

其它被审计到的问题：

| ID | 修前实测 | 修后实测 |
|---|---|---|
| A3 路由 | `/research` `/help` 等全部 404 | 全部 200（SPA 路由）；旧 `?view=` 深链保持可用 |
| A5 真实链接 | 首页 `<a>` = **0** | 首页 ≥ 24 个内部 `<a href>`（卡片/流程/快速开始/导航）|
| A11 窄视口 | `scrollWidth 860 > clientWidth 500` | `500 == 500`（无横向溢出）|
| A13 contextual help | 全站 0 个 | 8 个模块入口，全部指向**模块专属**帮助页（F20 逐个核对）|
| A15 Recent 重复 id | `recent-item-` ×5 | 用历史文件名做 id |
| A12 空状态 | `No projects yet.` 一行 | 教学型空状态：说明 + 两个真实动作（Projects / Explore 零结果 / History / Bibliography）|
