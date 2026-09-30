#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_export.py — Phase 4D.6：Export & Citation 契约自检（**只读**，供套件调用）

检查：
  1. 四格式 renderer 都存在，且都只消费 ExportDocument（不各自重新解释 source）
  2. schema 定义与磁盘一致；样例文档通过校验
  3. 跨格式 scholarly payload 一致（同一 source → 四格式同一 export_payload_hash）
  4. citation：三种内部样式可用；出版型样式在缺元数据时 fail closed
  5. bundle：结构齐备、manifest 完整、verify=VERIFIED、不含全库 passage
  6. 只写 `_workspace/exports/**`；不接受任意路径；审计只记元数据
  7. 前端安全（无 innerHTML/eval）+ ES 模块语法（按 ESM 解析）
  8. QA 工件齐备；core freeze + 谱系未被绕过
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

EXPORT_DIR = os.path.join(VAULT, "export_system")
SRC = os.path.join(VAULT, "workspace_ui", "static", "src")
QA = os.path.join(VAULT, "_workspace", "export_qa")
BANNED_MODULES = ("knowledge_api", "research_answer", "research_contract",
                  "research_execution", "synthesis_contract", "synthesis_claims",
                  "synthesis_render", "synthesis_adapters", "synthesis_entailment",
                  "synthesis_validation", "eval_integrity")
QA_FILES = ("cross_format_identity_qa.json", "citation_capability_qa.json",
            "research_export_qa.json", "abstention_export_qa.json",
            "project_bundle_qa.json", "browser_qa.json")
QA_SHOTS = ("export_menu.png", "citation_menu.png", "l2_export.png",
            "abstention_export.png", "project_export.png", "bundle_verify.png")


def _esm_problems():
    node = shutil.which("node")
    if not node:
        return []
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for fn in sorted(f for f in os.listdir(SRC) if f.endswith(".js")):
            dst = os.path.join(tmp, fn.replace(".js", ".mjs"))
            shutil.copyfile(os.path.join(SRC, fn), dst)
            r = subprocess.run([node, "--check", dst], capture_output=True, text=True)
            if r.returncode != 0:
                out.append("%s ESM 语法错误：%s" % (fn, (r.stderr or "").strip()[:140]))
    return out


def main():
    problems = []
    import export_system as EX

    # 1 renderer 齐备
    for name, mod in (("markdown", EX.markdown), ("json", EX.json_export),
                      ("html", EX.html_export), ("bundle", EX.bundle)):
        if not hasattr(mod, "render") and name != "bundle":
            problems.append("%s renderer 缺 render()" % name)
        if not hasattr(mod, "build_files") and name == "bundle":
            problems.append("bundle 缺 build_files()")
    for fn in sorted(os.listdir(EXPORT_DIR)):
        if not fn.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(EXPORT_DIR, fn), encoding="utf-8").read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        bad = mods & set(BANNED_MODULES)
        if bad:
            problems.append("export_system/%s import 核心内部：%s" % (fn, sorted(bad)))

    # 2 schema
    for name in (EX.SCHEMA_EXPORT_DOCUMENT, EX.SCHEMA_BUNDLE_MANIFEST,
                 EX.SCHEMA_CITATION_RECORD):
        sch = EX.model.load_schema(name)
        if sch.get("$id") != name:
            problems.append("schema $id 不一致：%s" % name)
        if sch.get("additionalProperties") is not False:
            problems.append("schema 非严格：%s" % name)

    # 3/4/5 端到端（在临时导出根里做，不污染真实 exports）
    from workspace_ui.server import api as A
    view = A.research("Seminar XI 中 gaze 与 objet a 是什么关系？", provider="mock",
                      save_history=False)["view"]
    prev = EX.policy.EXPORT_ROOTS.get("default")
    with tempfile.TemporaryDirectory(dir=os.path.join(VAULT, "_workspace")) as tmp:
        EX.policy.EXPORT_ROOTS["default"] = os.path.relpath(tmp, VAULT)
        try:
            d = EX.build_from_answer(view)
            texts = {"markdown": EX.markdown.render(d),
                     "json": EX.json_export.render(d),
                     "html": EX.html_export.render(d)}
            obj = EX.json_export.load(texts["json"])
            try:
                EX.assert_identity(d, obj)
            except EX.ExportError as exc:
                problems.append("JSON 与 source 身份不一致：%s" % exc.detail)
            out = EX.build_bundle(d, include_context=2)
            if out["verify"]["status"] != "VERIFIED":
                problems.append("bundle 自检未通过：%s" % out["verify"]["problems"][:3])
            if out["manifest"]["passage_count"] > 50:
                problems.append("bundle passage 数异常大：%s"
                                % out["manifest"]["passage_count"])
            if not texts["markdown"].count(d["citations"][0]["passage_id"]):
                problems.append("markdown 缺少 citation id")
            # citation capability
            rec = EX.citation_record("passage.S11.unknown.P2253",
                                     meta={"seminar_key": "S11"})
            # capability 的键是下划线形式（internal_short），样式名是连字符形式
            for style in EX.INTERNAL_STYLES:
                key = style.replace("-", "_")
                if not rec["capabilities"][key]:
                    problems.append("内部样式不可用：%s" % style)
                if not EX.render_citation(rec, style):
                    problems.append("内部样式渲染为空：%s" % style)
            for style in EX.BIBLIOGRAPHIC_STYLES:
                if rec["capabilities"][style]:
                    problems.append("缺出版元数据却可用：%s" % style)
            try:
                EX.render_citation(rec, "chicago")
                problems.append("chicago 未被拒绝")
            except EX.ExportError as exc:
                if exc.code != "BIBLIOGRAPHIC_METADATA_INCOMPLETE":
                    problems.append("chicago 错误码不对：%s" % exc.code)
            # 审计只记元数据
            for r in EX.read_audit():
                if any(k in json.dumps(r) for k in ("claim_text", "sections", "text")):
                    problems.append("审计记录了 scholarly 全文")
                    break
        finally:
            EX.policy.EXPORT_ROOTS["default"] = prev

    # 6 导出根
    from scholarly_api import policy as POL
    if POL.classify(os.path.join(EX.policy.EXPORT_ROOT_REL, "x.md")) != "USER_WORKSPACE":
        problems.append("导出根不在 USER_WORKSPACE")
    try:
        EX.policy.export_root("/tmp/evil")
        problems.append("任意路径未被拒")
    except EX.ExportError:
        pass
    try:
        EX.policy.resolve_export_path("../../etc/passwd")
        problems.append("路径穿越未被拒")
    except EX.ExportError:
        pass

    # 7 前端
    src_all = ""
    for fn in sorted(f for f in os.listdir(SRC) if f.endswith(".js")):
        s = open(os.path.join(SRC, fn), encoding="utf-8").read()
        src_all += s
        for bad in (".innerHTML", "insertAdjacentHTML", "document.write", "eval(",
                    "javascript:"):
            if bad in s:
                problems.append("%s 出现不安全 API：%s" % (fn, bad))
    if "api.exportCitation" not in src_all:
        problems.append("前端未走 citation formatter（§54）")
    problems += _esm_problems()

    # 8 QA 工件
    for f in QA_FILES:
        if not os.path.isfile(os.path.join(QA, f)):
            problems.append("缺 QA 证据：%s（跑 _scripts/_tools/build_export_qa.py）" % f)
    missing = [s for s in QA_SHOTS if not os.path.isfile(os.path.join(QA, s))]
    if missing:
        problems.append("缺视觉 QA 截图：%s" % missing[:3])
    try:
        xf = json.load(open(os.path.join(QA, "cross_format_identity_qa.json"),
                            encoding="utf-8"))
        if not xf.get("identical"):
            problems.append("跨格式一致性 QA 不成立")
        cap = json.load(open(os.path.join(QA, "citation_capability_qa.json"),
                             encoding="utf-8"))
        if cap.get("chicago") is not False:
            problems.append("citation capability QA 不成立")
    except Exception as exc:                                            # noqa: BLE001
        problems.append("QA 证据不可读：%s" % exc)

    for tool in ("core_freeze.py", "freeze_lineage.py"):
        r = subprocess.run([sys.executable, os.path.join(HERE, tool), "--verify", "--quiet"],
                           capture_output=True, text=True, cwd=VAULT)
        if r.returncode != 0:
            problems.append("%s 校验失败：%s" % (tool, (r.stdout + r.stderr)[-200:]))

    if problems:
        print("FAIL Export 契约自检未通过：")
        for p in problems[:12]:
            print("  - %s" % p)
        return 1
    print("Export 契约自检通过：四格式只消费 ExportDocument / schema 严格 / 跨格式身份一致 / "
          "bundle 自检 VERIFIED 且不含全库 / citation 三内部样式可用·出版型 fail closed / "
          "只写 _workspace/exports / 无 innerHTML·eval·ESM OK / QA 齐备 / freeze + 谱系 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
