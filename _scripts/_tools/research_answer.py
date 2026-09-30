#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research_answer.py — Phase 4B：**研究循环 + 回答组装 + claim/citation 模型**

它与 Phase 4A `research_agent` 的分工
─────────────────────────────────────
```
research_agent.research(q)   → 证据包 + trace（**不写答案**）      ← Phase 4A，契约不变
research_answer.run_task(pt) → 计划 + 证据包 + **回答** + claim 表  ← Phase 4B（本模块）
```
Phase 4A 的 `research()` 仍然不写答案（它的 `agent_note` 这么说，测试也这么断言）；
Phase 4B 在它**之上**加一层，负责把证据组织成可读回答。

本模块不重新实现检索：一切都走 `knowledge_api`（MCP 那一套）。

三条硬纪律
──────────
1. **不发明来源**（§24）：回答里的每条 substantive claim 要么挂着**真实 passage_id**，
   要么被显式归类为 `AGENT_SYNTHESIS` / `UNSUPPORTED`。没有第三条路。
2. **不保存隐藏推理**（§8）：计划是结构化的（research_goal / entities / subquestions /
   planned_operations），trace 只记工具、参数、结果 id、状态迁移、取舍的证据。
3. **不把 candidate ontology 说成已定论**（§17）：用到 v4a1 实体时，
   claim 里必须带上 `ontology_review_status: candidate`。

回答结构（§9，按问题类型自适应，但层次不省）
────────────────────────────────────────────
    brief_answer · theoretical_development · diachronic_differences
    key_primary_evidence · interpretation_layers · evidence_limitations

claim 分类（§11）
─────────────────
    PRIMARY_EVIDENCE · SECONDARY_INTERPRETATION · AGENT_SYNTHESIS
    CONTEXTUAL_INFERENCE · UNSUPPORTED
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

_APOS_R = re.compile(r"['’`]")
_NONWORD_R = re.compile(r"[^\w\s]", re.UNICODE)

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
MCP = os.path.join(HERE, "lacan_mcp")
sys.path.insert(0, HERE)
sys.path.insert(0, MCP)

import research_agent as ra          # noqa: E402
import knowledge_api as api          # noqa: E402
import ontology_v4a1 as onto         # noqa: E402
import evidence_sufficiency_v2 as esv2   # noqa: E402  （Phase 4C：分层判定，权威）
import research_contract as rcontract    # noqa: E402  （Phase 4C.1-B：可执行契约）
import research_execution as rexec       # noqa: E402  （Phase 4C.1-B2：执行调度器）
import evidence_sufficiency_v21 as esv21  # noqa: E402 （Phase 4C.1-B：任务完成层）
import citations as cit              # noqa: E402

CLAIM_CLASSES = ("PRIMARY_EVIDENCE", "SECONDARY_INTERPRETATION", "AGENT_SYNTHESIS",
                 "CONTEXTUAL_INFERENCE", "UNSUPPORTED")
PRIMARY_LEVELS = ("L1",)
SECONDARY_LEVELS = ("L2", "L3")

# 每个任务类型需要哪些能力（用于选研究操作；不硬编码某一条流程）
OPERATIONS_BY_CAPABILITY = {
    "period_coverage": "trace_concept",
    "diachronic_grouping": "trace_concept",
    "separate_lanes": "compare_concepts",
    "distinction_preservation": "compare_concepts",
    "terminology_mapping": "terminology_lookup",
    "context_aware_resolution": "resolve_entity",
    "case_evidence": "find_concept_evidence",
    "topology_evidence": "find_concept_evidence",
    "matheme_evidence": "find_concept_evidence",
    "source_trace": "trace_source",
    "entity_resolution": "resolve_entity",
    "cross_language": "search_passages",
    "seminar_constraint": "search_passages",
    "abstention": "search_passages",
    "source_layer_separation": "find_concept_evidence",
    "multi_lane": "compare_concepts",
}


def _squash(s):
    """**anchor 匹配**用的归一化：去标点、去空白（与 gold 推导同一套规则）。

    为什么必须去空白/标点：语料里同一个术语写作 `objet petit(a)`、
    `objet petit a`、`plus-de-jouir`、`plus de jouir` —— 按字面匹配会漏掉大半。
    这是**术语级**匹配，不是语义蕴含。
    """
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = _APOS_R.sub("", s)
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", "", _NONWORD_R.sub("", s)).lower()


def usable_terms(plan_or_task, limit=4):
    """**可用于检索/计数的术语**：丢掉句子级片段（与 ontology_gaps.is_valid_term 同判据）。

    实测教训：`在拉康教学中的角色经历了` 这种 12+ 字的句子片段被当成术语后，
    带 seminar 约束的检索会因为整串都不命中而返回空 —— 于是「补期 lane」静默失效。
    """
    out = []
    for t in (plan_or_task.get("salient_terms") or []):
        t = str(t)
        if not t or len(t) < 2:
            continue
        cjk = len(re.findall(r"[\u4e00-\u9fff]", t))
        # 8 字以上几乎不是术语（"在拉康教学中的角色经历了" 这种句子片段就是这么漏进来的）
        if cjk > 8 or len(t.split()) > 3:
            continue
        if t not in out:
            out.append(t)
    return out[:limit]


def _tokens(s):
    """归一化后按**词边界**取 ≥3 字符的实词（保留空格，别用 squash 之后的串）。"""
    t = unicodedata.normalize("NFKC", str(s or ""))
    t = _APOS_R.sub(" ", t)
    t = "".join(c for c in unicodedata.normalize("NFD", t)
                if unicodedata.category(c) != "Mn")
    return {w for w in re.findall(r"[a-z0-9]{3,}", t.lower())}


def _sem(sem):
    """`seminar.S14` → `S14`（第一版写成 replace("seminar.","S") → "SS14"）。"""
    return str(sem or "").replace("seminar.", "")


def _anchor_match(raw, anchors):
    """→ (strong, weak)：两种**术语级**代理，都不是语义蕴含。

    * strong：把 anchor 与段落都去掉标点/空白/变音后做子串匹配
      （`objet petit a` 能命中 `objet petit(a)`）。
    * weak：**词袋包含** —— anchor 的实词（≥3 字符）是否都在段落里出现。
      语料常把 objet 与 petit a 分开写（`l'objet dit par moi petit a`、
      `mon « objet » dit petit (a)`），strong 会漏掉这些真实证据，
      所以另记一个更弱、但覆盖面更广的代理。

    两个数都报出来；**都不等于「该段支持该 claim」** —— 真正的 entailment
    需要人工评审（§23）。
    """
    sq = _squash(raw)
    toks = _tokens(raw)          # 保留词边界：词袋包含要靠它
    strong = weak = False
    for a in anchors:
        sa = _squash(a)
        if sa and sa in sq:
            strong = weak = True
            break
        atoks = _tokens(a)          # set
        if len(atoks) >= 2 and all(t in toks for t in atoks):
            weak = True
        elif len(atoks) == 1 and next(iter(atoks)) in toks:
            weak = True
    return strong, weak


def anchor_pool(plan):
    """anchor 词池：**已解析实体自己的写法**（来自知识库，不是从问题里瞎猜）。

    第一版直接拿问题的显著词当 anchor，于是「拉康所谓的」「到底」这类片段
    也成了 anchor，citation_anchor_support_rate 被无意义地压低（实测 0.52）。
    """
    forms = []
    for e in plan.get("entities") or []:
        for eid in e.get("entities") or []:
            ent = onto.entity(eid)
            if ent:
                forms += [ent.get("fr"), ent.get("en"), ent.get("zh")]
                forms += list(ent.get("aliases") or [])
            g = onto.gold_concept(eid)
            if g:
                forms += [g.get("fr"), g.get("en"), g.get("zh")]
                forms += list(g.get("aliases") or [])
    out = []
    for f in forms:
        if f and len(str(f)) >= 2 and f not in out:
            out.append(str(f))
    return out[:24]


# ─────────────────────────────────────────────── 计划（结构化，非 CoT）

def _inner_content_candidates(fragment):
    """从一个问句残片里取出**可能是词条**的内容词候选（确定性、无模型）。

    只做两件事：① 中文 2–4 字连续子串；② 拉丁字母词。候选仍需 `resolve_entity`
    真的解析出实体才会进入计划 —— 所以这里宁可多给几个候选，也不猜语义。
    """
    frag = str(fragment or "")
    out = []
    for n in (4, 3, 2):
        for i in range(0, max(0, len(frag) - n + 1)):
            sub = frag[i:i + n]
            if not re.fullmatch(r"[\u4e00-\u9fff]{%d}" % n, sub):
                continue
            if rcontract.is_question_fragment(sub):
                continue
            # 中间/两端带虚词或动词的 n-gram 不是词条（`的欲望`、`拉康的欲`、`进入拉康`）
            if re.search(r"[的了吗着呢是在与和及或等里中内上下前后时进入把被从对]", sub):
                continue
            if sub not in out:
                out.append(sub)
    for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", frag):
        if w.lower() not in {x.lower() for x in out}:
            out.append(w)
    return out


def make_plan(public_task, budget=None):
    """→ 结构化研究计划。**不含**任何模型私有推理。

    计划由规则生成：能力 → 研究操作，实体 → 解析，语言 → lane 方向。
    """
    q = public_task["question"]
    caps = public_task.get("required_capabilities") or []
    terms = ra._salient_terms(q)
    resolutions = []
    # §18 硬规则：问句残片（`中文语料里`、`适合表示拉康的主体`…）不得进入实体解析。
    # ⚠️ 但残片里的**内容词**不能跟着一起丢：`进入拉康的欲望理论` 是残片，
    #    里面的「拉康 / 欲望」是真词条。做法是确定性地取 2–4 字子串候选，
    #    只保留**真的解析到实体**的那些（无实体 = 噪声，不入计划）。
    entity_terms = [t for t in terms if not rcontract.is_question_fragment(t)]
    seen_entity_sets = set()
    for t in terms:
        if not rcontract.is_question_fragment(t):
            continue
        for cand in _inner_content_candidates(t):
            if cand in entity_terms:
                continue
            try:
                r = api.resolve_entity(cand)
            except Exception:
                continue
            ents = tuple(sorted(c["entity_id"] for c in
                                (r.get("resolution") or {}).get("candidates") or []))
            if not ents or ents in seen_entity_sets:
                continue
            seen_entity_sets.add(ents)
            entity_terms.append(cand)
            if len(entity_terms) >= 6:
                break
        if len(entity_terms) >= 6:
            break
    for t in entity_terms[:6]:
        r = api.resolve_entity(t)
        resolutions.append({
            "term": t,
            "status": r["resolution"]["resolution_status"],
            "entities": [c["entity_id"] for c in r["resolution"]["candidates"]],
            "context_required": r["resolution"].get("context_required", False),
            "ontology_layer": r["resolution"].get("ontology_layer"),
        })
    ops = ["resolve_entity"]          # 任何研究都先解析实体（可复核的固定起点）
    for c in caps:
        op = OPERATIONS_BY_CAPABILITY.get(c)
        if op and op not in ops:
            ops.append(op)
    for op in ("find_concept_evidence", "search_passages", "get_context"):
        if op not in ops:
            ops.append(op)
    # 术语的全库命中数（结构性诊断；同时供稀疏性规则使用）
    import lacan_search
    term_counts = {}
    for tt in usable_terms({"salient_terms": terms}, 8):
        try:
            term_counts[tt] = len(lacan_search.lexical_search(tt, limit=50))
        except Exception:
            pass
    # 计划里说明「为什么选这些操作」——这是可复核的规则，不是推理
    return {
        "term_counts": term_counts,
        "research_goal": q,
        "anchor_pool": anchor_pool({"entities": resolutions}),
        "question_language": public_task.get("language"),
        "task_type": public_task.get("task_type"),
        "salient_terms": terms,
        "entities": resolutions,
        "subquestions": _subquestions(public_task),
        "planned_operations": ops,
        "operation_rationale": {op: [c for c in caps
                                     if OPERATIONS_BY_CAPABILITY.get(c) == op]
                                for op in ops},
        "budget": budget or ra.DEFAULT_BUDGET,
        "no_hidden_reasoning": True,
        "note": "计划是结构化的（目标/实体/子问题/操作）；不含任何模型私有推理。",
    }


def _subquestions(public_task):
    """按任务类型给出**结构性**子问题（不是理论判断）。"""
    tt = public_task.get("task_type")
    base = {
        "concept_definition": ["该概念在知识库里有实体吗？",
                               "直接原文证据是什么？",
                               "不同时期的定位是否不同？"],
        "concept_relation": ["A 与 B 在知识库里是不是两个独立实体？",
                             "各自的证据分别是什么？",
                             "它们之间的关系（若有）有无段号支持？"],
        "diachronic_development": ["早期证据在哪？", "中期证据在哪？", "晚期证据在哪？",
                                   "各期之间是发展还是矛盾？"],
        "seminar_specific": ["该期里相关术语出现了多少次？",
                             "术语约束下的证据是什么？",
                             "是否存在术语映射需要上下文？"],
        "case_research": ["个案文本出现在哪些期？", "它被用来支持什么理论位置？",
                          "原文陈述与解读如何分层？"],
        "freud_to_lacan": ["Freud 的术语与 Lacan 的术语各自在哪？",
                           "哪些是原话、哪些是重读？", "是否有跨语言证据？"],
        "philosophy_to_lacan": ["哲学来源在语料里出现多少？",
                                "Lacan 文本里的对应段落是哪些？",
                                "语料是否足以支持定论？"],
        "topology_matheme": ["拓扑/数学型术语的证据在哪？",
                             "是图示描述还是文字讨论？", "是否需要限定某一期？"],
        "translation_terminology": ["各译名在语料里的证据量是多少？",
                                    "是否存在受控映射？", "译名差异有无段号支持？"],
        "insufficient_unanswerable": ["语料里到底有没有相关材料？",
                                      "如果有，是否足以构成回答？"],
    }
    return base.get(tt, ["知识库能否支持这个问题？"])


# ─────────────────────────────────────────────── §13 证据充分性校准

# ⚠️ 只认**日级**日期（或 ISO 全日期）。第一版把裸年份也算进去，于是
#    「dans les années 1957-1960」这种**时期**问题被误判成「要确切日期」，
#    把某个时期问题从 SUPPORTED 降成 INSUFFICIENT —— 时期问题本库是能答的
#    （year_from/year_to 就是为此存在的）。
DATE_RE = re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}-\d{2}-\d{2}|"
                     r"\b\d{1,2}\s+(January|February|March|April|May|June|July|August|"
                     r"September|October|November|December)\b", re.I)
# 问「确切日期/时间」的措辞（必须同时出现，才构成结构性元数据缺口）
DATE_ASK_RE = re.compile(r"确切|准确|具体|几月几?日|哪一?天|哪日|什么时候|"
                         r"date|quand|exact", re.I)


def kb_has_session_dates():
    """知识库里到底有没有**确切日期** —— 这是结构事实，不是猜测。

    实测：canonical store 全部 passage 的 `session_date` 都是 unknown，
    语料只提供 `year_from`/`year_to`（见 sessions.jsonl / passages.jsonl）。
    """
    have = False
    for pid, m in list(api.KB_.meta().items())[:2000]:
        d = m.get("session_date")
        if d and d != "unknown":
            have = True
            break
    return have


def structural_capability_issues(question):
    """问题要求的东西，本库**结构上**是否可能提供？（→ [(code, message)]）"""
    out = []
    if DATE_RE.search(question) and DATE_ASK_RE.search(question) \
            and not kb_has_session_dates():
        out.append((
            "STRUCTURAL_METADATA_GAP",
            "问题要求**确切日期/时间**，而 canonical store 的所有 passage "
            "`session_date` 均为 unknown（语料只给 year_from/year_to）—— "
            "本库结构上无法回答该问题，证据再多也不构成支持。"))
    return out


def relevance_report(pack, question, pool=None):
    """**术语级**相关性：检索到的证据里有多少条包含「这个问题指向的东西」。

    ⚠️ 必须**跨语言**：中文问题的内容词不会出现在法文段落里 ——
    第一版只拿中文问题词去匹配，于是所有 zh→fr 任务的相关性都被算成 0
    （实测 relevance_rate_mean=0.25，还把时期问题误降级成 INSUFFICIENT）。
    所以匹配集合 = 已解析实体的**多语言写法**（anchor_pool） ∪ 问题内容词。
    """
    terms = [t for t in ra._salient_terms(question) if len(str(t)) >= 2]
    terms = list(dict.fromkeys(list(pool or []) + terms))
    ev = pack.get("evidence") or []
    hit = 0
    for e in ev:
        sq = _squash(e.get("text") or "")
        if any(_squash(t) and _squash(t) in sq for t in terms):
            hit += 1
    rate = (hit / len(ev)) if ev else None
    return {"terms": terms[:8], "evidence_n": len(ev), "matched_n": hit,
            "relevance_rate": rate,
            "method": "term_substring_after_punctuation_and_space_folding"}


SUPPORTED_MIN_RELEVANCE = 0.30


def corpus_sparsity_issue(question, plan):
    """语料**稀疏性**：问题指向的术语在全库只有极少命中时，声称「拉康如何看待 X」没有根据。

    这是可复核的结构事实（用词法索引数命中数），不是语义判断。
    实测一个弃权类任务：`frmi` 全库仅 3 段、`neuroscience(s)` 0 段 —— 3 处旁及提及
    不能支撑「拉康对 fMRI 的看法」这一研究操作。
    """
    import lacan_search
    counts = {}
    for t in usable_terms(plan, 8):
        try:
            counts[t] = len(lacan_search.lexical_search(t, limit=50))
        except Exception:
            continue
    if not counts:
        return None          # 没有可判定的术语 → 不做这条判断（不猜）
    best = max(counts.values())
    if best <= 3:
        rarest = sorted(counts.items(), key=lambda kv: kv[1])[:3]
        return ("CORPUS_SPARSITY",
                "问题指向的术语在全库命中极少（%s）——最相关的写法最多只有 %d 段证据，"
                "不足以支撑对该问题的实质性回答。"
                % (", ".join("%s=%d" % (k, v) for k, v in rarest), best))
    return None


def calibrate_state(pack, question, plan=None):
    """→ (state, reasons[], signals_addendum) —— 只做**规则式**降级，不升格。

    * 结构性能力缺口（如要确切日期）→ INSUFFICIENT_EVIDENCE
    * 术语级相关性过低 → 最多 PARTIALLY_SUPPORTED；为 0 → INSUFFICIENT_EVIDENCE
    """
    st = dict(pack.get("evidence_state") or {})
    state = st.get("state")
    reasons, add = [], {"relevance_rate": None, "structural_gaps": []}
    issues = structural_capability_issues(question)
    sparse = corpus_sparsity_issue(question, plan or {})
    if sparse:
        issues = list(issues) + [sparse]
    if issues:
        add["structural_gaps"] = [c for c, _ in issues]
        reasons += [m for _, m in issues]
        return "INSUFFICIENT_EVIDENCE", reasons, add
    rel = relevance_report(pack, question, (plan or {}).get("anchor_pool"))
    add["relevance_rate"] = rel["relevance_rate"]
    add["relevance_matched_n"] = rel["matched_n"]
    if rel["evidence_n"] and rel["relevance_rate"] is not None:
        if rel["relevance_rate"] == 0:
            reasons.append("检索到的 %d 条证据里，**没有一条**包含问题的内容词"
                           "（术语级相关性 = 0）→ 这些证据不构成对该问题的支持。"
                           % rel["evidence_n"])
            return "INSUFFICIENT_EVIDENCE", reasons, add
        if rel["relevance_rate"] < SUPPORTED_MIN_RELEVANCE and state == "SUPPORTED":
            reasons.append("只有 %.0f%% 的证据包含问题的内容词（阈值 %.0f%%）→ "
                           "降级为 PARTIALLY_SUPPORTED：宁可部分支持，也不要虚假完整。"
                           % (100 * rel["relevance_rate"],
                              100 * SUPPORTED_MIN_RELEVANCE))
            return "PARTIALLY_SUPPORTED", reasons, add
    return state, reasons, add


# ─────────────────────────────────────────────── trace（无隐藏推理）

class ResearchTrace:
    """§8/§25：只记工具、参数、结果 id、状态迁移、取舍的证据。"""

    def __init__(self, task_id):
        self.doc = {
            "schema_version": "research-trace-4b/v1",
            "task_id": task_id,
            "tool_calls": [],
            "entities_resolved": [],
            "retrieval_routes": [],
            "passages_seen": [],
            "passages_selected": [],
            "passages_rejected": [],
            "context_expansions": [],
            "source_traces": [],
            "state_transitions": [],
            "claims": [],
            "citations": [],
            "budget_usage": {},
            "warnings": [],
            "no_hidden_reasoning": True,
        }

    def tool(self, name, args, result, decision=None):
        ev = (result.get("evidence") or []) if isinstance(result, dict) else []
        ids = [e.get("passage_id") for e in ev]
        for pid in ids:
            if pid and pid not in self.doc["passages_seen"]:
                self.doc["passages_seen"].append(pid)
        rec = {"step": len(self.doc["tool_calls"]) + 1, "tool": name, "arguments": args,
               "result_ids": ids[:20], "evidence_n": len(ev),
               "state": ((result or {}).get("evidence_state") or {}).get("state"),
               "resolution_status": ((result or {}).get("resolution") or {}
                                     ).get("resolution_status"),
               "route": ((result or {}).get("retrieval") or {}).get("route"),
               "warnings": [w.get("code") for w in ((result or {}).get("warnings") or [])],
               "decision": decision}
        self.doc["tool_calls"].append(rec)
        if rec["state"]:
            self.doc["state_transitions"].append(
                {"step": rec["step"], "state": rec["state"]})
        if rec["route"]:
            self.doc["retrieval_routes"].append(rec["route"])
        # Phase 4C.1-B §13：`budget.used.context_expansions` 与 `trace.context_expansions`
        # 必须对得上（4C.1-A 的 Gate 19 正是抓到这个恒为空数组的旧缺陷）。
        if name == "get_context":
            self.doc["context_expansions"].append(
                {"step": rec["step"], "passage_id": (args or {}).get("passage_id"),
                 "before": (args or {}).get("before"), "after": (args or {}).get("after")})
        return rec

    def reject(self, pid, why):
        self.doc["passages_rejected"].append({"passage_id": pid, "reason": why})

    def select(self, pid):
        if pid not in self.doc["passages_selected"]:
            self.doc["passages_selected"].append(pid)


# ─────────────────────────────────────────────── claim 组装

def _claim(cid, text, cls, citations, anchor_terms, note=None, extra=None):
    c = {"claim_id": cid, "text": text, "classification": cls,
         "citations": list(citations), "anchor_terms": list(anchor_terms)}
    if note:
        c["note"] = note
    if extra:
        c.update(extra)
    return c


def _short(text, n=220):
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t if len(t) <= n else t[:n - 1] + "…"


def _lane_key(e):
    return (e.get("seminar_id"), e.get("language"), e.get("authority_level"))


def compose_answer(pack, plan=None):
    """把证据包组装成**可读的研究回答** + claim 表。

    ⚠️ 这里不写「拉康的意思是……」这类理论定论 —— 没有证据支持的句子不生成。
    生成的是：结构性事实（实体/时期/层级的分布）+ **逐字引用**（带段号）
    + 明确标注的综合判断（AGENT_SYNTHESIS）与限制。
    """
    claims = []
    pool = (plan or {}).get("anchor_pool") or []
    ev = pack.get("evidence") or []
    st = pack.get("evidence_state") or {}
    res = pack.get("resolution") or {}
    sections = {}

    # ── brief_answer：只陈述**证据状态**与可核事实，不冒充定论
    n = pack.get("evidence_n", len(ev))
    sem_n = len({e.get("seminar_id") for e in ev if e.get("seminar_id")})
    lang_n = pack.get("by_language") or {}
    state = st.get("state")
    brief = ("本次研究在知识库中取得 %d 条证据，覆盖 %d 个研讨班（语言分布：%s）；"
             "证据充分性判定为 **%s**。"
             % (n, sem_n, "、".join("%s×%d" % (k, v) for k, v in sorted(lang_n.items()))
                or "—", state))
    claims.append(_claim(
        "c-brief", brief, "CONTEXTUAL_INFERENCE",
        [e["passage_id"] for e in ev[:5]], [],
        note=("只陈述证据的数量/分布/状态判断，这些可由证据包直接复核。"
              "它是**元陈述**，因此不挂实体 anchor（挂了反而会把 "
              "anchor 支持率算错）。")))
    sections["brief_answer"] = brief

    # ── theoretical_development：按 lane（研讨班×语言×层级）分组 + 逐字引用
    dev = []
    groups = {}
    for e in ev:
        groups.setdefault(_lane_key(e), []).append(e)
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), str(kv[0])))
    for i, ((sem, lang, auth), items) in enumerate(ordered[:8], 1):
        head = ("**%s · %s · %s**（%d 条证据）" % (_sem(sem), lang, auth, len(items)))
        quotes = []
        for e in items[:2]:
            quotes.append("「%s」[%s]" % (_short(e.get("text"), 160),
                                         e.get("passage_id")))
        line = head + "：" + "；".join(quotes)
        dev.append(line)
        cls = ("PRIMARY_EVIDENCE" if auth in PRIMARY_LEVELS
               else "SECONDARY_INTERPRETATION" if auth in SECONDARY_LEVELS
               else "CONTEXTUAL_INFERENCE")
        claims.append(_claim(
            "c-dev-%d" % i,
            "在 %s 的 %s 证据里出现与该问题相关的表述（见所引段号）。"
            % (_sem(sem), auth),
            cls, [e["passage_id"] for e in items[:2]], pool[:3],
            note="逐字引用原始段落；判断句只限于「该段是该期/该层级的证据」。"))
    if not dev:
        dev = ["**没有取得任何证据** —— 因此不对该问题作任何理论陈述。"]
        claims.append(_claim("c-dev-none", dev[0], "CONTEXTUAL_INFERENCE", [],
                             [], note="无证据时的显式弃权句。"))
    sections["theoretical_development"] = "\n\n".join(dev)

    # ── diachronic_differences：只在真的跨期时出现
    by_sem = {}
    for e in ev:
        by_sem.setdefault(e.get("seminar_id"), []).append(e)
    periods = sorted({e.get("period") for e in ev if e.get("period")})
    if len(by_sem) >= 2 and len(periods) >= 2:
        lines = []
        for sem in sorted(by_sem, key=lambda s: str(s)):
            items = by_sem[sem]
            lines.append("- %s（%s）：%d 条；例：[%s]"
                         % (_sem(sem),
                            items[0].get("period"), len(items),
                            items[0]["passage_id"]))
        dia = ("证据分布在 **%d 个时期**（%s）与 %d 个研讨班：\n\n%s\n\n"
               "⚠️ 本层只呈现**分布**；「是发展还是转折」属解释判断，"
               "需要人读原文后确认。"
               % (len(periods), "、".join(periods), len(by_sem), "\n".join(lines)))
        claims.append(_claim(
            "c-dia", "证据跨 %d 个时期（%s）分布。" % (len(periods), "、".join(periods)),
            "CONTEXTUAL_INFERENCE",
            [e["passage_id"] for e in ev[:3]], [],
            note="时期边界取自 seminars.jsonl 的 year_from/year_to（不是猜测）。"))
        sections["diachronic_differences"] = dia

    # ── key_primary_evidence：法文 L1 原文优先列出
    primary = [e for e in ev if e.get("authority_level") in PRIMARY_LEVELS]
    if primary:
        lines = ["- `%s`（%s · %s）：%s"
                 % (e["passage_id"], _sem(e.get("seminar_id")),
                    e.get("language"), _short(e.get("text"), 200))
                 for e in primary[:5]]
        sections["key_primary_evidence"] = "\n".join(lines)
        claims.append(_claim(
            "c-primary", "知识库提供了 %d 条 L1（法文原文）证据，例如所列段号。"
            % len(primary), "PRIMARY_EVIDENCE",
            [e["passage_id"] for e in primary[:5]], pool[:3]))
    else:
        rec = [e for e in ev if e.get("trace_status") == "SOURCE_TRACE_INCOMPLETE"]
        sections["key_primary_evidence"] = (
            "**本次没有取到 L1 法文原文**；所有证据均为 L2/中文 recovered"
            "（%d 条带 SOURCE_TRACE_INCOMPLETE）。" % len(rec) if rec else
            "**本次没有取到 L1 法文原文**。")
        claims.append(_claim("c-primary-none", sections["key_primary_evidence"],
                             "CONTEXTUAL_INFERENCE", [], [],
                             note="禁止在没有 primary 证据时声称「拉康原文说」。"))

    # ── interpretation_layers：显式分层
    layers = {}
    for e in ev:
        layers[e.get("authority_level")] = layers.get(e.get("authority_level"), 0) + 1
    inc = [e for e in ev if e.get("trace_status") == "SOURCE_TRACE_INCOMPLETE"]
    onto_used = [c["entity_id"] for c in (res.get("candidates") or [])
                 if (c.get("ontology_layer") == onto.LAYER_ID)]
    lay = ["| 层 | 条数 | 说明 |", "|---|---|---|"]
    for lv, c in sorted(layers.items(), key=lambda kv: str(kv[0])):
        desc = {"L1": "法文原文（primary）", "L2": "二手/中译（secondary）",
                "L3": "研究笔记"}.get(str(lv), "其他")
        lay.append("| %s | %d | %s |" % (lv, c, desc))
    lay.append("| AGENT_SYNTHESIS | %d | 本回答中的结构性综合句（见 claim 表） |"
               % sum(1 for c in claims if c["classification"] == "AGENT_SYNTHESIS"))
    sections["interpretation_layers"] = "\n".join(lay)
    if onto_used:
        claims.append(_claim(
            "c-onto",
            "本次用到的 %s 属于 **ontology.v4a1 叠加层**，其 review_status 仍是 candidate"
            "（未经人工逐条审定），不得当作已定论的理论定义。"
            % "、".join(sorted(set(onto_used))),
            "CONTEXTUAL_INFERENCE", [], [],
            note="§17：candidate ontology entry 不得说成学术委员会确认的定义。"))

    # ── evidence_limitations：把该显示的限制全部显示（§9）
    lim = []
    for w in pack.get("warnings") or []:
        if w.get("code") in ("SOURCE_TRACE_INCOMPLETE", "CONTEXT_REQUIRED",
                             "ONTOLOGY_REPAIRED", "ENTITY_COLLISION",
                             "CONSTRAINT_RETURNED_NOTHING", "NO_VOCABULARY_HIT",
                             "TERMS_NOT_IN_CORPUS", "VECTOR_UNAVAILABLE",
                             "ALIAS_EXCLUDED", "SUPERSEDED_ENTITY",
                             "ONTOLOGY_DECLARED_EVIDENCE"):
            lim.append("- `%s`：%s" % (w["code"], _short(w.get("message"), 180)))
    for g in pack.get("ontology_gap_codes") or []:
        if g not in [w.get("code") for w in pack.get("warnings") or []]:
            lim.append("- `%s`（ontology gap code）" % g)
    for l in pack.get("limitations") or []:
        lim.append("- %s" % _short(l, 200))
    if inc:
        lim.append("- %d/%d 条证据为 SOURCE_TRACE_INCOMPLETE（中文 recovered），"
                   "引用时必须保留该告警。" % (len(inc), n))
    if not lim:
        lim.append("- 本次没有触发溯源/映射/约束类告警。")
    sections["evidence_limitations"] = "\n".join(lim)
    claims.append(_claim("c-lim", "本次研究存在上述证据限制。",
                         "CONTEXTUAL_INFERENCE", [], []))

    answer = {
        "schema_version": "research-answer-4b/v1",
        "question": pack.get("query"),
        "evidence_state": state,
        "sections": sections,
        "claims": claims,
        "citation_style": ("`[S<NN> · passage_id]`；recovered 中译必须带 "
                           "SOURCE_TRACE_INCOMPLETE 告警"),
        "generated_by": "research_answer.compose_answer（规则式组装，非 LLM 生成）",
        "note": ("回答由**规则**从证据包组装：引用是逐字的，结构性句子可由证据包复核；"
                 "不含模型私有推理，也不含没有段号支持的理论定论。"),
    }
    return answer


# ─────────────────────────────────────────────── claim/citation 校验

def validate_answer(answer, pack, strict=False):
    """§12：claim → citation 的**本地**校验（防止引用漂移）。

    → {ok, issues[], metrics{}}
      issues 里的每个元素都带 claim_id 与原因，便于定位。
    """
    issues = []
    meta = {e["passage_id"]: e for e in (pack.get("evidence") or [])}
    known = api.KB_.meta()
    cites_total = cites_real = cites_anchor = cites_cluster = 0
    substantive = [c for c in answer["claims"]
                   if c["classification"] != "AGENT_SYNTHESIS"]
    for c in answer["claims"]:
        # (1) citation 必须真实存在
        for pid in c["citations"]:
            cites_total += 1
            if pid not in known:
                issues.append({"claim_id": c["claim_id"], "kind": "FABRICATED_CITATION",
                               "passage_id": pid})
                continue
            cites_real += 1
            if pid not in meta:
                issues.append({"claim_id": c["claim_id"],
                               "kind": "CITATION_NOT_IN_EVIDENCE_PACK",
                               "passage_id": pid})
            # (2) anchor 词必须真的出现在该段（**term 级** entailment 代理）
            raw = known[pid].get("raw_text") or ""
            anchors = [a for a in c.get("anchor_terms") or [] if a]
            if anchors:
                strong, weak = _anchor_match(raw, anchors)
                if strong:
                    cites_anchor += 1
                if weak:
                    cites_cluster += 1
        # (3) substantive claim 必须有 citation（或显式弃权）
        if c["classification"] in ("PRIMARY_EVIDENCE", "SECONDARY_INTERPRETATION",
                                   "CONTEXTUAL_INFERENCE") and not c["citations"]:
            if "没有取得任何证据" not in c["text"] and "没有取到" not in c["text"] \
                    and "存在上述证据限制" not in c["text"]:
                issues.append({"claim_id": c["claim_id"], "kind": "UNSUPPORTED_CLAIM",
                               "text": _short(c["text"], 80)})
        # (4) 层级不能混：PRIMARY_EVIDENCE 必须真有 L1 证据
        if c["classification"] == "PRIMARY_EVIDENCE":
            if not any(meta.get(p, {}).get("authority_level") in PRIMARY_LEVELS
                       for p in c["citations"]):
                issues.append({"claim_id": c["claim_id"],
                               "kind": "SOURCE_LAYER_CONFUSION",
                               "detail": "声明 PRIMARY 但引用的段号里没有 L1"})
        # (5) recovered 中译不得被当作闭合 primary
        if c["classification"] == "PRIMARY_EVIDENCE":
            for p in c["citations"]:
                if meta.get(p, {}).get("trace_status") == "SOURCE_TRACE_INCOMPLETE":
                    issues.append({"claim_id": c["claim_id"],
                                   "kind": "PROVENANCE_UPGRADE",
                                   "passage_id": p})
    unsupported = [i for i in issues if i["kind"] == "UNSUPPORTED_CLAIM"]
    metrics = {
        "claims_total": len(answer["claims"]),
        "claims_substantive": len(substantive),
        "citations_total": cites_total,
        "citations_real": cites_real,
        "citations_anchor_supported": cites_anchor,
        "citations_term_cluster_supported": cites_cluster,
        "evidence_validity": (cites_real / cites_total) if cites_total else None,
        # ⚠️ **term 级代理**，不是真正的语义蕴含；真正的 entailment 需要人工评审
        "citation_anchor_support_rate": (cites_anchor / cites_real) if cites_real else None,
        "citation_term_cluster_rate": (cites_cluster / cites_real) if cites_real else None,
        "unsupported_claim_rate": (len(unsupported) / len(substantive))
        if substantive else 0.0,
        "fabricated_citations": len([i for i in issues
                                     if i["kind"] == "FABRICATED_CITATION"]),
        "provenance_upgrades": len([i for i in issues
                                    if i["kind"] == "PROVENANCE_UPGRADE"]),
        "source_layer_confusions": len([i for i in issues
                                        if i["kind"] == "SOURCE_LAYER_CONFUSION"]),
        "entailment_note": ("citation_anchor_support_rate（严格子串）与 "
                            "citation_term_cluster_rate（词袋包含）都是**术语级代理**；"
                            "语料把 objet 与 petit a 分开写时严格版会漏，"
                            "所以两个数都报。真正的语义蕴含需要人工评审"
                            "（见 research_human_review.jsonl，状态 NOT_REVIEWED）。"),
    }
    ok = not issues if strict else metrics["fabricated_citations"] == 0 \
        and metrics["provenance_upgrades"] == 0
    return {"ok": ok, "issues": issues, "metrics": metrics}


# ─────────────────────────────────────────────── 主入口

_MANIFEST_CACHE = {}


def _manifest_ref():
    """本次 run 的版本绑定引用（§A3 的 EvaluationRunManifest）。

    只读：记录 manifests/latest.json 的 run_id / engine_hash / git_commit，
    使每条 trace 都能回答「这份结果由哪一版代码/本体/语料/Gold 生成」。
    """
    if _MANIFEST_CACHE:
        return _MANIFEST_CACHE
    p = os.path.join(VAULT, "_data", "eval", "manifests", "latest.json")
    ref = {"manifest_path": os.path.relpath(p, VAULT), "available": False}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        ref.update({"available": True, "run_id": d.get("run_id"),
                    "engine_version": d.get("engine_version"),
                    "engine_hash": d.get("engine_hash"),
                    "git_commit": d.get("git_commit"),
                    "gold_version": d.get("gold_version"),
                    "ontology_version": d.get("ontology_version"),
                    "passage_store_version": d.get("passage_store_version"),
                    "task_set_version": d.get("task_set_version")})
    except Exception:
        pass
    _MANIFEST_CACHE.update(ref)
    return _MANIFEST_CACHE



def _entity_linked_pids(evp, plan):
    """哪些证据段落「已连接实体」（§9 的 directness signal）。

    判定是**结构性的**：该段包含某个已解析实体在知识库里的任一写法，
    或者该段本身就是概念卡声明的 passage（concept card link）。
    """
    import ontology_v4a1 as onto
    forms = []
    for e in (plan.get("entities") or []):
        for eid in e.get("entities") or []:
            ent = onto.entity(eid)
            if ent:
                forms += [ent.get("fr"), ent.get("en"), ent.get("zh")] + list(
                    ent.get("aliases") or [])
            g = onto.gold_concept(eid)
            if g:
                forms += [g.get("fr"), g.get("en"), g.get("zh")] + list(
                    g.get("aliases") or [])
    forms = [f for f in dict.fromkeys(forms) if f and len(str(f)) >= 2]
    out = set()
    for e in evp.get("evidence") or []:
        sq = _squash(e.get("text") or "")
        if any(_squash(f) and _squash(f) in sq for f in forms):
            out.add(e["passage_id"])
        if "concept_card_link" in (e.get("why_retrieved") or []):
            out.add(e["passage_id"])
    return out


# Phase 4B 用的旧类名 → v2 类名（兼容字段里两个都出现，避免改 4B 的测试）
_LEGACY_STRUCTURAL_ALIAS = {
    "METADATA_UNAVAILABLE": "STRUCTURAL_METADATA_GAP",
    "TOPIC_NOT_COVERED": "STRUCTURAL_TOPIC_NOT_COVERED",
    "FORMALISM_MISSING": "STRUCTURAL_FORMALISM_MISSING",
}


def _structural_gap_names(v2res):
    """v2 的结构性缺口类名 + 4B 时期的旧别名（兼容，不改 4B 测试）。"""
    names = [c["class"] for c in v2res.get("structural_unanswerability") or []]
    names += [_LEGACY_STRUCTURAL_ALIAS[c] for c in list(names)
              if c in _LEGACY_STRUCTURAL_ALIAS]
    return list(dict.fromkeys(names))


def _apply_v2(evp, v2res):
    """把 v2 的判定写回证据包（**只降级不升格**由 v2 规则保证），并留下分层字段。"""
    out = dict(evp)
    out["evidence_state"] = v2res
    out["sufficiency_v2"] = {k: v2res[k] for k in
                             ("engine", "availability_state", "topicality_state",
                              "coverage_state", "source_state", "ontology_state",
                              "final_state", "topic_support_levels",
                              "topic_prevalence", "discriminating_terms",
                              "absence_profile", "structural_unanswerability")}
    if v2res["final_state"] != (evp.get("evidence_state") or {}).get("state"):
        out["warnings"] = list(out.get("warnings") or []) + [{
            "code": "SUFFICIENCY_V2_DECISION", "severity": "warning",
            "message": ("Evidence Sufficiency v2：%s（availability=%s / topicality=%s / "
                        "coverage=%s / source=%s / ontology=%s）；理由：%s"
                        % (v2res["final_state"], v2res["availability_state"],
                           v2res["topicality_state"], v2res["coverage_state"],
                           v2res["source_state"], v2res["ontology_state"],
                           "；".join((v2res.get("reasons") or [])[:3])))}]
    return out


def _period_lanes(public_task, plan, evp, tr, budget, remaining=4):
    """对要求 period coverage 的任务，按**已观测到的时期**补一条受约束的检索 lane。

    这不是新检索系统：用的是同一个 `search_passages`，只是把 period/seminar
    作为**约束下推**（Phase 4A 已有的能力）。补进来的证据同样来自 canonical store。
    """
    caps = public_task.get("required_capabilities") or []
    if not ({"period_coverage", "diachronic_grouping"} & set(caps)):
        return []
    seen_periods = {e.get("period") for e in evp.get("evidence") or [] if e.get("period")}
    terms = usable_terms(plan, 2)
    if not terms:
        return []
    import knowledge_api as api
    import lacan_search
    out = []
    already = {e.get("seminar_id") for e in evp.get("evidence") or []}
    # 期内有哪些研讨班 —— 取自 seminars.jsonl（知识库结构，**不是** gold）
    sems = []
    if os.path.isfile(os.path.join(VAULT, "_data", "passage_store", "seminars.jsonl")):
        with open(os.path.join(VAULT, "_data", "passage_store", "seminars.jsonl"),
                  encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    sems.append((d["id"], "%s-%s" % (d.get("year_from"), d.get("year_to"))))
    period_of = dict(sems)
    seen_periods = {period_of.get(s) for s in already}
    # 优先补**尚未覆盖的时期**：在该期里挑主题词命中最多的研讨班
    missing = [s for s, p in sems if p not in seen_periods and s not in already]
    ranked = []
    for sem in missing[:8]:
        try:
            n = len(lacan_search.lexical_search(" ".join(terms), language=None,
                                                seminar=sem, limit=50))
        except Exception:
            n = 0
        ranked.append((n, sem))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    for n, sem in ranked:
        if len(out) >= 2 or len(out) >= remaining:
            break
        if n == 0:
            continue
        r = api.search_passages(" ".join(terms), seminar=sem, top_k=5)
        if r.get("evidence"):
            out.append({"seminar": sem, "result": r})
            tr.tool("search_passages", {"query": " ".join(terms), "seminar": sem,
                                        "top_k": 5, "phase4b": "period_lane"},
                    r, decision=("该期尚未被覆盖且主题词在此期有 %d 条命中 → "
                                 "补一条受约束 lane（研究循环第 6–8 步）" % n))
    return out


def _merge_evidence(evp, extra_steps):
    """把补充 lane 的证据并入证据包，并**重算** coverage/provenance/state。"""
    have = {e["passage_id"] for e in evp.get("evidence") or []}
    merged = list(evp.get("evidence") or [])
    for st in extra_steps:
        for e in st["result"].get("evidence") or []:
            if e["passage_id"] not in have:
                have.add(e["passage_id"])
                merged.append(e)
    import knowledge_api as api
    out = dict(evp)
    out["evidence"] = merged
    out["evidence_n"] = len(merged)
    out["coverage"] = api._coverage(merged)
    out["provenance"] = api._provenance_summary(merged)
    out["retrieval"] = {**(evp.get("retrieval") or {}),
                        "period_lanes_added": [s["seminar"] for s in extra_steps]}
    out["citable_passages"] = [e["passage_id"] for e in merged]
    out["by_language"] = ra._count(merged, "language")
    out["by_seminar"] = ra._count(merged, "seminar_id")
    out["by_authority"] = ra._count(merged, "authority_level")
    import evidence_sufficiency as es
    payload = {k: out.get(k) for k in
               ("request", "resolution", "retrieval", "evidence", "coverage",
                "provenance", "warnings", "evidence_state")}
    out["evidence_state"] = es.evaluate(payload)
    return out


def _apply_calibration(evp, state, reasons, signals, downgraded=True):
    """把校准结果写回证据包（**只降级**，并留下可复核的理由）。"""
    out = dict(evp)
    st = dict(out.get("evidence_state") or {})
    st["state"] = state
    st["reasons"] = list(reasons) + list(st.get("reasons") or [])
    sig = dict(st.get("signals") or {})
    sig.update({k: v for k, v in (signals or {}).items() if k in
                ("relevance_rate", "relevance_matched_n")})
    sig["structural_gaps"] = (signals or {}).get("structural_gaps") or []
    st["signals"] = sig
    st["calibrated_by"] = "research_answer.calibrate_state（规则式降级，不升格）"
    out["evidence_state"] = st
    if downgraded:
        out["warnings"] = list(out.get("warnings") or []) + [
            {"code": "SUFFICIENCY_CALIBRATED", "severity": "warning",
             "message": "证据充分性经 §13 校准降级为 %s：%s" % (state, "；".join(reasons))}]
    return out


def run_task(public_task, budget=None, record_gaps=False, compose=True,
             execute_contract=True):
    """完整研究循环：计划 → 多步检索（Phase 4A）→ 组装回答 → 校验。

    `public_task` **只允许**含公开字段（task_id/question/language/task_type/
    required_capabilities/split）——gold 由 evaluator 保管（§6）。

    `execute_contract=False`：只跑「主探索 + v2 证据层 + 契约校验（事后）」，**不启用**
    4C.1-B2 的执行调度器。用于**证据层校准集**（`calibrate_sufficiency_v2.py`）——
    那里测的是 v2 分层本身，必须与 Phase 4C 冻结指标逐字一致；执行层的效果由
    4C.1-B2 的 diagnostic 指标单独度量。
    """
    banned = [k for k in public_task
              if k in ("gold_evidence", "acceptable_evidence", "expected_operations",
                       "expected_entities", "expected_seminars", "expected_periods",
                       "answerability", "evaluation_notes", "forbidden_shortcuts")]
    if banned:
        raise ValueError("公开任务里不得含 gold 字段：%s" % banned)
    t0 = ra.time.time()
    plan = make_plan(public_task, budget)
    tr = ResearchTrace(public_task["task_id"])
    # ── 契约感知预算（Phase 4C.1-B2 §20）：先算出 required obligations 需要多少调用，
    #    从总预算里**预留**给执行调度器；主探索只用剩下的。总调用数仍不超过配置上限。
    cfg = dict(budget or ra.DEFAULT_BUDGET)
    pre_contract_for_budget = rcontract.compile_research_contract(
        public_task, plan, {"evidence": []}, executed_tools=[])
    pre_obligations = rcontract.contract_obligations(pre_contract_for_budget)
    n_required_lanes = len([l for l in pre_obligations["lanes"] if l.get("required")])
    n_facets = sum(1 for k, v in (pre_obligations["facets"] or {}).items() if v)
    n_endpoints = len(pre_obligations["endpoints"])
    # 需要多少次调用才能把 required obligations 做完（每个 lane ≤2 次：受控 + 词面补充）
    n_direct_ops = len([op for op in pre_obligations["operations"]
                        if op in ("compare_concepts", "trace_concept",
                                  "terminology_lookup")])
    # 实体解析本身也要花调用（每个内容词 1 次）
    n_terms = len(rcontract.content_terms(plan.get("salient_terms") or [])[:4]) or 1
    n_required_ops = len(pre_obligations["operations"])
    need_contract = rexec.estimate_required_calls(pre_contract_for_budget, plan,
                                                  pre_obligations)
    # 取两者较大值：前者是「lane 覆盖不到的操作」的保守估计，后者是契约义务的调用上界
    need = max(n_terms + 2 * n_required_lanes + 2 * n_facets + n_endpoints + n_direct_ops,
               need_contract + n_required_ops)
    reserved = max(1, min(max(1, cfg.get("max_tool_calls", 12) - 1), need))
    base_cfg = dict(cfg)
    if execute_contract:
        base_cfg["max_tool_calls"] = max(1, cfg.get("max_tool_calls", 12) - reserved)
    # 校准模式（execute_contract=False）下**不缩减**主探索预算：证据层行为必须与
    # Phase 4C 冻结指标逐字一致。
    pack = ra.research(public_task["question"], budget=base_cfg,
                       record_gaps=record_gaps)
    pack["budget"]["config"] = dict(cfg)          # 报告里的上限仍是用户配置的上限
    pack["budget"]["contract_reserved_calls"] = reserved
    trace_doc = pack["research_trace"]
    for step in trace_doc["steps"]:
        tr.tool(step["tool"], step["arguments"], {
            "evidence": [{"passage_id": p} for p in
                         (step["result_digest"].get("evidence_ids") or [])],
            "evidence_state": {"state": step["result_digest"].get("state")},
            "resolution": {"resolution_status":
                           step["result_digest"].get("resolution_status")},
            "retrieval": {"route": step["result_digest"].get("route")},
            "warnings": [{"code": c} for c in
                         (step["result_digest"].get("warnings") or [])],
        }, decision=step.get("decision"))
    # ── 研究循环的**补充步骤**（§7 的 6→7→8：识别缺口 → 限定 period/seminar → 第二条 lane）
    evp = pack["evidence_pack"]
    extra_steps = _period_lanes(public_task, plan, evp, tr, budget,
                                remaining=max(0, (pack["budget"]["config"]["max_tool_calls"]
                                                  - pack["budget"]["used"]["tool_calls"])))
    if extra_steps:
        evp = _merge_evidence(evp, extra_steps)
        # ⚠️ 补充步骤必须计入预算（§20）：否则「预算真的生效」这条判据是假的
        pack["budget"]["used"]["tool_calls"] += len(extra_steps)
        if pack["budget"]["used"]["tool_calls"] > pack["budget"]["config"]["max_tool_calls"]:
            pack["budget"]["exceeded"] = sorted(set(
                list(pack["budget"]["exceeded"]) + ["max_tool_calls"]))
    # ── §13/§32（Phase 4C）：**Evidence Sufficiency v2** 是权威判定。
    #    分层的 availability / topicality / coverage / source / ontology → final_state。
    #    v1 的那几个结构检查仍保留（它们是确定性信号，Phase 4B 的测试也还在用），
    #    但**状态由 v2 决定**，不再由 v1 的校准规则决定。
    state_before = pack["evidence_pack"]["evidence_state"]["state"]
    # ── Phase 4C.1-B：Plan → **Contract**（可执行、可检查、可失败）
    # 以 **trace 为准**：补充步骤（_period_lanes）只写进 tr.doc["tool_calls"]，
    # 不在 pack["research_trace"]["steps"] 里；用错来源会让契约的 completed_operations
    # 与 trace 对不上（Gate 19 的 COMPLETED_OPERATIONS_MISMATCH 就是这么抓到的）。
    pre_contract = rcontract.compile_research_contract(
        public_task, plan, {"evidence": []}, executed_tools=[])
    remaining = {
        "max_tool_calls": max(0, pack["budget"]["config"]["max_tool_calls"]
                              - pack["budget"]["used"]["tool_calls"]),
        "max_passages": max(0, pack["budget"]["config"]["max_passages"]
                            - pack["budget"]["used"]["passages"]),
        "max_context_expansions": max(0, pack["budget"]["config"]["max_context_expansions"]
                                      - pack["budget"]["used"]["context_expansions"]),
    }
    if execute_contract:
        sched = rexec.ResearchExecutionScheduler(public_task, plan, pre_contract,
                                                 budget=remaining, trace=tr,
                                                 record_gaps=record_gaps)
        execution = sched.run()
        sched_evidence = sched.evidence_records()
        if sched_evidence:
            evp = rexec.assemble_pack(evp, execution, sched_evidence)
        b_used = pack["budget"]["used"]
        b_used["tool_calls"] += execution["budget"]["used"]["tool_calls"]
        b_used["passages"] += execution["budget"]["used"]["passages"]
        b_used["context_expansions"] += execution["budget"]["used"]["context_expansions"]
        if execution["budget"]["exhausted"]:
            pack["budget"]["exceeded"] = sorted(set(
                list(pack["budget"]["exceeded"]) + ["contract_budget_exhausted"]))
    else:
        execution = {"schema_version": rexec.SCHEMA, "state": "NOT_SCHEDULED",
                     "state_machine": [{"from": None, "to": "NOT_SCHEDULED",
                                        "reason": "execute_contract=False（证据层校准模式）"}],
                     "required_operations": [], "scheduled_operations": [],
                     "executed_operations": [], "failed_operations": [],
                     "skipped_operations": [], "structurally_unavailable_operations": [],
                     "operations": [], "lanes": [], "endpoints": [], "constraints": [],
                     "relation": {"required": False}, "formalism": {},
                     "terminology": {}, "metadata": {}, "source_layers": {},
                     "generic_fallback": {"used": False,
                                          "satisfied_required_lane_n": 0},
                     "budget": {"config": remaining, "used": {"tool_calls": 0,
                                                              "passages": 0,
                                                              "context_expansions": 0},
                                "exhausted": False},
                     "limitations": [], "warnings": [],
                     "no_hidden_reasoning": True,
                     "note": "执行调度器未启用（证据层校准模式）"}
    # ── §13/§32：Evidence Sufficiency v2 必须在**执行层合并证据之后**评估
    #    （否则调度器新取到的 lane 证据不进入充分性判定）。
    linked = _entity_linked_pids(evp, plan)
    v2res = esv2.evaluate_v2(
        {"request": {"query": public_task["question"]},
         "resolution": evp.get("resolution") or {},
         "retrieval": evp.get("retrieval") or {},
         "evidence": evp.get("evidence") or [],
         "coverage": evp.get("coverage") or {},
         "provenance": evp.get("provenance") or {},
         "warnings": evp.get("warnings") or [],
         "evidence_state": evp.get("evidence_state") or {}},
        question=public_task["question"], plan=plan,
        entity_linked_pids=linked)
    evp = _apply_v2(evp, v2res)
    executed_tools = [c.get("tool") for c in (tr.doc.get("tool_calls") or [])]
    # ── relation lane 复核（B2 一致性）：调度器那一轮关系检索是在**分道搜索的 top-k
    #    交集**上判的（窄）；契约用的是**最终证据集**上的同一套确定性判定器（宽）。
    #    两者不一致时会把「R0_NONE」和「relation_evidence_n=5」同时写进 trace —— 这是
    #    自相矛盾。以**最终证据集上的判定器**为准，把结果同步回 relation lane 的记录。
    if execute_contract:
        try:
            rel = rcontract.relation_evidence(evp.get("evidence") or [],
                                              rcontract.entity_form_groups(plan),
                                              public_task.get("question") or "")
            rel_ids = rel.get("relation_evidence_ids") or []
            rel_n = rel.get("relation_evidence_n") or 0
            for lane in (execution.get("lanes") or []):
                if not str(lane.get("lane_id", "")).startswith("relation:"):
                    continue
                if rel_ids and not lane.get("evidence_ids"):
                    lane.update(status="SATISFIED", evidence_ids=rel_ids,
                                usable_hit_count=len(rel_ids),
                                hit_count=max(lane.get("hit_count") or 0, len(rel_ids)),
                                note=("relation lane 复核：最终证据集上确定性判定器命中 %d 段"
                                      "（strength=%s；分道交集那一轮为 %s）"
                                      % (rel_n, rel.get("relation_strength"),
                                         (execution.get("relation") or {}).get("relation_strength"))))
            if execution.get("relation"):
                execution["relation"].update(
                    relation_evidence_ids=rel_ids, relation_evidence_n=rel_n,
                    relation_strength=rel.get("relation_strength"),
                    relation_strength_counts=rel.get("relation_strength_counts"),
                    recheck="final_evidence_set（与契约同一个判定器）")
        except Exception:
            pass
    # 把执行记录交给契约编译器：lane 完成度必须看**执行时是否真的取到证据**
    # （§33：不允许用「调度过」冒充「有证据」；B1 的 RELATION lane 假完成就是这么来的）
    try:
        evp["execution"] = execution
    except Exception:
        pass
    op_statuses = {o.get("operation_id"): o.get("status")
                   for o in (execution.get("operations") or [])}
    contract = rcontract.compile_research_contract(public_task, plan, evp,
                                                  executed_tools=executed_tools,
                                                  op_statuses=op_statuses)
    v21 = esv21.evaluate_v21(v2res, contract, question=public_task["question"],
                             executed_operations=executed_tools)
    evp = esv21.apply_v21(evp, v21, contract)
    state = v21["final_state"]
    tr.doc["sufficiency_v2"] = {
        "engine": v2res["engine"], "state_before": state_before, "state_after": state,
        "availability_state": v2res["availability_state"],
        "topicality_state": v2res["topicality_state"],
        "coverage_state": v2res["coverage_state"],
        "source_state": v2res["source_state"],
        "ontology_state": v2res["ontology_state"],
        "topic_support_levels": v2res["topic_support_levels"],
        "topic_prevalence": v2res["topic_prevalence"],
        "discriminating_terms": v2res["discriminating_terms"],
        "structural_unanswerability": v2res["structural_unanswerability"],
        "absence_profile": v2res["absence_profile"],
        "reasons": v2res["reasons"],
    }
    # 兼容字段：Phase 4B 的测试读 trace["calibration"]["signals"]["structural_gaps"]。
    # 不为了新引擎去改 4B 的测试 —— 保留这个字段并让它由 v2 派生。
    tr.doc["calibration"] = {
        "state_before": state_before, "state_after": state,
        "reasons": v2res["reasons"],
        "signals": {"structural_gaps": _structural_gap_names(v2res),
                    "relevance_rate": (v2res.get("signals") or {}).get("relevance_rate"),
                    "topicality_state": v2res["topicality_state"],
                    "availability_state": v2res["availability_state"]},
        "engine": v2res["engine"],
    }
    # ── Phase 4C.1-B trace schema（research-trace/v2）
    tr.doc["schema_version"] = "research-trace/v2"
    tr.doc["research_contract"] = contract
    tr.doc["execution"] = execution
    # ── Phase 4C.1-B3 §6：两种完成率分开报（不用语义手段制造假的 100%）
    _ex_ops = {o["operation_id"]: o for o in (execution.get("operations") or [])}
    _req = list(execution["required_operations"])
    _exec_n = len([o for o in _req if (_ex_ops.get(o) or {}).get("status") == "EXECUTED"])
    _na_n = len([o for o in _req
                 if (_ex_ops.get(o) or {}).get("status") == "NOT_APPLICABLE"
                 and rcontract.BaseContract.not_applicable_is_proven(
                     {"structural_dependency": (_ex_ops.get(o) or {}).get(
                         "structural_dependency")})])
    _struct_n = len([o for o in _req
                     if (_ex_ops.get(o) or {}).get("status") == "STRUCTURALLY_UNAVAILABLE"])
    _req_n = len(_req)

    def _rate(n, d):
        return round(n / d, 4) if d else None

    tr.doc["execution_completion"] = {
        "state": execution["state"],
        "required_operations_resolved":
            len(execution["required_operations"]) - len(execution["skipped_operations"]),
        "required_lanes_resolved":
            len([l for l in execution["lanes"]
                 if l["required"] and l["status"] in
                 ("EXECUTED", "SATISFIED", "ZERO_ATTESTATION_CONFIRMED",
                  "STRUCTURALLY_UNAVAILABLE", "NOT_APPLICABLE")]),
        "constraints_processed": len(execution["constraints"]),
        "generic_fallback_satisfied_required_lane_n":
            execution["generic_fallback"]["satisfied_required_lane_n"],
        "complete": execution["state"] == "EXECUTION_COMPLETE",
        # B3 §6：raw = 真正 EXECUTED；resolved = EXECUTED + 合法 NOT_APPLICABLE +
        # STRUCTURALLY_UNAVAILABLE（结构性不可得也是「有结论」）
        "required_operation_n": _req_n,
        "raw_executed_n": _exec_n,
        "raw_executed_rate": _rate(_exec_n, _req_n),
        "not_applicable_proven_n": _na_n,
        "structurally_unavailable_n": _struct_n,
        "resolved_obligation_rate": _rate(_exec_n + _na_n + _struct_n, _req_n),
        "not_applicable_is_not_execution":
            "NOT_APPLICABLE 只进 resolved_obligation_rate，永不进 raw_executed_rate",
    }
    tr.doc["not_applicable_operations"] = contract.get("not_applicable_operations") or []
    tr.doc["resolved_operations"] = contract.get("resolved_operations") or []
    tr.doc["required_operation_resolution"] = {
        "required_operations": _req,
        "resolved_operations": contract.get("resolved_operations") or [],
        "not_applicable_operations": contract.get("not_applicable_operations") or [],
        "not_applicable_unproven": contract.get("not_applicable_unproven") or [],
        "structurally_unavailable_operations":
            contract.get("structurally_unavailable_operations") or [],
        "missing_operations": contract.get("missing_operations") or [],
    }
    tr.doc["terminology_completion"] = execution.get("terminology") or {}
    tr.doc["budget_plan"] = (execution.get("budget") or {}).get("plan") or {}
    tr.doc["state_machine"] = execution["state_machine"]
    tr.doc["evaluation_run_manifest"] = _manifest_ref()
    tr.doc["required_operations"] = contract["required_operations"]
    tr.doc["completed_operations"] = contract["completed_operations"]
    tr.doc["missing_operations"] = contract["missing_operations"]
    tr.doc["required_lanes"] = contract["required_lanes"]
    tr.doc["completed_lanes"] = contract["completed_lanes"]
    tr.doc["missing_lanes"] = contract["missing_lanes"]
    tr.doc["required_constraints"] = contract["required_constraints"]
    tr.doc["satisfied_constraints"] = contract["satisfied_constraints"]
    tr.doc["failed_constraints"] = contract["failed_constraints"]
    tr.doc["relation_evidence"] = {
        "required": contract["relation_evidence_required"],
        "n": contract["relation_evidence_n"],
        "ids": contract["relation_evidence_ids"],
        "kinds": contract["relation_kinds"],
    }
    tr.doc["source_layer_completion"] = {
        "required": contract["required_source_layers"],
        "available": contract["available_source_layers"],
        "missing": contract["missing_source_layers"],
        "corpus": contract.get("source_layer_corpus"),
    }
    tr.doc["formalism_completion"] = contract["formalism"]
    tr.doc["metadata_completion"] = contract["metadata"]
    tr.doc["evidence_usability"] = contract["evidence_usability"]
    tr.doc["sufficiency_v21"] = {
        "engine": v21["engine"],
        "v2_final_state": v21["v2_final_state"],
        "final_state": v21["final_state"],
        "state_ceiling": v21["state_ceiling"],
        "layers": v21["layers"],
        "completion_state": v21["completion_state"],
        "completion_reasons": v21["completion_reasons"],
        "supported_allowed": v21["supported_allowed"],
        "violated_rules": v21["violated_rules"],
        "transition": v21["transition"],
        "transition_reason": v21["transition_reason"],
        "dropped_reasons": v21["dropped_reasons"],
        "real_signal_line": v21["real_signal_line"],
    }
    tr.doc["final_state"] = state
    tr.doc["final_state_reason_codes"] = v21["completion_reasons"]
    # 最后一步状态与 final_state 若不同，**必须**有 transition reason（§13）
    last_step_state = (tr.doc.get("state_transitions") or [{}])[-1].get("state")
    tr.doc["state_transition_reason"] = v21["transition_reason"] or (
        "final_state 与最后一步一致（%s），无需额外 transition" % last_step_state)
    tr.doc["entities_resolved"] = plan["entities"]
    tr.doc["budget_usage"] = pack["budget"]["used"]
    tr.doc["warnings"] = pack["budget"]["exceeded"]
    for e in evp.get("evidence") or []:
        if e["passage_id"] not in tr.doc["passages_seen"]:
            tr.doc["passages_seen"].append(e["passage_id"])
    answer = compose_answer(evp, plan) if compose else None
    check = validate_answer(answer, evp) if answer else None
    if answer:
        for c in answer["claims"]:
            tr.doc["claims"].append({"claim_id": c["claim_id"],
                                     "classification": c["classification"],
                                     "citations": c["citations"]})
            for p in c["citations"]:
                if p not in tr.doc["citations"]:
                    tr.doc["citations"].append(p)
            for p in c["citations"]:
                tr.select(p)
        # 取舍记录：取到但没被任何 claim 用到的证据
        used = set(tr.doc["citations"])
        for e in evp["evidence"]:
            if e["passage_id"] not in used:
                tr.reject(e["passage_id"], "未进入任何 claim（排序靠后或与问题无关）")
    return {
        "schema_version": "research-run-4c1b/v1",
        "task_id": public_task["task_id"],
        "question": public_task["question"],
        "plan": plan,
        "evidence_pack": evp,
        "answer": answer,
        "answer_check": check,
        "trace": tr.doc,
        "budget": pack["budget"],
        "seconds": round(ra.time.time() - t0, 2),
        "gold_isolation": {"agent_input_fields": sorted(public_task.keys()),
                           "gold_fields_withheld": True},
    }


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "拉康所谓的 objet petit a 到底是什么？"
    pt = {"task_id": "adhoc", "question": q, "language": "zh",
          "task_type": "concept_definition",
          "required_capabilities": ["multi_step", "period_coverage"]}
    out = run_task(pt)
    print(json.dumps({k: out[k] for k in ("plan", "answer", "answer_check")},
                     ensure_ascii=False, indent=1)[:4000])
