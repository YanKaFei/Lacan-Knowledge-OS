#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase5c_acceptance.py — Phase 5C §59/§60：Bibliography Gate v1 的冻结与验收。

    python3 _scripts/_tools/phase5c_acceptance.py --freeze-gate   # 先冻结
    python3 _scripts/_tools/phase5c_acceptance.py --run [--regression path]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
for _p in (VAULT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

P5C = os.path.join(VAULT, "_data", "phase5c")
GATE = os.path.join(P5C, "phase5c_bibliography_gate_v1.json")

CRITERIA = [
    ("C1", "Passage/Witness/Edition/BibliographicItem collisions = 0"),
    ("C2", "fake bibliographic metadata = 0"),
    ("C3", "fake page locator = 0"),
    ("C4", "incomplete metadata rendered as full citation = 0"),
    ("C5", "citation capability violations = 0"),
    ("C6", "Zotero auto-canonicalization violations = 0"),
    ("C7", "metadata conflict silent overwrite = 0"),
    ("C8", "project backward compatibility PASS"),
    ("C9", "Obsidian user-content preservation PASS"),
    ("C10", "citation renderer cross-surface identity PASS"),
    ("C11", "security violations = 0"),
    ("C12", "scholarly semantic drift = 0"),
    ("C13", "full regression failed=[] skipped=[]"),
    ("C14", "core freeze PASS"),
    ("C15", "freeze lineage PASS"),
]


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def jd(p, d=None):
    if not os.path.isfile(p):
        return d
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def wr(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def sha_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def gate_payload():
    return {
        "schema_version": "phase5c-bibliography-gate/v1",
        "gate_id": "Phase 5C Bibliography Gate v1",
        "phase": "Phase 5C — Bibliography & Zotero Research Layer",
        "frozen": True, "frozen_at": utcnow(), "frozen_before_final_run": True,
        "git_head": subprocess.run(["git", "-C", VAULT, "rev-parse", "HEAD"],
                                   capture_output=True, text=True).stdout.strip(),
        "entities_that_must_stay_distinct": [
            "Passage", "Witness", "Edition", "BibliographicItem", "CorpusSource",
            "ProjectBibliographyRef", "ZoteroItem"],
        "not_in_scope": ["Corpus Expansion", "Cloud", "Multi-user", "Collaboration",
                         "New ontology"],
        "criteria": [{"id": i, "requirement": r, "blocking": True} for i, r in CRITERIA],
        "decision_values": ["PHASE_5C_COMPLETE", "PHASE_5C_BLOCKED"],
        "policy": {
            "any_criterion_fail": "PHASE_5C = BLOCKED",
            "no_gate_edits_after_freeze": True,
            "no_history_rewrite": "失败的 run 保留，修完新开 run",
            "no_metadata_inference": True,
            "no_fake_page_locator": True,
            "zotero_is_not_source_of_truth": True,
            "offline_by_default": True,
            "does_not_touch_scholarly_semantics": True,
            "stop_after_5c": "不得自动进入 5D Corpus Expansion / 5E Cloud",
        },
    }


def freeze_gate():
    if os.path.isfile(GATE):
        cur = jd(GATE)
        body = {k: v for k, v in gate_payload().items() if k != "frozen_at"}
        old = {k: v for k, v in cur.items() if k not in ("frozen_at", "gate_hash")}
        if body != old:
            print("FAIL Gate 已存在且判据发生变化 —— 冻结后不得修改")
            return 1
        print("Gate 已冻结且未改动：%s（%d 条判据）"
              % (os.path.relpath(GATE, VAULT), len(cur.get("criteria") or [])))
        return 0
    doc = gate_payload()
    doc["gate_hash"] = hashlib.sha256(json.dumps(
        {k: v for k, v in doc.items() if k != "gate_hash"},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    wr(GATE, doc)
    print("frozen gate -> %s（%d 条判据；gate_hash=%s）"
          % (os.path.relpath(GATE, VAULT), len(doc["criteria"]),
             doc["gate_hash"][:16]))
    return 0


# ─────────────────────────────────────────────────────────── 验收
def evaluate(regression_path):
    import bibliography as B
    from bibliography import model as M, registry as R, render as RD, zotero as Z
    from workspace_ui.server import bibliography as UIB
    import project_api as PA
    import project_api.bibliography as PB
    from project_api import store as S
    import obsidian_adapter.bibliography as OB
    from obsidian_adapter import vault as OV

    items = []

    def add(cid, ok, evidence):
        items.append({"id": cid, "status": "PASS" if ok else "FAIL",
                      "requirement": dict(CRITERIA)[cid],
                      "evidence": str(evidence)[:420]})
        print("  %-4s %-5s %s" % (cid, items[-1]["status"], str(evidence)[:160]),
              flush=True)

    reg_items, cand_items = R.items(), R.candidates()
    eds, wits, maps, works = R.editions(), R.mappings(), R.mappings(), R.works()
    reviewed = [i["bibliographic_id"] for i in reg_items]

    # C1：四类实体 id 不冲突
    ns = {"passage": set(), "witness": set(), "edition": set(), "bib": set(),
          "corpus_source": set(), "work": set()}
    for m in maps:
        if m.get("witness_id"):
            ns["witness"].add(m["witness_id"])
        if m.get("corpus_source_id"):
            ns["corpus_source"].add(m["corpus_source_id"])
    for e in eds:
        ns["edition"].add(e["edition_id"])
    for i in reg_items + cand_items:
        ns["bib"].add(i["bibliographic_id"])
    for w in works:
        ns["work"].add(w["work_id"])
    collisions = []
    pref = [("passage.", "passage"), ("witness.", "witness"), ("edition.", "edition"),
            ("bib.", "bib"), ("corpus-source.", "corpus_source"), ("work.", "work")]
    allids = [(v, k) for k, vs in ns.items() for v in vs]
    for v, k in allids:
        for p, kk in pref:
            if v.startswith(p) and kk != k:
                collisions.append("%s(%s) 命中 %s 命名空间" % (v, k, kk))
    add("C1", not collisions, "id 命名空间冲突=%s；样例 passage→witness→edition→bib "
        "链=%s" % (collisions[:3],
                   [(m.get("witness_id"), m.get("edition_id"), m.get("bibliographic_id"))
                    for m in maps if m.get("witness_id")][:2]))

    # C2：无伪书目 metadata（有值必须有 provenance；无占位）
    fake = []
    for it in reg_items + cand_items:
        prov = it.get("metadata_provenance") or {}
        for f in ("publisher", "publication_year", "publication_place", "isbn", "doi",
                  "edition", "title", "authors"):
            v = it.get(f)
            if v in (None, "", [], {}):
                continue
            if not (prov.get(f) or {}).get("source"):
                fake.append("%s.%s" % (it["bibliographic_id"], f))
        for f in ("publisher", "publication_year", "isbn", "doi"):
            v = it.get(f)
            if isinstance(v, str) and v.strip().lower() in ("unknown", "n/a", "????"):
                fake.append("%s.%s=占位" % (it["bibliographic_id"], f))
    for e in eds:                       # §8：仓库未记录 → 必须 null
        for f in ("publisher", "year", "isbn"):
            if e.get(f) not in (None, ""):
                fake.append("%s.%s=%r" % (e["edition_id"], f, e[f]))
    for it in reg_items:
        if it.get("review_status") != "reviewed":
            fake.append("%s 在 items 里却不是 reviewed" % it["bibliographic_id"])
        if it.get("review_basis") in (None, "PENDING_HUMAN_REVIEW", "NONE"):
            fake.append("%s reviewed 无可核依据" % it["bibliographic_id"])
    for it in cand_items:
        if it.get("review_status") == "reviewed":
            fake.append("%s 是 candidate 却标 reviewed" % it["bibliographic_id"])
    add("C2", not fake, "无 provenance / 占位 / 评审依据缺失=%s；bases=%s"
        % (fake[:4], sorted({(i.get("review_basis") or "-") for i in reg_items})))

    # C3：无伪页码
    bad_pages = []
    for it in reg_items + cand_items:
        pl = it.get("page_locator")
        if pl:
            if pl.get("kind") not in M.PAGE_LOCATOR_KINDS:
                bad_pages.append("%s 非法 kind" % it["bibliographic_id"])
            if re.match(r"^passage\.", str(pl.get("value") or "")):
                bad_pages.append("%s passage 号冒充 page" % it["bibliographic_id"])
        if it.get("pages") not in (None, "", [], {}):
            if not ((it.get("metadata_provenance") or {}).get("pages") or {}).get("source"):
                bad_pages.append("%s.pages 无 provenance" % it["bibliographic_id"])
    add("C3", not bad_pages, "伪页码=%s；page 类 locator=%s"
        % (bad_pages[:3], [(e["edition_id"], e["page_locator_available"]) for e in eds]))

    # C4/C5：能力矩阵与可渲染性**双向一致**
    c4, c5 = [], []
    styles = ("chicago", "apa", "mla", "bibtex")
    for it in reg_items:
        caps = RD.capability_matrix(it)
        for s in styles:
            try:
                txt = RD.render_bibliographic(it, s)
                rendered = bool(txt and txt.strip())
                err = None
            except ValueError as exc:
                rendered, err = False, str(exc)
            if caps.get(s) and not rendered:
                c5.append("%s.%s 声称可用但渲染失败" % (it["bibliographic_id"], s))
            if (not caps.get(s)) and rendered:
                c4.append("%s.%s 声称不可用却渲染出内容" % (it["bibliographic_id"], s))
            if rendered and ("Unknown" in txt or "????" in txt):
                c4.append("%s.%s 渲染含占位" % (it["bibliographic_id"], s))
    add("C4", not c4, "不完整 metadata 被当完整 citation 渲染=%s" % c4[:3])
    add("C5", not c5, "能力矩阵与渲染不一致=%s；样例 caps=%s"
        % (c5[:3], {s: RD.capability_matrix(reg_items[0]).get(s) for s in styles}))

    # C6：Zotero 不得自动 canonicalize
    sample = json.dumps([{"id": "C6KEY1", "type": "book", "title": "Test Volume",
                          "author": [{"literal": "Test Author"}],
                          "published": "1966",
                          "issued": {"date-parts": [[1966]]}}])
    imp = Z.import_file(sample, "csl-json")
    leaked = [c["candidate_id"] for c in imp["candidates"]
              if c["review_status"] == "reviewed" or c["canonicalized"]]
    inreg = [c["candidate_id"] for c in imp["candidates"]
             if c["candidate_id"] in reviewed]
    add("C6", not leaked and not inreg,
        "导入候选 %d 条；自动晋级=%s；混入 registry=%s"
        % (len(imp["candidates"]), leaked, inreg))

    # C7：冲突不得静默覆盖
    conflict_feed = json.dumps([
        {"id": "C7KEY", "type": "book", "title": "Test Volume",
         "author": [{"literal": "Test Author"}], "ISBN": "9780306406157",
         "issued": {"date-parts": [[1966]]}},
        {"id": "C7KEY2", "type": "book", "title": "Test Volume",
         "author": [{"literal": "Test Author"}], "ISBN": "9780306406157",
         "issued": {"date-parts": [[1967]]}}])
    imp2 = Z.import_file(conflict_feed, "csl-json")
    ok7 = bool(imp2["conflicts"]) and all(
        (not c["auto_overwrite"]) and len(c["values"]) >= 2 for c in imp2["conflicts"])
    add("C7", ok7, "conflicts=%d；fields=%s；auto_overwrite=%s；两来源保留=%s"
        % (len(imp2["conflicts"]), [c["field"] for c in imp2["conflicts"]],
           [c["auto_overwrite"] for c in imp2["conflicts"]],
           all(len(c["values"]) >= 2 for c in imp2["conflicts"])))

    # C8：项目向后兼容
    tmp = tempfile.mkdtemp(dir=os.path.join(VAULT, "_workspace"))
    prev = S.PROJECTS_DIR
    S.PROJECTS_DIR = tmp
    c8, c8ev = False, ""
    try:
        p = PA.create_project("P5C 验收隔离项目", "", ["p5c"])
        pid = p["project_id"]
        PA.add_bibliography_ref(pid, p.get("revision"), "Legacy Ref",
                                author="Test Author", year=1966)
        out = PB.list_bibliography(pid)
        legacy_ok = (len(out["legacy_user_supplied_refs"]) == 1
                     and out["legacy_user_supplied_refs"][0]["bibliographic_id"] is None
                     and out["legacy_user_supplied_refs"][0]["user_supplied"] is True)
        link_ok = True
        try:
            PB.link_legacy_ref(pid, None, out["legacy_user_supplied_refs"][0]["ref_id"],
                               "bib.doc.lacan.seminar-3")
        except Exception:                                                  # noqa: BLE001
            link_ok = False
        new_ok = True
        try:
            PB.add_bibliographic_item(pid, None, "bib.doc.lacan.seminar-3")
        except Exception:                                                  # noqa: BLE001
            new_ok = False
        c8 = legacy_ok and link_ok and new_ok
        c8ev = ("legacy 可读=%s；显式关联=%s；新式挂接=%s"
                % (legacy_ok, link_ok, new_ok))
    finally:
        S.PROJECTS_DIR = prev
        shutil.rmtree(tmp, ignore_errors=True)
    add("C8", c8, c8ev)

    # C9：Obsidian 用户区保留
    iso = os.path.join(VAULT, "_workspace", "acceptance", "p5c_gate", "vault")
    shutil.rmtree(iso, ignore_errors=True)
    c9, c9ev = False, ""
    try:
        v = OV.Vault(os.path.relpath(iso, VAULT))
        res = OB.save_bibliography_note("bib.doc.lacan.seminar-3", vault=v)
        txt = v.read(res["note"])
        v.write(res["note"], txt.rstrip("\n") + "\n\n## My Notes\n\n用户自己的字。\n")
        before = v.read(res["note"])
        OB.save_bibliography_note("bib.doc.lacan.seminar-3", vault=v)
        after = v.read(res["note"])
        c9 = (before == after and res["note"].startswith("_System/bibliography/")
              and "\nid:" not in after.split("---")[1]
              and "influence" not in after)
        c9ev = "用户区逐字节保留=%s；派生路径=%s" % (before == after, res["note"])
    except Exception as exc:                                               # noqa: BLE001
        c9ev = "异常：%s: %s" % (type(exc).__name__, str(exc)[:120])
    finally:
        shutil.rmtree(iso, ignore_errors=True)
    add("C9", c9, c9ev)

    # C10：跨表面同一性（registry / UI / Export 桥 / Obsidian 笔记同值）
    it0 = reg_items[0]
    ui_caps = UIB.capabilities(it0["bibliographic_id"])
    bridge = RD._bib_dict(it0)
    import export_system as EX
    rec = EX.citations.citation_record("passage.S11.unknown.P2253", bibliographic=bridge)
    same = (ui_caps["missing_fields"] ==
            RD.capability_matrix(it0)["missing_fields"]
            and rec["capabilities"]["chicago"] == RD.capability_matrix(it0)["chicago"])
    idh = [RD.citation_identity_hash(it0, s) for s in ("chicago", "apa", "mla", "bibtex")]
    add("C10", same and len(set(idh)) == len(idh),
        "UI/registry 能力矩阵一致=%s；export 桥 chicago 能力=%s（与 registry 一致）；"
        "四样式 identity hash 互异=%s"
        % (ui_caps["missing_fields"] == RD.capability_matrix(it0)["missing_fields"],
           rec["capabilities"]["chicago"], len(set(idh)) == len(idh)))

    # C11：安全
    sec, secev = [], []
    for bad in ("../../etc/passwd", "<script>x</script>", "a/b", "x" * 300):
        rr = Z.import_file(json.dumps([{"id": bad, "title": "t"}]), "csl")
        if rr["candidates"] or not rr["rejected"]:
            sec.append("unsafe key 未被拒绝: %r" % bad[:30])
    rr = Z.import_file(json.dumps([{"id": "S1", "title": "t",
                                    "URL": "javascript:alert(1)"}]), "csl")
    if rr["candidates"]:
        sec.append("javascript: URL 未被拒绝")
    try:
        Z.import_file("<x/>", "rdf")
        sec.append("XML 未被拒绝")
    except Z.ImportError_:
        pass
    try:
        Z.import_file("[" + ",".join(["{}"] * (Z.MAX_ITEMS + 5)) + "]", "csl")
        sec.append("超大导入未被拒绝")
    except Z.ImportError_:
        pass
    r3 = Z.import_file(json.dumps([{"id": "S2",
                                    "title": "<img src=x onerror=alert(1)>Safe"}]),
                       "csl")
    if "<img" in (r3["candidates"][0]["title"] or ""):
        sec.append("HTML 注入未净化")
    try:
        if M.safe_url("data:text/html;base64,AAA"):
            sec.append("data: URL 未被拒")
    except ValueError:
        pass                        # 抛错 = 正确拒绝（§43）
    secev = "违规=%s" % sec[:4]
    add("C11", not sec, secev)

    # C12：学术语义漂移
    lin = jd(os.path.join(VAULT, "_data", "core_freeze", "freeze_lineage.json"), {}) or {}
    add("C12", lin.get("semantic_changes_total") == 0
        and lin.get("all_segments_status_pass"),
        "谱系 semantic_total=%s；data_version=%s；product_runtime=%s"
        % (lin.get("semantic_changes_total"), lin.get("data_version_changes_total"),
           lin.get("product_runtime_changes_total")))

    # C13：回归
    reg_path = regression_path or os.path.join(P5C, "regression.json")
    reg = jd(reg_path, {}) or {}
    add("C13", reg.get("exit_code") == 0 and not reg.get("failed")
        and not reg.get("skipped"),
        "regression exit=%s suites=%s checks=%s failed=%s skipped=%s"
        % (reg.get("exit_code"), reg.get("suites"), reg.get("checks"),
           reg.get("failed"), reg.get("skipped")))

    # C14/C15
    def tool(name, *args):
        r = subprocess.run([sys.executable, os.path.join(HERE, name), *args],
                           capture_output=True, text=True, cwd=VAULT)
        return r.returncode
    rc14 = tool("core_freeze.py", "--verify", "--quiet")
    rc15 = tool("freeze_lineage.py", "--verify")
    add("C14", rc14 == 0, "core_freeze --verify exit=%s" % rc14)
    add("C15", rc15 == 0, "freeze_lineage --verify exit=%s" % rc15)

    failed = [i["id"] for i in items if i["status"] != "PASS"]
    return items, ("PHASE_5C_COMPLETE" if not failed else "PHASE_5C_BLOCKED"), failed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze-gate", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--regression", default=None)
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args(argv)
    if a.freeze_gate:
        return freeze_gate()
    if not a.run:
        return freeze_gate()
    gate = jd(GATE)
    if not gate:
        print("FAIL 缺冻结 Gate（先 --freeze-gate）")
        return 2
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_id = a.run_id or "5c_acceptance_%s_%s" % (stamp, sha_file(GATE)[:8])
    run_dir = os.path.join(P5C, run_id)
    os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)
    print("== Phase 5C acceptance ==", flush=True)
    res = evaluate(a.regression)
    if res[0] is None:
        return 1
    items, decision, failed = res
    wr(os.path.join(run_dir, "gate_results.json"),
       {"gate_id": gate["gate_id"], "gate_hash": gate["gate_hash"],
        "items": items, "failed": failed, "decision": decision})
    wr(os.path.join(run_dir, "manifest.json"), {
        "schema_version": "phase5c-acceptance-manifest/v1", "run_id": run_id,
        "created_at": utcnow(),
        "head": subprocess.run(["git", "-C", VAULT, "rev-parse", "HEAD"],
                               capture_output=True, text=True).stdout.strip(),
        "gate_id": gate["gate_id"], "gate_hash": gate["gate_hash"],
        "gate_file_sha256": sha_file(GATE),
        "registry_manifest": "_data/bibliography/manifest.json",
        "regression": (os.path.relpath(a.regression, VAULT) if a.regression
                       else "_data/phase5c/regression.json"),
        "decision": decision})
    wr(os.path.join(run_dir, "final_decision.json"), {
        "schema_version": "phase5c-final-decision/v1", "run_id": run_id,
        "decision": decision, "items": items, "failed": failed,
        "criteria_pass": sum(1 for i in items if i["status"] == "PASS"),
        "criteria_total": len(items),
        "next_capabilities": {
            "bibliography_layer": "READY" if decision == "PHASE_5C_COMPLETE" else "BLOCKED"},
        "stopped_after_5c": True,
        "finished_at": utcnow()})
    print("decision: %s（failed=%s）" % (decision, failed))
    print("artifacts: %s" % os.path.relpath(run_dir, VAULT))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
