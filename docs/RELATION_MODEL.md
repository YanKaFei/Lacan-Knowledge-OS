# RELATION_MODEL.md — 类型化关系模型

> 版本 `1.0.0`　·　配套契约：`00_System/Schemas/relation.schema.json`、`_data/relations/`

---

## 1. 为什么 Obsidian `[[wikilink]]` 不够

`[[wikilink]]` 是**无类型**的：它只说「这两个笔记有关」。
但知识库里绝大多数错误恰恰发生在**关系类型**上：

- 「拉康**批判**了笛卡尔」被写成「拉康**受**笛卡尔影响」
- 「米勒**重新定义**了 objet a」被写成「米勒**定义**了 objet a」
- 「这个概念**出现在** S11」被写成「这个概念**源自** S11」

所以系统同时维护两套：

| 层 | 形式 | 作用 |
|---|---|---|
| **呈现层** | Obsidian `[[wikilink]]` | 人阅读、Graph View、反向链接 |
| **语义层** | `_data/relations/*.jsonl` | Agent 遍历、溯源、校验 |

**两层必须一致**：校验器检查「语义层存在的边，呈现层是否有对应 wikilink；
呈现层的 wikilink 是否能映射到语义层的某条边」。不一致报
`RELATION_VIEW_MISMATCH` 警告。

---

## 2. 关系记录契约

```jsonc
{
  "relation_id": "rel.000001",
  "subject":     "concept.objet-a",
  "predicate":   "redefines",
  "object":      "state.objet-a.1964-1966",
  "evidence": {
    "passage_id":    ["passage.S11.1964-02-12.P007"],
    "assertion_type": "explicit",
    "quote":         "…",              // 可选：原文片段
    "note":          "…"               // 可选：人类说明
  },
  "confidence":     0.95,
  "review_status":  "reviewed",
  "authority_level": "L1",
  "created_at":     "2026-09-20T00:00:00Z",
  "updated_at":     "2026-09-20T00:00:00Z",
  "created_by":     "human:coffee",
  "schema_version": "1.0.0"
}
```

**必填字段**：`relation_id`, `subject`, `predicate`, `object`, `evidence`,
`confidence`, `review_status`, `authority_level`, `created_at`, `updated_at`。

---

## 3. 17 个谓词（封闭枚举，不允许自造）

| 谓词 | 语义 | 典型 subject → object |
|---|---|---|
| `defines` | 首次确立某概念 | `concept.objet-a` → `state.objet-a.1953-1955` |
| `redefines` | **改写**既有定义（与 defines 严格区分） | `state.objet-a.1964-1966` → `state.objet-a.1953-1955` |
| `develops` | 在既有基础上推进（非改写） | `concept.sinhtome` → `concept.symptom` |
| `references` | 单纯引用/提及 | `doc.lacan.seminar-11` → `concept.angoisse` |
| `contradicts` | 明确矛盾 | `state.x.1972-1973` → `state.x.1959-1963` |
| `influenced_by` | 思想受影响 | `person.jacques-lacan` → `philosopher.hegel` |
| `criticizes` | 批判（**不可与 influenced_by 混用**） | `person.jacques-lacan` → `philosopher.descartes` |
| `translates_as` | 译法对应 | `term.fr.jouissance` → `trans.fr-to-zh.jouissance` |
| `formalized_as` | 被形式化为某数学型 | `concept.objet-a` → `matheme.objet-a` |
| `represented_by` | 被某拓扑/图形表征 | `structure.neurosis` → `topology.mobius-strip` |
| `appears_in` | 出现在某文本/课次 | `concept.sinthome` → `session.S23.1975-11-18` |
| `related_to` | 弱关联（默认兜底，慎用） | 任意 |
| `clinical_application` | 临床运用 | `concept.forclusion` → `structure.psychosis` |
| `case_example` | 作为例证 | `structure.psychosis` → `case.schreber` |
| `topological_model` | 用某拓扑建模 | `structure.psychosis` → `topology.borromean-knot` |
| `primary_source` | 指向一手出处 | `concept.objet-a` → `doc.lacan.seminar-11` |
| `secondary_interpretation` | 指向二手解读 | `concept.objet-a` → `doc.miller.xxx` |

### 3.1 三组最容易混淆的谓词（必须严格区分）

**`defines` vs `redefines`**
这是拉康研究里最关键的一组区分。同一个概念在不同时期被改写时，
必须用 `redefines` 并**显式给出被改写的对象**，否则「历史演化」在数据层
就丢失了。校验规则：`redefines` 的 object 必须是 `concept_state` 类型。

**`influenced_by` vs `criticizes`**
拉康对黑格尔、笛卡尔、康德往往是「既受影响又批判」。
这两条关系**必须并存为两条记录**，不得合并成一条模糊的 `related_to`。
校验规则：同一对 subject/object 上二者可共存，但不得互相替代。

**`appears_in` vs `primary_source`**
`appears_in` 说的是「文本里提到了」；`primary_source` 说的是
「这是一手出处」。前者弱、后者强。用错会把「提及」冒充成「依据」。

---

## 4. 证据等级 `assertion_type`

| 值 | 含义 | 要求 |
|---|---|---|
| `explicit` | 原文明确说了 | `passage_id` **至少一个**（schema 强制） |
| `inferred` | 从原文推断（如跨文本比对） | 主库：`passage_id` 至少一个 + `note`；候选库：允许为空，但 `note` 必须写明缺什么证据（见 §4.1） |
| `editorial` | 编者/整理者判断（Miller 编本就属此类） | 需注明 `note` 与 edition |

**硬规则（两张表都要遵守）**

| assertion_type | 主库 `relations.jsonl` | 候选库 `relations.candidate.jsonl` |
|---|---|---|
| `explicit` | **必须有** `passage_id` | **必须有** `passage_id` |
| `inferred` | **必须有** `passage_id` | **允许为空**，但必须同时满足 ↓ |
| `editorial` | 可空（编者判断本身不是文本引用） | 可空 |

候选库里 `inferred` 且 `passage_id` 为空时，**强制要求**：

1. `evidence.note` 非空，且写明「缺什么证据、为什么缺」；
2. 该记录在 `_data/relations/` 里必须能被识别为未取证的候选。

## 4.1 为什么候选库要留这个口子（以及它为什么安全）

**留口子的理由**：候选库的定义就是「尚未取得证据的建议」。若强制 AI 的建议
都必须先找到段号，那等于要求 AI 在提出假设时就完成取证 —— 结果是 AI 干脆
不提议，或者更糟：**随便附一个段号来满足校验**。后者是灾难。

所以口子的价值在于：让「我怀疑 X 和 Y 有关系，但还没找到出处」这句话
**有地方可写**，而且是**显式地写成未取证**，而不是伪装成已取证。

**它为什么安全 —— 三道闸门**：

1. **物理隔离**：候选库是独立文件。Agent 读的是哪个文件，在路径上就看得见。
   「不确定性在文件系统层面可见」，不依赖任何代码正确性。
2. **审核闸门**：候选升入主库**只能由人**操作。升库时，主库的规则立即生效，
   无段号的 `inferred` 会被 validator 直接判为 error ——
   **想让一条候选进主库，就必须先补上段号**。
3. **可见性**：未取证的候选在报告里显式列出，不会因为「在候选库里」就被忽略。

因此这条不是漏洞，而是**受控的暂存区**：不安全的东西进不了主库，
但想法不会被制度性地扼杀。

> ⚠️ 反过来说：**如果将来有人把候选库直接接进检索层当事实用，这道设计就失效了。**
> 这正是 SOURCE_PROVENANCE 要求 `trace_claim` 必须返回
> `SOURCE_TRACE_INCOMPLETE` 的原因 —— 二者是同一道防线的两半。

---

## 5. `confidence` 的含义

`confidence` ∈ [0, 1]，表示**这条关系本身成立的把握**，不是「重要性」。

| 区间 | 含义 | 典型场景 |
|---|---|---|
| 0.95–1.0 | 原文直陈，无歧义 | `appears_in` 且有该页 passage |
| 0.80–0.94 | 原文支持，措辞需解读 | `redefines` 有明确改写语句 |
| 0.50–0.79 | 推断，有旁证 | `influenced_by` 无直接自述 |
| < 0.50 | 弱推测 | 仅作候选，**不得进入 `relations.jsonl`** |

**规则**：`confidence < 0.5` 的关系只能写入
`_data/relations/relations.candidate.jsonl`，不能进主库。

---

## 6. 三个文件，三种权威地位

```
_data/relations/
├── relations.jsonl              主库：已审核（reviewed/canonical），可被 Agent 直接引用
├── relations.candidate.jsonl    AI 建议：review_status = candidate，不可被引用为事实
└── relations.rejected.jsonl     被否决：保留否决理由，防止同一错误被反复提出
```

**为什么分文件而不是用字段区分**：分文件让「权威性」在**文件系统层面**可见。
Agent 拿到 `relations.candidate.jsonl` 就知道自己读的是建议集；
即使实现有 bug，也不可能把候选当事实用。

**AI 的权限边界**：
- ✅ 可以写 `relations.candidate.jsonl`（建议概念、建议关系、建议别名）
- ✅ 可以给候选打 `confidence`
- ❌ 不可以写 `relations.jsonl`
- ❌ 不可以把候选的 `review_status` 改成 `reviewed` / `canonical`

---

## 7. 关系的方向性与对称性

所有 17 个谓词都是**有向**的。对称关系（如 `related_to`）在存储时
按 `subject < object` 的规范化序（**NFKC + casefold 后的码点序**）规范化方向，只存一条，避免重复边。

反向查询由索引层处理，不在数据层存反向边（避免两份真相不一致）。

---

## 8. 校验规则清单（由 `validate_vault.py` 执行）

| 规则 | 级别 | 说明 |
|---|---|---|
| `predicate` 在 17 个枚举内 | 错误 | 禁止自造谓词 |
| `subject` / `object` 存在 | 错误 | 否则 `BROKEN_RELATION` |
| `subject != object` | 错误 | 禁止自环 |
| `assertion_type=explicit` 时 `passage_id` 非空 | 错误 | 禁止无证据的 explicit |
| `passage_id` 里每个 Passage 存在 | 错误 | 否则 `SOURCE_TRACE_INCOMPLETE` |
| `redefines.object` 是 `concept_state` | 错误 | 保证演化链语义正确 |
| `confidence < 0.5` 不在主库 | 错误 | 弱推测只能进候选库 |
| 主库记录的 `review_status` ∈ {reviewed, canonical} | 错误 | 候选不得混入主库 |
| 同一 (subject, predicate, object) 不重复 | 待实现 | 目前只查 `relation_id` 重复 |
| 语义层边与 wikilink 层一致 | 警告 | `RELATION_VIEW_MISMATCH` |
| `related_to` 占比过高（> 40%） | 待实现 | 目前由 `make_index.py` 的视图人工观察，校验器尚未实现该检查 |

最后一条是刻意的：`related_to` 是兜底谓词，一旦滥用，
「类型化关系」就退化回无类型 wikilink，整个模型失去意义。
实测中这个指标应当作为知识库健康度的一项长期监控。

---

## 9. 与溯源链的关系

一条关系的完整溯源链是：

```
relation (subject, predicate, object)
   └── evidence.passage_id
         └── passage → session → seminar/document → edition → source
```

`trace_claim` MCP 工具沿这条链返回。任何一环缺失 → `SOURCE_TRACE_INCOMPLETE`。

详见 `SOURCE_PROVENANCE.md`。

---

*配套：`relation.schema.json`（机器契约）、`ENTITY_MODEL.md`（ID 引用）、
`SOURCE_PROVENANCE.md`（溯源链）*
