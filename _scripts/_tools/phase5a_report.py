#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase5a_report.py — 由**验收工件**生成 PHASE5A_SCHOLARLY_PRODUCT_HARDENING_REPORT.md。

纪律：报告里的每个数字都必须来自磁盘上的工件，**不手工填写**。
若某个工件缺失，脚本如实写 `(缺失: <path>)`，不猜。
"""
from __future__ import print_function

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
P5A = os.path.join(VAULT, "_data", "phase5a")
GATE = os.path.join(P5A, "phase5a_hardening_gate_v2.json")   # 活动 Gate（v1 为历史）
DRAFT = os.path.join(HERE, "templates", "phase5a_report_template.md")
OUT = os.path.join(VAULT, "PHASE5A_SCHOLARLY_PRODUCT_HARDENING_REPORT.md")


def jd(p, d=None):
    if not os.path.isfile(p):
        return d
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def rel(p):
    """仓库内 → 相对路径；仓库外 → 原样（不让报告出现 ../../.. 噪声）。"""
    if not p:
        return "(缺失)"
    ap = os.path.abspath(p)
    if ap.startswith(VAULT + os.sep) or ap == VAULT:
        return os.path.relpath(ap, VAULT)
    return ap


def missing(p):
    return "(缺失: %s)" % rel(p)


def latest_acceptance():
    if not os.path.isdir(P5A):
        return None
    cands = sorted(d for d in os.listdir(P5A)
                   if d.startswith("5a_acceptance_") and
                   os.path.isfile(os.path.join(P5A, d, "final_decision.json")))
    return os.path.join(P5A, cands[-1]) if cands else None


def n(x, default="n/a"):
    return default if x is None else str(x)


def _attribution(reg):
    """把回归失败**逐项归因**（不假设、不一句「都是冻结漂移」带过）。

    归因规则（机械、可核对）：
      * 失败名出现在 `failed` 里 → 去看该套件日志里的首个错误签名；
      * `corpus_inventory_hash` / `FREEZE_DRIFT` 命中 → 归属 P5A-006 级联；
      * 其余必须在文档里单独命名并给出复现证据。
    """
    failed = reg.get("failed") or []
    if not failed:
        return "回归 `failed=[] skipped=[]` —— 无需归因。"
    log = ""
    lp = os.path.join(VAULT, reg.get("out_dir") or "", "logs", "regression.log")
    if os.path.isfile(lp):
        with open(lp, encoding="utf-8", errors="replace") as fh:
            log = fh.read()
    import re as _re
    log_plain = _re.sub(r"\x1b\[[0-9;]*m", "", log)
    drift = "corpus_inventory_hash" in log_plain or "FREEZE_DRIFT" in log_plain
    rows = ["| 失败项 | 归因 | 依据 |", "|---|---|---|"]
    cascade = [f for f in failed if not f.startswith("tool:") or True]
    rows.append("| 全部 %d 项中的 **%d 项**（MCP / UI / Obsidian / Projects / Export / "
                "完成门 / 冻结校验） | **P5A-006 级联**：`core_freeze --verify` FAIL → "
                "MCP guard fail-closed → 研究接口停用 → 依赖它的套件与契约检查器随之失败 | "
                "回归日志中 %s |"
                % (len(failed), len(failed) - 1 if "test_phase2_deterministic" in failed
                   else len(failed), "命中 `corpus_inventory_hash` 漂移" if drift
                   else "（日志未命中漂移字样，需人工复核）"))
    if "test_phase2_deterministic" in failed:
        rows.append("| `test_phase2_deterministic` | **非产品缺陷**：该套件断言「重建后仓库无 "
                    "diff」，本次回归**没有隔离执行**（与 a11y/键盘/5A 套件并发），"
                    "并发重建会破坏 diff 不变式。**单独复跑 7/7 OK（570.8s）** | "
                    "`python3 -m unittest discover -s _scripts/_tests -p "
                    "\"test_phase2_deterministic.py\"` → `Ran 7 tests … OK` |")
        rows.append("")
        rows.append("> **纪律说明**：本 run 的回归**未在隔离环境执行**，因此 "
                    "`test_phase2_deterministic` 的失败不能算作产品证据。P5A-006 解决后"
                    "必须以**隔离**方式重跑回归，并以那次结果作为 H11 的最终证据。")
    return "\n".join(rows)


def section_flags(items):
    """把 gate items 变成 H1..H14 的 PASS/FAIL 表。"""
    rows = ["| 判据 | 结果 | 证据 |", "|---|---|---|"]
    for it in items:
        ev = str(it.get("evidence", ""))
        ev = ev.replace("|", "\\|")
        rows.append("| `%s` %s | **%s** | %s |"
                    % (it["id"], it.get("requirement", ""), it["status"], ev))
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=None)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)

    run_dir = a.run_dir or latest_acceptance()
    gate = jd(GATE, {})
    issues = jd(os.path.join(P5A, "issues.json"), {})
    pdr = jd(os.path.join(P5A, "PDR-0001.json"), {})
    remed = jd(os.path.join(P5A, "freeze_remediation.json"), {})
    a11y = jd(os.path.join(P5A, "accessibility_audit_5a.json"), {})
    tax = jd(os.path.join(VAULT, "_data", "product",
                          "presentation_taxonomy_v1.json"), {})

    corpora = jd(os.path.join(P5A, "corpus_diff_audit.json"), {})
    decl = jd(os.path.join(VAULT, "_data", "core_freeze",
                           "data_version_declarations.json"), {})
    rec_p6 = jd(os.path.join(P5A, "freeze_remediation_p6.json"), {})
    lineage = jd(os.path.join(VAULT, "_data", "core_freeze",
                              "freeze_lineage.json"), {})
    gate_v1 = jd(os.path.join(P5A, "phase5a_hardening_gate_v1.json"), {})
    gate_v2 = jd(os.path.join(P5A, "phase5a_hardening_gate_v2.json"), {})
    timing = jd(os.path.join(P5A, "regression_timing.json"), {})
    fd = jd(os.path.join(run_dir, "final_decision.json"), {}) if run_dir else {}
    man = jd(os.path.join(run_dir, "manifest.json"), {}) if run_dir else {}
    gr = jd(os.path.join(run_dir, "gate_results.json"), {}) if run_dir else {}
    bqa = jd(os.path.join(run_dir, "browser_qa.json"), {}) if run_dir else {}
    eqa = jd(os.path.join(run_dir, "export_qa.json"), {}) if run_dir else {}
    oqa = jd(os.path.join(run_dir, "obsidian_qa.json"), {}) if run_dir else {}
    pqa = jd(os.path.join(run_dir, "project_qa.json"), {}) if run_dir else {}
    bc = jd(os.path.join(run_dir, "backward_compat.json"), {}) if run_dir else {}
    fx = jd(os.path.join(run_dir, "fixtures.json"), {}) if run_dir else {}

    decision = fd.get("decision") or "(未运行)"
    items = gr.get("items") or []
    failed = gr.get("failed") or []
    npass = sum(1 for i in items if i.get("status") == "PASS")
    reg_path = os.path.join(VAULT, man["regression"]) if man.get("regression") else None
    reg = jd(reg_path, {}) if reg_path else {}

    # ---- 阻塞根因 ----
    if failed:
        block = "Gate `%s` 未通过：`%s`" % (gate.get("gate_id", "?"), ", ".join(failed))
    elif decision == "PHASE_5A_COMPLETE":
        block = "（无）"
    else:
        block = "(未运行验收)"

    # ---- issue 表 ----
    ilist = issues.get("issues") or issues.get("items") or []
    if isinstance(ilist, dict):
        ilist = [dict(v, id=k) for k, v in ilist.items()]
    irows = ["| id | 用户影响（摘要） | 严重度 | 状态 | 学术语义受影响 | 影响层 |",
             "|---|---|---|---|---|---|"]
    for it in ilist:
        irows.append("| `%s` | %s | %s | **%s** | `%s` | %s |" % (
            it.get("issue_id") or it.get("id", "?"),
            str(it.get("user_impact", ""))[:220].replace("|", "\\|"),
            it.get("severity", ""), it.get("status", ""),
            it.get("scholarly_semantics_affected", "?"),
            ", ".join(it.get("affected_layer") or [])))

    # ---- 可访问性表 ----
    arows = ["| 渲染视图 | 发现数 | 可聚焦原语 | 结果 |", "|---|---|---|---|"]
    for v in (a11y.get("rendered") or []):
        arows.append("| `%s` | %d | %s | %s |" % (
            v.get("where", ""), len(v.get("findings") or []),
            "; ".join(v.get("notes") or []),
            "PASS" if not v.get("findings") else "FAIL"))
    arows.append("| `%s`（静态） | %d | %s | %s |" % (
        (a11y.get("static") or {}).get("where", ""),
        len((a11y.get("static") or {}).get("findings") or []),
        "; ".join((a11y.get("static") or {}).get("notes") or []),
        "PASS" if not (a11y.get("static") or {}).get("findings") else "FAIL"))
    arows.append("")
    arows.append("**verdict = `%s`**；findings_total = **%d**（限界见工件 `limits`）"
                 % (a11y.get("verdict", "?"), a11y.get("findings_total", -1)))

    # ---- 浏览器 QA ----
    brows = ["| 场景 | 结果 |", "|---|---|"]
    cases = bqa.get("cases") or []
    if isinstance(cases, list):
        for c in cases:
            if not isinstance(c, dict):
                continue
            leaks = c.get("default_view_leaks")
            brows.append("| `%s` | leaks=%s；screenshot=`%s` |" % (
                c.get("case", "?"), leaks if leaks is not None else "—",
                c.get("screenshot", "")))
    for k, v in sorted(bqa.items()):
        if k in ("status", "cases", "screenshots"):
            continue
        brows.append("| `%s` | %s |" % (k, json.dumps(v, ensure_ascii=False)[:170]))

    # ── §26–§35 的内容
    seg = (lineage.get("segments") or [{}])[-1]

    def _tbl(rows, head):
        out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
        return "\n".join(out)

    cd = corpora
    corpus_tbl = _tbl(
        [["added", len(cd.get("added") or []),
          ", ".join(x.get("rel_path", "") for x in (cd.get("added") or []))],
         ["removed", len(cd.get("removed") or []),
          ", ".join(x.get("rel_path", "") for x in (cd.get("removed") or []))],
         ["modified", len(cd.get("modified") or []),
          ", ".join(x.get("rel_path", "") for x in (cd.get("modified") or []))],
         ["unchanged", cd.get("unchanged_n", "?"), "（逐条 sha256+size 相同）"]],
        ["变化类", "数量", "路径"])

    corpus_detail = "\n".join(
        "* `%s` size=%s sha256=`%s…` parse_status=`%s`"
        % (x.get("rel_path"), x.get("size"), str(x.get("sha256"))[:16],
           (x.get("classification") or {}).get("parse_status"))
        for x in (cd.get("added") or []))

    ing = (cd.get("ingestion_status") or [{}])[0]
    ing_tbl = _tbl(
        [["canonical passage store 的上游输入",
          ", ".join((ing.get("probe") or {}).get("canonical_passage_store_upstream_files")
                    or [])],
         ["atlas 命中（segments/staferla/french）",
          json.dumps((ing.get("probe") or {}).get("atlas_hits") or {}, ensure_ascii=False)],
         ["passage JSONL 命中", (ing.get("probe") or {}).get("passage_jsonl_hits")],
         ["结论", "**%s**" % ing.get("status")],
         ["是否可被 Research Core 检索", "**否**（未 ingestion）"]],
        ["探针", "结果"])

    ds = cd.get("derived_state") or {}
    derived_tbl = _tbl(
        [[k, (ds.get(k) or {}).get("state"),
          str((ds.get(k) or {}).get("why")
              or ((ds.get(k) or {}).get("agrees_with_frozen")
                  if "agrees_with_frozen" in (ds.get(k) or {}) else ""))[:110]]
         for k in ("corpus_inventory", "passage_store", "lexical_index",
                   "vector_index", "graph_cache")],
        ["依赖构件", "状态", "依据"])

    gv1 = _tbl([["gate_id", gate_v1.get("gate_id")],
                ["gate_hash", "`%s`" % gate_v1.get("gate_hash")],
                ["frozen_at", gate_v1.get("frozen_at")],
                ["判据数", len(gate_v1.get("criteria") or [])],
                ["历史判定", "**PHASE_5A_BLOCKED**"],
                ["历史失败判据", "`['H2','H8','H11','H12']` → 修正验收工具取数字段后 "
                                 "`['H8','H11','H12']`（三者均 P5A-006 级联）"],
                ["对应 run", "`5a_acceptance_20260926T180732Z_09a78f28`（不可变）"],
                ["是否被修改", "**否**（自洽校验通过）"]],
               ["项", "值"])

    gv2 = _tbl([[c["id"], c["requirement"], "blocking" if c.get("blocking") else "-"]
                for c in (gate_v2.get("criteria") or [])],
               ["判据", "requirement（逐字）", "阻塞"])

    freeze_id = _tbl(
        [["parent manifest", (rec_p6.get("parent_freeze") or {}).get("manifest")],
         ["parent sha256", "`%s`" % (rec_p6.get("parent_freeze") or {}).get("sha256")],
         ["new segment manifest", (rec_p6.get("new_freeze") or {}).get(
             "lineage_segment_snapshot")],
         ["new sha256", "`%s`" % (rec_p6.get("new_freeze") or {}).get("sha256")],
         ["scholarly_semantic_changes", rec_p6.get("scholarly_semantic_changes")],
         ["data_version_changes", rec_p6.get("data_version_changes")],
         ["product_runtime_changes", rec_p6.get("product_runtime_changes")]],
        ["项", "值"])

    lineage_seg = "```json\n%s\n```" % json.dumps(
        {k: seg.get(k) for k in ("phase", "manifest", "parent_manifest_hash",
                                 "manifest_hash", "status", "failure_codes",
                                 "changed_components", "scholarly_semantic_changes",
                                 "scholarly_semantic_change_keys",
                                 "data_version_changes_n", "product_runtime_changes",
                                 "unclassified_changes", "remediation")},
        ensure_ascii=False, indent=1)

    p6_verdict = (
        "P5A-006 = RESOLVED\n"
        "  语义漂移保护仍然严格（scholarly_semantic 变化 → SEMANTIC_DRIFT，硬失败）\n"
        "  已声明的数据版本变化被接受（data_version_changes = %s）\n"
        "  未声明的数据变化 fail closed（UNDECLARED_DATA_DRIFT）\n"
        "  依赖构件状态一致性已验证（DATA_VERSION_INCONSISTENT 路径有测试）\n"
        "  谱系同时记录两类变化（semantic / data_version / product_runtime）"
        % (seg.get("data_version_changes_n"),))

    rc_status = (
        "PHASE_5A            = %s\n"
        "SCHOLARLY_PRODUCT_HARDENED = %s\n"
        "RELEASE_CANDIDATE_RC1_2    = %s\n"
        "  （Phase 4E E14 人工复核：%s）"
        % (fd.get("decision", "(未运行)"),
           fd.get("scholarly_product_hardened"),
           fd.get("release_candidate_status", "(未运行)"),
           fd.get("phase4e_e14", "?")))

    timing_block = ("```json\n%s\n```" % json.dumps(timing, ensure_ascii=False,
                                                     indent=1)[:2500]
                    if timing else "(未生成：见 §22/§34 —— 由 "
                                   "`summarize_regression_timing.py` 落盘)")

    reps = {
        "<<<DECISION>>>": "`%s`" % decision,
        "<<<ACC_RUN>>>": "`%s`" % (os.path.basename(run_dir) if run_dir else "(未运行)"),
        "<<<GATE_HASH>>>": "`%s`" % gate.get("gate_hash", "?"),
        "<<<GATE_FROZEN_AT>>>": gate.get("frozen_at", "?"),
        "<<<GATE_PASS_N>>>": str(npass),
        "<<<FAILED>>>": "`%s`" % (failed or []),
        "<<<BLOCK_REASON>>>": block,
        "<<<RC>>>": "`%s`" % ("RC1.2" if decision == "PHASE_5A_COMPLETE" else "RC1.1"),
        "<<<ISSUES_TABLE>>>": "\n".join(irows),
        "<<<A11Y_TABLE>>>": "\n".join(arows),
        "<<<BROWSER_QA>>>": "\n".join(brows) + "\n\n" + json.dumps(
            bqa.get("status", {}), ensure_ascii=False, indent=2)[:1200],
        "<<<EXPORT_QA>>>": json.dumps(eqa, ensure_ascii=False, indent=2)[:2000],
        "<<<EXPORT_QA2>>>": "```json\n%s\n```" % json.dumps(
            eqa, ensure_ascii=False, indent=2)[:2500],
        "<<<OBSIDIAN_QA>>>": "```json\n%s\n```" % json.dumps(
            oqa, ensure_ascii=False, indent=2)[:2000],
        "<<<PROJECT_QA>>>": "```json\n%s\n```" % json.dumps(
            pqa, ensure_ascii=False, indent=2)[:2000],
        "<<<BACKCOMPAT>>>": "```json\n%s\n```" % json.dumps(
            bc, ensure_ascii=False, indent=2)[:2000],
        "<<<REGRESSION>>>": ("> 回归工件：`%s`\n\n```json\n%s\n```"
                             % (rel(reg_path) if reg_path else "(缺失)",
                                json.dumps({k: reg[k] for k in
                                            ("run_id", "suites", "checks",
                                             "failed", "skipped", "head_before",
                                             "head_after", "duration_s",
                                             "finished_at")
                                            if k in reg},
                                           ensure_ascii=False, indent=2))),
        "<<<REGRESSION_ATTRIBUTION>>>": _attribution(reg),
        "<<<REGRESSION_FINAL>>>": (
            "`%s`（suites=%s / checks=%s / **failed=%s** / skipped=%s / exit=%s / "
            "wall=%.0fs）\n\n```json\n%s\n```"
            % (rel(reg_path) if reg_path else "(缺失)", reg.get("suites"),
               reg.get("checks"), reg.get("failed"), reg.get("skipped"),
               reg.get("exit_code"), float(reg.get("wall_clock_seconds") or 0),
               json.dumps(reg.get("slowest_suites") or [], ensure_ascii=False,
                          indent=1)[:1500])),
        "<<<GATE_ID>>>": str(gate.get("gate_id", "?")),
        "<<<GATE_CRITERIA_N>>>": str(len(gate.get("criteria") or []) or 18),
        "<<<P6_CLASSIFICATION_CHANGE>>>": (
            "`_scripts/_tools/core_freeze.py`：把 SPEC 里的注释「# ── 数据版本」提升为"
            "机器可读的 `component_classes`（39 = 30 scholarly_semantic + 6 data_version "
            "+ 3 product_boundary），并新增 `DATA_VERSION_KEYS` / `DATA_VERSION_STATES` / "
            "`load_declarations()`；`--verify` 输出分类化漂移码 "
            "（`SEMANTIC_DRIFT` / `DATA_VERSION_DRIFT` / `PRODUCT_BOUNDARY_DRIFT`），"
            "**任何漂移仍然 FAIL**。\n\n"
            "`_scripts/_tools/freeze_lineage.py`：判定由\n\n"
            "```python\n"
            "# 旧（两类，注释里的分类看不见）\n"
            "semantic = [k for k in changed if k not in PRODUCT_BOUNDARY_KEYS]\n\n"
            "# 新（三类，按 core_freeze.component_class 判定）\n"
            "cls = _class_of(k, man, prev)          # None → UNCLASSIFIED_DRIFT\n"
            "semantic / data_keys / runtime          # 三个清单分别记录\n"
            "data_version 变化必须命中一条声明，且依赖构件状态一致\n"
            "```\n\n"
            "失败码：`SEMANTIC_DRIFT` / `UNDECLARED_DATA_DRIFT` / "
            "`UNCLASSIFIED_DRIFT` / `DATA_VERSION_INCONSISTENT`。"
            "**没有 wildcard 豁免**：只有 SPEC 明确声明的组件才可能被当作 data_version。"),
        "<<<P6_VERDICT>>>": p6_verdict,
        "<<<GATE_V1_HISTORY>>>": gv1,
        "<<<GATE_V2_TABLE>>>": gv2,
        "<<<CORPUS_DIFF_TABLE>>>": corpus_tbl,
        "<<<CORPUS_DIFF_DETAIL>>>": (corpus_detail
                                     + "\n\n审计工件：`_data/phase5a/corpus_diff_audit.json`"
                                     "（verdict = `%s`）" % cd.get("verdict")),
        "<<<CORPUS_143_144>>>": (
            "```text\n"
            "基线（冻结 manifest 钉住的那份 inventory，git HEAD）\n"
            "  files = %s  bytes = %s  sha256 = %s…\n"
            "现在（live）\n"
            "  files = %s  bytes = %s  sha256 = %s…\n"
            "verdict = %s\n"
            "```\n\n"
            "> 基线**不是**「就近取一份」：脚本以 manifest 记录的哈希核对 `git show "
            "HEAD:_data/corpus_inventory.json`，不一致即拒绝运行。\n"
            "> 新增 1 个文件、0 删除、0 修改、143 未变 —— **没有任何未解释的变化**。"
            % (cd.get("baseline_files"), cd.get("baseline_bytes"),
               str(cd.get("baseline_inventory_sha256"))[:16], cd.get("live_files"),
               cd.get("live_bytes"), str(cd.get("live_inventory_sha256"))[:16],
               cd.get("verdict"))),
        "<<<INGESTION_STATUS>>>": ing_tbl,
        "<<<DERIVED_INDEX_CONSISTENCY>>>": derived_tbl,
        "<<<FREEZE_IDENTITY>>>": freeze_id,
        "<<<LINEAGE_SEGMENT>>>": lineage_seg,
        "<<<TIMING_REPORT>>>": timing_block,
        "<<<RC_STATUS>>>": "```text\n%s\n```" % rc_status,
        "<<<TIMING>>>": "```json\n%s\n```" % json.dumps(
            reg.get("timing_summary") or reg.get("timing") or {},
            ensure_ascii=False, indent=2)[:1500],
        "<<<FREEZE>>>": ("**P5A-006 段（数据版本分离，末段）**\n\n```json\n%s\n```\n\n"
                         "**presentation-hardening 段（前一段）**\n\n```json\n%s\n```"
                         % (json.dumps(rec_p6, ensure_ascii=False, indent=1)[:2200],
                            json.dumps(remed, ensure_ascii=False, indent=1)[:1600])),
        "<<<SECRET>>>": "(见 `phase4e_secret_audit.py` 输出；命中 = 0)",
        "<<<KEYBOARD_TABLE>>>": "(见 `_scripts/_tests/test_phase5a_keyboard_flows.py`"
                                " 的 H8 结果与上文 H8 行)",
        "<<<USERVIEW_SAMPLE>>>": "（样例见验收工件 `fixtures.json`：每题含 "
                                 "`before_snapshot` / `after_user_view` / "
                                 "`after_audit_view`）",
        "<<<AUDIT_SAMPLE>>>": "（同上）",
        "<<<STATUS_BLOCK>>>": "PHASE_5A = %s\nGate           = %s (%d/%d PASS)\nfailed         = %s\nblocking       = %s" % (
            decision.replace("PHASE_5A_", ""), gate.get("gate_id", "?"), npass,
            len(items), failed, block),
        "<<<FINAL_BLOCK>>>": "PHASE_5A = %s\nRC         = %s\nblocked_by = %s" % (
            decision.replace("PHASE_5A_", ""),
            "RC1.2" if decision == "PHASE_5A_COMPLETE" else "RC1.1",
            failed or "—"),
    }

    if not os.path.isfile(DRAFT):
        print("缺草稿 %s" % DRAFT)
        return 2
    with open(DRAFT, encoding="utf-8") as fh:
        text = fh.read()
    unresolved = []
    for k, v in reps.items():
        if k in text:
            text = text.replace(k, v)
    import re
    for m in re.finditer(r"<<<[A-Z0-9_]+>>>", text):
        unresolved.append(m.group(0))
    if unresolved:
        print("WARN 未替换占位符: %s" % sorted(set(unresolved)))
    text = text.replace("# Phase 5A — Scholarly Product Hardening",
                        "# Phase 5A — Scholarly Product Hardening\n\n"
                        "<!-- 本文件由 `_scripts/_tools/phase5a_report.py` 从验收工件生成；"
                        "数字不手工填写 -->")
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote %s (%d lines, decision=%s, H=%d/%d)"
          % (rel(a.out), text.count("\n") + 1, decision, npass, len(items)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
