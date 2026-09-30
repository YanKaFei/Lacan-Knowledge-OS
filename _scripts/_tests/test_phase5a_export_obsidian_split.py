#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase5a_export_obsidian_split.py — Phase 5A §11/§12/§46/§47/§55/§56

* **标准导出**（Markdown / JSON / HTML / Bundle）：internal validator diagnostics = 0；
* **Audit Bundle**：诊断存在（`audit/rejected_claims.json` + `audit/validation_trace.json`），
  且 bundle 自检 VERIFIED；
* **Obsidian 标准笔记**：不出现 validator trace；`include_audit=True` 时另存审计工件；
* 学术身份不变（claims / citations / state 在两种模式下一致）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
import contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", "_tools"))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for p in (TOOLS, os.path.join(TOOLS, "lacan_mcp"), VAULT):
    sys.path.insert(0, p)

import export_system as EX                          # noqa: E402
from scholarly_api import core                      # noqa: E402
from workspace_ui.server import viewmodel as VM, export_view as EV   # noqa: E402
from obsidian_adapter import adapter as OA          # noqa: E402
from obsidian_adapter import vault as OV            # noqa: E402

REJECT_Q = "黑格尔的主人—奴隶辩证法如何进入拉康的欲望理论？"
DIAG_MARKERS = ("NOT_ENTAILED", "已剔除", "因未通过验证被剔除", "通过蕴含验证的断言构成")


@contextlib.contextmanager
def _isolated_roots(tag):
    prev_export = EX.policy.EXPORT_ROOTS["default"]
    prev_env = os.environ.get("OBSIDIAN_VAULT_PATH")
    base = os.path.join(VAULT, "_workspace", "phase5a_tests", tag)
    os.makedirs(base, exist_ok=True)
    EX.policy.EXPORT_ROOTS["default"] = os.path.relpath(os.path.join(base, "exports"), VAULT)
    os.environ["OBSIDIAN_VAULT_PATH"] = os.path.join(base, "vault")
    try:
        yield base
    finally:
        EX.policy.EXPORT_ROOTS["default"] = prev_export
        if prev_env is None:
            os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        else:
            os.environ["OBSIDIAN_VAULT_PATH"] = prev_env
        shutil.rmtree(base, ignore_errors=True)


class TestExportObsidianSplit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        r = core.research(REJECT_Q, {"provider": "mock", "mode": "philosophy_to_lacan",
                                    "task_id": "p5a-export", "language": "any"})
        cls.view = VM.answer_view({"ok": True, "result": r,
                                   "meta": {"provider": "mock", "request_id": "p5a-export"}})
        cls.audit = cls.view["audit"]

    def test_00_standard_formats_have_no_diagnostics(self):
        doc = EV.build("research_run", view=self.view, source_id="p5a-export")
        blob = json.dumps(doc, ensure_ascii=False)
        for m in DIAG_MARKERS:
            self.assertNotIn(m, blob, "标准 ExportDocument 含内部诊断：%s" % m)
        for renderer in (EX.markdown.render, EX.json_export.render, EX.html_export.render):
            text = renderer(doc)
            for m in DIAG_MARKERS:
                self.assertNotIn(m, text, "标准导出渲染结果含内部诊断：%s" % m)

    def test_01_standard_export_keeps_scholarly_content(self):
        doc = EV.build("research_run", view=self.view, source_id="p5a-export")
        self.assertTrue(doc["sections"], "标准导出不得为空")
        self.assertEqual([c["claim_id"] for c in doc["claims"]],
                         [c["claim_id"] for c in self.view["claims"]])
        self.assertEqual([c["passage_id"] for c in doc["citations"]],
                         [c["passage_id"] for c in self.view["citations"]])
        self.assertEqual(doc["answer_state"], self.view["state"])

    def test_02_audit_bundle_carries_diagnostics_and_verifies(self):
        with _isolated_roots("export") as base:
            doc = EV.build("research_run", view=self.view, source_id="p5a-export",
                           include_audit=True)
            out = EV.run(doc, "bundle")
            self.assertEqual(out["verify"]["status"], "VERIFIED")
            root = os.path.join(VAULT, out["rel_dir"])
            for rel in ("audit/rejected_claims.json", "audit/validation_trace.json",
                        "audit/answer_audit_diagnostics.json"):
                p = os.path.join(root, rel)
                self.assertTrue(os.path.isfile(p), "Audit Bundle 缺 %s" % rel)
            with open(os.path.join(root, "audit/rejected_claims.json"),
                      encoding="utf-8") as fh:
                rej = json.load(fh)
            self.assertEqual(len(rej), self.audit["rejected_claims_n"])
            with open(os.path.join(root, "manifest.json"), encoding="utf-8") as fh:
                man = json.load(fh)
            self.assertTrue((man.get("export_options") or {}).get("include_audit"))
            self.assertTrue(man.get("bundle_hash"))

    def test_03_obsidian_standard_note_has_no_validator_trace(self):
        with _isolated_roots("obsidian") as base:
            v = OV.Vault()
            res = OA.save_research(self.view, vault=v)
            self.assertTrue(res.get("ok"), res)
            self.assertIsNone(res.get("audit_artifact"),
                              "标准笔记不应自动写审计工件")
            txt = v.read(res["research_note"]) or ""
            for m in DIAG_MARKERS:
                self.assertNotIn(m, txt, "Obsidian 标准笔记含内部诊断：%s" % m)
            self.assertTrue(txt.strip())

    def test_04_obsidian_audit_artifact_is_opt_in_and_complete(self):
        with _isolated_roots("obsidian_audit") as base:
            v = OV.Vault()
            res = OA.save_research(self.view, vault=v, include_audit=True)
            self.assertTrue(res.get("ok"), res)
            rel = res.get("audit_artifact")
            self.assertTrue(rel and v.exists(rel), "缺 audit artifact：%s" % rel)
            doc = json.loads(v.read(rel))
            self.assertEqual(doc["rejected_claims_n"], self.audit["rejected_claims_n"])
            # 审计工件里应有拒绝理由；标准笔记里不应有
            note = v.read(res["research_note"]) or ""
            self.assertNotIn("NOT_ENTAILED", note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
