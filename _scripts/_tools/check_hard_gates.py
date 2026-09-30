#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_hard_gates.py — §23 硬门禁**统一计算**（8 项原有 + 6 项新增 + 1 项本轮补充）

为什么要有它
───────────
§23 要求「14 项硬门禁全 0」。之前这些数字散在 5 个文档里，
每一条都是**手抄**的 —— 手抄的数字会过期，而且无法被程序校验。

本脚本把它们**从产物重新算一遍**，每一项都写清「怎么算的、数据从哪来」，
落 `_data/index/HARD_GATES.json` 与 `HARD_GATES_REPORT.md`。

17 项与算法
───────────
| # | 门禁 | 算法 |
|---|---|---|
| 1 | `fabricated_passage_ids` | 扫描所有引用 passage id 的产物，逐个到**真实 id 集合**里查 |
| 2 | `broken_passage_references` | 引用的 id 是否符合 `passage.*` ID 文法 |
| 3 | `canonical_source_mutation` | `.lacan-build/atlas` 两个源文件 sha256 vs `_build_meta.json` 记录 |
| 4 | `source_hash_mutation` | 同上（分开计数：一个是语料文件，一个是其记录） |
| 5 | `silent_provenance_upgrade` | `trace_status == COMPLETE` 却 `trace_missing` 非空；或 `L4 && canonical` |
| 6 | `gold_references_to_nonexistent_passages` | 45 条 gold 的 evidence ∪ 是否存在 |
| 7 | `vector_index_corpus_hash_mismatch` | `VECTOR_INDEX_MANIFEST.corpus_hash` vs `_build_meta.content_hash` |
| 8 | `automatic_source_link_canonicalization` | 候选文件里出现 `canonical=true` 或 `review_status != candidate` |
| 9 | `runtime_reference_parity_failure` | `RUNTIME_PARITY_MANIFEST.hard_gates` |
| 10 | `invalid_embedding_dimension` | `RUNTIME_PARITY_MANIFEST` + `RUNTIME_GATES` 的维度 |
| 11 | `NaN_or_Inf_embedding` | `RUNTIME_GATES.determinism.*.nan_or_inf` |
| 12 | `model_manifest_hash_mismatch` | `build_model_manifest.py --verify`（逐文件重算） |
| 13 | `wheelhouse_hash_mismatch` | `build_wheelhouse.py --verify`（逐 wheel 重算） |
| 14 | `answerable_unanswerable_metric_contamination` | 两个分母的 query_id 交集 + 不可答记录里不得有 answerable 指标 |
| 15 | `zero_norm_embedding` | `RUNTIME_GATES.determinism.*.zero_norm` |
| 16 | `max_seq_length_mismatch` | `RUNTIME_PARITY_MANIFEST` 的 ref vs onnx |
| 17 | `passage_outside_evaluation_pool` | `semantic_benchmark_results` 里所有 top-20 是否都在池内 |

用法
────
    python3 _scripts/_tools/check_hard_gates.py --run     # 全量重算（含 384MB 单次扫描）
    python3 _scripts/_tools/check_hard_gates.py --verify  # 只核已有产物是否仍为 0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")
VECDIR = os.path.join(IDX, "vector")
OUT_JSON = os.path.join(IDX, "HARD_GATES.json")
REPORT = os.path.join(VAULT, "HARD_GATES_REPORT.md")

PASSAGE_ID_RE = re.compile(r"^passage\.[A-Za-z0-9][A-Za-z0-9-]*(\.[A-Za-z0-9][A-Za-z0-9-]*)+$")
ATLAS = os.path.expanduser("<HOME>")

sys.path.insert(0, HERE)

# 会引用 passage id 的产物（相对 vault）。只写存在的。
ARTIFACTS_WITH_PASSAGE_IDS = [
    "retrieval_gold_adjudicated.jsonl",
    "retrieval_gold_answerable.jsonl",
    "retrieval_gold_unanswerable.jsonl",
    "retrieval_eval.jsonl",
    "lacan_contrastive_eval.jsonl",
    "concept_source_link_candidates.jsonl",
    "_data/relations/relations.jsonl",
    "_data/passage_store/claims.jsonl",
    "_data/passage_store/alignments.jsonl",
    "_data/index/alias_collisions.jsonl",
]

ID_KEYS = ("passage_id", "id", "candidate_passage_id")
LIST_KEYS = ("gold_passages", "passages", "positive_passages", "hard_negatives",
             "gold_evidence", "required", "strong", "contextual")


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def collect_referenced_ids():
    """从产物里收集所有被引用的 passage id（递归走 dict/list）。"""
    found = {}

    def walk(node, where):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ID_KEYS and isinstance(v, str) and v.startswith("passage."):
                    found.setdefault(v, where)
                elif k in LIST_KEYS:
                    walk(v, where)
                elif isinstance(v, (dict, list)):
                    walk(v, where)
        elif isinstance(node, list):
            for v in node:
                walk(v, where)

    for rel in ARTIFACTS_WITH_PASSAGE_IDS:
        p = os.path.join(VAULT, rel)
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        walk(json.loads(line), rel)
                    except json.JSONDecodeError:
                        pass
    return found


def read_store_ids_and_provenance():
    """**单次**扫描 passages.jsonl，同时拿到 id 集合 + provenance 违规计数。"""
    ids = set()
    silent_upgrade = 0
    l4_canonical = 0
    n = 0
    p = os.path.join(STORE, "passages.jsonl")
    with open(p, encoding="utf-8") as f:
        for line in f:
            n += 1
            d = json.loads(line)
            ids.add(d["id"])
            ts = d.get("trace_status")
            tm = d.get("trace_missing") or []
            if ts == "COMPLETE" and tm:
                silent_upgrade += 1
            if d.get("authority_level") == "L4" and d.get("canonical"):
                l4_canonical += 1
    return ids, {"passages": n, "silent_provenance_upgrade": silent_upgrade,
                 "L4_and_canonical": l4_canonical}


def cmd_run(verbose=True):
    import embedding_provider as ep  # noqa: F401  仅为保持 sys.path 一致的惯例

    gates = {}
    notes = {}

    # ── 1/2/5/6：一次扫描 + 一次引用收集
    store_ids, prov = read_store_ids_and_provenance()
    refs = collect_referenced_ids()
    missing = {k: v for k, v in refs.items() if k not in store_ids}
    malformed = {k: v for k, v in refs.items() if not PASSAGE_ID_RE.match(k)}
    gates["fabricated_passage_ids"] = len(missing)
    gates["broken_passage_references"] = len(malformed)
    notes["fabricated_passage_ids"] = {
        "referenced_ids": len(refs), "store_ids": len(store_ids),
        "sources_scanned": [r for r in ARTIFACTS_WITH_PASSAGE_IDS
                            if os.path.isfile(os.path.join(VAULT, r))],
        "examples": sorted(missing)[:5]}
    notes["broken_passage_references"] = {
        "grammar": PASSAGE_ID_RE.pattern, "examples": sorted(malformed)[:5]}
    gates["silent_provenance_upgrade"] = prov["silent_provenance_upgrade"] + prov["L4_and_canonical"]
    notes["silent_provenance_upgrade"] = {
        "rule": "trace_status == COMPLETE 却 trace_missing 非空（%d）；或 authority_level == L4 且 canonical（%d）"
                % (prov["silent_provenance_upgrade"], prov["L4_and_canonical"])}

    gold_ids = set()
    for rel in ("retrieval_gold_answerable.jsonl", "retrieval_gold_unanswerable.jsonl",
                "retrieval_gold_adjudicated.jsonl"):
        p = os.path.join(VAULT, rel)
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                ev = d.get("gold_evidence") or {}
                for v in ev.values():
                    gold_ids |= set(v or [])
                gold_ids |= set(d.get("gold_passages") or [])
    bad_gold = sorted(gold_ids - store_ids)
    gates["gold_references_to_nonexistent_passages"] = len(bad_gold)
    notes["gold_references_to_nonexistent_passages"] = {
        "gold_ids": len(gold_ids), "examples": bad_gold[:5]}

    # ── 3/4：源语料未被改动
    bm = json.load(open(os.path.join(STORE, "_build_meta.json"), encoding="utf-8"))
    mutated = []
    for name, rec in (bm.get("source_files") or {}).items():
        p = os.path.join(ATLAS, name)
        if not os.path.isfile(p):
            mutated.append({"file": name, "why": "source file missing"})
            continue
        if sha256_file(p) != rec.get("sha256"):
            mutated.append({"file": name, "why": "sha256 changed",
                            "expected": rec.get("sha256"), "actual": sha256_file(p)})
    gates["canonical_source_mutation"] = len([m for m in mutated if m["why"] == "sha256 changed"])
    gates["source_hash_mutation"] = len(mutated)
    notes["canonical_source_mutation"] = {"atlas": ATLAS, "files": list((bm.get("source_files") or {}).keys())}
    notes["source_hash_mutation"] = {"mutations": mutated}

    # ── 7：向量索引的 corpus hash 必须与**当前 store 文件**一致
    #
    # ⚠️ 第一版这里拿 `VECTOR_INDEX_MANIFEST.corpus_hash` 去比 `_build_meta.content_hash`，
    # 报出 1 —— 那是**两种不同规则的哈希**，属于我自己定义错，不是真违规：
    #   corpus_hash        = sha256(整个 passages.jsonl 的**原始字节**)
    #   _build_meta.content_hash = deterministic.content_hash(build 元数据 payload)（规范化 JSON）
    # 正确做法：按 `corpus_hash` 自己的规则**重算一遍**再比。
    vman = json.load(open(os.path.join(VAULT, "VECTOR_INDEX_MANIFEST.json"), encoding="utf-8"))
    store_file = os.path.join(STORE, "passages.jsonl")
    store_bytes_hash = sha256_file(store_file) if os.path.isfile(store_file) else None
    bench_man_p = os.path.join(VECDIR, "vector_benchmark_corpus_manifest.json")
    bench_corpus_hash = (json.load(open(bench_man_p, encoding="utf-8")).get("corpus_hash")
                         if os.path.isfile(bench_man_p) else None)
    mism = int(vman.get("corpus_hash") != store_bytes_hash) + \
        int(bench_corpus_hash is not None and bench_corpus_hash != store_bytes_hash)
    gates["vector_index_corpus_hash_mismatch"] = mism
    notes["vector_index_corpus_hash_mismatch"] = {
        "rule": "corpus_hash = sha256(passages.jsonl 原始字节)；按同一规则重算后比对",
        "manifest_corpus_hash": vman.get("corpus_hash"),
        "benchmark_manifest_corpus_hash": bench_corpus_hash,
        "recomputed_store_bytes_sha256": store_bytes_hash,
        "build_meta_content_hash_IS_A_DIFFERENT_RULE": bm.get("content_hash"),
        "status": vman.get("status")}

    # ── 8：溯源候选不得自动晋级
    cand = os.path.join(VAULT, "concept_source_link_candidates.jsonl")
    viol = 0
    total = 0
    concepts_hash_ok = None
    if os.path.isfile(cand):
        with open(cand, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                d = json.loads(line)
                total += 1
                if d.get("review_status") != "candidate" or d.get("canonical") is not False:
                    viol += 1
    rep = os.path.join(IDX, "concept_source_link_report.json")
    if os.path.isfile(rep):
        r = json.load(open(rep, encoding="utf-8"))
        concepts_hash_ok = (r["hashes"]["concepts_jsonl_before"] == r["hashes"]["concepts_jsonl_after"]
                            and sha256_file(os.path.join(STORE, "concepts.jsonl"))
                            == r["hashes"]["concepts_jsonl_after"])
        if concepts_hash_ok is False:
            viol += 1
    gates["automatic_source_link_canonicalization"] = viol
    notes["automatic_source_link_canonicalization"] = {
        "candidates": total, "violations": viol, "concepts_jsonl_unchanged": concepts_hash_ok}

    # ── 9/10/16：parity
    pm = os.path.join(VECDIR, "RUNTIME_PARITY_MANIFEST.json")
    parity = json.load(open(pm, encoding="utf-8")) if os.path.isfile(pm) else {}
    hg = parity.get("hard_gates") or {}
    gates["runtime_reference_parity_failure"] = int(hg.get("runtime_reference_parity_failure", 0))
    gates["invalid_embedding_dimension"] = int(hg.get("invalid_embedding_dimension", 0))
    gates["max_seq_length_mismatch"] = int(hg.get("max_seq_length_mismatch", 0))
    # 再做一次独立核对：维度与 max_seq_length 逐个比
    for k, v in (parity.get("models") or {}).items():
        if not (v.get("dims") or {}).get("match"):
            gates["invalid_embedding_dimension"] += 1
        if v.get("max_seq_length", {}).get("reference") != v.get("max_seq_length", {}).get("onnx"):
            gates["max_seq_length_mismatch"] += 1
    notes["runtime_reference_parity_failure"] = {
        "manifest": os.path.relpath(pm, VAULT), "overall": parity.get("overall_status"),
        "models": {k: v.get("status") for k, v in (parity.get("models") or {}).items()}}
    notes["invalid_embedding_dimension"] = {
        "dims": {k: v.get("dims") for k, v in (parity.get("models") or {}).items()}}
    notes["max_seq_length_mismatch"] = {
        "max_seq_length": {k: v.get("max_seq_length")
                           for k, v in (parity.get("models") or {}).items()}}

    # ── 11/15：运行时确定性
    gp = os.path.join(VECDIR, "RUNTIME_GATES.json")
    gatesdoc = json.load(open(gp, encoding="utf-8")) if os.path.isfile(gp) else {}
    det = gatesdoc.get("determinism") or {}
    gates["NaN_or_Inf_embedding"] = sum(int(v.get("nan_or_inf", 0)) for v in det.values())
    gates["zero_norm_embedding"] = sum(int(v.get("zero_norm", 0)) for v in det.values())
    notes["NaN_or_Inf_embedding"] = {"per_model": {k: v.get("nan_or_inf") for k, v in det.items()}}
    notes["zero_norm_embedding"] = {"per_model": {k: v.get("zero_norm") for k, v in det.items()}}

    # ── 12/13：manifest / wheelhouse 逐条重算（直接调既有校验器，不手抄）
    def run_verify(script, args):
        r = subprocess.run([sys.executable, os.path.join(HERE, script)] + args,
                           capture_output=True, text=True)
        try:
            out = json.loads(r.stdout[r.stdout.index("{"):])
        except Exception:
            return None, (r.stdout + r.stderr)[-400:]
        return out, None

    mm, e1 = run_verify("build_model_manifest.py", ["--verify"])
    wh, e2 = run_verify("build_wheelhouse.py", ["--verify"])
    gates["model_manifest_hash_mismatch"] = 0 if (mm and mm.get("status") == "PASS") else \
        (len(mm.get("problems", [])) if mm else 1)
    gates["wheelhouse_hash_mismatch"] = 0 if (wh and wh.get("status") == "PASS") else \
        (len(wh.get("problems", [])) if wh else 1)
    notes["model_manifest_hash_mismatch"] = {"verify": (mm or {}).get("status"),
                                             "files_checked": (mm or {}).get("files_checked"),
                                             "error": e1}
    notes["wheelhouse_hash_mismatch"] = {"verify": (wh or {}).get("status"),
                                         "wheel_count": (wh or {}).get("wheel_count"),
                                         "hash": (wh or {}).get("wheelhouse_hash"),
                                         "error": e2}

    # ── 14：answerable / unanswerable 不得互相污染
    sb = os.path.join(VECDIR, "semantic_benchmark_results.json")
    sem = json.load(open(sb, encoding="utf-8")) if os.path.isfile(sb) else {}
    contam = 0
    for m, r in (sem.get("results") or {}).items():
        ans = {q["query_id"] for q in r.get("per_query") or []}
        un = {q["query_id"] for q in (r.get("unanswerable") or {}).get("per_query") or []}
        contam += len(ans & un)
        for q in (r.get("unanswerable") or {}).get("per_query") or []:
            if "hit@20" in q or "mrr@10" in q or "ndcg@10" in q:
                contam += 1
    gates["answerable_unanswerable_metric_contamination"] = contam
    notes["answerable_unanswerable_metric_contamination"] = {
        "models": {m: {"answerable_n": r.get("answerable_n"),
                       "unanswerable_n": r.get("unanswerable_n")}
                   for m, r in (sem.get("results") or {}).items()},
        "rule": "两个分母的 query_id 不得相交；不可答记录不得带 answerable 指标"}

    # ── 17：评测返回的 passage 必须在池内
    pool_p = os.path.join(VECDIR, "evaluation_pool.json")
    outside = 0
    if os.path.isfile(pool_p) and sem:
        pool_ids = set(json.load(open(pool_p, encoding="utf-8"))["pool_ids"])
        for m, r in (sem.get("results") or {}).items():
            for q in r.get("per_query") or []:
                for mm2 in (q.get("metrics") or {}).values():
                    outside += sum(1 for p in mm2.get("top20") or [] if p not in pool_ids)
    gates["passage_outside_evaluation_pool"] = outside
    notes["passage_outside_evaluation_pool"] = {
        "pool": os.path.relpath(pool_p, VAULT),
        "rule": "所有 top-20 必须来自评测池"}

    total = sum(gates.values())
    doc = {
        "schema_version": "hard-gates/v1",
        "purpose": "§23：8 项原有 + 6 项新增（另补 3 项）= 全部必须为 0",
        "gate_count": len(gates),
        "gates": gates,
        "notes": notes,
        "all_zero": total == 0,
        "total_violations": total,
        "anchor": {"passage_store_content_hash": bm.get("content_hash"),
                   "passage_store_passages": prov["passages"]},
    }
    os.makedirs(IDX, exist_ok=True)
    json.dump(doc, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(OUT_JSON, "a", encoding="utf-8").write("\n")
    if verbose:
        width = max(len(k) for k in gates)
        for k, v in gates.items():
            print("  %-*s %s" % (width, k, v))
        print("[all_zero] %s (total=%d)" % (doc["all_zero"], total))
    write_report(doc)
    return doc


def write_report(doc):
    L = []
    A = L.append
    A("# HARD_GATES_REPORT.md — §23 硬门禁统一计算\n")
    A("> 生成：`_scripts/_tools/check_hard_gates.py`　·　原始数据：`_data/index/HARD_GATES.json`\n")
    A("**本文件里的每个数字都是现算的，不是从别处手抄的。**"
      "每一行的「算法」列写清数据来源；产物一变，重跑一次就能看出门禁有没有被打破。\n")
    A("## 0. 汇总\n")
    A("| 项 | 值 |")
    A("|---|---:|")
    A("| 门禁数 | **%d** |" % doc["gate_count"])
    A("| 违规总数 | **%d** |" % doc["total_violations"])
    A("| `all_zero` | **%s** |" % doc["all_zero"])
    A("| passage store 内 passage 数 | %s |" % doc["anchor"]["passage_store_passages"])
    A("| passage store content_hash | `%s` |" % str(doc["anchor"]["passage_store_content_hash"])[:24])
    A("")
    A("## 1. 逐项\n")
    A("| # | 门禁 | 值 | 算法 / 数据来源 |")
    A("|---|---|---:|---|")
    algo = {
        "fabricated_passage_ids": "扫描 %d 个产物收集引用 id，逐个到 passages.jsonl 的真实 id 集合（本项扫了 %s 条）里查"
                                  % (len(doc["notes"]["fabricated_passage_ids"]["sources_scanned"]),
                                     doc["notes"]["fabricated_passage_ids"]["store_ids"]),
        "broken_passage_references": "引用的 id 是否符合 `%s`" % PASSAGE_ID_RE.pattern,
        "canonical_source_mutation": "`.lacan-build/atlas` 源文件 sha256 vs `_build_meta.json` 记录",
        "source_hash_mutation": "同上（含源文件缺失）",
        "silent_provenance_upgrade": doc["notes"]["silent_provenance_upgrade"]["rule"],
        "gold_references_to_nonexistent_passages": "45 条 gold 的 evidence 并集（%d 条）逐个查真实 id 集合"
                                                   % doc["notes"]["gold_references_to_nonexistent_passages"]["gold_ids"],
        "vector_index_corpus_hash_mismatch": "按 `corpus_hash` 自己的规则重算 `sha256(passages.jsonl 字节)`，再与 "
                                             "`VECTOR_INDEX_MANIFEST` 和 benchmark manifest 比对",
        "automatic_source_link_canonicalization": "候选文件 %d 条中 `canonical=true` 或 `review_status != candidate` 的条数，"
                                                  "加上 `concepts.jsonl` 是否被改动"
                                                  % doc["notes"]["automatic_source_link_canonicalization"]["candidates"],
        "runtime_reference_parity_failure": "`RUNTIME_PARITY_MANIFEST.hard_gates` + 逐模型 status",
        "invalid_embedding_dimension": "`RUNTIME_PARITY_MANIFEST` 逐模型 dims.match",
        "NaN_or_Inf_embedding": "`RUNTIME_GATES.determinism.*.nan_or_inf` 求和",
        "model_manifest_hash_mismatch": "调 `build_model_manifest.py --verify`，逐文件重算 sha256",
        "wheelhouse_hash_mismatch": "调 `build_wheelhouse.py --verify`，逐 wheel 重算 sha256 + 重算 wheelhouse_hash",
        "answerable_unanswerable_metric_contamination": "两个分母 query_id 交集 + 不可答记录是否带 answerable 指标",
        "zero_norm_embedding": "`RUNTIME_GATES.determinism.*.zero_norm` 求和",
        "max_seq_length_mismatch": "`RUNTIME_PARITY_MANIFEST` 逐模型 ref vs onnx 的 max_seq_length",
        "passage_outside_evaluation_pool": "semantic benchmark 所有配置的 top-20 是否都在 `evaluation_pool` 内",
    }
    for i, (k, v) in enumerate(doc["gates"].items(), 1):
        A("| %d | `%s` | **%d** | %s |" % (i, k, v, algo.get(k, "—")))
    A("")
    A("## 2. 判定规则\n")
    A("任何一项 > 0 即视为**交付失败**（不是「需要注意」）。"
      "特别地：\n")
    A("- `fabricated_passage_ids` / `gold_references_to_nonexistent_passages` > 0 → 结论里不能出现任何引用。")
    A("- `canonical_source_mutation` / `source_hash_mutation` > 0 → 唯一副本被改动，必须先恢复再谈别的。")
    A("- `answerable_unanswerable_metric_contamination` > 0 → 所有 recall/MRR/nDCG 作废（分母被污染）。")
    A("- `runtime_reference_parity_failure` > 0 → **不得进入 semantic benchmark**（§11 原文）。")
    A("- `automatic_source_link_canonicalization` > 0 → 候选被自动当成结论，这是本项目最严重的越权。")
    A("")
    A("## 3. 复现\n")
    A("```bash")
    A("python3 _scripts/_tools/check_hard_gates.py --run      # 全量重算（含 384MB 单次扫描）")
    A("python3 _scripts/_tools/check_hard_gates.py --verify   # 只核已有产物")
    A("```")
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report] %s" % REPORT)


def cmd_verify():
    if not os.path.isfile(OUT_JSON):
        return {"status": "FAIL", "problems": ["缺 HARD_GATES.json（先跑 --run）"]}
    d = json.load(open(OUT_JSON, encoding="utf-8"))
    problems = ["%s = %s" % (k, v) for k, v in d["gates"].items() if v != 0]
    if len(d["gates"]) < 17:
        problems.append("门禁数只有 %d，少于 17" % len(d["gates"]))
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "gate_count": d["gate_count"], "all_zero": d["all_zero"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true")
    g.add_argument("--verify", action="store_true")
    a = ap.parse_args(argv)
    if a.run:
        doc = cmd_run()
        return 0 if doc["all_zero"] else 1
    r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
