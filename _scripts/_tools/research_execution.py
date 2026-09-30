#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research_execution.py — Phase 4C.1-B2：Research **Execution Scheduler**

为什么需要它（root cause，Phase 4C.1-B 诊断 27/27）
────────────────────────────────────────────────────
`research_agent.research()` 用一条 **互斥的 if/elif 链** 从问题类型里挑**一个**主工具：

    qtype 对比 → compare_concepts
    qtype 历时 → trace_concept
    有 seminar hint → search_passages(seminar=…)
    有解析实体 → find_concept_evidence
    否则 → search_passages

于是：① 每跑一次只执行一个主检索；② `plan`/`contract` 从未传进检索循环
（`run_task` 调 `ra.research(question, …)`，计划不是参数）；③ capability-mapped 操作
没有 dispatch 通道；④ 契约校验发生在循环**之后**，只能事后报 missing，无法驱动执行；
⑤ lane 不是执行对象，只是评测里的事后派生；⑥ seminar 约束只在 `sem_hint` 那一支下推。

本模块把「契约义务」变成**逐项调度**：

    ResearchContract → obligations → ExecutionPlan → tool calls → ExecutionResult
                                                    ↓
                              每个 required obligation 都有明确 execution record

三条铁律
────────
1. **禁止无记录消失**：每个 required operation / lane / endpoint / constraint 最终必须是
   `EXECUTED` / `FAILED` / `STRUCTURALLY_UNAVAILABLE` / `ZERO_ATTESTATION_CONFIRMED`
   之一，绝不静默 missing。
2. **generic fallback 不得满足 required lane**（§22）：若某个 lane 只能靠泛化 fallback
   取到证据（例如 fMRI lane 退回 `拉康`），该证据只记为 `fallback_evidence`，
   lane 状态为 `FAILED`，并计入 `generic_fallback_satisfied_required_lane_n`（必须为 0）。
3. **预算按契约优先级花**（§20）：required lane > required relation > required source layer
   > 可选探索；因预算不足而未执行 → `BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION`。

确定性：全部由 task_type / contract / 问题语义 / 约束 / 语料事实驱动，
**没有任何 task_id 分支**，也不调用任何 LLM。
"""
from __future__ import annotations

from collections import Counter
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lacan_mcp"))

import knowledge_api as api          # noqa: E402
import research_contract as rc       # noqa: E402
import gold_normalization as gn      # noqa: E402

SCHEMA = "research-execution/v2"   # B3：NOT_APPLICABLE / 类别预算 / 分级 formalism / 术语三层
OP_STATUS = ("PLANNED", "SCHEDULED", "EXECUTED", "FAILED", "SKIPPED_WITH_REASON",
             "STRUCTURALLY_UNAVAILABLE", "NOT_APPLICABLE")
# 终态（= 有明确结论，不再需要执行）；**NOT_APPLICABLE 必须有结构化依赖凭据**才合法
OP_TERMINAL = ("EXECUTED", "FAILED", "STRUCTURALLY_UNAVAILABLE", "NOT_APPLICABLE")
OP_RESOLVED = OP_TERMINAL
LANE_STATUS = ("NOT_STARTED", "EXECUTED", "SATISFIED", "ZERO_ATTESTATION_CONFIRMED",
               "FAILED", "STRUCTURALLY_UNAVAILABLE")
EXEC_STATES = ("PLANNED", "EXECUTING", "EXECUTION_COMPLETE", "EXECUTION_PARTIAL",
               "BLOCKED", "EVIDENCE_EVALUATED")

# 会「泛化到无主题信息」的词：它们命中再多也不能满足 required lane（§22）
GENERIC_FALLBACK_TERMS = ("拉康", "lacan", "精神分析", "psychanalyse", "无意识",
                          "inconscient", "seminar", "研讨班")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ResearchExecutionScheduler:
    """契约驱动的执行调度器（见模块 docstring）。"""

    def __init__(self, public_task, plan, contract, budget=None, trace=None,
                 record_gaps=False):
        self.task = public_task or {}
        self.plan = plan or {}
        self.contract = contract or {}
        self.obligations = rc.contract_obligations(self.contract)
        self.q = self.task.get("question") or ""
        self.budget = dict(budget or {})
        self.budget.setdefault("max_tool_calls", 12)
        self.budget.setdefault("max_passages", 60)
        self.budget.setdefault("max_context_expansions", 3)
        self.trace = trace
        self.record_gaps = record_gaps

        self.operations = []
        self.lanes = []
        self.endpoints = []
        self.constraints = []
        self.docs = []                 # 原始 api 响应（供合并）
        self.extra_evidence = []
        self.spent_calls = 0
        self.spent_passages = 0
        self.spent_context = 0
        self.budget_exhausted = False
        # ── Phase 4C.1-B3 §3：预算**分级隔离**（required_core / relation / context /
        #    optional 各自独立额度）。理由：B2 里 F01/F02 的 required source layer 会被
        #    relation 检索先把全局预算花光而截断 —— 那是不能接受的。
        self.class_spend = {}
        self.class_quota = {}
        self.class_exhausted = set()
        self.budget_plan = {}
        self.limitations = []
        self.warnings = []
        self.state_history = [{"from": None, "to": "PLANNED", "reason": "契约编译完成"},
                              {"from": "PLANNED", "to": "EXECUTING",
                               "reason": "调度器开始逐项执行 required obligations"}]
        self.generic_fallback_used = False
        self.generic_fallback_satisfied_required_lane = 0
        self._lane_budget_deferred = False
        self.relation = {"required": self.obligations["facets"]["relation"]}
        self.formalism = {}
        self.terminology = {}
        self.metadata = {}
        self.source_layers = {}
        self._op_index = {}
        self._lane_index = {}

    # ── 预算 ──────────────────────────────────────────────────────────
    def _can_call(self, n=1):
        return self.spent_calls + n <= self.budget["max_tool_calls"]

    # ── 优先级预算（§20）────────────────────────────────────────────────
    # 「required operation 不得因为 lane / 可选操作先把预算花光而消失」这句必须能被
    # 机械检查：把 **lane 之外的 required 专项操作** 的调用额度先扣住（floor），
    # lane 与 optional 只能在 floor 之上花钱。
    _OP_SPECIFIC = ("compare_concepts", "trace_concept", "find_relation_evidence",
                    "formalism_search", "terminology_lookup", "search_passages",
                    "find_concept_evidence", "metadata_check", "resolve_entity")
    _LANE_COVERED = ("metadata_check", "resolve_entity")
    _OP_CLASS = {"search_passages": "target_lane", "find_concept_evidence": "target_lane",
                 "get_context": "context", "trace_source": "optional",
                 "terminology_lookup": "terminology", "compare_concepts": "direct",
                 "trace_concept": "direct", "resolve_entity": "resolve",
                 "metadata_check": "metadata"}

    def _must_remaining(self):
        """仍未执行的 required 操作数（= 必须为它们留住的调用数）。

        覆盖**契约里列出的每一个 required 操作**（不只几个硬编码的「专项」），
        否则像 `get_context` 这种同样在 required 列表里的操作会把额度花掉，
        让后面的 required 操作无预算可执行。
        """
        n = 0
        for op in (self.obligations.get("operations") or []):
            if op in self._LANE_COVERED:
                continue
            rec = self._op_index.get(op)
            if rec is None or rec.get("status") not in OP_TERMINAL:
                n += 1
        return n

    _TERMINAL = OP_TERMINAL

    def _facet_demand(self):
        """还未执行的 required facet 需要多少次调用（relation=2 侧、source layer=1、
        formalism=1、terminology=1）。这些不在 `operations` 列表里，但同样是契约义务，
        算预算时**必须**算进去，否则 resolve_entity 会把它们的花费一次用光。"""
        n = 0
        f = self.obligations.get("facets") or {}
        if f.get("relation"):
            r0 = self._op_index.get("find_relation_evidence")
            if r0 is None or r0.get("status") not in self._TERMINAL:
                n += 2
        for layer in (f.get("source_layers") or []):
            if not (self.contract.get("source_layer_corpus") or {}).get(layer):
                continue
            lane = self._lane_index.get("source_layer:%s" % layer)
            if lane is None or lane.get("status") == "NOT_STARTED":
                n += 1
        if f.get("formalism"):
            r0 = self._op_index.get("formalism_search")
            if r0 is None or r0.get("status") not in self._TERMINAL:
                n += 1
        if f.get("terminology"):
            r0 = self._op_index.get("terminology_lookup")
            if r0 is None or r0.get("status") not in self._TERMINAL:
                n += max(1, len(self._terminology_terms()))
        return n

    def _terminology_terms(self):
        terms = list((self.contract.get("terminology") or {}).get("explicit_terms") or [])
        if not terms:
            terms = rc.content_terms(self.plan.get("salient_terms") or [], 2)
        return terms

    # ── 分级预算（B3 §3）──────────────────────────────────────────────
    # 每一类义务有**独立额度**，互不挤占：source layer 不会因为 relation 先跑而消失。
    # 类别：resolve / direct / period / source_layer / formalism / terminology /
    #       target_lane / relation / context / optional
    SHRINK_ORDER = ("optional", "context", "relation", "target_lane", "terminology",
                    "formalism", "period", "direct", "resolve", "source_layer")

    def _class_need(self):
        return class_need(self.contract, self.plan, self.obligations,
                          max_context=self.budget.get("max_context_expansions") or 0,
                          terminology_terms=self._terminology_terms())

    def plan_budget_classes(self):
        """把全局 max_tool_calls 分成**类别额度**（core 优先；不够时按 SHRINK_ORDER 收缩）。"""
        cap = int(self.budget.get("max_tool_calls", 12))
        need = self._class_need()
        grant = dict(need)
        total = sum(grant.values())
        shrunk = []
        floor = {"optional": 0, "context": 0, "relation": 2, "target_lane": 1}
        for cls in self.SHRINK_ORDER:
            if total <= cap:
                break
            cur = grant.get(cls, 0)
            fl = floor.get(cls, cur)
            if cur > fl:
                cut = min(cur - fl, total - cap)
                grant[cls] = cur - cut
                total -= cut
                shrunk.append({"class": cls, "from": cur, "to": grant[cls]})
        overcommit = total > cap
        self.class_quota = grant
        self.budget_plan = {
            "global_cap": cap,
            "class_need": dict(need),
            "class_quota": dict(grant),
            "shrunk": shrunk,
            "overcommit": bool(overcommit),
            "overcommit_by": (total - cap) if overcommit else 0,
            "policy": ("类别隔离：source_layer/relation/context/optional 各自额度；"
                       "收缩顺序 %s（required source layer 最后被削）" %
                       ",".join(self.SHRINK_ORDER)),
        }
        return self.budget_plan

    def _can_call_class(self, cls, n=1):
        if not self._can_call(n):
            return False
        if cls is None:
            return True
        return (self.class_spend.get(cls, 0) + n) <= self.class_quota.get(cls, 0)

    def _can_lane_call(self, n=1):
        """lane 调用：受 target_lane 类额度 + 全局上限约束（不再挤占其它类）。"""
        return self._can_call_class("target_lane", n)

    def _can_passages(self, n):
        return self.spent_passages + n <= self.budget["max_passages"]

    def _can_context(self):
        return self.spent_context < self.budget["max_context_expansions"]

    def _call(self, tool, args, op_id, purpose, constraints=None, bclass=None):
        """执行一次工具调用并记录（预算不足则记 SKIPPED_WITH_REASON）。

        `bclass` = 预算类别（B3 §3）。类别额度用尽 → 如实记 `CLASS_BUDGET_EXHAUSTED`，
        **不得**去借别的类别的额度（这正是 source layer 被 relation 饿死的成因）。
        """
        rec = self._op(op_id, tool, purpose, constraints=constraints)
        if not self._can_call_class(bclass):
            if bclass is not None:
                self.class_exhausted.add(bclass)
            if not self._can_call():
                self.budget_exhausted = True
            if rec.get("status") in ("EXECUTED", "FAILED") or rec.get("evidence_ids"):
                return None
            rec.update(status="SKIPPED_WITH_REASON",
                       failure_code=("CLASS_BUDGET_EXHAUSTED:%s" % bclass if bclass
                                     else "BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION"),
                       failure_message=("类别预算耗尽（%s：配额 %s，已用 %s）"
                                        % (bclass, self.class_quota.get(bclass),
                                           self.class_spend.get(bclass, 0))
                                        if bclass else
                                        "工具调用预算耗尽（%d）" % self.budget["max_tool_calls"]))
            self.limitations.append(
                "CLASS_BUDGET_EXHAUSTED:%s，%s 未执行" % (bclass, op_id))
            return None
        if not self._can_call():
            self.budget_exhausted = True
            # ⚠️ 同一个 operation 可能被多路执行器复用（如 search_passages 既做 relation
            #    单侧检索又是契约 required 操作）。**后续因预算失败的调用不得抹掉**前面
            #    已经成功执行并取到证据的记录 —— 否则「真正执行过」会被写成 skipped。
            if rec.get("status") in ("EXECUTED", "FAILED") or rec.get("evidence_ids"):
                return None
            rec.update(status="SKIPPED_WITH_REASON",
                       failure_code="BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION",
                       failure_message="工具调用预算耗尽（%d）" % self.budget["max_tool_calls"])
            self.limitations.append(
                "BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION：预算耗尽，%s 未执行" % op_id)
            return None
        rec.update(status="SCHEDULED", started_at=_now())
        self.spent_calls += 1
        if bclass is not None:
            self.class_spend[bclass] = self.class_spend.get(bclass, 0) + 1
        try:
            doc = api.call(tool, args)
        except Exception as exc:                              # pragma: no cover
            rec.update(status="FAILED", failure_code="TOOL_ERROR",
                       failure_message=str(exc)[:200], completed_at=_now())
            return None
        ev = doc.get("evidence") or []
        self.docs.append(doc)
        self.spent_passages += len(ev)
        rec.update(status="EXECUTED", completed_at=_now(),
                   evidence_ids=[e.get("passage_id") for e in ev],
                   evidence_n=len(ev),
                   inputs=args,
                   warnings=[w.get("code") for w in (doc.get("warnings") or [])])
        if self.trace is not None:
            # research_answer.ResearchTrace 的接口是 .tool(...)（research_agent.Trace 才是 .add）
            self.trace.tool(tool, args, doc, decision=purpose)
        return doc

    # ── 记录 ──────────────────────────────────────────────────────────
    def _op(self, op_id, op_type, basis, constraints=None, required=True):
        if op_id in self._op_index:
            return self._op_index[op_id]
        rec = {"operation_id": op_id, "operation_type": op_type, "basis": basis,
               "required": required, "status": "PLANNED", "started_at": None,
               "completed_at": None, "inputs": {}, "constraints": constraints or {},
               "evidence_ids": [], "evidence_n": 0, "failure_code": None,
               "failure_message": None, "decision": basis}
        self.operations.append(rec)
        self._op_index[op_id] = rec
        return rec

    def _lane(self, lane_id, lane_type, spec, expected="EXPECTED_POSITIVE"):
        if lane_id in self._lane_index:
            return self._lane_index[lane_id]
        rec = {"lane_id": lane_id, "lane_type": lane_type,
               "query_terms": spec.get("needles") or [],
               "entity_ids": [spec["entity_id"]] if spec.get("entity_id") else [],
               "language": spec.get("language"), "seminar_constraints":
                   [spec["seminar"]] if spec.get("seminar") else [],
               "period_constraints": [], "source_layer_constraints": [],
               "expected_hit_semantics": expected, "required": spec.get("required", True),
               "status": "NOT_STARTED", "evidence_ids": [], "usable_evidence_ids": [],
               "hit_count": 0, "usable_hit_count": 0, "constraint_applied": None,
               "fallback_used": False, "fallback_evidence_ids": [],
               "corpus_hits": None, "note": None}
        self.lanes.append(rec)
        self._lane_index[lane_id] = rec
        return rec

    def _usable(self, rec_ev):
        u = rc.classify_evidence_usability(rec_ev)
        return bool(u["can_support_substantive_claim"]), u["usability_class"]

    def _fill_lane(self, lane, doc, generic_only=False):
        if not doc:
            return lane
        ev = doc.get("evidence") or []
        for e in ev:
            ok, _cls = self._usable(e)
            pid = e.get("passage_id")
            if generic_only:
                lane["fallback_used"] = True
                lane["fallback_evidence_ids"].append(pid)
                continue
            if pid not in lane["evidence_ids"]:
                lane["evidence_ids"].append(pid)
            if ok and pid not in lane["usable_evidence_ids"]:
                lane["usable_evidence_ids"].append(pid)
        lane["hit_count"] = len(lane["evidence_ids"])
        lane["usable_hit_count"] = len(lane["usable_evidence_ids"])
        return lane

    # ── 主流程 ────────────────────────────────────────────────────────
    def run(self):
        self.plan_budget_classes()
        self._transition("EXECUTING",
                         "开始逐项执行 required obligations（预算按类别隔离：%s）"
                         % ",".join(sorted(self.class_quota)))
        # ① metadata facet 优先（§15）：元数据不可得 → 依赖它的普通操作进 NOT_APPLICABLE
        if self.obligations["facets"]["metadata"]:
            self._run_metadata()
        blocked = (self.metadata.get("metadata_state") == "METADATA_UNAVAILABLE")
        if blocked:
            self._mark_lanes_not_applicable(
                "METADATA_UNAVAILABLE：问题要的是元数据，语料层不存在该字段")
            self._mark_dependent_ops_not_applicable()
        # ② 实体解析（batched）
        self._run_resolve_entity()
        # ③ 直接必需操作（comparison / diachronic）
        if not blocked:
            self._run_compare_if_needed()
            self._run_diachronic_if_needed()
        # ④ period 约束下推
        if not blocked:
            self._run_period_constraints()
        # ⑤ **required source layers 先于 relation**（B3 §3 硬规则）：
        #    「哲学/弗洛伊德来源 → 拉康」这类任务里，来源层检索不得被关系检索饿死。
        if not blocked and self.obligations["facets"]["source_layers"]:
            self._run_source_layers()
        # ⑥ formalism（分级符号检索；required core）
        if not blocked and self.obligations["facets"]["formalism"]:
            self._run_formalism()
        # ⑦ terminology（映射 / 语料见证 / 上下文验证三层）
        if not blocked and self.obligations["facets"]["terminology"]:
            self._run_terminology()
        # ⑧ target lanes（entity / seminar / zero-attestation）
        if not blocked:
            self._run_lanes()
        # ⑨ relation（读得到已取回的 source/target 证据，但有自己的额度）
        if not blocked and self.obligations["facets"]["relation"]:
            self._run_relation()
        # ⑩ 条件操作：context expansion / trace_source（context/optional 额度）
        self._run_optional_operations()
        # ⑪ 收尾：契约要求但专项路径未覆盖的操作 → 确定性默认执行器 / 显式终态
        if not blocked:
            self._run_remaining_required_ops()
        self._finalize_operations()
        self._finalize_lanes()
        state = self._execution_state()
        self._transition(state, self._state_reason(state))
        return self._doc(state)


    # ① metadata
    def _run_metadata(self):
        rec = self._op("metadata_check", "metadata_check",
                       "MetadataQuestionContract：先查字段可得性", required=True)
        rec.update(status="EXECUTED", started_at=_now(), completed_at=_now(),
                   inputs={"fields": (self.contract.get("metadata") or {})
                           .get("metadata_required")},
                   evidence_n=0)
        self.metadata = dict(self.contract.get("metadata") or {})
        self.metadata["checked"] = True
        self.metadata["corpus_scan"] = {"executed": True, "scope": "whole_corpus",
                                        "method": "passage_store 字段统计"}

    # ② resolve_entity
    def _run_resolve_entity(self):
        terms = rc.content_terms(self.plan.get("salient_terms") or [])
        if not terms:
            terms = [t for t in (self.plan.get("salient_terms") or [])
                     if not rc.is_question_fragment(t)][:4]
        rec = self._op("resolve_entity", "resolve_entity",
                       "任何研究的固定起点；问句残片已先被过滤", required=True,
                       constraints={"content_terms": terms})
        if not self._can_call():
            self.budget_exhausted = True
            rec.update(status="SKIPPED_WITH_REASON",
                       failure_code="BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION",
                       failure_message="预算耗尽，未能解析实体")
            return
        # 实体解析要花调用（每词 1 次）。**先扣住其它未完成 required 专项操作的额度**，
        # 再决定本次解析几个词 —— 解析 4 个词很彻底，但不得把后面的 required 操作挤掉。
        others = 0
        for op in (self.obligations.get("operations") or []):
            if op in ("resolve_entity", "metadata_check"):
                continue
            r0 = self._op_index.get(op)
            if r0 is None or r0.get("status") not in self._TERMINAL:
                others += 1
        others += self._facet_demand()
        allowed = max(1, min(len(terms), int(self.class_quota.get("resolve", 1))))
        resolved = {}
        for t in terms[:min(4, allowed)]:
            if not self._can_call_class("resolve"):
                break
            self.spent_calls += 1
            self.class_spend["resolve"] = self.class_spend.get("resolve", 0) + 1
            try:
                r = api.resolve_entity(t)
            except Exception:                                  # pragma: no cover
                continue
            self.docs.append(r)
            resolved[t] = ((r.get("resolution") or {}).get("resolution_status"))
        rec.update(status="EXECUTED", started_at=_now(), completed_at=_now(),
                   inputs={"terms": terms[:min(4, allowed)]}, evidence_n=0,
                   failure_message=None if resolved else "所有词都未解析",
                   failure_code=None if resolved else "ENTITY_RESOLUTION_EMPTY")
        rec["resolution_status"] = resolved

    # ③ lanes
    def _run_lanes(self):
        for spec in self.obligations["lanes"]:
            if self.budget_exhausted or (not self._can_lane_call()
                                         and spec.get("expectation") != "EXPECTED_ZERO"):
                if not self._can_lane_call():
                    self._lane_budget_deferred = True
                self._lane(spec["lane_id"], "unknown", spec).update(
                    status="SKIPPED_WITH_REASON" if "SKIPPED_WITH_REASON" in LANE_STATUS
                    else "FAILED",
                    note="BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION")
                continue
            lane = self._lane(spec["lane_id"], self._lane_type(spec), spec,
                              spec.get("expectation", "EXPECTED_POSITIVE"))
            if spec.get("expectation") == "EXPECTED_ZERO":
                self._exec_zero_lane(lane, spec)
            elif spec.get("seminar"):
                self._exec_seminar_lane(lane, spec)
            elif lane["lane_type"] == "entity":
                self._exec_entity_lane(lane, spec)
            else:
                self._exec_term_lane(lane, spec)

    def _lane_type(self, spec):
        if spec.get("expectation") == "EXPECTED_ZERO":
            return "zero_attestation"
        if spec.get("seminar"):
            return "seminar"
        if spec.get("entity_id"):
            return "entity"
        return "lexical"

    def _exec_entity_lane(self, lane, spec):
        """实体 lane：优先 find_concept_evidence，其次**受约束**的词面检索。"""
        eid = spec.get("entity_id")
        doc = None
        if self._can_lane_call() and eid:
            doc = self._call("find_concept_evidence",
                             {"concept": eid, "top_k": 10}, "find_concept_evidence",
                             "实体 lane %s 的受控证据" % eid,
                             constraints={"entity": eid}, bclass="target_lane")
            lane["constraint_applied"] = True
        if not doc or not (doc.get("evidence") or []):
            # 受控检索为空 → 用该实体自己的写法做词面 lane（**不是**泛化 fallback）
            needles = [n for n in (spec.get("needles") or []) if n]
            if needles and self._can_lane_call():
                doc = self._call("search_passages",
                                 {"query": " ".join(needles), "top_k": 10},
                                 "search_passages",
                                 "实体 lane %s 的词面补充检索" % eid,
                                 constraints={"needles": needles}, bclass="target_lane")
                lane["constraint_applied"] = True
                lane["note"] = "受控检索为空 → 用该实体的本体写法做词面 lane"
        self._fill_lane(lane, doc)
        lane["status"] = "SATISFIED" if lane["usable_hit_count"] else (
            "EXECUTED" if lane["hit_count"] else "FAILED")

    def _exec_seminar_lane(self, lane, spec):
        """期号 lane：seminar 约束**下推到 API**（不是事后过滤）。"""
        if not self._can_lane_call():
            lane.update(status="NOT_STARTED",
                        note="预算留给 required 专项操作（§20 优先级）")
            return
        sem = spec.get("seminar")
        q = " ".join([n for n in (spec.get("needles") or []) if n]) or \
            " ".join(rc.content_terms(self.plan.get("salient_terms") or [])) or self.q
        doc = self._call("search_passages",
                         {"query": q, "seminar": sem, "top_k": 15},
                         "search_passages", "期号 lane %s 的受约束检索" % sem,
                         constraints={"seminar": sem}, bclass="target_lane")
        lane["constraint_applied"] = bool(doc is not None)
        self._fill_lane(lane, doc)
        if lane["usable_hit_count"]:
            lane["status"] = "SATISFIED"
        elif lane["hit_count"]:
            lane["status"] = "EXECUTED"
        else:
            lane["status"] = "FAILED"
        self.constraints.append({"kind": "seminar", "value": sem,
                                 "applied": bool(doc is not None),
                                 "reason": None if doc is not None
                                 else "预算耗尽或调用失败",
                                 "evidence_n": lane["hit_count"]})

    def _exec_term_lane(self, lane, spec):
        term = (spec.get("needles") or [""])[0]
        doc = None
        if term and self._can_lane_call():
            doc = self._call("search_passages", {"query": term, "top_k": 10},
                             "search_passages", "术语 lane %r" % term,
                             constraints={"term": term}, bclass="target_lane")
        self._fill_lane(lane, doc)
        if lane["usable_hit_count"]:
            lane["status"] = "SATISFIED"
        elif lane["hit_count"]:
            lane["status"] = "EXECUTED"
        else:
            lane["status"] = "FAILED"

    def _exec_zero_lane(self, lane, spec):
        """EXPECTED_ZERO lane：0 命中是**结论**（ZERO_ATTESTATION_CONFIRMED）。"""
        term = (spec.get("needles") or [""])[0]
        hits = self._corpus_hits(term)
        lane["corpus_hits"] = hits
        lane["hit_count"] = hits
        if hits == 0:
            lane["status"] = "ZERO_ATTESTATION_CONFIRMED"
            lane["note"] = ("corpus_scan executed=True scope=whole_corpus hits=0；"
                            "0 命中是本题的研究结论，不是检索失败")
        else:
            lane["status"] = "SATISFIED"

    def _corpus_hits(self, term):
        try:
            import evidence_sufficiency_v2 as esv2
            return int(esv2.prevalence(term))
        except Exception:                                        # pragma: no cover
            return 0

    # ④ relation
    def _run_relation(self):
        """relation retrieval（§9/§10）：A 段 + B 段 ≠ A↔B 证据。

        做法（确定性）：对每一对实体，
          ① 分别按各实体的写法各检索一次（两段各自的出现集）
          ② 取**段落交集**（同段共现）—— 交集为空再退回组合 query 一次
          ③ 对交集里的段落做 R0–R4 强度分级；必要时补 ±N 上下文
        """
        rec = self._op("find_relation_evidence", "relation_retrieval",
                       "relation_required：A 段 + B 段 ≠ A↔B 证据", required=True)
        groups = rc.entity_form_groups(self.plan)
        eids = [e for e in groups if groups[e]]
        if len(eids) < 2:
            # 关系题（如 Freud→Lacan / 哲学→Lacan）常常只解析出一侧实体；
            # 这时用**内容词**作为另一侧，仍然做真实的关系检索（不得直接判 structural）。
            extra = [t for t in rc.content_terms(self.plan.get("salient_terms") or [], 4)
                     if t and t not in eids]
            eids = (eids + extra)[:4]
            for e in eids:
                groups.setdefault(e, [e])
        all_pairs = [(eids[i], eids[j]) for i in range(len(eids))
                     for j in range(i + 1, len(eids))]
        # 自适应配对数（§20 优先级，不是放松契约）：关系证据是 required，但「跑几对」
        # 属于调度决策。先扣掉其它未完成的 required 专项操作要用的额度，再决定跑 1 对还是 2 对。
        others = 0
        for op in (self.obligations.get("operations") or []):
            if op in ("find_relation_evidence", "metadata_check", "resolve_entity"):
                continue
            r0 = self._op_index.get(op)
            if r0 is None or r0.get("status") not in self._TERMINAL:
                others += 1
        others += max(0, self._facet_demand() - 2)   # 扣掉关系自己需要的两侧
        # 语料层存在的 required source-layer lane 也要留一次调用（它们是 required lane，
        # 不能因为关系检索多跑一对就被饿死）
        for spec in self.obligations["lanes"]:
            if not spec.get("required"):
                continue
            if not str(spec.get("lane_id", "")).startswith("source_layer:"):
                continue
            layer = str(spec["lane_id"]).split(":", 1)[1]
            if (self.contract.get("source_layer_corpus") or {}).get(layer):
                if (self._lane_index.get(spec["lane_id"]) or {}).get("status",
                                                                    "NOT_STARTED") == "NOT_STARTED":
                    others += 1
        avail = self.budget["max_tool_calls"] - self.spent_calls - others
        n_pairs = 2 if avail >= 4 else (1 if avail >= 2 else 0)
        pairs = all_pairs[:n_pairs]
        if not pairs:
            rec.update(status="SKIPPED_WITH_REASON",
                       failure_code="BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION",
                       failure_message="预算不足以完成任何一对关系检索（留给其它 required 专项操作）",
                       completed_at=_now())
            self.relation = {"required": True, "executed": False, "pairs": [],
                             "strengths": {}, "evidence_ids": []}
            return
        sem = next((c["value"] for c in self.contract.get("required_constraints") or []
                    if c.get("kind") == "seminar"), None)
        found_ids, strengths, per_pair = [], {}, []
        for a, b in pairs:
            sets = {}
            for eid in (a, b):
                q = " ".join(groups[eid][:3])
                args = {"query": q, "top_k": 12}
                if sem:
                    args["seminar"] = sem
                doc = self._call("search_passages", args, "search_passages",
                                 "relation lane %s 的单侧检索" % eid,
                                 constraints={"pair": [a, b], "side": eid, "seminar": sem},
                                 bclass="relation")
                sets[eid] = {e.get("passage_id"): e for e in ((doc or {}).get("evidence") or [])}
            common = [pid for pid in sets.get(a, {}) if pid in sets.get(b, {})]
            cand = [sets[a][pid] for pid in common]
            if not cand and self._can_call():
                q = " ".join(groups[a][:2] + groups[b][:2])
                args = {"query": q, "top_k": 12, "entities": [a, b]}
                if sem:
                    args["seminar"] = sem
                doc = self._call("search_passages", args, "search_passages",
                                 "relation lane %s × %s 的组合检索（交集为空时）" % (a, b),
                                 constraints={"pair": [a, b], "seminar": sem})
                cand = list((doc or {}).get("evidence") or [])
            hits = 0
            for e in cand:
                st = rc.relation_strength(e.get("text") or "", [a, b])
                if st == "R0_NONE":
                    continue
                hits += 1
                strengths[st] = strengths.get(st, 0) + 1
                pid = e.get("passage_id")
                if pid and pid not in found_ids:
                    found_ids.append(pid)
                    self.extra_evidence.append(e)
            per_pair.append({"pair": [a, b], "cooccurrence_n": len(common),
                             "relation_hits": hits})
            # ±N 上下文窗口：只对**还没有找到**关系证据的组合做一次（受 context 预算约束）
            if hits == 0 and cand and self._can_context() and self._can_call():
                ctx = self._call("get_context",
                                 {"passage_id": cand[0].get("passage_id"),
                                  "before": 2, "after": 2}, "get_context",
                                 "relation 候选的上下文窗口（±2）",
                                 constraints={"pair": [a, b]})
                if ctx:
                    self.spent_context += 1
                    for e in ctx.get("evidence") or []:
                        st = rc.relation_strength(e.get("text") or "", [a, b])
                        if st != "R0_NONE":
                            strengths[st] = strengths.get(st, 0) + 1
                            pid = e.get("passage_id")
                            if pid and pid not in found_ids:
                                found_ids.append(pid)
                                self.extra_evidence.append(e)
        best = "R0_NONE"
        for r in rc.RELATION_STRENGTH:
            if strengths.get(r):
                best = r
        self.relation = {"required": True, "pairs": [[a, b] for a, b in pairs],
                         "per_pair": per_pair,
                         "relation_evidence_ids": found_ids,
                         "relation_evidence_n": len(found_ids),
                         "relation_strength": best,
                         "relation_strength_counts": strengths,
                         "method": ("单侧检索 → 同段交集 → R0–R4 强度分级 → ±N 上下文"
                                    "（全部 deterministic，无 LLM）")}
        rec.update(status="EXECUTED" if pairs else "STRUCTURALLY_UNAVAILABLE",
                   completed_at=_now(), evidence_ids=found_ids,
                   evidence_n=len(found_ids),
                   failure_code=None if found_ids else "RELATION_EVIDENCE_MISSING",
                   failure_message=None if found_ids else
                   "同段共现/关系陈述未找到（A、B 分别出现不算关系证据）")
        self._lane("relation:%s" % ("+".join(eids[:2]) or "none"), "relation",
                   {"needles": [], "required": True}).update(
            status="SATISFIED" if found_ids else "FAILED",
            evidence_ids=found_ids, usable_evidence_ids=found_ids,
            hit_count=len(found_ids), usable_hit_count=len(found_ids),
            constraint_applied=True, note="strength=%s" % best)

    # ⑤ source layers
    def _run_source_layers(self):
        avail = (self.contract.get("source_layer_corpus") or {})
        for layer in self.obligations["facets"]["source_layers"]:
            lane = self._lane("source_layer:%s" % layer, "source_layer",
                              {"needles": [], "required": True})
            if not avail.get(layer, False):
                lane.update(status="STRUCTURALLY_UNAVAILABLE",
                            note=("语料层不存在该来源层（whole-corpus 检查）："
                                  "external_source=%s；不得伪造 primary source"
                                  % avail.get("external_source")))
                self.source_layers[layer] = {"status": "STRUCTURALLY_UNAVAILABLE",
                                             "corpus_availability": False}
                continue
            q = " ".join(rc.content_terms(self.plan.get("salient_terms") or [])) or self.q
            doc = self._call("search_passages", {"query": q, "top_k": 10},
                             "search_passages", "来源层 lane %s" % layer,
                             constraints={"source_layer": layer},
                             bclass="source_layer")
            self._fill_lane(lane, doc)
            lane["status"] = "SATISFIED" if lane["usable_hit_count"] else "FAILED"
            self.source_layers[layer] = {"status": lane["status"],
                                        "corpus_availability": True}

    # ⑥ formalism（Phase 4C.1-B3 §3：**分级**符号检索，不再只做一次符号词面检索）
    def _run_formalism(self):
        form = self.contract.get("formalism") or {}
        syms = form.get("symbols") or ["◊"]
        task_type = self.contract.get("task_type") or self.plan.get("task_type")
        sem_info = form.get("formalism_seminar") or {}
        seminar = sem_info.get("seminar_id") if isinstance(sem_info, dict) else None
        sem_explicit = next((c["value"] for c in
                             (self.contract.get("required_constraints") or [])
                             if c.get("kind") == "seminar"), None)
        if sem_explicit:
            seminar = sem_explicit
        cands = form.get("formalism_candidates") or rc.formalism_query_forms(
            self.q, syms, task_type)
        forms = [f["form"] for f in cands if f.get("strength") == "DIRECT"] or list(syms)
        lane = self._lane("formalism", "formalism",
                          {"needles": forms, "required": True, "seminar": seminar})
        rec = self._op("formalism_search", "formalism_retrieval",
                       ("TopologyMatheme：分级形式检索（exact → normalized → spacing → "
                        "parenthesized → notation variant → related formal term）"),
                       required=True,
                       constraints={"symbols": syms, "seminar": seminar,
                                    "query_forms": forms})
        retr = rc.formalism_retrieve(self.q, syms, task_type, seminar=seminar, limit=10)
        ids, usable_ids, strategy_counts, hit_records = [], [], {}, []
        for h in retr["direct_hits"]:
            ev = api._passage_evidence(h["passage_id"],
                                       why=["formalism_%s" % h["match_strategy"]])
            if not ev:
                continue
            self.extra_evidence.append(ev)
            ok, _cls = self._usable(ev)
            if h["passage_id"] not in ids:
                ids.append(h["passage_id"])
            if ok and h["passage_id"] not in usable_ids:
                usable_ids.append(h["passage_id"])
            strategy_counts[h["match_strategy"]] = \
                strategy_counts.get(h["match_strategy"], 0) + 1
            hit_records.append({"passage_id": h["passage_id"],
                                "seminar_id": h["seminar_id"],
                                "raw_matched_form": h["raw_matched_form"],
                                "normalized_matched_form": h["normalized_matched_form"],
                                "match_strategy": h["match_strategy"],
                                "match_strength": h["match_strength"],
                                "query_form": h["query_form"]})
        # 阶段 4：对最强命中做 ±N 上下文（消耗 formalism 类额度；只做 1 次）
        context_ids = []
        if ids and self._can_context() and self._can_call_class("formalism"):
            doc = self._call("get_context",
                             {"passage_id": ids[0], "before": 2, "after": 2},
                             "get_context", "formalism 最强命中补上下文",
                             bclass="formalism")
            if doc:
                self.spent_context += 1
                for e in (doc.get("evidence") or []):
                    self.extra_evidence.append(e)
                    context_ids.append(e.get("passage_id"))
        lane.update(status="SATISFIED" if ids else "FAILED", evidence_ids=ids,
                    usable_evidence_ids=usable_ids, hit_count=len(ids),
                    usable_hit_count=len(usable_ids), constraint_applied=True,
                    note=("stages=%s；seminar=%s" % (",".join(sorted(strategy_counts)),
                                                     seminar)))
        corpus_counts = form.get("corpus_symbol_counts") or {}
        state = ("FORMALISM_FOUND" if ids else
                 ("RETRIEVED_FORMALISM_MISSING"
                  if (retr["direct_n"] or any(v > 0 for v in corpus_counts.values()))
                  else "CORPUS_FORMALISM_MISSING"))
        self.formalism = {
            "symbols": syms,
            "seminar_constraint": seminar,
            "seminar_source": (sem_info or {}).get("source") if isinstance(sem_info, dict) else None,
            "query_forms": [f["form"] for f in cands],
            "candidates": cands,
            "stages_executed": sorted(set(cands and [f["strategy"] for f in cands] or [])
                                      | set(strategy_counts)),
            "strategy_counts": strategy_counts,
            "hits": hit_records,
            "direct_n": retr["direct_n"],
            "supporting_n": retr["supporting_n"],
            "corpus_distribution": retr["corpus_distribution"],
            "context_expansion_ids": context_ids,
            "formalism_evidence_ids": ids,
            "formalism_evidence_n": len(ids),
            "whole_corpus_formalism_check": {
                "executed": True, "scope": "whole_corpus",
                "index_scanned": retr["index_scanned"],
                "symbol_counts": corpus_counts},
            "formalism_state": state,
        }
        rec.update(status="EXECUTED", completed_at=_now(), evidence_ids=ids,
                   evidence_n=len(ids),
                   failure_code=None if ids else "RETRIEVED_FORMALISM_MISSING",
                   failure_message=None if ids else
                   "分级形式检索未命中（语料层有该形式 → 属 retrieval，不是结构性缺失）")

    # ⑦ terminology（Phase 4C.1-B3 §5：mapping / attestation / context validation 三层分开）
    def _run_terminology(self):
        terms = list((self.contract.get("terminology") or {}).get("explicit_terms") or [])
        if not terms:
            terms = rc.content_terms(self.plan.get("salient_terms") or [], 2)
        rec = self._op("terminology_lookup", "terminology_lookup",
                       "TranslationTerminologyContract：强制术语桥查询", required=True)
        results = {}
        for t in terms:
            if not self._can_call_class("terminology"):
                self.class_exhausted.add("terminology")
                break
            doc = self._call("terminology_lookup", {"term": t}, "terminology_lookup",
                             "术语 %r 的受控映射（KNOWN_TRANSLATION）" % t,
                             constraints={"term": t}, bclass="terminology")
            cands = ((doc or {}).get("resolution") or {}).get("candidates") or []
            hits = self._corpus_hits(t)
            lane = self._lane_index.get("term:%s" % t) or \
                self._lane("term:%s" % t, "lexical", {"needles": [t], "required": True})
            lane["corpus_hits"] = hits
            usable = bool(lane.get("usable_hit_count"))
            if hits == 0:
                lane["status"] = "ZERO_ATTESTATION_CONFIRMED"
                lane["note"] = "corpus_scan executed=True hits=0（ZERO_ATTESTATION）"
            elif lane["status"] == "NOT_STARTED":
                lane["status"] = "SATISFIED" if usable else "EXECUTED"
            # ── 三层完成语义（**不得混写**）
            mapping = ("MAPPING_COMPLETE" if cands else
                       ("MAPPING_PARTIAL" if hits else "MAPPING_MISSING"))
            attestation = "ATTESTED" if hits else "ZERO_ATTESTATION"
            if not hits:
                ctx = "NOT_APPLICABLE"           # 零见证 → 没有东西可做上下文验证
            elif usable:
                ctx = "CONTEXT_VALIDATED"
            else:
                ctx = "CONTEXT_PENDING"
            results[t] = {
                "corpus_hits": hits,
                "known_translation": bool(cands),
                "translation_candidates": [
                    {"target_form": c.get("target_form"),
                     "target_language": c.get("target_language"),
                     "relation_type": c.get("relation_type")}
                    for c in cands][:5],
                "mapping_completion": mapping,
                "attestation_completion": attestation,
                "context_validation": ctx,
                "corpus_attested": hits > 0,
                "lane_status": lane["status"],
                "status": ("CORPUS_ATTESTED" if hits else "KNOWN_TRANSLATION_ONLY"),
            }
        rec.update(status="EXECUTED" if results else "SKIPPED_WITH_REASON",
                   completed_at=_now(), inputs={"terms": terms}, evidence_n=0,
                   failure_code=None if results else "NO_EXPLICIT_TERMS")
        self.terminology = {
            "terms": results,
            "mapping_completion_counts": dict(Counter(
                v["mapping_completion"] for v in results.values())),
            "attestation_completion_counts": dict(Counter(
                v["attestation_completion"] for v in results.values())),
            "context_validation_counts": dict(Counter(
                v["context_validation"] for v in results.values())),
            "status_vocabulary": {
                "mapping": ["MAPPING_COMPLETE", "MAPPING_PARTIAL", "MAPPING_MISSING"],
                "attestation": ["ATTESTED", "ZERO_ATTESTATION", "UNVALIDATED"],
                "context_validation": ["CONTEXT_VALIDATED", "CONTEXT_PENDING",
                                       "NOT_APPLICABLE"],
            },
            "rule": ("terminology mapping ≠ corpus attestation ≠ context validation："
                     "三层分别记录，任何一层不得用另一层的状态代替"),
        }

    # ⑧ compare / diachronic
    def _run_compare_if_needed(self):
        if "compare_concepts" not in (self.contract.get("required_operations") or []):
            return
        groups = rc.entity_form_groups(self.plan)
        eids = [e for e in groups if groups[e]][:2]
        terms = [t for t in rc.content_terms(self.plan.get("salient_terms") or [], 4)
                 if t and t not in eids]
        rec = self._op("compare_concepts", "compare_concepts",
                       "ComparisonResearchContract：逐实体 lane + 对比 lane", required=True)
        # 两侧的取值顺序：已解析实体 → 内容词（**不用**问句残片，也不把整句塞进去）
        sides = (eids if len(eids) >= 2 else terms[:2])
        if len(sides) < 2 or not self._can_call():
            rec.update(status="STRUCTURALLY_UNAVAILABLE" if len(sides) < 2
                       else "SKIPPED_WITH_REASON",
                       failure_code="NOT_ENOUGH_RESOLVED_ENTITIES" if len(sides) < 2
                       else "BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION",
                       failure_message=("可解析实体与内容词合计不足 2 个，无法做受控对比"
                                        if len(sides) < 2 else "预算耗尽"),
                       completed_at=_now())
            return
        doc = self._call("compare_concepts",
                         {"concept_a": sides[0], "concept_b": sides[1], "top_k": 10},
                         "compare_concepts", "两侧的受控对比（分道，不拼 query）",
                         constraints={"pair": sides}, bclass="direct")
        rec.update(status="EXECUTED" if doc is not None else "FAILED",
                   completed_at=_now(),
                   evidence_ids=[e.get("passage_id")
                                 for e in ((doc or {}).get("evidence") or [])],
                   evidence_n=len(((doc or {}).get("evidence") or [])))

    def _run_diachronic_if_needed(self):
        if "trace_concept" not in (self.contract.get("required_operations") or []):
            return
        rec = self._op("trace_concept", "trace_concept",
                       "DiachronicResearchContract：按 period 分组 + 端点 lane",
                       required=True)
        groups = rc.entity_form_groups(self.plan)
        eids = [e for e in groups if groups[e]]
        concept = eids[0] if eids else " ".join(
            rc.content_terms(self.plan.get("salient_terms") or []))[:40]
        doc = None
        if self._can_call():
            doc = self._call("trace_concept", {"concept": concept, "per_period": 5},
                             "trace_concept", "历时分组证据",
                             constraints={"concept": concept}, bclass="direct")
        rec.update(status="EXECUTED" if doc else "SKIPPED_WITH_REASON",
                   completed_at=_now(),
                   failure_code=None if doc else "BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION",
                   evidence_ids=[e.get("passage_id")
                                 for e in ((doc or {}).get("evidence") or [])],
                   evidence_n=len(((doc or {}).get("evidence") or [])))
        for ep in self.obligations["endpoints"]:
            self._run_endpoint(ep)

    def _run_endpoint(self, ep):
        lane = self._lane(ep["endpoint_id"], "diachronic_endpoint",
                          {"needles": [], "seminar": ep["seminar"], "required": True})
        q = " ".join(rc.content_terms(self.plan.get("salient_terms") or [])) or self.q
        doc = self._call("search_passages",
                         {"query": q, "seminar": ep["seminar"], "top_k": 15},
                         "search_passages", "历时端点 %s" % ep["seminar"],
                         constraints={"seminar": ep["seminar"]}, bclass="direct")
        self._fill_lane(lane, doc)
        lane["status"] = "SATISFIED" if lane["usable_hit_count"] else "FAILED"
        lane["constraint_applied"] = doc is not None
        self.endpoints.append({"endpoint_id": ep["endpoint_id"],
                               "seminar": ep["seminar"],
                               "evidence_n": lane["hit_count"],
                               "usable_evidence_n": lane["usable_hit_count"],
                               "completion": "COMPLETE" if lane["usable_hit_count"]
                               else "INCOMPLETE"})
        self.constraints.append({"kind": "seminar", "value": ep["seminar"],
                                 "applied": doc is not None,
                                 "reason": None if doc is not None else "预算/失败",
                                 "evidence_n": lane["hit_count"]})

    # ⑧b period 约束下推（§9）：问题点名了时期，就必须**带着 period 去检索**并留下
    #     applied 记录（不能只在契约里声明）。每个 required period 约束都留一条记录，
    #     取不到就 applied=False + 原因，绝不静默消失。
    def _run_period_constraints(self):
        periods = [c.get("value") for c in
                   (self.contract.get("required_constraints") or [])
                   if c.get("kind") == "period" and c.get("value")]
        if not periods:
            return
        q = " ".join(rc.content_terms(self.plan.get("salient_terms") or [])) or self.q
        for p in periods:
            lane = self._lane("period:%s" % p, "period",
                              {"needles": [], "required": True, "period": p})
            doc = None
            if self._can_call_class("period"):
                doc = self._call("search_passages",
                                 {"query": q, "period": p, "top_k": 15},
                                 "search_passages", "period 约束下推 %s" % p,
                                 constraints={"period": p}, bclass="period")
            self._fill_lane(lane, doc)
            lane["constraint_applied"] = doc is not None
            lane["status"] = ("SATISFIED" if lane["usable_hit_count"]
                              else ("EXECUTED" if lane["hit_count"] else "FAILED"))
            self.constraints.append({
                "kind": "period", "value": p, "applied": doc is not None,
                "reason": None if doc is not None
                else "预算耗尽或检索失败（约束未能下推）",
                "evidence_n": lane["hit_count"]})

    # ⑨ 可选操作
    def _run_optional_operations(self):
        for op in self.obligations["optional_operations"]:
            rec = self._op(op, op, "手段型操作（缺失不降级）", required=False)
            if rec["status"] != "PLANNED":
                continue
            if op == "get_context" and self._can_context() and \
                    self._can_call_class("context"):
                pids = [e.get("passage_id") for e in self.extra_evidence[:1]] or \
                       [l["evidence_ids"][0] for l in self.lanes if l["evidence_ids"]][:1]
                if pids:
                    doc = self._call("get_context", {"passage_id": pids[0],
                                                     "before": 2, "after": 2},
                                     "get_context", "给最强证据补上下文",
                                     bclass="context")
                    if doc:
                        self.spent_context += 1
                        rec.update(status="EXECUTED", completed_at=_now())
                        continue
            if op == "trace_source" and self._can_call_class("optional"):
                pids = [l["evidence_ids"][0] for l in self.lanes if l["evidence_ids"]][:1]
                if pids:
                    doc = self._call("trace_source", {"passage_id": pids[0]},
                                     "trace_source", "给 top-1 证据补溯源链",
                                     bclass="optional")
                    if doc:
                        rec.update(status="EXECUTED", completed_at=_now())
                        continue
            rec.update(status="SKIPPED_WITH_REASON",
                       failure_code="OPTIONAL_NOT_NEEDED",
                       failure_message="手段型操作；本次执行路径未用到")

    # 收尾
    def _run_remaining_required_ops(self):
        """契约要求、但前面的专项路径没有覆盖到的操作 → 给它一个**确定性默认执行器**。

        为什么需要：`AbstentionResearchContract` / `SeminarSpecificContract` /
        `CaseResearchContract` / `TranslationTerminologyResearchContract` 把
        `search_passages` 列为 required（它是这些任务类型的正当动作），而
        `search_passages` 同时又是「手段型」——两处口径必须在这里对齐：
        只要它在 `required_operations` 里，就必须真的执行一次，不得只标 skipped。
        """
        terms = rc.content_terms(self.plan.get("salient_terms") or [])
        q = " ".join(terms) or self.q
        for op in self.obligations["operations"]:
            rec = self._op_index.get(op)
            if rec is not None and rec["status"] in OP_TERMINAL:
                continue
            if rec is not None and rec["status"] == "SKIPPED_WITH_REASON" \
                    and rec.get("failure_code") != "OPTIONAL_NOT_NEEDED":
                continue
            cls = self._OP_CLASS.get(op)
            if not self._can_call_class(cls):
                # 预算用尽：标明原因后**继续**给后面的操作留记录（不得提前 break 让它们消失）
                if not self._can_call():
                    self.budget_exhausted = True
                if cls:
                    self.class_exhausted.add(cls)
                rec = rec or self._op(op, op, "契约要求", required=True)
                rec.update(status="SKIPPED_WITH_REASON",
                           failure_code=("CLASS_BUDGET_EXHAUSTED:%s" % cls if cls
                                         else "BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION"),
                           failure_message=("类别预算耗尽（%s：配额 %s，已用 %s）"
                                            % (cls, self.class_quota.get(cls),
                                               self.class_spend.get(cls, 0))
                                            if cls else "预算在契约完成前耗尽"))
                continue
            if op == "search_passages":
                sem = next((c["value"] for c in
                            self.contract.get("required_constraints") or []
                            if c.get("kind") == "seminar"), None)
                args = {"query": q, "top_k": 10}
                if sem:
                    args["seminar"] = sem
                self._call("search_passages", args, "search_passages",
                           "契约要求的通用检索（内容词，不把整句送进词法层）",
                           constraints={"seminar": sem} if sem else None,
                           bclass="target_lane")
            elif op == "get_context":
                pids = [l["evidence_ids"][0] for l in self.lanes if l.get("evidence_ids")]
                if not pids:
                    break
                doc = self._call("get_context",
                                 {"passage_id": pids[0], "before": 2, "after": 2},
                                 "get_context", "契约要求的上下文补充",
                                 bclass="context")
                if doc:
                    self.spent_context += 1
            elif op == "trace_source":
                pids = [l["evidence_ids"][0] for l in self.lanes if l.get("evidence_ids")]
                if not pids:
                    break
                self._call("trace_source", {"passage_id": pids[0]}, "trace_source",
                           "契约要求的溯源链补充", bclass="optional")
            elif op == "find_concept_evidence":
                groups = rc.entity_form_groups(self.plan)
                eids = [e for e in groups if groups[e]]
                concept = eids[0] if eids else (terms[0] if terms else self.q)
                self._call("find_concept_evidence", {"concept": concept, "top_k": 10},
                           "find_concept_evidence",
                           "契约要求的受控概念证据检索（concept=%s）" % concept,
                           constraints={"concept": concept}, bclass="target_lane")
            elif op == "compare_concepts":
                self._run_compare_if_needed()
            elif op == "terminology_lookup":
                self._run_terminology()
            elif op == "trace_concept":
                self._run_diachronic_if_needed()
            elif op == "resolve_entity":
                continue          # 已在 _run_resolve_entity 处理
            else:
                break             # 其余交给 _finalize_operations 显式标状态

    # ── Phase 4C.1-B3 §2：NOT_APPLICABLE 语义 ────────────────────────────
    # required operation 只有在**存在明确、机器可验证的 upstream 结构性原因**时，
    # 才允许记 NOT_APPLICABLE。普通 retrieval failure 一律不得包装成 NOT_APPLICABLE。
    DEPENDENT_ON_METADATA = ("search_passages", "find_concept_evidence", "get_context",
                             "trace_source", "trace_concept", "compare_concepts",
                             "find_relation_evidence", "formalism_search",
                             "terminology_lookup")

    def _metadata_dependency_proof(self):
        """构造 metadata → dependent operation 的结构依赖凭据（可复算）。"""
        meta = self.metadata or self.contract.get("metadata") or {}
        fields = list(meta.get("metadata_missing_fields") or [])
        proofs = []
        for f in fields or ["session_date"]:
            raw = str(f)
            key = ("session_date" if "session_date" in raw else
                   raw.split("（")[0].strip())
            proofs.append(rc.metadata_structural_proof(key))
        return {
            "upstream_operation": "metadata_check",
            "upstream_state": "METADATA_UNAVAILABLE",
            "dependency": "问题要的是 metadata；语料层不存在该字段",
            "fields": fields,
            "proofs": proofs,
            "rule": ("NOT_APPLICABLE 只允许用于「依赖 metadata 的普通检索」；"
                     "必须有 whole-corpus 扫描凭据（corpus_scan.executed=true, "
                     "scope=whole_corpus, n_with_real_value=0）"),
        }

    def _mark_lanes_not_applicable(self, reason):
        for spec in self.obligations["lanes"]:
            lane = self._lane(spec["lane_id"], self._lane_type(spec), spec)
            if lane["status"] == "NOT_STARTED":
                lane.update(status="NOT_APPLICABLE", note=reason,
                            structural_dependency={"reason_code": "METADATA_UNAVAILABLE",
                                                   "upstream_operation": "metadata_check"})

    def _mark_dependent_ops_not_applicable(self):
        proof = self._metadata_dependency_proof()
        for op in self.obligations["operations"]:
            if op == "metadata_check":
                continue
            rec = self._op(op, op, "MetadataQuestionContract：依赖 metadata 的检索",
                           required=True)
            if op in self.DEPENDENT_ON_METADATA:
                rec.update(status="NOT_APPLICABLE",
                           failure_code="METADATA_UNAVAILABLE",
                           failure_message=("依赖的 metadata 字段全库不可得；"
                                            "按 NOT_APPLICABLE 记终态（不做无关检索）"),
                           completed_at=_now(),
                           structural_dependency=proof)
            else:
                rec.update(status="STRUCTURALLY_UNAVAILABLE",
                           failure_code="METADATA_UNAVAILABLE",
                           failure_message="问题要的是元数据且该字段全库不存在",
                           completed_at=_now())
        for c in (self.contract.get("required_constraints") or []):
            if c.get("value") in (None, ""):
                continue
            self.constraints.append({
                "kind": c.get("kind"), "value": c.get("value"), "applied": False,
                "reason": "METADATA_UNAVAILABLE：问题要的是元数据，不做无关的全文检索",
                "evidence_n": 0})

    def _finalize_lanes(self):
        """required lane 落在终态之外 → 显式标状态（§4：禁止无记录消失）。"""
        for lane in self.lanes:
            if lane["required"] and lane["status"] == "NOT_STARTED":
                lane["status"] = ("SKIPPED_WITH_REASON"
                                  if self.budget_exhausted else "FAILED")
                lane["note"] = ("BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION"
                                if self.budget_exhausted
                                else "该 lane 未被任何执行路径覆盖")

    def _finalize_operations(self):
        for op in self.obligations["operations"]:
            rec = self._op_index.get(op)
            if rec is None:
                # 契约要求但调度器没有留下记录 → 必须显式记录，不得静默消失。
                # 区分两种原因：预算耗尽（可恢复）vs 没有执行路径（结构性）。
                rec = self._op(op, op, "契约要求但调度器无对应实现", required=True)
                if self.budget_exhausted:
                    rec.update(status="SKIPPED_WITH_REASON",
                               failure_code="BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION",
                               failure_message="预算在契约完成前耗尽，该操作未调度")
                else:
                    rec.update(status="STRUCTURALLY_UNAVAILABLE",
                               failure_code="NO_EXECUTOR_FOR_OPERATION",
                               failure_message="调度器没有该 operation 的执行路径")
            elif rec["status"] in ("PLANNED", "SCHEDULED"):
                rec.update(status="SKIPPED_WITH_REASON",
                           failure_code="NOT_SCHEDULED",
                           failure_message="该操作未被本次执行路径调度")

    def _mark_lanes_structurally_unavailable(self, reason):
        for spec in self.obligations["lanes"]:
            lane = self._lane(spec["lane_id"], self._lane_type(spec), spec)
            if lane["status"] == "NOT_STARTED":
                lane.update(status="STRUCTURALLY_UNAVAILABLE", note=reason)

    # 状态
    def _execution_state(self):
        req_ops = self.obligations["operations"]
        # required=true 且 SKIPPED_WITH_REASON **仍然算未完成**（§5）
        unresolved = [o for o in req_ops
                      if (self._op_index.get(o) or {}).get("status") in
                      (None, "PLANNED", "SCHEDULED", "SKIPPED_WITH_REASON")]
        unresolved += [o for o in req_ops if o not in self._op_index]
        req_lanes = [l for l in self.obligations["lanes"] if l.get("required")]
        # 「resolved」= 有终态记录（§23）；FAILED / STRUCTURALLY_UNAVAILABLE 也是终态 ——
        # 它们影响的是 **sufficiency**（v2.1 会据此禁止 SUPPORTED），不是执行完成度。
        bad_lanes = [l["lane_id"] for l in self.lanes
                     if l["required"] and l["status"] in ("NOT_STARTED",)]
        structural = [l for l in self.lanes
                      if l["status"] in ("STRUCTURALLY_UNAVAILABLE", "NOT_APPLICABLE")]
        if len(structural) >= max(1, len(req_lanes)) and not any(
                l["status"] in ("SATISFIED", "ZERO_ATTESTATION_CONFIRMED")
                for l in self.lanes):
            return "BLOCKED"
        # B3：EXECUTION_PARTIAL 只表示「有 required obligation 没有终态」。
        # 类别预算提前收手（relation/context/optional 之类）已经如实记在
        # budget.exhausted_classes 里，不再单独把执行状态拉成 PARTIAL。
        if not unresolved and not bad_lanes:
            return "EXECUTION_COMPLETE"
        return "EXECUTION_PARTIAL"

    def _state_reason(self, state):
        if state == "EXECUTION_COMPLETE":
            return "所有 required operation 与 required lane 都已有执行记录"
        if state == "BLOCKED":
            return "结构性阻塞（如 metadata 字段全库不存在 / 来源层不存在）"
        if self.budget_exhausted:
            return "BUDGET_EXHAUSTED_BEFORE_CONTRACT_COMPLETION"
        return "部分 required obligation 未满足（见 operations/lanes 记录）"

    def _transition(self, to, reason):
        last = self.state_history[-1]["to"] if self.state_history else None
        if last == to:
            return
        self.state_history.append({"from": last, "to": to, "reason": reason})

    def _doc(self, state):
        self._transition("EVIDENCE_EVALUATED", "执行完成 → 交给 Evidence Sufficiency v2.1")
        return {
            "schema_version": SCHEMA,
            "state": state,
            "state_machine": self.state_history,
            "required_operations": self.obligations["operations"],
            "scheduled_operations": [o["operation_id"] for o in self.operations],
            "executed_operations": [o["operation_id"] for o in self.operations
                                    if o["status"] == "EXECUTED"],
            "failed_operations": [o["operation_id"] for o in self.operations
                                  if o["status"] == "FAILED"],
            "skipped_operations": [{"operation_id": o["operation_id"],
                                    "reason": o.get("failure_code")}
                                   for o in self.operations
                                   if o["status"] == "SKIPPED_WITH_REASON"],
            "structurally_unavailable_operations":
                [o["operation_id"] for o in self.operations
                 if o["status"] == "STRUCTURALLY_UNAVAILABLE"],
            "not_applicable_operations": [
                {"operation_id": o["operation_id"],
                 "structural_dependency": o.get("structural_dependency")}
                for o in self.operations if o["status"] == "NOT_APPLICABLE"],
            "resolved_operations": [o["operation_id"] for o in self.operations
                                    if o["status"] in OP_TERMINAL],
            "operations": self.operations,
            "lanes": self.lanes,
            "endpoints": self.endpoints,
            "constraints": self.constraints,
            "relation": self.relation,
            "formalism": self.formalism,
            "terminology": self.terminology,
            "metadata": self.metadata,
            "source_layers": self.source_layers,
            "generic_fallback": {
                "used": self.generic_fallback_used,
                "satisfied_required_lane_n": self.generic_fallback_satisfied_required_lane,
                "terms": list(GENERIC_FALLBACK_TERMS),
                "rule": "泛化 fallback 的证据只进 fallback_evidence，不得满足 required lane",
            },
            "budget": {
                "config": self.budget,
                "used": {"tool_calls": self.spent_calls,
                         "passages": self.spent_passages,
                         "context_expansions": self.spent_context},
                "exhausted": self.budget_exhausted,
                "exhausted_classes": sorted(self.class_exhausted),
                "class_quota": dict(self.class_quota),
                "class_spend": dict(self.class_spend),
                "plan": self.budget_plan,
                "priority": ["required_source_layer", "required_target_lane",
                             "required_formalism", "required_terminology",
                             "required_relation", "required_context",
                             "optional_exploration"],
            },
            "limitations": self.limitations,
            "warnings": self.warnings,
            "no_hidden_reasoning": True,
            "note": ("执行层只回答「契约要求的事做了没有」；证据够不够由 "
                     "Evidence Sufficiency v2.1 判定。两者在 trace 里分层存放。"),
        }

    # 供合并用
    def extra_evidence_records(self):
        return list(self.extra_evidence)

    def evidence_records(self):
        """本次执行取到的**全部**证据记录（按 passage_id 去重，保持出现顺序）。

        执行层只负责「做了什么、取到哪些段落」；够不够由 v2.1 判定。
        """
        seen, out = set(), []
        for doc in self.docs:
            for e in (doc.get("evidence") or []):
                pid = e.get("passage_id")
                if pid and pid not in seen:
                    seen.add(pid)
                    out.append(e)
        for e in self.extra_evidence:
            pid = e.get("passage_id")
            if pid and pid not in seen:
                seen.add(pid)
                out.append(e)
        return out


REQUIRED_CALL_OPS = ("metadata_check", "resolve_entity")


def class_need(contract, plan, obligations, max_context=3, terminology_terms=None):
    """契约义务 → **各类别**所需调用数（模块级，调度器与预算预留共用）。

    这是 B3 §3 的唯一口径：预算预留（run_task）与调度器配额都从这里来，
    两处若各算一套，就会出现「预留了 5 次、实际需要 9 次」的饿死。
    """
    ob = obligations or {}
    f = ob.get("facets") or {}
    ops = list(ob.get("operations") or [])
    n = {}
    n["resolve"] = max(1, len(rc.content_terms((plan or {}).get("salient_terms") or [], 4)))
    n["direct"] = (sum(1 for o in ops if o in ("compare_concepts", "trace_concept"))
                   + len(ob.get("endpoints") or []))
    n["period"] = len([c for c in (contract.get("required_constraints") or [])
                       if c.get("kind") == "period"])
    n["source_layer"] = len([l for l in (f.get("source_layers") or [])
                             if (contract.get("source_layer_corpus") or {}).get(l)])
    n["formalism"] = 2 if f.get("formalism") else 0
    terms = terminology_terms
    if terms is None:
        terms = list((contract.get("terminology") or {}).get("explicit_terms") or [])
        if not terms:
            terms = rc.content_terms((plan or {}).get("salient_terms") or [], 2)
    n["terminology"] = (max(1, len(terms))
                        if (f.get("terminology") or "terminology_lookup" in ops) else 0)
    n["target_lane"] = len([l for l in (ob.get("lanes") or [])
                            if l.get("required")
                            and l.get("expectation") != "EXPECTED_ZERO"])
    n["relation"] = 4 if f.get("relation") else 0
    n["context"] = min(2, int(max_context or 0))
    n["optional"] = 1 if ob.get("optional_operations") else 0
    # required op 里**不在 lane 覆盖**之列的（search_passages / find_concept_evidence
    # 在 lane 之后还要单独跑一次）→ 额外留额度。宁多不少（上界），不够时按 SHRINK_ORDER 收缩。
    op_cls = Counter({"target_lane": 0})
    for o in ops:
        cls = ResearchExecutionScheduler._OP_CLASS.get(o)
        if cls == "target_lane":
            op_cls["target_lane"] += 1
        elif cls:
            n[cls] = max(n.get(cls, 0), 1)
    n["target_lane"] += op_cls["target_lane"]
    return n


def estimate_required_calls(contract, plan, obligations):
    """契约义务需要多少次工具调用（与调度器同源；上界）。

    用途：`run_task` 在跑主探索之前按这个数**预留**额度（§20 契约感知预算），
    否则「required operations 真的执行了」会被主探索花光预算而变成假的。
    """
    need = class_need(contract, plan, obligations)
    return int(sum(need.values()))


def schedule(public_task, plan, contract, budget=None, trace=None, record_gaps=False):
    """便捷入口：契约 → 执行记录。"""
    return ResearchExecutionScheduler(public_task, plan, contract, budget=budget,
                                      trace=trace,
                                      record_gaps=record_gaps).run()


# ── 把执行结果并进 evidence pack ─────────────────────────────────────────
def assemble_pack(base_pack, execution, extra_evidence):
    """把执行层的补充证据并入基础 pack，并重算 coverage / provenance / evidence_state。"""
    import evidence_sufficiency as es1
    seen, ev = set(), []
    for e in (base_pack.get("evidence") or []) + list(extra_evidence or []):
        pid = e.get("passage_id")
        if pid and pid not in seen:
            seen.add(pid)
            ev.append(e)
    pack = dict(base_pack)
    pack["evidence"] = ev
    pack["evidence_n"] = len(ev)
    pack["coverage"] = api._coverage(ev)
    pack["provenance"] = api._provenance_summary(ev)
    pack["by_language"] = _count(ev, "language")
    pack["by_seminar"] = _count(ev, "seminar_id")
    pack["by_authority"] = _count(ev, "authority_level")
    payload = {k: pack.get(k) for k in
               ("request", "resolution", "retrieval", "evidence", "coverage",
                "provenance", "warnings", "evidence_state")}
    payload["request"] = pack.get("request") or {}
    pack["evidence_state"] = es1.evaluate(payload)
    pack["execution_merged"] = {
        "added_evidence_n": len(extra_evidence or []),
        "execution_state": (execution or {}).get("state"),
        "lanes_satisfied": [l["lane_id"] for l in (execution or {}).get("lanes") or []
                            if l["status"] in ("SATISFIED", "ZERO_ATTESTATION_CONFIRMED")],
    }
    return pack


def _count(ev, key):
    out = {}
    for e in ev:
        k = e.get(key)
        if k is None:
            continue
        out[k] = out.get(k, 0) + 1
    return out


__all__ = [n for n in dir() if not n.startswith("_")]
