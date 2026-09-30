# Research Evaluation Method — Phase 4B

> 实现：`_scripts/_tools/research_eval_4b.py`
> 结果：`_data/eval/research_eval_results_v1.dev.json` / `.holdout.json` / `_v1.json`
> trace：`_data/eval/research_traces_4b/<task_id>.json`
> 人工评审骨架：`_data/eval/research_human_review.jsonl`

## 1. 指标（§21）——dev / holdout 各自报告

| 指标 | dev | holdout |
|---|---|---|
| `evidence_validity`（引用是否真实） | 1.0 | 1.0 |
| `fabricated_citations_total` | 0 | 0 |
| `citation_anchor_support_rate`（术语级代理） | 0.3443 | 0.2934 |
| `citation_term_cluster_rate`（词袋代理） | 0.3603 | 0.3134 |
| `claim_coverage` | 0.8528 | 0.9004 |
| `unsupported_claim_rate` | 0.0139 | 0.0 |
| `source_layer_confusions_total` | 0 | 0 |
| `sufficiency_accuracy` | 0.9444 | 0.7778 |
| `entity_resolution_accuracy` | 0.8333 | 0.7778 |
| `period_coverage_mean` | 0.6667 | 0.7083 |
| `separate_lanes_accuracy` | 0.875 | 0.5 |
| `lane_recall_mean`（lane 级召回） | 0.0561 | 0.0885 |
| `research_completion_rate` | 0.9444 | 1.0 |
| `multi_step_rate` | 1.0 | 1.0 |
| `tool_calls_mean` | 9.17 | 9.89 |
| `false_supported` | ['rt-J02'] | ['rt-J01'] |

## 2. 不合成单一总分（§22）

结果文件里**没有** `score` / `overall_score` 之类字段（测试断言）。
`score_policy` 明确写着：任何汇总展示都不得隐藏 unsupported claim /
citation entailment / evidence sufficiency。dashboard 只做并列展示。

## 3. 开发集与盲测集（§29/§30）

* dev = 18 个任务（用于发现问题、改实现）；
* holdout = 9 个任务，**只在开发集定稿后跑**；
* 首次盲跑之后，我没有再改 Agent / 检索规则（只改了 evaluator 与门禁判据）；
  holdout 的数字因此是可复现的，但**不是**「反复调过之后的数字」。
* 每条任务的 traces 与逐条指标都在 `research_traces_4b/`，可逐题复核。

## 4. 预算与 Gold 隔离

* 预算行为单测：`--budget-check`（max_tool_calls=2）→ 结果见
  `_data/index/RESEARCH_4B_BUDGET_CHECK.json`（`all_passed = True`）；
* 评测过程 `record_gaps=False`：**不写** canonical、不写缺口队列；
* Gold 只在 evaluator 侧；送进 Agent 的字段被逐条记录（`gold_isolation`）。

## 5. 人工评审（§23）

`research_human_review.jsonl` 为每题提供
`theoretical_coherence / historical_accuracy / distinction_preservation /
answer_usefulness / overclaiming / clarity` 六个维度，
`human_scores` **全为 null**、`review_status = NOT_REVIEWED`。
本阶段**没有**人工评审者，因此不给出任何人工分数，也不让 LLM 冒充。

## 6. 这套评测**没测**什么

* 没有测「论证的理论深度」——纯程序无法判断，留给人工；
* Citation Entailment 只有术语级代理（见 `CLAIM_CITATION_MODEL.md` §3）；
* `lane_recall` 的参考集是**近全量**（≤400）而非全部命中，长尾未覆盖；
* 27 个任务覆盖 10 类，**不是**拉康研究问题的全集。
