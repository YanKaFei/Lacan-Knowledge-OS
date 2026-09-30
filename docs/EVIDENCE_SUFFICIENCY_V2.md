# Evidence Sufficiency v2 — Phase 4C

> 实现：`_scripts/_tools/lacan_mcp/evidence_sufficiency_v2.py`
> v1（Phase 4A）保留在 `evidence_sufficiency.py`，**历史结果不覆盖**。
> 权威判定：Research Agent 现用 v2（`research_answer.run_task` → `esv2.evaluate_v2`）。

## 1. 为什么分层（Phase 4B 的实证）

`rt-J02`（fMRI）取到 10 条证据并判 SUPPORTED，而实测该主题在语料里几乎没有专门论述。
问题在于 v1 把两件事混在一句判断里：

* **找到了相关文本**（availability）
* **这些文本是否真的以该问题为主题**（topicality）

v2 拆成六层，最后才给 `final_state`：

| 层 | 取值 |
|---|---|
| `availability_state` | NONE / SPARSE / AVAILABLE |
| `topicality_state` | ABSENT / INCIDENTAL / CONTEXTUAL / SUBSTANTIAL / DIRECT |
| `coverage_state` | NONE / LOW / MEDIUM / HIGH |
| `source_state` | NO_EVIDENCE / RECOVERED_ONLY / SECONDARY_ONLY / PRIMARY_PRESENT_BUT_NON_TOPICAL / PRIMARY_PRESENT |
| `ontology_state` | ENTITY_PRESENT / CANDIDATE_ONLY / MISSING_ENTITY / ENTITY_COLLISION / AMBIGUOUS_ENTITY |
| `final_state` | SUPPORTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE / CONFLICTING_EVIDENCE |

外加 `reasons[]` / `absence_profile` / `structural_unanswerability` / `signals`。
**没有任何 0–1 confidence，也没有 cosine 阈值**（测试断言：源码里不存在
`cosine < 数值` 形式的阈值表达式）。

## 2. 每条证据的 `topic_support_level`（§5）

| 级别 | 判定（全部可复核） |
|---|---|
| `DIRECT` | 命中主题词 **且** 实体已连接 **且**（段内重复 ≥2 次 / 与核心拉康概念共现 / 邻域 ±2 段持续） |
| `SUBSTANTIAL` | 命中主题词且实体已连接，但缺少上述加强信号 |
| `CONTEXTUAL` | 不含主题词，但含关联实体，或作为上下文件并入 |
| `INCIDENTAL` | 只提到名词/人名/技术词（无实体连接、无加强信号） |

判定用到的结构事实：`topic_occurrences` / `entity_linked` / `core_concept_cooccurrence` /
`neighbour_persistence` / `terminology_bridge`，全部写进 `evidence[].topic_signals`。

## 3. 语料计数必须精确（一个实测过的坑）

`corpus_prevalence` 用词法索引的**精确计数**，且**只取最紧的 FTS 变体**：
`syntax_variants(...)[:1]`。第一版落到第二档（中文 bigram AND），
把「莫比乌斯」算成 270 段 —— 而那其实是把三个 bigram 分别命中拼在一起的结果。
计数必须与「是不是真的出现过」一致。

> 副产品：这个修正顺带发现 Phase 4B 的 `rt-J01` **gold 可能错误**
> （法文拼写稀疏，但中文语料 241–270 段实质讨论莫比乌斯带）→ 进裁决队列。

## 4. 结构性不可答（§11）

`METADATA_UNAVAILABLE` · `TOPIC_NOT_COVERED` · `SOURCE_CHAIN_INCOMPLETE` ·
`ONTOLOGY_GAP` · `FORMALISM_MISSING`，全部进入 `structural_unanswerability`
与 `reasons`，并直接决定 `final_state = INSUFFICIENT_EVIDENCE`。

⚠️ `FORMALISM_MISSING` 只认**符号/数学型诉求**（`$ ◊ ◇ matheme 公式 数学型`），
不认拓扑对象名 —— 第一版把「莫比乌斯」「拓扑」也算进来，于是把
`rt-J01` 误判为缺形式化（语料其实用散文解释了单面性构造）。

## 5. directness > raw count（§14）

`final_state` 的判定顺序刻意不是「条数够就 SUPPORTED」：

* `DIRECT` 级别（哪怕只有 1–2 条，尤其是 L1 原文）→ 可 `SUPPORTED`；
* `SUBSTANTIAL` 且 `source_state = PRIMARY_PRESENT` → `SUPPORTED`；
* `SUBSTANTIAL` 但只有 recovered 中译 → `PARTIALLY_SUPPORTED`；
* `CONTEXTUAL` → 最多 `PARTIALLY_SUPPORTED`；
* `INCIDENTAL` / `ABSENT` → `INSUFFICIENT_EVIDENCE`。

预登记阈值（写在代码里，不是事后凑的）：`GENERIC_PREVALENCE=300`（泛用词不算主题词）、
`SPARSE_PREVALENCE=5`、`DIRECT_MIN=1`、`SUBSTANTIAL_MIN=2`、`MULTI_SEMINAR_MIN=2`。

## 6. 不与历时研究冲突（§13）

v2 **不使用「证据互相矛盾」这类语义判断**；多期差异只体现为
`coverage_state` 的时期分布。回归用例 `diachronic_multi_period` 要求
S7→S20 的 jouissance 问题保持 `SUPPORTED`（实测通过）。
