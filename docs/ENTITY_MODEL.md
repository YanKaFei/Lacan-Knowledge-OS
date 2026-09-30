# ENTITY_MODEL.md — 实体模型与稳定 ID

> 版本 `1.0.0`　·　配套契约：`00_System/Schemas/knowledge.schema.json`、`id-namespaces.json`

---

## 1. 为什么需要「稳定 ID」

系统里所有的可追溯性最终都压在 ID 上：

```
AI 结论 → Claim → Passage → Session → Document/Seminar → Edition → Original Source
```

这条链每一跳都是 ID 引用。**只要 ID 会变，链条就会断**，而断了以后
无法区分「本来就没有出处」和「出处丢了」——这正是要禁止的
把无法验证的内容伪装成来源事实。

因此 ID 是**设计产物**，不是实现细节。

---

## 2. ID 语法（强制）

```
<namespace>.<slug>[.<slug>...]
```

| 规则 | 说明 |
|---|---|
| 字符集 | 段与段之间用 `.`；首段小写，**后续段允许大写**（承载 `S11` / `P001` / `S-barre` 等拉康记法） |
| 每段 | 必须 `[a-z0-9]` 开头，长度 ≥ 1 |
| 总长 | 3–120 字符 |
| 正则 | `^[a-z][a-z0-9-]*(\.[A-Za-z0-9][A-Za-z0-9-]*)+$` |
| 禁止 | 空格、下划线、中文、路径分隔符、`.` 结尾（首段不得大写） |

**为什么不用中文 ID**：filesystem / URL / Obsidian 别名 / 未来的 MCP 参数
全都要传它。中文 ID 在跨工具链时会持续产生编码与规范化问题
（`é` 的 NFC/NFD 差异已经在本项目的实际文件名里出现过）。
中文只出现在 `title` / `canonical_name` / `aliases`。

---

## 3. 24 个实体类型与命名空间

| # | type | 命名空间 | ID 形如 | 目录 |
|---|---|---|---|---|
| 1 | `source` | `source.` | `source.local.desktop-lacan` | `01_Sources/` |
| 2 | `document` | `doc.` | `doc.lacan.seminar-11` | `01_Sources/Documents/` |
| 3 | `seminar` | `seminar.` | `seminar.S11` | `02_Lacan_Seminars/` |
| 4 | `session` | `session.` | `session.S11.1964-02-12` | `02_Lacan_Seminars/` |
| 5 | `passage` | `passage.` | `passage.S11.1964-02-12.P001` | 随 Session |
| 6 | `concept` | `concept.` | `concept.objet-a` | `04_Concepts/` |
| 7 | `concept_state` | `state.` | `state.objet-a.1964-1966` | `04_Concepts/States/` |
| 8 | `term` | `term.` | `term.fr.jouissance` | `05_Terminology/` |
| 9 | `translation` | `trans.` | `trans.fr-to-zh.jouissance` | `05_Terminology/Alignments/` |
| 10 | `person` | `person.` | `person.jacques-lacan` | `11_Thinkers/` |
| 11 | `philosopher` | `philosopher.` | `philosopher.hegel` | `11_Thinkers/Philosophers/` |
| 12 | `psychoanalyst` | `person.` | `person.jacques-alain-miller` | `11_Thinkers/Psychoanalysts/` |
| 13 | `case` | `case.` | `case.schreber` | `07_Cases/` |
| 14 | `clinical_structure` | `structure.` | `structure.psychosis` | `06_Clinical/Structures/` |
| 15 | `matheme` | `matheme.` | `matheme.S-barre` | `08_Topology_Mathemes/Mathemes/` |
| 16 | `topology` | `topology.` | `topology.mobius-strip` | `08_Topology_Mathemes/Topology/` |
| 17 | `formula` | `formula.` | `formula.fantasy.S-diamond-a` | `08_Topology_Mathemes/Formulas/` |
| 18 | `discourse` | `discourse.` | `discourse.analyst` | `08_Topology_Mathemes/Discourses/` |
| 19 | `school` | `school.` | `school.ecole-de-la-cause-freudienne` | `12_Schools_Debates/Schools/` |
| 20 | `debate` | `debate.` | `debate.ordinary-psychosis` | `12_Schools_Debates/Debates/` |
| 21 | `reading_note` | `note.` | `note.2011-wu-qiong-reading` | `13_Reading_Notes/` |
| 22 | `synthesis` | `synth.` | `synth.real-across-periods` | `14_Synthesis/` |
| 23 | `question` | `q.` | `q.status-of-ordinary-psychosis` | `15_Questions/` |
| 24 | `research_project` | `project.` | `project.ordinary-psychosis` | `16_Research_Projects/` |

**特殊命名空间（非 Markdown 节点，但同样需要 ID）**

| 用途 | 命名空间 | 形如 |
|---|---|---|
| 逻辑文献（一个作品，跨版本跨分卷） | `work.` | `work.lacan.seminar-23` |
| 具体版本 | `edition.` | `edition.seminar-23.seuil-fr` |

> `work` / `edition` 在 Phase 1 先以 ID 形态确定（因为重复检测与分卷合并必须
> 依赖它们），其完整节点类型在 Phase 2 落地时并入 schema。

---

## 4. ID 分配规则

### 4.1 用 slug 而不是哈希

ID 必须**人类可读且可从内容反推**。因此：

- 概念用**法语原词的 slug**：`concept.objet-a`、`concept.jouissance`、
  `concept.nom-du-pere`、`concept.sinthome`。
  原因是法语是底本语言，中文译名分歧大（对象a / 对象小a / 小对形），
  用中文做 ID 会让别名归并变得不可能。
- 研讨班用期号：`seminar.S11`（不用标题，因为标题有法/英/中三种写法）。
- Session 用**日期**：`session.S11.1964-02-12`。
  日期是唯一跨语言不变量；用「第 5 课」会因版本不同而错位。
- Passage 用 `session_id` + 页内序号 `P001`。

### 4.2 数值型 slug 的补零

`P001` 补零到 3 位，保证字典序 = 阅读序（`P001 < P002 < P010`）。
研讨班期号**不补零**（`S1`…`S27`），因为它不参与字符串排序。

### 4.3 变音符号归一化（实测踩过的坑）

实测语料里有 **12 个文件名不是 NFC**，例如 `Repe\u0300res pour la psychose ordinaire…`
（`e` + U+0300 组合抑音符）与它的 NFC 形式 `Repères…`、`Gae\u0308tan Gatian de Cle\u0301rambault…`、`Traite\u0301 des hallucination…`。
注意：`Repe\u0300res`（组合抑音符）与 `Rêpes`（抑扬符）**不是同一个字符**，不构成编码变体 ——
这正是本节要警告的那类错误，别把不同字符当成同一个字的两种写法。
ID 生成必须先做 `unicodedata.normalize("NFKC", s)`，再去掉变音符号
（`é`→`e`），再做 slug 化。**否则同一个概念会产生两个 ID**
（这正是 `test_inventory` 里同名归一化要处理的问题）。

### 4.4 ID 一经发布永不更改

- 改名只能改 `title` / `canonical_name`。
- 确需废弃时，保留节点、把 `status` 设为 `deprecated`，并用
  `relation: redefines` 指向新 ID。**不删除、不复用。**

---

## 4.5 文件名必须等于 ID（硬不变量）

> **每个知识节点的文件名（去掉 `.md`）必须与它的 `id` 完全一致。**

理由：Obsidian 的 `[[wikilink]]` 解析是**按文件名**的。如果文件名与 ID 不一致，
`[[seminar.S3]]` 这种以 ID 为目标的链接就会断——读者点不开，Graph View 里也会
出现孤点。这条不是风格偏好，是可点击性的前提。

实测踩过的坑（本轮真实发生）：

| 文件名（错） | id | 后果 |
|---|---|---|
| `analyst.jacques-lacan.md` | `person.jacques-lacan` | 所有指向 `[[person.jacques-lacan]]` 的链接全断 |
| `session.S3-unknown.md` | `session.S3.1955-unknown` | 同上（已修；日期未定的 session 用 `<year>-unknown` 形态） |

因此 `validate_vault.py` 把 `文件名 ≠ id` 判为 **error**（而非 warning）。

**连带好处**：文件名即 ID，意味着「用 grep 找文件」与「用 ID 找实体」是同一个操作，
Agent 端不需要额外索引就能定位节点。

---

## 4.6 日期未定时的 ID 写法

真实语料里有的文本只到「页」级，课次日期无法确证（例如本地 `S3 PSYCHOSES.pdf`
没有课次分隔与日期题头）。此时**不得编造日期来凑规范 ID**，改用：

```
session.S3.1955-unknown              # 年份已知，具体课次未定
passage.S3.1955-unknown.P010         # 页锚 P010，日期段与 session 一致
```

配套 frontmatter：

```yaml
session_date: 1955-01-01          # 只精确到年，取该年 01-01
session_date_precision: year      # exact | year | unknown
trace_status: SOURCE_TRACE_INCOMPLETE
```

`session_date_precision` 是**必读字段**：没有它，`1955-01-01` 会被下游
误当成「1955 年 1 月 1 日那一课」。有了它，系统能明确表达
「我知道它出自 S3、且在这一年，但不知道哪一课」。

---

## 5. 去重规则

ID 唯一性不等于实体唯一性。两个不同 ID 可能指同一个东西，
去重靠 `canonical_name` + `aliases` + 人工判定：

| 步骤 | 规则 | 自动化程度 |
|---|---|---|
| 1 | 同 type 内 `canonical_name` 必须唯一 | 校验器强制（错误） |
| 2 | 归一化后的 `canonical_name` 碰撞 → 警告 | 校验器（警告） |
| 3 | `aliases` 与另一个节点的 `canonical_name` 相同 → 提示合并 | 校验器（提示） |
| 4 | 合并动作只能由人执行，且必须留下 `supersedes` 关系 | 人工 |

**AI 可以做**：建议 alias、建议「这两个可能是同一个概念」。
**AI 不可以做**：自动合并两个 `concept`，或自动把某个建议写进 `canonical`。

---

## 6. 概念的两层结构（本模型的核心）

```
concept.objet-a
  id:              concept.objet-a
  type:            concept
  canonical_name:  objet petit a
  aliases:         [对象 a, 对象小a, 小对形, objet a, the object a]
  fr:              objet petit a
  en:              object petit a
  zh:              对象 a
  concept_states:  [state.objet-a.1953-1955,
                    state.objet-a.1964-1966,
                    state.objet-a.1967-1971,
                    state.objet-a.1972-1973]
  ← 注意：这里**没有** definition 字段。本体不承载定义。
```

```
state.objet-a.1964-1966
  id:            state.objet-a.1964-1966
  type:          concept_state
  concept_id:    concept.objet-a
  period:        1964-1966
  state_label:   a 作为欲望的原因，与「阉割」「缺失」绑定
  passages:      [passage.S11.1964-02-12.P007, ...]   ← 必须有证据
  sources:       [doc.lacan.seminar-11]
  supersedes:    state.objet-a.1953-1955      ← 显式表达改写
```

**schema 层面的强制**：

- `type: concept` → `required: [concept_states, canonical_name, aliases]`
- `type: concept_state` → `required: [concept_id, period, passages, sources]`
- `period` 是枚举，不允许自由文本（否则「分期」就失去可比性）

**为什么这能防住「合并成一句通顺的话」**：本体里没有定义字段，
所以「补全这张卡」只能去写某一个 `concept_state`，而每个 state 都绑定
一个具体的 `period` 和具体的 `passage`。想要一句跨时期的总结，
就必须新建一个 `synthesis`（L4），而 L4 永远不能变成 canonical。

---

## 7. Passage ID 与结构路径

```
passage.S11.1964-02-12.P007
        └┬─┘ └───┬────┘ └┬─┘
     seminar   session   页内/结构内序号
```

配套字段：

```yaml
id:             passage.S11.1964-02-12.P007
type:           passage
seminar:        S11
session_date:   1964-02-12
source_id:      doc.lacan.seminar-11
structure_path: S11/1964-02-12/section-03/para-07
page_from:      23
page_to:        23
paragraph_index: 7
```

- `structure_path` 承载 `Document→Seminar→Session→Section→Paragraph` 全路径。
- **重新切分时 ID 不变**：即使段落边界调整，只要语义单元仍属同一 Session，
  ID 保持稳定；新增段落追加新序号，不重排旧序号。
- 跨语言版本通过 `aligns_with` 指向**同一个 Passage 的其他语言 rendition**。

---

## 8. 关系中的 ID 引用

关系记录（见 RELATION_MODEL.md）的 `subject` / `object` 都是上述 ID。
校验器必须检查：

1. `subject` / `object` 必须能在 vault 中找到对应节点（否则 `BROKEN_RELATION`）。
2. `subject` 与 `object` 不得相同（自环，除非谓词显式允许，目前都不允许）。
3. `evidence.passage_id` 里的每个 Passage 必须存在（否则
   `SOURCE_TRACE_INCOMPLETE`）。
4. `predicate` 必须在 17 个枚举值内。

---

## 9. 实测：当前语料会产出哪些实体（Phase 2 预估）

基于 `_data/corpus_inventory.json` 的实测数据推算：

| 实体类型 | 预计数量 | 依据 |
|---|---|---|
| `source` | 3–5 | 本机桌面、lacan.com、未来 GitHub |
| `document` | 90–100 | 143 个文件归并掉 4 组字节级重复 + 5 组同书分卷后 |
| `seminar` | 6（当前）/ 27（目标） | 实测识别出 S1/S3/S5/S10/S20/S23 |
| `session` | 100+ | 仅 S20/S23 中英对照本就有大量课次 |
| `concept` | 100–200 | 取决于 Phase 2 术语表 |
| `term` | 300–600 | 三语术语 |
| `passage` | 10⁴–10⁵ | 结构性切分后 |

> 分卷合并的实测例子：`Lacan on Psychosis…part-01-pages-1-104.pdf` 与
> `part-02-pages-105-207.pdf` 在物理上是两个文件，逻辑上是**一个 `document`**。
> 架构要求 `document` 层合并、物理文件不动。

---

*配套：`id-namespaces.json`（机器可读）、`RELATION_MODEL.md`（关系）、
`KNOWLEDGE_SCHEMA.md`（字段）*
