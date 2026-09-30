# Topicality Model — Phase 4C

## 1. 问题

「存在若干检索命中」≠「KB 对该主题具有足够知识」。
`rt-J02` 的 10 条证据全部是旁及提及；`rt-J01` 的法文写法只有 1 段，
但中文语料有 241–270 段实质讨论。**条数本身不说明主题性。**

## 2. 信号（全部可审计，见 `evidence[].topic_signals`）

| 信号 | 含义 | 实现 |
|---|---|---|
| `topic_occurrences` | 该段里主题词出现几次 | 去标点/空白/变音后子串计数 |
| `entity_linked` | 该段是否连着已解析实体 | 实体写法命中 ∪ concept card link |
| `core_concept_cooccurrence` | 是否同时出现核心拉康概念 | 53 条概念卡的 fr/en/zh 形式池 |
| `neighbour_persistence` | 同 session ±2 段是否也出现主题词 | store 原序邻域扫描 |
| `terminology_bridge` | 是否由术语桥召回 | `why_retrieved` |
| `corpus_prevalence` | 主题词在全库的精确命中数 | 词法索引 COUNT（最紧变体） |
| `discriminating_terms` | 哪些词算主题词 | 有实体者优先；其余按命中数剔掉泛用词 |
| `absence_profile` | 「没有找到什么」 | 无实体 / 无关系证据 / 无 primary 专门论述 |
| `structural_unanswerability` | 结构上做不到的事 | 五类，见 v2 §4 |

**没有模型打分、没有概率层。** 若将来引入模型辅助，只能作为
`candidate signal`，不能成为唯一判据（§9）。

## 3. 有效 / 无效的信号（实测）

**有效**：

1. `discriminating_terms` + `corpus_prevalence` —— 把 `fMRI`(0) 与
   `拉康`(2511)、`看待`(140) 分开，是 J02 被正确降级的**主因**；
2. `entity_linked` + `core_concept_cooccurrence` —— 把 DIRECT 与 INCIDENTAL 分开；
3. `absence_profile` —— 「无实体 + 无关系 + 无 primary 专门论述」构成可读的弃权理由；
4. 结构性分类 —— METADATA_UNAVAILABLE / FORMALISM_MISSING 是**确定性**判据，
   不依赖任何主题性猜测。

**无效或需谨慎**：

1. **纯条数**（v1 的做法）：10 条旁及 ≫ 1 条直接 —— 已废弃为主判据；
2. **不加过滤的中文片段当术语**：`黑格尔的主人`、`进入拉康的欲望理论` 这类句子片段
   命中接近 0，会让 `TOPIC_NOT_COVERED` 误触发（已按 >8 汉字剔除）；
3. **中文 bigram AND 计数**：会把不存在的词算成几百段（莫比乌斯 270）；
4. **把拓扑对象名当「形式化诉求」**：导致 J01 误判（已窄化为符号/数学型）；
5. **`neighbour_persistence` 成本较高**（每段一次邻域扫描），当前只用于加强 DIRECT 判定。

## 4. 已知边界

* 主题性仍是**词面 + 结构**的近似：语义层面的「这段是否在论证该问题」需要人；
* `core_concept_cooccurrence` 只说明「同段出现」，不代表论证关联；
* 语料缺词形时（如公式符号）会低估主题性 —— 这正是 FORMALISM_MISSING 的用途，
  但它也是**最需要人裁决**的一类（rt-H02 已在队列里）。
