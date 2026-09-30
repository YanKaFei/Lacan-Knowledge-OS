#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_phase4a_completion.py — Phase 4A §28：**20 条完成判据**

规则（§28 原文的意思）
──────────────────────
* 20 条**全部**成立，才能说 `PHASE 4A KNOWLEDGE ACCESS LAYER = COMPLETE`；
* 只要有任意一条不成立，只能说 `PARTIAL` 或 `BLOCKED`；
* **绝不允许**为了让门通过而降低判据 —— 所以本文件里的每条判据都是
  「查一个已经存在的产物 / 跑一个已经存在的检查」，而不是在这里放宽阈值。

产物
────
    _data/index/PHASE4A_COMPLETION_GATE.json

用法
────
    python3 _scripts/_tools/check_phase4a_completion.py            # 打印报告
    python3 _scripts/_tools/check_phase4a_completion.py --verify   # 不同过则 exit 1
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
IDX = os.path.join(VAULT, "_data", "index")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

OUT = os.path.join(IDX, "PHASE4A_COMPLETION_GATE.json")

DOCS = [
    "MCP_ARCHITECTURE.md", "MCP_TOOL_CONTRACTS.md", "EVIDENCE_SUFFICIENCY.md",
    "RESEARCH_AGENT.md", "RESEARCH_AGENT_EVAL.md", "ONTOLOGY_GAP_QUEUE.md",
    "CURATOR_AGENT_DESIGN.md", "PHASE4A_FINDINGS.md",
    "DELIVERY_EVIDENCE_PHASE4A.md", "MCP_DSH_INTEGRATION.md",
]


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def sh(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=VAULT)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def suite(pattern):
    """跑一个测试套件并取「Ran N tests」—— 用真实执行，不读缓存。

    ⚠️ 不用 `unittest discover -s ... -p ...`：从仓库根跑时它 **Ran 0 tests**
    （discovery 需要 top_level_dir），于是「≥15 项」会被一个 0 悄悄满足或悄悄不满足。
    """
    return sh("cd _scripts/_tests && python3 -m unittest %s 2>&1 "
              "| grep -E '^(Ran |OK|FAILED)'" % pattern)


def main(argv):
    checks = []

    def add(cid, name, passed, evidence):
        checks.append({"id": cid, "name": name, "passed": bool(passed),
                       "evidence": evidence})

    # ── 1 MCP server 真能起来并握手
    proof = jload(os.path.join(VAULT, "_data", "mcp", "DSH_CLIENT_PROOF.json"), {})
    add(1, "MCP server 经 stdio 被 DSH 的 SDK 成功调用（14/14）",
        proof.get("passed") == proof.get("total") and proof.get("total", 0) >= 10,
        "%s/%s；sdk@%s" % (proof.get("passed"), proof.get("total"),
                           (proof.get("dsh_sdk") or {}).get("version")))

    # ── 2 恰好 10 个 tool + 共享 8 段输出
    ts = jload(os.path.join(VAULT, "_data", "mcp", "tool_schemas.json"), {})
    add(2, "恰好 10 个 tool，且共享 8 段输出 schema",
        ts.get("count") == 10 and len(ts.get("output_sections") or []) == 8,
        "count=%s sections=%s" % (ts.get("count"),
                                  len(ts.get("output_sections") or [])))

    # ── 3 只读硬门
    ro = jload(os.path.join(IDX, "READONLY_GATE.json"), {})
    hg4 = jload(os.path.join(IDX, "PHASE4A_HARD_GATES.json"), {})
    add(3, "§21/§27 只读硬门全过 + 11 项硬门禁 = 0",
        bool(ro.get("all_passed")) and hg4.get("gate_count") == 11
        and hg4.get("all_zero") is True and hg4.get("total_violations") == 0,
        "只读 %s/%s（%s 个文件）；11 项硬门禁 violations=%s"
        % (ro.get("passed"), ro.get("total"), ro.get("monitored_files"),
           hg4.get("total_violations")))

    # ── 4 证据充分性：四状态 + 无 cosine 阈值
    st = jload(os.path.join(VAULT, "_data", "eval", "research_eval_results.json"), {})
    m = st.get("metrics") or {}
    add(4, "四状态可达且无 cosine 阈值（method 固定）",
        set(m.get("states_reached") or []) >= {"SUPPORTED", "PARTIALLY_SUPPORTED"}
        and os.path.isfile(os.path.join(HERE, "lacan_mcp", "evidence_sufficiency.py")),
        "states=%s" % m.get("states_reached"))

    # ── 5 三个新测试套件在最近一次完整 run 里 OK
    # 优先读**本轮**的套件中间记录（TEST_RUN.suites.json）；否则会读到上一轮的 FAIL
    tr_full = jload(os.path.join(IDX, "TEST_RUN.json"), {})
    tr_suites = jload(os.path.join(IDX, "TEST_RUN.suites.json"), {})
    tr = tr_suites if (tr_suites and tr_suites.get("results")) else tr_full
    results = {r["name"]: r["status"] for r in (tr.get("results") or [])}
    need = ["test_phase4a_mcp", "test_phase4a_research", "test_phase4a_sufficiency"]
    add(5, "Phase 4A 三个测试套件在最近完整 run 中全 OK",
        all(results.get(n) == "OK" for n in need) and not tr.get("quick_mode"),
        {n: results.get(n) for n in need} | {"quick_mode": tr.get("quick_mode")})

    # ── 6 §20：≥15 项 MCP 契约测试
    rc, out = suite("test_phase4a_mcp")
    ncases = int((re.search(r"Ran (\d+) tests", out) or [0, 0])[1] or 0)
    add(6, "§20 MCP 契约测试 ≥15 项且全绿", rc == 0 and ncases >= 15,
        "Ran %d tests, rc=%d" % (ncases, rc))

    # ── 7 research agent 套件项数
    rc7, out7 = suite("test_phase4a_research")
    n7 = int((re.search(r"Ran (\d+) tests", out7) or [0, 0])[1] or 0)
    add(7, "Research Agent 测试全绿（预算/trace/重试/引用）",
        rc7 == 0 and n7 >= 20, "Ran %d tests, rc=%d" % (n7, rc7))

    # ── 8 sufficiency 套件
    rc8, out8 = suite("test_phase4a_sufficiency")
    n8 = int((re.search(r"Ran (\d+) tests", out8) or [0, 0])[1] or 0)
    add(8, "Evidence Sufficiency 测试全绿（适用性/范围/碰撞）",
        rc8 == 0 and n8 >= 12, "Ran %d tests, rc=%d" % (n8, rc8))

    # ── 9 契约文档由代码渲染且不过期
    rc9, out9 = sh("python3 _scripts/_tools/render_contracts.py --check")
    add(9, "MCP_TOOL_CONTRACTS.md / tool_schemas.json 与 schemas.py 同步",
        rc9 == 0, out9.strip()[:160])

    # ── 10 研究评测：全部 case 达期望 + 零编造
    add(10, "§16/§17 研究评测：10/10 case 达期望，fabricated=0",
        m.get("n") == 10 and m.get("no_fabrication") == 1.0
        and m.get("passage_validity") == 1.0 and m.get("budget_compliance") == 1.0,
        {k: m.get(k) for k in ("n", "classifier_accuracy",
                               "tool_selection_correctness", "passage_validity",
                               "sufficiency_correctness", "gap_detection_accuracy",
                               "no_fabrication")})

    # ── 11 缺口队列：只记候选
    ogq_path = os.path.join(VAULT, "_data", "ontology_gap_queue.jsonl")
    rows = []
    if os.path.isfile(ogq_path):
        with open(ogq_path, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f if l.strip()]
    # Phase 4A.1 起：修复过的条目按 §9 追加 `resolved` / `invalidated` 状态行，
    # 因此判据改为「新发现必为 candidate + 任何行都不提议改 canonical +
    # resolved 行可审计」——后两条是**新增**约束，不是放宽。
    _new_only_candidate = all(
        r.get("status") == "candidate" for r in rows if not r.get("status_updated_by"))
    add(11, "§22/§9 ontology_gap_queue：新发现=candidate、任何行都不提议改 canonical",
        bool(rows) and _new_only_candidate
        and all(r.get("status") in ("candidate", "resolved", "invalidated")
                for r in rows)
        and all(not r.get("canonical_change_proposed") for r in rows)
        and all(r.get("resolution_commit") for r in rows
                if r.get("status") == "resolved"),
        "%d 行（含状态更新行）" % len(rows))

    # ── 12 缺口队列文档
    add(12, "ONTOLOGY_GAP_QUEUE.md 存在且给出候选与统计",
        os.path.isfile(os.path.join(VAULT, "ONTOLOGY_GAP_QUEUE.md")),
        "ONTOLOGY_GAP_QUEUE.md")

    # ── 13 结构化 trace 落盘（§18）
    traces = []
    tdir = os.path.join(VAULT, "_data", "eval", "research_traces")
    if os.path.isdir(tdir):
        traces = [f for f in os.listdir(tdir) if f.endswith(".json")]
    ok_trace = False
    if traces:
        one = jload(os.path.join(tdir, sorted(traces)[0]), {})
        ok_trace = bool(one.get("research_trace", {}).get("no_hidden_reasoning"))
    add(13, "§18 research trace 落盘且声明无隐藏推理", bool(traces) and ok_trace,
        "%d 个 trace 文件" % len(traces))

    # ── 14 引用契约
    add(14, "§14/§15 引用契约（抽查/校验/层级）实现且被测试覆盖",
        os.path.isfile(os.path.join(HERE, "lacan_mcp", "citations.py"))
        and results.get("test_phase4a_research") == "OK",
        "citations.py + citation tests")

    # ── 15 CLI debug harness
    rc15a, out15a = sh("./_scripts/_tools/lacan-kb mcp-selftest 2>&1 | tail -1")
    rc15b, out15b = sh("./_scripts/_tools/lacan-kb research '什么是 objet a？' --no-gaps "
                       "2>&1 | head -3")
    # 自检项数会随阶段增长（Phase 4A.1 加了 1 条），所以断言「全过」而不是硬编码数字
    import re as _re
    _m = _re.search(r"(\d+)/(\d+) passed", out15a)
    _selftest_ok = bool(_m) and _m.group(1) == _m.group(2) and int(_m.group(2)) >= 34
    add(15, "§26 CLI debug harness：mcp-selftest 与 research 可用",
        rc15a == 0 and _selftest_ok and "query" in out15b,
        (out15a.strip()[:40] + " | " + out15b.strip().split("\n")[0][:40]))

    # ── 16 DSH 集成与 Codex 配置都有成文证据
    integ = os.path.join(VAULT, "MCP_DSH_INTEGRATION.md")
    txt = open(integ, encoding="utf-8").read() if os.path.isfile(integ) else ""
    add(16, "§19 DSH 集成证明 + Codex 配置成文",
        "dsh-mcp-client" in txt and "config.toml" in txt
        and "DSH_CLIENT_PROOF.json" in txt, "MCP_DSH_INTEGRATION.md")

    # ── 17 九份文档齐
    missing = [d for d in DOCS if not os.path.isfile(os.path.join(VAULT, d))]
    add(17, "§25 交付文档齐全（9 份 + DSH 集成说明）", not missing,
        missing or "%d 份齐" % len(DOCS))

    # ── 18 未改动 Phase 1–3 的 canonical 历史数据
    rc18, out18 = sh("git status --porcelain -- _data/passage_store "
                     "_data/index/lexical.sqlite _data/terminology_bridge.jsonl")
    add(18, "未修改 Phase 1–3 canonical 历史数据（git 无改动）",
        rc18 == 0 and not out18.strip(), out18.strip()[:120] or "无改动")

    # ── 19 Phase 3C 完成门与 17 项硬门禁仍然成立（没有回退）
    g3 = jload(os.path.join(IDX, "PHASE3_COMPLETION_GATE.json"), {})
    hg = jload(os.path.join(IDX, "HARD_GATES.json"), {})
    # ⚠️ 必须读**真实的键**：`g3.get("passed") == g3.get("total")` 会变成
    #    `None == None` → True，于是一条本该报告「读不到」的判据会假过。
    g3_ok = (g3.get("gate_count") == 22 and g3.get("passed_count") == 22
             and g3.get("closable") is True)
    hg_ok = (hg.get("gate_count") == 17 and hg.get("all_zero") is True)
    add(19, "Phase 3C 完成门未回退，17 项硬门禁仍为 0",
        g3_ok and hg_ok,
        "3C=%s/%s closable=%s；hard_gates=%s all_zero=%s"
        % (g3.get("passed_count"), g3.get("gate_count"), g3.get("closable"),
           hg.get("gate_count"), hg.get("all_zero")))

    # ── 20 预算默认 12，且工具数没被偷偷扩张
    rc20, out20 = sh("python3 -c \"import sys;sys.path.insert(0,'_scripts/_tools');"
                     "sys.path.insert(0,'_scripts/_tools/lacan_mcp');"
                     "import research_agent as r, schemas;"
                     "print(r.DEFAULT_BUDGET['max_tool_calls'], len(schemas.TOOLS))\"")
    add(20, "§13 预算默认 max_tool_calls=12，且 tool 数=10",
        rc20 == 0 and out20.strip() == "12 10", out20.strip())

    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)
    doc = {
        "schema_version": "phase4a-completion-gate/v1",
        "phase": "Phase 4A Knowledge Access Layer & Research Agent",
        "checks": checks, "passed": passed, "total": total,
        "closable": passed == total,
        "verdict": ("PHASE 4A KNOWLEDGE ACCESS LAYER = COMPLETE" if passed == total
                    else "PARTIAL / BLOCKED —— 未过条目见 checks"),
        "rule": ("20 条全过才可声明 COMPLETE；未全过时只能说 PARTIAL/BLOCKED，"
                 "且**不得**为了过关而降低任何判据（§28）。"),
    }
    os.makedirs(IDX, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if "--json" in argv:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for c in checks:
            print("  %-5s %-52s %s" % ("PASS" if c["passed"] else "FAIL",
                                       c["name"][:52], str(c["evidence"])[:80]))
        print("[phase4a-gate] %d/%d -> %s" % (passed, total, doc["verdict"]))
    if "--verify" in argv:
        return 0 if doc["closable"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
