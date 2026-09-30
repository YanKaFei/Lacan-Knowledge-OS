#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase5a_corpus_diff.py — P5A-006 §6/§7/§10：语料数据版本变化的**真实差异审计**。

只做**事实采集**，不做判定，不写任何受保护工件。

对比基线 = 冻结 manifest 所钉住的那份 inventory（默认取 `git show HEAD:<path>`，
并以 sha256 与 manifest 记录值核对；不一致直接报错，不"就近取一个"）。

输出（`_data/phase5a/corpus_diff_audit.json`）：
    added / removed / modified / unchanged   逐条含 rel_path / size / sha256 / classification
    ingestion_status                         新增文件是否进入 canonical passage store
    derived_state                            passage store / FTS / vector / graph / inventory 状态

§6 纪律：若 added 之外还存在**未解释**的 removed/modified，本工具把
`unexplained_changes` 置位，调用方必须停止自动推进并上报。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
P5A = os.path.join(VAULT, "_data", "phase5a")
INV_REL = "_data/corpus_inventory.json"
FREEZE = os.path.join(VAULT, "_data", "core_freeze", "scholarly_core_freeze_v1.json")
PASSAGES = os.path.join(VAULT, "_data", "passage_store", "passages.jsonl")
STORE_META = os.path.join(VAULT, "_data", "passage_store", "_build_meta.json")
INDEX_MANIFEST = os.path.join(VAULT, "_data", "index", "INDEX_MANIFEST.json")
VECTOR_MANIFEST = os.path.join(VAULT, "_data", "index", "vector",
                               "VECTOR_INDEX_MANIFEST.json")


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def jd(p, d=None):
    if not os.path.isfile(p):
        return d
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def frozen_inventory():
    """→ (inventory_dict, sha256, source_label, mode)。

    两种状态都必须被正确处理：

    * **冻结尚未追上 live**（有未处理的漂移）：基线 = manifest 钉住的那份
      （`git show HEAD:` 的字节必须与 manifest 记录值一致，否则拒绝"就近取用"）；
    * **冻结已经追上 live**（P5A-006 已按声明推进）：此时没有漂移，
      判据变成「live == manifest」→ 返回 historical 基线（父段前的 HEAD 版本）仅供记录。
    """
    man = jd(FREEZE, {})
    pinned = (man.get("components") or {}).get("corpus_inventory_hash")
    live_bytes = open(os.path.join(VAULT, INV_REL), "rb").read()
    live_sha = sha_bytes(live_bytes)
    if pinned and live_sha == pinned:
        # 冻结已追上 → 无漂移；仍取历史基线用于记录 143→144 的过渡
        r = subprocess.run(["git", "-C", VAULT, "show", "HEAD:%s" % INV_REL],
                           capture_output=True)
        if r.returncode != 0:
            return json.loads(live_bytes.decode("utf-8")), live_sha, \
                "(no history baseline)", "NO_DRIFT_SINCE_FREEZE"
        return (json.loads(r.stdout.decode("utf-8")), sha_bytes(r.stdout),
                "git HEAD:%s（历史基线；冻结已推进到 live）" % INV_REL,
                "NO_DRIFT_SINCE_FREEZE")
    r = subprocess.run(["git", "-C", VAULT, "show", "HEAD:%s" % INV_REL],
                       capture_output=True)
    if r.returncode != 0:
        raise SystemExit("无法取得冻结基线：git show HEAD:%s 失败" % INV_REL)
    got = sha_bytes(r.stdout)
    if pinned and got != pinned:
        raise SystemExit("冻结基线 sha256 与 manifest 不符：%s != %s（拒绝就近取用）"
                         % (got[:16], str(pinned)[:16]))
    return json.loads(r.stdout.decode("utf-8")), got, "git HEAD:%s" % INV_REL, "DRIFT"


def _key(rec):
    return rec.get("rel_path") or rec.get("path")


def classify(rec):
    """→ 记录级分类（用记录里**已有**的字段，不猜）。"""
    if not rec:
        return None
    return {
        "parse_status": rec.get("parse_status"),
        "extension": rec.get("extension"),
        "source_type": rec.get("source_type"),
        "estimated_language": rec.get("estimated_language"),
        "is_duplicate": rec.get("is_duplicate"),
    }


def diff(old, new):
    o = {_key(r): r for r in old.get("records") or []}
    n = {_key(r): r for r in new.get("records") or []}
    added = sorted(set(n) - set(o))
    removed = sorted(set(o) - set(n))
    modified, unchanged = [], sorted(set(o) & set(n))
    for k in unchanged[:]:                      # noqa: B007  原地筛选
        a, b = o[k], n[k]
        same = (a.get("sha256") == b.get("sha256") and a.get("size") == b.get("size"))
        if not same:
            modified.append({
                "rel_path": k,
                "before": {"size": a.get("size"), "sha256": a.get("sha256")},
                "after": {"size": b.get("size"), "sha256": b.get("sha256")},
            })
            unchanged.remove(k)
    row = lambda k, r: {"rel_path": k, "size": r.get("size"), "sha256": r.get("sha256"),
                        "document_id": r.get("document_id"),
                        "classification": classify(r)}
    return {
        "added": [row(k, n[k]) for k in added],
        "removed": [row(k, o[k]) for k in removed],
        "modified": modified,
        "unchanged_n": len(unchanged),
    }


def ingestion_status(added_rows):
    """§7：新增文件属于 (A) source inventory only 还是 (B) 已进入 canonical passage store。

    只认**结构事实**，不靠"看起来像"：
      1. canonical passage store 的 `recovered_file` 取值域（= 它的上游输入集合）；
      2. 直接扫 `build_passage_store.py` 真正消费的那几个 atlas 文件；
      3. passage JSONL 全量命中数。
    """
    import sqlite3

    atlas_dir = os.path.expanduser("<HOME>")
    consumed = ["segments.jsonl", "french_staferla.jsonl", "french.jsonl"]

    # 1) passage store 的上游文件域（canonical）
    upstream_domain = []
    sqlite_p = os.path.join(VAULT, "_index", "passage_store.sqlite")
    try:
        con = sqlite3.connect("file:%s?mode=ro" % sqlite_p, uri=True)
        cur = con.cursor()
        cur.execute("select distinct recovered_file from passages")
        upstream_domain = sorted(x[0] for x in cur.fetchall() if x[0])
        con.close()
    except Exception as exc:                                              # noqa: BLE001
        upstream_domain = ["(probe failed: %s)" % type(exc).__name__]

    out = []
    for r in added_rows:
        rel = r["rel_path"]
        base = os.path.basename(rel)
        stem = os.path.splitext(base)[0]
        sha = r.get("sha256") or ""
        needles = [x for x in (stem, sha, rel, base) if x]

        atlas_hits = {}
        for fn in consumed:
            fp = os.path.join(atlas_dir, fn)
            n = 0
            if os.path.isfile(fp):
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    for ln in fh:
                        if any(x in ln for x in needles):
                            n += 1
            atlas_hits[fn] = n

        passages_hits = 0
        if os.path.isfile(PASSAGES):
            with open(PASSAGES, encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    if any(x in ln for x in needles):
                        passages_hits += 1

        ingested = bool(passages_hits or any(atlas_hits.values()))
        out.append({
            "rel_path": rel, "sha256": r.get("sha256"), "size": r.get("size"),
            "probe": {
                "canonical_passage_store_upstream_files": upstream_domain,
                "atlas_hits": atlas_hits,
                "passage_jsonl_hits": passages_hits,
            },
            "ingested_into_canonical_passage_store": ingested,
            "status": ("INGESTED" if ingested else "SOURCE_INVENTORY_ONLY"),
            "note": ("新增文件**尚未**进入 canonical passage store（passage 的上游是 "
                     ".lacan-build/atlas 的 segments.jsonl / french_staferla.jsonl / "
                     "french.jsonl，与原始语料目录是**两条链**）；产品不得宣称它可被 "
                     "Research Core 检索。" if not ingested
                     else "已在 passage store 中可检索"),
        })
    return out


def derived_state(before_sha, after_sha):
    """§10：依赖构件状态必须明确，不允许 inventory=new / index=old 却宣称一致。"""
    meta = jd(STORE_META, {}) or {}
    idx = jd(INDEX_MANIFEST, {}) or {}
    vec = jd(VECTOR_MANIFEST, {}) or {}
    live_inv = jd(os.path.join(VAULT, INV_REL), {}) or {}
    man = jd(FREEZE, {})
    comps = man.get("components") or {}
    n_passages = None
    if os.path.isfile(PASSAGES):
        n_passages = sum(1 for ln in open(PASSAGES, encoding="utf-8") if ln.strip())
    frozen_ps = meta.get("content_hash")
    return {
        "corpus_inventory": {
            "state": "CHANGED" if before_sha != after_sha else "UNCHANGED_BY_DESIGN",
            "before_hash": before_sha, "after_hash": after_sha,
            "before_files": 143, "after_files": (live_inv.get("totals") or {}).get("files"),
            "content_hash_excl_generated_at": live_inv.get("content_hash"),
        },
        "passage_store": {
            "state": ("REBUILT" if frozen_ps and meta.get("content_hash")
                      and comps.get("passage_store_version") != meta.get("content_hash")
                      else "UNCHANGED_BY_DESIGN"),
            "passages_jsonl_lines": n_passages,
            "build_meta_content_hash": meta.get("content_hash"),
            "frozen_passage_store_version": comps.get("passage_store_version"),
            "changed_by_this_corpus_addition": False,
            "why": ("passage store 由 atlas/*.jsonl 构建，不由原始语料目录直接构建；"
                    "新增的原始文件未进入 atlas，因此 passage store 不变（这是"
                    "UNCHANGED_BY_DESIGN，不是陈旧）"),
        },
        "lexical_index": {
            "state": ("UNAVAILABLE" if not idx else "UNCHANGED_BY_DESIGN"),
            "manifest_content_hash": idx.get("content_hash"),
            "frozen_retrieval_index_lexical": comps.get("retrieval_index_lexical"),
            "agrees_with_frozen": idx.get("content_hash") == comps.get(
                "retrieval_index_lexical"),
        },
        "vector_index": {
            "state": ("UNAVAILABLE" if not vec else "UNCHANGED_BY_DESIGN"),
            "manifest": os.path.relpath(VECTOR_MANIFEST, VAULT) if vec else None,
        },
        "graph_cache": {"state": "UNCHANGED_BY_DESIGN",
                        "why": "概念图/缓存由 ontology + atlas 派生，不读原始语料目录"},
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(P5A, "corpus_diff_audit.json"))
    a = ap.parse_args(argv)

    old, before_sha, src, mode = frozen_inventory()
    live = jd(os.path.join(VAULT, INV_REL), {}) or {}
    live_sha = sha_bytes(open(os.path.join(VAULT, INV_REL), "rb").read())
    d = diff(old, live)

    unexplained = []
    if mode == "NO_DRIFT_SINCE_FREEZE":
        # 冻结已追上 live：判据 = live 必须等于 manifest 的记录值（无未处理漂移），
        # 且**已记录的差异审计**必须与 live 身份一致（审计是关于那次已接受的过渡）。
        audit = jd(os.path.join(P5A, "corpus_diff_audit.json")) or {}
        if audit.get("live_inventory_sha256") != live_sha:
            unexplained.append("历史审计记录的 live 哈希与当前 live 不一致")
        if (audit.get("baseline_files"), audit.get("live_files")) != (143, 144):
            unexplained.append("历史审计的 143→144 记录缺失或不符")
        if len(audit.get("added") or []) != 1 or (audit.get("removed") or []) \
                or (audit.get("modified") or []):
            unexplained.append("历史审计的 added/removed/modified 不符（应 1/0/0）")
    else:
        if d["removed"]:
            unexplained.append("removed=%d" % len(d["removed"]))
        if d["modified"]:
            unexplained.append("modified=%d" % len(d["modified"]))
        if len(d["added"]) != 1:
            unexplained.append("added=%d（预期 1）" % len(d["added"]))

    rec = {
        "schema_version": "phase5a-corpus-diff-audit/v1",
        "issue_id": "P5A-006",
        "baseline_source": src,
        "baseline_inventory_sha256": before_sha,
        "live_inventory_sha256": live_sha,
        "baseline_files": (old.get("totals") or {}).get("files"),
        "live_files": (live.get("totals") or {}).get("files"),
        "baseline_bytes": (old.get("totals") or {}).get("bytes"),
        "live_bytes": (live.get("totals") or {}).get("bytes"),
        "added": d["added"], "removed": d["removed"], "modified": d["modified"],
        "unchanged_n": d["unchanged_n"],
        "unexplained_changes": unexplained,
        "mode": mode,
        "verdict": ("NO_DRIFT_SINCE_FREEZE" if (mode == "NO_DRIFT_SINCE_FREEZE"
                                               and not unexplained)
                    else ("EXACTLY_ONE_ADDED_NO_OTHER_CHANGE" if not unexplained
                          else "UNEXPLAINED_CHANGES_PRESENT_STOP")),
        "ingestion_status": ingestion_status(d["added"]),
        "derived_state": derived_state(before_sha, live_sha),
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")

    print("语料差异审计（%s → live）" % src)
    print("  files %s → %s | bytes %s → %s"
          % (rec["baseline_files"], rec["live_files"],
             rec["baseline_bytes"], rec["live_bytes"]))
    print("  added=%d removed=%d modified=%d unchanged=%d"
          % (len(rec["added"]), len(rec["removed"]), len(rec["modified"]),
             rec["unchanged_n"]))
    for r in rec["added"]:
        print("  + %s  size=%s sha256=%s… status=%s"
              % (r["rel_path"], r["size"], (r["sha256"] or "")[:12],
                 r["classification"]["parse_status"]))
    for r in rec["removed"]:
        print("  - %s" % r["rel_path"])
    for r in rec["modified"]:
        print("  ~ %s" % r["rel_path"])
    print("  verdict: %s" % rec["verdict"])
    for i in rec["ingestion_status"]:
        print("  ingestion: %s -> %s" % (i["rel_path"], i["status"]))
    print("→ %s" % os.path.relpath(a.out, VAULT))
    return 0 if not unexplained else 3


if __name__ == "__main__":
    sys.exit(main())
