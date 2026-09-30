#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_ontology_v4a1_repairs.py — Phase 4A.1：把「修复」如实写回缺口队列

它做什么（§9）
──────────────
对 `_data/ontology_gap_queue.jsonl` 里每一条 `candidate`：

* 如果本层已经补上了缺失实体 / 拆开了碰撞 → **追加**一条 `status: resolved`
  （带 `resolution_commit` / `resolved_entity_ids` / `resolution_evidence` / 理由）；
* 如果这条记录本身就不成立（例如 `Lacan` 是人名而非概念术语）
  → 追加 `status: invalidated` 并给出理由；
* 仍然成立的 → 保持 `candidate`，不动。

**绝不物理删除**（§9）：历史行永远留在文件里，`read_all()` 读到的是最后一行。

幂等：目标状态已经是当前状态时不重复追加。

产物
────
    _data/ontology_gap_queue.jsonl                      （追加状态更新行）
    _data/ontology/v4a1/gap_resolutions.jsonl           （本次处理的审计副本）

用法
────
    python3 apply_ontology_v4a1_repairs.py [--check]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import ontology_gaps as ogq          # noqa: E402
import ontology_v4a1 as onto         # noqa: E402

LAYER = os.path.join(VAULT, "_data", "ontology", "v4a1")
AUDIT = os.path.join(LAYER, "gap_resolutions.jsonl")

# 明确判定为「本条记录不成立」的情形（会写 invalidated + 理由）
INVALIDATED = {
    "Lacan": ("「Lacan」是人名，不是概念术语 —— 概念库里没有它并不构成 ontology gap；"
              "该条目来自 4A 早期按词面抽取的候选，本层据术语有效性判定为**失效**记录。"),
}


def decide(row):
    """→ (status, entities, evidence, reason) 或 None（保持 candidate）。"""
    import knowledge_api as api
    term = row.get("term")
    if term in INVALIDATED:
        return "invalidated", [], [], INVALIDATED[term]
    itype = row.get("issue_type")
    if itype == "missing_entity":
        res = api.resolve_entity(term)["resolution"]
        if res["resolution_status"] == "UNRESOLVED":
            return None
        ents = [c["entity_id"] for c in res["candidates"]]
        reason_extra = ""
        if not ents and res.get("context_required"):
            # 上下文受限：实体**已存在**，只是该裸形式不自动解析
            ents = list(res.get("context_required_entities") or [])
            reason_extra = ("；该裸形式是**上下文受限**别名，实体已建立但需上下文才解析"
                            "（不是缺实体）")
        ev = []
        for c in ents:
            e = onto.entity(c)
            if e:
                ev += list(e.get("passages") or [])[:2]
        return ("resolved", ents, ev[:3],
                "ontology.v4a1 已建立该词对应的实体（%s）；解析状态 %s%s"
                % (ents, res["resolution_status"], reason_extra))
    if itype == "entity_collision":
        res = api.resolve_entity(term)["resolution"]
        if res["resolution_status"] == "ENTITY_COLLISION":
            return None
        return ("resolved", [c["entity_id"] for c in res["candidates"]], [],
                "碰撞已拆分为独立实体（mig.v4a1.001 entity_split）")
    if itype == "missing_terminology_mapping":
        ev = api.terminology_lookup(term)
        if not (ev.get("resolution") or {}).get("candidates"):
            return None
        return ("resolved", [e["entity_id"] for e in ev["resolution"]["entities"]], [],
                "ontology.v4a1 已建立受控术语映射（controlled_term_mapping）")
    return None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    commit = onto.layer_meta().get("resolution_ref")
    rows = ogq.read_all()
    out, changed = [], 0
    for r in rows:
        d = decide(r)
        if not d:
            out.append({"issue_id": r["issue_id"], "term": r.get("term"),
                        "issue_type": r.get("issue_type"), "action": "still_open",
                        "status": r.get("status")})
            continue
        status, ents, ev, reason = d
        already = (r.get("status") == status)
        entry = {"issue_id": r["issue_id"], "term": r.get("term"),
                 "issue_type": r.get("issue_type"), "action": status,
                 "status": status, "resolution_commit": commit,
                 "resolved_entity_ids": ents, "resolution_evidence": ev,
                 "resolution_reason": reason, "already_applied": already,
                 "layer": onto.LAYER_ID}
        out.append(entry)
        if not already and not a.check:
            ogq.update_status(r["issue_id"], status, resolution_commit=commit,
                              resolved_entity_ids=ents, evidence=ev, reason=reason)
            changed += 1
    if not a.check:
        os.makedirs(LAYER, exist_ok=True)
        with open(AUDIT, "w", encoding="utf-8") as f:
            for e in out:
                f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    print("缺口状态处理：%d 条记录，其中 %d 条本次更新（resolution_ref=%s）"
          % (len(out), changed, commit))
    for e in out:
        print("  %-16s %-12s %-14s %s" % (e["issue_id"][:16], e["term"],
                                          e["action"],
                                          (e.get("resolution_reason") or "")[:60]))
    if a.check:
        # 只检查**本脚本审计文件里记录过的**状态更新是否已应用。
        # ⚠️ 第一版把「所有 candidate 都不得再可解析」当成判据 —— 那会在
        #    Phase 4B 往队列里写新候选（研究用词）后误报：新候选本来就该由
        #    人来决定，不该被本脚本追着改。
        import json as _json
        if not os.path.isfile(AUDIT):
            print("缺审计文件 %s（先跑一次不带 --check）" % AUDIT)
            return 1
        audit = [(_json.loads(l)) for l in open(AUDIT, encoding="utf-8") if l.strip()]
        live = {r["issue_id"]: r["status"] for r in ogq.read_all()}
        bad = [e["term"] for e in audit
               if e["action"] in ("resolved", "invalidated")
               and live.get(e["issue_id"]) != e["action"]]
        if bad:
            print("审计文件里记录的状态更新未生效：%s" % bad)
            return 1
        print("审计文件里 %d 条状态更新均已生效（新候选由人决定，不自动改）"
              % len([e for e in audit if e['action'] in ('resolved', 'invalidated')]))
    print("统计：%s" % json.dumps(ogq.stats(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
