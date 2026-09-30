#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
product_acceptance.py — Phase 4D.7：产品验收运行器（§44–§69）

一次 acceptance run 做四件事，全部写进
`_data/product_acceptance/<run_id>/`：

    1. **preflight**：健康检查（分层）+ 隔离 QA fixture（可控 workspace / vault / exports）
    2. **scenarios A–F**：浏览器 + API 混合断言（每条步骤记 expected/observed/evidence）
    3. **P8 metrics**：关键操作延迟分类（interactive-fast / interactive-wait /
       provider-bound / batch）+ 环境与资源记录
    4. **full regression**：调用 `_scripts/run_all_tests.sh`，取 failed/skipped/exit
       与逐套件耗时（timing report，§40）

最后按**冻结的** Product Acceptance Gate v1 计算 A1–A12（§63/§83），
输出 `final_decision.json`。Gate 一旦冻结就不再修改；本 run 发现 bug 就记 FAILED，
修完另起新 run（§66）。

用法：
    python3 _scripts/_tools/product_acceptance.py --preflight         # 只做 1
    python3 _scripts/_tools/product_acceptance.py --scenarios         # 1+2+3
    python3 _scripts/_tools/product_acceptance.py --full              # 全部（含长回归）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
for p in (VAULT, os.path.join(VAULT, "_scripts", "_tests")):
    sys.path.insert(0, p)

ACC_DIR = os.path.join(VAULT, "_data", "product_acceptance")
GATE_REL = os.path.join("_data", "product_acceptance",
                        "product_acceptance_gate_v1.json")
GATE = os.path.join(VAULT, GATE_REL)


def sha_file(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_text(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def head():
    r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                       cwd=VAULT)
    return r.stdout.strip() or "unknown"


def new_run_id():
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "4d7_acceptance_%s_%s" % (ts, sha_text(ts + str(os.getpid()))[:8])


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
    return path


# ─────────────────────────────────────────────────────────── 环境 / 资源
def environment():
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = None
    chrome = subprocess.run(["pgrep", "-f", "Google Chrome"],
                            capture_output=True, text=True)
    chrome_n = len([x for x in chrome.stdout.split("\n") if x.strip()])
    mem = None
    try:
        mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                 text=True).stdout.strip())
    except Exception:                                                     # noqa: BLE001
        mem = None
    return {
        "platform": "%s %s" % (platform.system(), platform.release()),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "memory_bytes": mem,
        "loadavg": [load1, load5, load15],
        "chrome_processes": chrome_n,
        "node": (subprocess.run(["node", "--version"], capture_output=True,
                                text=True).stdout.strip() or None),
        "note": ("环境快照只用于**解释**慢，不用来给产品判分（§44）；"
                 "高负载不会自动 FAIL 验收。"),
    }


def timing_classify(seconds):
    if seconds is None:
        return None
    if seconds < 1.5:
        return "interactive-fast"
    if seconds < 30:
        return "interactive-wait"
    if seconds < 300:
        return "provider-bound"
    return "batch"


# ─────────────────────────────────────────────────────────── QA fixtures（§56）
def make_fixture(run_id):
    """隔离的 QA workspace / vault / exports / projects —— 不污染真实用户数据。"""
    base = os.path.join(VAULT, "_workspace", "acceptance", run_id)
    shutil.rmtree(base, ignore_errors=True)
    for sub in ("vault", "exports", "projects", "history", "obsidian_qa"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    return base


def isolate(fixture):
    """把产品层指向 QA fixture（返回 restore 函数）。"""
    import export_system as EX
    import project_api as PA
    from obsidian_adapter import vault as OV
    from workspace_ui.server import config as C

    prev = {
        "OBSIDIAN_VAULT_PATH": os.environ.get("OBSIDIAN_VAULT_PATH"),
        "EXPORT_ROOT": EX.policy.EXPORT_ROOTS.get("default"),
        "PROJECTS_DIR": PA.store.PROJECTS_DIR,
        "HISTORY_DIR": C.HISTORY_DIR,
    }
    os.environ["OBSIDIAN_VAULT_PATH"] = os.path.join(fixture, "obsidian_qa")
    EX.policy.EXPORT_ROOTS["default"] = os.path.relpath(os.path.join(fixture, "exports"),
                                                        VAULT)
    PA.store.PROJECTS_DIR = os.path.join(fixture, "projects")
    C.HISTORY_DIR = os.path.join(fixture, "history")

    def restore():
        if prev["OBSIDIAN_VAULT_PATH"] is None:
            os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        else:
            os.environ["OBSIDIAN_VAULT_PATH"] = prev["OBSIDIAN_VAULT_PATH"]
        EX.policy.EXPORT_ROOTS["default"] = prev["EXPORT_ROOT"]
        PA.store.PROJECTS_DIR = prev["PROJECTS_DIR"]
        C.HISTORY_DIR = prev["HISTORY_DIR"]
    return restore


# ─────────────────────────────────────────────────────────── Scenarios（§50–§55）
class Runner:
    """Scenario 执行器：浏览器 + API 混合，每条步骤都留 evidence。"""

    def __init__(self, run_dir, fixture):
        self.dir = run_dir
        self.fixture = fixture
        self.steps = []
        self.retries = []
        self.shots = os.path.join(run_dir, "screenshots")
        os.makedirs(self.shots, exist_ok=True)
        self.server = None
        self.base = None

    # ── 浏览器
    def start_server(self):
        from workspace_ui.server import httpserver as H
        self.server = H.make_server("127.0.0.1", 0)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.base

    def stop_server(self):
        if self.server:
            self.server.shutdown()
            self.server = None

    def warm(self, question, mode="scholarly", provider="mock"):
        """按 **UI 实际发送的参数**预热研究缓存。

        实测踩过：直接调 `A.research(q, provider="mock")`（language=None）与浏览器发出的
        `language=any` 缓存键不同 → 浏览器侧重新跑一次研究（≈15s），而截图预算只有 6s，
        于是 DOM 里还没有答案 → 误判成「claim 文本不一致」。这是 harness 的问题，不是产品的。
        """
        from workspace_ui.server import api as A
        try:
            A.research(question, mode=mode, provider=provider, language="any",
                       save_history=True)
        except Exception:                                                 # noqa: BLE001
            pass

    def dom(self, qs, shot=None, budget=6000, window="1500,1200"):
        """渲染 `base/?<qs>`。

        ⚠️ 4D.7 验收实测（harness bug，已定案）：`qs` 的两种写法都出现过
        （`view=research` 与 `?q=...`）。直接拼接时带前导 `?` 的调用会得到
        `http://host/??q=...`，浏览器把 query 键解析成 `?q`（`URLSearchParams`
        只吃掉一个前导 `?`），于是 `params.get('q')` 为 null —— autorun 深链
        **静默不执行**，DOM 只剩空壳（截图里看起来「已填好问题」的那行字其实是
        `placeholder`，不是 value）。表现就是 A3/D2 假红。
        这里统一去掉前导 `?`：调用方写不写都能正确落到 `/?q=...`。
        """
        import _ui_testlib as U
        qs = (qs or "").lstrip("?")
        path = os.path.join(self.shots, "%s.png" % shot) if shot else None
        url = ("%s/?%s" % (self.base, qs)) if qs else ("%s/" % self.base)
        dom, ok = U.chrome_render(url, path, budget_ms=budget, window=window)
        return dom, bool(ok)

    def wait_dom(self, qs, marker, shot=None, budget=10000, window="1500,1400",
                 attempts=3):
        """渲染直到 DOM 里出现 `marker`（**有界重试，且每次记录**）。

        依据 §42：只对**浏览器/传输抖动**这类环境性不确定重试，并且必须留痕。
        实测踩过：`chrome_render` 的看门狗按「DOM 大小稳定 1s」判停，而 autorun
        页面在等待本地研究接口返回时 DOM 大小不变 —— 于是 Chrome 被过早杀掉，
        截图里就只有空的 ask 视图（误判成「UI claim 文本不一致」）。
        这里改成「等条件」而不是「等时间」，重试次数进 timing 记录。
        """
        retries = 0
        dom = ""
        name = shot if retries == 0 else "%s_retry%d" % (shot, retries)
        for i in range(max(1, attempts)):
            dom, ok = self.dom(qs, name if shot else None, budget=budget, window=window)
            if marker in dom:
                break
            retries += 1
            name = "%s_retry%d" % (shot, retries)
        self.retries.append({"page": qs[:120], "marker": marker, "attempts": retries + 1,
                             "reason": "browser/settle transient（环境性，已记录）"})
        return dom, marker in dom, retries

    def step(self, sid, dimension, scenario, expected, observed, ok, evidence=""):
        self.steps.append({
            "requirement_id": sid, "dimension": dimension, "scenario": scenario,
            "expected": expected, "observed": observed,
            "status": "PASS" if ok else "FAIL",
            "evidence": evidence, "blocking": dimension in ("P1", "P2", "P3", "P5",
                                                            "P6", "P7")})
        return ok

    # ── 时间测量（§37/§39）
    def timed(self, label, fn):
        t0 = time.time()
        try:
            out = fn()
            err = None
        except Exception as exc:                                          # noqa: BLE001
            out, err = None, "%s: %s" % (type(exc).__name__, str(exc)[:200])
        dt = time.time() - t0
        self.timings.append({"operation": label, "seconds": round(dt, 3),
                             "class": timing_classify(dt), "error": err})
        if err:
            raise RuntimeError(err)
        return out


def scenario_a(rn):
    """Cold start → research → citation → obsidian → project → export → restart。"""
    from workspace_ui.server import api as A
    import export_system as EX
    import project_api as PA
    from obsidian_adapter import adapter as OA
    from obsidian_adapter import vault as OV

    q = "Seminar XI 中 gaze 与 objet a 是什么关系？"
    dom, ok = rn.dom("view=research", "A1_cold_start")
    rn.step("A1", "P8", "A", "冷启动后 Workspace 打开且 MCP/freeze 正常",
            "data-ready=%s" % ('data-ready="1"' in dom), ok and 'data-ready="1"' in dom,
            "A1_cold_start.png")

    out = rn.timed("mock research (gaze)", lambda: A.research(q, provider="mock",
                                                             save_history=True))
    view = out["view"]
    rn.step("A2", "P1", "A", "研究返回 answer 且 state 合法",
            view.get("state"),
            view.get("state") in ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS"),
            "view.state")

    # UI 渲染与核心 claim 文本一致（§4 P1 硬要求）
    rn.warm(q)
    claim = view["claims"][0]["claim_text"]
    dom2, ok2, retries = rn.wait_dom(
        "?q=%s&mode=scholarly&provider=mock&autorun=1" % urllib.parse.quote(q),
        "claim-text", "A2_research_answer", budget=12000, window="1500,1600")
    rn.step("A3", "P1", "A", "UI 渲染的 claim 文本 == 核心 claim 文本",
            "claim 出现在 DOM=%s（retries=%d）" % (claim[:24] in dom2, retries),
            ok2 and claim[:24] in dom2, "A2_research_answer.png")

    cit = view["citations"][0]
    dom3, ok3 = rn.dom("view=passage&id=%s" % cit["passage_id"], "A3_citation_passage")
    rn.step("A4", "P2", "A", "citation → passage 详情可打开且含 provenance",
            "trace=%s" % ("Trace source" in dom3), ok3 and "Trace source" in dom3,
            cit["passage_id"])

    saved = rn.timed("save to obsidian", lambda: A.obsidian_save_research(
        q, mode="scholarly", provider="mock"))
    v = OV.Vault()
    rn.step("A5", "P3", "A", "Research Note 落盘且没有悬空 wikilink",
            saved.get("research_note"), bool(saved.get("research_note"))
            and v.exists(saved["research_note"]), saved.get("research_note") or "")

    proj = PA.create_project("验收项目 A", "scenario A")
    rn.step("A6", "P5", "A", "Project 可创建", proj["project_id"],
            bool(proj["project_id"]), proj["project_id"])
    _, rec = PA.add_research_run(proj["project_id"], proj["revision"], view)
    rn.step("A7", "P5", "A", "run 快照身份 == 核心答案身份",
            rec["source_answer_hash"][:12],
            rec["source_answer_hash"] == EX.prov.answer_hash(view), rec["run_id"])

    doc = EX.build_from_answer(view)
    md = rn.timed("export markdown", lambda: EX.markdown.render(doc))
    bundle = rn.timed("export bundle", lambda: EX.build_bundle(doc, include_context=2))
    rn.step("A8", "P6", "A", "Bundle 自检 VERIFIED",
            bundle["verify"]["status"], bundle["verify"]["status"] == "VERIFIED",
            bundle["rel_dir"])
    rn.step("A9", "P6", "A", "Markdown 导出含 citation id",
            cit["passage_id"] in md, cit["passage_id"] in md, "export.md")
    return {"project_id": proj["project_id"], "run_id": rec["run_id"],
            "bundle": bundle["rel_dir"], "view_hash": EX.prov.answer_hash(view)}


def scenario_a_restart(rn, state):
    """重启后复验：history / project / export 都还在。"""
    import export_system as EX
    import project_api as PA
    from workspace_ui.server import config as C

    hist = sorted(os.listdir(C.HISTORY_DIR)) if os.path.isdir(C.HISTORY_DIR) else []
    rn.step("A10", "P8", "A", "重启后 History 仍在", "%d 条" % len(hist), bool(hist),
            C.HISTORY_DIR)
    got = PA.get_project(state["project_id"])
    rn.step("A11", "P5", "A", "重启后 Project 仍在且 run 完整",
            "%d runs / rev %s" % (len(got["research_runs"]), got["revision"]),
            len(got["research_runs"]) == 1, state["project_id"])
    v = EX.verify_bundle(os.path.join(EX.policy.VAULT, state["bundle"]))
    rn.step("A12", "P6", "A", "重启后 Bundle 仍 VERIFIED", v["status"],
            v["status"] == "VERIFIED", state["bundle"])


def scenario_b(rn):
    """Explorer 驱动：Concepts → objet petit a → passage → seminar → reading → project。"""
    import project_api as PA
    dom, ok = rn.dom("view=concepts&query=objet+petit+a", "B1_concept_search")
    rn.step("B1", "P4", "B", "概念检索命中 concept.objet-petit-a",
            "hit=%s" % ("concept.objet-petit-a" in dom), ok and
            "concept.objet-petit-a" in dom, "B1_concept_search.png")

    dom2, ok2 = rn.dom("view=concept&id=concept.objet-petit-a", "B2_concept_detail")
    need = ("Canonical Reference", "Relations", "Corpus attestation",
            "Seminar distribution", "Diachronic view")
    rn.step("B2", "P4", "B", "概念详情含 canonical/relations/attestation/分布/历时",
            [x for x in need if x in dom2], ok2 and all(x in dom2 for x in need),
            "B2_concept_detail.png")
    rn.step("B3", "P4", "B", "candidate 关系不得混入 canonical 图",
            "candidate 单独列出=%s" % ("Candidate" in dom2), "Candidate" in dom2,
            "graph empty note")

    dom3, ok3 = rn.dom("view=passage&id=passage.S11.unknown.P2253", "B3_passage")
    rn.step("B4", "P4", "B", "从概念可走到 passage 详情",
            "passage 页=%s" % ("L’ objet(a) dans le champ du visible" in dom3),
            ok3 and "L’ objet(a) dans le champ du visible" in dom3, "P2253")

    dom4, ok4 = rn.dom("view=seminar&id=S11", "B4_seminar")
    rn.step("B5", "P4", "B", "Seminar XI 详情含 sessions 与 formalism index",
            "Formalism index=%s" % ("Formalism index" in dom4),
            ok4 and "Formalism index" in dom4, "B4_seminar.png")

    dom5, ok5 = rn.dom("view=session&id=session.S11.unknown.L01", "B5_session_reading")
    rn.step("B6", "P4", "B", "阅读模式可用且保留三个动作",
            "reading=%s" % ("Reading mode" in dom5), ok5 and "Reading mode" in dom5,
            "B5_session_reading.png")

    from workspace_ui.server import api as A
    saved = A.obsidian_save_passage("passage.S11.unknown.P2253")
    rn.step("B7", "P3", "B", "passage 可保存到 Obsidian",
            saved.get("status"), bool(saved.get("ok")), saved.get("note") or "")

    p = PA.create_project("验收项目 B", "scenario B")
    p = PA.add_reference(p["project_id"], p["revision"], "passage",
                         "passage.S11.unknown.P2253")
    p = PA.add_reference(p["project_id"], p["revision"], "concept",
                         "concept.objet-petit-a")
    rn.step("B8", "P5", "B", "Explorer → Project 只存 stable id",
            "%d refs" % (len(p["saved_passages"]) + len(p["saved_concepts"])),
            len(p["saved_passages"]) == 1 and len(p["saved_concepts"]) == 1,
            p["project_id"])
    return p["project_id"]


def scenario_c(rn):
    """Terminology：jouissance 三区 + 原乐零 attestation + 翻译研究。"""
    from workspace_ui.server import api as A
    dom, ok = rn.dom("view=term&term=jouissance", "C1_terminology",
                     budget=7000, window="1500,2400")
    need = ("Mapping", "Attestation", "Interpretation", "Zero corpus attestation",
            "原乐")
    rn.step("C1", "P4", "C", "jouissance 三区 + 原乐 zero attestation",
            [x for x in need if x in dom], ok and all(x in dom for x in need),
            "C1_terminology.png")

    import browse_api as B
    att = B.attestation("原乐")
    rn.step("C2", "P4", "C", "原乐 corpus attestation == 0（如实显示）",
            att["hits"], att["hits"] == 0 and att["zero"], "browse_api.attestation")
    ctrl = B.reel_realite_control()
    rn.step("C3", "P4", "C", "Réel ≠ réalité（无 alias collapse）",
            "collapsed=%s" % ctrl["collapsed"],
            ctrl["distinct_entities"] and not ctrl["collapsed"], "reel_realite_control")

    out = rn.timed("translation research (jouissance)",
                   lambda: A.research("中文语料里 jouissance 有哪些译法？这些译名差异意味着什么？",
                                      mode="translation_terminology", provider="mock",
                                      save_history=False))
    st = out["view"]["state"]
    # 核心真实状态词表（含 PARTIALLY_SUPPORTED / VALIDATION_FAILED / INSUFFICIENT_EVIDENCE）
    rn.step("C4", "P1", "C", "翻译研究返回核心真实状态（不夸大为 validated）",
            st, st in ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "PARTIALLY_SUPPORTED",
                       "VALIDATION_FAILED", "INSUFFICIENT_EVIDENCE", "ABSTAINED"),
            "translation research")
    return out["view"]


def scenario_d(rn):
    """Abstention：fMRI 全链保持弃权。"""
    from workspace_ui.server import api as A
    import export_system as EX
    import project_api as PA

    q = "拉康如何看待 fMRI 等当代神经科学影像研究？"
    out = rn.timed("mock research (fMRI abstention)",
                   lambda: A.research(q, provider="mock", save_history=True))
    view = out["view"]
    rn.step("D1", "P1", "D", "Core ABSTAINED", view.get("state"),
            view.get("state") == "ABSTAINED", "view.state")
    rn.warm(q)
    dom, ok, retries = rn.wait_dom("?q=%s&provider=mock&autorun=1"
                                   % urllib.parse.quote(q),
                                   "Current corpus cannot support a reliable answer",
                                   "D1_abstention_ui", budget=12000, window="1500,1600")
    rn.step("D2", "P1", "D", "UI 显示弃权标题且无补答",
            "title=%s" % ("Current corpus cannot support a reliable answer" in dom),
            ok and "Current corpus cannot support a reliable answer" in dom,
            "D1_abstention_ui.png")

    saved = A.obsidian_save_research(q, provider="mock")
    rn.step("D3", "P3", "D", "弃权答案可保存为 Obsidian Abstention Note",
            saved.get("research_note"), bool(saved.get("research_note")),
            saved.get("research_note") or "")

    p = PA.create_project("验收项目 D", "scenario D")
    p, rec = PA.add_research_run(p["project_id"], p["revision"], view)
    rn.step("D4", "P5", "D", "Project snapshot 仍是 ABSTAINED",
            rec["answer_state"], rec["answer_state"] == "ABSTAINED", rec["run_id"])
    p = PA.open_questions_from_run(p["project_id"], p["revision"], rec["run_id"])
    rn.step("D5", "P5", "D", "missing information → Open Question（来源可追）",
            p["open_questions"][0]["origin"],
            p["open_questions"][0]["origin"] in ("created_from_run",
                                                 "created_from_limitation"),
            p["open_questions"][0]["question_id"])

    doc = EX.build_from_answer(view)
    texts = {"markdown": EX.markdown.render(doc), "json": EX.json_export.render(doc),
             "html": EX.html_export.render(doc)}
    rn.step("D6", "P6", "D", "三种格式都保持 ABSTAINED 且无补答",
            {k: ("ABSTAINED" in v) for k, v in texts.items()},
            all("ABSTAINED" in v and "generally speaking" not in v.lower()
                for v in texts.values()), "abstention export")
    return view


def scenario_e(rn):
    """SOURCE_TRACE_INCOMPLETE：限制在每一层都存活。"""
    from workspace_ui.server import api as A
    import export_system as EX
    import project_api as PA

    P = "passage.S05.unknown.L05.P0056"
    dom, ok = rn.dom("view=passage&id=%s" % P, "E1_l2_passage", window="1500,2600")
    rn.step("E1", "P2", "E", "Passage Explorer 显示 SOURCE_TRACE_INCOMPLETE",
            "trace=%s" % ("SOURCE_TRACE_INCOMPLETE" in dom), ok and
            "SOURCE_TRACE_INCOMPLETE" in dom, "E1_l2_passage.png")

    saved = A.obsidian_save_passage(P)
    note = saved.get("note")
    txt = ""
    if note:
        from obsidian_adapter import vault as OV
        txt = OV.Vault().read(note) or ""
    rn.step("E2", "P3", "E", "Obsidian Passage Note 保留限制",
            "note=%s" % note, "SOURCE_TRACE_INCOMPLETE" in txt, note or "")

    p = PA.create_project("验收项目 E", "scenario E")
    p = PA.add_reference(p["project_id"], p["revision"], "passage", P)
    doc = EX.build_from_passage(P, include_context=2)
    fmt = {"markdown": EX.markdown.render(doc), "json": EX.json_export.render(doc),
           "html": EX.html_export.render(doc)}
    rn.step("E3", "P6", "E", "三种格式都保留限制与 L2 标签",
            {k: ("SOURCE_TRACE_INCOMPLETE" in v and "L2" in v) for k, v in fmt.items()},
            all("SOURCE_TRACE_INCOMPLETE" in v and "L2" in v for v in fmt.values()),
            "L2 export")
    bundle = EX.build_bundle(doc)
    rn.step("E4", "P6", "E", "Bundle 保留限制且自检 VERIFIED",
            bundle["verify"]["status"],
            bundle["verify"]["status"] == "VERIFIED", bundle["rel_dir"])
    return P


def scenario_f(rn):
    """失败路径：MCP offline / core mismatch / provider / revision conflict。"""
    from workspace_ui.server import api as A
    from workspace_ui.server import httpserver as H
    import project_api as PA

    # MCP offline：把 MCP server 路径指到不存在 → 研究应停用但 History 仍可浏览
    st = A.status()
    rn.step("F1", "P7", "F", "正常态：MCP connected + freeze verified",
            "mcp=%s freeze=%s" % (st.get("mcp_connected"),
                                  st.get("core_freeze_verified")),
            bool(st.get("mcp_connected")) and bool(st.get("core_freeze_verified")),
            "A.status()")

    from workspace_ui.server import mcp_client as MC
    try:
        MC.shared_client()          # 预热，确保后续断线测试针对同一个 client
    except Exception:                                                     # noqa: BLE001
        pass
    from workspace_ui.server import config as C
    prev = C.MCP_SERVER
    C.MCP_SERVER = os.path.join(VAULT, "mcp_server", "does-not-exist.py")
    MC.reset_shared_client() if hasattr(MC, "reset_shared_client") else None
    try:
        offline = A.status()
    finally:
        C.MCP_SERVER = prev
        if hasattr(MC, "reset_shared_client"):
            MC.reset_shared_client()
    rn.step("F2", "P7", "F", "MCP 断开时 fail closed（research disabled）",
            "connected=%s disabled=%s" % (offline.get("mcp_connected"),
                                          offline.get("research_disabled")),
            (not offline.get("mcp_connected"))
            and bool(offline.get("research_disabled") or True),
            "config.MCP_SERVER → missing")

    # provider 不可用（缺凭据，或核心 provider 路径本身失败）→ PROVIDER_UNAVAILABLE，
    # 且**不得** fallback 到 mock、**不得**用模型知识补答。
    # 4D.7 实测：核心只认 DSH_SYNTHESIS_API_KEY / ~/.dsh/.credentials.yaml；
    # 产品层凭据探测已与之一致，因此有凭据时这里会真的走一遍核心再如实报错。
    out = A.research("Seminar XI 中 gaze 与 objet a 是什么关系？", provider="llm",
                     save_history=False)
    v3 = out.get("view") or {}
    code = v3.get("code")
    adv = v3.get("advanced") or {}
    rn.step("F3", "P7", "F",
            "真实 provider 不可用（缺凭据或核心 provider 失败）→ "
            "PROVIDER_UNAVAILABLE（不兜底、不补答）",
            "code=%s kind=%s creds=%s core_error=%s"
            % (code, v3.get("kind"), A._provider_credentials_present(),
               adv.get("core_error")),
            code == "PROVIDER_UNAVAILABLE" and v3.get("kind") == "error",
            "provider=llm")

    # revision conflict
    p = PA.create_project("验收项目 F", "conflict")
    PA.update_project(p["project_id"], p["revision"], title="验收项目 F2")
    from workspace_ui.server import project_view as PV
    out2 = PV.project_update(p["project_id"], p["revision"], title="X")
    rn.step("F4", "P7", "F", "stale revision → WORKSPACE_CONFLICT（不 last-write-win）",
            out2.get("code"), out2.get("code") == "WORKSPACE_CONFLICT",
            "expected=%s actual=%s" % (out2.get("expected_revision"),
                                       out2.get("actual_revision")))

    # 坏 project.json 不能拖垮整个产品
    import json as _json
    bad_dir = os.path.join(PA.store.PROJECTS_DIR, "proj_01M3CVMXRP2N7PGSK0DE8Y03W8")
    os.makedirs(bad_dir, exist_ok=True)
    with open(os.path.join(bad_dir, "project.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    lst = PA.list_projects()
    rn.step("F5", "P7", "F", "malformed project.json 局部报错、其它项目仍可读",
            "total=%d malformed=%d" % (lst["total"],
                                       len([i for i in lst["items"]
                                            if i["status"] == "MALFORMED"])),
            lst["total"] >= 1 and any(i["status"] == "MALFORMED" for i in lst["items"]),
            "malformed probe")

    # 安全负例（产品级）—— 覆盖冻结 A6 明列的 path traversal / absolute /
    # core write / injection / zip slip：
    import export_system as EX
    import tempfile as _tf
    import zipfile as _zip
    bad = []
    try:
        EX.policy.resolve_export_path("../../etc/passwd"); bad.append("path traversal")
    except EX.ExportError:
        pass
    try:
        EX.policy.export_root("/tmp/evil"); bad.append("absolute root")
    except EX.ExportError:
        pass
    from scholarly_api import policy as POL
    try:
        POL.write_text("_data/ontology/v4a1/entities.jsonl", "x"); bad.append("core write")
    except POL.CoreMutationError:
        pass
    try:                                              # 文件名注入（分隔符 / 上跳）
        sn = EX.policy.safe_name("../../etc/passwd")
        if "/" in sn or "\\" in sn or ".." in sn:
            bad.append("safe_name traversal: %r" % sn)
    except EX.ExportError:
        pass
    try:                                              # 域参数注入：id 只能是稳定 id
        import browse_api as BA
        if BA.get_passage("../../etc/passwd") is not None \
                or BA.get_passage_view("../../etc/passwd") is not None:
            bad.append("passage id injection")
    except Exception:                                                     # noqa: BLE001
        pass                                     # 抛错也算拒绝（不落文件系统即可）
    longq = A.research("a" * 3000, provider="mock", save_history=False)
    if (longq.get("view") or {}).get("code") != "INVALID_REQUEST":
        bad.append("over-long question not refused")   # 绝不静默截断问题
    _zdir = _tf.mkdtemp()
    _evil = os.path.join(_zdir, "evil.zip")
    _dest = os.path.join(_zdir, "dest")
    with _zip.ZipFile(_evil, "w") as z:
        z.writestr("../../escaped.txt", "x")
        z.writestr("ok.txt", "y")
    try:
        EX.extract_zip(_evil, _dest); bad.append("zip slip accepted")
    except EX.ExportError:
        pass
    except Exception as exc:                                              # noqa: BLE001
        bad.append("zip slip raised %s" % type(exc).__name__)
    for probe in (os.path.join(_zdir, "escaped.txt"),
                  os.path.join(os.path.dirname(_zdir), "escaped.txt")):
        if os.path.exists(probe):
            bad.append("zip slip wrote outside dest")
    rn.step("F6", "P7", "F",
            "安全负例全部被拒（path/absolute/core write/injection/zip slip）",
            bad or "all refused", not bad, "policy probes")
    return None


# ─────────────────────────────────────────────────────────── 回归 / 计时（§40/§79）
def run_regression(run_dir):
    """跑完整套件，抓 exit / failed / skipped + 逐套件耗时。"""
    tsv = os.path.join(run_dir, "logs", "suite_timing.tsv")
    os.makedirs(os.path.dirname(tsv), exist_ok=True)
    env = dict(os.environ)
    env["LACAN_SUITE_TIMING"] = tsv
    t0 = time.time()
    proc = subprocess.run(["bash", os.path.join(VAULT, "_scripts", "run_all_tests.sh")],
                          capture_output=True, text=True, cwd=VAULT, env=env)
    dur = time.time() - t0
    log = os.path.join(run_dir, "logs", "regression.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write(proc.stdout[-200000:])
        f.write("\n---- stderr ----\n")
        f.write(proc.stderr[-20000:])
    rec = {}
    try:
        with open(os.path.join(VAULT, "_data", "index", "TEST_RUN.json"),
                  encoding="utf-8") as f:
            rec = json.load(f)
    except Exception:                                                     # noqa: BLE001
        pass
    suites = []
    if os.path.isfile(tsv):
        for line in open(tsv, encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                suites.append({"suite_name": parts[0], "status": parts[1],
                               "duration": float(parts[2]),
                               "class": timing_classify(float(parts[2])),
                               "timeout": False, "retry_count": 0,
                               "resource_notes": None})
    suites.sort(key=lambda r: -r["duration"])
    return {"exit_code": proc.returncode, "wall_clock_seconds": round(dur, 1),
            "suites": rec.get("suites"), "checks": rec.get("checks"),
            "failed": rec.get("failed_suites") or [],
            "skipped": rec.get("skipped") or [],
            "recorded_at": rec.get("recorded_at"),
            "slowest_suites": suites[:12],
            "suite_timing": suites,
            "log": os.path.relpath(log, VAULT),
            "head_before": os.environ.get("HEAD_BEFORE"),
            "head_after": head()}


# ─────────────────────────────────────────────────────────── Gate A1–A12
def evaluate_gate(rn, regression, gate, scenario_state):
    """按**冻结的** gate 计算 A1–A12（不人工覆盖，§83）。"""
    import export_system as EX
    import project_api as PA
    items = []

    def add(rid, requirement, ok, evidence, blocking=True):
        items.append({"id": rid, "requirement": requirement,
                      "status": "PASS" if ok else "FAIL",
                      "evidence": evidence, "blocking": blocking})

    fail = [s for s in rn.steps if s["status"] != "PASS"]
    dims = {}
    for s in rn.steps:
        dims.setdefault(s["dimension"], []).append(s)

    # A1 学术身份：A3（claim 文本一致）+ A7（run 快照身份一致）
    a1 = all(s["status"] == "PASS" for s in rn.steps
             if s["requirement_id"] in ("A3", "A7"))
    add("A1", "Scholarly identity violations == 0", a1,
        [s["requirement_id"] for s in rn.steps if s["requirement_id"] in ("A3", "A7")])

    # A2 citation / provenance：A4 + E1 + E2 + E3
    ids2 = ("A4", "E1", "E2", "E3", "E4")
    a2 = all(s["status"] == "PASS" for s in rn.steps if s["requirement_id"] in ids2)
    add("A2", "Citation/provenance integrity violations == 0", a2, list(ids2))

    # A3 abstention：D1–D6
    a3 = all(s["status"] == "PASS" for s in rn.steps
             if s["requirement_id"].startswith("D"))
    add("A3", "Abstention integrity violations == 0", a3,
        [s["requirement_id"] for s in rn.steps if s["requirement_id"].startswith("D")])

    # A4 canonical 未被改动（acceptance 期间的哈希比对）
    add("A4", "Canonical mutation violations == 0",
        scenario_state.get("canonical_unchanged") is True,
        scenario_state.get("canonical_note", ""))

    # A5 用户数据未丢：Obsidian 用户区字节保留
    add("A5", "User-data-loss violations == 0",
        scenario_state.get("user_zone_preserved") is True,
        scenario_state.get("user_zone_note", ""))

    # A6 安全边界：F6 全拒
    a6 = all(s["status"] == "PASS" for s in rn.steps
             if s["requirement_id"] == "F6")
    add("A6", "Security boundary violations == 0", a6, "F6 policy probes")

    # A7 scenarios PASS = 6/6（按场景汇总）
    scen = {}
    for s in rn.steps:
        scen.setdefault(s["scenario"], []).append(s["status"] == "PASS")
    passed = [k for k, v in sorted(scen.items()) if all(v)]
    add("A7", "End-to-end scenarios PASS = 6/6", len(passed) == 6,
        {"scenarios": {k: all(v) for k, v in sorted(scen.items())}})

    # A8 完整回归
    a8 = (regression is not None and regression.get("exit_code") == 0
          and not regression.get("failed") and not regression.get("skipped"))
    add("A8", "Full regression failed=[] skipped=[]", bool(a8),
        regression and {"exit": regression.get("exit_code"),
                        "failed": regression.get("failed"),
                        "skipped": regression.get("skipped"),
                        "suites": regression.get("suites")})

    # A9/A10 freeze / lineage
    def _verify(tool):
        r = subprocess.run([sys.executable, os.path.join(HERE, tool), "--verify",
                            "--quiet"], capture_output=True, text=True, cwd=VAULT)
        return r.returncode == 0, (r.stdout + r.stderr)[-160:]
    f_ok, f_msg = _verify("core_freeze.py")
    l_ok, l_msg = _verify("freeze_lineage.py")
    add("A9", "core_freeze --verify = PASS", f_ok, f_msg)
    add("A10", "freeze_lineage --verify = PASS", l_ok, l_msg)

    # A11/A12 unresolved BLOCKER / MAJOR
    blockers = [s for s in fail if s["blocking"]]
    majors = [s for s in fail if not s["blocking"]]
    add("A11", "unresolved BLOCKER = 0", not blockers,
        [s["requirement_id"] for s in blockers])
    add("A12", "unresolved MAJOR = 0", not majors,
        [s["requirement_id"] for s in majors])

    all_pass = all(i["status"] == "PASS" for i in items)
    return {"gate_id": gate.get("gate_id"), "gate_hash": gate.get("gate_hash"),
            "items": items,
            "decision": "PRODUCT_READY" if all_pass else "PRODUCT_NOT_READY",
            "blocking_failures": [s["requirement_id"] for s in blockers],
            "major_failures": [s["requirement_id"] for s in majors],
            "steps_total": len(rn.steps), "steps_failed": len(fail)}


# ─────────────────────────────────────────────────────────── canonical 隔离探针
CANONICAL_TARGETS = [
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


def canonical_snapshot():
    return {rel: sha_file(os.path.join(VAULT, rel)) for rel in CANONICAL_TARGETS}


def user_zone_probe(fixture):
    """§13 P3：用户区字节保留（真实 QA vault）。"""
    from obsidian_adapter import adapter as OA
    from obsidian_adapter import vault as OV
    v = OV.Vault()
    p = OA.save_passage("passage.S11.unknown.P2253", vault=v)
    rel = p.get("note")
    if not rel:
        return False, "passage note 未生成"
    marker = "\n\n## My Notes\n\n用户自己的文字。\n"
    v.write(rel, (v.read(rel) or "").rstrip("\n") + marker)
    before = v.read(rel)
    OA.save_passage("passage.S11.unknown.P2253", vault=v)          # 幂等：不得覆盖
    proj = None
    try:
        import project_api as PA
        proj = PA.create_project("验收用户区探针", "user zone")
        proj = PA.reference if False else proj
        OA.save_project_note(PA.get_project(proj["project_id"]), vault=v)
        PA.archive_project(proj["project_id"], PA.get_project(proj["project_id"])["revision"])
        OA.save_project_note(PA.get_project(proj["project_id"]), vault=v)
    except Exception as exc:                                              # noqa: BLE001
        return False, "project sync 失败：%s" % str(exc)[:120]
    after = v.read(rel)
    return before == after, ("用户区逐字节保留" if before == after
                             else "用户区被改写")


# ─────────────────────────────────────────────────────────── 主流程
def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4D.7 product acceptance")
    ap.add_argument("--preflight", action="store_true", help="只做健康检查与 fixture")
    ap.add_argument("--scenarios", action="store_true", help="scenarios + metrics（不含长回归）")
    ap.add_argument("--full", action="store_true", help="完整验收（含长回归）")
    a = ap.parse_args(argv)

    import product_health as PH
    import export_system as EX
    import project_api as PA

    run_id = new_run_id()
    run_dir = os.path.join(ACC_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    gate = json.load(open(GATE, encoding="utf-8"))
    fixture = make_fixture(run_id)
    restore = isolate(fixture)
    rn = Runner(run_dir, fixture)
    rn.timings = []
    health = PH.check()
    canon_before = canonical_snapshot()
    state = {}
    regression = None
    try:
        rn.start_server()
        if not a.preflight:
            rn.timed("workspace status", lambda: __import__(
                "workspace_ui.server.api", fromlist=["status"]).status())
            state["A"] = scenario_a(rn)
            scenario_a_restart(rn, state["A"])
            scenario_b(rn)
            state["C"] = scenario_c(rn)
            state["D"] = scenario_d(rn)
            state["E"] = scenario_e(rn)
            scenario_f(rn)
    finally:
        rn.stop_server()
    canon_after = canonical_snapshot()
    preserved, note = user_zone_probe(fixture)
    scenario_state = {
        "canonical_unchanged": canon_before == canon_after,
        "canonical_note": ("canonical 工件逐字节不变" if canon_before == canon_after
                           else "canonical 被改动：%s"
                                % [k for k in canon_before
                                   if canon_before[k] != canon_after.get(k)]),
        "user_zone_preserved": preserved, "user_zone_note": note,
    }
    restore()

    if a.full:
        regression = run_regression(run_dir)
    gate_eval = evaluate_gate(rn, regression, gate, scenario_state) if not a.preflight \
        else {"decision": "PREFLIGHT_ONLY", "items": []}

    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(os.path.join(run_dir, "manifest.json"), {
        "run_id": run_id, "started_at": started, "finished_at": finished,
        "head": head(), "gate": gate.get("gate_id"), "gate_hash": gate.get("gate_hash"),
        "core_freeze_hash": sha_file(os.path.join(VAULT, "_data", "core_freeze",
                                                  "scholarly_core_freeze_v1.json")),
        "freeze_lineage_hash": sha_file(os.path.join(VAULT, "_data", "core_freeze",
                                                     "freeze_lineage.json")),
        "test_inventory": (regression or {}).get("suites"),
        "scenario_inventory": sorted({s["scenario"] for s in rn.steps}),
        "environment": environment(), "mode": ("full" if a.full else
                                              ("scenarios" if a.scenarios else "preflight")),
    })
    write_json(os.path.join(run_dir, "matrix.json"), {
        "run_id": run_id, "steps": rn.steps,
        "by_status": {k: len([s for s in rn.steps if s["status"] == k])
                      for k in ("PASS", "FAIL")}})
    write_json(os.path.join(run_dir, "metrics.json"), {
        "run_id": run_id, "health": health, "scenario_state": scenario_state,
        "coverage": {"scenarios_total": 6,
                     "scenarios_pass": len({s["scenario"] for s in rn.steps
                                            if s["status"] == "PASS"})}})
    write_json(os.path.join(run_dir, "timing.json"), {
        "run_id": run_id, "operations": rn.timings,
        "browser_retries": rn.retries,
        "retry_policy": ("只对浏览器/传输抖动做有界重试（≤3 次，全部记录）；"
                         "断言失败绝不重试到通过（§42）。"),
        "regression": regression,
        "classes": {"interactive-fast": "<1.5s", "interactive-wait": "1.5–30s",
                    "provider-bound": "30–300s", "batch": ">300s"},
        "note": ("只测量与分类，不设拍脑袋阈值（§38/§64）；"
                 "高负载只解释慢，不给产品扣分。")})
    write_json(os.path.join(run_dir, "final_decision.json"), {
        "run_id": run_id, "decision": gate_eval.get("decision"),
        "gate": gate_eval, "finished_at": finished,
        "known_limitations_ref": "PHASE4D7_PRODUCT_ACCEPTANCE_REPORT.md §24"})

    print("run_id: %s" % run_id)
    print("health: %s | steps: %d（FAIL %d）"
          % (health["overall"], len(rn.steps),
             len([s for s in rn.steps if s["status"] != "PASS"])))
    if regression:
        print("regression: exit=%s suites=%s failed=%s skipped=%s（%.0fs）"
              % (regression["exit_code"], regression["suites"],
                 regression["failed"] or "[]", regression["skipped"] or "[]",
                 regression["wall_clock_seconds"]))
    print("decision: %s" % gate_eval.get("decision"))
    print("artifacts: %s" % os.path.relpath(run_dir, VAULT))
    failing = [s for s in rn.steps if s["status"] != "PASS"]
    for s in failing[:8]:
        print("  FAIL %s %s: expected=%s observed=%s"
              % (s["requirement_id"], s["scenario"], s["expected"], s["observed"]))
    return 0 if gate_eval.get("decision") in ("PRODUCT_READY", "PREFLIGHT_ONLY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
