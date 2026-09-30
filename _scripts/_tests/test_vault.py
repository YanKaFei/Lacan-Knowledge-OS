#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_vault.py — Knowledge OS vault 契约测试

覆盖用户要求的七项检查：
  1. ID 唯一性
  2. YAML schema
  3. broken wikilinks
  4. invalid relations
  5. source trace
  6. duplicate entities
  7. orphan concepts

每一项都有**负例**（故意构造坏数据）来证明检查真的会失败 ——
只有正例的测试无法区分「检查通过」和「检查根本没跑」。
"""

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from collections import defaultdict

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))          # vault 根
SCHEMAS = os.path.join(VAULT, "00_System", "Schemas")
RELATIONS = os.path.join(VAULT, "_data", "relations")

ID_RE = re.compile(r"^[a-z][a-z0-9-]*(\.[A-Za-z0-9][A-Za-z0-9-]*)+$")

# 命名空间以 00_System/Schemas/id-namespaces.json 为唯一真源（schema_version 1.0.0）。
# 下面的值与之对齐；测试里额外断言二者不漂移，避免契约分裂。
NAMESPACE_BY_TYPE = {
    "source": "source.", "document": "doc.", "seminar": "seminar.",
    "session": "session.", "passage": "passage.", "concept": "concept.",
    "concept_state": "state.", "term": "term.", "translation": "trans.",
    "person": "person.", "philosopher": "philosopher.",
    "psychoanalyst": "person.",
    "case": "case.", "clinical_structure": "structure.", "matheme": "matheme.",
    "topology": "topology.", "formula": "formula.", "discourse": "discourse.",
    "school": "school.", "debate": "debate.", "reading_note": "note.",
    "synthesis": "synth.", "question": "q.", "research_project": "project.",
    # Phase 2 新增的三类 **store 层**实体（不是 md 节点，故不在 entity_type 枚举里）
    "witness": "witness.", "alignment": "align.", "passage_witness": "pw.",
}


def load_namespace_file():
    """读 id-namespaces.json，返回 {type: namespace_str}。"""
    path = os.path.join(SCHEMAS, "id-namespaces.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    et = d.get("entity_types") or {}
    if isinstance(et, list):
        return {e["type"]: e["namespace"] for e in et if "type" in e}
    return {k: v.get("namespace") for k, v in et.items()}

PREDICATES = {
    "defines", "redefines", "develops", "references", "contradicts",
    "influenced_by", "criticizes", "translates_as", "formalized_as",
    "represented_by", "appears_in", "related_to", "clinical_application",
    "case_example", "topological_model", "primary_source",
    "secondary_interpretation",
}


# ------------------------------------------------------------------ 读取层
def iter_notes(root):
    """遍历知识节点。

    排除项（重要）：
      * `00_System/Templates/` —— Obsidian 模板不是知识节点。
      * 含 `{{...}}` 占位符的文件 —— 未实例化的模板。
      * 根目录的 7 份设计文档 —— 它们的 `[[...]]` 是**示例**，不是真实链接。

    判定「是知识节点」的机械标准：frontmatter 里有合法形态的 `id`
    （见下方 ID_RE）。模板的 `{{id}}` 与设计文档的「无 frontmatter」
    都会被这条标准自动排除，而真正的节点一个都不会漏。
    """
    skip_dirs = {".obsidian", ".git", "node_modules"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            if rel.split(os.sep)[:2] == ["00_System", "Templates"]:
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    text = f.read()
            except Exception:
                continue
            if "{{" in text[:4000]:
                continue
            if not text.startswith("---"):
                continue
            end = text.find("\n---", 3)
            if end == -1:
                continue
            try:
                fm = yaml.safe_load(text[3:end])
            except Exception:
                continue
            if not isinstance(fm, dict):
                continue
            if not ID_RE.match(str(fm.get("id", ""))):
                continue
            yield p


def parse_frontmatter(path):
    """返回 (frontmatter dict, body, error)。"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        return None, "", f"read-error: {e}"
    if not text.startswith("---"):
        return None, text, "no-frontmatter"
    end = text.find("\n---", 3)
    if end == -1:
        return None, text, "unterminated-frontmatter"
    raw = text[3:end]
    try:
        fm = yaml.safe_load(raw)
    except Exception as e:
        return None, text[end + 4:], f"yaml-error: {e}"
    if not isinstance(fm, dict):
        return None, text[end + 4:], "frontmatter-not-mapping"
    return fm, text[end + 4:], None


def iter_wikilinks(body):
    for m in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", body):
        yield m.group(1).strip()


def load_vault(root):
    notes = []
    for p in iter_notes(root):
        rel = os.path.relpath(p, root)
        fm, body, err = parse_frontmatter(p)
        notes.append({"path": p, "rel": rel, "fm": fm, "body": body, "error": err})
    return notes


def load_relations(root):
    out = {"main": [], "candidate": [], "rejected": []}
    for key, fn in (("main", "relations.jsonl"),
                    ("candidate", "relations.candidate.jsonl"),
                    ("rejected", "relations.rejected.jsonl")):
        p = os.path.join(root, "_data", "relations", fn)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    out[key].append(json.loads(line))
                except Exception as e:
                    out[key].append({"__parse_error__": f"{fn}:{ln}: {e}"})
    return out


# ------------------------------------------------------------------ 校验逻辑
def check_id_uniqueness(notes):
    problems = []
    seen = {}
    for n in notes:
        fm = n["fm"]
        if not fm or "id" not in fm:
            continue
        i = fm["id"]
        if i in seen:
            problems.append(f"重复 ID {i}: {seen[i]} 与 {n['rel']}")
        else:
            seen[i] = n["rel"]
    return problems


def check_schema(notes, schema_path):
    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except ImportError:
        return [("SKIP", "jsonschema 未安装")]
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema)
    problems = []
    for n in notes:
        if n["fm"] is None:
            continue
        for e in sorted(v.iter_errors(n["fm"]), key=lambda x: list(x.path)):
            loc = "/".join(str(x) for x in e.path) or "(root)"
            problems.append(f"{n['rel']} :: {loc} :: {e.message}")
    return problems


def check_wikilinks(notes, root):
    """返回 (broken, unresolved)。目标可按文件名、相对路径或 id 解析。"""
    # 建立索引：id -> rel, 文件名 stem -> rel, 相对路径 -> rel
    by_id, by_stem, by_relpath = {}, {}, {}
    for n in notes:
        by_relpath[os.path.splitext(n["rel"])[0]] = n["rel"]
        by_relpath[n["rel"]] = n["rel"]
        by_stem.setdefault(os.path.splitext(os.path.basename(n["rel"]))[0], []).append(n["rel"])
        fm = n["fm"]
        if fm and fm.get("id"):
            by_id[fm["id"]] = n["rel"]

    broken = []
    for n in notes:
        base = os.path.dirname(n["rel"])
        for target in iter_wikilinks(n["body"]):
            t = target.strip()
            cands = [t, t + ".md", os.path.normpath(os.path.join(base, t)) + ".md",
                     os.path.normpath(os.path.join(base, t))]
            ok = (t in by_id or t in by_stem or t in by_relpath
                  or any(c in by_relpath for c in cands)
                  or any(os.path.splitext(os.path.basename(c))[0] in by_stem for c in cands))
            if not ok:
                broken.append(f"{n['rel']} -> [[{t}]]")
    return broken, []


def check_relations(rels, notes, root):
    """返回 (errors, warnings)。"""
    by_id = {}
    for n in notes:
        if n["fm"] and n["fm"].get("id"):
            by_id[n["fm"]["id"]] = n
    errs, warns = [], []

    for bucket in ("main", "candidate"):
        for r in rels[bucket]:
            tag = f"{bucket}:{r.get('relation_id', '?')}"
            if "__parse_error__" in r:
                errs.append(f"{tag} JSON 解析失败: {r['__parse_error__']}")
                continue
            for f in ("relation_id", "subject", "predicate", "object",
                      "evidence", "confidence", "review_status",
                      "authority_level", "created_at", "updated_at"):
                if f not in r:
                    errs.append(f"{tag} 缺必填字段 {f}")
            if r.get("predicate") not in PREDICATES:
                errs.append(f"{tag} 非法谓词 {r.get('predicate')!r}")
            for side in ("subject", "object"):
                v = r.get(side)
                if v and not ID_RE.match(str(v)):
                    errs.append(f"{tag} {side} ID 形态非法: {v!r}")
                elif v and v not in by_id:
                    errs.append(f"{tag} BROKEN_RELATION: {side} 不存在: {v}")
            if r.get("subject") and r.get("subject") == r.get("object"):
                errs.append(f"{tag} 自环关系")
            ev = r.get("evidence") or {}
            at = ev.get("assertion_type")
            if at not in ("explicit", "inferred", "editorial"):
                errs.append(f"{tag} assertion_type 非法: {at!r}")
            if at == "explicit" and not ev.get("passage_id"):
                errs.append(f"{tag} assertion_type=explicit 但无 passage_id")
            for pid in ev.get("passage_id") or []:
                if pid not in by_id:
                    errs.append(f"{tag} 证据 Passage 不存在: {pid}")
            # redefines 的 object 必须是 concept_state
            if r.get("predicate") == "redefines":
                obj = by_id.get(r.get("object"))
                if obj and obj["fm"].get("type") != "concept_state":
                    errs.append(f"{tag} redefines.object 必须是 concept_state，"
                                f"实际 {obj['fm'].get('type')}")
            # 主库不得含候选
            if bucket == "main" and r.get("review_status") not in ("reviewed", "canonical"):
                errs.append(f"{tag} 主库记录 review_status={r.get('review_status')} "
                            f"（只允许 reviewed/canonical）")
            # 弱置信度不得进主库
            conf = r.get("confidence")
            if bucket == "main" and isinstance(conf, (int, float)) and conf < 0.5:
                errs.append(f"{tag} confidence={conf} < 0.5，不得进主库")
    return errs, warns


def check_source_trace(notes, rels):
    """L4 / synthesis 必须有 trace_status；断链必须显式标注。"""
    problems = []
    by_id = {n["fm"]["id"]: n for n in notes if n["fm"] and n["fm"].get("id")}
    for n in notes:
        fm = n["fm"]
        if not fm:
            continue
        t = fm.get("type")
        lvl = fm.get("authority_level")
        if t == "synthesis" or lvl == "L4":
            if not fm.get("trace_status"):
                problems.append(f"{n['rel']} L4/synthesis 缺 trace_status")
            if not fm.get("sources") and not fm.get("passages"):
                problems.append(f"{n['rel']} L4/synthesis 缺 sources 与 passages")
            if fm.get("review_status") == "canonical":
                problems.append(f"{n['rel']} L4 内容被标为 canonical —— 禁止")
        if t == "synthesis" and lvl != "L4":
            problems.append(f"{n['rel']} type=synthesis 的 authority_level 必须是 L4")
        # passage 引用必须存在
        for pid in fm.get("passages") or []:
            if pid not in by_id:
                problems.append(f"{n['rel']} 引用的 Passage 不存在: {pid}")
        # concept_state 必须有 period 与证据
        if t == "concept_state":
            if not fm.get("period"):
                problems.append(f"{n['rel']} concept_state 缺 period")
            if not fm.get("concept_id"):
                problems.append(f"{n['rel']} concept_state 缺 concept_id")
            else:
                c = by_id.get(fm["concept_id"])
                if c is None:
                    problems.append(f"{n['rel']} concept_id 指向不存在的概念: {fm['concept_id']}")
                elif c["fm"].get("type") != "concept":
                    problems.append(f"{n['rel']} concept_id 指向的不是 concept 类型")
    return problems


def check_duplicate_entities(notes):
    """同 type 内 canonical_name 唯一；别名碰撞提示。"""
    problems = []
    by_type_canon = defaultdict(list)
    for n in notes:
        fm = n["fm"]
        if not fm:
            continue
        cn = fm.get("canonical_name")
        if cn:
            by_type_canon[(fm.get("type"), cn.strip().lower())].append(n["rel"])
    for (t, cn), paths in by_type_canon.items():
        if len(paths) > 1:
            problems.append(f"canonical_name 冲突 [{t}] {cn!r}: {paths}")
    return problems


def check_orphan_concepts(notes, rels):
    """孤儿：没有任何 relation 指向或指向它，且没有 concept_state 的概念。"""
    by_id = {n["fm"]["id"]: n for n in notes if n["fm"] and n["fm"].get("id")}
    connected = set()
    for bucket in ("main", "candidate"):
        for r in rels[bucket]:
            connected.add(r.get("subject"))
            connected.add(r.get("object"))
    orphans = []
    for n in notes:
        fm = n["fm"]
        if not fm:
            continue
        if fm.get("type") == "concept":
            cid = fm["id"]
            states = fm.get("concept_states") or []
            if cid in connected:
                continue
            if states:
                continue
            orphans.append(f"{n['rel']} ({cid}) —— 无 relation 且无 concept_state")
    return orphans


# ================================================================== 测试
class VaultContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notes = load_vault(VAULT)
        cls.rels = load_relations(VAULT)
        cls.with_id = [n for n in cls.notes if n["fm"] and n["fm"].get("id")]

    # ---- 0 前置：确实读到了测试数据
    def test_00_fixtures_present(self):
        self.assertGreaterEqual(
            len(self.with_id), 15,
            f"vault 中带 id 的节点只有 {len(self.with_id)} 个，测试数据不足")
        self.assertTrue(self.rels["main"], "主库 relations 为空")
        self.assertTrue(self.rels["candidate"], "候选 relations 为空")

    # ---- 1 ID 唯一性
    def test_01_id_uniqueness(self):
        probs = check_id_uniqueness(self.notes)
        self.assertEqual(probs, [], f"ID 不唯一:\n" + "\n".join(probs))

    def test_01b_id_format_and_namespace(self):
        bad = []
        for n in self.with_id:
            fm = n["fm"]
            i, t = fm["id"], fm.get("type")
            if not ID_RE.match(i):
                bad.append(f"{n['rel']}: ID 形态非法 {i!r}")
                continue
            prefix = NAMESPACE_BY_TYPE.get(t)
            if prefix and not i.startswith(prefix):
                bad.append(f"{n['rel']}: type={t} 的 ID 应以 {prefix!r} 开头，实际 {i!r}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_01d_namespace_table_matches_schema_file(self):
        """本测试内的命名空间表必须与 id-namespaces.json 一致（防契约漂移）。

        这正是本轮真实踩到的坑：测试与 schema 各自维护一份命名空间，
        结果 concept_state 一处写 concept-state.、一处写 state.。
        """
        ns = load_namespace_file()
        if ns is None:
            self.skipTest("id-namespaces.json 不存在")
        drift = []
        for t, expected in NAMESPACE_BY_TYPE.items():
            got = ns.get(t)
            if got is None:
                drift.append(f"{t}: 未在 id-namespaces.json 中定义")
            elif got + "." != expected:
                drift.append(f"{t}: 测试={expected!r} vs schema={got + '.'!r}")
        # 反向：schema 里定义的 type 也必须在测试表里，否则校验会漏掉整类
        for t in ns:
            if t not in NAMESPACE_BY_TYPE:
                drift.append(f"{t}: 在 id-namespaces.json 中定义，但测试表未覆盖")
        self.assertEqual(drift, [], "命名空间契约漂移:\n" + "\n".join(drift))

    def test_01e_fixture_ids_match_namespace_patterns(self):
        """每个实体的 id 必须命中 id-namespaces.json 给该 type 的 pattern。

        这条与 validate_vault.py 独立：即使那个工具坏了，契约仍被守住。
        """
        import re as _re
        path = os.path.join(SCHEMAS, "id-namespaces.json")
        if not os.path.exists(path):
            self.skipTest("id-namespaces.json 不存在")
        with open(path, encoding="utf-8") as fh:
            et = json.load(fh).get("entity_types") or {}
        bad = []
        for n in self.with_id:
            fm = n["fm"]
            t, i = fm.get("type"), fm["id"]
            spec = et.get(t)
            if not spec or not spec.get("pattern"):
                bad.append(f"{i}: type={t} 无 namespace pattern")
                continue
            # JSON 里的 pattern 已是转义形态；直接用于 re 即可
            if not _re.match(spec["pattern"], i):
                bad.append(f"{i}: 不匹配 {t} 的 pattern {spec['pattern']}")
        self.assertEqual(bad, [], "ID 与命名空间 pattern 不符:\n" + "\n".join(bad))

    def test_01c_negative_id_collision_detected(self):
        """负例：人为造重复 ID，检查必须报错。"""
        n = dict(self.with_id[0])
        n2 = dict(n); n2["rel"] = "fake/dup.md"
        probs = check_id_uniqueness(self.with_id + [n2])
        self.assertTrue(probs, "重复 ID 未被检出（检查失效）")

    # ---- 2 YAML schema
    def test_02_schema_conformance(self):
        probs = check_schema(self.notes, os.path.join(SCHEMAS, "knowledge.schema.json"))
        probs = [p for p in probs if not str(p).startswith("SKIP")]
        self.assertEqual(probs, [], "Schema 校验失败:\n" + "\n".join(map(str, probs)))

    def test_02b_negative_schema_rejects_unknown_field(self):
        """负例：额外字段必须被 additionalProperties:false 拒绝。"""
        try:
            import jsonschema
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema 未安装")
        with open(os.path.join(SCHEMAS, "knowledge.schema.json"), encoding="utf-8") as fh:
            schema = json.load(fh)
        v = Draft202012Validator(schema)
        good = dict(self.with_id[0]["fm"])
        self.assertEqual(list(v.iter_errors(good)), [], "基准样本本身就不合法")
        bad = dict(good); bad["完全没定义的字段"] = "x"
        self.assertTrue(list(v.iter_errors(bad)), "未定义字段未被拒绝（字段封闭失效）")

    def test_02c_negative_schema_rejects_l4_canonical(self):
        """负例：synthesis 必须被强制为 L4，且 L4 不得标 canonical。"""
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema 未安装")
        with open(os.path.join(SCHEMAS, "knowledge.schema.json"), encoding="utf-8") as fh:
            schema = json.load(fh)
        v = Draft202012Validator(schema)
        synth = {
            "id": "synth.test", "type": "synthesis", "title": "t",
            "canonical_name": "t", "aliases": [], "language": "zh",
            "authority_level": "L1",  # ← 故意违规
            "review_status": "candidate", "status": "draft",
            "generated_by": "ai:test", "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z", "schema_version": "1.0.0",
            "trace_status": "COMPLETE", "sources": ["x.y"], "passages": ["a.b"],
        }
        self.assertTrue(list(v.iter_errors(synth)),
                        "synthesis 声明非 L4 却通过了校验（L4 强制失效）")

    # ---- 2e 「L4 永不 canonical」必须在 schema 层就堵死（对抗式审查抓到的旁路）
    def test_02e_l4_can_never_be_canonical(self):
        """`authority_level: L4` + `review_status: canonical` 必须被 schema 拒绝。

        缺陷来源（对抗式审查）：三份文档（ARCHITECTURE §3、KNOWLEDGE_SCHEMA §5、
        SOURCE_PROVENANCE）都承诺「L4 永不 canonical」，但 validator 里唯一的
        相关检查是「`generated_by` 以 `ai:` 开头且缺 `reviewed_by`」。于是只要
        `generated_by: "human:..."` 且填了 `reviewed_by`，一个 L4 节点就能以
        canonical 通过全部校验（实测 0 error / 0 warning）。

        这条是本库最核心的一条不变量：AI 综合永不成为馆藏定本。
        所以不能只在 validator 里加规则 —— 必须在**两侧**都堵：
        这里先证明 schema 侧拒绝，validator 侧另有 test_validate_vault 覆盖。
        """
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema 未安装")
        with open(os.path.join(SCHEMAS, "knowledge.schema.json"), encoding="utf-8") as fh:
            v = Draft202012Validator(json.load(fh))
        base = {
            "id": "concept.probe", "type": "concept", "title": "t",
            "canonical_name": "l4-probe", "aliases": [], "language": "zh",
            "status": "active", "generated_by": "human:someone",
            "reviewed_by": "human:someone",
            "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z", "schema_version": "1.0.0",
            "concept_states": ["state.probe.1964-1966"],
        }
        # 1) L4 + canonical → 必须失败（这正是被绕过的组合）
        bad = dict(base, authority_level="L4", review_status="canonical")
        self.assertTrue(
            list(v.iter_errors(bad)),
            "L4 + canonical 通过了 schema 校验 —— 「L4 永不 canonical」被绕过")
        # 2) L4 + reviewed → 允许（人可以复核 AI 内容，但不能把它变成定本）
        ok = dict(base, authority_level="L4", review_status="reviewed")
        self.assertEqual(
            [e.message for e in v.iter_errors(ok)], [],
            "L4 + reviewed 应当被允许")
        # 3) L1/L2/L3 + canonical → 允许
        for lvl in ("L1", "L2", "L3"):
            with self.subTest(level=lvl):
                good = dict(base, authority_level=lvl, review_status="canonical")
                self.assertEqual(
                    [e.message for e in v.iter_errors(good)], [],
                    f"{lvl} + canonical 应当被允许")

    # ---- 2d 类型专属条件规则（schema 的 allOf/if-then）必须真的生效
    def test_02d_type_specific_conditional_rules(self):
        """逐条探测 schema 的 if/then 规则 —— 不能只信「写了就算生效」。

        每条都成对：缺必需字段 → 必须失败；补齐 → 必须通过。
        只测「通过」那一半是查不出问题的（一个空的 then 也能通过）。
        """
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema 未安装")
        with open(os.path.join(SCHEMAS, "knowledge.schema.json"), encoding="utf-8") as fh:
            schema = json.load(fh)
        v = Draft202012Validator(schema)
        base = {
            "id": "x.y", "type": "passage", "title": "t", "canonical_name": "t",
            "aliases": [], "language": "fr", "authority_level": "L1",
            "review_status": "candidate", "status": "draft",
            "generated_by": "ai:test", "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z", "schema_version": "1.0.0",
        }
        passage_full = dict(base, seminar="S3", session_date="1955-01-01",
                            source_id="doc.x", structure_path="a/b",
                            page_from=1, page_to=1)
        synth_base = dict(base, type="synthesis", trace_status="COMPLETE",
                          sources=["a.b"], passages=["c.d"])
        probes = [
            ("passage 缺 6 个专属字段", dict(base), True),
            ("passage 补齐后通过", passage_full, False),
            ("concept 缺 concept_states", dict(base, type="concept"), True),
            ("concept 有 concept_states",
             dict(base, type="concept", concept_states=["state.x.1964-1966"]), False),
            ("concept_state 缺 concept_id/period",
             dict(base, type="concept_state"), True),
            ("synthesis 声明 L1（必须被强制 L4）",
             dict(synth_base, authority_level="L1"), True),
            ("synthesis 声明 L4", dict(synth_base, authority_level="L4"), False),
            ("session 缺 seminar/session_date", dict(base, type="session"), True),
            ("seminar 缺 seminar 字段", dict(base, type="seminar"), True),
            ("source 缺 source_type", dict(base, type="source"), True),
            ("session_date_precision 非法值",
             dict(base, type="seminar", seminar="S3",
                  session_date_precision="大概"), True),
            ("session 用 <year>-unknown 形态",
             dict(base, id="session.S3.1955-unknown", type="session",
                  seminar="S3", session_date="1955-01-01",
                  session_date_precision="year"), False),
        ]
        for name, obj, should_fail in probes:
            with self.subTest(probe=name):
                errors = list(v.iter_errors(obj))
                self.assertEqual(
                    bool(errors), should_fail,
                    f"{name}: 期望{'失败' if should_fail else '通过'}，"
                    f"实际{'失败' if errors else '通过'}"
                    + (f"（{errors[0].message[:120]}）" if errors else ""))

    # ---- 3 broken wikilinks
    def test_03_no_broken_wikilinks(self):
        broken, _ = check_wikilinks(self.notes, VAULT)
        self.assertEqual(broken, [], "断链:\n" + "\n".join(broken))

    def test_03b_negative_broken_wikilink_detected(self):
        """负例：故意指向不存在的笔记，检查必须报错。"""
        fake = [{"path": "x", "rel": "fake/note.md",
                 "fm": {"id": "concept.fake", "type": "concept"},
                 "body": "见 [[concept.根本不存在]] 与 [[不存在的笔记]]", "error": None}]
        broken, _ = check_wikilinks(fake + self.notes, VAULT)
        self.assertTrue(broken, "断链未被检出（检查失效）")

    # ---- 4 invalid relations
    def test_04_relations_valid(self):
        errs, _ = check_relations(self.rels, self.notes, VAULT)
        self.assertEqual(errs, [], "关系错误:\n" + "\n".join(errs))

    def test_04b_negative_bad_predicate_detected(self):
        """负例：自造谓词必须被拒。"""
        bad = {"main": [{
            "relation_id": "rel.bad", "subject": "concept.objet-a",
            "predicate": "随便编的谓词", "object": "term.fr.jouissance",
            "evidence": {"passage_id": [], "assertion_type": "inferred"},
            "confidence": 0.9, "review_status": "reviewed",
            "authority_level": "L1", "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z"}]}
        errs, _ = check_relations({**bad, "candidate": [], "rejected": []}, self.notes, VAULT)
        self.assertTrue(any("非法谓词" in e for e in errs), f"未拒绝自造谓词: {errs}")

    def test_04c_negative_explicit_without_evidence_detected(self):
        """负例：assertion_type=explicit 却没有 passage_id，必须被拒。"""
        bad = {"main": [{
            "relation_id": "rel.bad2", "subject": "concept.objet-a",
            "predicate": "related_to", "object": "term.fr.jouissance",
            "evidence": {"passage_id": [], "assertion_type": "explicit"},
            "confidence": 0.9, "review_status": "reviewed",
            "authority_level": "L1", "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z"}]}
        errs, _ = check_relations({**bad, "candidate": [], "rejected": []}, self.notes, VAULT)
        self.assertTrue(any("explicit 但无 passage_id" in e for e in errs), f"{errs}")

    def test_04d_negative_candidate_in_main_detected(self):
        """负例：候选不得混进主库。"""
        bad = {"main": [{
            "relation_id": "rel.bad3", "subject": "concept.objet-a",
            "predicate": "related_to", "object": "term.fr.jouissance",
            "evidence": {"passage_id": [], "assertion_type": "inferred"},
            "confidence": 0.2, "review_status": "candidate",
            "authority_level": "L4", "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z"}]}
        errs, _ = check_relations({**bad, "candidate": [], "rejected": []}, self.notes, VAULT)
        self.assertTrue(any("不得进主库" in e for e in errs), f"{errs}")
        self.assertTrue(any("只允许 reviewed/canonical" in e for e in errs), f"{errs}")

    def test_04e_negative_broken_relation_target_detected(self):
        """负例：指向不存在的实体必须被拒。"""
        bad = {"main": [{
            "relation_id": "rel.bad4", "subject": "concept.does-not-exist",
            "predicate": "related_to", "object": "term.fr.jouissance",
            "evidence": {"passage_id": [], "assertion_type": "inferred"},
            "confidence": 0.9, "review_status": "reviewed",
            "authority_level": "L1", "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z"}]}
        errs, _ = check_relations({**bad, "candidate": [], "rejected": []}, self.notes, VAULT)
        self.assertTrue(any("BROKEN_RELATION" in e for e in errs), f"{errs}")

    def test_04f_negative_redefines_wrong_target_detected(self):
        """负例：redefines 指向非 concept_state 必须被拒。"""
        bad = {"main": [{
            "relation_id": "rel.bad5", "subject": "concept.objet-a",
            "predicate": "redefines", "object": "term.fr.jouissance",
            "evidence": {"passage_id": [], "assertion_type": "inferred"},
            "confidence": 0.9, "review_status": "reviewed",
            "authority_level": "L1", "created_at": "2026-09-20T00:00:00Z",
            "updated_at": "2026-09-20T00:00:00Z"}]}
        errs, _ = check_relations({**bad, "candidate": [], "rejected": []}, self.notes, VAULT)
        self.assertTrue(any("redefines.object" in e for e in errs), f"{errs}")

    # ---- 5 source trace
    def test_05_source_trace_valid(self):
        probs = check_source_trace(self.notes, self.rels)
        self.assertEqual(probs, [], "溯源问题:\n" + "\n".join(probs))

    def test_05b_every_passage_id_resolves(self):
        """所有被引用的 Passage 必须真实存在。"""
        by_id = {n["fm"]["id"] for n in self.with_id}
        missing = []
        for bucket in ("main", "candidate"):
            for r in self.rels[bucket]:
                for pid in (r.get("evidence") or {}).get("passage_id") or []:
                    if pid not in by_id:
                        missing.append(f"{r.get('relation_id')} -> {pid}")
        for n in self.with_id:
            for pid in n["fm"].get("passages") or []:
                if pid not in by_id:
                    missing.append(f"{n['rel']} -> {pid}")
        self.assertEqual(missing, [], "引用了不存在的 Passage:\n" + "\n".join(missing))

    def test_05c_passage_files_exist_on_disk(self):
        """Passage 实体必须有对应的 Markdown 文件。"""
        for n in self.with_id:
            if n["fm"].get("type") == "passage":
                self.assertTrue(os.path.exists(n["path"]), f"{n['rel']} 不存在")

    def test_05d_negative_l4_canonical_detected(self):
        """负例：L4 标 canonical 必须被拒。"""
        fake = [{"path": "x", "rel": "fake/synth.md", "body": "", "error": None,
                 "fm": {"id": "synth.x", "type": "synthesis", "authority_level": "L4",
                        "review_status": "canonical", "sources": [], "passages": [],
                        "trace_status": "COMPLETE"}}]
        probs = check_source_trace(fake, {"main": [], "candidate": []})
        self.assertTrue(any("canonical" in p for p in probs), f"{probs}")

    def test_05e_negative_synthesis_not_l4_detected(self):
        fake = [{"path": "x", "rel": "fake/synth2.md", "body": "", "error": None,
                 "fm": {"id": "synth.y", "type": "synthesis", "authority_level": "L1",
                        "review_status": "candidate", "sources": ["a.b"],
                        "passages": ["c.d"], "trace_status": "COMPLETE"}}]
        probs = check_source_trace(fake, {"main": [], "candidate": []})
        self.assertTrue(any("必须是 L4" in p for p in probs), f"{probs}")

    def test_05f_concept_state_requires_period_and_concept(self):
        """concept_state 必须绑定 period 与 concept_id。"""
        fake = [{"path": "x", "rel": "fake/cs.md", "body": "", "error": None,
                 "fm": {"id": "state.x.1964-1966", "type": "concept_state",
                        "concept_id": "concept.根本不存在"}}]
        probs = check_source_trace(fake, {"main": [], "candidate": []})
        self.assertTrue(any("缺 period" in p for p in probs), f"{probs}")
        self.assertTrue(any("不存在" in p for p in probs), f"{probs}")

    # ---- 6 duplicate entities
    def test_06_no_duplicate_entities(self):
        probs = check_duplicate_entities(self.notes)
        self.assertEqual(probs, [], "重复实体:\n" + "\n".join(probs))

    def test_06b_negative_duplicate_canonical_name_detected(self):
        fake = [
            {"path": "a", "rel": "a.md", "body": "", "error": None,
             "fm": {"id": "concept.aa", "type": "concept", "canonical_name": "Same Name"}},
            {"path": "b", "rel": "b.md", "body": "", "error": None,
             "fm": {"id": "concept.bb", "type": "concept", "canonical_name": "same name"}},
        ]
        probs = check_duplicate_entities(fake)
        self.assertTrue(probs, "canonical_name 冲突未被检出")

    # ---- 7 orphan concepts
    def test_07_orphan_concepts(self):
        orphans = check_orphan_concepts(self.notes, self.rels)
        self.assertEqual(orphans, [], "孤儿概念:\n" + "\n".join(orphans))

    def test_07b_negative_orphan_detected(self):
        fake = [{"path": "x", "rel": "fake/orphan.md", "body": "", "error": None,
                 "fm": {"id": "concept.孤儿", "type": "concept", "concept_states": []}}]
        orphans = check_orphan_concepts(fake, {"main": [], "candidate": []})
        self.assertTrue(orphans, "孤儿概念未被检出")

    # ---- 8 概念两层结构
    def test_08_concept_has_states(self):
        """每个 concept 都必须有 concept_states，且每个 state 真实存在。"""
        by_id = {n["fm"]["id"]: n for n in self.with_id}
        for n in self.with_id:
            fm = n["fm"]
            if fm.get("type") != "concept":
                continue
            states = fm.get("concept_states") or []
            with self.subTest(concept=fm["id"]):
                self.assertTrue(states, f"{fm['id']} 没有任何 concept_state")
                for s in states:
                    self.assertIn(s, by_id, f"{fm['id']} 指向不存在的 state {s}")
                    self.assertEqual(by_id[s]["fm"].get("type"), "concept_state")
                    self.assertEqual(by_id[s]["fm"].get("concept_id"), fm["id"],
                                     f"{s} 的 concept_id 反向不一致")

    def test_08b_concept_body_has_no_definition_section(self):
        """结构约束：概念本体不得承载定义（只能有状态表与别名）。"""
        offenders = []
        for n in self.with_id:
            fm = n["fm"]
            if fm.get("type") != "concept":
                continue
            body = n["body"]
            for bad in ("## 定义", "## Definition", "# 定义"):
                if bad in body:
                    offenders.append(f"{n['rel']} 含 {bad!r}")
        self.assertEqual(offenders, [],
                         "概念本体出现定义区块（违反两层结构）:\n" + "\n".join(offenders))

    # ---- 9 用户硬约束：源目录未被触碰
    def test_09_source_corpus_untouched(self):
        """源目录只读：inventory 声明的 143 个文件必须仍在。"""
        inv_path = os.path.join(VAULT, "_data", "corpus_inventory.json")
        self.assertTrue(os.path.exists(inv_path), "缺少 corpus_inventory.json")
        with open(inv_path, encoding="utf-8") as fh:
            inv = json.load(fh)
        self.assertTrue(inv.get("source_readonly"), "inventory 未声明只读")
        missing = [r["rel_path"] for r in inv["records"]
                   if not os.path.exists(r["path"])]
        self.assertEqual(missing, [],
                         f"{len(missing)} 个源文件消失:\n" + "\n".join(missing[:10]))

    # ---- 11 引文逐字保真（本项目的核心承诺）
    QUOTE_SOURCES = {
        "passage.ST1.unknown.L01.P0010": {
            "fixture": "S3 PSYCHOSES.pdf",
            "pdf_page_index": 9,          # PDF 第 10 页（0-based 9）
            "heading": "## 引文（法文，逐字）",
        },
    }

    def test_11_quotes_are_verbatim(self):
        """笔记里的法文引文必须与底本 PDF 逐字符一致。

        为什么必须测这个：引文保真是整个系统的存在理由。本测试第一版运行时
        真的抓到一处缺陷 —— 引文用了 ASCII 直引号 `'`，而底本用的是排版撇号 `’`。
        看起来一样，逐字符不一样；对引用系统来说这是缺陷，不是格式差异。

        刻意**不做**撇号/引号归一化：归一化会把缺陷洗成通过。
        """
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf 未安装")

        def norm(s):
            return re.sub(r"[\s\u2028\u2029]+", " ", s.replace("\u00a0", " ")).strip()

        for rel, spec in self.QUOTE_SOURCES.items():
            with self.subTest(passage=rel):
                note = next((n for n in self.with_id
                             if n["fm"].get("id") == rel), None)
                self.assertIsNotNone(note, f"找不到节点 {rel}")
                m = re.search(
                    re.escape(spec["heading"]) + r"\s*\n\s*>\s*(.+)", note["body"])
                self.assertIsNotNone(m, f"{rel} 中没有找到引文块")
                quote = norm(m.group(1))
                pdf = os.path.join(VAULT, "00_System", "_fixtures", spec["fixture"])
                self.assertTrue(os.path.exists(pdf), f"缺底本 {pdf}")
                page = norm(PdfReader(pdf, strict=False)
                            .pages[spec["pdf_page_index"]].extract_text() or "")
                frags = [f.strip() for f in re.split(r"\s+-\s+", quote)
                         if len(f.strip()) > 20]
                self.assertTrue(frags, f"{rel} 引文太短，无法核对")
                bad = [f for f in frags if f not in page]
                self.assertEqual(
                    bad, [],
                    f"{rel} 的引文与底本 {spec['fixture']} 不一致（逐字符比对）:\n"
                    + "\n".join("  ✗ " + b[:90] for b in bad))

    def test_10_fixture_hashes_match_inventory(self):
        """fixture 必须与 inventory 中记录的 sha256 一致。"""
        import hashlib
        man_path = os.path.join(VAULT, "00_System", "_fixtures", "manifest.json")
        with open(man_path, encoding="utf-8") as fh:
            man = json.load(fh)
        with open(os.path.join(VAULT, "_data", "corpus_inventory.json"),
                  encoding="utf-8") as fh:
            inv = json.load(fh)
        by_rel = {r["rel_path"]: r["sha256"] for r in inv["records"]}
        for f in man["fixtures"]:
            with self.subTest(f=f["fixture_file"]):
                self.assertEqual(by_rel.get(f["origin_rel_path"]), f["origin_sha256"],
                                 "fixture 记录的 hash 与 inventory 不一致")
                p = os.path.join(VAULT, "00_System", "_fixtures", f["fixture_file"])
                self.assertTrue(os.path.exists(p), f"fixture 缺失: {p}")
                with open(p, "rb") as fh:
                    actual = hashlib.sha256(fh.read()).hexdigest()
                self.assertEqual(actual, f["origin_sha256"],
                                 "fixture 文件内容与声明 hash 不符")


if __name__ == "__main__":
    unittest.main(verbosity=2)
