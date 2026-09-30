#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4a_research.py — Phase 4A §11–§13 / §17 / §18 / §22：Research Agent

测什么
──────
* **多步通用 loop**，不是某一条问题硬编码：A–J 十个问题都要能跑出**分类正确**的结果
* **预算**（§13）：`max_tool_calls` 必须真的封顶，超了要如实报 limitations
* **trace 结构化**（§18）：只记 tool/参数/结果摘要/决策，**不记隐藏推理**
* **对比必须分道**（§8）：两侧 lane 独立，lane 名必须是真词而不是疑问片段
* **自适应重试**（§12）：约束放宽 / 桥扩展真的会触发，并在 trace 里留痕
* **缺口只记候选**（§22）：`status: candidate`、`canonical_change_proposed: false`
* **只读**（§21）：跑完 agent，canonical store 与索引的哈希不变
* **引用契约**（§14/§15）：citation 校验器能抓出「编造的 id」与「缺引用断言」
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
MCP = os.path.join(TOOLS, "lacan_mcp")
STORE = os.path.join(VAULT, "_data", "passage_store")
sys.path.insert(0, TOOLS)
sys.path.insert(0, MCP)

import research_agent as ra  # noqa: E402
import ontology_gaps as ogq  # noqa: E402
import citations as cit  # noqa: E402
import knowledge_api as api  # noqa: E402
import query_terms as qt  # noqa: E402

A_J = [
    ("A", "什么是 objet a？", "cross_language"),
    ("B", "desire 和 demand 有什么区别？", "comparison"),
    ("C", "Seminar XI 如何讨论 gaze？", "seminar"),
    ("D", "研讨班十一期如何讨论凝视？", "seminar"),
    ("E", "l'Autre 与 l'autre 有什么区别", "comparison"),
    ("F", "What does Lacan mean by jouissance?", "concept"),
    ("G", "Le réel et la réalité", "contrastive"),
    ("H", "jouissance 在研讨班七期", "seminar"),
    ("I", "What is the difference between the Symbolic and the Imaginary?", "comparison"),
    ("J", "signifiant 和 signifié", "contrastive"),
]

TRACE_KEYS = {"step", "tool", "arguments", "result_digest", "decision", "note"}
DIGEST_KEYS = {"evidence_n", "evidence_ids", "state", "resolution_status",
               "route", "warnings"}


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class TestQueryPlanning(unittest.TestCase):
    """§0 侦察发现的真实缺陷：把自然语言整句送进词法层 → 0 命中。"""

    def test_01_question_fragments_are_not_terms(self):
        for q in ("desire 和 demand 有什么区别？", "什么是 objet a？",
                  "Seminar XI 如何讨论 gaze？"):
            terms = qt.salient_terms(q)
            for bad in ("有什么区别", "什么是", "如何讨论", "between", "and"):
                self.assertNotIn(bad, terms, "%s 泄漏进了显著词" % q)
        self.assertEqual(qt.salient_terms("desire 和 demand 有什么区别？"),
                         ["desire", "demand"])

    def test_02_alias_terms_come_from_the_kb_not_from_heuristics(self):
        self.assertIn("objet a", qt.salient_terms("什么是 objet a？"))
        self.assertIn("the Symbolic", qt.salient_terms(
            "What is the difference between the Symbolic and the Imaginary?"))

    def test_03_effective_query_recovers_zero_hit_sentences(self):
        cases = [({"query": "如何讨论凝视"}, "凝视"),
                 ({"query": "jouissance 在研讨班七期", "seminar": "seminar.S07"},
                  "jouissance")]
        for args, want in cases:
            r = api.search_passages(top_k=5, **args)
            self.assertEqual(r["retrieval"]["query_strategy"], "term_decomposition")
            self.assertEqual(r["retrieval"]["effective_query"], want)
            self.assertGreater(len(r["evidence"]), 0,
                               "%s 应当能取到证据（语料里确实有）" % args)
            self.assertIn("QUERY_DECOMPOSED", [w["code"] for w in r["warnings"]])

    def test_04_no_vocabulary_hit_is_not_silently_empty(self):
        r = api.search_passages("zzzqqqxxx不存在的词", top_k=5)
        self.assertEqual(r["evidence"], [])
        codes = [w["code"] for w in r["warnings"]]
        self.assertIn("NO_VOCABULARY_HIT", codes)
        self.assertIn("TERMS_NOT_IN_CORPUS", codes)


class TestResearchLoop(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.runs = {}
        for tag, q, _ in A_J:
            cls.runs[tag] = ra.research(q, record_gaps=False)

    def test_10_every_query_classified_as_expected(self):
        for tag, q, want in A_J:
            p = self.runs[tag]["evidence_pack"]
            self.assertEqual(p["query_type"], want, "%s: %s" % (tag, q))
            self.assertEqual(p["query"], q)

    def test_11_no_query_crashes_and_all_have_eight_sections(self):
        for tag, q, _ in A_J:
            p = self.runs[tag]["evidence_pack"]
            for sec in ("query", "query_type", "retrieval_route", "evidence",
                        "evidence_state", "citable_passages", "limitations",
                        "citation_contract"):
                self.assertIn(sec, p, tag)
            self.assertEqual(p["evidence_state"]["method"],
                             "structural_only_no_cosine_threshold")

    def test_12_evidence_ids_are_real_and_citable(self):
        known = set()
        with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    known.add(json.loads(line)["id"])
        for tag, q, _ in A_J:
            p = self.runs[tag]["evidence_pack"]
            for e in p["evidence"]:
                self.assertIn(e["passage_id"], known, tag)
            self.assertEqual(p["citable_passages"],
                             [e["passage_id"] for e in p["evidence"]], tag)

    def test_13_budget_is_enforced(self):
        r = ra.research("什么是 objet a？", budget={"max_tool_calls": 2,
                                                   "max_passages": 5,
                                                   "max_context_expansions": 0,
                                                   "max_retries": 0},
                        record_gaps=False)
        used = r["budget"]["used"]
        self.assertLessEqual(used["tool_calls"], 2)
        self.assertLessEqual(used["passages"], 5)
        self.assertLessEqual(used["context_expansions"], 0)
        self.assertTrue(r["evidence_pack"]["limitations"], "超预算必须写进 limitations")

    def test_14_budget_defaults_match_spec(self):
        self.assertEqual(ra.DEFAULT_BUDGET["max_tool_calls"], 12)
        r = ra.research("le désir", record_gaps=False)
        self.assertEqual(r["budget"]["config"]["max_tool_calls"], 12)
        self.assertLessEqual(r["budget"]["used"]["tool_calls"], 12)

    def test_15_trace_has_no_hidden_reasoning(self):
        for tag, q, _ in A_J:
            tr = self.runs[tag]["research_trace"]
            self.assertTrue(tr["no_hidden_reasoning"])
            for st in tr["steps"]:
                self.assertLessEqual(set(st), TRACE_KEYS, st)
                self.assertLessEqual(set(st["result_digest"]), DIGEST_KEYS, st)
                self.assertTrue(st["tool"])
                self.assertIsInstance(st["arguments"], dict)
            # 只看**内容**：`no_hidden_reasoning` 这个键名本身会撞上关键词，
            # 所以先把它摘掉再扫。
            blob = json.dumps({k: v for k, v in tr.items()
                               if k != "no_hidden_reasoning"},
                              ensure_ascii=False).lower()
            for forbidden in ("chain of thought", "chain_of_thought", "thinking",
                              "thought", "因为所以", "我的推理", "内心独白"):
                self.assertNotIn(forbidden, blob, tag)

    def test_16_comparison_uses_separate_lanes_with_real_terms(self):
        # 对比类问题必须真的走到 compare_concepts（独立 lane），而不是拼成一个 query
        for tag in ("B", "E", "I", "J"):
            tools = [x["tool"] for x in self.runs[tag]["research_trace"]["steps"]]
            self.assertIn("compare_concepts", tools, "%s 没有走分道对比：%s" % (tag, tools))
        # 直接核 lane 结构（比 trace 摘要更硬）：lane 名必须是**真词**，
        # 不能是「有什么区别」这种疑问片段（第一版的真实 bug）
        r = api.compare_concepts("desire", "demand", top_k=5)
        self.assertEqual(r["retrieval"]["lanes_mode"], "per_concept")
        self.assertEqual(r["retrieval"]["merge_policy"], "FORBID_MERGE")
        lanes = r["retrieval"]["lanes"]
        self.assertEqual([l["lane"] for l in lanes], ["a", "b"])
        self.assertEqual([l["concept"] for l in lanes], ["desire", "demand"])
        for l in lanes:
            # 用**整词相等**判定：`and` 是 `demand` 的子串，
            # 子串检查会误报（第一版就是这样误报的）。
            self.assertNotIn(l["concept"].strip().lower(),
                             ("有什么区别", "between", "and", "difference",
                              "区别", "vs", "versus"))
        self.assertIn("SEPARATE_LANES_ENFORCED",
                      [w["code"] for w in r["warnings"]])
        # 证据条目带 lane 标记，且两侧不合并
        self.assertTrue(all(e.get("lane") in ("a", "b") for e in r["evidence"]))

    # ── 以下三条在 Phase 4A.1 之后**按版本化方式更新**：
    #    Phase 4A.1 修好了 gaze/regard、Autre/autre、signifié、demande 这些缺口，
    #    于是旧断言（「一侧无证据」「CONFLICTING_EVIDENCE」）描述的已不再是当前事实。
    #    更新方式：**断言当前（修复后）行为** + **断言历史事实仍可观测**
    #    （Phase 3 的 bridge / guard 结论一行未改，见 TestHistoricalFactsPreserved）。
    #    这是「版本化的本体层」，不是把旧 benchmark 改写成好看的数字。

    def test_17_adaptive_retry_fires_and_leaves_a_trace(self):
        """C 类：英文 gaze 在 S11 内 0 段，但概念本身有中文/法文形式。

        修复后 agent 仍要**多步**（先解析、再检索、术语桥、再检索），并且
        必须如实交代证据是怎么来的 —— 要么找到 S11 内的其他形式，
        要么说明放宽到了别的研讨班。
        """
        r = self.runs["C"]
        tools = [s["tool"] for s in r["research_trace"]["steps"]]
        self.assertGreaterEqual(tools.count("search_passages"), 2,
                                "多步检索没有触发：%s" % tools)
        p = r["evidence_pack"]
        self.assertGreater(p["evidence_n"], 0, "修复后 gaze 必须能取到证据")
        st = p["evidence_state"]
        self.assertIn(st["state"], ("SUPPORTED", "PARTIALLY_SUPPORTED"))
        # 如果约束确实无法满足，必须明说来自别处；否则必须给出 S11 内的证据
        s11 = [e for e in p["evidence"] if e.get("seminar_id") == "seminar.S11"]
        if not s11:
            self.assertTrue(any("别的研讨班" in l or "放宽" in l
                                for l in p["limitations"]),
                            "没有 S11 证据时必须说明放宽了约束：%s" % p["limitations"])

    def test_18_comparison_with_previously_missing_side_is_now_supported(self):
        """B/J：Phase 4A 时「一侧没有实体」，4A.1 已补齐 → 对比两侧都成立。

        同时验证**歧义候选没有被当成对比的两侧**这一条仍然成立。
        """
        for tag in ("B", "J"):
            p = self.runs[tag]["evidence_pack"]
            st = p["evidence_state"]
            self.assertEqual(st["state"], "SUPPORTED", "%s: %s" % (tag, st["reasons"]))
            lanes = None
            for step in self.runs[tag]["research_trace"]["steps"]:
                if step["tool"] == "compare_concepts":
                    lanes = step["arguments"]
            self.assertIsNotNone(lanes, "%s 没有走分道对比" % tag)
        # 两侧都解析出来（且是**不同的**实体）
        for tag, want in (("B", {"concept.desir", "concept.demande"}),
                          ("J", {"concept.signifiant", "concept.signifie"})):
            got = set(self.runs[tag]["evidence_pack"]["resolved_entities"])
            self.assertTrue(want <= got, "%s 期望 %s，实际 %s" % (tag, want, got))

    def test_19_collision_pair_is_repaired_and_historical_fact_preserved(self):
        """E：`l'Autre`/`l'autre` 的 ENTITY_COLLISION 已拆成两个实体。

        * 当前层：不再是 CONFLICTING_EVIDENCE，两侧解析到不同实体；
        * 历史事实：Phase 3 的 bridge 里那行 `distinct_from/ENTITY_COLLISION`
          **原样保留**（不被本相位重写），并可被 `guard_view()` 对照出来。
        """
        st = self.runs["E"]["evidence_pack"]["evidence_state"]
        self.assertNotEqual(st["state"], "CONFLICTING_EVIDENCE",
                            "修复后不应再是 CONFLICTING_EVIDENCE")
        ents = set(self.runs["E"]["evidence_pack"]["resolved_entities"])
        self.assertIn("concept.big-other", ents)
        self.assertIn("concept.little-other", ents)
        # 历史事实仍在 Phase 3 数据里
        import terminology_bridge as tb
        rows = [r for r in tb.distinct_pairs()
                if {r["source_form"], r["target_form"]} == {"Autre", "autre"}]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_binding"], "ENTITY_COLLISION")
        import ontology_v4a1 as onto
        view = {tuple(r["pair"]): r for r in onto.guard_view()}
        row = view[("Autre", "autre")]
        self.assertEqual(row["pre_repair_class"], "ENTITY_COLLISION")
        self.assertEqual(row["post_repair_class"], "RESOLVED_CONTEXT_REQUIRED")

    def test_20_english_terms_resolve_via_determiner_normalization(self):
        r = self.runs["I"]["evidence_pack"]
        self.assertIn("concept.le-symbolique", r["resolved_entities"])
        self.assertIn("concept.l-imaginaire", r["resolved_entities"])
        rr = api.resolve_entity("Symbolic")
        self.assertEqual(rr["resolution"]["resolution_status"], "RESOLVED")
        self.assertIn("ALIAS_NORMALIZED", [w["code"] for w in rr["warnings"]])
        self.assertTrue(rr["retrieval"]["alias_normalized"])

    def test_21_trace_source_chain_is_present_when_evidence_exists(self):
        for tag in ("A", "I"):
            p = self.runs[tag]["evidence_pack"]
            if p["evidence"]:
                self.assertIn("source_trace", p, tag)

    def test_22_agent_never_writes_canonical(self):
        watch = [os.path.join(STORE, n) for n in
                 ("passages.jsonl", "concepts.jsonl", "concept_states.jsonl",
                  "claims.jsonl", "alignments.jsonl")]
        watch.append(os.path.join(VAULT, "_data", "index", "lexical.sqlite"))
        before = {p: _sha(p) for p in watch if os.path.isfile(p)}
        ra.research("什么是 objet a？", record_gaps=False)
        after = {p: _sha(p) for p in before}
        self.assertEqual(before, after)


class TestOntologyGapQueue(unittest.TestCase):

    def test_30_new_gaps_are_recorded_as_candidates_only(self):
        """§22：**新发现**的缺口只能是 candidate，且永不提议改动 canonical。

        Phase 4A.1 起，队列里同时存在 `resolved` / `invalidated` 的历史条目
        （§9 要求保留 audit trail），所以这里断言的是：
          * 新 `propose()` 出来的行是 candidate；
          * 任何状态的行的 `canonical_change_proposed` 都是 False。
        """
        r = api.resolve_entity("gaze")
        ogq.from_response(r, "test")
        rows = ogq.read_all()
        self.assertTrue(rows, "缺口没有被记录")
        for row in rows:
            self.assertIn(row["status"], ("candidate", "resolved", "invalidated"))
            self.assertFalse(row["canonical_change_proposed"])
            self.assertIn(row["issue_type"], ogq.ISSUE_TYPES)
            self.assertTrue(row["detected_by"])
            self.assertTrue(row["issue_id"].startswith("ogq."))

    def test_31_gap_queue_is_deduped_and_append_only(self):
        before = len(ogq.read_all())
        r = api.resolve_entity("gaze")
        ogq.from_response(r, "test")
        self.assertEqual(len(ogq.read_all()), before, "同一条缺口不应重复写入")

    def test_37_gap_rows_have_the_six_required_fields(self):
        """§22：issue_id / issue_type / term / evidence / detected_by / status=candidate。"""
        rows = ogq.read_all()
        self.assertTrue(rows)
        for row in rows:
            for field in ("issue_id", "issue_type", "term", "evidence",
                          "detected_by", "status"):
                self.assertIn(field, row, "%s 缺字段 %s" % (row.get("issue_id"), field))
            self.assertIn(row["status"], ("candidate", "resolved", "invalidated"))
            self.assertTrue(row["issue_id"].startswith("ogq."))
            self.assertIn(row["issue_type"], ogq.ISSUE_TYPES)
            self.assertTrue(row["detected_by"])
            self.assertIn("detected_at", row)
            self.assertIsInstance(row["evidence"], dict)

    def test_32_gap_stats_shape(self):
        s = ogq.stats()
        for k in ("total", "by_type", "by_status"):
            self.assertIn(k, s)

    def test_34_junk_terms_never_enter_the_queue(self):
        """整句 query / 功能词 / 元词都不是「缺口」—— 队列不能变成噪声桶。

        实测：第一版记录了 `between` / `does` / `mean` / `Seminar` /
        `如何讨论` / `有什么区别` / `研讨班十一期如何讨论凝视？` 这样的行。
        """
        junk = [None, "", "  ", "有什么区别", "如何讨论", "Seminar", "does",
                "mean", "between", "什么是", "Seminar XI 如何讨论 gaze？",
                "研讨班十一期如何讨论凝视？", "在研讨班七期", "证据",
                "拉康在研讨班十一期里究竟是如何把凝视与对象a组织起来的呢"]
        for t in junk:
            ok, why = ogq.is_valid_term(t)
            self.assertFalse(ok, "%r 被误判为有效术语（%s）" % (t, why))
            # append=False：契约测试**不许**往真实队列里写东西
            self.assertIsNone(ogq.propose("missing_entity", t or "x", term=t,
                                          append=False))
        for t in ("gaze", "objet", "réalité", "signifié", "l'Autre", "凝视"):
            ok, why = ogq.is_valid_term(t)
            self.assertTrue(ok, "%r 被误判为无效（%s）" % (t, why))

    def test_35_queue_is_deduped_and_prunable(self):
        before = len(ogq.read_all())
        ogq.prune()
        self.assertEqual(len(ogq.read_all()), before, "已清理过的队列不应再被删")
        for row in ogq.read_all():
            ok, why = ogq.is_valid_term(row.get("term"))
            self.assertTrue(ok, "队列里仍有无效术语 %r（%s）" % (row.get("term"), why))

    def test_36_repaired_gaps_are_marked_not_deleted(self):
        """§9：修复后**不删**历史行，而是追加 `status: resolved` / `invalidated`。

        Phase 4A.1 语义变更（已在 ONTOLOGY_REPAIR_PHASE4A1.md 记录）：
        旧实现把失效条目从文件里删掉 —— 那会让「缺口什么时候被修好」永久消失。
        """
        rows = ogq.read_all()
        self.assertTrue(rows)
        # 没有仍处于 candidate 的、其术语现在已可解析的条目
        import knowledge_api as api
        open_but_resolvable = [
            r for r in rows
            if r.get("status") == "candidate" and r["issue_type"] == "missing_entity"
            and api.resolve_entity(r["term"])["resolution"]["resolution_status"]
            != "UNRESOLVED"]
        self.assertEqual(open_but_resolvable, [],
                         "已可解析却仍是 candidate：%s"
                         % [r["term"] for r in open_but_resolvable])
        # 每一条 resolved 都必须带 resolution_commit / 实体 / 证据或理由
        for r in rows:
            if r.get("status") == "resolved":
                self.assertTrue(r.get("resolution_commit"), r.get("term"))
                self.assertTrue(r.get("resolved_entity_ids") or r.get("resolution_reason"),
                                r.get("term"))
        # 文件里保留历史行（行数 > 唯一 id 数）
        n_lines = sum(1 for l in open(ogq.QUEUE, encoding="utf-8") if l.strip())
        self.assertGreater(n_lines, len(rows), "状态更新应当是**追加**，历史行不得消失")

    def test_33_agent_records_gaps_but_only_as_candidates(self):
        before = len(ogq.read_all())
        ra.research("什么是 objet a？", record_gaps=True)
        after = ogq.read_all()
        self.assertGreaterEqual(len(after), before)
        for row in after:
            self.assertIn(row["status"], ("candidate", "resolved", "invalidated"))
            self.assertFalse(row["canonical_change_proposed"])
        # 新追加的行必须是 candidate（发现记录），除非它是状态更新行
        for row in after:
            if row.get("status_updated_by"):
                self.assertIn(row["status"], ("resolved", "invalidated"))
            else:
                self.assertEqual(row["status"], "candidate")


class TestCitations(unittest.TestCase):
    """§14/§15：引用契约。`citations.py` 直接查词法索引做真值 —— 比调用方
    自报 known_ids 更硬（调用方可能自己就是错的）。"""

    @classmethod
    def setUpClass(cls):
        import sqlite3
        con = sqlite3.connect(os.path.join(VAULT, "_data", "index", "lexical.sqlite"))
        try:
            cls.fr_l1 = con.execute(
                "SELECT id FROM passage_meta WHERE language='fr' AND "
                "authority_level='L1' LIMIT 1").fetchone()[0]
            cls.zh_rec = con.execute(
                "SELECT id FROM passage_meta WHERE language='zh' AND "
                "trace_status='SOURCE_TRACE_INCOMPLETE' LIMIT 1").fetchone()[0]
        finally:
            con.close()
        cls.fake = "passage.S99.unknown.P9999"

    def test_40_extract_citations_finds_real_and_fake(self):
        text = ("拉康在此谈到凝视 [S11 / %s]，另见 %s 与 %s。" %
                (self.fr_l1, self.zh_rec, self.fake))
        cites = cit.extract_citations(text)
        self.assertEqual(len(cites), 3)
        by_id = {c["passage_id"]: c for c in cites}
        self.assertTrue(by_id[self.fr_l1]["valid"])
        self.assertTrue(by_id[self.zh_rec]["valid"])
        self.assertFalse(by_id[self.fake]["valid"])
        self.assertEqual(by_id[self.fr_l1]["seminar"],
                         "seminar." + self.fr_l1.split(".")[1])

    def test_41_fabricated_ids_are_caught(self):
        rep = cit.validate("只有一条编造的引用 %s。" % self.fake)
        self.assertEqual(rep["fabricated"], [self.fake])
        self.assertEqual(rep["valid_n"], 0)
        self.assertEqual(rep["invalid_n"], 1)
        good = cit.validate("真实引用 %s。" % self.fr_l1)
        self.assertEqual(good["fabricated"], [])
        self.assertEqual(good["citation_validity"], 1.0)

    def test_42_support_levels_are_primary_vs_secondary(self):
        p = cit.classify_support(self.fr_l1)
        self.assertTrue(p["exists"])
        self.assertEqual(p["level"], "primary")
        z = cit.classify_support(self.zh_rec)
        self.assertEqual(z["level"], "secondary_recovered_translation")
        self.assertTrue(z["warning"], "SOURCE_TRACE_INCOMPLETE 必须带告警")
        self.assertIn("SOURCE_TRACE_INCOMPLETE", z["warning"])
        self.assertFalse(cit.classify_support(self.fake)["exists"])

    def test_43_unsupported_claim_rate_is_a_lower_bound(self):
        text = ("欲望是他者的欲望 [S11 / %s]。另外，圣状是一个结构性的概念。" % self.fr_l1)
        rep = cit.unsupported_claim_rate(text)
        self.assertGreaterEqual(rep["theoryish_claims"], 1)
        self.assertGreater(rep["unsupported_claim_rate"], 0.0)
        self.assertIn("下界", rep["caveat"])
        self.assertEqual(rep["method"], "sentence_level_heuristic")

    def test_45_support_levels_distinguish_primary_secondary_and_ai(self):
        """§15：primary / secondary / **agent synthesis** 必须显式可分。"""
        import sqlite3
        con = sqlite3.connect(os.path.join(VAULT, "_data", "index", "lexical.sqlite"))
        try:
            fr = con.execute("SELECT id FROM passage_meta WHERE language='fr' AND "
                             "authority_level='L1' LIMIT 1").fetchone()[0]
            zh = con.execute("SELECT id FROM passage_meta WHERE language='zh' LIMIT 1"
                             ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(cit.classify_support(fr)["level"], "primary")
        self.assertTrue(cit.classify_support(fr)["is_source"])
        self.assertIn(cit.classify_support(zh)["level"],
                      ("secondary", "secondary_recovered_translation"))
        # 非源层级：L3/L4 就算语言/角色像源，也不得被当成 source
        self.assertEqual(cit.AUTHORITY_TO_LEVEL["L4"], "agent_synthesis")
        self.assertEqual(cit.AUTHORITY_TO_LEVEL["L3"], "research_note")
        for lv in ("primary", "secondary", "secondary_recovered_translation",
                   "research_note", "agent_synthesis", "unknown"):
            self.assertIn(lv, cit.SUPPORT_LEVELS)

    def test_46_agent_returns_evidence_pack_not_an_answer(self):
        """§11/§12：Agent **不写答案**，也不存在「一次 search 就写长答案」的字段。"""
        r = ra.research("什么是 objet a？", record_gaps=False)
        for forbidden in ("answer", "response_text", "final_answer", "essay"):
            self.assertNotIn(forbidden, r)
        self.assertIn("evidence_pack", r)
        self.assertIn("research_trace", r)
        self.assertIn("不写答案", r["agent_note"])
        # 证据包里给的只有**可引用的 id 白名单**，没有成文结论
        self.assertEqual(r["evidence_pack"]["citable_passages"],
                         [e["passage_id"] for e in r["evidence_pack"]["evidence"]])

    def test_44_citation_report_shape_and_no_primary_claim(self):
        rep = cit.citation_report("欲望是需求与要求的差 [S11 / %s]。" % self.fr_l1)
        for k in ("citation_validity", "valid_n", "invalid_n", "fabricated",
                  "support_levels", "has_primary", "unsupported"):
            self.assertIn(k, rep)
        self.assertTrue(rep["has_primary"])
        # 中文 recovered 证据绝不能被称为 primary source
        rep2 = cit.citation_report("凝视在这里被提到 [S11 / %s]。" % self.zh_rec)
        self.assertTrue(rep2["has_recovered_secondary"])
        self.assertFalse(rep2["has_primary"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
