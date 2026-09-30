# LACANIAN_SEMANTIC_GUARD.md — Phase 3C §7

> 代码：`_scripts/_tools/lacanian_semantic_guard.py`　·　配对来源：`_data/terminology_bridge.jsonl`（`relation_type = distinct_from`）

## 0. 这个 Guard 解决什么

通用 embedding 会把理论上必须区分的近义项压平。**§7 明确禁止用「调高 embedding 权重」来掩盖**。所以 Guard 不动 embedding，它在**检索结构**上阻止合并：

1. **识别** —— query 是否同时涉及某组配对的两侧；
2. **分道** —— 每侧一条独立 lane，且 lane query **显式排除另一侧的写法**；
3. **如实报警** —— 本库实测发现的问题必须报出来，不假装能区分。

## 1. ★ 必须先说的事实：一部分「压平」发生在**知识库层**，不在 embedding

§6 点名的 7 组配对，逐一去 concept store 里查 entity 绑定，结果是：

| 配对 | 一侧 entity | 另一侧 entity | 绑定状态 |
|---|---|---|---|
| `Autre` / `autre` | `concept.l-autre` | `concept.l-autre` | **ENTITY_COLLISION** |
| `Réel` / `réalité` | `concept.le-reel` | **无** | **COUNTERPART_ENTITY_MISSING** |
| `désir` / `demande` | `concept.desir` | **无** | **COUNTERPART_ENTITY_MISSING** |
| `besoin` / `demande` | **无** | **无** | **BOTH_ENTITIES_MISSING** |
| `objet` / `objet a` | **无** | `concept.objet-petit-a` | **COUNTERPART_ENTITY_MISSING** |
| `sujet` / `moi` | `concept.sujet` | **无** | **COUNTERPART_ENTITY_MISSING** |
| `signifiant` / `signifié` | `concept.le-symbolique`, `concept.signifiant` | **无** | **COUNTERPART_ENTITY_MISSING** |

**只有 `Autre/autre` 两侧都有 entity，而且两侧落到同一个 entity；其余 6 组至少一侧没有 entity。**

这意味着：**通用 embedding 压平这些区分，一部分原因是知识库自己没有为其中一侧建立实体。** 把责任全推给 embedding 是不诚实的。

Guard 的回应不是假装能区分，而是：

- `ENTITY_COLLISION`（Autre/autre）：**禁止 equivalent 扩展**，两条 lane 以表面形式为键；
- `COUNTERPART_ENTITY_MISSING`（5 组）：缺失侧**不生成任何等价关系**，lane 标记 `unbound_side`；
- `BOTH_ENTITIES_MISSING`（besoin/demande）：完全依赖表面形式。

**要把这些区分真正建立起来，需要先补概念实体（知识工程），而不是换更大的模型。**

## 2. 报警码

| 码 | 触发条件 | 严重度 | 动作 |
|---|---|---|---|
| `ENTITY_COLLISION` | 配对两侧绑到同一 entity | high | 禁止 equivalent 扩展；lane 以表面形式为键 |
| `COUNTERPART_ENTITY_MISSING` | 配对一侧无 entity | medium | 缺失侧只用自己的表面形式；标 `unbound_side` |
| `BOTH_ENTITIES_MISSING` | 两侧都无 entity | medium | 两条 lane 均用表面形式；不生成 equivalent |

## 3. 「降低混淆」怎么被测量

分道之后，两个概念的候选**只在各自 lane 内排序**，跨 lane 混入是可检测的（lane 归属写在 evidence entry 上）。因此可以分别报告：

- **Raw Vector Contrastive Pass** —— 纯 embedding 自己在候选集里能不能排对；
- **System Contrastive Pass** —— Guard + 分道之后，最终系统能不能保住区分。

§16 要求两者**分开报告**，见 `ROUTED_RETRIEVAL_EVALUATION.md`。

## 4. 样例

```
query: Réel 和 réalité 有什么区别？
flattening_risk: medium
lanes_required: 2
  lane tb.distinct.02.a  表面形式=Réel  entity=['concept.le-reel']
     query_forms   = ['Réel', 'Réel：实在界', 'impossible', 'le réel', 'the Real', '实在界']
     excluded_forms= ['realite']
  lane tb.distinct.02.b  表面形式=réalité  entity=[]
     query_forms   = ['réalité']
     excluded_forms= ['impossible', 'le reel', 'realite', 'reel', 'reel 实在界', 'the real', '实在界']
```

**`excluded_forms` 非空就是防压平的实证**：另一侧的写法被明确挡住，不会在本 lane 里把两个概念重新混起来。

