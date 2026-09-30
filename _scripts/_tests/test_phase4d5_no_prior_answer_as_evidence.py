#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.5 §13/§42/§43/§44/§74：Project 内容永不进入 EvidencePacket"""
import inspect, json, os, re, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _project_testlib as L
import project_api as PA
from workspace_ui.server import project_view as PV


class NoPriorAnswerAsEvidence(unittest.TestCase):
    def test_00_project_layer_never_touches_evidence_paths(self):
        """检查**代码**而不是散文：docstring 里提到 EvidencePacket 是说明，不是调用。

        实测教训：直接 `assertNotIn("EvidencePacket", src)` 会被自己的文档字符串绊倒。
        这里用 AST 只看 import 与真实调用。
        """
        import ast
        root = os.path.join(VAULT, "project_api")
        banned_imports = ("knowledge_api", "research_answer", "research_contract",
                          "research_execution", "synthesis_contract", "synthesis_claims",
                          "synthesis_render", "synthesis_adapters", "synthesis_entailment",
                          "synthesis_validation", "eval_integrity", "hybrid_retrieve",
                          "lacan_search")
        banned_calls = ("evidence_packet", "search_passages", "run_validation_pipeline",
                        "build_evidence", "validate_claims")
        for fn in sorted(os.listdir(root)):
            if not fn.endswith(".py"):
                continue
            tree = ast.parse(open(os.path.join(root, fn), encoding="utf-8").read())
            mods, calls = set(), set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module.split(".")[0])
                elif isinstance(node, ast.Call):
                    f = node.func
                    name = getattr(f, "id", None) or getattr(f, "attr", None)
                    if name:
                        calls.add(name)
            self.assertEqual(mods & set(banned_imports), set(),
                             "%s import 了核心内部：%s" % (fn, mods & set(banned_imports)))
            self.assertEqual(calls & set(banned_calls), set(),
                             "%s 调用了 evidence 路径：%s" % (fn, calls & set(banned_calls)))

    def test_01_project_api_imports_only_stable_product_interfaces(self):
        """§65：可调用 scholarly_api / browse_api / obsidian_adapter；不得进校验/检索内部。"""
        root = os.path.join(VAULT, "project_api")
        banned = ("synthesis_", "eval_integrity", "research_execution",
                  "research_contract", "retrieval", "hybrid_retrieve",
                  "lacan_search", "knowledge_api")
        for fn in sorted(os.listdir(root)):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(root, fn), encoding="utf-8").read()
            for mod in banned:
                self.assertIsNone(
                    re.search(r"^\s*(import|from)\s+\S*%s" % re.escape(mod), src, re.M),
                    "%s 不得 import %s" % (fn, mod))

    def test_02_run_storage_does_not_call_mcp(self):
        """存 run 只是拷贝视图：函数体里不得出现研究/MCP 调用（只看调用，不看注释）。"""
        import ast
        tree = ast.parse(inspect.getsource(PA.add_research_run))
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = getattr(f, "id", None) or getattr(f, "attr", None)
                if name:
                    calls.add(name)
        for bad in ("research", "search_passages", "call_tool", "run_validation_pipeline"):
            self.assertNotIn(bad, calls, "add_research_run 不应调用 %s：%s" % (bad, sorted(calls)))
        # 只允许做「写快照 + 更新 project.json」这类工作区操作
        self.assertIn("mutate", calls)
        self.assertIn("_atomic_write_json", calls)

    def test_03_context_for_agent_is_marked_not_evidence(self):
        view = L.answer(L.Q_GAZE)
        with L.isolated_projects("noev"):
            p = L.make_project("N")
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
            ctx = PA.context_for_agent(p["project_id"], selected_run_ids=[rec["run_id"]],
                                       include_current_question="继续上一题")
            self.assertEqual(ctx["evidence_role"], "NOT_EVIDENCE")
            self.assertIn("never an EvidencePacket member", ctx["note"])
            self.assertIn("question interpretation", ctx["note"])

    def test_04_context_budget_is_selective(self):
        """§42：只能选择性读取；不得把整个项目历史塞进 prompt。"""
        view = L.answer(L.Q_GAZE)
        with L.isolated_projects("noev2"):
            p = L.make_project("N")
            p = PA.add_note(p["project_id"], p["revision"], "笔记一", title="n1")
            p = PA.add_note(p["project_id"], p["revision"], "笔记二", title="n2")
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
            ctx = PA.context_for_agent(p["project_id"])
            self.assertEqual(ctx["selected_notes"], [], "默认不塞任何笔记")
            self.assertEqual(ctx["selected_runs"], [], "默认不塞任何历史 run")
            ctx2 = PA.context_for_agent(p["project_id"],
                                        selected_note_ids=[p["notes"][0]["note_id"]])
            self.assertEqual(len(ctx2["selected_notes"]), 1)
            self.assertNotIn("research_runs", ctx2, "上下文里没有整包历史")

    def test_05_research_from_project_goes_through_mcp_core(self):
        """§12：Project 内研究仍是新 ResearchRequest → MCP → 冻结核心。"""
        with L.isolated_projects("noev3"):
            p = L.make_project("N")
            out = PV.project_research(p["project_id"], p["revision"], L.Q_GAZE,
                                      provider="mock", store_run=False)
            self.assertEqual(out["kind"], "project_research")
            self.assertIn(out["answer_state"],
                          ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "ABSTAINED"))
            self.assertEqual(out["project_context_role"],
                             "question interpretation only — NOT evidence")
            view = out["view"]
            self.assertEqual(view["kind"], "answer")
            self.assertTrue(view["citations"], "证据必须来自 corpus")

    def test_06_citations_come_from_canonical_corpus(self):
        """§44：run 的每一条 citation 都必须指向**真实存在的语料段落**，
        且 project.json 里不得出现任何自造的 evidence 字段。"""
        import browse_api as B
        view = L.answer(L.Q_GAZE)
        with L.isolated_projects("noev4"):
            p = L.make_project("N")
            p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
            run = PA.get_run(p["project_id"], rec["run_id"])
            self.assertTrue(run["citation_ids"])
            for pid in run["citation_ids"]:
                self.assertIsNotNone(B.get_passage_view(pid),
                                     "citation 必须来自 corpus：%s" % pid)
            doc = PA.read_project(p["project_id"])
            self.assertNotIn("evidence", json.dumps(doc, ensure_ascii=False).lower())
            self.assertNotIn("evidence_packet", json.dumps(doc).lower())
            # 项目里保存的 citation id 集合 == 核心答案给出的集合（不自增、不删减）
            self.assertEqual(sorted(run["citation_ids"]),
                             sorted(c["passage_id"] for c in view["citations"]))
