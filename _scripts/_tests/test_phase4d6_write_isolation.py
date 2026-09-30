#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §62/§63/§45/§46/§49：导出不碰核心、不改 workspace、路径受限、可审计"""
import ast, hashlib, json, os, re, subprocess, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX

TARGETS = [
    "_data/ontology/v4a1/entities.jsonl",
    "_data/ontology/v4a1/relations.jsonl",
    "_data/passage_store/concepts.jsonl",
    "_data/passage_store/passages.jsonl",
    "_data/core_freeze/scholarly_core_freeze_v1.json",
    "_data/core_freeze/freeze_lineage.json",
    "_data/eval/research_human_review_round2.jsonl",
    "_data/eval/scholarship_readiness_none.jsonl",
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


class ExportWriteIsolation(unittest.TestCase):
    def test_00_canonical_untouched_by_exports(self):
        before = {rel: sha(rel) for rel in TARGETS}
        view = L.view()
        with L.export_root("iso"):
            for fmt in ("markdown", "json", "html", "bundle"):
                d = EX.build_from_answer(view)
                if fmt == "bundle":
                    EX.build_bundle(d, include_context=2)
                else:
                    EX.policy.write_file(
                        os.path.join(EX.export_root(),
                                     "%s.%s" % (d["export_id"], fmt)), "x")
            EX.build_from_passage(L.P_L2)
            EX.build_from_answer(L.abstention_view())
        self.assertEqual(before, {rel: sha(rel) for rel in TARGETS})

    def test_01_core_freeze_still_verifies(self):
        r = subprocess.run([sys.executable,
                            os.path.join(VAULT, "_scripts", "_tools", "core_freeze.py"),
                            "--verify", "--quiet"], capture_output=True, text=True,
                           cwd=VAULT)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-200:])

    def test_02_workspace_objects_unchanged(self):
        """§63：导出不得改 project revision / run / Obsidian note / history 快照。"""
        import _project_testlib as PL
        import project_api as PA
        with PL.isolated_projects("exiso"):
            p = PL.make_project("ISO")
            p, rec = PA.add_research_run(p["project_id"], p["revision"], L.view())
            rev_before = PA.get_project(p["project_id"])["revision"]
            with L.export_root("iso2"):
                EX.build_from_project_run(p["project_id"], rec["run_id"])
                EX.build_project_summary(p["project_id"])
            got = PA.get_project(p["project_id"])
            self.assertEqual(got["revision"], rev_before)
            self.assertEqual(len(got["research_runs"]), 1)
            self.assertEqual(PA.verify_project_runs(p["project_id"])["overall"],
                             "VERIFIED")

    def test_03_export_root_is_workspace(self):
        from scholarly_api import policy as POL
        self.assertEqual(POL.classify(os.path.join(EX.policy.EXPORT_ROOT_REL, "x.md")),
                         "USER_WORKSPACE")
        self.assertEqual(EX.policy.EXPORT_ROOTS["default"], EX.policy.EXPORT_ROOT_REL)

    def test_04_arbitrary_path_rejected(self):
        """§46：不接受用户给的任意路径（只能给已登记的 root 名）。"""
        with self.assertRaises(EX.ExportError) as ctx:
            EX.policy.export_root("/tmp/anywhere")
        self.assertEqual(ctx.exception.code, "EXPORT_POLICY_DENIED")
        with self.assertRaises(EX.ExportError):
            EX.policy.resolve_export_path("../../etc/passwd")

    def test_05_core_paths_refused_by_policy(self):
        from scholarly_api import policy as POL
        for target in ("_data/ontology/v4a1/entities.jsonl",
                       "_data/eval/gold_v2/x.jsonl",
                       "_data/core_freeze/scholarly_core_freeze_v1.json"):
            with self.assertRaises(POL.CoreMutationError):
                POL.write_text(target, "x")

    def test_06_audit_records_metadata_only(self):
        """§49：审计只记元数据，不记 scholarly 全文。"""
        with L.export_root("audit"):
            d = L.doc()
            EX.build_bundle(d)
            recs = EX.read_audit()
            self.assertTrue(recs)
            blob = json.dumps(recs, ensure_ascii=False)
            self.assertNotIn("claim_text", blob)
            self.assertNotIn(str(d["claims"][0]["claim_text"])[:20], blob)
            self.assertIn("export_id", recs[-1])
            self.assertIn("bundle_hash", recs[-1])

    def test_07_export_system_does_not_import_core_internals(self):
        root = os.path.join(VAULT, "export_system")
        banned = ("synthesis_contract", "synthesis_claims", "synthesis_render",
                  "synthesis_adapters", "synthesis_entailment", "synthesis_validation",
                  "research_execution", "research_contract", "eval_integrity",
                  "knowledge_api")
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
            self.assertEqual(mods & set(banned), set(), fn)

    def test_08_export_layer_never_triggers_research(self):
        root = os.path.join(VAULT, "export_system")
        for fn in sorted(os.listdir(root)):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(root, fn), encoding="utf-8").read()
            self.assertIsNone(re.search(r"\b(research|search_passages)\s*\(", src), fn)
