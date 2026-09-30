#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_adjudicated_truth.py — Phase 4C.1-A §A5：三个人工裁决题的**版本化 evaluation truth**

三个裁决已经由人类做出（Phase 4C Human Review + Adjudication，**冻结**）：

    rt-J01  AGENT_CORRECT        gold 由法文 needle 推导 → 跨语言覆盖失败
    rt-H02  GOLD_CORRECT         只认可 answerability 标签；gold evidence 构造不合格
    rt-G01  NEEDS_MORE_EVIDENCE  两侧均未证实；followup_required = true

本脚本把这三条裁决转成**机器可读的 gold_v2 设计**：

    _data/eval/evaluation_truth_adjudicated_v1.json

关键约束
────────
* **不改 v1 gold**（`research_tasks_v1.jsonl` / `gold_derivation` 逐字节不变）；
* 本文件是 `gold_v2` 的**规范**（spec），而不是新 gold 本身；
  真正重建 gold 属下一阶段（Phase 4C.1-B），本阶段只把「truth 应该是什么」写死；
* 计数（莫比乌斯 / ◊ / hegel …）由**语料实扫**得出，不是手写的。

用法
────
    python3 build_adjudicated_truth.py --rebuild     # 实扫语料并写文件
    python3 build_adjudicated_truth.py --check       # 校验输入未变 + 内部一致（快）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
STORE = os.path.join(VAULT, "_data", "passage_store")
OUT = os.path.join(EVAL, "evaluation_truth_adjudicated_v1.json")
sys.path.insert(0, HERE)
import eval_integrity as ei  # noqa: E402
import gold_normalization as gn  # noqa: E402

# 需要实扫的 needle（按任务分组）—— 全部为「v2 语义」（token 边界安全）
SCAN_NEEDLES = {
    "rt-J01": [
        {"name": "莫比乌斯", "needle": "莫比乌斯", "language": "zh"},
        {"name": "莫比乌斯带", "needle": "莫比乌斯带", "language": "zh"},
        {"name": "moebius", "needle": "moebius", "language": "fr"},
        {"name": "bande de moebius", "needle": "bande de moebius", "language": "fr"},
        {"name": "sujet_barre", "needle": "sujet barré", "language": None},
    ],
    "rt-H02": [
        {"name": "diamond", "needle": "◊", "language": None},
        {"name": "S_diamond_a", "needle": "S ◊ a", "language": None},
        {"name": "S_diamond_a_relaxed", "needle": "S ◊ a", "language": None,
         "relaxed": True},
        {"name": "(S_diamond_a)", "needle": "(S ◊ a)", "language": None},
        {"name": "poincon", "needle": "poinçon", "language": None},
        {"name": "formule", "needle": "formule", "language": None},
    ],
    "rt-G01": [
        {"name": "hegel", "needle": "hegel", "language": None},
        {"name": "黑格尔", "needle": "黑格尔", "language": "zh"},
        {"name": "maitre", "needle": "maître", "language": "fr"},
        {"name": "esclave", "needle": "esclave", "language": "fr"},
        {"name": "奴隶", "needle": "奴隶", "language": "zh"},
        {"name": "kojeve", "needle": "Kojève", "language": None},
        {"name": "maitre+esclave_same_passage", "needle": "@relation:maître|esclave",
         "language": "fr"},
    ],
}


def scan_corpus():
    """一次扫描给出所有 needle 的 corpus 级计数（v2 语义）。"""
    pats = {}
    for t, items in SCAN_NEEDLES.items():
        for it in items:
            if it["needle"].startswith("@relation:"):
                a, b = it["needle"][len("@relation:"):].split("|")
                pats[(t, it["name"])] = ("relation", re.compile(re.escape(gn.strip_marks(a)), re.I),
                                         re.compile(re.escape(gn.strip_marks(b)), re.I))
                continue
            if gn.is_symbolic_needle(it["needle"]):
                # 含符号的 needle（◊ / S ◊ a / (S ◊ a)）：符号是语义的一部分，
                # 必须原样保留，绝不能被 token 化丢掉（否则 `S ◊ a` → `s a`）。
                rx = gn.symbolic_needle_regex(
                    it["needle"], relaxed=bool(it.get("relaxed")))
                pats[(t, it["name"])] = ("symbolic", rx, None)
                continue
            toks = gn.needle_tokens_v2(it["needle"])
            if not toks:                       # 兜底：无 token 且非符号
                pats[(t, it["name"])] = ("literal", re.compile(re.escape(gn.strip_marks(it["needle"]))), None)
            elif len(toks) == 1:
                pats[(t, it["name"])] = ("token", re.compile(re.escape(toks[0]), re.I), None)
            else:
                sep = r"[\s\-‐‑–—'’`()\[\]{}«»\"“”/]+"
                pats[(t, it["name"])] = ("seq", re.compile(
                    sep.join(re.escape(x) for x in toks), re.I), None)
    counts = {k: 0 for k in pats}
    by_sem = {k: {} for k in pats}
    n = 0
    with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            n += 1
            text = gn.strip_marks(d.get("raw_text") or "")
            if not text:
                continue
            sem = d.get("seminar_id")
            for key, (kind, rx, rx2) in pats.items():
                if kind == "relation":
                    hit = bool(rx.search(text) and rx2.search(text))
                elif kind == "symbolic":
                    hit = bool(rx and rx.search(text))
                else:
                    hit = bool(rx.search(text))
                if hit:
                    counts[key] += 1
                    by_sem[key][sem] = by_sem[key].get(sem, 0) + 1
    return n, counts, by_sem


def evidence_block(n, counts, by_sem):
    out = {}
    for (t, name), c in counts.items():
        out.setdefault(t, {})[name] = {
            "needle": next(i["needle"] for i in SCAN_NEEDLES[t] if i["name"] == name),
            "language": next(i["language"] for i in SCAN_NEEDLES[t] if i["name"] == name),
            "hits": c,
            "top_seminars": sorted(by_sem[(t, name)].items(),
                                   key=lambda kv: -kv[1])[:6],
        }
    for t in out:
        out[t]["_scan"] = {"corpus_passages": n,
                           "method": "gold_normalization v2（token 边界安全；子句标点切断）"}
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    tasks = {r["task_id"]: r for r in ei.jl(os.path.join(EVAL, "research_tasks_v1.jsonl"))}
    reviews = {r["task_id"]: r for r in ei.jl(os.path.join(EVAL, "research_human_review.jsonl"))}
    queue = {r["task_id"]: r for r in ei.jl(os.path.join(EVAL, "human_adjudication_queue.jsonl"))}
    inputs_sha = {
        "research_tasks_v1.jsonl": ei.sha256_file(os.path.join(EVAL, "research_tasks_v1.jsonl")),
        "research_human_review.jsonl": ei.sha256_file(os.path.join(EVAL, "research_human_review.jsonl")),
        "human_adjudication_queue.jsonl": ei.sha256_file(os.path.join(EVAL, "human_adjudication_queue.jsonl")),
    }

    if a.check:
        doc = ei.jd(OUT)
        problems = []
        if not doc:
            print("缺 %s（先跑 --rebuild）" % os.path.relpath(OUT, VAULT))
            return 1
        for k, v in (doc.get("frozen_inputs_sha256") or {}).items():
            if inputs_sha.get(k) != v:
                problems.append("冻结输入已变：%s" % k)
        for t in ("rt-J01", "rt-H02", "rt-G01"):
            dec = queue.get(t, {}).get("decision")
            if doc["tasks"][t]["adjudication_decision"] != dec:
                problems.append("%s 裁决与队列不一致：%s vs %s"
                                % (t, doc["tasks"][t]["adjudication_decision"], dec))
        if problems:
            for p in problems:
                print("  FAIL", p)
            return 1
        print("adjudicated truth 与冻结输入一致（3/3 裁决、输入哈希未变）")
        return 0

    n, counts, by_sem = scan_corpus() if a.rebuild else (0, {}, {})
    if not a.rebuild:
        old = ei.jd(OUT)
        if old:
            print("已有 %s；用 --rebuild 重算，或 --check 校验"
                  % os.path.relpath(OUT, VAULT))
            return 0
    ev = evidence_block(n, counts, by_sem) if a.rebuild else {}

    doc = {
        "schema_version": "evaluation-truth-adjudicated/v1",
        "phase": "Phase 4C.1-A §A5",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "SPEC_ONLY_NOT_APPLIED",
        "applies_to": "gold_v2（下一阶段重建；本阶段**不**改 research_tasks_v1.jsonl）",
        "frozen_inputs_sha256": inputs_sha,
        "why": ("Phase 4C 人工裁决证明 v1 gold 在三个任务上不能直接当作 evaluation truth。"
                "本文件把裁决转成机器可读的 gold_v2 规范，v1 历史证据逐字节保留。"),
        "tasks": {
            "rt-J01": {
                "question": tasks["rt-J01"]["question"],
                "adjudication_decision": "AGENT_CORRECT",
                "target_answerability": "PARTIALLY_SUPPORTED",
                "why_not_full_supported": ("关键证据是 recovered 中文 L2，未回溯 L1 法文 witness；"
                                          "用户明确要求「原文依据」，故不能升为完整 SUPPORTED。"),
                "v1_defect": {
                    "kind": "gold_cross_language_coverage_failure",
                    "detail": ("v1 只用**法文** needle `moebius` / `bande de moebius` 推导 answerability，"
                               "漏掉中文 witness 的「莫比乌斯带」。"),
                    "v1_lane_needles": [],
                    "v1_no_gold_reason": tasks["rt-J01"]["gold_derivation"].get("no_gold_reason"),
                },
                "gold_v2_required_changes": [
                    "新增中文 lane：`莫比乌斯` / `莫比乌斯带`（multilingual concept-level derivation）",
                    "纳入直接关联主体的 passage（如 `passage.S13.unknown.L06.P0136`）",
                    "纳入解释单面性构造的 passage（如 `passage.S09.unknown.L15.P0012`）",
                    "为 recovered 中文 passage 回溯对应法文 witness",
                    "Möbius(topology) 与 Paul Julius Möbius(person) 实体消歧",
                    "排除普通英文 `strips` 造成的 lexical false positive",
                    "为 sujet / sujet barré 建立 relation evidence lane",
                ],
                "expected_zero_lanes": [],
                "supported_forbidden_conditions": [
                    "缺 L1 法文 primary 时不得判 SUPPORTED（最高 PARTIALLY_SUPPORTED）",
                    "只用单语（法文）surface form 推导 answerability",
                ],
                "corpus_evidence": ev.get("rt-J01", {}),
                "human_baseline": {
                    "scores": reviews["rt-J01"]["human_scores"],
                    "citation_support": reviews["rt-J01"]["citation_support"],
                    "scholarly_usable": reviews["rt-J01"]["scholarly_usable"],
                },
            },
            "rt-H02": {
                "question": tasks["rt-H02"]["question"],
                "adjudication_decision": "GOLD_CORRECT",
                "adjudication_scope": "只认可 answerability 标签（SUPPORTED）；gold evidence 构造不合格",
                "target_answerability": "SUPPORTED",
                "v1_defect": {
                    "kind": "gold_evidence_derivation_defect",
                    "detail": ("v1 lane 用 `fantasme` / `objet a` 词法 needle；抽出的 6 条 gold passage "
                               "无一条含 `◊` 或完整 matheme，其中 3 条是 Seminar XIV 卷首版本说明。"),
                    "v1_lane_needles": [l["needles"] for l in
                                        tasks["rt-H02"]["gold_derivation"]["lanes"]],
                },
                "gold_v2_required_changes": [
                    "新增 explicit formalism lane：`◊` / `S ◊ a` / `(S ◊ a)` / `poinçon` / `formule`",
                    "优先纳入直接 formalism passages（`S14.P0029` / `S14.P0055` / `S14.P0066`）",
                    "原 `fantasme` / `objet a` lane 降为 contextual lane，不承担 matheme gold 主体",
                    "`seminar_constraint=S14` 必须真正下推到 retrieval",
                    "entity 用 `concept.fantasme` × `concept.objet-petit-a`（而非 structure × fantasme）",
                ],
                "formalism_two_level_contract": {
                    "RETRIEVED_FORMALISM_MISSING": "本次 evidence set 未检到公式 → 属 retrieval failure",
                    "CORPUS_FORMALISM_MISSING": "formalism-specific 全库扫描后仍无该形式 → 才可能是结构性不可答",
                },
                "supported_forbidden_conditions": [
                    "未经 formalism-specific 全库扫描就断言 FORMALISM_MISSING 为结构性不可答",
                    "把「检索集里没有符号」当作「语料里没有符号」",
                ],
                "expected_zero_lanes": [],
                "corpus_evidence": ev.get("rt-H02", {}),
                "human_baseline": {
                    "scores": reviews["rt-H02"]["human_scores"],
                    "citation_support": reviews["rt-H02"]["citation_support"],
                    "scholarly_usable": reviews["rt-H02"]["scholarly_usable"],
                },
            },
            "rt-G01": {
                "question": tasks["rt-G01"]["question"],
                "adjudication_decision": "NEEDS_MORE_EVIDENCE",
                "target_answerability": "UNDETERMINED_PENDING_RELATION_RETRIEVAL",
                "followup_required": True,
                "why_not_resolved": ("Agent 的 INSUFFICIENT 来自失败检索（Hegel/主奴侧无 lane），"
                                     "Gold 的 SUPPORTED 也缺 relation evidence —— 两侧均未被证实。"),
                "v1_defect": {
                    "kind": "relation_lane_missing + false_topic_not_covered",
                    "detail": ("`fr_hegel` lane 多为旁及提及；`fr_maitre_esclave` 由 maître+esclave "
                               "词面规则构造，抽中的 `S17.P0009` 是 Lacan 的主人话语而非黑格尔主奴辩证法；"
                               "v2 的 TOPIC_NOT_COVERED 依据是中文问句残片。"),
                    "v1_lane_needles": [l["needles"] for l in
                                        tasks["rt-G01"]["gold_derivation"]["lanes"]],
                },
                "task_metadata_conflict": {
                    "expected_periods": tasks["rt-G01"]["expected_periods"],
                    "expected_seminars": tasks["rt-G01"]["expected_seminars"],
                    "problem": ("expected_periods 只写 1969-1970，但 expected_seminars 同时要求 S02 与 S17；"
                                "S02（1954-1955）不属于 1969-1970，重建 Gold 时必须校正。"),
                },
                "gold_v2_required_changes": [
                    "Hegel / 黑格尔 专门 lane",
                    "Kojève 专门 lane",
                    "Hegelian maître-esclave relation lane",
                    "Lacan `Discours du Maître` 与 Hegelian master-slave 实体/语境消歧",
                    "desire / désir de l'Autre / reconnaissance relation lane",
                    "强制 relation evidence 检索（不得拼接两个独立 evidence pool）",
                    "source-layer separation（Hegel / Kojève / Lacan 重新使用 / Lacan 自身欲望理论）",
                    "校正 expected_periods 与 expected_seminars 的不一致",
                    "重建 Gold evidence 后再最终 adjudicate answerability",
                ],
                "supported_forbidden_conditions": [
                    "缺 relation evidence 时不得判 SUPPORTED",
                    "以问句残片作为 discriminating terms 断言 TOPIC_NOT_COVERED",
                ],
                "expected_zero_lanes": [],
                "corpus_evidence": ev.get("rt-G01", {}),
                "human_baseline": {
                    "scores": reviews["rt-G01"]["human_scores"],
                    "citation_support": reviews["rt-G01"]["citation_support"],
                    "scholarly_usable": reviews["rt-G01"]["scholarly_usable"],
                },
            },
        },
        "policy": {
            "v1_untouched": "本文件不改写 research_tasks_v1.jsonl / gold_derivation / 任何 frozen 结果。",
            "next_phase": "Phase 4C.1-B 依据本规范重建 gold_v2（新文件、新版本号，旧 benchmark 历史保留）。",
        },
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("wrote %s" % os.path.relpath(OUT, VAULT))
        print("  status=%s" % doc["status"])
        for t, d in doc["tasks"].items():
            print("  %-7s %-20s target=%s" % (t, d["adjudication_decision"],
                                              d["target_answerability"]))
            if a.rebuild:
                for name, c in (d.get("corpus_evidence") or {}).items():
                    if name.startswith("_"):
                        continue
                    print("        %-28s hits=%d" % (name, c["hits"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
