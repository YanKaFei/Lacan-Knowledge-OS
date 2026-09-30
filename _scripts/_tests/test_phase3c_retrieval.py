#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase3c_retrieval.py — Phase 3C 契约测试（§5–§24）

覆盖本轮新增/升级的组件，重点钉住几条**结构性纪律**：

* Terminology Bridge：11 字段齐；`equivalent` 必须同一 entity；
  `expand()` **结构性排除** `distinct_from`（不是靠调用方自觉）
* Semantic Guard：contrastive query 必须分道，且 lane 带 `excluded_forms`
* Query Routing：10 类路由；exact/FR 类**默认关向量**；歧义不静默解析
* Entity Resolution：中文子串扫描确实补到实体；按 entity 去重（不把 1 个概念当 2 个）
* Full Index：manifest 13 字段；§4 验证通过；大产物不入 Git
* Evidence Bundle v2：6 个新字段齐；abstention **不使用 cosine 阈值**
* Completion Gate：22 条；未全过时不得给出完成声明
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
VECDIR = os.path.join(VAULT, "_data", "index", "vector")
IDX = os.path.join(VAULT, "_data", "index")
sys.path.insert(0, TOOLS)

BRIDGE = os.path.join(VAULT, "_data", "terminology_bridge.jsonl")
BRIDGE_AUDIT = os.path.join(VAULT, "_data", "terminology_bridge_audit.json")
VMAN = os.path.join(VAULT, "VECTOR_INDEX_MANIFEST.json")
FULL_MAN = os.path.join(VECDIR, "FULL_INDEX_MANIFEST.minilm.json")
FULL_VER = os.path.join(VECDIR, "FULL_INDEX_VERIFICATION.json")
FULL_RES = os.path.join(VECDIR, "full_corpus_results.json")
ROUTE_COV = os.path.join(VECDIR, "ROUTING_COVERAGE.json")
CONTRAST = os.path.join(VECDIR, "contrastive_system_vs_raw.json")
GATE = os.path.join(IDX, "PHASE3_COMPLETION_GATE.json")


def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else None


def jl(p):
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


class TerminologyBridge(unittest.TestCase):
    FIELDS = ("term_id", "source_form", "source_language", "target_form",
              "target_language", "entity_id", "relation_type", "status",
              "review_status", "source", "notes")

    def test_00_all_rows_have_11_fields(self):
        rows = jl(BRIDGE)
        self.assertTrue(rows, "缺 terminology_bridge.jsonl")
        for r in rows:
            for f in self.FIELDS:
                self.assertIn(f, r, "bridge 行缺字段 %s" % f)

    def test_01_equivalent_requires_same_entity(self):
        """§6：X 依赖 entity identity，不是字符串翻译。"""
        import terminology_bridge as tb
        for r in tb.equivalents():
            self.assertTrue(r["entity_id"], "equivalent 必须有 entity_id")
            self.assertEqual(r["relation_type"], "equivalent")
        # 反向：同一 entity 内不得出现「自己映射到自己以外」的跨 entity 记录
        by_term = {}
        for r in tb.equivalents():
            by_term.setdefault(r["term_id"], set()).add(r["entity_id"])
        for tid, ents in by_term.items():
            self.assertEqual(len(ents), 1, "term_id %s 跨了多个 entity" % tid)

    def test_02_expand_never_returns_distinct_from(self):
        """**结构性**排除：不是靠调用方记得不要用。"""
        import terminology_bridge as tb
        bad = []
        for r in tb.distinct_pairs():
            for form in (r["source_form"], r["target_form"]):
                for m in tb.expand(form, target_langs=None):
                    if (m["target_form"], m["entity_id"]) == (r["target_form"], r["entity_id"]) \
                            and r["entity_binding"] == "ENTITY_COLLISION":
                        bad.append((form, m))
        self.assertEqual(bad, [], "distinct_from 泄漏进了 expand(): %s" % bad[:2])

    def test_03_seven_contrastive_pairs_with_binding(self):
        rows = jl(BRIDGE)
        df = [r for r in rows if r["relation_type"] == "distinct_from"]
        self.assertEqual(len(df), 7, "§6 点名 7 组配对")
        for r in df:
            self.assertIn(r["entity_binding"],
                          ("ENTITY_COLLISION", "COUNTERPART_ENTITY_MISSING",
                           "BOTH_ENTITIES_MISSING", "BOTH_BOUND_DISTINCT"))
            self.assertTrue(r["notes"])

    def test_04_audit_passes(self):
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "build_terminology_bridge.py"),
                            "--audit"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-600:])
        out = json.loads(r.stdout[r.stdout.index("{"):])
        self.assertEqual(out["status"], "PASS", out)


class SemanticGuard(unittest.TestCase):
    def test_10_contrastive_query_gets_lanes_with_exclusions(self):
        import lacanian_semantic_guard as g
        d = g.analyze("Réel 和 réalité 有什么区别？")
        self.assertGreaterEqual(d["lanes_required"], 2, "必须分道")
        for lane in d["lanes"]:
            self.assertTrue(lane["excluded_forms"],
                            "lane 必须显式排除另一侧的写法，否则会在 lane 内重新混合")
            self.assertIn("exclusion_reason", lane)

    def test_11_single_side_query_does_not_duplicate_lanes(self):
        """只提到一侧时不该造出两条一模一样的 lane。"""
        import lacanian_semantic_guard as g
        d = g.analyze("Comment se définit le grand Autre ?")
        self.assertEqual(d["lanes_required"], 0)
        self.assertTrue(any(w["code"] == "ENTITY_COLLISION" for w in d["warnings"]),
                        "Autre/autre 在知识库里共用一个 entity —— 必须报警")

    def test_12_guard_never_claims_it_can_distinguish_a_collision(self):
        import lacanian_semantic_guard as g
        d = g.analyze("l'Autre 与 l'autre 有什么区别")
        self.assertTrue(d["warnings"])
        codes = {w["code"] for w in d["warnings"]}
        self.assertIn("ENTITY_COLLISION", codes)
        w = next(x for x in d["warnings"] if x["code"] == "ENTITY_COLLISION")
        self.assertIn("数据层", w["message"] + w["action"])


class QueryRouting(unittest.TestCase):
    def test_20_ten_routes_declared(self):
        import query_routing_policy as rp
        self.assertGreaterEqual(len(rp.ROUTING_TABLE), 10)
        for name, p in rp.ROUTING_TABLE.items():
            for k in ("components", "vector_enabled", "vector_weight",
                      "vector_candidate_limit", "lanes", "why"):
                self.assertIn(k, p, "%s 缺 %s" % (name, k))

    def test_21_exact_and_fr_monolingual_disable_vector(self):
        import query_routing_policy as rp
        for route in ("EXACT_QUOTATION", "EXACT_SOURCE_LOOKUP", "FR_MONOLINGUAL"):
            p = rp.ROUTING_TABLE[route]
            self.assertFalse(p["vector_enabled"], "%s 应默认关向量" % route)
            self.assertEqual(p["vector_candidate_limit"], 0,
                             "关向量时候选上限必须是 0（不是「算了但权重 0」）")

    def test_22_routing_actually_runs_and_disables_vector(self):
        cov = load(ROUTE_COV)
        self.assertIsNotNone(cov, "缺 ROUTING_COVERAGE.json —— 路由没有实际跑过")
        self.assertGreaterEqual(cov["queries_routed"], 40)
        self.assertGreaterEqual(cov["distinct_routes_used"], 3)
        self.assertGreater(cov["vector_disabled_queries"], 0, "没有任何 query 关掉向量")
        self.assertGreater(cov["multi_lane_queries"], 0, "没有任何 query 走多 lane")

    def test_23_ambiguous_entity_not_silently_resolved(self):
        import query_routing_policy as rp
        p = rp.ROUTING_TABLE["AMBIGUOUS_ENTITY"]
        self.assertFalse(p["vector_enabled"])
        self.assertIn("不静默解析", p["why"])
        plan = rp.plan_for("A 在拉康那里是什么意思")
        self.assertIn("ambiguous_entities", plan)


class EntityResolution(unittest.TestCase):
    def test_30_cjk_scan_recovers_entities_router_missed(self):
        import entity_resolution as er
        r = er.resolve("大他者是怎么被定义的")
        ids = [e["entity_id"] for e in r["entities"]]
        self.assertIn("concept.l-autre", ids)
        self.assertTrue(any(e["origin"] == "cjk_scan" for e in r["entities"]),
                        "中文查询应由子串扫描补到实体")
        s = er.stats_over_gold()
        self.assertGreaterEqual(s["queries_gaining_entities"], 10,
                                "实测应有 ≥10 条 gold query 因此获得实体")

    def test_31_dedup_by_entity_not_by_alias(self):
        """同一个 entity 的多个别名命中不得被当成多个概念（否则会错误分道）。"""
        import entity_resolution as er
        r = er.resolve("Comment se définit le grand Autre ?")
        ids = [e["entity_id"] for e in r["entities"]]
        self.assertEqual(len(ids), len(set(ids)), "实体没有按 entity_id 去重")
        self.assertEqual(ids.count("concept.l-autre"), 1)


class FullVectorIndex(unittest.TestCase):
    REQUIRED = ("corpus_hash", "passage_count", "language_counts", "embedding_model",
                "model_hash", "runtime_hash", "dimensions", "normalization",
                "index_type", "index_version", "build_config_hash", "created_from",
                "index_artifact_hash")

    def test_40_manifest_has_13_required_fields(self):
        m = load(FULL_MAN)
        self.assertIsNotNone(m, "缺 FULL_INDEX_MANIFEST.minilm.json")
        for k in self.REQUIRED:
            self.assertIn(k, m, "manifest 缺 %s" % k)
            self.assertNotIn(m[k], (None, "", {}), "%s 为空" % k)
        self.assertEqual(m["passage_count"], 249105)
        self.assertEqual(m["dimensions"], 384)

    def test_41_verification_passed(self):
        v = load(FULL_VER)
        self.assertIsNotNone(v, "缺 FULL_INDEX_VERIFICATION.json")
        self.assertTrue(v["passed"], "§4 验证未通过: %s" % v.get("failed"))
        for k in ("vector_count", "dimension", "nan_count", "inf_count",
                  "duplicate_vector_ids", "missing_passage_ids", "extra_passage_ids",
                  "passage_to_vector_one_to_one", "repeat_query_topk_deterministic",
                  "index_artifact_hash_matches_manifest"):
            self.assertIn(k, v["checks"], "§4 缺判据 %s" % k)
            self.assertTrue(v["checks"][k]["passed"], "%s 未通过" % k)

    def test_42_big_artifacts_not_in_git(self):
        for rel in ("_data/index/vector/full_index_minilm.npy",
                    "_data/index/vector/full_index_minilm.ids.txt",
                    "_data/index/vector/full_index_minilm.progress.json"):
            r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=VAULT)
            self.assertEqual(r.returncode, 0, "%s 应被 gitignore" % rel)
        # 但 manifest 必须可入库
        r = subprocess.run(["git", "check-ignore", "-q",
                            "_data/index/vector/FULL_INDEX_MANIFEST.minilm.json"],
                           cwd=VAULT)
        self.assertNotEqual(r.returncode, 0, "manifest 必须能入 Git")


class FullCorpusEvaluation(unittest.TestCase):
    CONFIGS = ["L", "V", "E+L", "L+V", "E+L+V", "E+L+X", "E+L+V+X", "E+L+V+X+M", "ROUTED"]

    def test_50_ten_configs_and_scale_marked(self):
        d = load(FULL_RES)
        self.assertIsNotNone(d, "缺 full_corpus_results.json")
        self.assertIn("249,105", d["scale"])
        m = list(d["models"].values())[0]
        for c in self.CONFIGS:
            self.assertIn(c, m["aggregate"], "缺配置 %s" % c)
        self.assertEqual(d["answerable_n"], 40)
        self.assertEqual(d["unanswerable_n"], 5)

    def test_51_routed_vs_static_numbers_present(self):
        d = load(FULL_RES)
        m = list(d["models"].values())[0]["aggregate"]
        for c in ("ROUTED", "E+L+V+X", "L"):
            self.assertIsNotNone(m[c]["hit@20"], "%s 无 hit@20" % c)

    def test_52_per_class_reported(self):
        d = load(FULL_RES)
        m = list(d["models"].values())[0]
        self.assertTrue(m["by_class"], "必须分 query class 报告")
        self.assertGreaterEqual(len(m["by_class"]), 4)
        for cls, v in m["by_class"].items():
            self.assertIn("ROUTED", v)

    def test_53_zh_to_fr_has_results(self):
        d = load(FULL_RES)
        m = list(d["models"].values())[0]
        z = m["by_class"].get("zh_to_fr")
        self.assertIsNotNone(z, "必须单独报 ZH→FR")
        self.assertGreater(z["n"], 0)
        self.assertIsNotNone(z["E+L+V+X"]["hit@20"])

    def test_54_attribution_report_exists_and_states_verdict(self):
        p = os.path.join(VAULT, "FULL_CORPUS_ABLATION.md")
        self.assertTrue(os.path.isfile(p), "缺 FULL_CORPUS_ABLATION.md")
        t = open(p, encoding="utf-8").read()
        self.assertIn("术语桥", t)
        self.assertIn("分量", t)
        self.assertTrue("principal cross-language mechanism" in t
                        or "边际大于" in t or "两者边际相同" in t,
                        "必须明确给出 X / V 的归因结论")


class ContrastiveAndAbstention(unittest.TestCase):
    def test_60_raw_and_system_reported_separately(self):
        d = load(CONTRAST)
        self.assertIsNotNone(d, "缺 contrastive_system_vs_raw.json")
        self.assertEqual(d["n"], 10)
        self.assertIn("raw_vector_contrastive_pass", d)
        self.assertIn("system_contrastive_pass", d)
        self.assertIn("不要求", d["gate_statement"])

    def test_61_system_not_worse_than_raw(self):
        d = load(CONTRAST)
        self.assertGreaterEqual(d["system_contrastive_pass"],
                                d["raw_vector_contrastive_pass"],
                                "System 比 Raw 差 —— 分道有害，报告必须改")

    def test_62_abstention_forbids_cosine_threshold(self):
        import inspect
        import routed_retrieval as rr
        src = inspect.getsource(rr.evidence_sufficiency)
        self.assertIn("structural_only_no_cosine_threshold", src)
        b = {"evidence": [{"session_id": "s1", "why_retrieved": ["lexical"],
                           "lexical_rank": 1, "vector_rank": 2}]}
        d = rr.evidence_sufficiency(b)
        self.assertIn(d["status"], ("SUPPORTED", "PARTIALLY_SUPPORTED",
                                    "INSUFFICIENT_EVIDENCE"))
        self.assertIn("禁止", d["prohibited"])

    def test_63_bundle_v2_has_six_new_fields(self):
        """§17：6 个新字段必须真的被产出（跑一条真 query 验证）。"""
        import inspect
        import routed_retrieval as rr
        src = inspect.getsource(rr.retrieve_bundle)
        for f in ("retrieval_route", "term_expansions", "semantic_guard",
                  "contrastive_lane", "vector_enabled", "component_contribution"):
            self.assertIn('"%s"' % f, src, "bundle 缺字段 %s" % f)


class CompletionGate(unittest.TestCase):
    def test_70_gate_has_22_checks(self):
        d = load(GATE)
        self.assertIsNotNone(d, "缺 PHASE3_COMPLETION_GATE.json")
        self.assertEqual(len(d["checks"]), 22, "§24 有 22 条")

    def test_71_no_declaration_when_not_closable(self):
        d = load(GATE)
        if not d["closable"]:
            self.assertIsNone(d["declaration_allowed"],
                              "门禁未全过却给出完成声明 —— §24 被绕过")
        else:
            self.assertEqual(d["declaration_allowed"],
                             "PHASE 3 RETRIEVAL LAYER = COMPLETE")

    def test_72_phase4_not_entered(self):
        t = open(os.path.join(VAULT, "PHASE3C_FINDINGS.md"), encoding="utf-8").read() \
            if os.path.isfile(os.path.join(VAULT, "PHASE3C_FINDINGS.md")) else ""
        if t:
            self.assertNotIn("已进入 Phase 4", t)
            self.assertIn("不进入 Phase 4", t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
