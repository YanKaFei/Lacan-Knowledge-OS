# PASSAGE_MODEL.md — Canonical Passage Model

> 版本 `1.0.0`　·　事实来源：`_data/passage_store/_build_meta.json`（`id_scheme` 与 `counts`）、
> `_data/passage_store/passages.jsonl`（249,105 条，逐行统计）、
> `_data/passage_store/passage_witnesses.jsonl`（249,105 条连接）、
> `00_System/Schemas/id-namespaces.json`（pattern 实测比对）、
> `_scripts/_tools/build_passage_store.py`、`_scripts/_tools/validate_vault.py`
> （`audit_passage_store()`）、`_scripts/_tools/render_vault.py`（分页逻辑）

---

## 1. 四级结构：Document → Seminar → Session → Passage

```
Document（逻辑文献，来自 Phase 1 inventory 的 document_id）
  └── Seminar        seminar.S<NN>            一期一行        28 条
        └── Session  session.S<NN>.<日期>[.L<NN>]  一课次一行   559 条
              └── Passage  passage.<session 前缀>.P<nnnn>  一段一行  249,105 条
```

**Passage 是最小引用证据单位。** 所有断言（Claim）、概念分期
（`concept_state`）、关系（relation）最终都必须落到一个 Passage 上；
页码、章节名、自由引述都不算证据。这一条是 Phase 1 `SOURCE_PROVENANCE.md`
定下的，Phase 2 把它做成了可机械检索的实体。

### 1.1 四级各自承载什么

| 级 | 承载 | 不承载 |
|---|---|---|
| Document | 物理文件与 sha256、逻辑归并（重复/分卷） | 文本内容 |
| Seminar | 期号、罗马数字、法/中标题、年份区间、课数、语言版本 | 具体段落 |
| Session | 课次（lesson）、日期与其精度、段数、语言集合 | 具体段落 |
| **Passage** | **原文文本、语言、角色、权威层级、溯源链、审核状态** | 概念、关系、断言（那些是上层实体） |

---

## 2. ID 规范（照抄实现）

来源：`_build_meta.json` → `id_scheme`，与 `build_passage_store.py`
的 `seminar_id()`（第 106–121 行）及两处 passage ID 生成（第 267、322 行）一致。

```jsonc
{
  "seminar": "seminar.S<NN>",
  "session": "session.S<NN>.<YYYY-MM-DD|YYYY-unknown|unknown>[.L<NN>]",
  "passage": "passage.S<NN>.<same as session>.<L<NN>>.P<nnnn>",
  "deterministic": true,
  "notes": "ID 不依赖时间/读取顺序/UUID/dict 迭代顺序；日期不可证时保留 unknown"
}
```

### 2.1 Seminar ID

`seminar_id()` 的规则：剥掉前导 `s`/`S`，正则 `^(\d+)([A-Za-z]?)$`，
数字**零填充到 2 位**，后缀大写：

| 源 `seminar` | 产出 ID |
|---|---|
| `s1` | `seminar.S01` |
| `s9` | `seminar.S09` |
| `s19` | `seminar.S19` |
| `s19b` | `seminar.S19B` |
| `s27` | `seminar.S27` |

**无法匹配正则时**（第 118–119 行）：不猜，原样大写并去掉非字母数字字符 ——
保留可追溯性优先于形态好看。

### 2.2 Session ID

`session.S<NN>.<日期段>[.L<NN>]`，其中日期段实际取三种形态：

| 形态 | 含义 | 实测是否出现 |
|---|---|---|
| `YYYY-MM-DD` | 精确课次日期 | ❌ 未出现（源数据无此信息） |
| `YYYY-unknown` | 只确证到年份 | ❌ 未出现（见 §3） |
| `unknown` | 完全未知 | ✅ **559 / 559 全部是这一种** |

课次后缀 `.L<NN>`：中译有 `lesson` 时加上（`L01`…`L27`），
法文转录无课次时不加（`build_passage_store.py` 第 263–264 vs 315–318 行）。

| 语言 | session ID 形态 | 实测段数 |
|---|---|---|
| 中译（有 lesson） | `session.S01.unknown.L01` | 82,578（全部带 `.L`） |
| 法语（无 lesson） | `session.S01.unknown` | 166,527（全部不带 `.L`） |

### 2.3 Passage ID

由 session ID 去掉 `session.` 前缀 + `.P<nnnn>`（4 位零填充）：

| 语言 | Passage ID 示例 |
|---|---|
| 中译 | `passage.S01.unknown.L01.P0001` |
| 法语 | `passage.S01.unknown.P0001` |

序号 `P<nnnn>` 是**该 session 内的出现序**（`sequence_in_session`），
按源文件读取顺序从 1 递增，零填充 4 位保证字典序 = 阅读序。

### 2.4 ✅ 已修正：`id_scheme.passage` 模板串不再有歧义

早期版本的 `id_scheme.passage` 写作 `passage.S<NN>.<same as session>.<L<NN>>.P<nnnn>`，
字面读会得出「`.L<NN>` 出现两次」。**现已改为**（实测 `_build_meta.json`）：

```
passage.S<NN>.<date>[\.L<NN>].P<nnnn>
```

方括号表示 `.L<NN>` 是**可选的一段**，只出现一次。对照：

| | 形态 |
|---|---|
| 中译（有课次） | `passage.S01.unknown.L01.P0001` |
| 法语（无课次） | `passage.S01.unknown.P0001` |

两者都符合修正后的模板串。**歧义已消除。**

### 2.5 分页 `.p<K>`：**是渲染层页码，不是 store 的 ID**

`session` 的 ID 规范允许 `.p<K>` 后缀（`id-namespaces.json` 的 session pattern
实测接受 `.p[0-9]{1,4}`）。用途：一节法语课的段落可达 **9,905 段**
（实测最大 `session.S05.unknown`），渲染成单个 Markdown 会过大，
故 `render_vault.py` 按 `--chunk`（默认 150）分页，每页需要**唯一** ID。

⚠️ **必须区分两件事**（已实测核对）：

| | 是否含 `.p<K>` | 证据 |
|---|---|---|
| **store 里的 `session_id` / passage `id`** | ❌ **不含** | 对 249,105 条 `passages.jsonl` 逐行正则扫描：含 `.p<K>` 的 passage id = **0**，含 `.p<K>` 的 session id = **0** |
| **渲染出的 Markdown 页的 id / 文件名** | ✅ 含 | `render_vault.py` 第 204、227 行 `"%s.p%d" % (s["id"], pi)`，且仅当页数 > 1 时才加 |

即：**分页是 `render_vault.py` 的渲染行为**，它**不改写 store 里的 ID**。
store 中一个 session 只有一行、一个 ID。

这样设计是对的：若把页码写进 store 的 ID，同一段的 ID 就会随
`--chunk` 取值变化 —— 直接违反 §5「ID 不得因重跑改变」。

> 因为默认 `chunk=150`、最大 session 有 9,905 段，**渲染时会**产生
> `session.S05.unknown.p1` … `p67` 这类页 ID。但**这些只存在于 vault 的
> Markdown 层**，不属于 Passage Store。

---

## 3. 日期不可确证时保留 `unknown`，禁止猜测

### 3.1 为什么源数据只能给 `unknown`

实测 `<HOME>` 的字段集合：

```
['chars', 'fr_title', 'lesson_numbers', 'lessons', 'roman', 'segments',
 'seminar', 'slug', 'year_from', 'year_to', 'zh_title']
```

**只有 `year_from` / `year_to`（年份区间），没有任何具体课次日期。**
中译 `segments.jsonl` 的字段是 `['file','id','lesson','roman','seminar','slug','text']`
—— 有 `lesson`（课次号）但**没有日期**。

因此：**能从源数据推出的最细粒度是「年份」，而连「哪一课对应哪一年」都无法确定。**

### 3.2 实现选择了比「年份」更保守的 `unknown`

`build_passage_store.py` 第 279–280、332–333 行把 `session_date` 与
`session_date_precision` 一律写成 `"unknown"`，而**不是**用 `year_from` 凑
`YYYY-unknown`。

这是一个**刻意的保守选择**，理由是：一期的 `year_from`–`year_to` 跨两年
（如 S1 是 1953–1954），把整期所有课次都标成 `1953-unknown` 会**把 1954 年的课错标成 1953**。
在无法确定某课属于哪一年时，`unknown` 是唯一诚实的值。

> 这与 `test_06_no_invented_metadata` 的立场一致：该测试显式**允许** `YYYY-unknown`
> （`session_date_precision == "year"`），但只要给了月日就必须有据。
> 实现目前比测试允许的更严格。

### 3.3 `session_date_precision` 三值

| 值 | 含义 | 出现条件 | 实测计数 |
|---|---|---|---|
| `exact` | 确证的课次日期 | 需要源数据有具体日期（当前没有） | **0** |
| `year` | 只确证到年份 | 配合 `YYYY-unknown` 形式；需能证明「该课属于该年」 | **0** |
| `unknown` | 完全未知 | 当前全部 | **249,105** |

⚠️ **实测**：`session_date_precision` 的取值分布是唯一的 `{"unknown": 249105}`。
`exact` 与 `year` 两个分支**在代码里没有生成路径**——它们是**为将来预留的枚举值**，
不是本阶段已实现的能力。

`test_01` 用一条硬约束锁住一致性：**ID 里写 `.unknown.` 的，`session_date`
与 `session_date_precision` 都必须是 `unknown`**。这条防止「ID 说不知道、字段却编了个日期」。

---

## 4. 为什么 `s19b` 独立成 `S19B`，不折叠进 S19

代码注释（`build_passage_store.py` 第 108–111 行）写得很直接：

> `s19b` 是语料里的一个**附加单元**（第十九期的一个 variant），
> 不是 s19 —— 必须保号且带后缀，不能把它折叠进 S19，
> 否则「28 期」这个口径会悄悄变成 27 期的某个重复。

实测两者的区别（`seminars.jsonl`）：

| | `seminar.S19` | `seminar.S19B` |
|---|---|---|
| 法文标题 | `…ou pire` | `Le savoir du psychanalyste` |
| 中文标题 | `……或更糟` | `分析家的知识` |
| 罗马数字 | `XIX` | `XIXb` |
| 年份 | 1971–1972 | 1971–1972 |
| 课数 | 12 | 7（`lesson_numbers` = 1…7） |
| 段数（`segments`） | 2,749 | 97 |
| 字符数（`chars`） | 124,033 | 188,567 |
| session 数 | 13 | 8 |
| passage 数 | 6,418 | 3,204 |

> 注意二者**年份区间完全相同**（1971–1972）—— 所以年份无法用来区分它们，
> 后缀是唯一区分手段。另一处反常：S19B 的 `segments` 只有 97，
> 却声明 `chars` 188,567（S19 是 2,749 段 / 124,033 字符）。
> 这个不一致来自上游 `seminars.json`，**本阶段未追查**，仅记录。

**折叠会造成的具体损害**：S19 与 S19B 各有独立课次编号（S19B 是 1–7），
折叠后 `session.S19.unknown.L01` 会同时指代两个不同的课，
Passage ID 直接冲突 —— 而 ID 冲突意味着**引用不再可靠**，这是本库的底线。

**代价**：`seminar` 计数器变成 28，严格说是「27 期 + 1 个附加单元」。
文档口径统一写作「28 个 seminar 单元」以免误读。

---

## 5. ID 稳定性：不得因重跑改变

### 5.1 确定性来源

ID **不依赖**：墙上时间、文件系统读取顺序、UUID、dict 迭代顺序。
实现手段：所有 JSONL 写出前都排序（`passages.sort(key=lambda p: p["id"])`，
第 389 行；`sessions`/`seminars` 按 id 排序，第 390–391 行），
ID 只由 `seminar`/`lesson`/`sequence_in_session` 决定。

### 5.2 契约（有测试）

`test_phase2_passage_store.py::test_02_ids_stable_across_rebuild`：
重建后 Passage ID **序列逐字相同**。

### 5.3 重新切分时的规则

> **新段追加序号，不重排旧序号。**

即：若将来把某 session 切得更细，`P0001`…`P0100` 的含义**不得改变**，
新段从 `P0101` 起追加。反向做（重排）会让所有历史引用指向错误的文本 ——
那比 ID 变长糟糕得多。

**注意**：本阶段**没有做重新切分**（sequence 就是源文件行序）。
这条规则是给 Phase 3+ 的约束，不是已完成的行为。

---

## 6. Passage 完整字段表

**28 个字段，全部实际写出**（实测 `passages.jsonl` 每条记录的键集合，
中法语一致，无差异）。来源：`build_passage_store.py` 第 271–299（fr）
与 324–355（zh）行的字典字面量。

| # | 字段 | 类型 | 说明 | 实测取值 |
|---|---|---|---|---|
| 1 | `id` | string | Passage ID | `passage.S01.unknown.L01.P0001` |
| 2 | `type` | string | 固定 `"passage"` | `passage` |
| 3 | `session_id` | string | 所属 session | `session.S01.unknown.L01` |
| 4 | `seminar_id` | string | 所属 seminar | `seminar.S01` |
| 5 | `language` | string | `zh` / `fr` | `zh` |
| 6 | `witness_id` | string | 具体文本版本（**冗余单值**；权威连接已移到 `passage_witnesses` 表，见 `WITNESS_MODEL.md` §5.3） | `witness.zh.translation-project` |
| 7 | `translation_id` | string | 语言角色 | `trans.zh.translation-project` |
| 8 | `text_role` | string | `translation` / `transcription` | `translation` |
| 9 | `authority_level` | string | L1 / L2 | `L2`（zh）/ `L1`（fr） |
| 10 | `lesson` | int \| null | 课次号；法语无 → null | `1`（zh）/ `null`（fr） |
| 11 | `sequence_in_session` | int | session 内出现序（= ID 的 P 号） | `1` |
| 12 | `session_date` | string | 日期或 `unknown` | `unknown` |
| 13 | `session_date_precision` | string | `exact`/`year`/`unknown` | `unknown` |
| 14 | `year_from` | int | 该期起始年 | `1953` |
| 15 | `year_to` | int | 该期结束年 | `1954` |
| 16 | `source_file_relpath` | string | **仅中译有**：源文件内相对路径 | `translation/Leçon-01.md` |
| 17 | `raw_text` | string | 原文（**未经任何改动**） | — |
| 18 | `normalized_text` | string | 归一化文本 | 本阶段 == `raw_text` |
| 19 | `normalization_operations` | array | 归一化操作清单 | `[]` |
| 20 | `review_status` | string | 审核状态 | `candidate` |
| 21 | `status` | string | 生命周期 | `recovered` |
| 22 | `canonical` | bool | 是否定本 | `false` |
| 23 | `source_state` | string | **仅中译有**：上游状态 | `upstream_missing` |
| 24 | `provenance` | object | 溯源元组（7 子字段） | 见 §7 |
| 25 | `trace_status` | string | `COMPLETE` / `SOURCE_TRACE_INCOMPLETE` | `SOURCE_TRACE_INCOMPLETE` |
| 26 | `trace_missing` | array \| null | 缺哪几环 | `["logical_document"]` |
| 27 | `generated_by` | string | 生成者 | `script:build_passage_store.py` |
| 28 | `schema_version` | string | 模式版本 | `1.0.0` |

### 6.1 语言间字段差异（实测）

| 字段 | 中译 | 法语 |
|---|---|---|
| `lesson` | 恒为整数（82,578/82,578 非空） | 恒为 `null`（166,527/166,527） |
| `source_file_relpath` | 有（`translation/Leçon-NN.md`） | **无** |
| `source_state` | 有（`upstream_missing`） | **无** |
| `session_date` / `precision` | 均 `unknown` | 均 `unknown` |
| `authority_level` | `L2` | `L1` |

> `source_file_relpath` 与 `source_state` 是**语言不对称**字段：
> 它们记录「上游是否还在」。中译上游目录已消失故需要标记，
> 法语转录上游仍在故不加。这不是遗漏。

### 6.2 `normalized_text` 与无损性

**实测**：`raw_text != normalized_text` 的记录数 = **0**（249,105 条全部相等），
且 `normalization_operations` 全为 `[]`，`normalized_text` 无一条为空。

含义：**本阶段没有做任何归一化**。这满足 §七「无损」要求 ——
原文完整保留在 `raw_text`，且「改了什么」有显式的空清单可解释
（空数组 = 文本未被改动，而不是「忘了记」）。

将来加归一化时，必须同时写入 `normalization_operations`，
否则 `normalized_text` 与 `raw_text` 的差异将不可解释 —— 这会破坏可追溯性。

---

## 7. 溯源元组（`provenance`）

7 个子字段（`build_passage_store.py` 第 233–253 行的 `provenance()`）：

| 子字段 | 含义 | 实测（当前） |
|---|---|---|
| `source_segment_id` | 源段号（如 `s1-01-0001`） | ✅ 有值 |
| `source_file` | 源 JSONL 文件名 | `segments.jsonl` / `french_staferla.jsonl` |
| `source_file_sha256` | 源 JSONL 的 sha256 | ✅ 有值 |
| `document_id` | 逻辑文档 id（来自 inventory） | ❌ **null** |
| `physical_file` | 物理文件相对路径 | ❌ **null** |
| `physical_sha256` | 物理文件 sha256 | 回退为 `source_file_sha256` |
| `segment_sha256` | 该段 `raw_text` 的 sha256 | ✅ 实测 249,105/249,105 与 `raw_text` 一致 |

### 7.1 断链在哪一环，为什么

`trace_missing` 实测分布：`{('zh','logical_document'): 82578, ('fr','logical_document'): 166527}`
—— **全部 249,105 段都缺 `logical_document`**。

**根因**（已独立复现）：`load_inventory_by_hash()` 把 `corpus_inventory.json` 建成
`sha256 → 文档` 的映射，然后拿 atlas 源文件的 sha256 去查。
但实测两个 hash **都不在 inventory 里**：

```
segments.jsonl(zh)          hash 在 corpus_inventory 里吗 -> False
french_staferla.jsonl(fr)   hash 在 corpus_inventory 里吗 -> False
```

原因：`corpus_inventory.json` 扫描的是 `<HOME>`
（143 个原始件），而这两个 atlas `.jsonl` 住在 `.lacan-build/atlas/` ——
**根本不在 inventory 的扫描范围内**。

因此 `document_id` / `physical_file` 解析不出，`physical_sha256` 回退成
源 JSONL 的 hash，`trace_status` 一律 `SOURCE_TRACE_INCOMPLETE`。

> **这是诚实的行为，不是 bug**：闭合不了就标 INCOMPLETE 并写明缺哪一环，
> 而不是假装闭合。但它也意味着 **Phase 2 的溯源链只到 Level 1（源段号 + sha256），
> 到不了逻辑文档层**。要闭合，需要把 `.lacan-build/atlas/` 纳入 inventory
> 或建立 atlas 文件 → document 的映射。见 `CORPUS_INTEGRATION_REPORT.md`。

---

## 8. 与 Phase 1 ID 体系的关系（✅ 已收敛）

早期版本里，Phase 2 生成的 ID **全部不匹配** Phase 1
`00_System/Schemas/id-namespaces.json` 的 pattern，而 `validate_vault.py`
也不校验 passage store —— 两套 ID 规范分叉且**无检查发现**。

**现在两侧都已收敛。** 实测 `id-namespaces.json` 当前 pattern：

| type | 当前 pattern（实测） | Phase 2 产出 | 匹配 |
|---|---|---|---|
| seminar | `^seminar\.[sS](?:0[1-9]\|[12][0-9])(?:[A-Za-z])?$` | `seminar.S01`、`seminar.S19B` | ✅ |
| session | `^session\.[sS](?:0[1-9]\|[12][0-9])(?:[A-Za-z])?\.(?:[0-9]{4}-(?:[0-9]{2}-[0-9]{2}\|unknown)\|unknown)(?:\.L[0-9]{2,3})?(?:\.p[0-9]{1,4})?$` | `session.S01.unknown`、`session.S01.unknown.L01`、`session.S01.unknown.p3` | ✅ 三者皆通过 |
| passage | `^passage\.[sS](?:0[1-9]\|[12][0-9])(?:[A-Za-z])?\.(?:[0-9]{4}-(?:[0-9]{2}-[0-9]{2}\|unknown)\|unknown)(?:\.L[0-9]{2,3})?\.P[0-9]{4}$` | `passage.S01.unknown.P0001`、`passage.S01.unknown.L01.P0001` | ✅ |

关键变化：pattern 现在接受 **零填充 `S<NN>`**（`S01`）、**`S19B` 字母后缀**、
**裸 `unknown` 日期段**、**`.L<NN>` 课次后缀**、**`.p<K>` 分页后缀**。

### 8.1 ✅ `validate_vault.py` 现在**校验** passage store

新增了 `audit_passage_store()`（`_scripts/_tools/validate_vault.py` 第 306 行起），
在报告里产出 `report["passage_store"]`，含 **7 项检查**：

| # | 检查 | 防的是哪个坑 |
|---|---|---|
| 1 | 计数守恒（zh 82,578 / fr 166,527 / 合 249,105） | 段数悄悄缩水 |
| 2 | ID 唯一 | 引用歧义 |
| 3 | **ID 命中 `id-namespaces.json` 的 pattern** | **本 §8 描述的两套规范分叉** |
| 4 | 溯源自洽（`SOURCE_TRACE_INCOMPLETE` 必须写明缺哪一环） | 静默断链 |
| 5 | 无损（`raw_text == normalized_text` 时 `operations` 必须为空） | 不可解释的文本改动 |
| 6 | `passage_witnesses` 连接表的引用必须存在 | 悬空边 |
| 7 | 未闭合的 translation 不得是 canonical | 无据升格 |

**实测输出**（截至本文档同步时）：

```
passage_store.present = True
counts = {"passages": 249105, "unique_ids": 249105,
          "by_language": {"zh": 82578, "fr": 166527},
          "passage_witness_links": 249105}
errors = []      warnings = []
```

即 **passage store 校验 0 error / 0 warning**。
（注意：`validate_vault.py` 整体此时仍报 2 个 error，但**不在 passage store**，
而在 `_data/relations/` 的 fixture 引用了不存在的 Passage —— 见 §8.2。）

### 8.2 ⚠️ 仍未解决的一处不一致：Phase 1 fixture 的 relation 证据指向旧式 ID

虽然 ID 规范已收敛，但 **Phase 1 的 fixture 数据仍写着已不存在的 ID**。
实测 `validate_vault.py` 报：

```
ERR SOURCE_TRACE_INCOMPLETE | evidence.passage_id 指向不存在的实体：
                              passage.S03.1955-unknown.L01.P0010
```

问题：`passage.S03.1955-unknown.L01.P0010` 是**旧式**写法
（`1955-unknown` 年份段 + `.L01`），而 Phase 2 实际产出的是
`passage.S03.unknown.L01.P0010`（裸 `unknown`）。

**根因**：Phase 1 建 fixture 时，ID 规范尚未与 Phase 2 对齐；
现在 pattern 放宽了，但**已写入的数据没跟着改**。

**影响**：`validate_vault.py` 报 2 个 error（同一条被引两次）。
**本文件不擅自修数据**（用户要求：只改文档）。需在 `_data/relations/*.jsonl`
里把该 ID 改为实际存在的形态，或改为其他真实 Passage。

---

*配套：`PHASE2_ARCHITECTURE.md` · `WITNESS_MODEL.md` · `SOURCE_PROVENANCE.md`（Phase 1） ·
`ENTITY_MODEL.md`（Phase 1）*
