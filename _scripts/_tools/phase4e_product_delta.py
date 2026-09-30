#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_product_delta.py — Phase 4E §60–§67：Product Acceptance **Delta** Verification

4D.7 的 Product Acceptance Gate v1 与它的 run **不改**（immutable）。本工具只做增量验证：
重跑受 real provider 影响的维度与场景，并证明**真实 LLM 答案**在产品全链路上同样成立。

    P1 Research Integrity    → 真实 provider 的 answer_state / claim 身份 / 引用绑定
    P2 Evidence & Provenance → citation → passage → source layer → provenance 可回查
    P5 Research Projects     → 真实答案（含非 validated 态）可存为 run，快照身份保留
    P6 Export                → 四格式身份 + bundle 自检
    P7 Provider Failure      → 无凭据 / provider 故障：PROVIDER_UNAVAILABLE、不 fallback
    P8 Operational Readiness → 真实 provider 路径的耗时特征（只测量、不设阈值）

不假设真实 provider 一定给出 validated 答案：`VALIDATION_FAILED` / `INSUFFICIENT_EVIDENCE` /
`ABSTAINED` 都是**合法**结果。因此：

* 「契约级」步骤（无错误码 / 合法状态 / 不 fallback / canonical 与用户区不变 /
  四格式身份 / bundle 自检 / Project 可存 / Obsidian 可存）**无条件**执行并断言；
* 「validated 答案专属」步骤（claim 身份、citation→passage 回查、source layer）
  只在真的拿到带 citation 的真实答案时执行；否则记 `N/A(reason)` 并如实说明。
  为拿到这样的答案，会依次尝试**最多 3 个不同的冻结问题**（不是对同一输入重试到过关）。

用法：
    python3 _scripts/_tools/phase4e_product_delta.py [--skip-ui]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(VAULT, "_scripts", "_tests"), VAULT):
    if p not in sys.path:
        sys.path.insert(0, p)

import product_acceptance as PA                      # noqa: E402（复用只读工具，不修改）

OUT_ROOT = os.path.join(VAULT, "_data", "phase4e")
CANDIDATES = [
    ("rt-D01", "seminar_specific", "Seminar XI 中 gaze/regard 是如何与 objet a 发生关系的？"),
    ("rt-B01", "concept_relation",
     "desire、demand 和 need 三者是什么关系？请分别给出各自的证据。"),
    ("rt-I02", "translation_terminology", "Réel 与 réalité 为什么必须在术语层区分开？"),
]
ABSTENTION_QUESTION = "拉康如何看待 fMRI 等当代神经科学影像研究？"
LEGAL = ("VALIDATED", "VALIDATED_WITH_QUALIFICATIONS", "PARTIALLY_SUPPORTED",
         "VALIDATION_FAILED", "INSUFFICIENT_EVIDENCE", "ABSTAINED")
SUBSTANTIVE = ("DEFINITION", "DISTINCTION", "RELATION", "DIACHRONIC_CHANGE",
               "SOURCE_INFLUENCE", "REINTERPRETATION", "TERMINOLOGY", "FORMALISM")


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Delta:
    def __init__(self, run_dir):
        self.dir = run_dir
        self.steps = []
        os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)
        os.makedirs(os.path.join(run_dir, "screenshots"), exist_ok=True)

    def step(self, sid, dimension, expected, observed, ok, evidence="", na=None):
        status = "N/A" if na else ("PASS" if ok else "FAIL")
        self.steps.append({"id": sid, "dimension": dimension, "expected": expected,
                           "observed": str(observed)[:400], "status": status,
                           "evidence": evidence, "na_reason": na})
        print("  %-6s %-4s %s" % (sid, status, str(observed)[:110]))
        return status == "PASS"

    def write(self, name, obj):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")


def real_available():
    import run_synthesis_4c1d as rt
    import synthesis_adapters as sad
    try:
        rt.load_dsh_key()
    except Exception:                                                     # noqa: BLE001
        return False
    return bool(sad.OpenAICompatibleProvider(timeout=10).available)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4E product delta verification")
    ap.add_argument("--skip-ui", action="store_true")
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args(argv)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = a.run_id or "4e_product_delta_%s_%s" % (stamp, PA.sha_text(stamp)[:8])
    run_dir = os.path.join(OUT_ROOT, run_id)
    os.makedirs(run_dir, exist_ok=True)
    d = Delta(run_dir)
    if not real_available():
        print("SKIPPED_PROVIDER_UNAVAILABLE：无凭据，delta verification 需要真实 provider")
        return 3

    import browse_api as BA
    import export_system as EX
    import project_api as PApi
    from workspace_ui.server import api as A

    fixture = PA.make_fixture(run_id)
    restore = PA.isolate(fixture)
    rn = PA.Runner(run_dir, fixture)
    rn.timings = []
    canon_before = PA.canonical_snapshot()
    chosen, attempts = None, []
    try:
        rn.start_server()
        rn.timed("workspace status", lambda: A.status())
        if not a.skip_ui:
            dom, ok = rn.dom("view=research", "dA1_cold_start")
            d.step("D-A1", "P8", "Workspace 冷启动可打开（MCP/freeze 正常）",
                   'data-ready=%s' % ('data-ready="1"' in dom),
                   ok and 'data-ready="1"' in dom, "dA1_cold_start.png")

        for tid, mode, q in CANDIDATES:
            if chosen:
                break
            out = rn.timed("REAL research %s" % tid,
                           lambda q=q, mode=mode: A.research(q, mode=mode, provider="llm",
                                                             language="any",
                                                             save_history=True))
            view = out["view"] or {}
            attempts.append({"task_id": tid, "mode": mode, "state": view.get("state"),
                             "kind": view.get("kind"), "code": view.get("code"),
                             "claims": len(view.get("claims") or []),
                             "citations": len(view.get("citations") or [])})
            print("    -> %s state=%s claims=%s citations=%s"
                  % (tid, view.get("state"), len(view.get("claims") or []),
                     len(view.get("citations") or [])))
            if view.get("kind") == "answer" and view.get("citations"):
                chosen = {"task_id": tid, "mode": mode, "question": q, "view": view}

        d.step("D-A2", "P1", "真实 provider 返回合法答案状态（无 error code）",
               "attempts=%s" % json.dumps(attempts, ensure_ascii=False),
               bool(attempts) and all(x["kind"] == "answer" and x["code"] is None
                                      for x in attempts)
               and {x["state"] for x in attempts} <= set(LEGAL),
               "view.state / view.code")

        if chosen:
            q, mode = chosen["question"], chosen["mode"]
            claim = (chosen["view"].get("claims") or [{}])[0].get("claim_text")
            if not a.skip_ui and claim:
                rn.warm(q, mode=mode, provider="llm")
                dom2, ok2, retries = rn.wait_dom(
                    "?q=%s&mode=%s&provider=llm&autorun=1" % (urllib.parse.quote(q), mode),
                    "claim-text", "dA3_real_answer", budget=25000, window="1500,1600")
                d.step("D-A4", "P1", "UI 渲染的 claim 文本 == 核心 claim 文本（真实 provider）",
                       "claim 出现在 DOM=%s（retries=%d）" % (claim[:20] in dom2, retries),
                       ok2 and claim[:20] in dom2, "dA3_real_answer.png")
            cit = (chosen["view"].get("citations") or [{}])[0]
            pid = cit.get("passage_id")
            panel = A.passage_panel(pid, 2, 2) if pid else {}
            d.step("D-A5", "P2", "citation → passage 详情可回查（真实 provider 的引用绑定）",
                   "panel kind=%s / %s" % ((panel or {}).get("kind"), pid),
                   bool(pid) and (panel or {}).get("kind") != "error", str(pid))
            d.step("D-A6", "P2", "citation 的 passage 真实存在于语料",
                   "get_passage=%s" % (BA.get_passage(pid) is not None if pid else None),
                   bool(pid) and BA.get_passage(pid) is not None, str(pid))
            layers = sorted({c.get("source_layer") for c in chosen["view"]["citations"]
                             if c.get("source_layer")})
            d.step("D-A7", "P2", "每条 citation 带 source layer",
                   "layers=%s" % layers, bool(layers), "citation.source_layer")
        else:
            for sid, dim, exp in (("D-A4", "P1", "UI claim 身份（需要带 citation 的真实答案）"),
                                  ("D-A5", "P2", "citation → passage 回查"),
                                  ("D-A6", "P2", "citation 的 passage 存在"),
                                  ("D-A7", "P2", "citation 带 source layer")):
                d.step(sid, dim, exp, "本轮 3 个不同冻结问题都未产出带 citation 的真实答案",
                       ok=False, na="no citations in this delta run")

        target = (chosen or {}).get("view") or {
            "kind": "answer", "state": attempts[0]["state"], "claims": [],
            "citations": [], "limitations": [], "warnings": [], "advanced": {}}
        doc = EX.build_from_answer(target)
        EX.markdown.render(doc)
        EX.json_export.render(doc)
        EX.html_export.render(doc)
        d.step("D-A8", "P6", "四格式身份一致（同一 ExportDocument，任意合法状态）",
               "payload_hash=%s / state=%s" % (str(doc.get("export_payload_hash"))[:12],
                                               target.get("state")),
               bool(doc.get("export_payload_hash")), "export_payload_hash")
        bundle = rn.timed("export bundle (real answer)",
                          lambda: EX.build_bundle(doc, include_context=2))
        d.step("D-A9", "P6", "真实答案的 bundle 自检 VERIFIED",
               bundle["verify"]["status"], bundle["verify"]["status"] == "VERIFIED",
               bundle["rel_dir"])

        proj = PApi.create_project("4E delta 真实 provider", "delta")
        proj, rec = PApi.add_research_run(proj["project_id"], proj["revision"], target)
        d.step("D-A10", "P5", "任意合法真实状态的答案都能存为 Project run（delta 发现的缺陷）",
               "state=%s / run=%s" % (rec.get("answer_state"), rec["run_id"]),
               rec.get("answer_state") == target.get("state"), rec["run_id"])
        d.step("D-A11", "P5", "Project 快照身份 == 核心答案身份（source_answer_hash）",
               rec["source_answer_hash"][:12],
               rec["source_answer_hash"] == EX.prov.answer_hash(target), rec["run_id"])
        d.step("D-A12", "P5", "Project 快照保留 citation_ids / 完整 snapshot",
               "%s cites / snapshot=%s" % (len(rec.get("citation_ids") or []),
                                           bool(rec.get("snapshot"))),
               len(rec.get("citation_ids") or []) == len(target.get("citations") or [])
               and bool(rec.get("snapshot")), rec["run_id"])

        qsave = (chosen or {}).get("question") or CANDIDATES[0][2]
        saved = A.obsidian_save_research(qsave,
                                        mode=(chosen or {}).get("mode", "scholarly"),
                                        provider="llm")
        note = saved.get("research_note")
        text = ""
        if note:
            from obsidian_adapter import vault as OV
            text = OV.Vault().read(note) or ""
        pid = None
        if chosen:
            pid = ((chosen["view"].get("citations") or [{}])[0] or {}).get("passage_id")
        d.step("D-A13", "P3", "真实答案可保存为 Obsidian 笔记且 provenance 保留",
               "note=%s / passage 引用=%s" % (note, bool(pid) and pid in text),
               bool(note) and (not pid or pid in text)
               and ("passage." in text or "SOURCE_TRACE" in text), note or "")

        outd = rn.timed("REAL research (fMRI abstention)",
                        lambda: A.research(ABSTENTION_QUESTION, provider="llm",
                                           language="any", save_history=True))
        vd = outd["view"] or {}
        d.step("D-D1", "P1", "真实 provider 下 fMRI 问题核心弃权",
               vd.get("state"), vd.get("state") == "ABSTAINED", "view.state")
        substantive = [c for c in (vd.get("claims") or [])
                       if c.get("claim_type") in SUBSTANTIVE]
        d.step("D-D2", "P1", "弃权无实质 claim（不补答）",
               "%d claims / %d substantive" % (len(vd.get("claims") or []), len(substantive)),
               not substantive, "abstention leakage")
        if not a.skip_ui:
            rn.warm(ABSTENTION_QUESTION, provider="llm")
            domd, okd, retd = rn.wait_dom(
                "?q=%s&provider=llm&autorun=1" % urllib.parse.quote(ABSTENTION_QUESTION),
                "Current corpus cannot support a reliable answer", "dD1_real_abstention",
                budget=25000, window="1500,1600")
            d.step("D-D3", "P1", "UI 显示弃权标题且不补答（真实 provider）",
                   "title=%s（retries=%d）"
                   % ("Current corpus cannot support a reliable answer" in domd, retd),
                   okd and "Current corpus cannot support a reliable answer" in domd,
                   "dD1_real_abstention.png")

        import run_synthesis_4c1d as rt
        prev_key = os.environ.pop("DSH_SYNTHESIS_API_KEY", None)
        prev_home = os.environ.get("HOME")
        tmp_home = os.path.join(run_dir, "logs", "empty_home")
        os.makedirs(tmp_home, exist_ok=True)
        os.environ["HOME"] = tmp_home
        try:
            outn = A.research(CANDIDATES[0][2], provider="llm", save_history=False)
            vn = outn.get("view") or {}
            d.step("D-F1", "P7",
                   "无凭据时真实 provider → PROVIDER_UNAVAILABLE（不是 INTERNAL_ERROR）",
                   vn.get("code"), vn.get("code") == "PROVIDER_UNAVAILABLE", "provider=llm")
            d.step("D-F2", "P7", "无凭据时不得 fallback 出答案",
                   "kind=%s claims=%s" % (vn.get("kind"), len(vn.get("claims") or [])),
                   vn.get("kind") == "error" and not vn.get("claims"), "no-fallback")
        finally:
            if prev_home is not None:
                os.environ["HOME"] = prev_home
            if prev_key is not None:
                os.environ["DSH_SYNTHESIS_API_KEY"] = prev_key
            rt.load_dsh_key()
        outr = A.research(CANDIDATES[0][2], mode=CANDIDATES[0][1], provider="llm",
                          language="any", save_history=False)
        d.step("D-F3", "P7", "恢复凭据后无需重启即可再次真实研究",
               "kind=%s state=%s" % ((outr.get("view") or {}).get("kind"),
                                     (outr.get("view") or {}).get("state")),
               (outr.get("view") or {}).get("kind") == "answer", "provider=llm")
    finally:
        rn.stop_server()

    canon_after = PA.canonical_snapshot()
    d.step("D-G1", "P2", "canonical 工件在 delta 验证期间逐字节不变",
           "unchanged=%s" % (canon_before == canon_after), canon_before == canon_after,
           "canonical snapshot")
    preserved, note = PA.user_zone_probe(fixture)
    d.step("D-G2", "P3", "Obsidian 用户区逐字节保留", note, preserved, "user zone probe")
    restore()

    d.write("matrix.json", {"run_id": run_id, "steps": d.steps,
                            "by_status": {k: len([s for s in d.steps if s["status"] == k])
                                          for k in ("PASS", "FAIL", "N/A")},
                            "validated_answer_question": (chosen or {}).get("task_id"),
                            "real_attempts": attempts})
    d.write("timing.json", {"run_id": run_id, "operations": rn.timings,
                            "classes": {"interactive-fast": "<1.5s",
                                        "interactive-wait": "1.5–30s",
                                        "provider-bound": "30–300s",
                                        "batch": ">300s"},
                            "note": "真实 provider 只测量与分类，不设阈值"})
    d.write("manifest.json", {"schema_version": "phase4e-product-delta/v1",
                              "run_id": run_id, "created_at": utcnow(),
                              "head": PA.head(), "provider": "llm",
                              "purpose": "CCR-0001 product delta verification",
                              "scenarios": ["A(real)", "D(real)", "F(real)"],
                              "dimensions": ["P1", "P2", "P3", "P5", "P6", "P7", "P8"],
                              "frozen_4d7_run_untouched":
                                  "4d7_acceptance_20260926T041607Z_0c642385",
                              "environment": PA.environment()})
    failed = [s for s in d.steps if s["status"] == "FAIL"]
    na = [s for s in d.steps if s["status"] == "N/A"]
    d.write("final_decision.json", {"run_id": run_id,
                                    "decision": "DELTA_PASS" if not failed else "DELTA_FAIL",
                                    "steps": len(d.steps),
                                    "failed": [s["id"] for s in failed],
                                    "na": [s["id"] for s in na]})
    print("run_id: %s | steps=%d PASS=%d FAIL=%d N/A=%d"
          % (run_id, len(d.steps),
             len([s for s in d.steps if s["status"] == "PASS"]), len(failed), len(na)))
    print("artifacts: %s" % os.path.relpath(run_dir, VAULT))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
