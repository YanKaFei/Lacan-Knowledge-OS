# ADJUDICATED_GOLD_GUIDE.md — §2–§4 Adjudicated Gold 说明

> 产物：`retrieval_gold_adjudicated.jsonl`（45 条）
> 规格来源：`_data/adjudicated_gold_spec.jsonl`（人写）
> 生成：`_scripts/_tools/build_adjudicated_gold.py`

---

## 1. 与 proxy 集的分工（§1 明确要求）

| 集 | 文件 | 角色 |
|---|---|---|
| **proxy** | `retrieval_eval.jsonl`（120 条） | **regression / smoke test**：parser 回归、tokenizer 比较、metadata filter、exact lookup |
| **adjudicated** | `retrieval_gold_adjudicated.jsonl`（45 条） | **质量度量**：embedding model selection、ablation |

⚠️ **proxy 集不得单独作为 embedding model selection 的 ground truth** ——
它的 gold 是词面自动推导的，且**期内仍存在采样顺序偏差**（gold 段号中位远小于
每期段数；跨期偏差已修，期内未根治）。详见 `PHASE3_FINDINGS.md §3`。

## 2. 为什么需要 adjudicated gold（实测证据）

| gold | lexical hit@20 |
|---|---:|
| proxy | 0.3178 |
| **adjudicated** | **0.175** |

差近一倍。**不是检索变差**，而是 adjudicated gold 要求严格得多：

* evidence 需**多写法共现**或高区分度写法，而非「含该词」
* 查询是**研究性问题**（含 `philosophy_to_lacan`、`cross_language_zh_fr`
  这类词法几乎无解的类别）

**proxy 会高估检索能力** —— 这是要 adjudicated gold 的核心原因。

## 3. §5 intent 模型修正（先分析，不引入 LLM）

**实测原因**：proxy 的 intent 一致率 62/120，主因是 **taxonomy overlap**。

典型：`objet petit a 是什么` 被 router 判为 `concept_relationship`，
因为问题里出现 ≥2 个实体。**同一个问题可以同时是定义类与关系类** ——
单一 intent 在结构上无法表达。

**修法**：`primary_intent` + `secondary_intents[]` 多标签。

```json
{"primary_intent":"clinical_case",
 "secondary_intents":["concept_definition","freud_to_lacan"]}
```

`test_05_multi_intent_model` 断言：`secondary_intents` 至少有一条非空
（否则等于没改），且 primary 不重复出现在 secondary。

## 4. Evidence Grade（§3）

```json
"gold_evidence": {"required": [...], "strong": [...], "contextual": []}
```

| 级 | 判定规则（脚本） | 含义 |
|---|---|---|
| `required` | 命中 **≥2 个不同写法** | 更可能真的在讨论该概念 |
| `strong` | 命中 1 个高区分度写法 | 相关但把握较低 |
| `contextual` | **留空** | 不自动填充 |

**`required` 可以为空**（§3 明确允许）。实测 45 条中 **4 条有 required**、
40 条有 evidence、**5 条无任何 evidence**（如实留空，**没有为填 schema 而虚构**）。

## 5. ★ 诚实标注：这不是 fully human adjudicated

`review_status = "adjudicated_script_assisted"`。

| 环节 | 谁做的 |
|---|---|
| 查询撰写 | **人** |
| 分级维度设计 | **人** |
| passage 解析与验证存在 | 脚本（多写法共现 → required） |
| 第二独立标注者复核 | **无** |

因此：
* **不得**标 `reviewed` —— 没有第二个标注者
* `annotation.note` 明确写「passage 仍是词面匹配推导，gold_evidence 可争议」
* **这是中间态**，不是终点

## 6. 覆盖（§2 的 12 类）

| primary_intent | 条数 |
|---|---:|
| concept_definition | 6 |
| conceptual_relation | 5 |
| diachronic_development | 5 |
| seminar_specific | 4 |
| exact_source | 4 |
| clinical_case | 4 |
| freud_to_lacan | 3 |
| philosophy_to_lacan | 3 |
| matheme | 3 |
| topology | 3 |
| translation_terminology | 3 |
| cross_language_zh_fr | 2 |
| **合计** | **45** |

## 7. 校验

`test_phase3b_contracts.py`：

* `test_00` schema 完整（§2 要求的 11 个字段）
* `test_01` 12 类 intent 全覆盖
* `test_02` **338 个 gold passage ID 全部真实存在** → 0 缺失（新硬门禁）
* `test_03` evidence grade 结构正确、不虚构
* `test_04` `review_status` 诚实取值
* `test_05` 多标签模型真的被使用
