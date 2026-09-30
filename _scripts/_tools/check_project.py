#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_project.py — Phase 4D.5：Research Project 契约自检（**只读**，供套件调用）

检查：
  1. project_api 只读写 USER_WORKSPACE；不 import 核心内部 / synthesis / retrieval
  2. 项目层不产生 evidence：`context_for_agent` 必须标 NOT_EVIDENCE；不调研究/MCP
  3. 存储纪律：schema_version / revision / 原子写 / WORKSPACE_CONFLICT
  4. QA 项目与证据齐备（正常项目 + 弃权项目 + 跨项目引用 + Obsidian Hub + 截图）
  5. 前端安全：无 innerHTML / insertAdjacentHTML / document.write / eval
  6. ES 模块语法（按 ESM 解析：`node --check x.js` 会漏掉 ESM 语法错）
  7. core freeze + 冻结谱系未被绕过
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)

PROJ = os.path.join(VAULT, "project_api")
SRC = os.path.join(VAULT, "workspace_ui", "static", "src")
QA = os.path.join(VAULT, "_workspace", "project_qa")
BANNED_MODULES = ("knowledge_api", "research_answer", "research_contract",
                  "research_execution", "synthesis_contract", "synthesis_claims",
                  "synthesis_render", "synthesis_adapters", "synthesis_entailment",
                  "synthesis_validation", "eval_integrity", "hybrid_retrieve",
                  "lacan_search")
QA_SHOTS = ("project_list.png", "project_overview.png", "project_questions.png",
            "project_runs.png", "project_abstained_run.png", "project_evidence.png",
            "project_open_questions.png", "project_hypotheses.png", "project_notes.png",
            "project_revision_conflict.png", "project_archived.png")
QA_FILES = ("cross_project_qa.json", "abstention_qa.json", "project_manifest_qa.json",
            "project_verify_qa.json", "obsidian_hub.md")


def _imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    mods, calls = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "id", None) or getattr(f, "attr", None)
            if name:
                calls.add(name)
    return mods, calls


def _esm_syntax_problems():
    node = shutil.which("node")
    if not node:
        return []
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        for fn in sorted(f for f in os.listdir(SRC) if f.endswith(".js")):
            dst = os.path.join(tmp, fn.replace(".js", ".mjs"))
            shutil.copyfile(os.path.join(SRC, fn), dst)
            r = subprocess.run([node, "--check", dst], capture_output=True, text=True)
            if r.returncode != 0:
                problems.append("%s ESM 语法错误：%s" % (fn, (r.stderr or "").strip()[:140]))
    return problems


def main():
    problems = []
    import project_api as PA
    from workspace_ui.server import project_view as PV

    # 1
    for fn in sorted(os.listdir(PROJ)):
        if not fn.endswith(".py"):
            continue
        mods, calls = _imports(os.path.join(PROJ, fn))
        bad = mods & set(BANNED_MODULES)
        if bad:
            problems.append("project_api/%s import 了核心内部：%s" % (fn, sorted(bad)))
        if calls & {"evidence_packet", "search_passages", "run_validation_pipeline"}:
            problems.append("project_api/%s 调用了 evidence 路径" % fn)
    from scholarly_api import policy as POL
    if POL.classify("_workspace/projects/x/project.json") != "USER_WORKSPACE":
        problems.append("项目存储不在 USER_WORKSPACE")

    # 2
    with tempfile.TemporaryDirectory(dir=os.path.join(VAULT, "_workspace")) as tmp:
        prev = PA.store.PROJECTS_DIR
        PA.store.PROJECTS_DIR = tmp
        try:
            p = PA.create_project("契约自检", tags=["qa"])
            ctx = PA.context_for_agent(p["project_id"])
            if ctx.get("evidence_role") != "NOT_EVIDENCE":
                problems.append("context_for_agent 未标 NOT_EVIDENCE")
            if ctx.get("selected_notes") != [] or ctx.get("selected_runs") != []:
                problems.append("context_for_agent 默认携带内容（违反 §42 预算）")
            doc = PA.read_project(p["project_id"])
            if doc.get("schema_version") != 1 or doc.get("revision") != 1:
                problems.append("项目 schema/revision 初值不对")
            try:
                PA.update_project(p["project_id"], 99, title="x")
                problems.append("revision 冲突未被拦截")
            except PA.Conflict:
                pass
            runs = PA.verify_project_runs(p["project_id"])
            if runs["overall"] not in ("VERIFIED",):
                problems.append("空项目的 verify 状态异常：%s" % runs["overall"])
        finally:
            PA.store.PROJECTS_DIR = prev

    # 3
    src = open(os.path.join(PROJ, "store.py"), encoding="utf-8").read()
    for need in ("POL.assert_writable", "os.replace", "expected_revision",
                 "WORKSPACE_CONFLICT", "PROJECT_SCHEMA_VERSION"):
        if need not in src:
            problems.append("store.py 缺关键机制：%s" % need)

    # 4 QA 工件
    for f in QA_FILES:
        if not os.path.isfile(os.path.join(QA, f)):
            problems.append("缺 QA 证据：%s（跑 _scripts/_tools/build_project_qa.py）" % f)
    missing = [s for s in QA_SHOTS if not os.path.isfile(os.path.join(QA, s))]
    if missing:
        problems.append("缺视觉 QA 截图：%s" % missing[:3])
    qa = PA.list_projects()["items"]
    titles = {p["title"] for p in qa}
    for need in ("拉康欲望理论研究", "Lacan 与现代神经科学"):
        if need not in titles:
            problems.append("缺 QA 项目：%s" % need)
    try:
        cross = json.load(open(os.path.join(QA, "cross_project_qa.json"), encoding="utf-8"))
        if not (cross["project_a"]["has_passage"] and cross["project_b"]["has_passage"]):
            problems.append("跨项目引用 QA 不成立")
        abd = json.load(open(os.path.join(QA, "abstention_qa.json"), encoding="utf-8"))
        if abd["answer_state"] != "ABSTAINED" or abd["stored_as_answered"]:
            problems.append("弃权项目 QA 不成立")
        if not abd["relations_snapshot_stable"] or abd["canonical_relations_created"]:
            problems.append("弃权项目产生了 canonical 关系")
    except Exception as exc:                                        # noqa: BLE001
        problems.append("QA 证据不可读：%s" % exc)

    # 5 前端安全
    for fn in sorted(f for f in os.listdir(SRC) if f.endswith(".js")):
        s = open(os.path.join(SRC, fn), encoding="utf-8").read()
        for bad in (".innerHTML", "insertAdjacentHTML", "document.write", "eval(",
                    "javascript:"):
            if bad in s:
                problems.append("%s 出现不安全 API：%s" % (fn, bad))

    # 6 ESM 语法
    problems += _esm_syntax_problems()

    # 7 冻结
    for tool in ("core_freeze.py", "freeze_lineage.py"):
        r = subprocess.run([sys.executable, os.path.join(HERE, tool), "--verify", "--quiet"],
                           capture_output=True, text=True, cwd=VAULT)
        if r.returncode != 0:
            problems.append("%s 校验失败：%s" % (tool, (r.stdout + r.stderr)[-200:]))

    if problems:
        print("FAIL Research Project 契约自检未通过：")
        for p in problems[:12]:
            print("  - %s" % p)
        return 1
    print("Research Project 契约自检通过：project_api 只碰 USER_WORKSPACE / 不进 evidence 路径 / "
          "schema+revision+原子写+冲突拦截 / QA 项目与证据齐备 / "
          "前端无 innerHTML·eval / ESM 语法 OK / core freeze + 谱系 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
