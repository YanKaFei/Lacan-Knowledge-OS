#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase4a1_ontology.py — Phase 4A.1 Ontology Repair & Terminology Control 的契约测试

覆盖 §1–§10 的每一条完成判据，外加一条贯穿全阶段的纪律：

> **修复不得靠改写历史**：Phase 3 的 bridge / guard / Gold Concept Set / 旧评测结果
> 必须原样保留，修复只发生在版本化叠加层（`ontology.v4a1`）。

所以本套件每个「修好了」的断言，都配一条「旧事实仍可观测」的断言。
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
MCP = os.path.join(TOOLS, "lacan_mcp")
STORE = os.path.join(VAULT, "_data", "passage_store")
LAYER = os.path.join(VAULT, "_data", "ontology", "v4a1")
IDX = os.path.join(VAULT, "_data", "index")
sys.path.insert(0, TOOLS)
sys.path.insert(0, MCP)

import ontology_v4a1 as onto          # noqa: E402
import knowledge_api as api           # noqa: E402
import entity_resolution as er        # noqa: E402
import terminology_bridge as tb       # noqa: E402
import ontology_gaps as ogq           # noqa: E402


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def jd(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return d


class TestLayerIntegrity(unittest.TestCase):
    """叠加层本身的结构与完整性。"""

    def test_01_layer_loads_with_manifest(self):
        meta = onto.layer_meta()
        self.assertEqual(meta["layer_id"], "ontology.v4a1")
        self.assertTrue(meta["resolution_ref"].startswith("ontology.v4a1#"))
        self.assertEqual(meta["entity_count"], len(onto.entities()))

    def test_02_validator_reports_zero_errors(self):
        rec = jd(os.path.join(IDX, "ONTOLOGY_V4A1_VALIDATION.json"))
        self.assertIsNotNone(rec, "先跑 validate_ontology_v4a1.py")
        self.assertEqual(rec["n_errors"], 0, rec["errors"])
        self.assertTrue(rec["all_passed"])
        self.assertGreaterEqual(len(rec["checks"]), 10)

    def test_03_products_match_spec(self):
        """`--check` 能证明产物与 spec 一致（可复算）。"""
        import subprocess
        r = subprocess.run([sys.executable,
                            os.path.join(TOOLS, "build_ontology_v4a1.py"), "--check"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_04_no_gold_concept_touched(self):
        gold = jl(os.path.join(STORE, "concepts.jsonl"))
        self.assertEqual(len(gold), 53, "Gold Concept Set 必须仍是 53 条")
        ids = {c["id"] for c in gold}
        self.assertFalse(ids & set(onto.entity_ids()),
                         "叠加层不得与 Gold 撞 id（只能新增）")
        for c in gold:
            self.assertNotEqual(c.get("_layer"), "ontology.v4a1")


class TestGazeTerminologyControl(unittest.TestCase):
    """§1：gaze / regard / 凝视 的受控映射。"""

    def test_10_controlled_mapping_exists_and_is_not_plain_synonym(self):
        for form in ("gaze", "regard", "凝视"):
            m = onto.terminology_lookup(form)
            self.assertTrue(m["mappings"], form)
            for row in m["mappings"]:
                self.assertEqual(row["relation_type"], "controlled_term_mapping",
                                 "必须是受控映射，不是普通同义（equivalent）")
                self.assertEqual(row["entity_id"], "concept.gaze")
                self.assertIn("context_requirement", row)
                self.assertIn("auto_resolution", row)
                self.assertEqual(row["review_status"], "candidate")
                self.assertTrue(row["evidence"], "映射自身要带证据段号")

    def test_11_entity_aware(self):
        """映射必须落到 entity 上（而不是字符串表）。"""
        rows = jl(os.path.join(LAYER, "term_mappings.jsonl"))
        for r in rows:
            self.assertTrue(r["entity_id"].startswith(("concept.", "term.")))
            self.assertIsNotNone(onto.entity(r["entity_id"]))

    def test_12_ordinary_regard_is_not_auto_resolved(self):
        """核心风险：法文 regard 的日常义不得被当成 Lacanian gaze。"""
        bare = onto.resolve("regard")
        self.assertEqual(bare["status"], "AMBIGUOUS")
        self.assertTrue(bare["context_required"])
        self.assertEqual(bare["entities"], [])
        # 走了 MCP 层也一样
        r = api.resolve_entity("regard")["resolution"]
        self.assertEqual(r["resolution_status"], "AMBIGUOUS")
        self.assertTrue(r["context_required"])
        self.assertEqual([c["entity_id"] for c in r["candidates"]], [])

    def test_13_regard_with_context_resolves(self):
        for ctx in ("Seminar XI 谈凝视", "regard 与 gaze", "看与被看：凝视"):
            r = api.resolve_entity("regard", context=ctx)["resolution"]
            self.assertEqual(r["resolution_status"], "RESOLVED", ctx)
            self.assertEqual([c["entity_id"] for c in r["candidates"]], ["concept.gaze"])

    def test_14_gaze_and_ningmu_resolve_without_context(self):
        for form in ("gaze", "凝视"):
            r = api.resolve_entity(form)["resolution"]
            self.assertEqual([c["entity_id"] for c in r["candidates"]], ["concept.gaze"],
                             form)

    def test_15_evidence_is_real_and_scoped(self):
        ev = jl(os.path.join(LAYER, "evidence.jsonl"))
        gaze_ev = [e for e in ev if e["entity_id"] == "concept.gaze"]
        self.assertTrue(gaze_ev)
        scoped = [e for e in gaze_ev if e["tier"] == "context_scoped"]
        self.assertTrue(scoped, "S11 内的 regard 必须作为**上下文受限**证据单列")
        for e in scoped:
            self.assertEqual(e["assertion_type"], "context_scoped_term_occurrence")
            self.assertTrue(e["caveat"], "上下文受限证据必须带 caveat")
            self.assertEqual(e["scope"]["seminar"], "seminar.S11")
        # 核心证据来自无歧义形式
        core_forms = {f for e in gaze_ev if e["tier"] == "core" for f in e["matched_forms"]}
        self.assertTrue(core_forms & {"gaze", "凝视"})


class TestAutreSplit(unittest.TestCase):
    """§2：Autre / autre 的拆分与迁移。"""

    def test_20_two_entities_exist(self):
        for eid in ("concept.big-other", "concept.little-other"):
            e = onto.entity(eid)
            self.assertIsNotNone(e, eid)
            self.assertEqual(e["entity_role"], "concept")
            self.assertTrue(e["passages"], "%s 必须有真实 supporting passage" % eid)
            self.assertTrue(e["distinction_from"])

    def test_21_case_bearing_forms_resolve_to_the_right_side(self):
        cases = {"l'Autre": "concept.big-other", "Autre": "concept.big-other",
                 "grand Autre": "concept.big-other", "大他者": "concept.big-other",
                 "l'autre": "concept.little-other", "petit autre": "concept.little-other",
                 "小他者": "concept.little-other"}
        for form, want in cases.items():
            r = api.resolve_entity(form)["resolution"]
            got = [c["entity_id"] for c in r["candidates"]]
            self.assertEqual(got, [want], "%s → %s（实际 %s）" % (form, want, got))

    def test_22_bare_autre_stays_ambiguous(self):
        r = api.resolve_entity("autre")["resolution"]
        self.assertEqual(r["resolution_status"], "AMBIGUOUS")
        self.assertTrue(r["context_required"])
        self.assertEqual(r["candidates"], [])
        # 带上下文才解析
        r2 = api.resolve_entity("autre", context="小他者与 autre")["resolution"]
        self.assertEqual([c["entity_id"] for c in r2["candidates"]],
                         ["concept.little-other"])

    def test_23_single_char_A_still_guarded(self):
        r = api.resolve_entity("A")["resolution"]
        self.assertEqual(r["resolution_status"], "UNRESOLVED")
        e = onto.entity("concept.big-other")
        self.assertIn("A", e["single_char_aliases_excluded"])

    def test_24_migration_record_preserves_legacy_entity(self):
        migs = jl(os.path.join(LAYER, "migrations.jsonl"))
        split = [m for m in migs if m["kind"] == "entity_split"]
        self.assertEqual(len(split), 1)
        m = split[0]
        self.assertEqual(m["from_entity"], "concept.l-autre")
        self.assertEqual(set(m["to_entities"]),
                         {"concept.big-other", "concept.little-other"})
        self.assertTrue(m["kept_in_store"])
        self.assertFalse(m["deleted"])
        self.assertEqual(m["resolution_precedence"], "successors_win")
        self.assertTrue(m["evidence"])
        # 旧实体**仍在** Gold Concept Set 里（没有被删）
        gold = {c["id"] for c in jl(os.path.join(STORE, "concepts.jsonl"))}
        self.assertIn("concept.l-autre", gold)

    def test_25_legacy_entity_is_superseded_not_returned(self):
        r = api.resolve_entity("l'Autre")
        ids = [c["entity_id"] for c in r["resolution"]["candidates"]]
        self.assertNotIn("concept.l-autre", ids, "旧实体不应出现在解析结果里")
        self.assertTrue(r["resolution"]["superseded"])
        self.assertIn("SUPERSEDED_ENTITY", [w["code"] for w in r["warnings"]])

    def test_26_phase3_layer_still_resolves_legacy(self):
        """Phase 3 的 resolver 行为**没有**被本层修改（历史可复现）。"""
        r = er.resolve("Comment se définit le grand Autre ?")
        self.assertIn("concept.l-autre", [e["entity_id"] for e in r["entities"]])


class TestNewEntities(unittest.TestCase):
    """§3/§5：缺失实体与 objet 的分级处理。"""

    REQUIRED = {
        # entity_id: (canonical_name, fr, en, zh)
        "concept.realite": ("reality", "réalité", "reality", "现实"),
        "concept.signifie": ("signified", "signifié", "signified", "所指"),
        "concept.demande": ("demand", "demande", "demand", "要求"),
        "concept.besoin": ("need", "besoin", "need", "需要"),
        "concept.moi": ("moi", "le moi", "ego", "自我"),
    }

    def test_30_all_new_entities_are_complete(self):
        for eid, (canon, fr, en, zh) in self.REQUIRED.items():
            e = onto.entity(eid)
            self.assertIsNotNone(e, eid)
            self.assertEqual(e["canonical_name"], canon)
            self.assertEqual(e["fr"], fr)
            self.assertEqual(e["en"], en)
            self.assertEqual(e["zh"], zh)
            self.assertTrue(e["aliases"])
            self.assertTrue(e["passages"], "%s 缺真实 supporting passage" % eid)
            self.assertTrue(e["source_notes"], "%s 缺 provenance" % eid)
            self.assertEqual(e["review_status"], "candidate")
            self.assertIsNone(e["definition"], "不得编造理论定义")
            self.assertIn(e["definition_status"], ("not_written_backlog",
                                                   "not_applicable_term_level"))
            self.assertTrue(e["distinction_from"], "%s 必须有区分关系" % eid)

    def test_31_evidence_ids_all_real(self):
        known = set()
        for line in open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8"):
            if line.strip():
                known.add(json.loads(line)["id"])
        for e in onto.entities():
            for pid in e["passages"]:
                self.assertIn(pid, known, "%s 的 %s 不存在" % (e["id"], pid))
        for r in jl(os.path.join(LAYER, "evidence.jsonl")):
            self.assertIn(r["passage_id"], known)

    def test_32_objet_is_term_level_not_concept(self):
        """§5：objet 只到 term 级，不强行提升为 Concept。"""
        e = onto.entity("term.objet")
        self.assertIsNotNone(e)
        self.assertEqual(e["entity_role"], "term")
        self.assertEqual(e["type"], "term")
        self.assertIsNone(onto.entity("concept.objet"))
        self.assertTrue(e.get("upgrade_path"), "必须写清升级为 Concept 的条件")
        self.assertIn("concept.objet-petit-a", e["distinction_from"])

    def test_33_objet_and_objet_a_are_distinguishable(self):
        a = api.resolve_entity("objet a")["resolution"]
        b = api.resolve_entity("objet")["resolution"]
        self.assertEqual([c["entity_id"] for c in a["candidates"]],
                         ["concept.objet-petit-a"])
        self.assertEqual([c["entity_id"] for c in b["candidates"]], ["term.objet"])
        # objet a 出现时不得再匹配裸 objet
        self.assertIn("alias_exclude_forms", onto.entity("term.objet"))
        self.assertTrue(onto.entity("term.objet")["alias_exclude_forms"])

    def test_34_moi_reviewed_and_added_with_evidence(self):
        """§3 要求「审查 subject/ego，证据充分才新增」——这里断言两条都成立。"""
        e = onto.entity("concept.moi")
        self.assertIsNotNone(e)
        self.assertIn("concept.sujet", e["distinction_from"])
        self.assertGreaterEqual(e["passage_evidence_n"], 10)


class TestDistinctionRelations(unittest.TestCase):
    """§4：typed 区分关系，且不得只写 related_to。"""

    def test_40_no_related_to_and_typed_by_extension(self):
        rels = jl(os.path.join(LAYER, "relations.jsonl"))
        self.assertTrue(rels)
        for r in rels:
            self.assertNotEqual(r["predicate"], "related_to",
                                "%s 用了弱关联兜底" % r["relation_id"])
            self.assertIn(r["predicate"], ("distinct_from", "develops", "appears_in"))

    def test_41_every_relation_has_real_evidence(self):
        known = set()
        for line in open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8"):
            if line.strip():
                known.add(json.loads(line)["id"])
        for r in jl(os.path.join(LAYER, "relations.jsonl")):
            pids = r["evidence"]["passage_id"]
            self.assertTrue(pids, "%s 无证据" % r["relation_id"])
            for pid in pids:
                self.assertIn(pid, known)
            self.assertIn(r["evidence"]["assertion_type"],
                          ("explicit", "inferred", "editorial"))
            self.assertEqual(r["review_status"], "candidate")

    def test_42_required_distinctions_present(self):
        rels = jl(os.path.join(LAYER, "relations.jsonl"))
        pairs = {(r["subject"], r["predicate"], r["object"]) for r in rels}
        for want in (("concept.le-reel", "distinct_from", "concept.realite"),
                     ("concept.signifiant", "distinct_from", "concept.signifie"),
                     ("concept.big-other", "distinct_from", "concept.little-other"),
                     ("concept.objet-petit-a", "distinct_from", "term.objet"),
                     ("concept.besoin", "develops", "concept.demande"),
                     ("concept.demande", "develops", "concept.desir")):
            self.assertIn(want, pairs, "缺关系 %s" % (want,))

    def test_43_vocabulary_extension_is_declared(self):
        v = jd(os.path.join(LAYER, "vocabulary.json"))
        preds = {p["predicate"] for p in
                 v["extension"]["relation_predicates_added"]}
        self.assertIn("distinct_from", preds)
        self.assertTrue(any(t["relation_type"] == "controlled_term_mapping"
                            for t in v["extension"]["term_mapping_types_added"]))
        self.assertEqual(v["base_relation_predicates"], 17)
        for c in v["extension"]["ontology_defect_classes"]:
            self.assertIn(c["class"], ("ENTITY_COLLISION", "ONTOLOGY_MISSING",
                                       "MODEL_COLLAPSE", "RESOLVED"))


class TestGuardReclassification(unittest.TestCase):
    """§8：缺陷分类与重分类。"""

    def test_50_defect_classes_distinguished(self):
        self.assertEqual(onto.defect_class("ENTITY_COLLISION"), "ENTITY_COLLISION")
        self.assertEqual(onto.defect_class("COUNTERPART_ENTITY_MISSING"),
                         "ONTOLOGY_MISSING")
        self.assertEqual(onto.defect_class("BOTH_ENTITIES_MISSING"), "ONTOLOGY_MISSING")
        self.assertIsNone(onto.defect_class(None))

    def test_51_no_live_defects_left(self):
        s = onto.guard_summary()
        self.assertEqual(s["pairs"], len(tb.distinct_pairs()))
        self.assertEqual(s["still_defective"], [], "仍有未重分类的缺陷")
        self.assertEqual(s["pre_classes"].get("ENTITY_COLLISION"), 1)
        self.assertEqual(s["post_classes"].get("ENTITY_COLLISION"), None)

    def test_52_historical_bridge_rows_untouched(self):
        """§6：Phase 3C 的 bridge 结论一行未改（修复只发生在叠加层）。"""
        rows = {r["term_id"]: r for r in tb.distinct_pairs()}
        self.assertEqual(rows["tb.distinct.01"]["entity_binding"], "ENTITY_COLLISION")
        self.assertEqual(rows["tb.distinct.01"]["entity_id"], "concept.l-autre")
        self.assertEqual(rows["tb.distinct.02"]["entity_binding"],
                         "COUNTERPART_ENTITY_MISSING")
        self.assertEqual(len(tb.distinct_pairs()), 7)

    def test_53_repaired_pairs_are_reclassified_in_guard_view(self):
        view = {tuple(r["pair"]): r for r in onto.guard_view()}
        self.assertEqual(view[("Autre", "autre")]["post_repair_class"],
                         "RESOLVED_CONTEXT_REQUIRED")
        self.assertEqual(view[("Réel", "réalité")]["post_repair_class"], "RESOLVED")
        self.assertEqual(view[("objet", "objet a")]["post_repair_class"], "RESOLVED")
        for row in onto.guard_view():
            self.assertTrue(row["repaired"], row["pair"])


class TestGapQueueAudit(unittest.TestCase):
    """§9：缺口状态更新（追加，不删）。"""

    def test_60_statuses_updated_with_audit_fields(self):
        rows = ogq.read_all()
        statuses = {r["status"] for r in rows}
        self.assertIn("resolved", statuses)
        self.assertIn("invalidated", statuses)
        for r in rows:
            if r["status"] == "resolved":
                self.assertTrue(r.get("resolution_commit"))
                self.assertTrue(r.get("resolved_entity_ids"))
            if r["status"] == "invalidated":
                self.assertTrue(r.get("resolution_reason"))
            self.assertFalse(r["canonical_change_proposed"])

    def test_61_history_is_append_only(self):
        n_lines = sum(1 for l in open(ogq.QUEUE, encoding="utf-8") if l.strip())
        n_ids = len(ogq.read_all())
        self.assertGreater(n_lines, n_ids, "状态更新必须是追加，历史行不得消失")
        raw = [json.loads(l) for l in open(ogq.QUEUE, encoding="utf-8") if l.strip()]
        ids = [r["issue_id"] for r in raw]
        self.assertGreater(len(ids), len(set(ids)), "同 id 应有多行（原始 + 更新）")

    def test_62_resolutions_reference_real_entities_and_commit(self):
        rows = ogq.read_all()
        for r in rows:
            if r["status"] == "resolved":
                self.assertTrue(r["resolution_commit"].startswith("ontology.v4a1#"))
                for eid in r["resolved_entity_ids"]:
                    self.assertTrue(onto.entity(eid) or eid.startswith("concept."),
                                    eid)


class TestVersionedEvaluation(unittest.TestCase):
    """§6：旧结果不覆盖；新结果单独版本化。"""

    def test_70_old_results_untouched_and_new_version_exists(self):
        old = jd(os.path.join(VAULT, "_data", "eval", "research_eval_results.json"))
        new = jd(os.path.join(VAULT, "_data", "eval",
                              "research_eval_results.v4a1.json"))
        self.assertIsNotNone(old, "Phase 4A 的旧结果文件必须还在")
        self.assertIsNotNone(new, "v4a1 新结果文件缺失")
        self.assertEqual(new["ontology_layer"], "ontology.v4a1")
        self.assertIn("不覆盖", new["supersedes"])
        self.assertEqual(new["metrics"]["n"], 10)
        self.assertEqual(new["metrics"]["no_fabrication"], 1.0)

    def test_71_v4a1_dataset_records_why_expectations_changed(self):
        rows = jl(os.path.join(VAULT, "_data", "eval", "research_eval_v4a1.jsonl"))
        self.assertEqual(len(rows), 10)
        changed = [r for r in rows if r.get("expectation_change_reason")]
        self.assertTrue(changed, "改过期望就必须写明理由")
        for r in rows:
            self.assertTrue(r.get("supersedes"))
        # 旧数据集**仍然**写着旧期望（历史事实）
        old = {r["id"]: r for r in
               jl(os.path.join(VAULT, "_data", "eval", "research_eval.jsonl"))}
        self.assertEqual(old["E"]["allowed_states"], ["CONFLICTING_EVIDENCE"])


class TestRegressionRecord(unittest.TestCase):
    """§7/§10：回归记录里的每一条都成立。"""

    def test_80_regression_all_passed(self):
        rec = jd(os.path.join(IDX, "ONTOLOGY_V4A1_REGRESSION.json"))
        self.assertIsNotNone(rec, "先跑 regress_ontology_v4a1.py")
        self.assertTrue(rec["all_passed"],
                        [c for c in rec["checks"] if not c["passed"]])
        self.assertGreaterEqual(rec["passed"], 15)
        self.assertEqual(rec["integrity"]["changed"], [])
        self.assertEqual(rec["integrity"]["fabricated_passage_ids"], [])
        self.assertEqual(rec["integrity"]["passages"], 249105)

    def test_81_mcp_regression_covers_required_tools(self):
        rec = jd(os.path.join(IDX, "ONTOLOGY_V4A1_REGRESSION.json"))
        tools = {m["tool"] for m in rec["mcp"]}
        for t in ("resolve_entity", "terminology_lookup", "get_concept",
                  "find_concept_evidence", "compare_concepts", "trace_concept"):
            self.assertIn(t, tools, t)
        for m in rec["mcp"]:
            self.assertTrue(m["sections_ok"], m)
            self.assertNotIn("error", m)

    def test_82_readonly_gate_still_green(self):
        rec = jd(os.path.join(IDX, "READONLY_GATE.json"))
        self.assertIsNotNone(rec)
        self.assertTrue(rec["all_passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
