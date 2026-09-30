#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
synthesis_adversarial.py — Phase 4C.1-D §33/§34/§35/§42：对抗测试

「Validator 如果永远 PASS，没有价值。」（§42）所以这里**刻意构造必须被抓住的失败**：

    outside_knowledge_leakage  模型用包外常识补答案（§33）
    source_layer_leakage       只有 L2 却写「拉康法文原文」（§34）
    citation_laundering        正确的拉康事实 + 一个真实但不支持它的 passage（§35）
    relation_overreach         两段各自出现 → 断言两者有理论关系（§14/§15）
    terminology_overclaim      零见证却写「常用译法」（§17）
    diachronic_overreach       只有一侧证据却断言「完全转向」（§16）
    media_as_theory            媒体嵌入承担理论 claim
    editorial_as_lacan         编者说明冒充拉康论述

全部用 **scripted provider**（确定性、离线），因此 CI 里可跑；真实 LLM 的同类
prompt 也由同一个流水线处理（`--mode llm`）。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_answer as ans               # noqa: E402
import synthesis_contract as sc             # noqa: E402
import synthesis_claims as scl              # noqa: E402
import synthesis_adapters as sad            # noqa: E402
import synthesis_entailment as se           # noqa: E402
import synthesis_validation as sv           # noqa: E402


class ScriptedProvider(sad.SynthesisProvider):
    """按脚本返回 claims 的 provider（用于构造对抗输入）。"""
    name = "scripted_adversarial"
    deterministic = True

    def __init__(self, claims, sections=None, abstention=None):
        self._claims = claims
        self._sections = sections or {}
        self._abstention = abstention
        self.output_hash = None

    @property
    def available(self):
        return True

    def complete(self, system, user, schema):
        out = {"claims": self._claims, "sections": self._sections,
               "abstention": self._abstention}
        self.output_hash = __import__("hashlib").sha256(
            __import__("json").dumps(out, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()
        return out


class ScriptedJudgeProvider(sad.SynthesisProvider):
    """按脚本返回 judge 结论（测试聚合与 disagreement 路径）。"""
    name = "scripted_judge"
    deterministic = True

    def __init__(self, verdicts):
        self.verdicts = verdicts

    @property
    def available(self):
        return True

    def complete(self, system, user, schema):
        return {"judgments": [dict(atom_id=k, **v)
                              for k, v in self.verdicts.items()]}


def _task(tid):
    for l in open(os.path.join(EVAL, "research_tasks_v1.jsonl"), encoding="utf-8"):
        if not l.strip():
            continue
        d = __import__("json").loads(l)
        if d["task_id"] == tid:
            return d
    raise KeyError(tid)


def _contract(tid):
    t = _task(tid)
    run = ans.run_task({k: t[k] for k in ("task_id", "question", "language",
                                          "task_type", "required_capabilities",
                                          "split")}, record_gaps=False)
    return sc.build_synthesis_input_contract(run), run


def _ev(contract, pred, n=1):
    return [e["passage_id"] for e in (contract.get("usable_evidence") or [])
            if pred(e)][:n]


# 对抗用例定义（claims 会被送进完整 D 流水线）
def _cases():
    c, _ = _contract("rt-D01")
    d01_ev = _ev(c, lambda e: e["citation_eligibility"] == "ELIGIBLE", 1)
    d01_any = _ev(c, lambda e: True, 1)
    l2 = _ev(c, lambda e: e["source_layer"].startswith("L2"), 1)
    i03, _ = _contract("rt-I03")
    j02, _ = _contract("rt-J02")
    c03, _ = _contract("rt-C03")
    # INELIGIBLE 证据**不会**进 usable_evidence（这是上游防线）——
    # 对抗测试要显式构造「模型仍然引用了它」的情形，因此从 excluded_evidence 里取真实条目
    def _ineligible(contract, cls):
        for e in (contract.get("excluded_evidence") or []):
            if e.get("usability_class") == cls:
                return [e]
        return []
    def _mk_ineligible(base_ev, cls):
        """构造一条 INELIGIBLE 证据（真实 passage + 真实文本，仅把 usability/资格标为违规）。"""
        if not base_ev:
            return None
        e = dict(base_ev)
        e["usability_class"] = cls
        e["citation_eligibility"] = "INELIGIBLE"
        e["claim_permissions"] = ["limitation"]
        return e
    _base_ev = next((e for e in (c.get("usable_evidence") or [])), None)
    _media_item = _mk_ineligible(_base_ev, "MEDIA_ONLY")
    _edit_item = _mk_ineligible(_base_ev, "EDITORIAL_METADATA")
    media = [_media_item["passage_id"]] if _media_item else []
    edit = [_edit_item["passage_id"]] if _edit_item else []
    def _with_ineligible(contract, items):
        """把 INELIGIBLE 条目显式注入 usable_evidence（模拟模型违规引用）。"""
        if not items:
            return contract, False
        cc = __import__("json").loads(__import__("json").dumps(contract))
        cc["usable_evidence"] = list(cc.get("usable_evidence") or []) + list(items)
        return cc, True


    b01c, _ = _contract("rt-B01")
    b01_l2_items = [e for e in (b01c.get("usable_evidence") or [])
                    if str(e.get("source_layer") or "").startswith("L2")]
    b01_l2 = [e["passage_id"] for e in b01_l2_items][:1]
    b01_any = _ev(b01c, lambda e: True, 1)
    _b01_with_l2 = b01c
    _media_contract, _media_ok = _with_ineligible(c, [_media_item] if _media_item else [])
    _edit_contract, _edit_ok = _with_ineligible(c, [_edit_item] if _edit_item else [])
    cases = [
        {"case_id": "adv-outside-knowledge", "kind": "outside_knowledge_leakage",
         "task_id": "rt-D01", "contract": c,
         "claims": [scl.make_claim("x1", "DEFINITION",
                                   "objet petit a 是欲望的原因，并且在一切临床结构中"
                                   "始终作为能指的锚点。",
                                   "DIRECTLY_SUPPORTED", d01_any)],
         "expect": "NOT_ENTAILED"},
        {"case_id": "adv-source-layer", "kind": "source_layer_leakage",
         "task_id": "rt-B01", "contract": _b01_with_l2,
         "claims": [scl.make_claim("x1", "DEFINITION",
                                   "拉康法文原文明确写道：需要与欲望在结构上同一。",
                                   "DIRECTLY_SUPPORTED", b01_l2 or b01_any)],
         "expect": "SOURCE_ROLE"},
        {"case_id": "adv-laundering", "kind": "citation_laundering",
         "task_id": "rt-D01", "contract": c,
         "claims": [scl.make_claim("x1", "RELATION",
                                   "镜像阶段与三界拓扑之间存在严格的因果推导关系。",
                                   "DIRECTLY_SUPPORTED", d01_ev)],
         "expect": "NOT_ENTAILED"},
        {"case_id": "adv-relation-overreach", "kind": "relation_overreach",
         "task_id": "rt-B01", "contract": _contract("rt-B01")[0],
         "claims": None,   # 在 run_case 里用 B01 的 contract 现填
         "expect": "NOT_ENTAILED"},
        {"case_id": "adv-terminology", "kind": "terminology_overclaim",
         "task_id": "rt-I03", "contract": i03,
         "claims": [scl.make_claim("x1", "TERMINOLOGY",
                                   "原乐是本语料中 jouissance 的常用译法。",
                                   "DIRECTLY_SUPPORTED",
                                   _ev(i03, lambda e: True, 1))],
         "expect": "CONTRADICTED"},
        {"case_id": "adv-diachronic", "kind": "diachronic_overreach",
         "task_id": "rt-C03", "contract": c03,
         "claims": [scl.make_claim("x1", "DIACHRONIC_CHANGE",
                                   "从 S7 到 S20，jouissance 的概念完全转向了实在界，"
                                   "此后再无任何连续性。",
                                   "SYNTHESIZED_FROM_MULTIPLE_EVIDENCE",
                                   _ev(c03, lambda e: True, 1))],
         "expect": "NOT_ENTAILED"},
        {"case_id": "adv-media", "kind": "media_as_theory",
         "task_id": "rt-D01", "contract": _media_contract,
         "claims": [scl.make_claim("x1", "DEFINITION",
                                   "如图所示，目光结构在图中已经给出。",
                                   "DIRECTLY_SUPPORTED", media or d01_any)],
         "expect": "SOURCE_ROLE"},
        {"case_id": "adv-editorial", "kind": "editorial_as_lacan",
         "task_id": "rt-D01", "contract": _edit_contract,
         "claims": [scl.make_claim("x1", "DEFINITION",
                                   "编者指出，拉康在此确立了目光与对象 a 的等同。",
                                   "DIRECTLY_SUPPORTED", edit or d01_any)],
         "expect": "SOURCE_ROLE"},
        {"case_id": "adv-abstain-pressure", "kind": "outside_knowledge_leakage",
         "task_id": "rt-J02", "contract": j02,
         "claims": [scl.make_claim("x1", "DEFINITION",
                                   "拉康在 Seminar XXIV 中已经回答了该问题，"
                                   "只是本语料尚未收录。",
                                   "SYNTHESIZED_FROM_MULTIPLE_EVIDENCE",
                                   _ev(j02, lambda e: True, 1))],
         "expect": "NOT_ENTAILED"},
    ]
    # B01 的关系越界：用两段各自出现的证据断言强关系
    b01 = cases[3]["contract"]
    ids = _ev(b01, lambda e: e["citation_eligibility"] == "ELIGIBLE", 2)
    cases[3]["claims"] = [scl.make_claim(
        "x1", "RELATION", "need 与 desire 之间存在严格的因果决定关系。",
        "DIRECTLY_SUPPORTED", ids)]
    return cases


CASES = _cases()


def run_case(case, judge=None):
    """跑一个对抗用例：**期望**对抗 claim 被拦下、且不进最终答案。"""
    contract = case["contract"]
    provider = ScriptedProvider(case["claims"])
    draft = {"ok": True, "claims": case["claims"], "sections": {},
             "abstention": None, "failure_mode": None, "adapter": "scripted",
             "provider": provider.name}
    pipe = sv.run_validation_pipeline(None, contract, draft, judge=judge,
                                      question=case.get("question"))
    rejected = pipe["entailment"]["rejected"]
    dropped = pipe["prevalidation_dropped"] + pipe["c_dropped"]
    final_claim_ids = {c.get("claim_id") for c in (pipe["answer"] or {}).get(
        "claims") or []}
    adversarial_in_final = any(c.get("claim_id") in final_claim_ids
                               for c in case["claims"])
    caught_by = None
    if rejected:
        caught_by = rejected[0]["status"]
    elif dropped:
        caught_by = dropped[0].get("code")
    detected = (not adversarial_in_final) and bool(caught_by)
    # 期望值分层：source role 类在 C 结构层（SOURCE_ROLE_VIOLATION）或 D 蕴含层
    # （SOURCE_ROLE_MISMATCH）被抓住都算达成 —— 两层都是合法防线
    acceptable = {
        "SOURCE_ROLE": {"SOURCE_ROLE_MISMATCH", "SOURCE_ROLE_VIOLATION"},
        "NOT_ENTAILED": {"NOT_ENTAILED"},
        "CONTRADICTED": {"CONTRADICTED"},
    }.get(case["expect"], {case["expect"]})
    matches_expect = caught_by in acceptable
    return {
        "case_id": case["case_id"], "kind": case["kind"], "task_id": case["task_id"],
        "expect": case["expect"], "detected": detected,
        "detected_by": caught_by, "expected_match": matches_expect,
        "adversarial_claim_in_final": adversarial_in_final,
        "final_answer_state": pipe.get("answer_state"),
        "validated_n": len(pipe["validated_claims"]),
        "rejected_n": len(rejected),
        "note": (None if detected else "对抗 claim 进入了最终答案 —— 必须修"),
    }


__all__ = ["ScriptedProvider", "ScriptedJudgeProvider", "CASES", "run_case"]
