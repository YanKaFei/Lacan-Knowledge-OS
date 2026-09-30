#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_final_daily_use_ui — Final Daily Use & Bibliography UX Hardening 产品层契约。

覆盖（§2–§10/§13–§21/§24–§32/§41/§56）：
    * Gate v1 冻结完整性与 F1–F18 结构；
    * 一键启动/停止/体检脚本与三个 .command 存在、可执行、且**不含危险 kill**；
    * 逐样式引文可用性**带原因**；Seuil 0 段落 → internal 不可用；Staferla 段落级可用；
    * candidate 永远不可引用（API 层硬门禁）；
    * 导入永远是 candidate + 跨次强去重 + 冲突 UNRESOLVED（不自动裁决）；
    * 首页/Explore/书目详情结构；三个显示不合并；
    * Obsidian 派生笔记不含 id:/type: 且用户区逐字节保留。
不启动服务器、不开浏览器（真实浏览器 QA 在 daily_use_acceptance.py 的 Gate 里）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HERE, "..", ".."))
for _p in (VAULT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bibliography as B                                                   # noqa: E402
from _i18n_testlib import assert_text_wired, key_for, messages                 # noqa: E402
from bibliography import zotero as Z                                       # noqa: E402
from workspace_ui.server import bibliography as WB                         # noqa: E402
from workspace_ui.server import viewmodel as VM                            # noqa: E402

SEUIL = "bib.witness.seuil-pdf"
STAFERLA = "bib.witness.staferla"
ZH = "bib.witness.translation-project"
CAND = "bib.doc.lacan.seminar-23"
STATIC = os.path.join(VAULT, "workspace_ui", "static")
GATE = os.path.join(VAULT, "_data", "daily_use", "daily_use_gate_v1.json")


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


class GateV1(unittest.TestCase):
    def test_gate_frozen_and_complete(self):
        self.assertTrue(os.path.isfile(GATE), "Gate v1 必须先冻结")
        g = json.loads(_read(GATE))
        self.assertEqual(g["gate_id"], "final-daily-use-gate-v1")
        ids = [i["id"] for i in g["items"]]
        self.assertEqual(ids, ["F%d" % n for n in range(1, 19)])
        self.assertEqual(g["items_n"], 18)
        self.assertTrue(all(i["blocking"] for i in g["items"]))
        payload = {k: v for k, v in g.items() if k not in ("gate_hash", "frozen_at")}
        import hashlib
        h = hashlib.sha256(json.dumps(payload, ensure_ascii=False,
                                      sort_keys=True).encode()).hexdigest()
        self.assertEqual(h, g["gate_hash"], "Gate v1 被事后改动")

    def test_acceptance_run_ids_immutable_naming(self):
        root = os.path.join(VAULT, "_data", "daily_use")
        for name in os.listdir(root):
            if name.startswith("daily_use_bibliography_acceptance_"):
                self.assertRegex(
                    name,
                    r"^daily_use_bibliography_acceptance_\d{8}T\d{6}Z_[0-9a-f]{8}$")


class RuntimeLaunchers(unittest.TestCase):
    SHELL = ("start_lacan_os.sh", "stop_lacan_os.sh", "check_lacan_os.sh")
    COMMANDS = ("Start Lacan Knowledge OS.command",
                "Stop Lacan Knowledge OS.command",
                "Check Lacan Knowledge OS.command")

    def test_scripts_and_commands_exist_and_executable(self):
        for s in self.SHELL:
            p = os.path.join(VAULT, "_scripts", "runtime", s)
            self.assertTrue(os.path.isfile(p), p)
            self.assertTrue(os.access(p, os.X_OK), "%s 必须可执行" % s)
        for c in self.COMMANDS:
            p = os.path.join(VAULT, c)
            self.assertTrue(os.path.isfile(p), p)
            self.assertTrue(os.access(p, os.X_OK), "%s 必须可执行" % c)

    def test_no_dangerous_kill(self):
        """§27：只允许杀自己记录并验证 identity 的 PID（扫描 runtime 下**全部**脚本）。"""
        rdir = os.path.join(VAULT, "_scripts", "runtime")
        files = sorted(f for f in os.listdir(rdir) if f.endswith(".sh"))
        self.assertGreaterEqual(len(files), 4)
        for s in files:
            p = os.path.join(rdir, s)
            text = _read(p)
            code = "\n".join(ln for ln in text.splitlines()
                             if not ln.lstrip().startswith("#"))
            for bad in ("killall", "pkill", "kill -f", "kill chrome", "xargs kill"):
                self.assertNotIn(bad, code, "%s 含危险 kill：%s" % (s, bad))
        stop = _read(VAULT, "_scripts", "runtime", "stop_lacan_os.sh")
        self.assertRegex(stop + _read(VAULT, "_scripts", "runtime", "lib.sh"),
                         r"ps\s+-o\s+command=|command=", "必须做 command line 身份校验")

    def test_start_does_not_rebuild_corpus_or_call_llm(self):
        text = "".join(_read(VAULT, "_scripts", "runtime", s)
                       for s in self.SHELL if os.path.isfile(
                           os.path.join(VAULT, "_scripts", "runtime", s)))
        for forbidden in ("build_full_vector_index", "build_passage_store",
                          "build_bibliography_registry", "api.zotero.org",
                          "run_synthesis", "curl http"):
            self.assertNotIn(forbidden, text,
                             "启动/停止/体检路径不得出现 %s" % forbidden)


class CitationAvailability(unittest.TestCase):
    def test_per_style_reasons_present(self):
        for bid in (SEUIL, STAFERLA, ZH):
            out = WB.citation_availability(bid)
            self.assertEqual(out["review_status"], "reviewed")
            self.assertEqual(len(out["rows"]), 7)
            for row in out["rows"]:
                if not row["available"]:
                    self.assertTrue(row["reason"],
                                    "%s/%s 不可用必须给原因" % (bid, row["style"]))

    def test_seuil_zero_passages_blocks_internal(self):
        out = WB.citation_availability(SEUIL)
        self.assertEqual(out["passage_realizations"]["total"], 0)
        self.assertEqual(out["passage_realizations"]["state"],
                         "Not linked (0 passages)")
        for style in ("internal_short", "internal_full", "provenance"):
            row = [r for r in out["rows"] if r["style"] == style][0]
            self.assertFalse(row["available"], "%s 不得假装有 passage" % style)
            self.assertIn("PassageRealization", row["reason"])
        self.assertIn("Passage Realizations = 0", out["internal_note"])

    def test_staferla_passage_level_ready_formal_unavailable(self):
        out = WB.citation_availability(STAFERLA)
        self.assertEqual(out["passage_realizations"]["total"], 166527)
        for style in ("internal_short", "internal_full", "provenance"):
            row = [r for r in out["rows"] if r["style"] == style][0]
            self.assertTrue(row["available"], style)
        for style in ("chicago", "apa", "mla", "bibtex"):
            row = [r for r in out["rows"] if r["style"] == style][0]
            self.assertFalse(row["available"], style)
            self.assertIn("Missing verified metadata", row["reason"])

    def test_no_reviewed_item_is_bibliographically_complete(self):
        """§1：reviewed ≠ 书目完整；不得有任何条目缺 metadata 却被判为可引用。"""
        for it in B.registry.items():
            caps = B.render.capability_matrix(it)
            if it.get("publisher") and it.get("publication_year"):
                continue
            for style in ("chicago", "apa", "mla", "bibtex"):
                self.assertFalse(caps.get(style),
                                 "%s 缺 metadata 却声明 %s 可用" % (
                                     it["bibliographic_id"], style))

    def test_candidate_never_citable(self):
        out = WB.citation_availability(CAND)
        self.assertTrue(out["candidate_not_citable"])
        self.assertTrue(all(r["available"] is False for r in out["rows"]))
        for style in ("internal_short", "internal_full", "provenance", "chicago",
                      "apa", "mla", "bibtex"):
            r = WB.citation(CAND, style)
            self.assertFalse(r["available"], style)
            self.assertIn("CANDIDATE_NOT_CITABLE", r["reason"])

    def test_citation_identity_is_single_renderer(self):
        """§32：同一 item+style 在任何出口 identity_hash 一致。"""
        for bid in (SEUIL, STAFERLA):
            for style in ("chicago", "bibtex"):
                a = WB.citation(bid, style)
                b = WB.citation(bid, style)
                self.assertEqual(a["identity_hash"], b["identity_hash"])


class ImportSemantics(unittest.TestCase):
    def _payload(self, year, publisher, doi):
        return json.dumps([{
            "type": "book", "title": "Probe unit-test item",
            "author": [{"family": "Probe", "given": "Unit"}],
            "issued": {"date-parts": [[year]]}, "publisher": publisher, "DOI": doi}])

    def test_always_candidate_and_cross_import_strong_duplicate(self):
        doc = self._payload(1966, "Alpha", "10.9999/unittest.dup")
        first = Z.import_file(doc, "csl-json")
        self.assertEqual(len(first["candidates"]), 1)
        self.assertEqual(first["candidates"][0]["review_status"], "candidate")
        # 跨次导入：把已存候选作为 existing 传入 → 强键命中
        again = Z.import_file(doc, "csl-json", existing=first["candidates"])
        self.assertTrue(again["duplicates"])
        self.assertEqual(again["duplicates"][0]["kind"], "EXACT_KEY")
        self.assertFalse(again["duplicates"][0]["auto_merged"])

    def test_weak_duplicate_not_merged(self):
        a = json.loads(self._payload(1966, None, None))[0]
        b = json.loads(self._payload(1966, None, None))[0]
        res = Z.import_file(json.dumps([a, b]), "csl-json")
        self.assertTrue(res["duplicates"])
        self.assertEqual(res["duplicates"][0]["kind"], "candidate_duplicate")
        self.assertFalse(res["duplicates"][0]["auto_merged"])

    def test_conflict_unresolved_not_last_write_wins(self):
        two = json.dumps([json.loads(self._payload(1966, "Alpha", "10.9999/u.conf"))[0],
                          json.loads(self._payload(1967, "Beta", "10.9999/u.conf"))[0]])
        res = Z.import_file(two, "csl-json")
        self.assertTrue(res["conflicts"])
        fields = {c["field"] for c in res["conflicts"]}
        self.assertIn("publication_year", fields)
        for c in res["conflicts"]:
            self.assertEqual(c["resolution"], "UNRESOLVED")
            self.assertFalse(c["auto_overwrite"])
            self.assertGreaterEqual(len(c["values"]), 2)

    def test_xml_unsupported(self):
        with self.assertRaises(Exception):
            Z.import_file("<xml/>", "csl-json")


class ProductPresentation(unittest.TestCase):
    def test_home_and_explore_structure(self):
        """P5D-004 后：文案断言走 i18n key（源码调用 + en/zh 双语词典），比字符串 grep 更强。"""
        home = _read(STATIC, "src", "home.js")
        for bid in ("home-research", "home-explore", "home-projects",
                    "home-bibliography", "home-open-obsidian"):
            self.assertIn(bid, home)
        for key in ("concepts", "persons", "cases", "seminars", "passages",
                    "terminology", "bibliography"):
            self.assertIn("'%s'" % key, home)
        for text in ("Corpus-grounded Scholarly Research Workspace",
                     "Explore → Research → Inspect Evidence",
                     "Bibliography → Inspect Metadata"):
            assert_text_wired(self, "home.js", text)

    def test_bibliography_detail_sections_and_three_displays(self):
        js = _read(STATIC, "src", "bibliography.js")
        for section in ("Overview", "Review Status", "Metadata Completeness",
                        "Citation Availability", "Editions", "Witnesses",
                        "Passages", "Seminars", "Projects", "Provenance"):
            assert_text_wired(self, "bibliography.js", section)
        for did in ("bib-review-status", "bib-metadata-completeness",
                    "bib-availability", "bib-passage-realizations",
                    "bib-candidate-banner", "bib-trace-incomplete"):
            self.assertIn(did, js)
        assert_text_wired(self, "bibliography.js",
                          "Reviewed does NOT mean bibliographically complete.")
        assert_text_wired(self, "bibliography.js", "SOURCE_TRACE_INCOMPLETE")
        self.assertIn("not linked", js.lower())          # §7 缺层不得隐藏

    def test_no_approve_all_entry_point(self):
        for name in ("bibliography.js", "project.js", "home.js", "app.js"):
            js = _read(STATIC, "src", name)
            self.assertNotRegex(
                js, r"['\"][^'\"]*(Approve All|Import & Approve)[^'\"]*['\"]\s*[,)]",
                "%s 不得提供 Approve All 类入口" % name)

    def test_status_counts_are_objective(self):
        st = VM.status_view({"connected": True, "core_freeze_verified": True,
                             "server": {"name": "x"}, "checked_at": "now"})
        reg = st["bibliography_registry"]
        self.assertEqual(set(("core", "mcp", "corpus", "workspace", "explorer",
                              "obsidian", "bibliography", "provider")),
                         set(st["layers"].keys()))
        self.assertEqual(reg["items"], reg["reviewed"] + reg["candidates"])
        self.assertTrue(reg["counts_are_objective"])
        blob = json.dumps(reg).lower()
        self.assertNotIn("completeness_score", blob)
        self.assertNotIn("%", blob)

    def test_provider_unavailable_does_not_disable_local(self):
        st = VM.status_view({"connected": True, "core_freeze_verified": True,
                             "server": {"name": "x"}, "checked_at": "now"})
        self.assertIn(st["layers"]["provider"], ("READY", "DEGRADED", "UNAVAILABLE"))
        self.assertFalse(st["research_disabled"])


class ObsidianDerivedNote(unittest.TestCase):
    def test_derived_note_discipline_and_user_zone(self):
        import obsidian_adapter.bibliography as OB
        from obsidian_adapter import vault as OV
        tmp = tempfile.mkdtemp(dir=os.path.join(VAULT, "_workspace", "test_vaults"))
        try:
            v = OV.Vault(root=tmp)
            OB.save_bibliography_note(STAFERLA, vault=v)
            rel = OB.note_rel(STAFERLA)
            self.assertEqual(rel, "_System/bibliography/%s.md" % STAFERLA)
            text = v.read(rel)
            self.assertNotRegex(text, r"(?m)^id:\s")
            self.assertNotRegex(text, r"(?m)^type:\s")
            self.assertIn("publisher: —", text)
            self.assertIn("publication_year: —", text)
            zone = "## My Notes\n\n\u4e2d\u6587 \u00ee\u00e9 \U0001f600\n\n"
            v.write(rel, text + zone)
            before = v.read(rel)
            OB.save_bibliography_note(STAFERLA, vault=v)
            after = v.read(rel)
            self.assertEqual(before[before.index("## My Notes"):],
                             after[after.index("## My Notes"):])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_candidate_has_no_publishable_note(self):
        import obsidian_adapter.bibliography as OB
        from obsidian_adapter import vault as OV
        tmp = tempfile.mkdtemp(dir=os.path.join(VAULT, "_workspace", "test_vaults"))
        try:
            with self.assertRaises(Exception):
                OB.save_bibliography_note(CAND, vault=OV.Vault(root=tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class DailyUseGuide(unittest.TestCase):
    SECTIONS = ("1. 一键启动", "2. Research", "3. Explore", "4. Projects",
                "5. Bibliography", "6. Zotero Import", "7. Obsidian", "8. Export",
                "9. 一键停止", "10. 故障排查")

    def test_guide_has_required_sections(self):
        p = os.path.join(VAULT, "DAILY_USE_GUIDE.md")
        self.assertTrue(os.path.isfile(p))
        text = _read(p)
        for s in self.SECTIONS:
            self.assertRegex(text, r"(?m)^#{2,3}\s*%s" % re.escape(s), s)
        for needle in ("Internal Citation", "Provenance Citation",
                       "Formal Bibliographic Citation",
                       "will not invent publisher, year, ISBN, or page numbers",
                       "_workspace/runtime/logs/"):
            self.assertIn(needle, text, needle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
