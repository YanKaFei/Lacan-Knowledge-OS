<div align="center">

# Lacan Knowledge OS

**面向拉康精神分析的语料驱动研究环境。**
证据优先，解释其次，绝不编造。

[English](README.md) · [**中文**](README.zh.md) · [日本語](README.ja.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Italiano](README.it.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-6b4c2f?style=flat-square)](LICENSE)
[![Core](https://img.shields.io/badge/学术内核-冻结%20%C2%B7%2039%20个组件-43403b?style=flat-square)](docs/ARCHITECTURE.md)
[![Tests](https://img.shields.io/badge/回归-146%20套件%20%C2%B7%200%20失败-3f6b4a?style=flat-square)](docs/SCHOLARLY_REGRESSION_SPEC_V1.md)
[![MCP](https://img.shields.io/badge/MCP-10%20个工具%20%C2%B7%202025--11--25-6b4c2f?style=flat-square)](docs/MCP_TOOL_CONTRACTS.md)
[![Corpus](https://img.shields.io/badge/语料库-配套仓库%20%C2%B7%20仅供研究-8a6d1f?style=flat-square)](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus)

</div>

---

> ### 这个系统只围绕一条规则
>
> *任何断言都必须能落回一个段号。*
>
> 语料撑不住的问题，系统会**弃权** —— 它不会用模型知识作答。
> **弃权是结果，不是错误。**

---

> ## ⚠️ 版权与使用范围 —— 装语料之前请先读这一段
>
> **引擎开源，语料不是。** 两件东西，两套规则：
>
> | | 许可 / 状态 |
> |---|---|
> | **引擎源码**（本仓库） | Apache-2.0 —— 可自由使用、修改、再分发、在其上做商业产品 |
> | **参考语料库**（[配套私有仓库](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus)） | **第三方受版权保护的文本。** 公开可读，但**仅供研究与学习**；「公开可见」不等于「授权」—— **未**授权商用、再分发或对外提供服务。 |
> | **公有领域 demo 语料**（[`corpus-demo-v1`](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus/releases/tag/corpus-demo-v1) · [`demo-corpus/`](demo-corpus)） | 公有领域（Falret 1890 · Binet 1892 · Janet 1909）—— 可自由再分发 |
>
> **说白一点。** 语料库里是：拉康研讨班的**法语工作转录**、**瑟伊版印刷本**（S1–S5）的文本抽取、
> 以及一个**社区中译项目**。这些权利**都不属于本项目**。它被公开出来，是为了让研究者能拿到语料；而**「公开可得」不等于「给你授权」** —— 它不允许商用、
> 不允许再分发、不允许镜像、不允许重新打包、不允许对外提供服务、不允许当作对外发布模型的训练数据。
>
> **你的使用是否合法，最终由你自己判断** —— 本项目无法替你回答，也不构成法律意见。
> 完整分析见 [`RIGHTS.md`](RIGHTS.md)（含中文要点）。
>
> **如果要做能公开、能分享、能商用的东西，就用引擎 + 你有权使用的语料**：公有领域 demo 语料、
> 你自己的文本、或已获授权的版本 —— 这条路全程支持，见 [`CORPUS.md`](CORPUS.md) 与
> [`docs/DEMO_CORPUS.md`](docs/DEMO_CORPUS.md)。

---

## 这是什么

**Lacan Knowledge OS** 把研讨班与文集文本变成**可引用的证据库**，并在你的问题与任何答案之间
放了一个**冻结的学术内核**。

<img src="assets/diagrams/architecture.svg" alt="架构：Agent 通过 MCP 进入；产品层之下是冻结的 39 组件学术内核；语料由你另行提供，不属于开源引擎。" width="100%">

| | 能力 | 它给你什么 |
|---|---|---|
| 🔎 | **Research** | 提问 → 内核检索段落、构建证据契约，**然后**才生成答案；每条 claim 都必须通过引用与蕴含校验 |
| 📖 | **Explore** | 直接读语料：段落、会话、研讨班、概念、术语 —— 不经过任何模型 |
| 🔬 | **Evidence Inspector** | `答案 → claim → 段落 → 会话 → 研讨班 → 见证本/来源`，并给出被引用的**那一句**与上下文窗口 |
| 🗂️ | **Research Projects** | 把一次次运行变成长期课题（问题、假设、段落、人物、个案、书目）|
| 📚 | **文献与引用** | 复核状态、元数据完整度、逐样式引用可用性 —— **以及不可用的原因** |
| ✍️ | **Obsidian 桥** | 证据与校验留在这里；你的理解、笔记与写作留在你自己的 vault 里 |

### 你可以随时审计的那条链

<img src="assets/diagrams/evidence-chain.svg" alt="证据链：答案 → claim → 段落 → 会话 → 研讨班/文档 → 见证本/来源，以及展示引用句、上下文与来源链的 Evidence Inspector。" width="100%">

## 它拒绝做什么

这些"拒绝"就是设计本身，不是缺陷：

| 拒绝 | 原因 |
|---|---|
| **不凭模型知识作答** | 合成只允许使用检索到的证据；契约不足即输出 `ABSTAINED`。 |
| **不静默修补来源** | `SOURCE_TRACE_INCOMPLETE` 保持可见；藏起来等于误述来源。 |
| **不编造书目数据** | 出版社、年份、ISBN、页码从不猜；给不出的样式会写明原因。 |
| **不自动提升为 canonical** | 导入的或 AI 产出的材料一律以 **candidate** 进入，直到有人类提升它。 |
| **不留未声明的语义变化** | 39 个学术组件哈希钉住；未声明改动会让冻结校验失败，启动器**拒绝启动**。 |

---

## 开始使用

**你是 AI agent 吗？** 先跑这一条，按它打印的内容行事 —— 它决定研究能不能跑：

```sh
python3 tools/ensure_corpus.py --status      # 退出码 0 = 语料就绪 · 3 = 必须提醒用户
python3 tools/ensure_corpus.py --json        # 结构化状态，便于 agent 读取
```

### 1 · 克隆引擎

```sh
git clone https://github.com/YanKaFei/Lacan-Knowledge-OS.git
cd Lacan-Knowledge-OS
python3 -m workspace_ui.server.cli --port 3090
# → http://127.0.0.1:3090/help    13 页帮助中心（没有语料也完全可用）
```

### 2 · 给它一份语料 —— 三条路任选

| 路径 | 你能得到 | 怎么做 |
|---|---|---|
| **A. 参考语料库**（公开下载，仅供研究）| 完整拉康研讨班语料：1,979 个文件 · 249,105 段落 · 索引即装即用 | 配套仓库 [`YanKaFei/Lacan-Knowledge-OS-corpus`](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus) → `python3 tools/ensure_corpus.py --install --pack corpus-pack-v1.tar.gz --manifest corpus-pack-v1.manifest.json` |
| **B. 公有领域 demo** | 19 世纪法语临床文献（Falret · Binet · Janet）—— 可自由再分发 | `python3 tools/build_demo_corpus.py .` |
| **C. 你自己的文本** | 你有权使用的任何文本，用引擎自带的构建器接进来 | [`CORPUS.md`](CORPUS.md) · `python3 _scripts/inventory_corpus.py --help` |

**路径 A 展开说明。** 配套仓库提供的是**语料包**：一个带哈希清单的归档，安装时
`tools/fetch-corpus.py` 会**逐文件校验**，缺一个或改一个字节都拒绝安装。

```sh
curl -sLO https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus/releases/download/corpus-v1/corpus-pack-v1.tar.gz
curl -sLO https://raw.githubusercontent.com/YanKaFei/Lacan-Knowledge-OS-corpus/main/corpus-pack-v1.manifest.json
python3 tools/fetch-corpus.py --pack corpus-pack-v1.tar.gz \
    --manifest corpus-pack-v1.manifest.json --into .
python3 _scripts/_tools/core_freeze.py --verify      # → SCHOLARLY_CORE_READY
python3 -m workspace_ui.server.cli --port 3090       # 现在研究能真正回答了
```

路径 A 的访问权是**按人授予**的，而且**仅供研究使用**（见 [`RIGHTS.md`](RIGHTS.md)）。
拿不到访问权也没关系：路径 B / C 今天就能让你有一个能跑的系统。
语料打包与转交（不公开语料地把语料交给同事）见 [`docs/CORPUS_PACK.md`](docs/CORPUS_PACK.md)。

### 3 · 校验契约（这才是这个项目的重点）

```sh
python3 _scripts/_tools/core_freeze.py --verify      # 39 个学术组件
python3 _scripts/_tools/freeze_lineage.py --verify   # 七个阶段零语义变化
python3 _scripts/_tools/build_i18n.py --check        # 界面文案 ↔ 词典 ↔ 调用点
python3 _scripts/_tools/build_help.py --check        # Help 链接、锚点、0 虚构
bash _scripts/run_all_tests.sh                       # 146 套件 · 78 校验器
```

**环境要求**：Python 3.9+（核心路径只用标准库）+ 现代浏览器。**没有打包器、没有构建步骤** ——
`index.html` 直接以 ES 模块加载。向量检索与真实大模型是可选扩展
（[`docs/EMBEDDING_PROVIDER.md`](docs/EMBEDDING_PROVIDER.md)）。

---

## 怎么用

<img src="assets/diagrams/workflow.svg" alt="一次完整研究：提问 → 查看证据 → 深入原文 → 保存材料 → 整理来源 → 形成自己的知识；弃权是一等结果。" width="100%">

1. **提问** —— 一次一个问题。
2. **读状态** —— `VALIDATED`、`VALIDATED_WITH_QUALIFICATIONS`、`PARTIALLY_SUPPORTED`、
   `VALIDATION_FAILED`、`INSUFFICIENT_EVIDENCE`、`ABSTAINED`。请按字面读。
3. **验证** —— 点开引文 chip：Evidence Inspector 给出被引用的那一句、上下文窗口与来源链。
   *答案是内核的结论，Inspector 才是语料真正说的话。*
4. **深入** —— 在 Explore 里打开同一个段落，把上下文读完。
5. **留下** —— `Add to Project`，或 `Save to Obsidian`。

### 界面构成

| 位置 | 内容 |
|---|---|
| **首页** | 任务导向：**你想做什么？** —— 6 张任务卡、6 步研究流程（配一次任务全程的示意图）、5 分钟快速开始；每个入口都是真链接 |
| **Research** | 提问框、Mode / Provider / Research language；答案头部带**实测溯源**（provider · 模型 · 墙钟 · 是否缓存 · 发送次数）|
| **Explore** | 段落、会话、研讨班、概念、术语、人物、个案 —— 只读 |
| **Evidence Inspector** | 右侧面板：原文段落、引用句、上下文调节、来源链、译文 |
| **帮助中心** | `/help` —— 13 个主题、左侧目录、锚点、上一页/下一页、主题搜索、语言即时切换，另有三张**内联 SVG 示意图**（系统分层 · 证据链 · 一次研究任务的全程），图内文字随界面语言即时切换 |
| **语言** | 界面语言（EN/中文）与**研究语言**是两个彼此独立的设置 |

帮助里出现的每个控件名都从真实界面渲染；每条功能性断言都有机器核验：
**45/45 通过 · 0 文档虚构 · 0 断链**。

---

## 在 DSH / 任意 MCP 客户端里使用

这个仓库**本身**就是一个 [DeepSeek Harness](https://github.com/deepseek-ai) 插件目标：
自带 MCP server、可直接粘贴的 row、可安装的 bundle 与幂等的安装脚本。

```sh
dsh plugin --profile web add github:YanKaFei/Lacan-Knowledge-OS
python3 tools/install-dsh-row.py --profile web     # 把 server 路径绑到你的 clone
python3 _scripts/_tools/lacan-kb-mcp               # 或单独运行 MCP server
```

工具名形如 `mcp__lacan-kb__search_passages`、`…get_passage`、`…get_context`、
`…resolve_entity`、`…list_concepts`、`…search_terminology`、`…compare_concepts`、
`…find_relation`、`…list_seminars`、`…get_sources` —— **10 个工具**，协议 `2025-11-25`。
已用 DSH 自己的 MCP SDK 证明（`_data/mcp/DSH_CLIENT_PROOF.json`，**14/14 项**）。
详见 [`docs/DSH_PLUGIN.md`](docs/DSH_PLUGIN.md)。

---

## 优势与劣势

<table>
<tr><th width="50%">✅ 优势</th><th width="50%">⚠️ 劣势与限制</th></tr>
<tr valign="top"><td>

**可核验优先于流畅。** 每条 claim 都绑定 passage id，整条链可以手工审计。

**诚实的失败。** 弃权、`INSUFFICIENT_EVIDENCE`、显式"不可用"都是一等输出，没有编造的填充。

**契约是可执行的。** 39 组件冻结与七段谱系由代码检查，而不是文件里的承诺。

**离线优先。** `Offline / Mock` 不需要凭据、不联网，且是确定性的。

**一份契约，多个客户端。** 同一个 MCP 表面服务网页界面、DSH 与任何带 MCP 的编辑器。

**可审计的历史。** 每次运行都是不可变快照；重新研究同一问题会新增一条，不覆盖旧的。

**语料是可分离的。** 引擎公开（Apache-2.0），语料是第三方材料、有自己的边界，或干脆自备 ——
两者永不混在同一个仓库里。

</td><td>

**你需要一份有权使用的语料。** 开箱只能看到界面、帮助中心与契约；装好语料之后才会真正回答。
参考语料包可公开下载，但属于**仅供研究**的材料。

**参考语料是研究材料，不是产品资产。** 不可商用、不可再分发 —— 见 [`RIGHTS.md`](RIGHTS.md)。

**范围是有主见的。** 它只回答**关于语料**的问题；出版史、在场者、日期这类问题会弃权，
因为语料不携带那类元数据。

**没有质量分数。** 全系统没有"置信度百分比"；解读质量始终是你的判断。

**对笔记本级工作流偏重。** 参考语料连派生索引约 2.5 GB。

**向量检索是可选的。** 没装 embedding 依赖时退回词法匹配（界面会显示当前用的是哪一种）。

**真实 LLM 合成是一次阻塞调用。** 长请求 45–60 秒；界面显示真实耗时，"停止等待"不取消后端作业。

**产品层演进快，学术层冻结。** 便利功能经常变；改**语义**必须走正式的 Core Change Request。

**预设你熟悉这个领域。** 它不会教你拉康。

</td></tr>
</table>

---

## 文档地图

| 文档 | 内容 |
|---|---|
| [`RIGHTS.md`](RIGHTS.md) | **权利与可用范围全文** —— 引擎 vs 语料、访问权给了什么/没给什么（含中文要点）|
| [`NOTICE`](NOTICE) | 同样的边界，以分发者需要的格式 |
| [`AGENTS.md`](AGENTS.md) | AI 在本仓库必须遵守的规则 —— 第一条就是查语料 |
| [`corpus.json`](corpus.json) | 机器可读的语料引用：在哪、怎么装、缺了怎么办 |
| [`CORPUS.md`](CORPUS.md) | 自备语料：构建器期望什么 |
| [`docs/DEMO_CORPUS.md`](docs/DEMO_CORPUS.md) | 公有领域 demo 语料及其还差的本体层 |
| [`docs/CORPUS_PACK.md`](docs/CORPUS_PACK.md) | 打包并转交语料，而不公开发布 |
| [`docs/PUBLIC_EDITION.md`](docs/PUBLIC_EDITION.md) | 本公开仓库是怎么切出来并做反向验证的 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/MCP_ARCHITECTURE.md`](docs/MCP_ARCHITECTURE.md) | 分层与 MCP 表面 |
| [`docs/DAILY_USE_GUIDE.md`](docs/DAILY_USE_GUIDE.md) · [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | 日常操作 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md) · [`CHANGELOG.md`](CHANGELOG.md) | 如何参与、凭据纪律、变更历史 |

## 状态

- **学术内核**：已冻结 v1 —— `SCHOLARLY_CORE_READY`，39 个哈希钉住组件，语义漂移 **0**。
- **产品层**：日常可用；最近一次验收 **20/20 阻断项通过**、**146 套回归 / 78 校验器 / 0 失败 / 0 跳过**。
- **分发方式**：引擎公开（Apache-2.0）· 参考语料公开、**仅供研究** · 公有领域 demo 语料进行中。
- **路线图**：[`docs/ROADMAP.md`](docs/ROADMAP.md)。

<div align="center">

代码：[Apache-2.0](LICENSE) · 源文本：**不再分发，未授权商用**（[`RIGHTS.md`](RIGHTS.md)）

*如果这个系统帮你省下了一周的引文核对，它就完成了它的工作。*

</div>
