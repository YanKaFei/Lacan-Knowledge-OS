# LEXICAL_INDEX.md — 词法检索基线

> 版本 `1.0.0`
> 实现：`_scripts/_tools/build_lexical_index.py`（建索引 + benchmark）
> 　　　`_scripts/_tools/lacan_search.py`（查询接口）
>
> ⚠️ **时点说明**：`lacan_search.py` 在本文档撰写期间**持续变化**
> （242 → 388 → 395 行，还在长）。新增的机制包括 `syntax_variants()`（§4.2）
> 与 `expand_aliases()`（§4.3）。
>
> **本文档刻意以「机制 + 函数名」描述，而不是以行号描述** —— 行号会烂，
> 机制不会。文中出现的行号仅供定位参考；**对不上时以**
> `grep -n "^def " _scripts/_tools/lacan_search.py` **的实际输出为准**。
> §4.2 / §4.3 / §4.4 的结论都做过实测复现（命令见 §9），不依赖行号。
> 产出：`_data/index/lexical.sqlite` · `_data/index/tokenizer_benchmark.json`
> 总纲：`RETRIEVAL_ARCHITECTURE.md`

---

## 0. 状态

| 项 | 状态 | 证据 |
|---|---|---|
| FTS5 索引 | ✅ 已建 | `_data/index/lexical.sqlite`（241 MB） |
| 法语策略 | ✅ 已 benchmark 并锁定 C | `tokenizer_benchmark.json` → `french.chosen` |
| 中文策略 | ✅ 已 benchmark 并锁定 B | `tokenizer_benchmark.json` → `chinese.chosen` |
| 查询接口 | ✅ 已实现 | `lacan_search.lexical_search()` |
| 多档查询升级 | ✅ 已实现 | `lacan_search.syntax_variants()`（§4.2） |
| 别名扩展 | 🟡 已实现，但适用范围窄 | `lacan_search.expand_aliases()`（§4.3 / §4.4 缺陷） |
| 确定性 | ✅ 有测试 | `test_phase3_lexical.py::test_06` |
| 可重建 | ✅ 有测试 | `test_phase3_lexical.py::test_07` |
| **INDEX_MANIFEST.json** | ✅ **已产出** | vault 根；覆盖 lexical + alias，`embedding: null`（§6） |

三个测试套件中，本层由 `test_phase3_lexical.py`（**12 项**）覆盖，实测全绿。

---

## 1. 为什么用 SQLite FTS5

Phase 1 环境勘察已实测：本机 SQLite **3.51.0 支持 FTS5**
（`create virtual table … using fts5` 成功）。

因此**不引入外部检索引擎**：索引是单文件、无服务依赖、可整体重建、
便于 diff 与审计。这与 `ARCHITECTURE.md` 的「派生物可重建」原则一致。

---

## 2. 表结构（实测 `sqlite_master`）

### 2.1 `passage_meta` —— 249,105 行

```sql
CREATE TABLE passage_meta (
    id TEXT PRIMARY KEY,               -- passage.S<NN>.<date>[.L<NN>].P<nnnn>
    session_id TEXT NOT NULL,
    seminar_id TEXT NOT NULL,
    language TEXT NOT NULL,            -- fr | zh
    lesson INTEGER,
    session_date TEXT NOT NULL,        -- YYYY-MM-DD | unknown
    session_date_precision TEXT NOT NULL,
    text_role TEXT NOT NULL,           -- transcription | translation | edition
    authority_level TEXT NOT NULL,     -- L1 | L2
    review_status TEXT NOT NULL,
    status TEXT NOT NULL,              -- recovered
    canonical INTEGER NOT NULL,        -- 0（全库无 canonical）
    trace_status TEXT NOT NULL,
    witness_id TEXT,
    corpus_source_id TEXT,
    document_id TEXT,
    raw_text TEXT NOT NULL             -- ★ canonical 原文，检索直接返回它
)
```

配套索引：`idx_meta_seminar` / `idx_meta_session` / `idx_meta_lang` /
`idx_meta_trace` / `idx_meta_auth`（5 个，支持 metadata 过滤）。

> `raw_text` 冗余存在检索库里，是为了让命中结果**不必回查** passage store
> 就能返回原文。它来自 canonical store，检索层**只读不改**。

### 2.2 `passage_source_map` —— 249,105 行

```sql
CREATE TABLE passage_source_map (
    passage_id TEXT PRIMARY KEY,
    witness_id TEXT, corpus_source_id TEXT
)
```

来源：`_data/passage_store/passage_realizations.jsonl`（Phase 3 §0 迁移产物）。
用于按 `witness_id` / `corpus_source_id` 过滤（`lacan_search` 支持这两个参数）。

### 2.3 三张 FTS5 表

| 表 | 行数 | tokenizer | 存放什么 |
|---|---:|---|---|
| `fr_fts` | 166,527 | `unicode61 remove_diacritics 2` | 法语**归一化**文本 |
| `zh_fts` | 82,578 | `unicode61` | 中文 **bigram** 串 |
| `zh_fts_trigram` | 82,578 | `trigram` | 中文**原始**文本（仅用于 benchmark 对比） |

三张表都是 `content=''`（外部内容表）—— 正文不在 FTS 表里，
只存索引，正文由 `passage_meta.raw_text` 提供。

实测行数与 canonical store 完全一致：`166,527 + 82,578 = 249,105`。

---

## 3. 法语归一化：一次真实的教训

### 3.1 踩的坑：撇号不能替换成空格

第一版把撇号替换为空格：

```
l'Autre  →  l autr      ← 错！
```

`remove_diacritics 2` 把 `Autre` 折叠成 `autre`……但这里得到的是 **`autr`**
（`Autre` 去掉变音后并不会少字母，问题出在别处：`l'Autre` 先被撇号切成了 `l` + `Autre`，
再做变音折叠与截断处理，产出的是**截断词干**）。

结果：`autr` 既不是 `l` 也不是 `autre`，**查 `Autre` 永远命中不了**。
第一版 benchmark 的法语数字因此完全失真，还给出了**方向相反**的结论
（当时「选定」了最差的 A 策略）。

### 3.2 正确做法（当前实现，`build_lexical_index.py:78-96`）

```python
def norm_fr(s):
    s = unicodedata.normalize("NFKC", s)
    s = _APOS.sub("", s)        # 撇号 → 删除（l'Autre → lautre）
    s = _HYPH.sub(" ", s)       # 连字符 → 空格（Nom-du-Père → nom du pere，三段可检）
    s = strip_accents(s)        # 变音折叠
    s = _NONWORD.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip().lower()
```

| 输入 | 归一化结果 | 为什么 |
|---|---|---|
| `l'Autre` | `lautre` | 保留 elision 的**完整拼写**，不产生截断词干 |
| `Nom-du-Père` | `nom du pere` | 三段（nom / du / pere）**都可独立检索** |
| `plus-de-jouir` | `plus de jouir` | 同上 |
| `désir` | `desir` | 变音折叠 |

### 3.3 查询侧必须生成 elision 变体

同一段法语里，`l'Autre` 既可能以 `lautre` 出现，也可能以独立的 `autre` 出现。
所以查询侧要**两种都给**（`query_variants_fr()`）：

```
>>> query_variants_fr("l'Autre")
['l', 'autre', 'lautre']

>>> syntax_ok("l'Autre", "fr")
'"autre" AND "lautre"'
```

这就是「查 `Autre` 能查到 `l'Autre`」的原因。索引侧与查询侧**必须成对设计**，
只改一侧就会产生无法解释的假阴性。

### 3.4 benchmark 必须是「策略自洽」的

`build_lexical_index.py:288-296` 记下了另一个教训：

> 第一版 benchmark 拿「未归一化的查询词」去查「归一化过的索引」，
> 于是 `l'Autre` 被切成 `l`+`autr` 去 AND 匹配，必然零命中 ——
> **那测的是「假阴性拒答」，不是检索质量。**

现在的做法：每种策略用**它自己的**查询侧处理去查**它自己的**索引侧文本，
并以 ground truth（原始文本子串匹配）计算 recall。

---

## 4. 中文：bigram + **两档升级**（短语优先 → AND 兜底）

### 4.1 为什么需要 bigram

FTS5 没有中文分词。三种策略的实际效果：

| 策略 | 机制 | 问题 |
|---|---|---|
| `unicode61`（原样） | 连续 CJK 变成**一个 token** | 等于不可检索（除非整段完全匹配） |
| `trigram` | 3 字滑窗 | 单字 / 双字查询失效（不足 3 字无 token） |
| **bigram** | 2 字滑窗 | 任意 ≥2 字查询都能命中；1 字退化为单字 |

实现（`build_lexical_index.py:125-153`）：自己在索引前把连续 CJK 切成二元组，
写入空格分隔的 token 串。

```
「大他者」 → "大他 他者"
```

**刻意没有引入 jieba** —— 用户 §3 要求「不得未经 benchmark 锁定任何单一 tokenizer」。
bigram 是无词典方案，不依赖任何第三方分词器。

### 4.2 坑：单一策略必然在两种失败模式之间摇摆 —— 所以是**两档升级**

这是本层第二个真实教训。历史与现状要说清：

**历史（第一版）**：中文查询用 `AND` 连接 bigram。后果：

> bigram 把 `不存在的词` 切成 `不存 存在 在的 的词`，若用 AND，
> 只要其中任一 bigram 命中就返回结果 —— **实测该错误让一个纯噪声查询
> 返回了 5 条无关结果（欧西坦语诗歌）**。

**修法一（短语匹配）**：改成把相邻 bigram 串成 FTS5 **短语**：

```
syntax_ok("大他者", "zh")  →  '"大他 他者"'
```

实测噪声查询降到 **0 条**（`欧西坦语诗歌` / `量子色动力学` 均 0）。
但**过紧**：只做短语匹配时，`凝视 小客体` **零命中** ——
因为这两个词在文本里从不**相邻**，而语料里含「凝视」的段有 341 段。

**修法二（当前实现，`syntax_variants()` @ `lacan_search.py:179`）**：
返回**由紧到松**的多档查询串，短语优先、无结果再退到 AND：

```
>>> syntax_variants("凝视 小客体", "zh")
['"凝视 小客 客体"',        # 第 1 档：整句短语（最精确）
 '"凝视" AND "小客 客体"']   # 第 2 档：按词 AND，每词仍是 bigram 短语
```

`lexical_search()` 逐档尝试，**命中即停**（`lacan_search.py:339-362`）。

设计理由（照抄代码注释，`lacan_search.py:182-189`）：

| 只做一档 | 失败模式 |
|---|---|
| 只做短语 | **过紧** → 大量假阴性（`凝视 小客体` = 0） |
| 只做 AND | **过松** → 假阳性（噪声查询返回无关结果） |

> 所以：短语优先（精确），无结果再退到 AND（宽松）。
> 这样两类失败模式各由一档承担，而不是用一档去同时满足两种需求。

**实测验证**：

| 查询 | 结果 |
|---|---|
| `欧西坦语诗歌` | **0 条** |
| `量子色动力学` | **0 条** |
| `大他者` | 5 条（首条 `passage.S21.unknown.L10.P0099`） |
| `圣状` | 5 条（首条 `passage.S24.unknown.L10.P0062`） |
| `凝视 小客体` | **0 条** ⚠️ 见 §4.4 |

法语仍是 `AND`（`syntax_ok` 第 163-172 行）—— 因为法语归一化后每个 token 是完整词，
不存在 bigram 那类「部分命中」问题。**中文与法语的查询语法不同，这是有意的**。

### 4.3 别名扩展（`expand_aliases()` @ `lacan_search.py:227`）

同一节里新增的另一个机制：查询侧把词扩展成它在 alias index 里的**同义写法**。

```
>>> expand_aliases(["对象a"])
['object a', 'objet a', 'objet petit a', 'objet petit a / object a',
 'objet petit a：对象 (a)', '客体小a', ...]
```

`lexical_search()` 只在**原查询无命中**时才用扩展（`lacan_search.py:290`
注释：「避免稀释精确查询」），且替换是**逐词**进行的
（`word_parts` / `alias_words`，见 `lacan_search.py:297-309`）。

设计意图（照抄注释）：扩展只在**已登记的别名**内进行，**不发明新写法**。

### 4.4 ⚠️ 已发现：`expand_aliases` 无法修复它自己引用的那个例子

`expand_aliases()` 的 docstring 用 `凝视 小客体` 作为motivating example，
并说「缺的不是证据，而是**写法对齐**：`小客体` 与 `对象a` 是同一个概念的不同译名」。

**实测该推论不成立**：

| 检查 | 结果 |
|---|---|
| `expand_aliases(["小客体"])` | **`[]`** ❌ |
| `expand_aliases(["凝视"])` | **`[]`** ❌ |
| `expand_aliases(["对象a"])` | `['object a', 'objet a', ...]` ✅ |
| `lexical_search("凝视 小客体", language="zh")` | **0 条** ❌ |

**根因**：alias index 里登记的是 **`小客体a`** 与 **`客体小a`**（带结尾的 `a`），
**没有 `小客体`**。实测：

```
>>> exact_lookup("小客体")   → 0 条
>>> exact_lookup("小客体a")  → 1 条（concept.objet-petit-a）
>>> exact_lookup("凝视")     → 0 条   ← 它不是别名，是术语
```

而 `expand_aliases()` 走的是 `exact_lookup()` **精确匹配**，
所以未登记的**写法变体**（少一个字符）不会被扩展。

**影响**：

1. 别名扩展的实际适用范围比 docstring 暗示的窄 ——
   只有**逐字命中已登记别名**的查询才会被扩展；
2. `凝视 小客体` 这类「术语 + 常见简称」的查询**仍然 0 条**；
3. `凝视` 不在 alias index 里（它不在 53 条 Gold Concept 中），
   所以无论怎么扩展都不会被覆盖。

**这是"文档与实现不一致"，需在补齐时二选一**：

* 要么把 `小客体` 之类的**写法变体**也登记进 alias index（需人工审核，
  因为它涉及「是否算同一实体」的判定，不能自动做）；
* 要么修订 docstring，不再用它当作已验证的例子。

**注意**：这不否定 `expand_aliases` 的价值 —— 对**已登记**别名它是有效的；
问题只在「它修不了它声称修的那个例子」。

## 5. Tokenizer benchmark 实测数字

文件：`_data/index/tokenizer_benchmark.json`（以下数字**照抄自该文件**）。

### 5.1 法语（19 条查询有 ground truth）

| 策略 | recall_proxy | precision_proxy | 命中查询数 | 选中 |
|---|---:|---:|---:|---|
| `A_raw_query` | 0.789 | 0.249 | 18/19 | |
| `B_accent_only` | 0.789 | 0.249 | 18/19 | |
| **`C_normalized_with_elision_variants`** | **0.895** | 0.222 | **19/19** | ✅ |

选定 **C**。注意 C 的 precision 略低（0.222 vs 0.249）而 recall 明显更高
（0.895 vs 0.789）—— 选择规则（`build_lexical_index.py:411-421`）是
**先 recall 再 precision，平手取字典序最小**，且不依据模型宣传或外部排名。

### 5.2 中文（6 条查询有 ground truth）

| 策略 | recall_proxy | 命中查询数 | 选中 |
|---|---:|---:|---|
| `A_trigram_raw` | 0.333 | 2/6 | |
| **`B_bigram`** | **0.833** | 6/6 | ✅ |
| `C_unicode61_raw` | 0.667 | 4/6 | |

选定 **B（bigram）**。

> ⚠️ **样本量说明**：中文 benchmark 只有 6 条查询，`recall_proxy` 的分辨率是
> 1/6 ≈ 0.167 —— 相邻两个策略之间可能只差 1 条查询。**这个数字不足以支撑
> 「bigram 优于 trigram」的强结论**，只足以排除 `trigram`（0.333 明显偏低）。
> 要真正定论需要更大的查询集，见 `RETRIEVAL_EVALUATION.md`。

### 5.3 选择规则（照抄）

```
按 ground-truth recall_proxy 降序；平手取字典序最小。
不依据模型宣传或外部 benchmark 排名。
```

---

## 6. INDEX_MANIFEST.json：✅ **已产出**

> **状态更新**：本文档早期版本记录「`INDEX_MANIFEST.json` 不存在
> （`manifest()` 已写但从未被调用）」。**该问题已修** ——
> 现在 vault 根有 `INDEX_MANIFEST.json`。

### 6.1 实测内容

```
schema_version : "index-manifest/v1"
corpus         : {passages_jsonl, corpus_hash: 889dd5f9afec…, passage_count: 249105,
                  source_sha256: {zh: 8a109068…, fr: 2712d6da…}}
indices        : [ {name: "lexical", version: "1",
                    artifacts: ["_data/index/lexical.sqlite"],
                    passage_count: 249105,
                    tokenizer: {french: "C_normalized_with_elision_variants",
                                chinese: "B_bigram",
                                normalization: "fr: NFKC+去撇号+连字符→空格+去变音; zh: bigram+短语匹配"},
                    build_config_hash: "1e1bf6914bd73c04",
                    rebuild: "python3 _scripts/_tools/build_lexical_index.py"},
                   {name: "alias", version: "1", artifacts: [...]} ]
embedding      : null
embedding_note : "向量索引**未实现**（Phase 3 只实现 lexical + alias + graph）；
                  字段保留以便后续回填 model/dimensions"
git_policy     : "大型可重建索引不入 git；本 manifest + canonical corpus 可完整重建全部索引"
generated_at   : "2032-02-15T15:10:02+00:00"   ← 内容推导（stamp_mode: deterministic）
content_hash   : "719574da684ad861…"
```

### 6.2 该 manifest 满足 §13 的哪些要求

| §13 要求 | manifest 字段 |
|---|---|
| 索引可重建 | `indices[].rebuild`（给出重建命令） |
| 可自证来源 | `corpus.corpus_hash` + `corpus.source_sha256` |
| 记录 tokenizer 选择 | `indices[].tokenizer`（法语/中文各自选中的策略） |
| 构建配置可追溯 | `indices[].build_config_hash` |
| 大文件不入 git 的策略 | `git_policy` |

**同时修掉的还有一处键名不匹配**：早期 `manifest()` 读的是
`bench_result["chosen_strategy"]`，而 benchmark 实际写的是
`french.chosen` / `chinese.chosen` —— 现在 manifest 里两个值都正确填上了。

### 6.3 `embedding: null` 是一个**正面**的诚实标记

manifest 没有假装向量索引存在，而是：

```json
"embedding": null,
"embedding_note": "向量索引**未实现**（Phase 3 只实现 lexical + alias + graph）"
```

这与 `VECTOR_INDEX.md` 顶部的状态标注、以及
`hybrid_retrieve` 的 `warnings: ["VECTOR_COMPONENT_ABSENT: ..."]`
三处一致 —— **同一个事实在三个地方都说没有**。

对应测试：`test_phase3_retrieval.py::test_19_manifest_matches_corpus_hash` /
`test_20_manifest_index_cli_verifies` / `test_21_large_indices_not_tracked_by_git`。

---

## 7. 如何重建

```bash
cd <HOME>

# 完整重建（建索引 + 跑 benchmark）
python3 _scripts/_tools/build_lexical_index.py

# 只建索引（测试重建用，跳过 benchmark）
python3 _scripts/_tools/build_lexical_index.py --no-bench

# 确定性时间戳（默认内容推导；--stamp 才写真实时间）
python3 _scripts/_tools/build_lexical_index.py --stamp
```

重建**不修改** canonical store，有测试锁住：

```
test_phase3_lexical.py::test_08_does_not_mutate_canonical_store
    比对 passages.jsonl 的 (mtime_ns, size) 前后一致

test_phase3_lexical.py::test_07_index_is_reproducible
    重建后 sqlite_master 全部 SQL + 前 5000 个 passage id 的 sha256 不变
```

---

## 8. 查询接口

```python
from lacan_search import (lexical_search, exact_passage, alias_lookup,
                          syntax_ok, syntax_variants, expand_aliases)

exact_passage("passage.S11.unknown.L01.P0001")   # 不存在 → None（不编造）
lexical_search("大他者", language="zh", limit=10)
lexical_search("l'Autre", language="fr", limit=10)
lexical_search("objet a", language="fr", seminar="S11",
               trace_status="COMPLETE", authority_level="L1",
               corpus_source_id="corpus-source.staferla")
```

### 8.0 辅助函数

| 函数 | 作用 | 位置 |
|---|---|---|
| `syntax_ok(q, language, phrase=False)` | 生成**单个** FTS5 查询串（中文=短语；法语=AND；`phrase=True` 时法语也用短语） | `:148` |
| `syntax_variants(q, language, phrase=False)` | 生成**由紧到松**的多档查询串（短语 → AND） | `:179` |
| `expand_aliases(terms, max_variants=3)` | 把词扩展成 alias index 里的同义写法 | `:227` |

### 8.1 支持的过滤参数（`lacan_search.py:251-253`）

| 参数 | 说明 |
|---|---|
| `language` | `fr` / `zh`；缺省则两语都查 |
| `seminar` | 接受 `S11` 或 `seminar.S11`（自动补前缀） |
| `session` | session 全 ID |
| `trace_status` | `COMPLETE` / `SOURCE_TRACE_INCOMPLETE` |
| `authority_level` | `L1` / `L2` |
| `text_role` | `transcription` / `translation` / `edition` |
| `corpus_source_id` | 走 `passage_source_map` |
| `witness_id` | 同上 |
| `phrase` | 强制短语匹配 |

### 8.2 排序规则

```sql
ORDER BY score ASC, m.id ASC     -- bm25 升序（越小越相关），再按 id 保证确定序
```

跨语言合并时按 `(-score, passage_id)` 排序 —— **排序键完整，不含时间/随机**，
所以同一查询两次结果逐字相同（`test_06` 锁住）。

### 8.3 结果字段（`_row_to_hit`）

每条命中含：`passage_id`（由 `id` 改名而来）、`session_id`、`seminar_id`、
`language`、`lesson`、`session_date`、`text_role`、`authority_level`、
`review_status`、`status`、`canonical`、`trace_status`、`witness_id`、
`corpus_source_id`、`document_id`、`text`、`rank`、`score`、`why_retrieved`。

`why_retrieved` 形如 `lexical_zh` / `lexical_fr` / `exact_id` ——
这是 Evidence Bundle 里 `why_retrieved` 字段的来源，**从第一天就带着**。

---

## 9. 复核命令

```bash
cd <HOME>

# 行数
python3 -c "
import sqlite3; c=sqlite3.connect('_data/index/lexical.sqlite')
for t in ('passage_meta','fr_fts','zh_fts','zh_fts_trigram','passage_source_map'):
    print(t, c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0])"

# benchmark 数字
python3 -m json.tool _data/index/tokenizer_benchmark.json | head -40

# 噪声查询必须 0 条
python3 -c "
import sys; sys.path.insert(0,'_scripts/_tools'); import lacan_search as L
print('噪声:', len(L.lexical_search('欧西坦语诗歌', language='zh', limit=10)))
print('正常:', len(L.lexical_search('大他者', language='zh', limit=5)))"

# 测试
cd _scripts/_tests && python3 -m unittest test_phase3_lexical
```

---

*配套：`RETRIEVAL_ARCHITECTURE.md` · `QUERY_MODEL.md` · `HYBRID_RETRIEVAL.md` ·
`EVIDENCE_BUNDLE.md` · `RETRIEVAL_EVALUATION.md`*
