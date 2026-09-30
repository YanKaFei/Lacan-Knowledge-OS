#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase5a_acceptance.py — Phase 5A §51/§52/§53：Hardening Gate v1 的冻结与验收。

    python3 _scripts/_tools/phase5a_acceptance.py --freeze-gate    # 冻结（最终 run 之前）
    python3 _scripts/_tools/phase5a_acceptance.py --run [--regression path]

产出 `_data/phase5a/5a_acceptance_<ts>_<id>/`：manifest / gate_results / browser_qa /
export_qa / obsidian_qa / project_qa / fixtures / final_decision。

纪律：
* Gate **先冻结后验收**；冻结后不得改判据（policy.no_gate_edits_after_freeze）。
* 任一 H 判据 FAIL → `PHASE_5A = BLOCKED`；旧 run 不改写。
* 只用**已封存**的 Phase 4E run 与 RC1.1 工件做 fixture（不重跑 14 题）。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
P5A = os.path.join(VAULT, "_data", "phase5a")
# ── Gate 版本（§21–§24）
#   v1 是**历史且不可变**的：它记录了覆盖缺口，失败结果（11/14）永久保留。
#   v2 是**更严的继任者**：H1–H14 逐字继承（不放松任何阈值），
#      并把四项产品 QA 从「诊断性证据」升为**阻塞判据**（H15–H18）。
GATE_V1 = os.path.join(P5A, "phase5a_hardening_gate_v1.json")
GATE_V2 = os.path.join(P5A, "phase5a_hardening_gate_v2.json")
GATE = os.environ.get("P5A_GATE") or GATE_V2      # 默认使用 v2
FREEZE_DIR = os.path.join(VAULT, "_data", "core_freeze")
LIVE_FREEZE = os.path.join(FREEZE_DIR, "scholarly_core_freeze_v1.json")
PREV_SEGMENT = os.path.join(FREEZE_DIR, "history",
                            "scholarly_core_freeze_v1.4e-ccr0001-remediation.json")
SEALED_RUN = os.path.join(VAULT, "_data", "phase4e",
                          "phase4e_real_llm_20260926T115518Z_1c8e1efc")
PRODUCT_BOUNDARY = ("scholarly_api_core_hash", "scholarly_api_objects_hash",
                    "scholarly_api_policy_hash")
FIXTURE_TASKS = ["rt-B01", "rt-F01", "rt-G01", "rt-G02", "rt-I03"]

# 直接以脚本方式运行时要能 import 产品包（workspace_ui / export_system / ...）：
# 以脚本运行时 Python 只把 _scripts/_tools 放进 sys.path，仓库根**不在**里面。
sys.path.insert(0, VAULT)
sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tests"))
sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tools"))

CRITERIA = [
    ("H1", "internal validator diagnostics in default user view = 0"),
    ("H2", "audit diagnostics preserved = 100%"),
    ("H3", "scholarly claim/citation/answer-state identity violations = 0"),
    ("H4", "source limitation loss = 0"),
    ("H5", "abstention behavior changes = 0"),
    ("H6", "RC1.1 workspace backward compatibility = PASS"),
    ("H7", "accessibility known issues fixed = 3/3"),
    ("H8", "keyboard critical flows = PASS"),
    ("H9", "operational error vs scholarly limitation classification violations = 0"),
    ("H10", "security regressions = 0"),
    ("H11", "full regression failed=[] skipped=[]"),
    ("H12", "core freeze valid"),
    ("H13", "freeze lineage valid"),
    ("H14", "scholarly semantic drift = 0"),
]

# ── Gate v2 新增的四个**阻塞** QA 判据（§22）
#   它们此前只是被记录、被打印，**不进入 decision** —— 那是 Gate v1 的覆盖缺口。
#   提升为阻塞判据 = **加严**，没有任何 v1 判据被放松。
CRITERIA_V2_EXTRA = [
    ("H15", "standard export internal audit diagnostics = 0 "
            "and standard bundle contains no audit/"),
    ("H16", "audit bundle VERIFIED and audit diagnostics preserved = 100%"),
    ("H17", "standard Obsidian research note internal diagnostics = 0 "
            "and audit artifact preserves diagnostics"),
    ("H18", "user-owned content byte-identical after save / sync / project ops"),
]
CRITERIA_V2 = CRITERIA + CRITERIA_V2_EXTRA
GATE_VERSIONS = {
    1: {"file": GATE_V1, "gate_id": "Phase 5A Hardening Gate v1",
        "criteria": CRITERIA, "run_prefix": "5a_acceptance",
        "parent_gate_hash": None},
    2: {"file": GATE_V2, "gate_id": "Phase 5A Hardening Gate v2",
        "criteria": CRITERIA_V2, "run_prefix": "5a_acceptance_v2",
        "parent_gate_hash": None},   # 冻结时填 v1 的 gate_hash
}


def gate_version_of(path):
    for v, spec in GATE_VERSIONS.items():
        if os.path.abspath(spec["file"]) == os.path.abspath(path):
            return v
    return None


def utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha_file(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def jd(p, d=None):
    if not os.path.isfile(p):
        return d if d is not None else {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def wr(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def gate_payload(version=None):
    version = version or 2
    spec = GATE_VERSIONS[version]
    doc = {
        "schema_version": "phase5a-hardening-gate/v%d" % version,
        "gate_id": spec["gate_id"],
        "gate_version": version,
        "phase": "Phase 5A — Scholarly Product Hardening",
        "pdr": "PDR-0001", "ccr": None,
        "frozen": True, "frozen_at": utcnow(), "frozen_before_final_run": True,
        "git_head": subprocess.run(["git", "-C", VAULT, "rev-parse", "HEAD"],
                                   capture_output=True, text=True).stdout.strip(),
        "baseline": {"release_candidate": "RC1.1", "phase4e": "COMPLETE",
                     "ccr_0001": "ACCEPTED_FOR_REMEDIATION",
                     "phase4e_e14": "PENDING"},
        "criteria": [{"id": i, "requirement": r, "blocking": True}
                     for i, r in spec["criteria"]],
        "decision_values": ["PHASE_5A_COMPLETE", "PHASE_5A_BLOCKED"],
        "policy": {
            "any_criterion_fail": "PHASE_5A = BLOCKED",
            "no_gate_edits_after_freeze": True,
            "no_history_rewrite": "失败的 run 保留，修完新开 run",
            "semantic_rule": ("只允许产品边界/呈现层变化；scholarly 语义漂移必须为 0；"
                              "data_version 变化必须被声明且依赖构件状态一致"),
            "no_new_features": True,
        },
    }
    if version == 2:
        v1 = jd(GATE_V1)
        doc["parent_gate"] = {"gate_id": v1.get("gate_id"),
                              "gate_hash": v1.get("gate_hash"),
                              "historical_result": ("PHASE_5A_BLOCKED；"
                                                    "failed=['H2','H8','H11','H12'] → "
                                                    "修正工具后 failed=['H8','H11','H12']"),
                              "immutable": True}
        doc["coverage_upgrade"] = {
            "why_v2": ("Gate v1 的 H1–H14 **不含** browser/export/obsidian/project QA "
                       "作为阻塞判据：它们被记录、被打印，却不进入 decision。"
                       "若将来 QA 失败而 H 判据全过，run 仍会报 PHASE_5A_COMPLETE —— 那是错的。"),
            "what_changed": ("四项产品 QA 从**诊断性证据**升为**阻塞判据** H15–H18。"),
            "not_relaxed": "H1–H14 的 requirement 文本逐字继承自 v1，未降低任何阈值。",
            "stricter_successor": True,
        }
        doc["inherited_criteria_verbatim"] = [
            {"id": i, "requirement": r} for i, r in CRITERIA]
    return doc


def freeze_gate():
    """冻结**当前活动** Gate（默认 v2）。

    §20：Gate v1 **绝不修改**（它记录了覆盖缺口与 11/14 的历史失败）。
    §23：v2 是更严的继任者；H1–H14 逐字继承，新增 H15–H18。
    """
    version = gate_version_of(GATE) or 2
    # ★ 永不触碰 v1：若活动 Gate 被指到 v1 且它已存在，只做完整性校验
    if version == 1:
        # ★ v1 的完整性 = **文件自洽**（记录的 gate_hash == 自身内容哈希）。
        #   不拿"当前生成器"去比对历史：生成器会随阶段演进，历史 gate 不会。
        print("Gate v1 为历史不可变版本：%s（不修改）" % os.path.relpath(GATE_V1, VAULT))
        cur = jd(GATE_V1)
        if not cur:
            print("FAIL 缺 Gate v1：%s" % os.path.relpath(GATE_V1, VAULT))
            return 1
        want = cur.get("gate_hash")
        got = hashlib.sha256(json.dumps(
            {k: v for k, v in cur.items() if k != "gate_hash"},
            ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        if want != got:
            print("FAIL Gate v1 已被事后改动：记录=%s 实际=%s"
                  % (str(want)[:16], got[:16]))
            return 1
        print("Gate v1 完整性 OK（%d 条判据；gate_hash=%s）"
              % (len(cur.get("criteria") or []), str(want)[:16]))
        return 0

    path = GATE_VERSIONS[version]["file"]
    if os.path.isfile(path):
        cur = jd(path)
        body = {k: v for k, v in gate_payload(version).items() if k != "frozen_at"}
        old = {k: v for k, v in cur.items() if k not in ("frozen_at", "gate_hash")}
        if body != old:
            print("FAIL gate 已存在且判据发生变化 —— 冻结后不得修改：%s"
                  % os.path.relpath(path, VAULT))
            return 1
        print("Gate 已冻结且未改动：%s（%d 条判据）"
              % (os.path.relpath(path, VAULT), len(cur.get("criteria") or [])))
        return 0
    doc = gate_payload(version)
    doc["gate_hash"] = hashlib.sha256(json.dumps(
        {k: v for k, v in doc.items() if k != "gate_hash"},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    wr(path, doc)
    print("frozen gate -> %s（%d 条判据；gate_hash=%s；parent(v1)=%s）"
          % (os.path.relpath(path, VAULT), len(doc["criteria"]),
             doc["gate_hash"][:16],
             str((doc.get("parent_gate") or {}).get("gate_hash"))[:16]))
    return 0


def _legacy_coverage(payload):
    """legacy（无结构化 audit）：「原 sections 的每一行」是否都能在
    「用户面 ∪ 审计面」里取回。H2 要求 lines_missing == 0（零丢失）。

    这正是「移走而不是删除」的可验证表述 —— 也是 Gate v1 从未检查过的性质。
    """
    from workspace_ui.server import presentation as PZ
    uf = PZ.user_facing_view(payload)
    av = PZ.audit_view(payload)
    def _lines(v):
        """section 的值可能是 str，也可能是**行的 list**（冻结渲染器两种都用过）。
        必须都按「一行一行」处理 —— 用 str(list) 会把整段压成一行，
        让「行级零丢失」变成一句空话（实测踩过）。"""
        if v is None:
            return []
        if isinstance(v, (list, tuple)):
            out = []
            for x in v:
                out.extend(_lines(x))
            return out
        return str(v).split("\n")

    avail = set()
    for src in ([s.get("text") for s in (uf.get("sections") or [])]
                + [s.get("text") for s in (av.get("legacy_routed_text") or [])]):
        for ln in _lines(src):
            avail.add(ln.strip())
    total, missing = 0, []
    for sid, txt in (payload.get("sections") or {}).items():
        for ln in _lines(txt):
            ln = ln.strip()
            if not ln:
                continue
            total += 1
            if ln not in avail:
                missing.append({"section": sid, "line": ln[:90]})
    return {"lines_total": total, "lines_missing": len(missing),
            "missing_sample": missing[:3]}


# ── fixtures（§33/§34）：用**已封存**的 4E run，不重跑 provider
def build_fixtures(out_dir):
    from workspace_ui.server import presentation as PZ
    rows = {}
    with open(os.path.join(SEALED_RUN, "task_results.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                rows[r["task_id"]] = r
    fixtures = []
    for tid in FIXTURE_TASKS:
        row = rows.get(tid)
        if not row:
            continue
        payload = row.get("final_answer") or {}
        view = {"kind": "answer", "state": payload.get("answer_state"),
                "answer_permission": payload.get("answer_permission"),
                "question": payload.get("question"),
                "sections": [{"id": k, "text": v, "internal": PZ.classify_section(
                    k, v, PZ.has_structured_audit(payload)) == PZ.AUDIT_DIAGNOSTIC}
                    for k, v in (payload.get("sections") or {}).items()],
                "claims": [{"claim_id": c.get("claim_id"),
                            "claim_text": c.get("claim_text"),
                            "claim_type": c.get("claim_type"),
                            "evidence_ids": c.get("evidence_ids")}
                           for c in payload.get("validated_claims") or []],
                "citations": [{"passage_id": c.get("passage_id"),
                               "quoted_span": c.get("quoted_span")}
                              for c in payload.get("citations") or []],
                "limitations": list(payload.get("source_limitations") or []),
                "audit": PZ.audit_view(payload), "raw": {"scholarly_payload": payload}}
        audit = PZ.audit_view(payload)
        # ★ H2 缺陷修复（P5A-ACC-DEFECT-001）：legacy payload 结构上**没有**
        #   `audit_diagnostics`，所以 `len(audit["rejected"])` 恒为 0，与产品是否正确
        #   无关。权威计量是 payload 自带的 `summary.*`（冻结流水线写入），legacy 时
        #   由 audit_view 原样转出。这里把两侧的**事实**都记下来，判据在 H2 里做。
        ent = row.get("entailment") or {}
        fixtures.append({
            "task_id": tid, "source": "phase4e sealed run（未重跑 provider）",
            "before_snapshot": {
                "schema_version": payload.get("schema_version"),
                "raw_sections_has_diagnostics": bool(
                    PZ.LEGACY_ENGINEERING_TEXT.search(
                        json.dumps(payload.get("sections") or {}, ensure_ascii=False))),
                "final_answer": payload,
                "final_answer_hash": row["identities"].get("final_answer_hash"),
            },
            "after_user_view": {"sections": [s for s in view["sections"]
                                            if not s["internal"]],
                                "claims_n": len(view["claims"]),
                                "citations_n": len(view["citations"]),
                                "answer_state": view["state"],
                                "source_limitations_n": len(view["limitations"]),
                                "user_facing_diagnostics":
                                    PZ.scan_user_facing_internal_diagnostics(payload)},
            "after_audit_view": {
                # 结构化数组长度（v1.1 才有内容；legacy 恒 0 —— 仅作记录）
                "rejected_n": len(audit.get("rejected") or []),
                "repaired_n": len(audit.get("repaired") or []),
                # ★ 权威计量：payload 自己记录的计数（两种 schema 都有）
                "rejected_claims_n": audit.get("rejected_claims_n"),
                "repaired_claims_n": audit.get("repaired_claims_n"),
                "generated_claims_n": audit.get("generated_claims_n"),
                "validated_claims_n": audit.get("validated_claims_n"),
                "derived_from_legacy": audit.get("derived_from_legacy"),
                "brief_answer_verbatim": audit.get("brief_answer_verbatim"),
                "routed_sections": audit.get("routed_sections"),
                "legacy_routed_text_n": len(audit.get("legacy_routed_text") or []),
            },
            "sealed_metrics": {
                "generated": row.get("generated_claims"),
                "validated": len(row.get("validated_claims") or []),
                "rejected": len(ent.get("rejected") or []),
                "repaired": len(ent.get("repaired") or []),
                "prevalidation_dropped": len(row.get("prevalidation_dropped") or []),
                "c_stage_dropped": len(row.get("c_dropped") or []),
                "quote_fixes": len(row.get("quote_fixes") or []),
            },
            "sealed_rejected_n": len(ent.get("rejected") or []),
            "legacy_coverage": _legacy_coverage(payload),
            "sealed_state": row.get("answer_state"),
        })
    wr(os.path.join(out_dir, "fixtures.json"),
       {"schema_version": "phase5a-fixtures/v1", "source_run": os.path.relpath(SEALED_RUN, VAULT),
        "tasks": FIXTURE_TASKS, "fixtures": fixtures})
    return fixtures


def evaluate(out_dir, regression_path, fixtures, criteria=None, qa=None):
    from workspace_ui.server import presentation as PZ
    criteria = criteria or CRITERIA
    qa = qa or {}
    items = []

    def add(hid, ok, evidence):
        items.append({"id": hid, "status": "PASS" if ok else "FAIL",
                      "requirement": dict(criteria)[hid], "blocking": True,
                      "evidence": evidence})

    # H1/H2/H3/H4：fixtures 上的呈现不变式
    h1 = [f["task_id"] for f in fixtures if f["after_user_view"]["user_facing_diagnostics"]]
    add("H1", not h1, "user-facing diagnostics=0（fixtures=%d；命中=%s）"
        % (len(fixtures), h1))
    h2_bad, h2_why = [], []
    for f in fixtures:
        av, sm = f["after_audit_view"], f["sealed_metrics"]
        tid = f["task_id"]
        # (a) payload 自带计量必须与封存 run 逐题一致（两种 schema 都适用）
        for key, sealed in (("generated_claims_n", sm["generated"]),
                            ("validated_claims_n", sm["validated"]),
                            ("rejected_claims_n", sm["rejected"]),
                            ("repaired_claims_n", sm["repaired"])):
            if av.get(key) is not None and sealed is not None and av[key] != sealed:
                h2_bad.append(tid)
                h2_why.append("%s:%s %s!=%s" % (tid, key, av[key], sealed))
        if av.get("derived_from_legacy"):
            # (b) legacy：内容必须能在审计面取回，且**行级零丢失**
            if not (av.get("routed_sections") and av.get("legacy_routed_text_n")):
                h2_bad.append(tid)
                h2_why.append("%s:legacy 无 legacy_routed_text" % tid)
            cov = f["legacy_coverage"]
            if cov["lines_missing"]:
                h2_bad.append(tid)
                h2_why.append("%s:行级丢失 %d/%d %s"
                              % (tid, cov["lines_missing"], cov["lines_total"],
                                 cov["missing_sample"]))
        else:
            # (c) 结构化：数组长度必须与权威计量一致
            if av["rejected_n"] != (av.get("rejected_claims_n") or 0):
                h2_bad.append(tid)
                h2_why.append("%s:rejected %s!=%s"
                              % (tid, av["rejected_n"], av.get("rejected_claims_n")))
    h2_bad = sorted(set(h2_bad))
    add("H2", not h2_bad,
        "audit diagnostics 100%% 保留（%d 题；权威计量一致性 + legacy 行级零丢失；"
        "不一致=%s %s）" % (len(fixtures), h2_bad, h2_why[:4]))
    h3_bad = [f["task_id"] for f in fixtures
              if f["after_user_view"]["answer_state"] != f["sealed_state"]]
    add("H3", not h3_bad, "answer_state 身份一致（不一致=%s）" % h3_bad)
    h4_bad = [f["task_id"] for f in fixtures
              if f["after_user_view"]["source_limitations_n"]
              != len(f["before_snapshot"]["final_answer"].get("source_limitations") or [])]
    add("H4", not h4_bad, "source_limitations 条数不变（不一致=%s）" % h4_bad)

    # H5：弃权三题（封存 run）行为不变
    rows = {}
    with open(os.path.join(SEALED_RUN, "task_results.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                rows[r["task_id"]] = r
    jbad = []
    for tid in ("rt-J01", "rt-J02", "rt-J03"):
        r = rows.get(tid) or {}
        fa = r.get("final_answer") or {}
        substantive = [c for c in fa.get("validated_claims") or []
                       if c.get("claim_type") in ("DEFINITION", "DISTINCTION", "RELATION",
                                                  "DIACHRONIC_CHANGE", "SOURCE_INFLUENCE",
                                                  "REINTERPRETATION", "TERMINOLOGY",
                                                  "FORMALISM")]
        if r.get("answer_state") != "ABSTAINED" or not fa.get("abstention") or substantive:
            jbad.append(tid)
    add("H5", not jbad, "J01/J02/J03 仍 ABSTAINED 且无实质补答（异常=%s）" % jbad)

    # H6：RC1.1 向后兼容（真实旧快照：不改字节 + 呈现干净）
    import glob
    legacy, legacy_bad = [], []
    for p in sorted(glob.glob(os.path.join(VAULT, "_workspace", "projects", "*",
                                           "snapshots", "*.json")))[:6]:
        payload = ((jd(p).get("snapshot") or {}).get("raw") or {}).get("scholarly_payload")
        if not payload:
            continue
        before = sha_file(p)
        diag = PZ.scan_user_facing_internal_diagnostics(payload)
        legacy.append({"file": os.path.relpath(p, VAULT), "diagnostics": diag,
                       "unmodified": sha_file(p) == before})
        if diag or sha_file(p) != before:
            legacy_bad.append(os.path.basename(p))
    add("H6", bool(legacy) and not legacy_bad,
        "%d 份 RC1.1 快照渲染干净且逐字节未变（异常=%s）" % (len(legacy), legacy_bad))
    wr(os.path.join(out_dir, "backward_compat.json"),
       {"snapshots_checked": legacy, "bad": legacy_bad})

    # H7 / H8：跑套件（真实渲染 / 真实浏览器）
    def suite(name):
        r = subprocess.run([sys.executable, "-m", "unittest", name],
                           capture_output=True, text=True,
                           cwd=os.path.join(VAULT, "_scripts", "_tests"))
        return r.returncode, " ".join((r.stdout + r.stderr).split())[-260:]

    rc7, msg7 = suite("test_phase5a_accessibility")
    add("H7", rc7 == 0, "test_phase5a_accessibility exit=%s %s" % (rc7, msg7[-120:]))
    rc8, msg8 = suite("test_phase5a_keyboard_flows")
    add("H8", rc8 == 0, "test_phase5a_keyboard_flows exit=%s %s" % (rc8, msg8[-120:]))

    # H9：错误 vs 学术限制 的分类
    from workspace_ui.server import viewmodel as VM
    cls_err = PZ.classify_error({"code": "PROVIDER_UNAVAILABLE"})
    cls_trace = PZ.classify_section("limitations", "SOURCE_TRACE_INCOMPLETE 来源链不完整", True)
    cls_audit = PZ.classify_section("brief_answer", "本回答由 3 条…", True)
    ok9 = (cls_err == PZ.OPERATIONAL_ERROR and cls_trace == PZ.SCHOLARLY_LIMITATION
           and cls_audit == PZ.AUDIT_DIAGNOSTIC)
    add("H9", ok9, "error=%s / trace=%s / audit=%s" % (cls_err, cls_trace, cls_audit))

    # H10：安全（密钥审计 + 策略探针）
    r = subprocess.run([sys.executable, os.path.join(HERE, "phase4e_secret_audit.py"),
                        "--json", os.path.join(P1 := P5A, "secret_audit_5a.json")],
                       capture_output=True, text=True, cwd=VAULT)
    sec = jd(os.path.join(P5A, "secret_audit_5a.json"))
    probes = []
    import export_system as EX
    from scholarly_api import policy as POL
    for fn, args in ((EX.policy.resolve_export_path, ("../../etc/passwd",)),
                     (EX.policy.export_root, ("/tmp/evil",)),
                     (POL.write_text, ("_data/ontology/v4a1/entities.jsonl", "x"))):
        try:
            fn(*args)
            probes.append(args[0])
        except Exception:                                                 # noqa: BLE001
            pass
    add("H10", sec.get("verdict") == "PASS" and not probes,
        "secret_audit=%s（real findings=%d）；policy probes refused=%s"
        % (sec.get("verdict"), len(sec.get("real_credential_findings") or []),
           not probes))

    # H11：全量回归
    reg = jd(regression_path or os.path.join(P5A, "regression.json"))
    add("H11", reg.get("exit_code") == 0 and not reg.get("failed") and not reg.get("skipped"),
        "regression exit=%s suites=%s checks=%s failed=%s skipped=%s"
        % (reg.get("exit_code"), reg.get("suites"), reg.get("checks"),
           reg.get("failed"), reg.get("skipped")))

    # H12/H13：冻结与谱系
    def tool(name, *args):
        r = subprocess.run([sys.executable, os.path.join(HERE, name), *args],
                           capture_output=True, text=True, cwd=VAULT)
        return r.returncode, " ".join((r.stdout + r.stderr).split())[-200:]
    rc12, m12 = tool("core_freeze.py", "--verify", "--quiet")
    add("H12", rc12 == 0, "core_freeze --verify exit=%s" % rc12)
    rc13, m13 = tool("freeze_lineage.py", "--verify")
    lin = jd(os.path.join(FREEZE_DIR, "freeze_lineage.json"))
    n_seg = len(lin.get("segments") or [])
    # 判据文本是 "freeze lineage valid" —— 实现只断言**结构性有效**，
    # 不硬编码段数（阶段会继续追加段，段数不是判据）。
    h13_ok = (rc13 == 0 and n_seg >= 6
              and lin.get("all_segments_status_pass")
              and lin.get("all_segments_semantic_changes_zero")
              and lin.get("live_matches_last_segment"))
    add("H13", h13_ok,
        "freeze_lineage exit=%s 段数=%s 全段 PASS=%s 语义变化全 0=%s live=末段=%s "
        "(semantic=%s / data_version=%s / product_runtime=%s)"
        % (rc13, n_seg, lin.get("all_segments_status_pass"),
           lin.get("all_segments_semantic_changes_zero"),
           lin.get("live_matches_last_segment"), lin.get("semantic_changes_total"),
           lin.get("data_version_changes_total"),
           lin.get("product_runtime_changes_total")))

    # H14：scholarly 语义漂移 = 0（与 4E 段比较：只允许产品边界组件变）
    # H14 判据文本："scholarly semantic drift = 0"。
    #   ★ P5A-006：按 core_freeze.component_class 的**三类**判定，
    #     不再用「非产品边界即语义」的旧二分（那会把语料版本变化误判成语义漂移）。
    #   被测对象 = live manifest 与谱系中**它的上一段**之间的组件差异。
    import core_freeze as _CF
    lin14 = jd(os.path.join(FREEZE_DIR, "freeze_lineage.json"))
    live = jd(LIVE_FREEZE)
    segs = [e for e in (lin14.get("segments") or [])
            if e.get("historical_artifact") == "present"]
    parent_rel = segs[-1].get("parent_manifest") if segs else None
    prev = jd(os.path.join(FREEZE_DIR, parent_rel)) if parent_rel else {}
    lc, pc = live.get("components") or {}, prev.get("components") or {}
    changed = sorted(k for k in set(lc) | set(pc) if lc.get(k) != pc.get(k))
    classes = live.get("component_classes") or _CF.component_classes()
    semantic = [k for k in changed
                if classes.get(k, _CF.component_class(k)) == _CF.CLASS_SCHOLARLY]
    data_keys = [k for k in changed
                 if classes.get(k, _CF.component_class(k)) == _CF.CLASS_DATA]
    runtime = [k for k in changed
               if classes.get(k, _CF.component_class(k)) == _CF.CLASS_PRODUCT]
    last = segs[-1] if segs else {}
    dv_ok = (last.get("all_data_version_changes_declared_and_consistent") is not False
             and not (last.get("failure_codes") or []))
    add("H14", semantic == [] and dv_ok,
        "changed=%s semantic=%s data_version=%s product_runtime=%s "
        "declared&consistent=%s unchanged=%d/%d"
        % (changed, semantic, data_keys, runtime, dv_ok,
           len([k for k in pc if pc.get(k) == lc.get(k)]), len(pc)))

    # ── Gate v2：H15–H18（四项产品 QA 升为**阻塞**判据，§22）
    eqa_, oqa_, pqa_ = qa.get("export") or {}, qa.get("obsidian") or {}, \
        qa.get("project") or {}
    if any(i["id"] in ("H15", "H16", "H17", "H18") for i in
           [{"id": i} for i, _ in criteria]):

        std = eqa_.get("standard") or {}
        leaks = {fmt: (std.get(fmt) or {}).get("diagnostics") or []
                 for fmt in ("markdown", "json", "html")}
        bundle_audit = ((std.get("bundle") or {}).get("audit_files_leaked") or [])
        add("H15", (eqa_.get("status") == "OK"
                    and all(not v for v in leaks.values())
                    and not bundle_audit
                    and (std.get("bundle") or {}).get("has_audit_dir") is False),
            "standard export diagnostics=%s；standard bundle audit/%s=%s"
            % ({k: v for k, v in leaks.items()}, "leaked", bundle_audit))

        aud = eqa_.get("audit") or {}
        b = aud.get("bundle") or {}
        files = b.get("files") or []
        add("H16", (b.get("verify") == "VERIFIED"
                    and aud.get("preservation") == "PASS"
                    and aud.get("carries_not_entailed") is True
                    and aud.get("validation_trace_present") is True
                    and aud.get("audit_diagnostics_present") is True),
            "audit bundle verify=%s；preservation=%s %s；carries_not_entailed=%s；"
            "validation_trace=%s；audit_diagnostics=%s；files=%s"
            % (b.get("verify"), aud.get("preservation"),
               aud.get("preservation_detail"), aud.get("carries_not_entailed"),
               aud.get("validation_trace_present"),
               aud.get("audit_diagnostics_present"), files))

        add("H17", (oqa_.get("status") == "OK"
                    and not (oqa_.get("note_diagnostics") or [])
                    and oqa_.get("audit_artifact_exists") is True
                    and oqa_.get("audit_artifact_has_content") is True),
            "standard note diagnostics=%s；audit artifact exists=%s content=%s；"
            "audit artifact diagnostics=%s"
            % (oqa_.get("note_diagnostics"), oqa_.get("audit_artifact_exists"),
               oqa_.get("audit_artifact_has_content"),
               oqa_.get("audit_artifact_diagnostics")))

        add("H18", (oqa_.get("user_zone_preserved") is True
                    and oqa_.get("unmanaged_note_preserved") is True
                    and pqa_.get("user_content_preserved") is True),
            "My Notes 逐字节保留=%s；非受管笔记保留=%s；用户工作区内容保留=%s"
            % (oqa_.get("user_zone_preserved"),
               oqa_.get("unmanaged_note_preserved"),
               pqa_.get("user_content_preserved")))

    failed = [i["id"] for i in items if i["status"] != "PASS"]
    return items, ("PHASE_5A_COMPLETE" if not failed else "PHASE_5A_BLOCKED"), failed


# ── 浏览器 QA（§54 A–G）
def browser_qa(out_dir):
    from _cdp_testlib import CDP, chrome_available
    from workspace_ui.server import api as A
    from workspace_ui.server import httpserver as H
    if not chrome_available():
        return {"status": "UNAVAILABLE", "reason": "no Chrome"}
    srv = H.make_server("127.0.0.1", 0)
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    shots = os.path.join(out_dir, "screenshots")
    os.makedirs(shots, exist_ok=True)
    cases = [
        ("A_validated_qualified", "?q=%s&mode=scholarly&provider=mock&autorun=1"
         % __import__("urllib.parse", fromlist=["quote"]).quote(
             "Seminar XI 中 gaze 与 objet a 是什么关系？")),
        ("C_abstention", "?q=%s&provider=mock&autorun=1"
         % __import__("urllib.parse", fromlist=["quote"]).quote(
             "拉康如何看待 fMRI 等当代神经科学影像研究？")),
        ("D_reject_diagnostics", "?q=%s&mode=philosophy_to_lacan&provider=mock&autorun=1"
         % __import__("urllib.parse", fromlist=["quote"]).quote(
             "黑格尔的主人—奴隶辩证法如何进入拉康的理论？")),
        ("F_trace_incomplete", "?view=passage&id=passage.S05.unknown.L05.P0056"),
    ]
    out = {"status": "OK", "cases": [], "taxonomy_version": "presentation-taxonomy/v1"}
    try:
        cdp = CDP(window="1400,1000")
        for name, qs in cases:
            cdp.navigate(base + "/" + qs)
            cdp.wait_js("document.body && document.body.dataset.ready === '1'", 40)
            if name.startswith(("A", "C", "D")):
                cdp.wait_js("(() => { const r = document.getElementById('result');"
                            " return r && !r.hidden; })()", 60)
            user_text = cdp.js("document.getElementById('main').innerText")
            # 默认视图不得出现内部诊断
            leaked = [m for m in ("NOT_ENTAILED", "已剔除", "因未通过验证被剔除",
                                  "通过蕴含验证的断言构成")
                      if m and m in (user_text or "")]
            png = cdp.call("Page.captureScreenshot", {"format": "png"}).get("data")
            if png:
                with open(os.path.join(shots, "%s_default.png" % name), "wb") as f:
                    f.write(base64.b64decode(png))
            rec = {"case": name, "default_view_leaks": leaked,
                   "screenshot": "%s_default.png" % name}
            if name.startswith("D"):
                # 打开 Advanced/Audit 后必须能看到 rejection trace
                cdp.js("(() => { const d = document.querySelector('#advanced-panel details');"
                       " if (d) d.open = true; return !!d; })()")
                cdp.js("(() => { const d = document.querySelectorAll('#advanced-panel details');"
                       " d.forEach(x => x.open = true); return d.length; })()")
                audit_text = cdp.js("document.getElementById('advanced-panel').innerText")
                rec["audit_visible"] = bool(
                    audit_text and ("Rejected claims" in audit_text
                                    or "Validator record" in audit_text))
                rec["audit_mentions_not_entailed"] = bool(
                    audit_text and "NOT_ENTAILED" in audit_text)
                # ★ 精确判定：Audit 区块**不得**被呈现成错误。
                #   旧实现是 `"ERROR" in text.upper()` —— 太粗：Advanced 面板里
                #   合法地会出现 INTERNAL_ERROR / PROVIDER_UNAVAILABLE 等错误码，
                #   于是必然假红。改为：① 必须有中性措辞「not an error」；
                #   ② Audit 区块内不得出现错误样式元素（is-err / is-failed / .error）。
                styled = cdp.js("""(() => {
                  const panel = document.getElementById('advanced-panel');
                  const boxes = panel ? panel.querySelectorAll('details') : [];
                  let audit = null;
                  boxes.forEach((d) => { const s = d.querySelector('summary');
                    if (s && /Audit — validator diagnostics/.test(s.textContent)) audit = d; });
                  if (!audit) return JSON.stringify({found: false});
                  const errEls = audit.querySelectorAll('.is-err, .is-failed, .error').length;
                  const txt = audit.innerText || '';
                  return JSON.stringify({found: true, err_els: errEls,
                    neutral: /not an error/i.test(txt)});
                })()""")
                try:
                    info = json.loads(styled) if isinstance(styled, str) else (styled or {})
                except Exception:                                         # noqa: BLE001
                    info = {}
                rec["audit_block_found"] = bool(info.get("found"))
                rec["audit_neutral_wording"] = bool(info.get("neutral"))
                rec["audit_error_styled_elements"] = int(info.get("err_els") or 0)
                rec["audit_styled_as_error"] = bool(info.get("found")
                                                    and (not info.get("neutral")
                                                         or int(info.get("err_els") or 0)))
                png2 = cdp.call("Page.captureScreenshot", {"format": "png"}).get("data")
                if png2:
                    with open(os.path.join(shots, "%s_audit_open.png" % name), "wb") as f:
                        f.write(base64.b64decode(png2))
                rec["audit_screenshot"] = "%s_audit_open.png" % name
            out["cases"].append(rec)
        cdp.close()
    except Exception as exc:                                              # noqa: BLE001
        out["status"] = "FAILED"
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    finally:
        srv.shutdown()
    # E：provider unavailable（不依赖浏览器）
    try:
        prev_home = os.environ.get("HOME")
        prev_key = os.environ.pop("DSH_SYNTHESIS_API_KEY", None)
        os.environ["HOME"] = os.path.join(out_dir, "logs", "empty_home")
        os.makedirs(os.environ["HOME"], exist_ok=True)
        try:
            v = A.research("Seminar XI 中 gaze 与 objet a 是什么关系？", provider="llm",
                           save_history=False).get("view") or {}
            out["case_E_provider_unavailable"] = {"code": v.get("code"),
                                                 "kind": v.get("kind")}
        finally:
            if prev_home is not None:
                os.environ["HOME"] = prev_home
            if prev_key is not None:
                os.environ["DSH_SYNTHESIS_API_KEY"] = prev_key
    except Exception as exc:                                              # noqa: BLE001
        out["case_E_provider_unavailable"] = {"error": str(exc)[:120]}
    # G：键盘（真实浏览器里的按键契约）由 test_phase5a_keyboard_flows 覆盖（H8）
    out["case_G_keyboard"] = "covered by test_phase5a_keyboard_flows (H8)"
    return out


def export_qa(out_dir):
    import export_system as EX
    from scholarly_api import core
    from workspace_ui.server import viewmodel as VM, export_view as EV
    prev = EX.policy.EXPORT_ROOTS["default"]
    # ★ 隔离根必须在 _workspace/** 下（策略登记为 USER_WORKSPACE）。
    #   放在 _data/** 会被写闸门正确拒绝 —— 那是产品**做对了**，是验收脚本放错了地方。
    iso = os.path.join("_workspace", "acceptance", os.path.basename(out_dir), "exports")
    shutil.rmtree(os.path.join(VAULT, iso), ignore_errors=True)
    EX.policy.EXPORT_ROOTS["default"] = iso
    marker = ("NOT_ENTAILED", "已剔除", "因未通过验证被剔除")
    out = {"status": "OK", "standard": {}, "audit": {}}
    try:
        r = core.research("黑格尔的主人—奴隶辩证法如何进入拉康的欲望理论？",
                          {"provider": "mock", "mode": "philosophy_to_lacan",
                           "task_id": "p5a-acc-export", "language": "any"})
        view = VM.answer_view({"ok": True, "result": r,
                               "meta": {"provider": "mock", "request_id": "p5a-acc-export"}})
        doc = EV.build("research_run", view=view, source_id="p5a-acc-export")
        for fmt in ("markdown", "json", "html"):
            text = {"markdown": EX.markdown.render, "json": EX.json_export.render,
                    "html": EX.html_export.render}[fmt](doc)
            out["standard"][fmt] = {"length": len(text),
                                    "diagnostics": [m for m in marker if m in text]}
        b1 = EV.run(doc, "bundle")
        out["standard"]["bundle"] = {"verify": b1["verify"]["status"],
                                     "has_audit_dir": os.path.isdir(
                                         os.path.join(VAULT, b1["rel_dir"], "audit"))}
        # 权威计量（H16 的「100% 保留」要对着它比，而不是对着 0 比）
        exp_rej = ((view.get("audit") or {}).get("rejected_claims_n")
                   if isinstance(view.get("audit"), dict) else None)
        out["audit"]["expected_rejected_n"] = exp_rej
        doc_a = EV.build("research_run", view=view, source_id="p5a-acc-export",
                         include_audit=True)
        b2 = EV.run(doc_a, "bundle")
        root = os.path.join(VAULT, b2["rel_dir"])
        out["audit"]["bundle"] = {
            "verify": b2["verify"]["status"],
            "files": sorted(f for f in os.listdir(os.path.join(root, "audit"))
                            if f.endswith(".json"))
            if os.path.isdir(os.path.join(root, "audit")) else [],
        }
        rej = jd(os.path.join(root, "audit", "rejected_claims.json"), [])
        out["audit"]["rejected_n"] = len(rej)
        out["audit"]["carries_not_entailed"] = any(
            "NOT_ENTAILED" in json.dumps(x, ensure_ascii=False) for x in rej)
        vt = jd(os.path.join(root, "audit", "validation_trace.json"), {})
        out["audit"]["validation_trace_present"] = bool(vt)
        ad = jd(os.path.join(root, "audit", "answer_audit_diagnostics.json"), {})
        out["audit"]["audit_diagnostics_present"] = bool(ad)
        if exp_rej is None:
            out["audit"]["preservation"] = "UNKNOWN"
        elif exp_rej == 0:
            out["audit"]["preservation"] = "PASS" if len(rej) == 0 else "FAIL"
        else:
            out["audit"]["preservation"] = ("PASS" if len(rej) >= exp_rej else "FAIL")
        out["audit"]["preservation_detail"] = {
            "expected_rejected_n": exp_rej, "bundle_rejected_n": len(rej)}
        # 标准 bundle 里**不允许**出现 audit 目录（H15）
        rel = b1.get("rel_dir") or ""
        std_root = os.path.join(VAULT, rel)
        leaked = []
        for dirpath, _dirnames, filenames in os.walk(std_root):
            for fn in filenames:
                p_ = os.path.relpath(os.path.join(dirpath, fn), std_root)
                if p_.split(os.sep)[0] == "audit":
                    leaked.append(p_)
        out["standard"]["bundle"]["audit_files_leaked"] = sorted(leaked)
    except Exception as exc:                                              # noqa: BLE001
        out["status"] = "FAILED"
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        out["traceback"] = traceback.format_exc()[-1200:]
    finally:
        EX.policy.EXPORT_ROOTS["default"] = prev
    return out


def obsidian_qa(out_dir):
    from scholarly_api import core
    from workspace_ui.server import viewmodel as VM
    from obsidian_adapter import adapter as OA
    from obsidian_adapter import vault as OV
    prev_env = os.environ.get("OBSIDIAN_VAULT_PATH")
    # ★ 同理：受管 vault 必须是 _workspace/** 下的相对路径（策略登记为 USER_WORKSPACE）；
    #   绝对路径也不能指向未分类的 _data/**（实测踩过：VaultError: empty path segment
    #   与写闸门拒绝）。
    iso = os.path.join("_workspace", "acceptance", os.path.basename(out_dir), "vault")
    shutil.rmtree(os.path.join(VAULT, iso), ignore_errors=True)
    os.environ["OBSIDIAN_VAULT_PATH"] = iso
    out = {"status": "OK"}
    try:
        r = core.research("黑格尔的主人—奴隶辩证法如何进入拉康的欲望理论？",
                          {"provider": "mock", "mode": "philosophy_to_lacan",
                           "task_id": "p5a-acc-obsidian", "language": "any"})
        view = VM.answer_view({"ok": True, "result": r,
                               "meta": {"provider": "mock",
                                        "request_id": "p5a-acc-obsidian"}})
        v = OV.Vault()
        # H18：先放一份**非受管**的用户笔记（不是本系统生成的），同步后必须逐字节不变
        unmanaged_rel = "13_Reading_Notes/my-own-note.md"
        unmanaged_body = ("---\ntitle: 我自己的笔记\n---\n\n"
                          "## 我的阅读记录\n\n"
                          "这段文字是用户自己写的，任何同步都不得覆盖。\n")
        v.write(unmanaged_rel, unmanaged_body)
        unmanaged_before = v.read(unmanaged_rel)
        res = OA.save_research(view, vault=v, include_audit=True)
        note = v.read(res.get("research_note")) or ""
        marker = ("NOT_ENTAILED", "已剔除", "因未通过验证被剔除")
        # 用户区逐字节保留：写一行再同步一次
        marker_text = "\n\n## My Notes\n\n用户自己的文字。\n"
        v.write(res["research_note"], note.rstrip("\n") + marker_text)
        before = v.read(res["research_note"])
        OA.save_research(view, vault=v, include_audit=True)
        after = v.read(res["research_note"])
        # H17：审计工件里必须**保留**诊断（用户面为 0 不等于审计面为空）
        audit_text = ""
        if res.get("audit_artifact") and v.exists(res["audit_artifact"]):
            audit_text = v.read(res["audit_artifact"]) or ""
        out.update({
            "audit_artifact_diagnostics": [m for m in marker if m in audit_text],
            "audit_artifact_has_content": bool(audit_text),
            "unmanaged_note": unmanaged_rel,
            "unmanaged_note_preserved": unmanaged_before == v.read(unmanaged_rel),
            "note": res.get("research_note"),
            "note_diagnostics": [m for m in marker if m in note],
            "audit_artifact": res.get("audit_artifact"),
            "audit_artifact_exists": bool(res.get("audit_artifact")
                                          and v.exists(res["audit_artifact"])),
            "user_zone_preserved": before == after,
        })
    except Exception as exc:                                              # noqa: BLE001
        out["status"] = "FAILED"
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        out["traceback"] = traceback.format_exc()[-1200:]
    finally:
        if prev_env is None:
            os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        else:
            os.environ["OBSIDIAN_VAULT_PATH"] = prev_env
    return out


def project_qa(out_dir):
    """§57/§39：RC1.1 项目可打开、旧 run 不 mutation。"""
    import glob
    import project_api as PA
    out = {"status": "OK", "projects": []}
    try:
        lst = PA.list_projects()
        for item in (lst.get("items") or [])[:5]:
            pid = item.get("project_id")
            proj = PA.get_project(pid)
            runs = proj.get("research_runs") or []
            snaps = []
            for run in runs[:3]:
                p = os.path.join(PA.store.PROJECTS_DIR, pid, "snapshots",
                                 "%s.json" % run.get("run_id"))
                if os.path.isfile(p):
                    snaps.append({"run_id": run.get("run_id"), "sha256": sha_file(p),
                                  "state": run.get("answer_state")})
            out["projects"].append({"project_id": pid,
                                    "status": proj.get("status"),
                                    "runs_n": len(runs), "snapshots": snaps})
        # ── H18：用户工作区内容在项目操作后必须**逐字节不变**
        import hashlib as _h
        probe = os.path.join(PA.store.PROJECTS_DIR, "_user_content_probe.txt")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("用户自己的工作区内容\n第二行\n")
        before_hash = _h.sha256(open(probe, "rb").read()).hexdigest()
        for item in (lst.get("items") or [])[:3]:
            try:
                PA.get_project(item.get("project_id"))     # 项目操作
            except Exception:                                             # noqa: BLE001
                pass
        after_hash = _h.sha256(open(probe, "rb").read()).hexdigest()
        out["user_content_probe"] = os.path.relpath(probe, VAULT)
        out["user_content_preserved"] = before_hash == after_hash
        os.remove(probe)
    except Exception as exc:                                              # noqa: BLE001
        out["status"] = "FAILED"
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 5A acceptance / gate")
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
    gver = gate.get("gate_version") or 0
    gcrit = [(c["id"], c["requirement"]) for c in (gate.get("criteria") or [])]
    if not gate:
        print("FAIL 缺冻结 Gate（先 --freeze-gate）")
        return 2
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    prefix = GATE_VERSIONS.get(gver, {}).get("run_prefix", "5a_acceptance")
    run_id = a.run_id or "%s_%s_%s" % (
        prefix, stamp, hashlib.sha256(stamp.encode()).hexdigest()[:8])
    out_dir = os.path.join(P5A, run_id)
    os.makedirs(os.path.join(out_dir, "logs"), exist_ok=True)

    print("== Phase 5A acceptance ==")
    fixtures = build_fixtures(out_dir)
    print("  fixtures: %d 题（来自封存 4E run）" % len(fixtures))
    bqa = browser_qa(out_dir)
    print("  browser QA: %s" % bqa.get("status"))
    eqa = export_qa(out_dir)
    print("  export QA: %s" % eqa.get("status"))
    oqa = obsidian_qa(out_dir)
    print("  obsidian QA: %s" % oqa.get("status"))
    pqa = project_qa(out_dir)
    print("  project QA: %s" % pqa.get("status"))
    items, decision, failed = evaluate(
        out_dir, a.regression, fixtures, criteria=gcrit,
        qa={"export": eqa, "obsidian": oqa, "project": pqa, "browser": bqa})
    for i in items:
        print("  %-4s %-5s %s" % (i["id"], i["status"], str(i["evidence"])[:110]))
    print("decision: %s（failed=%s）" % (decision, failed))

    wr(os.path.join(out_dir, "browser_qa.json"), bqa)
    wr(os.path.join(out_dir, "export_qa.json"), eqa)
    wr(os.path.join(out_dir, "obsidian_qa.json"), oqa)
    wr(os.path.join(out_dir, "project_qa.json"), pqa)
    # §32/§43：E14 与 release promotion **独立**。Phase 5A 的技术验收不改变
    # Phase 4E 的人工复核义务 —— 不得假定它已完成，也不得替它下结论。
    e14_pending = not os.path.isfile(os.path.join(VAULT, "_data", "phase4e",
                                                  "human_spot_review_v2.jsonl"))
    complete = decision == "PHASE_5A_COMPLETE"
    rc = "RC1.2" if complete else "RC1.1"
    rc_status = ("PENDING_PHASE4E_HUMAN_CLOSURE"
                 if (complete and e14_pending) else
                 ("SIGNED" if complete else "NOT_CREATED"))
    wr(os.path.join(out_dir, "gate_results.json"),
       {"gate_id": gate["gate_id"], "gate_version": gver,
        "gate_hash": gate["gate_hash"],
        "items": items, "failed": failed, "decision": decision,
        "release_candidate": rc, "release_candidate_status": rc_status,
        "phase4e_e14": "PENDING" if e14_pending else "PRESENT_UNVERIFIED_BY_THIS_TOOL"})
    wr(os.path.join(out_dir, "manifest.json"), {
        "schema_version": "phase5a-acceptance-manifest/v1", "run_id": run_id,
        "created_at": utcnow(),
        "head": subprocess.run(["git", "-C", VAULT, "rev-parse", "HEAD"],
                               capture_output=True, text=True).stdout.strip(),
        "gate_id": gate["gate_id"], "gate_version": gver,
        "gate_hash": gate["gate_hash"],
        "parent_gate_hash": (gate.get("parent_gate") or {}).get("gate_hash"),
        "gate_file_sha256": sha_file(GATE),
        "baseline": gate["baseline"], "pdr": gate["pdr"],
        "fixture_source_run": os.path.relpath(SEALED_RUN, VAULT),
        "regression": os.path.relpath(a.regression, VAULT) if a.regression else
                      "_data/phase5a/regression.json",
        "decision": decision,
        "screenshots": sorted(os.listdir(os.path.join(out_dir, "screenshots")))
        if os.path.isdir(os.path.join(out_dir, "screenshots")) else []})
    wr(os.path.join(out_dir, "final_decision.json"), {
        "schema_version": "phase5a-final-decision/v1", "run_id": run_id,
        "gate_id": gate["gate_id"], "gate_version": gver,
        "gate_hash": gate["gate_hash"],
        "decision": decision, "items": items, "failed": failed,
        "criteria_total": len(items),
        "criteria_pass": sum(1 for i in items if i["status"] == "PASS"),
        "next_capabilities": {
            "presentation_hardening": "READY" if complete else "BLOCKED",
            "accessibility_baseline": "READY" if complete else "BLOCKED",
            "qa_gating": "ENFORCED" if gver >= 2 else "DIAGNOSTIC_ONLY"},
        "release_candidate": rc,
        "release_candidate_status": rc_status,
        "phase4e_e14": ("PENDING" if e14_pending
                        else "human_spot_review_v2.jsonl present（本工具不验证其结论）"),
        "scholarly_product_hardened": bool(complete),
        "finished_at": utcnow()})
    print("artifacts: %s" % os.path.relpath(out_dir, VAULT))
    return 0 if decision == "PHASE_5A_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
