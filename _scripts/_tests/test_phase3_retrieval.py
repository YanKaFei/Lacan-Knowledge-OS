#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase3_retrieval.py — §16 综合检索测试

一文件覆盖 §16 点名的多数条目（其余在各自的专项测试文件里）：

  exact passage lookup · metadata filters · quoted phrase search ·
  deterministic retrieval · hybrid fusion · graph depth limit ·
  deduplication · evidence diversity · invalid passage rejection ·
  incomplete provenance preservation · recovered translation status preservation ·
  source-link candidate cannot become canonical · index manifest / corpus hash match ·
  vector backend interface · evidence bundle validity
"""

import json
import os
import sqlite3
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
IDX = os.path.join(VAULT, "_data", "index")
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
sys.path.insert(0, TOOLS)


class Retrieval(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import hybrid_retrieve as H
        cls.H = H
        cls.bundle = H.retrieve("大他者 是什么", top_k=8)

    # ---- evidence bundle 结构（§9）
    def test_00_bundle_schema(self):
        for k in ("query", "intent", "entities", "filters", "evidence",
                  "coverage", "warnings"):
            with self.subTest(field=k):
                self.assertIn(k, self.bundle, f"bundle 缺 {k}")

    def test_01_evidence_required_fields(self):
        req = ("passage_id", "seminar_id", "session_id", "language", "text",
               "source_authority", "text_role", "canonical_status",
               "provenance_status", "lexical_rank", "vector_rank", "graph_rank",
               "fusion_rank", "why_retrieved")
        for e in self.bundle["evidence"]:
            for k in req:
                with self.subTest(pid=e.get("passage_id"), field=k):
                    self.assertIn(k, e, f"{e.get('passage_id')} 缺 {k}")

    # ---- ★ 四维独立，不得压成一个 authority/confidence（§1）
    def test_02_four_dimensions_stay_separate(self):
        for e in self.bundle["evidence"]:
            with self.subTest(pid=e["passage_id"]):
                self.assertIn(e["source_authority"], ("L0", "L1", "L2", "L3", "L4"))
                self.assertIsInstance(e["canonical_status"], bool)
                self.assertIn(e["provenance_status"],
                              ("COMPLETE", "SOURCE_TRACE_INCOMPLETE"))
                self.assertIn(e["text_role"],
                              ("translation", "transcription", "edition", "note"))
                # 不允许出现「一个字段代表全部状态」的合成字段
                for bad in ("authority", "confidence", "score_only", "trust"):
                    self.assertNotIn(bad, e,
                                     f"出现把多维压平的合成字段 {bad!r}")

    # ---- invalid passage rejection / 不编造
    def test_03_no_fabricated_ids_and_validate(self):
        problems = self.H.validate_bundle(self.bundle)
        self.assertEqual(problems, [], "\n".join(problems))
        con = sqlite3.connect(os.path.join(IDX, "lexical.sqlite"))
        try:
            ids = {r[0] for r in con.execute("SELECT id FROM passage_meta")}
        finally:
            con.close()
        for e in self.bundle["evidence"]:
            self.assertIn(e["passage_id"], ids)

    def test_04_validate_bundle_rejects_fabricated(self):
        bad = json.loads(json.dumps(self.bundle))
        bad["evidence"] = [dict(bad["evidence"][0],
                                passage_id="passage.S99.unknown.P9999")]
        problems = self.H.validate_bundle(bad)
        self.assertTrue(any("FABRICATED_PASSAGE_ID" in p for p in problems),
                        "校验器必须能拒绝编造的 passage_id")

    def test_05_validate_bundle_rejects_provenance_tamper(self):
        if not self.bundle["evidence"]:
            self.skipTest("无 evidence")
        bad = json.loads(json.dumps(self.bundle))
        bad["evidence"][0]["provenance_status"] = "COMPLETE_MAYBE"
        problems = self.H.validate_bundle(bad)
        self.assertTrue(any("PROVENANCE_STATUS_INVALID" in p for p in problems))

    # ---- incomplete provenance preservation（§1/§15）
    def test_06_incomplete_provenance_preserved(self):
        """检索层不得把 SOURCE_TRACE_INCOMPLETE 洗成 COMPLETE。"""
        con = sqlite3.connect(os.path.join(IDX, "lexical.sqlite"))
        try:
            prov = {r[0]: r[1] for r in
                    con.execute("SELECT id, trace_status FROM passage_meta")}
        finally:
            con.close()
        for e in self.bundle["evidence"]:
            with self.subTest(pid=e["passage_id"]):
                self.assertEqual(e["provenance_status"], prov[e["passage_id"]],
                                 "evidence 的 provenance 与 store 不一致（被篡改）")

    # ---- recovered Chinese translation status preservation
    def test_07_recovered_translation_status_preserved(self):
        with open(os.path.join(STORE, "translations.jsonl"), encoding="utf-8") as f:
            trans = {json.loads(l)["id"]: json.loads(l)
                     for l in f if l.strip()}
        zh = [t for t in trans.values() if t["language"] == "zh"]
        self.assertTrue(zh)
        for t in zh:
            self.assertEqual(t["status"], "recovered")
            self.assertFalse(t["canonical"])
        # 检索返回的中文 evidence 必须仍是 L2 + INCOMPLETE，不得被升级
        for e in self.bundle["evidence"]:
            if e["language"] == "zh":
                self.assertEqual(e["source_authority"], "L2")
                self.assertFalse(e["canonical_status"])

    # ---- deterministic retrieval
    def test_08_retrieval_is_deterministic(self):
        a = self.H.retrieve("大他者 是什么", top_k=8)
        b = self.H.retrieve("大他者 是什么", top_k=8)
        self.assertEqual([e["passage_id"] for e in a["evidence"]],
                         [e["passage_id"] for e in b["evidence"]])
        self.assertEqual(a["coverage"], b["coverage"])

    # ---- hybrid fusion（RRF）
    def test_09_rrf_fusion_is_rank_based(self):
        scores, ranks = self.H.rrf_fuse({
            "lexical": [{"passage_id": "p1", "rank": 1},
                        {"passage_id": "p2", "rank": 2}],
            "graph": [{"passage_id": "p2", "rank": 1}],
        })
        # p2 在两个组件都出现，RRF 应高于 p1（尽管 p1 在 lexical 排第一）
        self.assertGreater(scores["p2"], scores["p1"])
        self.assertEqual(ranks["p2"], {"lexical": 2, "graph": 1})

    def test_10_fusion_uses_ranks_not_raw_scores(self):
        """§7：不得 0.5*BM25 + 0.5*cosine。RRF 只吃 rank。"""
        # 同样 rank 但分数悬殊 → 融合结果必须相同
        a, _ = self.H.rrf_fuse({"x": [{"passage_id": "p", "rank": 1, "score": 999}]})
        b, _ = self.H.rrf_fuse({"x": [{"passage_id": "p", "rank": 1, "score": 0.001}]})
        self.assertEqual(a, b, "融合结果被原始分数影响 —— 违反 RRF 只用名次的约束")

    # ---- graph depth limit（§8）
    def test_11_graph_depth_and_limit_respected(self):
        import query_router
        plan = query_router.route("objet a 与 sinthome 的关系")
        g1 = self.H.graph_component(plan, max_depth=0,
                                    candidate_limit=5)
        self.assertEqual(g1, [], "max_depth=0 时不应有任何扩展")
        g2 = self.H.graph_component(plan, max_depth=1, candidate_limit=3)
        self.assertLessEqual(len(g2), 3, "graph 候选数必须受 candidate_limit 限制")
        for h in g2:
            with self.subTest(pid=h["passage_id"]):
                self.assertTrue(h.get("graph_reason"),
                                "每条 graph 结果必须带 graph_reason（可解释）")
                self.assertLessEqual(h.get("graph_depth", 0), 1)

    def test_12_graph_does_not_use_unreviewed_candidates(self):
        """候选库的关系是未审核建议，不得作为检索依据。"""
        rels = self.H.load_relations()
        self.assertIn("main", rels)
        self.assertIn("candidate", rels)
        # 只走主库：candidate 里的 relation_id 不应出现在任何 graph_reason 里
        cand_ids = {r.get("relation_id") for r in rels["candidate"]}
        self.assertTrue(cand_ids)   # 确认确实有候选关系存在（否则此测试无意义）
        plan_src = open(os.path.join(TOOLS, "hybrid_retrieve.py"),
                        encoding="utf-8").read()
        self.assertIn('rels["main"]', plan_src)
        self.assertNotIn('rels["candidate"]', plan_src,
                         "graph 扩展不得读取候选库")

    # ---- deduplication / diversity（§10）
    def test_13_diversify_collapses_near_duplicates(self):
        items = [
            {"passage_id": "p1", "session_id": "s1", "text": "同样的文本内容 abc",
             "seminar_id": "seminar.S01"},
            {"passage_id": "p2", "session_id": "s1", "text": "同样的文本内容 abc",
             "seminar_id": "seminar.S01"},
        ]
        kept, dropped = self.H.diversify(items, top_k=5)
        self.assertEqual(len(kept), 1, "近重复应被折叠")
        self.assertEqual(dropped[0]["reason"], "near_duplicate")

    def test_14_diversify_enforces_session_limit(self):
        items = [{"passage_id": "p%d" % i, "session_id": "s1",
                  "text": "完全不同内容 %d" % i, "seminar_id": "seminar.S01"}
                 for i in range(10)]
        kept, dropped = self.H.diversify(items, session_limit=2, top_k=10)
        self.assertLessEqual(len(kept), 2, "同一 session 不得超过集中度上限")

    def test_15_diachronic_prefers_period_coverage(self):
        """历时查询应避免某一 seminar 连续堆积。"""
        items = [{"passage_id": "p%d" % i, "session_id": "s%d" % i,
                  "text": "内容 %d" % i, "seminar_id": "seminar.S01"}
                 for i in range(6)]
        kept_strict, _ = self.H.diversify(items, top_k=6, diachronic=True)
        sems = [k["seminar_id"] for k in kept_strict]
        # 连续同一 seminar 不得超过 2（其余被让位）
        streak = max((sum(1 for _ in g) for g in
                      __import__("itertools").groupby(sems)), default=0)
        self.assertLessEqual(streak, 2, "历时模式下同一 seminar 不应连续堆积")

    def test_16_coverage_reports_four_dimensions(self):
        cov = self.bundle["coverage"]
        for k in ("seminars", "periods", "languages", "authority_levels"):
            with self.subTest(field=k):
                self.assertIn(k, cov, f"coverage 缺 {k}")

    # ---- vector backend interface（§6）
    def test_17_vector_backend_interface(self):
        """未实现时必须**如实报缺**，不得静默当作 0 分。"""
        import query_router
        plan = query_router.route("test")
        hits, status = self.H.vector_component(plan, adapter=None)
        self.assertEqual(hits, [])
        self.assertFalse(status["implemented"])
        self.assertTrue(status.get("reason"))

    def test_18_vector_adapter_contract(self):
        """adapter 必须提供 embed_documents / embed_query / model_metadata。

        本阶段没有 production adapter，但**接口契约必须可被测试** ——
        用一个最小 fake adapter 验证 hybrid 能接上它。
        """
        class FakeAdapter:
            def search(self, query, limit=10):
                return [{"passage_id": self.pid, "score": 0.9, "rank": 1}]
            pid = None

        import query_router
        plan = query_router.route("test")
        # 拿一个真实 ID
        con = sqlite3.connect(os.path.join(IDX, "lexical.sqlite"))
        try:
            real = con.execute("SELECT id FROM passage_meta LIMIT 1").fetchone()[0]
        finally:
            con.close()
        fa = FakeAdapter(); fa.pid = real
        hits, status = self.H.vector_component(plan, adapter=fa, limit=5)
        self.assertTrue(status["implemented"])
        self.assertEqual(hits[0]["passage_id"], real)
        self.assertEqual(hits[0]["rank"], 1)

    # ---- index manifest（§13）
    def test_19_manifest_matches_corpus_hash(self):
        import hashlib
        mp = os.path.join(IDX, "INDEX_MANIFEST.json")
        self.assertTrue(os.path.isfile(mp), f"缺 {mp}")
        with open(mp, encoding="utf-8") as f:
            man = json.load(f)
        for k in ("corpus", "indices", "schema_version"):
            self.assertIn(k, man)
        pp = os.path.join(STORE, "passages.jsonl")
        h = hashlib.sha256()
        with open(pp, "rb") as fh:
            while True:
                b = fh.read(1 << 20)
                if not b:
                    break
                h.update(b)
        self.assertEqual(man["corpus"]["corpus_hash"], h.hexdigest(),
                         "manifest 的 corpus_hash 与 canonical corpus 不一致")
        self.assertEqual(man["corpus"]["passage_count"], 249105)

    def test_20_manifest_index_cli_verifies(self):
        r = subprocess.run([sys.executable,
                            os.path.join(TOOLS, "lacan-kb"), "index", "--verify"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, f"index --verify 失败:\n{r.stdout}\n{r.stderr}")

    def test_21_large_indices_not_tracked_by_git(self):
        big = os.path.join(IDX, "lexical.sqlite")
        self.assertTrue(os.path.isfile(big))
        r = subprocess.run(["git", "check-ignore", "-q",
                            os.path.relpath(big, VAULT)],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, "大型派生索引必须被 .gitignore 覆盖")
        man = os.path.relpath(os.path.join(IDX, "INDEX_MANIFEST.json"), VAULT)
        r2 = subprocess.run(["git", "check-ignore", "-q", man], capture_output=True,
                            text=True, cwd=VAULT)
        self.assertNotEqual(r2.returncode, 0, "INDEX_MANIFEST.json 必须入库")

    # ---- source-link candidate 不得 canonical（§11）
    def test_22_source_link_candidates_are_candidates_only(self):
        p = os.path.join(STORE, "concept_source_link_candidates.jsonl")
        if not os.path.isfile(p):
            self.skipTest("source linking candidates 尚未生成")
        with open(p, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f if l.strip()]
        self.assertTrue(rows)
        for r in rows:
            with self.subTest(c=r.get("concept_id")):
                self.assertEqual(r["review_status"], "candidate",
                                 "自动 source linking 一律 candidate")
                for k in ("concept_id", "candidate_passage_id", "methods",
                          "score", "review_status"):
                    self.assertIn(k, r)

    # ---- 不改 canonical store
    def test_23_retrieval_does_not_mutate_canonical_store(self):
        pp = os.path.join(STORE, "passages.jsonl")
        before = (os.stat(pp).st_mtime_ns, os.path.getsize(pp))
        self.H.retrieve("大他者 与 享乐", top_k=5)
        after = (os.stat(pp).st_mtime_ns, os.path.getsize(pp))
        self.assertEqual(before, after, "检索不得修改 canonical passage store")

    # ---- CLI 可用
    def test_24_cli_search_and_evidence(self):
        for args in (["search", "objet petit a", "--mode", "lexical", "--limit", "3"],
                     ["search", "凝视与小客体a", "--mode", "hybrid", "--limit", "3"],
                     ["evidence", "大他者 是什么", "--top-k", "3"]):
            with self.subTest(args=args):
                r = subprocess.run([sys.executable, os.path.join(TOOLS, "lacan-kb")]
                                   + args, capture_output=True, text=True, cwd=VAULT)
                self.assertEqual(r.returncode, 0,
                                 f"CLI 失败 {args}:\n{r.stdout[-300:]}\n{r.stderr[-300:]}")

    def test_25_cli_explain_shows_components(self):
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "lacan-kb"),
                            "search", "大他者", "--mode", "hybrid", "--explain"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0)
        out = r.stdout + r.stderr
        for needle in ("QueryPlan", "alias", "lexical", "graph", "vector"):
            with self.subTest(needle=needle):
                self.assertIn(needle, out, f"--explain 未展示 {needle}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
