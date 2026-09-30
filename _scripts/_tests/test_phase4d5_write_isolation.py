#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §67：Project 操作前后 canonical 工件逐字节不变"""
import hashlib, os, subprocess, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA
from workspace_ui.server import project_view as PV

TARGETS = [
    "_data/ontology/v4a1/entities.jsonl",
    "_data/ontology/v4a1/relations.jsonl",
    "_data/ontology/v4a1/term_mappings.jsonl",
    "_data/passage_store/concepts.jsonl",
    "_data/passage_store/passages.jsonl",
    "_data/passage_store/witnesses.jsonl",
    "_data/core_freeze/scholarly_core_freeze_v1.json",
    "_data/core_freeze/freeze_lineage.json",
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
    def test_00_canonical_untouched_by_project_lifecycle(self):
        before = {rel: sha(rel) for rel in TARGETS}
        view = L.answer(L.Q_GAZE)
        with L.isolated_projects("iso"):
            p = L.make_project("ISO", tags=["t"], questions=["q?"])
            pid = p["project_id"]
            p = PA.add_reference(pid, p["revision"], "concept", L.C_DESIR)
            p = PA.add_reference(pid, p["revision"], "passage", L.P_L1)
            p, rec = PA.add_research_run(pid, p["revision"], view)
            # ⚠️ 每次 mutation 都会 +1：必须把新的 revision 串下去，
            #    否则 revision guard 会（正确地）报 WORKSPACE_CONFLICT。
            p = PA.add_note(pid, p["revision"], "note")
            p = PA.add_open_question(pid, p["revision"], "oq")
            p = PA.add_hypothesis(pid, p["revision"], "hyp")
            p = PA.add_bibliography_ref(pid, p["revision"], "Écrits", year=1966)
            PA.verify_project_runs(pid)
            PA.compare_runs(pid, rec["run_id"], rec["run_id"])
            PV.project_detail(pid)
            PV.export_manifest(pid)
            PA.archive_project(pid, PA.get_project(pid)["revision"])  # 读最新再写
        after = {rel: sha(rel) for rel in TARGETS}
        self.assertEqual(before, after, "canonical 工件被 Project 操作改动")

    def test_01_core_freeze_still_verifies(self):
        r = subprocess.run([sys.executable,
                            os.path.join(VAULT, "_scripts", "_tools", "core_freeze.py"),
                            "--verify", "--quiet"], capture_output=True, text=True,
                           cwd=VAULT)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-300:])

    def test_02_policy_blocks_core_writes(self):
        from scholarly_api import policy as POL
        self.assertEqual(POL.classify("_workspace/projects/x/project.json"), "USER_WORKSPACE")
        for target in ("_data/ontology/v4a1/entities.jsonl",
                       "_data/eval/gold_v2/tasks.jsonl",
                       "_data/core_freeze/scholarly_core_freeze_v1.json"):
            with self.assertRaises(POL.CoreMutationError):
                POL.write_text(target, "x")

    def test_03_project_api_cannot_import_core(self):
        """§65：不得 import synthesis / validator / retrieval internals。"""
        import ast
        root = os.path.join(VAULT, "project_api")
        banned = ("synthesis_contract", "synthesis_claims", "synthesis_render",
                  "synthesis_adapters", "synthesis_entailment", "synthesis_validation",
                  "research_execution", "research_contract", "eval_integrity",
                  "knowledge_api", "hybrid_retrieve", "lacan_search")
        for fn in sorted(os.listdir(root)):
            if not fn.endswith(".py"):
                continue
            tree = ast.parse(open(os.path.join(root, fn), encoding="utf-8").read())
            mods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module.split(".")[0])
            self.assertEqual(mods & set(banned), set(),
                             "%s import 了禁止模块" % fn)

    def test_04_no_git_commits_in_tests(self):
        import re
        root = os.path.join(VAULT, "_scripts", "_tests")
        for fn in sorted(os.listdir(root)):
            if not fn.startswith("test_phase4d5"):
                continue
            src = open(os.path.join(root, fn), encoding="utf-8").read()
            self.assertIsNone(re.search(r"git\s+(add|commit)", src), fn)

    def test_05_project_writes_go_through_policy(self):
        """所有落盘必须经 policy 闸门（否则 _workspace 之外也能写）。"""
        src = open(os.path.join(VAULT, "project_api", "store.py"), encoding="utf-8").read()
        self.assertIn("POL.assert_writable", src)
        ops = open(os.path.join(VAULT, "project_api", "items.py"), encoding="utf-8").read()
        self.assertIn("S.POL.assert_writable", ops)
