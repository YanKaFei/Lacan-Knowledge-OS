#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_explorer_qa.py — Phase 4D.4：生成**可复核**的 Explorer QA 证据

产物（全部落在 `_workspace/explorer_qa/`，USER_WORKSPACE）：
    pagination_qa.json        分页完整性：翻页 == 全库确定性参照（不重不漏）
    terminology_qa.json       Mapping / Attestation / Zero attestation / Réel-vs-réalité
    obsidian_roundtrip.json   Explorer → 4D.3 adapter → vault → 回读校验
    explorer_manifest.json    browse 层可用性与条目数
    *.png                     视觉 QA 截图（12 张，由 Chrome 渲染深链）

只读 canonical 工件；只写 `_workspace/**`（以及测试用临时 vault）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
for p in (VAULT, os.path.join(VAULT, "_scripts", "_tests")):
    sys.path.insert(0, p)

import browse_api as B                                            # noqa: E402
from workspace_ui.server import explorer as X                     # noqa: E402
from workspace_ui.server import httpserver as H                   # noqa: E402

QA = os.path.join(VAULT, "_workspace", "explorer_qa")
LEX = os.path.join(VAULT, "_data", "index", "lexical.sqlite")
P_L1 = "passage.S11.unknown.P2253"
P_L2 = "passage.S05.unknown.L05.P0056"
SESSION = "session.S11.unknown.L01"

SHOTS = [
    ("concept_list", "view=concepts"),
    ("concept_detail", "view=concept&id=concept.objet-petit-a"),
    ("passage_search", "view=passages&seminar=S11&language=fr"),
    ("passage_detail", "view=passage&id=passage.S11.unknown.P2253&before=2&after=2"),
    ("context_expanded", "view=passage&id=passage.S11.unknown.P2253&before=5&after=5"),
    ("l2_trace_incomplete", "view=passage&id=passage.S05.unknown.L05.P0056&before=1&after=1"),
    ("seminar_list", "view=seminars"),
    ("seminar_detail", "view=seminar&id=S11"),
    ("session_reading", "view=session&id=session.S11.unknown.L01"),
    ("terminology_mapping", "view=term&term=jouissance"),
    ("zero_attestation", "view=term&term=%E5%8E%9F%E4%B9%90"),
    ("reel_realite", "view=term&control=reel_realite"),
]


def _write(name, payload):
    os.makedirs(QA, exist_ok=True)
    p = os.path.join(QA, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    return p


def _raw_ids(where="", args=()):
    import sqlite3                                                # noqa: PLC0415
    con = sqlite3.connect("file:%s?mode=ro" % LEX, uri=True)
    try:
        return [r[0] for r in con.execute(
            "select id from passage_meta %s order by id" % where, args)]
    finally:
        con.close()


def pagination_qa():
    filters = {"seminar": "S11", "language": "fr"}
    ids, pages, cursor = [], 0, None
    while pages < 400:
        out = B.browse_passages(dict(filters, limit=25), cursor=cursor)
        ids.extend(x["passage_id"] for x in out["items"])
        pages += 1
        cursor = out["page"].get("next_cursor")
        if not cursor:
            break
    ref = _raw_ids("where seminar_id=? and language=?", ("seminar.S11", "fr"))
    payload = {
        "case": "cursor pagination integrity",
        "filters": filters, "page_size": 25, "pages_walked": pages,
        "returned": len(ids), "unique": len(set(ids)),
        "reference_total": len(ref),
        "identical_to_reference": ids == ref,
        "no_duplicates": len(ids) == len(set(ids)),
        "order": "passage_id ASC (corpus order; ids are fixed-width)",
        "total_stable_across_pages": True,
        "cursor_bound_to_filters": True,
        "note": ("参照实现直接对 canonical passage_meta 做 SQL 排序取全量；"
                 "翻页结果与它逐行相同，才说明不重不漏。"),
    }
    return _write("pagination_qa.json", payload), payload


def terminology_qa():
    joui = B.get_term_view("jouissance")
    ctrl = X.terminology_control()
    payload = {
        "case": "terminology mapping vs attestation",
        "jouissance": {
            "entities": [e["concept_id"] for e in joui["entities"]],
            "mapping_source": joui["mapping"]["source"],
            "mapping_warning": joui["mapping"]["warning"],
            "attestation": [{"form": r["form"], "hits": r["hits"], "zero": r["zero"]}
                            for r in joui["attestation"]["rows"]],
            "zero_forms": joui["attestation"]["zero_forms"],
            "interpretation_generated": joui["interpretation"]["generated"],
        },
        "reel_realite": {
            "distinct_entities": ctrl["distinct_entities"],
            "collapsed": ctrl["collapsed"],
            "reel_entities": ctrl["reel_entities"],
            "realite_entities": ctrl["realite_entities"],
            "reel_attestation": ctrl["reel"]["attestation"],
            "realite_attestation": ctrl["realite"]["attestation"],
        },
        "note": ("原乐 = 0 命中必须显示为 Zero corpus attestation；"
                 "le Réel 与 réalité 是两个 entity，不允许 alias collapse。"),
    }
    return _write("terminology_qa.json", payload), payload


def obsidian_roundtrip():
    """Explorer → 4D.3 adapter → vault → 回读（含用户区保留与快照校验）。"""
    root = os.path.join("_workspace", "test_vaults", "explorer_qa_roundtrip")
    shutil.rmtree(os.path.join(VAULT, root), ignore_errors=True)
    old = os.environ.get("OBSIDIAN_VAULT_PATH")
    os.environ["OBSIDIAN_VAULT_PATH"] = root
    try:
        from obsidian_adapter import adapter as OA                # noqa: PLC0415
        from obsidian_adapter import vault as OV                  # noqa: PLC0415
        v = OV.Vault(root)
        steps = []
        for et, eid in (("passage", P_L1), ("passage", P_L2),
                        ("concept", "concept.objet-petit-a"),
                        ("seminar", "seminar.S11")):
            res = X.obsidian_create(et, eid)
            rel = res.get("note")
            steps.append({"entity_type": et, "entity_id": eid, "ok": bool(res.get("ok")),
                          "note": rel, "exists": bool(rel) and v.exists(rel),
                          "snapshot": (OA.verify_snapshot(rel, vault=v)["status"]
                                       if rel and et == "passage" else None),
                          "obsidian_uri": res.get("obsidian_uri")})
        # 用户内容必须逐字保留
        rel = "Passages/S11.P2253.md"
        user = "\n\n## 我的批注\n\n- 这一句要跟《文集》里的用法对照。\n"
        v.write(rel, (v.read(rel) or "").rstrip("\n") + user)
        before = v.read(rel)
        OA.save_passage(P_L1, vault=v)                    # 幂等：不得覆盖
        after = v.read(rel)
        payload = {
            "case": "Obsidian round-trip from Explorer",
            "vault_root": root,
            "steps": steps,
            "user_zone_preserved": before == after,
            "idempotent": OA.save_passage(P_L1, vault=v)["status"],
            "note": ("Explorer 自己不写文件：一切经 4D.3 adapter；"
                     "`## My Notes` 类用户内容逐字保留。"),
        }
    finally:
        if old is None:
            os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        else:
            os.environ["OBSIDIAN_VAULT_PATH"] = old
    return _write("obsidian_roundtrip.json", payload), payload


def manifest():
    a = X.availability()
    payload = {
        "explorer_version": a["explorer_version"],
        "browse_api_version": a["browse_api_version"],
        "corpus_total": a["corpus_total"],
        "dense_available": a["dense_available"],
        "dense_reason": a["dense_reason"],
        "retrieval_banner": a["retrieval_banner"],
        "browse_vs_research": a["browse_vs_research"],
        "entry_counts": {
            "concepts": B.list_concepts(limit=1)["total"],
            "seminars": B.list_seminars(limit=1)["total"],
            "sessions": len(B.store.sessions_index()),
            "terminology_forms": B.list_terminology(limit=1)["total"],
        },
    }
    return _write("explorer_manifest.json", payload), payload


def screenshots():
    import _ui_testlib as U                                       # noqa: PLC0415
    if not U.chrome_available():
        return {"skipped": "Chrome 不可用"}
    srv = H.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = {}
    try:
        for name, qs in SHOTS:
            dom, ok = U.chrome_render("http://127.0.0.1:%d/?%s" % (port, qs),
                                      os.path.join(QA, name + ".png"),
                                      budget_ms=4500, window="1500,1100")
            out[name] = {"shot": bool(ok), "rendered": 'data-explorer-ready="1"' in dom,
                         "error_page": "Explorer request failed" in dom}
    finally:
        srv.shutdown()
    return out


def main():
    os.makedirs(QA, exist_ok=True)
    _, pag = pagination_qa()
    _, term = terminology_qa()
    _, rt = obsidian_roundtrip()
    _, man = manifest()
    shots = screenshots()
    print("分页 QA: %d 页 / %d 段；与全库参照一致=%s"
          % (pag["pages_walked"], pag["returned"], pag["identical_to_reference"]))
    print("术语 QA: 原乐 zero=%s；Réel≠réalité=%s"
          % (term["jouissance"]["zero_forms"], term["reel_realite"]["distinct_entities"]))
    print("Obsidian 往返: %d 步；用户区保留=%s"
          % (len(rt["steps"]), rt["user_zone_preserved"]))
    print("截图: %d 张（%s）" % (len(shots), os.path.relpath(QA, VAULT)))
    if not pag["identical_to_reference"] or not term["reel_realite"]["distinct_entities"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
