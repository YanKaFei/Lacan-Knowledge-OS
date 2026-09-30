# TERMINOLOGY_BRIDGE.md — Phase 3C §5–§6 Cross-lingual Terminology Bridge

> 构建：`_scripts/_tools/build_terminology_bridge.py`　·　读取 API：`_scripts/_tools/terminology_bridge.py`　·　数据：`_data/terminology_bridge.jsonl`

## 0. X 不再是 preprocessing hack

Phase 3B.2 实测：跨语言检索的主要有效增益来自 `X`，不是纯 embedding。因此 3C 把它升为**一级检索组件**：自己的 schema、自己的文件、自己的 API、自己的审计，而不是散在 benchmark 里的几行代码。

| 项 | 值 |
|---|---:|
| 映射条数 | **2605** |
| `equivalent`（可扩展查询） | **2598** |
| `distinct_from`（**禁止**等同） | **7** |
| 覆盖 entity | **53** |
| 语言 | en, fr, und, zh |

## 1. Schema：每条 11 个必需字段（§5）

`term_id` · `source_form` · `source_language` · `target_form` · `target_language` · `entity_id` · `relation_type` · `status` · `review_status` · `source` · `notes`

示例（equivalent）：

```json
{
 "term_id": "tb.acting-out.en.fr.001",
 "source_form": "acting out",
 "source_language": "en",
 "target_form": "acting out",
 "target_language": "fr",
 "entity_id": "concept.acting-out",
 "relation_type": "equivalent",
 "status": "active",
 "review_status": "candidate",
 "source": "concept_store:concept.acting-out"
}
```

## 2. `relation_type` 只有两种，规则写进代码

| 取值 | 含义 | X 能否用它扩展查询 |
|---|---|---|
| `equivalent` | **同一个 `entity_id`** 的跨语言写法 | ✅ **只有它可以** |
| `distinct_from` | **必须区分、不得等同**的配对 | ❌ **结构性排除** |

`terminology_bridge.expand()` 只遍历 `equivalent` 记录 —— 不是靠调用方记得不要用 `distinct_from`，而是**这个函数根本不返回它们**。

## 3. §6：依赖 entity identity，不是字符串翻译

`equivalent` 的生成条件是**两侧 `entity_id` 相同**。任何只靠字符串相似、没有同一 entity 的候选，**一律不生成 equivalent**。

### 3.1 ★ 本轮查出来的事实（必须写进报告）

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

这条事实的含义：**通用 embedding 压平这些区分，一部分原因是知识库自己也没有为其中一侧建立实体。** 把责任全推给 embedding 是不诚实的。真正的修法是**补概念实体（知识工程）**，而不是换更大的模型。

## 4. API

```python
import terminology_bridge as tb
tb.expand('小客体a', target_langs=('fr',))  # → [(target_form, entity_id, term_id)]
tb.distinct_pairs()                        # §6 的 7 组「必须区分」
tb.is_distinct('Autre', 'autre')           # → True
tb.lexical_forms_for_entity(eid)           # 该 entity 的全部 surface forms
```

## 5. 审计

```bash
python3 _scripts/_tools/build_terminology_bridge.py --audit
```

审计会检查：任一配对**不得同时**是 `equivalent` 与 `distinct_from`；文件 hash 与 audit 记录一致；`distinct_from` 条数必须等于 §6 点名的 7 组。

## 6. 边界

- `equivalent` 的 `review_status = candidate` —— **没有人工逐条审阅**，它由 concept 卡片的显式字段推导。
- 别名语言靠启发式判定（`fr` 标记 / CJK 检测），`source_language` 的可靠性低于 concept 卡片的显式 `zh`/`fr`/`en` 字段。
- 它**不解决**知识库的 entity 合并问题 —— 那是 §7 Guard 报 `ENTITY_COLLISION` 的事。
