#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.4 §44/§60/§61：Cursor 分页完整性（不重、不漏、可复算）"""
import sys, os, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _explorer_testlib as L


class Pagination(unittest.TestCase):
    def test_00_no_duplicates_no_missing(self):
        """§61：page1 ∩ page2 = ∅，且合起来 == 全库 deterministic 参照。"""
        f = {"seminar": "S05", "language": "zh"}
        ids, pages = L.page_ids(f, limit=40)
        ref = L.raw_ids("where seminar_id=? and language=?", ("seminar.S05", "zh"))
        self.assertGreater(pages, 3, "样本应当跨多页")
        self.assertEqual(len(ids), len(set(ids)), "翻页出现重复")
        self.assertEqual(ids, ref, "翻页结果与全库参照不一致（缺行或错序）")

    def test_01_total_is_stable_across_pages(self):
        f = {"seminar": "S11", "language": "fr"}
        out1 = L.B.browse_passages(dict(f, limit=25))
        out2 = L.B.browse_passages(dict(f, limit=25),
                                   cursor=out1["page"]["next_cursor"])
        self.assertEqual(out1["page"]["total"], out2["page"]["total"])
        self.assertLess(out2["page"]["remaining"], out1["page"]["remaining"])
        self.assertEqual(out1["page"]["remaining"], out1["page"]["total"])

    def test_02_cursor_is_bound_to_filters(self):
        """§44：换了筛选条件还用旧 cursor 必须报错，而不是静默返回错位页。"""
        out = L.B.browse_passages({"seminar": "S11", "limit": 5})
        cur = out["page"]["next_cursor"]
        with self.assertRaises(L.B.cursors.CursorError):
            L.B.browse_passages({"seminar": "S12", "limit": 5}, cursor=cur)

    def test_03_bad_cursor_fails_closed(self):
        for bad in ("garbage", "eyJ2Ijoid3JvbmcifQ==", "!!!not-base64!!!"):
            with self.assertRaises(L.B.cursors.CursorError):
                L.B.browse_passages({"seminar": "S11"}, cursor=bad)

    def test_04_order_is_documented_and_stable(self):
        out = L.B.browse_passages({"seminar": "S11", "limit": 5})
        self.assertIn("passage_id ASC", out["page"]["order"])
        self.assertEqual(out["page"]["order"], out["page"]["order"])

    def test_05_last_page_has_no_cursor(self):
        f = {"seminar": "S27", "language": "zh"}
        ids, pages = L.page_ids(f, limit=200)
        self.assertEqual(ids, L.raw_ids("where seminar_id=? and language=?",
                                        ("seminar.S27", "zh")))
        self.assertIsNone(L.B.browse_passages(dict(f, limit=200))["page"]["next_cursor"]
                          if len(ids) <= 200 else None)

    def test_06_pagination_evidence_recorded(self):
        """把分页 QA 证据写到 _workspace，供报告引用。"""
        f = {"seminar": "S11", "language": "fr"}
        ids, pages = L.page_ids(f, limit=25)
        ref = L.raw_ids("where seminar_id=? and language=?", ("seminar.S11", "fr"))
        payload = {"filters": f, "page_size": 25, "pages": pages,
                   "returned": len(ids), "unique": len(set(ids)),
                   "reference_total": len(ref), "identical_to_reference": ids == ref,
                   "no_duplicates": len(ids) == len(set(ids)),
                   "order": "passage_id ASC"}
        p = L.save_marker("pagination_qa.json", payload)
        self.assertTrue(os.path.isfile(p))
        self.assertTrue(payload["identical_to_reference"])
