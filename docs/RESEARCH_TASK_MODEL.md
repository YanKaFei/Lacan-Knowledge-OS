# Research Task Model — Phase 4B

> 数据集：`_data/eval/research_tasks_v1.jsonl`（**27** 个任务：dev 18 / holdout 9）
> 公开视图：`_data/eval/research_tasks_v1.public.jsonl`
> gold 推导审计：`_data/eval/research_tasks_v1.gold_derivation.json`

## 1. 为什么不再用「单句 retrieval query」当评测单位

Phase 3/4A 的评测单位是 query；Phase 4B 的单位是**研究任务**：
需要多步检索、上下文件展开、实体解析、来源分层、时期推理与证据取舍。
这 27 个问题都是真实拉康研究问题（不是为系统编的），10 类覆盖：

| task_type | 数量 |
|---|---|
| `case_research` | 2 |
| `concept_definition` | 3 |
| `concept_relation` | 3 |
| `diachronic_development` | 3 |
| `freud_to_lacan` | 2 |
| `insufficient_unanswerable` | 4 |
| `philosophy_to_lacan` | 2 |
| `seminar_specific` | 3 |
| `topology_matheme` | 2 |
| `translation_terminology` | 3 |

## 2. Schema（§5）

| 字段 | 用途 |
|---|---|
| `task_id` / `question` / `language` / `task_type` | 身份与分类 |
| `expected_entities` | **问题本身蕴含**的实体（用于实体解析准确率） |
| `desirable_entities` | 理想情况下还会找到的实体（**不计分**，避免不公平期望） |
| `expected_operations` | 期望的研究操作 |
| `expected_seminars` / `expected_periods` | 期号与时期期望（`expected_periods` **由知识库真实期段推导**） |
| `required_capabilities` | 能力标签（决定计划里的操作） |
| `answerability` | `SUPPORTED` / `PARTIALLY_SUPPORTED` / `INSUFFICIENT_EVIDENCE` |
| `gold_evidence` / `acceptable_evidence` | 参考证据（**分层抽样**，见 §4） |
| `lane_eval_sets` | 每个 lane 的**近全量**命中集（≤400）→ 用于 lane 级召回 |
| `forbidden_shortcuts` | 明确禁止的捷径（写进文档，供人复核） |
| `evaluation_notes` | 该任务的实测事实（如 needle 计数） |
| `review_status` | 一律 `script_assisted_unreviewed`（**没有第二个人工标注者**） |

## 3. gold 是**推导**出来的，不是手写的

`build_research_tasks_v1.py` 为每个任务声明词面 needle（按 lane / 语言 / 研讨班），
在 canonical store 上现算：

* 归一化：NFKC → 去撇号/连字符 → 去变音 → 去标点 → 小写 → **再去空白**
  （去空白是必需的：同一术语在语料里有 `plus-de-jouir` / `plus de jouir` 两种写法）；
* 分层抽样：每期 ≤3、每 lane ≤20；
* **段号逐个核对存在于 store**（本次 653 个 gold 段号，0 编造）。

## 4. 一个被实测纠正的度量错误（重要）

`gold_evidence` 是**分层抽样**（取的是 store 顺序最早的几条），
而检索返回的是**排序靠前**的段落 —— 两者交集天然接近 0。
实测 rt-D01：gold 9 条全在 S11，agent 也在 S11 取到 12 条，**交集仍为 0**。

若把它当召回分母，会得出「检索全错」的假结论。
因此本阶段改用 **`lane_eval_sets`**（每个 lane 的近全量命中集，≤400）
计算 `lane_recall`，并把旧的抽样召回归名为 `gold_sample_recall_*` 并注明**不是**质量指标。

## 5. 不可答任务（J 类，4 个）

| task_id | 实测事实（用于证明「库里确实没有」） |
|---|---|
| `rt-J01` | `moebius` 全库 **1** 段、`bande de moebius` **0** 段（拓扑词主要是 `borroméen` 499 段） |
| `rt-J02` | `frmi` **3** 段（全部 zh/S13）、`neuroscience(s)` **0** 段 |
| `rt-J03` | 全部 passage 的 `session_date` = unknown（语料只给 year_from/year_to） |
| `rt-J04` | `wittgenstein` 19 段，全部是旁及提及 → 只能 PARTIALLY_SUPPORTED |

## 6. Gold 隔离（§6）

送进 Agent 的只有 `public_view()` 的 6 个字段：
`task_id / question / language / task_type / required_capabilities / split`。
`run_task()` 对含 gold 字段的输入**直接抛错**；trace 里也不出现任何 gold 字段名
（硬门禁第 12 项 + `test_phase4b_research.TestGoldIsolation` 双保险）。

## 7. 已知的方法局限（如实列出）

* **没有第二个人工标注者**：`review_status` 全是 `script_assisted_unreviewed`；
* gold 是**词面**推导的（没有逐段人工通读），`acceptable_evidence` 覆盖度有限；
* `expected_periods` 由 seminar 推导，若真实答案是「跨期的连续演变」，粒度仍偏粗；
* 任务集为 10 类设计，**不代表**拉康研究的全部问题类型。
