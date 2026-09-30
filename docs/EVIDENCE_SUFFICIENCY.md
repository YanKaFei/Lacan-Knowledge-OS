# Evidence Sufficiency — Lacanian Knowledge OS（Phase 4A §7–§10）

> 引擎：`_scripts/_tools/lacan_mcp/evidence_sufficiency.py`
> 测试：`_scripts/_tests/test_phase4a_sufficiency.py`（15 项）

---

## 1. 它判断什么（§10）

**判断**：当前 Knowledge Base 是否提供了足够证据来支持**当前研究操作**。
**不判断**：哪个理论解释是正确的。

这不是一句免责声明，而是**接口设计**：引擎只看结构性事实
（有几条证据、来自几个 session、被几个分量召回、约束是否满足、有没有碰撞），
它对「拉康到底什么意思」没有任何输入通道。

---

## 2. 为什么禁止 cosine 阈值（§7）

Phase 3C 实测：**不可答 query 的 top1 余弦高于可答 query**
（minilm −0.0128 / mpnet −0.0076）。

所以 `cosine < t → 无证据` 在数学上就是错的 —— 它不是「不够灵敏」，
而是**方向反了**。因此本引擎：

* 完全不接收任何相似度分数；
* `method` 字段固定为 `structural_only_no_cosine_threshold`；
* `signals` 里不允许出现 `cosine` / `similarity` 键（`test_01` 断言）；
* 输出**不是** 0–1 confidence，而是原始信号 + 人话理由。

---

## 3. 四个状态（§7）

| 状态 | 含义 | 触发 |
|---|---|---|
| `SUPPORTED` | 证据量、一致性、多样性、约束四项都到位 | 全部达标 |
| `PARTIALLY_SUPPORTED` | 有证据，但至少一项不达标（逐条列出原因） | 见下 |
| `INSUFFICIENT_EVIDENCE` | 没有证据，或实体型操作完全没解析出实体 | `n < 1` |
| `CONFLICTING_EVIDENCE` | 证据**结构上无法归给单一实体** | `ENTITY_COLLISION` 且 `n > 0` |

`AMBIGUOUS_ENTITY` **不是**状态 —— 它是上游解析状态（§7 明确）。

### 3.1 一致性信号只在「≥2 个独立检索族」跑过时才适用

这是 Phase 4A 修掉的一个真实缺陷。第一版无条件要求
「≥50% 的证据被 ≥2 个分量同时召回」，而 routing policy 是**按问题类型**决定分量组合的
（Phase 3C 结论：向量是辅助、**不得强制启用**）。只跑词法族时
「≥2 个分量」在结构上不可能满足 → 所有单族查询都被判 `PARTIALLY_SUPPORTED`。

那等于用「我们没跑向量」去指控「证据不足」，与 Phase 3C 的结论直接冲突。

修法：按**独立族**判适用性。

| 族 | 成员 | 为什么这样分 |
|---|---|---|
| `lexical` | `exact`, `lexical` | 两者高度相关，同时命中**不构成**独立佐证 |
| `bridge` | `terminology_bridge` | 受控跨语言映射，是另一条检索策略 |
| `vector` | `vector` | 语义召回，与词法独立 |

* `independent_families_executed < 2` → `component_agreement = None`，
  写入 `notes`（**信息性**，不参与判定），**不降级**；
* `≥ 2` → 按原阈值判定。

### 3.2 session 多样性按**请求范围**判定

同样一类错误：法语 Staferla 语料**没有课次级 id**，
单个研讨班的法文段全部落在 `session.S<NN>.unknown` 一个 session 上。
于是「session 数 < 2」是**语料溯源粒度**造成的，不是证据单薄。

当请求本身限定了范围（`seminar` / `period` / `language`）时：

* 多样性要求降为 ≥1；
* 「范围是否被满足」由 `constraint_satisfaction` 承担；
* 该放宽写入 `notes`，并把请求范围原样写进理由。

未限定范围的请求**仍然**要求跨 session 多样性 —— 一条 session 的表述不足以支撑跨文本结论。

---

## 4. 信号清单

`signals` 里的原始量（不做加权、不压成单一数值）：

```
resolved_entity_count · resolved_entity_coverage · required_entity_missing
passage_count · distinct_session_count · distinct_seminar_count · distinct_period_count
component_agreement · component_agreement_applicable · independent_families_executed
exact_lexical_support · terminology_bridge_support
provenance_completeness · source_trace_incomplete_n
authority_levels · has_primary_evidence
duplicate_concentration · contradictory_evidence
ontology_gap · entity_collision · constraint_satisfaction · request_scoped
vector_enabled
```

⚠️ §8 列出的 14 类信号**逐项**由
`test_phase4a_sufficiency.py::test_15_all_required_signals_are_present` 断言存在
（其中 `primary_vs_secondary` 映射到 `has_primary_evidence` + `authority_levels`
两个键）—— 信号不是「叙述里提过」，而是**必须在 `signals` 里查得到**。

输出结构：

```json
{
  "state": "PARTIALLY_SUPPORTED",
  "signals": { "...": "原始值" },
  "reasons": ["决定状态的理由（人话）"],
  "notes":   ["信息性说明：某个信号为何不适用"],
  "method":  "structural_only_no_cosine_threshold",
  "prohibited": "禁止 cosine 阈值…",
  "scope_note": "只判断 KB 是否支持本次研究操作，不判断理论正确性"
}
```

`reasons` 与 `notes` **分开**：前者参与判定，后者只解释「为什么某个信号缺席」——
否则「这次为什么没报一致性」会变成一段看不见的推理。

---

## 5. 不降级但必须报告的两种情形

| 情形 | 处理 | 理由 |
|---|---|---|
| `SOURCE_TRACE_INCOMPLETE` | **不降级**，但计入 `source_trace_incomplete_n` 并写进 `reasons` | 中文 recovered 语料的上游原件缺失是**事实**，要如实说；但证据本身仍可引用、可回查 |
| `ontology_gap`（缺实体/缺映射） | **不降级**，但写进 `reasons`，并进 §22 队列 | 缺口是知识库的待办，不是本次操作「证据不足」 |

这两条都来自同一个原则：**不要把「知识库的另一处缺陷」算到当前这次检索头上**，
但**也绝不隐藏它**。

---

## 6. 实测分布（`_data/eval/research_eval_results.json`）

A–J 十问上达到三个状态：

| 状态 | 例子 | 原因 |
|---|---|---|
| `SUPPORTED` | A `什么是 objet a？`（15 条，8 个研讨班） | 四项达标 |
| `PARTIALLY_SUPPORTED` | B `desire 和 demand`（一侧无证据）、F（一致性 47%）、H（两族互不重合） | 逐条列出 |
| `CONFLICTING_EVIDENCE` | E `l'Autre 与 l'autre` | `ENTITY_COLLISION`，证据无法归属 |

`INSUFFICIENT_EVIDENCE` 在本批 A–J 里没有出现（C 因自适应重试取到了 1 条别的研讨班的证据）——
它由 `test_02` 用构造 payload 与 `selftest` 第 17 项另行覆盖，
不用「制造一个必然失败的 query」来凑状态。

---

## 7. 边界

* 引擎**不**读语料文本内容做语义判断 —— 它只看证据条目的结构字段；
* 引擎**不**决定用哪个 tool（那是 Research Agent 的事）；
* 引擎**不**改任何阈值以外的行为，阈值全部预登记在文件顶部：

```python
MIN_EVIDENCE = 1
SUPPORTED_MIN_AGREEMENT = 0.5
SUPPORTED_MIN_SESSIONS = 2
DUPLICATE_CONCENTRATION_MAX = 0.8
PRIMARY_LEVELS = ("L1", "L2")
```

改这些常量属于**改判据**，必须走评审 —— 不允许为了某次验收好看而调（§30）。
