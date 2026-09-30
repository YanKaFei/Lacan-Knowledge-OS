#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lacan_search.py — 检索层公共接口（Phase 3 §3/§4）

对外提供（供 CLI 与测试调用）：

    exact_passage(passage_id)              按 stable ID 精确取一段
    lexical_search(q, **filters)           词法检索（FTS5）+ metadata 过滤
    alias_lookup(alias)                    别名精确查询（含歧义暴露）

设计纪律
────────
* **只读**：本模块不写任何东西，尤其不改 canonical passage store。
* **确定性**：同查询同结果（排序键完整，不含时间/随机）。
* **不编造**：查不到就返回空 / None，绝不返回不存在的 passage_id。
* **归一化只作用在派生索引上**：canonical `raw_text` 一字不改；
  检索用的归一化文本在建索引时写入 FTS 表，查询侧做同样的归一化。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

IDX = os.path.join(VAULT, "_data", "index")
LEX = os.path.join(IDX, "lexical.sqlite")
BENCH = os.path.join(IDX, "tokenizer_benchmark.json")

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_APOS = re.compile(r"['\u2019\u02bc]")
_HYPH = re.compile(r"[-\u2010-\u2015]")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm_fr(s):
    """法语索引侧归一化（与 build_lexical_index.norm_fr 必须一致）。"""
    s = unicodedata.normalize("NFKC", s)
    s = _APOS.sub("", s)
    s = _HYPH.sub(" ", s)
    s = strip_accents(s)
    s = _NONWORD.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def query_variants_fr(s):
    """法语查询侧：为 elision 生成可检索替代（l'Autre → lautre / autre）。"""
    s = unicodedata.normalize("NFKC", s)
    out = []
    for raw in re.split(r"\s+", s.strip()):
        if not raw:
            continue
        for piece in _APOS.split(raw):
            if piece:
                out.append(piece)
        joined = _APOS.sub("", raw)
        if joined:
            out.append(joined)
    seen, uniq = set(), []
    for t in out:
        t = norm_fr(t)
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _flush_cjk(chars):
    s = "".join(chars)
    return s if len(s) == 1 else " ".join(s[i:i + 2] for i in range(len(s) - 1))


def bigrams_zh(s):
    out, buf = [], []
    for ch in s:
        if _CJK.match(ch):
            buf.append(ch)
        else:
            if buf:
                out.append(_flush_cjk(buf)); buf = []
            if ch.strip():
                out.append(ch.lower())
    if buf:
        out.append(_flush_cjk(buf))
    return " ".join(x for x in out if x)


def _con():
    if not os.path.isfile(LEX):
        raise FileNotFoundError(
            "lexical index 不存在：先跑 _scripts/_tools/build_lexical_index.py")
    con = sqlite3.connect(LEX)
    con.row_factory = sqlite3.Row
    return con


_META_COLS = ("id", "session_id", "seminar_id", "language", "lesson",
              "session_date", "session_date_precision", "text_role",
              "authority_level", "review_status", "status", "canonical",
              "trace_status", "witness_id", "corpus_source_id", "document_id")


def _row_to_hit(row, rank, score=None, why="lexical"):
    keys = list(row.keys())
    d = {k: row[k] for k in _META_COLS if k in keys}
    # passage_id 必须无条件存在：优先取 id，其次取已有的 passage_id
    if "id" in d:
        d["passage_id"] = d.pop("id")
    else:
        pid = d.pop("passage_id", None) or (
            row["id"] if "id" in keys else None)
        if not pid:
            raise KeyError("hit 无 id/passage_id，可用列：%r" % keys)
        d["passage_id"] = pid
    d["text"] = row["raw_text"] if "raw_text" in row.keys() else None
    # canonical 在 passage 上是 0/1（是否已审定为本）；SQLite 存的是整数
    d["canonical"] = bool(d.get("canonical"))
    d["rank"] = rank
    d["score"] = score
    d["why_retrieved"] = why
    return d


def exact_passage(passage_id):
    """按 stable ID 精确取一段。不存在 → None（不编造）。"""
    con = _con()
    try:
        r = con.execute("SELECT * FROM passage_meta WHERE id=?",
                        (str(passage_id),)).fetchone()
        return _row_to_hit(r, rank=1, score=1.0, why="exact_id") if r else None
    finally:
        con.close()


def syntax_ok(q, language, phrase=False):
    """把自由文本转成 FTS5 查询串。

    中文**必须**用「短语匹配」而非 AND：
    bigram 把 `不存在的词` 切成 `不存 存在 在的 的词`，若用 AND，
    只要其中任一 bigram 命中就返回结果 —— 实测该错误让一个纯噪声查询
    返回了 5 条无关结果（欧西坦语诗歌）。短语匹配要求 bigram **按序相邻**，
    才等价于子串匹配。
    """
    if language == "zh":
        toks = [t for t in bigrams_zh(q).split() if t]
        if not toks:
            return None
        # 相邻 bigram 序列 → FTS5 短语
        return '"%s"' % " ".join(toks[:24]).replace('"', '""')
    if language == "fr":
        if phrase:
            toks = [t for t in norm_fr(q).split() if t]
            if not toks:
                return None
            return '"%s"' % " ".join(toks[:12]).replace('"', '""')
        toks = [t for t in query_variants_fr(q) if len(t) >= 2]
        if not toks:
            return None
        return " AND ".join('"%s"' % t.replace('"', '""') for t in toks[:6])
    toks = [t for t in re.split(r"\s+", q.strip()) if t]
    if not toks:
        return None
    return " AND ".join('"%s"' % t.replace('"', '""') for t in toks[:6])


def syntax_variants(q, language, phrase=False):
    """返回按「由紧到松」排列的若干 FTS5 查询串。

    为什么需要多档（实测教训）：
    * 只做**短语匹配**时，`凝视 小客体` 零命中 —— 因为这两个词在文本里
      从不**相邻**，而语料里含「凝视」的段有 341 段。过紧 = 大量假阴性。
    * 只做 **AND** 时，噪声查询 `zzzqqqxxx不存在的词` 会因某个 bigram
      偶然命中而返回结果。过松 = 假阳性。

    所以：短语优先（精确），无结果再退到 AND（宽松）。
    这样两类失败模式各由一档承担，而不是用一档去同时满足两种需求。
    """
    out = []
    if language == "zh":
        toks = [t for t in bigrams_zh(q).split() if t]
        if toks:
            out.append('"%s"' % " ".join(toks[:24]))
        # AND：以「词」为单位（标点/空白切分），再对每个词做 bigram 短语
        words = [w for w in re.split(r"[\s，。！？、；：,.!?;:]+", q.strip()) if w]
        if len(words) > 1:
            parts = []
            for w in words[:4]:
                bt = [t for t in bigrams_zh(w).split() if t]
                if bt:
                    parts.append('"%s"' % " ".join(bt))
            if len(parts) > 1:
                out.append(" AND ".join(parts))
    elif language == "fr":
        if phrase:
            toks = [t for t in norm_fr(q).split() if t]
            if toks:
                out.append('"%s"' % " ".join(toks[:12]))
        toks = [t for t in query_variants_fr(q) if len(t) >= 2]
        if toks:
            out.append(" AND ".join('"%s"' % t for t in toks[:6]))
    else:
        toks = [t for t in re.split(r"\s+", q.strip()) if t]
        if toks:
            out.append(" AND ".join('"%s"' % t for t in toks[:6]))
    # 去重保序
    seen, uniq = set(), []
    for f in out:
        if f and f not in seen:
            seen.add(f)
            uniq.append(f)
    return uniq


def expand_aliases(terms, max_variants=3):
    """把查询词扩展到它在 alias index 里的同义写法。

    作用范围（实测校准，别高估它）：
    本函数只对**已登记在 alias index 里的别名**生效。实测：

        expand_aliases(["对象a"])  -> ['object a', 'objet a', ...]   ✅
        expand_aliases(["小客体"])  -> []                            ❌
        expand_aliases(["凝视"])    -> []                            ❌

    原因：index 里登记的是 `小客体a` / `客体小a`（**带结尾 a**），没有 `小客体`；
    `凝视` 干脆不在 53 条 Gold Concept 里。少一个字符的变体不会被扩展 ——
    因为「`小客体` 是否等同于 `小客体a`」属于**实体判定**，
    按 §4 纪律不得由脚本自动决定，必须人工登记。

    所以：`凝视 小客体` 返回 0 是**诚实的** —— 语料里没有同时含这两个串的段，
    而它俩的写法对齐尚未人工登记。不要把它当成本函数能解决的例子。
    """
    import alias_index
    out = []
    for t in terms:
        for h in alias_index.exact_lookup(t)[:max_variants]:
            eid = h["entity_id"]
            # 取该实体的所有别名写法（同一实体的不同译名/拼写）
            rows = alias_index._load()
            for r in rows:
                if r["entity_id"] == eid and r["alias"] not in out:
                    out.append(r["alias"])
    return out


def lexical_search(query, language=None, limit=20, seminar=None, session=None,
                   trace_status=None, authority_level=None, text_role=None,
                   corpus_source_id=None, witness_id=None, phrase=False,
                   pool_ids=None):
    """词法检索 + metadata 过滤。

    排序：FTS5 bm25 分数升序（越小越相关），再按 passage_id 保证确定序。

    `pool_ids`（可选）：把检索**限定在一个候选集合内**。
    为什么需要它：如果只在全库排名里取前 N 再按池过滤，
    池内命中数会被「全库排名」这个无关因素压低 —— 拿这种数字去和
    池内做向量检索比较，是**不公平对照**（实测会把 lexical 的 hit@20
    从池内真实水平压到 0.006）。评测消融必须让所有方法在**同一候选集内**排序。
    """
    if not query or not str(query).strip():
        return []
    q = str(query).strip()
    quoted = phrase or (q.startswith('"') and q.endswith('"') and len(q) > 2)
    if quoted:
        q = q.strip('"')

    langs = [language] if language else ["fr", "zh"]
    hits = []
    # ---- 别名扩展：拆出查询里的词，映射到同义写法
    raw_terms = [w for w in re.split(r"[\s，。！？、；：,.!?;:]+", q) if len(w) >= 2]
    alias_extra = []
    alias_extra_map = {}
    try:
        import alias_index as _ai
        rows_all = _ai._load()
        for w in raw_terms:
            # 变量名不要用 hits —— 会把外层累积的结果列表覆盖掉（实测踩过：
            # `hits = _ai.exact_lookup(w)` 让带 passage_id 的结果被别名条目替换，
            # 随后排序时报 KeyError: 'passage_id'）。
            alias_hits = _ai.exact_lookup(w)
            reps = []
            for h in alias_hits:
                for r in rows_all:
                    if r["entity_id"] == h["entity_id"] and r["alias"] != w:
                        if r["alias"] not in reps:
                            reps.append(r["alias"])
            if reps:
                alias_extra_map[w] = reps[:4]
                alias_extra.extend(reps[:4])
    except Exception:
        pass
    # 只在「原查询无命中」时才用别名扩展，避免稀释精确查询
    con = _con()
    try:
        # 候选集限定：在**同一个连接**上建临时表，避免把 6,305 个 id
        # 拼成一条巨大的 IN (...) 语句。
        if pool_ids is not None:
            con.execute("CREATE TEMP TABLE _pool_filter(id TEXT PRIMARY KEY)")
            con.executemany("INSERT OR IGNORE INTO _pool_filter(id) VALUES(?)",
                            [(str(p),) for p in pool_ids])
        for lang in langs:
            table = "fr_fts" if lang == "fr" else "zh_fts"
            fqs = syntax_variants(q, lang, phrase=quoted)
            if not fqs:
                continue
            # 逐词拆解，供「替换某一项为同义别名」使用
            word_parts, alias_words = [], []
            if lang == "zh":
                for w in raw_terms:
                    bt = [t for t in bigrams_zh(w).split() if t]
                    if not bt:
                        continue
                    word_parts.append('"%s"' % " ".join(bt))
                    reps = []
                    for h in (alias_extra_map.get(w) or []):
                        rb = [t for t in bigrams_zh(h).split() if t]
                        if rb:
                            reps.append('"%s"' % " ".join(rb))
                    alias_words.append(reps[:3])
            where, params = [], []
            if seminar:
                where.append("m.seminar_id = ?")
                params.append(seminar if str(seminar).startswith("seminar.")
                            else "seminar." + str(seminar).lstrip("sS"))
            if session:
                where.append("m.session_id = ?")
                params.append(session)
            for col, val in (("trace_status", trace_status),
                             ("authority_level", authority_level),
                             ("text_role", text_role)):
                if val:
                    where.append("m.%s = ?" % col)
                    params.append(val)
            if corpus_source_id:
                where.append("s.corpus_source_id = ?")
                params.append(corpus_source_id)
            if witness_id:
                where.append("s.witness_id = ?")
                params.append(witness_id)
            if pool_ids is not None:
                where.append("m.id IN (SELECT id FROM _pool_filter)")
            sql = ("SELECT m.*, bm25(%s) AS score FROM %s f "
                   "JOIN passage_meta m ON m.rowid = f.rowid "
                   "LEFT JOIN passage_source_map s ON s.passage_id = m.id "
                   "WHERE f.body MATCH ?" % (table, table))
            if where:
                sql += " AND " + " AND ".join(where)
            sql += " ORDER BY score ASC, m.id ASC LIMIT ?"
            rows = []
            for fq in fqs:
                try:
                    rows = con.execute(sql, [fq] + params + [limit * 4]).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                if rows:
                    break   # 紧的查询有结果就不放宽
            # 仍然没有 → 把 AND 的**某一项**替换成它的同义别名，逐组合重试。
            # （整句替换没用：实测 `凝视 小客体` 里的「凝视」是好的，
            #   坏的只是「小客体」这一项；要换的是**项**，不是整句。）
            if not rows and len(alias_words) > 1:
                import itertools
                for combo in itertools.islice(
                        itertools.product(*[v or [None] for v in alias_words]), 48):
                    parts = []
                    for base, rep in zip(word_parts, combo):
                        parts.append(rep if rep else base)
                    fq = " AND ".join(parts)
                    try:
                        rows = con.execute(sql, [fq] + params + [limit * 4]).fetchall()
                    except sqlite3.OperationalError:
                        rows = []
                    if rows:
                        break
            for r in rows:
                try:
                    sc = -float(r["score"])
                except Exception:
                    sc = None
                hits.append(_row_to_hit(r, rank=0, score=sc,
                                        why="lexical_%s" % lang))
    finally:
        con.close()

    # 合并两语结果：按 score 降序（bm25 已取负），再按 id 保证确定序
    hits.sort(key=lambda h: (-(h.get("score") or 0.0), h["passage_id"]))
    for i, h in enumerate(hits, 1):
        h["rank"] = i
    return hits[:limit]


def alias_lookup(alias, case_sensitive=False):
    """别名精确查询（转发到 alias_index，保留歧义信息）。"""
    import alias_index
    return alias_index.exact_lookup(alias, case_sensitive=case_sensitive)


def index_manifest_path():
    return os.path.join(IDX, "INDEX_MANIFEST.json")
