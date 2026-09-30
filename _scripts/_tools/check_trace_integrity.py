#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_trace_integrity.py — Phase 4C.1-A §A2：frozen / actual research trace 的完整性门禁

为什么单独一个门禁
──────────────────
Phase 4C 的 Gate 16 只扫校准 fixture（`evidence_sufficiency_calibration.v4c.json`），
对 `_data/eval/research_traces_4b/*.json` 里**真实**的 27 条 trace 没有任何检查。
Phase 4C 人工评审随后在真实 trace 里发现了五类不一致（§A2 §1–§5）：

    1. required/planned operations 与实跑不一致
    2. 最后一步状态 ≠ final_state，且没有 transition reason
    3. state explanation 引用了并不存在的 signals（component_agreement / constraint_satisfaction）
    4. budget.used.context_expansions 与 trace.context_expansions 对不上
    5. final_state 缺少可解释的 transition

冻结策略（关键）
────────────────
历史 trace **不得修改**。因此本门禁把发现分成两级：

    VIOLATION       —— 声明 `research-trace/v2` 契约的 trace 出现不一致
    LEGACY_FROZEN   —— 历史冻结 trace（`research-trace-4b/v1`）的既知不一致

只有 VIOLATION 会让门禁失败；LEGACY_FROZEN 全部写进
`_data/eval/trace_integrity_baseline_v1.json` 另册记录，**不掩盖、也不靠改历史变绿**。

用法
────
    python3 check_trace_integrity.py            # 打印 + 写基线
    python3 check_trace_integrity.py --verify   # 有契约违规则退出码 1
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
OUT = os.path.join(EVAL, "trace_integrity_baseline_v1.json")
CONTRACT = os.path.join(EVAL, "trace_contract.schema.json")
sys.path.insert(0, HERE)
import eval_integrity as ei  # noqa: E402

TRACE_DIRS = ("_data/eval/research_traces_4c1b3",
              "_data/eval/research_traces_4c1b2",
              "_data/eval/research_traces_4c1b",
              "_data/eval/research_traces_4b", "_data/eval/research_traces_v2",
              "_data/eval/research_traces_context_audit")


def iter_traces():
    for rel in TRACE_DIRS:
        d = os.path.join(VAULT, rel)
        for p in sorted(glob.glob(os.path.join(d, "*.json"))):
            if os.path.basename(p) in ("MANIFEST.json", "COMPARISON.json"):
                continue
            try:
                yield rel, os.path.basename(p)[:-5], json.load(open(p, encoding="utf-8"))
            except Exception as exc:                     # pragma: no cover
                yield rel, os.path.basename(p)[:-5], {"_parse_error": str(exc)}


def schema_findings(trace, schema):
    """v2 契约 trace 必须满足 `trace_contract.schema.json`（无 jsonschema 时跳过）。"""
    if trace.get("schema_version") != ei.CONTRACT_SCHEMA:
        return []
    try:
        import jsonschema
    except Exception:                                     # pragma: no cover
        return []
    v = jsonschema.Draft7Validator(schema)
    errs = sorted(v.iter_errors(trace), key=lambda e: list(e.path))
    return [{"code": "TRACE_SCHEMA_VIOLATION", "severity": "VIOLATION",
             "detail": "/%s: %s" % ("/".join(str(x) for x in e.path), e.message)}
            for e in errs[:8]]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    schema = ei.jd(CONTRACT, {}) or {}
    violations, legacy = [], []
    checked = defaultdict(int)
    for rel, tid, tr in iter_traces():
        checked[rel] += 1
        if "_parse_error" in tr:
            violations.append({"task_id": tid, "dir": rel, "code": "TRACE_UNPARSEABLE",
                               "severity": "VIOLATION", "detail": tr["_parse_error"]})
            continue
        for f in ei.trace_integrity_findings(tr):
            f = dict(f, task_id=tid, dir=rel)
            (violations if f["severity"] == "VIOLATION" else legacy).append(f)
        for f in schema_findings(tr, schema):
            violations.append(dict(f, task_id=tid, dir=rel))

    by_code = Counter(f["code"] for f in legacy)
    tasks_by_code = defaultdict(list)
    for f in legacy:
        tasks_by_code[f["code"]].append(f["task_id"])
    doc = {
        "schema_version": "trace-integrity-baseline/v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "contract_schema": ei.CONTRACT_SCHEMA,
        "contract_schema_file": os.path.relpath(CONTRACT, VAULT),
        "scanned_dirs": {k: v for k, v in checked.items()},
        "traces_scanned": sum(checked.values()),
        "contract_violations": len(violations),
        "contract_violation_examples": violations[:10],
        "legacy_frozen_total": len(legacy),
        "legacy_frozen_by_code": dict(by_code),
        "legacy_frozen_tasks_by_code": {k: sorted(set(v)) for k, v in tasks_by_code.items()},
        "legacy_frozen_sample": legacy[:24],
        "policy": ("历史冻结 trace 不得修改；其既知不一致只在此造册。"
                   "只有声明 %s 的 trace 才会被判为门禁违规。" % ei.CONTRACT_SCHEMA),
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("trace integrity：扫描 %d 条（%s）" % (doc["traces_scanned"], dict(checked)))
        print("  契约违规（%s）：%d" % (ei.CONTRACT_SCHEMA, len(violations)))
        print("  历史冻结既知不一致：%d  %s" % (len(legacy), dict(by_code)))
        print("-> %s" % os.path.relpath(OUT, VAULT))
    if a.verify:
        return 0 if not violations else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
