# KNOWLEDGE_SCHEMA.md — YAML Frontmatter 字段契约

> 版本 `1.0.0`　·　机器可读契约：`00_System/Schemas/knowledge.schema.json`（JSON Schema Draft 2020-12）

---

## 1. 字段集合是封闭的

`knowledge.schema.json` 顶层设 `additionalProperties: false`。
**任何不在下表中的字段都会让校验失败。**

设计意图：字段失控是知识库长期腐化的主要形式——今天加 `my_note`，
明天加 `temp_source`，一年后没人知道哪些字段有语义。
所以新增字段必须走流程：

1. 改 `knowledge.schema.json`
2. 提升 `schema_version`（语义化版本）
3. 在 `00_System/Schemas/CHANGELOG.md` 记录：为什么加、谁加的、旧节点如何迁移

---

## 2. 必需字段（13 个）

每个知识节点都必须有：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 稳定 ID，正则 `^[a-z][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)+$` |
| `type` | enum | 24 个实体类型之一（见 ENTITY_MODEL.md） |
| `title` | string | 人类可读标题（可中文） |
| `canonical_name` | string | 规范名，同 type 内唯一，用于去重 |
| `aliases` | string[] | 别名 / 异译 / 跨语言写法 |
| `language` | enum | `zh`/`en`/`fr`/`de`/`la`/`grc`/`ru`/`und`/`mul` |
| `authority_level` | enum | `L0`–`L4` |
| `review_status` | enum | `candidate`/`needs_review`/`reviewed`/`canonical`/`rejected` |
| `status` | enum | `stub`/`draft`/`active`/`needs_update`/`archived`/`deprecated` |
| `generated_by` | string | `human:<name>` / `ai:<model>/<run>` / `script:<name>@<ver>` |
| `created_at` | string | ISO 8601 datetime |
| `updated_at` | string | ISO 8601 datetime |
| `schema_version` | string | 语义化版本 `^\d+\.\d+\.\d+$` |

**`generated_by` 为什么是必填**：它是区分「人写的」和「AI 写的」的
**唯一机械判据**。没有它，未来就无法批量审计 AI 内容的边界。

---

## 3. 可选字段（按用途分组）

### 3.1 来源与溯源

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_type` | string | 来源种类（本机 / 网站 / GitHub / 个人笔记…） |
| `source_id` | stable_id | 指向 `source` 实体 |
| `source_url` | uri | 原始 URL |
| `source_hash` | sha256 | **对应源文件的 sha256**，用于证明「这段内容确实来自那个文件」 |
| `source_path` | string | 原始路径（如 `<HOME>`） |
| `sources` | stable_id[] | 依据的 Source/Document 列表 |
| `passages` | stable_id[] | 依据的 Passage 列表 |
| `trace_status` | enum | `COMPLETE`/`SOURCE_TRACE_INCOMPLETE`/`NOT_APPLICABLE` |
| `confidence` | number 0–1 | 把握程度 |

`source_hash` 是**防篡改锚点**：源文件一旦变化，hash 不匹配即可发现
「这条知识与它声称的出处已经对不上了」。实测中 143 个文件全部已算出
sha256，可直接用于此字段。

### 3.2 文献结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `seminar` | `^S([1-9]\|1[0-9]\|2[0-7])$` | 研讨班期号 |
| `session_date` | `YYYY-MM-DD` | 课次日期 |
| `structure_path` | string | `Document→Seminar→Session→Section→Paragraph` 路径 |
| `paragraph_index` | integer | 段内序号 |
| `page_from` / `page_to` | integer\|null | 页码 |
| `edition` | string | 版本（如 `Seuil 1973` / `商务印书馆 2021`） |
| `translator` | string | 译者 |
| `publisher` | string | 出版社 |
| `publication_year` | integer 1800–2100 | 出版年 |

### 3.3 概念史

| 字段 | 类型 | 说明 |
|---|---|---|
| `period` | enum | 分期，见 §4 |
| `period_label` | string | 时期的人类可读标签 |
| `concept_states` | stable_id[] | **仅 `type: concept`**：指向各阶段 State |
| `concept_id` | stable_id | **仅 `type: concept_state`**：所属概念本体 |
| `state_label` | string | **仅 `type: concept_state`**：该阶段的表述 |
| `supersedes` | stable_id | **仅 `type: concept_state`**：被本阶段改写的 State |

### 3.4 语言与翻译

| 字段 | 类型 | 说明 |
|---|---|---|
| `fr` / `en` / `zh` | string | 三语写法 |
| `aligns_with` | stable_id[] | **仅 `translation`/`passage`**：跨语言对齐目标 |

### 3.5 审核与组织

| 字段 | 类型 | 说明 |
|---|---|---|
| `reviewed_by` | string | 审核人 |
| `reviewed_at` | datetime | 审核时间 |
| `tags` | string[] | Obsidian 标签 |
| `related` | string[] | wikilink 目标列表 |

---

## 4. `period` 分期枚举

拉康理论分期不采用「早期/中期/晚期」这种三分——太粗，会把
1964 的转折和 1972 的转折压平。采用与研讨班年代对齐的八段：

| 值 | 覆盖 | 标志性事件 |
|---|---|---|
| `pre-1953` | –1953 | 精神病学时期、《论精神病与人格的关系》 |
| `1953-1955` | 1953–1955 | 罗马报告、《言语与语言的功能》、S1–S2 |
| `1955-1958` | 1955–1958 | S3 精神病、S4 对象关系、S5 无意识的形成 |
| `1959-1963` | 1959–1963 | S7 伦理学、S8 移情、S10 焦虑 |
| `1964-1966` | 1964–1966 | **S11 四个基本概念**（转折）、S12、S13 |
| `1967-1971` | 1967–1971 | S14–S18、对象 a 的形式化、四种话语（S17） |
| `1972-1973` | 1972–1973 | **S20 Encore**、S21、性分化公式 |
| `1974-1976` | 1974–1976 | **S23 圣状**、S24、S25、RSI 与波罗米结 |
| `1976-1981` | 1976–1981 | 晚期、S26–S27、结的拓扑 |

未来若确需更细分期，**必须新增枚举值而不是改用自由文本**——
自由文本会让「按时期检索」失去可比性。

---

## 5. `review_status` 状态机

```
candidate ──→ needs_review ──→ reviewed ──→ canonical
    │              │              │            │
    └──────────────┴──────────────┴────────────┴──→ rejected
```

| 状态 | 含义 | 谁可以写 |
|---|---|---|
| `candidate` | AI 或脚本产生，未经人看 | AI / 脚本 |
| `needs_review` | 已进入审核队列 | AI / 脚本 / 人 |
| `reviewed` | 人已核对内容 | **仅人** |
| `canonical` | 馆藏定本 | **仅人** |
| `rejected` | 明确否决（保留理由防反复提出） | 人 |

**硬规则（schema + 校验器双重强制）**

1. `authority_level: L4` 的节点，`review_status` **不得为 `canonical`**。
2. `review_status` ∈ {`reviewed`, `canonical`} 时，`reviewed_by` 必填。
3. 状态只能单向推进（除 → `rejected`）；回退需人工显式操作并留记录。

---

## 6. 类型专属强制字段（JSON Schema `allOf` 条件）

| 当 `type` 是 | 额外必须包含 |
|---|---|
| `passage` | `seminar`, `session_date`, `source_id`, `structure_path`, `page_from`, `page_to` |
| `session` | `seminar`, `session_date` |
| `seminar` | `seminar` |
| `concept` | `concept_states`, `canonical_name`, `aliases` |
| `concept_state` | `concept_id`, `period`, `passages`, `sources` |
| `synthesis` | `trace_status`, `sources`, `passages`（且 `authority_level` 被**强制为 `L4`**） |
| `source` | `source_type` |

`synthesis` 那条是架构里最硬的一处约束：**AI 综合在结构上不可能
被标成 L1/L2**，因为 schema 会把 `authority_level` 覆写为常量 `L4`。

---

## 7. 完整示例

### 7.1 概念本体（注意：没有 definition）

```yaml
---
id: concept.objet-a
type: concept
title: objet petit a（对象 a）
canonical_name: objet petit a
aliases: [对象 a, 对象小a, 小对形, objet a, the object a, l'objet a]
language: mul
fr: objet petit a
en: object petit a
zh: 对象 a
authority_level: L2
review_status: reviewed
status: active
reviewed_by: human:coffee
reviewed_at: "2026-09-20T00:00:00Z"
generated_by: human:coffee
concept_states:
  - state.objet-a.1953-1955
  - state.objet-a.1964-1966
  - state.objet-a.1972-1973
related: [concept.desir, concept.fantasma, topology.mobius-strip]   # frontmatter 里不带 [[ ]]，正文里才用
tags: [概念/对象a, 领域/拓扑]
created_at: "2026-09-20T00:00:00Z"
updated_at: "2026-09-20T00:00:00Z"
schema_version: 1.0.0
---
```

### 7.2 概念阶段状态（定义在这里）

```yaml
---
id: state.objet-a.1964-1966
type: concept_state
title: objet a — 1964–1966：作为欲望的原因
canonical_name: objet a (1964-1966)
aliases: [对象a 1964]
language: mul
concept_id: concept.objet-a
period: 1964-1966
period_label: S11–S12 时期
state_label: a 作为欲望的原因，与阉割、缺失绑定
authority_level: L1
review_status: reviewed
status: active
generated_by: human:coffee
sources: [doc.lacan.seminar-11]
passages: [passage.S11.1964-02-12.P007]
supersedes: state.objet-a.1953-1955
related: [state.objet-a.1953-1955]
tags: [概念/对象a, 分期/1964-1966]
created_at: "2026-09-20T00:00:00Z"
updated_at: "2026-09-20T00:00:00Z"
schema_version: 1.0.0
---
```

> ⚠️ 上例中的 `passage.S11.1964-02-12.P007` 是**结构示例**。
> 真实 Passage ID 必须在 Phase 2 解析 S11 底本后按实际课次生成；
> 在此之前不得把它当作已存在的证据使用。

---

## 8. 校验与工具

| 工具 | 作用 |
|---|---|
| `_scripts/_tools/validate_vault.py` | 全量校验：schema + ID 唯一性 + canonical_name 唯一性 + wikilink + relation |
| `_scripts/_tools/make_index.py` | 生成 `_index/Views/` 各视图 |
| `_scripts/test_inventory.py` | inventory 引擎的 red/green 测试（21 项） |

校验输出：`_index/Reports/validation-report.md` + `.json`。

---

*配套：`knowledge.schema.json`（机器契约）、`ENTITY_MODEL.md`（ID 与实体）、
`RELATION_MODEL.md`（关系）、`SOURCE_PROVENANCE.md`（溯源）*
