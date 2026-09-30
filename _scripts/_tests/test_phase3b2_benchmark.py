#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase3b2_benchmark.py — Phase 3B.2 语义评测 / 消融 / 溯源候选 契约测试

这些测试**不重跑**评测（那要几十分钟），只校验**已产出产物之间的自洽性**：

* 评测池没有被偷偷改过（`pool_ids_sha256` 重算一致）
* §14：6,000 条 benchmark corpus **一字未改**（content_hash 不变）
* 池子里确实含全部 gold evidence 与全部反例段落（否则名次无意义）
* answerable / unanswerable 两个分母不重叠、不互相污染
* 所有返回的 passage 都在池内（不能出现池外幻觉）
* 反例的 verdict 与它自己的 margin 一致（规则写在代码里，不是事后凑）
* `VECTOR_INDEX_MANIFEST` 的门禁判据与证据文件一致；
  全量索引不存在时 **status 必须是 NOT_BUILT**（§21 不能被绕过）
* 溯源候选全部 `review_status=candidate` / `canonical=false`，
  且 `concepts.jsonl` 的 hash 与生成时一致（没有自动晋级）
* 报告文件存在且与 JSON 同源（防止文档漂移）
"""
import hashlib
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
VECDIR = os.path.join(VAULT, "_data", "index", "vector")

POOL = os.path.join(VECDIR, "evaluation_pool.json")
BENCH = os.path.join(VECDIR, "vector_benchmark_corpus.jsonl")
BENCH_MANIFEST = os.path.join(VECDIR, "vector_benchmark_corpus_manifest.json")
RESULTS = os.path.join(VECDIR, "semantic_benchmark_results.json")
ABLATION = os.path.join(VECDIR, "hybrid_ablation_v2.json")
CROSSLANG = os.path.join(VECDIR, "CROSSLANG_DIAGNOSTIC.json")
VMAN = os.path.join(VAULT, "VECTOR_INDEX_MANIFEST.json")
CONCEPTS = os.path.join(VAULT, "_data", "passage_store", "concepts.jsonl")
SRC_CAND = os.path.join(VAULT, "concept_source_link_candidates.jsonl")
SRC_REPORT_JSON = os.path.join(VAULT, "_data", "index", "concept_source_link_report.json")

GOLD_ANS = os.path.join(VAULT, "retrieval_gold_answerable.jsonl")
GOLD_UNANS = os.path.join(VAULT, "retrieval_gold_unanswerable.jsonl")
CONTRAST = os.path.join(VAULT, "lacan_contrastive_eval.jsonl")

MD = {
    "semantic": os.path.join(VAULT, "SEMANTIC_BENCHMARK_RESULTS.md"),
    "ablation": os.path.join(VAULT, "HYBRID_ABLATION_REPORT_V2.md"),
    "crosslang": os.path.join(VAULT, "CROSSLANG_DIAGNOSTIC.md"),
    "sourcelink": os.path.join(VAULT, "SOURCE_LINKING_REPORT.md"),
    "gate": os.path.join(VAULT, "RUNTIME_GATES_REPORT.md"),
}


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def sha256_join(items):
    h = hashlib.sha256()
    for x in items:
        h.update(str(x).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def records_sha256(path):
    h = hashlib.sha256()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            h.update(json.dumps(json.loads(line), ensure_ascii=False,
                                sort_keys=True).encode("utf-8"))
            h.update(b"\n")
    return h.hexdigest()


def gold_ids(g):
    out = set()
    for ids in (g.get("gold_evidence") or {}).values():
        out |= set(ids or [])
    return out


class Pool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = load(POOL)

    def test_00_pool_ids_untampered(self):
        self.assertEqual(sha256_join(self.pool["pool_ids"]),
                         self.pool["pool_ids_sha256"],
                         "evaluation_pool 被改过（pool_ids_sha256 不符）")
        self.assertEqual(len(self.pool["pool_ids"]),
                         len(set(self.pool["pool_ids"])), "池内有重复 id")
        self.assertEqual(self.pool["pool_size"], len(self.pool["pool_ids"]))

    def test_01_benchmark_corpus_unchanged(self):
        """§14 要求 6,000 条 benchmark corpus 重跑时**不变**。

        两个哈希用途不同，都要验：
          * `content_hash` = manifest payload 的 canonical hash（由 deterministic 写入）
          * `records_sha256` = **文件内容**的规范化哈希（行序敏感、键序不敏感）
        第一版这里拿整文件 sha256 去比 `content_hash`，必然不相等 ——
        那是把两种哈希混为一谈（不是语料变了）。
        """
        bm = load(BENCH_MANIFEST)
        comp = self.pool["components"]["vector_benchmark_corpus"]
        self.assertEqual(comp["content_hash"], bm.get("content_hash"),
                         "benchmark corpus 的 content_hash 变了 —— §14 被破坏")
        self.assertEqual(comp["records_sha256"], records_sha256(BENCH),
                         "benchmark corpus 的**文件内容**变了 —— §14 被破坏")
        # manifest 自身的 canonical hash 也验一遍
        sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tools"))
        import deterministic
        payload = {k: v for k, v in bm.items()
                   if k not in deterministic._VOLATILE_KEYS}
        self.assertEqual(deterministic.content_hash(payload), bm["content_hash"],
                         "benchmark corpus manifest 的 canonical hash 自校验失败")

    def test_02_pool_superset_of_eval_needs(self):
        ids = set(self.pool["pool_ids"])
        need = set()
        for g in jl(GOLD_ANS) + jl(GOLD_UNANS):
            need |= gold_ids(g)
        for c in jl(CONTRAST):
            need |= set(c.get("positive_passages") or [])
            need |= set(c.get("hard_negatives") or [])
        missing = sorted(need - ids)
        self.assertEqual(missing, [],
                         "池子缺 %d 条评测要用的 passage（名次会失真）: %s"
                         % (len(missing), missing[:5]))

    def test_03_pool_must_include_gold_or_recall_is_meaningless(self):
        """记录「只用 6,000 条时 gold 覆盖为 0」这个事实，防止有人把池子改回去。"""
        ov = self.pool["overlap"]
        self.assertGreater(ov["queries_with_zero_gold_in_benchmark"], 0,
                           "这条记录的意义就是 benchmark-only 覆盖不足；"
                           "若变成 0 说明语料/抽样变了，必须重新论证池子设计")
        self.assertGreater(
            self.pool["components"]["gold_evidence_union"]["added_not_in_benchmark"], 0)


class Benchmark(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = load(RESULTS)
        cls.pool = load(POOL)
        cls.pool_ids = set(cls.pool["pool_ids"])

    def test_10_two_denominators_disjoint(self):
        for m, r in self.d["results"].items():
            ans = {q["query_id"] for q in r["per_query"]}
            un = {q["query_id"] for q in r["unanswerable"]["per_query"]}
            self.assertEqual(ans & un, set(),
                             "%s: answerable 与 unanswerable 有重叠" % m)
            self.assertEqual(r["answerable_n"], len(ans))
            self.assertEqual(r["unanswerable_n"], len(un))
            self.assertGreater(r["answerable_n"], 0, "%s: answerable 分母为 0" % m)

    def test_11_no_passage_outside_pool(self):
        for m, r in self.d["results"].items():
            for q in r["per_query"]:
                for cfg, mm in q["metrics"].items():
                    outside = [p for p in mm["top20"] if p not in self.pool_ids]
                    self.assertEqual(outside, [],
                                     "%s/%s/%s 返回了池外 passage: %s"
                                     % (m, q["query_id"], cfg, outside[:3]))

    def test_12_hard_gates_zero(self):
        for k, v in self.d["meta"]["hard_gates"].items():
            self.assertEqual(v, 0, "硬门禁 %s = %s" % (k, v))

    def test_13_directions_declared_honestly(self):
        for m, r in self.d["results"].items():
            dirs = r["directions"]
            for name in ("A_zh2zh", "B_zh2fr", "C_fr2fr", "D_fr2zh", "MUL_mixed"):
                self.assertIn(name, dirs, "%s 缺方向 %s" % (m, name))
            # n=0 的方向必须**明确标成 0**，不能悄悄给个数字
            for name in ("C_fr2fr", "D_fr2zh"):
                if dirs[name].get("n", 0) == 0:
                    self.assertNotIn("V", dirs[name],
                                     "%s/%s n=0 却给了指标 —— 等于编数字" % (m, name))

    def test_14_zh_fr_direction_recorded_with_real_numbers(self):
        for m, r in self.d["results"].items():
            b = r["directions"]["B_zh2fr"]
            self.assertIn("n", b)
            if b["n"]:
                self.assertIn("V", b)
                self.assertIn("hit@20", b["V"])
                self.assertIsInstance(b["V"]["hit@20"], float)
        # 池内 gold 语言分布必须与「方向 B」的定义一致：gold 全为 fr
        texts = load(os.path.join(VECDIR, "cache_pool_texts.json"))["by_id"]
        for m, r in self.d["results"].items():
            for q in r["per_query"]:
                if "B_zh2fr" in q["directions"]:
                    self.assertEqual(q["query_language"], "zh")
                    self.assertEqual(set(q["gold_languages"]), {"fr"})

    def test_15_contrastive_verdict_matches_its_own_rule(self):
        for m, r in self.d["results"].items():
            c = r["contrastive"]
            self.assertGreater(c["n"], 0, "%s: 反例评测没跑" % m)
            for row in c["rows"]:
                cm, cp, cn = (row.get("candidate_margin"),
                              row.get("candidate_positive_rank"),
                              row.get("candidate_negative_rank"))
                if None in (cm, cp, cn):
                    self.assertIn(row["verdict"], ("PASS", "FAIL"))
                    continue
                expect = "PASS" if cp < cn else "FAIL"
                self.assertEqual(row["verdict"], expect,
                                 "%s/%s verdict 与自身名次不符" % (m, row["eval_id"]))
                self.assertEqual(cm, cn - cp)

    def test_16_unanswerable_not_scored_into_answerable(self):
        for m, r in self.d["results"].items():
            u = r["unanswerable"]
            self.assertIn("独立分母", u["note"])
            for q in u["per_query"]:
                self.assertNotIn("hit@20", q,
                                 "不可答 query 不得带 answerable 指标")


class Ablation(unittest.TestCase):
    def test_20_six_configs_present(self):
        a = load(ABLATION)
        for c in ("L", "V", "E+L", "L+V", "E+L+V", "E+L+V+M"):
            self.assertIn(c, a["configs"], "缺配置 %s" % c)
            for m in a["models"]:
                self.assertIn(c, a["models"][m], "%s 缺配置 %s" % (m, c))

    def test_21_graph_exclusion_is_explained(self):
        a = load(ABLATION)
        self.assertTrue(a.get("graph_excluded_reason"))
        self.assertIn("fixture", a["graph_excluded_reason"])

    def test_22_E_and_M_definitions_present(self):
        """口径必须写下来 —— 不写清就是偷偷改题。"""
        a = load(ABLATION)
        self.assertIn("精确短语", a["E_definition"])
        self.assertIn("不使用 gold", a["M_definition"])

    def test_23_m_is_noop_and_says_so(self):
        """`M` 在本 gold 集上是空操作 → 两个配置必须**数值相同**，
        且定义里必须说明原因（否则读者会以为 metadata 过滤被验证过了）。"""
        a = load(ABLATION)
        for m, agg in a["models"].items():
            self.assertEqual(agg["E+L+V"]["hit@20"], agg["E+L+V+M"]["hit@20"],
                             "%s: M 应当是空操作，两个配置却不同 —— 定义或实现变了" % m)
        self.assertIn("空操作", a["M_definition"])


class CrossLangDiagnostic(unittest.TestCase):
    def test_30_three_hypotheses_all_measured(self):
        d = load(CROSSLANG)
        for h in ("H1_query_document_asymmetry", "H2_truncation", "H3_index_or_pool"):
            self.assertIn(h, d["hypotheses"])
        for m, v in d["models"].items():
            self.assertEqual(v.get("status"), "OK", "%s: 诊断未完成" % m)
            self.assertIn("gold_token_length", v)          # H2
            self.assertIn("H1_margin", v)                  # H1
            sc = v["H3_self_query_ceiling"]                # H3
            self.assertGreater(sc["self_probes"], 0)
            self.assertLessEqual(sc["self_in_top20_count"], sc["self_probes"])

    def test_31_h3_ceiling_interpretation_is_consistent(self):
        """自查询上界是 H3 的判据：若它接近 100%，报告就不能说「索引有问题」。"""
        d = load(CROSSLANG)
        md = open(MD["crosslang"], encoding="utf-8").read()
        for m, v in d["models"].items():
            sc = v["H3_self_query_ceiling"]
            ratio = sc["self_in_top20_count"] / sc["self_probes"]
            if ratio >= 0.95:
                self.assertIn("不成立", md,
                              "H3 实测接近 100%%，报告却没说该假设不成立（%s）" % m)


class VectorGateNotBypassed(unittest.TestCase):
    def test_40_full_corpus_gate_not_bypassed(self):
        man = load(VMAN)
        gate = man["gate_12_full_corpus"]
        ev = gate["evidence"]
        # 判据与证据必须一致
        for k, v in ev.items():
            self.assertEqual(v["passed"], gate["criteria"][k],
                             "判据 %s 的 passed 与 criteria 不一致" % k)
        self.assertEqual(gate["passed"], all(v["passed"] for v in ev.values()))
        # §3C §3：status 由**产物判据**决定；质量判据不得冒充产物状态
        sb = gate.get("status_basis") or {}
        art = sb.get("artifact_criteria_passed") or {}
        expect = ("BUILT_VALIDATED"
                  if art and all(art.get(k) for k in sb["artifact_criteria"])
                  and sb.get("full_index_verification_passed") else "NOT_BUILT")
        self.assertEqual(man["status"], expect, "status 与产物判据不一致")

    def test_41_registry_reflects_runtime(self):
        """旧版 registry 写着 onnxruntime MISSING —— 那是过期描述，必须已被更正。"""
        man = load(VMAN)
        neural = [r for r in man["registry"] if r.get("is_neural")]
        self.assertEqual(len(neural), 2, "registry 应有两个 neural provider")
        for r in neural:
            self.assertTrue(r["available"], "%s 仍标记不可用（与实测矛盾）" % r["model"])
            self.assertEqual(r["max_input"], 128,
                             "%s 的记录长度应为 128（sentence_bert_config.json）" % r["model"])


class SourceLinkCandidates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = jl(SRC_CAND) if os.path.isfile(SRC_CAND) else None
        cls.rep = load(SRC_REPORT_JSON) if os.path.isfile(SRC_REPORT_JSON) else None

    def test_50_all_candidates_not_promoted(self):
        self.assertIsNotNone(self.rows, "缺 concept_source_link_candidates.jsonl")
        self.assertGreater(len(self.rows), 0)
        for r in self.rows:
            self.assertEqual(r["review_status"], "candidate",
                             "出现非 candidate 的 review_status")
            self.assertIs(r["canonical"], False, "出现 canonical=true 的候选")
            self.assertIn("永不", r["promotion_rule"])

    def test_51_concept_store_untouched(self):
        self.assertIsNotNone(self.rep)
        h = self.rep["hashes"]
        self.assertEqual(h["concepts_jsonl_before"], h["concepts_jsonl_after"],
                         "生成候选时改动了 concepts.jsonl")
        self.assertEqual(sha256_file(CONCEPTS), h["concepts_jsonl_after"],
                         "concepts.jsonl 现在与生成时不一致")
        for k, v in self.rep["hard_gates"].items():
            self.assertEqual(v, 0, "硬门禁 %s = %s" % (k, v))

    def test_52_candidates_point_to_real_passages(self):
        ids = set()
        with open(os.path.join(VAULT, "_data", "passage_store", "passages.jsonl"),
                  encoding="utf-8") as f:
            for line in f:
                ids.add(json.loads(line)["id"])
        bad = [r["candidate_passage_id"] for r in self.rows
               if r["candidate_passage_id"] not in ids]
        self.assertEqual(bad, [], "候选指向不存在的 passage: %s" % bad[:5])

    def test_53_proxy_metric_is_labelled_as_proxy(self):
        self.assertIn("代理指标", self.rep["sampling_eval"]["top1_verbatim_definition"])
        self.assertIn("不是精度", self.rep["sampling_eval"]["top1_verbatim_definition"])


class FRDirectionSupplement(unittest.TestCase):
    """§16 —— C/D 用补充标注测到，且**不得污染**主集与主池。"""

    SUPP = os.path.join(VAULT, "retrieval_gold_fr_supplement.jsonl")
    POOL_FR = os.path.join(VECDIR, "evaluation_pool_fr.json")
    FRJSON = os.path.join(VECDIR, "fr_directions.json")

    def test_70_supplement_is_separate_from_primary(self):
        self.assertTrue(os.path.isfile(self.SUPP), "缺补充 gold")
        rows = jl(self.SUPP)
        self.assertGreaterEqual(len(rows), 10)
        for r in rows:
            self.assertEqual(r["supplementary_for"][0] in ("C_fr2fr", "D_fr2zh"), True)
            self.assertEqual(r["language"], "fr")
            self.assertEqual(r["review_status"], "adjudicated_script_assisted",
                             "不得声称已人审")
            self.assertTrue(r["annotation"]["not_merged_into_primary"])
            self.assertIn("独立分母", r["denominator_note"])
        # 主集文件不得含补充集的 query_id
        primary = {g["query_id"] for g in jl(GOLD_ANS)} | \
                  {g["query_id"] for g in jl(GOLD_UNANS)}
        self.assertEqual(primary & {r["query_id"] for r in rows}, set(),
                         "补充集的 query_id 混进了主集")

    def test_71_main_pool_untouched(self):
        pool = load(POOL)
        self.assertEqual(sha256_join(pool["pool_ids"]), pool["pool_ids_sha256"])
        fr = load(self.POOL_FR)
        self.assertTrue(fr["isolated_from_main_pool"])
        self.assertEqual(sha256_join(fr["pool_ids"]), fr["pool_ids_sha256"])
        self.assertNotEqual(fr["pool_ids_sha256"], pool["pool_ids_sha256"])

    def test_72_both_directions_have_samples(self):
        d = load(self.FRJSON)
        for m, v in d["models"].items():
            self.assertGreater(v["aggregate"]["C_fr2fr"]["n"], 0,
                               "%s: 方向 C 仍无样本" % m)
            self.assertGreater(v["aggregate"]["D_fr2zh"]["n"], 0,
                               "%s: 方向 D 仍无样本" % m)
            for q in v["per_query"]:
                self.assertGreater(q["gold_in_pool_n"], 0,
                                   "%s/%s 的 gold 不在池内" % (m, q["query_id"]))

    def test_73_contrarian_finding_is_recorded(self):
        """「跨语言靠术语表不靠 embedding」这个反直觉结论必须有据可查。"""
        d = load(self.FRJSON)
        for m, v in d["models"].items():
            dv = v["aggregate"]["D_fr2zh"]
            self.assertEqual(dv["V"]["hit@20"], 0.0,
                             "%s: D 方向上向量不再是 0 —— 结论变了，报告必须改" % m)
            self.assertGreater(dv["E+L+V+X"]["hit@20"], dv["V"]["hit@20"],
                               "%s: D 方向上 X 未带来增益" % m)
        md = open(os.path.join(VAULT, "PHASE3B2_FINDINGS.md"), encoding="utf-8").read()
        # 不要断言跨行会断开的整句 —— 分别断言两个关键短语
        self.assertIn("术语表", md)
        self.assertIn("不是 embedding", md)

    def test_74_c_direction_vector_is_not_helpful(self):
        d = load(self.FRJSON)
        for m, v in d["models"].items():
            dv = v["aggregate"]["C_fr2fr"]
            self.assertGreaterEqual(dv["L"]["hit@20"], dv["E+L+V"]["hit@20"],
                                    "%s: C 方向上混合不再劣于词法 —— 报告里的负面结论需更新" % m)


class ObjectiveCompliance(unittest.TestCase):
    """§25 —— §1–§25 每条都必须有**可执行判据**，且没有 BLOCKED。"""

    def test_80_no_blocked_and_not_overclaiming(self):
        import subprocess
        r = subprocess.run(
            [sys.executable, os.path.join(VAULT, "_scripts", "_tools",
                                          "check_objective_compliance.py"), "--verify"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-400:])
        # `--verify` 输出的是 indent=2 的多行 JSON，取整个对象而不是最后一行
        out = json.loads(r.stdout[r.stdout.index("{"):])
        self.assertEqual(out["status"], "PASS", out)
        self.assertEqual(out["blocked"], 0, out)
        self.assertGreaterEqual(out["item_count"], 25, "条目数应 ≥25（§1–§25）")

    def test_81_compliance_report_lists_every_section(self):
        p = os.path.join(VAULT, "OBJECTIVE_COMPLIANCE.md")
        self.assertTrue(os.path.isfile(p), "缺 OBJECTIVE_COMPLIANCE.md")
        t = open(p, encoding="utf-8").read()
        for i in range(1, 26):
            self.assertIn("| §%d |" % i, t, "报告缺 §%d" % i)
        self.assertIn("是否声明 Phase 3 完成 | **否**", t)
        self.assertIn("是否进入 Phase 4 | **否**", t)

    def test_82_partial_items_declare_their_gap(self):
        d = json.load(open(os.path.join(VAULT, "_data", "index",
                                        "OBJECTIVE_COMPLIANCE.json"), encoding="utf-8"))
        partials = [r for r in d["items"] if r["status"] == "PARTIAL"]
        self.assertTrue(partials, "应当至少有一条 PARTIAL（§16），全 PROVEN 反而可疑")
        for r in partials:
            self.assertTrue(r.get("gap"), "%s 标了 PARTIAL 却没写缺口" % r["section"])


class WheelhouseCommandUsable(unittest.TestCase):
    """回归：`built_from.download_command` 曾经被逐字符 join 破坏成不可用。"""

    def test_90_download_command_is_a_usable_command(self):
        wh = load(os.path.join(VAULT, "WHEELHOUSE_MANIFEST.json"))
        dc = wh["built_from"]["download_command"]
        self.assertIn("--only-binary=:all:", dc)
        self.assertIn("pip", dc)
        self.assertNotIn("  ", dc, "命令里出现双空格 —— 疑似被逐字符 join 过")
        self.assertLess(len(dc.split()), 200, "token 数异常偏多（逐字符 join 的签名）")


class DocsExist(unittest.TestCase):
    def test_60_reports_present(self):
        for k, p in MD.items():
            self.assertTrue(os.path.isfile(p), "缺报告 %s" % p)
            self.assertGreater(os.path.getsize(p), 500, "%s 内容过少" % p)

    def test_61_reports_do_not_claim_completion(self):
        """报告里不能出现「已完成 Phase 3」这类越界声明。"""
        for k, p in MD.items():
            txt = open(p, encoding="utf-8").read()
            for bad in ("已进入 Phase 4", "Phase 4 已完成"):
                self.assertNotIn(bad, txt, "%s 出现越界声明: %s" % (k, bad))


if __name__ == "__main__":
    unittest.main(verbosity=2)
