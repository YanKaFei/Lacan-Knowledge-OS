#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_entailment_calibration.py — Phase 4C.1-D §43：entailment 校准集生成器

生成 `_data/eval/claim_entailment_calibration_v1.jsonl`（40 例 / 10 类）：

    positive_direct / positive_paraphrase / partial / lexical_only /
    wrong_source_role / wrong_citation / contradiction / composite_overreach /
    corpus_absence / metadata_absence

**确定性**：全部证据取自语料真实段落（passage_id + 真实文本），不手写文本；
期望状态由**规格**给出（不是由被测函数给出），因此校准集可以反过来检验 validator。

用法：python3 build_entailment_calibration.py [--check]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
EVAL = os.path.join(VAULT, "_data", "eval")
OUT = os.path.join(EVAL, "claim_entailment_calibration_v1.jsonl")
STORE = os.path.join(VAULT, "_data", "passage_store", "passages.jsonl")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import research_contract as rc        # noqa: E402

N = 40


def _load_passages():
    """取若干真实段落（L1 法文 / L2 中译 / 短片段）用于构造校准证据。"""
    want = {"L1": [], "L2": [], "FRAGMENT": [], "MEDIA": []}
    with open(STORE, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            text = str(d.get("raw_text") or "")
            cls = rc.classify_evidence_usability({"text": text})["usability_class"]
            auth = d.get("authority_level")
            if cls == "SUBSTANTIVE_TEXT" and auth == "L1" and len(text) > 160 \
                    and len(want["L1"]) < 12:
                want["L1"].append(d)
            elif cls == "SUBSTANTIVE_TEXT" and auth == "L2" and len(text) > 120 \
                    and len(want["L2"]) < 12:
                want["L2"].append(d)
            elif cls == "FRAGMENT_ONLY" and len(want["FRAGMENT"]) < 4:
                want["FRAGMENT"].append(d)
            elif cls == "MEDIA_ONLY" and len(want["MEDIA"]) < 4:
                want["MEDIA"].append(d)
            if all(len(v) >= (12 if k in ("L1", "L2") else 4)
                   for k, v in want.items()):
                break
    return want


def _ev(d, cls=None, eligibility=None):
    text = str(d.get("raw_text") or "")
    u = rc.classify_evidence_usability({"text": text})
    cls = cls or u["usability_class"]
    if eligibility is None:
        eligibility = ("ELIGIBLE" if cls == "SUBSTANTIVE_TEXT"
                       and d.get("authority_level") == "L1"
                       and not str(d.get("trace_status") or "").startswith(
                           "SOURCE_TRACE_INCOMPLETE")
                       else ("QUALIFIED" if cls == "SUBSTANTIVE_TEXT"
                             else "INELIGIBLE"))
    perms = (["substantive", "contextual", "limitation"]
             if eligibility != "INELIGIBLE" else ["limitation"])
    layer = ("L1_TRANSCRIPTION" if d.get("authority_level") == "L1" else
             ("L2_RECOVERED" if str(d.get("trace_status") or "").startswith(
                 "SOURCE_TRACE_INCOMPLETE") else "L2_TRANSLATION"))
    return {"passage_id": d["id"], "seminar_id": d.get("seminar_id"),
            "session_id": d.get("session_id"), "language": d.get("language"),
            "authority_level": d.get("authority_level"),
            "text_role": d.get("text_role"), "trace_status": d.get("trace_status"),
            "text": text, "usability_class": cls,
            "citation_eligibility": eligibility, "claim_permissions": perms,
            "source_layer": layer, "attribution": "（校准集）",
            "rank": 1, "selection_reason": ["calibration"]}


def _contract(evidence, relation=None, terminology=None):
    return {"task_id": "calibration", "task_type": "concept_definition",
            "usable_evidence": evidence,
            "relation_evidence": relation or {"required": False, "n": 0, "ids": [],
                                              "strength": "R0_NONE"},
            "terminology_evidence": terminology or {},
            "source_layers": {"required": [], "available": [], "missing": []},
            "formalism_evidence": {}, "metadata_evidence": {},
            "claim_permissions": {}, "citation_policy": {},
            "abstention_requirements": {}, "warnings": [],
            "status": "READY", "answer_permission": "FULL_SYNTHESIS"}


def _first_clause(text, n=90):
    t = " ".join(str(text or "").split())
    for sep in ("。", "！", "？", ".", "；", ";"):
        i = t.find(sep)
        if 20 <= i <= n + 40:
            return t[:i + 1]
    return t[:n]


def build():
    p = _load_passages()
    cases = []
    i = 0

    def add(cat, contract, atom, expect, strength=None, requires_judge=False,
            note=""):
        nonlocal i
        i += 1
        cases.append({
            "case_id": "ce-%02d" % i, "category": cat,
            "question": "校准样例", "contract": contract, "atom": atom,
            "expected_status": expect, "expected_strength": strength,
            "requires_judge": requires_judge, "note": note,
            "source": "claim_entailment_calibration_v1",
        })

    # ① positive_direct（逐字包含 → 离线可判）
    for d in p["L1"][:4]:
        ev = _ev(d)
        text = " ".join(str(d["raw_text"]).split())
        add("positive_direct", _contract([ev]),
            {"atom_id": "a1", "atom_text": text[:80], "claim_type": "DEFINITION",
             "epistemic_status": "DIRECTLY_SUPPORTED",
             "evidence_ids": [d["id"]]},
            "ENTAILED", "E4_DIRECT", note="逐字包含")

    # ② positive_paraphrase（同义复述 → 需要 judge）
    #    ⚠️ 复述必须是**对该段真实内容**的轻度改写，否则期望标签本身就是错的
    #    （第一版用了与段落无关的通用复述，被真实 judge 正确判为 NOT_ENTAILED —— 记在报告里）
    for d in p["L1"][4:8]:
        ev = _ev(d)
        base = _first_clause(d.get("raw_text"))
        para = (base.replace("c’est", "ceci est").replace("n’est", "n est")
                .replace("il y a", "il existe"))
        add("positive_paraphrase", _contract([ev]),
            {"atom_id": "a1",
             "atom_text": para,
             "claim_type": "DEFINITION", "epistemic_status": "QUALIFIED_INFERENCE",
             "evidence_ids": [d["id"]]},
            "ENTAILED", "E3_SUBSTANTIVE", requires_judge=True,
            note="对真实段落的轻度改写（同义/语序），judge 应判 ENTAILED")

    # ③ partial（前半是段落原话，后半是超出证据的全称断言 → 部分蕴含）
    for d in p["L1"][8:12]:
        ev = _ev(d)
        base = _first_clause(d.get("raw_text"))
        add("partial", _contract([ev]),
            {"atom_id": "a1",
             "atom_text": "%s；并且这一结论在拉康全部时期、全部临床结构中都始终有效。"
                          % base,
             "claim_type": "DEFINITION", "epistemic_status": "DIRECTLY_SUPPORTED",
             "evidence_ids": [d["id"]]},
            "PARTIALLY_ENTAILED", None, requires_judge=True,
            note="一半可核（原话）+ 一半越界（全称）")

    # ④ lexical_only（只提到同一术语）
    for d in p["L1"][:4]:
        ev = _ev(d)
        add("lexical_only", _contract([ev]),
            {"atom_id": "a1",
             "atom_text": "该术语在拉康的拓扑学中承担奠基性的因果作用。",
             "claim_type": "DEFINITION", "epistemic_status": "QUALIFIED_INFERENCE",
             "evidence_ids": [d["id"]]},
            "NOT_ENTAILED", "E1_LEXICAL" if False else None,
            note="只有术语重合，没有论断")

    # ⑤ wrong_source_role（L2 中译被当成原文）
    for d in (p["L2"][:4] or p["L1"][:4]):
        ev = _ev(d)
        add("wrong_source_role", _contract([ev]),
            {"atom_id": "a1", "atom_text": "拉康法文原文明确写道：主体的结构由能指决定。",
             "claim_type": "DEFINITION", "epistemic_status": "DIRECTLY_SUPPORTED",
             "evidence_ids": [d["id"]]},
            "SOURCE_ROLE_MISMATCH", "E0_NONE", note="来源层措辞越界")

    # ⑥ wrong_citation（引用洗白：真实 passage 但不支持断言）
    for d in p["L1"][:4]:
        ev = _ev(d)
        add("wrong_citation", _contract([ev]),
            {"atom_id": "a1",
             "atom_text": "镜像阶段与三界拓扑之间存在严格的因果推导关系。",
             "claim_type": "RELATION", "epistemic_status": "DIRECTLY_SUPPORTED",
             "evidence_ids": [d["id"]]},
            "NOT_ENTAILED", None, note="citation 存在但与断言无关")

    # ⑦ contradiction（与证据矛盾）
    for d in p["L1"][:4]:
        ev = _ev(d)
        add("contradiction", _contract([ev],
                                       terminology={"原乐": {
                                           "mapping_completion": "MAPPING_COMPLETE",
                                           "attestation_completion": "ZERO_ATTESTATION",
                                           "context_validation": "NOT_APPLICABLE",
                                           "corpus_hits": 0, "evidence_ids": []}}),
            {"atom_id": "a1", "atom_text": "原乐是本语料中 jouissance 的常用译法。",
             "claim_type": "TERMINOLOGY", "epistemic_status": "DIRECTLY_SUPPORTED",
             "evidence_ids": [d["id"]]},
            "CONTRADICTED", "E0_NONE", note="零见证 vs 常用译法")

    # ⑧ composite_overreach（A、B 各自出现 → 断言强关系）
    for k in range(4):
        a, b = p["L1"][k % len(p["L1"])], p["L1"][(k + 1) % len(p["L1"])]
        evs = [_ev(a), _ev(b)]
        add("composite_overreach",
            _contract(evs, relation={"required": True, "n": 0, "ids": [],
                                     "strength": "R1_COOCCURRENCE"}),
            {"atom_id": "a1",
             "atom_text": "两个概念之间存在严格的因果决定关系，前者必然产生后者。",
             "claim_type": "RELATION", "epistemic_status": "SYNTHESIZED_FROM_MULTIPLE_EVIDENCE",
             "evidence_ids": [a["id"], b["id"]]},
            "NOT_ENTAILED", "E1_LEXICAL", note="R1 支撑不了因果关系")

    # ⑨ corpus_absence（由全库普查支撑）
    for k in range(4):
        d = p["L1"][k % len(p["L1"])]
        atom = {"atom_id": "a1", "atom_text": "术语「原乐」在当前语料中零见证（全库 0 段）。",
                "claim_type": "CORPUS_ABSENCE", "epistemic_status": "CORPUS_ABSENCE",
                "evidence_ids": [],
                "corpus_scan_ref": {"scope": "whole_corpus", "term": "原乐",
                                    "corpus_hits": 0, "run": k}}
        add("corpus_absence", _contract([_ev(d)]), atom, "ENTAILED", "E4_DIRECT",
            note="普查凭据支撑缺失断言")

    # ⑩ metadata_absence（由 metadata scan 支撑）
    for k in range(4):
        d = p["L1"][k % len(p["L1"])]
        c = _contract([_ev(d)])
        c["metadata_evidence"] = {"metadata_required": ["exact_date"],
                                  "metadata_state": "METADATA_UNAVAILABLE",
                                  "metadata_missing_fields": ["session_date（全库 unknown）"]}
        atom = {"atom_id": "a1", "atom_text": "全库 session_date 不可用（全为 unknown）。",
                "claim_type": "METADATA", "epistemic_status": "CORPUS_ABSENCE",
                "evidence_ids": [],
                "corpus_scan_ref": {"scope": "whole_corpus", "field": "session_date",
                                    "n_with_real_value": 0, "run": k}}
        add("metadata_absence", c, atom, "ENTAILED", "E4_DIRECT",
            note="metadata scan 支撑")
    return cases


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    cases = build()
    if a.check:
        have = [json.loads(l) for l in open(OUT, encoding="utf-8") if l.strip()] \
            if os.path.isfile(OUT) else []
        if json.dumps(have, ensure_ascii=False, sort_keys=True) != \
                json.dumps(cases, ensure_ascii=False, sort_keys=True):
            print("校准集与生成器不一致（重跑 build_entailment_calibration.py）")
            return 1
        print("校准集与生成器一致：%d 例" % len(have))
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")
    print("-> %s（%d 例 / %d 类）" % (os.path.relpath(OUT, VAULT), len(cases),
                                      len({c["category"] for c in cases})))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
