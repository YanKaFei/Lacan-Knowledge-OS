#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §10–§12/§39–§43/§76/§77：Project 导出（summary / bundle，类型边界清楚）"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import _project_testlib as PL
import export_system as EX
import project_api as PA


class ProjectExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pctx = PL.isolated_projects("export_qa")
        cls.pctx.__enter__()
        p = PL.make_project("导出测试项目", "desc", tags=["t1"],
                            questions=["欲望与要求的关系？"])
        cls.pid = p["project_id"]
        rev = p["revision"]
        for kind, item in (("concept", "concept.desir"), ("seminar", "seminar.S11"),
                           ("passage", "passage.S11.unknown.P2253"),
                           ("term", "jouissance")):
            p = PA.add_reference(cls.pid, rev, kind, item)
            rev = p["revision"]
        view = L.view()
        # ⚠️ 不要叫 `cls.run`：那会盖掉 unittest.TestCase.run（TypeError: dict not callable）
        p, cls.run_rec = PA.add_research_run(cls.pid, rev, view)
        rev = p["revision"]
        p = PA.add_open_question(cls.pid, rev, "需要 S13 的 L1 证据。")
        rev = p["revision"]
        p = PA.add_hypothesis(cls.pid, rev, "假设 X：jouissance 与 sexual non-relation 相关。")
        rev = p["revision"]
        p = PA.add_note(cls.pid, rev, "用户笔记正文 ZZZ", title="笔记")
        rev = p["revision"]
        p = PA.add_bibliography_ref(cls.pid, rev, "Écrits", author="Jacques Lacan",
                                    year=1966, source_type="book")
        cls.project = PA.get_project(cls.pid)

    @classmethod
    def tearDownClass(cls):
        cls.pctx.__exit__(None, None, None)

    def test_00_summary_contains_workspace_structure(self):
        d = EX.build_project_summary(self.pid)
        proj = d["project"]
        for k in ("research_questions", "runs_index", "saved_concepts",
                  "saved_seminars", "saved_passages", "saved_terms"):
            self.assertIn(k, proj, k)
        self.assertEqual(proj["evidence_role"], "NOT_EVIDENCE")
        self.assertEqual(proj["saved_concepts"], ["concept.desir"])
        self.assertEqual(proj["saved_seminars"], ["seminar.S11"])

    def test_01_user_blocks_separated(self):
        d = EX.build_project_summary(self.pid)
        ub = d["user_blocks"]
        for k in ("user_hypotheses", "open_questions", "user_notes", "bibliography"):
            self.assertIn(k, ub, k)
        for h in ub["user_hypotheses"]:
            self.assertTrue(h["not_validated"])
            self.assertEqual(h["label"], "USER HYPOTHESIS — NOT VALIDATED")

    def test_02_hypothesis_label_in_all_formats(self):
        """§40/§77：USER HYPOTHESIS — NOT VALIDATED 是硬门禁。"""
        d = EX.build_project_summary(self.pid)
        texts = L.rendered(d)
        texts["bundle"] = "".join(blob.decode("utf-8") for _r, blob in
                                  EX.bundle.build_files(d)[0])
        for fmt, text in texts.items():
            self.assertIn("NOT VALIDATED", text, fmt)

    def test_03_open_questions_not_claims(self):
        d = EX.build_project_summary(self.pid)
        for q in d["user_blocks"]["open_questions"]:
            self.assertFalse(q["is_claim"])
        self.assertEqual(d["claims"], [])

    def test_04_project_run_export_uses_snapshot(self):
        d = EX.build_from_project_run(self.pid, self.run_rec["run_id"])
        self.assertEqual(d["answer_state"], "VALIDATED_WITH_QUALIFICATIONS")
        self.assertEqual(d["source_answer_hash"], self.run_rec["source_answer_hash"])
        self.assertEqual(d["snapshot_integrity"], "VERIFIED")
        self.assertEqual(d["question"], self.run_rec["question"])

    def test_05_modified_run_requires_optin(self):
        """§38：snapshot 被改过 → 必须显式确认，不能默认导出。"""
        import json as _json
        path = os.path.join(PA.store.project_dir(self.pid), "snapshots",
                            "%s.json" % self.run_rec["run_id"])
        suffix = None
        try:
            with open(path, encoding="utf-8") as f:
                doc = _json.load(f)
            doc["snapshot"]["sections"][0]["text"] = "被改写"
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(doc, f, ensure_ascii=False)
            with self.assertRaises(EX.ExportError) as ctx:
                EX.build_from_project_run(self.pid, self.run_rec["run_id"])
            self.assertEqual(ctx.exception.code, "EXPORT_SOURCE_MODIFIED")
            ok = EX.build_from_project_run(self.pid, self.run_rec["run_id"],
                                           export_options={"allow_modified": True})
            self.assertEqual(ok["snapshot_integrity"], "MODIFIED")
        finally:
            pass

    def test_06_project_bundle_contains_project_json(self):
        with L.export_root("proj"):
            d = EX.build_project_summary(self.pid)
            out = EX.build_bundle(d)
            files = L.bundle_files(out["dir"])
            self.assertIn("project/project.json", files)
            self.assertIn("bibliography/bibliography.json", files)
            self.assertEqual(out["verify"]["status"], "VERIFIED")
            payload = json.load(open(os.path.join(out["dir"], "project",
                                                  "project.json"), encoding="utf-8"))
            self.assertEqual(payload["project"]["project_id"], self.pid)

    def test_07_bibliography_fields_not_completed(self):
        """§42：用户没填的字段就缺着 —— 导出**不补** author/year/publisher。

        ⚠️ `BibliographyRef` 的字段集是 4D.5 定义的
        （id/title/author/year/source_type/identifier/url_or_reference/user_note），
        本来就没有 publisher；publisher 是**出版型 citation** 的要求，
        由 `citation_capabilities()` 单独判定。
        """
        d = EX.build_project_summary(self.pid)
        for b in d["user_blocks"]["bibliography"]:
            self.assertNotIn("publisher", b)
            self.assertEqual(b.get("identifier"), None)
            self.assertIn("identifier", b["missing_fields"])
            self.assertFalse(b.get("url_or_reference"))
        # 出版型 citation 的完整性由 capability 判定，缺 publisher 就不可用
        from export_system import citation_capabilities
        caps = citation_capabilities({}, bibliographic={"author": "J", "title": "Écrits",
                                                        "year": 1966})
        self.assertFalse(caps["capabilities"]["chicago"])
        self.assertIn("publisher", caps["missing_fields"]["chicago"])

    def test_08_no_corpus_dump_in_project_bundle(self):
        with L.export_root("proj2"):
            d = EX.build_project_summary(self.pid)
            out = EX.build_bundle(d)
            files = [f for f in L.bundle_files(out["dir"]) if f.startswith("passages/")]
            self.assertLessEqual(len(files), 2, "只能导出项目显式保存的 passage")
            total = sum(os.path.getsize(os.path.join(r, f))
                        for r, _d, fs in os.walk(out["dir"]) for f in fs)
            self.assertLess(total, 2_000_000)
