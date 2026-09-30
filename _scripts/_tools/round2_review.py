#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
round2_review.py — Phase 4C.1-E：第二轮 **盲评** 的准备 / 记录 / 汇总

纪律（本文件的存在理由）
────────────────────────
§11：**绝对禁止**系统自动填写人工评分。
     本文件**不产生任何分数**：它只 prepare packet / record explicit human decision /
     validate schema / aggregate after completion。
     任何一条 REVIEWED 记录都必须带 provenance.submitted_by（人类消息）与
     provenance.written_by == "review recorder (no scoring by system)"。

§6/§8：盲评。packet 不得暴露 Round 1 的分数与评论、旧 Agent 状态、旧 Phase 4C 答案、
      期望改善、修复历史、内部 debug（tool calls / budget / latency / retry /
      rejected claims / Gate 细节）。build 时先做**泄漏扫描**，不干净就拒绝出包。

§7：packet 内容 = 任务 + 当前 final validated answer + validated claims +
    实际被引用的 citation/evidence + 事实性的 source limitations + answer state。

§13/§14：被评审的答案必须钉死到 D2 封存 run：每题记录 answer_hash / packet_view_hash，
        并在 --check 时逐题复算。

用法
────
    python3 round2_review.py --build            # E1：出包（幂等；已存在则只校验）
    python3 round2_review.py --check            # E1/E2：校验（供套件调用，只读）
    python3 round2_review.py --show rt-A01      # 打印某一包（给用户评审）
    python3 round2_review.py --record rt-A01 --scores /path/payload.json --submitted-by "..."
    python3 round2_review.py --aggregate        # E2：仅当 14/14 REVIEWED 才允许
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
RUNS = os.path.join(EVAL, "runs")
POINTER = os.path.join(EVAL, "research_synthesis_results.4c1d.json")
TASKS_P = os.path.join(EVAL, "research_tasks_v1.jsonl")
ROUND1_RECORDS = os.path.join(EVAL, "research_human_review.jsonl")
ROUND1_RESULTS = os.path.join(EVAL, "human_review_results_v1.json")
ROUND1_SET = os.path.join(EVAL, "human_review_set_v1.json")
FROZEN_IDENTITY = os.path.join(EVAL, "phase4c1d2_frozen_identity.json")
DATASET = os.path.join(EVAL, "research_human_review_round2.jsonl")
PACKETS = os.path.join(EVAL, "human_review_round2_packets")
SET_V1 = os.path.join(EVAL, "human_review_round2_set_v1.json")
MANIFEST = os.path.join(EVAL, "human_review_round2_manifest.json")
SCHEMA_P = os.path.join(EVAL, "round2_review_schema.json")
GATE_P = os.path.join(EVAL, "scholarly_readiness_gate_v1.json")
TAXONOMY_P = os.path.join(EVAL, "round2_taxonomy_v1.json")
RESULTS_V2 = os.path.join(EVAL, "human_review_results_v2.json")
RESULTS_V2_MD = os.path.join(VAULT, "HUMAN_REVIEW_RESULTS_V2.md")
FINAL_MD = os.path.join(VAULT, "PHASE4C1_FINAL_SCHOLARLY_REGRESSION.md")
PASSAGES = os.path.join(VAULT, "_data", "passage_store", "passages.jsonl")
TOOLS_DIR = os.path.join(VAULT, "_scripts", "_tools")

SET_VERSION = "round2-review-set/v1"
PACKET_SCHEMA = "human-review-packet-round2/v1"
MANIFEST_SCHEMA = "human-review-round2-manifest/v1"
RECORD_SCHEMA = "human-review-round2/v1"

ROUND1_RECORDS_SHA = ("a14ea5316ccaaf90f95e197f9674bca9620848fcc726a1bd5d4c9694fe4bfb3d")

DIMENSIONS = ("theoretical_coherence", "historical_accuracy",
              "distinction_preservation", "answer_usefulness", "overclaiming", "clarity")
CITATION_SUPPORT = ("PASS", "PARTIAL", "FAIL")
SCHOLARLY_USABLE = ("YES", "WITH_REVISION", "NO")

# 盲评泄漏黑名单：packet（json + md）中**任何一处**出现即拒绝出包。
# 说明：L1 / L2 是来源层标记，**必须**展示，故不在黑名单内。
BLIND_FORBIDDEN = [
    # Round 1 / 旧状态 / 期望
    "Round 1", "Round1", "round 1", "第一轮", "第一轮评分", "旧 Agent", "旧答案",
    "bucket", "strong_success", "borderline", "insufficient_evidence_bucket",
    "SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE",
    "expected improvement", "应该改善", "以前失败", "之前失败", "从 1 分提升",
    # 修复 / 蕴含 / 门禁内部
    "已剔除", "剔除", "未通过验证", "NOT_ENTAILED", "PARTIALLY_ENTAILED",
    "CONTRADICTED", "SOURCE_ROLE_MISMATCH", "INSUFFICIENT_CONTEXT",
    "rejected_claim", "rejected claims", "repair", "repaired", "NARROW_CLAIM",
    "entailment", "judge", "validator", "Gate", "gate21", "D_SOURCE_ROLE",
    # debug / 运行内部
    "tool_call", "tool calls", "lane", "budget", "execution_state", "evidence_n",
    "retrieval", "scheduler", "class_quota", "passage_store", "vector_unavailable",
    "VECTOR_UNAVAILABLE", "SEPARATE_LANES_ENFORCED", "ONTOLOGY_REPAIRED",
    "TERMS_NOT_IN_CORPUS", "QUERY_DECOMPOSED", "provider", "latency", "retry",
    "attempts", "token", "trace_summary", "failure taxonom",
    "RANKING_FAILURE", "ONTOLOGY_GAP", "FORMALISM_MISSING",
    # 工程词汇：必须已被 neutralize；仍出现即视为未清洗
    "forbidden_outputs_observed", "theoretical_development_without_evidence",
    "pipeline_log_as_answer", "search_passages", "resolve_entity",
    "find_concept_evidence", "citation_eligibility", "state_ceiling",
    "failed_constraints", "resolved_operations", "missing_operations",
]

# 修复历史行（D2 答案里 limitations 段会记录「已剔除…（NOT_ENTAILED）」）
REPAIR_LINE_RE = re.compile(
    r"(已剔除|未通过验证|NOT_ENTAILED|PARTIALLY_ENTAILED|CONTRADICTED|"
    r"SOURCE_ROLE_MISMATCH|不能进入最终答案|被剔除)")

# 内部「证据充分性状态」标签 → 中性表述。§6/§7F：packet 只展示 answer state，
# 不展示机器状态词；正文的语义（"证据上限不足"）必须完整保留。
STATE_LABEL_MASK = {
    "INSUFFICIENT_EVIDENCE": "证据不足以回答",
    "PARTIALLY_SUPPORTED": "证据仅部分支持",
    "CONFLICTING_EVIDENCE": "证据相互冲突",
    "SUPPORTED": "证据充分",
}
STATE_LABEL_RE = re.compile(r"\b(%s)\b" % "|".join(STATE_LABEL_MASK))


def mask_state_labels(value):
    """→ (masked_value, replaced_n)：只作用于答案正文，不动 claim 的 epistemic_status。"""
    if not isinstance(value, str) or not value:
        return value, 0
    n = len(STATE_LABEL_RE.findall(value))
    if not n:
        return value, 0
    return STATE_LABEL_RE.sub(lambda m: STATE_LABEL_MASK[m.group(1)], value), n


# 内部工程词汇 → 中性学术表述（§8：packet 不展示工具名 / 内部字段路径 / 机器判定词）。
# 语义必须保留：只换词，不删信息。每次替换数量写入 view_transforms 供审计。
VOCAB_NORMALIZE = [
    (re.compile(r"citation_eligibility\s*∈\s*\{[^}]*\}"), "符合引用资格"),
    (re.compile(r"citation_eligibility"), "引用资格"),
    (re.compile(r"EDITORIAL_METADATA"), "编辑性元数据"),
    (re.compile(r"research contract"), "研究范围设定"),
    (re.compile(r"failed_constraints"), "未满足的约束"),
    (re.compile(r"resolved_operations"), "已执行的操作"),
    (re.compile(r"missing_operations"), "未执行的操作"),
    (re.compile(r"search_passages"), "段落检索"),
    (re.compile(r"resolve_entity"), "实体解析"),
    (re.compile(r"find_concept_evidence"), "概念证据查找"),
    (re.compile(r"source_layers\.required"), "来源层要求"),
    (re.compile(r"source_layers\.available"), "来源层实际可用"),
    (re.compile(r"source_layers\.corpus"), "来源层语料标注"),
    (re.compile(r"state_ceiling"), "证据上限"),
    (re.compile(r"lacan_primary"), "拉康一手材料"),
    (re.compile(r"lacan_translation"), "拉康译本"),
    (re.compile(r"metadata/history\s+claim"), "元数据/史学断言"),
    (re.compile(r"\bcontract\b"), "研究范围设定"),
    (re.compile(r"\bperiod\b"), "时期"),
    (re.compile(r"\bspan\b"), "逐字片段"),
    (re.compile(r"\bfailed\b"), "未满足"),
    (re.compile(r"SUBSTANTIVE_TEXT"), "实质性正文"),
    (re.compile(r"substantive\s+METADATA\s+claim"), "实质性元数据断言"),
    (re.compile(r"substantive\s+claim"), "实质性断言"),
]

ABSTENTION_CATEGORY_GLOSS = {
    "METADATA_UNAVAILABLE": "元数据不可得",
    "NO_SUBSTANTIVE_EVIDENCE": "无可用的实质性证据",
    "TOPIC_NOT_COVERED": "语料未覆盖该主题",
    "SOURCE_CHAIN_INCOMPLETE": "来源链未闭合",
}


def normalize_internal_vocab(value):
    if not isinstance(value, str) or not value:
        return value, 0
    n = 0
    for rx, repl in VOCAB_NORMALIZE:
        value, k = rx.subn(repl, value)
        n += k
    return value, n


def clean_text(value):
    """状态标签 + 内部词汇 → 中性表述；返回 (text, n)。"""
    value, n1 = normalize_internal_vocab(value)
    value, n2 = mask_state_labels(value)
    return value, n1 + n2


def clean_tree(obj):
    """递归清洗 dict/list/str；返回 (obj, n)。"""
    n = 0
    if isinstance(obj, str):
        out, k = clean_text(obj)
        return out, k
    if isinstance(obj, list):
        out = []
        for it in obj:
            v, k = clean_tree(it)
            out.append(v)
            n += k
        return out, n
    if isinstance(obj, dict):
        out = {}
        for kk, vv in obj.items():
            v, k = clean_tree(vv)
            out[kk] = v
            n += k
        return out, n
    return obj, 0


def curate_abstention(ab):
    """弃权说明的**策展视图**：保留学术实质（缺什么/有什么/还需要什么），
    丢弃机器自检清单（如 forbidden_outputs_observed）。返回 (view, dropped_keys)。"""
    if ab is None:
        return None, []
    if isinstance(ab, str):
        return ab, []
    if not isinstance(ab, dict):
        return ab, []
    out, dropped = {}, []
    codes = ab.get("abstention_reason_codes") or []
    if codes:
        out["abstention_categories"] = [ABSTENTION_CATEGORY_GLOSS.get(c, c) for c in codes]
    for key in ("missing_information", "available_partial_information",
                "next_required_sources"):
        if ab.get(key):
            out[key] = ab[key]
    for key in ab:
        if key not in out and key != "abstention_reason_codes":
            dropped.append(key)
    return out, dropped


# ─────────────────────────────────────────────────────────── 基础工具
def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: str) -> str:
    with open(p, "rb") as f:
        return sha_bytes(f.read())


def canon(obj) -> str:
    """规范化 JSON：用于跨进程可复算的内容哈希。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canon_hash(obj) -> str:
    return sha_text(canon(obj))


def load_json(p: str):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(p: str):
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def write_json(p: str, doc) -> None:
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


def write_jsonl(p: str, rows) -> None:
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─────────────────────────────────────────────────────── D2 封存 run 校验
def sealed_run():
    ptr = load_json(POINTER)
    run_id = ptr.get("run_id")
    run_dir = os.path.join(VAULT, ptr.get("run_dir") or "")
    return ptr, run_id, run_dir


def verify_sealed_run(rows=None) -> dict:
    """§28.1：验证 D2 sealed run。任何一项不一致 → E PREPARATION = BLOCKED。"""
    checks = []

    def chk(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    try:
        ptr, run_id, run_dir = sealed_run()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "checks": [{"check": "pointer", "ok": False,
                                         "detail": str(exc)}]}

    chk("pointer.mode", ptr.get("mode") == "llm", ptr.get("mode"))
    chk("pointer.marker", ptr.get("marker") == "REAL_LLM_DIAGNOSTIC", ptr.get("marker"))
    man_p = os.path.join(run_dir, "run_manifest.json")
    res_p = os.path.join(run_dir, "results.json")
    met_p = os.path.join(run_dir, "metrics.json")
    seal_p = os.path.join(run_dir, "seal.json")
    for p in (man_p, res_p, met_p, seal_p):
        chk("file:" + os.path.basename(p), os.path.isfile(p), p)
    if not all(c["ok"] for c in checks):
        return {"ok": False, "checks": checks}

    man = load_json(man_p)
    res = load_json(res_p)
    seal = load_json(seal_p)

    chk("seal.sealed", seal.get("sealed") is True, seal.get("sealed"))
    chk("seal.human_validated_false", seal.get("human_validated") is False,
        seal.get("human_validated"))
    chk("seal.provider_success", seal.get("provider_success") == "14/14",
        seal.get("provider_success"))
    chk("seal.gate21_violations", seal.get("gate21_violations") == 0,
        seal.get("gate21_violations"))
    chk("seal.validator_version", seal.get("validator_version") == "entailment-validator/1",
        seal.get("validator_version"))
    # 三个可字节复算的 seal 字段
    chk("seal.manifest_hash", sha_file(man_p) == seal.get("manifest_hash"),
        sha_file(man_p)[:16])
    chk("seal.metrics_hash", sha_file(met_p) == seal.get("metrics_hash"),
        sha_file(met_p)[:16])
    chk("seal.results_hash", sha_file(res_p) == seal.get("results_hash"),
        sha_file(res_p)[:16])
    # 另 5 个 seal 字段是「逻辑子集哈希」，recipe 未落在代码里 → 诚实标注，不当作通过项
    logical_gap = {
        "raw_provider_outputs_hash": seal.get("raw_provider_outputs_hash"),
        "structured_claims_hash": seal.get("structured_claims_hash"),
        "entailment_results_hash": seal.get("entailment_results_hash"),
        "validated_claims_hash": seal.get("validated_claims_hash"),
        "final_answers_hash": seal.get("final_answers_hash"),
        "reproducible_from_repo": False,
        "note": ("这 5 个是当年按逻辑子集算的哈希，生成 recipe 未落库；"
                 "本阶段改用 E1 自己定义的逐题 answer_hash / packet_view_hash 复算，"
                 "并以 seal 的 3 个字节哈希 + manifest + audit + Gate 21 作为 run 完整性依据。"),
    }

    rows = res.get("rows") or []
    chk("results.rows_14", len(rows) == 14, len(rows))
    ids = [r.get("task_id") for r in rows]
    chk("results.task_ids_unique", len(set(ids)) == len(ids), len(set(ids)))
    chk("results.marker", res.get("marker") == "REAL_LLM_DIAGNOSTIC", res.get("marker"))
    chk("results.gate21_empty", len((res.get("gate21") or {}).get("violations") or []) == 0,
        len((res.get("gate21") or {}).get("violations") or []))
    chk("results.human_validated_false", res.get("human_validated") is False,
        res.get("human_validated"))
    chk("results.all_answers_present",
        all(isinstance(r.get("answer"), dict) and r.get("answer_state") for r in rows),
        sum(1 for r in rows if isinstance(r.get("answer"), dict)))

    # engine hash 无漂移（与 run manifest 钉住的 10 个模块逐个比对）
    live = {}
    for name, rel in _engine_name_path().items():
        p = os.path.join(VAULT, rel)
        live[name] = sha_file(p) if os.path.isfile(p) else None
    pinned = man.get("engine_hashes") or {}
    drift = {k: (v, live.get(k)) for k, v in pinned.items() if live.get(k) != v}
    chk("engine_hashes_no_drift", not drift,
        "10 个模块一致" if not drift else drift)
    chk("engine_hash_count", len(pinned) == 10, len(pinned))

    # prompt hashes（D2 §3 冻结值）
    try:
        sys.path.insert(0, TOOLS_DIR)
        sys.path.insert(0, os.path.join(TOOLS_DIR, "lacan_mcp"))
        import synthesis_adapters as sadapt  # noqa: PLC0415
        import synthesis_entailment as sent  # noqa: PLC0415
        prompt_h = {
            "synthesis_prompt_hash": sha_text(sadapt.SYSTEM_CONTRACT),
            "judge_prompt_hash": sha_text(sent.JUDGE_SYSTEM),
        }
    except Exception as exc:  # noqa: BLE001
        prompt_h = {"error": str(exc)}
    frozen = load_json(FROZEN_IDENTITY) if os.path.isfile(FROZEN_IDENTITY) else {}
    chk("prompt.synthesis", prompt_h.get("synthesis_prompt_hash") ==
        frozen.get("synthesis_prompt_hash"), prompt_h.get("synthesis_prompt_hash", "")[:16])
    chk("prompt.judge", prompt_h.get("judge_prompt_hash") ==
        frozen.get("judge_prompt_hash"), prompt_h.get("judge_prompt_hash", "")[:16])

    # Round 1 基线永久冻结
    if os.path.isfile(ROUND1_RECORDS):
        chk("round1.records_sha", sha_file(ROUND1_RECORDS) == ROUND1_RECORDS_SHA,
            sha_file(ROUND1_RECORDS)[:16])

    ok = all(c["ok"] for c in checks)
    return {"ok": ok, "checks": checks, "run_id": run_id, "run_dir": run_dir,
            "manifest_hash": sha_file(man_p), "results_hash": sha_file(res_p),
            "metrics_hash": sha_file(met_p), "seal": seal, "manifest": man,
            "gate21_violations": (res.get("gate21") or {}).get("violations") or [],
            "prompt_hashes": prompt_h, "engine_hashes": pinned,
            "legacy_seal_logical_hashes": logical_gap}


def _engine_name_path() -> dict:
    """engine_hashes 的键（basename）→ 仓库相对路径。"""
    out = {}
    for root, _dirs, files in os.walk(TOOLS_DIR):
        if "__pycache__" in root:
            continue
        for fn in files:
            if fn in ("synthesis_contract.py", "synthesis_claims.py", "synthesis_render.py",
                      "synthesis_adapters.py", "synthesis_entailment.py",
                      "synthesis_validation.py", "research_execution.py",
                      "research_contract.py", "research_answer.py", "eval_integrity.py",
                      "run_synthesis_4c1d.py"):
                out[fn] = os.path.relpath(os.path.join(root, fn), VAULT)
    return out


# ─────────────────────────────────────────────────────────── 任务与语料
def review_task_ids():
    """与 Round 1 完全相同的 14 个任务，顺序沿用冻结的 round-1 set。"""
    s = load_json(ROUND1_SET)
    return [it["task_id"] for it in s["items"]]


def task_defs():
    rows = load_jsonl(TASKS_P)
    return {r["task_id"]: r for r in rows}


def load_passage_map(ids) -> dict:
    """一次性扫描 passage store，只取被引用的段落。"""
    need = set(ids)
    out = {}
    if not need:
        return out
    with open(PASSAGES, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            p = json.loads(line)
            if p["id"] in need:
                out[p["id"]] = p
                if len(out) == len(need):
                    break
    return out


def excerpt_of(passage, span):
    txt = passage.get("normalized_text") or passage.get("raw_text") or ""
    if not txt:
        return {"excerpt": "", "excerpt_match": False}
    if span:
        i = txt.find(span)
        if i >= 0:
            a, b = max(0, i - 220), min(len(txt), i + len(span) + 220)
            return {"excerpt": txt[a:b], "excerpt_match": True,
                    "excerpt_span_offset": i}
    return {"excerpt": txt[:400], "excerpt_match": False}


# ────────────────────────────────────────────────────────── packet 渲染
def filter_limitations(text):
    """移除修复历史行（§8：不得展示 repair/reject 记录）；返回 (kept_text, dropped_n)。"""
    if not text:
        return None, 0
    kept, dropped = [], 0
    for line in str(text).split("\n"):
        if line.strip() and REPAIR_LINE_RE.search(line):
            dropped += 1
            continue
        kept.append(line)
    body = "\n".join(kept).strip()
    return (body or None), dropped


def render_packet(row, task, pmap) -> dict:
    a = row["answer"]
    txf = []

    # 正文：以封存 answer.sections（[{id,text}]，模板顺序）为准 —— 这就是渲染出来的答案
    sec_list, dropped_brief, dropped_repair, clean_n = [], 0, 0, 0
    raw_sections = a.get("sections")
    if isinstance(raw_sections, list) and raw_sections:
        for sec in raw_sections:
            sid, txt = sec.get("id"), sec.get("text")
            if sid == "brief_answer":            # 内部计数句 → 不进 packet
                dropped_brief += 1
                continue
            txt, d = filter_limitations(txt)
            dropped_repair += d
            txt, n = clean_text(txt)
            clean_n += n
            if txt:
                sec_list.append({"id": sid, "text": txt})
    else:                                        # 兜底：按命名段拼
        for key in ("main_analysis", "key_distinctions", "diachronic_analysis",
                    "source_notes", "limitations"):
            txt, d = filter_limitations(a.get(key))
            dropped_repair += d
            txt, n = clean_text(txt)
            clean_n += n
            if txt:
                sec_list.append({"id": key, "text": txt})
    if dropped_brief:
        txf.append({"field": "answer.sections[brief_answer]", "action": "removed",
                    "removed_n": dropped_brief,
                    "reason": "内部计数统计句，非学术内容"})
    if dropped_repair:
        txf.append({"field": "answer.sections[].text", "action": "filtered_lines",
                    "removed_n": dropped_repair,
                    "reason": "按盲评规则移除的内部工程记录行"})
    abst_view, abst_dropped = curate_abstention(a.get("abstention"))
    if abst_view is not None:
        abst_view, n = clean_tree(abst_view)
        clean_n += n
    if abst_dropped:
        txf.append({"field": "answer.abstention", "action": "curated_view",
                    "dropped_keys": abst_dropped,
                    "reason": "机器自检/内部字段，按盲评规则不入 packet"})
    if clean_n:
        txf.append({"field": "answer.sections", "action": "internal_vocab_neutralized",
                    "replaced_n": clean_n,
                    "reason": "按盲评规则把内部状态词/工具名/字段路径换成中性学术表述"})

    # claims（只用 validated set；claim_text 同样做内部词汇中性化，quoted_span 保持逐字）
    claims = []
    quotes = {}
    claim_clean_n = 0
    for c in row.get("validated_claims") or []:
        q = c.get("quotation") or {}
        if q.get("passage_id"):
            quotes[(c.get("claim_id"), q["passage_id"])] = q.get("exact_span")
        ctext, k = clean_text(c.get("claim_text"))
        claim_clean_n += k
        claims.append({
            "claim_id": c.get("claim_id"),
            "claim_type": c.get("claim_type"),
            "epistemic_status": c.get("epistemic_status"),
            "claim_text": ctext,
            "evidence_ids": c.get("evidence_ids") or [],
            "quoted_span": q.get("exact_span"),
            "quoted_from": q.get("passage_id"),
        })
    if claim_clean_n:
        txf.append({"field": "validated_claims[].claim_text",
                    "action": "internal_vocab_neutralized", "replaced_n": claim_clean_n,
                    "reason": "按盲评规则把内部状态词/工具名/字段路径换成中性学术表述"})

    # citations（实际被引用的证据；不含机器判定字段如 citation_eligibility）
    citations, missing = [], []
    for blk in a.get("citations") or []:
        cid = blk.get("claim_id")
        for ps in blk.get("passages") or []:
            pid = ps.get("passage_id")
            p = pmap.get(pid)
            if p is None:
                missing.append(pid)
                continue
            span = quotes.get((cid, pid))
            ex = excerpt_of(p, span)
            citations.append({
                "claim_id": cid,
                "passage_id": pid,
                "quoted_span": span,
                "seminar_id": ps.get("seminar_id") or p.get("seminar_id"),
                "language": ps.get("language") or p.get("language"),
                "source_layer": ps.get("source_layer"),
                "authority_level": ps.get("authority_level") or p.get("authority_level"),
                "text_role": ps.get("text_role") or p.get("text_role"),
                "provenance_status": ps.get("trace_status") or p.get("trace_status"),
                "year_from": p.get("year_from"),
                "year_to": p.get("year_to"),
                "excerpt": ex["excerpt"],
                "excerpt_match": ex["excerpt_match"],
            })

    # 事实性 source limitations（只陈述来源与可达性，不做评价）
    layers = sorted({c["source_layer"] for c in citations if c.get("source_layer")})
    incomplete = sorted({c["passage_id"] for c in citations
                         if (c.get("provenance_status") or "") != "COMPLETE"})
    src_lim = []
    if layers:
        src_lim.append({"kind": "CITED_SOURCE_LAYERS", "value": layers,
                        "statement": "本答案实际引用的来源层（L1 = 原始转写；"
                                     "L2 = recovered 文本）"})
    if incomplete:
        src_lim.append({"kind": "SOURCE_TRACE_INCOMPLETE", "passage_ids": incomplete,
                        "statement": "这些被引用段落的溯源链未闭合到原始物理文件"
                                     "（上游不可达），只有 recovered 文件级 sha256 可验"})
    man_abs, man_abs_n = clean_text((a.get("source_notes") or ""))
    if man_abs_n:
        txf.append({"field": "answer.source_notes", "action": "internal_vocab_neutralized",
                    "replaced_n": man_abs_n,
                    "reason": "按盲评规则把内部状态词/工具名/字段路径换成中性学术表述"})
    if man_abs:
        src_lim.append({"kind": "ANSWER_SOURCE_NOTES", "statement": man_abs})

    packet = {
        "schema_version": PACKET_SCHEMA,
        "blind": True,
        "review_round": 2,
        "task": {"task_id": row["task_id"], "question": row["question"],
                 "task_type": row.get("task_type") or task.get("task_type")},
        "answer_state": {
            "answer_state": a.get("answer_state"),
            "answer_permission": a.get("answer_permission"),
            "synthesis_template": a.get("synthesis_template"),
        },
        "final_answer": {
            "source": ("D2 sealed run 的 validated final scholarly answer"
                       "（取封存 run 的 answer.sections，逐段顺序不变；"
                       "仅按盲评规则移除/中性化内部工程字段）"),
            "sections": sec_list,
            "abstention": abst_view,
        },
        "claims": claims,
        "citations": citations,
        "source_limitations": src_lim,
        "integrity": {
            "source_run_id": None,          # build 时填
            "answer_hash": canon_hash(a),
            "packet_view_hash": None,       # build 时填
            # packet 里只放**计数级**变换记录（不含内部字段名/词汇）；
            # 逐条明细写进 manifest 的 packet_view_transforms_detail（不进 reviewer 视野）
            "view_transforms": [{
                k: t[k] for k in ("field", "action", "removed_n", "replaced_n") if k in t
            } for t in txf],
            "missing_passages": missing,
        },
        "review_form": {
            "human_scores": {d: None for d in DIMENSIONS},
            "citation_support": None,
            "scholarly_usable": None,
            "reviewer_comment": {"most_worth_keeping": None,
                                 "most_needing_change": None, "raw": None},
            "scale_note": ("6 维各 1–5；historical_accuracy 可填 N/A；"
                           "overclaiming = 5 表示没有明显过度断言（越高越好，未反转）"),
            "system_may_not_score": ("本表由**人类 reviewer** 填写；"
                                     "系统不得代填、不得据任何机器指标或内部验证流程推断"),
        },
    }
    packet["integrity"]["packet_view_hash"] = canon_hash({
        "final_answer": packet["final_answer"], "claims": claims,
        "citations": citations, "source_limitations": src_lim,
    })
    # 逐条变换明细：build() 会把它从 packet 里摘出来，只写进 manifest
    packet["_detail_transforms"] = txf
    return packet


def packet_markdown(pkt, honesty_note=True) -> str:
    t, a, ans = pkt["task"], pkt["answer_state"], pkt["final_answer"]
    L = []
    L.append("# Review %s / 14 — %s（盲评 Round 2）" % ("{n}", t["task_id"]))
    L.append("")
    L.append("## A. Task")
    L.append("")
    L.append("* `task_id`: `%s`" % t["task_id"])
    L.append("* `task_type`: `%s`" % t["task_type"])
    L.append("* question: %s" % t["question"])
    L.append("")
    L.append("## B. Current Final Answer（validated final scholarly answer）")
    L.append("")
    SEC_TITLE = {
        "working_definition": "工作定义", "key_distinctions": "关键区分",
        "relationship": "关系", "diachronic_analysis": "历时分析",
        "diachronic": "历时分析", "terminology": "术语",
        "formalism": "形式化", "limitations": "限制", "source_notes": "来源说明",
        "main_analysis": "主分析", "abstention": "弃权说明", "comparison": "比较",
        "metadata": "元数据", "translation": "翻译",
    }
    secs = ans.get("sections")
    if isinstance(secs, list):
        for sec in secs:
            L.append("### %s" % SEC_TITLE.get(sec.get("id"), sec.get("id")))
            L.append("")
            L.append(str(sec.get("text") or "").strip())
            L.append("")
    elif isinstance(secs, dict):
        for kk, vv in secs.items():
            L.append("### %s" % SEC_TITLE.get(kk, kk))
            L.append("")
            L.append(str(vv).strip())
            L.append("")
    abst = ans.get("abstention")
    if abst:
        L.append("### 弃权说明")
        L.append("")
        if isinstance(abst, dict):
            for kk, vv in abst.items():
                if isinstance(vv, list):
                    L.append("* **%s**：" % kk)
                    for item in vv:
                        L.append("  * %s" % str(item).strip())
                else:
                    L.append("* **%s**：%s" % (kk, vv))
        else:
            L.append(str(abst).strip())
        L.append("")
    L.append("## C. Answer State")
    L.append("")
    L.append("* `answer_state`: `%s`　·　`answer_permission`: `%s`　·　template: `%s`"
             % (a["answer_state"], a["answer_permission"], a["synthesis_template"]))
    L.append("")
    L.append("## D. Claims（已通过验证的断言）")
    L.append("")
    L.append("| claim_id | type | epistemic_status | claim |")
    L.append("|---|---|---|---|")
    for c in pkt["claims"]:
        L.append("| `%s` | %s | %s | %s |" % (c["claim_id"], c["claim_type"],
                                              c["epistemic_status"],
                                              str(c["claim_text"]).replace("|", "\\|")))
    L.append("")
    L.append("## E. Citations / Evidence（答案实际引用的证据）")
    L.append("")
    for c in pkt["citations"]:
        L.append("* **%s** ← `%s`（%s · %s · %s · provenance=%s%s）"
                 % (c["claim_id"], c["passage_id"], c["seminar_id"], c["language"],
                    c["source_layer"], c["provenance_status"],
                    "" if not (c.get("year_from") or c.get("year_to"))
                    else " · %s–%s" % (c.get("year_from"), c.get("year_to"))))
        if c.get("quoted_span"):
            L.append("  * quoted span: `%s`" % c["quoted_span"])
        L.append("  * excerpt: %s" % (c.get("excerpt") or "").replace("\n", " ").strip()[:600])
    L.append("")
    L.append("## F. Source Limitations（事实描述，不含评价）")
    L.append("")
    for s in pkt["source_limitations"]:
        L.append("* **%s**：%s" % (s["kind"], s.get("statement") or s.get("value")))
    if not pkt["source_limitations"]:
        L.append("* （本包无额外来源限制条目）")
    L.append("")
    L.append("## G. Review Form（**仅由人类填写**）")
    L.append("")
    L.append("```")
    for d in DIMENSIONS:
        L.append("%-26s : 1–5%s" % (d, " 或 N/A" if d == "historical_accuracy" else ""))
    L.append("%-26s : PASS / PARTIAL / FAIL" % "citation_support")
    L.append("%-26s : YES / WITH_REVISION / NO" % "scholarly_usable")
    L.append("%-26s : ..." % "reviewer_comment")
    L.append("```")
    L.append("")
    L.append("> %s" % pkt["review_form"]["scale_note"])
    L.append(">")
    L.append("> **系统不得代填任何一项**：本表由人类 reviewer 填写；"
             "不得据任何机器指标或内部验证流程推断分数。")
    if honesty_note:
        L.append("")
        L.append("---")
        L.append("")
        L.append("> 盲评说明：本包为盲评视图。正文逐字取自 D2 封存 run 的 validated final "
                 "answer；按盲评规则移除了内部工程字段（见 `integrity.view_transforms`）。"
                 "本包不含既往评审的任何记录、也不含任何倾向性提示。")
    L.append("")
    return "\n".join(L)


# ────────────────────────────────────────────────────────── 泄漏扫描
def blindness_hits(text: str):
    hits = []
    low = text
    for tok in BLIND_FORBIDDEN:
        if re.fullmatch(r"[A-Za-z0-9_ ]+", tok):
            if re.search(r"\b%s\b" % re.escape(tok), low, flags=re.IGNORECASE):
                hits.append(tok)
        else:
            if tok in low:
                hits.append(tok)
    return sorted(set(hits))


def blindness_scan(packet) -> list:
    hits = []
    for where, blob in (("packet.json", canon(packet)),
                        ("packet.md", packet_markdown(packet))):
        for tok in blindness_hits(blob):
            hits.append({"where": where, "token": tok})
    return hits


# ────────────────────────────────────────────────────────── E1: build
def build(quiet=False):
    ver = verify_sealed_run()
    if not ver["ok"]:
        print("E PREPARATION = BLOCKED（D2 sealed run 校验未通过）")
        for c in ver["checks"]:
            if not c["ok"]:
                print("  - %s: %s" % (c["check"], c["detail"]))
        return 3

    ptr, run_id, run_dir = sealed_run()
    res = load_json(os.path.join(run_dir, "results.json"))
    rows = {r["task_id"]: r for r in res["rows"]}
    defs = task_defs()
    ids = review_task_ids()
    missing = [t for t in ids if t not in rows]
    if missing:
        print("E PREPARATION = BLOCKED（sealed run 缺任务：%s）" % missing)
        return 3

    cited = set()
    for t in ids:
        for blk in (rows[t]["answer"].get("citations") or []):
            for ps in blk.get("passages") or []:
                if ps.get("passage_id"):
                    cited.add(ps["passage_id"])
    pmap = load_passage_map(cited)
    unresolved = sorted(cited - set(pmap))

    packets = {}
    detail_transforms = {}
    for t in ids:
        pkt = render_packet(rows[t], defs.get(t, {}), pmap)
        pkt["integrity"]["source_run_id"] = run_id
        pkt["integrity"]["missing_passages"] = sorted(
            set(pkt["integrity"]["missing_passages"]))
        # 先把逐条变换明细摘出来（它含内部字段名，**不得**进 packet，也不得参与泄漏扫描）
        detail_transforms[t] = pkt.pop("_detail_transforms", [])
        packets[t] = pkt

    # 盲评泄漏扫描 → 不干净就拒绝出包
    leaks = {}
    for t in ids:
        h = blindness_scan(packets[t])
        if h:
            leaks[t] = h
    if leaks:
        print("E PREPARATION = BLOCKED（盲评包泄漏 Round1/内部信息）")
        for t, h in leaks.items():
            print("  - %s: %s" % (t, h[:6]))
        return 3

    os.makedirs(PACKETS, exist_ok=True)
    # set（只有顺序与完整性，不含 bucket / 旧状态 / 理由）
    prev_set = load_json(SET_V1) if os.path.isfile(SET_V1) else None
    rowmap = {}
    if os.path.isfile(DATASET):
        for r in load_jsonl(DATASET):
            rowmap[r["task_id"]] = r
    set_doc = {
        "schema_version": SET_VERSION,
        "phase": "Phase 4C.1-E",
        "selection_policy": ("与 Round 1 **完全相同**的 14 个任务（顺序沿用 "
                             "_data/eval/human_review_set_v1.json）。盲评：不展示 "
                             "bucket / 旧状态 / 期望改善。"),
        "source_run_id": run_id,
        "items": [],
    }
    dataset = []
    for n, t in enumerate(ids, 1):
        pkt = packets[t]
        pj = os.path.join(PACKETS, "%s.json" % t)
        pm = os.path.join(PACKETS, "%s.md" % t)
        write_json(pj, pkt)
        md = packet_markdown(pkt, honesty_note=False).replace("{n}", str(n))
        with open(pm, "w", encoding="utf-8") as f:
            f.write(md)
        set_doc["items"].append({
            "order": n, "task_id": t,
            "task_type": (defs.get(t) or {}).get("task_type"),
            "question": rows[t]["question"],
            "answer_hash": pkt["integrity"]["answer_hash"],
            "answer_state": pkt["answer_state"]["answer_state"],
        })
        old = rowmap.get(t) or {}
        dataset.append({
            "schema_version": RECORD_SCHEMA,
            "review_round": 2,
            "review_status": old.get("review_status") or "NOT_REVIEWED",
            "task_id": t,
            "question": rows[t]["question"],
            "task_type": (defs.get(t) or {}).get("task_type"),
            "source_run_id": run_id,
            "source_answer_hash": pkt["integrity"]["answer_hash"],
            "answer_state": pkt["answer_state"]["answer_state"],
            "answer_permission": pkt["answer_state"]["answer_permission"],
            "human_scores": old.get("human_scores"),
            "citation_support": old.get("citation_support"),
            "scholarly_usable": old.get("scholarly_usable"),
            "reviewer_comment": old.get("reviewer_comment"),
            "requested_changes": old.get("requested_changes"),
            "reviewer_id": old.get("reviewer_id"),
            "reviewed_at": old.get("reviewed_at"),
            "reviewer_type": old.get("reviewer_type"),
            "provenance": old.get("provenance"),
            "system_may_not_score_attestation":
                "本记录由人类 reviewer 给出；系统只做格式校验与落盘，不参与评分。",
        })
    write_json(SET_V1, set_doc)
    write_jsonl(DATASET, dataset)

    reviewed = sum(1 for r in dataset if r["review_status"] == "REVIEWED")
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "round2_review_set_version": SET_VERSION,
        "phase": "Phase 4C.1-E",
        "generated_at": utcnow(),
        "git_head": _git_head(),
        "source_run_id": run_id,
        "source_run_dir": os.path.relpath(run_dir, VAULT),
        "source_run_manifest_hash": ver["manifest_hash"],
        "source_run_results_hash": ver["results_hash"],
        "source_run_metrics_hash": ver["metrics_hash"],
        "source_run_seal": {
            "sealed": ver["seal"].get("sealed"),
            "human_validated": ver["seal"].get("human_validated"),
            "provider_success": ver["seal"].get("provider_success"),
            "gate21_violations": ver["seal"].get("gate21_violations"),
            "validator_version": ver["seal"].get("validator_version"),
        },
        "legacy_seal_logical_hashes": ver["legacy_seal_logical_hashes"],
        "engine_hashes": ver["engine_hashes"],
        "prompt_hashes": {k: v for k, v in (ver["prompt_hashes"] or {}).items()},
        "reviewer": {"reviewer_count": 1, "reviewer_status": "SINGLE_REVIEWER",
                     "inter_rater_agreement": "NOT_APPLICABLE"},
        "frozen_artifacts": {
            "gate": {"path": os.path.relpath(GATE_P, VAULT), "sha256": sha_file(GATE_P)},
            "taxonomy": {"path": os.path.relpath(TAXONOMY_P, VAULT),
                         "sha256": sha_file(TAXONOMY_P)},
            "schema": {"path": os.path.relpath(SCHEMA_P, VAULT),
                       "sha256": sha_file(SCHEMA_P)},
            "frozen_identity": {"path": os.path.relpath(FROZEN_IDENTITY, VAULT),
                                "sha256": sha_file(FROZEN_IDENTITY)},
            "round1_records": {"path": os.path.relpath(ROUND1_RECORDS, VAULT),
                               "sha256": sha_file(ROUND1_RECORDS)},
            "round1_results": {"path": os.path.relpath(ROUND1_RESULTS, VAULT),
                               "sha256": sha_file(ROUND1_RESULTS)},
        },
        "dataset_state_at_freeze": {
            "total": len(dataset), "reviewed": reviewed,
            "not_reviewed": len(dataset) - reviewed,
            "any_human_score_present": any(
                r.get("human_scores") or r.get("citation_support") or
                r.get("scholarly_usable") for r in dataset),
            "note": "gate 在本状态（reviewed=0）冻结；此后不得修改。",
        },
        "blindness": {
            "clean": True, "checked_packets": len(ids),
            "forbidden_tokens": BLIND_FORBIDDEN,
            "hits": {},
        },
        "answer_hash_per_task": {t: packets[t]["integrity"]["answer_hash"] for t in ids},
        "packet_view_hash_per_task": {t: packets[t]["integrity"]["packet_view_hash"]
                                      for t in ids},
        "tasks": [{
            "order": i + 1, "task_id": t,
            "answer_hash": packets[t]["integrity"]["answer_hash"],
            "packet_view_hash": packets[t]["integrity"]["packet_view_hash"],
            "claims_n": len(packets[t]["claims"]),
            "citations_n": len(packets[t]["citations"]),
            "answer_state": packets[t]["answer_state"]["answer_state"],
        } for i, t in enumerate(ids)],
        "citation_resolution": {
            "cited_passages": len(cited), "resolved": len(pmap),
            "unresolved": unresolved,
        },
        "packet_view_transforms_detail": detail_transforms,
        "verification": ver["checks"],
    }
    write_json(MANIFEST, manifest)
    if not quiet:
        print("E1 出包完成：%d 包；cited passages %d（未解析 %d）；盲评扫描 clean；"
              "REVIEWED %d/%d" % (len(ids), len(cited), len(unresolved), reviewed, len(ids)))
        print("  → %s" % os.path.relpath(PACKETS, VAULT))
        print("  → %s / %s / %s" % (os.path.relpath(SET_V1, VAULT),
                                    os.path.relpath(DATASET, VAULT),
                                    os.path.relpath(MANIFEST, VAULT)))
    return 0


def _git_head() -> str:
    import subprocess
    try:
        return subprocess.run(["git", "-C", VAULT, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


# ────────────────────────────────────────────────────────── E1/E2: check
def check(quiet=False) -> int:
    problems = []
    if not os.path.isfile(MANIFEST):
        print("FAIL 尚未出包（缺 %s）" % os.path.relpath(MANIFEST, VAULT))
        return 1
    man = load_json(MANIFEST)
    ids = [t["task_id"] for t in man["tasks"]]
    # ① 冻结件哈希未变（acceptance rule / taxonomy / schema 被改即违规）
    for key, path in (("gate", GATE_P), ("taxonomy", TAXONOMY_P), ("schema", SCHEMA_P)):
        want = (man["frozen_artifacts"][key] or {}).get("sha256")
        got = sha_file(path) if os.path.isfile(path) else None
        if got != want:
            problems.append("冻结件被改动：%s（%s != %s）" % (key, str(got)[:16], str(want)[:16]))
    # ② packet 14/14 + 内容与封存 run 一致 + 无泄漏
    ptr, run_id, run_dir = sealed_run()
    res = load_json(os.path.join(run_dir, "results.json"))
    rows = {r["task_id"]: r for r in res["rows"]}
    for t in ids:
        pj = os.path.join(PACKETS, "%s.json" % t)
        pm = os.path.join(PACKETS, "%s.md" % t)
        if not (os.path.isfile(pj) and os.path.isfile(pm)):
            problems.append("缺 packet：%s" % t)
            continue
        pkt = load_json(pj)
        got = canon_hash(rows[t]["answer"])
        if got != pkt["integrity"]["answer_hash"]:
            problems.append("%s: answer_hash 与封存 run 不一致" % t)
        if canon_hash({"final_answer": pkt["final_answer"], "claims": pkt["claims"],
                       "citations": pkt["citations"],
                       "source_limitations": pkt["source_limitations"]}) \
                != pkt["integrity"]["packet_view_hash"]:
            problems.append("%s: packet_view_hash 不可复算" % t)
        if pkt["integrity"].get("missing_passages"):
            problems.append("%s: citation 未解析 %s" % (t, pkt["integrity"]["missing_passages"]))
        h = blindness_scan(pkt)
        if h:
            problems.append("%s: 盲评泄漏 %s" % (t, h[:4]))
    # ③ dataset schema + 「系统不得代填」
    rows2 = load_jsonl(DATASET) if os.path.isfile(DATASET) else []
    if len(rows2) != len(ids):
        problems.append("dataset 行数 %d != %d" % (len(rows2), len(ids)))
    reviewed = 0
    for r in rows2:
        ok, errs = validate_record(r)
        if not ok:
            problems.append("%s: schema 违规 %s" % (r.get("task_id"), errs[:3]))
        if r.get("review_status") == "REVIEWED":
            reviewed += 1
            if (r.get("provenance") or {}).get("written_by") != \
                    "review recorder (no scoring by system)":
                problems.append("%s: 缺少『系统不评分』provenance" % r["task_id"])
            if not (r.get("provenance") or {}).get("submitted_by"):
                problems.append("%s: 缺少 submitted_by（人类提交凭证）" % r["task_id"])
            if r.get("source_answer_hash") != (rows.get(r["task_id"], {})
                                               .get("answer") and
                                               canon_hash(rows[r["task_id"]]["answer"])):
                problems.append("%s: source_answer_hash 与封存答案不一致" % r["task_id"])
        else:
            if any(r.get(k) for k in ("human_scores", "citation_support",
                                      "scholarly_usable", "reviewer_comment")):
                problems.append("%s: NOT_REVIEWED 却已有评分字段" % r["task_id"])
    if problems:
        print("FAIL 4C.1-E Round2 准备校验未通过：")
        for p in problems[:12]:
            print("  - %s" % p)
        return 1
    if not quiet:
        print("4C.1-E Round2 准备校验通过：packets %d/%d；盲评无泄漏；"
              "gate/taxonomy/schema 哈希未变；%d/%d REVIEWED"
              % (len(ids), len(ids), reviewed, len(ids)))
    return 0


def validate_record(rec) -> tuple:
    """用 JSON Schema 校验一条 Round 2 记录（stdlib 无 jsonschema 时退化为手工校验）。"""
    errs = []
    try:
        import jsonschema  # noqa: PLC0415
        schema = load_json(SCHEMA_P)
        v = jsonschema.Draft202012Validator(schema)
        for e in v.iter_errors(rec):
            errs.append("%s: %s" % ("/".join(str(x) for x in e.absolute_path) or "(root)",
                                    e.message))
        return (not errs), errs
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        return False, ["schema 校验器异常：%s" % exc]
    if rec.get("review_round") != 2:
        errs.append("review_round != 2")
    if rec.get("review_status") not in ("NOT_REVIEWED", "REVIEWED"):
        errs.append("review_status 非法")
    if rec.get("review_status") == "REVIEWED":
        hs = rec.get("human_scores") or {}
        for d in DIMENSIONS:
            if d not in hs:
                errs.append("缺维度 %s" % d)
        if rec.get("citation_support") not in CITATION_SUPPORT:
            errs.append("citation_support 非法")
        if rec.get("scholarly_usable") not in SCHOLARLY_USABLE:
            errs.append("scholarly_usable 非法")
    return (not errs), errs


# ────────────────────────────────────────────────────────── 记录（人工提交）
def record(task_id, payload, submitted_by, amend_reason=None, quiet=False) -> int:
    rows = load_jsonl(DATASET) if os.path.isfile(DATASET) else []
    idx = next((i for i, r in enumerate(rows) if r["task_id"] == task_id), None)
    if idx is None:
        print("FAIL 未知 task_id：%s" % task_id)
        return 2
    rec = rows[idx]
    if rec.get("review_status") == "REVIEWED" and not amend_reason:
        print("拒绝覆盖：%s 已是 REVIEWED（如需更正请给出 --reason）" % task_id)
        return 2

    hs = payload.get("human_scores") or {}
    missing = [d for d in DIMENSIONS if d not in hs]
    if missing or payload.get("citation_support") not in CITATION_SUPPORT \
            or payload.get("scholarly_usable") not in SCHOLARLY_USABLE:
        print("FAIL 评分不完整，拒绝写入（系统**不会**替你猜任何一项）：")
        if missing:
            print("  - 缺维度: %s" % ", ".join(missing))
        if payload.get("citation_support") not in CITATION_SUPPORT:
            print("  - citation_support 必须是 PASS/PARTIAL/FAIL")
        if payload.get("scholarly_usable") not in SCHOLARLY_USABLE:
            print("  - scholarly_usable 必须是 YES/WITH_REVISION/NO")
        return 2
    for d in DIMENSIONS:
        v = hs.get(d)
        if d == "historical_accuracy" and (v in (None, "N/A")):
            continue
        if not (isinstance(v, int) and 1 <= v <= 5):
            print("FAIL 维度 %s=%r 非法（须 1–5%s）"
                  % (d, v, " 或 N/A" if d == "historical_accuracy" else ""))
            return 2
    comment = payload.get("reviewer_comment") or {}
    if not (comment.get("raw") or comment.get("most_worth_keeping")
            or comment.get("most_needing_change")):
        print("FAIL 缺 reviewer_comment（至少回答：最值得保留 / 最大问题 / 需要什么改变）")
        return 2

    rec.update({
        "review_status": "REVIEWED",
        "human_scores": hs,
        "citation_support": payload["citation_support"],
        "scholarly_usable": payload["scholarly_usable"],
        "reviewer_comment": comment,
        "requested_changes": payload.get("requested_changes"),
        "reviewer_id": payload.get("reviewer_id") or "not_supplied_by_reviewer",
        "reviewed_at": utcnow(),
        "reviewer_type": "human",
        "provenance": {
            "written_by": "review recorder (no scoring by system)",
            "submitted_by": submitted_by,
            "validated": True,
            "note": ("分数与评论由人类提交；系统只做格式校验与落盘，不参与评分。"
                     + ("" if not amend_reason else "（更正理由：%s）" % amend_reason)),
        },
    })
    ok, errs = validate_record(rec)
    if not ok:
        print("FAIL 记录不符合 round2 schema，未写入：%s" % errs[:4])
        return 2
    rows[idx] = rec
    write_jsonl(DATASET, rows)
    reviewed = sum(1 for r in rows if r["review_status"] == "REVIEWED")
    if not quiet:
        print("已写入 %s（%d/%d REVIEWED）" % (task_id, reviewed, len(rows)))
    return 0


# ────────────────────────────────────────────────────────── 展示
def show(task_id) -> int:
    p = os.path.join(PACKETS, "%s.md" % task_id)
    if not os.path.isfile(p):
        print("FAIL 缺 packet：%s（先 --build）" % task_id)
        return 2
    with open(p, encoding="utf-8") as f:
        txt = f.read()
    print(txt)
    n = None
    if os.path.isfile(SET_V1):
        for it in load_json(SET_V1)["items"]:
            if it["task_id"] == task_id:
                n = it["order"]
    reviewed = 0
    total = 0
    if os.path.isfile(DATASET):
        rows = load_jsonl(DATASET)
        total = len(rows)
        reviewed = sum(1 for r in rows if r["review_status"] == "REVIEWED")
    print("> 进度：%s/%s REVIEWED（当前包：Review %s / %s）"
          % (reviewed, total, n, total))
    return 0


# ────────────────────────────────────────────────────────── E2: aggregate
def _taxonomy_round1():
    d = load_json(ROUND1_RESULTS)
    tax = load_json(TAXONOMY_P)
    cmap = tax["round1_issue_code_map"]
    freq = d.get("issue_code_frequency") or {}
    out = {c: 0 for c in tax["classes"]}
    for code, n in freq.items():
        cls = cmap.get(code)
        if cls:
            out[cls] += n
    return out


def _taxonomy_round2(records):
    tax = load_json(TAXONOMY_P)
    out = {c: 0 for c in tax["classes"]}
    for r in records:
        txt = " ".join([
            (r.get("reviewer_comment") or {}).get("raw") or "",
            (r.get("reviewer_comment") or {}).get("most_needing_change") or "",
            " ".join(r.get("requested_changes") or []),
        ])
        for rule in tax["keyword_rules_ordered"]:
            for kw in rule["keywords"]:
                if re.fullmatch(r"[A-Za-z0-9_ ]+", kw):
                    hit = re.search(r"\b%s\b" % re.escape(kw), txt, flags=re.IGNORECASE)
                else:
                    hit = kw in txt
                if hit:
                    out[rule["class"]] += 1
                    break
    return out


def _stats(values):
    vals = sorted(v for v in values if isinstance(v, int))
    if not vals:
        return {"n": 0, "mean": None, "median": None}
    n = len(vals)
    mean = round(sum(vals) / n, 4)
    med = vals[n // 2] if n % 2 else round((vals[n // 2 - 1] + vals[n // 2]) / 2, 4)
    return {"n": n, "mean": mean, "median": med}


def aggregate(quiet=False) -> int:
    rows = load_jsonl(DATASET) if os.path.isfile(DATASET) else []
    reviewed = [r for r in rows if r.get("review_status") == "REVIEWED"]
    if len(reviewed) != 14:
        if not quiet:
            print("NOT_READY 尚未完成：%d/14 REVIEWED —— 14/14 之前不得汇总/对照（§16/§31）"
                  % len(reviewed))
        return 2
    man = load_json(MANIFEST)
    gate = load_json(GATE_P)
    if sha_file(GATE_P) != (man["frozen_artifacts"]["gate"] or {}).get("sha256"):
        print("FAIL acceptance rule 在冻结后被修改 —— 拒绝汇总（评审结果不可信）")
        return 2

    by_type = {}
    for r in reviewed:
        by_type.setdefault(r["task_id"], []).append(r)
    usable = {k: 0 for k in SCHOLARLY_USABLE}
    cit = {k: 0 for k in CITATION_SUPPORT}
    for r in reviewed:
        usable[r["scholarly_usable"]] += 1
        cit[r["citation_support"]] += 1
    dims = {}
    for d in DIMENSIONS:
        vals, na = [], 0
        for r in reviewed:
            v = (r.get("human_scores") or {}).get(d)
            if v == "N/A" or v is None:
                na += 1
                continue
            vals.append(v)
        s = _stats(vals)
        s["n_na"] = na
        s["na_tasks"] = [r["task_id"] for r in reviewed
                         if (r.get("human_scores") or {}).get(d) in (None, "N/A")]
        dims[d] = s

    r1 = load_json(ROUND1_RESULTS)
    cmp_dims = {}
    for d in DIMENSIONS:
        m1 = (r1["per_dimension"].get(d) or {}).get("mean")
        m2 = dims[d]["mean"]
        cmp_dims[d] = {
            "round1_mean": m1, "round2_mean": m2,
            "delta": None if (m1 is None or m2 is None) else round(m2 - m1, 4),
        }
    transitions = []
    r1rec = {r["task_id"]: r for r in load_jsonl(ROUND1_RECORDS)}
    for r in sorted(reviewed, key=lambda x: x["task_id"]):
        o = r1rec.get(r["task_id"], {})
        dd = {}
        for d in DIMENSIONS:
            a = (o.get("human_scores") or {}).get(d)
            b = (r.get("human_scores") or {}).get(d)
            if isinstance(a, int) and isinstance(b, int):
                dd[d] = b - a
        transitions.append({
            "task_id": r["task_id"],
            "round1_scholarly_usable": o.get("scholarly_usable"),
            "round2_scholarly_usable": r["scholarly_usable"],
            "round1_citation_support": o.get("citation_support"),
            "round2_citation_support": r["citation_support"],
            "dimension_deltas": dd,
        })

    tax1, tax2 = _taxonomy_round1(), _taxonomy_round2(reviewed)
    tax_delta = {c: {"round1": tax1.get(c, 0), "round2": tax2.get(c, 0),
                     "delta": tax2.get(c, 0) - tax1.get(c, 0)}
                 for c in load_json(TAXONOMY_P)["classes"]}

    # 机器指标（并列报告，绝不用于推断 scholarly_usable）
    ptr, run_id, run_dir = sealed_run()
    met = load_json(os.path.join(run_dir, "metrics.json"))
    res = load_json(os.path.join(run_dir, "results.json"))
    g21_counts = {}
    for v in (res.get("gate21") or {}).get("violations") or []:
        code = v.get("code") if isinstance(v, dict) else str(v)
        g21_counts[code] = g21_counts.get(code, 0) + 1
    machine = {
        "run_id": run_id,
        "gate21_violation_total": sum(g21_counts.values()),
        "gate21_by_code": g21_counts,
        "claim_validation_rate": met.get("claim_validation_rate"),
        "rejected_claim_rate": met.get("rejected_claim_rate"),
        "direct_entailment_rate": met.get("direct_entailment_rate"),
        "quote_validation_rate": met.get("quote_validation_rate"),
        "disclaimer": gate["machine_metrics_disclaimer"],
    }

    verdict = _evaluate_gate(gate, usable, cit, dims, cmp_dims, g21_counts, tax2, reviewed)
    diagnosis = (None if verdict["verdict"] == "SCHOLARLY_CORE_READY"
                 else _not_ready_diagnosis(gate, verdict, reviewed, tax2, g21_counts))

    out = {
        "schema_version": "human-review-results/v2",
        "phase": "Phase 4C.1-E — Final Scholarly Regression + Human Review Round 2",
        "generated_at": utcnow(),
        "generated_by": "deterministic aggregation (no scoring by the system)",
        "inputs": {
            "round2_records": os.path.relpath(DATASET, VAULT),
            "round2_records_sha256": sha_file(DATASET),
            "packets_dir": os.path.relpath(PACKETS, VAULT),
            "review_set": os.path.relpath(SET_V1, VAULT),
            "manifest": os.path.relpath(MANIFEST, VAULT),
            "source_run_id": run_id,
            "round1_records_sha256": sha_file(ROUND1_RECORDS),
            "gate_sha256": sha_file(GATE_P),
            "taxonomy_sha256": sha_file(TAXONOMY_P),
        },
        "reviewer": gate["reviewer"],
        "completeness": {"records_total": len(rows), "reviewed": len(reviewed),
                         "missing": [r["task_id"] for r in rows
                                     if r["review_status"] != "REVIEWED"],
                         "all_reviewed": len(reviewed) == 14},
        "by_scholarly_usable": usable,
        "by_citation_support": cit,
        "per_dimension": dims,
        "round1_vs_round2": {
            "scholarly_usable": {"round1": r1["scholarly_usable"], "round2": usable},
            "citation_support": {"round1": r1["citation_support"], "round2": cit},
            "per_dimension": cmp_dims,
        },
        "per_task_transition": transitions,
        "error_taxonomy_delta": tax_delta,
        "machine_metrics": machine,
        "readiness_gate": verdict,
        "g5_evaluator": {
            "version": G5_EVALUATOR_VERSION,
            "machine_fields_used": list(G5_MACHINE_FIELDS),
            "outside_knowledge_supporting_evidence":
                _g5_supporting_outside_knowledge_evidence(),
            "taxonomy_role": "diagnostic_only（不参与 G5 pass/fail）",
        },
        "gate_evaluation_history": _gate_evaluation_history(verdict),
        "not_ready_diagnosis": diagnosis,
    }
    write_json(RESULTS_V2, out)
    with open(RESULTS_V2_MD, "w", encoding="utf-8") as f:
        f.write(render_results_md(out, gate))
    with open(FINAL_MD, "w", encoding="utf-8") as f:
        f.write(render_final_md(out, gate))
    if not quiet:
        print("E2 汇总完成 → %s / %s / %s" % (os.path.relpath(RESULTS_V2, VAULT),
                                              os.path.basename(RESULTS_V2_MD),
                                              os.path.basename(FINAL_MD)))
        print("  verdict = %s" % verdict["verdict"])
    return 0


G5_EVALUATOR_VERSION = "gate-evaluator/2"

# G5 的**机器侧**只使用冻结引擎**已有**的 Gate 21 字段（不新建阈值）：
G5_MACHINE_FIELDS = ("D_ABSTENTION_CONTAINS_SUBSTANTIVE_CLAIM",)

# G5 的**人工侧**：只识别 reviewer **明确报告**了弃权完整性失败。
# 「提到弃权」≠「弃权完整性失败」：肯定式/中性提及（如「正确且有信息价值的学术弃权」）
# 一律**不得**计为 violation。Error taxonomy 的 ABSTENTION_FAILURE 关键词频次
# 仅作 diagnostic reporting，**不参与** G5 判定。
ABSTENTION_VIOLATION_PATTERNS = [
    ("V1_SHOULD_HAVE_ABSTAINED",
     r"(本应|本该|应当|应该|应予|理应)[^。；\n]{0,12}(弃权|拒答|说明无法回答)"
     r"[^。；\n]{0,8}(但|却|仍|还是|反而)"),
    ("V2_EXPLICIT_ABSTENTION_FAILURE",
     r"(弃权失败|弃权失效|违反弃权|破坏弃权|abstention\s*(failure|violation)|"
     r"弃权完整性[^。；\n]{0,8}(失败|破坏|违反|不成立))"),
    ("V3_MODEL_KNOWLEDGE_USED",
     r"(使用|利用|依赖|调用|借助)[^。；\n]{0,14}(模型自身|自身|模型|训练数据|预训练)"
     r"[^。；\n]{0,8}(知识|记忆)[^。；\n]{0,12}(回答|补写|输出|给出|生成|断言|作答)"),
    ("V4_EVIDENCE_ABSENT_BUT_ANSWERED",
     r"(缺乏证据|没有证据|无证据|证据不足|证据之外|语料外|包外|corpus\s*外)"
     r"[^。；\n]{0,10}(却|仍然|仍|还是|反而)[^。；\n]{0,14}"
     r"(回答|断言|给出具体|补写|输出|结论|作答)"),
    ("V5_ABSTAIN_LABEL_BUT_CONTENT",
     r"(标记|声称|自称|标示)[^。；\n]{0,8}(ABSTAIN|ABSTAINED|弃权)[^。；\n]{0,20}(但|却)"
     r"[^。；\n]{0,20}(包含|含|输出|写|给出)[^。；\n]{0,12}"
     r"(语料外|无证据|无法[^。；\n]{0,6}支持|corpus\s*外|包外)"),
    ("V6_KNOWLEDGE_OVERREACH", r"(模型知识越界|知识越界|越界回答|外部知识越界)"),
]
_NEGATION_GUARD = re.compile(
    r"(不存在|没有发现|未发现|并未发现|未见|不构成|无误|没有出现|未出现|没有|并未|不是)")


def abstention_violation_reports(rows):
    """→ 明确报告了「弃权完整性失败」的条目列表（含否定守卫）。

    语义边界（冻结 G5）：只有 reviewer **断言**弃权完整性被破坏才算 violation；
    肯定式/中性提及（"正确且有信息价值的学术弃权"、"应继续维持为部分弃权"、
    "证据不足因此弃权合理"）一律不计。
    """
    out = []
    for r in rows:
        txt = " ".join([(r.get("reviewer_comment") or {}).get("raw") or "",
                        " ".join(r.get("requested_changes") or [])])
        for pid, pat in ABSTENTION_VIOLATION_PATTERNS:
            for m in re.finditer(pat, txt):
                window = txt[max(0, m.start() - 16):m.start()]
                if _NEGATION_GUARD.search(window):
                    continue           # 否定控制："不存在弃权失败" / "没有发现模型知识越界"
                out.append({"task_id": r["task_id"], "pattern": pid,
                            "matched": m.group(0)[:80],
                            "scholarly_usable": r["scholarly_usable"]})
    return out


def abstention_integrity_machine_violations(g21):
    """G5 机器侧：**只**汇总冻结引擎已有的 Gate 21 字段。"""
    return {c: g21.get(c, 0) for c in G5_MACHINE_FIELDS}


def _g5_supporting_outside_knowledge_evidence():
    """冻结引擎里「外部知识越界」的既有控制是对抗套件的 case（非逐题字段）。

    没有逐题字段就**如实说明**，而不是新造一个阈值。仅作 supporting evidence。
    """
    import glob
    for d in sorted(glob.glob(os.path.join(RUNS, "4c1d_adversarial_*"))):
        rp = os.path.join(d, "results.json")
        if not os.path.isfile(rp):
            continue
        try:
            res = load_json(rp)
        except Exception:  # noqa: BLE001
            continue
        adv = res.get("adversarial") or {}
        for case in (adv.get("cases") or res.get("cases") or []):
            if case.get("kind") == "outside_knowledge_leakage" or \
                    case.get("case_id") == "outside_knowledge_leakage":
                return {"source": os.path.relpath(rp, VAULT),
                        "run_id": res.get("run_id"),
                        "case_id": case.get("case_id"),
                        "kind": case.get("kind"),
                        "detected": case.get("detected"),
                        "detected_by": case.get("detected_by"),
                        "adversarial_claim_in_final": case.get("adversarial_claim_in_final"),
                        "final_answer_state": case.get("final_answer_state"),
                        "note": ("冻结引擎**无逐题** outside_knowledge 字段；"
                                 "外部知识越界的既有控制是这一条**套件级**对抗用例"
                                 "（仅作 supporting evidence，不参与 G5 计数）")}
    return {"source": None, "case": "outside_knowledge_leakage", "detected": None,
            "note": "未找到对抗套件的 outside_knowledge 用例；G5 机器侧仍只用 Gate 21 字段。"}


G5_V1_SNAPSHOT = os.path.join(EVAL, "gate_g5_correction",
                                 "evaluator_v1_result_snapshot.json")


def _gate_evaluation_history(current_verdict):
    """保留历史判定：第一次（v1 evaluator）的 NOT_READY 不得删除。"""
    hist = []
    if os.path.isfile(G5_V1_SNAPSHOT):
        v1 = load_json(G5_V1_SNAPSHOT)
        hist.append({
            "evaluation": "initial",
            "evaluator_version": v1.get("evaluator_version", "gate-evaluator/1"),
            "verdict": v1.get("verdict"),
            "failed_criteria_ids": v1.get("failed_criteria_ids"),
            "g5_observed": v1.get("g5_observed"),
            "reason": "G5 evaluator implementation defect"
                      "（taxonomy mention count 被当作 violation counter）",
            "snapshot": os.path.relpath(G5_V1_SNAPSHOT, VAULT),
            "snapshot_sha256": sha_file(G5_V1_SNAPSHOT),
        })
    hist.append({
        "evaluation": "corrected",
        "evaluator_version": G5_EVALUATOR_VERSION,
        "verdict": current_verdict["verdict"],
        "failed_criteria_ids": [c["id"] for c in current_verdict["criteria"]
                                if not c["ok"]],
        "reason": "G5 machine side 只用冻结引擎已有 Gate 21 字段；human side 只计"
                  "明确违反报告；taxonomy 降为 diagnostic",
        "rule_semantics_unchanged": True,
    })
    return hist


def _not_ready_diagnosis(gate, verdict, reviewed, tax2, g21):
    """NOT_READY 时按 §34 输出：失败判据 / 受影响任务 / 根因假设 / 最小修复提案。

    **只报告事实，不改规则**：frozen gate / taxonomy 的哈希仍写在 inputs 里，
    任何修订都必须由人工确认后另行进行。
    """
    failed = [x for x in verdict["criteria"] if not x["ok"]]
    out = {
        "failed_criteria_ids": [x["id"] for x in failed],
        "failed_criteria_observed": {x["id"]: x["observed"] for x in failed},
        "affected_tasks": [],
        "abstention_mention_evidence": [],
        "human_verdicts_on_abstention_tasks": {},
        "observations": [],
        "root_cause_hypotheses": [],
        "minimum_remediation_proposal": [],
        "discipline_note": ("本诊断只输出事实与提案；评审前冻结的 gate / taxonomy / schema "
                            "哈希未被改动（见 inputs）。任何规则修订都必须由人工确认后另行进行，"
                            "不得在看到分数后即时改 prompt 或删题。"),
    }
    tax = load_json(TAXONOMY_P)
    rule = next((x for x in tax["keyword_rules_ordered"]
                 if x["class"] == "ABSTENTION_FAILURE"), None)
    kw_list = rule["keywords"] if rule else []
    for r in reviewed:
        txt = " ".join([(r.get("reviewer_comment") or {}).get("raw") or "",
                        " ".join(r.get("requested_changes") or [])])
        hits = []
        for kw in kw_list:
            if re.fullmatch(r"[A-Za-z0-9_ ]+", kw):
                if re.search(r"\b%s\b" % re.escape(kw), txt, flags=re.IGNORECASE):
                    hits.append(kw)
            elif kw in txt:
                hits.append(kw)
        if hits:
            out["abstention_mention_evidence"].append({
                "task_id": r["task_id"], "scholarly_usable": r["scholarly_usable"],
                "citation_support": r["citation_support"], "matched_keywords": hits})
    for tid in ("rt-J01", "rt-J02", "rt-J03"):
        rec = next((r for r in reviewed if r["task_id"] == tid), None)
        if rec:
            out["human_verdicts_on_abstention_tasks"][tid] = {
                "scholarly_usable": rec["scholarly_usable"],
                "citation_support": rec["citation_support"]}
    out["affected_tasks"] = sorted({e["task_id"] for e in out["abstention_mention_evidence"]})
    if "G5_abstention_integrity" in out["failed_criteria_ids"]:
        ev = out["abstention_mention_evidence"]
        non_failure = [e for e in ev if e["scholarly_usable"] in ("YES", "WITH_REVISION")]
        out["observations"].append(
            "G5 的 %d 次命中全部来自评论**提到**弃权（含对弃权的肯定与「需要改变」建议）；"
            "三个弃权题的人工判定为 YES / YES / WITH_REVISION，无一是失败判定。"
            % len(ev))
        out["observations"].append(
            "G5 机器侧（Gate 21 弃权违规 = %s）为 0，即无「模型知识越界」的机器证据。"
            % g21.get("D_ABSTENTION_CONTAINS_SUBSTANTIVE_CLAIM", 0))
        if non_failure:
            out["root_cause_hypotheses"].append(
                "G5 的**实现**把「评论中出现弃权相关词」当作「人工判为 ABSTENTION_FAILURE」，"
                "而冻结判据的措辞是后者；taxonomy 冻结语义本就声明按**命中**计频、非互斥、不判成败 —— "
                "实现把「提及」误当「失败」，属于判据实现过宽，而非学术结论冲突。")
        out["minimum_remediation_proposal"] = [
            "方案 A（推荐，需人工确认）：把 G5 的人工侧实现改为「该题 scholarly_usable == NO "
            "且 taxonomy 命中 ABSTENTION_FAILURE」才算失败；机器侧保持 Gate 21 == 0 不变。"
            "按方案 A 复核本题数据：三个弃权题均非 NO → 人工侧不成立 → G5 通过。",
            "方案 B：保留命中式实现，但在 judge 口径上把 taxonomy 的 ABSTENTION_FAILURE "
            "关键词限定为**否定式**表述（如「弃权失败」「不该弃权」），剔除肯定式提及。",
            "方案 C：不动规则，维持 SCHOLARLY_CORE_NOT_READY，把 G5 作为已知口径缺陷记录，"
            "在 4C.1-F 修正后重跑（代价：本轮结论被一条实现缺陷阻断）。",
            "无论选哪个：**不得**改动已冻结的 gate/taxonomy/schema 文件本身而不留痕；"
            "若确认修订，应同时更新 frozen_artifacts 哈希与 E 报告中的冻结记录。",
        ]
    return out


def _evaluate_gate(gate, usable, cit, dims, cmp_dims, g21, tax2, reviewed):
    """按**冻结的** criteria id 逐条判定（实现与 gate 文件由测试绑定）。"""
    res = []
    ids = [c["id"] for c in gate["criteria"]]

    def add(cid, ok, observed, statement, threshold=None):
        res.append({"id": cid, "ok": bool(ok), "observed": observed,
                    "statement": statement, "threshold": threshold})

    no = usable.get("NO", 0)
    add("G1_no_majority_NO", no <= 7, {"scholarly_usable.NO": no, "of": 14},
        "scholarly_usable = NO 不得再占多数（≤ 7 / 14）", "<= 7")
    fail = cit.get("FAIL", 0)
    add("G2_citation_fail_drop", fail <= 4, {"citation_support.FAIL": fail, "of": 14},
        "citation_support = FAIL 显著低于 Round 1（9/14）：≤ 4 / 14", "<= 4")
    sr = g21.get("D_SOURCE_ROLE_VIOLATION_IN_FINAL", 0)
    add("G3_no_source_role_violation", sr == 0,
        {"D_SOURCE_ROLE_VIOLATION_IN_FINAL": sr}, "final answer 无 source-role 违规", "== 0")
    comp = ["D_SUBSTANTIVE_CLAIM_WITHOUT_EVIDENCE", "D_REJECTED_CLAIM_IN_FINAL",
            "D_FINAL_CLAIM_NOT_IN_VALIDATED_SET", "D_INVALID_CITATION_IN_FINAL",
            "D_INVALID_QUOTE_IN_FINAL", "D_ABSENCE_CLAIM_WITHOUT_SCAN_PROVENANCE"]
    uns = sum(g21.get(c, 0) for c in comp)
    add("G4_no_unsupported_claim_in_final", uns == 0,
        {c: g21.get(c, 0) for c in comp}, "final answer 无未受支持的实质 claim", "== 0")
    mach = abstention_integrity_machine_violations(g21)
    human_reports = abstention_violation_reports(reviewed)
    add("G5_abstention_integrity",
        sum(mach.values()) == 0 and not human_reports,
        {"machine": mach,
         "machine_fields_used": list(G5_MACHINE_FIELDS),
         "human_explicit_violation_reports": len(human_reports),
         "human_report_detail": human_reports[:4],
         "diagnostic_taxonomy_ABSTENTION_FAILURE_mentions":
             tax2.get("ABSTENTION_FAILURE", 0),
         "diagnostic_only_note": ("taxonomy 关键词频次仅作 diagnostic reporting，"
                                  "不参与 G5 判定（冻结语义：issue-focus frequency，"
                                  "非互斥、非 pass/fail classifier）")},
        "弃权题不因模型知识越界（机器侧已有 Gate 21 字段 == 0 且 人工无明确违反报告）",
        "machine==0 且 human_reports==0")
    yes = usable.get("YES", 0)
    yr = yes + usable.get("WITH_REVISION", 0)
    add("G6_explicit_human_support", (yes >= 1 and yr >= 9),
        {"YES": yes, "YES+WITH_REVISION": yr, "of": 14},
        "至少 1 题 YES，且 YES + WITH_REVISION ≥ 9 / 14", "YES>=1 且 >=9")
    reg = 0.0
    worst = None
    for d, c in cmp_dims.items():
        if c["round1_mean"] is None or c["round2_mean"] is None:
            continue
        drop = c["round1_mean"] - c["round2_mean"]
        if drop > reg:
            reg, worst = drop, d
    add("G7_no_dimension_regression", reg <= 0.5,
        {"max_drop": round(reg, 4), "dimension": worst},
        "任一维度 Round 2 均值不得比 Round 1 低超过 0.5", "<= 0.5")

    all_ok = all(x["ok"] for x in res)
    return {
        "gate": "Scholarly Readiness Gate v1",
        "gate_sha256": sha_file(GATE_P),
        "frozen_at": gate["frozen_at"],
        "criteria": res,
        "verdict": "SCHOLARLY_CORE_READY" if all_ok else "SCHOLARLY_CORE_NOT_READY",
        "criteria_ids_expected": ids,
        "all_criteria_hold": all_ok,
    }


def render_results_md(out, gate):
    u, c, d = out["by_scholarly_usable"], out["by_citation_support"], out["per_dimension"]
    L = ["# HUMAN_REVIEW_RESULTS_V2 — Phase 4C.1-E Round 2（人工盲评）", "",
         "> 记录来源：`%s`（sha256 `%s`）" % (out["inputs"]["round2_records"],
                                              out["inputs"]["round2_records_sha256"][:16]),
         "> 被评答案来源：D2 封存 run `%s`" % out["inputs"]["source_run_id"],
         "> 评分主体：**人类 reviewer**（1 位；不报告 inter-rater agreement）",
         "> 系统只做格式校验与确定性汇总，**不参与评分**。", "",
         "## 1. 完整性", "",
         "```", "records_total = %d" % out["completeness"]["records_total"],
         "reviewed      = %d" % out["completeness"]["reviewed"],
         "all_reviewed  = %s" % out["completeness"]["all_reviewed"], "```", "",
         "## 2. Scholarly usability", "",
         "| 取值 | n |", "|---|---:|"]
    for k in SCHOLARLY_USABLE:
        L.append("| %s | %d |" % (k, u.get(k, 0)))
    L += ["", "## 3. Citation support", "", "| 取值 | n |", "|---|---:|"]
    for k in CITATION_SUPPORT:
        L.append("| %s | %d |" % (k, c.get(k, 0)))
    L += ["", "## 4. 六维（mean / median，historical_accuracy 排除 N/A）", "",
          "| 维度 | n | n_na | mean | median |", "|---|---:|---:|---:|---:|"]
    for k in DIMENSIONS:
        s = d[k]
        L.append("| %s | %d | %d | %s | %s |" % (k, s["n"], s["n_na"], s["mean"], s["median"]))
    L += ["", "## 5. Round 1 vs Round 2", "",
          "| 指标 | Round 1 | Round 2 | Delta |", "|---|---:|---:|---:|"]
    r1u = out["round1_vs_round2"]["scholarly_usable"]["round1"]
    for k in SCHOLARLY_USABLE:
        L.append("| %s | %d | %d | %+d |" % (k, r1u.get(k, 0), u.get(k, 0),
                                             u.get(k, 0) - r1u.get(k, 0)))
    r1c = out["round1_vs_round2"]["citation_support"]["round1"]
    for k in CITATION_SUPPORT:
        L.append("| Citation %s | %d | %d | %+d |" % (k, r1c.get(k, 0), c.get(k, 0),
                                                      c.get(k, 0) - r1c.get(k, 0)))
    for k in DIMENSIONS:
        cc = out["round1_vs_round2"]["per_dimension"][k]
        L.append("| %s (mean) | %s | %s | %s |" % (k, cc["round1_mean"], cc["round2_mean"],
                                                   cc["delta"]))
    L += ["", "## 6. Error taxonomy delta", "",
          "| 类别 | Round 1 | Round 2 | Delta |", "|---|---:|---:|---:|"]
    for k, v in sorted(out["error_taxonomy_delta"].items(),
                       key=lambda kv: -kv[1]["round2"]):
        L.append("| %s | %d | %d | %+d |" % (k, v["round1"], v["round2"], v["delta"]))
    L += ["", "## 7. 逐题 transition", "",
          "| task | R1 usable | R2 usable | R1 citation | R2 citation |", "|---|---|---|---|---|"]
    for t in out["per_task_transition"]:
        L.append("| %s | %s | %s | %s | %s |" % (
            t["task_id"], t["round1_scholarly_usable"], t["round2_scholarly_usable"],
            t["round1_citation_support"], t["round2_citation_support"]))
    L += ["", "## 8. 机器指标（并列报告，**不作为学术可用性判据**）", "", "```",
          "gate21_violation_total = %s" % out["machine_metrics"]["gate21_violation_total"],
          "claim_validation_rate = %s" % out["machine_metrics"]["claim_validation_rate"],
          "rejected_claim_rate   = %s" % out["machine_metrics"]["rejected_claim_rate"],
          "direct_entailment_rate= %s" % out["machine_metrics"]["direct_entailment_rate"],
          "quote_validation_rate = %s" % out["machine_metrics"]["quote_validation_rate"],
          "```", "", "> %s" % out["machine_metrics"]["disclaimer"], "",
          "## 9. Scholarly Readiness Gate（评审前冻结）", "",
          "gate `%s`（frozen_at `%s`，sha256 `%s`）"
          % (out["readiness_gate"]["gate"], out["readiness_gate"]["frozen_at"],
             out["readiness_gate"]["gate_sha256"][:16]), "",
          "| 判据 | 结论 | 观测 |", "|---|---|---|"]
    for x in out["readiness_gate"]["criteria"]:
        L.append("| %s | %s | %s |" % (x["id"], "PASS" if x["ok"] else "FAIL",
                                       json.dumps(x["observed"], ensure_ascii=False)))
    L += ["", "**verdict = `%s`**" % out["readiness_gate"]["verdict"], ""]
    return "\n".join(L)


def render_final_md(out, gate):
    r = out["readiness_gate"]
    L = ["# Phase 4C.1-E Final Result", "",
         "## 1. Status", "", "```", r["verdict"], "```", "",
         "## 2. Human Review Completion", "",
         "```", "reviewed = %d / 14" % out["completeness"]["reviewed"],
         "missing  = %s" % (out["completeness"]["missing"] or "—"), "```", "",
         "## 3. Round 2 Scholarly Usability", "",
         "```", json.dumps(out["by_scholarly_usable"], ensure_ascii=False), "```", "",
         "## 4. Round 2 Citation Support", "",
         "```", json.dumps(out["by_citation_support"], ensure_ascii=False), "```", "",
         "## 5. Six-dimension Scores", "", "```",
         json.dumps({k: {"mean": v["mean"], "median": v["median"], "n": v["n"],
                         "n_na": v["n_na"]} for k, v in out["per_dimension"].items()},
                    ensure_ascii=False, indent=1), "```", "",
         "## 6. Round 1 vs Round 2", "",
         "见 `HUMAN_REVIEW_RESULTS_V2.md` §5（含六维 mean/median 与 delta）。", "",
         "## 7. Per-task Transition Matrix", "",
         "| task | R1 usable | R2 usable | R1 citation | R2 citation |", "|---|---|---|---|---|"]
    for t in out["per_task_transition"]:
        L.append("| %s | %s | %s | %s | %s |" % (
            t["task_id"], t["round1_scholarly_usable"], t["round2_scholarly_usable"],
            t["round1_citation_support"], t["round2_citation_support"]))
    L += ["", "## 8. Error Taxonomy Delta", "", "```",
          json.dumps(out["error_taxonomy_delta"], ensure_ascii=False, indent=1), "```", "",
          "## 9. Positive Controls", "",
          "见 `HUMAN_REVIEW_RESULTS_V2.md` 逐题 transition（Round 1 的 strong_success / "
          "borderline / insufficient / failure 四桶对照）。", "",
          "## 10. Abstention Controls", "",
          "弃权题（rt-J02 / rt-J03 / rt-J01）在 Round 2 的 scholarly_usable 与 "
          "ABSTENTION_FAILURE 命中见 §3 与 §8。", "",
          "## 11. Remaining Scholarly Weaknesses", "",
          "见 §8 taxonomy delta 中 Round 2 仍 > 0 的类别，以及 `per_task_transition` 中"
          "仍未改善的题。", "",
          "## 12. Machine vs Human Agreement", "", "```",
          json.dumps(out["machine_metrics"], ensure_ascii=False, indent=1), "```", "",
          "## 13. Scholarly Readiness Gate", "", "```",
          json.dumps(r, ensure_ascii=False, indent=1), "```", "",
          "## 14. Final Decision", "", "```", r["verdict"], "```", ""]
    d = out.get("not_ready_diagnosis")
    if d:
        L += ["## 15. NOT_READY 诊断（§34：只报事实，不改规则）", "",
              "**失败判据**：%s" % ", ".join(d["failed_criteria_ids"]), "",
              "**受影响任务**：%s" % (", ".join(d["affected_tasks"]) or "—"), "",
              "**观测**：", ""]
        L += ["* %s" % o for o in d["observations"]]
        L += ["", "**弃权题人工判定**：", "",
              "| task | scholarly_usable | citation_support |", "|---|---|---|"]
        for k, v in d["human_verdicts_on_abstention_tasks"].items():
            L.append("| %s | %s | %s |" % (k, v["scholarly_usable"], v["citation_support"]))
        L += ["", "**命中证据（评论中触发 ABSTENTION_FAILURE 关键词者）**：", "",
              "| task | scholarly_usable | citation | 命中关键词 |", "|---|---|---|---|"]
        for e in d["abstention_mention_evidence"]:
            L.append("| %s | %s | %s | %s |" % (e["task_id"], e["scholarly_usable"],
                                               e["citation_support"],
                                               ", ".join(e["matched_keywords"])))
        L += ["", "**根因假设**：", ""]
        L += ["* %s" % h for h in d["root_cause_hypotheses"]]
        L += ["", "**最小修复提案**（需人工确认后才可执行）：", ""]
        L += ["* %s" % m for m in d["minimum_remediation_proposal"]]
        L += ["", "> %s" % d["discipline_note"], ""]
    L += ["**停止**：不自动进入 Phase 4D。若 NOT_READY，先输出 remaining_failure_taxonomy / "
          "affected_tasks / root_cause_hypotheses / minimum_remediation_proposal，等待确认。", ""]
    return "\n".join(L)


# ────────────────────────────────────────────────────────── main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4C.1-E Round 2 盲评准备/记录/汇总")
    ap.add_argument("--build", action="store_true", help="E1：生成 14 个盲评包 + dataset + manifest")
    ap.add_argument("--check", action="store_true", help="校验（只读；供套件调用）")
    ap.add_argument("--show", default=None, help="打印某一包（给用户评审）")
    ap.add_argument("--record", default=None, help="写入某一题的人工评分（task_id）")
    ap.add_argument("--scores", default=None, help="人工评分 payload（JSON 文件路径）")
    ap.add_argument("--submitted-by", default=None, help="人类提交凭证（原话来源）")
    ap.add_argument("--reason", default=None, help="更正已有记录时的理由（默认拒绝覆盖）")
    ap.add_argument("--aggregate", action="store_true", help="E2：14/14 后汇总")
    ap.add_argument("--verify-run", action="store_true", help="只验证 D2 sealed run")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.verify_run:
        v = verify_sealed_run()
        print(json.dumps({k: v[k] for k in ("ok", "run_id") if k in v},
                         ensure_ascii=False))
        for c in v["checks"]:
            print("  %-34s %s  %s" % (c["check"], "OK " if c["ok"] else "FAIL", c["detail"]))
        return 0 if v["ok"] else 3
    if a.build:
        return build(quiet=a.quiet)
    if a.check:
        return check(quiet=a.quiet)
    if a.show:
        return show(a.show)
    if a.record:
        if not a.scores:
            print("FAIL --record 需要 --scores <payload.json>")
            return 2
        payload = load_json(a.scores)
        return record(a.record, payload, a.submitted_by or "direct human message in session",
                      amend_reason=a.reason, quiet=a.quiet)
    if a.aggregate:
        return aggregate(quiet=a.quiet)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
