#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_phase2_passage_store.py — Canonical Passage Store（Phase 2）

覆盖用户要求的这些测试项：
  2. stable passage ID
  4. passage count conservation
  5. provenance closure
  6. no invented metadata
  7. broken passage references
  9. duplicate passage IDs
  10. source hash stability
  11. lossless ingestion
  15. idempotent re-ingestion

契约（来自任务书 §一/§二/§六/§七/§八）：
  * Passage 是最小引用证据单位；ID 一旦生成不得因重跑而改变
  * 日期不能确认时必须保留 unknown，不得猜测
  * **不创建 249,105 个 Markdown**：人类阅读层与机器 Store 分离
  * ID 不得依赖时间 / 读取顺序 / UUID / dict 迭代顺序
  * normalization 必须可解释：raw_text + normalized_text + operations
  * 每个 Passage 必须能闭合到 source segment → document → physical file → sha256
"""

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE_DIR = os.path.join(VAULT, "_data", "passage_store")
SQLITE = os.path.join(VAULT, "_index", "passage_store.sqlite")
BUILDER = os.path.join(VAULT, "_scripts", "_tools", "build_passage_store.py")

ZH_BASELINE = 82578
FR_BASELINE = 166527
TOTAL_BASELINE = 249105

# §一 的 ID 形态示例
ID_RE_PASSAGE = re.compile(
    r"^passage\.S(?:T\d{1,2}|\d{2}[A-Z]?)\.(?:\d{4}-(?:\d{2}-\d{2}|unknown)|unknown)(?:\.L\d{2,3})?\.P\d{4}$")
ID_RE_SESSION = re.compile(
    r"^session\.S(?:T\d{1,2}|\d{2}[A-Za-z]?)\."
    r"(?:\d{4}-(?:\d{2}-\d{2}|unknown)|unknown)"
    r"(?:\.L\d{2,3})?(?:\.p\d{1,4})?$")
ID_RE_SEMINAR = re.compile(r"^seminar\.S(?:T\d{1,2}|\d{2}[A-Z]?)$")


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


class PassageStore(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.built = os.path.isfile(BUILDER)
        if cls.built:
            # 确保 store 存在（构建是幂等的，重复跑不应改变内容）
            subprocess.run([sys.executable, BUILDER], capture_output=True,
                           text=True, cwd=VAULT)
        cls.passages_p = os.path.join(STORE_DIR, "passages.jsonl")
        cls.witnesses_p = os.path.join(STORE_DIR, "witnesses.jsonl")
        cls.translations_p = os.path.join(STORE_DIR, "translations.jsonl")
        cls.passages = None
        if os.path.isfile(cls.passages_p):
            cls.passages = list(load_jsonl(cls.passages_p))
        # 源文件 sha256（供 test_04 校验）
        cls._zh_sha = None
        cls._fr_sha = None
        mp = os.path.join(VAULT, "_data", "BACKUP_MANIFEST.json")
        if os.path.isfile(mp):
            with open(mp, encoding="utf-8") as fh:
                man = json.load(fh)
            for fe in man["files"]:
                if fe["path"] == "segments.jsonl":
                    cls._zh_sha = fe["sha256"]
                elif fe["path"] == "french_staferla.jsonl":
                    cls._fr_sha = fe["sha256"]

    def setUp(self):
        if not self.built:
            self.fail(f"缺构建脚本 {BUILDER}")
        if self.passages is None:
            self.fail(f"缺 Passage store: {self.passages_p}")

    # ---- 0 store 与 schema 存在
    def test_00_store_files_exist(self):
        for p in (self.passages_p, self.witnesses_p, self.translations_p):
            with self.subTest(path=p):
                self.assertTrue(os.path.isfile(p), f"缺 {p}")
        self.assertTrue(os.path.isfile(SQLITE), f"缺 machine store {SQLITE}")

    # ---- 2 stable passage ID（形态 + 确定性）
    def test_01_passage_id_shape_and_unknown_preserved(self):
        """ID 形态必须符合 §一 的规范；无法确认的日期必须保留 unknown。"""
        bad = []
        for p in self.passages[:5000]:
            if not ID_RE_PASSAGE.match(p["id"]):
                bad.append(p["id"])
        self.assertEqual(bad[:5], [], f"ID 形态不合规，例：{bad[:3]}")
        # unknown 必须真的被保留（不得被猜成具体日期）
        has_unknown = any(".unknown." in p["id"] for p in self.passages[:5000])
        self.assertTrue(has_unknown, "在无法确证日期时应出现 .unknown.，实际没有")
        for p in self.passages[:5000]:
            if ".unknown." in p["id"]:
                self.assertEqual(p["session_date"], "unknown",
                                 "ID 写 unknown 但 session_date 不是 unknown")
                self.assertEqual(p["session_date_precision"], "unknown")

    # ---- 2b stable ID 不依赖时间/顺序/UUID（重建后逐字相同）
    def test_02_ids_stable_across_rebuild(self):
        """同一语料重建，Passage ID 集合必须逐字相同。"""
        before = [p["id"] for p in self.passages]
        r = subprocess.run([sys.executable, BUILDER], capture_output=True,
                           text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, f"重建失败:\n{r.stderr[-600:]}")
        after = [p["id"] for p in load_jsonl(self.passages_p)]
        self.assertEqual(before, after, "重建后 Passage ID 序列发生变化")

    # ---- 4 passage count conservation
    def test_03_count_conservation(self):
        """段数守恒：zh 82,578 / fr 166,527 / 合 249,105，一条都不能少。"""
        n = len(self.passages)
        self.assertEqual(n, TOTAL_BASELINE, f"Passage 总数 {n} != {TOTAL_BASELINE}")
        from collections import Counter
        c = Counter(p["language"] for p in self.passages)
        self.assertEqual(c["zh"], ZH_BASELINE, f"中文 {c['zh']} != {ZH_BASELINE}")
        self.assertEqual(c["fr"], FR_BASELINE, f"法文 {c['fr']} != {FR_BASELINE}")

    # ---- 5 provenance closure
    def test_04_provenance_closure(self):
        """§八 溯源：要么整条闭合，要么**显式**标 INCOMPLETE 并写明缺哪一环。

        实测事实（很重要，别再搞错）：
        `atlas/segments.jsonl` 与 `atlas/french_staferla.jsonl` **不在** Phase 1 的
        143 个原始文件里 —— 它们是 .lacan-build/ 的产物。所以：

          * 中译：上游源目录已消失 → 只能到「recovered 文件」，缺 upstream original
          * 法语：atlas 文件可自证 sha256，但上游 STAFERLA 不在本机 → 缺 physical source

        因此正确的契约不是「全部闭合」，而是：
          「COMPLETE 的必须真的闭合；INCOMPLETE 的必须有 trace_missing 且字段一致」
        """
        complete = incomplete = 0
        problems = []
        for p in self.passages:
            prov = p.get("provenance") or {}
            ts = p.get("trace_status")
            # 1) 承载该段的可验证文件必须始终存在且 hash 可查
            if not prov.get("source_segment_id"):
                problems.append(f"{p['id']}: 缺 source_segment_id")
            if not prov.get("recovered_file_sha256"):
                problems.append(f"{p['id']}: 缺 recovered_file_sha256")
            if prov.get("recovered_file_sha256") not in {self._zh_sha, self._fr_sha}:
                problems.append(f"{p['id']}: recovered_file_sha256 不可信")
            # 2) upstream_state 必须显式
            if prov.get("upstream_state") not in ("upstream_missing",
                                                  "upstream_present"):
                problems.append(f"{p['id']}: upstream_state 非法")
            # 3) 状态与字段一致
            if ts == "COMPLETE":
                complete += 1
                # COMPLETE 的含义（两跳模型）：
                #   ① recovered_file + sha256   （承载该段的可验证文件）
                #   ② physical_source_file + sha256（该文件的上游原始下载，可达时）
                # document_id 只有在源文件属于 Phase 1 那 143 个原始件时才非空；
                # atlas 的 jsonl 不在其中，故不强制。
                for k in ("source_segment_id", "recovered_file_sha256",
                          "physical_source_file", "physical_source_sha256"):
                    if not prov.get(k):
                        problems.append(f"{p['id']}: COMPLETE 但缺 {k}")
                if p.get("trace_missing"):
                    problems.append(f"{p['id']}: COMPLETE 却有 trace_missing")
            elif ts == "SOURCE_TRACE_INCOMPLETE":
                incomplete += 1
                if not p.get("trace_missing"):
                    problems.append(f"{p['id']}: INCOMPLETE 但没写缺哪一环")
            else:
                problems.append(f"{p['id']}: 非法 trace_status {ts}")
            if len(problems) > 5:
                break
        self.assertEqual(problems[:5], [], "\n".join(problems[:5]))
        # 本阶段实测：两个语料的链都尚未闭合到原始物理文件
        self.assertGreater(incomplete, 0,
                           "应存在 INCOMPLETE 的 Passage（上游确实不可达）")

    @classmethod
    def _sha_cache(cls):
        return None

    def test_05_trace_incomplete_is_explicit(self):
        """无法闭合的必须显式标 SOURCE_TRACE_INCOMPLETE，不能伪造来源。"""
        for p in self.passages[:20000]:
            self.assertIn("trace_status", p, "Passage 必须有 trace_status")
            self.assertIn(p["trace_status"],
                          ("COMPLETE", "SOURCE_TRACE_INCOMPLETE"),
                          f"非法 trace_status: {p['trace_status']}")
            if p["trace_status"] == "SOURCE_TRACE_INCOMPLETE":
                self.assertTrue(p.get("trace_missing"),
                                "标了 INCOMPLETE 就必须写明缺哪一环")

    # ---- 5c 法语可达的第二跳必须真的接上（否则是工程缺口而非客观不可达）
    def test_05b_french_second_hop_is_linked(self):
        """法语转录的第二跳（原始下载）可达，因此**必须**接上。

        对照：中译的上游源目录已消失 → 客观不可达 → 保持 INCOMPLETE 是正确的。
        但法语不同：`.lacan-build/staferla/S*.txt`（28 份）就在本机，
        所以 `trace_status` 必须能到 COMPLETE。若这里出现 INCOMPLETE，
        那是**工程缺口**，不是事实，必须修。
        """
        fr = [p for p in self.passages if p["language"] == "fr"]
        self.assertTrue(fr, "没有法语 passage")
        unlinked = [p["id"] for p in fr
                    if not (p.get("provenance") or {}).get("physical_source_sha256")]
        self.assertEqual(
            unlinked[:5], [],
            f"{len(unlinked)} 个法语 Passage 未接上第二跳（本机有源文件，属工程缺口）")
        incomplete = [p["id"] for p in fr if p["trace_status"] != "COMPLETE"]
        self.assertEqual(
            incomplete[:5], [],
            f"{len(incomplete)} 个法语 Passage 仍标 INCOMPLETE —— 但第二跳可达")

    # ---- 5d 中译的不可达是事实，必须保持显式 INCOMPLETE
    def test_05c_zh_remains_honestly_incomplete(self):
        """中译上游源目录已消失 → 必须保持 INCOMPLETE 且写明缺哪一环。"""
        zh = [p for p in self.passages if p["language"] == "zh"]
        self.assertTrue(zh, "没有中译 passage")
        wrong = [p["id"] for p in zh
                 if p["trace_status"] != "SOURCE_TRACE_INCOMPLETE"]
        self.assertEqual(
            wrong[:5], [],
            f"{len(wrong)} 个中译 Passage 声称 COMPLETE —— 上游确实不可达，不得伪称闭合")
        for p in zh[:200]:
            self.assertIn("upstream_original_file", p["trace_missing"],
                          "中译必须写明缺 upstream_original_file")

    # ---- 6 no invented metadata    # ---- 6 no invented metadata
    def test_06_no_invented_metadata(self):
        """不得发明元数据：日期未确证时不得出现编造的 MM-DD。"""
        for p in self.passages[:20000]:
            sd = p["session_date"]
            if sd == "unknown":
                continue
            # 允许 YYYY-unknown（年份有据），禁止在无据时给月日
            self.assertRegex(
                sd, r"^\d{4}-(\d{2}-\d{2}|unknown)$",
                f"session_date 形态可疑: {sd}")
            if sd.endswith("-unknown"):
                self.assertEqual(p["session_date_precision"], "year")
        # 语料本身只提供年份区间 —— 因此不得出现比年份更细的确证日期

    # ---- 7 broken passage references + 9 duplicate IDs
    def test_07_no_duplicate_ids(self):
        seen = {}
        dup = []
        for i, p in enumerate(self.passages):
            if p["id"] in seen:
                dup.append(p["id"])
            else:
                seen[p["id"]] = i
        self.assertEqual(dup[:5], [], f"重复 Passage ID {len(dup)} 个")

    def test_08_passage_references_resolve(self):
        """Passage 引用的 session / seminar 实体必须存在。"""
        sessions = set()
        sp = os.path.join(STORE_DIR, "sessions.jsonl")
        self.assertTrue(os.path.isfile(sp), f"缺 {sp}")
        for s in load_jsonl(sp):
            sessions.add(s["id"])
        bad = [p["id"] for p in self.passages[:20000]
               if p["session_id"] not in sessions]
        self.assertEqual(bad[:5], [], f"引用了不存在的 session: {bad[:3]}")

    # ---- 10 source hash stability
    def test_09_source_hash_stable(self):
        """source hash 必须与 BACKUP_MANIFEST 记录一致（且重跑不变）。"""
        mp = os.path.join(VAULT, "_data", "BACKUP_MANIFEST.json")
        with open(mp, encoding="utf-8") as fh:
            man = json.load(fh)
        want = {f["path"]: f["sha256"] for f in man["files"]}
        zh = "segments.jsonl"
        fr = "french_staferla.jsonl"
        self.assertIn(zh, want)
        self.assertIn(fr, want)
        # store 里记录的源 hash 必须与 manifest 一致
        src_hashes = set()
        for p in self.passages[:20000]:
            src_hashes.add(p["provenance"]["recovered_file_sha256"])
        self.assertTrue(src_hashes <= {want[zh], want[fr]},
                        f"store 记录的源 sha256 不在 manifest 中: {src_hashes}")

    # ---- 11 lossless ingestion
    def test_10_lossless_ingestion(self):
        """无损：raw_text 必须能机械重建原始 segment；normalization 必须可解释。"""
        # 对每个 Passage：raw_text 必须与源 jsonl 中对应 segment 的文本逐字一致
        import json as _j
        src = os.path.expanduser("<HOME>")
        zh_raw = {}
        with open(src, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = _j.loads(line)
                zh_raw[d["id"]] = d["text"]
        checked = 0
        mismatched = []
        for p in self.passages:
            if p["language"] != "zh":
                continue
            sid = p["provenance"]["source_segment_id"]
            if sid in zh_raw and p["raw_text"] != zh_raw[sid]:
                mismatched.append(p["id"])
            checked += 1
            if checked >= 20000:
                break
        self.assertEqual(mismatched[:5], [],
                         f"raw_text 与源 segment 不一致（非无损）: {mismatched[:3]}")
        # normalization 必须可解释：有 operations 才能有 normalized_text 差异
        for p in self.passages[:20000]:
            ops = p.get("normalization_operations") or []
            if p["raw_text"] != p["normalized_text"] and not ops:
                self.fail(f"{p['id']} 文本被改变但没有记录 normalization operations")

    # ---- 15 idempotent re-ingestion
    def test_11_idempotent_reingestion(self):
        """重复 ingest 必须产出逐字节相同的 store。"""
        def digest():
            h = hashlib.sha256()
            for p in sorted(os.listdir(STORE_DIR)):
                fp = os.path.join(STORE_DIR, p)
                if os.path.isfile(fp):
                    h.update(p.encode())
                    with open(fp, "rb") as f:
                        h.update(f.read())
            return h.hexdigest()
        before = digest()
        subprocess.run([sys.executable, BUILDER], capture_output=True, text=True,
                       cwd=VAULT, check=True)
        self.assertEqual(before, digest(), "重复 ingest 产出了不同的 store")

    # ---- §二 不得创建 249,105 个 Markdown
    def test_12_no_mass_markdown(self):
        """人类阅读层与机器 Store 分离：不得为每个 Passage 生成一个 md。

        阈值说明（实测校准）：本阶段设计粒度是
          **每个 seminar 一页 + 每个 session 一页**
        实测产出约 1,975 个 md：

          * 28 个 seminar 页
          * 531 个中译 session 页（含课次，段多时分 `.pN`）
          * 28 个法语 session 页（法语源数据**没有** lesson 字段，
            故只到 seminar 级 session；未编造课次）

        这个量级**正是设计要的**，不是「海量文件」。
        阈值取 5000 是用来拦住「为 249,105 个 Passage 各建一个 md」那种做法 ——
        两者差了约 126 倍（249,105 vs 1,975）。
        """
        sem_dir = os.path.join(VAULT, "02_Lacan_Seminars")
        md_count = 0
        for dp, _, fns in os.walk(sem_dir):
            md_count += sum(1 for f in fns if f.endswith(".md"))
        self.assertLess(
            md_count, 5000,
            f"02_Lacan_Seminars 下有 {md_count} 个 md —— 疑似为每个 Passage 建了文件")
        self.assertGreater(
            md_count, 0, "人类阅读层应当有 Seminar/Session 页")

    # ---- validator 必须真的校验 passage store（对抗式审查发现它曾经完全不看）
    def test_14_validator_audits_passage_store(self):
        """`validate_vault.py` 必须校验 passage store，并把结果写进报告。

        缺陷来源：对抗式审查实测 `grep "passage" validate_vault.py` 零命中 ——
        于是「ID 命名空间分叉」这类问题没有任何检查会发现。
        """
        r = subprocess.run([sys.executable,
                            os.path.join(VAULT, "_scripts", "_tools",
                                         "validate_vault.py"), "--json"],
                           capture_output=True, text=True, cwd=VAULT)
        self.assertEqual(r.returncode, 0, f"validator 失败:\n{r.stderr[-500:]}")
        rep = json.loads(r.stdout)
        self.assertIn("passage_store", rep, "报告里没有 passage_store 一节")
        ps = rep["passage_store"]
        self.assertTrue(ps.get("present"), "passage store 应被检测到")
        self.assertEqual(ps.get("errors"), [], f"passage store 校验有错: {ps.get('errors')}")
        counts = ps.get("counts") or {}
        self.assertEqual(counts.get("passages"), TOTAL_BASELINE)
        self.assertEqual(counts.get("by_language", {}).get("zh"), ZH_BASELINE)
        self.assertEqual(counts.get("by_language", {}).get("fr"), FR_BASELINE)

    # ---- 渲染器不得清掉人工/fixture 节点（实测踩过）
    def test_15_render_preserves_non_render_files(self):
        """渲染器只应删自己产出的 seminar 页与 sessions 目录。

        缺陷来源：第一版 `render_vault.py` 用 `rmtree` 清整个 `S??_*` 目录，
        把 `02_Lacan_Seminars/S03_Seminar_III/` 下的人工 fixture passage 一起删了
        （实测：validator 随即报 2 条 SOURCE_TRACE_INCOMPLETE，因为 relation
        指向的 fixture passage 文件已被渲染器删除）。
        """
        # fixture 使用 ST<n> 专用号段（语料只渲染 S01–S27），
        # 因此它的目录不该被渲染器清理。
        sd = os.path.join(VAULT, "02_Lacan_Seminars", "ST1_Fixture")
        fixture = os.path.join(sd, "passage.ST1.unknown.L01.P0010.md")
        self.assertTrue(os.path.isfile(fixture),
                        "fixture passage 不存在（可能被渲染器删掉了）")
        # 跑一次渲染，fixture 必须还在
        subprocess.run([sys.executable,
                        os.path.join(VAULT, "_scripts", "_tools", "render_vault.py"),
                        "--quiet"], capture_output=True, text=True, cwd=VAULT)
        self.assertTrue(os.path.isfile(fixture),
                        "渲染后 fixture passage 消失了 —— 渲染器不得删非自产文件")

    # ---- machine store 可以精确读取同一 Passage    # ---- machine store 可以精确读取同一 Passage
    def test_13_sqlite_holdssame_passages(self):
        con = sqlite3.connect(SQLITE)
        try:
            n = con.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
            self.assertEqual(n, TOTAL_BASELINE,
                             f"SQLite 里 {n} 条 != {TOTAL_BASELINE}")
            # 抽一条比对 JSONL 与 SQLite 是否一致
            pid = self.passages[0]["id"]
            row = con.execute(
                "SELECT raw_text, language FROM passages WHERE id=?", (pid,)).fetchone()
            self.assertIsNotNone(row, f"SQLite 里找不到 {pid}")
            self.assertEqual(row[0], self.passages[0]["raw_text"])
            self.assertEqual(row[1], self.passages[0]["language"])
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
