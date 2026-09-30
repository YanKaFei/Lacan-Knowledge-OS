# CLAIM_MODEL.md — Claim 层（断言）

> 版本 `1.0.0`　·　**状态：模型定义。本阶段没有产出任何 claim 记录。**
> 事实来源：`build_passage_store.py` 模块 docstring（声称产出 `claims.jsonl`）、
> `_data/passage_store/`（**实测无 `claims.jsonl`**）、
> Phase 1 `RELATION_MODEL.md` / `KNOWLEDGE_SCHEMA.md` / `SOURCE_PROVENANCE.md`

---

## 0. 先说清楚本阶段做了什么、没做什么

| 项 | 状态 |
|---|---|
| Claim 数据模型（字段与约束） | ✅ 本文档定义 |
| 「AI 自动生成默认 candidate」规则 | ✅ 本文档定义 |
| 「无 `supporting_passages` 不得 canonical」规则 | ✅ 本文档定义 |
| **`claims.jsonl` 产物** | ✅ **已存在，2 行**（`_data/passage_store/_concept_meta.json` → `counts.claims: 2`） |
| **任何 claim 记录** | **2 条样例** |

`build_passage_store.py` 第 10 行的 docstring 把 `claims.jsonl` 列为产出，
但**该脚本本身从不写它**。真正写它的是
`_scripts/_tools/seed_concepts_and_claims.py`（第 59、370 行）——
**该脚本已运行，`claims.jsonl` 现有 2 行**（实测）。

**因此 §2 字段表已与实现的记录结构（第 301–340 行）逐字段对齐**，
并已改正与初版提案的四处差异（见 §2.3）。

---

## 1. Claim 是什么，为什么需要它

### 1.1 三个层次的分工

| 层 | 回答 | 已实现？ |
|---|---|---|
| **Passage** | 「原文是怎么说的？」 | ✅ 249,105 条 |
| **Relation** | 「两个实体之间是什么关系？」 | ⚠️ 5 条样例（`_data/relations/*.jsonl`） |
| **Claim** | 「库里主张了什么？」 | ❌ 0 条 |

**Relation 不够用。** Relation 是**二元**的
（`subject --predicate--> object`，Phase 1 定义了 17 个谓词）。
但研究里大量主张是**带条件的句子**，例如：

> 「在 S11 时期，objet a 被表述为欲望的原因，而非欲望的对象。」

这句话里有：时期限定（S11）、两个概念（objet a / désir）、一个对比结构
（而非）、以及需要多段证据支撑。硬塞进二元 relation 会丢掉大半信息。

**Claim 就是承载这种句子的实体**：它有自己的 `statement` 文本、
自己的证据列表、自己的时期与权威层级。

### 1.2 Claim 与 Relation 不是替代关系

| | Relation | Claim |
|---|---|---|
| 形态 | `subject --predicate--> object` | 一句自然语言 `statement` |
| 谓词 | 封闭 17 个枚举 | 无（开放文本） |
| 证据 | `evidence.passage_id`（Phase 1 已定义） | `supporting_passages` |
| 适合 | 结构性事实（「A 出现在 S3」） | 论证性主张（「A 在 S3 中被重新定义为…」） |
| 可机械查询 | 高（可遍历） | 低（需语义检索） |

**结论**：两者都要。
Claim 的可查询性差是**自觉付出的代价** —— 换取表达力。
需要机械遍历时，用 Relation；需要承载论证时，用 Claim；
**并且 Claim 应尽量同时登记它所依赖的 Relation**（见 §4.3）。

---

## 2. 字段定义（提案）

| # | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| 1 | `id` | string | ✅ | 稳定 ID，见 §2.1 |
| 2 | `statement` | string | ✅ | 断言本身（自然语言，一句话为主） |
| 3 | `supporting_passages` | string[] | ✅ | **支撑该断言的 Passage ID 列表** |
| 4 | `concepts` | string[] | ⬜ | 涉及的概念 ID（`concept.*` / `state.*`） |
| 5 | `period` | string | ⬜ | 理论分期，复用 Phase 1 `concept_period` 9 值枚举 |
| 6 | `source_type` | string | ✅ | `primary` / `secondary` / `note` / `synthesis` |
| 7 | `authority_level` | string | ✅ | `L1`/`L2`/`L3`/`L4`（Phase 1 权威分层） |
| 8 | `status` | string | ✅ | `draft` / `active` / `deprecated` / `rejected` |
| 9 | `review_status` | string | ✅ | `candidate`/`needs_review`/`reviewed`/`canonical`/`rejected` |
| 10 | `confidence` | number 0–1 | ✅ | 该断言成立的把握 |
| 11 | `created_by` | string | ✅ | `human:<name>` / `ai:<model>/<run>` / `script:<name>` |
| 12 | `trace_status` | string | ✅ | `COMPLETE` / `SOURCE_TRACE_INCOMPLETE`。**实测按 `supporting_passages` 是否为空自动推导** |
| 13 | `note` | string | ✅ | 人类可读说明（实测含「AI/脚本生成的 Claim 一律 candidate，不得 canonical」） |
| 14 | `generated_by` | string | ✅ | 实测 `script:seed_concepts_and_claims.py` |
| 15 | `schema_version` | string | ✅ | `1.0.0` |

**实现里没有的字段**（我曾列为「建议附加」，但实现未采用）：`counter_evidence`、
`relations`、`created_at` / `updated_at`。保留在 §4.3 作为**Phase 3 建议**，
不当作已实现能力。

### 2.1 `id` 形态（**按实现**）

实现用的是**语义 slug**，不是序号（`seed_concepts_and_claims.py` 第 303、323 行）：

```
claim.<slug>
例：claim.objet-a-cause-of-desire      （对象 a 是欲望的原因）
    claim.sinthome-fourth-ring         （圣状是第四项）
```

特征：**无期号段、无序号**，直接以断言语义命名。
> 与我初版提案（`claim.S11.000001`）的差异：实现选择可读 slug。
> 代价是「按期批量检索」不能再靠 ID 前缀，须改用 `period` 字段。
> **以实现为准。**

### 2.3 与初版提案的差异（以实现为准）

| 字段 | 我初版提案 | 实现（`seed_concepts_and_claims.py`） |
|---|---|---|
| `id` 形态 | `claim.S11.000001`（期号 + 序号） | `claim.objet-a-cause-of-desire`（语义 slug） |
| `source_type` 取值 | `primary`/`secondary`/`note`/`synthesis` | 实测用 **`concept_card`**（卡面转写）—— 取值域比我设想的更细 |
| `note` | 未列 | ✅ 有（承载「为何 candidate」等说明） |
| `trace_status` | 列为「建议附加」 | ✅ **实为必填**，按 `supporting_passages` 是否为空推导 |
| `counter_evidence` / `relations` / `created_at` | 列为建议 | ❌ 实现未采用 |

**本节保留差异记录，以免读者按我的提案去找不存在的字段。**

### 2.2 ⚠️ 与 Phase 1 命名空间的关系

Phase 1 `id-namespaces.json` 的 24 个类型里**没有 `claim`**
（它有 `synthesis`，但 synthesis 是「AI 综合产物」，语义比 claim 窄）。
落地时必须：
① 新增 `claim` 命名空间；② 加进 `knowledge.schema.json` 的 `entity_type` 枚举；
③ 记入 `00_System/Schemas/CHANGELOG.md`。与 `alignment` 同一处理（`ALIGNMENT_MODEL.md` §2.3）。

---

## 3. 两条关键约束（用户明确要求）

### 3.1 约束一：AI 自动生成的 Claim 默认 `candidate`

| 生产方式 | `created_by` | 允许的初始 `review_status` |
|---|---|---|
| 人写 | `human:<name>` | `candidate` / `needs_review` / 可直接 `reviewed` |
| **AI 生成** | `ai:<model>/<run>` | **只能 `candidate`** |
| 脚本机械提取 | `script:<name>` | `candidate` |

**硬规则**：`created_by` 以 `ai:` 开头的 Claim，
**不得**在生成时即写 `reviewed` 或 `canonical`。

**为什么**：Claim 是**最容易被误当事实**的实体 —— 它是一句完整的、读起来像结论的话。
Relation 出错（「A 影响 B」写反了）尚可机械发现；Claim 出错则表现为
**一段流畅、自洽、有出处指向的文字**，而人类读者几乎不会去逐条核对。

这与 Phase 1 `ARCHITECTURE.md` §3 的分层一致：

- AI 生成的 Claim 是 **L4**（`source_type: synthesis`）
- **L4 永不 canonical**（schema 层已强制，见 `KNOWLEDGE_SCHEMA.md` §5 与 §3.2）
- 人可以把它提升到 `reviewed`（表示「我复核过 AI 的说法」），
  但**不能**变成馆藏定本

### 3.2 约束二：无 `supporting_passages` 的 Claim 不得进入 `canonical`

| `supporting_passages` | 允许的最高 `review_status` |
|---|---|
| 空 `[]` | **`candidate`** |
| 非空，但 passages 不存在于 store | `candidate`（且标 `SOURCE_TRACE_INCOMPLETE`） |
| 非空且全部可解析 | `needs_review` → `reviewed` → `canonical` |

**硬规则**：`review_status == "canonical"` ⇒ `supporting_passages` 非空
**且每个 ID 都能在 `passages.jsonl` 中解析**。

**为什么**：`canonical` 在本库的定义是「馆藏定本」——
即「本库愿意为之背书」。**没有证据的背书就是伪造权威。**
这与 Phase 1 `SOURCE_PROVENANCE.md` 的核心承诺一致：

```
AI Answer → Concept / Claim → Passage → Session → Document/Seminar → Edition → Original Source
任何断链必须明确标记为 SOURCE_TRACE_INCOMPLETE
```

Claim 层是这个链条的**第 2 环**（紧接 Answer）。如果这一环允许无证据，
整条链的存在就没有意义。

### 3.3 两条约束的组合矩阵

| `created_by` | `supporting_passages` | 最高 `review_status` | 说明 |
|---|---|---|---|
| `human:` | 非空可解析 | `canonical` | 正常的人工定本 |
| `human:` | 空 | `candidate` | 人的猜测也需证据才能成定本 |
| `ai:` | 非空可解析 | **`reviewed`** | AI 可被复核，但**永不 canonical**（L4 规则） |
| `ai:` | 空 | `candidate` | 双重禁止 |
| `script:` | 非空可解析 | `needs_review` | 机械提取需人看 |

**注意第三行**：AI + 有证据 ≠ canonical。这是**两条独立约束叠加**的结果 ——
`supporting_passages` 解决「有没有证据」，`authority_level: L4` 解决「谁说的」。
**有证据的 AI 断言仍然不是定本。**

---

## 4. Claim 与其他层的关系

### 4.1 与 Passage：证据关系（强制）

```
claim.S11.000001
   supporting_passages: [passage.S11.unknown.L03.P0012,
                         passage.S11.unknown.L03.P0013]
```

- Claim **不复制**原文，只引用 Passage ID。
- `supporting_passages` 就是 Claim 的**证据基础**，也是 §3.2 的判据。
- 每个被引 Passage 必须能在 `passages.jsonl` 解析；否则
  `trace_status: SOURCE_TRACE_INCOMPLETE`。

### 4.2 与 Concept：论域关系（可选但建议）

`concepts` 字段引用 `concept.*` / `state.*`（Phase 1 概念两层模型）。

**关键**：Claim 的 `period` **不应**被用来把概念的不同时期合并。
Phase 1 `ARCHITECTURE.md` §4 的结构约束是：**概念本体不承载定义，
定义只存在于 `concept_state`**。Claim 的正确用法是：

- ✅ Claim 引用**特定时期**的 `state.S11.1964-1966`，主张「此期 a 被表述为欲望的原因」
- ❌ Claim 引用 `concept.objet-a` 本体并主张「a 就是欲望的原因」
  —— 这是把多期压成单一静态定义，正是 Phase 1 明令禁止的

### 4.3 与 Relation：互补（建议登记）

Claim 应尽量在 `relations` 字段登记它所依赖的 relation_id，
这样同一事实有两处表达：
一处给机器遍历（Relation），一处给人阅读（Claim）。
两者不一致时可被检测（Phase 1 `RELATION_MODEL.md` §1 的
`RELATION_VIEW_MISMATCH` 思路）。

**17 个可用谓词**（Phase 1 `relation.schema.json` 实测枚举）：

```
defines, redefines, develops, references, contradicts, influenced_by,
criticizes, translates_as, formalized_as, represented_by, appears_in,
related_to, clinical_application, case_example, topological_model,
primary_source, secondary_interpretation
```

### 4.4 完整链条

```
AI Answer / 研究结论
      │
   Claim（本文档）              ← 有 statement，必须挂证据
      │ supporting_passages
   Passage（PASSAGE_MODEL.md）  ← 最小证据单元，249,105 条已就位
      │ provenance + witness/translation
   Session / Seminar
      │
   Document → Edition → Original Source
```

**当前断点**：`Passage → Document` 这一环**全部 249,105 条都是
`SOURCE_TRACE_INCOMPLETE`**（实测 `trace_missing: ["logical_document"]`，
见 `PASSAGE_MODEL.md` §7）。因此即使现在实现 Claim 层，
**任何 Claim 的溯源链都会继承这个断点**，`trace_status` 必然是 INCOMPLETE。

**这意味着 Claim 层在 Phase 3 落地前，先要解决 Passage 的逻辑文档闭合。**
否则 Claim 层只能产出「看起来有证据、实际链断」的实体 —— 正是本库最想避免的。

---

## 5. 存储与审核工作流（提案）

### 5.1 文件布局

沿用 Phase 1 `RELATION_MODEL.md` §6 的三文件模式：

```
_data/claims/
├── claims.jsonl             主库：已审核（reviewed / canonical）
├── claims.candidate.jsonl   AI / 脚本建议：candidate
└── claims.rejected.jsonl    被否决：保留理由，防反复提出
```

**为什么分文件**：让「权威性」在**文件系统层面可见**。
即使实现有 bug，也不可能把候选当事实用。

### 5.2 状态机

```
candidate ──→ needs_review ──→ reviewed ──→ canonical
    │              │              │            │
    └──────────────┴──────────────┴────────────┴──→ rejected
```

| 状态 | 谁能写 |
|---|---|
| `candidate` | AI / 脚本 / 人 |
| `needs_review` | AI / 脚本 / 人 |
| `reviewed` | **仅人**（需 `reviewed_by`） |
| `canonical` | **仅人**，且 `supporting_passages` 非空可解析，且 `authority_level` ≠ L4 |
| `rejected` | 人 |

（与 Phase 1 `KNOWLEDGE_SCHEMA.md` §5 状态机一致。）

---

## 6. Phase 3 落地前置清单

| # | 前置项 | 为什么必须 |
|---|---|---|
| 1 | **解决 Passage → Document 闭合** | 否则所有 Claim 的 `trace_status` 必然 INCOMPLETE（§4.4） |
| 2 | 在 `id-namespaces.json` + `knowledge.schema.json` 增加 `claim` | 否则与已定契约冲突（§2.2） |
| 3 | 决定 `statement` 的语言与粒度规范 | 中英法混写会让检索与去重失效 |
| 4 | 定义「AI 生成 Claim」的入口与限流 | 防止批量生成数万条无审核能力的候选 |
| 5 | 定义 `counter_evidence` 的使用规范 | 只记有利证据 = 系统性偏倚 |
| 6 | 与 `_data/relations/` 的边界约定 | 避免同一事实两处表达互相矛盾 |

---

*配套：`PASSAGE_MODEL.md` · `ALIGNMENT_MODEL.md` · `PHASE2_ARCHITECTURE.md` ·
Phase 1 `RELATION_MODEL.md` · `SOURCE_PROVENANCE.md` · `KNOWLEDGE_SCHEMA.md`*
