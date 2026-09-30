# Research Answer Contract — Phase 4B

> 实现：`_scripts/_tools/research_answer.py`
> 分工：`research_agent.research()`（Phase 4A）产出证据包、**不写答案**；
> `research_answer.run_task()`（Phase 4B）在其上组织回答。

## 1. 研究循环（§7）

```
1 理解请求      make_plan()：目标 / 显著词 / 实体 / 子问题 / 计划操作
2 解析实体      resolve_entity ×≤6
3 选研究操作    能力→操作映射（period_coverage→trace_concept；separate_lanes→compare_concepts…）
4 首轮检索      research_agent.research()（Phase 4A 多步 loop）
5 看上下文      get_context（Phase 4A）
6 识别缺口      证据包里的 period / lane / gap
7 收窄范围      **_period_lanes()：按知识库自己的 seminar×period 结构补期**
8 第二条 lane   受约束 search_passages（seminar 下推）——同一套 KB 工具，不是新检索
9 溯源          trace_source（Phase 4A）
10 证据充分性   evidence_sufficiency + **§13 校准**（只降级）
11 停或继续     预算（含 Phase 4B 补充步骤）
12 组回答       compose_answer()
13 校验引用     validate_answer()（claim→citation 本地校验）
```

**不硬编码单一流程**：操作由 `required_capabilities` 决定，没有能力标签时退回
`resolve_entity → search_passages → get_context`。

## 2. 结构化计划，不含隐藏推理（§8）

`plan` 里只有：`research_goal / question_language / task_type / salient_terms /
entities / subquestions / planned_operations / operation_rationale /
budget / term_counts / anchor_pool`。
**没有** chain-of-thought；`trace.no_hidden_reasoning = true`，
trace 只记 `tool / arguments / result_ids / state / route / warnings / decision(一句规则说明)`。

## 3. 回答结构（§9）

| 段 | 何时出现 | 内容 |
|---|---|---|
| `brief_answer` | 总是 | 证据数量/分布/充分性判定（**元陈述**，可复核） |
| `theoretical_development` | 总是 | 按 lane（研讨班×语言×层级）分组 + **逐字引用**（带段号） |
| `diachronic_differences` | 证据跨 ≥2 时期时 | 各期分布 + 明确「是发展还是转折属解释判断」 |
| `key_primary_evidence` | 总是 | L1 法文原文优先；没有 primary 时**明说没有** |
| `interpretation_layers` | 总是 | 层级表：L1/L2/L3/AGENT_SYNTHESIS 各多少条 |
| `evidence_limitations` | 总是 | 溯源缺口 / ontology gap / 约束未满足 / 预算 / 校准理由 |

回答由**规则**组装（不是 LLM 生成），因此每个句子都可回溯到证据包；
`definition` 之类的理论定论**不生成**。

## 4. 引用契约（§10）

* 每条 substantive claim 至少一个真实 `passage_id`；
* 展示形式：`「原文…」[passage.S14.unknown.P5990]`（段号即引用）；
* `trace_source` 可闭合时，`provenance` 出现在证据条目里；
* **recovered 中译**（`SOURCE_TRACE_INCOMPLETE`）必须带告警，
  且**不得**被分类为 `PRIMARY_EVIDENCE`（`validate_answer` 会把这种情况判为
  `PROVENANCE_UPGRADE`，硬门禁第 5 项禁止）。

## 5. Claim 分类（§11）

`PRIMARY_EVIDENCE / SECONDARY_INTERPRETATION / AGENT_SYNTHESIS /
CONTEXTUAL_INFERENCE / UNSUPPORTED`。
最终用户文本不必逐句打标签，但 `answer.claims` 里逐条可见，
evaluator 可检查（目标：`UNSUPPORTED` ≈ 0；实测 dev 0.0139、
holdout 0.0）。

## 6. 禁止引用漂移（§12）

`validate_answer()` 做**本地**校验（claim 与 citation 一一对应）：

* `FABRICATED_CITATION`：id 不在 canonical store；
* `CITATION_NOT_IN_EVIDENCE_PACK`：id 不在本次证据包里；
* `UNSUPPORTED_CLAIM`：substantive claim 没有引用（且不是显式弃权句）；
* `SOURCE_LAYER_CONFUSION`：声明 PRIMARY 但引用里没有 L1；
* `PROVENANCE_UPGRADE`：把 recovered 中译当 primary。

## 7. 与模型的分工（§24）

回答模型可以 **synthesize**，不得 **invent source**。
本实现走的是更保守的一条：回答**不由 LLM 生成**，只由 KB 证据按规则组装；
因此不存在「模型通识被伪装成 KB 证据」的路径。
若将来要接 LLM 生成散文，`validate_answer()` 就是它的准入校验器
（`strict=True` 时任何 issue 都算失败）。
