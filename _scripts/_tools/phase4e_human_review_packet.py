#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase4e_human_review_packet.py — Phase 4E E14：**盲审**人工复核材料包（不调用任何 LLM）

背景（acceptance semantics audit 结论）：
    冻结 Gate 的 E14 逐字要求 `human spot review FAIL = 0`，证据文件
    `human_spot_review.jsonl`。Phase 4E 期间实际做的是 **agent-mediated** 预审，
    它**不满足** E14。因此需要真实人工复核；本工具只准备材料，不做判断。

纪律（§4 anti-anchoring）：
    每题**只**输出：question / final answer / claims / citations+evidence /
    source limitations / answer state。
    **禁止**输出：agent 预审结论、D2 对照、Round1/Round2 评分、期望结果、
    修复/剔除计数、entailment 内部状态、Gate 期望、provider/延迟元数据。
    工具内含 allow-list 与「禁字段」断言，命中即失败。

用法：
    python3 _scripts/_tools/phase4e_human_review_packet.py \
        [--run _data/phase4e/phase4e_real_llm_20260926T115518Z_1c8e1efc] \
        [--out _data/phase4e/human_review_packet]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))

TASKS = ["rt-D01", "rt-I02", "rt-H02", "rt-C03", "rt-J02", "rt-G01"]
DEFAULT_RUN = "_data/phase4e/phase4e_real_llm_20260926T115518Z_1c8e1efc"
DEFAULT_OUT = "_data/phase4e/human_review_packet"

# 允许出现在 packet 里的字段（其余一律不写）
ALLOWED = {"task_id", "question", "answer_state", "answer_permission", "sections",
           "claims", "citations", "source_limitations", "abstention", "warnings"}
CLAIM_FIELDS = ("claim_id", "claim_type", "claim_text", "epistemic_status",
                "evidence_ids", "quotation")
CITATION_FIELDS = ("claim_id", "passage_id", "quoted_span", "source_layer",
                   "provenance_status", "citation_status")
# 明确禁止的锚定信息（出现在 packet 文本里 = 失败）
FORBIDDEN_TOKENS = ("agent_pre_review", "verdict", "WITH_CONCERN", "4c1d2", "D2 ",
                    "Round1", "Round2", "Gate", "gate", "repaired", "rejected",
                    "expected", "PASS ", "FAIL ")


# 核心在 sections 里会写一句**验证计数**样板（"本回答由 N 条通过蕴含验证的断言构成…
# 其中 M 条为直接支持…K 条断言因未通过验证被剔除"）。那属于**repair/reject 历史**，
# §4 明确不许给 reviewer 看（会 anchoring），因此这里按正则抹掉整句。
_COUNT_BOILERPLATE = [
    re.compile(r"本回答由[^。]*断言构成[^。]*。"),
    re.compile(r"[^。]*因未通过验证被剔除[^。]*。"),
    re.compile(r"[^。]*已剔除[^。]*。"),
    re.compile(r"\b\d+\s*(claims?|assertions?)\s+(validated|rejected|repaired)\b[^.]*\."),
]
# 只禁「评价性/锚定性」元数据（他人结论、对照、评分、期望）。答案自身可见文本
# （含核心写进 sections 的 reject 日志）**不**在此列 —— 见 build_task 的取舍说明。
_FORBIDDEN_IN_TEXT = ("verdict", "WITH_CONCERN", "agent_pre_review", "agent-mediated",
                      "4c1d2", "Round1", "Round2", "expected outcome", "expectation",
                      "D2 ", "gate FAIL", "gate PASS", "E14")


def sanitize_text(value):
    """抹掉验证计数样板句；返回 (清洗后文本, 是否被改过)。"""
    if not isinstance(value, str):
        return value, False
    out = value
    for pat in _COUNT_BOILERPLATE:
        out = pat.sub("", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"^[；;、,，\-\s]+", "", out).strip()
    return out, (out != value)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def build_task(row):
    """只取允许字段，构成**盲审**材料。"""
    fa = row.get("final_answer") or {}
    out = {
        "task_id": row["task_id"],
        "question": row.get("question"),
        "answer_state": row.get("answer_state"),
        "answer_permission": row.get("answer_permission"),
        # ⚠️ 取舍（审计期间两次修正后的结论）：sections **原样保留**。
        #    理由：E14 要判的是「用户实际看到的最终答案」是否退化/畸形；若把
        #    核心写进 sections.limitations 的 reject 日志（"已剔除未通过蕴含验证的断言…
        #    （NOT_ENTAILED）"）先洗掉，就把「check 5：synthesis 畸形/截断」的检测对象
        #    本身删掉了 —— 那等于帮被测对象遮掩。反 anchoring 禁的是**评价性元数据**
        #    （他人 verdict / D2 对照 / 评分 / 期望结果），不是答案自身的可见文本。
        #    该现象已在审计文件 §11 记为工程发现 F-1（可 mock 复现 ⇒ 非 adapter 引入）。
        "sections": dict(fa.get("sections") or {}),
        "claims": [{k: c.get(k) for k in CLAIM_FIELDS if c.get(k) is not None}
                   for c in (fa.get("validated_claims") or [])],
        "citations": [{k: c.get(k) for k in CITATION_FIELDS if c.get(k) is not None}
                      for c in (fa.get("citations") or [])],
        "source_limitations": list(fa.get("source_limitations") or []),
        "warnings": list(fa.get("warnings") or []),
    }
    if fa.get("abstention"):
        ab = fa["abstention"]
        out["abstention"] = {k: ab.get(k) for k in
                             ("category", "categories", "missing_information",
                              "available_partial_information", "required_sources",
                              "abstention_reason_codes", "next_required_sources")
                             if ab.get(k) is not None}
    extra = set(out) - ALLOWED
    assert not extra, "packet 含未允许字段：%s" % extra
    return out


def to_markdown(p):
    L = ["# 人工复核材料（盲审） — `%s`" % p["task_id"], "",
         "> 你看到的是系统对下面这个问题的**最终输出**。请按 §checks 五项做判断，",
         "> 不要参考任何自动评分、历史评审或期望结果（材料里也没有）。", "",
         "## Question", "", p.get("question") or "", "",
         "## Answer state", "", "`%s`（permission: `%s`）"
         % (p.get("answer_state"), p.get("answer_permission")), ""]
    sec = p.get("sections") or {}
    for k in sorted(sec):
        v = sec[k]
        L += ["## Section: %s" % k, "", str(v) if not isinstance(v, (dict, list))
              else json.dumps(v, ensure_ascii=False, indent=1), ""]
    L += ["## Claims（最终答案里的 claim）", ""]
    for c in p["claims"]:
        L.append("- **%s** · `%s` · `%s`" % (c.get("claim_id"), c.get("claim_type"),
                                             c.get("epistemic_status")))
        L.append("  - %s" % c.get("claim_text"))
        L.append("  - evidence: `%s`" % (c.get("evidence_ids") or []))
        q = c.get("quotation")
        if q:
            L.append("  - quotation: `%s` @ `%s`" % (str(q.get("exact_span"))[:200],
                                                     q.get("passage_id")))
    L += ["", "## Citations（逐字引用位）", ""]
    for c in p["citations"]:
        L.append("- `%s` · `%s` · `%s`%s" % (c.get("passage_id"), c.get("source_layer"),
                                             c.get("provenance_status"),
                                             "" if not c.get("quoted_span")
                                             else " · 「%s」" % str(c["quoted_span"])[:200]))
    if p.get("warnings"):
        L += ["", "## Warnings", ""] + ["- %s" % w for w in p["warnings"]]
    L += ["", "## Source limitations", ""]
    for x in p["source_limitations"]:
        L.append("- %s" % x)
    if p.get("abstention"):
        L += ["", "## Abstention", "", "```json",
              json.dumps(p["abstention"], ensure_ascii=False, indent=1), "```"]
    return "\n".join(L) + "\n"


SCHEMA = {
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "phase4e-human-spot-review/v1",
  "title": "Phase 4E E14 human spot review record",
  "type": "object",
  "additionalProperties": False,
  "required": ["schema_version", "task_id", "reviewer_type", "reviewed_at", "verdict",
               "checks", "comment"],
  "properties": {
    "schema_version": {"const": "phase4e-human-spot-review/v1"},
    "task_id": {"enum": TASKS},
    "reviewer_type": {"const": "human"},
    "reviewer": {"type": "string"},
    "reviewed_at": {"type": "string", "minLength": 10},
    "verdict": {"enum": ["PASS", "WITH_CONCERN", "FAIL"]},
    "checks": {
      "type": "object", "additionalProperties": False,
      "required": ["scholarly_degradation", "citation_evidence_mismatch",
                   "new_overclaim", "abstention_leakage",
                   "malformed_or_truncated_synthesis"],
      "properties": {
        "scholarly_degradation": {"enum": ["none", "minor", "major"]},
        "citation_evidence_mismatch": {"enum": ["none", "minor", "major"]},
        "new_overclaim": {"enum": ["none", "minor", "major"]},
        "abstention_leakage": {"enum": ["none", "minor", "major", "not_applicable"]},
        "malformed_or_truncated_synthesis": {"enum": ["none", "minor", "major"]}}},
    "comment": {"type": "string", "minLength": 1},
    # 仅当 verdict=WITH_CONCERN：判断是否 adapter 引入
    "concern_class": {"enum": ["existing_scholarly_limitation",
                               "phase4e_adapter_induced", "unclear"]}
  },
}

TEMPLATE = {
  "schema_version": "phase4e-human-spot-review/v1",
  "task_id": "rt-D01",
  "reviewer_type": "human",
  "reviewer": "<你的名字/ID>",
  "reviewed_at": "<YYYY-MM-DDTHH:MM:SSZ>",
  "verdict": "<PASS | WITH_CONCERN | FAIL>",
  "checks": {
    "scholarly_degradation": "<none | minor | major>",
    "citation_evidence_mismatch": "<none | minor | major>",
    "new_overclaim": "<none | minor | major>",
    "abstention_leakage": "<none | minor | major | not_applicable>",
    "malformed_or_truncated_synthesis": "<none | minor | major>"},
  "comment": "<为什么这么判：具体指出 claim / citation / 限制 的哪一处>",
  "concern_class": "<仅 verdict=WITH_CONCERN 时填：existing_scholarly_limitation | phase4e_adapter_induced | unclear>",
}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4E E14 blind human review packet")
    ap.add_argument("--run", default=DEFAULT_RUN)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    run_dir = a.run if os.path.isabs(a.run) else os.path.join(VAULT, a.run)
    out_dir = a.out if os.path.isabs(a.out) else os.path.join(VAULT, a.out)
    os.makedirs(out_dir, exist_ok=True)

    rows = {}
    with open(os.path.join(run_dir, "task_results.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                rows[r["task_id"]] = r
    seal = json.load(open(os.path.join(run_dir, "seal.json"), encoding="utf-8"))

    manifest_files = {}
    for tid in TASKS:
        row = rows.get(tid)
        assert row, "sealed run 缺少 %s" % tid
        packet = build_task(row)
        jp = os.path.join(out_dir, "%s.json" % tid)
        mp = os.path.join(out_dir, "%s.md" % tid)
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(packet, f, ensure_ascii=False, indent=1)
            f.write("\n")
        md = to_markdown(packet)
        for tok in _FORBIDDEN_IN_TEXT:
            assert tok not in md, "packet %s 命中禁字段 %r（会 anchoring）" % (tid, tok)
        for tok in _FORBIDDEN_IN_TEXT:
            assert tok not in json.dumps(packet, ensure_ascii=False), \
                "packet %s json 命中禁字段 %r" % (tid, tok)
        with open(mp, "w", encoding="utf-8") as f:
            f.write(md)
        manifest_files[tid] = {"json": os.path.relpath(jp, VAULT),
                               "markdown": os.path.relpath(mp, VAULT),
                               "json_sha256": _sha(jp), "markdown_sha256": _sha(mp)}

    with open(os.path.join(out_dir, "human_spot_review_schema.json"), "w",
              encoding="utf-8") as f:
        json.dump(SCHEMA, f, ensure_ascii=False, indent=1)
        f.write("\n")
    tpl = os.path.join(out_dir, "human_spot_review_template.jsonl")
    with open(tpl, "w", encoding="utf-8") as f:
        for tid in TASKS:
            d = dict(TEMPLATE)
            d["task_id"] = tid
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    readme = """# Phase 4E E14 — 人工盲审材料包

冻结 Gate 的 **E14** 逐字要求：`human spot review FAIL = 0（6 题，含 rt-D01/I02/H02/C03/J02/G01）`，
证据文件 `human_spot_review.jsonl`。Phase 4E 期间完成的是 **agent-mediated 预审**
（`_data/phase4e/agent_pre_review.jsonl`），**不满足** E14。本目录是给**真实人工**
复核用的盲审材料。

## 怎么用

1. 逐个读 `rt-XXX.md`（机器可读版本 `rt-XXX.json`，内容相同）。
2. 每题按下面五项判断，并给一个 verdict：

   ```
   PASS / WITH_CONCERN / FAIL
   ```

   五项 checks：`scholarly_degradation` · `citation_evidence_mismatch` ·
   `new_overclaim` · `abstention_leakage` · `malformed_or_truncated_synthesis`
   （各取 `none / minor / major`）。

3. 把 6 题写进 `human_spot_review_v2.jsonl`（一行一题，字段见
   `human_spot_review_schema.json` 与 `human_spot_review_template.jsonl`），
   放到 `_data/phase4e/human_spot_review_v2.jsonl`。
4. 跑闭合评估：

   ```bash
   python3 _scripts/_tools/phase4e_human_closure.py --human \
       _data/phase4e/human_spot_review_v2.jsonl
   ```

   它会**重新执行** Phase 4E Remediation Gate v1 的 E1–E17 评估（E1–E13/E15–E17 复用
   已验证证据，E14 用你的人工记录），产出新的 closure run，
   并给出 `PHASE_4E_COMPLETE` / `AWAITING_HUMAN_SPOT_REVIEW` / `BLOCKED`。

## 判定规则（**冻结，不得改**）

* 任一题 `FAIL` → E14 FAIL → `PHASE_4E = BLOCKED`（报告 failed task / comment /
  是否 adapter 引入 / 最小补救）。
* `FAIL = 0` → E14 PASS。
* `WITH_CONCERN` 不自动 FAIL，但必须判断属于
  `existing_scholarly_limitation` 还是 `phase4e_adapter_induced`；
  若是后者，**升级处理**。

## 本材料包**故意**不含（防 anchoring）

agent 预审结论 · D2 对照 · Round1/Round2 评分 · 期望结果 · 修复/剔除计数 ·
entailment 内部状态 · Gate 期望结果 · provider 元数据/延迟。

## 来源与封存

* 来源 run（sealed，未改动）：`%s`
* seal: `provider_success=%s`，`results_hash=%s`
* 本材料包生成时间：`%s`
""" % (os.path.relpath(run_dir, VAULT), seal.get("provider_success"),
       str(seal.get("results_hash"))[:16], time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme)

    manifest = {
        "schema_version": "phase4e-human-review-packet/v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_run": os.path.relpath(run_dir, VAULT),
        "source_seal_sha256": _sha(os.path.join(run_dir, "seal.json")),
        "source_results_sha256": seal.get("results_hash"),
        "tasks": TASKS, "files": manifest_files,
        "allowed_fields": sorted(ALLOWED),
        "excluded_by_design": [
            "agent 预审结论 / 其他 reviewer 的意见",
            "D2 对照与分类",
            "Round1 / Round2 评分",
            "期望结果 / 预期 verdict",
            "Gate 判定口径与期望（含 E14 规则文本）",
            "每条 claim 的 entailment 内部状态与修复/剔除计数",
            "provider / 延迟 / token 元数据",
            "（说明：sections 与 warnings 原样保留 —— 它们是用户可见文本，"
            "含核心写入的 reject 日志；那属检查对象，不是锚定信息）"],

        "no_llm_calls": True,
        "schema": os.path.relpath(os.path.join(out_dir,
                                              "human_spot_review_schema.json"), VAULT),
        "template": os.path.relpath(tpl, VAULT),
        "answer_file_expected": "_data/phase4e/human_spot_review_v2.jsonl",
    }
    with open(os.path.join(out_dir, "packet_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    print("packet -> %s（%d 题；无 LLM 调用）" % (os.path.relpath(out_dir, VAULT),
                                                  len(TASKS)))
    for tid in TASKS:
        print("  %s  %s + %s" % (tid, os.path.basename(manifest_files[tid]["markdown"]),
                                 os.path.basename(manifest_files[tid]["json"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
