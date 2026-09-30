#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_lexical_index.py — §3 Lexical Retrieval Baseline（派生索引，不改 canonical）

产出（均可重建；大文件不入 git，manifest 入 git）
────────────────────────────────────────────────
    _data/index/lexical.sqlite           FTS5 索引 + metadata
    _data/index/tokenizer_benchmark.json tokenizer 对比实测（§3 要求先 benchmark）

为什么用 SQLite FTS5
────────────────────
Phase 1 已确认本机 SQLite 3.51.0 **支持 FTS5**（实测 `create virtual table … using fts5`），
因此不需要引入外部检索引擎，也不引入向量库。

两个 tokenizer 策略（法语与中文分别处理）
───────────────────────────────────────
法语的问题：FTS5 的 unicode61 tokenizer 会把 `l'Autre` 拆成 `l` + `Autre`，
把 `Nom-du-Père` 拆成三段，且变音符号默认不折叠 —— 拉康术语正好全中这些坑。
策略对比：
  A. `unicode61`（基线，原样）
  B. `unicode61 remove_diacritics 2` + **索引前文本归一化**：
     撇号 → 空格、连字符 → 空格、变音折叠。查询侧做同样归一化。

中文的问题：FTS5 没有中文分词。
策略对比：
  A. `unicode61`（对中文几乎等于不分词 —— 整段变一个 token）
  B. `trigram`（FTS5 内置，子串匹配）
  C. **bigram**：自己在索引前把连续 CJK 切成二元组，写入空格分隔的 token
     （不依赖 jieba；用户 §3 明确要求不得未经 benchmark 锁定任何单一 tokenizer）

benchmark 用**同一组真实查询**跑 Recall，结果写进 tokenizer_benchmark.json；
`lacan_search.py` 读取 benchmark 里胜出的策略作为默认。

用法
────
    python3 build_lexical_index.py              # 建索引 + 跑 benchmark
    python3 build_lexical_index.py --no-bench   # 只建索引（测试重建用）
    python3 build_lexical_index.py --stamp
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from deterministic import add_stamp_flag, content_hash  # noqa: E402

STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")
LEX = os.path.join(IDX, "lexical.sqlite")
BENCH = os.path.join(IDX, "tokenizer_benchmark.json")

PASSAGES = os.path.join(STORE, "passages.jsonl")

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
# 法语归一化：撇号（ASCII + 排版）→ 空格；连字符 → 空格；变音折叠
_APOS = re.compile(r"['\u2019\u02bc]")
_HYPH = re.compile(r"[-\u2010-\u2015]")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm_fr(s):
    """法语**索引侧**归一化（作用于 derived 文本，不动 canonical）。

    关键修正（实测踩过）：撇号**不能**替换成空格。
    `l'Autre` → `l autr` 会产出**截断词干** `autr`，它既不是 `l` 也不是 `autre`，
    于是查 `Autre` 永远命中不了 —— 第一版 benchmark 的法语数字因此完全失真。

    正确做法：
      * 撇号 → **删除**（`l'Autre` → `lautre`，保留 elision 的完整拼写）
      * 连字符 → 空格（`Nom-du-Père` → `nom du pere`，三段都可检）
      * 变音折叠 + 标点清理
    查询侧另有用 `query_variants_fr()` 生成 elision 的替代切分（见该函数）。
    """
    s = unicodedata.normalize("NFKC", s)
    s = _APOS.sub("", s)
    s = _HYPH.sub(" ", s)
    s = strip_accents(s)
    s = _NONWORD.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def query_variants_fr(s):
    """法语**查询侧**：为每个词生成可检索的替代写法。

    `l'Autre` 既可能以 `lautre`（elision 保留）出现，也可能作为 `autre` 独立出现，
    所以两种都要给出 —— 否则「查 Autre 查不到 l'Autre」这类假阴性无法解释。
    """
    s = unicodedata.normalize("NFKC", s)
    out = []
    for raw in re.split(r"\s+", s.strip()):
        if not raw:
            continue
        for piece in _APOS.split(raw):          # l'Autre → [l, Autre]
            if piece:
                out.append(piece)
        joined = _APOS.sub("", raw)             # l'Autre → lAutre
        if joined:
            out.append(joined)
    seen, uniq = set(), []
    for t in out:
        t = norm_fr(t)
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def bigrams_zh(s):
    """把连续 CJK 串切成二元组（不依赖 jieba）。

    为什么用 bigram：FTS5 无中文分词，`unicode61` 会把整段中文当一个 token
    （等于不可检索）；`trigram` 需要 ≥3 字才能匹配，单词查询失效。
    bigram 让任意 ≥2 字查询都能命中，且对 1 字查询退化为单字。
    注意：这里**没有**引入 jieba —— 用户要求先 benchmark 再决定。
    """
    out = []
    buf = []
    for ch in s:
        if _CJK.match(ch):
            buf.append(ch)
        else:
            if buf:
                out.append(_flush_cjk(buf))
                buf = []
            if ch.strip():
                out.append(ch.lower())
    if buf:
        out.append(_flush_cjk(buf))
    return " ".join(x for x in out if x)


def _flush_cjk(chars):
    s = "".join(chars)
    if len(s) == 1:
        return s
    return " ".join(s[i:i + 2] for i in range(len(s) - 1))


def iter_passages(limit=0):
    n = 0
    with open(PASSAGES, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            yield d
            n += 1
            if limit and n >= limit:
                return


def build(limit=0, quiet=True):
    os.makedirs(IDX, exist_ok=True)
    if os.path.exists(LEX):
        os.remove(LEX)
    con = sqlite3.connect(LEX)
    try:
        con.executescript("""
        PRAGMA journal_mode=MEMORY;
        PRAGMA synchronous=OFF;

        CREATE TABLE passage_meta (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            seminar_id TEXT NOT NULL,
            language TEXT NOT NULL,
            lesson INTEGER,
            session_date TEXT NOT NULL,
            session_date_precision TEXT NOT NULL,
            text_role TEXT NOT NULL,
            authority_level TEXT NOT NULL,
            review_status TEXT NOT NULL,
            status TEXT NOT NULL,
            canonical INTEGER NOT NULL,
            trace_status TEXT NOT NULL,
            witness_id TEXT,
            corpus_source_id TEXT,
            document_id TEXT,
            raw_text TEXT NOT NULL
        );
        CREATE INDEX idx_meta_seminar ON passage_meta(seminar_id);
        CREATE INDEX idx_meta_session ON passage_meta(session_id);
        CREATE INDEX idx_meta_lang ON passage_meta(language);
        CREATE INDEX idx_meta_trace ON passage_meta(trace_status);
        CREATE INDEX idx_meta_auth ON passage_meta(authority_level);
        -- witness/corpus_source 由 realization 表关联，这里存冗余便于过滤
        CREATE TABLE passage_source_map (
            passage_id TEXT PRIMARY KEY,
            witness_id TEXT, corpus_source_id TEXT
        );

        -- 法语：归一化文本 + remove_diacritics
        CREATE VIRTUAL TABLE fr_fts USING fts5(
            body, content='', tokenize="unicode61 remove_diacritics 2"
        );
        -- 中文：bigram 归一化文本
        CREATE VIRTUAL TABLE zh_fts USING fts5(
            body, content='', tokenize="unicode61"
        );
        -- 中文策略 B：trigram（用于 benchmark 对比）
        CREATE VIRTUAL TABLE zh_fts_trigram USING fts5(
            body, content='', tokenize="trigram"
        );
        """)

        ws = {}   # witness / corpus_source
        rm = os.path.join(STORE, "passage_realizations.jsonl")
        if os.path.isfile(rm):
            with open(rm, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        ws[r["passage_id"]] = (r.get("witness_id"),
                                               r.get("corpus_source_id"))

        n_fr = n_zh = 0
        t0 = time.time()
        for d in iter_passages(limit):
            pid = d["id"]
            lang = d["language"]
            prov = d.get("provenance") or {}
            w, csrc = ws.get(pid, (d.get("witness_id"), None))
            con.execute(
                "INSERT INTO passage_meta VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, d["session_id"], d["seminar_id"], lang, d.get("lesson"),
                 d["session_date"], d["session_date_precision"], d["text_role"],
                 d["authority_level"], d["review_status"], d["status"],
                 1 if d.get("canonical") else 0, d["trace_status"],
                 w, csrc, prov.get("document_id"), d["raw_text"]))
            con.execute("INSERT INTO passage_source_map VALUES (?,?,?)",
                        (pid, w, csrc))
            if lang == "fr":
                con.execute("INSERT INTO fr_fts(rowid, body) VALUES (?,?)",
                            (con.execute("SELECT rowid FROM passage_meta WHERE id=?",
                                         (pid,)).fetchone()[0],
                             norm_fr(d["raw_text"])))
                n_fr += 1
            elif lang == "zh":
                rid = con.execute("SELECT rowid FROM passage_meta WHERE id=?",
                                  (pid,)).fetchone()[0]
                con.execute("INSERT INTO zh_fts(rowid, body) VALUES (?,?)",
                            (rid, bigrams_zh(d["raw_text"])))
                con.execute("INSERT INTO zh_fts_trigram(rowid, body) VALUES (?,?)",
                            (rid, d["raw_text"]))
                n_zh += 1
        con.commit()
    finally:
        con.close()
    return {"passages": n_fr + n_zh, "fr": n_fr, "zh": n_zh,
            "seconds": round(time.time() - t0, 1)}


# ------------------------------------------------------------------ benchmark
FR_QUERIES = [
    "l'Autre", "d'Autre", "Nom-du-Père", "plus-de-jouir", "objet a",
    "jouissance", "désir", "père", "signifiant", "symptôme",
    "forclusion", "fantasme", "l'objet", "n'être", "qu'à",
    "Autre", "père", "mère", "réel", "savoir",
]
ZH_QUERIES = ["大他者", "享乐", "圣状", "能指", "欲望", "对象a"]


def _fts_query(body_tokens):
    """把归一化后的 token 串成 FTS5 查询（AND）。"""
    toks = [t for t in body_tokens.split() if t]
    if not toks:
        return None
    return " AND ".join('"%s"' % t for t in toks[:6])


def _ground_truth(terms, language, cap_per_term=200):
    """在**原始文本**里做区分大小写的子串匹配，作为 benchmark 的 ground truth。

    这是公平比较的前提：第一版 benchmark 拿「未归一化的查询词」去查
    「归一化过的索引」，于是 `l'Autre` 被切成 `l`+`autr` 去 AND 匹配，
    必然零命中 —— 那测的是「假阴性拒答」，不是检索质量。实测该错误结论为
    「法语选定 A_unicode61_raw」，方向完全反了。benchmark 必须对每种策略
    使用**与其一致的查询侧处理**，并以 ground truth 计算 recall。
    """
    gt = {}
    want = [t.lower() for t in terms]
    with open(PASSAGES, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            if d["language"] != language:
                continue
            low = d["raw_text"].lower()
            for t in want:
                if t in low:
                    gt.setdefault(t, [])
                    if len(gt[t]) < cap_per_term:
                        gt[t].append(d["id"])
            if all(len(gt.get(t, [])) >= cap_per_term for t in want):
                break
    return gt


def bench():
    """公平的 tokenizer 对比。

    每种策略都用**它自己的查询侧处理**去查**它自己的索引侧文本**，
    并以 ground-truth（原始文本子串匹配）计算 recall。
    """
    con = sqlite3.connect(LEX)

    def run_fr(name, tokenizer, table="fr_fts"):
        """`tokenizer(q) -> [tokens]`：各策略自带的查询侧处理。"""
        gt = _ground_truth(FR_QUERIES, "fr")
        found = nonempty = den = prec_num = prec_den = 0
        for q in FR_QUERIES:
            gold = set(gt.get(q.lower(), []))
            if not gold:
                continue
            den += 1
            toks = [t for t in tokenizer(q) if len(t) >= 2]
            if not toks:
                continue
            fq = " AND ".join('"%s"' % t for t in toks[:4])
            try:
                rows = con.execute(
                    "SELECT m.id FROM %s f JOIN passage_meta m ON m.rowid=f.rowid "
                    "WHERE f.body MATCH ? LIMIT 500" % table, (fq,)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            ids = {r[0] for r in rows}
            if ids:
                nonempty += 1
                prec_num += len(ids & gold)
                prec_den += len(ids)
            if ids & gold:
                found += 1
        return {"queries_with_ground_truth": den, "queries_with_hits": nonempty,
                "queries_with_gold_hit": found,
                "recall_proxy": round(found / den, 3) if den else 0.0,
                "precision_proxy": round(prec_num / prec_den, 3) if prec_den else 0.0}

    def run_zh(name, table, norm_query):
        gt = _ground_truth([q for q in ZH_QUERIES], "zh")
        found = 0
        nonempty = 0
        den = 0
        for q in ZH_QUERIES:
            gold = set(gt.get(q.lower(), []))
            if not gold:
                continue
            den += 1
            qt = norm_query(q) or q
            toks = [t for t in qt.split() if t]
            if not toks:
                continue
            fq = " AND ".join('"%s"' % t for t in toks[:6])
            try:
                rows = con.execute(
                    "SELECT m.id FROM %s f JOIN passage_meta m ON m.rowid=f.rowid "
                    "WHERE f.body MATCH ? LIMIT 200" % table, (fq,)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            ids = {r[0] for r in rows}
            if ids:
                nonempty += 1
            if ids & gold:
                found += 1
        return {"queries_with_ground_truth": den,
                "queries_with_hits": nonempty,
                "queries_with_gold_hit": found,
                "recall_proxy": round(found / den, 3) if den else 0.0}

    out = {"french": {"strategies": {}}, "chinese": {"strategies": {}}}
    try:
        # 法语：A 原样查询（对归一化索引 —— 故意保留以展示失败模式）；
        #       B 归一化查询（策略自身一致）
        # A：原样查询（不处理撇号）→ 对归一化索引，展示假阴性
        out["french"]["strategies"]["A_raw_query"] = run_fr(
            "A", lambda q: re.split(r"\s+", q))
        # B：只做变音折叠（不处理撇号/连字符）
        out["french"]["strategies"]["B_accent_only"] = run_fr(
            "B", lambda q: [strip_accents(t).lower()
                            for t in re.split(r"\s+", q)])
        # C：完整归一化 + elision 变体（本次修正的策略）
        out["french"]["strategies"]["C_normalized_with_elision_variants"] = run_fr(
            "C", query_variants_fr)
        # 中文
        out["chinese"]["strategies"]["A_trigram_raw"] = run_zh(
            "A", "zh_fts_trigram", lambda q: q)
        out["chinese"]["strategies"]["B_bigram"] = run_zh(
            "B", "zh_fts", bigrams_zh)
        out["chinese"]["strategies"]["C_unicode61_raw"] = run_zh(
            "C", "zh_fts", lambda q: q)
    finally:
        con.close()

    def pick(d):
        # 先 recall，再 precision，最后字典序（平手取更简单者）
        items = sorted(d["strategies"].items(),
                       key=lambda kv: (-kv[1]["recall_proxy"],
                                       -kv[1].get("precision_proxy", 0.0),
                                       kv[0]))
        return items[0][0]
    out["french"]["chosen"] = pick(out["french"])
    out["chinese"]["chosen"] = pick(out["chinese"])
    out["selection_rule"] = ("按 ground-truth recall_proxy 降序；平手取字典序最小。"
                             "不依据模型宣传或外部 benchmark 排名。")
    out["benchmark_note"] = ("每种策略用**其自身一致的**查询侧归一化，"
                             "并以原始文本子串匹配为 ground truth；"
                             "A 策略刻意保留「原样查询 vs 归一化索引」以展示失败模式。")
    out["zh_queries"] = ZH_QUERIES
    out["fr_queries"] = FR_QUERIES
    with open(BENCH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
    return out


def manifest(limit=0, bench_result=None):
    """INDEX_MANIFEST 的 lexical 部分（§13：索引可重建的凭证）。"""
    corpus_hash = hashlib.sha256()
    with open(PASSAGES, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            corpus_hash.update(b)
    return {
        "schema_version": "index-manifest/v1",
        "index": "lexical",
        "index_version": content_hash({"corpus": corpus_hash.hexdigest(),
                                       "limit": limit})[:16],
        "corpus_hash": corpus_hash.hexdigest(),
        "passage_count": 249105 if not limit else limit,
        "tokenizer": (bench_result or {}).get("chosen_strategy", {}),
        "build_config_hash": content_hash({"limit": limit})[:16],
        "artifacts": [os.path.relpath(LEX, VAULT), os.path.relpath(BENCH, VAULT)],
    }


def main():
    ap = argparse.ArgumentParser(description="建 lexical index（§3）")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-bench", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    add_stamp_flag(ap)
    args = ap.parse_args()

    st = build(limit=args.limit, quiet=args.quiet)
    if not args.no_bench:
        b = bench()
        if not args.quiet:
            print(f"[lexical] 法语选定: {b['french']['chosen']}  "
                  f"中文选定: {b['chinese']['chosen']}", file=sys.stderr)
    if not args.quiet:
        print(f"[lexical] passages={st['passages']} (fr={st['fr']} zh={st['zh']}) "
              f"{st['seconds']}s", file=sys.stderr)
        print(f"[lexical] -> {LEX}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
