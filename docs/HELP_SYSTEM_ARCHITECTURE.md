# HELP_SYSTEM_ARCHITECTURE — P5D-005 帮助与引导系统

> 阶段：**P5D-005 — DAILY_USE_ONBOARDING_AND_HELP**（本轮 ID 说明见 `P5D-005-UX-AUDIT.md` §0）
> 结论：`scholarly_semantics_changed = false` / `product_runtime_changed = true`
> 冻结核心与谱系：`core_freeze --verify` PASS、`freeze_lineage --verify` PASS（`semantic=0`）

## 1. 目标与判据

把"系统能力很多但不知道怎么用"变成"打开就知道先做什么、能走到哪一步"，并且**用真实浏览器任务测试证明 Help 真的有用**。

判据不是"`/help` 返回 200"，而是：

```text
首页任务入口 = PASS      模块 deep link = PASS      contextual help = PASS
Help 内部链接 = PASS     broken links = 0           broken anchors = 0
8/8 首用者任务 = PASS    documentation fiction = 0  claim pending = 0
```

（Gate v3 · F20 `HELP_SYSTEM_EFFECTIVE`，见 `_data/daily_use/daily_use_gate_v3.json`）

## 2. 分层与数据流

```
        ┌──────────────────────────── 作者层（唯一真源）────────────────────────────┐
        │ _data/daily_use/help/help_content.json   13 页正文（en + zh + 结构 + 链接）│
        │ _data/daily_use/help/ui_keys.json        新增产品文案（首页/Help chrome）  │
        │ _data/daily_use/help/help_claims.json    功能性断言 + 机器可核的检验方式    │
        └───────────────────────────────┬───────────────────────────────────────────┘
                                        │  compile_doc() / i18n_entries()（确定性）
                    ┌───────────────────┴────────────────────┐
                    ▼                                        ▼
   workspace_ui/server/help_view.py              _scripts/_tools/build_help.py
   （结构 + i18n key，**不含正文**）              （校验 / 生成词典 / 链接报告 / claims）
                    │                                        │
                    │ /api/help/content                      ▼
                    ▼                          _data/daily_use/i18n/manual_keys.json
   workspace_ui/static/src/help.js             （help.* 337 条 + ui_keys 63 条）
   （用既有 i18n.js 的 t() 渲染正文）                        │
                    │                                        ▼
                    │                        workspace_ui/static/src/i18n_messages.js
                    └───────────────► 用户看到的 Help（en / zh 即时切换）◄─────────┘
```

关键设计（为什么这样切）：

| 决定 | 理由 |
|---|---|
| 正文放 JSON（en+zh），**不**放 JS | 单一真源；i18n 词典由它生成，不可能漂移 |
| API 只回**结构 + key**，不回正文 | 正文必须由既有 `i18n.js` 渲染（§17：不建第二套 locale）；也顺手缩小了响应体 |
| 正文里引控件写 `{{ui:KEY}}`，渲染时取真实标签 | Help **不可能**说出一个产品里不存在的按钮名（不存在 → link/claim 检查当场失败）|
| 原文块 `kind="source"` 只有一份文本、不进词典 | Layer B：示例问题/引文不随 UI 语言变化（§17）|
| 每个 functional claim 都带机器可核的检验方式 | §11 禁止 documentation fiction；`element` 类由真实浏览器套件逐条验证 |

## 3. 路由

服务端（`workspace_ui/server/httpserver.py`）只把**产品路由**交给 SPA，**不是**通配回退：

```
SPA：/  /home  /research  /explore  /projects  /bibliography  /persons  /cases
     /zotero  /help  /help/<13 个主题>
其它：/api/*（含未知 → 404 JSON）、/static/*、其它路径 → 404
```

前端（`workspace_ui/static/src/router.js`）两层同时成立：

1. **路径路由**（新）：`pathState()` 把路径解释成视图；`pathFor()` 把视图写回规范路径；
   `goTo(href)` 处理页面里真实 `<a href="/…">` 的点击（`wireLinks()` 拦截左键，
   中键/新标签/`target`/`download` 保持浏览器原生行为）。
2. **查询参数状态**（旧，完全保留）：`?view=…` / `?q=…` / `?inspect=…` / `?seminar=…` 等；
   `state()` = 路径默认值 ⊕ 查询参数（查询参数优先）。

因此：老深链、老测试、老书签全部照旧；新路由可以分享、收藏、在新标签打开。

## 4. 页面与模块映射

| 模块（视图） | contextual help | 模块主链接 |
|---|---|---|
| research | `/help/research` | `/research` |
| explore / concepts / passages / seminars / terminology | `/help/explore` | `/explore` |
| projects | `/help/projects` | `/projects` |
| bibliography | `/help/bibliography` | `/bibliography` |
| entities（persons / cases） | `/help/persons-cases` | `/persons` `/cases` |
| zotero（bibliography 导入区） | `/help/zotero` | `/zotero` |
| obsidian | `/help/obsidian` | `/help/obsidian` |
| home / saved / exports / history | `/help` | `/` |

映射的**唯一真源**是 `help_view.MODULES`，经 `/api/help/content` 下发给前端
（`app.js::updateContextualHelp()` 只用服务端的表，不在前端另抄一份）。
顶栏右端的 `? Help`（`#contextual-help`）随当前模块更新 href —— **不会**全指 `/help`。

## 5. Help Center 的界面

```
┌───────────────┬──────────────────────────────────────────────┐
│ Topics        │  5-minute quick start           ← h1          │
│ [搜索框]      │  一句话摘要                                   │
│ Start here    │  ## What this system is        ← anchor       │
│  5-minute…    │  正文（引用控件渲染成真实标签）               │
│  Research vs… │  <pre> 原文块（不翻译）                       │
│ Modules       │  → 真链接行                                   │
│  Research     │                                              │
│  Evidence …   │  [← 上一页] [Back to Help] [下一页 →]         │
│ Reference     │  Back to the module                           │
│ Troubleshoot. │                                               │
└───────────────┴──────────────────────────────────────────────┘
```

- 左侧目录按 `Start here / Modules / Reference / Troubleshooting` 分组，当前页 `aria-current="page"`；
- 目录上方搜索框按**标题+摘要**过滤（无匹配时给出可读空状态，不静默留白）；
- 每页有 `Previous / Next / Back to Help / Back to the module`；
- 窄视口（≤900px）单列、sidebar 变横向条；实测 430px **无横向溢出**；
- 全部 DOM 节点构建（无 `innerHTML`），键盘可达（Tab + Enter 实测可导航）。

## 6. 首页信息架构

```
Hero：Lacan Knowledge OS · 定位句 · [开始一次研究] [第一次使用？]
你想做什么？        6 张任务卡（全部是真实 <a href>）
一次完整研究如何进行 6 步（每步可点）＋ 证据优先提示
第一次使用？5 分钟    6 步清单 ＋ [查看完整教程]
[Open Obsidian] [? Help]
System Status（折叠，8 层）+ Recent
```

原 `System Status 在最上` 的问题已消除：内部状态仍然可见（Gate F6 契约的 id 与 8 层都在），
但**排在任务之后**且默认折叠。

## 7. 可核性（不是文档说了算）

| 产物 | 内容 | 谁在守 |
|---|---|---|
| `HELP_LINK_REPORT.json` | 内部链接 / 跨页 anchor / 16 个模块 deep link 的可达性 | `test_p5d005_help`、F20 |
| `HELP_CLAIM_VERIFICATION.json` | 42 条 functional claim 的 status（browser/API/source） | `test_p5d005_help`、F20 |
| `_workspace/ui_qa/p5d005_help_claim_browser.json` | `element` 类 claim 在真实 DOM 上的逐条结果 | 浏览器套件写入 |
| `_workspace/ui_qa/p5d005_help_browser.json` | 8 个首用者任务 + findability + 浏览器 QA | 浏览器套件写入 |
| `_workspace/ui_qa/p5d005_help_*`（gate run 内） | F20 的逐步证据 | `daily_use_acceptance.py --run --gate v3` |

**反虚构机制**：Help 正文里的每个 `{{ui:KEY}}` 必须存在于 i18n 词典；
每条 functional claim 必须有一条机器检验通过；链接/锚点必须可解析。
任何一项不成立 → `build_help.py` 退出码非 0 → F20 FAIL。

## 8. 边界（本轮明确不改）

corpus / canonical ontology / passage 内容 / retrieval 语义 / EvidencePacket 语义 /
synthesis 语义 / bibliography canonical review state / 引用完整性规则 /
Person & Case canonical 数据 / Project 学术数据模型 / MCP scholarly 协议 / provider 行为 ——
**全部未改**（`core_freeze --verify` 39 组件哈希一致；`freeze_lineage` `semantic=0`）。

本轮唯一的产品行为修复是 **P5D-005-T2**：`/api/obsidian/status` 从未返回
`vault_uri/open_uri`，导致首页 `Open Obsidian` 永远走"未配置 URI"分支（还会打印 `unknown`）。
现在补上 `obsidian://open?vault=<active_root 名>`（复用既有适配器的命名规则，
不做 shell 调用、不写任何内容），并把降级文案改成产品真实路径。
