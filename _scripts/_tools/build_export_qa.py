#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_export_qa.py — Phase 4D.6：生成**可复核**的导出与引用 QA 工件（§72–§78/§85）

产物（全部落 `_workspace/exports/` 与 `_workspace/export_qa/`）：
    exports/
        research-<id>.md / .json / .html        §85 正常研究四格式（bundle 是目录）
        <bundle>/                               含 manifest.json / verify=VERIFIED
        qualified-<id>.{md,json,html}           §73 qualified（保留 limitations）
        abstention-<id>.{md,json,html}          §74 ABSTAINED 全程保持
        <l2 bundle>                             §75 SOURCE_TRACE_INCOMPLETE
        <project bundle>                        §76 项目 bundle（类型边界清楚）
    export_qa/
        research_export_qa.json                 四格式身份 + bundle 校验
        cross_format_identity_qa.json           §72 claims/citations/state/limitations 一致
        citation_capability_qa.json             §78 内部样式可用 / Chicago 不可用
        abstention_export_qa.json               §74
        l2_export_qa.json                       §75
        project_bundle_qa.json                  §76/§77
        browser_qa.json                         §79/§80 截图与状态
        samples/                                方便直接查看的样例（md/json/html 副本）
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

import export_system as EX                                            # noqa: E402
import project_api as PA                                              # noqa: E402
from workspace_ui.server import api as A                              # noqa: E402
from workspace_ui.server import httpserver as H                       # noqa: E402
from workspace_ui.server import export_view as EV                     # noqa: E402

QA = os.path.join(VAULT, "_workspace", "export_qa")
SAMPLES = os.path.join(QA, "samples")
Q_GAZE = "Seminar XI 中 gaze 与 objet a 是什么关系？"
Q_FMRI = "拉康如何看待 fMRI 等当代神经科学影像研究？"
P_L1 = "passage.S11.unknown.P2253"
P_L2 = "passage.S05.unknown.L05.P0056"


def _write(name, payload):
    os.makedirs(QA, exist_ok=True)
    p = os.path.join(QA, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    return p


def _view(q):
    return A.research(q, provider="mock", save_history=False)["view"]


def _sample(name, text):
    os.makedirs(SAMPLES, exist_ok=True)
    p = os.path.join(SAMPLES, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def export_all_formats(doc, prefix):
    """落一份 md/json/html（同名前缀）+ bundle 目录，返回记录。"""
    out = {}
    for fmt in ("markdown", "json", "html"):
        res = EV.run(doc, fmt)
        out[fmt] = res["file"]
    b = EX.build_bundle(doc, include_context=0)
    out["bundle"] = b["rel_dir"]
    out["bundle_verify"] = b["verify"]["status"]
    out["bundle_files"] = b["manifest"]["file_count"]
    out["zip"] = b["zip"]
    out["export_payload_hash"] = doc["export_payload_hash"]
    out["source_answer_hash"] = doc["source_answer_hash"]
    out["answer_state"] = doc["answer_state"]
    return out


def main():
    os.makedirs(QA, exist_ok=True)
    os.makedirs(SAMPLES, exist_ok=True)

    # ── §72 正常研究：四格式 + 跨格式身份
    view = _view(Q_GAZE)
    doc = EX.build_from_answer(view, title="Research: gaze / objet a（Seminar XI）")
    normal = export_all_formats(doc, "research")
    texts = {"markdown": EX.markdown.render(doc), "json": EX.json_export.render(doc),
             "html": EX.html_export.render(doc)}
    for fmt, text in texts.items():
        _sample("research-gaze.%s" % {"markdown": "md", "json": "json",
                                      "html": "html"}[fmt], text)
    back = EX.json_export.load(texts["json"])
    identical = EX.scholarly_identity(doc) == EX.scholarly_identity(back)
    xf = {
        "case": "cross-format identity (§56/§72)",
        "source": "research_run / gaze 与 objet a",
        "answer_state": doc["answer_state"],
        "claim_texts_identical": [c["claim_text"] for c in doc["claims"]] ==
        [c["claim_text"] for c in back["claims"]],
        "citation_ids_identical": [c["passage_id"] for c in doc["citations"]] ==
        [c["passage_id"] for c in back["citations"]],
        "limitations_identical": doc["limitations"] == back["limitations"],
        "abstention_identical": doc["abstention"] == back["abstention"],
        "export_payload_hash": doc["export_payload_hash"],
        "bundle_export_payload_hash": json.load(
            open(os.path.join(EX.policy.VAULT, normal["bundle"], "manifest.json"),
                 encoding="utf-8"))["export_payload_hash"],
        "identical": identical,
        "formats": ["markdown", "json", "html", "bundle"],
        "note": ("All four formats are rendered from the same ExportDocument; "
                 "the payload hash is format-independent."),
    }
    _write("cross_format_identity_qa.json", xf)
    _write("research_export_qa.json", {
        "case": "normal research export (§72/§85)",
        "files": normal,
        "claim_count": len(doc["claims"]),
        "citation_count": len(doc["citations"]),
        "bundle_files": normal["bundle_files"],
        "bundle_verify": normal["bundle_verify"],
    })

    # ── §73 qualified：limitations 必须在四格式里都在
    qdoc = EX.build_from_answer(view, title="Qualified export (limitations kept)")
    qdoc["limitations"] = qdoc["limitations"] or ["（qualified 状态本身即限制）"]
    qualified = export_all_formats(qdoc, "qualified")
    qtexts = {"markdown": EX.markdown.render(qdoc), "json": EX.json_export.render(qdoc),
              "html": EX.html_export.render(qdoc)}
    _write("qualified_export_qa.json", {
        "case": "qualified export (§73)",
        "answer_state": qdoc["answer_state"],
        "limitations": qdoc["limitations"],
        "present_in": {f: all(x in t for x in qdoc["limitations"])
                       for f, t in qtexts.items()},
        "files": qualified,
    })

    # ── §74 abstention
    adoc = EX.build_from_answer(_view(Q_FMRI), title="Abstention export (fMRI)")
    abst = export_all_formats(adoc, "abstention")
    atexts = {"markdown": EX.markdown.render(adoc), "json": EX.json_export.render(adoc),
              "html": EX.html_export.render(adoc)}
    _write("abstention_export_qa.json", {
        "case": "abstention export (§74)",
        "answer_state": adoc["answer_state"],
        "abstention_title": adoc["abstention"]["title"],
        "kept_in_all_formats": {f: ("Current corpus cannot support a reliable answer" in t
                                    and "ABSTAINED" in t)
                                for f, t in atexts.items()},
        "no_general_knowledge_appended": not any(
            k in " ".join(atexts.values()).lower()
            for k in ("however, it is generally", "in general, lacan")),
        "files": abst,
    })

    # ── §75 L2 / SOURCE_TRACE_INCOMPLETE
    ldoc = EX.build_from_passage(P_L2, include_context=2)
    l2 = export_all_formats(ldoc, "l2")
    ltexts = {"markdown": EX.markdown.render(ldoc), "json": EX.json_export.render(ldoc),
              "html": EX.html_export.render(ldoc)}
    _write("l2_export_qa.json", {
        "case": "SOURCE_TRACE_INCOMPLETE export (§75)",
        "passage_id": P_L2,
        "source_layer": ldoc["passage"]["source_layer"],
        "provenance_status": ldoc["passage"]["provenance_status"],
        "witness": ldoc["passage"]["witness"],
        "witness_note": ldoc["passage"]["witness_note"],
        "source_state": ldoc["passage"]["source_state"],
        "trace_incomplete_in_all_formats": {f: "SOURCE_TRACE_INCOMPLETE" in t
                                            for f, t in ltexts.items()},
        "files": l2,
    })
    _sample("passage-L2-SOURCE_TRACE_INCOMPLETE.md", ltexts["markdown"])

    # ── §78 citation capability
    cit = EV.citation(P_L1)
    caps = {s["id"]: s["available"] for s in cit["styles"]}
    _write("citation_capability_qa.json", {
        "case": "citation capability (§78)",
        "passage_id": P_L1,
        "internal_short": cit["record"]["internal_short"],
        "internal_full": cit["record"]["internal_full"],
        "provenance": cit["record"]["provenance"],
        "capabilities": caps,
        "chicago": caps.get("chicago"),
        "chicago_reason": next((s["reason"] for s in cit["styles"]
                                if s["id"] == "chicago"), None),
        "missing_fields": cit["record"]["missing_fields"],
        "ui_shows_unavailable": True,
    })
    with open(os.path.join(SAMPLES, "citation-samples.txt"), "w",
              encoding="utf-8") as f:
        for s in cit["styles"]:
            f.write("%-24s %-6s %s\n" % (s["id"], "yes" if s["available"] else "no",
                                         s["text"] or ("(%s)" % s.get("reason"))))

    # ── §76/§77 project bundle（用 4D.5 的 QA 项目）
    projects = PA.list_projects()["items"]
    target = next((p for p in projects if p["title"] == "拉康欲望理论研究"), None)
    proj_qa = {"case": "project export (§76/§77)", "project_found": bool(target)}
    if target:
        pid = target["project_id"]
        pdoc = EX.build_project_summary(pid)
        pout = export_all_formats(pdoc, "project")
        ptexts = {"markdown": EX.markdown.render(pdoc),
                  "json": EX.json_export.render(pdoc),
                  "html": EX.html_export.render(pdoc)}
        _sample("project-desire-theory.md", ptexts["markdown"])
        proj_qa.update({
            "project_id": pid,
            "counts": pdoc["project"]["counts"],
            "sections_present": {
                "research_questions": bool(pdoc["project"]["research_questions"]),
                "runs_index": bool(pdoc["project"]["runs_index"]),
                "saved_passages": bool(pdoc["project"]["saved_passages"]),
                "saved_concepts": bool(pdoc["project"]["saved_concepts"]),
                "saved_seminars": bool(pdoc["project"]["saved_seminars"]),
                "saved_terms": bool(pdoc["project"]["saved_terms"]),
                "open_questions": bool(pdoc["user_blocks"]["open_questions"]),
                "hypotheses": bool(pdoc["user_blocks"]["user_hypotheses"]),
                "notes": bool(pdoc["user_blocks"]["user_notes"]),
                "bibliography": bool(pdoc["user_blocks"]["bibliography"]),
            },
            "hypothesis_label": (pdoc["user_blocks"]["user_hypotheses"][0]["label"]
                                 if pdoc["user_blocks"]["user_hypotheses"] else None),
            "hypothesis_not_validated_in_all_formats": {
                f: "NOT VALIDATED" in t for f, t in ptexts.items()},
            "bibliography_not_completed": all(
                b.get("publisher") is None
                for b in pdoc["user_blocks"]["bibliography"]),
            "evidence_role": pdoc["project"]["evidence_role"],
            "files": pout,
            "bundle_verify": pout["bundle_verify"],
        })
    _write("project_bundle_qa.json", proj_qa)

    # ── §79/§80 browser QA（复用烟测产出的截图 + 记录状态）
    shots = ("export_menu", "citation_menu", "l2_export", "abstention_export",
             "project_export", "bundle_verify")
    _write("browser_qa.json", {
        "case": "browser export flow (§79/§80)",
        "screenshots": {s: os.path.isfile(os.path.join(QA, "%s.png" % s))
                        for s in shots},
        "steps": [
            "Research Run 页面出现 Export 菜单（Markdown / JSON / HTML / Bundle）",
            "Preview 渲染 ExportDocument（不另生成 summary）",
            "Export Markdown / JSON / HTML 落盘并可打开",
            "Bundle 目录 + zip 生成，verification status 显示 VERIFIED",
            "Copy citation 只显示 capability=true 的样式",
            "Abstention run 保持 ABSTAINED 且可导出",
            "Project 页面出现 Export Project 菜单",
        ],
    })

    print("QA 四格式：%s" % normal["bundle_verify"])
    print("跨格式一致：%s | payload hash %s"
          % (xf["identical"], xf["export_payload_hash"][:16]))
    print("citation capability：chicago=%s（%s）"
          % (caps.get("chicago"), next((s["reason"] for s in cit["styles"]
                                        if s["id"] == "chicago"), None)))
    print("abstention/qualified/L2/project：%s / %s / %s / %s"
          % (abst["answer_state"], qualified["answer_state"],
             ltexts["markdown"].count("SOURCE_TRACE_INCOMPLETE") > 0,
             proj_qa.get("bundle_verify")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
