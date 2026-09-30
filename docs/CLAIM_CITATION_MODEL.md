# Claim / Citation Model — Phase 4B

## 1. Claim 对象

```json
{
  "claim_id": "c-dev-3",
  "text": "在 S10 的 L1 证据里出现与该问题相关的表述（见所引段号）。",
  "classification": "PRIMARY_EVIDENCE",
  "citations": ["passage.S10.unknown.P8724", "passage.S10.unknown.P8448"],
  "anchor_terms": ["objet petit a", "objet a", "对象a"],
  "note": "逐字引用原始段落；判断句只限于「该段是该期/该层级的证据」。"
}
```

* `citations` 是**这一条 claim 自己的**引用（不是段落末尾统一挂一串）；
* `anchor_terms` 来自**已解析实体的多语言写法**（`plan.anchor_pool`），
  不是从问题里瞎猜的词 —— 第一版用问题显著词当 anchor，
  把「拉康所谓的」也当成了 anchor，指标被无意义压低；
* 元陈述（证据数量/分布/限制）**不挂 anchor**。

## 2. Citation 校验的五类问题

见 `RESEARCH_ANSWER_CONTRACT.md` §6。每类都由 `validate_answer()` 报出
`claim_id` + `kind`，可直接定位到句。

## 3. Citation Entailment 只有**术语级代理**（必须说清）

纯程序无法判断「这段话是否真的支持这个断言」。本阶段实现两个代理：

| 指标 | 规则 | 实测（dev） |
|---|---|---|
| `citation_anchor_support_rate` | anchor 与段落都去标点/空白/变音后做**子串**匹配 | 0.3443 |
| `citation_term_cluster_rate` | anchor 的实词（≥3 字符）是否都在段落里（**词袋包含**） | 0.3603 |

两者都**不等于**语义蕴含。实测语料会把同一术语写成
`objet petit(a)`、`l'objet dit par moi petit a`（objet 与 petit a 分开写），
严格子串会漏，所以两个数都报出来以显示这个差距。

**真正的 entailment 需要人**：`_data/eval/research_human_review.jsonl` 里
`citation_entailment` 属人工维度，当前状态一律 `NOT_REVIEWED`，
`human_scores` 全为 `null`（§23：不伪造人工评分）。

## 4. 层级不得混（§11/§15）

* `PRIMARY_EVIDENCE` 必须引用 `authority_level == L1` 的段；
* L2/L3 只能进 `SECONDARY_INTERPRETATION`；
* 中文 recovered（`SOURCE_TRACE_INCOMPLETE`）**无论语言**都不得升为 primary；
* 结构性综合句（时期分布、实体候选状态）归 `CONTEXTUAL_INFERENCE` 并注明依据。

实测（dev）：`source_layer_confusions_total = 0`、
`provenance_upgrades_total = 0`。

## 5. Unsourced context（§24）

若将来允许模型使用通识推断，必须归类为 `AGENT_SYNTHESIS` / `UNSOURCED_CONTEXT`，
**不得**伪装成 KB evidence。当前实现不生成此类句子。
