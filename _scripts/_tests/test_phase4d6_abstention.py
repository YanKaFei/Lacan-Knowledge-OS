#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4D.6 §9/§74：ABSTAIN 导出（四格式保持，禁止补答）"""
import os, sys, unittest
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0,VAULT); sys.path.insert(0,HERE)
import _export_testlib as L
import export_system as EX


class AbstentionExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.view = L.abstention_view()
        cls.doc = EX.build_from_answer(cls.view)

    def test_00_state_preserved(self):
        self.assertEqual(self.doc["answer_state"], "ABSTAINED")
        self.assertTrue(self.doc["abstention"])
        self.assertEqual(self.doc["abstention"]["title"],
                         "Current corpus cannot support a reliable answer")

    def test_01_all_formats_keep_abstention(self):
        texts = L.rendered(self.doc)
        texts["bundle"] = "".join(
            blob.decode("utf-8") for _rel, blob in
            EX.bundle.build_files(self.doc)[0])
        for fmt, text in texts.items():
            self.assertIn("Current corpus cannot support a reliable answer", text, fmt)
            self.assertIn("ABSTAINED", text, fmt)

    def test_02_missing_information_present(self):
        ab = self.doc["abstention"]
        self.assertTrue(ab.get("missing_information"))
        md = EX.markdown.render(self.doc)
        self.assertIn("Missing information", md)
        self.assertIn(str(ab["missing_information"][0])[:20], md)

    def test_03_no_general_knowledge_answer_appended(self):
        """§74：禁止补一段 general knowledge。"""
        blob = " ".join(L.rendered(self.doc).values())
        for bad in ("however", "generally speaking", "in general", "补充说明",
                    "众所周知"):
            self.assertNotIn(bad, blob.lower().replace("however, the corpus", ""), bad)

    def test_04_abstention_keeps_core_claims_verbatim(self):
        """弃权答案里核心自己给出的 claim（如 CORPUS_ABSENCE）必须**逐字保留**，
        但绝不能出现「补出来的答案性 claim」。"""
        src = [c["claim_text"] for c in self.view["claims"]]
        got = [c["claim_text"] for c in self.doc["claims"]]
        self.assertEqual(got, src)
        self.assertEqual(self.doc["citations"], [])
        for c in self.doc["claims"]:
            self.assertIn(c["claim_type"], ("CORPUS_ABSENCE", "METADATA_ABSENCE",
                                            "TOPIC_NOT_COVERED", "LIMITATION"))

    def test_05_sections_verbatim_and_marked(self):
        """§6：段落逐字导出（弃权时它们说明为什么无法回答），不得改写成结论。

        ★ Phase 5A（P5A-001）追加：默认导出的 `sections` 是**用户可见面**；
          被划到审计面的校验器诊断**不得丢失** —— 必须能从 audit 视图取回。
        """
        src = [s["text"] for s in self.view["sections"]]
        got = [s["text"] for s in self.doc["sections"]]
        self.assertEqual(got, src)
        md = EX.markdown.render(self.doc)
        self.assertIn("ABSTAINED", md)
        self.assertIn("Current corpus cannot support a reliable answer", md)
        from workspace_ui.server import presentation as PZ
        payload = ((self.view.get("raw") or {}).get("scholarly_payload")) or {}
        av = PZ.audit_view(payload)
        self.assertTrue(PZ.audit_available(payload),
                        "被划走的诊断必须在 audit 面可取（移走≠删除）")
        if av.get("derived_from_legacy"):
            # legacy（v1 载荷）：内容以文本形式被路由 → 必须能逐段取回
            retrieved = {x.get("section") for x in (av.get("legacy_routed_text") or [])}
            for r in (av.get("routed_sections") or []):
                self.assertIn(r.get("section"), retrieved,
                              "audit 面未能取回被划走的段落 %s" % r.get("section"))
        else:
            # 结构化（v1.1 载荷）：诊断仍**留在载荷里**，由 audit 面暴露
            self.assertTrue(isinstance(payload.get("audit_diagnostics"), dict)
                            and payload["audit_diagnostics"],
                            "结构化载荷必须保留 audit_diagnostics")
        # 用户可见面里不得再出现内部诊断特征
        self.assertEqual(PZ.scan_user_facing_internal_diagnostics(payload), [])

    def test_06_bundle_of_abstention_verifies(self):
        with L.export_root("abst"):
            out = EX.build_bundle(self.doc)
            self.assertEqual(out["verify"]["status"], "VERIFIED")
            self.assertEqual(out["counts"]["passages"], 0)
