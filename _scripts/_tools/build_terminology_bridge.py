#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_terminology_bridge.py — Phase 3C §5–§6 Cross-lingual Terminology Bridge

X 从「临时 preprocessing hack」升为**一级检索组件**，因此它需要自己的
schema / index / API，而不是散在 benchmark 里的几行代码。

    _data/terminology_bridge.jsonl   映射表（可 diff、入 Git）
    terminology_bridge.py            读取 + API（expand / distinct_from / audit）

每条 mapping 的 11 个必需字段（§5）
──────────────────────────────────
term_id · source_form · source_language · target_form · target_language ·
entity_id · relation_type · status · review_status · source · notes

`relation_type` 只有两种取值
────────────────────────────
* `equivalent` —— **同一个 entity_id** 的跨语言写法。
  这是 X 唯一允许用来做查询扩展的关系。
* `distinct_from` —— **必须区分**的配对（§6 的 Autre/autre、Réel/réalité …）。
  它们**不是**翻译，而是「不得等同」的显式声明。X **永远不得**用它们扩展查询；
  Semantic Guard 用它们来判定「这条 query 涉及需要分道的概念」。

★ §6 要求 X 依赖 **entity identity** 而不是字符串翻译。本脚本把这一条变成可核的规则：
    只有 `relation_type == equivalent` 且两侧 `entity_id` 相同的记录才生成；
    任何只靠字符串相似而没有同一 entity 的候选，一律**不生成 equivalent**。

本轮实测到一个必须写进报告的事实
────────────────────────────────
§6 点名的 7 组配对里，**只有一对两侧都有 entity，而且两侧落到同一个 entity**：

| 配对 | 一侧 entity | 另一侧 entity |
|---|---|---|
| Autre / autre | `concept.l-autre` | `concept.l-autre` ← **同一个** |
| Réel / réalité | `concept.le-reel` | **无 entity** |
| désir / demande | `concept.desir` | **无 entity** |
| besoin / demande | **无 entity** | **无 entity** |
| objet / objet a | **无 entity** | `concept.objet-petit-a` |
| sujet / moi | `concept.sujet` | **无 entity** |
| signifiant / signifié | `concept.signifiant`（+ `concept.le-symbolique` 歧义） | **无 entity** |

**也就是说：通用 embedding 之所以会压平这些区分，一部分原因是知识库自己
也没有为其中一侧建立实体。** 这个事实必须出现在报告里 ——
把责任全推给 embedding 是不诚实的。Guard 的做法不是假装能区分，
而是**拒绝等同 + 显式报 `ENTITY_COLLISION` / `COUNTERPART_ENTITY_MISSING`**。

用法
────
    python3 _scripts/_tools/build_terminology_bridge.py --build
    python3 _scripts/_tools/build_terminology_bridge.py --audit
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
OUT = os.path.join(VAULT, "_data", "terminology_bridge.jsonl")
AUDIT = os.path.join(VAULT, "_data", "terminology_bridge_audit.json")

CONCEPTS = os.path.join(STORE, "concepts.jsonl")
ALIASES = os.path.join(VAULT, "_data", "index", "alias_index.jsonl")

CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
LATIN = re.compile(r"[A-Za-z]")
# 法语特有的判别线索（用于把 alias 分到 fr / en）
FR_MARK = re.compile(r"[àâäéèêëîïôöùûüçœæ]|\b(le|la|les|du|des|un|une|l|d)\b", re.I)

# §6 点名必须区分的配对。relation_type 一律 `distinct_from`。
CONTRASTIVE_PAIRS = [
    ("Autre", "autre", "l'Autre（大他者）vs l'autre（小他者/他人）"),
    ("Réel", "réalité", "le Réel（实在界）vs la réalité（现实）"),
    ("désir", "demande", "désir（欲望）vs demande（要求）"),
    ("besoin", "demande", "besoin（需要）vs demande（要求）"),
    ("objet", "objet a", "objet（一般对象）vs objet petit a（对象 a）"),
    ("sujet", "moi", "sujet（主体）vs moi（自我）"),
    ("signifiant", "signifié", "signifiant（能指）vs signifié（所指）"),
]


def fold(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s.lower()).strip()


def detect_lang(form):
    if not form or not str(form).strip():
        return None
    s = str(form)
    if CJK.search(s):
        return "zh"
    if LATIN.search(s):
        return "fr" if FR_MARK.search(s) else "und"
    return "und"


def load_concepts():
    out = {}
    with open(CONCEPTS, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                out[c["id"]] = c
    return out


def load_alias_entities():
    """folded alias → set(entity_id)，用于判定某一侧到底绑到哪些 entity。"""
    m = {}
    with open(ALIASES, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                m.setdefault(fold(r["alias"]), set()).add(r["entity_id"])
    return m


def build():
    concepts = load_concepts()
    alias_map = load_alias_entities()
    rows = []

    # ── ① equivalent：同一 entity 内的跨语言写法
    for eid, c in sorted(concepts.items()):
        # 显式语言字段是**权威**来源（不是猜的）
        forms = {}
        for lang_field, lang in (("zh", "zh"), ("fr", "fr"), ("en", "en")):
            v = c.get(lang_field)
            if isinstance(v, str) and v.strip():
                for part in re.split(r"[/／|]", v):
                    part = part.strip()
                    if part and len(fold(part)) >= 2:
                        forms.setdefault(lang, set()).add(part)
        # aliases：语言靠启发式判定，标记 language_source
        for a in (c.get("aliases") or []):
            if isinstance(a, str) and len(fold(a)) >= 2:
                lg = detect_lang(a)
                if lg:
                    forms.setdefault(lg, set()).add(a.strip())
        langs = sorted(forms)
        n = 0
        for sl in langs:
            for tl in langs:
                if sl == tl:
                    continue
                for sf in sorted(forms[sl]):
                    for tf in sorted(forms[tl]):
                        n += 1
                        rows.append({
                            "schema_version": "terminology-bridge/v1",
                            "term_id": "tb.%s.%s.%s.%03d" % (eid.split(".", 1)[1],
                                                             sl, tl, n),
                            "source_form": sf,
                            "source_language": sl,
                            "target_form": tf,
                            "target_language": tl,
                            "entity_id": eid,
                            "relation_type": "equivalent",
                            "status": "active",
                            "review_status": "candidate",
                            "source": "concept_store:%s" % eid,
                            "notes": ("由 concept 卡片的显式 %s/%s 字段或 aliases 推出的**同一 entity**"
                                      "跨语言写法。X 的查询扩展只允许用这一类记录。"
                                      % (sl, tl)),
                        })

    # ── ② distinct_from：§6 点名必须区分、**不得等同**的配对
    for i, (a, b, why) in enumerate(CONTRASTIVE_PAIRS, 1):
        ea = sorted(alias_map.get(fold(a), set()))
        eb = sorted(alias_map.get(fold(b), set()))
        if ea and eb and set(ea) & set(eb):
            binding = "ENTITY_COLLISION"
            eid = ea[0]
        elif ea and eb:
            binding = "BOTH_BOUND_DISTINCT"
            eid = None
        elif ea or eb:
            binding = "COUNTERPART_ENTITY_MISSING"
            eid = (ea or eb)[0]
        else:
            binding = "BOTH_ENTITIES_MISSING"
            eid = None
        rows.append({
            "schema_version": "terminology-bridge/v1",
            "term_id": "tb.distinct.%02d" % i,
            "source_form": a,
            "source_language": detect_lang(a) or "fr",
            "target_form": b,
            "target_language": detect_lang(b) or "fr",
            "entity_id": eid,
            "relation_type": "distinct_from",
            "status": "active",
            "review_status": "candidate",
            "source": "phase3c:semantic_guard",
            "notes": ("**必须区分，不得等同**：%s。X 永远不得用这条记录扩展查询。"
                      "entity_binding=%s；side_a_entities=%s；side_b_entities=%s"
                      % (why, binding, ea or "none", eb or "none")),
            "entity_binding": binding,
            "side_a_entities": ea,
            "side_b_entities": eb,
            "distinction_rationale": why,
        })

    # 确定性排序
    rows.sort(key=lambda r: (r["relation_type"], r["term_id"]))
    with open(OUT, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    eq = [r for r in rows if r["relation_type"] == "equivalent"]
    df = [r for r in rows if r["relation_type"] == "distinct_from"]
    audit = {
        "schema_version": "terminology-bridge-audit/v1",
        "rows": len(rows),
        "equivalent_rows": len(eq),
        "distinct_from_rows": len(df),
        "entities_covered": len({r["entity_id"] for r in eq}),
        "languages": sorted({r["source_language"] for r in eq} |
                            {r["target_language"] for r in eq}),
        "language_pairs": sorted({(r["source_language"], r["target_language"]) for r in eq}),
        "contrastive_binding": {
            r["term_id"]: {"pair": [r["source_form"], r["target_form"]],
                           "binding": r["entity_binding"],
                           "side_a_entities": r["side_a_entities"],
                           "side_b_entities": r["side_b_entities"]}
            for r in df},
        "★finding": {
            "statement": ("§6 点名的 7 组配对里，**只有 Autre/autre 两侧都有 entity，"
                          "而且两侧落到同一个 entity**；其余 6 组至少一侧没有 entity。"),
            "implication": ("通用 embedding 压平这些区分，**部分原因是知识库自己没有"
                            "为其中一侧建实体**。不能把责任全推给 embedding。"),
            "guard_response": ("Guard 不假装能区分：它**拒绝等同**并显式报 "
                               "ENTITY_COLLISION / COUNTERPART_ENTITY_MISSING。"),
        },
        "hash": hashlib.sha256(open(OUT, "rb").read()).hexdigest(),
    }
    json.dump(audit, open(AUDIT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[bridge] %d 条（equivalent %d / distinct_from %d），覆盖 %d 个 entity，语言 %s"
          % (len(rows), len(eq), len(df), audit["entities_covered"], audit["languages"]))
    for tid, v in audit["contrastive_binding"].items():
        print("   %-16s %-22s %s" % (tid, "/".join(v["pair"]), v["binding"]))
    return audit


DOC = os.path.join(VAULT, "TERMINOLOGY_BRIDGE.md")


def write_doc():
    """§23 交付物：TERMINOLOGY_BRIDGE.md"""
    a = json.load(open(AUDIT, encoding="utf-8"))
    rows = [json.loads(l) for l in open(OUT, encoding="utf-8") if l.strip()]
    A = []
    A.append("# TERMINOLOGY_BRIDGE.md — Phase 3C §5–§6 Cross-lingual Terminology Bridge\n")
    A.append("> 构建：`_scripts/_tools/build_terminology_bridge.py`　·　"
             "读取 API：`_scripts/_tools/terminology_bridge.py`　·　"
             "数据：`_data/terminology_bridge.jsonl`\n")
    A.append("## 0. X 不再是 preprocessing hack\n")
    A.append("Phase 3B.2 实测：跨语言检索的主要有效增益来自 `X`，不是纯 embedding。"
             "因此 3C 把它升为**一级检索组件**：自己的 schema、自己的文件、自己的 API、"
             "自己的审计，而不是散在 benchmark 里的几行代码。\n")
    A.append("| 项 | 值 |")
    A.append("|---|---:|")
    A.append("| 映射条数 | **%d** |" % a["rows"])
    A.append("| `equivalent`（可扩展查询） | **%d** |" % a["equivalent_rows"])
    A.append("| `distinct_from`（**禁止**等同） | **%d** |" % a["distinct_from_rows"])
    A.append("| 覆盖 entity | **%d** |" % a["entities_covered"])
    A.append("| 语言 | %s |" % ", ".join(a["languages"]))
    A.append("")
    A.append("## 1. Schema：每条 11 个必需字段（§5）\n")
    A.append("`term_id` · `source_form` · `source_language` · `target_form` · "
             "`target_language` · `entity_id` · `relation_type` · `status` · "
             "`review_status` · `source` · `notes`\n")
    A.append("示例（equivalent）：\n")
    ex = next(r for r in rows if r["relation_type"] == "equivalent")
    A.append("```json")
    A.append(json.dumps({k: ex[k] for k in
                         ("term_id", "source_form", "source_language", "target_form",
                          "target_language", "entity_id", "relation_type", "status",
                          "review_status", "source")}, ensure_ascii=False, indent=1))
    A.append("```\n")
    A.append("## 2. `relation_type` 只有两种，规则写进代码\n")
    A.append("| 取值 | 含义 | X 能否用它扩展查询 |")
    A.append("|---|---|---|")
    A.append("| `equivalent` | **同一个 `entity_id`** 的跨语言写法 | ✅ **只有它可以** |")
    A.append("| `distinct_from` | **必须区分、不得等同**的配对 | ❌ **结构性排除** |")
    A.append("")
    A.append("`terminology_bridge.expand()` 只遍历 `equivalent` 记录 —— "
             "不是靠调用方记得不要用 `distinct_from`，而是**这个函数根本不返回它们**。\n")
    A.append("## 3. §6：依赖 entity identity，不是字符串翻译\n")
    A.append("`equivalent` 的生成条件是**两侧 `entity_id` 相同**。"
             "任何只靠字符串相似、没有同一 entity 的候选，**一律不生成 equivalent**。\n")
    A.append("### 3.1 ★ 本轮查出来的事实（必须写进报告）\n")
    A.append("| 配对 | 一侧 entity | 另一侧 entity | 绑定状态 |")
    A.append("|---|---|---|---|")
    seen = set()
    for r in rows:
        if r["relation_type"] != "distinct_from":
            continue
        seen.add(r["term_id"])
        A.append("| `%s` / `%s` | %s | %s | **%s** |" % (
            r["source_form"], r["target_form"],
            ", ".join("`%s`" % x for x in (r.get("side_a_entities") or [])) or "**无**",
            ", ".join("`%s`" % x for x in (r.get("side_b_entities") or [])) or "**无**",
            r.get("entity_binding")))
    A.append("")
    A.append("**只有 `Autre/autre` 两侧都有 entity，而且两侧落到同一个 entity；"
             "其余 6 组至少一侧没有 entity。**\n")
    A.append("这条事实的含义：**通用 embedding 压平这些区分，一部分原因是知识库自己"
             "也没有为其中一侧建立实体。** 把责任全推给 embedding 是不诚实的。"
             "真正的修法是**补概念实体（知识工程）**，而不是换更大的模型。\n")
    A.append("## 4. API\n")
    A.append("```python")
    A.append("import terminology_bridge as tb")
    A.append("tb.expand('小客体a', target_langs=('fr',))  # → [(target_form, entity_id, term_id)]")
    A.append("tb.distinct_pairs()                        # §6 的 7 组「必须区分」")
    A.append("tb.is_distinct('Autre', 'autre')           # → True")
    A.append("tb.lexical_forms_for_entity(eid)           # 该 entity 的全部 surface forms")
    A.append("```\n")
    A.append("## 5. 审计\n")
    A.append("```bash")
    A.append("python3 _scripts/_tools/build_terminology_bridge.py --audit")
    A.append("```")
    A.append("")
    A.append("审计会检查：任一配对**不得同时**是 `equivalent` 与 `distinct_from`；"
             "文件 hash 与 audit 记录一致；`distinct_from` 条数必须等于 §6 点名的 7 组。\n")
    A.append("## 6. 边界\n")
    A.append("- `equivalent` 的 `review_status = candidate` —— **没有人工逐条审阅**，"
             "它由 concept 卡片的显式字段推导。")
    A.append("- 别名语言靠启发式判定（`fr` 标记 / CJK 检测），`source_language` 的"
             "可靠性低于 concept 卡片的显式 `zh`/`fr`/`en` 字段。")
    A.append("- 它**不解决**知识库的 entity 合并问题 —— 那是 §7 Guard 报 "
             "`ENTITY_COLLISION` 的事。")
    with open(DOC, "w", encoding="utf-8") as f:
        f.write("\n".join(A) + "\n")
    print("[bridge] %s" % DOC)


def cmd_audit():
    if not os.path.isfile(AUDIT):
        return {"status": "FAIL", "problems": ["缺 terminology_bridge_audit.json"]}
    a = json.load(open(AUDIT, encoding="utf-8"))
    problems = []
    if a["equivalent_rows"] == 0:
        problems.append("没有任何 equivalent 映射 —— X 无东西可用")
    if a["distinct_from_rows"] != len(CONTRASTIVE_PAIRS):
        problems.append("distinct_from 条数不是 %d" % len(CONTRASTIVE_PAIRS))
    if os.path.isfile(OUT) and hashlib.sha256(open(OUT, "rb").read()).hexdigest() != a["hash"]:
        problems.append("bridge 文件与 audit 记录的 hash 不符")
    # 硬规则：distinct_from 绝不能同时是 equivalent
    rows = [json.loads(l) for l in open(OUT, encoding="utf-8") if l.strip()]
    seen = {}
    for r in rows:
        k = (fold(r["source_form"]), fold(r["target_form"]))
        seen.setdefault(k, set()).add(r["relation_type"])
    both = [k for k, v in seen.items() if len(v) > 1]
    if both:
        problems.append("同一配对既是 equivalent 又是 distinct_from：%s" % both[:3])
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "equivalent_rows": a["equivalent_rows"],
            "distinct_from_rows": a["distinct_from_rows"],
            "entities_covered": a["entities_covered"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--build", action="store_true")
    g.add_argument("--audit", action="store_true")
    g.add_argument("--doc", action="store_true")
    a = ap.parse_args(argv)
    if a.build:
        build()
        write_doc()
        return 0
    if a.doc:
        write_doc()
        return 0
    r = cmd_audit()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
