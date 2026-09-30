# HELP_TASK_COMPLETION_REPORT — P5D-005 首用者任务测试

> 判据（§13）：**不用**「`/help` 返回 200」当"帮助有效"，而是**真实浏览器**里
> 让一个"不知道内部架构、不知道 route"的用户，**只靠首页与 Help** 完成 8 个任务。
> 测试纪律：所有目标 URL 都是测试**从当前页面真实可见的链接里发现**的（不硬编码 route），
> 然后**真实点击**；只读取看得见的元素（`offsetParent !== null`）。
>
> 复现：`python3 -m unittest _scripts._tests.test_p5d005_help_browser`
> 证据：`_workspace/ui_qa/p5d005_help_browser.json`、
>       `_workspace/ui_qa/p5d005_help_claim_browser.json`

## 1. 结论

```text
FIRST_TIME_USER_TASKS = 8/8 PASS
```

| 任务 | 用户目标 | 到达路径（**发现式**，非硬编码） | 结果 |
|---|---|---|---|
| TASK 1 | 问 "Seminar XI 中 gaze 和 eye 有什么区别？" | 首页 hero `开始一次研究` **或** 任务卡 `问一个拉康问题` → `/research`；`? Help` → `/help/research` 解释怎么问 | **PASS** |
| TASK 2 | 想知道 AI 的依据原文 | 首页 `Help` → 目录里发现 `Evidence and provenance` → 照它说的点引文 chip → **真的**跑了一次 mock 研究（3 个 citation chip）→ 打开 Evidence Inspector（`Original passage` / `passage_id` 可见） | **PASS** |
| TASK 3 | 不想问 AI，只想搜原文 | 首页卡片 `寻找原文与出处` → `/explore`（7 个入口）；`Research vs Explore` 页明确 `Research 从问题 / Explore 从材料 / Projects 长期课题` | **PASS** |
| TASK 4 | 要长期研究 objet a | 首页 `第一次使用？` → `/help/getting-started`（覆盖 Research→证据→passage→Project）→ 页面里的 `/projects` 链接 → 项目视图 | **PASS** |
| TASK 5 | 为什么 reviewed 还不能出 Chicago 引用 | Help 目录 → `Bibliography and citations` → 页面明写 `Reviewed does NOT mean bibliographically complete` + `candidate` 不可引用 + `BIBLIOGRAPHIC_METADATA_INCOMPLETE` → 链接到 `/bibliography` | **PASS** |
| TASK 6 | 导入 Zotero 后为什么还是 candidate | Help 目录 → `Zotero import` → 页面只声称 `CSL JSON` / `Better BibTeX JSON`，并写明 `always candidates` / `no automatic canonicalization` → 链接到 `/zotero`（真实落到导入面板） | **PASS** |
| TASK 7 | 中文材料为什么显示 SOURCE_TRACE_INCOMPLETE | 用 Help **搜索框**搜该 token → 打开 `Status reference` → 页面把它定义为**学术限制**（`scholarly limitation`），并说明文本仍可用；断言里明确**禁止**把它写成 bug | **PASS** |
| TASK 8 | 界面中文、但只想搜法文 | Help 目录 → `Interface language vs Research language` → 页面给出 `界面=中文 + Research language=Français` 合法 + 两者独立；产品侧核对：切换界面语言后 `#language-select` **不变**、`<html lang>` 同步为 `zh-CN` | **PASS** |

## 2. §16 Findability 指标（真实点击数）

| 目标 | 起点 | 点击数 | 目标要求 | 结果 |
|---|---|---|---|---|
| Research | 首页 | **1** | ≤ 2 | PASS |
| Explore | 首页 | **1** | ≤ 2 | PASS |
| Projects | 首页 | **1** | ≤ 2 | PASS |
| Bibliography | 首页 | **1** | ≤ 2 | PASS |
| Getting Started | 首页 | **1** | ≤ 1 | PASS |
| 模块 contextual help | 模块内 | **1** | ≤ 1 | PASS |

（每次都是真实点击，路径记录在证据文件的 `findability` 字段。）

## 3. §18 浏览器 QA

| 检查 | 结果 |
|---|---|
| desktop 1500×1100 渲染首页 / Help / 各模块 | PASS |
| narrow 430×900（**修复前** `scrollWidth 860 > clientWidth 500`）| PASS：现在 `sw == cw == 500` |
| no console error（每次状态读取都断言 `errors + uncaught == []`）| PASS |
| back navigation（`history.back()` 回到**上一个**页面）| PASS |
| keyboard（聚焦侧栏链接 + Enter 真触发导航）| PASS |
| Help sidebar 可用 / 当前主题可见（`aria-current=page`）| PASS |
| anchor 存在（状态页等页面 > 5 个 `[id]`）| PASS |
| language switching（Help 正文即时切换、不刷新；原文块不变）| PASS |

## 4. §11 Documentation fiction = 0

`help_claims.json` 里的 42 条 functional claim 全部有机器可核的检验方式：

| 类型 | 条数 | 谁核验 |
|---|---|---|
| `ui_key`（引用的控件名必须存在于 i18n 词典）| 6 | `build_help.py`（静态）|
| `element`（真实 DOM 上必须存在）| 26 | 浏览器套件逐条执行 JS 断言 |
| `api`（真实接口/字段必须存在）| 4 | `build_help.py --url`（真实实例）|
| `source`（产品源码里必须有对应实现）| 2 | `build_help.py`（静态）|
| `pages_all` / `links_all` / `ui_refs_all` / `styles_subset` | 4 | `build_help.py` + 链接报告 |

```text
DOCUMENTATION_FICTION = 0
CLAIM_PENDING        = 0        （在 F20 的核验环境里：真实实例 + 真实浏览器）
CLAIM_VERIFIED       = 42 / 42
BROKEN_INTERNAL_LINKS = 0
BROKEN_ANCHORS        = 0
MODULE_DEEP_LINKS     = 16（全部指向真实页）
HELP_PAGES            = 13
```

## 5. 这一轮暴露并修掉的真实缺陷

| ID | 缺陷 | 影响 | 修法 |
|---|---|---|---|
| **P5D-005-T1** | 帮助/首页还没接上时的既有风险：动态 i18n key 会被构建器判成死条目 | 界面漏出 `projects.no-projects-yet` 这种 key 文本（被 4D.5 浏览器烟测当场抓住）| `teachEmpty()` 改为接收**已翻译文本**，调用点写 `t('…')` 字面量；构建器随之能看到，`--check` 也能守住 |
| **P5D-005-T2** | `/api/obsidian/status` 从不返回 `vault_uri/open_uri`，首页 `Open Obsidian` 永远走"未配置 URI"并打印 `unknown` | 按钮看起来是坏的 | 状态接口补 `vault_uri/open_uri`（`obsidian://open?vault=<active_root 名>`，复用既有适配器命名规则，不做 shell 调用）；降级文案改为产品真实路径 |
| **P5D-005-T3** | 路由把它自己的子视图参数吃掉：`navigate({view:'concepts'})` 写出的 URL 变成 `/explore?...`（丢掉 `?view=concepts`），回来时渲染成 Explore 首页 | 概念检索提交后**没有结果**（4D.4 交互烟测 + 5A 键盘 K3 双双抓出）| 只有"路径已表达"的视图才吞掉 `?view=`；`concepts/passages/saved/…` 一律保留 `?view=` |

三个都是**先被既有回归抓住**、再修的（而不是事后补文档）——这也说明这套回归仍然有效。

## 6. 与 Gate 的关系

```text
F19_LANGUAGE_SWITCH_FUNCTIONAL = PASS（本次 run 内重跑；历史条目未改）
F20_HELP_SYSTEM_EFFECTIVE      = PASS（13/13 子条件 true，infra_retry_used=false）
DAILY_USE_GATE_V3              = 20/20 PASS（F1–F20，全 blocking）

ACCEPTANCE_RUN = daily_use_bibliography_acceptance_20260929T193259Z_7433aed0
  verdict=COMPLETE  failed=[]  total_secs=3257.11
  gate: final-daily-use-gate-v3 · items_n=20 · hash=1017ae26bbe92022…
  F16: suites=146 / checks=78 / failed=[] / skipped=[] / quick_mode=false / secs=3057.63
  head_before == head_after == f70402e5b852923028283c93f81dbfb12f1911f4
```

F20 的 13 个子条件与本报告的 8 个任务直接对应：
`HOMEPAGE_TASK_ENTRYPOINTS` / `MODULE_DEEP_LINKS` / `CONTEXTUAL_HELP` /
`HELP_INTERNAL_LINKS` / `BROKEN_LINKS_0` / `BROKEN_ANCHORS_0` /
`FIRST_TIME_TASKS_8_8` / `DOCUMENTATION_FICTION_0` / `CLAIM_PENDING_0` /
`CLAIM_VERIFIED_ALL` / `HELP_PAGES_13` / `I18N_OK` / `ELEMENT_CLAIMS_BROWSER`。
