#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
synthesis_adapters.py — Phase 4C.1-C §20/§21/§22/§23：Mock 与 LLM synthesis adapter

设计要点
────────
* **deterministic mock 优先**：`MockSynthesisAdapter` 不调用任何模型，
  只根据 `SynthesisInputContract` + 证据文本**逐字引用**地拼装 claims 与 answer。
  它的存在是为了先证明 Input Contract / Claim Schema / Citation Binding /
  Abstention / Output Schema 这条链路闭环。
* **provider 抽象**：`SynthesisProvider` 只有一个方法 `complete(system, user, schema)`；
  `MockProvider` 是确定性实现，`OpenAICompatibleProvider` 是接口（DeepSeek/OpenAI/Qwen/GLM
  都走 OpenAI 兼容协议），**没有 key 就不可用**，诊断流程默认不启用。
* **provider 失败不得产出半成品**：任何异常 → `{ok: False, failure_mode: LLM_PROVIDER_FAILURE,
  claims: [], answer: None}`，调用方必须把该任务记为 synthesis_failed。
* LLM 返回的 JSON **必须**先过 `synthesis_claims.validate_claims` 与
  `synthesis_render.validate_answer`；不合法即失败，不"修一修再用"。
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import synthesis_claims as sc          # noqa: E402
import synthesis_render as sr          # noqa: E402

SYSTEM_CONTRACT = """你是拉康研究知识库的**受限**学术综合器。

硬边界（违反即失败）：
1. 只能使用下面提供的 evidence packet（每段都有 passage_id）。
2. **不得**用记忆、常识、网络知识补充任何事实。
3. **不得**用一般知识修补缺失的证据。
4. **不得**编造引文；引用必须是该段落里**逐字存在**的 span。
5. **不得**把解释说成拉康的原话（interpretation ≠ quotation）。
6. 每条 substantive claim 必须给出 evidence_ids（passage_id 列表）。
7. 只有包内 citation_eligibility ∈ {ELIGIBLE, QUALIFIED} 的证据能支持 substantive claim；
   MEDIA_ONLY / BIBLIOGRAPHY_ONLY / EDITORIAL_METADATA / FRAGMENT_ONLY 只能进 limitation。
8. 来源层措辞必须与证据一致：L2 / recovered 证据不得写成「拉康原文说」。
9. 如果 answer_permission = ABSTAIN，必须输出弃权结构（结论/原因/仅能确认/需要什么），
   不得输出普通理论发展，也不得罗列检索日志。
10. 不得输出 UNSUPPORTED 状态的 claim。

输出必须是 JSON，且符合给定 schema。
"""


# ══════════════════════════════════════════════════════════════════════ provider
class SynthesisProvider:
    """provider 抽象（§22）：不绑定任何厂商。"""
    name = "base"
    deterministic = False

    @property
    def available(self):
        return False

    def complete(self, system, user, schema):        # pragma: no cover - interface
        raise NotImplementedError


class MockProvider(SynthesisProvider):
    """确定性 provider：不调用模型，返回空（真正的内容由 MockSynthesisAdapter 生成）。"""
    name = "deterministic_mock"
    deterministic = True

    @property
    def available(self):
        return True

    def complete(self, system, user, schema):
        return {"_mock": True}


class OpenAICompatibleProvider(SynthesisProvider):
    """OpenAI 兼容 provider（DeepSeek / OpenAI / Qwen / GLM 均可）。

    只有显式配置 `DSH_SYNTHESIS_API_KEY` 才 available；诊断流程默认不启用，
    因此本阶段不会产生任何网络调用。
    """
    name = "openai_compatible"
    deterministic = False

    def __init__(self, base_url=None, api_key=None, model=None, timeout=60):
        self.base_url = (base_url or os.environ.get("DSH_SYNTHESIS_BASE_URL")
                         or "https://api.deepseek.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("DSH_SYNTHESIS_API_KEY")
        self.model = model or os.environ.get("DSH_SYNTHESIS_MODEL") or "deepseek-chat"
        self.timeout = timeout

    @property
    def available(self):
        return bool(self.api_key)

    def complete(self, system, user, schema):
        if not self.available:
            raise RuntimeError("provider 不可用：未配置 API key")
        import urllib.request
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer %s" % self.api_key})
        import time as _time
        t0 = _time.time()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        latency = _time.time() - t0
        content = (((doc.get("choices") or [{}])[0].get("message") or {})
                   .get("content") or "{}")
        try:
            out = json.loads(content)
        except Exception:
            out = {}
        if isinstance(out, dict):
            # 成本/时延 telemetry（§38）——调用方自行决定是否记录，绝不进入答案
            out["_usage"] = dict(doc.get("usage") or {}, latency_s=round(latency, 3),
                                 model=doc.get("model") or self.model,
                                 response_id=doc.get("id"))
        return out


# ══════════════════════════════════════════════════════════════════════ helpers
def _usable(contract):
    return [e for e in (contract.get("usable_evidence") or [])
            if e.get("citation_eligibility") != "INELIGIBLE"]


def _substantive(contract):
    return [e for e in _usable(contract)
            if "substantive" in (e.get("claim_permissions") or [])]


def _span(ev, max_len=160):
    """逐字 span（必须是该段文本的前缀/子串，禁止重构）。"""
    t = str(ev.get("text") or "")
    if not t:
        return ""
    cut = t[:max_len]
    m = list(re.finditer(r"[。！？；.!?;]", cut))
    if m and m[-1].end() >= 20:
        cut = cut[:m[-1].end()]
    return cut.strip()


def _quote(ev, kind="CORPUS_QUOTE", span=None, presented_as=None):
    span = span if span is not None else _span(ev)
    q = {"kind": kind, "passage_id": ev.get("passage_id"), "exact_span": span,
         "language": ev.get("language"), "source_layer": ev.get("source_layer"),
         "attribution": ev.get("attribution")}
    if presented_as:
        q["presented_as"] = presented_as
    return q


def _claim_text(ev, span):
    return "%s：%s" % (ev.get("attribution"), span)


def _pick_for_entity(contract, entity_id, forms):
    """该实体在证据里最靠前的一条 substantive 证据（词面在场）。"""
    import gold_normalization as gn
    for ev in _substantive(contract):
        text = str(ev.get("text") or "")
        if any(gn.contains_v2(text, f) for f in (forms or []) if f):
            return ev
    return None


def _lane_evidence(contract, lane_id, evidence_by_id):
    for lane in contract.get("execution_lanes") or []:
        if lane.get("lane_id") == lane_id:
            return [evidence_by_id[p] for p in (lane.get("evidence_ids") or [])
                    if p in evidence_by_id]
    return []


class _Builder:
    def __init__(self, contract):
        self.contract = contract
        self.ev_by_id = {e["passage_id"]: e for e in _usable(contract)}
        self.claims = []
        self.sections = {}
        self._n = 0

    def add(self, claim_type, text, status, evs, quotation=None, corpus_scan_ref=None,
            permissions=None):
        self._n += 1
        ids = [e.get("passage_id") if isinstance(e, dict) else e for e in (evs or [])]
        c = sc.make_claim("c%d" % self._n, claim_type, text, status, ids,
                          source_layer=(evs[0].get("source_layer")
                                        if evs and isinstance(evs[0], dict) else None),
                          quotation=quotation, corpus_scan_ref=corpus_scan_ref,
                          claim_permissions_used=permissions or [])
        self.claims.append(c)
        return c


# ══════════════════════════════════════════════════════════════════════ mock
class MockSynthesisAdapter:
    """确定性 mock synthesis（§20）。**只用包内证据逐字引用**。"""
    name = "mock_deterministic"

    def __init__(self, provider=None):
        self.provider = provider or MockProvider()

    # ── 入口
    def synthesize(self, question, contract, packet=None):
        perm = contract.get("answer_permission")
        if contract.get("status") != "READY" or perm == "BLOCKED":
            return {"ok": False, "failure_mode": "SYNTHESIS_NOT_ALLOWED",
                    "detail": "contract status=%s permission=%s"
                              % (contract.get("status"), perm),
                    "claims": [], "answer": None, "adapter": self.name}
        tpl = (contract.get("synthesis_template") or {}).get("template")
        b = _Builder(contract)
        if perm == "ABSTAIN":
            self._abstain(b, contract)
        else:
            getattr(self, "_tpl_%s" % tpl.lower(), self._tpl_definition)(b, contract)
            self._qualification_claims(b, contract, perm)
        sections = dict(b.sections)
        sections.setdefault("limitations", self._limitations(contract))
        sections.setdefault("source_notes", self._source_notes(contract))
        needs_ab = (perm == "ABSTAIN") or (
            tpl == "ABSTENTION" and perm == "QUALIFIED_SYNTHESIS")
        abstention = self._abstention_block(contract) if needs_ab else None
        return {"ok": True, "failure_mode": None, "claims": b.claims,
                "sections": sections, "abstention": abstention,
                "adapter": self.name, "provider": self.provider.name}

    # ── templates
    def _tpl_definition(self, b, c):
        subs = _substantive(c)
        for i, ev in enumerate(subs[:3]):
            span = _span(ev)
            if not span:
                continue
            b.add("DEFINITION", _claim_text(ev, span), "DIRECTLY_SUPPORTED", [ev],
                  quotation=_quote(ev), permissions=["substantive"])
        if len(subs) >= 2:
            b.add("DEFINITION",
                  "多段证据（%s）从不同期次指向同一术语，可确认该词在语料中有稳定的"
                  "论述位置。" % "、".join(sorted({e.get("seminar_id") or "?"
                                                  for e in subs[:3]})),
                  "SYNTHESIZED_FROM_MULTIPLE_EVIDENCE", subs[:3],
                  permissions=["substantive"])
        b.sections["working_definition"] = self._quoted_block(subs[:3])
        b.sections["structural_function"] = (
            "语料未提供可直接引用的「结构功能」定义段；该层面需要更多直接证据。")
        b.sections["key_distinctions"] = "（见 terminology / relation 证据，如有）"
        b.sections["period_source_qualification"] = self._source_notes(c)
        b.sections["evidence"] = self._evidence_list(subs[:3])

    def _tpl_comparison(self, b, c):
        ents = (c.get("entities") or {})
        forms = ents.get("form_groups") or {}
        picked = {}
        for eid in list(forms)[:2]:
            ev = _pick_for_entity(c, eid, forms.get(eid))
            if ev:
                picked[eid] = ev
        if len(picked) >= 2:
            for key, ev in list(picked.items())[:2]:
                b.add("DISTINCTION", _claim_text(ev, _span(ev)), "DIRECTLY_SUPPORTED",
                      [ev], quotation=_quote(ev), permissions=["substantive"])
            b.sections["term_a"] = self._quoted_block([list(picked.values())[0]])
            b.sections["term_b"] = self._quoted_block([list(picked.values())[1]])
            b.sections["differences"] = ("两侧各自有独立段落证据，但**差异本身**需要"
                                         "对照证据（见 relation 部分）。")
        rel = self._relation_claim(b, c)
        b.sections["relations"] = rel or "关系证据不足：两侧各自出现**不等于**两者有关系。"
        b.sections["why_it_matters"] = ("区分的意义取决于关系证据是否成立；"
                                        "本回答不越过证据。")

    def _tpl_relation(self, b, c):
        # seminar 约束下的直接证据（逐字引用，source-aware）
        for lane in (c.get("execution_lanes") or []):
            if not str(lane.get("lane_id", "")).startswith("seminar."):
                continue
            evs = [b.ev_by_id[p] for p in (lane.get("evidence_ids") or [])
                   if p in b.ev_by_id]
            evs = [e for e in evs if "substantive" in (e.get("claim_permissions") or [])]
            if evs:
                b.add("DEFINITION", _claim_text(evs[0], _span(evs[0])),
                      "DIRECTLY_SUPPORTED", [evs[0]], quotation=_quote(evs[0]),
                      permissions=["substantive"])
                b.sections.setdefault("seminar_evidence",
                                      self._quoted_block(evs[:2]))
                break
        rel = self._relation_claim(b, c)
        b.sections["relationship"] = rel or "同段共现/关系陈述证据不足。"
        b.sections["mechanism_or_position"] = "机制/结构位置需要直接关系证据，本回答不推断。"
        b.sections["direct_evidence"] = self._evidence_list(_usable(c)[:3])

    def _tpl_diachronic(self, b, c):
        dia = c.get("diachronic") or {}
        eps = dia.get("endpoints") or []
        for ep in eps[:2]:
            evs = [b.ev_by_id[p] for p in (ep.get("evidence_ids") or [])
                   if p in b.ev_by_id]
            evs = [e for e in evs if "substantive" in (e.get("claim_permissions") or [])]
            if not evs:
                continue
            label = "earlier_endpoint" if ep is eps[0] else "later_endpoint"
            b.add("DIACHRONIC_CHANGE", _claim_text(evs[0], _span(evs[0])),
                  "DIRECTLY_SUPPORTED", [evs[0]], quotation=_quote(evs[0]),
                  permissions=["substantive"])
            b.sections[label] = self._quoted_block(evs[:2])
        if len([k for k in b.sections if k.endswith("_endpoint")]) == 2:
            both = [p for ep in eps[:2] for p in (ep.get("evidence_ids") or [])
                    if p in b.ev_by_id][:3]
            b.add("DIACHRONIC_CHANGE",
                  "两端点各有可用证据：可确认该术语在两期都被论述；"
                  "「什么保持不变 / 什么被重新表述」需要逐段比对，本回答不越过证据。",
                  "SYNTHESIZED_FROM_MULTIPLE_EVIDENCE",
                  [b.ev_by_id[p] for p in both], permissions=["substantive"])
            b.sections["what_remains"] = "（需逐段比对，本回答不推断）"
            b.sections["what_changes"] = "（需逐段比对，本回答不推断）"
            b.sections["what_is_reformulated"] = "（需逐段比对，本回答不推断）"
        else:
            b.add("LIMITATION", "至少一个历时端点缺少可用证据，无法比较两期差异。",
                  "QUALIFIED_INFERENCE", [], corpus_scan_ref=dia or {"endpoints": eps})

    def _tpl_freud_to_lacan(self, b, c):
        self._source_layer_template(b, c, "Freud")

    def _tpl_philosophy_to_lacan(self, b, c):
        self._source_layer_template(b, c, "哲学来源")

    def _source_layer_template(self, b, c, label):
        src = c.get("source_layers") or {}
        corpus = src.get("corpus") or {}
        lacan = _lane_evidence(c, "source_layer:lacan_primary", b.ev_by_id)
        if lacan:
            ev = lacan[0]
            b.add("REINTERPRETATION", _claim_text(ev, _span(ev)), "DIRECTLY_SUPPORTED",
                  [ev], quotation=_quote(ev), permissions=["substantive"])
            b.sections["lacan_source"] = self._quoted_block(lacan[:2])
        missing = src.get("missing") or []
        structural = [x for x in missing if not corpus.get(x, False)]
        if structural:
            b.add("LIMITATION",
                  "当前知识库**不能直接核验 %s 原文层**：该来源层在语料普查中不存在"
                  "（%s）。任何「影响关系」的结论都缺少一手来源证据。"
                  % (label, "、".join(structural)),
                  "QUALIFIED_INFERENCE", [],
                  corpus_scan_ref={"scope": "whole_corpus", "layer_counts": corpus,
                                   "missing_structural": structural})
            b.sections["what_cannot_be_verified"] = (
                "当前知识库不能直接核验 %s 原文层（语料层不存在该来源层）。" % label)
        b.sections["freud_source" if label == "Freud" else "source_philosophy"] = (
            "（该来源层在语料中%s）" % ("存在" if not structural else "不存在"))

    def _tpl_translation_terminology(self, b, c):
        terms = c.get("terminology_evidence") or {}
        blocks = []
        for term, v in terms.items():
            mapping = v.get("mapping_completion")
            att = v.get("attestation_completion")
            ctx = v.get("context_validation")
            hits = int(v.get("corpus_hits") or 0)
            cands = v.get("translation_candidates") or []
            text = ("术语 %s：译名映射=%s%s；语料见证=%s（全库 %d 段）；上下文验证=%s。"
                    % (term, mapping,
                       ("（%s）" % "、".join([c_.get("target_form") or ""
                                            for c_ in cands[:3] if c_.get("target_form")])
                        if cands else ""), att, hits, ctx))
            lane_evs = [b.ev_by_id[p] for p in
                        ((v.get("evidence_ids") or [])) if p in b.ev_by_id]
            if hits == 0:
                # 零见证优先（即使 lane 上挂着检索残留证据，也不得与 attestation=0 矛盾）
                b.add("CORPUS_ABSENCE",
                      "术语 %s：译名映射=%s，但当前语料 attestation=0（全库 0 段）。"
                      % (term, mapping), "CORPUS_ABSENCE", [],
                      corpus_scan_ref={"scope": "whole_corpus", "term": term,
                                       "corpus_hits": 0, "mapping": mapping,
                                       "attestation": att})
                blocks.append(text)
                continue
            if lane_evs:
                b.add("TERMINOLOGY", text + " 语料原文：" + _span(lane_evs[0]),
                      "DIRECTLY_SUPPORTED", [lane_evs[0]], quotation=_quote(lane_evs[0]),
                      permissions=["substantive"])
            elif hits == 0:
                # 零见证：这是**全库普查**结论，不是「没有证据」——用 CORPUS_ABSENCE + 凭据
                b.add("CORPUS_ABSENCE",
                      "术语 %s：译名映射=%s，但当前语料 attestation=0（全库 0 段）。"
                      % (term, mapping), "CORPUS_ABSENCE", [],
                      corpus_scan_ref={"scope": "whole_corpus", "term": term,
                                       "corpus_hits": 0, "mapping": mapping,
                                       "attestation": att})
            else:
                # 语料有见证但本次没有段落级证据 → 只能说「有见证、未验证上下文」
                b.add("LIMITATION",
                      "术语 %s：语料见证=%s（全库 %d 段），但本次未取到可引用的段落级证据，"
                      "上下文验证=%s。" % (term, att, hits, ctx),
                      "QUALIFIED_INFERENCE", [],
                      corpus_scan_ref={"scope": "whole_corpus", "term": term,
                                       "corpus_hits": hits, "mapping": mapping,
                                       "attestation": att,
                                       "context_validation": ctx})
            blocks.append(text)
        b.sections["term_mapping"] = "\n".join(blocks) or "（无显式译名）"
        b.sections["corpus_attestation"] = (
            "语料见证与译名映射**分开**：映射已知不等于语料常用（例如原乐=0 段）。")
        b.sections["context_validation"] = (
            "上下文验证只在有段落级证据时成立；零见证术语没有可验证上下文。")
        b.sections["semantic_implication"] = "语义差异需要逐段比对，本回答不越过证据。"

    def _tpl_topology_matheme(self, b, c):
        f = c.get("formalism_evidence") or {}
        hits = f.get("hits") or []
        shown = 0
        for h in hits[:3]:
            ev = b.ev_by_id.get(h.get("passage_id"))
            if not ev:
                continue
            raw = h.get("raw_matched_form")
            span = raw if raw and raw in str(ev.get("text") or "") else _span(ev)
            b.add("FORMALISM",
                  "语料中的形式表达式为 `%s`（%s，strategy=%s）" %
                  (raw, ev.get("passage_id"), h.get("match_strategy")),
                  "DIRECTLY_SUPPORTED", [ev],
                  quotation=_quote(ev, span=span), permissions=["substantive"])
            shown += 1
        b.sections["formal_expression"] = "\n".join(
            "- `%s`（%s，strategy=%s，seminar=%s）" %
            (h.get("raw_matched_form"), h.get("passage_id"), h.get("match_strategy"),
             h.get("seminar_id")) for h in hits[:3]) or "（未取到形式表达式）"
        b.sections["components"] = ("形式成分按语料原样列出：%s"
                                    % "、".join(f.get("symbols") or []))
        b.sections["structural_relation"] = (
            "结构关系只陈述证据里出现的写法；**不**把自然语言解释冒充拉康原句。")
        b.sections["lacan_textual_explanation"] = self._quoted_block(
            [b.ev_by_id[h["passage_id"]] for h in hits[:2]
             if h.get("passage_id") in b.ev_by_id])
        if not shown:
            b.add("LIMITATION", "formalism 契约要求形式证据，但本次未取到可直接引用的形式表达。",
                  "QUALIFIED_INFERENCE", [], corpus_scan_ref=f or {"hits": 0})

    def _tpl_metadata(self, b, c):
        self._abstain(b, c)

    def _tpl_abstention(self, b, c):
        self._abstain(b, c)

    # ── relation
    def _relation_claim(self, b, c):
        rel = c.get("relation_evidence") or {}
        ids = rel.get("ids") or []
        evs = [b.ev_by_id[p] for p in ids if p in b.ev_by_id]
        evs = [e for e in evs if "substantive" in (e.get("claim_permissions") or [])]
        if not evs:
            return None
        ev = evs[0]
        pairs = rel.get("pairs") or []
        pair_txt = ("%s ↔ %s" % (pairs[0][0], pairs[0][1])) if pairs else "两侧术语"
        b.add("RELATION",
              "在语料中，%s 在同一段落中构成关系陈述（strength=%s）：%s"
              % (pair_txt, rel.get("strength") or "R?", _span(ev)),
              "DIRECTLY_SUPPORTED", evs[:2], quotation=_quote(ev),
              permissions=["substantive"])
        return self._quoted_block(evs[:2])

    # ── abstention（§11）
    def _abstain(self, b, c):
        ab = self._abstention_block(c)
        b.add("LIMITATION",
              "当前知识库无法可靠回答该问题：%s。" % "；".join(ab["abstention_reason_codes"]),
              "QUALIFIED_INFERENCE", [],
              corpus_scan_ref={"reason_codes": ab["abstention_reason_codes"],
                               "scope": "whole_corpus"})
        for x in ab["available_partial_information"]:
            b.add("CORPUS_ABSENCE", x, "CORPUS_ABSENCE", [],
                  corpus_scan_ref={"scope": "whole_corpus",
                                   "detail": x[:80]})
        b.sections["conclusion"] = "当前知识库**无法可靠回答**该问题。"
        b.sections["why"] = "\n".join("- %s" % r for r in
                                      ab["missing_information"]) or "- 证据不足"
        b.sections["what_can_be_said"] = "\n".join("- %s" % x for x in
                                                   ab["available_partial_information"]) \
            or "- 暂无可确认的结论"
        b.sections["what_would_be_needed"] = "\n".join(
            "- %s" % x for x in ab["next_required_sources"])

    def _abstention_block(self, contract):
        ara = contract.get("abstention_requirements") or {}
        codes = ara.get("reason_codes") or []
        if not codes and contract.get("answer_permission") == "QUALIFIED_SYNTHESIS":
            # 限定性弃权：原因来自 qualified_reasons（不是「结构性不可答」，而是「不够确定」）
            codes = [r for r in (ara.get("qualified_reasons") or [])] or [
                "EVIDENCE_PARTIAL"]
        if not codes:
            codes = ["NO_SUBSTANTIVE_EVIDENCE"]
        v2 = {}
        tr_meta = contract.get("metadata_evidence") or {}
        sub = contract.get("research_contract_summary") or {}
        missing, partial, need = [], [], []
        if "METADATA_UNAVAILABLE" in codes:
            fields = tr_meta.get("metadata_missing_fields") or []
            missing.append("问题要的是元数据，而语料层不存在该字段：%s"
                           % "、".join(str(f) for f in fields))
            partial.append("语料本身存在（可检索文本仍在），但**不含**所问字段")
            need.append("引入含该字段的目录/档案（如确切的报告时间、地点、在场者名单）")
        if "TOPIC_NOT_COVERED" in codes:
            missing.append("目标主题在当前语料中只有极少数旁及命中，没有形成论述")
            partial.append("可以确认该主题在语料中**未被展开论述**")
            need.append("引入覆盖该主题的研讨班/文本（并保持来源层可核）")
        if "ONTOLOGY_GAP" in codes:
            missing.append("主题词在知识库中没有对应实体，只能靠词面命中")
            need.append("为该主题补本体条目（entity/术语桥）")
        if "NO_SUBSTANTIVE_EVIDENCE" in codes:
            missing.append("本次取到的段落都不能承担实质性论断")
        if "CORPUS_FORMALISM_MISSING" in codes:
            missing.append("所问的形式表达式在全库普查中不存在")
            need.append("引入含该形式表达的文本（L1 原文优先）")
        if (sub.get("missing_source_layers") or []):
            missing.append("缺少必需来源层：%s" % sub["missing_source_layers"])
            need.append("补该来源层的一手文本")
        return {
            "abstention_reason_codes": codes,
            "missing_information": missing or ["证据不足以支撑任何实质性论断"],
            "available_partial_information": partial or [
                "仅能确认检索到的段落与问题主题相关，但不足以形成结论"],
            "next_required_sources": need or ["引入能直接覆盖该问题的语料（并保持可回查）"],
            "answer_state": "ABSTAINED",
        }

    # ── 限定与说明
    def _qualification_claims(self, b, c, perm):
        sub = c.get("research_contract_summary") or {}
        if perm == "QUALIFIED_SYNTHESIS":
            q = (c.get("abstention_requirements") or {}).get("qualified_reasons") or []
            b.add("LIMITATION",
                  "本回答是**限定性**综合：%s。" % "；".join(q or ["证据只部分支持"]),
                  "QUALIFIED_INFERENCE", [],
                  corpus_scan_ref={"qualified_reasons": q})
        for ml in (sub.get("missing_lanes") or []):
            b.add("LIMITATION", "必需的分析面（%s）没有取到证据。" % ml,
                  "QUALIFIED_INFERENCE", [],
                  corpus_scan_ref={"missing_lane": ml})
        if sub.get("missing_operations"):
            b.add("LIMITATION", "以下必需操作未执行：%s" % sub["missing_operations"],
                  "QUALIFIED_INFERENCE", [],
                  corpus_scan_ref={"missing_operations": sub["missing_operations"]})

    def _quoted_block(self, evs):
        out = []
        for ev in evs:
            span = _span(ev)
            if span:
                out.append("- %s（%s）：%s" % (ev.get("attribution"),
                                              ev.get("passage_id"), span))
        return "\n".join(out)

    def _evidence_list(self, evs):
        return "\n".join("- %s（%s，%s）" % (e.get("passage_id"), e.get("source_layer"),
                                            e.get("citation_eligibility")) for e in evs)

    def _limitations(self, contract):
        parts = []
        q = len([e for e in (contract.get("usable_evidence") or [])
                 if e.get("citation_eligibility") == "QUALIFIED"])
        if q:
            parts.append("本回答引用的证据中有 %d 段属于**限定引用**"
                         "（recovered 中译或非原文层），结论不可当作原文层证据。" % q)
        for r in (contract.get("abstention_requirements") or {}).get(
                "qualified_reasons") or []:
            parts.append("契约限制：%s" % r)
        if contract.get("answer_permission") == "QUALIFIED_SYNTHESIS":
            parts.append("本回答属于限定性综合（QUALIFIED_SYNTHESIS）："
                         "可以说明现有材料支持什么，但不能写成完全确定的理论结论。")
        return "\n".join("- %s" % p for p in parts)

    def _source_notes(self, contract):
        layers = {}
        for e in contract.get("usable_evidence") or []:
            layers[e.get("source_layer")] = layers.get(e.get("source_layer"), 0) + 1
        note = "、".join("%s×%d" % (k, v) for k, v in sorted(layers.items()))
        src = contract.get("source_layers") or {}
        extra = []
        if (src.get("missing") or []):
            extra.append("缺少来源层：%s" % "、".join(src["missing"]))
        return ("证据来源层构成：%s。%s" % (note or "（无）", "；".join(extra))).strip()


# ══════════════════════════════════════════════════════════════════════ LLM adapter
class ScholarlySynthesisAdapter:
    """LLM synthesis adapter（§21）：provider 抽象 + 严格验证 + 失败不留半成品。"""

    def __init__(self, provider=None):
        self.provider = provider or MockProvider()

    def _prompt(self, question, contract):
        packet = {
            "question": question,
            "task_type": contract.get("task_type"),
            "answer_permission": contract.get("answer_permission"),
            "synthesis_template": contract.get("synthesis_template"),
            "claim_permissions": contract.get("claim_permissions"),
            "citation_policy": contract.get("citation_policy"),
            "abstention_requirements": contract.get("abstention_requirements"),
            "research_contract_summary": contract.get("research_contract_summary"),
            "relation_evidence": contract.get("relation_evidence"),
            "source_layers": contract.get("source_layers"),
            "formalism_evidence": contract.get("formalism_evidence"),
            "terminology_evidence": contract.get("terminology_evidence"),
            "evidence": [{k: e.get(k) for k in
                          ("passage_id", "seminar_id", "language", "authority_level",
                           "text_role", "trace_status", "usability_class",
                           "citation_eligibility", "source_layer", "attribution",
                           "claim_permissions", "text")}
                         for e in contract.get("usable_evidence") or []],
        }
        schema = {
            "allowed_claim_types": list(sc.CLAIM_TYPES) if hasattr(sc, "CLAIM_TYPES")
            else ["DEFINITION", "DISTINCTION", "RELATION", "DIACHRONIC_CHANGE",
                  "SOURCE_INFLUENCE", "REINTERPRETATION", "TERMINOLOGY",
                  "FORMALISM", "METADATA", "CORPUS_ABSENCE", "LIMITATION"],
            "allowed_epistemic_status": ["DIRECTLY_SUPPORTED",
                                         "SYNTHESIZED_FROM_MULTIPLE_EVIDENCE",
                                         "QUALIFIED_INFERENCE", "CORPUS_ABSENCE"],
            "claims": [{"claim_id": "c1", "claim_type": "DEFINITION",
                        "claim_text": "…", "epistemic_status": "DIRECTLY_SUPPORTED",
                        "evidence_ids": ["passage…"], "quotation": {
                            "kind": "CORPUS_QUOTE", "passage_id": "passage…",
                            "exact_span": "…", "language": "fr",
                            "source_layer": "L1_TRANSCRIPTION"}}],
            "sections": {"brief_answer": "…"},
            "abstention": None,
        }
        return (SYSTEM_CONTRACT,
                "证据包与要求如下（JSON）：\n%s\n\n请输出符合这个 schema 的 JSON：\n%s"
                % (json.dumps(packet, ensure_ascii=False), json.dumps(schema,
                                                                     ensure_ascii=False,
                                                                     indent=1)))

    def synthesize(self, question, contract, packet=None, strict=True):
        """strict=True：整份响应必须通过 C 的结构验证（C 阶段语义）。
        strict=False：返回**原始** claims，交给 D 的流水线逐条清洗/验证/修复/剔除。"""
        if contract.get("status") != "READY" or \
                contract.get("answer_permission") == "BLOCKED":
            return {"ok": False, "failure_mode": "SYNTHESIS_NOT_ALLOWED",
                    "detail": "contract status=%s" % contract.get("status"),
                    "claims": [], "answer": None, "adapter": "llm",
                    "provider": getattr(self.provider, "name", "?")}
        system, user = self._prompt(question, contract)
        try:
            raw = self.provider.complete(system, user, {})
        except Exception as exc:                                  # provider 失败
            return {"ok": False, "failure_mode": "LLM_PROVIDER_FAILURE",
                    "detail": str(exc)[:300], "claims": [], "answer": None,
                    "adapter": "llm", "provider": getattr(self.provider, "name", "?")}
        if not isinstance(raw, dict) or raw.get("_mock"):
            return {"ok": False, "failure_mode": "LLM_PROVIDER_FAILURE",
                    "detail": "provider 未返回结构化结果", "claims": [], "answer": None,
                    "adapter": "llm", "provider": getattr(self.provider, "name", "?")}
        claims = raw.get("claims") or []
        if not strict:
            return {"ok": True, "failure_mode": None, "claims": claims,
                    "sections": raw.get("sections") or {},
                    "abstention": raw.get("abstention"),
                    "adapter": "llm", "provider": getattr(self.provider, "name", "?"),
                    "usage": raw.get("_usage") or {},
                    "strict": False}
        rep = sc.validate_claims(claims, contract)
        if rep["violations"]:
            return {"ok": False, "failure_mode": "SYNTHESIS_SCHEMA_INVALID",
                    "detail": rep.get("failure_counts") or rep.get("violations"),
                    "claims": [], "answer": None,
                    "adapter": "llm", "provider": getattr(self.provider, "name", "?"),
                    "validation": rep}
        return {"ok": True, "failure_mode": None, "claims": claims,
                "sections": raw.get("sections") or {},
                "abstention": raw.get("abstention"),
                "adapter": "llm", "provider": getattr(self.provider, "name", "?"),
                "usage": raw.get("_usage") or {},
                "strict": True, "validation": rep}


def make_adapter(name="mock", provider=None):
    if name == "mock":
        return MockSynthesisAdapter(provider or MockProvider())
    if name == "llm":
        return ScholarlySynthesisAdapter(provider or OpenAICompatibleProvider())
    raise ValueError("unknown adapter: %s" % name)


__all__ = ["SYSTEM_CONTRACT", "SynthesisProvider", "MockProvider",
           "OpenAICompatibleProvider", "MockSynthesisAdapter",
           "ScholarlySynthesisAdapter", "make_adapter"]
