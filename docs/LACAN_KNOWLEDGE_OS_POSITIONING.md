# Lacan-Knowledge-OS 定位说明（逐句核实版）

> 用途：把你那段「学术研究操作系统」的表述变成**可以对外说、且经得起核查**的版本。
> 核查方式：每条都在本机运行中的系统上实测/查库完成（2026-09-29），证据随条列出。
> 结论：**大方向完全成立**；有 **1 处宣称了不存在的功能**（写作初稿），另有若干处需要**加限定**。

---

## A. 建议采用的表述（修正版，可直接使用）

> 一个面向拉康派精神分析研究的**研究工作流系统**。它不是单纯的资料库，也不是只会聊天的 AI，而是把原始语料、检索、证据链、研究项目、人物/个案、书目、Obsidian 笔记和大模型 synthesis 组织成一套**可审计**的研究工作流。
>
> 它的核心价值不是"替你解释拉康"，而是：让任何一个关于拉康的问题，都尽可能回到**具体文本、具体出处、具体证据**，再进行研究和写作。

**一、它由 6 层组成**

1. **语料层**：拉康研讨班文本，当前 **249,105** 个 passage。来源是两个 witness：`witness.fr.staferla`（法文工作转录，166,527 段）与 `witness.zh.translation-project`（社区中译，82,578 段）。另有 `witness.fr.seuil-pdf`（瑟伊版 PDF 抽取，带页码定位）**只作为元数据记录存在，未产出任何 passage（0 段）**。仓库另有 144 份源文档（约 1.2 GB），其中只有研讨班语料被切分为 passage。
2. **检索层**：lexical / exact / entity / metadata 多路检索（seminar、session、language、source_layer、date_range、concept、formalism 等过滤）；向量检索是**辅助**通道，可用性由 `dense_available` 如实上报。
3. **学术证据层**：每条回答上的引文都能沿 `回答 → claim → passage → session → seminar/document → witness/corpus_source` 回溯；`trace_source` 另给 edition / source_layer / trace_status，并且**缺层如实标注**（`Not linked`、`SOURCE_TRACE_INCOMPLETE`），不补不猜。
4. **研究工作台（Projects）**：长期研究主题、research question、hypothesis、evidence、人物、个案、参考文献、未解问题、个人笔记、研究 run 快照与比对、export manifest。
5. **知识管理层（Obsidian）**：笔记写在**受管工作区 vault**（默认 `_workspace/obsidian_vault`，可用 `OBSIDIAN_VAULT_PATH` 指向你自己的库）；概念/研讨班/段落/研究/项目/书目笔记都是**派生笔记**（`_System/...`，不含 `id:`/`type:`），其中 `## My Notes` 用户区**逐字节保护**、二次同步不覆盖。
6. **AI 研究层**：大模型只在**检索出来的证据**上做 synthesis，并且会在证据不足时**弃权**（`ABSTAINED`），不用模型知识硬编；真实 provider 必须显式选择并配置凭据（默认离线/mock），provider 不可用时本地功能不受影响。

**二、它现在能做什么**

1. **直接问理论问题**：先检索语料、再形成回答；可打开 Evidence Inspector 看它引用了哪些 passage。回答状态按字面读：`VALIDATED` / `VALIDATED_WITH_QUALIFICATIONS` / `PARTIALLY_SUPPORTED` / `VALIDATION_FAILED` / `INSUFFICIENT_EVIDENCE` / `ABSTAINED`。
2. **查原文而非只看总结**：在 Explore 里追一段话出现在哪些文本、前后文、seminar、session、法文/中文材料、witness 来源与 L1/L2 层。
3. **做概念研究**：围绕一个概念查相关 passage、seminar、术语变体、人物关联、相关概念，以及 canonical concept card（并区分 canonical / candidate / 未见证）。
4. **做历时研究**：系统有 `diachronic` 模式与跨 session 证据；但**它不会自动产出一部"概念史"** —— 它回答你提出的历时问题，结论仍取决于证据是否充分（可能附条件或弃权）。

**三、人和个案研究**：Person / Case Explorer 严格分开，`Person ≠ Case`、`mention ≠ influence`、`alias ≠ 概念同义`，且**禁止自动 NER 晋级**。当前 reviewed：7 位人物（Descartes、Freud、Hegel、Kojève、Lévi-Strauss、Saussure、Schreber）＋ 5 个个案（Aimée、Dora、Little Hans、Schreber、Wolf-Man），判定方式是**确定性别名匹配 + 最小提及阈值（3）**。

**四、长期研究工作台**：Project 里可以持续放 research question / hypothesis / passages / concepts / persons / cases / bibliography / open questions / notes，并按 revision 并发保护，不会"聊完就丢"。

**五、文献与 Zotero**：管理 bibliographic item、区分 `reviewed` / `candidate`、区分 metadata completeness、判断"能不能正式引用 / 缺哪些 metadata"、导入 Zotero CSL JSON 与 Better BibTeX JSON、检查 DOI / ISBN / title-author-year 重复、展示 metadata conflict。**缺什么就显示缺什么**——它不会为了生成漂亮的 APA / Chicago 而偷偷补作者、年份、出版社。

**六、与 Obsidian 的分工**：系统负责证据、原文、检索、来源、数据结构、bibliographic state、validation 与 synthesis；Obsidian 负责你的理解、概念笔记、联想、写作与个人知识网络。机器负责"不乱说"，你负责"怎么理解"。

**七、它辅助写作的方式（**与你的原稿不同，请注意**）**：系统**不生成"初稿"**。它给的是：已核证的证据与引文、可导出的 Markdown / JSON / HTML / bundle、可用的引用样式（`internal-short` / `internal-full` / `provenance`；`chicago` / `mla` / `apa` / `bibtex` 因 metadata 不足**当前一律不可用**并给出缺项）、以及"保存到 Obsidian"。写作链路是：
`资料 → 检索 → 证据 → claim → 导出/打包 → 你在 Obsidian 里写成文章`。

**八、它适合做什么**：理论研究（性化公式、objet a、gaze、jouissance、Real/réalité、Other/autre/Autre、sinthome、四种话语、RSI、Name-of-the-Father）、个案研究（Schreber、Dora、Aimée、Wolf Man、Little Hans）、以及跨学科方向（拉康×梅洛-庞蒂 / 黑格尔 / 索绪尔 / Lévi-Strauss / 身体现象学 等）——**前提是语料里有相应证据**；没有就如实弃权（例如"拉康如何看待 fMRI 等当代神经科学影像"在本系统里就是**弃权样例**）。

**九、一句话定位**：它不是"拉康聊天机器人"，而是 **Lacan-specific Research Environment（拉康派精神分析数字研究环境）**：目标不是让 AI 替你成为拉康专家，而是让你在研究拉康时，拥有一个能检索原文、追踪证据、组织概念、管理个案与文献、并服务长期写作的研究工作流。

---

## B. 逐条核查（结论 / 证据）

| 原稿说法 | 判定 | 实测证据 |
| --- | --- | --- |
| 核心语料约 24.9 万 passage | ✅ 精确 | `passages = 249,105`；按 witness：staferla 166,527 + zh.translation-project 82,578 |
| 存放"拉康研讨班、法文文本、中文材料、相关文献" | ⚠️ 加限定 | passage 只来自上述 2 个 witness；另有 `witness.fr.seuil-pdf`（带页码定位）**0 段**，只作书目/见证记录；仓库 144 份源文档中其余部分是文档/书目对象，未全部切分为 passage |
| lexical / exact / entity / metadata 多路检索，不只靠向量 | ✅ | 检索过滤：seminar/session/language/source_layer/date_range/concept/formalism；向量为辅助并上报 `dense_available` |
| 回答 → claim → passage → session → seminar/document → witness/source | ✅ | 冻结核心的 claim/entailment/citation 管线 + `trace_source` 链（含 edition/source_layer/trace_status）；缺层写 `Not linked` |
| Projects 保存长期主题/问题/假设/证据/人物/个案/参考文献 | ✅ | project_api：question / hypothesis / note / open_question / evidence refs / run 快照 / compare / verify / manifest |
| 与 Obsidian 连接，长期保存概念卡、研究笔记、书目笔记、个人思考 | ✅（加限定） | 默认写入**受管工作区 vault** `_workspace/obsidian_vault`（`OBSIDIAN_VAULT_PATH` 可改指你的库）；`_System/...` 为派生笔记；用户区逐字节保护 |
| 大模型不自由发挥，在检索证据上 synthesis，证据不足时 abstain | ✅ | 六个 answer state；`ABSTAINED` 是**学术状态**而非错误；provider 必须显式选择 |
| 能问 objet a / gaze / jouissance / 性化公式 等问题 | ✅（结果取决于语料） | 示例问题即为验收用样例；证据不足时系统给 `INSUFFICIENT_EVIDENCE` 或 `ABSTAINED` |
| 能查原文（哪些文本、前后文、seminar、session、法/中文、witness） | ✅ | Explorer：passages / passage + context / seminars / session reading / terminology / languages / witness / provenance / L1·L2 |
| 概念研究（相关 passages/seminar/术语变体/人物/相关概念/canonical card） | ✅ | `browse_api` 概念详情：Canonical Reference / 关系 / 术语 / 相关概念 / 证据样本 |
| 历时研究："1960 前后的 Real 与 1970 后的 Real 有什么区别" | ⚠️ 加限定 | 有 `diachronic` 任务类型与跨 session 证据；但**系统不自动合成概念史**，能否得到可用答案取决于证据充分性 |
| Person / Case 严格分开；Schreber(person) ≠ Schreber(case) | ✅ 完全成立 | `person.schreber` 与 `case.schreber` 为不同实体，跨 kind 折叠被拒绝；`mention ≠ influence`；禁止自动 NER 晋级 |
| 人物名单 Freud/Hegel/Kojève/Descartes/Saussure/Lévi-Strauss/Schreber | ✅ 逐字吻合 | reviewed persons = 上述 7 位（`person.freud` 的 mention 索引被标注 truncated） |
| 个案名单 Schreber/Dora/Little Hans/Wolf-Man/Aimée | ✅ 逐字吻合 | reviewed cases = 上述 5 个 |
| Bibliography：reviewed/candidate、completeness、能否正式引用、缺哪些字段 | ✅ | `GET /api/explore/citation_availability` 逐样式给 `READY|UNAVAILABLE` **+ 原因** |
| Zotero CSL JSON / Better BibTeX JSON、DOI/ISBN/title-author-year 去重、conflict | ✅ | 只支持这两种文件；XML → `UNSUPPORTED_FORMAT`；去重强/弱两档，**从不自动合并**；冲突 `UNRESOLVED`，**只展示** |
| "不会为了漂亮引用偷偷补作者/年份/出版社" | ✅ **强成立** | 4 条 reviewed 条目目前**没有任何一条**能生成完整 Chicago/APA/MLA/BibTeX；publisher/year/ISBN 保持 `null`（`—`） |
| Obsidian 分工："机器负责不乱说，你负责怎么理解" | ✅ | 派生笔记 + 用户区保护 + 无自动 canonical 晋级 |
| "让 AI 根据已选证据生成初稿" | ❌ **当前不存在** | 全仓库无 draft/初稿 生成入口；Export 格式为 `markdown / json / html / bundle`，写作由你完成 |
| 适合跨学科（4E cognition、电影理论等） | ⚠️ 取决于语料 | 可以问；语料没有就弃权（fMRI 问题即弃权样例），系统不会用模型知识补 |

---

## C. 不可写入正式表述的说法（会失真或过度承诺）

1. **"已通过人类学术复核"** —— 不成立。验收协议是 **AI-only**（`review_assurance=AI_ONLY`、`human_review_performed=false`）。"可审计"指**工程与证据可追溯**，不等于人文同行评议。
2. **"可以生成正式 APA/Chicago/MLA/BibTeX 引用"** —— 当前 false：4 条 reviewed 条目均缺已核实出版信息；正式样式一律 `UNAVAILABLE` 并列出缺项。
3. **"能给出页码级定位"** —— 仅瑟伊版 witness 有 `page_locator`，但它 **0 段**；Staferla（166,527 段）无页码元数据。段落级引用只能到 passage/session 层级。
4. **"中文材料与法文完全对应"** —— 中文侧是社区中译，状态为 `SOURCE_TRACE_INCOMPLETE`、`edition_id = null`；这是**学术限制**，系统如实显示。
5. **"人物/个案是全量知识图谱"** —— 当前是 7 位人物 / 5 个个案（确定性别名匹配 + 最小提及 3 次），不是通用 NER 索引；`mention` 只是提及，**不能推断影响关系**。
6. **"AI 能替你把文章写出来"** —— 见 B 表最后两行：证据、引文、导出、Obsidian 保存都有；**初稿与论证是你的工作**。
7. **"Work 层做了版本/版次推断"** —— Work 层只做**确定性映射**；`Not linked` 就是 `Not linked`。
