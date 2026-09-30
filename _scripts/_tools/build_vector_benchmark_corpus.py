#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_vector_benchmark_corpus.py — §8 Representative Vector Benchmark Corpus

目标：从 249,105 段里抽 **5,000–8,000 段**，作为向量评测的固定底本。
**禁止纯随机抽样** —— 纯随机会让罕见期/语言/概念被淹没，测出来的东西没有代表性。

分层维度（§8 明确要求）
───────────────────────
1. 28 个 seminar 全覆盖
2. zh / fr 两种语言
3. 不同年代（period）
4. 不同 session（同一 session 不要占满）
5. 已连接 Gold Concept 的 passage（10 条概念名下的真实 passage）
6. **lexical-positive**：lexical baseline 能命中的段（保证 L 路径有东西可排）
7. **lexical-hard**：lexical 命中但排序靠后 / 高 bm25 的段（区分度高的样点）
8. **cross-language targets**：法文段中与中文 gold 概念相关的（B 方向的目标侧）

产出
────
    _data/index/vector/vector_benchmark_corpus.jsonl     被选中的 passage id + 分层标签
    _data/index/vector/vector_benchmark_corpus_manifest.json  可复现凭证

确定性
──────
抽样必须**不依赖时间/随机种子漂移**：用 `blake2b(passage_id)` 的稳定哈希排序，
按每层配额取前 N。同输入 → 同输出 → 可复现（有测试）。

用法
    python3 build_vector_benchmark_corpus.py
    python3 build_vector_benchmark_corpus.py --target 6000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from deterministic import add_stamp_flag, apply_stamp  # noqa: E402

STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")
OUTDIR = os.path.join(IDX, "vector")
LEX = os.path.join(IDX, "lexical.sqlite")
OUT = os.path.join(OUTDIR, "vector_benchmark_corpus.jsonl")
MANIFEST = os.path.join(OUTDIR, "vector_benchmark_corpus_manifest.json")

TARGET = 6000
MIN_TARGET, MAX_TARGET = 5000, 8000

# 分层配额（总和 = TARGET 附近；按层取满即止）
PER_SEMINAR_CAP = 400        # 每期上限，保证 28 期都进得来
# ⚠️ per-session 上限必须**按语言**分别设定（实测踩过）：
# 中译 531 个 session（平均 155 段），法语只有 28 个 session（平均 **5947** 段）。
# 第一版用统一的 cap=3，结果法语只被取到 28×3=84 段，而 zh 取到 1587 段 ——
# 完全不能代表 66% 是法语的语料。
PER_SESSION_CAP = {"fr": 160, "zh": 5}
GOLD_CONCEPT_RESERVED = 200  # 已连接 Gold Concept 的 passage 预留量
LEXICAL_HARD_RESERVED = 400  # 高区分度样点预留量


def stable_key(pid):
    """确定性排序键（不用 random，不用时间）。"""
    return hashlib.blake2b(pid.encode("utf-8"), digest_size=8).hexdigest()


def load_gold_concept_passages():
    """10 个已连接真实 Passage 的 Gold Concept 名下的 passage。"""
    out = set()
    p = os.path.join(STORE, "concepts.jsonl")
    if not os.path.isfile(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            c = json.loads(line)
            for pid in (c.get("passages") or []):
                out.add(pid)
    return out


def main():
    ap = argparse.ArgumentParser(description="建 stratified vector benchmark corpus（§8）")
    ap.add_argument("--target", type=int, default=TARGET)
    ap.add_argument("--quiet", action="store_true")
    add_stamp_flag(ap)
    args = ap.parse_args()
    target = max(MIN_TARGET, min(MAX_TARGET, args.target))

    os.makedirs(OUTDIR, exist_ok=True)
    con = sqlite3.connect(LEX)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("""
            SELECT id, seminar_id, session_id, language, session_date,
                   authority_level, trace_status, text_role
            FROM passage_meta
        """).fetchall()
    finally:
        con.close()

    gold_pids = load_gold_concept_passages()

    # ---- 分层：按 (seminar, language) 分桶，桶内按稳定哈希排序
    strata = defaultdict(list)
    for r in rows:
        strata[(r["seminar_id"], r["language"])].append(r)
    for k in strata:
        strata[k].sort(key=lambda r: stable_key(r["id"]))

    # ---- 各期配额：先保证每期都有，再按语言平衡
    picked = {}          # pid -> labels
    sem_counts = defaultdict(int)
    sess_counts = defaultdict(int)

    def take(r, label):
        if r["id"] in picked:
            picked[r["id"]]["labels"].add(label)
            return True
        if sem_counts[r["seminar_id"]] >= PER_SEMINAR_CAP:
            return False
        cap = PER_SESSION_CAP.get(r["language"], 5)
        if sess_counts[r["session_id"]] >= cap:
            return False
        picked[r["id"]] = {
            "passage_id": r["id"], "seminar_id": r["seminar_id"],
            "session_id": r["session_id"], "language": r["language"],
            "labels": {label},
        }
        sem_counts[r["seminar_id"]] += 1
        sess_counts[r["session_id"]] += 1
        return True

    # ① Gold Concept 连接段（预留）
    for r in rows:
        if len(picked) >= GOLD_CONCEPT_RESERVED:
            break
        if r["id"] in gold_pids:
            take(r, "gold_concept_linked")

    # ② 每 (seminar, language) 轮流取，保证 28 期 × 2 语覆盖。
    # 语料里 fr 占 66%、zh 占 34%，子集应大致同比例（否则又是一种偏差）。
    lang_total = defaultdict(int)
    for r in rows:
        lang_total[r["language"]] += 1
    grand = sum(lang_total.values())
    lang_quota = {k: int(target * v / grand) for k, v in lang_total.items()}
    lang_counts = defaultdict(int)

    def lang_full(lang):
        return lang_counts[lang] >= lang_quota.get(lang, target)

    keys = sorted(strata.keys())
    idx = {k: 0 for k in keys}
    progress = True
    while progress and len(picked) < target:
        progress = False
        for k in keys:
            if len(picked) >= target:
                break
            if lang_full(k[1]):
                continue
            arr, i = strata[k], idx[k]
            while i < len(arr):
                r = arr[i]
                i += 1
                if take(r, "stratified_%s" % k[1]):
                    lang_counts[r["language"]] += 1
                    progress = True
                    break
            idx[k] = i

    # ③ lexical-hard：从高 bm25 差异的段补（用 authority/trace 混合特征近似）
    #    §8 的「lexical-hard」定义为「lexical 命中但区分度低/排序靠后」；
    #    这里用 authority_level + text_role 的稀缺组合作为代理，
    #    并**如实标注**这是代理而非真实 bm25 尾部。
    if len(picked) < target:
        rest = [r for r in rows
                if r["id"] not in picked and
                r["authority_level"] in ("L2", "L3")]
        rest.sort(key=lambda r: stable_key(r["id"]))
        for r in rest:
            if len(picked) >= target:
                break
            take(r, "lexical_hard_proxy")

    rows_out = sorted(picked.values(),
                      key=lambda x: (x["seminar_id"], x["language"],
                                     x["passage_id"]))
    for x in rows_out:
        x["labels"] = sorted(x["labels"])

    with open(OUT, "w", encoding="utf-8") as f:
        for x in rows_out:
            f.write(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n")

    # ---- 覆盖率自检
    sems = sorted({x["seminar_id"] for x in rows_out})
    langs = sorted({x["language"] for x in rows_out})
    label_counts = defaultdict(int)
    for x in rows_out:
        for l in x["labels"]:
            label_counts[l] += 1

    corpus_hash = hashlib.sha256()
    with open(os.path.join(STORE, "passages.jsonl"), "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            corpus_hash.update(b)

    man = {
        "schema_version": "vector-benchmark-corpus/v1",
        "corpus_hash": corpus_hash.hexdigest(),
        "full_passage_count": len(rows),
        "subset_size": len(rows_out),
        "sampling": {
            "method": "deterministic stratified（blake2b(passage_id) 稳定排序）",
            "random": False,
            "strata": "(seminar_id, language)",
            "per_seminar_cap": PER_SEMINAR_CAP,
            "per_session_cap": PER_SESSION_CAP,
            "per_session_cap_reason": ("按语言分别设限：中译 531 session（均 155 段）、"
                                       "法语仅 28 session（均 5947 段）。统一 cap 会让"
                                       "法语被饿死（实测 84 段 vs zh 1587 段）。"),
            "layers": ["gold_concept_linked", "stratified_zh/fr",
                       "lexical_hard_proxy"],
            "note": ("lexical_hard_proxy 是用 authority_level/text_role 稀缺组合做的**代理**，"
                     "不是真实 bm25 尾部 —— 如实标注，避免假装它是真的 lexical-hard"),
        },
        "language_quota": dict(sorted(lang_quota.items())),
        "coverage": {
            "seminars": len(sems), "seminar_ids": sems[:40],
            "languages": langs, "by_language": _count(rows_out, "language"),
            "by_label": dict(sorted(label_counts.items())),
        },
        "artifacts": [os.path.relpath(OUT, VAULT)],
        "rebuild": "python3 _scripts/_tools/build_vector_benchmark_corpus.py",
    }
    apply_stamp(man, stamp=args.stamp)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2, sort_keys=True)

    if not args.quiet:
        print(f"[vbench] subset={len(rows_out)}/{len(rows)}  "
              f"seminars={len(sems)} langs={langs}", file=sys.stderr)
        print(f"[vbench] by_label={dict(sorted(label_counts.items()))}",
              file=sys.stderr)
        print(f"[vbench] -> {OUT}", file=sys.stderr)
        print(f"[vbench] -> {MANIFEST}", file=sys.stderr)
    return 0


def _count(rows, key):
    out = defaultdict(int)
    for r in rows:
        out[r[key]] += 1
    return dict(sorted(out.items()))


if __name__ == "__main__":
    sys.exit(main())
