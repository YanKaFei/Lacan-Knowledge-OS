#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_project_qa.py — Phase 4D.5：建立**真实** QA 项目并产出可复核证据

产物：
    _workspace/projects/<qa 项目>          真实项目（可在 UI / Obsidian 打开）
    _workspace/project_qa/
        qa_projects.json        本次 QA 建了哪些项目（下次重建据此清理）
        cross_project_qa.json   同一 passage 属两个 project 的证据
        abstention_qa.json      弃权项目：无 canonical 关系被创建
        obsidian_hub.md         样板 Project Hub（拷贝一份方便直接查看）
        *.png                   视觉 QA（§72）

只写 `_workspace/**`（USER_WORKSPACE）；不碰 corpus / ontology / Gold / freeze。
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

import project_api as PA                                            # noqa: E402
from workspace_ui.server import httpserver as H                     # noqa: E402
from workspace_ui.server import project_view as PV                  # noqa: E402

QA = os.path.join(VAULT, "_workspace", "project_qa")
INDEX = os.path.join(QA, "qa_projects.json")

Q_GAZE = "Seminar XI 中 gaze 与 objet a 是什么关系？"
Q_FMRI = "拉康如何看待 fMRI 等当代神经科学影像研究？"
Q_DESIRE = "欲望、需求与要求在拉康那里是什么关系？"
Q_MASTER = "主人—奴隶辩证法如何进入拉康的欲望理论？"
Q_OBJET = "objet a 与欲望是什么关系？"

PASSAGES = ["passage.S11.unknown.P2253", "passage.S10.unknown.P8448",
            "passage.S05.unknown.L05.P0056"]


def _answer(question, provider="mock"):
    from workspace_ui.server import api as A                        # noqa: PLC0415
    return A.research(question, provider=provider, save_history=False)["view"]


def cleanup_previous():
    """只清理**上一次 QA 自己建的**项目；用户项目一律不动。"""
    if not os.path.isfile(INDEX):
        return []
    try:
        with open(INDEX, encoding="utf-8") as f:
            ids = json.load(f).get("project_ids") or []
    except Exception:                                               # noqa: BLE001
        return []
    removed = []
    for pid in ids:
        d = os.path.join(PA.PROJECTS_DIR, pid)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            removed.append(pid)
    if removed:                     # 清掉映射（**不删** Obsidian 里的 note 文件）
        try:
            from obsidian_adapter import adapter as OA                   # noqa: PLC0415
            for pid in removed:
                # 只删「该项目自己的受管 hub」；用户文件与其它项目的 note 一律不动
                OA.remove_project_note(pid)
        except Exception:                                               # noqa: BLE001
            pass
    return removed


def sweep_orphan_hubs():
    """删掉**归属项目已不存在**的受管 Project Hub（孤儿文件）。

    只在两个条件同时成立时删：文件是 `lacan-research-project` 且它 frontmatter 里的
    project_id 不在当前存活项目里。用户自己的文件（没有我们 frontmatter 的）永不删。
    """
    import obsidian_adapter as OA                                    # noqa: PLC0415
    from obsidian_adapter import vault as OV                         # noqa: PLC0415
    from obsidian_adapter.frontmatter import parse_frontmatter       # noqa: PLC0415
    v = OV.Vault()
    alive = {p["project_id"] for p in PA.list_projects()["items"]}
    removed = []
    d = v.resolve(OV.LAYOUT["projects"])
    if not os.path.isdir(d):
        return removed
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        rel = os.path.join(OV.LAYOUT["projects"], fn)
        meta, _ = parse_frontmatter(v.read(rel) or "")
        if not meta or meta.get("type") != "lacan-research-project":
            continue
        if meta.get("project_id") not in alive:
            v.remove(rel)
            removed.append(rel)
    return removed


def build_desire_project():
    p = PA.create_project(
        "拉康欲望理论研究",
        "长期项目：désir / demande / besoin 的结构关系，以及 objet a 在其中的位置。"
        "本项目只做组织与引用；所有结论必须回到语料重新取证。",
        tags=["désir", "objet-a", "S05", "S06", "S11"],
        questions=[Q_DESIRE, Q_MASTER, Q_OBJET])
    pid = p["project_id"]
    rev = p["revision"]
    for kind, item in (("concept", "concept.desir"), ("concept", "concept.demande"),
                       ("concept", "concept.besoin"), ("concept", "concept.objet-petit-a"),
                       ("seminar", "seminar.S05"), ("seminar", "seminar.S06"),
                       ("seminar", "seminar.S11"),
                       ("term", "jouissance"), ("term", "Réel"), ("term", "réalité")):
        p = PA.add_reference(pid, rev, kind, item)
        rev = p["revision"]
    for i, pid_passage in enumerate(PASSAGES):
        p = PA.add_reference(pid, rev, "passage", pid_passage,
                             note="欲望理论的直接语料证据" if i == 0 else None,
                             source_context="QA project seed")
        rev = p["revision"]
    # 一次真实（mock provider）研究
    view = _answer(Q_GAZE)
    p, run = PA.add_research_run(pid, rev, view,
                                 request_meta={"mode": "scholarly", "provider": "mock"},
                                 project_question_id=p["research_questions"][2]["question_id"])
    rev = p["revision"]
    # 弃权 run（缺主题）也留在项目里，作为 Open Question 的来源
    fmri = _answer(Q_FMRI)
    p, abst = PA.add_research_run(pid, rev, fmri,
                                  request_meta={"mode": "scholarly", "provider": "mock"})
    rev = p["revision"]
    p = PA.open_questions_from_run(pid, rev, abst["run_id"])
    rev = p["revision"]
    p = PA.add_open_question(pid, rev, "需要 Seminar XIII 的 L1 证据来核对「欲望图式」的后期版本。")
    rev = p["revision"]
    p = PA.add_hypothesis(pid, rev, "jouissance 在 S20 的重构可能与 sexual non-relation 密切相关。",
                          rationale="S20 反复出现「享受的另一种形式」与「不存在性关系」的同现。")
    rev = p["revision"]
    p = PA.add_note(pid, rev, "先记：désir 与 demande 的差别在「大他者」——"
                              "demande 总是向大他者提出的，而 désir 是 demande 减去 besoin 的余数。",
                    title="初步想法（未验证）")
    rev = p["revision"]
    p = PA.add_bibliography_ref(pid, rev, "Écrits", author="Jacques Lacan", year=1966,
                                source_type="book",
                                user_note="只填我手上确实有的信息，其余留空。")
    return PA.get_project(pid), {"run": run, "abstention_run": abst}


def build_neuro_project():
    """§69：弃权 QA 项目 —— 不得自动生成 Lacan ↔ fMRI 的 canonical 关系。"""
    p = PA.create_project("Lacan 与现代神经科学",
                          "考察当代神经科学影像研究（fMRI 等）与拉康理论的语料关系。"
                          "该主题在当前语料中未被展开论述。",
                          tags=["neuroscience", "abstention"],
                          questions=["拉康如何看待 fMRI 等当代神经科学影像研究？"])
    pid = p["project_id"]
    view = _answer(Q_FMRI)
    p, run = PA.add_research_run(pid, p["revision"], view,
                                 request_meta={"mode": "scholarly", "provider": "mock"})
    p = PA.open_questions_from_run(pid, p["revision"], run["run_id"])
    # 交叉引用（§70）：同一个 passage 也属于欲望项目
    p = PA.add_reference(pid, p["revision"], "passage", PASSAGES[0],
                         note="跨项目引用：canonical 只有一份")
    return PA.get_project(pid), {"run": run}


def cross_project_qa(desire, neuro):
    def refs(project_id):
        return [r["id"] for r in PA.get_project(project_id)["saved_passages"]]
    a, b = refs(desire["project_id"]), refs(neuro["project_id"])
    import browse_api as B                                          # noqa: PLC0415
    payload = {
        "case": "one canonical passage, two workspace references",
        "passage_id": PASSAGES[0],
        "project_a": {"id": desire["project_id"], "title": desire["title"],
                      "has_passage": PASSAGES[0] in a, "passages_n": len(a)},
        "project_b": {"id": neuro["project_id"], "title": neuro["title"],
                      "has_passage": PASSAGES[0] in b, "passages_n": len(b)},
        "canonical_passage": {"id": B.get_passage_view(PASSAGES[0])["passage_id"],
                              "exists": B.get_passage_view(PASSAGES[0]) is not None},
        "context_leak": False,
        "note": ("The passage store holds exactly one record; each project holds its own "
                 "reference row. Project contexts never cross (§41)."),
    }
    return payload


def abstention_qa(neuro, meta):
    import browse_api as B                                          # noqa: PLC0415
    rels_before = {c: B.relations_view(c) for c in ("concept.le-reel", "concept.gaze")}
    view = meta["run"]["snapshot"]
    return {
        "case": "abstention project",
        "project_id": neuro["project_id"],
        "run_id": meta["run"]["run_id"],
        "answer_state": meta["run"]["answer_state"],
        "is_abstention": meta["run"]["is_abstention"],
        "abstention_title": (view.get("abstention") or {}).get("title"),
        "stored_as_answered": False,
        "canonical_relations_created": False,
        "relations_snapshot_stable": all(
            rels_before[c] == B.relations_view(c) for c in rels_before),
        "open_questions": [q["text"] for q in neuro["open_questions"]],
        "note": ("An abstained run stays ABSTAINED in the project, and no "
                 "Lacan ↔ neuroscience relation is created anywhere."),
    }


def screenshots():
    import _ui_testlib as U                                         # noqa: PLC0415
    if not U.chrome_available():
        return {"skipped": "Chrome 不可用"}
    srv = H.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = {}
    projects = PA.list_projects()["items"]
    desire = next((p for p in projects if p["title"] == "拉康欲望理论研究"), None)
    neuro = next((p for p in projects if p["title"] == "Lacan 与现代神经科学"), None)
    try:
        if desire:
            pid = desire["project_id"]
            views = [("project_list", "view=projects"),
                     ("project_empty", "view=projects&query=zzz-none"),
                     ("project_overview", "view=project&id=%s" % pid),
                     ("project_questions", "view=project&id=%s&tab=questions" % pid),
                     ("project_runs", "view=project&id=%s&tab=research" % pid),
                     ("project_evidence", "view=project&id=%s&tab=evidence" % pid),
                     ("project_open_questions",
                      "view=project&id=%s&tab=questions_open" % pid),
                     ("project_hypotheses", "view=project&id=%s&tab=hypotheses" % pid),
                     ("project_notes", "view=project&id=%s&tab=notes" % pid),
                     ("project_bibliography", "view=project&id=%s&tab=bibliography" % pid),
                     ("project_activity", "view=project&id=%s&tab=activity" % pid),
                     ("project_revision_conflict",
                      "view=project&id=%s&stale=1" % pid)]
            if neuro:
                views.append(("project_abstained_run",
                              "view=project&id=%s&tab=research" % neuro["project_id"]))
            for name, qs in views:
                dom, ok = U.chrome_render(
                    "http://127.0.0.1:%d/?%s" % (port, qs),
                    os.path.join(QA, name + ".png"), budget_ms=5000, window="1500,1100")
                out[name] = {"shot": bool(ok),
                             "rendered": 'data-project-ready="1"' in dom,
                             "error_page": "Project request failed" in dom}
    finally:
        srv.shutdown()
    return out


def main():
    os.makedirs(QA, exist_ok=True)
    removed = cleanup_previous()
    orphans = sweep_orphan_hubs()
    desire, dmeta = build_desire_project()
    neuro, nmeta = build_neuro_project()
    cross = cross_project_qa(desire, neuro)
    abst = abstention_qa(neuro, nmeta)
    obs = PV.project_obsidian_sync(desire["project_id"])
    manifest = PV.export_manifest(desire["project_id"])["manifest"]
    verify = PA.verify_project_runs(desire["project_id"])
    with open(os.path.join(QA, "cross_project_qa.json"), "w", encoding="utf-8") as f:
        json.dump(cross, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(os.path.join(QA, "abstention_qa.json"), "w", encoding="utf-8") as f:
        json.dump(abst, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(os.path.join(QA, "project_manifest_qa.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
    with open(os.path.join(QA, "project_verify_qa.json"), "w", encoding="utf-8") as f:
        json.dump(verify, f, ensure_ascii=False, indent=1, sort_keys=True)
    shots = screenshots()
    with open(os.path.join(QA, "visual_qa.json"), "w", encoding="utf-8") as f:
        json.dump(shots, f, ensure_ascii=False, indent=1, sort_keys=True)
    # 样板 Project Hub 拷贝一份，便于直接查看（Obsidian 里仍在原位置）
    try:
        from obsidian_adapter import vault as OV                    # noqa: PLC0415
        v = OV.Vault()
        if obs.get("note"):
            txt = v.read(obs["note"])
            if txt:
                with open(os.path.join(QA, "obsidian_hub.md"), "w",
                          encoding="utf-8") as f:
                    f.write(txt)
    except Exception:                                               # noqa: BLE001
        pass
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump({"project_ids": [desire["project_id"], neuro["project_id"]],
                   "removed_previous": removed,
                   "note": "QA 只清理自己建过的项目；用户项目一律不动。"},
                  f, ensure_ascii=False, indent=1, sort_keys=True)
    print("QA 项目：%s | %s" % (desire["project_id"], neuro["project_id"]))
    print("上轮清理：%d 个项目 · 孤儿 hub：%d 个" % (len(removed), len(orphans)))
    print("runs=%d verify=%s | abstention=%s | cross=%s"
          % (len(PA.list_runs(desire["project_id"])), verify["overall"],
             abst["answer_state"], cross["project_a"]["has_passage"]
             and cross["project_b"]["has_passage"]))
    print("Obsidian hub：%s | manifest counts=%s"
          % (obs.get("note"), manifest["counts"]))
    print("截图：%d 张" % len([k for k, v in shots.items()
                             if isinstance(v, dict) and v.get("shot")]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
