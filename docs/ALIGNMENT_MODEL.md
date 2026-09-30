# ALIGNMENT_MODEL.md — FR–ZH 对齐模型

> 版本 `1.0.0`　·　**状态：模型定义 + 现状诊断。本阶段没有产出任何 alignment 记录。**
> 事实来源：`_data/passage_store/passages.jsonl`（实测统计）、
> `_data/passage_store/_build_meta.json`、`build_passage_store.py` 的模块 docstring；
> 明确不存在 `_data/passage_store/alignments.jsonl`（已用 `ls` 确认）

---

## 0. 先说清楚本阶段做了什么、没做什么

| 项 | 状态 |
|---|---|
| Alignment 数据模型（实体与字段） | ✅ 本文档定义 |
| `relation_type` 枚举 | ✅ 本文档定义 |
| 现状诊断（为什么不能假设 1:1） | ✅ 实测，见 §2 |
| **`alignments.jsonl` 产物** | ✅ **已存在，4 行**（`_data/passage_store/_concept_meta.json` → `counts.alignments: 4`） |
| **大规模自动对齐** | ❌ **不做**（见 §7） |
| **任何 alignment 记录** | **4 条样例**，全部 `candidate`，覆盖 4 种 `relation_type` |

`build_passage_store.py` 的模块 docstring（第 10 行）把 `alignments.jsonl`
列为产出之一，但**该脚本本身从不写这个文件**。
真正写它的是 `_scripts/_tools/seed_concepts_and_claims.py`（第 58、369 行）——
**该脚本已运行，`alignments.jsonl` 现有 4 行**（实测）。

**因此本文档的字段名不是凭空提案** —— §2 的字段表已与
`seed_concepts_and_claims.py` 第 224–277 行的实际记录结构**逐字段对齐**
（实测 4 条样例，覆盖 4 种 `relation_type`）。惟 `alignment_id` 形态
与实际有差异，见 §2.2。

---

## 1. 禁止假设 1:1

### 1.1 段数根本不是 1:1

| 语言 | 段数 | 出处 |
|---|---|---|
| 法语转录 | 166,527 | `_build_meta.json` → `counts.by_language.fr`；实测逐行计数 |
| 中译 | 82,578 | 同上 → `.zh` |

```
比值 = 166,527 / 82,578 = 2.0166…   ≈ 2.017 : 1
相差 = 83,949 段
```

**法语比中文多出约一倍。** 任何「第 N 段对第 N 段」的对齐在 $N > 82,578$ 时
直接失败，在此之前的对应关系也毫无依据。

### 1.2 更糟：粒度和切分单位都不同（这是真正的问题）

段数比只是表象。实测更根本的差异在**结构**：

| | 法语 | 中译 |
|---|---|---|
| `lesson` 字段 | **恒为 `null`**（166,527/166,527） | **恒为整数**（82,578/82,578） |
| session_id 形态 | `session.S01.unknown` | `session.S01.unknown.L01` |
| 每期 session 数 | **1** | **21–29**（按课次切分） |
| session_id 集合交集 | **0**（两者形态不同，无法在 session 级配对） | |

实测对照（前 6 期）：

| seminar | fr 段数 | zh 段数 | 比值 | fr sessions | zh sessions |
|---|---:|---:|---:|---:|---:|
| S01 | 9,779 | 4,102 | 2.38 | 1 | 23 |
| S02 | 9,035 | 4,700 | 1.92 | 1 | 25 |
| S03 | 7,456 | 3,509 | 2.12 | 1 | 25 |
| S04 | 7,654 | 3,054 | 2.51 | 1 | 24 |
| S05 | 9,905 | 4,905 | 2.02 | 1 | 28 |
| S06 | 8,863 | 5,595 | 1.58 | 1 | 27 |

**读法**：法语转录是一整期一段流（9779 条连续段），
中译是按课次组织的（23 个 session）。**比值还逐期浮动（1.58–2.51）**，
说明连「每 N 段法语对 1 段中文」这种固定比例也不成立。

### 1.3 结论

> **对齐关系天然是 N:M 的，且粒度层级不同（seminar 级 vs lesson 级）。
> 任何假设 1:1 或固定比例的实现都是错的。**

这也解释了为什么本阶段**不做**大规模对齐：在对齐模型尚未验证前跑启发式算法，
只会产生 82,578 条互相矛盾的猜测，而**每一条猜测都会污染溯源链**。

---

## 2. Alignment 实体（提案）

### 2.1 字段

| # | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| 1 | `alignment_id` | string | ✅ | 稳定 ID，形态见 §2.2 |
| 2 | `source_passages` | string[] | ✅ | 法语侧 Passage ID 列表（≥1） |
| 3 | `target_passages` | string[] | ✅ | 中文侧 Passage ID 列表（**可为空**，见 `1:0`） |
| 4 | `relation_type` | enum | ✅ | 见 §3，5 值 |
| 5 | `confidence` | number 0–1 | ✅ | 该对齐成立的把握 |
| 6 | `review_status` | enum | ✅ | 复用 Phase 1 五值：`candidate`/`needs_review`/`reviewed`/`canonical`/`rejected` |
| 7 | `method` | string | ✅ | 怎么做出来的（`manual` / `heuristic:<name>` / `model:<id>`） |
| 8 | `authority_level` | string | ✅ | L1–L4；脚本产出的样例实测为 **`L4`** |
| 9 | `note` | string | ✅ | 人类可读说明（实测每条都有，含「为何此条只是样例」） |
| 10 | `generated_by` | string | ✅ | 实测 `script:seed_concepts_and_claims.py` |
| 11 | `schema_version` | string | ✅ | `1.0.0` |

**与初版提案的差异（以实现为准）**：实现用 `authority_level` 而非 `created_by`，
用 `note` 而非 `evidence`，且**没有** `created_at` / `updated_at`。
本表已按 `seed_concepts_and_claims.py` 的实际记录改正。

### 2.2 `alignment_id` 形态（**按实现**）

实现里出现两种形态（`seed_concepts_and_claims.py` 第 225、239、254、268 行）：

```
align.<seminar>.<seq>            例：align.s01.0001
align.<seminar|lang>.<slug>      例：align.s03.demo-n1
                                      align.s01.missing-zh
                                      align.zh.uncertain-source
```

特征：**期号段小写**（`s01` / `s03`，与 Passage/Session ID 的大写 `S01` 不同），
第二段可以是序号（`0001`）或语义 slug（`missing-zh` / `uncertain-source`）。

> ⚠️ 与我初版提案的差异：我原本提议
> `align.S01.fr-zh.000001`（含语言对）。实现**不把语言对放进 ID**
> —— 语言对可从 `source_passages`/`target_passages` 所属 witness 推出，
> 放进 ID 属冗余。**以实现为准**（我保留此差异记录以免误导）。

### 2.3 ⚠️ 与 Phase 1 命名空间的关系

Phase 1 `id-namespaces.json` 的 24 个类型里**没有 `alignment`**。
本模型引入了一个新的实体类型，因此 Phase 3 落地时**必须**：
① 在 `id-namespaces.json` 增加 `alignment` 命名空间；
② 在 `knowledge.schema.json` 的 `entity_type` 枚举里增加 `alignment`；
③ 记入 `00_System/Schemas/CHANGELOG.md`。

（Phase 1 的 `RELATION_MODEL.md` 里已有 `translates_as` 谓词，
那是**概念/术语层**的译法关系，与本文档的**文本段层**对齐不是一回事：
前者说「术语 A 译作 B」，后者说「第 X 段对应第 Y 段」。两者都需要。）

---

## 3. `relation_type` 枚举（5 值）

**核心：枚举必须能表达「不对齐」和「不知道」，而不只是「对齐」。**

| 值 | 读法 | 含义 | 实测必要性 |
|---|---|---|---|
| `1:1` | 一段对一段 | 单段可直接对应 | 少数情况 |
| `N:1` | 多段对一段 | 多句法语合成一段中文（**最可能的主要形态**） | 由 §1 的 2.017:1 比值推断 |
| `1:N` | 一段对多段 | 一句法语被拆成多段中文 | 可能存在 |
| `1:0` | **有原文，无译文（缺译）** | 法语有这段，中译**没有对应** | 83,949 段的差额**必须**有地方安放 |
| `0:1` | **有译文，来源不明** | 中文有这段，找不到对应法文 | 翻译可能增补/改写 |

### 3.1 为什么 `1:0` 与 `0:1` 是必需的

如果枚举只有「1:1 / N:1 / 1:N」，那么那 83,949 段的差额**在模型里无处表示**。
实现者会被迫二选一：

- ❌ 把差额硬塞进 N:1（伪造对应）→ **污染溯源链**，违反本库第一原则
- ❌ 干脆不记录 → 对齐结果**看起来**覆盖完整，实际缺失被隐藏

**`1:0` / `0:1` 让「缺失」成为一等公民。**
这与 Phase 1 `SOURCE_PROVENANCE.md` 的 `SOURCE_TRACE_INCOMPLETE`
是同一种设计哲学：**不知道必须能写出来，否则就会被伪装成知道。**

### 3.2 各类型的 `target_passages` 约束

| `relation_type` | `source_passages` | `target_passages` |
|---|---|---|
| `1:1` | 长度 1 | 长度 1 |
| `N:1` | 长度 ≥ 2 | 长度 1 |
| `1:N` | 长度 1 | 长度 ≥ 2 |
| `1:0` | 长度 ≥ 1 | **必须为空 `[]`** |
| `0:1` | **必须为空 `[]`** | 长度 ≥ 1 |

> 注：`0:1` 的 `source_passages` 为空，说明「我们不知道它对应哪段法文」——
> 这**不等于**「它没有来源」，而是一种**显式的未知**。

---

## 4. 任何 heuristic alignment 默认 `candidate`，不得自动 canonical

### 4.1 规则

| 生产方式 | `method` | 必须的 `review_status` |
|---|---|---|
| 人工逐条对齐 | `manual` | 可写 `reviewed`（需 `reviewed_by`） |
| 启发式（长度比、锚点词、位置） | `heuristic:<name>` | **只能 `candidate`** |
| 模型推断 | `model:<id>` | **只能 `candidate`** |

**硬规则**：`method` 不是 `manual` 的记录，`review_status` **不得**是
`canonical`；也不得在未经人工复核的情况下升为 `reviewed`。

### 4.2 为什么这条不能松

对齐错误是**最隐蔽**的错误类型。举例：

- 若把 S01 第 500 段法语错误地对到第 501 段中文，两段语义往往**相近**
  （同一课、相邻位置），人工抽检极易漏过；
- 但一旦有人引用该对齐去论证「拉康这里说的是 X」，溯源链就会指向
  **错误的中文句子**，而链条上每一环看起来都完整（`trace_status: COMPLETE`）；
- **这比缺证据更危险**：缺证据会被标 `SOURCE_TRACE_INCOMPLETE`，
  而错误证据会**顺利通过所有检查**。

因此对齐必须默认 `candidate`，且**不得自动 canonical** —— 与 Phase 1
「AI 内容不得自动升格」是同一条红线的延伸。

### 4.3 `confidence` 的使用

| 区间 | 含义 | 允许的 `review_status` |
|---|---|---|
| 0.95–1.0 | 人工确认 | `reviewed` / `canonical`（canonical 仍需人） |
| 0.80–0.94 | 强启发式信号 | `needs_review` |
| 0.50–0.79 | 弱信号 | `candidate` |
| < 0.50 | 猜测 | `candidate`，且**不得作为任何断言的依据** |

（与 Phase 1 `RELATION_MODEL.md` §5 的 `confidence` 语义保持一致。）

---

## 5. `method` 字段的作用

`method` 不是装饰，它决定「这条对齐能不能被信任」：

| 值形态 | 示例 | 可审计性 |
|---|---|---|
| `manual` | `manual` | 高：有人负责 |
| `heuristic:<name>` | `heuristic:length-ratio` | 中：算法可重跑复现 |
| `model:<id>` | `model:deepseek-v3/run-2026-09-20` | 低：需记录模型与运行，否则不可复现 |

**要求**：`method` 必须写到能**重跑复现**的粒度。
写 `model` 而不写模型 id 与运行标识，等于放弃可复现性。

---

## 6. 与 Passage / Witness / Translation 的关系

```
passage.S01.unknown.P0001        （fr，来自 witness.fr.staferla）
        ▲
        │ source_passages
   align.S01.fr-zh.000001  ── relation_type: N:1, method: manual, review_status: reviewed
        │ target_passages
        ▼
passage.S01.unknown.L01.P0003    （zh，来自 witness.zh.translation-project）
```

- 对齐**引用 Passage ID**，不复制文本（文本只存在于 `passages.jsonl`）。
- 对齐**跨 witness**：一端必属 `witness.fr.staferla`，另一端必属
  `witness.zh.translation-project`（`WITNESS_MODEL.md`）。
- 对齐**不改变** Passage 本身。它是一层附加关系，删掉不影响 Passage Store。
- 因此对齐**可重建/可丢弃**，与 Phase 1「衍生索引不得成为唯一知识本体」一致 ——
  但**人工审核结论**（`review_status: reviewed`）是劳动成果，
  若重建对齐数据集必须单独保留人工结果。

---

## 7. 为什么本阶段只定义模型、不做大规模对齐

| 理由 | 说明 |
|---|---|
| **粒度层级未统一** | fr 是 seminar 级单 session（1 期 1 条），zh 是 lesson 级（1 期 ~25 条）。需要先决定对齐在**哪一级**做（段级？课次级？），这直接影响 `source_passages`/`target_passages` 的基数 |
| **缺人工基准集** | 没有一批已人工确认的 N:M 样例，就无法评估任何启发式的准确率。先跑算法等于**没有尺子就量长度** |
| **错误对齐最隐蔽** | §4.2：错对齐能顺利通过所有检查，比缺证据更危险。在无人工审核能力的阶段批量生产对齐，是在给未来埋雷 |
| **对齐不阻塞其他工作** | Passage Store、witness/translation 分层、确定性构建都不依赖对齐。先做对齐会拖慢已验证的部分 |
| **成本** | 82,578 条目标段，每条都要找法语对应；人工核对是数万次判断量级 |

**本阶段的实际交付**：把「不能假设 1:1」这件事**用实测数字钉死**
（2.017:1，逐期浮动 1.58–2.51，session 粒度不同），
并把「缺译 / 来源不明」写进枚举。这样 Phase 3 的实现在动手前就知道边界在哪。

---

## 8. Phase 3 落地前置清单

| # | 前置项 | 为什么必须 |
|---|---|---|
| 1 | 在 `id-namespaces.json` + `knowledge.schema.json` 增加 `alignment` 类型 | 否则新实体与已定契约冲突（§2.3） |
| 2 | 决定对齐层级（段级 / 课次级 / 混合） | 决定 `source_passages`/`target_passages` 的基数与算法 |
| 3 | 建人工基准集（建议 ≥200 条，覆盖 5 种 `relation_type`） | 没有基准无法评估准确率 |
| 4 | 解决 `1:0` 的 83,949 段差额归属 | 否则差额会被硬塞进 N:1 |
| 5 | 明确长句切分策略 | 法语一段 vs 中文多段的边界由什么决定 |
| 6 | 定义人工审核工作流（谁能写 `reviewed`） | 对齐的 `reviewed` 是劳动成果，需可追责 |

---

*配套：`PASSAGE_MODEL.md` · `WITNESS_MODEL.md` · `TRANSLATION_MODEL.md` ·
`CLAIM_MODEL.md` · Phase 1 `RELATION_MODEL.md`（`translates_as` 谓词）*
