#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_spot_review_packet.py — Phase 4E §38：把 6 题人工抽查的**输入材料**打印出来。

只读。它不评分、不写任何文件；输出供 reviewer 逐题按 §39 的五项检查判断
（学术退化 / citation-evidence mismatch / 过度断言 / 弃权泄漏 / adapter 截断或畸形综合），
结论由 reviewer 写进 `_data/phase4e/human_spot_review.jsonl`。

用法：
    python3 _scripts/_tools/phase4e_spot_review_packet.py --run <4E run 目录> [--task rt-D01]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))

SPOT = ["rt-D01", "rt-I02", "rt-H02", "rt-C03", "rt-J02", "rt-G01"]


def load_rows(run_dir):
    p = os.path.join(run_dir, "task_results.jsonl")
    return {json.loads(l)["task_id"]: json.loads(l)
            for l in open(p, encoding="utf-8") if l.strip()}


def show(tid, row, width=260):
    fa = row.get("final_answer") or {}
    print("=" * 100)
    print("%s | %s | mode=%s | task_type=%s | %s | provider=%s/%s | %.0fs"
          % (tid, row.get("answer_state"), row.get("product_mode"), row.get("task_type"),
             row.get("task_type_fidelity"), row.get("provider"), row.get("model"),
             row.get("synthesis_latency_s") or 0))
    print("Q: %s" % row.get("question"))
    print("contract=%s permission=%s | claims gen=%s repaired=%s rejected=%s validated=%s"
          % (row.get("contract_status"), row.get("answer_permission"),
             row.get("generated_claims"),
             len((row.get("entailment") or {}).get("repaired") or []),
             len((row.get("entailment") or {}).get("rejected") or []),
             len(row.get("validated_claims") or [])))
    ent = {r.get("final_claim_id") or r.get("claim_id"): r
           for r in ((row.get("entailment") or {}).get("results") or [])}
    print("-- 最终 claims --")
    for c in fa.get("validated_claims") or []:
        e = ent.get(c.get("claim_id")) or {}
        print("  [%s/%s/%s] %s" % (c.get("claim_type"), c.get("epistemic_status"),
                                   e.get("status"),
                                   str(c.get("claim_text"))[:width]))
        print("      evidence=%s" % (c.get("evidence_ids") or []))
    print("-- 被剔除（rejected）--")
    for r in ((row.get("entailment") or {}).get("rejected") or []):
        print("  [%s] %s" % (r.get("status"), str(r.get("claim_text"))[:120]))
    print("-- citations --")
    for c in fa.get("citations") or []:
        print("  %s | %s | %s | %s" % (c.get("passage_id"), c.get("source_layer"),
                                       c.get("provenance_status"),
                                       str(c.get("quoted_span"))[:90]))
    lim = fa.get("source_limitations") or []
    print("-- limitations (%d) --" % len(lim))
    for x in lim[:6]:
        print("  - %s" % str(x)[:220])
    ab = fa.get("abstention")
    if ab:
        print("-- abstention --")
        print("  category=%s missing=%d partial=%d sources=%s"
              % (ab.get("category") or ab.get("abstention_reason_codes"),
                 len(ab.get("missing_information") or []),
                 len(ab.get("available_partial_information") or []),
                 str(ab.get("required_sources") or ab.get("next_required_sources"))[:120]))
    sec = fa.get("sections") or {}
    print("-- sections: %s --" % sorted(sec.keys()))
    brief = sec.get("brief_answer") or sec.get("answer") or ""
    print("  brief: %s" % str(brief)[:400])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4E spot review packet")
    ap.add_argument("--run", required=True)
    ap.add_argument("--task", default=None)
    a = ap.parse_args(argv)
    rows = load_rows(a.run if os.path.isabs(a.run) else os.path.join(VAULT, a.run))
    for tid in ([a.task] if a.task else SPOT):
        if tid in rows:
            show(tid, rows[tid])
        else:
            print("!! 缺少 %s" % tid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
