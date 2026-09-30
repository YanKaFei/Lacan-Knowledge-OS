# Human Review Guide — Phase 4C（§16–§18、§23、§24）

## 0. 最重要的一条

**不要因为答案「写得像学术文章」就给高分。**
本系统不生成散文式论证（回答由规则从证据组装），所以「读起来像不像论文」
不是评分依据。**唯一依据是：关键 claim 有没有真实的 Passage 支持。**

## 1. 评分维度（1–5，方向必须看清）

| 维度 | 1 | 3 | 5 |
|---|---|---|---|
| `theoretical_coherence` | 论证断裂或自相矛盾 | 基本连贯但有跳跃 | 论证连贯，且每一步都由所引段号支撑 |
| `historical_accuracy` | 时期/期号陈述与语料冲突 | 大体一致，个别期号含糊 | 所有时期/期号陈述都能在语料里对上 |
| `distinction_preservation` | 把必须区分的概念混同（如 Real = réalité） | 提到区分但执行不彻底 | 区分严格，且给出区分依据的段号 |
| `answer_usefulness` | 无法用于任何学术写作 | 可作为线索 | 可直接作为写作底稿的证据骨架 |
| `overclaiming` | **1 = 严重过度断言** | 3 = 偶有超出证据的措辞 | **5 = 无实质过度断言** |
| `clarity` | 结构混乱 | 结构可读 | 结构清晰、层次分明 |

⚠️ `overclaiming` 的方向与其它维度**相反**：分数越高 = 越少过度断言。

## 2. 额外一项（§18）：`citation_support`

| 取值 | 含义 |
|---|---|
| `PASS` | 关键理论 claim 确实被所引 Passage 支持 |
| `PARTIAL` | 部分 claim 支持、部分只是「词出现在同一段」 |
| `FAIL` | 引用存在但**不支持**该 claim（引用漂移） |

程序只能证明「引用存在」（Phase 4B 已做到：fabricated = 0）；
**是否真的支持**只能由人来判断 —— 这一项是本阶段最需要人类输入的地方。

## 3. 流程

1. 打开 `_data/eval/human_review_packets/<task_id>.json`：内含问题、回答分段、
   claim 表（含分类与逐条引用）、引用列表、**原文摘录**、来源层级、trace 摘要、
   充分性分层与告警。**不含任何模型私有推理。**
2. 在 `_data/eval/research_human_review.jsonl` 里**逐条**填写 `human_scores` 与
   `citation_support`，把 `review_status` 改成 `REVIEWED`，并填 `reviewer_id` /
   `reviewed_at`。
3. 对 `_data/eval/human_adjudication_queue.jsonl` 里的冲突（当前 3 条：
   rt-J01, rt-G01, rt-H02）作出裁决：填 `decision`（保留/修改 gold 及理由）、
   `adjudicated_by`、`adjudicated_at`，状态改 `ADJUDICATED`。
4. 若认为 Gold 错误：**不要直接改 `research_tasks_v1.jsonl`**（§26）。
   记录裁决理由；将来若要更新，另建 `gold_v2` 版本，旧 benchmark 历史保留。

## 4. 单人评审（§23）

当前 `reviewer_count = 1`，`reviewer_status = SINGLE_REVIEWER`。
**不得报告 inter-rater agreement**（没有第二位评审者时该指标不存在）。
若将来有第二位评审者，再增加 agreement / adjudication 流程。

## 5. 系统**不会**做的事（§24）

* 不会自动填写任何 `human_scores`（当前全部为 `null`）；
* 不会把 `review_status` 从 `NOT_REVIEWED` 改成别的值；
* 不会把裁决状态从 `PENDING` 改成 `ADJUDICATED`。
硬门禁第 13 项「false human review generation = 0」会检查这三件事。
