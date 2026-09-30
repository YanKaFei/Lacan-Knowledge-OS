#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_concept_source_candidates.py — §22 Gold Concept 溯源候选（**只产候选，绝不晋级**）

背景
────
53 个 Gold Concept 里 **43 个** `passages == []`（`trace_status = SOURCE_TRACE_INCOMPLETE`）。
它们来自术语表（`catalog_source = terms_catalog_c.TERMS_C`），definition 是手写的，
`source_notes` 只提到研讨班号，**没有任何 passage 锚点**。

Phase 3B 时这份工作被记为「未实现」，理由是向量路径被运行时阻断 ——
而 vector 恰恰是最高质量的一路。现在运行时恢复了，所以本轮把它做掉。

铁律（写进每条记录，也写进校验）
────────────────────────────────
* 全部 `review_status = "candidate"`、`canonical = false`
* **绝不**写回 `concepts.jsonl`、**绝不**改 vault 里的概念卡
* 脚本/AI 产生的候选**永不自动晋级**为 canonical（§23 硬门禁
  `automatic_source_link_canonicalization = 0`）

候选来源（三路 + 一个约束），全部走**已有**的检索组件
──────────────────────────────────────────────────────
| 代号 | 来源 | 实现 |
|---|---|---|
| `exact` | 别名精确短语 | `lacan_search.lexical_search(alias, phrase=True)` |
| `lexical` | FTS5 BM25 | `lacan_search.lexical_search(query)` |
| `vector` | 语义 | **对 lexical 前 K 条做向量重排**（见下方限制） |
| `metadata` | 期号/领域 | `period` → seminar 范围（**加分不硬过滤**） |

⚠️ **vector 这一路的限制必须说清**：全量 249,105 条的向量索引**仍未构建**
（`VECTOR_INDEX_MANIFEST.status = NOT_BUILT`，§21 门禁未过）。
所以这里不是「全库向量检索」，而是「**词法召回的前 K 条内做向量重排**」——
它的召回上限被词法锁住。这是诚实的能力边界，不是等价替代。

融合：RRF(k=60)，只用名次。

用法
────
    .venv-embedding/bin/python _scripts/_tools/build_concept_source_candidates.py --run
    python3 _scripts/_tools/build_concept_source_candidates.py --verify
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
TOOLS = HERE
sys.path.insert(0, TOOLS)

CONCEPTS = os.path.join(STORE, "concepts.jsonl")
ALIAS_COLLISIONS = os.path.join(VAULT, "_data", "index", "alias_collisions.jsonl")
OUT_JSONL = os.path.join(VAULT, "concept_source_link_candidates.jsonl")
OUT_JSON = os.path.join(VAULT, "_data", "index", "concept_source_link_report.json")
REPORT = os.path.join(VAULT, "SOURCE_LINKING_REPORT.md")

RRF_K = 60
LEX_CANDIDATES = 200      # vector 重排的候选上限（受词法召回限制）
TOP_K = 5                 # 每个 concept 最多保留多少候选
MIN_ALIAS_LEN = 3         # 过短的别名会产生大量假命中


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_passage_texts(ids):
    """**一次**流式扫描 passages.jsonl，只留需要的 id。

    ⚠️ 不要在每个 concept 的循环里调用它 —— passages.jsonl 有 249,105 行 / 384 MB，
    逐个 concept 扫一遍就是 43 次全表扫描（实测会从几十秒变成几十分钟）。
    """
    want = set(ids)
    out = {}
    with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
        for line in f:
            if not want:
                break
            d = json.loads(line)
            if d["id"] in want:
                out[d["id"]] = d
                want.discard(d["id"])
    return out


# ── period → seminar 范围（来自 query_router 的分期表，不新造数据）
def seminar_range_ok(seminar_id, period):
    if not period or not seminar_id:
        return False
    try:
        import query_router
        table = getattr(query_router, "_SEM_PERIOD", None) or {}
        n = int(re.sub(r"\D", "", seminar_id) or 0)
        return table.get(n) == period
    except Exception:
        return False


def concept_terms(c):
    """concept → (查询串, 别名列表)。只用卡片自己的字段，不用外部知识。"""
    terms = []
    for k in ("canonical_name", "zh", "fr", "en"):
        v = c.get(k)
        if isinstance(v, str) and v.strip():
            terms.append(v.strip())
    for a in c.get("aliases") or []:
        if isinstance(a, str) and a.strip():
            terms.append(a.strip())
    # 去重保序
    seen, out = set(), []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    query = " ".join(out[:4])
    return query, out


def run(models=("minilm",), top_k=TOP_K, verbose=True):
    """三阶段：① 词法/别名召回收集 id ② **一次**读盘 ③ 向量重排 + 融合。

    三阶段是必要的：passages.jsonl 有 249,105 行 / 384 MB，
    如果在 concept 循环里查文本，就是 43 次全表扫描。
    """
    import numpy as np
    import lacan_search
    import embedding_provider as ep

    concepts = jl(CONCEPTS)
    unresolved = [c for c in concepts if not c.get("passages")]
    if verbose:
        print("[concept] 总 %d，未溯源 %d" % (len(concepts), len(unresolved)))

    collisions = set()
    if os.path.isfile(ALIAS_COLLISIONS):
        for r in jl(ALIAS_COLLISIONS):
            a = r.get("alias") or r.get("surface")
            if a:
                collisions.add(a.strip().lower())

    prov = {}
    for m in models:
        p = ep.OnnxTransformersProvider(m)
        if not p.available:
            raise SystemExit("provider %s 不可用: %s" % (m, p.blocked_reason))
        prov[m] = p

    before_hash = sha256_file(CONCEPTS)

    # ── 阶段 ①：只用词法/别名（不需要正文）
    plan = []
    all_ids = set()
    for c in unresolved:
        query, terms = concept_terms(c)
        exact, used_alias = {}, {}
        for a in terms:
            if len(re.sub(r"\W", "", a)) < MIN_ALIAS_LEN:
                continue
            try:
                hits = lacan_search.lexical_search(a, phrase=True, limit=200)
            except Exception:
                hits = []
            for i, h in enumerate(hits):
                pid = h["passage_id"]
                exact[pid] = max(exact.get(pid, 0.0), 1.0 / (1 + i))
                used_alias.setdefault(pid, a)
        try:
            lex_hits = lacan_search.lexical_search(query, limit=LEX_CANDIDATES)
        except Exception:
            lex_hits = []
        lex_rank = {}
        for i, h in enumerate(lex_hits, 1):
            lex_rank.setdefault(h["passage_id"], i)
        ids = list(lex_rank)[:LEX_CANDIDATES]
        all_ids |= set(ids)
        all_ids |= set(exact)
        plan.append((c, query, terms, exact, used_alias, lex_rank, ids))
        if verbose:
            print("  %-34s exact=%-4d lex=%-5d" % (c["id"], len(exact), len(lex_rank)))

    # ── 阶段 ②：一次读盘
    if verbose:
        print("[store] 需要 %d 条 passage，单次扫描 passages.jsonl …" % len(all_ids))
    db = load_passage_texts(all_ids)
    if verbose:
        print("[store] 取到 %d 条" % len(db))

    # ── 阶段 ③：向量重排 + 融合
    rows = []
    stats = {"with_candidates": 0, "no_candidate": 0, "verbatim_top1": 0,
             "vector_only_top1": 0, "ambiguous_alias_top1": 0}
    review_sample = []
    for c, query, terms, exact, used_alias, lex_rank, ids in plan:
        ids = [p for p in ids if p in db]
        vec_rank = {}
        if ids:
            qvs = {m: np.asarray(prov[m].embed_queries([query])[0], dtype="float32")
                   for m in models}
            sim = None
            for m in models:
                mat = np.asarray(prov[m].embed_documents(
                    [db[p]["normalized_text"] for p in ids], batch_size=16),
                    dtype="float32")
                s = mat @ qvs[m]
                sim = s if sim is None else sim + s
            sim = sim / len(models)
            order = np.lexsort((np.asarray(ids), -sim))
            for i, j in enumerate(order, 1):
                vec_rank[ids[j]] = i
        meta_ids = {p for p in ids if seminar_range_ok(db[p].get("seminar_id"), c.get("period"))}

        scores = {}
        for i, (pid, _) in enumerate(sorted(exact.items(), key=lambda x: (-x[1], x[0])), 1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + i)
        for pid, r in lex_rank.items():
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + r)
        for pid, r in vec_rank.items():
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + r)
        for pid in meta_ids:
            if pid in scores:
                scores[pid] += 1.0 / (RRF_K + 1)

        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:top_k]
        if not ranked:
            stats["no_candidate"] += 1
            review_sample.append((c, []))
            continue
        stats["with_candidates"] += 1
        concept_rows = []
        for rank, (pid, sc) in enumerate(ranked, 1):
            d = db[pid]
            text = d.get("normalized_text") or ""
            low = text.lower()
            matched_alias, verbatim = used_alias.get(pid), False
            for t in terms:
                if len(re.sub(r"\W", "", t)) >= MIN_ALIAS_LEN and t.lower() in low:
                    verbatim = True
                    matched_alias = matched_alias or t
                    break
            srcs = [n for n, tbl in (("exact", exact), ("lexical", lex_rank),
                                     ("vector", vec_rank)) if pid in tbl]
            if pid in meta_ids:
                srcs.append("metadata")
            row = {
                "schema_version": "concept-source-link-candidate/v1",
                "concept_id": c["id"],
                "concept_name": c.get("canonical_name"),
                "concept_language": c.get("language"),
                "concept_period": c.get("period"),
                "query_used": query,
                "candidate_passage_id": pid,
                "rank": rank,
                "rrf_score": round(sc, 8),
                "candidate_sources": srcs,
                "matched_alias": matched_alias,
                "verbatim_match": verbatim,
                "period_match": pid in meta_ids,
                "passage_language": d.get("language"),
                "seminar_id": d.get("seminar_id"),
                "session_id": d.get("session_id"),
                "authority_level": d.get("authority_level"),
                "trace_status": d.get("trace_status"),
                "candidate_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "review_status": "candidate",
                "canonical": False,
                "promotion_rule": ("脚本/AI 产生的候选**永不**自动晋级为 canonical；"
                                   "必须人工审阅并在概念卡上显式登记。"),
                "proposed_by": "script:build_concept_source_candidates.py",
                "proposal_reason": "concept 卡片无任何 passage 锚点（SOURCE_TRACE_INCOMPLETE）",
            }
            rows.append(row)
            concept_rows.append(row)
        if concept_rows:
            if concept_rows[0]["verbatim_match"]:
                stats["verbatim_top1"] += 1
            if concept_rows[0]["candidate_sources"] == ["vector"]:
                stats["vector_only_top1"] += 1
            al = (concept_rows[0].get("matched_alias") or "").strip().lower()
            if al and al in collisions:
                stats["ambiguous_alias_top1"] += 1
        review_sample.append((c, concept_rows))

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    after_hash = sha256_file(CONCEPTS)
    report = {
        "schema_version": "concept-source-link-report/v1",
        "unresolved_concepts": len(unresolved),
        "candidates_written": len(rows),
        "per_concept_top_k": top_k,
        "candidate_sources": {
            "exact": "别名精确短语（FTS phrase）",
            "lexical": "FTS5 BM25",
            "vector": ("★ 对词法前 %d 条做向量重排（**不是**全库向量检索 —— "
                       "全量索引仍未构建，见 VECTOR_INDEX_MANIFEST）" % LEX_CANDIDATES),
            "metadata": "period → seminar 范围，加分不硬过滤",
        },
        "sampling_eval": {
            "top5_coverage": stats["with_candidates"] / max(1, len(unresolved)),
            "no_candidate_count": stats["no_candidate"],
            "top1_verbatim_rate": stats["verbatim_top1"] / max(1, stats["with_candidates"]),
            "top1_verbatim_definition": (
                "**代理指标，不是精度**：top-1 候选的正文里是否**字面出现**该概念的"
                "某个别名/术语（长度 ≥%d）。它只能排除一部分假命中，"
                "不能证明语义正确 —— 真正的 precision 需要人工判定。" % MIN_ALIAS_LEN),
            "top1_vector_only_count": stats["vector_only_top1"],
            "top1_ambiguous_alias_count": stats["ambiguous_alias_top1"],
            "fp_patterns": [
                "仅由 `vector` 支撑的 top-1：没有词面证据，最可能是假命中（已在报告里单列）",
                "别名短于 %d 个字符：任何包含该字串的段落都会被命中" % MIN_ALIAS_LEN,
                "出现在 alias_collisions.jsonl 里的别名：多实体共用同一写法",
                "法术混合概念（fr 与 zh 别名进同一查询）：向量被两段语言拉向不同方向",
            ],
        },
        "hard_gates": {
            "automatic_source_link_canonicalization": 0,
            "non_candidate_review_status": 0,
            "concept_store_modified": int(before_hash != after_hash),
        },
        "hashes": {"concepts_jsonl_before": before_hash,
                   "concepts_jsonl_after": after_hash,
                   "output": sha256_file(OUT_JSONL) if os.path.isfile(OUT_JSONL) else None},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    json.dump(report, open(OUT_JSON, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    if verbose:
        print("[out] %s（%d 条候选）" % (OUT_JSONL, len(rows)))
        print("[gate] hard_gates = %s" % json.dumps(report["hard_gates"]))
    write_report(report, review_sample, rows)
    return report


def snippet(text, n=90):
    t = " ".join((text or "").split())
    return (t[:n] + "…") if len(t) > n else t


def write_report(report, sample, rows):
    text_by_pid = {}
    ids = [r["candidate_passage_id"] for r in rows]
    if ids:
        ps = load_passage_texts(ids)
        text_by_pid = {p: (d.get("normalized_text") or "") for p, d in ps.items()}
    L = []
    A = L.append
    A("# SOURCE_LINKING_REPORT.md — §22 Gold Concept 溯源**候选**（不是溯源结论）\n")
    A("> 生成：`_scripts/_tools/build_concept_source_candidates.py`　·　"
      "产物：`concept_source_link_candidates.jsonl`　·　"
      "统计：`_data/index/concept_source_link_report.json`\n")
    A("## 0. 状态：候选已产出，**但没有一个字被晋级**\n")
    A("| 项 | 值 |")
    A("|---|---:|")
    A("| 未溯源 Gold Concept | **%d** |" % report["unresolved_concepts"])
    A("| 产出候选条数 | %d |" % report["candidates_written"])
    A("| 有候选的 concept | %d / %d（top-5 覆盖率 %.3f） |" % (
        report["unresolved_concepts"] - report["sampling_eval"]["no_candidate_count"],
        report["unresolved_concepts"], report["sampling_eval"]["top5_coverage"]))
    A("| 一条候选都没有的 concept | **%d** |" % report["sampling_eval"]["no_candidate_count"])
    A("| 全部候选 `review_status = candidate` | ✅ |")
    A("| `canonical` 字段全为 false | ✅ |")
    A("| 硬门禁 `automatic_source_link_canonicalization` | **%d** |" % report["hard_gates"]["automatic_source_link_canonicalization"])
    A("| `concepts.jsonl` 是否被改动 | **%s** |" % ("否（hash 前后一致）" if report["hard_gates"]["concept_store_modified"] == 0 else "**是**"))
    A("")
    A("**这仍然是 PARTIAL。** 候选 ≠ 溯源。43 个 concept 的 `trace_status` 依旧是 "
      "`SOURCE_TRACE_INCOMPLETE`，卡片依旧是 `needs_review` —— "
      "除非有人**逐条人工确认**，它们不该变。\n")
    A("## 1. 候选从哪来（以及 vector 那一路的真实能力边界）\n")
    A("| 代号 | 来源 |")
    A("|---|---|")
    for k, v in report["candidate_sources"].items():
        A("| `%s` | %s |" % (k, v))
    A("")
    A("⚠️ **`vector` 不是全库向量检索。** 全量 249,105 条的向量索引**仍未构建**"
      "（`VECTOR_INDEX_MANIFEST.status = NOT_BUILT`，§21 门禁未过）。"
      "这里做的是「**词法召回前 %d 条之内**做向量重排」——"
      "它的召回上限被词法锁死。写成「已实现语义溯源」就是夸大。\n" % LEX_CANDIDATES)
    A("融合：RRF(k=%d)，只用名次，不用不可比的原始分数。\n" % RRF_K)
    A("## 2. §19 抽样评测\n")
    se = report["sampling_eval"]
    A("| 指标 | 值 |")
    A("|---|---:|")
    A("| top-5 覆盖率 | %.4f |" % se["top5_coverage"])
    A("| 无候选 concept 数 | %d |" % se["no_candidate_count"])
    A("| top-1 字面命中率 | %.4f |" % se["top1_verbatim_rate"])
    A("| top-1 仅由 vector 支撑 | %d |" % se["top1_vector_only_count"])
    A("| top-1 用了碰撞别名 | %d |" % se["top1_ambiguous_alias_count"])
    A("")
    A("**「top-1 字面命中率」是代理指标，不是 precision。** %s\n" % se["top1_verbatim_definition"])
    A("已识别的假阳性模式：\n")
    for p in se["fp_patterns"]:
        A("- %s" % p)
    A("")
    A("## 3. 抽样明细（**等人看，不是结论**）\n")
    A("下面是**确定性抽样**（未溯源 concept 里每 4 个取 1 个）的 top-3 候选。"
      "每一条都需要人来判断「这段真的在讲这个概念吗」。\n")
    for i, (c, crow) in enumerate(sample):
        if i % 4:
            continue
        A("### `%s` — %s（%s，%s）\n" % (
            c["id"], c.get("canonical_name"), c.get("zh") or "", c.get("period") or "—"))
        A("查询串：`%s`\n" % crow[0]["query_used"] if crow else "")
        A("| # | passage | 来源 | 字面命中 | 期号匹配 | 正文片段 |")
        A("|---|---|---|---|---|---|")
        for r in crow[:3]:
            A("| %d | `%s` | %s | %s | %s | %s |" % (
                r["rank"], r["candidate_passage_id"], "+".join(r["candidate_sources"]),
                "✓" if r["verbatim_match"] else "✗", "✓" if r["period_match"] else "✗",
                snippet(text_by_pid.get(r["candidate_passage_id"], "")).replace("|", "/")))
        A("")
    A("## 4. 晋级规则（不可绕过）\n")
    A("1. 候选全部落在 `concept_source_link_candidates.jsonl`，**不在 vault 里**。")
    A("2. 概念卡只在**人工确认**后才登记 passage，且登记时必须写明确认人。")
    A("3. 本脚本**没有**写 `concepts.jsonl`（hash 前后一致，见 §0 表）。")
    A("4. 硬门禁 `automatic_source_link_canonicalization` 必须保持 0。\n")
    A("## 5. 不能声称的东西\n")
    A("- 不能说「43 个 concept 已溯源」—— 只产出了候选。")
    A("- 不能说候选质量已验证 —— 抽样表是给人看的，没经过人工标注。")
    A("- 不能把 top-1 字面命中率当 precision 使用。")
    A("- 不能用这份结果推断全库语义检索能力（vector 只在前 %d 条词法候选内重排）。" % LEX_CANDIDATES)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("[report] %s" % REPORT)


def cmd_verify():
    problems = []
    if not os.path.isfile(OUT_JSONL):
        return {"status": "FAIL", "problems": ["缺 concept_source_link_candidates.jsonl"]}
    rows = jl(OUT_JSONL)
    if not rows:
        problems.append("候选为空")
    for r in rows:
        if r.get("review_status") != "candidate":
            problems.append("非 candidate 的 review_status: %s" % r.get("concept_id"))
            break
    if any(r.get("canonical") is not False for r in rows):
        problems.append("出现 canonical=true 的候选 —— 自动晋级被触发")
    rep = json.load(open(OUT_JSON, encoding="utf-8")) if os.path.isfile(OUT_JSON) else {}
    hg = rep.get("hard_gates", {})
    for k, v in hg.items():
        if v != 0:
            problems.append("硬门禁 %s=%s" % (k, v))
    if rep.get("hashes", {}).get("concepts_jsonl_before") != \
            rep.get("hashes", {}).get("concepts_jsonl_after"):
        problems.append("concepts.jsonl 被改动了")
    elif sha256_file(CONCEPTS) != rep.get("hashes", {}).get("concepts_jsonl_after"):
        problems.append("concepts.jsonl 现在的 hash 与生成时不一致")
    return {"status": "PASS" if not problems else "FAIL", "problems": problems,
            "candidates": len(rows), "hard_gates": hg}


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--models", default="minilm")
    ap.add_argument("--top-k", type=int, default=TOP_K)
    a = ap.parse_args(argv)
    if a.run:
        run(models=tuple(a.models.split(",")), top_k=a.top_k)
        return 0
    r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
