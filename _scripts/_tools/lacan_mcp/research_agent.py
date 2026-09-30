#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research_agent.py — Phase 4A §11–§13/§18 只读 Lacan Research Agent

分工（§1 的核心）
─────────────────
MCP / `knowledge_api` 返回**结构化证据**；Research Agent 负责
**理解研究任务 → 多步调用工具 → 比较证据 → 组织证据包 → 判断证据是否充分**。
它**不写理论文章**：产出的是一份**证据包（evidence pack）+ 结构化 research trace**，
最终的自然语言答案由调用它的 LLM（DSH / Codex）依据这份包来写。

这这样切分的理由很实际：§17 要求评的是
tool selection / passage validity / citation validity / sufficiency 正确性 ——
这些都可以对**证据包**客观核对；而「答案读起来好不好」不可核对。

通用 research loop（**不硬编码某一条流程**，§12）
────────────────────────────────────────────────
1. `resolve_entity` —— 先看问题里有哪些概念能被解析（对每个显著词都试）
2. 依据**问题类别**（由 route / guard / intent 推出）选择主工具：
   * 对比类（含两个概念）→ `compare_concepts`（独立 lane）
   * 历时类（intent=diachronic 或含时期线索）→ `trace_concept`
   * 实体类 → `find_concept_evidence`
   * 其它 → `search_passages`
3. **自适应重试**（这是「多步」的实质）：
   * 主检索命中为空 / 状态 INSUFFICIENT → 换更宽的路径重试（去约束 / 加桥扩展）
   * 该词没有 entity → 用 `terminology_lookup` 找受控映射，再重试
   * 涉及必须区分的配对 → 升级为 `compare_concepts`
   * 跨语言（zh 问）→ 检查证据里是否有 fr，没有就用桥扩展重试一次
4. `get_context`（可选，最多 N 次）—— 给最重要的证据补本地上下文
5. `trace_source`（可选）—— 给最强证据补溯源链
6. `evidence_sufficiency` —— 由知识访问层在每次调用里给出；agent 汇总为最终状态
7. 汇总 `evidence_pack` + `limitations` + `ontology_gap_candidates`

预算（§13）
───────────
`max_tool_calls`（默认 12）· `max_passages`（默认 60）· `max_context_expansions`
（默认 3）· `max_retries`（默认 2）。超预算**必须停下并报告 limitations**，
不许无限循环。

不记录模型隐藏推理（§18）
─────────────────────────
trace 里只有：step / tool / 参数 / 结果摘要（ids、state、counts）/ 决策理由。
没有任何「思维过程」。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import knowledge_api as api      # noqa: E402
import ontology_gaps as ogq      # noqa: E402
import query_terms as qt         # noqa: E402

DEFAULT_BUDGET = {
    "max_tool_calls": 12,
    "max_passages": 60,
    "max_context_expansions": 3,
    "max_retries": 2,
}

CJK = qt.CJK
LATIN = qt.LATIN
STOP = qt.STOP


def _salient_terms(query):
    """显著词 —— 复用 `query_terms`（与知识访问层**同一套**规划）。

    第一版在这里自己写了一套正则，结果是「有什么区别」被当成一个显著词，
    成了对比 lane 的名字（实测 `lane「有什么区别」证据数 = 0`）。
    现在只有一处实现，两个调用方共用。
    """
    return qt.salient_terms(query)


class Trace:
    """结构化 research trace（§18）。**只记事实，不记推理。**"""

    def __init__(self):
        self.steps = []

    def add(self, tool, arguments, result, decision=None, note=None):
        digest = {
            "evidence_n": len(result.get("evidence") or []),
            "evidence_ids": [e.get("passage_id") for e in (result.get("evidence") or [])][:10],
            "state": (result.get("evidence_state") or {}).get("state"),
            "resolution_status": (result.get("resolution") or {}).get("resolution_status"),
            "route": (result.get("retrieval") or {}).get("route"),
            "warnings": [w.get("code") for w in (result.get("warnings") or [])],
        }
        self.steps.append({"step": len(self.steps) + 1, "tool": tool,
                           "arguments": arguments, "result_digest": digest,
                           "decision": decision, "note": note})

    def to_dict(self):
        return {"schema_version": "research-trace/v1",
                "no_hidden_reasoning": True,
                "note": ("只记录工具调用与结果摘要；**不含**任何模型私有推理。"),
                "steps": self.steps}


class Budget:
    def __init__(self, **kw):
        b = dict(DEFAULT_BUDGET)
        b.update({k: v for k, v in kw.items() if v is not None})
        self.cfg = b
        self.calls = 0
        self.passages = 0
        self.context_expansions = 0
        self.retries = 0
        self.exceeded = []

    def remaining_passages(self):
        return max(0, self.cfg["max_passages"] - self.passages)

    def spend_call(self):
        """⚠️ **硬上限**：到顶就不再放行，而不是「先花掉再记账」。

        第一版是 `self.calls += 1` 之后再比 —— 于是 `max_tool_calls=2` 也会
        实际调用 3 次（第 3 次只是被标成超预算）。预算写在 spec 里就是上限，
        不是审计口径。
        """
        if self.calls >= self.cfg["max_tool_calls"]:
            self.exceeded.append("max_tool_calls")
            return False
        self.calls += 1
        return True

    def spend_passages(self, n):
        """passage 预算：**请求前先夹紧**（见 `_clamp_topk`），这里只记账。

        为什么不像 tool_calls 那样直接拒绝：证据已经在这次调用里取回来了，
        拒绝它并不能「少花」—— 能做的是下一次要得更少，并把结果如实记账。
        """
        self.passages += n
        if self.passages > self.cfg["max_passages"]:
            self.exceeded.append("max_passages")
            return False
        return True

    def spend_context(self):
        if self.context_expansions >= self.cfg["max_context_expansions"]:
            self.exceeded.append("max_context_expansions")
            return False
        self.context_expansions += 1
        return True

    def spend_retry(self):
        if self.retries >= self.cfg["max_retries"]:
            self.exceeded.append("max_retries")
            return False
        self.retries += 1
        return True

    def ok(self):
        return not self.exceeded

    def report(self):
        return {"config": self.cfg, "used": {"tool_calls": self.calls,
                                             "passages": self.passages,
                                             "context_expansions": self.context_expansions,
                                             "retries": self.retries},
                "exceeded": sorted(set(self.exceeded))}


COMPARE_MARKERS = ("区别", "差异", "对比", "比较", "不同", "vs", "versus",
                   "différence", "difference", "distinction", "distinguish")
CN_ORD = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
          "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13, "十四": 14,
          "十五": 15, "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
          "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24, "二十五": 25,
          "二十六": 26, "二十七": 27}


def _seminar_hint(query):
    """Phase 4A 层的中文序数期号提示（「研讨班十一期」→ seminar.S11）。

    ⚠️ 这是 **4A 层新增**，不改 `query_router` 既有行为 —— 3A/3B 的数字因此仍可复现。
    实测 router 只认 `Seminar XI` / `S11` 这类写法，中文序数解析不出来。
    """
    m = re.search(r"研讨班([一二三四五六七八九十]+)期", query or "")
    if not m:
        return None
    n = CN_ORD.get(m.group(1))
    return "seminar.S%02d" % n if n else None


def _classify(query, plan=None):
    """问题类别 —— 用 routing policy / guard / intent 推，不硬编码某个具体问题。"""
    import query_router
    import query_routing_policy as rp
    if plan is None:
        plan = query_router.route(query)
    route = rp.plan_for(query, plan)
    name = route["route"]
    # 对比标记优先：问题里出现「区别/差异/différence/vs」且有两个显著词时，
    # 即使用户用的不是 guard 收录的那几种写法，也应当分道对比。
    ql = (query or "").lower()
    if any(mk in ql for mk in COMPARE_MARKERS):
        terms = _salient_terms(query)
        if len(terms) >= 2:
            route = dict(route)
            route["route"] = "CONCEPT_COMPARISON"
            route["why"] = "查询含对比标记 %s 且有两个显著词" % [
                mk for mk in COMPARE_MARKERS if mk in ql][:2]
            return "comparison", route
    if name == "CONTRASTIVE_TERMINOLOGY":
        return "contrastive", route
    if name == "CONCEPT_COMPARISON":
        return "comparison", route
    if name == "DIACHRONIC":
        return "diachronic", route
    if name == "SEMINAR_SPECIFIC":
        return "seminar", route
    if name == "EXACT_QUOTATION":
        return "exact_quotation", route
    if name == "EXACT_SOURCE_LOOKUP":
        return "exact_source", route
    if name == "ZH_TO_FR":
        return "cross_language", route
    if name == "FR_MONOLINGUAL":
        return "monolingual_fr", route
    if name == "AMBIGUOUS_ENTITY":
        return "ambiguous", route
    return "concept", route


def _clamp_topk(args, b):
    """把请求的 top_k 夹到**剩余 passage 预算**内（`max_passages` 才真的是上限）。"""
    a = dict(args)
    if "top_k" in a:
        a["top_k"] = max(1, min(int(a["top_k"] or 1), b.remaining_passages() or 1))
    if "per_period" in a:
        a["per_period"] = max(1, min(int(a["per_period"] or 1),
                                    b.remaining_passages() or 1))
    return a


def _lane_terms(query, terms, n=2):
    """对比 lane 的词面：内容词、去重、剔掉对比标记。

    为什么单独一层：`_salient_terms` 已经删过疑问片段，但「区别/差异」这类
    **标记词**在 `strip_fragments` 里是按整段删的，理论上仍可能以别的组合漏进来。
    对比的两侧如果拿到标记词，就会产出「一侧没有证据」的假对比。
    """
    out = []
    for t in (terms or []):
        tl = str(t).lower()
        if any(mk in tl for mk in COMPARE_MARKERS):
            continue
        if tl in STOP:
            continue
        if t not in out:
            out.append(t)
    if len(out) >= n:
        return out[:n]
    # 兜底：raw query 去掉疑问片段后再切一次
    extra = [w for w in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\-]{2,}|[\u4e00-\u9fff]{2,}",
                                   qt.strip_fragments(query))
             if w not in out and w.lower() not in STOP]
    for w in extra:
        out.append(w)
        if len(out) >= n:
            break
    return out


def research(query, budget=None, record_gaps=True, save_trace_dir=None):
    """跑一次多步研究。返回**证据包 + trace + limitations**（不生成理论文章）。"""
    import query_router
    import query_routing_policy as rp

    t0 = time.time()
    b = Budget(**(budget or {}))
    tr = Trace()
    limitations = []
    plan = query_router.route(query)
    qtype, route = _classify(query, plan)
    # ⚠️ router 已经能从 `Seminar XI` / `S11` 解析出 seminar.S11，
    #    第一版只用中文序数正则，于是 `Seminar XI 如何讨论 gaze？` 这条路
    #    在访问层被**隐式**加上了 seminar.S11 约束（search_passages 里下推），
    #    agent 自己却不知道 → 既没报告范围，也没触发「约束放宽」重试。
    sem_hint = _seminar_hint(query) or ((plan.get("seminars") or [None])[0])
    if sem_hint and sem_hint not in (plan.get("seminars") or []):
        plan = dict(plan)
        plan["seminars"] = list(plan.get("seminars") or []) + [sem_hint]

    # ⚠️ 期号是**主导语义**：问题一旦把范围钉在某一期上，研究操作就是
    #    「这一期怎么说」。第一版只在选工具时才用它，query_type 仍报
    #    cross_language —— 于是同一类问题（D 与 C）类别不一致。
    if sem_hint and qtype in ("cross_language", "monolingual_fr", "concept",
                              "exact_source", "ambiguous", "exact_quotation"):
        qtype = "seminar"

    # ── step 1：解析显著词（这决定了后面能不能做实体约束检索）
    terms = _salient_terms(query)
    resolutions = {}
    # 这一轮里**看过的每一份响应**都留档：pack 末尾要如实汇总「这次操作暴露了
    # 哪些缺口」。只从主检索里收，会漏掉 step 1 解析出来的 UNRESOLVED_ENTITY
    # （实测：`gaze` 的缺口就是这样漏掉的）。
    extra_docs = []
    gap_candidates = []      # §22：只记候选，不修
    for t in terms[:6]:
        if not b.spend_call():
            limitations.append("预算耗尽：未解析完全部候选词（%s）" % terms[:6])
            break
        r = api.resolve_entity(t)
        resolutions[t] = r
        extra_docs.append(r)
        tr.add("resolve_entity", {"term": t}, r,
               decision=("可用实体" if r["resolution"]["resolution_status"] == "RESOLVED"
                         else "未解析/歧义 → 不据此硬搜"))
        if record_gaps:
            gap_candidates += ogq.from_response(r, "research_agent.resolve_entity")
    # ⚠️ 只有 RESOLVED 的候选才能当「可解析实体」。
    #    第一版把 AMBIGUOUS / ENTITY_COLLISION 的候选也收了进来 ——
    #    于是 `signifiant 和 signifié` 会拿「signifiant 的两个歧义候选」
    #    去做概念对比（对比的两侧根本不是用户问的那两侧）。
    resolved_entities, ambiguous_terms, collision_terms = [], [], []
    gap_candidates = []      # §22：只记候选，不修
    for t, r in resolutions.items():
        st = r["resolution"]["resolution_status"]
        if st == "RESOLVED":
            resolved_entities += [c["entity_id"] for c in r["resolution"]["candidates"]]
        elif st == "AMBIGUOUS":
            ambiguous_terms.append(t)
        elif st == "ENTITY_COLLISION":
            collision_terms.append(t)
    resolved_entities = list(dict.fromkeys(resolved_entities))

    # ── step 2：选主工具
    primary = None
    decision = None
    q_used = None
    if qtype in ("contrastive", "comparison") and len(resolved_entities) >= 2:
        primary = ("compare_concepts",
                   {"concept_a": resolved_entities[0], "concept_b": resolved_entities[1],
                    "top_k": 10})
        decision = ("检测到两个可解析概念（%s）→ 用独立 lane 对比，"
                    "**不**把两者拼成一个 query" % resolved_entities[:2])
    elif qtype in ("contrastive", "comparison"):
        # 概念没都解析出来 → 用**内容词**做 lane（仍然分道），并记 gap。
        # 为什么不是 terms[:2]：terms 里可能混着疑问片段（第一版就是这样把
        # `有什么区别` 当成了 lane 名）。这里再滤一遍标记词，并保证两侧不同。
        words = _lane_terms(query, terms)
        primary = ("compare_concepts",
                   {"concept_a": words[0], "concept_b": words[1], "top_k": 10})
        decision = ("问题看起来是对比，但只有 %d 个概念解析出来 → 仍走分道，"
                    "未解析的一侧会如实报缺失" % len(resolved_entities))
    elif qtype == "diachronic":
        primary = ("trace_concept",
                   {"concept": resolved_entities[0] if resolved_entities else query,
                    "per_period": 5})
        decision = "router 判为历时问题 → 按 period 分组取证据"
    elif sem_hint:
        # ⚠️ 送进词法层的必须是**内容词**。整句中文会被 Phase 3 的
        #    bigram 短语档变成 `"研讨 讨班 班十 十一 一期 期如 如何 …"` → 0 命中，
        #    而语料里 S07 的 jouissance / S11 的 凝视 明明有材料。
        q_used = " ".join(_lane_terms(query, terms)) or query
        q_used = q_used.strip()
        primary = ("search_passages",
                   {"query": q_used, "seminar": sem_hint, "top_k": 15})
        decision = ("解析出期号 %s → seminar 约束**下推**到检索层"
                    "（不是事后过滤）；查询词取显著词 %r（不把整句送进词法层）"
                    % (sem_hint, q_used))
    elif resolved_entities:
        primary = ("find_concept_evidence",
                   {"concept": resolved_entities[0], "top_k": 15})
        decision = "有可解析实体 → 用实体约束的证据检索（而非通用检索）"
    else:
        primary = ("search_passages", {"query": query, "top_k": 10})
        decision = "没有可解析实体 → 退回通用检索（不做字符串强匹配）"

    if not b.spend_call():
        limitations.append("预算耗尽：未能执行主检索")
        main = {"request": {"tool": "none"}, "evidence": [], "warnings": [],
                "resolution": {}, "retrieval": {}, "evidence_state": {"state": "INSUFFICIENT_EVIDENCE",
                                                                     "reasons": ["预算耗尽"]}}
    else:
        main = api.call(primary[0], _clamp_topk(primary[1], b))
        tr.add(primary[0], _clamp_topk(primary[1], b), main, decision=decision)
        b.spend_passages(len(main.get("evidence") or []))
        if record_gaps:
            gap_candidates += ogq.from_response(main, "research_agent.primary")

    # ── step 3：自适应重试（这是「多步」的实质，也是 §17 要测的 retry 行为）
    state = (main.get("evidence_state") or {}).get("state")
    ev = main.get("evidence") or []
    retries_done = []
    if state in ("INSUFFICIENT_EVIDENCE", "PARTIALLY_SUPPORTED") or not ev:
        # 3a. 没有受控映射 → 先查桥，再放宽重试
        if not ev and terms:
            if b.spend_retry() and b.spend_call():
                tl = api.terminology_lookup(terms[0])
                extra_docs.append(tl)
                tr.add("terminology_lookup", {"term": terms[0]}, tl,
                       decision="主检索为空 → 先确认该词是否有受控跨语言映射")
                targets = [c["target_form"] for c in
                           (tl.get("resolution") or {}).get("candidates") or []][:4]
                if targets and b.spend_call():
                    wide = api.search_passages(" ".join([terms[0]] + targets), top_k=10)
                    extra_docs.append(wide)
                    main = wide
                    retries_done.append("bridge_expansion")
                    tr.add("search_passages", {"query": " ".join([terms[0]] + targets)},
                           wide, decision="用 Terminology Bridge 的目标写法放宽重试")
                    ev = wide.get("evidence") or []
                    state = (wide.get("evidence_state") or {}).get("state")
        # 3a-2. seminar 约束把结果清空了 → 放宽约束重试一次（并如实记下来）
        if not ev and sem_hint:
            if b.spend_retry() and b.spend_call():
                loose = api.search_passages(q_used or query, top_k=10)
                extra_docs.append(loose)
                tr.add("search_passages", {"query": query, "seminar": None},
                       loose, decision=("seminar=%s 约束下 0 命中 → 放宽约束重试，"
                                        "用来判断「语料里到底有没有」"
                                        "（不等于该期内没有）" % sem_hint))
                retries_done.append("seminar_constraint_relaxed")
                limitations.append(
                    "seminar=%s 约束下没有证据；放宽后的结果来自**别的**研讨班，"
                    "不能当作该期表述。" % sem_hint)
                if loose.get("evidence"):
                    main = loose
                    ev = loose.get("evidence") or []
                    state = (loose.get("evidence_state") or {}).get("state")
        # 3b. 跨语言但证据里没有法文 → 用桥扩展再试一次
        if qtype == "cross_language" and ev and not any(
                e.get("language") == "fr" for e in ev):
            if b.spend_retry() and b.spend_call():
                import terminology_bridge as tb
                forms = []
                for eid in resolved_entities[:2]:
                    forms += tb.lexical_forms_for_entity(eid)[:6]
                fr_forms = [f for f in forms if re.search(r"[A-Za-zÀ-ÿ]", f)][:6]
                if fr_forms:
                    fr = api.search_passages(" ".join(fr_forms), language="fr", top_k=10)
                    extra_docs.append(fr)
                    tr.add("search_passages", {"query": " ".join(fr_forms), "language": "fr"},
                           fr, decision="中文问题但证据里没有法文原文 → 用术语桥走法文侧重试")
                    retries_done.append("cross_language_fr_retry")
                    if fr.get("evidence"):
                        main = _merge_lanes(main, fr)
                        ev = main["evidence"]
                        state = main["evidence_state"]["state"]

    # ── step 4：本地上下文（有限次）
    contexts = {}
    for e in (ev[:3] if ev else []):
        # ⚠️ 顺序必须是「先检查工具调用预算，再记上下文预算」：反过来会出现
        #    「context_expansions 记了 1 次，但 get_context 其实没调用」的假账
        #    （Gate 19 的 CONTEXT_EXPANSION_COUNT_MISMATCH 抓的就是这种对不上）。
        if not b.spend_call():
            limitations.append("预算耗尽：上下文补充提前结束")
            break
        if not b.spend_context():
            limitations.append("预算耗尽：只补了 %d 处上下文" % len(contexts))
            break
        pid = e["passage_id"]
        ctx = api.get_context(pid, before=2, after=2)
        contexts[pid] = {"window_size": (ctx.get("retrieval") or {}).get("window_size"),
                         "passage_ids": [x["passage_id"] for x in ctx.get("evidence") or []]}
        tr.add("get_context", {"passage_id": pid, "before": 2, "after": 2}, ctx,
               decision="给最强证据补本地上下文（保持 store 原序，不做总结）")

    # ── step 5：溯源（给 top-1 补链）
    source_trace = None
    if ev and b.spend_call():
        source_trace = api.trace_source(ev[0]["passage_id"])
        tr.add("trace_source", {"passage_id": ev[0]["passage_id"]}, source_trace,
               decision="给 top-1 证据补溯源链（不完整时保留告警）")
        if (source_trace.get("provenance") or {}).get("gaps"):
            limitations.append("top-1 证据的溯源链不完整（SOURCE_TRACE_INCOMPLETE）")

    # ── step 6：汇总证据包
    final_state = (main.get("evidence_state") or {})
    if b.exceeded:
        limitations.append("预算已超：%s —— 停止继续检索并如实报告" % sorted(set(b.exceeded)))
    if final_state.get("state") == "INSUFFICIENT_EVIDENCE":
        limitations.append("证据不足：当前知识库未能提供支撑本次研究操作的证据")
    if ov := (main.get("resolution") or {}).get("collisions"):
        limitations.append("存在 ENTITY_COLLISION：知识库无法把两侧证据归给不同实体")

    # ── 汇总「这次操作暴露了哪些缺口」
    # ⚠️ 第一版 pack 里**没有** resolution / warnings / coverage / provenance，
    #    于是「缺实体」「ENTITY_COLLISION」「VECTOR_UNAVAILABLE」这些本该由
    #    证据包如实交代的事情，只剩工具层内部有 —— 调用方看不到。
    def _codes_from(doc):
        out = set()
        for w in (doc or {}).get("warnings") or []:
            out.add(w.get("code"))
        res = (doc or {}).get("resolution") or {}
        for g in (res.get("ontology_gaps") or []) + (res.get("collisions") or []):
            out.add(g.get("code"))
        for lane in ((doc or {}).get("retrieval") or {}).get("lanes") or []:
            pass
        return out

    GAP_CODES = {"COUNTERPART_ENTITY_MISSING", "BOTH_ENTITIES_MISSING",
                 "UNRESOLVED_ENTITY", "NO_CONTROLLED_MAPPING", "ENTITY_COLLISION",
                 "AMBIGUOUS_ENTITY", "ONTOLOGY_GAP", "DISTINCT_FROM",
                 "NO_VOCABULARY_HIT", "TERMS_NOT_IN_CORPUS",
                 "CONSTRAINT_RETURNED_NOTHING", "PASSAGE_NOT_FOUND"}
    all_codes = set()
    for doc in [main] + list(extra_docs):
        all_codes |= _codes_from(doc)
    all_codes |= {g.get("issue_type") for g in gap_candidates if g.get("issue_type")}
    ontology_gap_codes = sorted(c for c in all_codes if c in GAP_CODES)

    all_ids = [e["passage_id"] for e in ev]
    pack = {
        "schema_version": "evidence-pack/v1",
        "query": query,
        "query_type": qtype,
        "retrieval_route": (route or {}).get("route"),
        "seminar_hint": sem_hint,
        "query_terms": terms,
        "resolved_entities": resolved_entities,
        "ambiguous_terms": ambiguous_terms,
        "collision_terms": collision_terms,
        "terms": terms,
        "unresolved_terms": [t for t, r in resolutions.items()
                             if r["resolution"]["resolution_status"] != "RESOLVED"],
        "primary_tool": primary[0],
        "resolution": (main.get("resolution") or {}),
        "coverage": (main.get("coverage") or {}),
        "provenance": (main.get("provenance") or {}),
        "warnings": (main.get("warnings") or []),
        "ontology_gap_codes": ontology_gap_codes,
        "ontology_gap_candidates": [
            {"issue_id": g.get("issue_id"), "issue_type": g.get("issue_type"),
             "term": g.get("term"), "status": g.get("status"),
             "canonical_change_proposed": g.get("canonical_change_proposed")}
            for g in gap_candidates],
        "evidence": ev,
        "evidence_n": len(ev),
        "evidence_state": final_state,
        "by_language": _count(ev, "language"),
        "by_seminar": _count(ev, "seminar_id"),
        "by_authority": _count(ev, "authority_level"),
        "contexts": contexts,
        "source_trace": (source_trace or {}).get("provenance"),
        "citable_passages": all_ids,
        "citation_contract": {
            "rule": ("任何理论性断言都必须引用 citable_passages 里的真实 id，"
                     "格式建议 `[S11 / passage.S11....]`；"
                     "SOURCE_TRACE_INCOMPLETE 的证据引用时必须带告警。"),
            "primary_available": any(e.get("authority_level") == "L1" and
                                     e.get("language") == "fr" for e in ev),
            "recovered_secondary_n": sum(
                1 for e in ev if e.get("trace_status") == "SOURCE_TRACE_INCOMPLETE"),
            "must_not": ["把 recovered 中译当作已闭合的 primary source",
                         "在没有 primary 证据时声称「拉康原文说」"],
        },
        "limitations": limitations,
        "retries_done": retries_done,
    }
    trace = tr.to_dict()
    trace["budget"] = b.report()
    out = {"evidence_pack": pack, "research_trace": trace,
           "budget": b.report(), "seconds": round(time.time() - t0, 2),
           "agent_note": ("Research Agent **不写答案**：它产出证据包与 trace，"
                          "由调用它的 LLM 依据 citable_passages 组织回答。")}
    if save_trace_dir:
        os.makedirs(save_trace_dir, exist_ok=True)
        fn = os.path.join(save_trace_dir,
                          "trace-%s.json" % re.sub(r"\W+", "-", query)[:40])
        json.dump(out, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        out["trace_path"] = fn
    return out


def _count(ev, key):
    out = {}
    for e in ev:
        out[e.get(key)] = out.get(e.get(key), 0) + 1
    return out


def _merge_lanes(a, b):
    """把两次检索的证据合并（按 passage_id 去重），并保留两次的 warnings。"""
    seen, ev = set(), []
    for e in (a.get("evidence") or []) + (b.get("evidence") or []):
        if e["passage_id"] not in seen:
            seen.add(e["passage_id"])
            ev.append(e)
    merged = dict(a)
    merged["evidence"] = ev
    merged["warnings"] = (a.get("warnings") or []) + [
        w for w in (b.get("warnings") or [])
        if w.get("code") not in {x.get("code") for x in (a.get("warnings") or [])}]
    import evidence_sufficiency as es
    payload = {k: merged.get(k) for k in
               ("request", "resolution", "retrieval", "evidence", "coverage",
                "provenance", "warnings", "evidence_state")}
    payload["request"] = merged.get("request") or {}
    merged["evidence_state"] = es.evaluate(payload)
    merged["coverage"] = api._coverage(ev)
    merged["provenance"] = api._provenance_summary(ev)
    merged["retrieval"] = {**(a.get("retrieval") or {}), "merged_lanes": True}
    return merged


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "什么是 objet a？"
    print(json.dumps(research(q), ensure_ascii=False, indent=1)[:6000])
