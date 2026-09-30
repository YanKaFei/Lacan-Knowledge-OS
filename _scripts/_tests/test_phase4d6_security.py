#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §69：导出安全（path traversal / zip slip / 恶意标题 / 注入 / 超大 / 非法 id）"""
import json, os, sys, unittest, zipfile
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class ExportSecurity(unittest.TestCase):
    def test_00_path_traversal_in_verify_refused(self):
        # 注意：macOS/POSIX 下反斜杠不是分隔符，所以只测真正的路径穿越形态
        for bad in ("../../etc/passwd", "/etc/passwd", "a/../../b", "a/b/../../../c"):
            with self.assertRaises(EX.ExportError) as ctx:
                EX.policy.resolve_export_path(bad)
            self.assertEqual(ctx.exception.code, "EXPORT_POLICY_DENIED")

    def test_01_safe_name_sanitises(self):
        self.assertNotIn("/", EX.safe_name("../../etc/passwd"))
        self.assertNotIn("..", EX.safe_name("....//x"))
        self.assertLessEqual(len(EX.safe_name("x" * 500)), 120)
        self.assertTrue(EX.safe_name("正常标题 2000"))

    def test_02_zip_slip_refused_on_extract(self):
        with L.export_root("zip") as root:
            target = os.path.join(root, "evil.zip")
            with zipfile.ZipFile(target, "w") as z:
                z.writestr("../escape.txt", "x")
            with self.assertRaises(EX.ExportError):
                EX.extract_zip(target, os.path.join(root, "out"))
            abs_zip = os.path.join(root, "evil2.zip")
            with zipfile.ZipFile(abs_zip, "w") as z:
                z.writestr("/abs.txt", "x")
            with self.assertRaises(EX.ExportError):
                EX.extract_zip(abs_zip, os.path.join(root, "out2"))

    def test_03_malicious_title_in_filename(self):
        d = L.doc()
        d["title"] = "../../evil: *title*?"
        with L.export_root("maltitle"):
            out = EX.build_bundle(d)
            self.assertTrue(out["dir"].startswith(EX.export_root()))
            self.assertNotIn("..", os.path.basename(out["dir"]))
            self.assertNotIn("/", os.path.basename(out["dir"]))

    def test_04_html_injection_escaped(self):
        d = L.doc()
        d["question"] = "<script>alert(1)</script>"
        d["sections"] = [{"label": "x", "text": "<img src=x onerror=alert(2)>"}]
        html = EX.html_export.render(d)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x", html)

    def test_05_markdown_frontmatter_injection(self):
        d = L.doc()
        d["title"] = "t\n---\nmalicious: yes"
        md = EX.markdown.render(d)
        from obsidian_adapter.frontmatter import parse_frontmatter
        meta, _ = parse_frontmatter(md)
        self.assertNotIn("malicious", meta)

    def test_06_malicious_bibliography_field(self):
        d = L.doc()
        d["user_blocks"] = {"bibliography": [
            {"title": "x\n---\nstatus: hacked", "author": "<script>a</script>"}]}
        md = EX.markdown.render(d)
        html = EX.html_export.render(d)
        self.assertNotIn("<script>a</script>", html)
        from obsidian_adapter.frontmatter import parse_frontmatter
        meta, _ = parse_frontmatter(md)
        self.assertNotIn("status", meta)

    def test_07_oversized_export_bounded(self):
        d = L.doc()
        # 用 project.saved_passages 造出「600 个待 materialize 的 passage」，
        # 这是 collect_passage_ids 真正读取的字段（不需要伪造完整 citation record）
        d2 = dict(d, project={"saved_passages": ["passage.S11.unknown.P%04d" % i
                                                 for i in range(600)]})
        self.assertEqual(EX.bundle.MAX_PASSAGES, 500)
        with self.assertRaises(EX.ExportError) as ctx:
            EX.bundle.build_files(d2)
        self.assertEqual(ctx.exception.code, "EXPORT_POLICY_DENIED")

    def test_08_invalid_source_id(self):
        with self.assertRaises(EX.ExportError) as ctx:
            EX.build_from_passage("../../etc/passwd")
        self.assertEqual(ctx.exception.code, "EXPORT_SOURCE_NOT_FOUND")
        with self.assertRaises(EX.ExportError):
            EX.build_from_project_run("not-a-project", "no-run")

    def test_09_broken_symlink_in_source(self):
        """passthrough：broken symlink 不应让导出崩掉，而是 fail closed。"""
        with L.export_root("sym") as root:
            link = os.path.join(root, "dangling")
            try:
                os.symlink(os.path.join(root, "missing-target"), link)
            except OSError:
                self.skipTest("symlink 不可用")
            v = EX.verify_bundle(link)
            self.assertIn(v["status"], ("BROKEN", "MODIFIED"))

    def test_10_include_context_validated(self):
        d = L.doc()
        with L.export_root("ctx"):
            with self.assertRaises(EX.ExportError) as ctx:
                EX.build_bundle(d, include_context=99)
            self.assertEqual(ctx.exception.code, "EXPORT_POLICY_DENIED")

    def test_11_unexpected_document_field_rejected(self):
        d = L.doc()
        d["evil"] = {"x": 1}
        with self.assertRaises(EX.ExportError) as ctx:
            EX.json_export.render(d)
        self.assertEqual(ctx.exception.code, "SCHEMA_VALIDATION_FAILED")
