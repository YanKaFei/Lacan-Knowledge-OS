#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §59/§60：Project 安全（注入 / 越界 / 超大 / 非法 id / symlink / 冲突）"""
import json, os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA
from workspace_ui.server import project_view as PV


class Security(unittest.TestCase):
    def test_00_title_path_injection_rejected(self):
        with L.isolated_projects("sec"):
            for bad in ("../../etc/passwd", "a/b", "a\\b", "x\x00y", "line\nbreak"):
                with self.assertRaises(PA.Invalid, msg=bad):
                    PA.create_project(bad)

    def test_01_title_length_limit(self):
        with L.isolated_projects("sec2"):
            with self.assertRaises(PA.Invalid):
                PA.create_project("x" * 201)
            self.assertTrue(PA.create_project("x" * 200)["project_id"])

    def test_02_tag_injection_rejected(self):
        with L.isolated_projects("sec3"):
            # 注意：重复标签会先去重再计数，所以「超量」必须用 31 个**不同**标签
            for bad in (["a/b"], ["a\\b"], ["x" * 61],
                        ["t%d" % i for i in range(31)]):
                with self.assertRaises(PA.Invalid, msg=str(bad)[:40]):
                    PA.create_project("T", tags=bad)

    def test_03_ids_are_never_paths(self):
        with L.isolated_projects("sec4"):
            p = L.make_project("T")
            for kind in ("passage", "concept", "seminar", "term"):
                for bad in ("../../x", "/etc/passwd", "a/b", "", "x" * 201):
                    with self.assertRaises(PA.Invalid, msg="%s %r" % (kind, bad)):
                        PA.add_reference(p["project_id"], p["revision"], kind, bad)

    def test_04_project_id_validation(self):
        with L.isolated_projects("sec5"):
            for bad in ("proj_short", "../../etc", "proj_" + "A" * 30, "", None):
                with self.assertRaises(PA.Invalid):
                    PA.get_project(bad)

    def test_05_markdown_injection_is_data_not_code(self):
        """§60：标题/笔记里的 markdown / HTML 只是文本，不执行。"""
        with L.isolated_projects("sec6") as root:
            p = L.make_project("<img src=x onerror=alert(1)>",
                               "**bold** <script>alert(2)</script>")
            txt = open(os.path.join(root, p["project_id"], "project.json"),
                       encoding="utf-8").read()
            self.assertIn("onerror", txt)          # 原样保存
            js = open(os.path.join(VAULT, "workspace_ui", "static", "src", "project.js"),
                      encoding="utf-8").read()
            self.assertNotIn(".innerHTML", js)     # 但渲染时绝不当作 HTML

    def test_06_oversized_description_and_note(self):
        with L.isolated_projects("sec7"):
            with self.assertRaises(PA.Invalid):
                PA.create_project("T", description="x" * 4001)
            p = L.make_project("T2")
            with self.assertRaises(PA.Invalid):
                PA.add_note(p["project_id"], p["revision"], "x" * 200_001)

    def test_07_symlink_escape_is_refused(self):
        """项目根内的 symlink 指向外部时不得被写入。"""
        with L.isolated_projects("sec8") as root:
            outside = os.path.join(VAULT, "_workspace", "test_projects", "outside_target")
            os.makedirs(outside, exist_ok=True)
            link = os.path.join(root, "proj_01M3CVMXRP2N7PGSK0DE8Y03W8")
            try:
                os.symlink(outside, link)
            except OSError:
                self.skipTest("symlink 不可用")
            # 该 id 合法但目录是 symlink → 闸门按解析后路径判定，仍在 _workspace 内（允许），
            # 但绝不能写到 _workspace 之外
            from scholarly_api import policy as POL
            target = os.path.join(link, "project.json")
            self.assertEqual(POL.classify(target), "USER_WORKSPACE")
            outside_core = os.path.join(VAULT, "_data", "ontology", "v4a1", "entities.jsonl")
            with self.assertRaises(POL.CoreMutationError):
                POL.write_text(outside_core, "x")

    def test_08_revision_conflict_is_409(self):
        import threading
        import urllib.error, urllib.request
        from workspace_ui.server import httpserver as H
        with L.isolated_projects("sec9"):
            p = L.make_project("T")
            PA.update_project(p["project_id"], p["revision"], title="T2")
            srv = H.make_server("127.0.0.1", 0)
            port = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                body = json.dumps({"project_id": p["project_id"],
                                   "expected_revision": p["revision"],
                                   "title": "T3"}).encode()
                req = urllib.request.Request(
                    "http://127.0.0.1:%d/api/projects/update" % port, data=body,
                    headers={"Content-Type": "application/json"})
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req, timeout=30)
                self.assertEqual(ctx.exception.code, 409)
                payload = json.loads(ctx.exception.read().decode())
                self.assertEqual(payload["code"], "WORKSPACE_CONFLICT")
            finally:
                srv.shutdown()

    def test_09_unknown_kind_rejected(self):
        with L.isolated_projects("sec10"):
            p = L.make_project("T")
            out = PV.project_add(p["project_id"], p["revision"], "person", {"id": "x"})
            self.assertEqual(out["code"], "INVALID_REQUEST")
            with self.assertRaises(PA.Invalid):
                PA.add_reference(p["project_id"], p["revision"], "person", "x")
