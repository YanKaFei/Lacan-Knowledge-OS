#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_bibliography_registry.py — Phase 5C §10：确定性构建书目登记表。

    python3 _scripts/_tools/build_bibliography_registry.py [--check]

来源全部机器可验证：`01_Sources/Documents/*.md` + passage store 的
`witnesses` / `corpus_sources`。**禁止**从文本猜出版社/年份/ISBN/页码（§11/§50）。
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

import bibliography as B                                                   # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if a.check:
        # §54：registry **构建是确定性的**；磁盘内容必须与重建结果一致
        disk = B.registry.manifest()
        if not disk:
            print("FAIL 缺 registry manifest（先构建）")
            return 1
        rebuilt = B.registry.build()
        import hashlib as _h
        import json as _j
        h = _h.sha256(_j.dumps(rebuilt, ensure_ascii=False,
                               sort_keys=True).encode("utf-8")).hexdigest()
        # 用与 write_all 相同的口径复算
        probe = B.registry.write_all(rebuilt, store="/tmp/p5c_probe_store")
        ok = (probe["content_hash"] == disk.get("content_hash")
              and probe["counts"] == disk.get("counts"))
        print("%s bibliography registry 与重建一致：disk=%s rebuilt=%s counts=%s"
              % ("OK  " if ok else "FAIL", str(disk.get("content_hash"))[:16],
                 str(probe["content_hash"])[:16], probe["counts"]))
        return 0 if ok else 1
    res = B.registry.build()
    man = B.registry.write_all(res)
    print("书目登记表 -> %s" % os.path.relpath(B.registry.STORE, VAULT))
    print("  freeze_class = %s（§55）" % man["freeze_class"])
    print("  counts: %s" % man["counts"])
    print("  reviewed items:")
    for it in B.registry.items():
        caps = B.model.capability_flags(it)
        print("    %-34s type=%-20s completeness=%-12s chicago=%s missing=%s"
              % (it["bibliographic_id"], it["item_type"],
                 it["metadata_completeness"], caps["chicago"],
                 ",".join(caps["missing_fields"]) or "-"))
    print("  editions:")
    for ed in B.registry.editions():
        print("    %-30s page_locator_available=%s publisher=%r year=%r isbn=%r"
              % (ed["edition_id"], ed["page_locator_available"], ed["publisher"],
                 ed["year"], ed["isbn"]))
    print("  candidates (未晋级): %s"
          % [c["bibliographic_id"] for c in B.registry.candidates()])
    print("  works: %s" % [w["work_id"] for w in B.registry.works()])
    return 0


if __name__ == "__main__":
    sys.exit(main())
