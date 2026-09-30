#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase3b1_runtime.py — Phase 3B.1 离线 embedding 运行时契约测试

覆盖：
  §2  RUNTIME_TARGET 由解释器自身 tag 推导（不按 "macOS" 猜）
  §4  运行时直接依赖来自真实 import 探测（不是手写）
  §5/§6 wheelhouse：manifest 完整、逐 wheel sha256 可校验、lock 一致、
        且**离线装得出来**（--no-index，干净 venv）
  §9  Tokenizer Gate：★ 不能有 padding 泄漏 ★ / truncation 契约 / 特殊 token
  §10 Semantics Gate：维度 / NaN / 零范数 / 重复确定性
  §11 Reference Parity：fixture 覆盖截断边界 + 与 sentence-transformers 数值一致
  §12 MODEL_MANIFEST 的 sha256 必须对得上真实文件
  §23 硬门禁计数必须为 0

为什么要有「padding 泄漏」这条测试
──────────────────────────────────
第一版 provider 用 `mask[i, :len(b.ids)] = 1` 造 attention mask。
而 `tokenizers` 0.22.2 的 `encode_batch` 会**按批内最长补齐**（tokenizer.json 自带
padding 配置），于是 `len(b.ids)` 对批内每条都是同一个数，mask 全变 1，
`<pad>` 被当成真实 token 参与 mean-pooling —— **向量全错，而且不报错**。
这是 §11 reference parity 才揪出来的。本测试把它钉死。
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.path.join(VAULT, "_scripts", "_tools")
BUILD = os.path.expanduser("<HOME>")
VECDIR = os.path.join(VAULT, "_data", "index", "vector")

RUNTIME_TARGET = os.path.join(VAULT, "RUNTIME_TARGET.json")
REQ_IN = os.path.join(VAULT, "embedding-runtime-requirements.in")
REQ_LOCK = os.path.join(VAULT, "embedding-runtime-requirements.lock")
WH_MANIFEST = os.path.join(VAULT, "WHEELHOUSE_MANIFEST.json")
MODEL_MANIFEST = os.path.join(VAULT, "MODEL_MANIFEST.json")
FIXTURE = os.path.join(VECDIR, "embedding_reference_fixture.json")
PARITY_MANIFEST = os.path.join(VECDIR, "RUNTIME_PARITY_MANIFEST.json")
REF_MODEL_MANIFEST = os.path.join(VECDIR, "REFERENCE_MODEL_MANIFEST.json")

ONNX_PY = os.path.join(VAULT, ".venv-embedding", "bin", "python")
REF_PY = os.path.join(BUILD, "reference-venv", "bin", "python")

MODELS = ("minilm", "mpnet")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def run(py, code, timeout=900):
    return subprocess.run([py, "-c", code], capture_output=True, text=True,
                          timeout=timeout)


class RuntimeTarget(unittest.TestCase):
    """§2 — 平台判定必须来自解释器，不许按操作系统名猜。"""

    def test_01_runtime_target_exists_and_has_probe(self):
        self.assertTrue(os.path.isfile(RUNTIME_TARGET), "缺 RUNTIME_TARGET.json")
        t = load(RUNTIME_TARGET)
        for k in ("operating_system", "machine", "python_version_short", "cache_tag",
                  "sysconfig_platform", "supported_wheel_tags_count",
                  "supported_wheel_tags", "wheel_selection_rule", "probe_commands"):
            self.assertIn(k, t, "RUNTIME_TARGET 缺字段 %s" % k)
        self.assertGreaterEqual(t["supported_wheel_tags_total"], 100,
                                "supported tags 数量不合理")
        self.assertTrue(t["probe_commands"], "必须记录原始探测命令")

    def test_02_wheel_selection_rule_forbids_os_name_guessing(self):
        t = load(RUNTIME_TARGET)
        rule = t["wheel_selection_rule"]
        self.assertIn("不得仅按", rule)
        # sysconfig 报 universal2 而机器是 arm64 —— 这条差异必须被显式记录
        self.assertEqual(t["machine"], "arm64")
        self.assertIn("universal2", t["sysconfig_platform"])

    def test_03_wheelhouse_platform_tags_come_from_interpreter(self):
        if not os.path.isfile(WH_MANIFEST):
            self.skipTest("wheelhouse 未构建")
        wh = load(WH_MANIFEST)
        tags = wh["built_from"]["platform_tags_offered"]
        self.assertTrue(tags, "必须记录实际使用的平台 tag")
        for p in tags:
            self.assertTrue(p.endswith(("_arm64", "_universal2")),
                            "不应混入非本机架构 tag: %s" % p)
        # RUNTIME_TARGET.supported_wheel_tags 本身只存了前 60 个（head），
        # 因此不能直接做子集判断；改为**重新从解释器推导一遍**再比。
        r = run(ONNX_PY, "import sys,json;sys.path.insert(0,%r);"
                "import build_wheelhouse as b;print(json.dumps(b.supported_platforms(%r)))"
                % (TOOLS, ONNX_PY))
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        derived = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(set(tags), set(derived),
                         "wheelhouse 用的平台 tag 必须等于解释器当前支持的 tag 集合")


class RuntimeDeps(unittest.TestCase):
    """§4 — 依赖来自 AST 扫描 + 运行时验证，不是猜的。"""

    def test_10_direct_deps_match_actual_imports(self):
        src = open(os.path.join(TOOLS, "embedding_provider.py"), encoding="utf-8").read()
        for mod in ("numpy", "onnxruntime", "tokenizers"):
            self.assertTrue(
                ("import %s" % mod) in src or ("from %s import" % mod) in src,
                "provider 实际 import %s，.in 里必须声明" % mod)
        declared = [l.strip() for l in open(REQ_IN, encoding="utf-8")
                    if l.strip() and not l.startswith("#")]
        self.assertEqual(sorted(declared), ["numpy", "onnxruntime", "tokenizers"])

    def test_11_lock_has_no_handwritten_transitive_deps(self):
        lock = open(REQ_LOCK, encoding="utf-8").read()
        # 传递依赖必须由 pip 解析得到；至少这些真实存在的必须在内
        for pkg in ("coloredlogs", "flatbuffers", "protobuf", "sympy", "numpy",
                    "onnxruntime", "tokenizers"):
            self.assertIn(pkg.lower(), lock.lower(),
                          "lock 缺 %s —— 传递依赖必须是 pip 解析出来的" % pkg)


class Wheelhouse(unittest.TestCase):
    """§5/§6 — wheelhouse 完整性 + 真的能离线装出来。"""

    @classmethod
    def setUpClass(cls):
        cls.wh = load(WH_MANIFEST) if os.path.isfile(WH_MANIFEST) else None

    def test_20_manifest_completeness(self):
        if self.wh is None:
            self.skipTest("wheelhouse 未构建")
        self.assertGreaterEqual(self.wh["wheel_count"], 30)
        for e in self.wh["wheels"]:
            for k in ("filename", "package", "version", "wheel_tags", "sha256",
                      "size_bytes", "source", "target_compatibility", "purpose"):
                self.assertIn(k, e, "wheel 条目缺 %s" % k)
            self.assertEqual(len(e["sha256"]), 64)

    def test_21_wheelhouse_verify_passes(self):
        if self.wh is None:
            self.skipTest("wheelhouse 未构建")
        r = run(sys.executable, "import sys;sys.path.insert(0,%r);"
                "import build_wheelhouse as b;"
                "import json;print(json.dumps(b.cmd_verify()))" % TOOLS)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["status"], "PASS", out)
        self.assertEqual(out["problems"], [])
        self.assertEqual(out["wheelhouse_hash"], out["recomputed_hash"])
        self.assertTrue(out["lock_consistent"], "wheelhouse 与 lock 不一致")

    def test_22_offline_install_proven(self):
        if self.wh is None:
            self.skipTest("wheelhouse 未构建")
        t = self.wh.get("offline_install_test")
        self.assertIsNotNone(t, "必须做过离线安装测试（§5/§6 核心证据）")
        self.assertEqual(t["status"], "PASS", t)
        self.assertFalse(t["network_used"], "--no-index 才叫离线")
        self.assertIn("--no-index", t["command"])
        self.assertEqual(t["version_mismatch_vs_lock"], {},
                         "离线装出来的版本必须与 lock 完全一致")
        self.assertEqual(t["import_check_returncode"], 0)
        self.assertGreaterEqual(t["packages_installed"], 30,
                                "离线装出来的包数不合理")
        self.assertIn("onnxruntime", t["import_check_stdout"])


class TokenizerAndSemanticsGate(unittest.TestCase):
    """§9/§10 — tokenizer 与语义契约（需要 .venv-embedding）。"""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(ONNX_PY):
            raise unittest.SkipTest("缺 .venv-embedding —— 运行时未安装")

    def test_30_attention_mask_has_no_padding_leak(self):
        """★ 回归测试：批内动态 padding 不得把 <pad> 算进 attention mask。★"""
        code = r'''
import json, sys
sys.path.insert(0, %r)
import embedding_provider as ep
texts = ["a", "le grand Autre et le sujet de l'inconscient dans la psychanalyse lacanienne " * 3,
         "大他者", "objet petit a", "象征界与语言的关系究竟是什么 " * 4]
out = {}
for k in ("minilm", "mpnet"):
    p = ep.OnnxTransformersProvider(k)
    batch = p.encode_lengths(texts)
    batch_sums = [int(sum(x["attention_mask"])) for x in batch]
    single = [int(sum(p.encode_lengths([t])[0]["attention_mask"])) for t in texts]
    out[k] = {"batch_sums": batch_sums, "single_sums": single,
              "batch_max": max(len(x["ids"]) for x in batch)}
print(json.dumps(out))
''' % (TOOLS,)
        r = run(ONNX_PY, code)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        for k, v in out.items():
            self.assertEqual(
                v["batch_sums"], v["single_sums"],
                "%s: 批内 mask 与单条 mask 不一致 —— 批内 padding 泄漏成有效 token" % k)
            # 这是旧 bug 的签名：批内所有 mask 都等于批内最长
            self.assertNotEqual(
                set(v["batch_sums"]), {v["batch_max"]},
                "%s: 批内 mask 全等于批内最长 %d —— padding 泄漏（旧 bug 复发）"
                % (k, v["batch_max"]))

    def test_31_truncation_follows_model_contract(self):
        code = r'''
import json, sys
sys.path.insert(0, %r)
import embedding_provider as ep
long_text = "le sujet de l'inconscient " * 400
zh_long = "无意识的主体与能指的关系" * 400
out = {}
for k in ("minilm", "mpnet"):
    p = ep.OnnxTransformersProvider(k)
    lc = p.length_contract
    L = p.encode_lengths([long_text, zh_long])
    out[k] = {"contract": lc, "effective": lc["effective_max_length"],
              "lengths": [len(x["ids"]) for x in L],
              "st_max_seq": lc["sentence_transformers_max_seq_length"]}
print(json.dumps(out))
''' % (TOOLS,)
        r = run(ONNX_PY, code)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        for k, v in out.items():
            c = v["contract"]
            # 长度必须来自模型目录，不是硬编码 512
            self.assertIsNotNone(c["sentence_transformers_max_seq_length"],
                                 "%s: 必须读出 sentence_bert_config.json 的 max_seq_length" % k)
            self.assertEqual(c["effective_max_length"],
                             c["sentence_transformers_max_seq_length"],
                             "%s: effective 必须等于 sentence-transformers 参考契约（不做静默分叉）" % k)
            for L in v["lengths"]:
                self.assertEqual(L, v["effective"],
                                 "%s: 超长文本必须被截断到契约长度 %d，实测 %d"
                                 % (k, v["effective"], L))

    def test_32_special_tokens_and_determinism(self):
        code = r'''
import json, sys
sys.path.insert(0, %r)
import embedding_provider as ep
texts = ["le grand Autre", "大他者", "objet petit a"]
out = {}
for k in ("minilm", "mpnet"):
    p = ep.OnnxTransformersProvider(k)
    e1 = p.encode_lengths(texts)
    e2 = p.encode_lengths(texts)
    v1 = p.embed_documents(texts)
    v2 = p.embed_documents(texts)
    out[k] = {
        "ids_equal_on_repeat": [x["ids"] for x in e1] == [x["ids"] for x in e2],
        "vecs_bitwise_equal": v1 == v2,
        "first_token_ids": [x["ids"][0] for x in e1],
        "last_token_ids": [x["ids"][-1] for x in e1],
        "tokens_are_str": all(isinstance(t, str) for x in e1 for t in x["tokens"]),
        "dims": len(v1[0]),
        "norms": [sum(y * y for y in v) ** 0.5 for v in v1],
        "finite": all(y == y and abs(y) != float("inf") for v in v1 for y in v),
        "zero_norm": any(all(y == 0.0 for y in v) for v in v1),
    }
    out[k]["bos_eos_repeat"] = len({(x["ids"][0], x["ids"][-1]) for x in e1}) == 1
print(json.dumps(out))
''' % (TOOLS,)
        r = run(ONNX_PY, code)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        for k, v in out.items():
            self.assertTrue(v["ids_equal_on_repeat"], "%s: tokenize 不确定" % k)
            self.assertTrue(v["vecs_bitwise_equal"], "%s: 重复推理不是逐位相同" % k)
            self.assertTrue(v["bos_eos_repeat"],
                            "%s: 每条都应带同一对特殊 token（首/尾 id 一致）" % k)
            self.assertFalse(v["zero_norm"], "%s: 出现零向量" % k)
            self.assertTrue(v["finite"], "%s: 出现 NaN/Inf" % k)
            for n in v["norms"]:
                self.assertAlmostEqual(n, 1.0, places=5, msg="%s: L2 范数不是 1" % k)
        self.assertEqual(out["minilm"]["dims"], 384)
        self.assertEqual(out["mpnet"]["dims"], 768)


class ModelManifest(unittest.TestCase):
    """§12 — 模型文件 hash 必须对得上真实文件。"""

    def test_40_model_manifest_hashes_match_files(self):
        self.assertTrue(os.path.isfile(MODEL_MANIFEST), "缺 MODEL_MANIFEST.json")
        man = load(MODEL_MANIFEST)
        import hashlib
        checked = 0
        for key, m in man["models"].items():
            root = m["model_directory"]
            # 长度契约必须被记进 manifest —— 它是能改变全部指标的参数
            self.assertIn("effective_max_length", m,
                          "%s: manifest 必须记录生效长度" % key)
            self.assertIn("sentence_bert_config.json", m["files"],
                          "%s: 决定截断长度的文件必须在 manifest 里" % key)
            for rel, f in m["files"].items():
                if not f.get("present"):
                    continue
                p = os.path.join(root, rel)
                self.assertTrue(os.path.isfile(p), "缺文件: %s" % p)
                h = hashlib.sha256(open(p, "rb").read()).hexdigest()
                self.assertEqual(h, f["sha256"], "模型文件被换过: %s" % p)
                checked += 1
        self.assertGreaterEqual(checked, 16, "MODEL_MANIFEST 里可校验的文件太少")


class ReferenceParity(unittest.TestCase):
    """§11 — 与 sentence-transformers 的数值一致性。"""

    def test_50_fixture_covers_truncation_boundary(self):
        self.assertTrue(os.path.isfile(FIXTURE), "缺 embedding_reference_fixture.json")
        fix = load(FIXTURE)
        n = fix["total_items"]
        self.assertGreaterEqual(n, 20, "§11 要求 20–30 条文本")
        self.assertLessEqual(n, 40)
        self.assertGreaterEqual(fix["query_items"], 5)
        buckets = fix["passage_token_length"]["by_bucket"]
        for b in ("tiny", "short", "near_limit", "over_limit"):
            self.assertGreater(buckets.get(b, 0), 0,
                               "fixture 必须覆盖长度桶 %s（否则截断差异测不出来）" % b)
        self.assertGreater(fix["passage_token_length"]["count_over_128"], 0,
                           "必须有 >128 token 的文本：这是截断契约的探针")

    def test_51_parity_manifest_passes(self):
        if not os.path.isfile(PARITY_MANIFEST):
            self.skipTest("parity 未运行")
        man = load(PARITY_MANIFEST)
        self.assertEqual(man["overall_status"], "PASS", man["models"])
        for k, v in man["models"].items():
            self.assertEqual(v["status"], "PASS", v)
            self.assertEqual(v["problems"], [])
            self.assertTrue(v["dims"]["match"], "%s: 维度不一致" % k)
            self.assertGreaterEqual(v["cosine_min"], 0.99999,
                                    "%s: 与参考实现的余弦过低" % k)
            self.assertLessEqual(v["max_abs_component_diff"], 1e-4,
                                 "%s: 分量差超过阈值" % k)
            self.assertEqual(v["top5_jaccard_min"], 1.0,
                             "%s: top-5 邻居集合与参考实现不一致" % k)
            self.assertEqual(v["max_seq_length"]["reference"],
                             v["max_seq_length"]["onnx"],
                             "%s: 截断长度与参考实现不一致" % k)

    def test_52_reference_weights_are_upstream(self):
        self.assertTrue(os.path.isfile(REF_MODEL_MANIFEST),
                        "缺 REFERENCE_MODEL_MANIFEST.json —— 参考权重来源不可追溯")
        man = load(REF_MODEL_MANIFEST)
        for k, m in man["models"].items():
            self.assertTrue(m["summary"]["all_downloaded"], "%s: 参考权重未下全" % k)
            self.assertEqual(m["summary"]["local_files_differing"], [],
                             "%s: 本地模型文件与上游不一致" % k)
            self.assertIn("model.safetensors", m["files"],
                          "%s: 必须有上游权重文件" % k)

    def test_53_reference_run_reproducible(self):
        """参考实现必须能在本机离线重跑（否则 parity 证据不可复现）。"""
        if not os.path.exists(REF_PY):
            self.skipTest("参考 venv 不存在")
        code = ("import os;os.environ.setdefault('HF_HUB_OFFLINE','1');"
                "os.environ.setdefault('TRANSFORMERS_OFFLINE','1');"
                "from sentence_transformers import SentenceTransformer;"
                "m=SentenceTransformer(%r,device='cpu');"
                "print(m.max_seq_length, m.get_sentence_embedding_dimension())"
                % os.path.join(BUILD, "reference-models", "minilm"))
        r = run(REF_PY, code)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        max_seq, dims = r.stdout.strip().splitlines()[-1].split()
        self.assertEqual(int(max_seq), 128,
                         "参考实现的 max_seq_length 应为 128（sentence_bert_config.json）")
        self.assertEqual(int(dims), 384)


class HardGates(unittest.TestCase):
    """§23 — 新增硬门禁必须为 0。"""

    def test_60_hard_gates_zero(self):
        if not os.path.isfile(PARITY_MANIFEST):
            self.skipTest("parity 未运行")
        g = load(PARITY_MANIFEST)["hard_gates"]
        for name in ("runtime_reference_parity_failure", "invalid_embedding_dimension",
                     "max_seq_length_mismatch"):
            self.assertEqual(g.get(name), 0, "硬门禁 %s = %s（应为 0）" % (name, g.get(name)))

    def test_61_vendor_gates_semantics(self):
        code = r'''
import json, sys
sys.path.insert(0, %r)
import embedding_provider as ep
finals = []
for k in ("minilm", "mpnet"):
    p = ep.OnnxTransformersProvider(k)
    v = p.embed_documents(["le grand Autre", "大他者"])
    finals.append({
        "model": k, "dims": len(v[0]),
        "nan_or_inf": sum(1 for x in v for y in x if y != y or abs(y) == float("inf")),
        "zero_norm": sum(1 for x in v if all(y == 0.0 for y in x)),
    })
print(json.dumps(finals))
''' % (TOOLS,)
        if not os.path.exists(ONNX_PY):
            self.skipTest("缺 .venv-embedding")
        r = run(ONNX_PY, code)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        for f in json.loads(r.stdout.strip().splitlines()[-1]):
            self.assertEqual(f["nan_or_inf"], 0, "NaN_or_Inf_embedding: %s" % f)
            self.assertEqual(f["zero_norm"], 0, "zero-norm embedding: %s" % f)


class HardGatesConsolidated(unittest.TestCase):
    """§23 —— 17 项硬门禁必须**现算**为 0（不是从文档里手抄）。"""

    def test_80_all_hard_gates_zero(self):
        r = run(sys.executable, "import sys,json;sys.path.insert(0,%r);"
                "import check_hard_gates as g;print(json.dumps(g.cmd_verify()))" % TOOLS)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["status"], "PASS", out)
        self.assertEqual(out["problems"], [])
        self.assertGreaterEqual(out["gate_count"], 17,
                                "§23 要求 8 项原有 + 6 项新增，本表应 ≥14；当前 %d"
                                % out["gate_count"])
        self.assertTrue(out["all_zero"], out)

    def test_81_gate_report_is_computed_not_copied(self):
        """报告必须含「算法/数据来源」列 —— 说明数字是算出来的，不是声明出来的。"""
        p = os.path.join(VAULT, "HARD_GATES_REPORT.md")
        self.assertTrue(os.path.isfile(p), "缺 HARD_GATES_REPORT.md")
        txt = open(p, encoding="utf-8").read()
        for name in ("fabricated_passage_ids", "runtime_reference_parity_failure",
                     "answerable_unanswerable_metric_contamination",
                     "wheelhouse_hash_mismatch",
                     "automatic_source_link_canonicalization"):
            self.assertIn(name, txt, "报告缺门禁 %s" % name)
        self.assertIn("算法 / 数据来源", txt)

    def test_82_vector_index_gate_uses_one_hash_rule(self):
        """`corpus_hash` 与 `content_hash` 是两种规则 —— 报告必须点明这一点。

        第一版门禁把两者直接相比，报出假违规 1。这个测试防止同类错误复发。
        """
        d = json.load(open(os.path.join(VAULT, "_data", "index", "HARD_GATES.json"),
                           encoding="utf-8"))
        n = d["notes"]["vector_index_corpus_hash_mismatch"]
        self.assertIn("rule", n)
        self.assertIn("原始字节", n["rule"])
        self.assertIn("build_meta_content_hash_IS_A_DIFFERENT_RULE", n)
        self.assertEqual(d["gates"]["vector_index_corpus_hash_mismatch"], 0)


class FixedLengthProbe(unittest.TestCase):
    """§9「定长固定文本」探针必须存在于 gate 产物里并通过。"""

    def test_90_fixed_length_padding_invariant(self):
        p = os.path.join(VAULT, "_data", "index", "vector", "RUNTIME_GATES.json")
        d = json.load(open(p, encoding="utf-8"))
        for k, v in d["tokenizer"].items():
            f = v.get("fixed_length_probe")
            self.assertIsNotNone(f, "%s 缺定长固定文本探针" % k)
            self.assertTrue(f["passed"], "%s 探针未通过: %s" % (k, f))
            self.assertTrue(f["padded_positions_masked"],
                            "%s: 补位没有被 mask 掉" % k)
            self.assertGreaterEqual(f["A_vs_B_cosine"], 0.99999)
            self.assertGreaterEqual(f["A_vs_C_cosine"], 0.99999)


class ReferenceIdentityRecorded(unittest.TestCase):
    """§11 —— manifest 必须记 model / revision / tokenizer hash / pooling / normalization。"""

    def test_91_model_identity_complete(self):
        p = os.path.join(VAULT, "_data", "index", "vector", "RUNTIME_PARITY_MANIFEST.json")
        man = json.load(open(p, encoding="utf-8"))
        ident = man.get("model_identity")
        self.assertTrue(ident, "parity manifest 缺 model_identity")
        for k, v in ident.items():
            for field in ("model", "revision", "tokenizer_sha256", "pooling",
                          "normalization", "dimensions", "sentencepiece_sha256"):
                self.assertIn(field, v, "%s 缺 %s" % (k, field))
                self.assertIsNotNone(v[field], "%s.%s 为空" % (k, field))
            self.assertEqual(len(v["tokenizer_sha256"]), 64)
            self.assertTrue(v["upstream"]["local_files_match_upstream"],
                            "%s: 本地模型文件与上游不一致" % k)
        self.assertTrue(man.get("reference_environment"))
        self.assertTrue(man.get("onnx_environment"))

    def test_92_fixture_self_describing(self):
        p = os.path.join(VAULT, "_data", "index", "vector", "embedding_reference_fixture.json")
        fix = json.load(open(p, encoding="utf-8"))
        self.assertIn("model_identity", fix, "fixture 应自描述（含 model_identity）")


class ThroughputCosted(unittest.TestCase):
    """§21 —— 全量索引未建，但成本必须**实测**清楚，且多线程必须被证明安全。"""

    def test_95_throughput_measured_and_threadsafe(self):
        p = os.path.join(VAULT, "_data", "index", "vector", "THROUGHPUT.json")
        self.assertTrue(os.path.isfile(p), "缺 THROUGHPUT.json —— 全量构建成本未实测")
        d = json.load(open(p, encoding="utf-8"))
        self.assertTrue(d["models"], "没有任何模型的吞吐数据")
        for k, v in d["models"].items():
            self.assertTrue(v["best_topk_agrees"],
                            "%s: 不同线程数下 top-k 不一致 → 多线程构建不安全" % k)
            self.assertGreaterEqual(len(v["per_thread_count"]), 2,
                                    "%s: 至少要比 1 线程与多线程" % k)
            proj = v["projection_full_corpus"]
            self.assertEqual(proj["passages"], 249105)
            self.assertGreater(proj["hours"], 0)
            self.assertGreater(proj["index_mb"], 0)
        # 门禁必须引用实测值，而不是留空
        man = json.load(open(os.path.join(VAULT, "VECTOR_INDEX_MANIFEST.json"),
                             encoding="utf-8"))
        ev = man["gate_12_full_corpus"]["evidence"]["full_corpus_index_exists"]
        self.assertTrue(ev.get("measured_throughput"),
                        "§21 证据里没有实测吞吐")
        self.assertIn("实测", ev["expected"])


class VectorIndexStatusSemantics(unittest.TestCase):
    """§21 §3C §3 — `status` 描述**产物**（索引建没建、验没验），不描述检索质量。

    两者必须能同时如实存在：索引已建成验证（BUILT_VALIDATED），
    而检索质量判据仍为 false。
    """

    def test_70_status_consistent_with_artifact_criteria(self):
        p = os.path.join(VAULT, "VECTOR_INDEX_MANIFEST.json")
        if not os.path.isfile(p):
            self.skipTest("无 VECTOR_INDEX_MANIFEST.json")
        man = load(p)
        gate = man["gate_12_full_corpus"]
        sb = gate.get("status_basis")
        self.assertIsNotNone(sb, "必须写明 status 由哪些判据决定（§3）")
        art = sb["artifact_criteria_passed"]
        expect = ("BUILT_VALIDATED"
                  if all(art.get(k) for k in sb["artifact_criteria"])
                  and sb.get("full_index_verification_passed") else "NOT_BUILT")
        self.assertEqual(man["status"], expect,
                         "status 与产物判据不一致（不得用质量判据否认产物状态）")
        # 质量判据必须单独存放，不与 status 混淆
        self.assertIn("retrieval_quality", man)
        self.assertEqual(set(man["retrieval_quality"]["criteria"]),
                         set(sb["quality_criteria"]))

    def test_71_no_declaration_while_quality_criteria_fail(self):
        p = os.path.join(VAULT, "VECTOR_INDEX_MANIFEST.json")
        if not os.path.isfile(p):
            self.skipTest("无 VECTOR_INDEX_MANIFEST.json")
        man = load(p)
        q = man["retrieval_quality"]["criteria"]
        if not all(q.values()):
            self.assertFalse(man["gate_12_full_corpus"]["passed"],
                             "质量判据未全过时 gate.passed 不得为 true")


if __name__ == "__main__":
    unittest.main(verbosity=2)
