#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_inventory.py — inventory 引擎的 red/green 测试

先写测试、看它 fail，再让 inventory_corpus.py 去满足它。
测试用「合成语料」而不是真实语料：真实语料会变，契约不该随它变。

运行:
  python3 -m unittest discover -s . -p "test_*.py" -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.join(HERE, "inventory_corpus.py")
sys.path.insert(0, HERE)
from inventory_corpus import classify_source_type  # noqa: E402


# ---------------------------------------------------------------- 合成语料
def build_fixture_corpus(root):
    """构造一个最小的、覆盖各分支的语料树。只写临时目录，不碰真实源。"""
    os.makedirs(os.path.join(root, "研讨班"), exist_ok=True)
    os.makedirs(os.path.join(root, "拉康派相关书籍"), exist_ok=True)
    os.makedirs(os.path.join(root, "图片"), exist_ok=True)

    zh = "拉康认为无意识像语言一样被结构。能指链条决定主体。"
    fr = "L'inconscient est structuré comme un langage. Le désir est l'effet de la demande."
    en = "The unconscious is structured like a language for the subject of the signifier."

    # 中文文本文件（也用于 sha256 重复检测）
    with open(os.path.join(root, "拉康派相关书籍", "笔记-中文.txt"), "w", encoding="utf-8") as f:
        f.write(zh * 40)
    # 与上者字节完全相同 → 必须被识别为 IDENTICAL_CONTENT
    with open(os.path.join(root, "拉康派相关书籍", "笔记-中文-副本.txt"), "w", encoding="utf-8") as f:
        f.write(zh * 40)
    # 法文
    with open(os.path.join(root, "研讨班", "S3 PSYCHOSES extrait.txt"), "w", encoding="utf-8") as f:
        f.write(fr * 40)
    # 英文，文件名带研讨班期号
    with open(os.path.join(root, "研讨班", "Seminar X anxiety.txt"), "w", encoding="utf-8") as f:
        f.write(en * 40)
    # 同名不同字节 → SAME_NAME_DIFFERENT_BYTES
    with open(os.path.join(root, "研讨班", "同名.txt"), "w", encoding="utf-8") as f:
        f.write("版本甲 " + zh * 10)
    with open(os.path.join(root, "研讨班", "同名(1).txt"), "w", encoding="utf-8") as f:
        f.write("版本乙 " + zh * 12)
    # 分卷 → SAME_BOOK_SPLIT_PARTS
    for part, pages in ((1, (1, 104)), (2, (105, 207))):
        with open(
            os.path.join(root, "拉康派相关书籍",
                         f"Lacan on Psychosis-part-{part:02d}-pages-{pages[0]}-{pages[1]}.txt"),
            "w", encoding="utf-8",
        ) as f:
            f.write(en * 20)
    # 零字节
    open(os.path.join(root, "研讨班", "空文件.txt"), "w").close()
    # 不支持格式
    with open(os.path.join(root, "研讨班", "data.bin"), "wb") as f:
        f.write(b"\x00\x01\x02\x03")
    # 最小 docx（zip 容器）
    _write_min_docx(os.path.join(root, "拉康派相关书籍", "导读拉康.docx"),
                    "导读拉康 " + zh * 20)
    # 最小 png（1x1）
    with open(os.path.join(root, "图片", "示意图.png"), "wb") as f:
        f.write(bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000a49444154789c63000100000500010d0a2db4"))
    # 必须被忽略
    with open(os.path.join(root, ".DS_Store"), "wb") as f:
        f.write(b"\x00" * 32)
    return root


def _write_min_docx(path, text):
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          "</Types>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>")
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
           "</w:body></w:document>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)


# ---------------------------------------------------------------- 测试
class InventoryRedGreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lkos-inv-")
        cls.src = os.path.join(cls.tmp, "source")
        cls.out = os.path.join(cls.tmp, "out")
        os.makedirs(cls.src, exist_ok=True)
        build_fixture_corpus(cls.src)
        cls.proc = subprocess.run(
            [sys.executable, INV, "--source", cls.src, "--out", cls.out],
            capture_output=True, text=True,
        )
        cls.json_path = os.path.join(cls.out, "corpus_inventory.json")
        cls.csv_path = os.path.join(cls.out, "corpus_inventory.csv")
        cls.md_path = os.path.join(cls.out, "corpus_report.md")
        cls.data = None
        if os.path.exists(cls.json_path):
            with open(cls.json_path, encoding="utf-8") as f:
                cls.data = json.load(f)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- 契约 0: 脚本能跑
    def test_00_script_exits_zero(self):
        self.assertEqual(
            self.proc.returncode, 0,
            f"inventory 脚本退出码非 0\nSTDOUT:{self.proc.stdout}\nSTDERR:{self.proc.stderr}",
        )

    # ---- 契约 1: 三份产出都存在
    def test_01_three_outputs_exist(self):
        for p in (self.json_path, self.csv_path, self.md_path):
            with self.subTest(path=p):
                self.assertTrue(os.path.exists(p), f"缺少产出文件 {p}")
                self.assertGreater(os.path.getsize(p), 0, f"{p} 为空")

    # ---- 契约 2: JSON 结构
    def test_02_json_schema_shape(self):
        d = self.data
        for key in ("schema", "generated_at", "source_root", "totals", "records",
                    "duplicate_groups", "anomalies", "by_extension", "by_parse_status",
                    "by_language", "by_source_type", "toolchain"):
            with self.subTest(key=key):
                self.assertIn(key, d, f"JSON 缺少顶层字段 {key}")
        self.assertTrue(d["source_readonly"] is True, "必须声明 source_readonly=True")
        self.assertEqual(d["source_root"], os.path.realpath(self.src))

    # ---- 契约 3: 每个 record 必备字段
    REQUIRED_RECORD_FIELDS = [
        "rel_path", "path", "filename", "extension", "size", "sha256",
        "estimated_language", "possible_author", "possible_title",
        "source_type", "parse_status", "duplicate_group", "is_duplicate",
    ]

    def test_03_record_required_fields(self):
        self.assertTrue(self.data["records"], "records 为空")
        for r in self.data["records"]:
            for k in self.REQUIRED_RECORD_FIELDS:
                with self.subTest(rel=r["rel_path"], field=k):
                    self.assertIn(k, r, f"{r['rel_path']} 缺字段 {k}")

    # ---- 契约 4: 隐藏垃圾文件被忽略
    def test_04_ignores_ds_store(self):
        paths = [r["rel_path"] for r in self.data["records"]]
        self.assertNotIn(".DS_Store", paths, ".DS_Store 不应进入 inventory")
        self.assertFalse(any(p.startswith("._") for p in paths), "AppleDouble 不应进入 inventory")
        self.assertEqual(len(paths), len(set(paths)), "rel_path 必须唯一")

    # ---- 契约 5: sha256 正确
    def test_05_sha256_matches(self):
        import hashlib
        for r in self.data["records"]:
            with self.subTest(rel=r["rel_path"]):
                with open(r["path"], "rb") as f:
                    expect = hashlib.sha256(f.read()).hexdigest()
                self.assertEqual(r["sha256"], expect)

    # ---- 契约 6: 重复检测
    def test_06_identical_content_detected(self):
        kinds = {g["kind"] for g in self.data["duplicate_groups"]}
        self.assertIn("IDENTICAL_CONTENT", kinds, "字节级重复未被检出")
        ident = [g for g in self.data["duplicate_groups"] if g["kind"] == "IDENTICAL_CONTENT"]
        members = set()
        for g in ident:
            members.update(g["members"])
        self.assertIn(os.path.join("拉康派相关书籍", "笔记-中文.txt"), members)
        self.assertIn(os.path.join("拉康派相关书籍", "笔记-中文-副本.txt"), members)

    def test_07_split_parts_detected(self):
        kinds = {g["kind"] for g in self.data["duplicate_groups"]}
        self.assertIn("SAME_BOOK_SPLIT_PARTS", kinds, "同书分卷未被检出")

    def test_08_duplicate_never_deletes(self):
        """硬约束：重复只标记，源文件必须全部还在。"""
        allowed_actions = {
            "KEEP_ALL_DO_NOT_DELETE (用户明确要求不删除重复)",
            "REVIEW_MANUALLY",
            "MERGE_AT_DOCUMENT_LEVEL (物理文件保持不动)",
        }
        for g in self.data["duplicate_groups"]:
            for m in g["members"]:
                with self.subTest(member=m):
                    self.assertTrue(os.path.exists(os.path.join(self.src, m)),
                                    f"源文件被改动了: {m}")
            self.assertIn(g["action"], allowed_actions,
                          f"未知处置动作（必须是非破坏性的）: {g['action']}")

    # ---- 契约 9: 语言判定
    def test_09_language_detection(self):
        by_rel = {r["rel_path"]: r for r in self.data["records"]}
        cases = [
            (os.path.join("拉康派相关书籍", "笔记-中文.txt"), "zh"),
            (os.path.join("研讨班", "S3 PSYCHOSES extrait.txt"), "fr"),
            (os.path.join("研讨班", "Seminar X anxiety.txt"), "en"),
        ]
        for rel, expect in cases:
            with self.subTest(rel=rel):
                self.assertIn(rel, by_rel, f"{rel} 未入库")
                self.assertEqual(by_rel[rel]["estimated_language"], expect,
                                 f"{rel} 语言判定错误")

    # ---- 契约 10: 研讨班期号识别
    def test_10_seminar_number_parsed(self):
        by_rel = {r["rel_path"]: r for r in self.data["records"]}
        s3 = by_rel.get(os.path.join("研讨班", "S3 PSYCHOSES extrait.txt"))
        self.assertIsNotNone(s3)
        self.assertEqual(s3["seminar_number"], 3)
        sx = by_rel.get(os.path.join("研讨班", "Seminar X anxiety.txt"))
        self.assertEqual(sx["seminar_number"], 10, "罗马数字 X 应解析为 10")

    # ---- 契约 11: parse_status 语义
    def test_11_parse_status_semantics(self):
        by_rel = {r["rel_path"]: r for r in self.data["records"]}
        self.assertEqual(by_rel[os.path.join("研讨班", "空文件.txt")]["parse_status"],
                         "EMPTY_TEXT")
        self.assertEqual(by_rel[os.path.join("研讨班", "data.bin")]["parse_status"],
                         "UNSUPPORTED_FORMAT")
        self.assertEqual(by_rel[os.path.join("图片", "示意图.png")]["parse_status"],
                         "IMAGE_NO_TEXT")

    # ---- 契约 12: docx 抽取
    def test_12_docx_text_extracted(self):
        r = next(x for x in self.data["records"]
                 if x["filename"] == "导读拉康.docx")
        self.assertTrue(r["parse_status"].startswith("PARSED"),
                        f"docx 解析失败: {r['parse_status']} {r.get('format_meta')}")
        self.assertEqual(r["estimated_language"], "zh")
        self.assertGreater(r["text_chars_sampled"], 100)

    # ---- 契约 13: 源类型分类
    def test_13_source_type_classification(self):
        by_rel = {r["rel_path"]: r for r in self.data["records"]}
        self.assertEqual(by_rel[os.path.join("研讨班", "S3 PSYCHOSES extrait.txt")]["source_type"],
                         "seminar_primary")
        self.assertEqual(by_rel[os.path.join("图片", "示意图.png")]["source_type"],
                         "image_asset")

    # ---- 契约 14: 异常收集
    def test_14_anomalies_collected(self):
        kinds = {a["kind"] for a in self.data["anomalies"]}
        self.assertIn("ZERO_BYTE", kinds, "零字节文件未报异常")
        self.assertIn("UNSUPPORTED_FORMAT", kinds, "不支持格式未报异常")
        for a in self.data["anomalies"]:
            with self.subTest(kind=a["kind"]):
                self.assertIn("rel_path", a)
                self.assertIn("detail", a)

    # ---- 契约 15: CSV 可读且行数一致
    def test_15_csv_roundtrip(self):
        import csv as _csv
        with open(self.csv_path, encoding="utf-8-sig") as f:
            rows = list(_csv.DictReader(f))
        self.assertEqual(len(rows), len(self.data["records"]),
                         "CSV 行数与 JSON records 数不一致")
        for r in rows:
            with self.subTest(rel=r["rel_path"]):
                self.assertTrue(r["sha256"], "CSV sha256 为空")
                self.assertTrue(r["rel_path"])

    # ---- 契约 16: 报告内容
    def test_16_report_content(self):
        with open(self.md_path, encoding="utf-8") as f:
            txt = f.read()
        for needle in ("Corpus Inventory Report", "只读扫描", "重复检测",
                       "研讨班覆盖率矩阵", "Source Authority"):
            with self.subTest(needle=needle):
                self.assertIn(needle, txt, f"报告缺少小节: {needle}")
        self.assertIn(str(len(self.data["records"])), txt, "报告未写入文件总数")

    # ---- 契约 17: 幂等性（除 generated_at）
    def test_17_idempotent(self):
        out2 = os.path.join(self.tmp, "out2")
        subprocess.run([sys.executable, INV, "--source", self.src, "--out", out2],
                       capture_output=True, text=True, check=True)
        with open(os.path.join(out2, "corpus_inventory.json"), encoding="utf-8") as f:
            d2 = json.load(f)
        a = dict(self.data); b = dict(d2)
        a.pop("generated_at"); b.pop("generated_at")
        self.assertEqual(json.dumps(a, sort_keys=True, ensure_ascii=False),
                         json.dumps(b, sort_keys=True, ensure_ascii=False),
                         "重复运行结果不一致（非幂等）")

    # ---- 契约 18: 绝不写源目录
    def test_18_source_untouched(self):
        before = {}
        for dirpath, _, names in os.walk(self.src):
            for n in names:
                fp = os.path.join(dirpath, n)
                before[fp] = os.stat(fp).st_mtime_ns
        subprocess.run([sys.executable, INV, "--source", self.src,
                        "--out", os.path.join(self.tmp, "out3")],
                       capture_output=True, text=True, check=True)
        after = {}
        for dirpath, _, names in os.walk(self.src):
            for n in names:
                fp = os.path.join(dirpath, n)
                after[fp] = os.stat(fp).st_mtime_ns
        self.assertEqual(before, after, "源目录被修改了（mtime 变化）")

    # ---- 契约 24: 不得记录 python-docx 合成的「假」元数据（幂等性根因）
    def test_24_no_synthesized_docx_timestamps(self):
        """缺 docProps/core.xml 的 docx，不得记录 created/modified。

        回归来源：幂等性测试在真实语料上偶发失败（两次运行差 1 秒）。
        根因是 python-docx 在 docx **没有** `docProps/core.xml` 时
        **动态合成** `created`/`modified`（用当前时间），于是：
          ① 同一文件两次扫描结果不同 → 破坏幂等性契约；
          ② 更糟的是**不诚实** —— 那个时间描述的是「扫描时刻」，
             不是文档的任何真实属性，却被记成 `docx_meta.modified`。
        处置：只在 zip 里真的存在 `docProps/core.xml` 时才记录这些字段。
        """
        import zipfile
        recs = {r["filename"]: r for r in self.data["records"]}
        r = recs.get("导读拉康.docx")
        self.assertIsNotNone(r, "fixture 里应有 导读拉康.docx")
        with zipfile.ZipFile(os.path.join(self.src, "拉康派相关书籍", "导读拉康.docx")) as z:
            has_core = any(n.endswith("core.xml") for n in z.namelist())
        meta = (r.get("format_meta") or {}).get("docx_meta") or {}
        with self.subTest(has_core_xml=has_core):
            if has_core:
                self.assertTrue(meta, "有 core.xml 时应记录 docx_meta")
            else:
                self.assertEqual(
                    meta, {},
                    f"docx 无 core.xml，却记录了合成元数据: {meta}")

    # ---- 契约 23: 期号识别不得被书名里的罗马数字劫持（回归）
    def test_23_seminar_number_not_hijacked_by_book_title(self):
        """文件名里已经有明确的「23期」时，不得被书名 "Book X" 劫持成 S10。

        回归来源：对抗式审查在真实语料里发现
        `研讨班/圣状 The Sinthome-…The Seminar of Jacques Lacan, Book X (Z-lib.io).pdf`
        被解析成 `seminar_number = 10`（抓到了 "Book X"），
        而它其实是 **S23**（同组 sha256 副本的另外两个文件名都写着「23期」）。
        后果：`corpus_report.md` 的研讨班覆盖率矩阵多出一个假 S10，
        而真实的 S23 少一个文件。
        """
        from inventory_corpus import parse_filename
        cases = [
            ("圣状 The Sinthome-拉康第二十三期研讨班-中英对照版 "
             "The Sinthome_ The Seminar of Jacques Lacan, Book X (Z-lib.io)",
             23),
            ("【中英】23圣状 The Sinthome-拉康第二十三期研讨班-中英对照版", 23),
            ("拉康研讨班20期中英对照", 20),
            ("Seminar X anxiety", 10),
            ("研讨班01期中文文字版", 1),
        ]
        for stem, expect in cases:
            with self.subTest(stem=stem[:48]):
                got = parse_filename(stem)["seminar_number"]
                self.assertEqual(
                    got, expect,
                    f"{stem[:60]}… 解析为 S{got}，应为 S{expect}")

    # ---- 契约 21: 用户明确要求的字段一个都不能少（JSON 与 CSV 两处）
    USER_REQUIRED_FIELDS = [
        "path", "filename", "extension", "size", "sha256",
        "estimated_language", "possible_author", "possible_title",
        "source_type", "duplicate_group", "parse_status",
    ]

    def test_21_user_required_fields_present_in_both_outputs(self):
        """brief 里逐条点名的 inventory 字段，JSON 与 CSV 都必须有。

        回归来源：第一版 CSV 只有 `rel_path`，没有 brief 明确要求的 `path`。
        """
        import csv as _csv
        rec = self.data["records"][0]
        with open(self.csv_path, encoding="utf-8-sig") as fh:
            header = next(_csv.reader(fh))
        missing_json = [f for f in self.USER_REQUIRED_FIELDS if f not in rec]
        missing_csv = [f for f in self.USER_REQUIRED_FIELDS if f not in header]
        self.assertEqual(missing_json, [], f"JSON record 缺字段: {missing_json}")
        self.assertEqual(missing_csv, [], f"CSV 缺字段: {missing_csv}")

    def test_22_document_id_bridges_duplicates_and_split_parts(self):
        """逻辑 document_id：重复组与同书分卷必须落到同一个 document_id。

        这是 inventory 与 vault 的 `document` 层之间的桥。没有它，
        「4 组字节级重复 + 5 组同书分卷」只是报告里的一段文字，下游无法机械消费。
        """
        recs = self.data["records"]
        by_rel = {r["rel_path"]: r for r in recs}
        # 1) 每个 record 都有 document_id，且形态合法
        for r in recs:
            with self.subTest(rel=r["rel_path"]):
                self.assertIn("document_id", r, "record 缺 document_id")
                self.assertRegex(r["document_id"], r"^doc\.[a-z0-9][a-z0-9.\-]*$")

        # 2) 分卷必须合并到同一 document_id
        parts = [r for r in recs if r.get("split_part")]
        self.assertGreaterEqual(len(parts), 2, "样本里没有分卷，无法验证合并")
        groups = {}
        for r in parts:
            base = r["filename"].split("-part-")[0]
            groups.setdefault(base, set()).add(r["document_id"])
        for base, ids in groups.items():
            with self.subTest(book=base):
                self.assertEqual(len(ids), 1,
                                 f"分卷 {base} 未合并为单一 document_id: {ids}")

        # 3) 字节级重复也必须合并到同一 document_id
        for g in self.data["duplicate_groups"]:
            if g["kind"] != "IDENTICAL_CONTENT":
                continue
            ids = {by_rel[m]["document_id"] for m in g["members"] if m in by_rel}
            with self.subTest(group=g["group_id"]):
                self.assertEqual(len(ids), 1,
                                 f"字节级重复 {g['group_id']} 的 document_id 不统一: {ids}")

    # ---- 契约 19: 目录语义分类必须可达（回归：曾全部落进 unknown）
    def test_19_directory_classification_reachable(self):
        """真实语料里的顶层目录语义必须被识别，unknown 不能吞掉整类资料。"""
        cases = [
            (["拉康派相关书籍"], ".pdf", "secondary_book"),
            (["拉康派精神病相关文献"], ".pdf", "secondary_source"),
            (["拉康派精神病相关文献"], ".docx", "research_note"),
            (["拉康派关于日常精神病的文献和想法记录"], ".docx", "research_note"),
            (["拉康派关于日常精神病的文献和想法记录", "原版文本文献"], ".pdf",
             "secondary_source"),
            (["卡特尔小组会议文档"], ".docx", "case_meeting"),
            (["研讨班"], ".pdf", "seminar_primary"),
            (["图片"], ".png", "image_asset"),
        ]
        for parts, ext, expect in cases:
            with self.subTest(parts=parts, ext=ext):
                got = classify_source_type(parts, ext, None, "文件")
                self.assertEqual(got, expect,
                                 f"{parts}/{ext} 分类为 {got}，应为 {expect}")

    def test_20_unknown_source_type_is_rare(self):
        """unknown 分类必须是小尾巴，不能吞掉主要资料类目。"""
        n = len(self.data["records"])
        n_unknown = self.data["by_source_type"].get("unknown", 0)
        self.assertLessEqual(
            n_unknown / max(n, 1), 0.10,
            f"unknown 占比 {n_unknown}/{n} 过高 —— 目录语义分类失效",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
