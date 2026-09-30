#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4a_mcp.py — Phase 4A §20：**15 项 MCP 契约测试**

这一套测的不是「能不能跑」，而是**契约边界**：

| # | 测什么 | 为什么 |
|---|---|---|
| 01 | initialize 协议协商 | stdio framing / 版本协商错了整条链路都不通 |
| 02 | capabilities **只**声明 tools | 声明了 resources/prompts 却实现不了 = 骗客户端 |
| 03 | tools/list 恰好 10 个，名字与 schemas 一致 | §4「克制」 |
| 04 | 每个 tool 的 inputSchema 是合法 JSON-Schema 子集 | 参数校验必须由 `argcheck` 真做 |
| 05 | 每个 tool 用**最小参数**都真的能跑 | 契约不能有跑不通的 tool |
| 06 | 每个响应都有**完整 8 段** | §6 |
| 07 | 每个响应 `evidence_state` 合法且 method 固定 | §7 禁止 cosine 阈值 |
| 08 | **evidence 里的 passage_id 全部真实存在** | §2 不得编造引用 |
| 09 | 所有 tool 无写入型参数 | §2/§21 只读 |
| 10 | 未知 tool → JSON-RPC 错误，不崩 | 协议健壮性 |
| 11 | 非法参数 → INVALID_ARGS，不抛异常 | 参数层 |
| 12 | 不存在的 passage_id → PASSAGE_NOT_FOUND | 不猜 ID |
| 13 | notification（无 id）不产生响应 | JSON-RPC 2.0 |
| 14 | `serve()` 的 stdout 只有 JSON-RPC 行 | 往 stdout 打日志会毁掉协议 |
| 15 | 调用全部 tool 后 canonical store / 索引**未被修改** | §21 只读硬门 |
"""

import hashlib
import io
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
MCP = os.path.join(TOOLS, "lacan_mcp")
sys.path.insert(0, TOOLS)
sys.path.insert(0, MCP)

import server  # noqa: E402
import schemas  # noqa: E402
import selftest as st  # noqa: E402
import validate as vd  # noqa: E402
import knowledge_api as api  # noqa: E402

STORE = os.path.join(VAULT, "_data", "passage_store")


def rpc(method, params=None, rid=1):
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = params
    return server.handle(msg)


def call(name, args=None, rid=2):
    return rpc("tools/call", {"name": name, "arguments": args or {}}, rid)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class TestMCPContract(unittest.TestCase):

    # ── 01
    def test_01_initialize_negotiates_protocol(self):
        r = rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                               "clientInfo": {"name": "t", "version": "1"}})
        res = r["result"]
        self.assertIn(res["protocolVersion"], server.SUPPORTED_PROTOCOL_VERSIONS)
        self.assertEqual(res["serverInfo"]["name"], server.SERVER_NAME)
        # 客户端给一个我们不支持的版本 → 必须回我们支持的最新版，而不是假装同意
        r2 = rpc("initialize", {"protocolVersion": "1999-01-01"})
        self.assertIn(r2["result"]["protocolVersion"], server.SUPPORTED_PROTOCOL_VERSIONS)
        self.assertNotEqual(r2["result"]["protocolVersion"], "1999-01-01")

    # ── 02
    def test_02_capabilities_declare_tools_only(self):
        res = rpc("initialize", {})["result"]
        self.assertEqual(list(res["capabilities"].keys()), ["tools"])
        self.assertIn("listChanged", res["capabilities"]["tools"])

    # ── 03
    def test_03_exactly_ten_tools_matching_schemas(self):
        listed = rpc("tools/list", {})["result"]["tools"]
        self.assertEqual(len(listed), 10, "§4 要求恰好 10 个 tool")
        self.assertEqual([t["name"] for t in listed], schemas.TOOL_NAMES)
        # 顺序也钉住：契约文档是按这个顺序渲染的
        self.assertEqual([t["name"] for t in listed],
                         [t["name"] for t in schemas.TOOLS])

    # ── 04
    def test_04_input_schemas_are_valid_subsets(self):
        import argcheck
        for t in rpc("tools/list", {})["result"]["tools"]:
            self.assertEqual(t["inputSchema"]["type"], "object", t["name"])
            self.assertFalse(t["inputSchema"].get("additionalProperties", True),
                             "%s 必须 additionalProperties=False（不许塞未声明参数）"
                             % t["name"])
            for prop, spec in (t["inputSchema"].get("properties") or {}).items():
                for k in spec:
                    self.assertIn(k, argcheck.SUPPORTED_KEYWORDS,
                                  "%s.%s 用了未支持的 JSON-Schema 关键字 %s"
                                  % (t["name"], prop, k))
            # outputSchema 故意不声明（我们返回 structuredContent，但不当协议级 schema）
            self.assertNotIn("outputSchema", t)

    # ── 05
    def test_05_every_tool_runs_with_minimal_args(self):
        pid = api.search_passages("objet a", top_k=1)["evidence"][0]["passage_id"]
        minimal = {
            "search_passages": {"query": "objet a"},
            "get_passage": {"passage_id": pid},
            "get_context": {"passage_id": pid},
            "resolve_entity": {"term": "objet a"},
            "get_concept": {"entity_id": "concept.objet-petit-a"},
            "find_concept_evidence": {"concept": "concept.objet-petit-a"},
            "trace_concept": {"concept": "concept.jouissance"},
            "compare_concepts": {"concept_a": "concept.desir",
                                 "concept_b": "concept.jouissance"},
            "trace_source": {"passage_id": pid},
            "terminology_lookup": {"term": "objet a"},
        }
        self.assertEqual(sorted(minimal), sorted(schemas.TOOL_NAMES))
        for name, args in minimal.items():
            r = call(name, args)
            self.assertIn("result", r, "%s 失败：%r" % (name, r))
            self.assertFalse(r["result"].get("isError"),
                             "%s 返回 isError：%s" % (name, r["result"].get("content")))
            self.assertIsInstance(r["result"]["structuredContent"], dict, name)

    # ── 06
    def test_06_every_response_has_eight_sections(self):
        pid = api.search_passages("jouissance", top_k=1)["evidence"][0]["passage_id"]
        for name in schemas.TOOL_NAMES:
            args = {"search_passages": {"query": "jouissance"},
                    "get_passage": {"passage_id": pid},
                    "get_context": {"passage_id": pid},
                    "resolve_entity": {"term": "jouissance"},
                    "get_concept": {"entity_id": "concept.jouissance"},
                    "find_concept_evidence": {"concept": "concept.jouissance"},
                    "trace_concept": {"concept": "concept.jouissance"},
                    "compare_concepts": {"concept_a": "concept.jouissance",
                                         "concept_b": "concept.desir"},
                    "trace_source": {"passage_id": pid},
                    "terminology_lookup": {"term": "jouissance"}}[name]
            sc = call(name, args)["result"]["structuredContent"]
            self.assertEqual(vd.validate_envelope(sc, tool=name), [],
                             "%s 输出不合格" % name)

    # ── 07
    def test_07_evidence_state_is_structural_never_cosine(self):
        r = call("search_passages", {"query": "objet a"})["result"]
        sc = r["structuredContent"]
        st_ = sc["evidence_state"]
        self.assertEqual(st_["method"], "structural_only_no_cosine_threshold")
        self.assertIn("cosine", st_["prohibited"].lower())
        self.assertNotIn("confidence", st_)
        # 信号里不得出现任何相似度分数（只有结构量）
        for k, v in st_["signals"].items():
            self.assertNotIn("cosine", k)
            self.assertNotIn("similarity", k)
            if isinstance(v, float):
                self.assertIn(k, ("component_agreement", "provenance_completeness",
                                  "duplicate_concentration", "resolved_entity_coverage"),
                              "可疑的 0–1 数值信号：%s" % k)

    # ── 08
    def test_08_no_fabricated_passage_ids(self):
        known = vd.passage_ids()
        self.assertGreater(len(known), 200000, "canonical store 未加载")
        for name, args in (("search_passages", {"query": "凝视", "top_k": 5}),
                           ("find_concept_evidence",
                            {"concept": "concept.jouissance", "top_k": 5}),
                           ("trace_concept", {"concept": "concept.jouissance",
                                              "per_period": 2}),
                           ("compare_concepts", {"concept_a": "concept.desir",
                                                 "concept_b": "concept.jouissance",
                                                 "top_k": 3})):
            sc = call(name, args)["result"]["structuredContent"]
            self.assertEqual(vd.validate_envelope(sc, tool=name, check_passages=True), [])
            for e in sc["evidence"]:
                self.assertIn(e["passage_id"], known)

    # ── 09
    def test_09_no_write_capable_parameters(self):
        bad = []
        for t in schemas.TOOLS:
            for p in (t["inputSchema"].get("properties") or {}):
                for pat in schemas.FORBIDDEN_PARAM_PATTERNS:
                    if pat in p.lower():
                        bad.append("%s.%s" % (t["name"], p))
        self.assertEqual(bad, [])
        # 目录里也不得有「写入型」tool 名
        for name in schemas.TOOL_NAMES:
            for pat in ("set", "write", "update", "delete", "create", "promote",
                        "merge", "canonicalize"):
                self.assertNotIn(pat, name)

    # ── 10
    def test_10_unknown_tool_is_protocol_error(self):
        r = call("write_canonical_truth", {"x": 1})
        self.assertIn("error", r)
        self.assertEqual(r["error"]["code"], server.INVALID_PARAMS)
        r2 = rpc("tools/does_not_exist", {})
        self.assertEqual(r2["error"]["code"], server.METHOD_NOT_FOUND)

    # ── 11
    def test_11_invalid_arguments_are_protocol_errors(self):
        # MCP 规范把「参数不合 schema」列为 protocol error（-32602）。
        # 关键是：**不抛异常**，而是回一个可读的 error 对象。
        for args in ({"query": ""},                      # minLength 违规
                     {"query": "objet a", "canonicalize": True},   # 未声明参数
                     {"query": "objet a", "top_k": 9999},          # 超上界
                     {"query": "objet a", "language": "klingon"}):  # enum 违规
            r = call("search_passages", args)
            self.assertIn("error", r, args)
            self.assertEqual(r["error"]["code"], server.INVALID_PARAMS)
            self.assertEqual(r["error"]["data"]["code"], "INVALID_ARGS")
            self.assertTrue(r["error"]["data"]["details"])
        r2 = call("get_passage", {"passage_id": 12345})
        self.assertEqual(r2["error"]["code"], server.INVALID_PARAMS)
        # 缺必填参数
        r3 = call("get_passage", {})
        self.assertEqual(r3["error"]["code"], server.INVALID_PARAMS)

    # ── 12
    def test_12_missing_passage_is_not_guessed(self):
        r = call("get_passage", {"passage_id": "passage.S99.unknown.P9999"})
        sc = r["result"]["structuredContent"]
        self.assertEqual(sc["evidence"], [])
        self.assertIn("PASSAGE_NOT_FOUND", [w["code"] for w in sc["warnings"]])
        self.assertEqual(sc["evidence_state"]["state"], "INSUFFICIENT_EVIDENCE")

    # ── 13
    def test_13_notifications_produce_no_response(self):
        self.assertIsNone(server.handle({"jsonrpc": "2.0",
                                         "method": "notifications/initialized"}))
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "ping"}))
        self.assertIsNotNone(server.handle({"jsonrpc": "2.0", "id": 9, "method": "ping"}))

    # ── 14
    def test_14_serve_writes_only_jsonrpc_on_stdout(self):
        inp = io.StringIO("\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-11-25"}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "get_passage",
                                   "arguments": {"passage_id": "nope"}}}),
        ]) + "\n")
        out = io.StringIO()
        err = io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            n = server.serve(inp, sys.stdout)
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        lines = [l for l in out.getvalue().split("\n") if l.strip()]
        self.assertEqual(n, 3)
        self.assertEqual(len(lines), 3, "stdout 行数 != 响应数（有杂音被写进 stdout）")
        for l in lines:
            doc = json.loads(l)          # 每行必须是完整 JSON
            self.assertEqual(doc["jsonrpc"], "2.0")
            self.assertIn("id", doc)
        self.assertNotIn("\r", out.getvalue())

    # ── 15
    def test_15_read_only_no_mutation_of_canonical_or_index(self):
        watch = [os.path.join(STORE, n) for n in
                 ("passages.jsonl", "concepts.jsonl", "concept_states.jsonl",
                  "sessions.jsonl", "witnesses.jsonl", "alignments.jsonl",
                  "passage_realizations.jsonl", "corpus_sources.jsonl")]
        watch.append(os.path.join(VAULT, "_data", "index", "lexical.sqlite"))
        before = {p: (_sha(p), os.path.getmtime(p)) for p in watch if os.path.isfile(p)}
        self.assertGreaterEqual(len(before), 5)
        pid = api.search_passages("objet a", top_k=1)["evidence"][0]["passage_id"]
        for name in schemas.TOOL_NAMES:
            call(name, {"search_passages": {"query": "objet a"},
                        "get_passage": {"passage_id": pid},
                        "get_context": {"passage_id": pid},
                        "resolve_entity": {"term": "objet a"},
                        "get_concept": {"entity_id": "concept.objet-petit-a"},
                        "find_concept_evidence": {"concept": "concept.objet-petit-a"},
                        "trace_concept": {"concept": "concept.jouissance"},
                        "compare_concepts": {"concept_a": "concept.desir",
                                             "concept_b": "concept.jouissance"},
                        "trace_source": {"passage_id": pid},
                        "terminology_lookup": {"term": "objet a"}}[name])
        after = {p: (_sha(p), os.path.getmtime(p)) for p in before}
        self.assertEqual(before, after, "调用 MCP tool 后 canonical store 被改动了")

    # ── 附加（§3）：selftest 必须全绿，且 tool 名与文档一致
    def test_16_selftest_all_green_and_contract_doc_current(self):
        # 把 selftest 的 JSON 报告吞掉：它会污染测试输出，
        # 让上层（completion gate）抓不到「Ran N tests」这一行。
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = st.run(json_out=True)
        self.assertEqual(rc, 0)
        r = os.system("python3 %s --check >/dev/null 2>&1"
                      % os.path.join(TOOLS, "render_contracts.py"))
        self.assertEqual(r, 0, "MCP_TOOL_CONTRACTS.md / tool_schemas.json 已过期")


class TestDelegationToPhase3(unittest.TestCase):
    """§4 的硬要求：`search_passages` 必须走 Phase 3 已验证的检索链，
    **禁止另写一套 retrieval**。这条只能靠静态事实守住 ——
    「看起来像在调用」不够，得证明访问层里不存在第二条检索实现。
    """

    @classmethod
    def setUpClass(cls):
        cls.src = open(os.path.join(MCP, "knowledge_api.py"), encoding="utf-8").read()

    def test_19_delegates_to_phase3_components(self):
        for anchor in ("query_router", "query_routing_policy", "plan_for(",
                       "full_corpus_retrieval", "lacan_search",
                       "entity_resolution", "terminology_bridge",
                       "lacanian_semantic_guard"):
            self.assertIn(anchor, self.src, "访问层没有用 %s（§4 要求复用 Phase 3）" % anchor)

    def test_20_no_second_retrieval_implementation(self):
        # 不得自己写 FTS/匹配：访问层里不应出现 FTS5 查询语法或 MATCH
        for bad in ("MATCH", "fts5", "CREATE VIRTUAL TABLE", "bm25("):
            self.assertNotIn(bad, self.src,
                             "访问层出现了自建检索痕迹：%s" % bad)
        # 唯一的 sqlite 连接只用于**元数据**读取（passage_meta），不是检索
        self.assertEqual(self.src.count("sqlite3.connect("), 1,
                         "访问层出现了不止一个 sqlite 连接 —— 需要确认它不是第二条检索实现")
        self.assertIn("FROM passage_meta ORDER BY rowid", self.src)

    def test_21_relations_and_concepts_are_monitored_by_the_readonly_gate(self):
        """§21 点名「canonical/source hash 与 **concept/relation** 文件」都要前后不变。"""
        rec = os.path.join(VAULT, "_data", "index", "READONLY_GATE.json")
        self.assertTrue(os.path.isfile(rec))
        doc = json.load(open(rec, encoding="utf-8"))
        self.assertTrue(doc.get("monitored_relation_files"),
                        "只读硬门没有监控 _data/relations/*.jsonl")
        self.assertIn("store/concepts.jsonl", doc["monitored"])
        self.assertGreaterEqual(doc["monitored_files"], 18)


class TestHardGatesCanFail(unittest.TestCase):
    """§27：11 项硬门禁必须为 0 —— 但**门禁得真的会红**。

    「一直是 0」和「永远不会红」是两件事。这里拿合成违规验证判据会命中，
    再验证真实产物确实是 0。一个从不失败的门禁等于没有门禁。
    """

    def test_17_synthetic_violations_are_detected(self):
        import check_phase4a_hard_gates as hg
        # 写 canonical 的代码必须被 WRITE_RE 抓到，且不被白名单覆盖
        bad = 'open(os.path.join(STORE, "concepts.jsonl"), "w")'
        self.assertTrue(hg.WRITE_RE.search(bad))
        seg = bad + "  # 上下文"
        self.assertFalse(any(k in seg for k in hg.WRITE_ALLOW))
        # 自动修复路径必须被 FIX_RE 抓到
        for src in ("def auto_fix(issue): pass",
                    "curator.canonicalize(x)",
                    "auto_promote(concept)",
                    "resolve_collision(entity)"):
            self.assertTrue(hg.FIX_RE.search(src), src)
        # 但**声明**与**否定测试**不能误报（否则门禁在自己的守卫上红）
        for src in ('"canonicalize",', 'FORBIDDEN = ["canonicalize"]',
                    'argcheck.validate({"query": "x", "canonicalize": True}, sch)'):
            self.assertFalse(hg.FIX_RE.search(src), src)
        self.assertTrue(hg.CANONICAL_TRUE_RE.search('row = {"canonical": True}'))
        self.assertFalse(hg.CANONICAL_TRUE_RE.search('"canonical": False'))

    def test_18_real_hard_gate_record_is_all_zero_and_non_vacuous(self):
        rec = os.path.join(VAULT, "_data", "index", "PHASE4A_HARD_GATES.json")
        self.assertTrue(os.path.isfile(rec), "先跑 check_phase4a_hard_gates.py")
        doc = json.load(open(rec, encoding="utf-8"))
        self.assertEqual(doc["gate_count"], 11)
        self.assertTrue(doc["all_zero"], doc["gates"])
        self.assertEqual(doc["total_violations"], 0)
        # 非空洞：确实扫到了写盘点，才有资格说「只允许这些」
        self.assertTrue(doc["access_layer_write_sites"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
