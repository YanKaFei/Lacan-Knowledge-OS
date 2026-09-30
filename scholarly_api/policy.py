#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scholarly_api.policy — Phase 4D.0 读写边界（Read / Write Boundary）

四类数据（§6）
──────────────
A. IMMUTABLE_CORE        只读：核心语义代码、冻结 prompt、validator、gate、
                         human review 工件、封存 eval run、Gold 基线、core freeze manifest
B. REBUILDABLE_MACHINE   允许重建：SQLite FTS / 向量索引 / 图缓存 / 检索缓存 / UI 缓存
                         —— 必须能由 Source of Truth（Markdown vault + corpus）重建
C. CANONICAL_KNOWLEDGE   受控写入：ontology、canonical concept mapping、已复核术语映射、
                         source metadata —— 必须走 review workflow（需 review token）
D. USER_WORKSPACE        产品层可自由创建：research notes、saved answers、bookmarks、
                         reading lists、annotations、projects、exports、Obsidian notes
                         —— **不得**反向污染 canonical core

纪律
────
* 产品层写文件必须走 `write_text()` / `write_json()`（本模块），它会按上面的分类拒绝或放行。
* 拒绝时抛 `CoreMutationError`，**不静默**；这正是 §7 boundary tests 断言的行为。
* 本模块不 import 核心语义模块（只依赖路径常量），因此产品层可以安全地只依赖它。
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(HERE)


class CoreMutationError(PermissionError):
    """产品层试图写入不可变 / 受控数据时抛出。"""


# ─────────────────────────────────────────────────────────── 分类规则
IMMUTABLE_CORE = [
    # 核心语义代码
    "_scripts/_tools/research_contract.py", "_scripts/_tools/research_execution.py",
    "_scripts/_tools/research_answer.py",
    "_scripts/_tools/lacan_mcp/evidence_sufficiency_v2.py",
    "_scripts/_tools/lacan_mcp/evidence_sufficiency_v21.py",
    "_scripts/_tools/synthesis_contract.py", "_scripts/_tools/synthesis_claims.py",
    "_scripts/_tools/synthesis_render.py", "_scripts/_tools/synthesis_adapters.py",
    "_scripts/_tools/synthesis_entailment.py", "_scripts/_tools/synthesis_validation.py",
    "_scripts/_tools/synthesis_adversarial.py",
    "_scripts/_tools/run_synthesis_4c1c.py", "_scripts/_tools/run_synthesis_4c1d.py",
    "_scripts/_tools/run_diagnostic_4c1b.py", "_scripts/_tools/run_diagnostic_4c1b2.py",
    "_scripts/_tools/run_diagnostic_4c1b3.py",
    "_scripts/_tools/eval_integrity.py",
    # 冻结件 / 验收工件
    "_data/eval/scholarly_readiness_gate_v1.json",
    "_data/eval/round2_taxonomy_v1.json",
    "_data/eval/round2_review_schema.json",
    "_data/eval/research_human_review.jsonl",
    "_data/eval/research_human_review_round2.jsonl",
    "_data/eval/human_review_results_v1.json",
    "_data/eval/human_review_results_v2.json",
    "_data/eval/human_adjudication_queue.jsonl",
    "_data/eval/human_review_set_v1.json",
    "_data/eval/phase4c1d2_frozen_identity.json",
    "_data/eval/research_tasks_v1.jsonl", "_data/eval/research_tasks_v1.gold_derivation.json",
    "_data/eval/gold_v2/*", "_data/eval/gold_lane_audit_v1.jsonl",
    "_data/eval/claim_entailment_calibration_v1.jsonl",
    "_data/eval/manifests/*",
    "_data/eval/evaluation_integrity_audit.json",
    "_data/eval/runs/*",                     # 封存 run：整目录只读
    "_data/core_freeze/*",                   # 冻结清单本身
    "_data/ontology/v4a1/*",                 # canonical ontology：只读（改动须走 review）
    "_data/relations/*",
    "_data/passage_store/*.jsonl",           # canonical passage store
    "_data/index/INDEX_MANIFEST.json", "_data/index/VECTOR_INDEX_MANIFEST.json",
    # Gold / 评测入口
    "_data/eval/research_eval_results*.json",
    "_data/eval/research_synthesis_results*.json",
]

REBUILDABLE_MACHINE = [
    "_index/passage_store.sqlite*",
    "_index/fts.sqlite*",
    "_index/vectors/*", "_index/*.lance/*",
    "_data/index/lexical.sqlite*", "_data/index/vector/*.npy",
    "_data/index/vector/*.faiss", "_data/index/vector/*.hnsw",
    "_data/index/*.sqlite*", "_data/index/embedding_cache*",
    "_data/index/rerank_cache*", "_data/index/zh_fts*",
    "_data/raw_text/*", "_data/processed/*", "_data/ocr/*",
    ".cache/*", "_cache/*", "ui_cache/*",
    "_index/Reports/*", "_index/Views/*",   # 派生视图：可重建（但由 build 写）
]

CANONICAL_KNOWLEDGE = [
    "_data/ontology/**",                     # 除 v4a1 已冻结部分外的本体演进
    "_data/terminology_bridge.jsonl",
    "_data/eval/gold_v2/*",                  # gold 变更须走 scholarly remediation
    "00_System/Schemas/*", "00_System/Validation/*",
]

USER_WORKSPACE = [
    # 核心变更请求：产品层**必须**能创建（这是「不许直接改核心」的出口）
    "_core_change_requests/requests/*",
    # 产品自产数据（MCP 审计日志、Workspace 历史等）：产品层可写，
    # 但**绝不回声污染核心**（§6 四类中归 D）
    "_data/product_audit/**",
    "_workspace/**",
    "Research/*", "Projects/*", "Notes/*", "Saved/*", "Annotations/*",
    "Concepts/*", "Seminars/*", "Passages/*", "Exports/*",
    "20-my-prompts/*", "user/*",
    "_user/*", "workspace/*",
]

CLASSES = ("IMMUTABLE_CORE", "REBUILDABLE_MACHINE", "CANONICAL_KNOWLEDGE",
           "USER_WORKSPACE")

_RULES = (
    ("IMMUTABLE_CORE", IMMUTABLE_CORE),
    ("REBUILDABLE_MACHINE", REBUILDABLE_MACHINE),
    ("CANONICAL_KNOWLEDGE", CANONICAL_KNOWLEDGE),
    ("USER_WORKSPACE", USER_WORKSPACE),
)


def _abs(path):
    """相对路径**一律按 VAULT 解析**（产品层可能在任意 cwd 下调用）。"""
    p = str(path)
    if not os.path.isabs(p):
        p = os.path.join(VAULT, p)
    return os.path.abspath(p)


def _rel(path):
    p = _abs(path)
    try:
        return os.path.relpath(p, VAULT).replace(os.sep, "/")
    except ValueError:          # 不同盘符（不该出现，保守处理）
        return p.replace(os.sep, "/")


def _match(rel, patterns):
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat):
            return True
        if pat.endswith("/**") and rel.startswith(pat[:-2]):
            return True
    return False


def classify(path):
    """→ 四类之一，或 "UNKNOWN"（未知路径默认**不可写**，由调用方显式确认）。"""
    rel = _rel(path)
    for name, patterns in _RULES:
        if _match(rel, patterns):
            return name
    return "UNKNOWN"


# ─────────────────────────────────────────────────────────── 写入闸门
def assert_writable(path, review_token=None):
    """分类闸门：不可变 → 抛错；受控 → 需 review_token；未知 → 抛错（保守）。"""
    rel = _rel(path)
    cls = classify(path)
    if cls == "IMMUTABLE_CORE":
        raise CoreMutationError(
            "拒绝写入不可变 Scholarly Core：%s（§6A）。"
            "若确需改动，请走 CORE_CHANGE_REQUEST → scholarly remediation phase。" % rel)
    if cls == "CANONICAL_KNOWLEDGE" and not review_token:
        raise CoreMutationError(
            "拒绝写入受控 canonical 数据：%s（§6C）。需 review workflow 签发的 "
            "review_token。" % rel)
    if cls == "UNKNOWN":
        raise CoreMutationError(
            "拒绝写入未分类路径：%s（§6 保守原则）。若确需写入，先在 "
            "scholarly_api/policy.py 中登记其数据分类。" % rel)
    return cls


def write_text(path, text, review_token=None, encoding="utf-8"):
    """产品层唯一被许可的写文本入口（路径按 VAULT 解析，不依赖 cwd）。"""
    cls = assert_writable(path, review_token=review_token)
    target = _abs(path)                       # 与 classify 使用同一套解析
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding=encoding) as f:
        f.write(text)
    return {"path": _rel(path), "class": cls, "bytes": len(text.encode(encoding))}


def write_json(path, obj, review_token=None):
    return write_text(path, json.dumps(obj, ensure_ascii=False, indent=2),
                      review_token=review_token)


# ─────────────────────────────────────────────────────────── 快照（供测试/审计）
IMMUTABLE_SNAPSHOT_PATHS = [
    "_data/core_freeze/scholarly_core_freeze_v1.json",
    "_data/eval/scholarly_readiness_gate_v1.json",
    "_data/eval/round2_taxonomy_v1.json",
    "_data/eval/research_human_review.jsonl",
    "_data/eval/research_human_review_round2.jsonl",
    "_data/eval/human_review_results_v2.json",
    "_data/eval/human_adjudication_queue.jsonl",
    "_data/eval/research_tasks_v1.jsonl",
    "_data/eval/gold_v2/lane_overrides_v1.json",
    "_data/ontology/v4a1/entities.jsonl",
    "_data/ontology/v4a1/relations.jsonl",
    "_data/ontology/v4a1/term_mappings.jsonl",
    "_scripts/_tools/synthesis_entailment.py",
    "_scripts/_tools/synthesis_adapters.py",
    "_scripts/_tools/research_contract.py",
]


def snapshot_immutable(paths=None):
    """→ {rel: sha256}，用于证明「产品操作没有改动核心」。"""
    out = {}
    for rel in (paths or IMMUTABLE_SNAPSHOT_PATHS):
        p = os.path.join(VAULT, rel)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out[rel] = hashlib.sha256(f.read()).hexdigest()
    return out


def diff_snapshot(before, after):
    """→ 变更清单 [{'path','action','before','after'}]（空 = 无核心改动）。"""
    changes = []
    for rel in sorted(set(before) | set(after)):
        b, a = before.get(rel), after.get(rel)
        if b != a:
            changes.append({"path": rel, "before": (b or "")[:16],
                            "after": (a or "")[:16],
                            "action": "created" if b is None else
                                      ("deleted" if a is None else "modified")})
    return changes
