#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §59：Explorer 操作前后 canonical 工件逐字节不变"""
import hashlib, json, os, subprocess, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L

TARGETS = [
    "_data/ontology/v4a1/entities.jsonl",
    "_data/ontology/v4a1/relations.jsonl",
    "_data/ontology/v4a1/term_mappings.jsonl",
    "_data/passage_store/concepts.jsonl",
    "_data/passage_store/passages.jsonl",
    "_data/passage_store/witnesses.jsonl",
    "_data/passage_store/translations.jsonl",
    "_data/core_freeze/scholarly_core_freeze_v1.json",
    "_data/eval/research_human_review_round2.jsonl",
    "_data/eval/scholarly_readiness_gate_v1.json",
]


def sha(rel):
    p = os.path.join(VAULT, rel)
    if not os.path.isfile(p):
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class WriteIsolation(unittest.TestCase):
    def test_00_canonical_artifacts_untouched_by_browsing(self):
        before = {rel: sha(rel) for rel in TARGETS}
        # 覆盖四类 Explorer 的全部读路径
        L.X.concept_list(limit=5)
        L.X.concept_detail(L.C_OBJET_A)
        L.X.passage_search({"seminar": "S11", "language": "fr"})
        L.X.passage_detail(L.P_L1)
        L.X.passage_detail(L.P_L2)
        L.X.seminar_list()
        L.X.seminar_detail("S11")
        L.X.session_reading(L.S_SESSION)
        L.X.terminology_list(query="jouissance")
        L.X.terminology_detail("jouissance")
        L.X.terminology_control()
        L.X.context_window(L.P_L1, 5, 5)
        L.B.formalism_counts("seminar.S11")
        after = {rel: sha(rel) for rel in TARGETS}
        self.assertEqual(before, after, "canonical 工件被 Explorer 改动")

    def test_01_core_freeze_still_verifies(self):
        r = subprocess.run([sys.executable,
                            os.path.join(HERE, "_tools", "core_freeze.py"),
                            "--verify", "--quiet"] if False else
                           [sys.executable,
                            os.path.join(VAULT, "_scripts", "_tools", "core_freeze.py"),
                            "--verify", "--quiet"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-400:])

    def test_02_explorer_writes_only_user_workspace(self):
        """产品层能写的地方只能是 USER_WORKSPACE。"""
        from scholarly_api import policy as POL
        self.assertEqual(POL.classify("_workspace/explorer_qa/x.json"), "USER_WORKSPACE")
        for target in ("_data/ontology/v4a1/entities.jsonl",
                       "_data/passage_store/passages.jsonl",
                       "_data/core_freeze/scholarly_core_freeze_v1.json",
                       "_data/eval/gold_v2/tasks.jsonl"):
            with self.assertRaises(POL.CoreMutationError):
                POL.write_text(target, "x")

    def test_03_browse_api_has_no_write_calls(self):
        """只读层只能以读模式 open；不得有 replace/remove/write_text/makedirs。"""
        import re
        root = os.path.join(VAULT, "browse_api")
        for fn in sorted(os.listdir(root)):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(root, fn), encoding="utf-8").read()
            for pat in (r"open\([^)]*,\s*['\"][wax]", r"os\.replace", r"shutil\.",
                        r"write_text", r"os\.remove", r"os\.makedirs", r"mkdir"):
                self.assertIsNone(re.search(pat, src),
                                  "%s 出现写操作：%s" % (fn, pat))
            # 读取是允许的，但必须显式读模式或纯读
            if "open(" in src:
                self.assertIn('encoding="utf-8"', src)

    def test_04_head_unchanged_guard_is_visible_to_suites(self):
        """HEAD 由 run_all_tests.sh 的 §23 guard 统一守；这里确认测试不自造提交。"""
        import re
        root = os.path.join(VAULT, "_scripts", "_tests")
        for fn in sorted(os.listdir(root)):
            if not fn.startswith("test_phase4d4"):
                continue
            src = open(os.path.join(root, fn), encoding="utf-8").read()
            self.assertIsNone(re.search(r"git\s+(add|commit)", src), fn)
