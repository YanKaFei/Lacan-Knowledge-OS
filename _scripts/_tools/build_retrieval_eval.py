#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_retrieval_eval.py — §2 Gold Evaluation Set（人写 spec + 机器解析 gold）

为什么要分两步
──────────────
gold passage **绝不能由人手填 ID** —— 那等于让评测集自己发明答案。
所以：

  1. `_data/retrieval_eval_spec.jsonl`：**人**写 query / intent /
     expected_entities / expected_seminars / language / notes
  2. 本脚本：对每条 query **确定性解析**出 gold_passages / acceptable_passages，
     全部 ID 都从 canonical passage store 里查出来

于是评测集的「答案」是可复核、可重生成的：改语料 → 重跑 → gold 自动更新，
且不可能出现不存在的 passage ID。

gold 的判定（确定性，可解释）
─────────────────────────────
* **gold_passages**：在 canonical store 里，`raw_text` **确实包含**该 query
  期望实体别名（或引号短语）的 Passage，按 (seminar, id) 排序取前 N。
  这是「一个正确答案必须至少命中其中一条」的基准集。
* **acceptable_passages**：命中该 query 的次要线索（例如同实体的其他写法、
  相关概念的别名）—— 命中算对但不强制。

允许多个 gold：一条 query 的 gold 本来就可能很多（用户 §2 明确要求
「不要为了方便强迫每题只有一个答案」）。

用法
────
    python3 build_retrieval_eval.py               # 从 spec 生成 retrieval_eval.jsonl
    python3 build_retrieval_eval.py --stats       # 只打印统计
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

STORE = os.path.join(VAULT, "_data", "passage_store")
SPEC = os.path.join(VAULT, "_data", "retrieval_eval_spec.jsonl")
OUT = os.path.join(VAULT, "retrieval_eval.jsonl")

# ── gold 抽样策略（本轮修正，原先有系统性偏差）
#
# 第一版 gold = 「语料扫描顺序里前 40 条含该词的段」。实测该做法有**系统性偏差**：
# 每期被扫描到的先后决定了谁进 gold，于是 S01 独占 57%、≤S05 占 78% ——
# gold 变成「早期研讨班抽样」，而不是「相关段落」。
# 而 BM25 返回的是**跨全语料的**最佳匹配（S06–S24 居多），两者交集常为空。
# 结果：Recall 测的是**截断偏差**，不是检索质量（实测 Recall@20 仅 0.31，
# 但那不是检索的真实水平）。
#
# 修正：**按 seminar 分层抽样**（每期最多 GOLD_PER_SEMINAR 条），
# 并保持总量上限。这样 gold 覆盖语料全期，度量才有意义。
GOLD_PER_SEMINAR = 3   # 每期最多进 gold 的条数
GOLD_CAP = 40          # gold 总量上限

# ★ 诚实声明（必须随产物一起被读到）
#
# 本文件的 gold 是**词面推导的 proxy**，不是人工标注的 ground truth。
# 它能可靠回答的是：「检索能否找到**字面提及**该概念的段落」；
# 它**不能**回答：「检索能否找到**主题相关**的段落」—— 因为「含该词」
# 与「关于该主题」并不等价（列术语表的段落也会含该词）。
#
# 因此：
#   * Recall 类指标应读作 **lexical proxy / 上界**，不是检索质量的真值；
#   * 更可解释的头条数字是 **per-query hit rate**（top-k 内命中至少一条 gold 的查询占比），
#     因为 Recall 会被大 gold 集稀释（gold 均值 ~18 条，命中均值 <1 条）。
#   * 期内仍存在「取前 N 条」的顺序效应：gold 段号中位远小于每期段数。
#     这需要人工标注才能根治，本阶段不做（见 PHASE3_FINDINGS §3.0b）。
ACCEPT_CAP = 20        # acceptable 上限

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_APOS = re.compile(r"['\u2019\u02bc]")
_HYPH = re.compile(r"[-\u2010-\u2015]")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def norm(s):
    """宽容归一化：大小写、变音、撇号、连字符、标点、空白全部抹平。

    只用于**评测的匹配判定**（gold 查找），不写回任何 canonical 文本。
    """
    s = unicodedata.normalize("NFKC", str(s))
    s = _APOS.sub("", s)
    s = _HYPH.sub("", s)
    s = strip_accents(s)
    s = _NONWORD.sub("", s)
    return s.lower()


def load_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def load_concepts():
    return {c["id"]: c for c in load_jsonl(os.path.join(STORE, "concepts.jsonl"))}


def entity_needles(concept):
    """把一个概念的所有写法收集成 needles（用于在语料里找 gold）。

    §3.0b 收紧（本轮修正）：原先直接收全部写法，于是出现
    `the other big other`（其实是 `the Other / big Other` 被斜杠/空格切出的**碎片**）
    这类宽 needle，宽 needle + 全库子串匹配必然命中大量**非主题**段落。
    实测 gold 段号中位仅 69（每期数千段）—— 说明 gold 系统性地落在
    每期**开头**，因为宽 needle 在开头就已被满足。

    修正：剔除「是另一个 needle 的（真）子串」的写法，只保留高区分度者。
    这一步不引入循环论证（不依赖检索结果），只是去掉冗余。
    """
    out = set()
    for k in ("canonical_name", "fr", "en", "zh", "title"):
        v = concept.get(k)
        if v:
            for part in re.split(r"[/／|]", str(v)):
                part = part.strip()
                if part:
                    out.add(part)
    for a in concept.get("aliases") or []:
        a = str(a).strip()
        if a:
            out.add(a)
    # 去掉过短或过泛的 needle（避免「a」「$」这种把整库都变成 gold）
    out = {n for n in out if len(norm(n)) >= 2}
    # 剔除「是更长 needle 的真子串」的碎片（真子串 = 两侧不是字母/汉字）
    import re as _re
    keep = set()
    for n in out:
        nn = norm(n)
        redundant = False
        for m in out:
            if m is n:
                continue
            mm = norm(m)
            if len(mm) <= len(nn):
                continue
            for mt in _re.finditer(_re.escape(nn), mm):
                a = mm[mt.start() - 1] if mt.start() > 0 else ""
                b = mm[mt.end()] if mt.end() < len(mm) else ""
                if not a.isalnum() and not b.isalnum():
                    redundant = True
                    break
            if redundant:
                break
        if not redundant:
            keep.add(n)
    return sorted(keep or out, key=lambda x: (-len(x), x))


def scan_store(needles_by_entity):
    """一次扫描 passages.jsonl，为每个 needle 记录命中的 passage。

    返回 {needle_norm: [(seminar_id, passage_id, language)]}
    """
    # 展平：needle_norm -> [entity_id]
    needle_owner = {}
    for eid, needles in needles_by_entity.items():
        for n in needles:
            needle_owner.setdefault(norm(n), set()).add(eid)

    hits = {}
    all_needles = list(needle_owner.keys())
    pp = os.path.join(STORE, "passages.jsonl")
    with open(pp, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            body = norm(d["raw_text"])
            if not body:
                continue
            for n in all_needles:
                # 不再按「前 N 条」截断 —— 截断会按语料顺序偏向低期号。
                # 全量收集，抽样交给后面的**按 seminar 分层**处理。
                if n in body:
                    hits.setdefault(n, []).append(
                        (d["seminar_id"], d["id"], d["language"]))
    return hits, needle_owner


def _by_seminar(pairs):
    out = {}
    for sem, pid in pairs:
        out.setdefault(sem, []).append(pid)
    return {k: sorted(v) for k, v in sorted(out.items())}


def stratified_sample(pairs, per_seminar=GOLD_PER_SEMINAR, cap=GOLD_CAP):
    """按 seminar 分层抽样，消除「扫描顺序 → 低期号偏向」。

    pairs: [(seminar_id, passage_id)]（可能含重复）
    每期最多取 per_seminar 条，总量不超过 cap。
    期内按 passage_id 排序 → 确定性。
    """
    by_sem = {}
    for sem, pid in pairs:
        by_sem.setdefault(sem, set()).add(pid)
    out = []
    for sem in sorted(by_sem):
        picks = sorted(by_sem[sem])[:per_seminar]
        for pid in picks:
            out.append((sem, pid))
    out.sort(key=lambda x: (x[0], x[1]))
    return out[:cap]


def build(spec_path=SPEC, out_path=OUT, quiet=False):
    spec = load_jsonl(spec_path)
    concepts = load_concepts()
    needles_by_entity = {eid: entity_needles(c) for eid, c in concepts.items()}
    hits, needle_owner = scan_store(needles_by_entity)

    rows = []
    for q in spec:
        gold, accept = set(), set()
        # ---- 主线索：期望实体
        for eid in q.get("expected_entities") or []:
            for n in needles_by_entity.get(eid, []):
                for sem, pid, lang in hits.get(norm(n), []):
                    gold.add((sem, pid))
        # ---- 引号短语：作为额外主线索
        for ph in re.findall(r'["“”「『]([^"“”」』]{2,})["“”」』]', q["query"]):
            for n in [ph]:
                for sem, pid, lang in hits.get(norm(n), []):
                    gold.add((sem, pid))
        # ---- 次要线索：其余实体的写法（acceptable）
        for eid in q.get("expected_entities") or []:
            for n in needles_by_entity.get(eid, []):
                for sem, pid, lang in hits.get(norm(n), []):
                    accept.add((sem, pid))

        # ---- seminar 约束：有期望期号时，gold 限定在该期内
        #（§3.0c：原先只在「限定期后 gold 为空」时才回退，等于没约束 ——
        #  于是 `Seminar XI 里 gaze 与 object a` 的 gold 会跨全语料。）
        sems = set(q.get("expected_seminars") or [])
        if sems:
            gold = {g for g in gold if g[0] in sems}
            accept = {a for a in accept if a[0] in sems}
        # 若限定期后 gold 为空（该期里没有该词的精确命中），
        # 退回该期的代表段作为 gold —— 但必须**显式记录**这是期级回退，
        # 不允许静默把「没找到」变成「找到了」。
        fallback_used = False
        if sems and not gold:
            fallback_used = True
            with open(os.path.join(STORE, "passages.jsonl"), encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    d = json.loads(line)
                    if d["seminar_id"] in sems:
                        gold.add((d["seminar_id"], d["id"]))
                        if len(gold) >= GOLD_CAP:
                            break

        # 分层抽样（修正系统性偏差）
        gold_sorted = stratified_sample(sorted(gold))
        # acceptable **必须是 gold 的子集**（命名暗示包含关系，原先不成立）
        accept_pool = [p for p in sorted(accept) if p in set(gold_sorted)]
        accept_sorted = stratified_sample(accept_pool,
                                          per_seminar=GOLD_PER_SEMINAR,
                                          cap=ACCEPT_CAP)

        rows.append({
            "query_id": q["query_id"],
            "query": q["query"],
            "intent": q["intent"],
            "expected_entities": q.get("expected_entities") or [],
            "expected_seminars": q.get("expected_seminars") or [],
            "gold_passages": [p for _, p in gold_sorted],
            "acceptable_passages": [p for _, p in accept_sorted],
            "gold_by_seminar": _by_seminar(gold_sorted),
            "language": q.get("language") or "und",
            "notes": q.get("notes") or "",
            "gold_source": ("seminar_level_fallback" if fallback_used
                            else "entity_needle_match"),
            # 没有 gold 必须**如实记录原因**，且评测时**不计入 recall 分母** ——
            # 否则等于把「语料里确实没有」伪装成「检索失败」，
            # 或者反过来用期级回退把空 gold 填满（两者都是粉饰）。
            "no_gold_reason": (None if gold_sorted else
                               ("no_expected_entities" if not (q.get("expected_entities") or [])
                                else "expected_entities_absent_from_corpus")),
            "counted_in_recall": bool(gold_sorted),
            "gold_derivation": {
                "method": ("在 canonical store 的 raw_text 里做宽容归一化子串匹配；"
                           "再**按 seminar 分层抽样**（每期 ≤%d 条，总量 ≤%d）"
                           "以消除「按语料扫描顺序截断 → 偏向低期号」的系统性偏差"
                           % (GOLD_PER_SEMINAR, GOLD_CAP)
                           + ("；该期无精确命中 → 回退为该期代表段（已显式标注）"
                              if fallback_used else "")),
                "acceptable_is_subset_of_gold": True,
                "needles_used": sorted({norm(n) for eid in
                                        (q.get("expected_entities") or [])
                                        for n in needles_by_entity.get(eid, [])}),
            },
        })

    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    stats = {
        "queries": len(rows),
        "with_gold": sum(1 for r in rows if r["gold_passages"]),
        "without_gold": sum(1 for r in rows if not r["gold_passages"]),
        "fallback_used": sum(1 for r in rows
                             if r["gold_source"] == "seminar_level_fallback"),
        "by_intent": {},
    }
    for r in rows:
        stats["by_intent"][r["intent"]] = stats["by_intent"].get(r["intent"], 0) + 1
    if not quiet:
        print(f"[eval] {stats['queries']} 条 query；有 gold {stats['with_gold']}、"
              f"无 gold {stats['without_gold']}、期级回退 {stats['fallback_used']}",
              file=sys.stderr)
        print(f"[eval] -> {out_path}", file=sys.stderr)
    return stats


def main():
    ap = argparse.ArgumentParser(description="生成 Gold Evaluation Set（§2）")
    ap.add_argument("--spec", default=SPEC)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()
    st = build(args.spec, args.out, quiet=args.stats)
    if args.stats:
        print(json.dumps(st, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
