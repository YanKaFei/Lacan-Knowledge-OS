# INGESTION_PIPELINE.md — 摄入流水线

> 版本 `1.0.0`　·　原则：**结构优先、只增不改、可重跑、每步可验证**

---

## 1. 全景

```
        ┌─────────────────────────────────────────────────────────┐
        │ 只读区  <HOME>  (永不写入)      │
        └─────────────────────────────────────────────────────────┘
                              │ ① 只读扫描
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ S0  INVENTORY            _scripts/inventory_corpus.py  ✅已实现│
   │     sha256 / 语言 / 元数据 / 重复组 / parse_status            │
   │     → _data/corpus_inventory.{json,csv} + corpus_report.md    │
   └──────────────────────────────────────────────────────────────┘
                              │
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ S1  DOCUMENT CONSOLIDATION                                    │
   │     4 组 sha256 重复 → 单 document 多物理文件                  │
   │     5 组同书分卷     → 单 document 多 part                     │
   │     产出 doc.* 实体 + work./edition. ID                        │
   └──────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
   ┌────────────────────────┐  ┌──────────────────────────────┐
   │ S2a TEXT EXTRACTION    │  │ S2b OCR (仅 14 个 NEEDS_OCR) │
   │   109 个 PARSED 直接过  │  │   ocrmypdf / tesseract        │
   └────────────────────────┘  └──────────────────────────────┘
                    └─────────┬─────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ S3  STRUCTURAL PARSING   ★ 禁止固定 token 切分                 │
   │     Document → Seminar → Session → Section → Paragraph        │
   │     产出 seminar.* / session.*                                │
   └──────────────────────────────────────────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ S4  PASSAGE SEGMENTATION                                      │
   │     稳定 ID passage.S11.1964-02-12.P007                        │
   │     structure_path 全路径保留                                  │
   └──────────────────────────────────────────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ S5  LANGUAGE + ALIGNMENT                                      │
   │     逐 Passage 语言判定；fr/en/zh 对齐 → translation 实体      │
   └──────────────────────────────────────────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ S6  ENTITY EXTRACTION            → 全部 review_status=candidate│
   │     concept / term / person / case / topology / matheme …      │
   └──────────────────────────────────────────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ S7  RELATION SUGGESTION          → relations.candidate.jsonl  │
   └──────────────────────────────────────────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ S8  VALIDATION                                               │
   │     validate_vault.py：schema / ID / wikilink / relation / trace│
   └──────────────────────────────────────────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ S9  HUMAN REVIEW & PROMOTION    ★ 只有人能把候选升为 canonical │
   └──────────────────────────────────────────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ S10 DERIVED INDEX BUILD（可随时全量重建）                      │
   │     SQLite FTS5 / LanceDB 向量 / Graph 索引 / alias 表         │
   └──────────────────────────────────────────────────────────────┘
```

---

## 2. 每一步的输入 / 输出 / 验收

### S0 INVENTORY — ✅ 已实现

| 项 | 内容 |
|---|---|
| 脚本 | `_scripts/inventory_corpus.py` |
| 输入 | 源目录（只读，`open(...,'rb')` / `open(...,'r',encoding=...)`） |
| 输出 | `_data/corpus_inventory.json`、`.csv`、`_data/corpus_report.md` |
| 实测 | 143 文件 / 1.198 GiB / **4 组字节级重复 + 5 组同书分卷** / 14 需 OCR |
| **附带产出** | **`document_id`（逻辑文档归并）**：143 文件 → **133** 个逻辑文档，9 个多文件文档。这把 S1 的核心工作提前到了 S0 —— 下游不必再从报告文字里反推归并关系 |
| 测试 | `_scripts/test_inventory.py` — **21 项全绿** |
| 验收 | ① 三份产出非空 ② `source_readonly: true` ③ 源目录 mtime 不变 ④ 幂等 |

**已实现的关键保证**

- 只读：进程内没有任何对源目录的写操作。
- 幂等：重复运行产出 byte-identical（除 `generated_at`），有测试断言。
- 容错：单文件解析失败不中断整体，记入 `anomalies`。
- 诚实：解析不确定时输出 `NEEDS_OCR` 等明确状态，而不是猜测。

### S1 DOCUMENT CONSOLIDATION

> ✅ **S0 已完成归并计算**：`corpus_inventory.json` 的每条 record 现在都带
> `document_id`（143 文件 → 133 逻辑文档，9 个多文件文档）。
> S1 因此只剩下「把归并结果渲染成 vault 节点」这一步，不再需要重新推导。

| 项 | 内容 |
|---|---|
| 输入 | `corpus_inventory.json` 的 `document_id` + `duplicate_groups` |
| 动作 | 按 `document_id` 生成 `document` 实体；字节级重复与同书分卷天然落在同一 id |
| 输出 | `01_Sources/Documents/*.md`（`doc.dup-*` / `doc.work-*` / `doc.<slug>-<hash>`） |
| 规则 | **物理文件一律不动**；`source_path` 记多值；`source_hash` 记每个物理文件 |
| 验收 | 每个 `document` 的 hash 集合与 inventory 的重复组一致 |

⚠️ 归并是**逻辑**行为。禁止移动、重命名、删除源文件。

### S2a 文本抽取 / S2b OCR

| 项 | 内容 |
|---|---|
| 输入 | 143 个文件的文本（109 已可解析）+ 14 个 NEEDS_OCR |
| 工具 | `pypdf`（已用）；OCR 需 `ocrmypdf`/`tesseract`（**尚未安装**） |
| 输出 | `_data/raw_text/<source_hash>.txt`（派生，可重建） |
| 验收 | 抽出的文本可回溯到 `source_hash`；OCR 结果人工抽检 |

**OCR 的目标 14 个文件**（`corpus_report.md` §3 全清单），其中体积较大的：

- 吴琼《雅克·拉康：阅读你的症状》612 页
- 齐泽克《意识形态的崇高客体》405 页
- 沈志中《精神分析辭彙》686 页
- 迪伦·埃文斯《拉康精神分析介绍性辞典》484 页
- 商务印书馆《研讨班七：精神分析的伦理学》482 页
- Clérambault《Oeuvre psychiatrique》Vol.1（465 页）/ Vol.2（408 页）
- Colette Soler《l'inconscient à ciel ouvert de la psychose》265 页

> 注意：`研讨班七`（482 页，商务印书馆 2021）是 **L1 一手文献**且需 OCR，
> 优先级最高——它是目前唯一的 S7 中文底本。

### S3 STRUCTURAL PARSING ★ 架构红线

| 项 | 内容 |
|---|---|
| 输入 | 文本 |
| 输出 | `seminar.*` / `session.*` |
| 规则 | **必须按文献结构解析**，禁止按固定 token 长度切分 |
| 依据 | 研讨班有明确的「课次 → 日期 → 小节」结构；Écrits 有篇目结构 |
| 验收 | 每个 `session` 有真实 `session_date`；无法确定日期的必须标 `unknown` 而非编造 |

**为什么禁止固定 token 切分**：拉康的论证单位是「课次」和「段落」。
按 512 token 切会把一个论证切成三段、把两次课拼成一段，
导致 Passage 无法承载「这段出自哪一课」这一最基本的信息。

### S4 PASSAGE SEGMENTATION

| 项 | 内容 |
|---|---|
| 输出 | `passage.*` 实体 |
| ID | `passage.<seminar>.<session_date>.P<nnn>` |
| 字段 | `structure_path` / `page_from` / `page_to` / `paragraph_index` |
| 稳定性 | 重新切分不改已有 ID；新段落追加序号 |
| 验收 | 每个 Passage 都能反解出 seminar 与 session_date |

### S5 LANGUAGE + ALIGNMENT

| 项 | 内容 |
|---|---|
| 输出 | `translation.*` 实体 + `aligns_with` 指针 |
| 语言判定 | 字符谱统计（中/拉丁/西里尔/希腊/阿拉伯 + 变音符号密度） |
| 对齐 | 同一 Passage 的 fr/en/zh rendition 互指 |
| 验收 | 不存在「孤立的中译块」（即找不到对应原文 Passage 的中译） |

### S6 ENTITY EXTRACTION

| 项 | 内容 |
|---|---|
| 输出 | `concept` / `term` / `person` / `case` / `topology` / `matheme` … |
| **强制** | 全部产出 `review_status: candidate`、`generated_by: ai:...` |
| 验收 | 无任何 AI 产出直接带 `canonical` |

### S7 RELATION SUGGESTION

| 项 | 内容 |
|---|---|
| 输出 | `_data/relations/relations.candidate.jsonl` |
| 强制 | `review_status: candidate`；`confidence < 0.5` 的只留候选 |
| 验收 | `relations.jsonl`（主库）中不含任何 `candidate` |

### S8 VALIDATION

| 项 | 内容 |
|---|---|
| 工具 | `_scripts/_tools/validate_vault.py --strict` |
| 检查 | schema / ID 唯一 / canonical_name 唯一 / broken wikilink / invalid relation / source trace / duplicate entity / orphan concept |
| 输出 | `_index/Reports/validation-report.{md,json}` |
| 验收 | `--strict` 退出码为 0 |

### S9 HUMAN REVIEW & PROMOTION ★ 唯一的人工闸门

提升路径：

```
candidate → needs_review → reviewed → canonical
```

**只有人**可以执行 `reviewed` / `canonical`，且必须填 `reviewed_by` + `reviewed_at`。
AI 综合（L4）**永不**成为 canonical。

### S10 DERIVED INDEX BUILD

| 索引 | 技术 | 可重建 |
|---|---|---|
| 别名精确表 | JSON / SQLite | ✅ |
| 词法检索 | SQLite **FTS5**（已验证可用，sqlite 3.51.0） | ✅ |
| 语义检索 | **LanceDB**（第一版选型） | ✅ |
| 图索引 | `relations.jsonl` + SQLite 邻接表 | ✅ |
| 元数据过滤 | SQLite | ✅ |

**明确不做**：不引入 Neo4j（关系规模未到需要图数据库的程度）。
**明确不做**：本阶段不对整个 corpus 做 embedding。

---

## 3. 三条不可违反的工程约束

### 3.1 只增不改（append-only）

- 源目录：**只读**。整个流水线没有任何回写源目录的代码路径。
- vault：新内容以新节点/新文件落地；修改已有节点必须留下 `updated_at` 变更。
- 派生物：可整体删除重建，不做原地增量修补。

### 3.2 幂等（idempotent）

每个阶段必须可重复运行且结果一致。S0 已有测试断言
（`test_17_idempotent`）。后续阶段的脚本必须遵循同样的契约。

### 3.3 失败要显式（fail loud）

| 情况 | 错误行为 | 正确行为 |
|---|---|---|
| PDF 无文字层 | 输出空内容当成功 | `NEEDS_OCR` + 异常清单 |
| 老式 .doc | 静默丢内容 | `PARSED_PARTIAL` + 建议 textutil |
| 不支持的格式 | 忽略 | `UNSUPPORTED_FORMAT` + 入异常清单 |
| 无法确定课次日期 | 猜一个日期 | 标 `unknown` |
| 找不到出处 | 编一个 | `SOURCE_TRACE_INCOMPLETE` |

---

## 4. 目录约定

```
派生数据（可删除重建，不入 git 或用小体积才入）
_data/corpus_inventory.json          人工可读，入 git
_data/corpus_inventory.csv           入 git
_data/corpus_report.md               入 git
_data/raw_text/*.txt                 体积大，.gitignore
_data/entities/*.json                入 git
_data/relations/*.jsonl              入 git（可 diff，是核心资产）
_data/provenance/*.json              入 git

索引（全部可重建，.gitignore）
_index/Views/*.md                    入 git（人读）
_index/Reports/*.md                  入 git
_index/fts.sqlite                    .gitignore
_index/vectors/                      .gitignore
```

---

## 5. 尚未具备的前置条件（诚实清单）

流水线要在 S2b 之后继续，还需要：

| 缺什么 | 影响 | 解法 |
|---|---|---|
| **OCR 工具链未装** | 14 个文件（含 S7 中译、埃文斯辞典）无法进入 S3 | 安装 `ocrmypdf` + `tesseract`（含 chi_sim/fra/eng 语言包） |
| **中译的「上游源目录」已消失**（`研讨班中译/`） | `corpus.py` 无法重跑 | 语料本体仍在 `.lacan-build/atlas/segments.jsonl`（82,578 段，**唯一副本**）→ ROADMAP **R0.1 先备份**，R0.2 导入；重抓 GitHub 降级为 R0.6 交叉校验 |
| **中文分词策略未定** | FTS5 对中文默认不分词 | Phase 3 决策（jieba / trigram / 自定义） |
| **结构解析规则未定** | 各版本排版不同 | Phase 2 逐本建立解析器 |

这些都必须显式记录，而不是假装流水线已经贯通。

---

*配套：`ARCHITECTURE.md`（总纲）、`SOURCE_PROVENANCE.md`（溯源要求）、
`ROADMAP.md`（阶段与优先级）*
