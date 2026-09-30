#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.1 §31-2/§5：MCP 层不得 import 核心内部实现（静态边界）。"""
import os, re, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT); sys.path.insert(0, HERE)

CORE = ("knowledge_api", "research_answer", "research_contract", "research_execution",
        "synthesis_contract", "synthesis_claims", "synthesis_render",
        "synthesis_adapters", "synthesis_entailment", "synthesis_validation",
        "eval_integrity", "core_freeze", "round2_review")

class McpCoreBoundary(unittest.TestCase):
    def _sources(self):
        d = os.path.join(VAULT, "mcp_server")
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".py"):
                yield fn, open(os.path.join(d, fn), encoding="utf-8").read()

    def test_00_no_core_imports(self):
        bad = []
        for fn, src in self._sources():
            for mod in CORE:
                if re.search(r"^\s*(import|from)\s+%s\b" % re.escape(mod), src, re.M):
                    bad.append("%s -> %s" % (fn, mod))
        self.assertEqual(bad, [], "MCP 层不得直接 import 核心：%s" % bad)

    def test_01_only_scholarly_api_dependency(self):
        seen = set()
        for fn, src in self._sources():
            for m in re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", src, re.M):
                seen.add(m.split(".")[0])
        allowed = {"scholarly_api", "mcp_server", "json", "os", "sys", "time", "uuid",
                   "argparse", "hashlib", "subprocess", "traceback", "re",
                   "concurrent", "datetime", "tempfile", "unittest", "__future__",
                   "jsonschema"}
        extra = seen - allowed
        self.assertEqual(extra, set(), "MCP 层出现了未批准的依赖：%s" % extra)

    def test_02_no_core_path_hacking(self):
        """除 config.py 的冻结校验器路径外，**字符串字面量**不得指向 _scripts。"""
        import ast
        for fn, src in self._sources():
            if fn == "config.py":
                continue
            tree = ast.parse(src)
            # 文档字符串是文档，不算路径引用
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    ds = ast.get_docstring(node, clean=False)
                    if ds:
                        docstrings.add(ds)
            bad = [n.value for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and "_scripts" in n.value and n.value not in docstrings]
            self.assertEqual(bad, [], "%s 的字符串字面量指向 _scripts：%s" % (fn, bad))

    def test_03_guard_uses_subprocess_not_import(self):
        src = open(os.path.join(VAULT, "mcp_server", "guard.py"), encoding="utf-8").read()
        self.assertIn("subprocess", src)
        self.assertIn("core_freeze.py", src)

if __name__ == "__main__":
    unittest.main()
