#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §4/§5/§22：Vault 检测与路径策略。"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L
from obsidian_adapter import vault as V

class VaultDetection(unittest.TestCase):
    def test_00_detects_existing_project_vault(self):
        d = V.detect()
        self.assertTrue(d["is_obsidian_vault"], "应检测到已有 .obsidian（复用而非新建）")
        self.assertIn("00_System", d["canonical_partitions_present"])
        self.assertIn("04_Concepts", d["canonical_partitions_present"])

    def test_01_default_root_inside_workspace(self):
        v = V.Vault()
        self.assertTrue(v.is_project_default)
        self.assertIn(os.path.join("_workspace", "obsidian_vault"), v.root)

    def test_02_layout_has_three_artifacts_plus_seminar(self):
        for k in ("research", "passages", "concepts", "seminars", "system"):
            self.assertIn(k, V.LAYOUT)

    def test_03_env_override_honoured(self):
        os.environ["OBSIDIAN_VAULT_PATH"] = os.path.join(L.VAULT, "_workspace", "ext_vault")
        try:
            v = V.Vault()
            self.assertFalse(v.is_project_default)
            self.assertTrue(v.root.endswith(os.path.join("_workspace", "ext_vault")))
        finally:
            os.environ.pop("OBSIDIAN_VAULT_PATH", None)

    def test_04_path_policy_rejects_escape(self):
        v = V.Vault(os.path.join("_workspace", "test_vaults", "policy"))
        for bad in ("../x.md", "/etc/passwd", "Research/../../x.md", "~/x.md", ""):
            with self.assertRaises(V.VaultError, msg=bad):
                v.resolve(bad)

    def test_05_no_arbitrary_destination_api(self):
        """接口只接受 note_type/title/id —— 没有接受任意路径的参数。"""
        import inspect
        from obsidian_adapter import adapter as A
        for fn in (A.save_research, A.save_passage, A.ensure_concept_note,
                   A.ensure_seminar_note):
            params = list(inspect.signature(fn).parameters)
            for bad in ("path", "dest", "destination", "target", "filename"):
                self.assertNotIn(bad, params, "%s 不应接受 %s" % (fn.__name__, bad))
