#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
knowledge_api.py — Phase 4A §1/§4 Knowledge Access Layer（10 个 tool 的实现）

它是什么、不是什么
──────────────────
**是**：把 Phase 3 已经验证过的检索链暴露成**结构化证据**。
**不是**：Answer Generator。这里**不生成**任何 Lacan 理论文章，
也不做 LLM 总结。Research Agent（`research_agent.py`）才负责组织答案。

关键纪律
────────
* **不重新实现检索**（§4）：`search_passages` 走 `query_routing_policy` +
  `full_corpus_retrieval` 的组件；`compare_concepts` 走
  `lacanian_semantic_guard` 的独立 lane。本模块只做**组装与呈现**。
* **READ ONLY**（§2）：全程只读 `_data/`；没有一行写 canonical knowledge。
* **统一输出**（§6）：所有 research/evidence tool 返回同一组 8 个 section。
* **不隐藏溯源缺口**（§4 Tool 9 / §14）：`SOURCE_TRACE_INCOMPLETE` 一定出现在
  warnings 与 evidence 条目里。
* **不静默解析**（§4 Tool 4）：歧义与 entity collision 原样上报。

数据来源（为什么读 SQLite 而不是 373MB 的 JSONL）
─────────────────────────────────────────────────
`_data/index/lexical.sqlite` 的 `passage_meta` 表**已经**含
id / session_id / seminar_id / language / authority_level / trace_status /
witness_id / corpus_source_id / raw_text 等字段，且**行序 == passages.jsonl 行序**
（构建时按 store 顺序插入）。因此常驻内存只需一次 249k 行的读取，
`get_context` 也能用 rowid 直接取邻居 —— 不必反复扫 373MB。

行序一致这一条**不是假设**：`_assert_row_order_matches_store()` 在首次使用时抽检。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VAULT = os.path.dirname(os.path.dirname(TOOLS))
IDX = os.path.join(VAULT, "_data", "index")
STORE = os.path.join(VAULT, "_data", "passage_store")
VECDIR = os.path.join(IDX, "vector")

sys.path.insert(0, TOOLS)
sys.path.insert(0, HERE)

import evidence_sufficiency as es  # noqa: E402
import query_terms as qt        # noqa: E402  （同目录，Phase 4A 共享规划层）
import ontology_v4a1 as onto    # noqa: E402  （Phase 4A.1 版本化本体叠加层）

LEX = os.path.join(IDX, "lexical.sqlite")
PASSAGES = os.path.join(STORE, "passages.jsonl")
CONCEPTS = os.path.join(STORE, "concepts.jsonl")

TOP_K_MAX = 50
DEFAULT_TOP_K = 10


# ─────────────────────────────────────────────────────────────── 只读数据层

class KB:
    """进程内只读知识库视图。**懒加载**，任何 tool 都只调用它的读方法。"""

    _inst = None

    def __init__(self):
        self._meta = None          # id -> row(dict)
        self._order = None         # store 顺序的 id 列表
        self._pos = None           # id -> 下标
        self._concepts = None
        self._relations = None
        self._witnesses = None
        self._corpus_sources = None
        self._realizations = None
        self._witness_links = None
        self._vector_index = None
        self._provider = None
        self.vector_status = {"available": None, "reason": None}
        self._row_order_checked = False

    # ---- 单例
    @classmethod
    def instance(cls):
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    # ---- passage meta（一次读全）
    def meta(self):
        if self._meta is None:
            con = sqlite3.connect(LEX)
            con.row_factory = sqlite3.Row
            rows = list(con.execute(
                "SELECT rowid, id, session_id, seminar_id, language, lesson, "
                "session_date, text_role, authority_level, review_status, status, "
                "canonical, trace_status, witness_id, corpus_source_id, "
                "document_id, raw_text FROM passage_meta ORDER BY rowid"))
            con.close()
            self._meta = {r["id"]: dict(r) for r in rows}
            self._order = [r["id"] for r in rows]
            self._pos = {pid: i for i, pid in enumerate(self._order)}
        return self._meta

    def order(self):
        self.meta()
        return self._order

    def pos(self, pid):
        self.meta()
        return self._pos.get(pid)

    def _assert_row_order_matches_store(self):
        """抽检「sqlite 行序 == passages.jsonl 行序」。不一致就必须报错，不能默默错。

        它决定了 `get_context` 的「前后」是不是**原文顺序** —— 这是 §4 Tool 3 的核心要求。
        """
        if self._row_order_checked:
            return
        probes = [0, 1, len(self.order()) // 3, len(self.order()) // 2,
                  len(self.order()) - 2, len(self.order()) - 1]
        want = {self._order[i] for i in probes}
        found = {}
        with open(PASSAGES, encoding="utf-8") as f:
            for line_no, line in enumerate(f):
                if not line.strip():
                    continue
                if line_no in probes:
                    found[line_no] = json.loads(line)["id"]
                if len(found) == len(probes):
                    break
        for i in probes:
            if found.get(i) != self._order[i]:
                raise RuntimeError(
                    "sqlite passage_meta 行序与 passages.jsonl 行序不一致"
                    "（位置 %d：%r vs %r）—— get_context 的「前后」将不可信，"
                    "必须改用直接读 store。" % (i, found.get(i), self._order[i]))
        self._row_order_checked = True

    # ---- concepts / relations / 溯源
    def concepts(self):
        """Gold Concept Set（53）+ Phase 4A.1 叠加实体。

        ⚠️ 合并规则：**gold 永不被覆盖**（`setdefault`）。叠加层只能新增 id；
        若两者撞 id 说明叠加层越界，这里保持 gold 不变并在 status 里能看出来。
        """
        if self._concepts is None:
            out = {}
            with open(CONCEPTS, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        c = json.loads(line)
                        c["_layer"] = "gold"
                        out[c["id"]] = c
            for e in onto.entities():
                if e["id"] in out:
                    continue          # gold 优先，叠加层不得覆盖
                row = dict(e)
                row["_layer"] = onto.LAYER_ID
                out[e["id"]] = row
            self._concepts = out
        return self._concepts

    def relations(self):
        if self._relations is None:
            rows = []
            d = os.path.join(VAULT, "_data", "relations")
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if fn.endswith(".jsonl"):
                        with open(os.path.join(d, fn), encoding="utf-8") as f:
                            for line in f:
                                if line.strip():
                                    r = json.loads(line)
                                    r.setdefault("_file", fn)
                                    rows.append(r)
            self._relations = rows
        return self._relations

    def _jsonl(self, name):
        p = os.path.join(STORE, name)
        rows = []
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        rows.append(json.loads(line))
        return rows

    def witnesses(self):
        if self._witnesses is None:
            self._witnesses = {w["id"]: w for w in self._jsonl("witnesses.jsonl")}
        return self._witnesses

    def corpus_sources(self):
        if self._corpus_sources is None:
            self._corpus_sources = {c["id"]: c for c in self._jsonl("corpus_sources.jsonl")}
        return self._corpus_sources

    def realizations(self):
        if self._realizations is None:
            m = {}
            for r in self._jsonl("passage_realizations.jsonl"):
                m.setdefault(r.get("passage_id"), []).append(r)
            self._realizations = m
        return self._realizations

    def witness_links(self):
        if self._witness_links is None:
            m = {}
            for r in self._jsonl("passage_witnesses.jsonl"):
                m.setdefault(r.get("passage_id"), []).append(r)
            self._witness_links = m
        return self._witness_links

    # ---- 向量（可缺席）
    def vector(self):
        """→ (index, provider)。不可用时返回 (None, None) 并记录原因（**不抛异常**）。"""
        if self._vector_index is not None or self.vector_status["available"] is False:
            return self._vector_index, self._provider
        try:
            import numpy  # noqa: F401
            import embedding_provider as ep
            import full_corpus_retrieval as fcr
            prov = ep.OnnxTransformersProvider("minilm")
            if not prov.available:
                raise RuntimeError(prov.blocked_reason)
            self._vector_index = fcr.Index()
            self._provider = prov
            self.vector_status = {"available": True, "reason": None,
                                  "index_version": self._vector_index.man.get("index_version"),
                                  "passage_count": self._vector_index.man.get("passage_count")}
        except Exception as e:
            self._vector_index = None
            self._provider = None
            self.vector_status = {"available": False,
                                  "reason": "%s: %s" % (type(e).__name__, e),
                                  "fix": ("用 .venv-embedding/bin/python 跑 MCP server / "
                                          "CLI 才能启用向量路径；否则自动降级为词法路径")}
        return self._vector_index, self._provider


KB_ = KB.instance()


# ─────────────────────────────────────────────────────────────── 组装工具

def _warn(code, message, severity="info", action=None, **extra):
    """结构化告警。`extra` 会原样保留 —— 例如 `pair`：

    ⚠️ 第一版只留 code/message/severity/action，把 guard 的 `pair` 丢了，
    于是 Phase 4A.1 的「按 pair 判断该碰撞是否已修复」永远匹配不上，
    修好的配对照样把状态压成 CONFLICTING_EVIDENCE。
    """
    out = {"code": code, "message": message, "severity": severity}
    if action:
        out["action"] = action
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def _passage_evidence(pid, why=None, comp=None, rank=None):
    """把 passage 元数据变成 evidence 条目。**只读**。"""
    m = KB_.meta().get(pid)
    if not m:
        return None
    e = {
        "passage_id": pid,
        "seminar_id": m.get("seminar_id"),
        "session_id": m.get("session_id"),
        "language": m.get("language"),
        "authority_level": m.get("authority_level"),
        "text_role": m.get("text_role"),
        "trace_status": m.get("trace_status"),
        "canonical": bool(m.get("canonical")),
        "witness_id": m.get("witness_id"),
        "corpus_source_id": m.get("corpus_source_id"),
        "review_status": m.get("review_status"),
        "text": (m.get("raw_text") or "")[:1200],
        "text_truncated": len(m.get("raw_text") or "") > 1200,
        "why_retrieved": why or [],
        "component_contribution": comp or {},
        "rank": rank,
        "period": _period_of(m.get("seminar_id")),
        "period_label": _period_label(m.get("seminar_id")),
    }
    if e["trace_status"] == "SOURCE_TRACE_INCOMPLETE":
        e["provenance_note"] = ("SOURCE_TRACE_INCOMPLETE：上游原件缺失"
                                "（中文 recovered 语料），**不得当作已闭合的 primary source**。")
    return e


_SEM_PERIOD_CACHE = None


def _sem_period_table():
    """seminar_id → 时期标签。

    ⚠️ 第一版读的是 `query_router._SEM_PERIOD` —— 那个属性**根本不存在**（空表），
    于是所有 passage 的 period 都是 None，历时分组形同虚设。
    真源有两个：`hybrid_retrieve._SEM_PERIOD`（手写表，27 条）与
    `_data/passage_store/seminars.jsonl` 的 `year_from`/`year_to`（**28 条，全部有值**）。
    这里以 **store 的真实年份字段**为准（可追溯、无遗漏），
    并把手写表作为 `period_label` 一并给出。
    """
    global _SEM_PERIOD_CACHE
    if _SEM_PERIOD_CACHE is None:
        table = {}
        try:
            import hybrid_retrieve as hr
            handwritten = getattr(hr, "_SEM_PERIOD", {}) or {}
        except Exception:
            handwritten = {}
        p = os.path.join(STORE, "seminars.jsonl")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    yf, yt = r.get("year_from"), r.get("year_to")
                    if yf and yt:
                        table[r["id"]] = "%s-%s" % (yf, yt)
        for k, v in handwritten.items():
            sid = "seminar.S%02d" % int(k)
            table.setdefault(sid, v)
        _SEM_PERIOD_CACHE = table
    return _SEM_PERIOD_CACHE


def _period_of(seminar_id):
    if not seminar_id:
        return None
    return _sem_period_table().get(seminar_id)


def _period_label(seminar_id):
    try:
        import hybrid_retrieve as hr
        import re
        t = getattr(hr, "_SEM_PERIOD", {}) or {}
        return t.get(int(re.sub(r"\D", "", seminar_id or "") or 0))
    except Exception:
        return None


def _coverage(ev):
    langs = {}
    for e in ev:
        langs[e.get("language")] = langs.get(e.get("language"), 0) + 1
    periods = {_period_of(e.get("seminar_id")) for e in ev if e.get("seminar_id")}
    periods.discard(None)
    return {
        "evidence_n": len(ev),
        "session_n": len({e.get("session_id") for e in ev if e.get("session_id")}),
        "seminar_n": len({e.get("seminar_id") for e in ev if e.get("seminar_id")}),
        "period_n": len(periods),
        "periods": sorted(periods),
        "language_mix": langs,
    }


def _provenance_summary(ev):
    from collections import Counter
    ts = Counter(e.get("trace_status") for e in ev)
    ws = Counter(e.get("witness_id") for e in ev)
    cs = Counter(e.get("corpus_source_id") for e in ev)
    return {
        "trace_status": dict(ts),
        "source_trace_incomplete_n": ts.get("SOURCE_TRACE_INCOMPLETE", 0),
        "witnesses": dict(ws),
        "corpus_sources": dict(cs),
        "authority_levels": dict(Counter(e.get("authority_level") for e in ev)),
        "note": ("trace_status 分布如实反映上游完整性；"
                 "SOURCE_TRACE_INCOMPLETE **不隐藏**。"),
    }


def _resolution(status=None, entities=None, candidates=None, ambiguous=None,
                collisions=None, ontology_gaps=None, unresolved_terms=None,
                reason=None, **extra):
    """**唯一的 resolution 组装点**，保证所有 tool 的 resolution 同构（§6）。

    ⚠️ 第一版各 tool 自己拼 dict：`search_passages` 给 `entities`，
    `resolve_entity` 给 `candidates` —— 于是 `evidence_sufficiency` 在
    trace_concept 路径上读不到 entities，把状态误判成 INSUFFICIENT_EVIDENCE。
    统一到这里之后，`entities` **永远**存在且是同一种形状。
    """
    ents = entities if entities is not None else (candidates or [])
    norm = []
    for e in ents:
        if isinstance(e, dict):
            norm.append({"entity_id": e.get("entity_id"),
                         "matched_alias": e.get("matched_alias"),
                         "origin": e.get("origin", "unknown"),
                         "entity_type": e.get("entity_type"),
                         "required": bool(e.get("required", False))})
        else:
            norm.append({"entity_id": str(e), "matched_alias": None,
                         "origin": "explicit", "entity_type": None, "required": True})
    out = {
        "resolution_status": status or ("RESOLVED" if norm else "UNRESOLVED"),
        "entities": norm,
        "ambiguous": ambiguous or [],
        "collisions": collisions or [],
        "ontology_gaps": ontology_gaps or [],
        "unresolved_terms": unresolved_terms or [],
    }
    if candidates is not None:
        # ⚠️ `candidates` 是**显式参数**，不在 **extra 里 —— 第一版忘了写回 out，
        #    于是 find_concept_evidence 读 r["resolution"]["candidates"] 直接 KeyError。
        out["candidates"] = candidates
    if reason:
        out["reason"] = reason
    out.update(extra)
    # Phase 4A.1：本体层信息一律显式出现（缺省也要有键，避免下游靠 .get 猜）
    out.setdefault("ontology_layer", "gold")
    out.setdefault("context_required", False)
    out.setdefault("superseded", [])
    out.setdefault("ontology_defect_class", None)
    return out


def _split_repaired_collisions(collisions):
    """把「Phase 3 报碰撞、但 Phase 4A.1 已修复」的配对分开（§8 的重分类）。

    ⚠️ 这不是为了让数字好看：一对实体若在**当前本体层**已经是两个独立实体，
    再把它当作 ENTITY_COLLISION 送进 evidence_sufficiency，
    就会用旧缺陷解释新数据（状态被误判成 CONFLICTING_EVIDENCE）。
    旧结论**不删**：仍以 `ONTOLOGY_REPAIRED` info 告警 + `ontology_repairs` 字段出现。
    """
    repaired_map = {}
    try:
        for row in onto.guard_view():
            if row["post_repair_class"] != "ENTITY_COLLISION":
                repaired_map[tuple(row["pair"])] = row
    except Exception:
        pass
    live, repaired = [], []
    for c in collisions or []:
        pair = tuple(c.get("pair") or [])
        if pair in repaired_map:
            repaired.append({**c, "ontology_layer": onto.LAYER_ID,
                             "post_repair_class": repaired_map[pair]["post_repair_class"],
                             "post_entities": repaired_map[pair]["post_entities"],
                             "note": "该配对在 ontology.v4a1 里已不再碰撞"})
        else:
            live.append(c)
    return live, repaired


def _split_repaired_gaps(gaps):
    """缺口同理：叠加层补齐的那一侧不再是缺口（改记 ontology_repairs）。"""
    live, repaired = [], []
    try:
        view = {tuple(r["pair"]): r for r in onto.guard_view()}
    except Exception:
        view = {}
    for g in gaps or []:
        pair = tuple(g.get("pair") or [])
        row = view.get(pair)
        if row and row["post_repair_class"] in ("RESOLVED", "RESOLVED_CONTEXT_REQUIRED"):
            repaired.append({**g, "post_repair_class": row["post_repair_class"],
                             "post_entities": row["post_entities"],
                             "ontology_layer": onto.LAYER_ID})
        else:
            live.append(g)
    return live, repaired


def _recompute_state(payload_like):
    """并入证据后重算 evidence_state（不许把旧状态留在响应里）。"""
    payload = {k: payload_like.get(k) for k in
               ("request", "resolution", "retrieval", "evidence", "coverage",
                "provenance", "warnings", "evidence_state")}
    if payload.get("evidence_state", {}).get("operation_requirements"):
        req = payload["evidence_state"]["operation_requirements"]
        payload["evidence_state"] = es.evaluate(payload)
        payload["evidence_state"]["operation_requirements"] = req
    else:
        payload["evidence_state"] = es.evaluate(payload)
    payload_like["evidence_state"] = payload["evidence_state"]
    return payload_like


def _envelope(request, resolution=None, retrieval=None, evidence=None,
              warnings=None, expect_entity=False, extra_coverage=None,
              extra_provenance=None, state_override=None):
    ev = evidence or []
    cov = _coverage(ev)
    if extra_coverage:
        cov.update(extra_coverage)
    payload = {
        "request": {**request, "expect_entity": expect_entity},
        "resolution": resolution or {},
        "retrieval": retrieval or {},
        "evidence": ev,
        "coverage": cov,
        "provenance": _provenance_summary(ev),
        "warnings": warnings or [],
    }
    if extra_provenance:
        payload["provenance"].update(extra_provenance)
    payload["evidence_state"] = es.evaluate(payload)
    if state_override:
        # 某些研究操作有**额外的**充分性条件（如对比要求两条 lane 都有证据）。
        # 这不是绕过引擎，而是把「本次操作需要什么」也纳入判断。
        sig = payload["evidence_state"]["signals"]
        sig.update(state_override.get("signals_addendum") or {})
        payload["evidence_state"]["state"] = state_override["state"]
        payload["evidence_state"]["reasons"] = (
            list(state_override.get("reasons") or [])
            + payload["evidence_state"]["reasons"])
        payload["evidence_state"]["operation_requirements"] = state_override.get("note")
    return payload


# ─────────────────────────────────────────────────────────────── Tool 1

def _plan_query(query, lang):
    """确定性查询规划 → (effective_query, terms, strategy, terms_not_in_corpus)。

    为什么访问层需要它（Phase 4A 实测，repair 记录见 PHASE4A_FINDINGS.md）
    ────────────────────────────────────────────────────────────────
    Phase 3 词法层「由紧到松」：中文是**整段 bigram 短语**，法文是**所有 token
    AND**。MCP 的调用方送的是自然语言，于是：

    * `如何讨论凝视` → 短语 `"如何 何讨 讨论 论凝 凝视"` → **0 命中**，
      而语料里含「凝视」的段有 **341** 段（S11 内 **93** 段）；
    * `jouissance 在研讨班七期` → `在研讨班七期` 把法文侧 AND 死 → **0 命中**，
      而 S07 内 jouissance 有材料。

    把「命中不了字符串」当成「知识库没有」是本相位最不能犯的错，所以：
    原样查询**零命中**时，才用显著词重查（由紧到松，与 `syntax_variants` 同构），
    并且**只用语料词表里真实存在的词**（`probe_terms`）。
    这是**读取知识库事实**，不是猜同义词，也不做机器翻译。
    """
    import full_corpus_retrieval as fcr
    if not query or not str(query).strip():
        return query, [], "as_given", []
    l = lang if lang in ("fr", "zh") else None
    try:
        if fcr.comp_lexical(query, l):
            return query, [], "as_given", []
    except Exception:
        return query, [], "as_given", []
    terms = qt.salient_terms(query)
    known, unknown = qt.probe_terms(terms, language=l)
    if not known:
        return query, terms, "no_vocabulary_hit", unknown
    return " ".join(known[:4]), terms, "term_decomposition", unknown


def search_passages(query, language="any", seminar=None, period=None, entities=None,
                    top_k=DEFAULT_TOP_K, retrieval_mode="auto", include_context=False,
                    explain=False):
    """通用证据检索 —— **走 Phase 3 的 Query Routing Policy，不另写检索**。"""
    import query_router
    import entity_resolution as er
    import query_routing_policy as rp
    import full_corpus_retrieval as fcr
    import lacanian_semantic_guard as guard_mod

    top_k = max(1, min(int(top_k or DEFAULT_TOP_K), TOP_K_MAX))
    plan = query_router.route(query)
    res = er.resolve(query, plan)
    route = rp.plan_for(query, plan)
    warnings = []

    # retrieval_mode 覆盖 routing 决策（但不改 routing policy 本身）
    mode = retrieval_mode or "auto"
    vector_enabled = route["vector_enabled"]
    if mode == "lexical":
        vector_enabled = False
    elif mode == "vector":
        vector_enabled = True
    elif mode == "exact":
        vector_enabled = False
    idx, prov = KB_.vector()
    if vector_enabled and idx is None:
        warnings.append(_warn("VECTOR_UNAVAILABLE",
                              "请求/路由要求向量路径，但运行时不可用：%s"
                              % (KB_.vector_status.get("reason") or "unknown"),
                              "warning", KB_.vector_status.get("fix")))
        vector_enabled = False

    lang = None if language in (None, "any") else language
    sem = seminar
    if sem and not str(sem).startswith("seminar."):
        sem = "seminar." + str(sem).lstrip("sS")
    # ⚠️ routing policy 已经把 "Seminar XI" 解析成 seminar.S11 ——
    #    但第一版没有把**它**下推给检索，于是 SEMINAR_SPECIFIC 这条路
    #    照样从全库取证据、只是事后过滤（约束形同虚设）。这里直接采用 router 的结果。
    router_sems = plan.get("seminars") or []
    if not sem and router_sems:
        sem = router_sems[0]

    # ── 查询规划：只在「原样查询词法零命中」时启用（见 `_plan_query`）
    q_eff, planned_terms, q_strategy, q_unknown = _plan_query(query, lang)
    if q_strategy == "term_decomposition":
        warnings.append(_warn(
            "QUERY_DECOMPOSED",
            "原样查询在词法层 **0 命中** → 按显著词重查：%r → %r。"
            "**这不是把 0 命中当作「知识库没有」**，而是访问层的确定性规划；"
            "两者结果都保留在检索元数据里。" % (query, q_eff), "info"))
    if q_unknown:
        warnings.append(_warn(
            "TERMS_NOT_IN_CORPUS",
            "这些词在语料词法索引里**没有任何命中**：%s —— "
            "可能是语言/译法差异，也可能是真实的 ontology gap；本层不替它们造写法。"
            % q_unknown, "warning", "如属真实缺口，请记入 ontology_gap_queue"))
    if q_strategy == "no_vocabulary_hit":
        warnings.append(_warn(
            "NO_VOCABULARY_HIT",
            "查询的**任何**内容词在语料里都没有词法命中 —— 这不是「排序靠后」，"
            "而是词表层面没有对应写法。", "warning"))

    # ⚠️ numpy 只在**真的用向量**时才 import —— 否则纯词法环境（system python3）
    #    会因为一句无关的 import 直接崩掉，而它本来可以正常服务。
    qv = None
    if vector_enabled and prov is not None:
        import numpy as np
        qv = np.asarray(prov.embed_queries([q_eff])[0], dtype="float32")

    E = fcr.comp_exact(q_eff, res)
    L = fcr.comp_lexical(q_eff, lang if lang in ("fr", "zh") else None, res=res)
    # ⚠️ 约束必须**下推到检索**，而不是只在结果上过滤：
    #    第一版先取全库 top-N 再按 seminar 过滤 —— 于是「jouissance + seminar.S07」
    #    返回 0 条（top-N 里没有 S07 的段落），而语料里其实有材料。
    #    `lacan_search.lexical_search` 本身支持 seminar 过滤，直接用它。
    if sem:
        import lacan_search
        pushed = []
        try:
            for h in lacan_search.lexical_search(q_eff, language=lang, seminar=sem,
                                                 limit=200):
                pushed.append(h["passage_id"])
        except Exception:
            pushed = []
        if pushed:
            L = list(dict.fromkeys(pushed + L))
    X = fcr.comp_bridge(res, target_langs=("fr",) if plan.get("language") == "zh"
                        else (("zh",) if plan.get("language") == "fr" else ("fr", "zh")))
    V = [p for p, _ in zip(*idx.search(qv, limit=fcr.TOPK_RETURN))] if qv is not None else []

    comp_rank = {"exact": {p: i for i, p in enumerate(E, 1)},
                 "lexical": {p: i for i, p in enumerate(L, 1)},
                 "terminology_bridge": {p: i for i, p in enumerate(X, 1)}}
    if vector_enabled:
        comp_rank["vector"] = {p: i for i, p in enumerate(V, 1)}

    if mode == "exact":
        ranked = E[:top_k]
    else:
        lists = [E, L]
        if vector_enabled:
            lists.append(V)
        if "x" in route["components"]:
            lists.append(X)
        ranked = fcr.rrf(lists)

    # 约束过滤（language / seminar / period）
    def keep(pid):
        m = KB_.meta().get(pid)
        if not m:
            return False
        if lang and m.get("language") != lang:
            return False
        if sem and m.get("seminar_id") != sem:
            return False
        if period and _period_of(m.get("seminar_id")) != period:
            return False
        return True

    ranked = [p for p in ranked if keep(p)][:top_k]
    if not ranked and (lang or sem or period):
        warnings.append(_warn(
            "CONSTRAINT_RETURNED_NOTHING",
            "加上约束（language=%s seminar=%s period=%s）后没有证据返回。"
            "**这不等于语料里没有相关材料**，只说明该约束下的 top-k 为空 —— "
            "放宽约束再试，或把它当作证据缺口报告。" % (lang, sem, period),
            "warning", "放宽 language/seminar/period 之一后重试"))
    for p in (entities or []):
        pass  # 额外实体只影响 resolution 展示；不改变证据排序（避免绕过 routing）

    ev = []
    for i, pid in enumerate(ranked, 1):
        cc = {k: v[pid] for k, v in comp_rank.items() if pid in v}
        why = [k for k in ("terminology_bridge", "exact", "lexical", "vector") if k in cc]
        item = _passage_evidence(pid, why=why, comp=cc, rank=i)
        if item:
            if include_context:
                item["context_refs"] = _context_ids(pid, 1, 1)
            ev.append(item)

    guard = guard_mod.analyze(query, plan)
    # 先算「哪些 Phase 3 碰撞/缺口已被 Phase 4A.1 修复」——后面的 warnings 循环
    # 与 resolution 组装都要用它，所以必须在两者**之前**（第一版放在了 resolution
    # 之前、warnings 之后，于是 rep_pairs 引用到未赋值的局部变量）。
    _raw_col = [w for w in guard.get("warnings") or []
                if w["code"] == "ENTITY_COLLISION"]
    _col, _rep_col = _split_repaired_collisions(_raw_col)
    _raw_gaps = [w for w in guard.get("warnings") or []
                 if w["code"] in ("COUNTERPART_ENTITY_MISSING", "BOTH_ENTITIES_MISSING")]
    _gaps, _rep_gaps = _split_repaired_gaps(_raw_gaps)
    rep_pairs = {tuple(r.get("pair") or []) for r in (_rep_col + _rep_gaps)}
    for w in guard.get("warnings") or []:
        if tuple(w.get("pair") or []) in rep_pairs:
            continue          # 已修复：改由 ONTOLOGY_REPAIRED + ontology_repairs 承载
        warnings.append(_warn(w["code"], w["message"], w.get("severity", "warning"),
                              w.get("action"), pair=w.get("pair")))
    if res.get("ambiguous"):
        warnings.append(_warn(
            "AMBIGUOUS_ENTITY",
            "%d 个词形命中多个 entity，**未被静默解析**：%s"
            % (len(res["ambiguous"]),
               [a["alias"] for a in res["ambiguous"][:3]]),
            "warning", "由调用方决定如何消歧；本层不替它选"))
    if plan.get("ambiguous_entities"):
        pass

    resolution = _resolution(
        status=("AMBIGUOUS" if res.get("ambiguous") else
                "ENTITY_COLLISION" if _col else
                "RESOLVED" if res["entities"] else "UNRESOLVED"),
        entities=[{"entity_id": e["entity_id"], "matched_alias": e.get("matched_alias"),
                   "origin": e["origin"],
                   "entity_type": e.get("entity_type"),
                   "required": (e["entity_id"] in (entities or [])
                                or e["origin"] == "router")}
                  for e in res["entities"]],
        ambiguous=res.get("ambiguous") or [],
        collisions=_col,
        ontology_gaps=_gaps,
        ontology_repairs=_rep_col + _rep_gaps,
        ontology_layer="gold",
        # ⚠️ 与 `_resolution` 其它调用点保持**同一种形状**（dict 列表）。
        #    第一版这里是字符串列表，evidence_sufficiency 读到 str 直接 AttributeError
        #    —— 只有真正走到「实体约束检索」这条路径才会炸（gaze 这次就踩到了）。
        unresolved_terms=[{"term": t, "entity_id": None, "reason": "not_resolved"}
                          for t in (entities or [])
                          if t not in {e["entity_id"] for e in res["entities"]}])
    retrieval = {
        "route": route["route"], "route_why": route["why"],
        "vector_enabled": vector_enabled,
        "vector_disabled_reason": (route["vector_disabled_reason"]
                                   if not vector_enabled else None),
        "retrieval_mode_requested": mode,
        "lanes_count": route["lanes_count"],
        "component_counts": {"exact": len(E), "lexical": len(L),
                             "terminology_bridge": len(X), "vector": len(V)},
        "component_ranks": ({p: {k: v[p] for k, v in comp_rank.items() if p in v}
                             for p in ranked[:10]} if explain else None),
        "fusion": "rrf(k=60)" if mode not in ("exact",) else "exact_only",
        "router_intent": plan.get("intent"),
        "router_language": plan.get("language"),
        "query_strategy": q_strategy,
        "original_query": query,
        "effective_query": q_eff,
        "planned_terms": planned_terms or None,
        "terms_not_in_corpus": q_unknown or None,
    }
    return _envelope(
        {"tool": "search_passages", "query": query, "language": language,
         "seminar": seminar, "period": period, "top_k": top_k,
         "retrieval_mode": mode, "include_context": include_context,
         "explain": explain},
        resolution, retrieval, ev, warnings, expect_entity=False)


# ─────────────────────────────────────────────────────────────── Tool 2

def get_passage(passage_id):
    m = KB_.meta().get(passage_id)
    warnings = []
    if not m:
        return _envelope(
            {"tool": "get_passage", "passage_id": passage_id},
            {"resolution_status": "PASSAGE_NOT_FOUND"},
            {"lookup": "canonical passage store"},
            [], [_warn("PASSAGE_NOT_FOUND",
                       "canonical passage store 里没有 id=%s" % passage_id,
                       "error", "不要猜 ID；用 search_passages 取真实 ID")],
            expect_entity=False)
    ev = [_passage_evidence(passage_id, why=["exact_lookup"], comp={"exact": 1}, rank=1)]
    pos = KB_.pos(passage_id)
    has_prev = bool(pos is not None and pos > 0)
    has_next = bool(pos is not None and pos < len(KB_.order()) - 1)
    retrieval = {
        "canonical_status": {"canonical": bool(m.get("canonical")),
                             "review_status": m.get("review_status"),
                             "authority_level": m.get("authority_level"),
                             "text_role": m.get("text_role")},
        "translation_status": {"language": m.get("language"),
                               "witness_id": m.get("witness_id"),
                               "text_role": m.get("text_role"),
                               "note": ("中文条目来自 translation witness；"
                                        "不是 Lacan 法文原文") if m.get("language") == "zh"
                               else None},
        "neighbor_availability": {"has_previous": has_prev, "has_next": has_next,
                                  "store_position": pos},
    }
    if m.get("trace_status") == "SOURCE_TRACE_INCOMPLETE":
        warnings.append(_warn("SOURCE_TRACE_INCOMPLETE",
                              "该 passage 的上游原件缺失（%s）—— 引用时必须保留此告警。"
                              % (m.get("witness_id") or "unknown witness"),
                              "warning", "不要把它当作已闭合的 primary source"))
    pr = _period_of(m.get("seminar_id"))
    return _envelope(
        {"tool": "get_passage", "passage_id": passage_id},
        _resolution(status="RESOLVED", entities=[], resolved_passage=passage_id,
                    period=pr),
        retrieval, ev, warnings, expect_entity=False)


def _context_ids(pid, before, after):
    pos = KB_.pos(pid)
    if pos is None:
        return None
    order = KB_.order()
    lo = max(0, pos - int(before))
    hi = min(len(order), pos + int(after) + 1)
    return order[lo:hi]


# ─────────────────────────────────────────────────────────────── Tool 3

def get_context(passage_id, before=3, after=3):
    KB_._assert_row_order_matches_store()
    m = KB_.meta().get(passage_id)
    if not m:
        return _envelope({"tool": "get_context", "passage_id": passage_id,
                          "before": before, "after": after},
                         {"resolution_status": "PASSAGE_NOT_FOUND"}, {},
                         [], [_warn("PASSAGE_NOT_FOUND",
                                    "canonical passage store 里没有 id=%s" % passage_id,
                                    "error")])
    ids = _context_ids(passage_id, before, after)
    # 同 session 内才算「本地上下文」；跨 session 必须标注，避免把不同课次连读
    ev = []
    for i, p in enumerate(ids):
        item = _passage_evidence(p, why=["store_order_neighbor"],
                                 comp={"store_order": abs(i - ids.index(passage_id)) + 1},
                                 rank=i + 1)
        if not item:
            continue
        item["is_target"] = (p == passage_id)
        item["store_position"] = KB_.pos(p)
        item["same_session_as_target"] = (
            KB_.meta()[p].get("session_id") == m.get("session_id"))
        ev.append(item)
    warnings = []
    if any(not e["same_session_as_target"] for e in ev):
        warnings.append(_warn("CONTEXT_CROSSES_SESSION",
                              "前后文跨越了 session 边界 —— 相邻段落**不一定**同一课次，"
                              "阅读时不要连成一段。", "warning"))
    if m.get("trace_status") == "SOURCE_TRACE_INCOMPLETE":
        warnings.append(_warn("SOURCE_TRACE_INCOMPLETE",
                              "目标 passage 上游原件缺失；前后文同样可能受影响。",
                              "warning"))
    return _envelope(
        {"tool": "get_context", "passage_id": passage_id,
         "before": before, "after": after},
        _resolution(status="RESOLVED", entities=[], resolved_passage=passage_id,
                    session_id=m.get("session_id"), seminar_id=m.get("seminar_id")),
        {"ordering": ("passages.jsonl 行序（已抽检 sqlite 行序一致）；"
                      "**未做任何总结**"),
         "ordering_verified": KB_._row_order_checked,
         "window_size": len(ev)},
        ev, warnings, expect_entity=False)


# ─────────────────────────────────────────────────────────────── Tool 4

def resolve_entity(term, language="any", context=None):
    """实体解析（Phase 3 底层 + Phase 4A.1 叠加策略）。

    叠加层带来的三件事：
      1. 新实体（gaze / big-other / little-other / realite / signifie / demande /
         besoin / moi / term.objet）可解析；
      2. **后继优先**：`concept.l-autre` 与后继持同一别名时只返回后继（旧实体不删，
         在 `superseded` 里如实列出）；
      3. **上下文受限别名**（regard / autre / moi / demande / besoin / signifie）
         缺上下文时返回 AMBIGUOUS + `context_required=true`，**不静默解析**。
    """
    import entity_resolution as er
    import lacanian_semantic_guard as guard_mod
    import terminology_bridge as tb
    import query_router

    # 显式 entity_id：调用方（如 trace_concept/find_concept_evidence）直接给 id 时，
    # 它就是权威 —— 不该再拿 id 字符串去做词面解析（实测：`concept.signifie`
    # 作为 term 会被判 UNRESOLVED，于是实体型操作报 INSUFFICIENT_EVIDENCE）。
    explicit = None
    tid = str(term or "").strip()
    if re.match(r"^(concept|term|state|seminar|session|passage|matheme|structure|case|"
                r"topology|doc|person|philosopher|corpus-source|witness|trans|align)\.",
                tid):
        if tid in KB_.concepts() or onto.entity(tid) or onto.gold_concept(tid):
            explicit = tid
    if explicit:
        e = KB_.concepts().get(explicit) or {}
        ov = {"term": term, "context": context, "status": "RESOLVED",
              "entities": [{"entity_id": explicit,
                            "matched_alias": e.get("canonical_name"),
                            "origin": "explicit_entity_id",
                            "entity_type": e.get("type")}],
              "ambiguous": [], "context_required": False, "context_note": None,
              "context_required_entities": [], "superseded": [],
              "match_kind": "explicit_id", "alias_excluded": [],
              "notes": ["调用方给出的是 entity_id 本身 → 直接采用（origin=explicit_entity_id）"],
              "base_status": "RESOLVED", "base_entity_ids": [explicit],
              "disambiguated_by": None, "layer": onto.LAYER_ID}
    else:
        ov = onto.resolve(term, context)      # Phase 4A.1 叠加解析
    q = term if not context else "%s %s" % (term, context)
    plan = query_router.route(q)
    res = er.resolve(q, plan)
    guard = guard_mod.analyze(q, plan)

    # 二次查找：冠词归一化后的精确匹配
    normalized = []
    if not res["entities"] and not ov["entities"] and not ov["context_required"]:
        normalized = qt.normalized_alias_match(term)
        if normalized:
            res = dict(res)
            res["entities"] = [{"entity_id": n["entity_id"],
                                "matched_alias": n["alias"],
                                "origin": "alias_determiner_normalized",
                                "entity_type": n.get("entity_type")}
                               for n in normalized]

    by_alias = [a for a in res["ambiguous"]
                if a["alias"].strip().lower() == term.strip().lower()]
    candidates, _seen_ent = [], set()
    # ⚠️ 合并规则（Phase 4A.1）：
    #   * 叠加层一旦给出实体（含上下文解析），它就是本层的**解析权威** ——
    #     不再把 Phase 3 的候选补进来。第一版是 `ov + base` 直接相接，
    #     于是 `l'Autre` 又把被取代的 concept.l-autre 加了回来。
    #   * 叠加层没给实体（纯 gold 词）→ 用 Phase 3 结果，但剔除 superseded。
    #   * 最后统一做一次**规范名精确匹配**消歧（`signifiant` 这种 gold 内歧义）。
    superseded_ids = {s["entity_id"] for s in ov["superseded"]}
    base_ents = [{"entity_id": e["entity_id"], "matched_alias": e.get("matched_alias"),
                  "origin": e.get("origin", "entity_resolution"),
                  "entity_type": e.get("entity_type")}
                 for e in res["entities"] if e["entity_id"] not in superseded_ids]
    if ov["entities"]:
        merged = list(ov["entities"])
        if ov.get("disambiguated_by"):
            pass
    else:
        merged = base_ents
    disamb = onto.disambiguate(term, [e["entity_id"] for e in merged])
    if disamb["by"] and len(merged) > 1:
        keep = set(disamb["kept"])
        merged = [e for e in merged if e["entity_id"] in keep]
        ov = dict(ov)
        ov["notes"] = list(ov["notes"]) + [
            "规范名精确匹配消歧：保留 %s，其余 %s 不返回"
            "（disambiguated_by=canonical_name_exact）" % (disamb["kept"], disamb["dropped"])]
    for e in merged:
        eid = e["entity_id"]
        if not eid or eid in _seen_ent:
            continue
        _seen_ent.add(eid)
        aliases = tb.lexical_forms_for_entity(eid)[:12]
        g = KB_.concepts().get(eid) or {}
        cand = {"entity_id": eid, "entity_type": e.get("entity_type"),
                "matched_alias": e.get("matched_alias"), "origin": e["origin"],
                "aliases": aliases or (g.get("aliases") or [])[:12],
                "ontology_layer": g.get("_layer", "gold"),
                "canonical_name": g.get("canonical_name")}
        if g.get("_layer") == onto.LAYER_ID:
            cand["definition_status"] = g.get("definition_status")
            cand["context_required_aliases"] = g.get("context_required_aliases") or []
            cand["distinction_from"] = g.get("distinction_from") or []
        candidates.append(cand)

    collisions_raw = [w for w in guard.get("warnings") or []
                      if w["code"] == "ENTITY_COLLISION"]
    collisions, repaired_collisions = _split_repaired_collisions(collisions_raw)
    gaps_raw = [w for w in guard.get("warnings") or []
                if w["code"] in ("COUNTERPART_ENTITY_MISSING", "BOTH_ENTITIES_MISSING")]
    # 缺口同理：叠加层补齐的那一侧不再是缺口，改记 ontology_repairs
    gaps = []
    repaired_gaps = []
    for g in gaps_raw:
        pair = tuple(g.get("pair") or [])
        row = next((r for r in onto.guard_view() if tuple(r["pair"]) == pair), None)
        if row and row["post_repair_class"] in ("RESOLVED",
                                                "RESOLVED_CONTEXT_REQUIRED"):
            repaired_gaps.append({**g, "post_repair_class": row["post_repair_class"],
                                 "post_entities": row["post_entities"],
                                 "ontology_layer": onto.LAYER_ID})
        else:
            gaps.append(g)

    # 状态优先级：**上下文缺失**优先于 Phase 3 的碰撞标记 ——
    # 后者正是本层刚修好的那对（Autre/autre），再据此报 ENTITY_COLLISION
    # 就等于用旧缺陷解释新数据。
    if ov["context_required"] and not candidates:
        status = "AMBIGUOUS"
    elif collisions and not candidates:
        status = "ENTITY_COLLISION"
    elif by_alias or (res.get("ambiguous") and len(candidates) == 0):
        status = "AMBIGUOUS"
    elif candidates:
        status = "RESOLVED"
    else:
        status = "UNRESOLVED"
    # 叠加层判定与 Phase 3 判定冲突时，以叠加层为准（它才有新实体），但记下来
    if ov["status"] == "AMBIGUOUS" and not candidates and status == "UNRESOLVED":
        status = "AMBIGUOUS"
    if ov["status"] == "RESOLVED" and candidates:
        status = "RESOLVED"

    warnings = []
    for w in onto.annotate_warnings(collisions + gaps):
        warnings.append(_warn(w["code"], w["message"], w.get("severity", "warning"),
                              w.get("action"), pair=w.get("pair")))
    # 已修复的配对不再以原 code 出现（细节在 resolution.ontology_repairs）

    if repaired_collisions or repaired_gaps:
        warnings.append(_warn(
            "ONTOLOGY_REPAIRED",
            "Phase 3 报出的 %d 个碰撞 / %d 个缺口在 ontology.v4a1 里**已修复**，"
            "因此不再计入本次状态判定（旧结论保留在 bridge 里不动）：%s"
            % (len(repaired_collisions), len(repaired_gaps),
               [(r.get("pair"), r.get("post_repair_class"))
                for r in repaired_collisions + repaired_gaps]),
            "info", "见 ONTOLOGY_REPAIR_PHASE4A1.md 与 ontology_v4a1.guard_view()"))
    if ov["context_required"]:
        warnings.append(_warn(
            "CONTEXT_REQUIRED",
            "%r 是**上下文受限**的术语形式：%s。本层不会把它静默解析成任何实体 —— "
            "请提供上下文（或直接给 entity_id）。候选：%s"
            % (term, ov["context_note"], ov["context_required_entities"]),
            "warning", "在 context 参数里给出可判定上下文，或改用更专名的形式"))
    if ov["superseded"]:
        warnings.append(_warn(
            "SUPERSEDED_ENTITY",
            "旧实体 %s 已被 %s 取代（Phase 4A.1 entity_split）：解析结果不返回旧实体，"
            "但旧实体**保留**为审计记录。"
            % ([s["entity_id"] for s in ov["superseded"]],
               [s["superseded_by"] for s in ov["superseded"]]), "info"))
    if ov["alias_excluded"]:
        warnings.append(_warn(
            "ALIAS_EXCLUDED",
            "按 alias_exclude_forms 排除：%s（例如 objet a 的存在使裸 objet 不再匹配）"
            % ov["alias_excluded"], "info"))
    if normalized:
        warnings.append(_warn(
            "ALIAS_NORMALIZED",
            "%r 与别名 %s 在**去掉冠词后**精确相等（%s）—— "
            "这是写法归一化，不是语义相似；matched_alias 原样保留。"
            % (term, [n["alias"] for n in normalized],
               "entity=%s" % normalized[0]["entity_id"]), "info"))
    if status == "UNRESOLVED":
        warnings.append(_warn("UNRESOLVED_ENTITY",
                              "%r 在当前知识库里**没有**对应 entity。"
                              "本层不会用字符串相似去替它造一个。" % term,
                              "warning", "如需补实体，只能生成 ontology gap candidate"))

    reason = {
        "RESOLVED": "在 alias index（gold ∪ ontology.v4a1）里唯一命中",
        "AMBIGUOUS": "同一词形命中多个 entity，或该形式是上下文受限别名（未静默解析）",
        "UNRESOLVED": "alias index 里没有任何该词形的实体",
        "ENTITY_COLLISION": "该词属于一组「必须区分但知识库绑到同一 entity」的配对",
    }[status]

    return _envelope(
        {"tool": "resolve_entity", "term": term, "language": language,
         "context": context, "expect_entity": True},
        _resolution(
            status=status, entities=candidates, candidates=candidates,
            ambiguous=by_alias or res.get("ambiguous") or [],
            collisions=collisions, ontology_gaps=gaps, reason=reason,
            ontology_repairs=repaired_collisions + repaired_gaps,
            ontology_layer=(onto.LAYER_ID if ov["entities"] or ov["context_required"]
                            or ov["superseded"] or disamb["by"] else "gold"),
            context_required=ov["context_required"],
            context_note=ov["context_note"],
            context_required_entities=ov["context_required_entities"],
            superseded=ov["superseded"],
            disambiguated_by=ov.get("disambiguated_by"),
            alias_excluded=ov["alias_excluded"],
            resolution_notes=ov["notes"],
            base_layer_entity_ids=[i for i in ov["base_entity_ids"]
                                   if i not in superseded_ids],
            disambiguation=disamb,
            distinct_from=[{"subject": r["subject"], "object": r["object"],
                            "predicate": r["predicate"],
                            "evidence": r["evidence"]["passage_id"]}
                           for r in onto.load()["relations"]
                           if r["predicate"] == "distinct_from"
                           and term and (r["subject"] in _seen_ent
                                         or r["object"] in _seen_ent)],
            distinct_from_term=[{"pair": [r["source_form"], r["target_form"]],
                                 "binding": r.get("entity_binding"),
                                 "rationale": r.get("distinction_rationale")}
                                for r in tb.distinct_pairs()
                                if term.strip().lower() in
                                (r["source_form"].lower(), r["target_form"].lower())]),
        {"lookup": "entity_resolution.resolve（Phase 3，不改）∪ ontology.v4a1 叠加层；"
                   "exact-first（大小写/变音敏感）→ folded 兜底",
         "ontology_layer": onto.LAYER_ID if onto.available() else None,
         "ontology_resolution_ref": onto.layer_meta().get("resolution_ref"),
         "alias_normalized": bool(normalized),
         "bridge_rows_for_term": len(tb.expand(term)),
         "controlled_term_mapping": onto.terminology_lookup(term)["mappings"],
         "context_rule": onto.terminology_lookup(term)["context_rule"],
         "suggested_forms": ([c["target_form"] for c in
                              (terminology_lookup(term).get("resolution") or {}
                               ).get("candidates") or []][:6])},
        [], warnings, expect_entity=True)


# ─────────────────────────────────────────────────────────────── Tool 5

def get_concept(entity_id):
    import terminology_bridge as tb
    c = KB_.concepts().get(entity_id)
    warnings = []
    if not c:
        return _envelope({"tool": "get_concept", "entity_id": entity_id},
                         _resolution(status="UNRESOLVED"), {}, [],
                         [_warn("CONCEPT_NOT_FOUND",
                                "concepts.jsonl 里没有 %s" % entity_id, "error")],
                         expect_entity=True)
    linked = list(c.get("passages") or [])
    rels = [r for r in KB_.relations()
            if entity_id in (r.get("from"), r.get("to"), r.get("subject"), r.get("object"))]
    src_links = []
    p = os.path.join(VAULT, "concept_source_link_candidates.jsonl")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("concept_id") == entity_id:
                    src_links.append({"passage_id": r["candidate_passage_id"],
                                      "rank": r["rank"], "review_status": r["review_status"],
                                      "canonical": r["canonical"]})
    gaps = []
    if not linked:
        gaps.append({"type": "NO_LINKED_PASSAGE",
                     "detail": "该 concept 卡没有 passage 锚点（trace_status=%s）"
                               % c.get("trace_status")})
    if not (c.get("definition") or "").strip():
        gaps.append({"type": "NO_DEFINITION", "detail": "卡上没有定义字段"})
    if c.get("review_status") != "reviewed":
        warnings.append(_warn("NOT_REVIEWED",
                              "concept 卡 review_status=%s（不是 reviewed）—— "
                              "引用时不要当作已审定的定论。" % c.get("review_status"),
                              "info"))
    if c.get("trace_status") == "SOURCE_TRACE_INCOMPLETE":
        warnings.append(_warn("SOURCE_TRACE_INCOMPLETE",
                              "该 concept 依旧 SOURCE_TRACE_INCOMPLETE。", "info"))
    # 是否有 reviewed definition
    has_reviewed_def = bool((c.get("definition") or "").strip()) and \
        c.get("review_status") in ("reviewed", "adjudicated")
    retrieval = {
        "has_reviewed_definition": has_reviewed_def,
        "definition_status": ("reviewed" if has_reviewed_def
                              else "NOT_AVAILABLE —— 本层不生成定义"),
        "definition": (c.get("definition") if has_reviewed_def else None),
        "related_titles": c.get("related_titles") or [],
        "tags": c.get("tags") or [],
        "relations": [{"id": r.get("id"), "type": r.get("type") or r.get("relation_type"),
                       "from": r.get("from"), "to": r.get("to"),
                       "review_status": r.get("review_status"),
                       "created_by": r.get("created_by")} for r in rels],
        "relation_count": len(rels),
        "source_link_candidates": src_links[:10],
        "source_link_note": ("这些是 **candidate**（review_status=candidate），"
                             "不是已确认的溯源。"),
        "ontology_gaps": gaps,
    }
    return _envelope(
        {"tool": "get_concept", "entity_id": entity_id},
        _resolution(status="RESOLVED",
         entities=[{"entity_id": entity_id, "matched_alias": c.get("canonical_name"),
                    "origin": "concept_store", "required": True}],
         canonical_name=c.get("canonical_name"),
         zh=c.get("zh"), fr=c.get("fr"), en=c.get("en"),
         aliases=c.get("aliases") or [],
         bridge_forms=tb.lexical_forms_for_entity(entity_id)[:16],
         languages=[k for k in ("zh", "fr", "en") if (c.get(k) or "").strip()],
         concept_status=c.get("status"), review_status=c.get("review_status"),
         period=c.get("period"), period_label_c=c.get("period_label"),
         trace_status=c.get("trace_status"),
         canonical=c.get("canonical")),
        retrieval,
        [_passage_evidence(pid, why=["concept_card_link"], comp={"concept_card": 1},
                           rank=i + 1)
         for i, pid in enumerate(linked) if KB_.meta().get(pid)],
        warnings, expect_entity=True)


# ─────────────────────────────────────────────────────────────── Tool 6

def find_concept_evidence(concept, seminar=None, period=None, language="any",
                          top_k=15):
    """实体约束证据：先解析实体，再在**该实体**范围内取证据。"""
    r = resolve_entity(concept)
    status = r["resolution"]["resolution_status"]
    if status in ("UNRESOLVED",):
        return _envelope(
            {"tool": "find_concept_evidence", "concept": concept, "seminar": seminar,
             "period": period, "language": language, "top_k": top_k},
            r["resolution"], {"route": "NONE", "vector_enabled": False},
            [], r["warnings"] + [_warn("NO_EVIDENCE_QUERY",
                                       "实体未解析出来，因此**没有**构造检索 —— "
                                       "本层不会用字符串相似硬搜。", "warning")],
            expect_entity=True)
    ent_ids = [c["entity_id"] for c in r["resolution"]["candidates"]][:4]
    import terminology_bridge as tb
    forms = []
    for eid in ent_ids:
        forms += tb.lexical_forms_for_entity(eid)[:8]
        if onto.entity(eid):        # Phase 4A.1 叠加实体：带上自己的声明形式
            forms += onto.entity(eid).get("aliases") or []
    q = " ".join(dict.fromkeys([concept] + forms))
    out = search_passages(q, language=language, seminar=seminar, period=period,
                          entities=ent_ids, top_k=top_k)
    # 叠加实体的**声明证据**（由 build_ontology_v4a1 的词面/上下文规则现算）优先并入：
    # 这些段号可回查、可复算，比纯检索排名更能代表该实体的证据基础。
    declared = []
    for eid in ent_ids:
        e = onto.entity(eid)
        if e:
            declared += list(e.get("passages") or [])
    if declared:
        have = {x["passage_id"] for x in out["evidence"]}
        extra = [pid for pid in dict.fromkeys(declared) if pid not in have]
        added = []
        for i, pid in enumerate(extra[:max(0, top_k - len(out["evidence"]))]):
            item = _passage_evidence(pid, why=["ontology_declared_evidence"],
                                     comp={"ontology.v4a1": 1},
                                     rank=len(out["evidence"]) + i + 1)
            if item:
                added.append(item)
        if added:
            out["evidence"] = out["evidence"] + added
            out["coverage"] = _coverage(out["evidence"])
            out["provenance"] = _provenance_summary(out["evidence"])
            _recompute_state(out)
            out["warnings"].append(_warn(
                "ONTOLOGY_DECLARED_EVIDENCE",
                "并入 %d 条 **ontology.v4a1 声明证据**（由词面/上下文规则在 canonical "
                "store 上现算，见 _data/ontology/v4a1/evidence.jsonl）。"
                % len(added), "info"))
    out["request"] = {"tool": "find_concept_evidence", "concept": concept,
                      "seminar": seminar, "period": period, "language": language,
                      "top_k": top_k, "expect_entity": True,
                      "expanded_query_forms": list(dict.fromkeys(forms))[:16]}
    out["retrieval"]["entity_constraint"] = ent_ids
    if status in ("AMBIGUOUS", "ENTITY_COLLISION"):
        out["warnings"].append(_warn(
            "ENTITY_CONSTRAINT_UNCERTAIN",
            "实体解析状态是 %s —— 证据可能混入同一 entity 下的其它概念。" % status,
            "warning"))
    return out


# ─────────────────────────────────────────────────────────────── Tool 7

def trace_concept(concept, language="any", per_period=5):
    """历时证据组织：period → seminar → session。**不生成历史总结。**"""
    r = resolve_entity(concept)
    if r["resolution"]["resolution_status"] == "UNRESOLVED":
        return _envelope(
            {"tool": "trace_concept", "concept": concept, "language": language,
             "per_period": per_period},
            r["resolution"], {"route": "NONE"}, [], r["warnings"],
            expect_entity=True)
    ev_all = find_concept_evidence(concept, language=language, top_k=TOP_K_MAX)
    by_period = {}
    for e in ev_all["evidence"]:
        p = _period_of(e.get("seminar_id")) or "unknown"
        by_period.setdefault(p, []).append(e)
    groups = []
    for p in sorted(by_period):
        items = by_period[p][:per_period]
        sems = {}
        for e in items:
            sems.setdefault(e.get("seminar_id"), []).append(e.get("passage_id"))
        groups.append({"period": p, "evidence_n": len(items),
                       "seminars": [{"seminar_id": s, "passage_ids": ids[:8]}
                                    for s, ids in sorted(sems.items())]})
    known = ["1953-1955", "1955-1958", "1958-1961", "1961-1964", "1964-1966",
             "1966-1969", "1969-1972", "1972-1975", "1975-1978", "1978-1981"]
    warnings = list(ev_all["warnings"])
    gaps = [{"code": "NO_EVIDENCE_FOR_PERIOD", "period": p}
            for p in known if p not in by_period]
    if "unknown" in by_period:
        gaps.append({"code": "PERIOD_UNKNOWN_FOR_SOME_EVIDENCE",
                     "n": len(by_period["unknown"])})
    if gaps:
        warnings.append(_warn("COVERAGE_GAPS",
                              "历时覆盖存在缺口（%d 个 period 无证据）—— "
                              "**不得据此断言该时期没有论述**。" % len(gaps),
                              "warning"))
    out = _envelope(
        {"tool": "trace_concept", "concept": concept, "language": language,
         "per_period": per_period},
        r["resolution"],
        {**ev_all["retrieval"], "grouping": "period → seminar → session",
         "period_groups": groups},
        ev_all["evidence"],
        warnings, expect_entity=True,
        extra_coverage={"coverage_gaps": gaps, "periods_with_evidence":
                        [g["period"] for g in groups]})
    return out


# ─────────────────────────────────────────────────────────────── Tool 8

def compare_concepts(concept_a, concept_b, language="any", top_k=10):
    """两概念对比 —— **必须用独立 lane**（§8/§4 Tool 8），不拼成一个 query。"""
    import lacanian_semantic_guard as guard_mod
    ra, rb = resolve_entity(concept_a), resolve_entity(concept_b)
    warnings = []
    combined = "%s %s" % (concept_a, concept_b)
    guard = guard_mod.analyze(combined)
    # 原始 guard 告警（带 pair）先做修复重分类，再决定哪些进 warnings
    _c_raw = [w for w in guard.get("warnings") or [] if w["code"] == "ENTITY_COLLISION"]
    _c_live, _c_rep = _split_repaired_collisions(_c_raw)
    _g_raw0 = [w for w in guard.get("warnings") or []
               if w["code"] in ("COUNTERPART_ENTITY_MISSING", "BOTH_ENTITIES_MISSING")]
    _g_live0, _g_rep0 = _split_repaired_gaps(_g_raw0)
    _rep_pairs = {tuple(r.get("pair") or []) for r in (_c_rep + _g_rep0)}
    for w in guard.get("warnings") or []:
        if tuple(w.get("pair") or []) in _rep_pairs:
            continue
        warnings.append(_warn(w["code"], w["message"], w.get("severity", "warning"),
                              w.get("action"), pair=w.get("pair")))
    warnings.append(_warn("SEPARATE_LANES_ENFORCED",
                          "两侧**分别**检索后并列，未把两个概念拼成一个 query；"
                          "因此不会在检索阶段把两者混为一个语义目标。", "info"))

    def lane(c):
        rr = resolve_entity(c)
        if rr["resolution"]["resolution_status"] == "UNRESOLVED":
            return {"concept": c, "resolution": rr["resolution"],
                    "evidence": [], "state": "INSUFFICIENT_EVIDENCE"}
        ev = find_concept_evidence(c, language=language, top_k=top_k)
        return {"concept": c, "resolution": ev["resolution"],
                "evidence": ev["evidence"], "coverage": ev["coverage"],
                "state": ev["evidence_state"]["state"], "lane_query": None,
                # lane 自己的告警必须带上来：某一侧 UNRESOLVED 是**对比的结论性事实**，
                # 丢在 lane 内部就等于把「一侧根本没有实体」藏起来了。
                "warnings": ev.get("warnings") or [],
                "ontology_gaps": (ev.get("resolution") or {}).get("ontology_gaps") or [],
                # ⚠️ 必须把 lane 内部的 `component_counts` 带上来：
                #    否则 sufficiency 看到的「独立检索族」是 0 个，
                #    于是所有对比类查询都会显示「一致性信号不适用（?）」。
                "component_counts": ((ev.get("retrieval") or {})
                                     .get("component_counts") or {})}

    la, lb = lane(concept_a), lane(concept_b)
    # 共享上下文：两侧证据所属 session 的交集（**结构性**，不是语义判断）
    sa = {e["session_id"] for e in la["evidence"]}
    sb = {e["session_id"] for e in lb["evidence"]}
    shared = sorted(sa & sb)
    pa = {e["passage_id"] for e in la["evidence"]}
    pb = {e["passage_id"] for e in lb["evidence"]}
    overlap = sorted(pa & pb)
    if overlap:
        warnings.append(_warn("EVIDENCE_OVERLAP",
                              "两侧 lane 有 %d 条相同 passage（同一段同时被两边命中）——"
                              "对比时不能把它当作区分性证据。" % len(overlap),
                              "warning"))
    # ── lane 告警与缺口上浮（去重，保序）
    seen_codes = {w.get("code") for w in warnings}
    lane_gaps = []
    for tag, lane_ in (("a", la), ("b", lb)):
        for w in lane_.get("warnings") or []:
            if w.get("code") in seen_codes:
                continue
            seen_codes.add(w.get("code"))
            warnings.append({**w, "lane": tag,
                             "message": "[lane %s · %s] %s"
                                        % (tag, lane_["concept"], w.get("message"))})
        for g in lane_.get("ontology_gaps") or []:
            lane_gaps.append({**g, "lane": tag, "lane_concept": lane_["concept"]})

    agg_counts = {}
    for lane_ in (la, lb):
        for k, v in (lane_.get("component_counts") or {}).items():
            agg_counts[k] = agg_counts.get(k, 0) + v
    retrieval = {
        "route": "CONCEPT_COMPARISON",
        "lanes_mode": "per_concept",
        "component_counts": agg_counts,
        "lanes": [{"lane": "a", "concept": concept_a,
                   "resolution_status": la["resolution"]["resolution_status"],
                   "evidence_n": len(la["evidence"]), "state": la["state"]},
                  {"lane": "b", "concept": concept_b,
                   "resolution_status": lb["resolution"]["resolution_status"],
                   "evidence_n": len(lb["evidence"]), "state": lb["state"]}],
        "merge_policy": "FORBID_MERGE",
        "vector_enabled": None,
        "shared_sessions": shared,
        "overlapping_passage_ids": overlap[:20],
        "no_theoretical_conclusion": ("本工具**不下理论结论** —— "
                                      "它只并列两侧证据与覆盖度。"),
    }
    # envelope 的 evidence 用「a 的」为主，两侧都在 retrieval.lanes 里；再并进 evidence[]
    merged = []
    for e in la["evidence"]:
        merged.append({**e, "lane": "a"})
    for e in lb["evidence"]:
        merged.append({**e, "lane": "b"})
    _g_raw = ([w for w in warnings
               if w["code"] in ("COUNTERPART_ENTITY_MISSING",
                                "BOTH_ENTITIES_MISSING")] + lane_gaps)
    _g_live, _g_rep = _split_repaired_gaps(_g_raw)
    _g_rep = _g_rep0 + _g_rep
    if _c_rep or _g_rep:
        warnings.append(_warn(
            "ONTOLOGY_REPAIRED",
            "Phase 3 报出的碰撞/缺口在 ontology.v4a1 里已修复，本次对比按独立实体进行：%s"
            % [(r.get("pair"), r.get("post_repair_class")) for r in _c_rep + _g_rep],
            "info", "见 ONTOLOGY_REPAIR_PHASE4A1.md"))
    resolution = _resolution(
        status=("ENTITY_COLLISION" if _c_live
                else "RESOLVED" if la["evidence"] and lb["evidence"] else "PARTIAL"),
        entities=(ra["resolution"]["entities"] + rb["resolution"]["entities"]),
        ambiguous=(ra["resolution"].get("ambiguous") or [])
        + (rb["resolution"].get("ambiguous") or []),
        collisions=_c_live,
        ontology_gaps=_g_live,
        ontology_repairs=_c_rep + _g_rep,
        ontology_layer=("ontology.v4a1"
                        if any(e.startswith(("concept.", "term.")) and onto.entity(e)
                               for e in (concept_a, concept_b))
                        else "gold"),
        lane_a=la["resolution"], lane_b=lb["resolution"])
    # 对比操作要求**两条 lane 都有证据**，否则不是「支持了对比」而是「只支持一侧」
    na, nb = len(la["evidence"]), len(lb["evidence"])
    if na == 0 and nb == 0:
        ov = {"state": "INSUFFICIENT_EVIDENCE",
              "reasons": ["两侧 lane 都没有证据。"],
              "note": "compare_concepts 要求两条 lane 各自有证据",
              "signals_addendum": {"lane_a_evidence_n": 0, "lane_b_evidence_n": 0}}
    elif na == 0 or nb == 0:
        empty = concept_a if na == 0 else concept_b
        other = concept_b if na == 0 else concept_a
        ov = {"state": "PARTIALLY_SUPPORTED",
              "reasons": ["lane「%s」证据数 = 0 —— 对比的**一侧完全没有证据**，"
                          "因此只能呈现另一侧（%s）的材料，"
                          "不足以支持对称对比。" % (empty, other)],
              "note": "compare_concepts 要求两条 lane 各自有证据",
              "signals_addendum": {"lane_a_evidence_n": na, "lane_b_evidence_n": nb}}
    else:
        ov = None
    return _envelope(
        {"tool": "compare_concepts", "concept_a": concept_a, "concept_b": concept_b,
         "language": language, "top_k": top_k},
        resolution, retrieval, merged, warnings, expect_entity=True,
        extra_coverage={"shared_session_n": len(shared), "overlap_n": len(overlap),
                        "lane_a_evidence_n": na, "lane_b_evidence_n": nb},
        state_override=ov)


# ─────────────────────────────────────────────────────────────── Tool 9

def trace_source(passage_id):
    m = KB_.meta().get(passage_id)
    if not m:
        return _envelope({"tool": "trace_source", "passage_id": passage_id},
                         {"resolution_status": "PASSAGE_NOT_FOUND"}, {}, [],
                         [_warn("PASSAGE_NOT_FOUND",
                                "canonical passage store 里没有 id=%s" % passage_id,
                                "error")])
    links = KB_.witness_links().get(passage_id) or []
    reals = KB_.realizations().get(passage_id) or []
    wids = {m.get("witness_id")} | {l.get("witness_id") for l in links}
    wids.discard(None)
    chain = []
    for wid in sorted(wids):
        w = KB_.witnesses().get(wid) or {}
        csid = w.get("corpus_source_id") or m.get("corpus_source_id")
        cs = KB_.corpus_sources().get(csid) or {}
        chain.append({
            "witness_id": wid, "witness_type": w.get("witness_type"),
            "language": w.get("language"), "upstream_state": w.get("upstream_state"),
            "corpus_source_id": csid,
            "corpus_source": {k: cs.get(k) for k in
                              ("title", "corpus_source_type", "authority_level",
                               "language", "license_note", "upstream_url")
                              if cs.get(k) is not None},
            "corpus_source_files": cs.get("files"),
        })
    gaps = []
    if m.get("trace_status") == "SOURCE_TRACE_INCOMPLETE":
        gaps.append({"code": "SOURCE_TRACE_INCOMPLETE",
                     "detail": "上游原件缺失；中文条目来自 translation witness"})
    prov = {
        "chain": chain,
        "passage_realizations": [{"realization_id": r.get("id"),
                                  "witness_id": r.get("witness_id"),
                                  "segment_sha256": (r.get("provenance") or {}).get("segment_sha256")
                                  or r.get("segment_sha256")} for r in reals[:6]],
        "physical_file": None,
        "physical_sha256": None,
        "recovered_file": None,
        "trace_status": m.get("trace_status"),
        "gaps": gaps,
        "recovered_corpus_note": ("该语料是从唯一幸存的中间产物 recovered 而来，"
                                  "上游原件不在本机 —— 这一条**必须**随证据一起展示。"
                                  if m.get("trace_status") == "SOURCE_TRACE_INCOMPLETE"
                                  else None),
    }
    warnings = []
    if gaps:
        warnings.append(_warn("SOURCE_TRACE_INCOMPLETE",
                              "溯源链在 corpus source 之后就断了（上游原件缺失）。",
                              "warning",
                              "引用时附带该告警；不得伪装成已闭合的 primary source"))
    return _envelope(
        {"tool": "trace_source", "passage_id": passage_id},
        _resolution(status="RESOLVED", entities=[], resolved_passage=passage_id,
                    witness_count=len(chain)),
        {"lookup": "passage → realization → witness → corpus_source",
         "chain_complete": not gaps,
         "chain_steps": len(chain)},
        [_passage_evidence(passage_id, why=["source_trace"], comp={"trace": 1}, rank=1)],
        warnings, expect_entity=False,
        extra_coverage={"chain_len": len(chain)},
        # ⚠️ 第一版把链建好却**没有交出去**（prov 变量成了死代码）——
        #    provenance section 只剩 trace_status 计数，调用方看不到 witness/corpus source。
        extra_provenance={"chain": chain, "gaps": gaps,
                          "recovered_corpus_note": prov["recovered_corpus_note"],
                          "passage_realizations": prov["passage_realizations"]})


# ─────────────────────────────────────────────────────────────── Tool 10

def terminology_lookup(term, source_language="any", target_language="any"):
    import terminology_bridge as tb
    eq = tb.expand(term, target_langs=(None if target_language == "any"
                                       else (target_language,)),
                   source_lang=(None if source_language == "any" else source_language))
    distinct = [r for r in tb.distinct_pairs()
                if term.strip().lower() in (r["source_form"].lower(),
                                            r["target_form"].lower())]
    warnings = []
    if not eq and not onto.terminology_lookup(term)["mappings"]:
        warnings.append(_warn("NO_CONTROLLED_MAPPING",
                              "%r 在 Terminology Bridge 里**没有**受控映射 —— "
                              "本工具不做机器翻译，也不会猜一个译文。" % term,
                              "warning",
                              "如需新映射，只能生成 ontology gap candidate"))
    if distinct:
        warnings.append(_warn("DISTINCT_FROM",
                              "%r 属于一组**必须区分、不得等同**的配对：%s。"
                              "Bridge 不会给出它与对方之间的等价映射。"
                              % (term, [r["source_form"] + "/" + r["target_form"]
                                        for r in distinct]),
                              "warning"))
    rows = []
    seen = set()
    for m in eq:
        key = (m["target_form"], m["entity_id"])
        if key in seen:
            continue
        seen.add(key)
        rows.append({"target_form": m["target_form"],
                     "target_language": m["target_language"],
                     "entity_id": m["entity_id"], "term_id": m["term_id"],
                     "source_form": m["source_form"],
                     "relation_type": "equivalent",
                     "review_status": "candidate",
                     "provenance": "concept_store（同 entity 的跨语言写法）"})
    # ── Phase 4A.1：受控术语映射（controlled_term_mapping）
    ovm = onto.terminology_lookup(term)
    for m in ovm["mappings"]:
        key = ("ctm", m["mapping_id"])
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "mapping_id": m["mapping_id"],
            "entity_id": m["entity_id"],
            "source_form": m["source_form"], "source_language": m["source_language"],
            "target_form": m["target_form"], "target_language": m["target_language"],
            "relation_type": "controlled_term_mapping",
            "context_requirement": m["context_requirement"],
            "context_rule": m.get("context_rule"),
            "auto_resolution": m["auto_resolution"],
            "auto_expansion": m["auto_expansion"],
            "distinction_guard": m.get("distinction_guard") or [],
            "review_status": m.get("review_status"),
            "layer": onto.LAYER_ID,
            "provenance": "ontology.v4a1/term_mappings.jsonl",
        })
    if ovm["mappings"]:
        warnings.append(_warn(
            "CONTROLLED_TERM_MAPPING",
            "%r 在 Phase 4A.1 里有**受控术语映射**（controlled_term_mapping）：%s。"
            "它与 equivalent 的区别是：每个形式各自带上下文条件与自动解析策略，"
            "不是无条件同义。"
            % (term, [(m["source_form"] + "→" + m["target_form"])
                      for m in ovm["mappings"]]),
            "info"))
    if ovm["context_required"]:
        warnings.append(_warn(
            "CONTEXT_REQUIRED",
            "%r 是需要上下文的映射（auto_resolution=false）：%s"
            % (term, (ovm.get("context_rule") or {}).get("on_missing_context")),
            "warning"))
    return _envelope(
        {"tool": "terminology_lookup", "term": term,
         "source_language": source_language, "target_language": target_language},
        _resolution(
            status="RESOLVED" if (eq or ovm["mappings"]) else "UNRESOLVED",
            entities=[{"entity_id": e, "matched_alias": None,
                       "origin": ("ontology.v4a1" if e in ovm["entity_ids"] else "bridge"),
                       "required": True}
                      for e in sorted({m["entity_id"] for m in eq}
                                      | set(ovm["entity_ids"]))],
            candidates=rows,
            distinct_from=[{"pair": [r["source_form"], r["target_form"]],
                            "binding": r.get("entity_binding"),
                            "rationale": r.get("distinction_rationale")}
                           for r in distinct],
            note=("这是**受控术语映射**，不是机器翻译；"
                  "review_status=candidate 表示尚未人工逐条审阅。"),
            ontology_layer=(onto.LAYER_ID if ovm["mappings"] else "gold"),
            context_required=ovm["context_required"],
            controlled_term_mapping=ovm["mappings"]),
        {"source": "terminology_bridge ∪ ontology.v4a1",
         "equivalent_rows_total": len(tb.equivalents()),
         "distinct_from_rows_total": len(tb.distinct_pairs()),
         "controlled_term_mapping_rows": len(ovm["mappings"]),
         "ontology_resolution_ref": onto.layer_meta().get("resolution_ref")},
        [_passage_evidence(pid, why=["controlled_term_mapping_evidence"],
                           comp={"ontology.v4a1": 1}, rank=i + 1)
         for i, pid in enumerate(dict.fromkeys(
             [pid for m in ovm["mappings"] for pid in (m.get("evidence") or [])]))
         if KB_.meta().get(pid)],
        warnings, expect_entity=True)


# ─────────────────────────────────────────────────────────────── dispatch

DISPATCH = {
    "search_passages": search_passages,
    "get_passage": get_passage,
    "get_context": get_context,
    "resolve_entity": resolve_entity,
    "get_concept": get_concept,
    "find_concept_evidence": find_concept_evidence,
    "trace_concept": trace_concept,
    "compare_concepts": compare_concepts,
    "trace_source": trace_source,
    "terminology_lookup": terminology_lookup,
}


def call(tool, args):
    """统一入口：调用某个 tool 并返回**共享 8-section** 响应。"""
    if tool not in DISPATCH:
        raise KeyError("unknown tool: %s" % tool)
    return DISPATCH[tool](**(args or {}))
