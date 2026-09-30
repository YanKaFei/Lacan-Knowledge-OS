#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lacanian_semantic_guard.py — Phase 3C §7 LacanianSemanticGuard

问题
────
通用 embedding 会把理论上**必须区分**的近义项压平。实测 contrastive benchmark
10 组只过 4/10。§7 明确禁止「调高 embedding 权重把问题盖住」——
所以这里做的不是调参，而是**在检索结构上阻止合并**。

Guard 做三件事
──────────────
1. **识别**：query 是否同时涉及某一组 contrastive pair 的两侧。
2. **分道**：一旦识别，要求**每个概念一条独立 lane**（§8），
   且每条的 lane query **显式排除另一侧的写法** —— 这就是「不合并」的机制，
   而不是事后 rerank。
3. **如实报警**：本库实测发现 §6 的 7 组配对里
   **只有 Autre/autre 两侧都有 entity 且落到同一个 entity**，其余至少一侧没有 entity。
   Guard 不假装能区分，它报 `ENTITY_COLLISION` / `COUNTERPART_ENTITY_MISSING`，
   把「知识库自己也没建实体」这件事摆到台面上。

为什么这是「降低混淆」而不是「掩盖混淆」
────────────────────────────────────────
分道之后，两个概念的候选**在各自 lane 内排序**，最后才在 Evidence Assembly 层
并列比较。任何跨 lane 的混入都是可检测的（lane 归属写在 evidence entry 上）。
所以「System Contrastive Pass」是可以被独立测量的 —— 见
`ROUTED_RETRIEVAL_EVALUATION.md`。

用法
────
    python3 _scripts/_tools/lacanian_semantic_guard.py --demo "Réel 和 réalité 有什么区别？"
    python3 _scripts/_tools/lacanian_semantic_guard.py --pairs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import terminology_bridge as tb  # noqa: E402

OUT_MD = os.path.join(VAULT, "LACANIAN_SEMANTIC_GUARD.md")

# 分道时视为「同一侧」的判别阈值
MIN_FORM_LEN = 3


def fold(s):
    return tb.fold(s)


def _mentions(query, form, case_sensitive=False):
    """query 是否提到某个表面形式。

    * 拉丁文字要求**词边界**（否则 `autre` 会在 `l'Autre` 里假命中，
      而那恰好是这组配对最要命的地方）；CJK 用子串。
    * `case_sensitive=True` 用于**两侧 fold 后相同**的配对（`Autre`/`autre`）：
      这时只有大小写能区分「用户说的是哪一个」。实测这就是本库唯一
      两侧绑到同一 entity 的那一组 —— 必须在措辞上尽力分辨。
    """
    if case_sensitive:
        f = str(form or "").strip()
        if len(f) < MIN_FORM_LEN:
            return False
        if re.search(r"[\u4e00-\u9fff]", f):
            return f in str(query)
        return re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(f),
                         str(query)) is not None
    q = fold(query)
    f = fold(form)
    if not f or len(f) < MIN_FORM_LEN:
        return False
    if re.search(r"[\u4e00-\u9fff]", f):
        return f in q
    return re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(f), q) is not None


def _independent_occurrence(query, form, other):
    """form 是否在 query 里有**不被 other 的匹配包含**的出现。"""
    q = str(query)
    f, o = fold(form), fold(other)
    if not f:
        return False
    if f == o:
        return False
    if f not in o and o not in f:
        return True
    if o in f:
        return True
    stripped = re.sub(re.escape(o), " ", q.lower())
    return bool(re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(f), stripped))


def _suppress_containment(query, a, b, hit_a, hit_b):
    fa, fb = fold(a), fold(b)
    if not (hit_a and hit_b) or fa == fb:
        return hit_a, hit_b
    if fa in fb:
        return _independent_occurrence(query, a, b), hit_b
    if fb in fa:
        return hit_a, _independent_occurrence(query, b, a)
    return hit_a, hit_b


def analyze(query, plan=None):
    """→ GuardDecision（纯函数，无副作用，可被 router / benchmark 复用）。"""
    pairs, lanes, warnings = [], [], []

    for r in tb.distinct_pairs():
        a, b = r["source_form"], r["target_form"]
        same_folded = fold(a) == fold(b)
        # 两侧 fold 相同（Autre/autre）→ 只能靠大小写分辨；否则用折叠匹配
        hit_a = _mentions(query, a, case_sensitive=same_folded)
        hit_b = _mentions(query, b, case_sensitive=same_folded)
        # ★ 包含关系抑制：若一侧的写法**完全被另一侧包含**（如 objet ⊂ objet a），
        #   它在 query 里的出现只是子串假象，不算"两侧都提到"。
        #   否则「什么是 objet a？」会被误判成对比问题，进而错误分道。
        hit_a, hit_b = _suppress_containment(query, a, b, hit_a, hit_b)
        if not (hit_a or hit_b):
            continue
        binding = r.get("entity_binding", "UNKNOWN")
        entry = {
            "term_id": r["term_id"],
            "pair": [a, b],
            "side_a_present": hit_a,
            "side_b_present": hit_b,
            "both_sides_present": hit_a and hit_b,
            "entity_binding": binding,
            "side_a_entities": r.get("side_a_entities") or [],
            "side_b_entities": r.get("side_b_entities") or [],
            "rationale": r.get("distinction_rationale"),
            "surface_indistinguishable": bool(same_folded),
        }
        pairs.append(entry)
        if binding == "ENTITY_COLLISION":
            warnings.append({
                "code": "ENTITY_COLLISION",
                "pair": [a, b],
                "message": ("知识库把「%s」与「%s」绑到了**同一个 entity**（%s）—— "
                            "也就是说**在数据层就没有区分**。Guard 只能阻止检索阶段合并，"
                            "区分本身需要先补概念实体。" % (a, b, r.get("entity_id"))),
                "severity": "high",
                "action": "禁止 equivalent 扩展；两条 lane 以**表面形式**为键独立检索",
            })
        elif binding == "COUNTERPART_ENTITY_MISSING":
            missing = b if entry["side_a_entities"] else a
            warnings.append({
                "code": "COUNTERPART_ENTITY_MISSING",
                "pair": [a, b],
                "message": ("「%s」在知识库里**没有对应的 concept entity** —— "
                            "只有一侧可绑。Guard 不会用字符串相似去替它造等价关系。"
                            % missing),
                "severity": "medium",
                "action": "缺失侧的 lane 只用它的表面形式，并标记 unbound_side",
            })
        elif binding == "BOTH_ENTITIES_MISSING":
            warnings.append({
                "code": "BOTH_ENTITIES_MISSING",
                "pair": [a, b],
                "message": "两侧都没有 concept entity —— 这组区分完全依赖表面形式。",
                "severity": "medium",
                "action": "两条 lane 都用表面形式；不生成任何 equivalent",
            })

        # ── 建 lane：每侧一条，且**显式排除另一侧的写法**
        # 若两侧折叠后相同（Autre/autre），建两条一模一样的 lane 只会制造噪声：
        # 真正的结论是「知识库在数据层就没区分」，交给 ENTITY_COLLISION 报警。
        # 只有用户**显式写出两种大小写**（如「l'Autre 与 l'autre 有什么区别」）
        # 才说明他在问「这两者的区别」，这时才分道。
        if same_folded and not (hit_a and hit_b):
            pair_note = "surface_indistinguishable_single_lane"
            pairs[-1]["lane_decision"] = pair_note
        elif hit_a or hit_b:
            for side_idx, (form, hits, ents, other_form, other_ents) in enumerate((
                    (a, hit_a, entry["side_a_entities"], b, entry["side_b_entities"]),
                    (b, hit_b, entry["side_b_entities"], a, entry["side_a_entities"]))):
                if not hits:
                    continue
                exclude = {fold(other_form)}
                for e in other_ents:
                    exclude |= {fold(x) for x in tb.lexical_forms_for_entity(e)}
                forms = {form}
                for e in ents:
                    # 同一 entity 的别名**减去**另一侧的写法 —— 这一步就是防压平
                    forms |= {x for x in tb.lexical_forms_for_entity(e)
                              if fold(x) not in exclude}
                lanes.append({
                    "lane_id": "%s.%s" % (r["term_id"], "ab"[side_idx]),
                    "pair_term_id": r["term_id"],
                    "surface_form": form,
                    "entity_ids": ents,
                    "entity_bound": bool(ents),
                    "query_forms": sorted(forms),
                    "excluded_forms": sorted(exclude),
                    "exclusion_reason": ("另一侧的写法（及其他/同一 entity 的对应写法）"
                                         "不得进入本 lane，否则两侧会在 lane 内重新混合"),
                })

    both = [p for p in pairs if p["both_sides_present"]]
    if both:
        risk = "high" if any(p["entity_binding"] == "ENTITY_COLLISION" for p in both) else "medium"
    elif pairs:
        risk = "low"
    else:
        risk = "none"

    return {
        "guard_version": "lacanian-semantic-guard/v1",
        "query": query,
        "contrastive_pairs_detected": pairs,
        "both_sides_present": len(both),
        "lanes": lanes,
        "lanes_required": len(lanes),
        "flattening_risk": risk,
        "warnings": warnings,
        "vector_policy": ("per_lane" if lanes else "allowed"),
        "merge_policy": ("FORBID_MERGE：涉及 contrastive 概念时**不得**把两个概念"
                         "合成一个 embedding query") if lanes else "normal",
        "can_distinguish": all(p["entity_binding"] != "ENTITY_COLLISION" for p in pairs)
        if pairs else None,
    }


def cmd_pairs():
    rows = tb.distinct_pairs()
    print(json.dumps([{k: r.get(k) for k in
                       ("term_id", "source_form", "target_form", "entity_id",
                        "entity_binding", "side_a_entities", "side_b_entities")}
                      for r in rows], ensure_ascii=False, indent=1))
    return 0


def write_doc():
    rows = tb.distinct_pairs()
    L = []
    A = L.append
    A("# LACANIAN_SEMANTIC_GUARD.md — Phase 3C §7\n")
    A("> 代码：`_scripts/_tools/lacanian_semantic_guard.py`　·　"
      "配对来源：`_data/terminology_bridge.jsonl`（`relation_type = distinct_from`）\n")
    A("## 0. 这个 Guard 解决什么\n")
    A("通用 embedding 会把理论上必须区分的近义项压平。**§7 明确禁止用「调高 embedding 权重」"
      "来掩盖**。所以 Guard 不动 embedding，它在**检索结构**上阻止合并：\n")
    A("1. **识别** —— query 是否同时涉及某组配对的两侧；")
    A("2. **分道** —— 每侧一条独立 lane，且 lane query **显式排除另一侧的写法**；")
    A("3. **如实报警** —— 本库实测发现的问题必须报出来，不假装能区分。\n")
    A("## 1. ★ 必须先说的事实：一部分「压平」发生在**知识库层**，不在 embedding\n")
    A("§6 点名的 7 组配对，逐一去 concept store 里查 entity 绑定，结果是：\n")
    A("| 配对 | 一侧 entity | 另一侧 entity | 绑定状态 |")
    A("|---|---|---|---|")
    for r in rows:
        A("| `%s` / `%s` | %s | %s | **%s** |" % (
            r["source_form"], r["target_form"],
            ", ".join("`%s`" % x for x in (r.get("side_a_entities") or [])) or "**无**",
            ", ".join("`%s`" % x for x in (r.get("side_b_entities") or [])) or "**无**",
            r.get("entity_binding")))
    A("")
    A("**只有 `Autre/autre` 两侧都有 entity，而且两侧落到同一个 entity；"
      "其余 6 组至少一侧没有 entity。**\n")
    A("这意味着：**通用 embedding 压平这些区分，一部分原因是知识库自己没有为其中一侧"
      "建立实体。** 把责任全推给 embedding 是不诚实的。\n")
    A("Guard 的回应不是假装能区分，而是：\n")
    A("- `ENTITY_COLLISION`（Autre/autre）：**禁止 equivalent 扩展**，两条 lane 以表面形式为键；")
    A("- `COUNTERPART_ENTITY_MISSING`（5 组）：缺失侧**不生成任何等价关系**，lane 标记 `unbound_side`；")
    A("- `BOTH_ENTITIES_MISSING`（besoin/demande）：完全依赖表面形式。\n")
    A("**要把这些区分真正建立起来，需要先补概念实体（知识工程），而不是换更大的模型。**\n")
    A("## 2. 报警码\n")
    A("| 码 | 触发条件 | 严重度 | 动作 |")
    A("|---|---|---|---|")
    A("| `ENTITY_COLLISION` | 配对两侧绑到同一 entity | high | 禁止 equivalent 扩展；lane 以表面形式为键 |")
    A("| `COUNTERPART_ENTITY_MISSING` | 配对一侧无 entity | medium | 缺失侧只用自己的表面形式；标 `unbound_side` |")
    A("| `BOTH_ENTITIES_MISSING` | 两侧都无 entity | medium | 两条 lane 均用表面形式；不生成 equivalent |")
    A("")
    A("## 3. 「降低混淆」怎么被测量\n")
    A("分道之后，两个概念的候选**只在各自 lane 内排序**，跨 lane 混入是可检测的"
      "（lane 归属写在 evidence entry 上）。因此可以分别报告：\n")
    A("- **Raw Vector Contrastive Pass** —— 纯 embedding 自己在候选集里能不能排对；")
    A("- **System Contrastive Pass** —— Guard + 分道之后，最终系统能不能保住区分。\n")
    A("§16 要求两者**分开报告**，见 `ROUTED_RETRIEVAL_EVALUATION.md`。\n")
    A("## 4. 样例\n")
    demo = analyze("Réel 和 réalité 有什么区别？")
    A("```")
    A("query: %s" % demo["query"])
    A("flattening_risk: %s" % demo["flattening_risk"])
    A("lanes_required: %d" % demo["lanes_required"])
    for ln in demo["lanes"]:
        A("  lane %s  表面形式=%s  entity=%s" % (
            ln["lane_id"], ln["surface_form"], ln["entities"] if "entities" in ln else ln["entity_ids"]))
        A("     query_forms   = %s" % ln["query_forms"])
        A("     excluded_forms= %s" % ln["excluded_forms"])
    A("```")
    A("")
    A("**`excluded_forms` 非空就是防压平的实证**：另一侧的写法被明确挡住，"
      "不会在本 lane 里把两个概念重新混起来。\n")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[guard] %s" % OUT_MD)


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--demo", metavar="QUERY")
    g.add_argument("--pairs", action="store_true")
    g.add_argument("--doc", action="store_true")
    a = ap.parse_args(argv)
    if a.pairs:
        return cmd_pairs()
    if a.doc:
        write_doc()
        return 0
    print(json.dumps(analyze(a.demo), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
