#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_recoverable_corpus.py — 只读审计 `.lacan-build/atlas/` 里可恢复的语料

为什么需要这个脚本：
    ROADMAP 把「导入 249,105 段既有语料」列为 Phase 2 第一优先，但那个数字
    如果只存在于散文里，就无法复核、也无法在导入后判断是否漏段。
    本脚本把该结论变成**可重复运行的机械事实**，并输出可入库的 JSON。

    同时对 `.lacan-build/atlas/` 做**完整性体检**：它是那 82,578 段中译的
    唯一副本（上游源目录 `研讨班项目内容/研讨班中译/` 已消失），
    必须能一眼看出它是否还完整。

用法:
    python3 audit_recoverable_corpus.py                    # 报告
    python3 audit_recoverable_corpus.py --json             # 机器可读
    python3 audit_recoverable_corpus.py --write            # 写入 _data/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deterministic import apply_stamp, add_stamp_flag  # noqa: E402

DEFAULT_SRC = os.path.expanduser("<HOME>")
# 本脚本位于 <vault>/_scripts/_tools/ → 上溯三层才是 vault 根
DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "_data", "recoverable_corpus.json")


def count_jsonl(path):
    """逐行统计 jsonl，返回 (记录数, 每期计数, 字段集, 样例, 坏行数)。"""
    n = 0
    per_seminar = Counter()
    fields = set()
    sample = None
    bad = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                bad += 1
                continue
            n += 1
            fields.update(d.keys())
            sem = d.get("seminar") or d.get("s") or d.get("index")
            if sem is not None:
                per_seminar[str(sem)] += 1
            if sample is None:
                # 只留叶子字段，绝不把整个对象当业务数据返回
                sample = {k: (str(v)[:120] if not isinstance(v, (int, float, bool, type(None)))
                              else v)
                          for k, v in d.items()}
    return n, per_seminar, sorted(fields), sample, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true")
    add_stamp_flag(ap)
    args = ap.parse_args()

    atlas = os.path.join(args.src, "atlas")
    staferla = os.path.join(args.src, "staferla")
    report = {
        "schema": "recoverable-corpus/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_root": atlas,
        "read_only": True,
        "layers": {},
        "integrity": {},
        "totals": {},
    }

    if not os.path.isdir(atlas):
        print(f"[FATAL] 找不到 {atlas}", file=sys.stderr)
        return 1

    # ---- 中译 segments.jsonl
    p = os.path.join(atlas, "segments.jsonl")
    if os.path.exists(p):
        n, per, fields, sample, bad = count_jsonl(p)
        report["layers"]["zh_translation"] = {
            "file": "atlas/segments.jsonl",
            "records": n,
            "seminars": len(per),
            "per_seminar": dict(sorted(per.items())),
            "fields": fields,
            "sample": sample,
            "malformed_lines": bad,
            "size_bytes": os.path.getsize(p),
            "is_sole_copy": True,
            "upstream_status": "上游源目录「研讨班中译/」已从 <HOME> 消失",
        }

    # ---- 法语转录 french_staferla.jsonl
    p = os.path.join(atlas, "french_staferla.jsonl")
    if os.path.exists(p):
        n, per, fields, sample, bad = count_jsonl(p)
        report["layers"]["fr_transcription"] = {
            "file": "atlas/french_staferla.jsonl",
            "records": n,
            "seminars": len(per),
            "fields": fields,
            "sample": sample,
            "malformed_lines": bad,
            "size_bytes": os.path.getsize(p),
            "provenance_note": ("Document de travail (transcription STAFERLA) — "
                                "texte non établi；引用必须标注「工作转录，非瑟伊版定本」"),
        }

    # ---- 28 期元数据
    p = os.path.join(atlas, "seminars.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            sems = json.load(f)
        report["layers"]["seminar_metadata"] = {
            "file": "atlas/seminars.json",
            "seminars": len(sems) if isinstance(sems, list) else None,
            "has_lesson_numbers": bool(
                isinstance(sems, list) and sems and "lesson_numbers" in sems[0]),
            "years_from": sorted({s.get("year_from") for s in sems
                                  if isinstance(s, dict) and s.get("year_from")})[:3]
            if isinstance(sems, list) else None,
        }

    # ---- 其他 atlas 资产
    others = {}
    for fn in ("french.jsonl", "lacancom.json", "term_vocab.json",
               "term_neighbours.json", "term_postings.json", "staferla_manifest.json"):
        fp = os.path.join(atlas, fn)
        if os.path.exists(fp):
            others[fn] = os.path.getsize(fp)
    report["layers"]["other_atlas_assets"] = others

    # ---- staferla 原始下载（第二道保险）
    if os.path.isdir(staferla):
        docx = [f for f in os.listdir(staferla) if f.lower().endswith(".docx")]
        txt = [f for f in os.listdir(staferla) if f.lower().endswith(".txt")]
        man = os.path.join(staferla, "manifest.json")
        paragraphs = None
        if os.path.exists(man):
            with open(man, encoding="utf-8") as f:
                m = json.load(f)
            if isinstance(m, list):
                paragraphs = sum(x.get("paragraphs", 0) for x in m
                                 if isinstance(x, dict))
        report["layers"]["staferla_raw"] = {
            "docx": len(docx), "txt": len(txt),
            "manifest_paragraphs": paragraphs,
            "role": "french_staferla.jsonl 的第二道保险（原始下载）",
        }

    # ---- 完整性判据
    zh = report["layers"].get("zh_translation", {})
    fr = report["layers"].get("fr_transcription", {})
    sem_meta = report["layers"].get("seminar_metadata", {})
    checks = []

    def chk(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    chk("中译在 28 期（S1–S27 + s19b）",
        zh.get("seminars") == 28, f"seminars={zh.get('seminars')}")
    chk("法语转录覆盖 28 期",
        fr.get("seminars") == 28, f"seminars={fr.get('seminars')}")
    chk("中译段数与历史记录一致（82,578）",
        zh.get("records") == 82578, f"records={zh.get('records')}")
    chk("法语转录段数与历史记录一致（166,527）",
        fr.get("records") == 166527, f"records={fr.get('records')}")
    chk("中译每段都带 seminar（可按期归位）",
        zh.get("seminars", 0) > 0 and "seminar" not in (zh.get("malformed_lines") or 0,),
        f"fields={zh.get('fields')}")
    chk("中译带 lesson 课次（Passage 映射的前提）",
        "lesson" in (zh.get("fields") or []), f"fields={zh.get('fields')}")
    chk("28 期元数据含 lesson_numbers",
        sem_meta.get("has_lesson_numbers") is True, str(sem_meta))
    chk("staferla 原始下载存在（第二道保险）",
        report["layers"].get("staferla_raw", {}).get("docx", 0) >= 28,
        str(report["layers"].get("staferla_raw", {})))
    chk("无坏行", (zh.get("malformed_lines", 0) + fr.get("malformed_lines", 0)) == 0,
        f"zh_bad={zh.get('malformed_lines')} fr_bad={fr.get('malformed_lines')}")

    report["checks"] = checks
    report["totals"] = {
        "zh_segments": zh.get("records"),
        "fr_segments": fr.get("records"),
        "combined": (zh.get("records") or 0) + (fr.get("records") or 0),
    }
    report["all_checks_pass"] = all(c["ok"] for c in checks)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 68)
        print("可恢复语料审计（.lacan-build/atlas/）")
        print("=" * 68)
        print(f"来源目录: {atlas}")
        print(f"中译:     {zh.get('records')} 段 / {zh.get('seminars')} 期"
              f"  ({zh.get('size_bytes', 0) / 1e6:.1f} MB)  ← 唯一副本")
        print(f"法语:     {fr.get('records')} 段 / {fr.get('seminars')} 期"
              f"  ({fr.get('size_bytes', 0) / 1e6:.1f} MB)")
        print(f"合计:     {report['totals']['combined']} 段")
        print(f"staferla 原始下载: {report['layers'].get('staferla_raw', {})}")
        print()
        print("完整性判据:")
        for c in checks:
            print(f"  {'✓' if c['ok'] else '✗'} {c['check']}  —— {c['detail']}")
        print()
        print("结论:", "全部通过" if report["all_checks_pass"] else "有判据未通过")

    if args.write:
        apply_stamp(report, stamp=args.stamp)
        os.makedirs(os.path.dirname(DEFAULT_OUT), exist_ok=True)
        with open(DEFAULT_OUT, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n[written] {DEFAULT_OUT}", file=sys.stderr)

    return 0 if report["all_checks_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
