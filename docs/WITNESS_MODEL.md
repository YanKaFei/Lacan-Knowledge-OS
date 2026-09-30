# WITNESS_MODEL.md — Witness 层（具体文本版本）

> 版本 `1.0.0`　·　事实来源：`_scripts/_tools/build_passage_store.py`
> （第 61–87 行 `ZH_WITNESS`/`FR_WITNESS`、第 191–197 行装配、第 459–463 行 SQLite 表）、
> `_data/passage_store/witnesses.jsonl`、`_data/passage_store/_build_meta.json`

---

## 1. 核心区分：抽象 Passage ≠ 具体文本版本

这是 Passage Store 里最容易搞错、也最重要的一层。

```
抽象 Passage（"S1 第 1 课的某一句"）
   │
   ├── witness.fr.staferla            ← 法语的 STAFERLA 工作转录（166,527 段）
   ├── witness.fr.seuil-pdf           ← 法语的 PDF 底本抽取（12,190 段，带页码，S1–S5）
   └── witness.zh.translation-project ← 中文的社区中译（82,578 段）
```

**一个 Passage 不是一段文本，是一个位置。** 它有稳定的 ID
（`passage.S01.unknown.L01.P0001`），但这个位置上的**文本**可以有多个来源：

- 法文（两份，**尚未互相映射**）：
  - STAFERLA 的工作转录（**不是**瑟伊版定本）
  - 本地法语 PDF 底本抽取（带页码，覆盖 S1–S5）
- 中文：Lacan-Chinese-Translation-Project 的社区中译
- 将来还可能有：瑟伊版定本、其他英译、修订版转录、更正版

**如果两者混为一谈**，就会出现「引用 `passage.S01...P0001` 时，
读者不知道被引的是哪一版文本」—— 而不同版本的同一句可能措辞不同，
这正是引用必须精确到版本的原因。

---

## 2. 本阶段实测的三个 witness

来源：`witnesses.jsonl` 实际内容（**3 条**）；计数与
`_data/passage_store/_build_meta.json` → `counts.witnesses` 一致。

| # | witness id | 语言 | `witness_kind` | `text_role` | 权威层级 | 段数 | `source_state` |
|---|---|---|---|---:|---:|---|---|
| 1 | `witness.fr.staferla` | fr | `transcription` | `transcription` | L1 | 166,527 | `upstream_present` |
| 2 | `witness.zh.translation-project` | zh | `translation` | `translation` | L2 | 82,578 | `upstream_missing` |
| 3 | **`witness.fr.seuil-pdf`** | fr | **`edition_extract`** | **`edition`** | L1 | **12,190** | `upstream_present` |

> 三条 witness 的段数加总（166,527 + 82,578 + 12,190 = 261,295）
> **不等于** Passage 总数 249,105 —— 因为 `witness.fr.seuil-pdf` 的
> 段**目前没有作为 Passage 进入 store**（见 §2.3）。

### 2.1 `witness.fr.staferla`（法语转录）

```json
{
  "id": "witness.fr.staferla",
  "language": "fr",
  "text_role": "transcription",
  "witness_kind": "transcription",
  "edition": "STAFERLA 工作转录",
  "translator": null,
  "authority_level": "L1",
  "status": "recovered",
  "canonical": false,
  "source_state": "upstream_present",
  "source_file": "french_staferla.jsonl",
  "source_file_sha256": "2712d6da07952b5c390b375a70b065cdddab6fbf9c073142be771df6224b33f5",
  "provenance_note": "Document de travail (transcription STAFERLA) — texte non établi；引用必须标注「工作转录，非瑟伊版定本」"
}
```

### 2.2 `witness.zh.translation-project`（中文社区中译）

```json
{
  "id": "witness.zh.translation-project",
  "language": "zh",
  "text_role": "translation",
  "witness_kind": "translation",
  "edition": "Lacan-Chinese-Translation-Project（社区中译）",
  "translator": "multiple (community)",
  "authority_level": "L2",
  "status": "recovered",
  "canonical": false,
  "source_state": "upstream_missing",
  "source_file": "segments.jsonl",
  "source_file_sha256": "8a109068af21a96e3a591838d2ffa78d8cb581d1f2efd6749c6fa95bb024a96c"
}
```

### 2.3 `witness.fr.seuil-pdf`（法语 PDF 底本抽取）★ 新增

```json
{
  "id": "witness.fr.seuil-pdf",
  "language": "fr",
  "text_role": "edition",
  "witness_kind": "edition_extract",
  "edition": "法语 PDF 底本抽取（S1–S5，带页码）",
  "translator": null,
  "authority_level": "L1",
  "status": "recovered",
  "canonical": false,
  "source_state": "upstream_present",
  "passage_link_state": "not_linked",
  "source_file": "french.jsonl",
  "source_file_sha256": "8d221f18c14614da6332d9a7e4274d3d25dfab7ece1942c6ae0260e4e07e5d6e",
  "provenance_note": "由本地法语 PDF 抽取，带 page 号；与 STAFERLA 转录是两份独立 witness。本阶段**未**在这两份 witness 之间建立对齐 —— 它们的切分粒度不同（PDF 9,799 段 vs 转录 1,868 段），任何未经审核的段对段映射都会是编造。"
}
```

**来源**：`<HOME>`。
实测 **12,190 行**，字段 `['clean','fr','id','page','roman','seminar','source']`
—— 注意其中有 **`page`**（页码），这是它与 STAFERLA 转录的关键差别。
实测逐期段数（与用户转述一致）：

| seminar | 段数 |
|---|---:|
| s1 | 3,034 |
| s2 | 3,218 |
| s3 | 2,387 |
| s4 | 2,571 |
| s5 | 980 |
| **合计** | **12,190** |

实测 `sha256` = `8d221f18c14614da6332d9a7e4274d3d25dfab7ece1942c6ae0260e4e07e5d6e`
—— **与 witness 记录里的 `source_file_sha256` 逐字一致**（已重算比对）。

#### 为什么它是 L1，却同时 `canonical: false`

与 STAFERLA 同理（§3）：L1 说的是「文本作者是拉康」，
`canonical: false` 说的是「这不是馆藏定本」。两者回答不同问题。

#### 关键：有两份法语 witness，但它们之间**刻意没有**段级映射

`passage_link_state: not_linked` 这个字段是这份 witness 独有的，
它明确宣告：**`witness.fr.seuil-pdf` 目前没有与任何 Passage 建立连接**。

**为什么不对齐是诚实的**：

| | STAFERLA 转录 | PDF 底本抽取 |
|---|---:|---:|
| 语言 | fr | fr |
| 段数（全部） | 166,527 | 12,190 |
| **S1 段数** | **1,868** | **9,799** |
| 切分单位 | 转录段落 | PDF 版面文本块 |
| 有页码吗 | ❌ 无 | ✅ 有（`page` 字段） |

**同一期（S1）两份法语的段数相差 5 倍以上**（1,868 vs 9,799）。
段数不同只是表象：**切分单位根本不是一回事** ——
PDF 抽取会把版面碎了，转录是按语义段落整理的。

在这种前提下，任何「第 N 段对第 N 段」或「按长度比配对」的映射
**都不是对齐，是编造**：它会产生 12,190 条看起来有据、实际无语义依据的边，
而这些边一旦被引用，溯源链就会指向**错误的位置**且**全程通过检查**
（与 `ALIGNMENT_MODEL.md` §4.2 描述的「错对齐最隐蔽」是同一风险）。

因此本阶段的选择是：**承认有两份独立 witness，不假装它们已对齐。**
`passage_link_state: not_linked` 就是这个状态的显式载体 ——
它让「未对齐」成为可机械查询的事实，而不是文档里的一句免责声明。

> **代价（如实记录）**：PDF 底本的 `page` 信息目前**无法用于引用**，
> 因为它没有连到 Passage。要利用它（例如「S3 p.115 的原文」），
> 必须先做**经人工审核**的对齐（Phase 3），或改用别的方式把页锚接入溯源链。

### 2.4 三者对比

| 维度 | `witness.fr.staferla` | `witness.fr.seuil-pdf` | `witness.zh.translation-project` |
|---|---|---|---|
| 语言 | `fr` | `fr` | `zh` |
| `text_role` | `transcription` | **`edition`** | `translation` |
| `witness_kind` | `transcription` | **`edition_extract`** | `translation` |
| `authority_level` | **`L1`** | **`L1`** | **`L2`** |
| 译者 | `null` | `null` | `multiple (community)` |
| `status` | `recovered` | `recovered` | `recovered` |
| `canonical` | `false` | `false` | `false` |
| `source_state` | `upstream_present` | `upstream_present` | **`upstream_missing`** |
| `passage_link_state` | — | **`not_linked`** | — |
| 页码 | ❌ | ✅ `page` | ❌ |
| `provenance_note` | ✅ 有（见 §4） | ✅ 有 | ❌ 无 |
| 段数 | 166,527 | 12,190 | 82,578 |
| 是否已连到 Passage | ✅ 166,527 条 | ❌ **0** | ✅ 82,578 条 |

---

## 3. 为什么权威层级不同（L1 vs L2）

这是 Phase 1 `ARCHITECTURE.md` §3 权威分层的直接应用：

| 层 | 定义 | 本案 |
|---|---|---|
| **L1 PRIMARY** | 拉康、弗洛伊德等人**本人文本** | 法语转录是拉康的**法语原话**（工作转录，但是原语言、原件作者） |
| **L2 SECONDARY** | 他人研究、译注、二手文献 | 中译是**他人的翻译**，不是拉康写的字 |

**关键点：L1 指的是「文本的作者是拉康」，不是「这个版本的可靠性最高」。**

因此 `witness.fr.staferla` 的 `authority_level` 是 L1，但它同时
`canonical: false`、`status: recovered`，并带一句醒目的 provenance 声明 ——
**等级高 ≠ 可以把工作转录当定本用**。这两个字段回答的是不同问题：

- `authority_level` = 这话是谁说的（拉康）
- `canonical` = 这是不是馆藏定本（不是）
- `status` = 这份数据是怎么来的（恢复来的）

中译是 L2，因为它的作者是译者群体；且它比法语多一重不确定性：
法语原话 → 译者理解 → 中文表述。

---

## 4. 为什么 STAFERLA 的 provenance 声明必须原样保留

### 4.1 声明原文

```
Document de travail (transcription STAFERLA) — texte non établi；
引用必须标注「工作转录，非瑟伊版定本」
```

前半句来自上游数据（`.lacan-build/atlas/french_staferla.jsonl` 每条记录的
`provenance` 字段，实测 166,527 条全部带这句），后半句是本库附加的中文操作要求。

### 4.2 「texte non établi」是什么意思，为什么致命

**「texte non établi」= 文本未确立/未校订**。具体意味着：

1. STAFERLA 转录是**爱好者/研究者手工转录**，不是 Seuil（瑟伊）出版社的定本。
2. 转录中可能有听写错误、漏字、标点整理。
3. 转录者会在**方括号里加入自己的补充**——上游声明明确写着
   «les ajouts entre crochets ne sont pas de Jacques Lacan»
   （方括号内的增补不是拉康的话）。

**第 3 条是致命的**：如果引用时不标注，读者会把转录者加的方括号内容
**当成拉康的原话**。这正好是本库存在的理由——防止无法验证的内容伪装成来源事实。

### 4.3 实现如何保证它不被丢掉

| 机制 | 位置 |
|---|---|
| `FR_WITNESS["provenance_note"]` 常量 | `build_passage_store.py` 第 85–86 行 |
| 写入 `witnesses.jsonl` 的 `provenance_note` | 实测存在（§2.1） |
| 写入 `translations.jsonl` 的 `provenance_note`（简版「工作转录，非瑟伊版定本。」） | 实测 `trans.fr.staferla` 有 |

⚠️ **缺一处**：`passages.jsonl` 的**每条法语 passage 没有** `provenance_note`。
声明的载体只到 witness / translation 级（**3 条 witness 中 2 条带声明**
——`witness.fr.staferla` 与 `witness.fr.seuil-pdf` 有，`witness.zh.translation-project` **没有**），
所以**引用某一条法语 passage 时，声明不在那条记录上**。
引用者必须回溯 `witness_id → witnesses.jsonl` 才能取到声明。

这是可接受的（witness 是版本的元数据，不该在 166,527 条上重复），
但**必须在工具层保证「展示 passage 时一并带出 witness 声明」**，
否则声明会在实际使用中被漏掉。`render_vault.py` 与未来的 MCP
工具都需要承担这个义务。**本阶段无此保障**，如实记录。

> 补充（同步 `passage_witnesses` 连接表）：`provenance_note` **也不在连接表里**
> （连接表 7 个字段不含它）。所以要取声明，仍然只能回到 `witnesses.jsonl`，
> 或读 SQLite 的 `witnesses` 表 —— 而**该表不含 `provenance_note`**（见 §6）。
> 结论不变：**声明的唯一可靠载体是 `witnesses.jsonl`。**

---

## 5. 旧 witness 永不被覆盖

### 5.1 规则

> **旧 witness 永不被覆盖；新版本是新增一个 witness。**

`build_passage_store.py` 的 `witnesses` 列表（第 192–197 行）是**字面量构造**，
每次构建都重新生成同样两条。它**没有**任何「按 id 覆盖已有 witness」的逻辑 ——
因为列表本身就是全量，且 id 固定。

### 5.2 为什么必须这样

假设将来拿到瑟伊版定本：

| 做法 | 后果 |
|---|---|
| ❌ 用瑟伊版**覆盖** `witness.fr.staferla` | 所有历史引用（`witness_id: witness.fr.staferla`）会**静默指向另一版文本**；引用完整性当场崩溃 |
| ✅ 新增 `witness.fr.seuil-1975` | 旧引用仍指向工作转录；新引用指向定本；两者可对比；谁引了哪版清清楚楚 |

**这与 Passage ID 的规则同构**：Passage 重切分时新段追加序号而不重排旧序号
（见 `PASSAGE_MODEL.md` §5.3）。**ID 与 witness 都遵守 append-only。**

### 5.3 连接表已就位；边待补

#### ✅ 结构：`passage_witnesses` 多对多连接表（已实现）

**这解决了早期版本的一处真实缺口。** 原先 `passages.jsonl` 里只有一个
`witness_id` 字段（单值），所以「一个 Passage 挂多个 witness」**在数据结构上无从表达**。
现在新增了独立连接表：

| 项 | 实测 |
|---|---|
| 文件 | `_data/passage_store/passage_witnesses.jsonl` |
| 行数 | **249,105**（= Passage 总数） |
| 字段（7） | `passage_id` / `witness_id` / `link_role` / `authority_level` / `review_status` / `method` / `schema_version` |
| SQLite 投影 | `passage_witnesses` 表，**249,105 行**，6 列（无 `schema_version`） |
| `_build_meta.json` | `counts.passage_witness_links: 249105` |

实测取值分布：

| 字段 | 取值 | 计数 |
|---|---|---|
| `link_role` | `transcription` | 166,527 |
| | `translation` | 82,578 |
| `authority_level` | `L1` | 166,527 |
| | `L2` | 82,578 |
| `review_status` | `candidate` | **249,105（全部）** |
| `method` | `native (该段即出自此 witness)` | **249,105（全部）** |

**多对多是真实的容量，不是设想**：主键是
`(passage_id, witness_id)` 组合意义上的边，同一 `passage_id` 将来可以有多行。
`link_role` 描述这条边的性质（该段是此 witness 的转录 / 翻译 / 版本抽取…），
`method` 说明这条边**怎么来的**（`native` = 该段本来就出自此 witness）。

#### ⏳ 现状：每段目前只连到**一个** witness，且本阶段不批量增加边

实测仍是 **1 Passage : 1 link**（249,105 行 = 249,105 段，
每段恰好一条边，`witness_id` 与 `passages.jsonl` 里那个单值字段一致）。

**本阶段不批量增加边的三条理由**：

1. **没有第二个 witness 可连**。第三条 witness（`witness.fr.seuil-pdf`）
   与 STAFERLA 之间的段级映射**刻意未建立**（§2.3），
   因为两者切分粒度差 5 倍以上，未经审核的映射就是编造。
   没有可信映射时，「多」只是把编造数据写进连接表。
2. **`method` 尚未有第二种取值**。目前 100% 是 `native`；
   一旦引入推断出来的边，`method` 必须能区分
   （`heuristic:*` / `model:*`，见 `ALIGNMENT_MODEL.md` §5），
   而这类边的审核能力本阶段不存在。
3. **连接表的价值在审核，不在数量**。加边不会失败、不会被检查拦住 ——
   所以更要在没有审核能力时克制。

#### ⚠️ 仍未解决的：新增 witness 需要改代码

连接表解决了**数据结构**问题，但没有解决**发现机制**：

- witness 仍是 `build_passage_store.py` 里的**硬编码字面量**
  （`FR_WITNESS` / `ZH_WITNESS` / 新增的 PDF witness）；
- **没有**「语料目录 → witness 自动发现」的机制；
- 新增一个 witness 仍须改代码并让生成循环知道该用哪个。

**这是 Phase 3 的事**，与连接表无关。

---

## 6. SQLite 投影

witness 也投影到机器层（`_index/passage_store.sqlite`）：

```sql
CREATE TABLE witnesses (
    id TEXT PRIMARY KEY, language TEXT, witness_kind TEXT,
    edition TEXT, authority_level TEXT, status TEXT,
    canonical INTEGER, source_file TEXT, source_file_sha256 TEXT
);
```

实测 `witnesses` 表 **3 行**（与 `witnesses.jsonl` 一致）。

连接表也投影（实测 **249,105 行**、6 列）：

```sql
CREATE TABLE passage_witnesses (
    passage_id TEXT, witness_id TEXT, link_role TEXT,
    authority_level TEXT, review_status TEXT, method TEXT
);
```

⚠️ 注意：连接表的 SQLite 版**比 JSONL 少一列**（JSONL 有 `schema_version`，
SQLite 没有）。这是投影的常规取舍，不影响边的语义。

### 6.1 ⚠️ 投影是有损的

SQLite 的 `witnesses` 表**没有** `provenance_note` 字段，
也没有 `text_role` / `source_state` / `translator` / `passage_link_state`。

含义：**机器层从 SQLite 取 witness 时会丢掉两类关键信息**：

| 丢掉的字段 | 承载的是什么 |
|---|---|
| `provenance_note` | STAFERLA 声明（§4）与 PDF witness 的「刻意未对齐」说明（§2.3） |
| `passage_link_state` | `not_linked` —— 「这份 witness 尚未连到 Passage」 |

**尤其第二项危险**：只看 SQLite 的人会看到 3 条 witness，却**看不到**
其中一条的段数（12,190）从未进入 `passages` 表 —— 由此可能误以为
该 witness 已被纳入检索范围。

这是一处**真实的信息降级**，值得在 Phase 3 修（把 `provenance_note`
与 `passage_link_state` 纳入 SQLite，或加 CHECK 约束要求存在）。

---

## 7. Witness vs Translation 的职责边界

两者容易混。实测区分如下：

| | Witness | Translation |
|---|---|---|
| 问题 | 「这是哪一版文本？」 | 「这段文本在库里扮什么语言角色？」 |
| 字段数 | 13（含 `witness_kind`/`text_role`/`source_state`/`provenance_note`） | 11 |
| 连接方式 | 被 `passage_witnesses` 连接表引用（多对多）；`passages.witness_id` 仍保留单值冗余 | 被 `passages.translation_id` 引用；`translations.witness_id` 指向 witness |
| 实测条数 | **3** | 2 |
| 一对多 | 一个 witness 可对应多条 translation；一个 passage 可有多个 witness 边 | — |

关系方向：**translation 挂在 witness 之下**
（`translations.witness_id` → `witnesses.id`）。
实测：`trans.zh.translation-project` → `witness.zh.translation-project`；
`trans.fr.staferla` → `witness.fr.staferla`。

⚠️ **注意不对称**：`translation` 只有 **2** 条，而 `witness` 有 **3** 条 ——
新增的 `witness.fr.seuil-pdf` **没有对应的 translation 记录**。
这是合理的（它是一条 `text_role: edition` 的版本抽取，不是翻译行为），
但意味着**不能假设「每个 witness 都有 translation」**。
遍历 witness 时要按 witness 表为准，不要用 translation 表反推 witness 集合。

详见 `TRANSLATION_MODEL.md`。

---

*配套：`TRANSLATION_MODEL.md` · `PASSAGE_MODEL.md` · `ALIGNMENT_MODEL.md`（为何两份法语 witness 未对齐） ·
`SOURCE_PROVENANCE.md`（Phase 1 §3 权威分层）*
