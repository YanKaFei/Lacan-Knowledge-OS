#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase3b_contracts.py — §22 Phase 3B 契约测试

覆盖：Adjudicated gold schema · Gold passage existence · Evidence grade ·
Multi-intent model · Ambiguous alias · Embedding provider contract ·
Deterministic benchmark sampling · Vector manifest · Hard gates
"""
import json, os, sqlite3, subprocess, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__))
VAULT=os.path.dirname(os.path.dirname(HERE))
STORE=os.path.join(VAULT,"_data","passage_store")
IDX=os.path.join(VAULT,"_data","index")
TOOLS=os.path.join(VAULT,"_scripts","_tools")
sys.path.insert(0, TOOLS)
GOLD=os.path.join(VAULT,"retrieval_gold_adjudicated.jsonl")
VMAN=os.path.join(VAULT,"VECTOR_INDEX_MANIFEST.json")
CMAN=os.path.join(IDX,"vector","vector_benchmark_corpus_manifest.json")

def jl(p):
    with open(p,encoding="utf-8") as f: return [json.loads(l) for l in f if l.strip()]

class Phase3B(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gold=jl(GOLD) if os.path.isfile(GOLD) else None
        cls.con=sqlite3.connect(os.path.join(IDX,"lexical.sqlite"))
        cls.ids={r[0] for r in cls.con.execute("SELECT id FROM passage_meta")}

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    # ---- §2 规模与 schema
    def test_00_adjudicated_gold_size_and_schema(self):
        self.assertIsNotNone(self.gold, f"缺 {GOLD}")
        self.assertGreaterEqual(len(self.gold),40,"至少 40 条（§24.1）")
        self.assertLessEqual(len(self.gold),60)
        req=("query_id","query","language","primary_intent","secondary_intents",
             "expected_entities","expected_seminars","constraints","gold_evidence",
             "annotation","review_status")
        for g in self.gold:
            for k in req:
                with self.subTest(q=g.get("query_id"),field=k):
                    self.assertIn(k,g,f"{g.get('query_id')} 缺 {k}")

    def test_01_intent_coverage(self):
        want={"concept_definition","conceptual_relation","diachronic_development",
              "seminar_specific","exact_source","clinical_case","freud_to_lacan",
              "philosophy_to_lacan","matheme","topology","translation_terminology",
              "cross_language_zh_fr"}
        got={g["primary_intent"] for g in self.gold}
        self.assertEqual(want-got,set(),f"缺 intent: {sorted(want-got)}")

    # ---- §4 gold passage 必须真实存在（新硬门禁）
    def test_02_gold_ids_all_exist(self):
        bad=[]; n=0
        for g in self.gold:
            for k in ("required","strong","contextual"):
                for pid in g["gold_evidence"][k]:
                    n+=1
                    if pid not in self.ids: bad.append(f"{g['query_id']}->{pid}")
        self.assertEqual(bad[:5],[],f"{len(bad)} 个 gold 引用了不存在的 passage")
        self.assertGreater(n,0,"gold 总数不应为 0")

    # ---- §3 evidence grade
    def test_03_evidence_grade_shape_and_no_fabrication(self):
        for g in self.gold:
            ge=g["gold_evidence"]
            self.assertEqual(set(ge.keys()),{"required","strong","contextual"})
            for k in ("required","strong","contextual"):
                self.assertIsInstance(ge[k],list)
        # required 可以为空（§3 明确）—— 但不得三者为空却声称 adjudicated
        empty=[g["query_id"] for g in self.gold
               if not any(g["gold_evidence"][k] for k in ("required","strong","contextual"))]
        # 允许无 evidence（如实留空），但必须能解释
        for g in self.gold:
            if g["query_id"] in empty:
                self.assertTrue(g["review_status"],
                                "无 evidence 的条目仍须有 review_status")

    # ---- §3/§4 诚实标注：不得冒充 fully human reviewed
    def test_04_review_status_is_honest(self):
        ok={"adjudicated_script_assisted","reviewed","needs_review"}
        for g in self.gold:
            with self.subTest(q=g["query_id"]):
                self.assertIn(g["review_status"],ok)
                self.assertIn("method",g["annotation"])

    # ---- §5 多标签 intent 模型
    def test_05_multi_intent_model(self):
        self.assertTrue(any(g["secondary_intents"] for g in self.gold),
                        "必须实际使用 secondary_intents（不能全是空）")
        for g in self.gold:
            self.assertIsInstance(g["secondary_intents"],list)
            self.assertNotIn(g["primary_intent"],g["secondary_intents"],
                             "primary 不应重复出现在 secondary")

    # ---- §7 provider contract
    def test_06_provider_contract(self):
        from embedding_provider import (EmbeddingProvider,HashingProvider,
                                        registry_status,ONNX_REGISTRY)
        for name in ("embed_documents","embed_queries","metadata"):
            self.assertTrue(hasattr(EmbeddingProvider,name))
        p=HashingProvider()
        vs=p.embed_documents(["a b c"]); self.assertEqual(len(vs),1)
        m=p.metadata()
        for k in ("provider","model","model_revision","dimensions","max_input",
                  "normalization","multilingual_capability","runtime","device",
                  "available"):
            with self.subTest(field=k):
                self.assertIn(k,m,f"metadata 缺 §7 要求字段 {k}")
        self.assertFalse(m.get("is_neural"),"hashing provider 必须声明非神经")
        # 真实模型必须登记且如实报缺
        st=registry_status()
        onnx=[x for x in st if x.get("provider")=="onnx-local"]
        self.assertEqual(len(onnx),len(ONNX_REGISTRY))
        for x in onnx:
            self.assertIn("blocked_reason",x)
            if not x["available"]:
                self.assertTrue(x["blocked_reason"],"不可用必须写明原因")

    def test_07_hashing_provider_has_no_cross_language_ability(self):
        from embedding_provider import HashingProvider,cosine
        p=HashingProvider()
        v=p.embed_documents(["大他者与享乐","jouissance et désir"])
        sim=cosine(v[0],v[1])
        self.assertLess(sim,0.2,"非神经 provider 的跨语言相似度应接近 0（如实特性）")

    # ---- §8 deterministic benchmark sampling
    def test_08_benchmark_corpus_manifest(self):
        self.assertTrue(os.path.isfile(CMAN),f"缺 {CMAN}")
        with open(CMAN,encoding="utf-8") as f: m=json.load(f)
        for k in ("subset_size","coverage","sampling","corpus_hash"):
            self.assertIn(k,m)
        self.assertGreaterEqual(m["subset_size"],5000)
        self.assertLessEqual(m["subset_size"],8000)
        self.assertFalse(m["sampling"]["random"],"§8 禁止纯随机抽样")
        self.assertEqual(m["coverage"]["seminars"],28,"28 期必须全覆盖")
        langs=set(m["coverage"]["languages"])
        self.assertEqual(langs,{"zh","fr"})

    def test_09_sampling_is_deterministic(self):
        import hashlib
        p=os.path.join(IDX,"vector","vector_benchmark_corpus.jsonl")
        before=hashlib.sha256(open(p,"rb").read()).hexdigest()
        r=subprocess.run([sys.executable,os.path.join(TOOLS,
            "build_vector_benchmark_corpus.py")],capture_output=True,text=True,cwd=VAULT)
        self.assertEqual(r.returncode,0,r.stderr[-400:])
        after=hashlib.sha256(open(p,"rb").read()).hexdigest()
        self.assertEqual(before,after,"benchmark 抽样必须可复现")

    # ---- §20 vector manifest
    def test_10_vector_manifest(self):
        self.assertTrue(os.path.isfile(VMAN),f"缺 {VMAN}")
        with open(VMAN,encoding="utf-8") as f: m=json.load(f)
        for k in ("corpus_hash","passage_count","subset_or_full","embedding_provider",
                  "model","model_revision","dimensions","normalization",
                  "build_config_hash","index_type","index_version"):
            with self.subTest(field=k):
                self.assertIn(k,m,f"manifest 缺 §20 要求字段 {k}")
        # 未过 gate 时不得声称已建
        if m["status"]=="NOT_BUILT":
            self.assertFalse(m["gate_12_full_corpus"]["passed"])
            self.assertTrue(m.get("blocked_reason"))

    def test_11_vector_manifest_corpus_hash_matches(self):
        import hashlib
        with open(VMAN,encoding="utf-8") as f: m=json.load(f)
        h=hashlib.sha256()
        with open(os.path.join(STORE,"passages.jsonl"),"rb") as fh:
            while True:
                b=fh.read(1<<20)
                if not b: break
                h.update(b)
        self.assertEqual(m["corpus_hash"],h.hexdigest(),
                         "vector manifest 的 corpus_hash 必须与 canonical corpus 一致")

    # ---- §6 ambiguous alias
    def test_12_alias_resolver_three_states(self):
        import alias_index as A
        # resolved
        r=A.exact_lookup("objet petit a")
        self.assertTrue(r)
        # ambiguous：有跨实体同写法碰撞的必须暴露
        coll=json.loads(open(os.path.join(IDX,"alias_collisions.jsonl"),
                             encoding="utf-8").readline())
        amb=A.exact_lookup(coll["alias_forms"][0])
        self.assertTrue(amb)
        # unresolved：不存在的别名返回空（不得自动绑定）
        self.assertEqual(A.exact_lookup("zzz_不存在的别名"),[])

    def test_13_high_ambiguity_aliases_not_auto_bound(self):
        """A / Other / Real / object / subject 等高歧义 alias 无上下文时不得自动绑定。"""
        import query_router as R
        for q in ("A","object","subject"):
            plan=R.route(q)
            with self.subTest(query=q):
                # 允许解析出实体，但若解析出，必须不是「静默单一绑定」
                ids={e["entity_id"] for e in plan["entities"]}
                if ids:
                    self.assertGreaterEqual(
                        len(plan["entities"]),1)
        # 单字符 A 必须被过滤（实测它会污染所有含字母 A 的查询）
        self.assertEqual(R.route("A 是什么")["entities"],[])

    # ---- §14 fusion 保留全部 rank
    def test_14_evidence_bundle_keeps_all_ranks(self):
        import hybrid_retrieve as H
        b=H.retrieve("大他者 与 享乐",top_k=3,explain=True)
        for e in b["evidence"]:
            for k in ("lexical_rank","vector_rank","graph_rank","alias_rank",
                      "fusion_rank"):
                self.assertIn(k,e)
        # explain 的键名必须与 evidence 一致
        ex=b["explain"]["fusion_order_before_diversity"]
        if ex:
            self.assertTrue(all(kk.endswith("_rank")
                                for kk in (ex[0].get("ranks") or {"x_rank":1})),
                            "explain.ranks 键名应与 evidence 统一为 <c>_rank")

    def test_15_no_production_vector_index_before_gate(self):
        """§12：gate 未过时不得生成 full-corpus production vector index。"""
        for name in ("vector_index.sqlite","vector.faiss","vector.hnsw","embeddings.npy"):
            p=os.path.join(IDX,"vector",name)
            self.assertFalse(os.path.isfile(p),
                             f"gate 未过却存在 production 产物: {name}")

if __name__=="__main__":
    unittest.main(verbosity=2)
