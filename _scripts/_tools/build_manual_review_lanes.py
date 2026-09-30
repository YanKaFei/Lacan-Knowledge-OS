#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_manual_review_lanes.py — Phase 4C.1-B §17：6 条 NEEDS_MANUAL_REVIEW lane 的**清单**

要求逐条给出：task_id / lane_id / needle / old_hits / new_hits / difference /
representative_examples / why_manual_review，并区分：

    SAFE_AUTOFIX              纯 lexical normalization 问题，且可 **deterministically 证明**
                              v1 的命中是跨 token 拼接（例如 `l'objet aux` → `objeta`：
                              末段 `a` 只是下一个词 `aux` 的前缀）
    NEEDS_MANUAL_REVIEW       不能确定性证明（可能确有合法变体，如 `objet (a)`）

**不替人做理论判断**：本脚本只做词法证据的机械判定，不改 v1 gold，也不改 v2 的保留策略。
产物：`_data/eval/gold_v2/manual_review_lanes_v1.json`
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
STORE = os.path.join(VAULT, "_data", "passage_store")
OUT = os.path.join(EVAL, "gold_v2", "manual_review_lanes_v1.json")
AUDIT = os.path.join(EVAL, "gold_lane_audit_v1.jsonl")
sys.path.insert(0, HERE)
import gold_normalization as gn            # noqa: E402

_WORD_AFTER = re.compile(r"[\w\u4e00-\u9fff]")


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def load_raw(ids):
    out = {}
    with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            if d["id"] in ids:
                out[d["id"]] = d.get("raw_text") or ""
    return out


def trailing_prefix_proof(raw_text, needles):
    """确定性证明「v1 命中来自**末段截断**」。

    条件（三者同时满足）：
      1. v1 命中区间的末尾紧邻仍是 word 字符（说明命中在词内被截断）；
      2. 把「命中末尾那一段 + 紧随其后的词字符」合成一个更长的词；
      3. needle 的最后一个 token 正好是那一段的结尾（即它只是更长词的前缀）。
    例：`l'objet aux` 的 v1 命中 `objeta` → 末段 `a` + `ux` = `aux` ≠ `a`，
    因此 v1 的命中不可能是完整 token，属跨 token 拼接 → 可 SAFE_AUTOFIX。
    """
    for needle in needles:
        ntoks = gn.needle_tokens_v2(needle)
        if not ntoks:
            continue
        last_tok = ntoks[-1]
        for _s, _e, rs, re_ in gn.match_positions_v1(raw_text, needle):
            after = raw_text[re_ + 1:]
            if not after or not _WORD_AFTER.match(after[0]):
                continue
            m = re.search(r"[\w\u4e00-\u9fff]+$", raw_text[rs:re_ + 1], re.UNICODE)
            if not m:
                continue
            piece = m.group(0)
            cont = re.match(r"[\w\u4e00-\u9fff]*", after, re.UNICODE).group(0)
            word = piece + cont
            if len(word) <= len(piece):
                continue
            if not (piece.lower().endswith(last_tok) or piece.lower() == last_tok):
                continue
            return True, {"span": raw_text[rs:re_ + 1][:60], "piece": piece,
                          "continued_word": word, "needle_last_token": last_tok,
                          "reason": "v1 命中在词内被截断：末段只是更长词 `%s` 的前缀" % word}
    return False, {}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    rows = jl(AUDIT)
    flagged = [r for r in rows if r["classification"] == "NEEDS_MANUAL_REVIEW"]
    need_ids = {pid for r in flagged for pid in (r.get("extra_ids") or [])}
    raw = load_raw(need_ids)

    lanes = []
    for r in flagged:
        ex = []
        proofs = 0
        total = 0
        for e in r.get("examples") or []:
            pid = e.get("passage_id")
            text = raw.get(pid, "")
            ok, proof = (trailing_prefix_proof(text, r.get("needles") or [])
                         if text else (False, {}))
            total += 1
            proofs += 1 if ok else 0
            ex.append({"passage_id": pid, "reason": e.get("reason"),
                       "raw_span": e.get("raw_span"), "deleted": e.get("deleted"),
                       "pieces": e.get("pieces"), "context": e.get("context"),
                       "deterministic_proof": proof or None,
                       "verdict": "SAFE_AUTOFIX" if ok else "NEEDS_MANUAL_REVIEW"})
        all_proven = bool(total) and proofs == total
        lanes.append({
            "task_id": r["task_id"], "lane_id": r["lane"],
            "needles": r.get("needles"), "language": r.get("language"),
            "seminar": r.get("seminar"),
            "old_hits": r.get("v1_hits"), "new_hits": r.get("v2_hits"),
            "difference": r.get("extra_v1_only"),
            "reasons": r.get("reasons"),
            "representative_examples": ex,
            "why_manual_review": (
                "v1 独有的命中只跨引号/括号等非子句标点（`punctuation_join`），"
                "或无法用已知机制解释（`unknown`）—— 这类位置**也可能**是合法变体"
                "（例如 `objet (a)`），因此不能仅凭词法规则自动判为假阳性。"),
            "deterministic_check": {
                "examples_examined": total, "proven_cross_token": proofs,
                "all_examples_proven": all_proven,
            },
            "status": "SAFE_AUTOFIX" if all_proven else "NEEDS_MANUAL_REVIEW",
            "note": ("本清单**不改** v1 gold，gold_v2 亦按 `NEEDS_MANUAL_REVIEW` 原样保留"
                     "（build_gold_v2.py 对这类 lane 不做任何自动重建）。"),
        })

    doc = {
        "schema_version": "manual-review-lanes/v1",
        "phase": "Phase 4C.1-B §17",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": os.path.relpath(AUDIT, VAULT),
        "n_lanes": len(lanes),
        "status_counts": {s: sum(1 for x in lanes if x["status"] == s)
                          for s in ("SAFE_AUTOFIX", "NEEDS_MANUAL_REVIEW")},
        "policy": ("SAFE_AUTOFIX 仅用于**可确定性证明**为跨 token 拼接的 lane；"
                   "其余一律 NEEDS_MANUAL_REVIEW，不替人工做判断。"),
        "lanes": lanes,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not a.quiet:
        print("NEEDS_MANUAL_REVIEW lane：%d 条 -> %s" % (len(lanes), doc["status_counts"]))
        for x in lanes:
            print("  %-7s %-16s needles=%-28s v1=%-4s v2=%-4s diff=%-4s %s"
                  % (x["task_id"], x["lane_id"], ",".join(x["needles"])[:28],
                     x["old_hits"], x["new_hits"], x["difference"], x["status"]))
        print("-> %s" % os.path.relpath(OUT, VAULT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
