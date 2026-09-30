#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_vault.py — 人类阅读层渲染（Phase 2 §二）

核心约束
────────
**不得为 249,105 个 Passage 各建一个 Markdown 文件。**
Obsidian 人类阅读层与机器 Passage Store 是两个东西，由同一个 stable ID 连接：

    机器层  _data/passage_store/passages.jsonl + _index/passage_store.sqlite
    人类层  02_Lacan_Seminars/S<NN>/…（少量 md，Passage 作为 heading）

三条实测教训（第一版都踩过，这里是修好后的版本）
───────────────────────────────────────────────
1. **每个文件必须有唯一 id**：第一版把一节课分页成 83 个 `.pN.md` 却给它们同一个
   `session.S01.unknown` id → validator 报 390 个 DUPLICATE_ID。
   现在分页是**显式 session 分页**：`session.S01.unknown.p1`，id 与文件名一致。
2. **frontmatter 必须严格符合 knowledge.schema.json**：第一版多写了
   `generated_at` / `year_from` / `year_to`（schema 没有），seminar 节点漏了
   `seminar` 字段，session 的 `seminar` 写成 `S01` 而非 schema 要求的期号形态
   → 5821 条 SCHEMA_INVALID。现在只写 schema 允许的字段。
3. **源文本里有外来链接语法，直接渲染会污染 vault**：实测 249,105 段里
   `![](...)` 2309 段、`[[wikilink]]` 2375 段、`[text](url)` 856 段 ——
   来自上游中译项目，在本 vault 里全是幽灵附件与断链。
   渲染层做**显示层归一化**：保留可见文本、目标降级为括号注记；
   机器层 `raw_text` **一字不改**，操作全部记进
   `_data/render_normalization.jsonl`（可机械回溯）。

用法
────
    python3 render_vault.py
    python3 render_vault.py --stamp
    python3 render_vault.py --chunk 150 --quiet
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from deterministic import add_stamp_flag, content_timestamp  # noqa: E402

STORE = os.path.join(VAULT, "_data", "passage_store")
SEM_ROOT = os.path.join(VAULT, "02_Lacan_Seminars")
NORM_LEDGER = os.path.join(VAULT, "_data", "render_normalization.jsonl")

DEFAULT_CHUNK = 150

# ---- 显示层归一化规则（机器层 raw_text 不动）
RE_EMBED = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
RE_MDLINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
RE_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")


def normalize_for_display(text):
    """把外来链接语法降级为纯文本。返回 (new_text, operations)。

    为什么必须做：
      1. `![](…)` 会被 Obsidian 当附件 → 实测 2950 条 ATTACHMENT_MISSING
      2. `[[…]]` 指向本 vault 不存在的笔记 → 实测 87 条 BROKEN_WIKILINK

    替代形式保留了信息：`![alt](url)` → `alt（url）`，`[[t|d]]` → `d（→t）`。
    目的是**可读 + 不污染图谱**，而不是隐藏来源。
    """
    ops = []
    out = text
    n = len(RE_EMBED.findall(out))
    if n:
        out = RE_EMBED.sub(lambda m: (m.group(1) or "图") + "（" + m.group(2) + "）", out)
        ops.append({"op": "embed_to_text", "count": n})
    n = len(RE_MDLINK.findall(out))
    if n:
        out = RE_MDLINK.sub(lambda m: m.group(1) + "（" + m.group(2) + "）", out)
        ops.append({"op": "mdlink_to_text", "count": n})
    n = len(RE_WIKILINK.findall(out))
    if n:
        out = RE_WIKILINK.sub(
            lambda m: ((m.group(2) or m.group(1)) + "（→" + m.group(1) + "）"), out)
        ops.append({"op": "wikilink_to_text", "count": n})
    return out, ops


def period_for_year(y):
    if not y:
        return "1967-1971"
    return ("1953-1955" if y < 1956 else "1955-1958" if y < 1959 else
            "1959-1963" if y < 1964 else "1964-1966" if y < 1967 else
            "1967-1971" if y < 1972 else "1972-1973" if y < 1974 else "1974-1976")


def load_jsonl(name):
    p = os.path.join(STORE, name)
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def q(s):
    """YAML 字符串字面量（一律加引号，避免 YAML 把 ISO 时间解析成 datetime）。"""
    if s is None:
        return "null"
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def fm_block(pairs):
    return "---\n" + "\n".join("%s: %s" % (k, v) for k, v in pairs) + "\n---\n\n"


def render(stamp=None, chunk=DEFAULT_CHUNK, quiet=False):
    seminars = load_jsonl("seminars.jsonl")
    sessions = load_jsonl("sessions.jsonl")
    if not seminars or not sessions:
        print("[fatal] passage_store 为空，先跑 build_passage_store.py", file=sys.stderr)
        return None

    if stamp is None:
        stamp = content_timestamp({"sessions": len(sessions),
                                   "passages": sum(s["passage_count"] for s in sessions)})
    ts = q(stamp)

    by_session = defaultdict(list)
    with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            p = json.loads(line)
            by_session[p["session_id"]].append(p)

    sessions_by_sem = defaultdict(list)
    for s in sessions:
        sessions_by_sem[s["seminar_id"]].append(s)

    # 清掉上一轮渲染写出的文件（分页数变化会留下孤儿），但**不删整个目录**：
    # 目录里可能住着人工节点与测试 fixture（实测踩过：rmtree 把
    # 02_Lacan_Seminars/S03_Seminar_III 下的 fixture passage 一起清掉了）。
    if os.path.isdir(SEM_ROOT):
        # 只清理**本渲染器会渲染的**那些 seminar 目录（即 store 里有对应 seminar 的），
        # 其余目录（人工节点、测试 fixture）一律不碰。
        # 实测踩过两次：先是 rmtree 整个 S??_* 目录，把 fixture passage 删了；
        # 改成按文件名删之后，又把 fixture 所在目录的 sessions/ 删了。
        render_sems = {s.split(".")[-1].upper() for s in
                       (m["id"] for m in seminars)}
        for d in os.listdir(SEM_ROOT):
            fp = os.path.join(SEM_ROOT, d)
            if not os.path.isdir(fp):
                continue
            m = re.match(r"^(S[A-Z0-9]+)_", d)
            if not m or m.group(1) not in render_sems:
                continue          # 不是我要渲染的 seminar → 不动
            for sub in ("sessions",):
                sd = os.path.join(fp, sub)
                if os.path.isdir(sd):
                    shutil.rmtree(sd)
            for fn in os.listdir(fp):
                # 只删本渲染器自己产出的 seminar 页
                if re.match(r"^seminar\.S[A-Z0-9]+\.md$", fn):
                    os.remove(os.path.join(fp, fn))

    written = []
    norm_ledger = []

    for sem in seminars:
        sid = sem["id"]                      # seminar.S01
        sem_short = sid.split(".")[-1]       # S01
        roman = (sem.get("roman") or "").upper()
        dirname = "%s_Seminar_%s" % (sem_short, roman or "X")
        sem_dir = os.path.join(SEM_ROOT, dirname)
        sess_dir = os.path.join(sem_dir, "sessions")
        os.makedirs(sess_dir, exist_ok=True)

        my_sessions = sorted(sessions_by_sem.get(sid, []), key=lambda s: s["id"])

        # ---- seminar 页（seminar 节点必须带 seminar 字段，值需匹配期号形态）
        L = [fm_block([
            ("id", q(sid)), ("type", "seminar"),
            ("title", q(sem.get("zh_title") or sem.get("fr_title") or sid)),
            ("canonical_name", q(sem.get("fr_title") or sid)),
            ("aliases", "[%s]" % q(sem.get("slug") or sid)),
            ("language", "mul"),
            ("seminar", q(sem_short)),
            ("period", q(period_for_year(sem.get("year_from")))),
            ("period_label", q("%s–%s" % (sem.get("year_from"), sem.get("year_to")))),
            ("authority_level", "L1"),
            ("review_status", "needs_review"),
            ("status", "active"),
            ("generated_by", q("script:render_vault.py")),
            ("created_at", ts), ("updated_at", ts),
            ("schema_version", q("1.0.0")),
            ("tags", "[研讨班/%s]" % sem_short),
        ])]
        L.append("# %s：%s" % (sid, sem.get("zh_title") or sem.get("fr_title") or ""))
        L.append("")
        L.append("| 项 | 值 |")
        L.append("|---|---|")
        L.append("| 法文标题 | %s |" % (sem.get("fr_title") or "—"))
        L.append("| 中文标题 | %s |" % (sem.get("zh_title") or "—"))
        L.append("| 罗马数字 | %s |" % (sem.get("roman") or "—"))
        L.append("| 年代 | %s–%s |" % (sem.get("year_from"), sem.get("year_to")))
        L.append("| 课数 | %s |" % sem.get("lessons"))
        L.append("| 语料段数 | %s |" % sem.get("segments"))
        L.append("")
        L.append("> ⚠️ **课次日期无法确证**：语料只给年份区间，未给逐课日期。"
                 "故 `session_date: unknown`，**不做推测**。")
        L.append("")
        L.append("## 课次")
        L.append("")
        L.append("| Session | 课次 | Passage 数 | 语言 | 日期 | 溯源 |")
        L.append("|---|---:|---:|---|---|---|")
        for s in my_sessions:
            n_files = max(1, (s["passage_count"] + chunk - 1) // chunk)
            links = []
            for k in range(1, n_files + 1):
                nm = s["id"] if n_files == 1 else "%s.p%d" % (s["id"], k)
                links.append("[[%s|%s]]" % (nm, nm.replace("session.", "")))
            L.append("| %s | %s | %d | %s | %s | `%s` |" % (
                " ".join(links),
                s.get("lesson") if s.get("lesson") is not None else "—",
                s["passage_count"], ",".join(s.get("languages") or []),
                s["session_date"], s["trace_status"]))
        L.append("")
        L.append("Passage 全量记录在 `_data/passage_store/passages.jsonl` 与 "
                 "`_index/passage_store.sqlite`。")
        L.append("")
        p_sem = os.path.join(sem_dir, sid + ".md")
        with open(p_sem, "w", encoding="utf-8") as f:
            f.write("\n".join(L))
        written.append(p_sem)

        # ---- session 页（显式分页；每页 id 唯一且 == 文件名）
        for s in my_sessions:
            rows = sorted(by_session.get(s["id"], []), key=lambda x: x["id"])
            if not rows:
                continue
            pages = [rows[i:i + chunk] for i in range(0, len(rows), chunk)]
            for pi, page in enumerate(pages, 1):
                pg_id = s["id"] if len(pages) == 1 else "%s.p%d" % (s["id"], pi)
                fname = pg_id + ".md"
                body = [fm_block([
                    ("id", q(pg_id)), ("type", "session"),
                    ("title", q("%s 第 %s 课%s" % (
                        sem_short, s["lesson"] if s["lesson"] is not None else "?",
                        ("（%d/%d）" % (pi, len(pages))) if len(pages) > 1 else ""))),
                    ("canonical_name", q(pg_id)),
                    ("aliases", "[%s]" % q(pg_id.replace("session.", ""))),
                    ("language", rows[0]["language"]),
                    ("seminar", q(sem_short)),
                    ("session_date", "unknown"),
                    ("session_date_precision", "unknown"),
                    ("authority_level", "L1"),
                    ("review_status", "needs_review"),
                    ("status", "active"),
                    ("trace_status", s["trace_status"]),
                    ("generated_by", q("script:render_vault.py")),
                    ("created_at", ts), ("updated_at", ts),
                    ("schema_version", q("1.0.0")),
                    ("tags", "[研讨班/%s]" % sem_short),
                ])]
                body.append("# %s%s" % (
                    pg_id, "" if len(pages) == 1
                    else "（第 %d/%d 页）" % (pi, len(pages))))
                body.append("")
                body.append("> **Passage 是最小引用证据单位。** 本页把同一 session 的 "
                            "Passage 渲染为 heading，可在 Obsidian 内引用：`[[%s#P0001]]`。"
                            % fname[:-3])
                body.append(">")
                body.append("> ⚠️ `session_date` = `unknown`（语料未给逐课日期，不做推测）；"
                            "`trace_status` = `%s`。" % s["trace_status"])
                body.append("")
                body.append("## Passage")
                body.append("")
                for p in page:
                    anchor = p["id"].rsplit(".", 1)[-1]
                    shown, ops = normalize_for_display(p["raw_text"])
                    if ops:
                        norm_ledger.append({
                            "passage_id": p["id"],
                            "render_file": os.path.relpath(
                                os.path.join(sess_dir, fname), VAULT),
                            "operations": ops,
                            "raw_preserved_in_store": True,
                        })
                    body.append("#### %s" % anchor)
                    body.append("")
                    body.append("`%s` 　lang=%s　authority=%s　trace=%s" % (
                        p["id"], p["language"], p["authority_level"], p["trace_status"]))
                    body.append("")
                    body.append(shown)
                    body.append("")
                    body.append("<sub>source segment `%s`　·　document `%s`　·　"
                                "sha256 `%s`%s</sub>" % (
                                    p["provenance"].get("source_segment_id"),
                                    p["provenance"].get("document_id"),
                                    (p["provenance"].get("recovered_file_sha256") or "")[:16],
                                    "" if not ops else "　·　显示层已归一化"))
                    body.append("")
                with open(os.path.join(sess_dir, fname), "w", encoding="utf-8") as f:
                    f.write("\n".join(body))
                written.append(os.path.join(sess_dir, fname))

    with open(NORM_LEDGER, "w", encoding="utf-8") as f:
        for r in sorted(norm_ledger, key=lambda x: x["passage_id"]):
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    if not quiet:
        print(f"[render] 写出 {len(written)} 个 Markdown（不是 "
              f"{sum(s['passage_count'] for s in sessions)} 个 Passage 文件）；"
              f"显示层归一化台账 {len(norm_ledger)} 条", file=sys.stderr)
    return {"markdown_files": len(written), "stamp": stamp,
            "sessions": len(sessions), "seminars": len(seminars),
            "normalized_passages": len(norm_ledger)}


def main():
    ap = argparse.ArgumentParser(description="渲染人类阅读层")
    ap.add_argument("--chunk", type=int, default=DEFAULT_CHUNK)
    ap.add_argument("--quiet", action="store_true")
    add_stamp_flag(ap)
    args = ap.parse_args()
    r = render(stamp=(None if not args.stamp else True), chunk=args.chunk,
               quiet=args.quiet)
    if r is None:
        return 1
    if not args.quiet:
        print(f"[render] -> {SEM_ROOT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
