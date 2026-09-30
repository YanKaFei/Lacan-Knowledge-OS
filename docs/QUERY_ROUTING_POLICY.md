# QUERY_ROUTING_POLICY.md — Phase 3C §9–§10

> 代码：`_scripts/_tools/query_routing_policy.py`　·　判定是**规则式**的，每条 route 都带 `why`（哪条规则命中），不是黑箱打分。

## 0. 为什么需要按 query class 路由

Phase 3B.2 / 3C 实测：**向量不是普适增益**。

| query class | 实测 | 结论 |
|---|---|---|
| FR 单语 | `L` **0.3125** > `E+L+V` 0.2500 | 向量**负贡献** → 默认关闭 |
| ZH→FR | 纯向量 **0.0000** | 主要机制是 `X`（术语桥），向量只作补充 |

所以「所有 query 都跑 E+L+V+X」是错的。§10 明确要求 `vector_enabled=false` 是一等能力，并且要有 `vector_weight` / `vector_candidate_limit`。

## 1. Routing table

| route | components | vector_enabled | weight | cand_limit | lanes | guard | 规则 |
|---|---|---:|---:|---:|---|---|---|
| `EXACT_QUOTATION` | exact + lexical + metadata | **❌ 关闭** | 0.0 | 0 | 1 | — | 查询里带引号短语 —— 用户要的是**字面出处**，语义近邻只会引入噪声 |
| `EXACT_SOURCE_LOOKUP` | exact + lexical + metadata | **❌ 关闭** | 0.0 | 0 | 1 | — | 查询里出现 passage/session/seminar 等 ID —— 精确定位，向量无意义 |
| `FR_MONOLINGUAL` | entity + lexical + metadata | **❌ 关闭** | 0.0 | 0 | 1 | — | 法语单语查询：Phase 3C 实测 `L` 优于含向量的配置（0.3125 vs 0.2500）→ 默认关向量 |
| `ZH_TO_FR` | entity + x + lexical + vector + metadata | ✅ | 0.5 | 200 | 1 | — | 中文问 → 需要法文证据：主要机制是 Terminology Bridge `X`，向量作补充 |
| `CONCEPTUAL_PARAPHRASE` | entity + lexical + vector + x | ✅ | 0.5 | 200 | 1 | — | 概念性改写（不是问句也不是引文）：实体 + 词法 + 向量 + 跨语言桥 |
| `CONCEPT_COMPARISON` | entity + lexical + vector | ✅ | 0.4 | 100 | per_concept | — | 涉及 ≥2 个概念 —— **每个概念独立 lane**（§9），最后才在证据层比较 |
| `DIACHRONIC` | entity + lexical + period + diversity + vector | ✅ | 0.3 | 120 | 1 | — | 历时性概念问题：期号感知 + 证据多样性为主，向量只作低权重补充 |
| `CONTRASTIVE_TERMINOLOGY` | guard + entity + lexical + vector + x | ✅ | 0.4 | 100 | per_contrastive_side | ✅ | Semantic Guard 命中 contrastive 配对 → **禁止合并**，每侧独立 lane（§8） |
| `SEMINAR_SPECIFIC` | entity + lexical + metadata + vector | ✅ | 0.3 | 120 | 1 | — | 查询显式限定研讨班：精确 subset 为主，向量低权重 |
| `AMBIGUOUS_ENTITY` | entity + lexical | **❌ 关闭** | 0.0 | 0 | 1 | — | 实体歧义且无线索 —— **不静默解析**，返回歧义候选让用户选（§9） |
| `GENERAL` | entity + lexical + vector + x | ✅ | 0.4 | 150 | 1 | — | 没有命中任何专门规则的兜底路径 |

## 2. 判定优先级

```
 1. CONTRASTIVE_TERMINOLOGY（Guard 命中，最高优先）
 2. EXACT_QUOTATION（引号）
 3. EXACT_SOURCE_LOOKUP（ID）
 4. AMBIGUOUS_ENTITY（歧义且无线索 → 不静默解析）
 5. DIACHRONIC
 6. CONCEPT_COMPARISON（≥2 概念 → 分 lane）
 7. SEMINAR_SPECIFIC
 8. FR_MONOLINGUAL
 9. ZH_TO_FR
10. CONCEPTUAL_PARAPHRASE
11. GENERAL（兜底）
```
**优先级顺序本身就是设计决定**：Guard 最高，因为一旦涉及必须区分的概念，任何「先合并再排序」的做法都会把区分弄丢；歧义解析排在精确匹配之后，因为引号和 ID 是用户显式给出的约束，不该被实体歧义挡住。

## 3. 向量关闭不是「算了但权重 0」

`vector_enabled=False` 时下游**不得计算向量**：`vector_candidate_limit = 0`，并且 `vector_disabled_reason` 会写进 Evidence Bundle。理由很实际 —— 全量索引上一次暴力余弦是几十毫秒，关掉它是真实的延迟收益，也是真实的**质量**收益（FR 单语实测）。

## 4. 歧义不静默解析（§9）

`AMBIGUOUS_ENTITY` 返回的是**歧义候选列表**，不是替用户选好的答案。实测有 42 条歧义别名（`alias_collisions.jsonl`），把其中一个静默当真会造成来源不明的结论。

## 5. 复现

```bash
python3 _scripts/_tools/query_routing_policy.py --route "Réel 和 réalité 有什么区别？"
python3 _scripts/_tools/query_routing_policy.py --table
```
