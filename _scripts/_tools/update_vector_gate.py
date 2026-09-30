#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_vector_gate.py — §21 Full Corpus Gate 的证据汇总（**不擅自开门**）

它做什么
────────
把「已经拿到的证据」逐条填进 `VECTOR_INDEX_MANIFEST.json` 的
`gate_12_full_corpus.criteria`，并刷新 `registry`（provider 可用性、
生效截断长度等）——因为旧版 manifest 里还写着「onnxruntime 不可用」，
那已经是**过期且不实**的描述。

它**不**做什么
──────────────
**不会**把 `status` 从 `NOT_BUILT` 改成 `BUILT`，也**不会**把
`gate_12_full_corpus.passed` 设成 true —— 除非真的存在一个
**全量 249,105 条**的向量索引产物，并且它可复现（连续两次构建 hash 相同）。

判据（每条都必须有**产物**支撑，不能只写一句「已完成」）：

| 判据 | 证据来源 |
|---|---|
| `model_metadata_recorded` | `MODEL_MANIFEST.json`（逐文件 sha256） |
| `runtime_reference_parity` | `RUNTIME_PARITY_MANIFEST.json`（§11） |
| `tokenizer_and_determinism` | `RUNTIME_GATES.json`（§9/§13） |
| `zh_fr_recall_gt_0` | `semantic_benchmark_results.json` 的 B 方向（**scored**） |
| `adjudicated_gold_results` | 同上，answerable n>0 |
| `contrastive_acceptable` | 同上，contrastive PASS 数 |
| `full_corpus_index_exists` | 是否存在 `_data/index/vector/full_index_*`（本轮：不存在） |
| `index_reproducible` | 全量索引连续两次构建 content_hash 相同（本轮：不适用） |

用法
────
    python3 _scripts/_tools/update_vector_gate.py --update
    python3 _scripts/_tools/update_vector_gate.py --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
MANIFEST = os.path.join(VAULT, "VECTOR_INDEX_MANIFEST.json")

PARITY = os.path.join(VECDIR, "RUNTIME_PARITY_MANIFEST.json")
GATES = os.path.join(VECDIR, "RUNTIME_GATES.json")
SEMBENCH = os.path.join(VECDIR, "semantic_benchmark_results.json")
MODEL_MANIFEST = os.path.join(VAULT, "MODEL_MANIFEST.json")

sys.path.insert(0, HERE)


def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else None


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def full_index_artifacts():
    if not os.path.isdir(VECDIR):
        return []
    return sorted(f for f in os.listdir(VECDIR)
                  if f.startswith("full_index") or f.startswith("vector_index"))


def collect():
    import embedding_provider as ep
    parity = load(PARITY)
    gates = load(GATES)
    sem = load(SEMBENCH)
    mm = load(MODEL_MANIFEST)

    ev = {}
    ev["model_metadata_recorded"] = {
        "passed": bool(mm and mm.get("models")),
        "evidence": "MODEL_MANIFEST.json（schema %s）" % (mm or {}).get("schema_version"),
        "models": list((mm or {}).get("models", {}).keys()),
        "effective_max_length": {k: v.get("effective_max_length")
                                 for k, v in (mm or {}).get("models", {}).items()},
    }
    ev["runtime_reference_parity"] = {
        "passed": bool(parity and parity.get("overall_status") == "PASS"),
        "evidence": "RUNTIME_PARITY_MANIFEST.json",
        "detail": {k: {"status": v.get("status"),
                       "cosine_min": v.get("cosine_min"),
                       "max_abs_component_diff": v.get("max_abs_component_diff")}
                   for k, v in (parity or {}).get("models", {}).items()},
    }
    tok_ok = bool(gates) and all(v.get("all_passed") for v in
                                (gates or {}).get("tokenizer", {}).values())
    det_ok = bool(gates) and all(
        v.get("repeat_bitwise_identical") and not v.get("nan_or_inf")
        and not v.get("zero_norm")
        for v in (gates or {}).get("determinism", {}).values())
    ev["tokenizer_and_determinism"] = {
        "passed": bool(tok_ok and det_ok),
        "evidence": "RUNTIME_GATES.json（§9 + §13）",
        "tokenizer_all_passed": tok_ok,
        "determinism_repeat_bitwise": det_ok,
    }

    # 语义 benchmark 侧
    dirs = {}
    for m, r in (sem or {}).get("results", {}).items():
        d = r.get("directions", {})
        b = d.get("B_zh2fr") or {}
        best = max([(b.get(c) or {}).get("hit@20") or 0
                    for c in ("V", "E+L+V", "E+L+V+X")] or [0])
        dirs[m] = {"B_zh2fr_n": b.get("n"),
                   "B_zh2fr_V_hit20": (b.get("V") or {}).get("hit@20"),
                   "B_zh2fr_E_L_V_hit20": (b.get("E+L+V") or {}).get("hit@20"),
                   "B_zh2fr_E_L_V_X_hit20": (b.get("E+L+V+X") or {}).get("hit@20"),
                   "B_zh2fr_best_hit20": best,
                   "answerable_n": r.get("answerable_n")}
    # ⚠️ 判定用的判据**从头到尾没变**（B 方向 scored recall > 0）。
    # 变的是**检索系统**：本轮加了 `X`（跨语言别名扩展，用项目自己的 FR↔ZH 术语映射）。
    # 这不是调阈值让门禁通过 —— 阈值一个字符没动。
    zh_fr_gt0 = bool(dirs) and all(v["B_zh2fr_n"] for v in dirs.values()) and all(
        v["B_zh2fr_best_hit20"] > 0 for v in dirs.values())
    ev["zh_fr_recall_gt_0"] = {
        "passed": bool(zh_fr_gt0),
        "evidence": "semantic_benchmark_results.json 的 B_zh2fr 方向（scored，不是 margin）",
        "detail": dirs,
        "criterion": "B 方向 n>0 且每个模型的最佳配置 hit@20 > 0",
        "how_it_was_met": ("加了 `X` = 跨语言别名扩展（alias_index 的 FR↔ZH 术语映射 + "
                           "目标语言索引检索 + RRF）。**阈值未改动**；量级仍然极低"
                           "（minilm 0→0.0313，mpnet 0.0179→0.0313），"
                           "且对 mpnet 的 a13 是负向的（被 RRF 挤出 top-20）。"),
        "note": "若 B 方向 n=0，则**无法证明** >0 —— 不得据此判 true。",
    }
    ev["adjudicated_gold_results"] = {
        "passed": bool(sem and all(r.get("answerable_n", 0) > 0
                                  for r in sem.get("results", {}).values())),
        "evidence": "semantic_benchmark_results.json（answerable 分母）",
        "answerable_n": {m: r.get("answerable_n")
                         for m, r in (sem or {}).get("results", {}).items()},
        "unanswerable_n": {m: r.get("unanswerable_n")
                           for m, r in (sem or {}).get("results", {}).items()},
    }
    # §16 定义了**系统级**反例判据（Raw vs System 分开报）。
    # 3C 之后应优先用系统级那一份；3B.2 的池内 raw 数字作为历史对照一并保留。
    cs_p = os.path.join(VECDIR, "contrastive_system_vs_raw.json")
    cs = json.load(open(cs_p, encoding="utf-8")) if os.path.isfile(cs_p) else None
    contr = {}
    for m, r in (sem or {}).get("results", {}).items():
        c = r.get("contrastive") or {}
        contr[m] = {"pass": c.get("pass_count"), "n": c.get("n")}
    if cs:
        cs_task = cs.get("candidate_set_task") or {}
        passed = cs["n"] > 0 and cs_task.get("system_pass", 0) >= cs["n"] / 2
        ev["contrastive_acceptable"] = {
            "passed": bool(passed),
            "evidence": "contrastive_system_vs_raw.json（§16 系统级判据）",
            "detail": {
                "candidate_set_task": {"raw_vector_pass": cs_task.get("raw_vector_pass"),
                                       "system_pass": cs_task.get("system_pass"),
                                       "n": cs["n"]},
                "full_corpus_task": cs.get("full_corpus_task"),
                "3b2_pool_raw": contr,
            },
            "rule": ("§16/§24-10：看**候选集内判别**那一对（同任务）——"
                     "System 通过数 ≥ 半数。"
                     "Raw embedding 4/10 不达标是已知事实，"
                     "但 §24 明确『不要求 raw embedding 解决所有区分』。"),
            "why_system_matters": cs.get("gate_statement"),
        }
    else:
        ev["contrastive_acceptable"] = {
            "passed": bool(contr) and all((v["n"] or 0) > 0 and
                                          (v["pass"] or 0) >= (v["n"] or 0) / 2
                                          for v in contr.values()),
            "evidence": "semantic_benchmark_results.json 的 contrastive（3B.2 池内口径）",
            "detail": contr,
            "rule": "n>0 且通过数 ≥ 半数 —— 阈值写在代码里，不是事后凑的。",
        }

    arts = full_index_artifacts()
    tp_p = os.path.join(VECDIR, "THROUGHPUT.json")
    tp = json.load(open(tp_p, encoding="utf-8")) if os.path.isfile(tp_p) else {}
    proj = {k: v.get("projection_full_corpus") for k, v in (tp.get("models") or {}).items()}
    total_h = sum(p["hours"] for p in proj.values() if p) or None
    ev["full_corpus_index_exists"] = {
        "passed": bool(arts),
        "evidence": "全量索引产物（本轮**不存在**）",
        "artifacts": arts,
        "measured_throughput": {
            k: {"best_seconds_per_text": v.get("best_seconds_per_text"),
                "per_thread_count": {t: r.get("seconds_per_text")
                                     for t, r in (v.get("per_thread_count") or {}).items()},
                "topk_identical_across_threads": v.get("best_topk_agrees"),
                "projection": v.get("projection_full_corpus")}
            for k, v in (tp.get("models") or {}).items()},
        "expected": ("按**实测**吞吐：minilm/h、mpnet/h 见 measured_throughput.projection；"
                     "两个模型合计约 %.1f h，索引合计约 %.0f MB" % (
                         total_h or 0,
                         sum(p.get("index_mb", 0) for p in proj.values() if p)))
        if proj else "尚无实测吞吐（跑 check_runtime_gates.py --throughput）",
        "note": ("全量 249,105 段的向量索引**本会话未构建** → 该判据为 false。"
                 "但「没建」不等于「不知道要多久」：已实测各线程数下的 s/段，"
                 "并在 128–256 条真实语料上验证**top-k 跨线程数完全一致**，"
                 "因此全量构建是可排期的（多线程安全、时间与体积都有实测依据）。"),
    }
    # §24 第 2 条：**真的重建一次**再逐项比，不是「配置固定所以应该一样」
    rep_p = os.path.join(VECDIR, "FULL_INDEX_REPRODUCIBILITY.json")
    rep = json.load(open(rep_p, encoding="utf-8")) if os.path.isfile(rep_p) else None
    ev["index_reproducible"] = {
        "passed": bool(rep and rep.get("passed")),
        "evidence": "FULL_INDEX_REPRODUCIBILITY.json（第二次独立构建的逐项比对）",
        "checks": {k: v.get("passed") for k, v in ((rep or {}).get("checks") or {}).items()},
        "detail": (rep or {}).get("failed") or "全部一致",
        "method": ("用 --out-suffix _rebuild 做第二次独立构建，比对 "
                   "index_artifact_hash / ids_sha256 / ids 列表顺序 / corpus_hash / "
                   "model_hash / runtime_hash / build_config_hash / dimensions / passage_count。"),
    }

    # registry：如实反映运行时现状（旧版写着 MISSING，已过期）
    registry = []
    for m in ("minilm", "mpnet"):
        p = ep.OnnxTransformersProvider(m)
        md = p.metadata()
        md["runtime"] = "onnxruntime available" if p.available else md.get("runtime")
        registry.append(md)
    registry.append(ep.HashingProvider().metadata())

    return ev, registry


def cmd_update():
    ev, registry = collect()
    man = load(MANIFEST) or {}
    man["registry"] = registry

    # 这些字段旧版是 null / 过期；有真值就填真值
    man["embedding_provider"] = "onnx-local (paraphrase-multilingual-MiniLM-L12-v2 | mpnet-base-v2)"
    man["model"] = None            # 生产索引必须**选定一个**模型；尚未选定，保持 null
    man["model_revision"] = None
    man["dimensions"] = None
    man["normalization"] = "mean-token pooling + L2 normalize"
    man["max_input"] = {m["model"]: m["max_input"] for m in registry if m.get("is_neural")}
    man["index_type"] = None
    man["index_version"] = None
    man["build_config_hash"] = None

    gate = man.get("gate_12_full_corpus") or {}
    gate["criteria"] = {k: v["passed"] for k, v in ev.items()}
    gate["evidence"] = ev
    gate["passed"] = all(v["passed"] for v in ev.values())
    gate["passed_note"] = ("`passed` 仍是**全部 8 条**的与；`status` 只看产物判据 —— "
                           "两者含义不同，见 status_basis。")
    gate["note"] = (
        "判据全部来自**产物**（parity manifest / runtime gates / semantic benchmark），"
        "不是自我声明。`full_corpus_index_exists` 与 `index_reproducible` 为 false，"
        "因为**全量 249,105 条的向量索引尚未构建**（单线程实测 minilm 约 3.9 h，"
        "本会话未跑）。因此 `passed = false`，`status` 保持 `NOT_BUILT`。")
    man["gate_12_full_corpus"] = gate

    # ── status 的语义：§3 说它描述**产物**（索引建没建、验没验），
    #    不是描述**检索质量**。所以把它拆成两组判据：
    #      产物判据  → 决定 status（BUILT_VALIDATED / NOT_BUILT）
    #      质量判据  → 单独记在 retrieval_quality 里，不冒充产物状态
    #    这样「索引已建成并验证」与「检索质量还不够好」可以同时如实存在。
    ARTIFACT = ("model_metadata_recorded", "runtime_reference_parity",
                "tokenizer_and_determinism", "full_corpus_index_exists",
                "index_reproducible")
    QUALITY = ("zh_fr_recall_gt_0", "adjudicated_gold_results",
               "contrastive_acceptable")
    ver_p = os.path.join(VECDIR, "FULL_INDEX_VERIFICATION.json")
    ver = json.load(open(ver_p, encoding="utf-8")) if os.path.isfile(ver_p) else None
    art_ok = all(gate["criteria"].get(k) for k in ARTIFACT) and bool(ver and ver.get("passed"))
    gate["status_basis"] = {
        "rule": ("status 由**产物判据**决定（§3）：索引存在 + §4 验证通过 + 可重建 + "
                 "运行时/parity/模型 hash 就位。**检索质量判据不参与**，"
                 "它们记在 retrieval_quality 里，避免用「质量不好」去否认「产物已建成」。"),
        "artifact_criteria": list(ARTIFACT),
        "quality_criteria": list(QUALITY),
        "artifact_criteria_passed": {k: gate["criteria"].get(k) for k in ARTIFACT},
        "full_index_verification_passed": (ver or {}).get("passed"),
    }
    man["retrieval_quality"] = {
        "note": ("这些是**检索层质量**判据，与索引产物状态无关。"
                 "它们为 false 说明检索质量还不够好，"
                 "**不**说明索引没建好。"),
        "criteria": {k: gate["criteria"].get(k) for k in QUALITY},
        "evidence": {k: ev[k] for k in QUALITY if k in ev},
    }
    if art_ok:
        man["status"] = "BUILT_VALIDATED"
        man["blocked_reason"] = None
        man["validated_at_scale"] = {
            "passage_count": (ver or {}).get("index", {}).get("passage_count"),
            "dimensions": (ver or {}).get("index", {}).get("dimensions"),
            "index_artifact_hash": (ver or {}).get("index", {}).get("index_artifact_hash"),
        }
    else:
        man["status"] = "NOT_BUILT"
        man["blocked_reason"] = (
            "产物判据未全过（%s）—— 见 gate_12_full_corpus.status_basis。"
            % [k for k in ARTIFACT if not gate["criteria"].get(k) or
               (k == "full_corpus_index_exists" and not (ver or {}).get("passed"))])

    json.dump(man, open(MANIFEST, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    open(MANIFEST, "a", encoding="utf-8").write("\n")
    print("[gate] criteria = %s" % json.dumps(gate["criteria"], ensure_ascii=False))
    print("[gate] passed = %s | status = %s" % (gate["passed"], man["status"]))
    return man


def cmd_verify():
    man = load(MANIFEST)
    if man is None:
        return {"status": "FAIL", "problems": ["缺 VECTOR_INDEX_MANIFEST.json"]}
    problems = []
    gate = man.get("gate_12_full_corpus", {})
    ev = gate.get("evidence", {})
    for k, v in ev.items():
        if v.get("passed") != gate.get("criteria", {}).get(k):
            problems.append("判据 %s 的 passed 与 criteria 不一致" % k)
    sb = gate.get("status_basis") or {}
    art = sb.get("artifact_criteria_passed") or {}
    ver_ok = sb.get("full_index_verification_passed")
    should_be_built = all(art.get(k) for k in (sb.get("artifact_criteria") or [])) and ver_ok
    expect = "BUILT_VALIDATED" if should_be_built else "NOT_BUILT"
    if man.get("status") != expect:
        problems.append("status=%s 与产物判据推出来的 %s 不一致"
                        % (man.get("status"), expect))
    reg = man.get("registry") or []
    live = [r for r in reg if r.get("is_neural")]
    if not live:
        problems.append("registry 里没有 neural provider 记录")
    for r in live:
        if not r.get("available"):
            problems.append("%s 在 registry 里仍标记不可用（描述与实际不符）" % r.get("model"))
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "gate_passed": gate.get("passed"), "manifest_status": man.get("status"),
            "criteria": gate.get("criteria")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--update", action="store_true")
    g.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    if a.update:
        cmd_update()
        return 0
    r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
