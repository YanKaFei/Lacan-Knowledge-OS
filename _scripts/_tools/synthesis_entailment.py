#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
synthesis_entailment.py — Phase 4C.1-D §5–§22：**Claim–Evidence Entailment**

C 阶段只证明「claim 有引用」。D 阶段要回答真正的问题：

    citation 是否**真的支持** claim？

Hybrid architecture（§9），顺序固定：

    ① Deterministic pre-check   （证据存在/资格/正文/来源角色/引文可核/范围相容）
    ② Lexical / structural match（术语与结构信号 → E1/E2/E3 提示）
    ③ Domain rules              （relation R0–R4 / diachronic composite /
                                 terminology mapping≠attestation / corpus absence /
                                 metadata scan）
    ④ LLM entailment judge      （只看 ClaimAtom + 它自己的证据，结构化输出）
    ⑤ Final aggregation         （**取最保守结论**；冲突记 ENTAILMENT_DISAGREEMENT）

三条不变：
    * `citation exists` ≠ `ENTAILED`；
    * 媒体/书目/编者证据**永远**不能支撑 substantive claim；
    * 只在确定性层无法判定时才调用 judge（省钱、可复算、可离线）。
"""
from __future__ import annotations

import json
import re
import unicodedata

SCHEMA = "claim-entailment/v1"

ENTAILMENT_STATUS = ("ENTAILED", "PARTIALLY_ENTAILED", "NOT_ENTAILED", "CONTRADICTED",
                     "INSUFFICIENT_CONTEXT", "SOURCE_ROLE_MISMATCH", "UNDETERMINED")
# 由轻到重（聚合时取 index 更大者 = 更保守）
_STATUS_SEVERITY = {"ENTAILED": 0, "PARTIALLY_ENTAILED": 1, "INSUFFICIENT_CONTEXT": 2,
                    "UNDETERMINED": 2, "SOURCE_ROLE_MISMATCH": 3, "NOT_ENTAILED": 4,
                    "CONTRADICTED": 5}
ENTAILMENT_STRENGTH = ("E0_NONE", "E1_LEXICAL", "E2_CONTEXTUAL", "E3_SUBSTANTIVE",
                       "E4_DIRECT")
_STRENGTH_RANK = {s: i for i, s in enumerate(ENTAILMENT_STRENGTH)}

QUOTE_STATUS = ("EXACT_QUOTE_VALID", "NORMALIZED_QUOTE_VALID", "QUOTE_NOT_FOUND")

REJECTION_STATUSES = ("NOT_ENTAILED", "CONTRADICTED", "SOURCE_ROLE_MISMATCH")

SUBSTANTIVE_CLAIM_TYPES = ("DEFINITION", "DISTINCTION", "RELATION", "DIACHRONIC_CHANGE",
                           "SOURCE_INFLUENCE", "REINTERPRETATION", "TERMINOLOGY",
                           "FORMALISM")

_ORIGINAL_PHRASES = re.compile(r"拉康原文|法文原文|原文说|原文写道|拉康写道|"
                               r"Lacan\s+dit|texte\s+original|in the original", re.I)
_UNIVERSAL = re.compile(r"总是|始终|一律|所有|任何|必然|从来|永远|"
                        r"always|never|all\s+\w+|necessarily", re.I)
_ABSENCE_PHRASES = re.compile(r"零见证|0\s*段|不存在|没有出现|未被展开|"
                              r"zero\s+attestation|not\s+attested", re.I)
_TERM_FREQ_PHRASES = re.compile(r"常用译法|常见译法|普遍使用|广泛使用|通用译法|"
                                r"commonly\s+used|widely\s+used", re.I)
_CLAUSE_SPLIT = re.compile(r"[，,；;。.!?！？]|\s+(?:and|while|whereas|but)\s+", re.I)


def _norm_ws(t):
    return re.sub(r"\s+", " ", str(t or "")).strip()


def _nfkc(t):
    return unicodedata.normalize("NFKC", _norm_ws(t))


# ══════════════════════════════════════════════════════════════════════ §5 atoms
def atomize_claim(claim, contract=None):
    """一条 StructuredClaim → ClaimAtom[]（§5/§6）。

    复合 claim 必须拆开验证：citation 可能只支持其中一个原子命题。
    拆分是**确定性**的（标点/并列连词切分），不做语义理解。
    """
    text = _norm_ws((claim or {}).get("claim_text"))
    ctype = (claim or {}).get("claim_type")
    # 带分隔符切分（分隔符保留），以便识别归属前缀「…拉康：」
    pieces = re.split(r"([，,；;。.!?！？]|\s+(?:and|while|whereas|but)\s+)", text)
    segs = []
    for i in range(0, len(pieces) - 1, 2):
        seg, delim = pieces[i].strip(), pieces[i + 1]
        if seg:
            segs.append((seg, delim))
    if len(pieces) % 2 == 1 and pieces[-1].strip():
        segs.append((pieces[-1].strip(), ""))
    if not segs:
        segs = [(text, "")]
    # 归属前缀（以「：」结尾）并入后一段
    merged, carry = [], ""
    for seg, delim in segs:
        if delim in ("：", ":"):
            carry += seg + "："
            continue
        merged.append((carry + seg).strip() if carry else seg)
        carry = ""
    if carry:
        merged.append(carry)
    # 开头的归属片段（「在该段…中」「当前收录的…显示」「编者说明」…）并入后一段
    if len(merged) >= 2 and len(merged[0]) <= 30 and re.search(
            r"拉康|该段|显示|编者|书目|根据|据", merged[0]):
        merged = [(merged[0] + "，" + merged[1])] + merged[2:]
    # 太短的碎片并回前一段
    final_parts = []
    for p in merged:
        if final_parts and len(p) < 8:
            final_parts[-1] = final_parts[-1] + "，" + p
        else:
            final_parts.append(p)
    parts = final_parts or [text]
    atoms = []
    for i, p in enumerate(parts, 1):
        atoms.append({
            "schema_version": SCHEMA,
            "atom_id": "%s.a%d" % (claim.get("claim_id"), i),
            "parent_claim_id": claim.get("claim_id"),
            "atom_text": p,
            "claim_type": ctype,
            "epistemic_status": claim.get("epistemic_status"),
            "evidence_ids": list(claim.get("evidence_ids") or []),
            "scope": claim.get("scope") or "claim-level",
            "source_attribution": None,
            "entailment_required": ctype in SUBSTANTIVE_CLAIM_TYPES,
            "corpus_scan_ref": claim.get("corpus_scan_ref"),
        })
    return atoms


# ══════════════════════════════════════════════════════════════════════ §12 quotes
def validate_quote(quotation, contract):
    """引文**确定性**核验（§12）：不得让 judge 决定引文是否存在。"""
    q = quotation or {}
    if not q:
        return {"status": None, "detail": "no quotation"}
    if q.get("kind") != "CORPUS_QUOTE":
        return {"status": "NOT_APPLICABLE", "kind": q.get("kind"),
                "detail": "非 CORPUS_QUOTE，不做逐字核验"}
    pid = q.get("passage_id")
    span = str(q.get("exact_span") or "")
    ev = {e["passage_id"]: e for e in (contract.get("usable_evidence") or [])}.get(pid)
    if not ev or not span:
        return {"status": "QUOTE_NOT_FOUND", "passage_id": pid,
                "detail": "段落不在包内或缺 exact_span"}
    text = str(ev.get("text") or "")
    if span in text:
        return {"status": "EXACT_QUOTE_VALID", "passage_id": pid,
                "detail": "exact_span 逐字命中"}
    if _nfkc(span) and _nfkc(span) in _nfkc(text):
        return {"status": "NORMALIZED_QUOTE_VALID", "passage_id": pid,
                "detail": "规范化（NFKC + 空白折叠）后命中"}
    return {"status": "QUOTE_NOT_FOUND", "passage_id": pid,
            "detail": "exact_span 既非逐字、也非规范化命中"}


def sanitize_claims(claims, contract):
    """LLM 输出的**预清洗**（记录在案，不静默）：

    * substantive claim 没有 evidence_ids → 丢掉（CLAIM_WITHOUT_EVIDENCE）
    * 引用了包外 passage 的 claim → 丢掉（INVALID_CITATION_REFERENCE）
    * 引文核验失败 → **只丢引文**（保留 claim，去掉 quotation）并记账
    """
    kept, dropped, quote_fixes = [], [], []
    usable = {e["passage_id"]: e for e in (contract.get("usable_evidence") or [])}
    for c in claims or []:
        c = dict(c)
        ctype = c.get("claim_type")
        ids = list(c.get("evidence_ids") or [])
        if ctype in SUBSTANTIVE_CLAIM_TYPES and not ids:
            dropped.append({"claim_id": c.get("claim_id"),
                            "code": "CLAIM_WITHOUT_EVIDENCE",
                            "claim_text": str(c.get("claim_text"))[:120]})
            continue
        bad = [i for i in ids if i not in usable]
        if bad:
            dropped.append({"claim_id": c.get("claim_id"),
                            "code": "INVALID_CITATION_REFERENCE",
                            "detail": bad})
            continue
        # absence / metadata 断言：必须由**引擎侧普查事实**支撑（由 pipeline 注入），
        # 否则丢掉 —— 模型不得凭空断言「不存在」。
        if c.get("claim_type") in ("CORPUS_ABSENCE", "METADATA") and \
                not c.get("corpus_scan_ref"):
            c["_needs_scan_ref"] = True
        q = c.get("quotation")
        if q and q.get("kind") == "CORPUS_QUOTE":
            vr = validate_quote(q, contract)
            if vr["status"] == "QUOTE_NOT_FOUND":
                c["quotation"] = None
                c["quotation_dropped"] = "QUOTE_NOT_FOUND"
                quote_fixes.append({"claim_id": c.get("claim_id"),
                                    "code": "QUOTE_NOT_FOUND",
                                    "passage_id": q.get("passage_id")})
        kept.append(c)
    return kept, dropped, quote_fixes


# ══════════════════════════════════════════════════════════════════════ ① precheck
def _is_substantive(atom):
    return atom.get("claim_type") in SUBSTANTIVE_CLAIM_TYPES


def deterministic_precheck(atom, contract):
    """确定性检查（§10）→ {"status","strength","reason"} 或 UNDETERMINED。"""
    text = str(atom.get("atom_text") or "")
    ids = list(atom.get("evidence_ids") or [])
    usable = {e["passage_id"]: e for e in (contract.get("usable_evidence") or [])}
    rel = contract.get("relation_evidence") or {}
    term = contract.get("terminology_evidence") or {}
    ctype = atom.get("claim_type")

    # ① 没有证据的 substantive 原子
    if _is_substantive(atom) and not ids:
        if atom.get("corpus_scan_ref"):
            return {"status": "ENTAILED", "strength": "E4_DIRECT",
                    "reason": "corpus_scan / metadata_scan 直接支撑（非 passage citation）",
                    "signal": "SCAN_ENTAILED"}
        return {"status": "NOT_ENTAILED", "strength": "E0_NONE",
                "reason": "substantive 原子没有 evidence", "signal": "NO_EVIDENCE"}

    # ② 引文核验（§12）
    q = atom.get("quotation")
    if q:
        vr = validate_quote(q, contract)
        if vr["status"] == "QUOTE_NOT_FOUND":
            return {"status": "NOT_ENTAILED", "strength": "E0_NONE",
                    "reason": "引文核验失败：%s" % vr["detail"],
                    "signal": "QUOTE_NOT_FOUND", "quote": vr}

    # ③ 证据资格与来源角色（§11）
    for eid in ids:
        ev = usable.get(eid)
        if ev is None:
            return {"status": "NOT_ENTAILED", "strength": "E0_NONE",
                    "reason": "引用了包外 passage %s" % eid,
                    "signal": "INVALID_CITATION"}
        if ev.get("citation_eligibility") == "INELIGIBLE":
            return {"status": "SOURCE_ROLE_MISMATCH", "strength": "E0_NONE",
                    "reason": "%s 属 INELIGIBLE（%s），不得承担理论断言"
                              % (eid, ev.get("usability_class")),
                    "signal": "INELIGIBLE_EVIDENCE"}
        if _is_substantive(atom) and "substantive" not in (ev.get("claim_permissions")
                                                            or []):
            return {"status": "SOURCE_ROLE_MISMATCH", "strength": "E0_NONE",
                    "reason": "%s 的 usability=%s 不能承担 substantive claim"
                              % (eid, ev.get("usability_class")),
                    "signal": "USABILITY_MISMATCH"}
        if not _norm_ws(ev.get("text")):
            return {"status": "INSUFFICIENT_CONTEXT", "strength": "E0_NONE",
                    "reason": "%s 正文为空" % eid, "signal": "EMPTY_PASSAGE"}

    # ④ 措辞 vs 来源层（§11/§34）
    if _ORIGINAL_PHRASES.search(text) and ids:
        layers = {usable.get(i, {}).get("source_layer") for i in ids}
        if layers and not (layers & {"L1_ORIGINAL", "L1_TRANSCRIPTION"}):
            return {"status": "SOURCE_ROLE_MISMATCH", "strength": "E0_NONE",
                    "reason": "只引用 %s，却使用「原文/拉康说」措辞" % sorted(layers),
                    "signal": "SOURCE_LANGUAGE_MISMATCH"}

    # ⑤ relation 规则（§15）
    if ctype == "RELATION":
        strength = rel.get("strength") or "R0_NONE"
        if strength in ("R0_NONE", "R1_COOCCURRENCE"):
            if re.search(r"关系|影响|导致|决定|因果|relation|cause", text, re.I):
                return {"status": "NOT_ENTAILED", "strength": "E1_LEXICAL",
                        "reason": "relation_strength=%s 支撑不了关系断言" % strength,
                        "signal": "RELATION_TOO_WEAK"}
        elif strength == "R2_CONTEXTUAL_RELATION":
            return {"status": "PARTIALLY_ENTAILED", "strength": "E2_CONTEXTUAL",
                    "reason": "relation_strength=R2：只能支撑限定性关系表述",
                    "signal": "RELATION_R2_QUALIFIED"}

    # ⑥ 术语 claim：mapping ≠ attestation（§17）
    if ctype == "TERMINOLOGY":
        for t_, v in (term or {}).items():
            if t_ and t_ in text:
                if _TERM_FREQ_PHRASES.search(text) and \
                        v.get("attestation_completion") == "ZERO_ATTESTATION":
                    return {"status": "CONTRADICTED", "strength": "E0_NONE",
                            "reason": "术语 %s 全库 attestation=0，却断言「常用/常见」" % t_,
                            "signal": "TERMINOLOGY_OVERCLAIM"}
                if v.get("mapping_completion") == "MAPPING_COMPLETE" and \
                        re.search(r"译名|映射|mapping", text):
                    return {"status": "ENTAILED", "strength": "E4_DIRECT",
                            "reason": "术语桥 mapping 记录直接支撑映射断言",
                            "signal": "TERMINOLOGY_MAP_ENTAILED",
                            "corpus_scan_ref": {"term": t_,
                                                "mapping": v.get("mapping_completion")}}

    # ⑥b formalism：命中的形式表达式就是该段证据（formalism_evidence.hits 已记录 raw_matched_form）
    if ctype == "FORMALISM":
        for h in ((contract.get("formalism_evidence") or {}).get("hits") or []):
            if h.get("passage_id") in ids and h.get("raw_matched_form"):
                if _norm_ws(h["raw_matched_form"]) in _norm_ws(text) or \
                        (h.get("normalized_matched_form") and
                         h["normalized_matched_form"] in _nfkc(text)):
                    return {"status": "ENTAILED", "strength": "E4_DIRECT",
                            "reason": "formalism 命中记录（raw_matched_form=%s）直接支撑"
                                      % h["raw_matched_form"],
                            "signal": "FORMALISM_HIT_ENTAILED"}

    # ⑦ corpus absence / metadata（§18/§19）：由全库普查凭据支撑（不要求 passage citation）
    if ctype in ("METADATA", "CORPUS_ABSENCE") and atom.get("corpus_scan_ref"):
        return {"status": "ENTAILED", "strength": "E4_DIRECT",
                "reason": "全库普查/metadata scan 凭据直接支撑该断言",
                "signal": "SCAN_ENTAILED"}
    if _ABSENCE_PHRASES.search(text) and atom.get("corpus_scan_ref"):
        return {"status": "ENTAILED", "strength": "E4_DIRECT",
                "reason": "全库普查凭据支撑缺失断言", "signal": "SCAN_ENTAILED"}

    return {"status": "UNDETERMINED", "strength": None, "reason": None, "signal": None}


# ══════════════════════════════════════════════════════════════════ ② lexical
_STOP = set("的 了 是 在 与 和 及 或 等 中 被 把 从 对 为 以 而 就 都 也 这 那 其 之 该 有 无 "
            "the a an of in on to and or is are was were for with that this it as by "
            "que qui est sont dans pour avec sur les des une un ce cette il elle".split())


def _tokens(text):
    t = _nfkc(text).lower()
    out = set(re.findall(r"[a-zà-ÿ]{3,}", t))
    out |= set(re.findall(r"[\u4e00-\u9fff]{2,}", t))
    return {w for w in out if w not in _STOP}


_ATTR_PREFIX = re.compile(r"^(在该段[^：:]*中，拉康|当前收录的[^：:]*显示[^：:]*|"
                          r"编者说明|书目[^：:]*)[：:]\s*")


def _strip_attr(text):
    return _ATTR_PREFIX.sub("", str(text or "")).strip()


def lexical_signal(atom, contract):
    """术语/结构信号（§9 的第 2 层）：→ strength 提示（E1/E2/E3/E4）。

    额外做一件事：**逐字包含**检验 —— 若（去掉归属前缀后的）原子文本是某段证据的
    子串，那就是可离线判定的 ENTAILED（E4_DIRECT）。这是最强、最可复核的信号。
    """
    core = _strip_attr(atom.get("atom_text"))
    usable = {e["passage_id"]: e for e in (contract.get("usable_evidence") or [])}
    if core and len(core) >= 8:
        for eid in (atom.get("evidence_ids") or []):
            ev = usable.get(eid) or {}
            if core and core in _norm_ws(ev.get("text")):
                return {"strength": "E4_DIRECT", "overlap": 1.0,
                        "hits": [], "exact_containment": True, "passage_id": eid}
            if _nfkc(core) and _nfkc(core) in _nfkc(ev.get("text")):
                return {"strength": "E4_DIRECT", "overlap": 1.0, "hits": [],
                        "exact_containment": True, "normalized": True,
                        "passage_id": eid}
    tt = _tokens(atom.get("atom_text"))
    if not tt:
        return {"strength": "E0_NONE", "overlap": 0.0, "hits": []}
    usable = {e["passage_id"]: e for e in (contract.get("usable_evidence") or [])}
    best = 0.0
    hits = []
    for eid in (atom.get("evidence_ids") or []):
        ev = usable.get(eid) or {}
        et = _tokens(ev.get("text"))
        if not et:
            continue
        inter = tt & et
        ratio = len(inter) / max(1, len(tt))
        if ratio > best:
            best, hits = ratio, sorted(inter)[:8]
    if best >= 0.6:
        return {"strength": "E3_SUBSTANTIVE", "overlap": round(best, 3), "hits": hits}
    if best >= 0.3:
        return {"strength": "E2_CONTEXTUAL", "overlap": round(best, 3), "hits": hits}
    if best > 0:
        return {"strength": "E1_LEXICAL", "overlap": round(best, 3), "hits": hits}
    return {"strength": "E0_NONE", "overlap": 0.0, "hits": []}


# ══════════════════════════════════════════════════════════════════ ④ LLM judge
JUDGE_SYSTEM = """你是**蕴含裁判**（entailment judge），只判断一件事：

    给定的一条 claim atom 是否能被给定的 evidence 文本支持？

严格边界：
1. 只能使用给出的 evidence 文本；不得使用你自己的拉康知识。
2. 不得因为「citation 存在」就判 ENTAILED —— 必须看文本是否**真的**表达该断言。
3. 证据只是提到同一术语 → E1_LEXICAL；语境相关但没表达断言 → E2_CONTEXTUAL；
   文本足以支持合理复述 → E3_SUBSTANTIVE；几乎直接表达，或形式关系明确 → E4_DIRECT。
4. 证据与断言相互矛盾 → CONTRADICTED。
5. 措辞超出证据范围（例如原文层不存在却写「拉康原文」）→ SOURCE_ROLE_MISMATCH。
6. 证据不足以判断 → INSUFFICIENT_CONTEXT。
7. 只输出 JSON，不要解释性前后文。
"""

JUDGE_SCHEMA = {
    "judgments": [{
        "atom_id": "c1.a1",
        "status": "ENTAILED|PARTIALLY_ENTAILED|NOT_ENTAILED|CONTRADICTED|"
                  "INSUFFICIENT_CONTEXT|SOURCE_ROLE_MISMATCH",
        "strength": "E0_NONE|E1_LEXICAL|E2_CONTEXTUAL|E3_SUBSTANTIVE|E4_DIRECT",
        "supported_scope": "被支持的部分（或 null）",
        "unsupported_scope": "不被支持的部分（或 null）",
        "reason": "一句话理由",
        "evidence_refs": ["passage…"],
    }]
}


def judge_prompt(atoms, contract, question=None):
    """judge 输入（§20）：**只**给 atom + 它自己的证据 + 必要任务语境。"""
    usable = {e["passage_id"]: e for e in (contract.get("usable_evidence") or [])}
    payload = {"question": question, "task_type": contract.get("task_type"),
               "atoms": [], "evidence": []}
    seen = set()
    for a in atoms:
        payload["atoms"].append({k: a.get(k) for k in
                                 ("atom_id", "parent_claim_id", "atom_text",
                                  "claim_type", "epistemic_status", "evidence_ids",
                                  "scope")})
        for eid in a.get("evidence_ids") or []:
            if eid in seen:
                continue
            seen.add(eid)
            ev = usable.get(eid) or {}
            payload["evidence"].append({
                "passage_id": eid, "seminar_id": ev.get("seminar_id"),
                "language": ev.get("language"), "authority_level": ev.get("authority_level"),
                "text_role": ev.get("text_role"), "source_layer": ev.get("source_layer"),
                "citation_eligibility": ev.get("citation_eligibility"),
                "text": ev.get("text"),
            })
    return (JUDGE_SYSTEM,
            "待判的 claim atoms 与证据如下（JSON）：\n%s\n\n"
            "请输出形如 %s 的 JSON。"
            % (json.dumps(payload, ensure_ascii=False),
               json.dumps(JUDGE_SCHEMA, ensure_ascii=False)))


class EntailmentJudge:
    """LLM judge 适配器（provider 抽象与 C 阶段一致；可离线、可脚本化）。"""

    def __init__(self, provider=None, enabled=True):
        self.provider = provider
        self.enabled = enabled and provider is not None and \
            getattr(provider, "available", False)
        self.calls = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0, "latency_s": 0.0}

    def judge(self, atoms, contract, question=None):
        """→ {atom_id: {status,strength,supported_scope,unsupported_scope,reason,refs}}"""
        if not self.enabled or not atoms:
            return {}
        system, user = judge_prompt(atoms, contract, question)
        try:
            raw = self.provider.complete(system, user, JUDGE_SCHEMA)
        except Exception as exc:                              # provider 失败
            return {"__provider_error__": {"status": "INSUFFICIENT_CONTEXT",
                                           "reason": "judge provider 失败：%s"
                                                     % str(exc)[:160]}}
        self.calls += 1
        if isinstance(raw, dict) and raw.get("_usage"):
            u = raw["_usage"]
            self.usage["input_tokens"] += int(u.get("prompt_tokens") or 0)
            self.usage["output_tokens"] += int(u.get("completion_tokens") or 0)
            self.usage["latency_s"] += float(u.get("latency_s") or 0)
        out = {}
        for j in (raw or {}).get("judgments") or []:
            if not isinstance(j, dict) or not j.get("atom_id"):
                continue
            st = j.get("status")
            if st not in ENTAILMENT_STATUS:
                st = "INSUFFICIENT_CONTEXT"
            strength = j.get("strength")
            if strength not in ENTAILMENT_STRENGTH:
                strength = None
            out[j["atom_id"]] = {
                "status": st, "strength": strength,
                "supported_scope": j.get("supported_scope"),
                "unsupported_scope": j.get("unsupported_scope"),
                "reason": j.get("reason"), "evidence_refs": j.get("evidence_refs") or [],
            }
        return out


# ══════════════════════════════════════════════════════════════════ ⑤ aggregate
def _conservative(a, b):
    """取更保守的 status；strength 取更小者。"""
    if a is None:
        return b
    if b is None:
        return a
    sa, sb = _STATUS_SEVERITY.get(a, 2), _STATUS_SEVERITY.get(b, 2)
    return a if sa >= sb else b


def validate_atom(atom, contract, judge=None, question=None, llm_pre=None):
    """单个原子的最终判定：确定性优先，无法判定才问 judge；冲突记 disagreement。

    `llm_pre`：调用方预先批量取得的 judge 结论（一次调用判多个原子，省 token）。
    """
    pre = deterministic_precheck(atom, contract)
    lex = lexical_signal(atom, contract)
    det_status = pre["status"] if pre["status"] != "UNDETERMINED" else None
    llm = {}
    if llm_pre is not None:
        llm = llm_pre.get(atom.get("atom_id")) or {}
    elif judge is not None and det_status is None:
        jm = judge.judge([atom], contract, question)
        llm = jm.get(atom.get("atom_id")) or {}
    final = det_status
    # 逐字包含 → 可离线判定 ENTAILED（不需要 judge）
    if final is None and lex.get("exact_containment"):
        final = "ENTAILED"
    if final is None and llm:
        final = llm.get("status")
    if final is None:
        # 没有 judge（离线/未配置）时的**离线策略**：
        #   * 与所有证据只有 E0/E1（无实质重合）→ NOT_ENTAILED
        #     （这正是「引用洗白 / 外部知识泄漏」的可离线检测面）
        #   * E2/E3 → INSUFFICIENT_CONTEXT（诚实：需要 judge 才能判定）
        if det_status is None:
            if lex["strength"] in ("E0_NONE", "E1_LEXICAL"):
                final = "NOT_ENTAILED"
                pre = dict(pre)
                pre["reason"] = ("证据与断言之间没有实质重合（仅 %s）——"
                                 "离线策略判 NOT_ENTAILED（疑似引用洗白/越界补知识）"
                                 % lex["strength"])
                pre["signal"] = "NO_SUBSTANTIVE_OVERLAP"
            else:
                final = "INSUFFICIENT_CONTEXT"
        else:
            final = det_status
    disagreement = bool(det_status and llm.get("status")
                        and det_status != llm["status"]) or \
        (det_status is None and llm.get("status") and lex["strength"] == "E0_NONE"
         and llm["status"] == "ENTAILED")
    if disagreement:
        # 冲突 → 取更保守者（§22），并打标
        final = _conservative(det_status, llm.get("status"))
    strength = pre.get("strength") or llm.get("strength") or lex["strength"]
    if final in ("NOT_ENTAILED", "CONTRADICTED", "SOURCE_ROLE_MISMATCH"):
        strength = strength or "E0_NONE"
    # 安全兜底（§35 引用洗白）：judge 说 ENTAILED，但证据与断言**零/仅词面重合**时，
    # 对 substantive 原子一律不通过 —— 真实 citation ≠ 有效 citation。
    if final == "ENTAILED" and det_status is None and _is_substantive(atom) and \
            lex["strength"] in ("E0_NONE", "E1_LEXICAL"):
        final = "NOT_ENTAILED"
        disagreement = True
        pre = dict(pre)
        pre["signal"] = "NO_OVERLAP_JUDGE_ENTAILED_OVERRIDE"
        pre["reason"] = ("judge 判 ENTAILED，但证据与断言仅 %s 重合 → 按 NOT_ENTAILED "
                         "处理（引用洗白防线）" % lex["strength"])
    # 安全兜底：judge 说「证据不足」但**没有任何实质重合**（E0/E1）时，
    # 对 substantive 原子必须判 NOT_ENTAILED —— 否则「证据不足」会滑过 reject 集合
    if final == "INSUFFICIENT_CONTEXT" and _is_substantive(atom) and \
            lex["strength"] in ("E0_NONE", "E1_LEXICAL"):
        final = "NOT_ENTAILED"
        pre = dict(pre)
        pre["signal"] = "NO_OVERLAP_INSUFFICIENT_OVERRIDE"
        pre["reason"] = ("judge 判 INSUFFICIENT_CONTEXT，但证据与断言仅有 %s 重合 → "
                         "按 NOT_ENTAILED 处理（substantive 断言必须被实质支持）"
                         % lex["strength"])
    if final == "PARTIALLY_ENTAILED" and strength and \
            _STRENGTH_RANK.get(strength, 0) > _STRENGTH_RANK["E3_SUBSTANTIVE"]:
        strength = "E3_SUBSTANTIVE"
    return {
        "atom_id": atom.get("atom_id"), "parent_claim_id": atom.get("parent_claim_id"),
        "status": final, "strength": strength,
        "deterministic_signal": {"status": det_status, "reason": pre.get("reason"),
                                 "signal": pre.get("signal")},
        "lexical_signal": lex,
        "llm_judgment": llm or None,
        "disagreement": disagreement,
        "reason": pre.get("reason") or (llm or {}).get("reason"),
        "evidence_refs": (llm or {}).get("evidence_refs") or
                         list(atom.get("evidence_ids") or []),
        "supported_scope": (llm or {}).get("supported_scope"),
        "unsupported_scope": (llm or {}).get("unsupported_scope"),
    }


def validate_claim(claim, contract, judge=None, question=None):
    atoms = atomize_claim(claim, contract)
    # 批量 judge：一次调用判定该 claim 的所有**未决**原子（省钱；也避免同 claim 内不一致）
    llm_map = {}
    if judge is not None:
        undecided = []
        for a in atoms:
            if deterministic_precheck(a, contract)["status"] != "UNDETERMINED":
                continue
            if lexical_signal(a, contract).get("exact_containment"):
                continue
            undecided.append(a)
        if undecided:
            llm_map = judge.judge(undecided, contract, question)
    verdicts = [validate_atom(a, contract, judge=judge, question=question,
                              llm_pre=llm_map) for a in atoms]
    # claim 级结论（§14/§23）：
    #   * 全部原子被蕴含                → ENTAILED（多原子 = composite）
    #   * 一部分被蕴含、一部分不被蕴含   → PARTIALLY_ENTAILED（触发 repair，而不是直接 reject）
    #   * 没有任何原子被蕴含            → NOT_ENTAILED
    #   * 出现矛盾 / 来源角色不符        → 直接取该状态
    statuses = [v["status"] for v in verdicts]
    if any(s == "CONTRADICTED" for s in statuses):
        status = "CONTRADICTED"
    elif any(s == "SOURCE_ROLE_MISMATCH" for s in statuses):
        status = "SOURCE_ROLE_MISMATCH"
    elif all(s == "ENTAILED" for s in statuses):
        status = "ENTAILED"
    elif any(s == "ENTAILED" for s in statuses):
        status = "PARTIALLY_ENTAILED"
    elif any(s == "PARTIALLY_ENTAILED" for s in statuses):
        status = "PARTIALLY_ENTAILED"
    elif any(s == "NOT_ENTAILED" for s in statuses):
        status = "NOT_ENTAILED"
    else:
        status = statuses[0] if statuses else "INSUFFICIENT_CONTEXT"
    strengths = [v["strength"] for v in verdicts if v["strength"]]
    strength = min(strengths, key=lambda s: _STRENGTH_RANK.get(s, 0)) if strengths else "E0_NONE"
    return {
        "claim_id": claim.get("claim_id"), "claim_type": claim.get("claim_type"),
        "atoms": verdicts, "status": status, "strength": strength,
        "composite": len(verdicts) > 1,
        "composite_kind": ("SINGLE_EVIDENCE_ENTAILMENT"
                           if len({e for v in verdicts for e in
                                   (v.get("evidence_refs") or [])}) <= 1
                           else "COMPOSITE_ENTAILMENT"),
        "disagreement": any(v["disagreement"] for v in verdicts),
        "reject": status in REJECTION_STATUSES,
    }


__all__ = ["SCHEMA", "ENTAILMENT_STATUS", "ENTAILMENT_STRENGTH", "QUOTE_STATUS",
           "REJECTION_STATUSES", "SUBSTANTIVE_CLAIM_TYPES", "JUDGE_SYSTEM",
           "JUDGE_SCHEMA", "EntailmentJudge", "atomize_claim", "validate_quote",
           "sanitize_claims", "deterministic_precheck", "lexical_signal",
           "validate_atom", "validate_claim", "judge_prompt"]
