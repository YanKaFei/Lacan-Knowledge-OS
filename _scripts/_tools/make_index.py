#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_index.py — 扫描 vault，生成 _index/Views/ 下的静态视图

产出（_index/Views/）：
  by-type.md       按 type 分组的实体清单
  by-authority.md  按 authority_level (L0–L4) 分组
  by-period.md     按拉康理论分期分组（concept_state 自带 period；概念本体按其各期状态归并）
  orphans.md       孤儿概念：没有任何 relation 指向的 concept
  broken-links.md  断链清单（与 validate_vault.py 同一套解析逻辑）

视图是**生成物**：不要手改，改了会被下一次运行覆盖。
数据来源与校验器完全一致 —— 直接复用 validate_vault.audit()，避免两套解析逻辑漂移。

用法：
  cd <vault-root>
  python3 _scripts/_tools/make_index.py
  python3 _scripts/_tools/make_index.py --out _index/Views
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deterministic import content_timestamp, add_stamp_flag  # noqa: E402

import validate_vault as VV  # noqa: E402

AUTHORITY_ORDER = [
    ("L0", "RAW", "未加工的原始件（扫描件、原始 PDF 等）"),
    ("L1", "PRIMARY", "拉康/弗洛伊德等一手文本"),
    ("L2", "SECONDARY", "他人研究、译注、二手文献"),
    ("L3", "RESEARCH NOTE", "人工笔记与人工整理"),
    ("L4", "AI SYNTHESIS", "AI 生成内容，永不自动升格"),
]

PERIOD_ORDER = [
    "pre-1953", "1953-1955", "1955-1958", "1959-1963", "1964-1966",
    "1967-1971", "1972-1973", "1974-1976", "1976-1981",
]


def _table(rows, header):
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join(["---"] * len(header)) + "|"]
    out.extend("| " + " | ".join(str(c) for c in r) + " |" for r in rows)
    return out


def _header(title, note=None, stamp=None):
    L = ["# %s" % title, ""]
    L.append("> 由 `_scripts/_tools/make_index.py` 生成%s —— 生成物，请勿手改。"
             % (("于 `%s`" % stamp) if stamp else ""))
    if note:
        L.append(">")
        L.append("> %s" % note)
    L.append("")
    return L


def _entity_link(ent):
    """Obsidian 友好的显示：id 为链接目标（[[id]] 需要文件名=id，否则退化为文件名）。"""
    stem = Path(ent["rel"]).stem
    eid = ent.get("id") or stem
    label = eid if eid == stem else "%s（%s）" % (eid, stem)
    return "[[%s|%s]]" % (stem, label)


def view_by_type(entities, stamp=None):
    L = _header("按 type 分组的实体清单",
                "实体必须通过 knowledge.schema.json 才会出现在这里。", stamp=stamp)
    by_type = defaultdict(list)
    for e in entities:
        by_type[e.get("type") or "(缺 type)"].append(e)
    L.append("共 **%d** 个实体，**%d** 种 type。" % (len(entities), len(by_type)))
    L.append("")
    for etype in sorted(by_type):
        rows = sorted(by_type[etype], key=lambda x: str(x.get("id")))
        L.append("## %s（%d）" % (etype, len(rows)))
        L.append("")
        L.extend(_table(
            [[_entity_link(e), e.get("canonical_name") or "—", e.get("title") or "—",
              e.get("authority_level") or "—", e.get("review_status") or "—",
              "`%s`" % e.get("rel")] for e in rows],
            ["id", "规范名", "标题", "authority", "review_status", "文件"]))
        L.append("")
    return "\n".join(L)


def view_by_authority(entities, stamp=None):
    L = _header("按 authority_level 分组的实体清单",
                "L4 是 AI 合成层，永不自动升格；L0–L1 才是一手证据。", stamp=stamp)
    by_auth = defaultdict(list)
    for e in entities:
        by_auth[e.get("authority_level") or "(缺)"].append(e)
    for level, name, desc in AUTHORITY_ORDER:
        rows = sorted(by_auth.get(level, []), key=lambda x: str(x.get("id")))
        L.append("## %s %s — %d 个节点" % (level, name, len(rows)))
        L.append("")
        L.append("%s" % desc)
        L.append("")
        if rows:
            L.extend(_table(
                [[_entity_link(e), e.get("type") or "—", e.get("title") or "—",
                  e.get("review_status") or "—"] for e in rows],
                ["id", "type", "标题", "review_status"]))
            L.append("")
    unknown = sorted(by_auth.get("(缺)", []), key=lambda x: str(x.get("id")))
    if unknown:
        L.append("## 未标 authority_level — %d 个节点" % len(unknown))
        L.append("")
        L.append("这些节点在 schema 校验中已经报错，需要补 `authority_level`。")
        L.append("")
        L.extend(_table([[_entity_link(e), "`%s`" % e.get("rel")] for e in unknown],
                        ["id", "文件"]))
        L.append("")
    return "\n".join(L)


def view_by_period(entities, stamp=None):
    L = _header("按理论分期（period）分组",
                "同一概念的不同时期表述必须并存，禁止用单一静态定义覆盖。", stamp=stamp)
    by_id = {e.get("id"): e for e in entities if e.get("id")}
    states = [e for e in entities if e.get("type") == "concept_state"]

    # 概念本体 → 其各期状态的 period 集合
    concept_periods = defaultdict(set)
    for st in states:
        cid = st.get("front", {}).get("concept_id")
        if cid and st.get("period"):
            concept_periods[cid].add(st["period"])

    L.append("共 **%d** 个 concept_state 节点，覆盖 **%d** 个时期。"
             % (len(states), len({s.get("period") for s in states if s.get("period")})))
    L.append("")
    for period in PERIOD_ORDER + ["(未标时期)"]:
        rows = [s for s in states if (s.get("period") or "(未标时期)") == period]
        if period == "(未标时期)":
            rows = [s for s in states if not s.get("period")]
        concepts = sorted(
            cid for cid, ps in concept_periods.items() if period in ps)
        L.append("## %s — %d 个 state" % (period, len(rows)))
        L.append("")
        if rows:
            L.extend(_table(
                [[_entity_link(s), s.get("front", {}).get("state_label") or "—",
                  "`%s`" % (s.get("front", {}).get("concept_id") or "—"),
                  "`%s`" % s.get("rel")] for s in sorted(rows, key=lambda x: str(x.get("id")))],
                ["state id", "该期表述标签", "概念本体", "文件"]))
            L.append("")
        if concepts:
            L.append("涉及概念本体：%s" % ", ".join("`%s`" % c for c in concepts))
            L.append("")
        if not rows and not concepts:
            L.append("（该期暂无节点）")
            L.append("")
    L.append("### 没有 state 的概念本体")
    L.append("")
    naked = sorted(
        (e for e in entities if e.get("type") == "concept"
         and not (e.get("front", {}).get("concept_states") or [])),
        key=lambda x: str(x.get("id")))
    if not naked:
        L.append("无。每个概念本体都至少挂了一个 state。")
    else:
        for e in naked:
            L.append("- %s —— 概念本体不承载定义，请补 `concept_states`"
                     % _entity_link(e))
    L.append("")
    return "\n".join(L)


def view_orphans(entities, relations, stamp=None):
    L = _header("孤儿概念（没有任何 relation 指向的 concept）",
                "入边 = 该 concept 出现在某条关系的 object 位置。", stamp=stamp)
    incoming = Counter()
    outgoing = Counter()
    for r in relations:
        if not isinstance(r, dict):
            continue
        obj = r.get("object")
        subj = r.get("subject")
        if isinstance(obj, str):
            incoming[obj] += 1
        if isinstance(subj, str):
            outgoing[subj] += 1

    concepts = sorted((e for e in entities if e.get("type") == "concept"),
                      key=lambda x: str(x.get("id")))
    orphans = [c for c in concepts if incoming.get(c.get("id"), 0) == 0]

    L.append("共有 concept 节点 **%d** 个，其中 **%d** 个是孤儿（无入边）。"
             % (len(concepts), len(orphans)))
    L.append("")
    if not orphans:
        L.append("无孤儿概念。")
        L.append("")
        return "\n".join(L)
    L.extend(_table(
        [[_entity_link(c), c.get("authority_level") or "—",
          c.get("review_status") or "—", outgoing.get(c.get("id"), 0),
          "`%s`" % c.get("rel")] for c in orphans],
        ["id", "authority", "review_status", "出边数", "文件"]))
    L.append("")
    L.append("> 处理建议：为每个孤儿概念补一条有证据的关系（subject 或 object 指向它），"
             "或把它并入更上位的概念。孤儿概念在 Graph View 里会漂浮。")
    L.append("")
    return "\n".join(L)


def view_broken_links(report, stamp=None):
    L = _header("断链清单",
                "断链是 SOURCE_TRACE_INCOMPLETE 的信号：先建缺失的节点，再谈引用。",
                stamp=stamp)
    broken = report.get("broken_wikilinks") or []
    L.append("共 **%d** 条断链（扫描到 %d 个 wikilink）。"
             % (len(broken), report["summary"].get("wikilinks", 0)))
    L.append("")
    if not broken:
        L.append("无断链。")
        L.append("")
        return "\n".join(L)
    L.extend(_table(
        [["`%s`" % b["target"], b["source"], b["line"] or "—",
          b["alias"] or "—", b["origin"]] for b in broken],
        ["缺失目标", "来源文件", "行", "别名", "位置"]))
    L.append("")
    return "\n".join(L)


def write_view(out_dir, name, content):
    path = Path(out_dir) / name
    path.write_text(content.rstrip("\n") + "\n", encoding="utf-8")
    return path


def build(vault, out_dir=None, stamp=None):
    vault = Path(vault).expanduser().resolve()
    out = Path(out_dir) if out_dir else vault / "_index" / "Views"
    out.mkdir(parents=True, exist_ok=True)

    report = VV.audit(vault, write=False)
    entities = report.get("entities", [])
    relations = report.get("relations", [])

    if stamp is None:
        # 默认：由内容推导（内容不变 → 时间戳不变 → 无 diff）
        from deterministic import content_timestamp
        stamp = content_timestamp({"entities": entities, "relations": relations})

    written = []
    written.append(write_view(out, "by-type.md", view_by_type(entities, stamp)))
    written.append(write_view(out, "by-authority.md", view_by_authority(entities, stamp)))
    written.append(write_view(out, "by-period.md", view_by_period(entities, stamp)))
    written.append(write_view(out, "orphans.md", view_orphans(entities, relations, stamp)))
    written.append(write_view(out, "broken-links.md", view_broken_links(report, stamp)))

    nav = ["# _index/Views —— 生成视图", "",
           "这些文件由 `_scripts/_tools/make_index.py` 生成，手改会被覆盖。", ""]
    for p in written:
        nav.append("- [[%s]]" % p.stem)
    nav.append("")
    nav.append("上游报告：`_index/Reports/validation-report.md`")
    nav.append("")
    written.append(write_view(out, "_index.md", "\n".join(nav)))
    return {"views": [str(p) for p in written], "entities": len(entities),
            "relations": len(relations), "report": report}


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成 _index/Views 静态视图")
    ap.add_argument("--vault", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--quiet", action="store_true")
    add_stamp_flag(ap)
    args = ap.parse_args(argv)

    vault = Path(args.vault).expanduser().resolve() if args.vault \
        else Path(__file__).resolve().parents[2]
    if not vault.is_dir():
        print("[fatal] vault 目录不存在: %s" % vault, file=sys.stderr)
        return 2

    stamp = (datetime.now(timezone.utc).isoformat(timespec="seconds")
             if args.stamp else None)
    result = build(vault, args.out, stamp=stamp)
    if not args.quiet:
        print("[index] entities=%d relations=%d" % (result["entities"], result["relations"]),
              file=sys.stderr)
        for p in result["views"]:
            print("[index] -> %s" % p, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
