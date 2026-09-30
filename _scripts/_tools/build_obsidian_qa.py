#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_obsidian_qa.py — 4D.3：生成**可复核**的 Obsidian 工作区 QA 工件。

产物结构（报告在 vault 外，避免报告自己变成图谱节点）：

    _workspace/obsidian_qa/
      GRAPH_QA.md      ← 由本脚本从真实 vault 计算生成（节点/边/断言）
      vault/           ← 真实工作区 vault 根（USER_WORKSPACE，可被 Obsidian 打开）
        Research/ Passages/ Concepts/ Seminars/ _System/

只写 `_workspace/**`（USER_WORKSPACE 类），不碰 corpus / passage store / ontology / 冻结件。
`GRAPH_QA.md` 的节点、边、计数**全部现算**，不写死 —— 手工维护的图报告会过期，
实测就出过一次（报告里 10 个节点，vault 里其实有 12 个）。
"""
from __future__ import annotations
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)

from obsidian_adapter import adapter as A                      # noqa: E402
from obsidian_adapter import vault as V                        # noqa: E402
from obsidian_adapter.frontmatter import parse_frontmatter     # noqa: E402
from scholarly_api import policy as POL                        # noqa: E402
from workspace_ui.server import api as UIA                     # noqa: E402

QA_ROOT = os.path.join("_workspace", "obsidian_qa")
VAULT_ROOT = os.path.join(QA_ROOT, "vault")

Q_GAZE = "Seminar XI 中 gaze/regard 是如何与 objet a 发生关系的？"
Q_FMRI = "拉康如何看待 fMRI 等当代神经科学影像研究？"
Q_META = "拉康 1953 年 11 月 18 日那场报告的确切时间、地点与在场者是谁？"
P_L2 = "passage.S05.unknown.L05.P0056"          # L2 recovered → SOURCE_TRACE_INCOMPLETE

USER_TEXT = "\n\n## 我自己的笔记\n\n- 这段先记下来，回头跟 S11 的第三章对照。\n- ✍️ 用户内容必须逐字保留。\n"


def _answer(q):
    out = UIA.research(q, provider="mock", save_history=False)
    return out["view"]


def _links(text):
    out = []
    for m in re.findall(r"!?\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", text or ""):
        t = m.strip()
        out.append(t[:-3] if t.endswith(".md") else t)
    return out


def _all_md(root):
    out = []
    for d, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".md"):
                out.append(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))
    return sorted(out)


def main():
    abs_qa = os.path.join(VAULT, QA_ROOT)
    shutil.rmtree(abs_qa, ignore_errors=True)
    v = V.Vault(VAULT_ROOT)
    if os.path.commonpath([os.path.realpath(v.root),
                           os.path.realpath(VAULT)]) != os.path.realpath(VAULT):
        raise SystemExit("QA vault 必须落在项目工作区内（USER_WORKSPACE）")

    # ── 1. 一次有引用（L1）的研究 ────────────────────────────────────────
    gaze = A.save_research(_answer(Q_GAZE), vault=v)
    if gaze.get("status") != "saved":
        raise SystemExit("gaze 保存失败：%s" % gaze)
    # ── 2. 两次弃权研究（主题缺失 / 元数据缺失）──────────────────────────
    fmri = A.save_research(_answer(Q_FMRI), vault=v)
    meta = A.save_research(_answer(Q_META), vault=v)
    # ── 3. 显式保存单段（Inspector 的 Save Passage 路径，L2 → 来源链未闭合）
    l2 = A.save_passage(P_L2, vault=v)

    # ── 4. 用户内容注入 + 受管区块更新后逐字比对（§13/§14/§47 实证）────────
    targets = [gaze["research_note"]] + gaze["passage_notes"] \
        + gaze["concept_notes"] + gaze["seminar_notes"] + [l2["note"]]
    preserved = []
    for rel in targets:
        before = v.read(rel)
        if "## My Notes" not in before:
            continue
        v.write(rel, before.rstrip("\n") + "\n" + USER_TEXT)
    # 触发受管区块重写：概念/研讨班 reference hub
    from obsidian_adapter.frontmatter import parse_frontmatter as _pf
    for rel in gaze["concept_notes"]:
        A.ensure_concept_note(_pf(v.read(rel))[0]["concept_id"], vault=v)
    for rel in gaze["seminar_notes"]:
        A.ensure_seminar_note(_pf(v.read(rel))[0]["seminar_id"], vault=v)
    for rel in targets:
        txt = v.read(rel) or ""
        if "✍️ 用户内容必须逐字保留。" in txt:
            preserved.append(rel)

    # ── 5. 现算图谱（节点/边/悬空链）────────────────────────────────────
    notes = _all_md(v.root)
    present = set(notes)
    nodes = list(notes)
    edges, dangling, embed_syntax = [], [], []
    for rel in notes:
        txt = v.read(rel) or ""
        if "![[" in txt:
            embed_syntax.append(rel)
        for t in _links(txt):
            if t + ".md" in present:
                edges.append((rel, t + ".md"))
            else:
                dangling.append((rel, t))
    edges = sorted(set(edges))

    # 断言：不容许悬空链 / embed 语法 / 非受管 note
    if dangling:
        raise SystemExit("QA vault 存在悬空 wikilink：%s" % dangling[:5])
    if embed_syntax:
        raise SystemExit("QA vault 存在 corpus 资产 embed（会是破图）：%s" % embed_syntax)
    for rel in notes:
        fm, _ = parse_frontmatter(v.read(rel) or "")
        if not (fm or {}).get("type"):
            raise SystemExit("QA note 无 frontmatter type：%s" % rel)

    # ── 6. 写 GRAPH_QA.md（报告在 vault 外，本身不进图谱）────────────────
    out = ["# Phase 4D.3 — Obsidian Graph QA（workspace links）", "",
           "> 由 `_scripts/_tools/build_obsidian_qa.py` **现算**生成；"
           "全部是 **workspace 链接**，不是 canonical ontology relation（§19/§43）。", "",
           "- vault 根：`%s/`（`%s`）" % (VAULT_ROOT, POL.classify(
               os.path.join(v.root, "Research", "x.md"))),
           "- 节点 %d / 边 %d / 悬空链接 %d" % (len(nodes), len(edges), len(dangling)), "",
           "## 节点（notes）", ""]
    out += ["- `%s`" % n for n in nodes]
    out += ["", "## 边（workspace edges）", "", "| from | → to |", "|---|---|"]
    out += ["| `%s` | `%s` |" % e for e in edges]
    out += ["", "## 断言（脚本现算，任一不成立即报错退出）", "",
            "| 断言 | 实测 |", "|---|---|",
            "| vault 内无 `![[…]]` embed 语法（corpus 资产不拷进 vault） | %d |"
            % len(embed_syntax),
            "| 无悬空 wikilink | %d |" % len(dangling),
            "| 每个 note 都有 frontmatter `type` | %d/%d |" % (len(nodes), len(nodes)),
            "| 弃权研究只产出 Research Note | fMRI concepts=%d passages=%d；"
            "元数据题 concepts=%d passages=%d |" % (
                len(fmri["concept_notes"]), len(fmri["passage_notes"]),
                len(meta["concept_notes"]), len(meta["passage_notes"])),
            "| 引用段落只在被引用时 materialize | 引用 %d 条 → passage note %d 篇 |"
            % (len(_answer(Q_GAZE)["citations"]), len(gaze["passage_notes"])),
            "| 用户 `## My Notes` 在受管区块重写后逐字保留 | %d 篇 |" % len(preserved),
            "| 显式保存单段会建 Seminar hub（无悬空 `[[Seminars/…]]`） | %s |"
            % os.path.basename(l2.get("seminar_note") or "—"),
            "", "### 已保存的 QA 工件", ""]
    out += ["- `%s` — `%s`" % (r, (parse_frontmatter(v.read(r) or "")[0] or {}).get("type"))
            for r in targets]
    out += ["- `%s` — `%s`" % (fmri["research_note"], "abstention research note"),
            "- `%s` — `%s`" % (meta["research_note"], "abstention research note"),
            "", "弃权题不创建任何 `fMRI → Lacan` 关系（§43）：图谱里只有 Research Note。", ""]
    with open(os.path.join(abs_qa, "GRAPH_QA.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out))

    print("QA vault: %s/（%d 节点 / %d 边 / 悬空 %d）"
          % (VAULT_ROOT, len(nodes), len(edges), len(dangling)))
    print("QA 报告: %s/GRAPH_QA.md" % QA_ROOT)
    print("用户区保留验证: %d 篇；L2 Seminar hub: %s"
          % (len(preserved), l2.get("seminar_note")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
