#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core_freeze.py — Phase 4D.0：Scholarly Core Freeze Manifest 的构建与校验

产物
────
    _data/core_freeze/scholarly_core_freeze_v1.json

纪律
────
* 本工具**只读**核心产物，只写 `_data/core_freeze/`（冻结清单本身）。
* 哈希分三类，可复算：
    - `file`    ：整文件 sha256
    - `symbol`  ：Python 模块内某个函数/常量的源码 sha256（`inspect.getsource`）
                  —— 用于把「语义单元」而不是整文件钉住
    - `json`    ：JSON 文件里的某个字段值
* `--verify` 逐项复算并与清单比对；任何漂移都是 FAIL（非零退出）。
  这是 4D.0 的核心门禁：产品层不得让核心悄悄变化。

用法
────
    python3 _scripts/_tools/core_freeze.py --build     # 生成/更新清单
    python3 _scripts/_tools/core_freeze.py --verify     # 复算校验（供套件调用）
    python3 _scripts/_tools/core_freeze.py --show       # 打印清单
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
LACAN = os.path.join(TOOLS, "lacan_mcp")
OUT_DIR = os.path.join(VAULT, "_data", "core_freeze")
OUT = os.path.join(OUT_DIR, "scholarly_core_freeze_v1.json")

for p in (TOOLS, LACAN):
    if p not in sys.path:
        sys.path.insert(0, p)

FREEZE_VERSION = "scholarly_core_freeze_v1"
SCHOLARLY_STATUS = "SCHOLARLY_CORE_READY"

# ── 语料档案（corpus profile）—— P5D-006 / demo corpus 阶段 2
#
# 问题（实测）：`_data/eval/` 里那 9 个**人工验收工件**（人工评审记录、裁定队列、
# 就绪门、错误分类法、评审 schema、gold_v2、冻结身份）是**参考语料自己的学科成果**。
# 换一份语料（demo / 自建）时它们必然缺席 → 旧实现的 `--verify` 报「未解析组件」→
# `mcp_server.guard` fail closed → 研究**完全跑不起来**。也就是说
# 「自带语料」这条被文档承诺的路，此前并未实现。
#
# 处理方式：把「这份语料有没有人工验收证据」变成 manifest 里**显式声明**的档案字段。
#   reference         ：参考语料。组件必须全部在场且哈希一致 → SCHOLARLY_CORE_READY（行为与本字段引入前**逐字节一致**）
#   unreviewed-corpus ：无人工验收证据的语料。缺席的人工验收组件写进 absent_components，
#                       其余组件（含全部 semantic 代码单元与 data_version）仍必须一致 →
#                       CORPUS_HUMAN_REVIEW_NOT_AVAILABLE（研究可运行，但**不带人工验收背书**）
#
# 纪律：缺席只能是**声明过的**、且只允许人工验收类组件；任何非声明缺席、任何「声明缺席但文件又在场」
#       （偷偷换上别的验收证据）都会被 `--verify` 判 FAIL。
PROFILE_REFERENCE = "reference"
PROFILE_UNREVIEWED = "unreviewed-corpus"
PROFILES = (PROFILE_REFERENCE, PROFILE_UNREVIEWED)
STATUS_UNREVIEWED = "CORPUS_HUMAN_REVIEW_NOT_AVAILABLE"

# 人工验收类组件（只有这一类允许在 unreviewed 档案下声明缺席）
HUMAN_ACCEPTANCE_KEYS = (
    "human_review_round1_hash",
    "human_review_round2_hash",
    "human_adjudication_hash",
    "scholarly_readiness_gate_hash",
    "round2_taxonomy_hash",
    "round2_review_schema_hash",
    "gold_v2_tasks_hash",
    "gold_v2_lane_overrides_hash",
    "frozen_identity_hash",
)

PROFILE_NOTES = {
    PROFILE_REFERENCE: (
        "参考语料：39 个组件（含 9 个人工验收工件）全部在场且哈希一致。"
    ),
    PROFILE_UNREVIEWED: (
        "本语料**没有人工验收证据**（_data/eval/ 的人工评审 / 金标 / 就绪门文件缺席，"
        "已在 absent_components 里逐一声明）。因此状态不是 SCHOLARLY_CORE_READY："
        "研究可以运行，但答案不携带任何人工验收背书，也不得被当作已验收的学科结论。"
        "另注：冻结内核的来源归属措辞（claim 文字里的说话人）是为参考语料写的，"
        "对**非参考语料不适用** —— demo 语料的答案只承诺检索 / 证据 / 引文 / 检查器 / 本体解析这条链。"
    ),
}

# ── 组件类（**机器可读**，写进 manifest.component_classes）
#
# Phase 5A / P5A-006 根因：本文件的 SPEC 早就把下面 6 个组件放在「# ── 数据版本」
# 注释块里，但**那只是注释** —— `freeze_lineage.py` 看不见这个分类，于是
# 「语料清单长大了一个文件」被误判成「学术语义发生变化」，lineage 必然 FAIL，
# 而如实重建基线又会让 FAIL 发生。两个方向都被堵死。
#
# 这里把注释提升为分类，使 lineage 能按类判定：
#   scholarly_semantic : 冻结的学术语义单元 —— 变化 = SEMANTIC_DRIFT，**硬失败**
#   product_boundary   : 产品边界（API/schema/runtime wiring）—— 变化 = 运行态变化
#   data_version       : 数据版本（语料/段落库/索引/本体）—— 变化必须**被声明且一致**
DATA_VERSION_KEYS = (
    "passage_store_version",
    "passage_store_passages_sha256",
    "retrieval_index_lexical",
    "retrieval_index_vector",
    "ontology_version",
    "corpus_inventory_hash",
)
PRODUCT_BOUNDARY_KEYS = (
    "scholarly_api_core_hash",
    "scholarly_api_objects_hash",
    "scholarly_api_policy_hash",
)
CLASS_SCHOLARLY = "scholarly_semantic"
CLASS_PRODUCT = "product_boundary"
CLASS_DATA = "data_version"

# 依赖构件状态枚举（§10：不允许「inventory=新 / index=旧」却宣称一致）
DATA_VERSION_STATES = ("CHANGED", "REBUILT", "UNCHANGED_BY_DESIGN", "UNAVAILABLE")

# 数据版本变化声明（§4/§12）。由 `phase5a_declare_data_version.py` 依据真实差异审计生成。
DECLARATIONS = os.path.join(OUT_DIR, "data_version_declarations.json")

# ── 冻结规格：component -> 取哈希的方式
#    每个条目都是 (kind, target)：
#      ("file",   "<repo-relative path>")
#      ("symbol", "<module>", "<symbol>")
#      ("json",   "<repo-relative path>", "<json pointer field>")
SPEC = {
    # ── 研究契约 / 执行 / 证据充分性
    "research_contract_hash": ("file", "_scripts/_tools/research_contract.py"),
    "execution_engine_hash": ("file", "_scripts/_tools/research_execution.py"),
    "evidence_sufficiency_hash": ("multi_file", [
        "_scripts/_tools/lacan_mcp/evidence_sufficiency_v2.py",
        "_scripts/_tools/lacan_mcp/evidence_sufficiency_v21.py"]),
    "research_answer_hash": ("file", "_scripts/_tools/research_answer.py"),

    # ── synthesis 边界与 prompt
    "synthesis_boundary_hash": ("file", "_scripts/_tools/synthesis_contract.py"),
    "synthesis_prompt_hash": ("symbol", "synthesis_adapters", "SYSTEM_CONTRACT"),
    "judge_prompt_hash": ("symbol", "synthesis_entailment", "JUDGE_SYSTEM"),

    # ── claim / entailment / repair
    "claim_atom_hash": ("symbol", "synthesis_entailment", "atomize_claim"),
    "claim_sanitize_hash": ("symbol", "synthesis_entailment", "sanitize_claims"),
    "entailment_validator_hash": ("symbol", "synthesis_entailment", "validate_atom"),
    "entailment_claim_hash": ("symbol", "synthesis_entailment", "validate_claim"),
    "repair_rules_hash": ("symbol", "synthesis_validation", "narrow_claim"),

    # ── 政策层
    "citation_policy_hash": ("symbol", "synthesis_contract", "citation_eligibility"),
    "source_role_policy_hash": ("symbol", "synthesis_entailment", "validate_claim"),
    "abstention_policy_hash": ("symbol", "synthesis_contract", "answer_permission"),

    # ── Gates（实现单元）
    "gate13_hash": ("symbol", "eval_integrity", "validate_human_review_record"),
    "gate13_baseline_hash": ("symbol", "eval_integrity", "baseline_immutability_findings"),
    "gate14_adjudication_hash": ("symbol", "eval_integrity", "adjudication_immutability_findings"),
    "gate19_hash": ("symbol", "eval_integrity", "trace_integrity_findings"),
    "gate20_hash": ("symbol", "eval_integrity", "synthesis_result_findings"),
    "gate21_hash": ("symbol", "eval_integrity", "synthesis_entailment_findings"),

    # ── 数据版本
    "passage_store_version": ("json", "_data/passage_store/_build_meta.json",
                              "content_hash"),
    "passage_store_passages_sha256": ("file", "_data/passage_store/passages.jsonl"),
    "retrieval_index_lexical": ("json", "_data/index/INDEX_MANIFEST.json",
                                "content_hash"),
    "retrieval_index_vector": ("file", "_data/index/vector/VECTOR_INDEX_MANIFEST.json"),
    "ontology_version": ("file", "_data/ontology/v4a1/MANIFEST.json"),
    "corpus_inventory_hash": ("file", "_data/corpus_inventory.json"),

    # ── 人工验收工件
    "human_review_round1_hash": ("file", "_data/eval/research_human_review.jsonl"),
    "human_review_round2_hash": ("file", "_data/eval/research_human_review_round2.jsonl"),
    "human_adjudication_hash": ("file", "_data/eval/human_adjudication_queue.jsonl"),
    "scholarly_readiness_gate_hash": ("file",
        "_data/eval/scholarly_readiness_gate_v1.json"),
    "round2_taxonomy_hash": ("file", "_data/eval/round2_taxonomy_v1.json"),
    "round2_review_schema_hash": ("file", "_data/eval/round2_review_schema.json"),
    "gold_v2_tasks_hash": ("file", "_data/eval/gold_v2/research_tasks_v2.jsonl"),
    "gold_v2_lane_overrides_hash": ("file",
        "_data/eval/gold_v2/lane_overrides_v1.json"),
    "frozen_identity_hash": ("file", "_data/eval/phase4c1d2_frozen_identity.json"),

    # ── 产品边界自身（API 与策略也必须被钉住）
    "scholarly_api_core_hash": ("file", "scholarly_api/core.py"),
    "scholarly_api_objects_hash": ("file", "scholarly_api/objects.py"),
    "scholarly_api_policy_hash": ("file", "scholarly_api/policy.py"),
}

# 派生视图（derived views）：内容含 generated_at（每次重算都会变），
# 因此**只记录、不参与 --verify 的漂移判定** —— 与 eval_integrity.DERIVED_FILES 同一原则。
# 真正需要钉住的是人工产出的验收记录（human_review_round1/2_hash），它们在上面 SPEC 里。
DERIVED_VIEWS = {
    "human_review_results_v1_hash": "_data/eval/human_review_results_v1.json",
    "human_review_results_v2_hash": "_data/eval/human_review_results_v2.json",
    "evaluation_integrity_audit_hash": "_data/eval/evaluation_integrity_audit.json",
    "eval_manifest_latest_hash": "_data/eval/manifests/latest.json",
    "validation_report_hash": "_index/Reports/validation-report.json",
    "test_run_record_hash": "_data/index/TEST_RUN.json",
}


D2_POINTER = "_data/eval/research_synthesis_results.4c1d.json"


def component_class(name):
    """→ 组件类（唯一分类入口；lineage 与 verify 都从这里取）。"""
    if name in PRODUCT_BOUNDARY_KEYS:
        return CLASS_PRODUCT
    if name in DATA_VERSION_KEYS:
        return CLASS_DATA
    return CLASS_SCHOLARLY


def component_classes():
    return {name: component_class(name) for name in SPEC}


def load_declarations():
    """→ 数据版本变化声明列表（缺文件 = 空列表，不猜）。"""
    if not os.path.isfile(DECLARATIONS):
        return []
    with open(DECLARATIONS, encoding="utf-8") as f:
        doc = json.load(f)
    if isinstance(doc, dict):
        return list(doc.get("declarations") or [])
    return list(doc or [])


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(rel: str):
    p = os.path.join(VAULT, rel)
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        return sha_bytes(f.read())


def _import(mod):
    return __import__(mod)


def compute(kind, *args):
    if kind == "file":
        return sha_file(args[0])
    if kind == "multi_file":
        parts = ["%s:%s" % (rel, sha_file(rel)) for rel in args[0]]
        return sha_bytes("\n".join(parts).encode("utf-8"))
    if kind == "symbol":
        mod, sym = args
        obj = getattr(_import(mod), sym, None)
        if obj is None:
            return None
        if isinstance(obj, str):
            return sha_bytes(obj.encode("utf-8"))
        try:
            return sha_bytes(inspect.getsource(obj).encode("utf-8"))
        except (OSError, TypeError):
            return None
    if kind == "json":
        rel, field = args
        p = os.path.join(VAULT, rel)
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        return doc.get(field)
    raise ValueError("未知 kind: %s" % kind)


def _git_head():
    import subprocess
    try:
        return subprocess.run(["git", "-C", VAULT, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _d2_run():
    p = os.path.join(VAULT, D2_POINTER)
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        ptr = json.load(f)
    run_dir = os.path.join(VAULT, ptr.get("run_dir") or "")
    seal = os.path.join(run_dir, "seal.json")
    man = os.path.join(run_dir, "run_manifest.json")
    return {
        "d2_sealed_run_id": ptr.get("run_id"),
        "d2_marker": ptr.get("marker"),
        "d2_seal_hash": sha_file(os.path.relpath(seal, VAULT)) if os.path.isfile(seal)
                        else None,
        "d2_run_manifest_hash": sha_file(os.path.relpath(man, VAULT))
                                if os.path.isfile(man) else None,
    }


def build_manifest(profile=PROFILE_REFERENCE):
    if profile not in PROFILES:
        raise ValueError("unknown corpus profile: %r（可选：%s）" % (profile, ", ".join(PROFILES)))
    comp = {}
    unresolved = []
    absent = []
    for name, spec in SPEC.items():
        try:
            comp[name] = compute(*spec)
        except Exception as exc:  # noqa: BLE001
            comp[name] = None
            unresolved.append("%s: %s" % (name, exc))
        if comp[name] is None:
            # 只有「无人工验收证据的语料」档案、且属于人工验收类，才允许**声明缺席**
            if profile == PROFILE_UNREVIEWED and name in HUMAN_ACCEPTANCE_KEYS:
                absent.append(name)
            else:
                unresolved.append(name)
    doc = {
        "schema_version": "scholarly-core-freeze/v1",
        "freeze_version": FREEZE_VERSION,
        "scholarly_status": (SCHOLARLY_STATUS if profile == PROFILE_REFERENCE
                             else STATUS_UNREVIEWED),
        "corpus_profile": profile,
        "absent_components": sorted(set(absent)),
        "profile_note": PROFILE_NOTES[profile],
        "git_commit": _git_head(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "components": comp,
        # ★ P5A-006：把 SPEC 的分类写成机器可读字段（谱系层据此判定）
        "component_classes": component_classes(),
        "data_version_states_enum": list(DATA_VERSION_STATES),
        # ★ P5A-006 §12：数据版本变化声明（组件 / before / after / reason /
        #   source_diff / ingestion_status / dependent_artifacts / verified_at）
        "data_version_declarations": load_declarations(),
        "unresolved_components": sorted(set(unresolved)),
        "notes": [
            "哈希三类：file = 整文件 sha256；symbol = 该 Python 符号的源码 sha256；"
            "json = JSON 文件的字段值（版本凭证）。",
            "`--verify` 逐项复算；任何漂移 = FAIL。产品层不得让核心悄悄变化。",
            "组件分三类（component_classes）：scholarly_semantic（语义，变化必硬失败）/"
            "product_boundary（产品边界与 runtime wiring）/ data_version（数据版本，"
            "变化必须由 data_version_declarations 声明且依赖构件状态一致）。",
            "`corpus_profile`：reference = 参考语料（全部组件在场，SCHOLARLY_CORE_READY）；"
            "unreviewed-corpus = 无人工验收证据的语料（缺席的人工验收组件在 absent_components "
            "里显式声明，状态 CORPUS_HUMAN_REVIEW_NOT_AVAILABLE，研究可运行但无人工背书）。",
            "本清单自身也被 scholarly_api.policy 归为 IMMUTABLE_CORE。",
        ],
    }
    doc.update(_d2_run())
    doc["derived_views"] = {k: sha_file(v) for k, v in DERIVED_VIEWS.items()}
    doc["derived_views_note"] = ("派生视图只记录、不参与漂移判定：它们含 generated_at，"
                                 "重算即变。冻结的是人工验收记录与语义单元哈希。")
    return doc


def build(profile=PROFILE_REFERENCE):
    os.makedirs(OUT_DIR, exist_ok=True)
    doc = build_manifest(profile)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
    print("freeze manifest -> %s（%d 个组件；未解析 %d；档案 %s）"
          % (os.path.relpath(OUT, VAULT), len(doc["components"]),
             len(doc["unresolved_components"]), doc["corpus_profile"]))
    if doc["absent_components"]:
        print("  声明缺席（人工验收类）：%s" % ", ".join(doc["absent_components"]))
    if doc["unresolved_components"]:
        print("  未解析：%s" % ", ".join(doc["unresolved_components"]))
    if profile != PROFILE_REFERENCE:
        print("  状态：%s —— %s" % (doc["scholarly_status"], doc["profile_note"]))
    return 0


def verify(quiet=False):
    if not os.path.isfile(OUT):
        print("FAIL 缺 core freeze manifest：%s（先 --build）" % os.path.relpath(OUT, VAULT))
        return 1
    with open(OUT, encoding="utf-8") as f:
        doc = json.load(f)
    # 缺 corpus_profile 的历史 manifest = reference（本字段引入前的行为**原样保留**）
    profile = doc.get("corpus_profile") or PROFILE_REFERENCE
    absent = set(doc.get("absent_components") or [])
    drift, missing = [], []
    classes = doc.get("component_classes") or component_classes()
    for name, spec in SPEC.items():
        want = (doc.get("components") or {}).get(name)
        if want is None:
            if name in absent:                       # 声明缺席：不计入 missing（下方单独核验）
                continue
            missing.append(name)
            continue
        got = compute(*spec)
        if got != want:
            drift.append((name, classes.get(name) or component_class(name)))
    semantic_drift = [n for n, c in drift if c == CLASS_SCHOLARLY]
    data_drift = [n for n, c in drift if c == CLASS_DATA]
    product_drift = [n for n, c in drift if c == CLASS_PRODUCT]
    problems = []
    if profile not in PROFILES:
        problems.append("未知 corpus_profile=%s（可选：%s）" % (profile, ", ".join(PROFILES)))
    if profile == PROFILE_UNREVIEWED:
        # ① 缺席只能落在人工验收类，且必须**真的仍然缺席**（防止悄悄换上别的验收证据）
        outside = sorted(k for k in absent if k not in HUMAN_ACCEPTANCE_KEYS)
        if outside:
            problems.append("声明缺席的组件不属于人工验收类：%s" % outside)
        present = sorted(k for k in absent
                         if (doc.get("components") or {}).get(k) is not None)
        if present:
            problems.append("声明缺席但清单里仍有哈希（不得偷偷替换验收证据）：%s" % present)
        if doc.get("scholarly_status") != STATUS_UNREVIEWED:
            problems.append("unreviewed 档案的 scholarly_status 必须是 %s（实际 %s）"
                            % (STATUS_UNREVIEWED, doc.get("scholarly_status")))
    if drift:
        problems.append("哈希漂移：%s" % "; ".join(
            "%s[%s]" % (n, c) for n, c in drift[:6]))
    if missing:
        problems.append("清单缺组件：%s" % ", ".join(missing[:6]))
    if doc.get("freeze_version") != FREEZE_VERSION:
        problems.append("freeze_version=%s" % doc.get("freeze_version"))
    if profile == PROFILE_REFERENCE and doc.get("scholarly_status") != SCHOLARLY_STATUS:
        problems.append("scholarly_status=%s" % doc.get("scholarly_status"))
    if doc.get("unresolved_components"):
        problems.append("存在未解析组件：%s" % doc["unresolved_components"][:6])
    if problems:
        print("FAIL Scholarly Core Freeze 校验未通过：")
        for p in problems:
            print("  - %s" % p)
        # ★ 漂移分类（机器可读；guard / 报告据此区分「核心被改」与「数据版本变了」）
        codes = []
        if semantic_drift:
            codes.append("SEMANTIC_DRIFT")
        if data_drift:
            codes.append("DATA_VERSION_DRIFT")
        if product_drift:
            codes.append("PRODUCT_BOUNDARY_DRIFT")
        if missing:
            codes.append("MISSING_COMPONENT")
        if doc.get("unresolved_components"):
            codes.append("UNRESOLVED_COMPONENT")
        if doc.get("corpus_profile") not in PROFILES:
            codes.append("UNKNOWN_CORPUS_PROFILE")
        print("DRIFT_CLASSES: %s" % (",".join(codes) or "NONE"))
        if semantic_drift:
            print("  semantic_drift_components: %s" % ", ".join(semantic_drift[:8]))
        if data_drift:
            print("  data_version_drift_components: %s" % ", ".join(data_drift[:8]))
        return 1
    if not quiet:
        print("Scholarly Core Freeze 校验通过：%d 个组件哈希一致；status=%s；"
              "freeze=%s（classes: semantic=%d / product=%d / data_version=%d）"
              % (len(doc["components"]), doc["scholarly_status"],
                 doc["freeze_version"],
                 sum(1 for c in classes.values() if c == CLASS_SCHOLARLY),
                 sum(1 for c in classes.values() if c == CLASS_PRODUCT),
                 sum(1 for c in classes.values() if c == CLASS_DATA)))
        if profile == PROFILE_UNREVIEWED:
            print("corpus_profile=%s（声明缺席 %d 个人工验收组件）"
                  % (profile, len(absent)))
            print("注意：%s" % doc.get("profile_note", PROFILE_NOTES[PROFILE_UNREVIEWED]))
    return 0


def show():
    with open(OUT, encoding="utf-8") as f:
        doc = json.load(f)
    print(json.dumps(doc, ensure_ascii=False, indent=2)[:4000])
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 4D.0 Scholarly Core Freeze")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--profile", default=PROFILE_REFERENCE,
                    choices=list(PROFILES),
                    help="语料档案：reference（缺省，参考语料）/ unreviewed-corpus"
                         "（无人工验收证据的语料；缺席的人工验收组件按声明处理）")
    a = ap.parse_args(argv)
    if a.build:
        return build(profile=a.profile)
    if a.profile != PROFILE_REFERENCE and not a.verify:
        ap.error("--profile 只与 --build 一起用（--verify 从 manifest 读档案）")
    if a.show:
        return show()
    return verify(quiet=a.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
