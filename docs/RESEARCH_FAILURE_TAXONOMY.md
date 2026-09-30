# Research Failure Taxonomy — Phase 4B（§26）

每个错误都要尽量**定位到层**，否则下一阶段不知道该修检索、本体、证据判定还是综合。
分类由 `research_eval_4b.classify()` 按可复核规则给出（不是人读出来的印象）。

## 1. 11 类

| 类别 | 触发规则（可复核） | 本阶段实测次数 |
|---|---|---|
| `ENTITY_RESOLUTION_FAILURE` | 见代码 `classify()` | 5 |
| `TERMINOLOGY_MAPPING_FAILURE` | 见代码 `classify()` | 0 |
| `RETRIEVAL_MISS` | 见代码 `classify()` | 7 |
| `RANKING_FAILURE` | 见代码 `classify()` | 6 |
| `CONTEXT_INSUFFICIENT` | 见代码 `classify()` | 0 |
| `ONTOLOGY_GAP` | 见代码 `classify()` | 25 |
| `SOURCE_GAP` | 见代码 `classify()` | 25 |
| `EVIDENCE_SUFFICIENCY_ERROR` | 见代码 `classify()` | 3 |
| `CITATION_ERROR` | 见代码 `classify()` | 0 |
| `SYNTHESIS_OVERCLAIM` | 见代码 `classify()` | 1 |
| `BUDGET_EXHAUSTION` | 见代码 `classify()` | 0 |

## 2. 判定规则（摘要）

* `ENTITY_RESOLUTION_FAILURE`：`expected_entities ⊄ 已解析实体`；
* `RETRIEVAL_MISS` / `RANKING_FAILURE`：`lane_recall == 0` / `< 0.05`（lane 级，非抽样 gold）；
* `ONTOLOGY_GAP`：证据包里出现**实体级**缺口码
  （`COUNTERPART_ENTITY_MISSING` / `BOTH_ENTITIES_MISSING` / `UNRESOLVED_ENTITY` /
  `AMBIGUOUS_ENTITY` / `ENTITY_COLLISION`）——**不含** `TERMS_NOT_IN_CORPUS`
  这类词表码（第一版把它们也算进来，结果 18/18 任务全报 ONTOLOGY_GAP，指标失去意义）；
* `SOURCE_GAP`：证据里有 `SOURCE_TRACE_INCOMPLETE`；
* `CONTEXT_INSUFFICIENT`：证据 >5 条却一次上下文都没补（仅概念/个案/历时类）；
* `EVIDENCE_SUFFICIENCY_ERROR`：`false_supported` 或 `false_insufficient`；
* `CITATION_ERROR`：编造引用 / 溯源升级 / 层级混淆；
* `SYNTHESIS_OVERCLAIM`：`unsupported_claim_rate > 0`；
* `BUDGET_EXHAUSTION`：预算被触顶；
* `TERMINOLOGY_MAPPING_FAILURE`：期号约束下 `CONSTRAINT_RETURNED_NOTHING`。

## 3. 本阶段**最重要**的一类：EVIDENCE_SUFFICIENCY_ERROR

实测出现 **3** 次，全部是 **false SUPPORTED**：

| task | 问题 | 为什么会误判 |
|---|---|---|
| `rt-J02` | 拉康如何看待 fMRI 等当代神经科学影像研究？ | 取到 10 条证据、状态判 SUPPORTED；但全库只有 `frmi` 3 段旁及提及 |
| `rt-J01` | 莫比乌斯带为什么适合表示拉康的主体？ | 全库 `moebius` 仅 1 段、`bande de moebius` 0 段 |

**没有为了让它们变绿而调规则**：这两条如实留在结果里，
并在 `PHASE4B_FINDINGS.md` 里给出「下一阶段该做什么」的证据基础（§27）。

另有 1 次 `false_insufficient`（holdout `rt-G01`，黑格尔任务被判 INSUFFICIENT 而我的
gold 标 SUPPORTED）：**没有改 gold**，作为人工评审要裁决的分歧留在
`research_human_review.jsonl`（NOT_REVIEWED）。

## 4. 层的归因（本阶段结论）

* **检索层**：`lane_recall_mean = 0.0561`（dev）——低，但主要原因是
  「top-k 取 10–20 条 vs lane 命中集几百条」，属**预期行为**而非故障；
* **本体层**：`ONTOLOGY_GAP` 25 次，主要来自研究用词
  （人名、哲学来源）没有实体 → 已写 62 条 `candidate` 进缺口队列；
* **证据判定层**：3 次 false SUPPORTED
  —— 这是**最该修**的一层（§13 明确：宁可 PARTIALLY 也不要虚假完整）；
* **综合层**：`SYNTHESIS_OVERCLAIM` 1 次
  （`unsupported_claim_rate = 0.0139`），
  引用编造/层级混淆 **0** 次。
