#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §42/§43：Browse API 契约（只读、无 LLM、确定性、与核心解耦）"""
import os, re, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L

ROOT = os.path.join(VAULT, "browse_api")
CORE_MODULES = ("knowledge_api", "research_answer", "research_contract",
                "research_execution", "synthesis_contract", "synthesis_claims",
                "synthesis_render", "synthesis_adapters", "synthesis_entailment",
                "synthesis_validation", "eval_integrity", "scholarly_api")


class BrowseApi(unittest.TestCase):
    def test_00_required_entries_exist(self):
        """§42：契约里的入口必须都在。"""
        need = ["list_concepts", "get_concept_view", "concept_graph",
                "list_seminars", "get_seminar_view", "list_sessions",
                "browse_passages", "get_passage_view", "session_stream",
                "list_terminology", "get_term_view", "source_trace",
                "witnesses", "realization_languages", "context"]
        missing = [n for n in need if not hasattr(L.B, n)]
        self.assertEqual(missing, [], "缺 Browse API 入口：%s" % missing)

    def test_01_no_llm_and_no_network(self):
        """§42：browse_api 不得调用 LLM，也不得联网。"""
        bad = []
        for fn in sorted(os.listdir(ROOT)):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(ROOT, fn), encoding="utf-8").read()
            for pat in (r"\bprovider\b", r"openai", r"anthropic", r"deepseek",
                        r"import\s+requests", r"urllib\.request", r"http\.client",
                        r"subprocess", r"socket"):
                if re.search(pat, src, re.I):
                    bad.append("%s: %s" % (fn, pat))
        self.assertEqual(bad, [], "browse_api 出现 LLM/网络/子进程痕迹：%s" % bad)

    def test_02_never_imports_core_internals(self):
        """§43：产品只读层不得 import 冻结核心内部实现。"""
        bad = []
        for fn in sorted(os.listdir(ROOT)):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(ROOT, fn), encoding="utf-8").read()
            for mod in CORE_MODULES:
                if re.search(r"^\s*(import|from)\s+%s\b" % re.escape(mod), src, re.M):
                    bad.append("%s -> %s" % (fn, mod))
        self.assertEqual(bad, [], "browse_api 不得 import 核心：%s" % bad)

    def test_03_readonly_sqlite_uri(self):
        """§42：SQLite 必须以 mode=ro 打开（写不进去）。"""
        src = open(os.path.join(ROOT, "store.py"), encoding="utf-8").read()
        self.assertIn("mode=ro", src)
        self.assertNotIn("INSERT INTO", src.upper())
        self.assertNotIn("DELETE FROM", src.upper())

    def test_04_availability_is_honest_about_dense(self):
        """§10：dense 不可用必须如实报告，不得假装可用。"""
        a = L.X.availability()
        self.assertIn("dense_available", a)
        if not a["dense_available"]:
            self.assertIn("unavailable", (a["retrieval_banner"] or "").lower())
            self.assertEqual(a["retrieval_mode"], "lexical")

    def test_05_browse_vs_research_naming_is_separated(self):
        """§41：两条路径必须分开命名，不得共用一个语义模糊的 endpoint。"""
        a = L.X.availability()
        self.assertIn("browse", a["browse_vs_research"])
        self.assertIn("post-filtered", a["browse_vs_research"]["research"])
        self.assertIn("exhaustive", a["browse_vs_research"]["browse"])

    def test_06_deterministic_same_input_same_output(self):
        """§60：同一 filters 重复调用 → 结果顺序一致。"""
        f = {"seminar": "S11", "language": "fr", "limit": 20}
        a = L.B.browse_passages(dict(f))
        b = L.B.browse_passages(dict(f))
        self.assertEqual([x["passage_id"] for x in a["items"]],
                         [x["passage_id"] for x in b["items"]])
        self.assertEqual(a["page"]["total"], b["page"]["total"])

    def test_07_corpus_total_is_real(self):
        self.assertEqual(L.B.corpus_total(), len(L.raw_ids()))

    def test_08_no_writes_anywhere(self):
        """只用只读连接：SQLite 侧不应产生任何写入（-wal/-journal 不出现）。"""
        import time
        L.B.browse_passages({"seminar": "S11", "limit": 5})
        L.B.get_concept_view(L.C_OBJET_A)
        L.B.get_term_view("jouissance")
        self.assertFalse(os.path.exists(L.LEX + "-wal") or os.path.exists(L.LEX + "-journal"),
                         "只读打开不应产生 journal/WAL")
