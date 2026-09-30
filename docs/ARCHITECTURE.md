# ARCHITECTURE.md — Lacanian Knowledge OS

> 版本 `1.0.0`　·　阶段 Phase 1（Inventory + Architecture + Vault Scaffold）
> 本文件是整个系统的架构总纲。任何实现若与本文件冲突，以本文件为准；
> 若要改变本文件，必须同时改 `00_System/Schemas/CHANGELOG.md`。

---

## 0. 这一阶段实际面对的现实（不是设想）

架构不能建立在想象上。以下是 `_scripts/inventory_corpus.py` 对
`<HOME>` 的实测结果（2026-09-20，只读扫描）：

| 指标 | 实测值 |
|---|---|
| 文件总数 | **143** |
| 总体积 | **1.198 GiB** |
| PDF / DOCX / PNG / JPG / DOC / EPUB | 90 / 30 / 14 / 2 / 4 / 3 |
| 文本可解析（PARSED） | 109 |
| 需 OCR（NEEDS_OCR） | 14 |
| 仅部分可解析（老式 .doc） | 4 |
| 图片（本阶段不做 OCR） | 16 |
| 语言分布 zh / fr / en / und | 87 / 24 / 22 / 10 |
| 精确重复文件（sha256 相同） | **4 组 / 9 个文件** |
| 同一本书被切分的分卷 | **5 组 / 10 个文件** |
| 用户自己标注「要重新ocr」 | 2 |
| **逻辑文档数（document_id 归并后）** | **133**（143 个文件 → 133 个逻辑文档） |
| 多文件逻辑文档 | 9（4 组字节级重复 + 5 组同书分卷） |

同时必须记录一处**关于既有语料的重要事实**，它直接决定路线图：

> `<HOME>` 记录过一个完整的
> `<HOME> knowledge/` vault：28 期研讨班中译 82,578 段 +
> 法语转录 166,527 段 + 57 张概念卡，以及 `.lacan-build/` 里一整套构建流水线。
> **该 vault 本体已不在磁盘上**（工作区只留下一个指向 `dsh-lacan-kb` 的死符号链接），
> 技能 `.dsh/skills/lacan-query/SKILL.md` 仍然指向这个不存在的路径。
>
> **但语料本身没有丢。** 实测 `.lacan-build/atlas/` 仍然保有：
>
> | 文件 | 内容 | 实测 |
> |---|---|---|
> | `segments.jsonl` | **28 期中译**，含 `lesson` 课次与段号 | 82,578 段 / 531 个 (期,课) 组合 |
> | `french_staferla.jsonl` | **28 期法语转录**（STAFERLA），带 provenance 声明 | 166,527 段 |
> | `seminars.json` | 28 期元数据（罗马数字/法文名/中文名/年份/课数） | 28 条 |
> | `french.jsonl` | 法语 PDF 底本抽取（S1–S5，带页码） | 8.7 MB |
> | `lacancom.json` / `term_vocab.json` / `term_neighbours.json` | lacan.com 书目、术语表、邻近词 | — |
>
> 合计 **249,105 个已带出处的段落**可直接用。
>
> ⚠️ 而中译的**上游源目录** `研讨班中译/` 已从 `<HOME>`
> 中消失。因此 `.lacan-build/atlas/segments.jsonl` 目前是那 82,578 段中译的
> **唯一副本** —— Phase 2 的第一件事是把它备份并导入 vault，
> 而不是去重抓 GitHub。

**架构含义**：语料不是一张白纸。Phase 1 要为**当前 143 个原始文件**建立 inventory，
同时 vault 结构必须**能无损接纳**那 249,105 段已结构化语料 ——
这正是 Passage 实体与 `passage.S<seminar>.<session_date>.P<nnn>` ID 格式
在设计上对齐 `.lacan-build` 既有段号体系（`s1-01-0001`）的原因：导入时不需要转换语义，
只需要补齐日期维度。

---

## 1. 第一原则：Markdown Vault 是唯一 Source of Truth

```
                    ┌──────────────────────────────────────────┐
                    │   Obsidian Vault (Markdown + YAML)       │
                    │   = 唯一知识本体 / Source of Truth        │
                    │   人类可读、可编辑、可双向链接、可 git    │
                    └──────────────────────────────────────────┘
                                     │
        ┌────────────┬───────────────┼───────────────┬────────────┐
        ▼            ▼               ▼               ▼            ▼
   SQLite FTS5   LanceDB 向量    Graph 索引     exact-alias     MCP Server
   (词法检索)     (语义检索)      (关系遍历)      (别名精确)      (统一外部接口)
        └────────────┴───────────────┴───────────────┴────────────┘
                    ▲
              全部可重新生成（derived, disposable）
              删掉任何一个，都能从 vault 重建
```

**硬规则（不可违反）**

1. **衍生索引不得成为唯一知识本体**。SQLite / LanceDB / 图索引全部是可丢弃的
   派生物；任何只存在于索引里的知识都是设计错误。
2. **自动生成物永不覆盖原始资料**。源目录 `<HOME>`
   全程只读（`test_inventory.py::test_18_source_untouched` 对此有自动化断言）。
3. **原始资料默认只读**。写入永远发生在 vault 内，不发生在源目录。
4. **每条 AI 结论都能回溯到 Source / Seminar / Session / Passage**，
   不能回溯的必须显式标记 `SOURCE_TRACE_INCOMPLETE`（见 SOURCE_PROVENANCE.md）。

---

## 2. 仓库布局

```
Lacan-Knowledge-OS/                    ← Obsidian vault 根（Source of Truth）
│
├── 00_System/                         系统层
│   ├── Schemas/                       JSON Schema（字段契约，封闭集合）
│   │   ├── knowledge.schema.json      所有节点 frontmatter 的强制契约
│   │   ├── relation.schema.json       关系记录契约
│   │   ├── id-namespaces.json         24 个实体类型的 ID 命名空间
│   │   └── CHANGELOG.md               schema 版本策略
│   ├── Templates/                     Obsidian 模板（新建节点从这里开始）
│   ├── Validation/                    校验规则说明
│   ├── Guidelines/                    写作规范 / AI 参与边界
│   └── _fixtures/                     Schema 验证用代表性样本（含 manifest）
│
├── 01_Sources/                        来源层（Source 实体）
│   ├── Documents/                     一个逻辑文献 = 一个 Document（含分卷合并）
│   ├── Editions/                      版本、译本、译者、出版社
│   └── Web_Archives/                  lacan.com 等网站的离线快照（后续阶段）
├── 02_Lacan_Seminars/                 研讨班（S01…S23…按需扩展）
│   └── S23_Seminar_XXIII/             Seminar → Session 两级
├── 03_Ecrits/                         Écrits 与单篇文本
├── 04_Concepts/                       概念（本体，不承载定义）
│   ├── States/                        ★ 概念的历史阶段状态（定义只在这里）
│   └── Comparisons/                   概念比较 / 辨析
├── 05_Terminology/                    术语与翻译
│   ├── FR/ EN/ ZH/                    三个语言各自的术语条目
│   └── Alignments/                    ★ 跨语言对齐（fr↔en↔zh 同一 passage）
├── 06_Clinical/                       临床结构（神经症/精神病/倒错、日常精神病）
├── 07_Cases/                          个案（Schreber、Aimée、临床演示…）
├── 08_Topology_Mathemes/              拓扑 / 数学型 / 公式 / 四种话语
├── 09_Philosophy/                     哲学（拉康与之的关系）
├── 10_Freud/                          弗洛伊德
├── 11_Thinkers/                       哲学家 / 精神分析家
├── 12_Schools_Debates/                学派与争论（ECF/WAP/Lacanian…）
├── 13_Reading_Notes/                  阅读笔记（L3）
├── 14_Synthesis/                      AI 综合（L4，永不自动升格）
├── 15_Questions/                      悬而未决的问题
├── 16_Research_Projects/              研究项目
│
├── _attachments/                      附件（图片、PDF 副本）
├── _data/                             ★ 衍生数据（可重新生成）
│   ├── corpus_inventory.json          inventory 产物
│   ├── corpus_inventory.csv           同上的表格形式
│   ├── corpus_report.md               inventory 人类可读报告
│   ├── entities/                      从 vault 抽出的实体表
│   ├── relations/                     relations.jsonl / relations.candidate.jsonl
│   └── provenance/                    溯源链缓存
├── _index/                            生成索引（Views / Reports）
└── _scripts/                          工具链
    ├── inventory_corpus.py            只读语料盘点（Phase 1 已交付）
    ├── _tools/validate_vault.py       vault 校验
    ├── _tools/make_index.py           生成 _index/Views
    └── _tests/                        自动化测试
```

**为什么 vault 里放 `_data` / `_index` / `_scripts`**：它们用 `_` 前缀，
Obsidian 仍然可索引但视觉上退到末尾；同时让「知识本体 + 派生索引 + 工具」
在一个 git 仓库里原子演进，`.gitignore` 只需排除体积大的派生物
（向量库、FTS 文件），JSONL / Markdown 索引应当入库以便 diff。

---

## 3. 权威分层（Source Authority）

| 层 | 名称 | 内容 | 谁的产物 |
|---|---|---|---|
| **L0** | RAW SOURCE | 原始文件字节（PDF/DOCX/图片） | 只读，不修改 |
| **L1** | PRIMARY SOURCE | Lacan 研讨班 / Écrits / 讲演；Freud 原文 | 拉康、弗洛伊德本人 |
| **L2** | SECONDARY SOURCE | Miller / Fink / Soler / Žižek / Maleval… 的研究 | 他人 |
| **L3** | RESEARCH NOTE | 人工研究笔记、卡特尔记录、翻译稿 | 人 |
| **L4** | AI SYNTHESIS | AI 生成的综合、概念建议、关系建议 | AI |

**分层不是标签，是权限**：

- `authority_level` 是 frontmatter 必填字段，schema 强制枚举。
- `type: synthesis` 的节点被 schema **强制**为 `authority_level: L4`。
- **L4 永不自动升格为 L1/L2/canonical**。升格只能由人做，且必须同时填写
  `reviewed_by` + `reviewed_at`，`review_status` 才能是 `canonical`。
- 校验器把「L4 节点却声称 canonical」直接判为错误。

对当前 143 个文件的实测分层：

| 层 | 文件数 | 说明 |
|---|---|---|
| L1 PRIMARY | 17 | 研讨班 PDF（实测识别出 **7 期**：S1/S2/S3/S4/S5/S20/S23；另有「研讨班七·伦理学」中译本存在但未解析出期号） |
| L2 SECONDARY | 76 | 二手书籍 27 + 二手研究文献 49 |
| L3 RESEARCH NOTE | 34 | 研究笔记 22 + 卡特尔会议记录 12 |
| L0/附件 | 16 | 图片（本阶段不做 OCR） |

> 注意：`判断依据` 见 `_data/corpus_inventory.json` 的 `source_type` 字段与
> `corpus_report.md` §6。这是**目录语义 + 文件名启发式**的自动判断，
> 是 L0 级事实，不是人工审定结论；进入 vault 时必须由人确认。

---

## 4. 实体模型：两层概念结构（架构上最重要的一条）

拉康的概念不能被压成单一静态定义。因此架构上把「概念」**拆成两层**：

```
concept.objet-a                     ← 本体：只有身份（ID、规范名、别名、跨语言写法）
       │  concept_states: [...]
       ├── state.objet-a.1953-1955     ← 阶段状态：定义只在这里
       ├── state.objet-a.1964-1966
       ├── state.objet-a.1967-1971
       └── state.objet-a.1972-1973
```

**为什么必须这样拆**：如果允许把定义写在 `concept.objet-a` 上，那么
「补全这张卡」这个动作天然会诱导把不同时期的解释合并成一句通顺的话——
这正是要禁止的。结构上让本体**没有地方放定义**，合并就不可能悄悄发生。

配套的三条机制：

1. `concept_state` 必须带 `period`（枚举分期）+ 至少一个 `passage` 证据。
2. `concept_state` 可以带 `supersedes`，显式表达「本阶段改写了上一阶段」。
3. 校验器把「有 concept 节点但没有任何 concept_state」判为 `orphan concept` 警告；
   把「concept_state 的 period 不在枚举内」判为错误。

完整实体清单（24 个 type）与 ID 命名空间见 **ENTITY_MODEL.md**。

---

## 5. Passage：最小证据单元

禁止按固定 token 长度切 PDF。结构优先：

```
Document → Seminar → Session → Section → Paragraph → Passage
```

- `Passage` 是**唯一可被引用**的最小单元，拥有稳定 ID，例如
  `passage.S11.1964-02-12.P001`。
- Passage 的 ID 里编码了 `seminar` + `session_date`，因此从任何引用都能
  反推回 Seminar 与 Session，不需要查表。
- `structure_path` 字段保留完整结构路径（如
  `S11/1964-02-12/section-03/para-07`），即使未来重新切分，ID 也不会变。
- **跨语言对齐**：法文/英文/中文三个版本的同一段落是**同一个 Passage 的不同
  Rendition**（`translation` 实体），通过 `aligns_with` 互相指向，
  而不是三个互不相干的块。见 §6。

---

## 6. 跨语言模型

当前语料本身就是多语言的（zh 87 / fr 24 / en 22）。实测中发现同一部作品
同时存在原版与中译，例如：

- `Incandescent Alphabets…(Annie G. Rogers).pdf` + `…汉化版.pdf`
- 研讨班 20 / 23 同时有「中文版」「中英对照版」「中英对照(1)」

架构规定：

| 实体 | 职责 |
|---|---|
| `document` | 一个逻辑作品（无论多少语言版本/多少个分卷文件） |
| `edition` | 该作品的一个具体版本（法文瑟伊版 / 英译 / 中译） |
| `translation` | 某一 Passage 在某一语言下的具体译法，带 `translator` |
| `passage.aligns_with` | 跨语言对齐指针 |

**禁止**：因方便而破坏法/英/中版本关系——即禁止把同一段落的中译和原文
切成两个不相关的知识块，或让中译块失去指向原文 Passage 的指针。

---

## 7. 与既有系统的关系（复用而不重造）

工作区里已存在三套东西，架构上明确各自的位置：

| 既有资产 | 现状 | 架构中的定位 |
|---|---|---|
| **`.lacan-build/atlas/`** | **存在。249,105 段已结构化语料**（中译 82,578 + 法语转录 166,527）+ 28 期元数据 + 术语网络 | ★ **Phase 2 第一优先导入对象**。这是 vault 之外最有价值的知识资产，且中译部分是**唯一副本** |
| `.lacan-build/`（38 个 py，含 `test_build.py` 55KB、`validate_vault.py`） | 存在。原 vault 的构建器 | **代码库保留并复用**。其 `build_corpus_index.py` / `build_cards.py` / `validate_vault.py` 是 Phase 2 的起点 |
| `<HOME>`（3,656 文件） | 存在。含 `corpus-lacan-com/`（lacan.com 抓取 616 txt）、`corpus-shidianguji/`（禅宗 1,695 txt）、`data/{lancedb,bm25,chunks}`（7 库 / 81,884 块）、`preset/lacan-plugin/` | **作为 `01_Sources/Web_Archives/` 的上游数据源**。Phase 6 做**导入**而非重抓。其 LanceDB 结构可作为未来向量库的 schema 参考 |
| `<HOME>` | 存在。~100 份 docs（citation resolver / claim graph / concept boundary registry / association graph…）+ 30 份 eval 结果 | **作为检索层与溯源层的设计参考与验收基线**。其中 CLAIM_TRACE / CITATION_RESOLVER / CONCEPT_BOUNDARY 与本项目的 SOURCE_PROVENANCE / RELATION_MODEL 目标重合，**必须先读再设计 Phase 4**，避免造第二套冲突架构 |
| `<HOME> knowledge/` | ❌ **不存在**（原 vault 本体） | 由 `.lacan-build/` 重新生成 |
| `.lacan-kb` 符号链接 | ⚠️ **死链**，指向不存在的 `dsh-lacan-kb` | 待清理；不要往里写数据 |

**为什么现在不直接 import 它们**：Phase 1 的任务边界是 inventory + 架构 + 骨架。
但架构（尤其 `_data/`、`01_Sources/Web_Archives/`、`04_Concepts/States/`、
Passage ID 格式）已经预留了它们的落位，因此 Phase 2 不需要改架构即可导入
那 249,105 段语料。

---

## 8. 未来检索架构（本阶段只定接口）

混合检索（Hybrid Retrieval），六路合流后重排：

```
Query
  ├─ 1. Exact alias        别名表精确命中（最高精度，处理「对象a / objet a / objet petit a」）
  ├─ 2. SQLite FTS5        词法检索（中文需配合分词策略；FTS5 已确认可用，sqlite 3.51.0）
  ├─ 3. Vector Search      语义检索（建议第一版用 LanceDB，见下）
  ├─ 4. Graph Search       关系图遍历（defines/redefines/influenced_by…）
  ├─ 5. Metadata filter    authority_level / period / seminar / review_status 过滤
  └─ 6. Reranker           交叉重排，输出带 passage_id 的结果
                │
                ▼
        每条结果必须携带：passage_id + source_id + authority_level + trace_status
```

**向量库选型**：第一版用 **LanceDB**（本地文件、无需服务、已有既有实践经验)。
**明确不引入 Neo4j**：关系规模（预计 10³–10⁵ 边）远未到需要图数据库的程度，
`_data/relations/*.jsonl` + 内存图 + SQLite 邻接表足够，且更易 diff 与审计。
只有出现「多跳路径查询性能成为瓶颈」或「需要 Cypher 级查询」时才重新评估。

---

## 9. 未来 MCP 接口（本阶段只预留）

统一知识服务 `lacan-kb-mcp`，DeepSeek Harness 与 Codex 都**通过它**访问，
而不是各自扫描全部文件：

| 工具 | 作用 |
|---|---|
| `search_knowledge` | 混合检索入口 |
| `get_concept` | 取概念本体（含全部 concept_state 链接） |
| `get_passage` | 取 Passage 原文 + 所属 Session/Seminar + 语言版本 |
| `get_source` | 取 Source/Document/Edition 元数据 |
| `get_neighbors` | 关系图邻居 |
| `search_by_period` | 按分期检索 |
| `search_seminar` | 按研讨班期号检索 |
| `compare_concepts` | 概念比较（跨 concept_state 并列，不合并） |
| `trace_claim` | 溯源链查询，返回完整链或 `SOURCE_TRACE_INCOMPLETE` |
| `get_topology` | 取拓扑/数学型 |
| `get_case` | 取个案 |
| `get_term_history` | 术语的三语与历史译法 |

**接口契约的关键约束**：`trace_claim` 必须返回完整链
`Claim → Passage → Session → Document/Seminar → Edition → Original Source`，
任何一环缺失就返回 `SOURCE_TRACE_INCOMPLETE` 而**不是**返回一个看起来完整的答案。

---

## 10. 本阶段（Phase 1）明确的非目标

以下**不在**本轮范围，且架构上已显式排除：

- ❌ 大规模修改原始文件（源目录全程只读）
- ❌ 删除重复资料（只标记 4 组 sha256 字节级重复 + 5 组同书分卷）
- ❌ 全量抓取 lacan.com（既有抓取成果已在 lacan-kb，走导入）
- ❌ 自动下载任意 GitHub repository
- ❌ 自动把 AI 分析写成 canonical knowledge（schema 层面禁止）
- ❌ 对整个 corpus 一次性 embedding
- ❌ 用固定 token chunking 替代文献结构解析
- ❌ 创建无法回溯来源的摘要
- ❌ 破坏法/英/中版本关系
- ❌ 批量转换所有资料为 Markdown（本阶段只做少量代表性样本）

---

## 11. 架构自检清单

任何后续改动前，逐条核对：

- [ ] Markdown vault 仍然是唯一 Source of Truth？
- [ ] 新增字段是否已进 schema 并记入 CHANGELOG？
- [ ] 新写入路径是否落在 vault 内（而非源目录）？
- [ ] L4 内容是否带 `trace_status` 且未被标为 canonical？
- [ ] Passage 是否仍能反向定位到 Seminar/Session？
- [ ] 跨语言版本是否仍通过 `aligns_with` 相连？
- [ ] 概念的多个历史阶段是否仍然并列，而非被合并？
- [ ] 衍生索引是否全部可重新生成？

---

*相关文档：`KNOWLEDGE_SCHEMA.md`（字段契约）· `ENTITY_MODEL.md`（实体与 ID）·
`RELATION_MODEL.md`（关系与谓词）· `SOURCE_PROVENANCE.md`（溯源与断链）·
`INGESTION_PIPELINE.md`（流水线）· `ROADMAP.md`（阶段计划）*
