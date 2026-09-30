#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.3 §2/§44/§45/§46：Obsidian 写入不触碰任何 canonical 数据。"""
import hashlib, os, re, subprocess, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _obsidian_testlib as L
from scholarly_api import policy as POL

def sha(p):
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()

class WriteIsolation(unittest.TestCase):
    def test_00_save_does_not_touch_core_or_canonical(self):
        v = L.fresh_vault("isolation")
        targets = {
            "ontology": os.path.join(VAULT, "_data", "ontology", "v4a1", "entities.jsonl"),
            "relations": os.path.join(VAULT, "_data", "ontology", "v4a1", "relations.jsonl"),
            "passage_store": os.path.join(VAULT, "_data", "passage_store", "passages.jsonl"),
            "human_review": os.path.join(VAULT, "_data", "eval",
                                         "research_human_review_round2.jsonl"),
            "gate": os.path.join(VAULT, "_data", "eval",
                                 "scholarly_readiness_gate_v1.json"),
            "freeze": os.path.join(VAULT, "_data", "core_freeze",
                                   "scholarly_core_freeze_v1.json"),
        }
        before = {k: sha(p) for k, p in targets.items() if os.path.isfile(p)}
        L.save(v)
        from obsidian_adapter import adapter as A
        A.save_passage(L.P_L2, vault=v)
        after = {k: sha(p) for k, p in targets.items() if os.path.isfile(p)}
        self.assertEqual(before, after, "Obsidian 导出改动了 canonical 工件")

    def test_01_policy_refuses_core_writes(self):
        v = L.fresh_vault("isolation2")
        for rel in ("../_data/ontology/v4a1/entities.jsonl", "../../_data/core_freeze/x.json"):
            with self.assertRaises(Exception):
                v.write(rel, "x")

    def test_02_adapter_does_not_import_core(self):
        core = ("knowledge_api","research_answer","research_contract","research_execution",
                "synthesis_contract","synthesis_claims","synthesis_render",
                "synthesis_adapters","synthesis_entailment","synthesis_validation",
                "eval_integrity","core_freeze")
        d = os.path.join(VAULT, "obsidian_adapter")
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py"): continue
            src = open(os.path.join(d, fn), encoding="utf-8").read()
            for mod in core:
                self.assertIsNone(re.search(r"^\s*(import|from)\s+%s\b" % mod, src, re.M),
                                  "%s import 了核心 %s" % (fn, mod))

    def test_03_core_freeze_still_verifies_after_saves(self):
        v = L.fresh_vault("isolation3"); L.save(v)
        r = subprocess.run([sys.executable,
                            os.path.join(VAULT, "_scripts", "_tools", "core_freeze.py"),
                            "--verify", "--quiet"], capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_04_workspace_dir_is_skipped_by_scholarly_validator(self):
        """工作区 note 不得成为 canonical 知识节点（validate_vault 跳过 _workspace）。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "vv", os.path.join(VAULT, "_scripts", "_tools", "validate_vault.py"))
        vv = importlib.util.module_from_spec(spec); spec.loader.exec_module(vv)
        self.assertIn("_workspace", vv.SKIP_DIR_PATHS)
