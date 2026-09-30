# QUERY_MODEL.md — QueryPlan 模型

> 版本 `1.1.0`　·　实现：`_scripts/_tools/query_router.py`（**344 行**）
> 总纲：`RETRIEVAL_ARCHITECTURE.md`　·　评测：`RETRIEVAL_EVALUATION.md`
>
> ⚠️ **时点说明**：本文档描述该文件在 **344 行**版本时的行为。
> 撰写期间它从 318 行涨到 344 行（修了期号解析、补齐 3 个 intent、调整了判定顺序），
> 本文档已按**当前**版本同步。若行号对不上，
> 以 `grep -n "^def \|\"intent\"\] = " _scripts/_tools/query_router.py` 为准。

---

## 0. 状态

| 项 | 状态 |
|---|---|
| `QueryPlan` 结构 | ✅ 已实现（16 个字段） |
| deterministic 规则解析 | ✅ 纯规则，**不调用任何模型** |
| LLM fallback | ✅ 接口就位，**默认 `None` 不启用** |
| `intent` 覆盖面 | ✅ 评测规范声明的 13 类**全部可产出**（`spec − router = ∅`） |
| 评测 intent 一致率 | 🟡 **61/120**（见 §5.3） |
| `研讨班 XI`（中文+罗马数字） | ✅ **已修**（见 §5.1） |
| `研讨班 11`（中文+阿拉伯数字，无「期」字） | 🔴 仍解析失败（见 §5.1） |
| `ambiguous_entities` 漏报 `case_variant` | ⚠️ 已知语义缺口（见 §5.5） |
| 单字母别名误命中 | 🟡 已知（见 §5.6） |
| alias 索引的 `language` 无区分力 | ⚠️ 已知弱点（见 §5.4） |

---

## 1. 设计纪律：deterministic first

用户 §5 硬要求，原话落在代码里（`query_router.py:6-9`）：

> 优先 deterministic parsing。能够 deterministic 完成的工作不得强制交给 LLM。
> LLM query analyzer 只能作为可选 fallback。

`route(query, llm_fallback=None)` 的实际行为：

| 条件 | 行为 |
|---|---|
| **默认**（不传 `llm_fallback`） | 纯规则。规则解析不出就返回 `intent="unknown"`，**不猜** |
| 显式传入 callable，且 `intent=="unknown"` 且 `entities` 为空 | 才调用 fallback，结果标 `from_llm_fallback=True` |

`from_llm_fallback` 字段本身就是审计设计：任何一次检索都能回答
「这个 QueryPlan 是规则产出的还是模型产出的」。

**实测**：120 条评测查询里，router 产出 `unknown` 的只有 **3 条** ——
纯规则已覆盖绝大多数查询，不需要 fallback。

---

## 2. QueryPlan 字段（逐字段实测）

来源：`route()` 的返回值。

| 字段 | 类型 | 实测行为 |
|---|---|---|
| `query` | str | 原始查询（strip 后） |
| `intent` | str | 见 §3 的完整枚举 |
| `seminars` | list[str] | 形如 `["seminar.S11"]` |
| `entities` | list[dict] | 走 alias index 精确匹配；每项含 `entity_id` / `matched_alias` / `exact_case` / `match_type` / `language` |
| `ambiguous_entities` | list[dict] | `entities` 中带 `ambiguous_with` 或 `case_variant_of` 的**子集**（在 `entities` 里也保留一份） |
| `quoted_phrases` | list[str] | `"…"` / `“…”` / `「…」` / `『…』`，至少 2 字符 |
| `language` | str \| None | `zh` / `fr` / `en` / `mul`，由字符谱判定 |
| `periods` | list[str] | 映射到 Phase 1 的 `concept_period` 枚举值 |
| `topology` / `discourses` / `mathemes` / `cases` | list[str] | 四张关键词表的命中实体 ID |
| `authority` | list[str] | `L1`–`L4` |
| `source_hints` | list[str] | `freud` / `lacan.com` / `seminar` / `ecrits` |
| `filters` | dict | 已就绪的过滤条件（供检索层直接用） |
| `from_llm_fallback` | bool | 是否走了 LLM fallback |

### 2.1 `filters` 的填充规则（实测）

| 触发 | 写入 |
|---|---|
| 识别到期号 | `filters["seminar_ids"] = ["seminar.S11"]` |
| 识别到分期 | `filters["periods"] = ["1974-1976"]` |
| 识别到权威词 | `filters["authority_levels"] = ["L1"]` |

未触发时 `filters` 为 `{}` —— **不写空值占位**，避免下游把「未约束」与「空约束」混淆。

### 2.2 `language` 判定规则

| 条件 | 结果 |
|---|---|
| 同时含 CJK 与拉丁字母 | `mul` |
| 只含 CJK | `zh` |
| 只有拉丁字母 + 含法语变音符号 `[àâäéèêëïîôöùûüÿçœæ]` | `fr` |
| 只有拉丁字母、无法语变音 | `en` |

注意这与 alias index 的 `language` 判定**规则不同**（那边对纯拉丁返回 `und`，不猜 fr/en）——
两处口径不一致是已知问题，见 §5.4。

---

## 3. `intent` 枚举（照抄代码实际会产出的值）

判定顺序**即优先级**（`query_router.py:255-280`）：

| 顺序 | intent | 触发条件 |
|---:|---|---|
| 1 | `translation_terminology` | 匹配译法关键词（`翻译`/`译法`/`怎么译`/`译成`） |
| 2 | `philosophy_relation` | 匹配哲学家/哲学关系线索 |
| 3 | `secondary_interpretation` | 匹配二手解读线索（如 `Miller` / `齐泽克` + `解读`） |
| 4 | `exact_quotation` | 有 quoted phrase |
| 5 | `case_analysis` | 命中个案表 |
| 6 | `topology_matheme` | 命中拓扑或数学型 |
| 7 | `discourse` | 命中话语表 |
| 8 | `diachronic_concept` | 有分期 **且** ≥1 个实体 |
| 9 | `seminar_specific` | 有期号 **且** 有实体 |
| 10 | `concept_relationship` | ≥2 个实体 |
| 11 | `concept_lookup` | 恰好 1 个实体 |
| 12 | `freud_lacan_comparison` | 含 `freud` / `弗洛伊德` |
| 13 | `cross_language` | `language == "mul"` |
| — | `unknown` | 以上全不命中（**没有兜底猜测**） |

> **顺序变更记录**：`translation_terminology` 原先排在第 9 位（在 `concept_lookup` 之后），
> 导致「含已知概念的译法查询」永远走不到它 —— **该分支实际不可达**。
> 现已提到第 1 位，实测 `jouissance 中文怎么译` → `translation_terminology` ✅。

实测在 120 条评测查询上的产出分布：

```
concept_relationship 35 · concept_lookup 17 · diachronic_concept 10
exact_quotation 10 · topology_matheme 10 · case_analysis 7
translation_terminology 7 · philosophy_relation 6 · discourse 5
secondary_interpretation 5 · unknown 3 · seminar_specific 2
freud_lacan_comparison 2 · cross_language 1
```

**覆盖完整性实测**：评测规范声明的 13 类 intent，
`spec − router = ∅`（**全部可产出**）；`router − spec = {unknown}`。

---

## 4. 实测：5 个真实查询的 `explain()` 输出

以下全部是 `python3 _scripts/_tools/query_router.py "<query>"` 的**原样输出**。

### 4.1 `研讨班 XI 里的 objet a`

```
QueryPlan:
  intent          : topology_matheme
  language        : mul
  seminars        : ['seminar.S11']
  periods         : —
  quoted_phrases  : —
  entities        : concept.objet-petit-a(objet a), concept.l-autre(A)
  mathemes        : ['matheme.objet-a']
  authority       : —
  source_hints    : ['seminar']
  filters         : {"seminar_ids": ["seminar.S11"]}
```

**中文 + 罗马数字**的期号已能解析（`filters.seminar_ids` 生效）——
这正是 §5.1 记录的修复。

⚠️ 但注意 `entities` 里有一个**误命中**：`concept.l-autre(A)`。
`A` 是单字母别名，被 `_candidate_aliases()` 的单 token 分支捕获。
它把实体数从 1 抬到 2，可能影响 intent 判定。见 §5.6。

### 4.2 `jouissance 中文怎么译`

```
QueryPlan:
  intent          : translation_terminology
  language        : mul
  seminars        : —
  periods         : —
  quoted_phrases  : —
  entities        : concept.jouissance(jouissance)
  authority       : —
  source_hints    : —
  filters         : {}
```

译法类查询**即使含已知概念**也能正确分类（因为该分支已提到最前）。

### 4.3 `拉康与黑格尔的主奴辩证法`

```
QueryPlan:
  intent          : philosophy_relation
  language        : zh
  seminars        : —
  periods         : —
  quoted_phrases  : —
  entities        : —
  authority       : —
  source_hints    : —
  filters         : {}
```

`philosophy_relation` 现已存在（此前为 `unknown`）。

### 4.4 `四种话语是什么`

```
QueryPlan:
  intent          : discourse
  language        : zh
  seminars        : —
  periods         : ['1967-1971']
  quoted_phrases  : —
  entities        : —
  discourses      : ['discourse.four-discourses']
  authority       : —
  source_hints    : —
  filters         : {"periods": ["1967-1971"]}
```

`"四种话语"` 在分期表里也注册为 `1967-1971` 的线索词（S17 时期），
所以即使用户没写年份，也拿到了分期约束。

### 4.5 `「无意识像语言一样被结构」`

```
QueryPlan:
  intent          : exact_quotation
  language        : zh
  seminars        : —
  periods         : —
  quoted_phrases  : ['无意识像语言一样被结构']
  entities        : —
  authority       : —
  source_hints    : —
  filters         : {}
```

引号被识别成 `quoted_phrases`，intent 直接定为 `exact_quotation` ——
这是「精确引文检索」与「概念检索」分流的依据。

---

## 5. 已确认的缺陷与已修项

### 5.1 期号解析：`研讨班 XI` **已修**，但另有两种写法仍失败

**已修**：`query_router.py:116-119` 新增了中文 + 罗马数字的分支，
注释写明「实测原先解析失败」：

```python
# 「研讨班 XI」/「Seminar XI 期」这类**中文 + 罗马数字**写法（实测原先解析失败）
m = re.search(r"研讨班\s*([IVXLC]{1,7})\b", text, re.I)
```

| 输入 | 修复前 | **现在** |
|---|---|---|
| `研讨班 XI` | `[]` ❌ | **`[11]`** ✅ |
| `研讨班11期` | `[11]` | `[11]` ✅ |
| `研讨班第十一期` | `[11]` | `[11]` ✅ |
| `S11` / `Seminar 11` / `Seminar XI` / `第十一期` | `[11]` | `[11]` ✅ |

**仍未解析的两种写法**：

| 输入 | 结果 | 原因 |
|---|---|---|
| `研讨班 11`（中文 + 阿拉伯数字，**无「期」字**） | `[]` ❌ | 阿拉伯数字分支要求 `期` 字 |
| `研讨班XI里的objet a`（罗马数字后紧跟汉字） | `[]` ❌ | 新增分支用了 `\b`；`XI里` 之间不存在 ASCII 词边界 |

**影响**：`filters.seminar_ids` 不生成 → 静默返回全库结果。
Bundle 应告警 `QUERY_CONSTRAINT_UNPARSED`（见 `EVIDENCE_BUNDLE.md §5`）。

### 5.2 评测规范的 13 类 intent **现已全部可产出** ✅

| spec 声明的 intent | router 能否产出 |
|---|---|
| `philosophy_relation`（6 条） | ✅ 现已实现 |
| `secondary_interpretation`（5 条） | ✅ 现已实现 |
| `translation_terminology`（8 条） | ✅ 现已可达（判定顺序前移） |

**该缺口已闭合**：实测 `spec − router = ∅`。

### 5.3 intent 标注一致率实测 **61/120**

```
120 条评测查询中 intent 与规范标注一致: 61 / 120 （不一致 59）
```

（本文档早期版本的该数字是 43/120；随着 router 补齐 3 个 intent 与期号解析，
已提升到 61/120。）

**残留不一致的主因**（需进一步定位）：

1. 单字母别名 `A` 等**误命中**使实体数虚增 1 → 从 `concept_lookup` 跳到
   `concept_relationship`（见 §5.6）；
2. `spec` 的 `intent` 标签是**目标标签**，部分条目的期望分类与规则的
   自然判定顺序不同（例如既有分期又有多个实体时，规范可能标
   `diachronic_concept`，而 router 因顺序先给出 `concept_relationship`）。

**结论**：61/120 这个数字**不能**解释为「router 准确率 51%」。
它衡量的是「规范的目标标签」与「router 当前行为」的差距 ——
即**待办清单的规模**，不是质量分数。
评测时必须区分「测 router 现状」与「测目标分类」。

### 5.4 alias index 的 `language` 对拉丁别名无区分力

`build_alias_index.detect_lang()` 对纯拉丁文本返回 `und`（**刻意不猜** fr/en）。
实测（alias 索引未变）：

| 来源 | 条目数 | 语言标注 |
|---|---:|---|
| `concept.fr` | 60 | `fr` **1** 条、`und` **59** 条 |
| `concept.en` | 68 | `und` **68** 条 |

总分布：`{und: 375, zh: 226, mul: 64, fr: 1}`。

所以任何「按语言过滤 alias」的逻辑都会静默丢掉几乎全部法语与英语条目。
当前 router 不按语言过滤 alias，故未触发；但这是**必须补的已知弱点**。

### 5.5 `ambiguous_entities` 会漏掉「写法存在但库中没有」的情况

实测 `exact_lookup("l'autre")`：

```jsonc
{ "entity_id": "concept.l-autre", "matched_alias": "l'Autre",
  "match_type": "case_variant", "case_sensitive": true,
  "ambiguous_with": [],                    // ← 空
  "ambiguity_reason": "大小写理论词：语料同时使用大小写两种形式…" }
```

而 `route()` 的判定条件是：

```python
if h.get("ambiguous_with") or h.get("case_variant_of"):
    plan["ambiguous_entities"].append(rec)
```

对 `l'autre`：`ambiguous_with` 为空、`case_variant_of` 也为 `None`
（因为 `l'autre` 与 `l'Autre` 指向**同一个**实体），**不会**进入 `ambiguous_entities`。

实测：

| 查询 | `ambiguous_entities` |
|---|---|
| `l'Autre 和 l'autre 有什么区别` | `[]` ❌ 未标 |
| `signifiant 是什么` | 2 条（跨实体碰撞）✅ |
| `圣状 和 sinthome` | 多条 ✅ |

**问题**：`l'autre` 这条查询里，「你要的小他者本库没有」这个信息
**只存在于 `entities[].match_type == "case_variant"` 里**。

`ambiguity_reason` 有值也**不能**当作「有歧义」的信号 ——
它在这里是解释大小写敏感性的说明文字。

**影响面**：`EVIDENCE_BUNDLE.md §7.1` 已把「Bundle 告警须同时检查
`match_type == "case_variant"`」列为实现要求。

### 5.6 单字母别名误命中 🟡

`_candidate_aliases()` 会把查询里的**单个 token** 也当作候选别名。
实测 `objet petit a 是什么` 与 `研讨班 XI 里的 objet a` 都额外命中
`concept.l-autre`（来自别名 `A`）。

**影响**：实体数虚增 → intent 从 `concept_lookup` 跳到 `concept_relationship`。
（这是 §5.3 残留不一致的主因之一。）

**可选修法**（未做）：对长度 ≤2 的拉丁别名要求词边界 + 大小写敏感匹配，
或不把单字符别名纳入候选召回。

---

## 6. 复核命令

```bash
cd <HOME>

# 单条查询
python3 query_router.py "研讨班 XI 里的 objet a"

# 期号解析逐条验证（含仍失败的两种写法）
python3 -c "
from query_router import _seminar_from
for t in ['研讨班 XI','研讨班 11','研讨班XI里的objet a','研讨班11期','Seminar XI','第十一期']:
    print(repr(t), '->', _seminar_from(t))"

# intent 覆盖完整性 + 一致率
cd ../.. && python3 -c "
import json,sys; sys.path.insert(0,'_scripts/_tools')
from query_router import route
rows=[json.loads(l) for l in open('_data/retrieval_eval_spec.jsonl',encoding='utf-8') if l.strip()]
got={route(r['query'])['intent'] for r in rows}
spec={r['intent'] for r in rows}
print('spec - router =', spec-got)
print('一致率:', sum(1 for r in rows if route(r['query'])['intent']==r['intent']), '/', len(rows))"
```

---

*配套：`RETRIEVAL_ARCHITECTURE.md` · `LEXICAL_INDEX.md` · `HYBRID_RETRIEVAL.md` ·
`EVIDENCE_BUNDLE.md` · `RETRIEVAL_EVALUATION.md`*
