#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase5b_acceptance.py — Phase 5B：Entity Explorer Gate v1 的冻结与验收。

    python3 _scripts/_tools/phase5b_acceptance.py --freeze-gate   # 先冻结（最终 run 之前）
    python3 _scripts/_tools/phase5b_acceptance.py --run [--regression path]

判据 B1–B15（§32）。核心是**机器验证**那些"禁止推断"的性质（§31）：
提及 ≠ 影响；共现 ≠ 理论关系；个案提及 ≠ 个案分析；Person ≠ Case；别名 ≠ 概念同义。
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
for _p in (VAULT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

P5B = os.path.join(VAULT, "_data", "phase5b")
GATE = os.path.join(P5B, "phase5b_entity_explorer_gate_v1.json")
ENT = os.path.join(VAULT, "_data", "entities")

CRITERIA = [
    ("B1", "Person/Case collisions = 0"),
    ("B2", "automatic inference violations = 0"),
    ("B3", "reviewed/candidate confusion = 0"),
    ("B4", "mention/influence confusion = 0"),
    ("B5", "case mention/analysis confusion = 0"),
    ("B6", "reviewed entity missing provenance = 0"),
    ("B7", "Schreber separation PASS"),
    ("B8", "Project integration PASS"),
    ("B9", "Obsidian user preservation PASS"),
    ("B10", "pagination integrity PASS"),
    ("B11", "security violations = 0"),
    ("B12", "scholarly semantic drift = 0"),
    ("B13", "full regression clean"),
    ("B14", "core freeze PASS"),
    ("B15", "freeze lineage PASS"),
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
        "schema_version": "phase5b-entity-explorer-gate/v1",
        "gate_id": "Phase 5B Entity Explorer Gate v1",
        "phase": "Phase 5B — Person / Case Explorer",
        "frozen": True, "frozen_at": utcnow(), "frozen_before_final_run": True,
        "git_head": subprocess.run(["git", "-C", VAULT, "rev-parse", "HEAD"],
                                   capture_output=True, text=True).stdout.strip(),
        "scope": {
            "deliverables": ["Reviewed Person Registry", "Reviewed Case Registry",
                             "entity_browse_api", "Person Explorer", "Case Explorer",
                             "Project integration", "Obsidian reference notes",
                             "derived mention index"],
            "start_from_verifiable_entities_only": True,
            "no_automatic_full_corpus_ner_promotion": True,
        },
        "control_objects": ["Freud", "Hegel", "Kojève", "Descartes", "Saussure",
                            "Lévi-Strauss", "Schreber", "Aimée", "Dora", "Little Hans",
                            "Wolf Man"],
        "separation_invariants": {
            "person_is_not_case": True,
            "mention_is_not_influence": True,
            "cooccurrence_is_not_theoretical_relation": True,
            "case_mention_is_not_case_analysis": True,
            "person_does_not_auto_collapse_into_case": True,
            "alias_is_not_conceptual_synonym": True,
        },
        "criteria": [{"id": i, "requirement": r, "blocking": True} for i, r in CRITERIA],
        "decision_values": ["PHASE_5B_COMPLETE", "PHASE_5B_BLOCKED"],
        "policy": {
            "any_criterion_fail": "PHASE_5B = BLOCKED",
            "no_gate_edits_after_freeze": True,
            "no_history_rewrite": "失败的 run 保留，修完新开 run",
            "no_inference_endpoints": True,
            "reviewed_requires_evidence_threshold": True,
            "stop_after_5b": "不得自动进入 5C Zotero / 5D Corpus Expansion / 5E Cloud",
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
    import entity_browse_api as E
    import project_api.entities as PE
    from project_api import store as S
    import obsidian_adapter.entities as OE
    from obsidian_adapter import vault as OV

    items = []

    def add(cid, ok, evidence):
        items.append({"id": cid, "status": "PASS" if ok else "FAIL",
                      "requirement": dict(CRITERIA)[cid],
                      "evidence": str(evidence)[:400]})
        print("  %-4s %-5s %s" % (cid, items[-1]["status"], str(evidence)[:150]),
              flush=True)

    pdoc = jd(os.path.join(ENT, "person_registry.json"), {}) or {}
    cdoc = jd(os.path.join(ENT, "case_registry.json"), {}) or {}
    man = jd(os.path.join(ENT, "registry_manifest.json"), {}) or {}
    if not pdoc or not cdoc:
        print("FAIL 缺登记表（先跑 build_entity_registries.py）")
        return None, None, ["B1"]

    pr = pdoc.get("reviewed") or []
    cr = cdoc.get("reviewed") or []
    pids = {r["id"] for r in pr}
    cids = {r["id"] for r in cr}

    # B1：Person/Case 命名空间不交叉
    add("B1", not (pids & cids),
        "person ids=%d / case ids=%d / 交集=%s"
        % (len(pids), len(cids), sorted(pids & cids)))

    # B2：推断端点一律被拒
    refused, leaking = [], []
    for op in E.FORBIDDEN_OPERATIONS:
        try:
            E.guarded(op)
            leaking.append(op)
        except E.InferenceNotSupported:
            refused.append(op)
    cross = []
    for eid, fn in (("case.schreber", E.get_person), ("person.schreber", E.get_case)):
        try:
            fn(eid)
            cross.append(eid)
        except E.InferenceNotSupported:
            pass
    add("B2", not leaking and not cross,
        "拒绝 %d/%d 个禁用操作；跨 kind 折叠被拒=%s；泄漏=%s"
        % (len(refused), len(E.FORBIDDEN_OPERATIONS), not cross, leaking))

    # B3：reviewed 必须有证据阈值；candidate 不得混入
    thr = man.get("min_mentions_threshold")
    bad_rev = [r["id"] for r in pr + cr
               if (r.get("mention_count") or 0) < thr
               or r.get("review_status") != "reviewed"]
    cand = [r["id"] for r in (pdoc.get("candidates_not_promoted") or [])
            + (cdoc.get("candidates_not_promoted") or [])]
    mixed = [c for c in cand if c in pids or c in cids]
    add("B3", not bad_rev and not mixed,
        "阈值=%s；不达标的 reviewed=%s；candidate 混入 reviewed=%s"
        % (thr, bad_rev, mixed))

    # B4/B5：任何位置都不得断言 influence / case_analysis
    def scan_flags(obj, path="", hits=None):
        hits = hits if hits is not None else []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("asserts_influence", "asserts_theoretical_relation",
                         "asserts_case_analysis") and v is True:
                    hits.append("%s.%s=true" % (path, k))
                if k in ("influence", "influences", "influenced_by",
                         "case_analysis", "theoretical_relation"):
                    hits.append("%s.%s 存在" % (path, k))
                scan_flags(v, "%s.%s" % (path, k), hits)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                scan_flags(v, "%s[%d]" % (path, i), hits)
        return hits

    reg_hits = scan_flags(pdoc, "person_registry") + scan_flags(cdoc, "case_registry")
    api_hits = scan_flags(E.manifest(), "entity_browse_api")
    add("B4", not reg_hits and not api_hits,
        "断言类字段命中=%s" % (reg_hits + api_hits)[:5])
    ca = [r["id"] for r in cr if r.get("asserts_case_analysis")]
    forb = set(E.manifest()["api"]["forbidden_operations"])
    add("B5", not ca and "case_analysis" in forb,
        "个案分析断言实体=%s；case_analysis 在禁用清单里=%s"
        % (ca, "case_analysis" in forb))

    # B6：reviewed 必须有 provenance
    miss = [r["id"] for r in pr + cr
            if not r.get("provenance") or not r.get("mention_sample_passage_ids")]
    add("B6", not miss, "缺 provenance 或提及样本的 reviewed=%s" % miss)

    # B7：Schreber 分离
    sch = man.get("schreber") or {}
    sp = E.get_person("person.schreber")
    sc = E.get_case("case.schreber")
    b7 = (sch.get("distinct_ids") is True
          and sp["id"] != sc["id"] and sp["mention_count"] > 0
          and sc["mention_count"] > 0
          and sc.get("subject_person") == "person.schreber"
          and bool((sc.get("subject_person_link") or {}).get("evidence_passage_ids")))
    add("B7", b7, "person=%s(%s) / case=%s(%s) / subject_person=%s / 连线证据=%s"
        % (sp["id"], sp["mention_count"], sc["id"], sc["mention_count"],
           sc.get("subject_person"),
           len((sc.get("subject_person_link") or {}).get("evidence_passage_ids") or [])))

    # B8：项目集成
    import tempfile
    import shutil
    import project_api as PA
    tmp = tempfile.mkdtemp(dir=os.path.join(VAULT, "_workspace"))
    prev = S.PROJECTS_DIR
    S.PROJECTS_DIR = tmp
    b8, b8ev = False, ""
    try:
        proj = PA.create_project("P5B 验收隔离项目", "", ["p5b"])
        pid = proj["project_id"]
        PE.add_entity_reference(pid, proj.get("revision"), "person.schreber", "person")
        PE.add_entity_reference(pid, None, "case.schreber", "case")
        refs = PE.list_entity_references(pid)["entity_references"]
        ids = sorted(r["entity_id"] for r in refs)
        kind_ok = all(r["evidence_kind"] == "MENTION_ONLY"
                      and not r["asserts_influence"]
                      and not r["asserts_case_analysis"] for r in refs)
        refused_mismatch = False
        try:
            PE.add_entity_reference(pid, None, "case.schreber", "person")
        except Exception:                                                  # noqa: BLE001
            refused_mismatch = True
        b8 = ids == ["case.schreber", "person.schreber"] and kind_ok and refused_mismatch
        b8ev = "refs=%s；mention-only=%s；kind 错配被拒=%s" % (ids, kind_ok, refused_mismatch)
    finally:
        S.PROJECTS_DIR = prev
        shutil.rmtree(tmp, ignore_errors=True)
    add("B8", b8, b8ev)

    # B9：Obsidian 用户区保留
    iso = os.path.join(VAULT, "_workspace", "acceptance", "p5b_gate", "vault")
    shutil.rmtree(iso, ignore_errors=True)
    b9, b9ev = False, ""
    try:
        v = OV.Vault(os.path.relpath(iso, VAULT))
        res = OE.save_entity_note("case.schreber", "case", vault=v)
        txt = v.read(res["note"])
        v.write(res["note"], txt.rstrip("\n") + "\n\n## My Notes\n\n用户自己的字。\n")
        before = v.read(res["note"])
        OE.save_entity_note("case.schreber", "case", vault=v)
        after = v.read(res["note"])
        b9 = before == after and "MENTION_ONLY" in after and "## My Notes" in after
        b9ev = ("用户区逐字节保留=%s；受管区含 MENTION_ONLY=%s；note=%s；"
                "不写 canonical 分区=%s"
                % (before == after, "MENTION_ONLY" in after, res["note"],
                   not res["note"].startswith(("07_Cases", "11_Thinkers"))))
    except Exception as exc:                                               # noqa: BLE001
        b9ev = "异常：%s: %s" % (type(exc).__name__, str(exc)[:120])
    finally:
        # ★ 隔离 vault 必须清理：否则派生笔记会被 `test_vault` 扫成实体（实测踩过）
        shutil.rmtree(iso, ignore_errors=True)
    add("B9", b9, b9ev)

    # B10：分页完整性
    def page_all(fetch):
        """fetch(cursor) → 响应；逐页取 id，直到 next_cursor 为空。"""
        seen, cur, guard = [], None, 0
        while guard < 400:
            guard += 1
            r = fetch(cur)
            seen += [i.get("id") or i.get("passage_id") for i in r["items"]]
            cur = r["page"]["next_cursor"]
            if not cur:
                break
        return seen

    pa = page_all(lambda c: E.list_persons(c, 2))
    ca2 = page_all(lambda c: E.list_cases(c, 2))
    mt = page_all(lambda c: E.mentions("case.schreber", c, 100))
    full_p = sorted(r["id"] for r in pr)
    full_c = sorted(r["id"] for r in cr)
    total_mentions = E.mentions("case.schreber", None, 1)["page"]["total"]
    bad_cursor = False
    try:
        E.decode_cursor("!!!not-base64!!!")
    except ValueError:
        bad_cursor = True
    b10 = (sorted(pa) == full_p and sorted(ca2) == full_c
           and len(mt) == len(set(mt)) == total_mentions and bad_cursor)
    add("B10", b10, "persons=%d/%d cases=%d/%d mentions=%d/%d 去重=%s 非法游标被拒=%s"
        % (len(pa), len(full_p), len(ca2), len(full_c), len(mt), total_mentions,
           len(mt) == len(set(mt)), bad_cursor))

    # B11：安全（不 import 冻结核心；id 不接受路径穿越；只读）
    def imports_of(path):
        tree = ast.parse(open(os.path.join(VAULT, path), encoding="utf-8").read())
        mods = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                mods.append(n.module or "")
        return mods

    banned = ("scholarly_api", "research_contract", "research_execution",
              "evidence_sufficiency", "synthesis_contract", "synthesis_adapters")
    bad_imp = [m for m in imports_of("entity_browse_api.py")
               if any(b in (m or "") for b in banned)]
    trav = False
    try:
        E.get_person("person.../../etc/passwd")
    except (KeyError, Exception):                                          # noqa: BLE001
        trav = True
    add("B11", not bad_imp and trav,
        "entity_browse_api 不 import 冻结核心=%s；穿越/未知 id 被拒=%s" % (not bad_imp, trav))

    # B12：学术语义漂移 = 0（来自谱系，按三类判定）
    lin = jd(os.path.join(VAULT, "_data", "core_freeze", "freeze_lineage.json"), {}) or {}
    add("B12", (lin.get("semantic_changes_total") == 0
                and lin.get("all_segments_status_pass")),
        "谱系 semantic_total=%s（data_version=%s / product_runtime=%s）全段 PASS=%s"
        % (lin.get("semantic_changes_total"), lin.get("data_version_changes_total"),
           lin.get("product_runtime_changes_total"), lin.get("all_segments_status_pass")))

    # B13：完整回归
    reg_path = regression_path or os.path.join(P5B, "regression.json")
    reg = jd(reg_path, {}) or {}
    add("B13", reg.get("exit_code") == 0 and not reg.get("failed")
        and not reg.get("skipped"),
        "regression exit=%s suites=%s checks=%s failed=%s skipped=%s"
        % (reg.get("exit_code"), reg.get("suites"), reg.get("checks"),
           reg.get("failed"), reg.get("skipped")))

    # B14/B15：冻结与谱系
    def tool(name, *args):
        r = subprocess.run([sys.executable, os.path.join(HERE, name), *args],
                           capture_output=True, text=True, cwd=VAULT)
        return r.returncode
    rc14 = tool("core_freeze.py", "--verify", "--quiet")
    rc15 = tool("freeze_lineage.py", "--verify")
    add("B14", rc14 == 0, "core_freeze --verify exit=%s" % rc14)
    add("B15", rc15 == 0, "freeze_lineage --verify exit=%s" % rc15)

    failed = [i["id"] for i in items if i["status"] != "PASS"]
    return items, ("PHASE_5B_COMPLETE" if not failed else "PHASE_5B_BLOCKED"), failed


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
    run_id = a.run_id or "5b_acceptance_%s_%s" % (
        stamp, sha_file(GATE)[:8])
    run_dir = os.path.join(P5B, run_id)
    os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)
    print("== Phase 5B acceptance ==", flush=True)
    res = evaluate(a.regression)
    if res[0] is None:
        return 1
    items, decision, failed = res
    wr(os.path.join(run_dir, "gate_results.json"),
       {"gate_id": gate["gate_id"], "gate_hash": gate["gate_hash"],
        "items": items, "failed": failed, "decision": decision})
    wr(os.path.join(run_dir, "manifest.json"), {
        "schema_version": "phase5b-acceptance-manifest/v1", "run_id": run_id,
        "created_at": utcnow(),
        "head": subprocess.run(["git", "-C", VAULT, "rev-parse", "HEAD"],
                               capture_output=True, text=True).stdout.strip(),
        "gate_id": gate["gate_id"], "gate_hash": gate["gate_hash"],
        "gate_file_sha256": sha_file(GATE),
        "registry_manifest": os.path.relpath(
            os.path.join(ENT, "registry_manifest.json"), VAULT),
        "regression": (os.path.relpath(a.regression, VAULT) if a.regression
                       else "_data/phase5b/regression.json"),
        "decision": decision})
    wr(os.path.join(run_dir, "final_decision.json"), {
        "schema_version": "phase5b-final-decision/v1", "run_id": run_id,
        "decision": decision, "items": items, "failed": failed,
        "criteria_pass": sum(1 for i in items if i["status"] == "PASS"),
        "criteria_total": len(items),
        "next_capabilities": {
            "person_case_explorer": "READY" if decision == "PHASE_5B_COMPLETE" else "BLOCKED"},
        "stopped_after_5b": True,
        "finished_at": utcnow()})
    print("decision: %s（failed=%s）" % (decision, failed))
    print("artifacts: %s" % os.path.relpath(run_dir, VAULT))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
