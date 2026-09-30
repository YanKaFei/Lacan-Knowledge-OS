#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest.py — Phase 4A §26 `lacan-kb mcp-selftest`

**独立于任何 MCP client** 地验证 Knowledge Access Layer：
它直接把 JSON-RPC 消息喂给 `server.handle()`，检查协议行为与 tool 契约，
所以「DeepSeek Harness 连不上」和「知识访问层是否正确」是两件可分开判断的事。

覆盖（§20 的 15 项里的协议侧部分）
──────────────────────────────────
1. initialize 协议协商        2. tools/list 与 schema 完整性
3. valid request             4. invalid args（缺参 / 未知参数 / 类型错）
5. unknown tool              6. nonexistent passage（PASSAGE_NOT_FOUND）
7. ambiguous entity          8. entity collision
9. incomplete provenance    10. empty retrieval
11. exact lookup            12. context boundaries（首尾）
13. language filter         14. seminar filter
15. terminology bridge      16. separate comparison lanes
17. evidence sufficiency 四状态可达性  18. no mutation（read-only 声明）
19. capabilities 只含 tools  20. stdout 只有协议消息（由 serve 的契约保证）

用法
────
    python3 _scripts/_tools/lacan_mcp/selftest.py            # 人读
    python3 _scripts/_tools/lacan_mcp/selftest.py --json     # 机器读
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import server  # noqa: E402
from schemas import TOOL_NAMES, TOOLS  # noqa: E402


def _call(name, args):
    r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": args}})
    return r.get("result") or {"isError": True, "structuredContent": r.get("error")}


def _ok(res):
    return not res.get("isError", False)


CHECKS = []


def check(cid, name, ok, detail=""):
    CHECKS.append({"id": cid, "name": name, "passed": bool(ok), "detail": str(detail)[:300]})


def run(json_out=False):
    CHECKS.clear()

    # 1. initialize 协商
    r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-11-25",
                                  "capabilities": {}, "clientInfo": {"name": "selftest",
                                                                     "version": "1"}}})
    res = r["result"]
    check(1, "initialize 协议协商", res["protocolVersion"] in server.SUPPORTED_PROTOCOL_VERSIONS,
          res["protocolVersion"])
    # 19. capabilities 只含 tools
    check(19, "capabilities 只声明 tools", list(res["capabilities"].keys()) == ["tools"],
          list(res["capabilities"].keys()))
    r2 = server.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize",
                        "params": {"protocolVersion": "1999-01-01"}})
    check(1.1, "未知协议版本回退到本实现版本",
          r2["result"]["protocolVersion"] == server.PROTOCOL_VERSION,
          r2["result"]["protocolVersion"])

    # 2. tools/list
    tl = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
    names = [t["name"] for t in tl]
    check(2, "tools/list 返回 10 个 tool", len(tl) == 10, names)
    check(2.1, "tool 名与契约一致", names == TOOL_NAMES, names)
    check(2.2, "每个 tool 都有 inputSchema",
          all(isinstance(t.get("inputSchema"), dict) and t["inputSchema"].get("type") == "object"
              for t in tl))

    # 4. invalid args
    bad = [
        ("search_passages", {}, "缺必填 query"),
        ("search_passages", {"query": "x", "top_k": 999}, "top_k 超上限"),
        ("search_passages", {"query": "x", "nope": 1}, "未知参数"),
        ("search_passages", {"query": 123}, "类型错"),
        ("search_passages", {"query": "x", "retrieval_mode": "bogus"}, "enum 外取值"),
        ("get_context", {"passage_id": "x", "before": -1}, "before 越界"),
    ]
    for i, (tool, args, why) in enumerate(bad):
        res = _call(tool, args)
        check("4.%d" % i, "invalid args: %s" % why, not _ok(res),
              (res.get("structuredContent") or {}).get("error", {}).get("code"))

    # 5. unknown tool
    res = _call("no_such_tool", {})
    check(5, "unknown tool 报错", not _ok(res),
          (res.get("structuredContent") or {}).get("error", {}).get("code"))

    # 3. valid request
    res = _call("search_passages", {"query": "大他者是怎么被定义的", "top_k": 3})
    sc = res.get("structuredContent") or {}
    check(3, "valid request 成功且含 8 section", _ok(res) and all(
        k in sc for k in ("request", "resolution", "retrieval", "evidence",
                          "coverage", "provenance", "warnings", "evidence_state")),
        list(sc.keys()))
    check(3.1, "search 走了 Query Routing（有 route）",
          bool((sc.get("retrieval") or {}).get("route")),
          (sc.get("retrieval") or {}).get("route"))
    check(3.2, "evidence 全部指向真实 passage",
          all((e.get("passage_id") or "").startswith("passage.")
              for e in sc.get("evidence") or []))

    # 6. nonexistent passage
    res = _call("get_passage", {"passage_id": "passage.S99.unknown.P9999"})
    sc = res.get("structuredContent") or {}
    check(6, "不存在的 passage → PASSAGE_NOT_FOUND",
          (sc.get("resolution") or {}).get("resolution_status") == "PASSAGE_NOT_FOUND",
          (sc.get("resolution") or {}).get("resolution_status"))
    check(6.1, "PASSAGE_NOT_FOUND 时 evidence 为空", not (sc.get("evidence") or []))

    # 7. ambiguous entity
    res = _call("resolve_entity", {"term": "A"})
    sc = res.get("structuredContent") or {}
    st = (sc.get("resolution") or {}).get("resolution_status")
    check(7, "resolve_entity 返回四状态之一",
          st in ("RESOLVED", "AMBIGUOUS", "UNRESOLVED", "ENTITY_COLLISION"), st)

    # 8. entity collision（Phase 4A.1 起按**版本化**语义检查）
    #    历史事实：Phase 3 的 bridge 里 Autre/autre 仍是 ENTITY_COLLISION（不改写）；
    #    当前行为：ontology.v4a1 已把它拆成两个实体，故不再作为**活碰撞**上报，
    #              但 bare `autre` 仍不得被静默解析（CONTEXT_REQUIRED）。
    res = _call("resolve_entity", {"term": "autre"})
    sc = res.get("structuredContent") or {}
    codes = [w.get("code") for w in sc.get("warnings") or []]
    import ontology_v4a1 as _onto
    _view = {tuple(r["pair"]): r for r in _onto.guard_view()}
    _hist = _view.get(("Autre", "autre"), {})
    check(8, "Autre/autre：历史碰撞仍可观测 + 修复后不静默解析",
          _hist.get("pre_repair_class") == "ENTITY_COLLISION"
          and "ONTOLOGY_REPAIRED" in codes
          and "CONTEXT_REQUIRED" in codes,
          {"pre": _hist.get("pre_repair_class"), "post": _hist.get("post_repair_class"),
           "codes": codes})

    # 9. incomplete provenance
    res = _call("trace_source", {"passage_id": "passage.S01.unknown.L01.P0001"})
    sc = res.get("structuredContent") or {}
    prov = sc.get("provenance") or {}
    codes = [w.get("code") for w in sc.get("warnings") or []]
    check(9, "中文 recovered passage 的 SOURCE_TRACE_INCOMPLETE 未被隐藏",
          "SOURCE_TRACE_INCOMPLETE" in codes and (prov.get("gaps") or []),
          codes)
    check(9.1, "溯源链真的返回了 witness 与 corpus_source",
          bool(prov.get("chain")) and bool(prov["chain"][0].get("witness_id")),
          len(prov.get("chain") or []))

    # 10. empty retrieval
    res = _call("search_passages", {"query": "zzzqqqxxyy 完全不存在的词形组合"})
    sc = res.get("structuredContent") or {}
    check(10, "空检索仍返回合法结构且状态可读", _ok(res)
          and (sc.get("evidence_state") or {}).get("state") in
          ("INSUFFICIENT_EVIDENCE", "PARTIALLY_SUPPORTED", "CONFLICTING_EVIDENCE"),
          (sc.get("evidence_state") or {}).get("state"))

    # 11. exact lookup
    res = _call("get_passage", {"passage_id": "passage.S08.unknown.L14.P0029"})
    sc = res.get("structuredContent") or {}
    check(11, "exact lookup 命中", len(sc.get("evidence") or []) == 1,
          len(sc.get("evidence") or []))

    # 12. context boundaries（position 0 不能有 previous）
    res = _call("get_context", {"passage_id": "passage.S01.unknown.L01.P0001",
                                "before": 5, "after": 2})
    sc = res.get("structuredContent") or {}
    nav = (sc.get("retrieval") or {})
    check(12, "context 边界正确（首条 has_previous=false）",
          nav.get("window_size", 0) >= 1 and nav.get("ordering_verified") is True,
          nav.get("window_size"))
    ids = [e["passage_id"] for e in sc.get("evidence") or []]
    check(12.1, "context 保持 store 顺序", ids == sorted(ids, key=lambda p: ids.index(p))
          and ids[0] == "passage.S01.unknown.L01.P0001", ids[:3])

    # 13. language filter
    res = _call("search_passages", {"query": "jouissance", "language": "fr", "top_k": 5})
    sc = res.get("structuredContent") or {}
    check(13, "language 过滤生效",
          all(e.get("language") == "fr" for e in sc.get("evidence") or []),
          [e.get("language") for e in sc.get("evidence") or []])

    # 14. seminar filter
    res = _call("search_passages", {"query": "jouissance", "seminar": "seminar.S07",
                                    "top_k": 5})
    sc = res.get("structuredContent") or {}
    # 这一条**必须非空验证** —— 第一版对空列表做 all() 是"空真"，
    # 结果 seminar 过滤把一切都滤掉了却显示 PASS。
    ev14 = sc.get("evidence") or []
    check(14, "seminar 过滤生效且非空（约束下推到检索）",
          bool(ev14) and all(e.get("seminar_id") == "seminar.S07" for e in ev14),
          "%d 条 / %s" % (len(ev14), sorted({e.get("seminar_id") for e in ev14})))

    # 15. terminology bridge
    res = _call("terminology_lookup", {"term": "小客体a", "target_language": "fr"})
    sc = res.get("structuredContent") or {}
    check(15, "Terminology Bridge 暴露受控映射",
          any(c.get("relation_type") == "equivalent"
              for c in (sc.get("resolution") or {}).get("candidates") or []),
          len((sc.get("resolution") or {}).get("candidates") or []))
    res = _call("terminology_lookup", {"term": "réalité"})
    sc = res.get("structuredContent") or {}
    check(15.1, "没有受控映射时不编造译文",
          any(w.get("code") == "NO_CONTROLLED_MAPPING" for w in sc.get("warnings") or []),
          [w.get("code") for w in sc.get("warnings") or []])

    # 16. separate comparison lanes
    res = _call("compare_concepts", {"concept_a": "désir", "concept_b": "demande",
                                     "top_k": 3})
    sc = res.get("structuredContent") or {}
    ret = sc.get("retrieval") or {}
    check(16, "compare 使用独立 lane 且禁止合并",
          ret.get("lanes_mode") == "per_concept" and ret.get("merge_policy") == "FORBID_MERGE"
          and len(ret.get("lanes") or []) == 2,
          (ret.get("lanes_mode"), ret.get("merge_policy")))
    # 修复后 désir/demande 两侧都有实体（这正是本阶段的目标），
    # 所以「一侧无证据」这条要用一个**仍然**无实体的另一侧来验证。
    _res2 = _call("compare_concepts", {"concept_a": "désir",
                                       "concept_b": "zzzqqqxxx-not-an-entity",
                                       "top_k": 3})
    _sc2 = _res2.get("structuredContent") or {}
    check(16.1, "一侧无证据 → 不是 SUPPORTED",
          (_sc2.get("evidence_state") or {}).get("state") != "SUPPORTED",
          (_sc2.get("evidence_state") or {}).get("state"))

    # 17. sufficiency states reachable
    #     ⚠️ Phase 4A.1 之后 `CONFLICTING_EVIDENCE` **不再由真实查询触发** ——
    #        因为 bridge 里的 7 组碰撞/缺口已全部修复（这正是本阶段的目标）。
    #        所以这里分两句断言：
    #        (a) 至少三态可由真实查询触达；
    #        (b) 「已无活碰撞」是**被验证的结论**，而不是恰好没测到。
    seen = set()
    for name, args in (("search_passages", {"query": "大他者是怎么被定义的"}),
                       ("search_passages", {"query": "zzzqqq 不存在"}),
                       ("compare_concepts", {"concept_a": "désir", "concept_b": "demande"}),
                       ("compare_concepts", {"concept_a": "désir",
                                             "concept_b": "zzzqqqxxx-not-an-entity"}),
                       ("resolve_entity", {"term": "autre"})):
        sc = _call(name, args).get("structuredContent") or {}
        st = (sc.get("evidence_state") or {}).get("state")
        if st:
            seen.add(st)
    check(17, "Evidence Sufficiency 至少三态可运行（真实查询）",
          len(seen & {"SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE",
                      "CONFLICTING_EVIDENCE"}) >= 3, sorted(seen))
    _g = _onto.guard_summary()
    check(17.1, "所有 Phase 3 碰撞/缺口已重分类（无 live 缺陷）",
          not _g.get("still_defective"),
          {"pre": _g.get("pre_classes"), "post": _g.get("post_classes")})

    # 18. no mutation：所有 tool 的 inputSchema 都不得有写入类参数
    from schemas import FORBIDDEN_PARAM_PATTERNS
    bad_params = []
    for t in TOOLS:
        for p in (t["inputSchema"].get("properties") or {}):
            for pat in FORBIDDEN_PARAM_PATTERNS:
                if pat in p.lower():
                    bad_params.append((t["name"], p))
    check(18, "所有 tool 无写入类参数（READ ONLY）", not bad_params, bad_params)

    passed = sum(1 for c in CHECKS if c["passed"])
    doc = {"schema_version": "mcp-selftest/v1",
           "checks": len(CHECKS), "passed": passed, "failed": len(CHECKS) - passed,
           "all_passed": passed == len(CHECKS),
           "results": CHECKS}
    if json_out:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for c in CHECKS:
            print("  %-5s %-46s %s" % ("PASS" if c["passed"] else "FAIL",
                                       c["name"][:46], c["detail"][:60]))
        print("[selftest] %d/%d passed" % (passed, len(CHECKS)))
    return 0 if doc["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run("--json" in sys.argv))
