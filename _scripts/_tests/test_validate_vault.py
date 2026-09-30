#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_validate_vault.py — 脚手架层（schema / 模板 / 校验工具）的 red/green 测试

测试原则：用合成 vault（临时目录），不碰真实 vault 内容。
真实 vault 里会有别的 agent 正在写的节点，契约不该随它漂移。

覆盖的契约（全部有真源）：
  * 00_System/Schemas/knowledge.schema.json   —— 实体 frontmatter
  * 00_System/Schemas/relation.schema.json    —— 关系记录（实现 RELATION_MODEL.md §2–§4）
  * 00_System/Schemas/id-namespaces.json      —— namespace 唯一真源
  * ENTITY_MODEL.md §2/§5/§8、RELATION_MODEL.md §1/§4/§5/§6 —— 校验器规则

运行:
  cd <vault-root>
  python3 -m unittest discover -s _scripts/_tests -p "test_validate_vault.py" -v
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import jsonschema
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
TOOLS = os.path.join(SCRIPTS, "_tools")
VAULT = os.path.dirname(SCRIPTS)

sys.path.insert(0, TOOLS)

import validate_vault as VV  # noqa: E402
import make_index as MI  # noqa: E402

SCHEMA_DIR = os.path.join(VAULT, "00_System", "Schemas")
KNOWLEDGE_SCHEMA = os.path.join(SCHEMA_DIR, "knowledge.schema.json")
RELATION_SCHEMA = os.path.join(SCHEMA_DIR, "relation.schema.json")
ID_NAMESPACES = os.path.join(SCHEMA_DIR, "id-namespaces.json")
TEMPLATES = os.path.join(VAULT, "00_System", "Templates")
VALIDATE = os.path.join(TOOLS, "validate_vault.py")
MAKE_INDEX = os.path.join(TOOLS, "make_index.py")

# 定稿的 namespace 表（ENTITY_MODEL.md §3 + 脚手架收敛结论）
EXPECTED_NAMESPACES = {
    "source": "source", "document": "doc", "seminar": "seminar", "session": "session",
    "passage": "passage", "concept": "concept", "concept_state": "state",
    "term": "term", "translation": "trans", "person": "person",
    "philosopher": "philosopher", "psychoanalyst": "person", "case": "case",
    "clinical_structure": "structure", "matheme": "matheme", "topology": "topology",
    "formula": "formula", "discourse": "discourse", "school": "school",
    "debate": "debate", "reading_note": "note", "synthesis": "synth",
    "question": "q", "research_project": "project",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ================================================================ 合成 vault
def base_front(**over):
    """13 个 required 字段齐全的最小合法 frontmatter。"""
    f = {
        "id": "concept.objet-petit-a",
        "type": "concept",
        "title": "对象小a",
        "canonical_name": "objet petit a",
        "aliases": ["对象a"],
        "language": "zh",
        "authority_level": "L3",
        "review_status": "candidate",
        "status": "stub",
        "generated_by": "human:tester",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "schema_version": "1.0.0",
    }
    f.update(over)
    return f


def write_note(root, relpath, front, body=""):
    """写节点。约定 relpath 的文件名 == front["id"]（硬规则，除非测试故意违反）。"""
    path = os.path.join(root, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = "---\n" + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + "---\n\n" + body
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def write_relation(root, name, records):
    d = os.path.join(root, "_data", "relations")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def valid_relation(**over):
    """主库（relations.jsonl）里一条合法的、已审核的关系。"""
    r = {
        "relation_id": "rel.000001",
        "subject": "concept.objet-petit-a",
        "predicate": "defines",
        "object": "state.objet-petit-a.1959-1963",
        "evidence": {
            "passage_id": ["passage.S7.1959-12-02.P012"],
            "assertion_type": "explicit",
            "quote": "l'objet petit a",
            "edition": "Seuil 1973",
        },
        "confidence": 0.9,
        "review_status": "reviewed",
        "authority_level": "L1",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "created_by": "human:tester",
        "schema_version": "1.0.0",
    }
    r.update(over)
    return r


def build_fixture_vault(root, include_broken=True):
    """最小但有意义的 vault：concept × 2、state、seminar、passage、2 条关系。"""
    write_note(root, "00_System/Templates/nav-sample.md", base_front(), "系统目录应被跳过")
    write_note(root, "_index/Reports/nav-sample.md", base_front(), "报告目录应被跳过")
    with open(os.path.join(root, "_index.md"), "w", encoding="utf-8") as f:
        f.write("# 根导航页，无 frontmatter，应被跳过\n")

    write_note(
        root, "04_Concepts/concept.objet-petit-a.md",
        base_front(
            id="concept.objet-petit-a",
            concept_states=["state.objet-petit-a.1959-1963"],
        ),
        body="概念本体不承载定义。\n\n- [[state.objet-petit-a.1959-1963|1959–1963]]\n"
             "- [[concept.grand-autre#注释]]\n"
             "- [[大彼者|按别名命中]]\n"
             + ("- [[concept.bu-cun-zai-de-dongxi]]\n" if include_broken else ""),
    )
    write_note(
        root, "04_Concepts/concept.grand-autre.md",
        base_front(id="concept.grand-autre", title="大他者",
                   canonical_name="grand Autre", aliases=["大彼者"], concept_states=[]),
        body="见 [[concept.objet-petit-a]]。\n",
    )
    write_note(
        root, "04_Concepts/States/state.objet-petit-a.1959-1963.md",
        base_front(
            id="state.objet-petit-a.1959-1963", type="concept_state",
            title="对象小a（1959–1963）", canonical_name="objet petit a @1959-1963",
            aliases=["欲望的原因"], concept_id="concept.objet-petit-a",
            period="1959-1963", state_label="作为欲望原因的对象",
            passages=["passage.S7.1959-12-02.P012"], sources=["source.freud-gw"],
        ),
        body="此阶段的表述。\n",
    )
    write_note(
        root, "02_Lacan_Seminars/S07_Seminar_VII/seminar.S7.md",
        base_front(id="seminar.S7", type="seminar", title="研讨班 VII：精神分析的伦理",
                   canonical_name="Séminaire VII", aliases=["S7"],
                   seminar="S7", period="1959-1963"),
        body="本研讨班讨论伦理与欲望。\n",
    )
    write_note(
        root, "02_Lacan_Seminars/S07_Seminar_VII/passage.S7.1959-12-02.P012.md",
        base_front(
            id="passage.S7.1959-12-02.P012", type="passage", title="S7 1959-12-02 p.12",
            canonical_name="S7 1959-12-02 p.12", aliases=[],
            seminar="S7", session_date="1959-12-02", session_date_precision="exact",
            source_id="source.freud-gw", structure_path="S7 > 1959-12-02 > §3 > ¶12",
            page_from=12, page_to=12,
        ),
        body="段号正文。\n",
    )
    return write_relation(root, "relations.jsonl", [
        valid_relation(),
        valid_relation(
            relation_id="rel.000002", subject="concept.grand-autre",
            predicate="related_to", object="concept.objet-petit-a",
            evidence={"passage_id": [], "assertion_type": "editorial",
                      "note": "两条概念在研究上互相牵连", "edition": "Seuil 1966"},
            confidence=0.6,
        ),
    ])


# ================================================================ 1. relation schema
class TestRelationSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_json(RELATION_SCHEMA)
        cls.validator = jsonschema.Draft202012Validator(cls.schema)

    def errors(self, record):
        return list(self.validator.iter_errors(record))

    def test_valid_relation_passes(self):
        self.assertEqual(self.errors(valid_relation()), [])

    def test_required_fields_are_exactly_the_contract(self):
        self.assertEqual(set(self.schema["required"]), {
            "relation_id", "subject", "predicate", "object", "evidence",
            "confidence", "review_status", "authority_level",
            "created_at", "updated_at",
        })

    def test_additional_properties_closed(self):
        self.assertFalse(self.schema["additionalProperties"])
        self.assertTrue(self.errors(valid_relation(bogus_field=1)))

    def test_created_by_from_relation_model_not_generated_by(self):
        """RELATION_MODEL.md §2 的字段名是 created_by。"""
        self.assertIn("created_by", self.schema["properties"])
        self.assertNotIn("generated_by", self.schema["properties"])
        self.assertTrue(self.errors(valid_relation(generated_by="human:x")))
        self.assertEqual(self.errors(valid_relation(created_by="ai:m/run-1")), [])

    def test_predicate_enum_is_exactly_the_17(self):
        expected = [
            "defines", "redefines", "develops", "references", "contradicts",
            "influenced_by", "criticizes", "translates_as", "formalized_as",
            "represented_by", "appears_in", "related_to", "clinical_application",
            "case_example", "topological_model", "primary_source",
            "secondary_interpretation",
        ]
        self.assertEqual(self.schema["$defs"]["predicate"]["enum"], expected)
        self.assertEqual(len(expected), 17)
        self.assertTrue(self.errors(valid_relation(predicate="is_friends_with")))

    def test_entity_ref_allows_uppercase_after_first_segment(self):
        pat = re.compile(self.schema["$defs"]["entity_ref"]["pattern"])
        for good in ("concept.objet-petit-a", "passage.S7.1959-12-02.P012",
                     "seminar.S3", "person.jacques-lacan", "term.fr.jouissance"):
            self.assertTrue(pat.match(good), good)
        for bad in ("concept", "Concept.objet", "concept.", "concept..x", "concept.对象"):
            self.assertFalse(pat.match(bad), bad)
        self.assertTrue(self.errors(valid_relation(subject="concept")))
        self.assertTrue(self.errors(valid_relation(object="Concept.objet")))

    def test_explicit_requires_at_least_one_passage(self):
        bad = valid_relation()
        bad["evidence"] = {"passage_id": [], "assertion_type": "explicit"}
        self.assertTrue(self.errors(bad))

    def test_inferred_requires_note(self):
        bad = valid_relation()
        bad["evidence"] = {"passage_id": ["passage.S7.1959-12-02.P012"],
                           "assertion_type": "inferred"}
        self.assertTrue(self.errors(bad), "inferred 必须有 note 说明推断依据")
        ok = valid_relation()
        ok["evidence"] = {"passage_id": [], "assertion_type": "inferred",
                          "note": "跨文本比对推出"}
        self.assertEqual(self.errors(ok), [], "候选库允许 inferred 暂无段号（主库由校验器强制）")

    def test_editorial_requires_note(self):
        bad = valid_relation()
        bad["evidence"] = {"passage_id": [], "assertion_type": "editorial"}
        self.assertTrue(self.errors(bad))
        ok = valid_relation()
        ok["evidence"] = {"passage_id": [], "assertion_type": "editorial",
                          "note": "编者分期判断", "edition": "Seuil 1973"}
        self.assertEqual(self.errors(ok), [])

    def test_assertion_type_enum_closed(self):
        bad = valid_relation()
        bad["evidence"] = {"passage_id": [], "assertion_type": "guessed", "note": "x"}
        self.assertTrue(self.errors(bad))

    def test_evidence_object_is_closed(self):
        bad = valid_relation()
        bad["evidence"]["locator"] = "S7 p.12"   # 曾是脚手架的自造字段，已删
        self.assertTrue(self.errors(bad))
        bad2 = valid_relation()
        bad2["evidence"]["whatever"] = 1
        self.assertTrue(self.errors(bad2))

    def test_confidence_bounds(self):
        self.assertTrue(self.errors(valid_relation(confidence=1.5)))
        self.assertTrue(self.errors(valid_relation(confidence=-0.1)))
        for v in (0, 0.5, 1):
            self.assertEqual(self.errors(valid_relation(confidence=v)), [])

    def test_enums_match_knowledge_schema(self):
        k = load_json(KNOWLEDGE_SCHEMA)
        for mine, theirs in (("review_status", "review_status"),
                             ("authority_level", "authority_level")):
            self.assertEqual(self.schema["$defs"][mine]["enum"],
                             k["$defs"][theirs]["enum"])
        self.assertEqual(self.schema["$defs"]["entity_ref"]["pattern"],
                         k["$defs"]["stable_id"]["pattern"])

    def test_relation_id_namespace(self):
        self.assertTrue(self.errors(valid_relation(relation_id="objet-a-1")))
        self.assertEqual(self.errors(valid_relation(relation_id="rel.000001")), [])
        self.assertEqual(self.errors(valid_relation(relation_id="rel.c000001")), [])


# ================================================================ 2. namespaces
class TestIdNamespaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = load_json(ID_NAMESPACES)
        cls.ns = cls.doc["entity_types"]
        cls.knowledge = load_json(KNOWLEDGE_SCHEMA)
        cls.stable = re.compile(cls.knowledge["$defs"]["stable_id"]["pattern"])

    # Phase 2 在 knowledge.schema 的 24 个实体类型之外，另加了 3 类
    # **store 层**实体（不是 md 节点，故不在 entity_type 枚举里）：
    #   witness / alignment / passage_witness
    PHASE2_STORE_TYPES = {"witness", "alignment", "passage_witness"}

    def test_covers_every_entity_type_of_knowledge_schema(self):
        expected = set(self.knowledge["$defs"]["entity_type"]["enum"])
        self.assertEqual(len(expected), 24)
        self.assertEqual(set(self.ns.keys()) - self.PHASE2_STORE_TYPES, expected,
                         "namespace 表应恰好覆盖 knowledge.schema 的 24 类 + Phase 2 的 3 类")

    def test_phase2_store_types_are_declared(self):
        """Phase 2 的 witness/alignment/passage_witness 必须有 namespace 与 pattern。"""
        for t in sorted(self.PHASE2_STORE_TYPES):
            with self.subTest(type=t):
                self.assertIn(t, self.ns, f"缺 {t} 的 namespace 定义")
                self.assertTrue(self.ns[t]["pattern"], f"{t} 缺 pattern")

    def test_namespace_table_is_the_agreed_final_one(self):
        got = {t: e["namespace"] for t, e in self.ns.items()}
        # Phase 2 增补的三类 store 实体
        got = {k: v for k, v in got.items() if k not in self.PHASE2_STORE_TYPES}
        self.assertEqual(got, EXPECTED_NAMESPACES)
        for t, ns in (("witness", "witness"), ("alignment", "align"),
                      ("passage_witness", "pw")):
            self.assertEqual(self.ns[t]["namespace"], ns)

    def test_person_namespace_is_shared_by_person_and_psychoanalyst(self):
        self.assertEqual(self.ns["person"]["namespace"], "person")
        self.assertEqual(self.ns["psychoanalyst"]["namespace"], "person")
        others = [e["namespace"] for t, e in self.ns.items() if t != "psychoanalyst"]
        self.assertEqual(len(others), len(set(others)), "除 psychoanalyst 外 namespace 必须唯一")

    def test_each_entry_shape(self):
        for t, e in self.ns.items():
            for key in ("namespace", "pattern", "example", "description"):
                self.assertIn(key, e, "type=%s 缺字段 %s" % (t, key))
                self.assertTrue(str(e[key]).strip(), "type=%s 的 %s 为空" % (t, key))

    def test_example_matches_pattern_and_stable_id(self):
        for t, e in self.ns.items():
            self.assertTrue(re.match(e["pattern"], e["example"]),
                            "type=%s: example %r 不匹配 pattern %r"
                            % (t, e["example"], e["pattern"]))
            self.assertTrue(self.stable.match(e["example"]),
                            "type=%s: example %r 不满足 stable_id" % (t, e["example"]))

    def test_namespace_is_the_id_prefix(self):
        for t, e in self.ns.items():
            self.assertTrue(e["example"].startswith(e["namespace"] + "."),
                            "type=%s: example 未以 namespace 开头" % t)

    def test_uppercase_notation_is_allowed(self):
        """S3 / P010 / S-barre 必须命中 pattern。"""
        for t, sample in (("seminar", "seminar.S3"),
                          ("seminar", "seminar.S03"),
                          ("session", "session.S03.unknown"),
                          ("session", "session.S03.unknown.L01"),
                          ("passage", "passage.S03.unknown.L01.P0010"),
                          ("matheme", "matheme.S-barre")):
            self.assertTrue(re.match(self.ns[t]["pattern"], sample),
                            "%s 应接受 %s" % (t, sample))

    def test_unknown_date_forms(self):
        """§一：日期不可确证时保留 unknown —— 只有两种诚实形态。

        定稿：`YYYY-MM-DD`（确证）或裸 `unknown`（不可确证）。
        **刻意不支持 `YYYY-unknown`** —— 它与「年份 + 两位月」在正则上歧义
        （`1955-un` 会被读成两位月），且实测 store 里 0 条使用该形态。
        少一种形态比多一种歧义形态安全。
        """
        for t, sample in (
            ("session", "session.S3.1955-06-01"),
            ("session", "session.S03.1955-06-01"),
            ("session", "session.S03.unknown"),          # 裸 unknown
            ("session", "session.S03.unknown.L01"),
            ("session", "session.S03.unknown.p3"),       # 显式分页
            ("passage", "passage.S03.unknown.P0010"),
            ("passage", "passage.S03.unknown.L01.P0010"),
        ):
            self.assertTrue(re.match(self.ns[t]["pattern"], sample),
                            "%s 应接受 %s" % (t, sample))
        # 不得接受被猜测出来的非法形态
        self.assertFalse(re.match(self.ns["session"]["pattern"], "session.S3.unknownish"))

    def test_term_and_trans_are_layered(self):
        """term 与 translation 都按 `<前缀>.<lang>.<slug>` 分层。

        定稿（Phase 2 收敛）：`translation` 的 namespace pattern 是
        `trans.<lang>.<slug>`，lang ∈ {fr,en,zh,mul}。
        * mul = 跨语言对照条目（如术语译法对）
        * fr/zh = 某语料的文本角色记录
        方向不进 ID —— 方向是关系属性。
        """
        self.assertTrue(re.match(self.ns["term"]["pattern"], "term.fr.jouissance"))
        self.assertFalse(re.match(self.ns["term"]["pattern"], "term.jouissance"))
        for sample in ("trans.mul.jouissance", "trans.zh.translation-project",
                       "trans.fr.staferla"):
            with self.subTest(sample=sample):
                self.assertTrue(re.match(self.ns["translation"]["pattern"], sample),
                                "translation 应接受 %s" % sample)
        # 旧的方向式写法已废弃（方向属于关系，不属于 ID）
        self.assertFalse(re.match(self.ns["translation"]["pattern"],
                                  "trans.fr-to-zh.jouissance"))

    def test_declares_itself_as_single_source_of_truth(self):
        self.assertIn("唯一真源", self.doc["note"])
        self.assertIn("ENTITY_MODEL.md", self.doc["note"])


# ================================================================ 3. 模板
TPL_TYPE = {
    "concept.md": "concept",
    "concept-state.md": "concept_state",
    "term.md": "term",
    "source.md": "source",
    "document.md": "document",
    "seminar.md": "seminar",
    "session.md": "session",
    "passage.md": "passage",
    "case.md": "case",
    "reading-note.md": "reading_note",
    "synthesis.md": "synthesis",
    "question.md": "question",
    "person.md": "person",
}

RENDER_BASE = {
    "schema_version": "1.0.0", "language": "zh", "review_status": "candidate",
    "status": "stub", "generated_by": "human:填写你的名字",
    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    "authority_level": "L3", "title": "示例标题", "canonical_name": "示例规范名",
    "alias_1": "示例别名一", "alias_2": "示例别名二", "tag_1": "example",
    "related_id": "concept.objet-a", "source_id": "source.local.desktop-lacan",
    "source_type": "seminar_primary", "source_url": "https://example.org/doc",
    "source_hash": "0" * 64, "source_path": "01_Sources/Documents/example.pdf",
    "document_id": "doc.lacan.seminar-11", "seminar": "S11",
    "seminar_id": "seminar.S11", "session_date": "1964-02-12",
    "session_date_precision": "exact",
    "structure_path": "S11/1964-02-12/section-03/para-07",
    "page_from": 23, "page_to": 23, "paragraph_index": 7,
    "passage_id_1": "passage.S11.1964-02-12.P007",
    "passage_id_2": "passage.S11.1964-02-12.P008",
    "period": "1964-1966", "period_label": "1964–1966 对象a 与阉割",
    "concept_id": "concept.objet-a",
    "concept_state_id_1": "state.objet-a.1964-1966",
    "concept_state_id_2": "state.objet-a.1972-1973",
    "state_label": "a 作为欲望的原因", "supersedes": "state.objet-a.1955-1958",
    "fr": "objet petit a", "en": "object petit a", "zh": "对象 a",
    "case_id": "case.schreber", "structure_id": "structure.psychosis",
    "matheme_id": "matheme.S-barre", "topology_id": "topology.mobius-strip",
    "formula_id": "formula.fantasy.S-diamond-a", "discourse_id": "discourse.analyst",
    "school_id": "school.ecole-de-la-cause-freudienne",
    "debate_id": "debate.ordinary-psychosis", "person_id": "person.jacques-lacan",
    "project_id": "project.ordinary-psychosis",
    "trace_status": "COMPLETE", "confidence": 0.5,
    "edition": "Seuil 1973", "translator": "示例译者", "publisher": "示例出版社",
    "publication_year": 1973, "reviewed_by": "human:审阅者",
    "reviewed_at": "2026-01-02T00:00:00Z",
}

PLACEHOLDER = re.compile(r"\{\{([a-z0-9_]+)\}\}")


def render_template(path, ns_examples):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    tpl = os.path.basename(path)
    etype = TPL_TYPE[tpl]
    values = dict(RENDER_BASE)
    values["id"] = ns_examples[etype]
    values["type"] = etype
    if etype == "synthesis":
        values["authority_level"] = "L4"
    if etype in ("source", "document", "passage", "seminar", "session"):
        values["authority_level"] = "L1"
    if etype in ("term", "translation"):
        values["authority_level"] = "L2"
    missing = sorted(set(PLACEHOLDER.findall(text)) - set(values))
    if missing:
        raise AssertionError("%s 有未登记的占位符: %s" % (tpl, missing))
    return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), text)


def split_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        raise AssertionError("模板渲染后没有可用 frontmatter")
    return yaml.safe_load(m.group(1)), m.group(2)


class TestTemplates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.knowledge = load_json(KNOWLEDGE_SCHEMA)
        cls.validator = jsonschema.Draft202012Validator(cls.knowledge)
        cls.ns = load_json(ID_NAMESPACES)["entity_types"]
        cls.examples = {t: e["example"] for t, e in cls.ns.items()}

    def test_all_thirteen_templates_exist(self):
        for name in TPL_TYPE:
            self.assertTrue(os.path.isfile(os.path.join(TEMPLATES, name)), "缺模板 %s" % name)

    def test_rendered_frontmatter_passes_knowledge_schema(self):
        for name, etype in TPL_TYPE.items():
            text = render_template(os.path.join(TEMPLATES, name), self.examples)
            front, _body = split_frontmatter(text)
            errs = list(self.validator.iter_errors(front))
            self.assertEqual(errs, [],
                             "%s 渲染后不通过 schema: %s" % (name, [e.message for e in errs]))
            self.assertEqual(front["type"], etype)
            for key in self.knowledge["required"]:
                self.assertIn(key, front, "%s 缺 required 字段 %s" % (name, key))
            # 文件名必须等于 id：模板的 id 必须来自 namespace 真源
            self.assertEqual(front["id"], self.examples[etype])

    def test_concept_body_carries_no_definition(self):
        """概念本体不承载定义：定义只存在于 state.* 节点。"""
        with open(os.path.join(TEMPLATES, "concept.md"), "r", encoding="utf-8") as f:
            concept = f.read()
        with open(os.path.join(TEMPLATES, "concept-state.md"), "r", encoding="utf-8") as f:
            state = f.read()
        _, concept_body = split_frontmatter(
            render_template(os.path.join(TEMPLATES, "concept.md"), self.examples))
        _, state_body = split_frontmatter(
            render_template(os.path.join(TEMPLATES, "concept-state.md"), self.examples))
        self.assertNotRegex(concept_body, r"(?m)^##+\s*定义")
        self.assertIn("state.", concept_body, "concept.md 应指向 state.* 命名空间")
        self.assertRegex(state_body, r"(?m)^##+\s*定义")
        self.assertIn("concept_states", concept)
        self.assertIn("concept_id", state)

    def test_passage_template_has_precision_and_trace_fields(self):
        with open(os.path.join(TEMPLATES, "passage.md"), "r", encoding="utf-8") as f:
            text = f.read()
        for field in ("session_date_precision", "trace_status", "paragraph_index", "edition"):
            self.assertIn(field, text, "passage.md 缺字段 %s" % field)

    def test_templates_index_documents_filename_rule(self):
        path = os.path.join(TEMPLATES, "_index.md")
        self.assertTrue(os.path.isfile(path), "Templates 需要一份说明")
        text = read_text(path)
        self.assertIn("文件名", text)
        self.assertIn("id", text)


# ================================================================ 4. 端到端
class TestValidateVaultEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="lacan-vault-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def run_cli(self, *args):
        cmd = [sys.executable, VALIDATE, "--vault", self.root] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True)

    def report(self):
        with open(os.path.join(self.root, "_index", "Reports",
                               "validation-report.json"), "r", encoding="utf-8") as f:
            return json.load(f)

    def codes(self, rep, severity=None):
        return [i["code"] for i in rep["issues"]
                if severity is None or i["severity"] == severity]

    def test_clean_vault_exits_zero_and_writes_both_reports(self):
        build_fixture_vault(self.root)
        p = self.run_cli()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for name in ("validation-report.md", "validation-report.json"):
            self.assertTrue(os.path.isfile(
                os.path.join(self.root, "_index", "Reports", name)))
        rep = self.report()
        self.assertEqual(rep["summary"]["errors"], 0, rep["issues"])
        self.assertEqual(rep["summary"]["entity_files"], 5)
        self.assertEqual(rep["summary"]["relations"], 2)
        self.assertEqual(rep["summary"]["relation_errors"], 0)
        self.assertEqual(rep["summary"]["view_mismatches"], 0)
        self.assertEqual(rep["summary"]["filename_id_mismatches"], 0)

    def test_nav_and_template_files_are_skipped_not_errors(self):
        build_fixture_vault(self.root)
        self.run_cli()
        rep = self.report()
        root = os.path.realpath(self.root)
        skipped = {os.path.relpath(os.path.realpath(s["path"]), root)
                   for s in rep["skipped"]}
        self.assertIn("00_System/Templates/nav-sample.md", skipped)
        self.assertIn("_index/Reports/nav-sample.md", skipped)
        self.assertEqual(rep["summary"]["errors"], 0)

    def test_exit_code_contract(self):
        """--strict 只看 error；--warnings-as-errors 把 warning 也当失败。"""
        build_fixture_vault(self.root)
        write_note(self.root, "04_Concepts/concept.warn-only.md",
                   base_front(id="concept.warn-only", canonical_name="warn only",
                              concept_states=[]),
                   body="断链 [[concept.nope]] 只是 warning。\n")
        rep_strict = self.run_cli("--strict")
        self.assertEqual(rep_strict.returncode, 0, rep_strict.stderr)
        self.assertEqual(self.report()["summary"]["errors"], 0)
        self.assertGreater(self.report()["summary"]["warnings"], 0)
        self.assertEqual(self.run_cli("--strict", "--warnings-as-errors").returncode, 1)

    def test_filename_must_equal_id(self):
        build_fixture_vault(self.root)
        write_note(self.root, "04_Concepts/wrong-filename.md",
                   base_front(id="concept.wrong-filename-2", canonical_name="wf"),
                   body="文件名与 id 不一致。\n")
        p = self.run_cli("--strict")
        self.assertEqual(p.returncode, 1)
        rep = self.report()
        self.assertIn("FILENAME_ID_MISMATCH", self.codes(rep, "error"))
        self.assertEqual(rep["filename_id_mismatches"][0]["filename"], "wrong-filename")
        self.assertEqual(rep["filename_id_mismatches"][0]["id"], "concept.wrong-filename-2")
        with open(os.path.join(self.root, "_index", "Reports", "validation-report.md"),
                  encoding="utf-8") as f:
            md = f.read()
        self.assertIn("应重命名为", md)

    def test_broken_wikilink_detected_and_resolvable_links_are_not(self):
        build_fixture_vault(self.root)
        # 只有 warning：--strict 不阻塞（exit 0），但 --warnings-as-errors 会
        self.assertEqual(self.run_cli("--strict").returncode, 0)
        p = self.run_cli("--strict", "--warnings-as-errors")
        self.assertEqual(p.returncode, 1)
        rep = self.report()
        self.assertEqual({b["target"] for b in rep["broken_wikilinks"]},
                         {"concept.bu-cun-zai-de-dongxi"})
        self.assertIn("BROKEN_WIKILINK", self.codes(rep, "warning"))
        self.assertEqual(rep["summary"]["wikilinks"], 5)

    def test_wikilink_forms_parse(self):
        links = VV.extract_wikilinks("a [[甲]] b [[乙|别名]] c [[丙#锚点]] d ![[图.png]] e `[[行内代码不算]]`")
        bodies = [l for l in links if not l["embed"]]
        self.assertEqual([l["target"] for l in bodies], ["甲", "乙", "丙"])
        self.assertEqual(bodies[1]["alias"], "别名")
        self.assertEqual(bodies[2]["anchor"], "锚点")
        self.assertEqual([l["target"] for l in links if l["embed"]], ["图.png"])

    def test_link_resolution_is_case_insensitive(self):
        """[[seminar.s3]] 与 [[seminar.S3]] 等价；但存储的 id 保持设计大小写。"""
        build_fixture_vault(self.root)
        write_note(self.root, "04_Concepts/concept.case-probe.md",
                   base_front(id="concept.case-probe", canonical_name="case probe"),
                   body="大小写不敏感：[[seminar.s7]]。\n")
        self.run_cli()
        rep = self.report()
        self.assertNotIn("seminar.s7", {b["target"] for b in rep["broken_wikilinks"]})

    def test_fenced_code_block_links_ignored(self):
        links = VV.extract_wikilinks("```\n[[不该算]]\n```\n[[该算]]\n")
        self.assertEqual([l["target"] for l in links], ["该算"])

    def test_duplicate_id_is_an_error(self):
        build_fixture_vault(self.root)
        # 同名同 id 出现在另一个目录 —— 文件名 == id 时唯一的重复可能
        write_note(self.root, "05_Terminology/concept.objet-petit-a.md",
                   base_front(id="concept.objet-petit-a", canonical_name="另一个规范名"),
                   body="dupe\n")
        p = self.run_cli("--strict")
        self.assertEqual(p.returncode, 1)
        rep = self.report()
        self.assertIn("DUPLICATE_ID", self.codes(rep, "error"))
        self.assertEqual(rep["duplicate_ids"][0]["id"], "concept.objet-petit-a")

    def test_duplicate_canonical_name_within_same_type_is_an_error(self):
        build_fixture_vault(self.root)
        write_note(self.root, "04_Concepts/concept.grand-autre-2.md",
                   base_front(id="concept.grand-autre-2", title="大他者（重复）",
                              canonical_name="grand Autre", aliases=[]),
                   body="dupe canonical\n")
        self.run_cli()
        self.assertIn("DUPLICATE_CANONICAL_NAME", self.codes(self.report(), "error"))

    def test_near_duplicate_canonical_name_is_a_warning(self):
        build_fixture_vault(self.root)
        write_note(self.root, "04_Concepts/concept.grand-autre-3.md",
                   base_front(id="concept.grand-autre-3", title="大他者（写法差异）",
                              canonical_name="grand-autre", aliases=[]),
                   body="归一化后与 grand Autre 碰撞。\n")
        self.run_cli()
        self.assertIn("CANONICAL_NAME_NEAR_DUPLICATE", self.codes(self.report(), "warning"))

    def test_alias_collision_is_an_info(self):
        build_fixture_vault(self.root)
        write_note(self.root, "04_Concepts/concept.probe-alias.md",
                   base_front(id="concept.probe-alias", canonical_name="probe alias",
                              aliases=["grand Autre"], concept_states=[]),
                   body="别名撞上别人的规范名。\n")
        self.run_cli()
        rep = self.report()
        self.assertIn("ALIAS_COLLIDES_WITH_CANONICAL", self.codes(rep, "info"))
        self.assertEqual(rep["summary"]["errors"], 0)

    def test_same_canonical_name_across_different_types_is_fine(self):
        build_fixture_vault(self.root)
        write_note(self.root, "05_Terminology/FR/term.fr.objet-petit-a.md",
                   base_front(id="term.fr.objet-petit-a", type="term", title="objet petit a",
                              canonical_name="grand Autre", aliases=[], fr="objet petit a"),
                   body="不同 type 之间 canonical_name 可以重名。\n")
        self.run_cli()
        self.assertNotIn("DUPLICATE_CANONICAL_NAME", self.codes(self.report(), "error"))

    def test_schema_violation_is_an_error(self):
        build_fixture_vault(self.root)
        write_note(self.root, "04_Concepts/concept.bad.md",
                   base_front(id="concept.bad", canonical_name="bad",
                              review_status="approved"),
                   body="非法 review_status。\n")
        p = self.run_cli("--strict")
        self.assertEqual(p.returncode, 1)
        self.assertIn("SCHEMA_INVALID", self.codes(self.report(), "error"))

    def test_namespace_mismatch_is_an_error(self):
        build_fixture_vault(self.root)
        write_note(self.root, "04_Concepts/concept2.wrong.md",
                   base_front(id="concept2.wrong", canonical_name="wrong ns"),
                   body="namespace 与 type 不符。\n")
        self.run_cli()
        self.assertIn("NAMESPACE_MISMATCH", self.codes(self.report(), "error"))

    def test_uppercase_ids_and_unknown_dates_are_accepted(self):
        build_fixture_vault(self.root)
        write_note(self.root, "02_Lacan_Seminars/S03_Seminar_III/seminar.S3.md",
                   base_front(id="seminar.S3", type="seminar", title="研讨班 III",
                              canonical_name="Séminaire III", aliases=["S3"],
                              seminar="S3", period="1955-1958"),
                   body="期号大写是允许的。\n")
        write_note(
            self.root, "02_Lacan_Seminars/S03_Seminar_III/session.S3.1955-unknown.md",
            base_front(id="session.S3.1955-unknown", type="session", title="S3 未定日期课次",
                       canonical_name="S3 1955 unknown", aliases=[], seminar="S3",
                       session_date="1955-01-01", session_date_precision="unknown"),
            body="课次日期未确证。\n")
        write_note(
            self.root, "02_Lacan_Seminars/S03_Seminar_III/passage.S3.1955-unknown.P010.md",
            base_front(id="passage.S3.1955-unknown.P010", type="passage",
                       title="S3 p.10", canonical_name="S3 p.10", aliases=[],
                       seminar="S3", session_date="1955-01-01",
                       session_date_precision="unknown", source_id="source.freud-gw",
                       structure_path="S3/1955-unknown/page-010", page_from=10, page_to=10),
            body="页锚为 P010。\n")
        self.run_cli()
        rep = self.report()
        self.assertNotIn("ID_PATTERN_INVALID", self.codes(rep, "error"))
        self.assertNotIn("NAMESPACE_MISMATCH", self.codes(rep, "error"))
        self.assertEqual(rep["summary"]["errors"], 0, rep["issues"])

    def test_missing_frontmatter_is_a_warning_not_a_crash(self):
        build_fixture_vault(self.root)
        path = os.path.join(self.root, "13_Reading_Notes/loose-note.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("没有 frontmatter 的散笔记。\n")
        p = self.run_cli()
        self.assertEqual(p.returncode, 0)
        rep = self.report()
        self.assertIn("MISSING_FRONTMATTER", self.codes(rep, "warning"))
        self.assertEqual(rep["summary"]["errors"], 0)

    # ---- 关系（RELATION_MODEL.md）
    def test_relation_schema_and_reference_checks(self):
        build_fixture_vault(self.root)
        write_relation(self.root, "extra.jsonl", [
            valid_relation(relation_id="rel.000101", predicate="is_friends_with"),
            valid_relation(relation_id="rel.000102", subject="concept.does-not-exist"),
            valid_relation(relation_id="rel.000103",
                           evidence={"passage_id": ["passage.S7.1959-12-02.P099"],
                                     "assertion_type": "explicit"}),
        ])
        p = self.run_cli("--strict")
        self.assertEqual(p.returncode, 1)
        codes = self.codes(self.report())
        self.assertIn("RELATION_SCHEMA_INVALID", codes)
        self.assertIn("BROKEN_RELATION", codes)
        self.assertIn("SOURCE_TRACE_INCOMPLETE", codes)

    def test_relation_self_loop_and_redefines_object_type(self):
        build_fixture_vault(self.root)
        write_relation(self.root, "extra.jsonl", [
            valid_relation(relation_id="rel.000201",
                           subject="concept.objet-petit-a",
                           object="concept.objet-petit-a"),
            valid_relation(relation_id="rel.000202", predicate="redefines",
                           subject="state.objet-petit-a.1959-1963",
                           object="concept.grand-autre"),
        ])
        self.run_cli()
        codes = self.codes(self.report())
        self.assertIn("RELATION_SELF_LOOP", codes)
        self.assertIn("RELATION_REDEFINES_OBJECT_TYPE", codes)

    def test_main_library_thresholds_and_ai_boundary(self):
        """RELATION_MODEL.md §5/§6：<0.50 不得进主库；AI 不得写主库。"""
        build_fixture_vault(self.root)
        write_relation(self.root, "relations.jsonl", [
            valid_relation(relation_id="rel.000301", confidence=0.3),
            valid_relation(relation_id="rel.000302", created_by="ai:deepseek/test-run"),
            valid_relation(relation_id="rel.000303", review_status="candidate"),
        ])
        self.run_cli()
        codes = self.codes(self.report(), "error")
        self.assertIn("RELATION_CONFIDENCE_MAIN_THRESHOLD", codes)
        self.assertIn("RELATION_AI_IN_MAIN", codes)
        self.assertIn("RELATION_MAIN_STATUS", codes)

    def test_candidate_library_allows_low_confidence_and_missing_evidence(self):
        """候选库的定义就是「尚未取得证据的建议」。"""
        build_fixture_vault(self.root)
        write_relation(self.root, "relations.candidate.jsonl", [
            valid_relation(relation_id="rel.c000001", confidence=0.3,
                           review_status="candidate", created_by="ai:m/run-1",
                           evidence={"passage_id": [], "assertion_type": "inferred",
                                     "note": "AI 建议：待人工判定"}),
        ])
        self.run_cli()
        rep = self.report()
        for code in ("RELATION_CONFIDENCE_MAIN_THRESHOLD", "RELATION_AI_IN_MAIN",
                     "RELATION_INFERRED_NO_EVIDENCE"):
            self.assertNotIn(code, self.codes(rep, "error"))

    def test_reviewed_inferred_relation_requires_evidence(self):
        build_fixture_vault(self.root)
        write_relation(self.root, "relations.jsonl", [
            valid_relation(relation_id="rel.000401", confidence=0.7,
                           evidence={"passage_id": [], "assertion_type": "inferred",
                                     "note": "推断但没有段号"}),
        ])
        self.run_cli()
        self.assertIn("RELATION_INFERRED_NO_EVIDENCE", self.codes(self.report(), "error"))

    def test_relation_duplicate_id_detected(self):
        build_fixture_vault(self.root)
        write_relation(self.root, "dup.jsonl", [valid_relation()])
        self.run_cli()
        self.assertIn("RELATION_DUPLICATE_ID", self.codes(self.report(), "error"))

    def test_view_layer_mismatch_warns(self):
        """语义层有边、正文没有对应 wikilink → Graph View 里看不见。"""
        build_fixture_vault(self.root)
        write_note(self.root, "04_Concepts/concept.isolated.md",
                   base_front(id="concept.isolated", canonical_name="isolated",
                              concept_states=["state.objet-petit-a.1959-1963"]),
                   body="正文故意不写任何链接。\n")
        write_relation(self.root, "extra.jsonl", [
            valid_relation(relation_id="rel.000501", subject="concept.isolated",
                           predicate="related_to", object="concept.objet-petit-a"),
        ])
        self.run_cli()
        rep = self.report()
        self.assertIn("RELATION_VIEW_MISMATCH", self.codes(rep, "warning"))
        self.assertEqual(rep["summary"]["errors"], 0)

    def test_frontmatter_brackets_warn_but_still_resolve(self):
        build_fixture_vault(self.root)
        write_note(self.root, "04_Concepts/concept.brackets.md",
                   base_front(id="concept.brackets", canonical_name="brackets",
                              related=["[[concept.grand-autre]]"]),
                   body="related 里多写了方括号。\n")
        self.run_cli()
        rep = self.report()
        self.assertIn("WIKILINK_BRACKETS_IN_FRONTMATTER", self.codes(rep, "warning"))
        self.assertNotIn("concept.grand-autre",
                         {b["target"] for b in rep["broken_wikilinks"]})

    def test_convergence_note_is_included_in_report(self):
        build_fixture_vault(self.root)
        d = os.path.join(self.root, "00_System", "Validation")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "convergence-note.md"), "w", encoding="utf-8") as f:
            f.write("### 收敛项\n\n- 文件名 == id 升级为 error\n")
        self.run_cli()
        with open(os.path.join(self.root, "_index", "Reports", "validation-report.md"),
                  encoding="utf-8") as f:
            md = f.read()
        self.assertIn("本次收敛修了什么", md)
        self.assertIn("文件名 == id 升级为 error", md)
        self.assertEqual(self.report()["convergence_note_path"],
                         "00_System/Validation/convergence-note.md")

    def test_json_flag_prints_parseable_json(self):
        build_fixture_vault(self.root)
        p = self.run_cli("--json", "--quiet")
        payload = json.loads(p.stdout)
        self.assertEqual(payload["summary"]["entity_files"], 5)

    def test_non_strict_exits_zero_even_with_errors(self):
        build_fixture_vault(self.root)
        write_note(self.root, "04_Concepts/concept.bad2.md",
                   base_front(id="concept.bad2", canonical_name="bad2", language="klingon"),
                   body="非法 language。\n")
        p = self.run_cli()
        self.assertEqual(p.returncode, 0)
        self.assertGreater(self.report()["summary"]["errors"], 0)

    def test_real_vault_runs_and_report_is_self_consistent(self):
        """真实 vault 里有别的 agent 正在写的节点：只要求跑得通、报告自洽、不崩。"""
        p = subprocess.run([sys.executable, VALIDATE, "--vault", VAULT, "--json", "--quiet"],
                           capture_output=True, text=True)
        self.assertIn(p.returncode, (0, 1), p.stdout + p.stderr)
        payload = json.loads(p.stdout)
        errs = [i for i in payload["issues"] if i["severity"] == "error"]
        self.assertEqual(payload["summary"]["errors"], len(errs))
        self.assertTrue(os.path.isfile(
            os.path.join(VAULT, "_index", "Reports", "validation-report.json")))
        self.assertEqual(payload["summary"]["filename_id_mismatches"],
                         len(payload["filename_id_mismatches"]))


# ================================================================ 5. 索引生成
class TestMakeIndex(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="lacan-index-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, MAKE_INDEX, "--vault", self.root] + list(args),
                              capture_output=True, text=True)

    def view(self, name):
        with open(os.path.join(self.root, "_index", "Views", name), "r",
                  encoding="utf-8") as f:
            return f.read()

    def test_generates_all_views(self):
        build_fixture_vault(self.root)
        p = self.run_cli()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for name in ("by-type.md", "by-authority.md", "by-period.md",
                     "orphans.md", "broken-links.md"):
            self.assertTrue(os.path.isfile(
                os.path.join(self.root, "_index", "Views", name)), "缺视图 %s" % name)

    def test_by_type_groups_entities(self):
        build_fixture_vault(self.root)
        self.run_cli()
        text = self.view("by-type.md")
        for needle in ("concept", "objet-petit-a", "passage", "seminar"):
            self.assertIn(needle, text)

    def test_orphan_concept_listed(self):
        """大他者没有任何关系指向它 → 孤儿；对象小a 有入边 → 不是孤儿。"""
        build_fixture_vault(self.root)
        self.run_cli()
        text = self.view("orphans.md")
        self.assertIn("concept.grand-autre", text)
        self.assertNotIn("concept.objet-petit-a", text)

    def test_broken_link_view_lists_targets(self):
        build_fixture_vault(self.root)
        self.run_cli()
        self.assertIn("concept.bu-cun-zai-de-dongxi", self.view("broken-links.md"))

    def test_by_authority_and_period(self):
        build_fixture_vault(self.root)
        self.run_cli()
        auth = self.view("by-authority.md")
        self.assertIn("L1", auth)
        self.assertIn("L3", auth)
        self.assertIn("1959-1963", self.view("by-period.md"))


# ================================================================ 6. 文档纪律
class TestGovernanceDocs(unittest.TestCase):
    def test_changelog_exists_and_records_v1(self):
        path = os.path.join(SCHEMA_DIR, "CHANGELOG.md")
        self.assertTrue(os.path.isfile(path))
        text = read_text(path)
        self.assertIn("1.0.0", text)
        self.assertIn("additionalProperties", text)

    def test_guidelines_exist(self):
        for name in ("writing-style.md", "ai-contribution-policy.md"):
            self.assertTrue(os.path.isfile(
                os.path.join(VAULT, "00_System", "Guidelines", name)))

    def test_ai_policy_forbids_auto_promotion(self):
        with open(os.path.join(VAULT, "00_System", "Guidelines",
                               "ai-contribution-policy.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("canonical", text)
        self.assertIn("L4", text)

    def test_section_indexes_exist(self):
        for i in range(17):
            for d in os.listdir(VAULT):
                if d.startswith("%02d_" % i):
                    self.assertTrue(os.path.isfile(os.path.join(VAULT, d, "_index.md")),
                                    "%s 缺 _index.md" % d)

    def test_requirements_pins_all_deps(self):
        text = read_text(os.path.join(SCRIPTS, "requirements.txt"))
        for pkg in ("pypdf", "python-docx", "PyYAML", "jsonschema",
                    "ebooklib", "Pillow", "langdetect", "beautifulsoup4"):
            self.assertIn(pkg, text)
        self.assertIn("3.9", text)

    def test_readme_and_home_exist(self):
        for name in ("README.md", "Home.md"):
            self.assertTrue(os.path.isfile(os.path.join(VAULT, name)), "缺 %s" % name)
        home = read_text(os.path.join(VAULT, "Home.md"))
        for level in ("L0", "L1", "L2", "L3", "L4"):
            self.assertIn(level, home)
        self.assertIn("Graph", home)


if __name__ == "__main__":
    unittest.main(verbosity=2)
