#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ontology_gaps.py — Phase 4A §22 Ontology Gap Queue（**只发现，不修复**）

它是什么
────────
一个**候选问题队列**：当系统发现知识库缺东西（缺实体、实体碰撞、缺术语映射、
缺关系）时，追加一条 `candidate` issue。

它**不是**什么（§2/§22/§29）
───────────────────────────
* 不自动补实体、不自动合并概念、不自动建关系、不自动解 ENTITY_COLLISION；
* 不改 `concepts.jsonl`、不改 relations、不改 terminology bridge；
* 队列里的东西**永远**是 `status: candidate`，等人决定。

写入位置
────────
`_data/ontology_gap_queue.jsonl` —— 这是**派生发现记录**，不是 canonical knowledge。
它由 `detected_by` 标明来源，只追加不删除（同一条重复检测会被去重）。

字段（§22 要求至少这些）
────────────────────────
issue_id · issue_type · term/entity · evidence · detected_by · status
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VAULT = os.path.dirname(os.path.dirname(TOOLS))
QUEUE = os.path.join(VAULT, "_data", "ontology_gap_queue.jsonl")

ISSUE_TYPES = (
    "missing_entity",            # 某术语在知识库里没有 entity
    "entity_collision",          # 必须区分的两个概念绑到同一个 entity
    "missing_terminology_mapping",  # Bridge 里没有受控映射
    "missing_relation",          # 概念卡之间没有关系
    "no_linked_passage",         # concept 卡没有 passage 锚点
    "missing_reviewed_definition",
)


def _issue_id(issue_type, key):
    h = hashlib.sha256(("%s|%s" % (issue_type, key)).encode("utf-8")).hexdigest()
    return "ogq.%s" % h[:16]


def _load_existing():
    ids = {}
    if os.path.isfile(QUEUE):
        with open(QUEUE, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    ids[r["issue_id"]] = r
    return ids


# ── 术语有效性过滤（**结构性**，不做语义判断）────────────────────────────
# 为什么必须有：队列第一版把整句 query 与功能词也当成「缺失的术语」记了进来 ——
# 实测出现了 `between` / `does` / `mean` / `Seminar` / `如何讨论` /
# `有什么区别` / `研讨班十一期如何讨论凝视？` 这样的行。
# 一条「候选缺口」如果连**术语**都不是，它就不是缺口，而是噪声：
# 它会让人工复核的时间浪费在假条目上，也会让统计失真。
MAX_TERM_CJK = 12          # 超过这个长度的 CJK「术语」几乎一定是句子片段
MAX_TERM_TOKENS = 3        # 拉丁词超过这个数就是短语/句子

# 「关于知识库自身」的元词：它们在语料里当然有词法命中，但**不是概念术语**。
# 实测噪声来源是「gaze 在知识库里有哪些证据？」这类提问。
META_WORDS = {"证据", "知识库", "语料", "材料", "概念", "术语", "文本", "段落",
              "检索", "结果", "内容", "问题", "方法", "意思", "含义"}

import re as _re


def is_valid_term(term):
    """→ (ok, reason)：这个字符串能不能算「一个术语」。"""
    if not term or not str(term).strip():
        return False, "空"
    t = str(term).strip()
    if t.endswith("?") or t.endswith("？"):
        return False, "以问号结尾（是问题，不是术语）"
    try:
        import query_terms as qt
        STOP = qt.STOP
        FRAGS = qt.QUESTION_FRAGMENTS
    except Exception:
        STOP, FRAGS = set(), ()
    low = t.lower()
    if low in STOP:
        return False, "功能词/停用词"
    for frag in FRAGS:
        if frag and frag in t:
            return False, "含疑问片段 %r" % frag
    if t in META_WORDS:
        return False, "关于知识库自身的元词，不是概念术语"
    try:
        import query_terms as qt2
        if qt2.strip_fragments(t) != t:
            return False, "含期号/疑问写法（是范围短语，不是术语）"
    except Exception:
        pass
    cjk = _re.findall(r"[\u4e00-\u9fff]", t)
    if len(cjk) > MAX_TERM_CJK:
        return False, "CJK 长度 %d > %d（是句子片段）" % (len(cjk), MAX_TERM_CJK)
    if len([w for w in _re.split(r"\s+", t) if w]) > MAX_TERM_TOKENS:
        return False, "词数 > %d（是短语/句子）" % MAX_TERM_TOKENS
    if not cjk and len(_re.sub(r"[^A-Za-z]", "", t)) < 3:
        return False, "过短"
    return True, None


def propose(issue_type, key, term=None, entity=None, evidence=None,
            detected_by="unknown", detail=None, append=True):
    """追加（或去重跳过）一条候选 issue。**只写队列，不写 canonical。**"""
    if issue_type not in ISSUE_TYPES:
        raise ValueError("未知 issue_type: %s（允许：%s）" % (issue_type, ISSUE_TYPES))
    # ⚠️ 无条件校验：`if term is not None` 会让 `term=None` **绕过**过滤 ——
    #    实测队列里就是这样出现 `"term": null` 的行的。
    ok, why = is_valid_term(term)
    if not ok:
        return None              # 噪声不进队列（结构过滤，不是判断）
    iid = _issue_id(issue_type, key)
    row = {
        "schema_version": "ontology-gap-issue/v1",
        "issue_id": iid,
        "issue_type": issue_type,
        "term": term,
        "entity": entity,
        "evidence": evidence or {},
        "detected_by": detected_by,
        "status": "candidate",
        "canonical_change_proposed": False,
        "detail": detail,
        "note": ("这是**发现记录**，不是修复方案。Phase 4A 不自动解决（§22）。"
                 "任何修复都必须由人决定并在 canonical store 上显式操作。"),
    }
    if not append:
        return row
    existing = _load_existing()
    if iid in existing:
        return existing[iid]
    row["detected_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
    with open(QUEUE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def _gap_terms(response):
    """从响应里取「应该被当成术语看待」的候选词（而不是整句 query）。"""
    req = response.get("request") or {}
    t = req.get("term")
    if t:
        return [t]
    q = req.get("query")
    if not q:
        return []
    try:
        import query_terms as qt
        return qt.salient_terms(q)[:6]
    except Exception:
        return []


def from_response(response, detected_by="research_agent"):
    """从任意 tool 响应里抽 ontology gap 候选。**不修改响应**。"""
    out = []
    res = response.get("resolution") or {}
    for gap in res.get("ontology_gaps") or []:
        out.append(propose("missing_entity", gap.get("pair", [None])[0] or "unknown",
                           term=gap.get("pair", [None])[0],
                           entity=gap.get("pair"),
                           evidence={"binding": gap.get("binding"),
                                     "rationale": gap.get("rationale")},
                           detected_by=detected_by,
                           detail=gap.get("message")))
    for col in res.get("collisions") or []:
        out.append(propose("entity_collision", col.get("pair", [None])[0] or "unknown",
                           term=col.get("pair", [None])[0], entity=col.get("pair"),
                           evidence={"binding": col.get("binding")},
                           detected_by=detected_by, detail=col.get("message")))
    if res.get("resolution_status") == "UNRESOLVED":
        # ⚠️ 用**显著词**而不是整句 query：第一版拿 request.query 直接记，
        #    于是队列里出现了 `研讨班十一期如何讨论凝视？` 这种「缺口」。
        for t in _gap_terms(response):
            got = propose("missing_entity", t, term=t,
                          evidence={"tool": (response.get("request") or {}).get("tool")},
                          detected_by=detected_by,
                          detail="术语在 alias index 里没有对应 entity")
            if got:
                out.append(got)
    for w in response.get("warnings") or []:
        if w.get("code") == "NO_CONTROLLED_MAPPING":
            t = (response.get("request") or {}).get("term")
            if t:
                got = propose("missing_terminology_mapping", t, term=t,
                                   evidence={"tool": "terminology_lookup"},
                                   detected_by=detected_by, detail=w.get("message"))
                if got:
                    out.append(got)
    return out


def prune(reason_log=None):
    """一次性清理：删掉**结构上不成立**的历史行（并返回被删的行）。

    为什么允许删：队列是**派生发现记录**，不是 canonical knowledge；
    而被删的行按 `is_valid_term` 连「术语」都不是（整句 query / 功能词）。
    留着它们会让人工复核与统计都被噪声带偏 —— 但删除必须**可审计**：
    `reason_log` 会收到每一行及其被删原因。
    """
    # ⚠️ 必须按**原始行**处理，不能按 `_load_existing()` 的去重结果重写：
    #    后者每个 issue_id 只剩一行，会把所有状态更新行（§9 的 audit trail）
    #    连同被 prune 的那一行一起丢掉 —— 实测把 18 行塌成 9 行。
    raw = []
    if os.path.isfile(QUEUE):
        with open(QUEUE, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    raw.append(json.loads(line))
    removed, kept = [], []
    for r in raw:
        ok, why = is_valid_term(r.get("term"))
        if ok:
            kept.append(r)
        else:
            removed.append({**r, "_removed_because": why})
    if removed:
        tmp = QUEUE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for r in kept:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp, QUEUE)
    if reason_log is not None:
        reason_log.extend(removed)
    return removed


VALID_STATUS = ("candidate", "resolved", "invalidated")


def update_status(issue_id, status, resolution_commit=None, resolved_entity_ids=None,
                  evidence=None, reason=None, append=True):
    """**追加**一条状态更新行（同 issue_id），历史行保留 = audit trail（§9）。

    为什么是追加而不是改写：队列是**发现史**。直接改掉旧行，
    「什么时候发现的、当时依据什么」就消失了；而 §9 明确要求保留。
    `read_all()` 取同 id 的**最后一行**，所以读到的永远是最新状态。
    """
    if status not in VALID_STATUS:
        raise ValueError("未知 status: %s（允许 %s）" % (status, VALID_STATUS))
    rows = _load_existing()
    prev = rows.get(issue_id)
    if not prev:
        return None
    if not append:
        return {**prev, "status": status}
    row = dict(prev)
    row.update({
        "status": status,
        "previous_status": prev.get("status"),
        "status_updated_by": "phase4a.1",
        "resolution_commit": resolution_commit,
        "resolved_entity_ids": resolved_entity_ids or [],
        "resolution_evidence": evidence or [],
        "resolution_reason": reason,
        "audit_trail": "本行是对同 issue_id 的**状态更新**；历史行保留在队列文件中",
    })
    with open(QUEUE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def recheck(log=None):
    """按**当前**代码重新核对每条候选是否仍然成立 → (removed, kept_n)。

    为什么需要它：队列是**派生**的，而派生数据会随代码修复而过期。
    实测：`Symbolic` / `Imaginary` / `Réel` / `désir` 这些行是在
    「冠词归一化」修好**之前**记下的 —— 现在它们都能解析出实体了，
    留着就是**假缺口**。宁可删掉并留审计记录，也不要让队列说谎。
    """
    """按**当前**代码重新核对每条候选是否仍然成立。

    ⚠️ Phase 4A.1 语义变更：不再**删除**失效条目，而是**追加** `status: resolved`
    的状态更新行（§9 要求保留 audit trail）。第一版是删除重写文件 ——
    那会让「这条缺口曾经存在、什么时候被修好的」永久消失。
    → (updated, still_open)
    """
    import knowledge_api as api
    from collections import Counter
    rows = _load_existing()
    updated, still_open = [], []
    commit = None
    try:
        import ontology_v4a1 as onto
        commit = onto.layer_meta().get("resolution_ref")
    except Exception:
        pass
    counts = Counter()
    for iid, r in rows.items():
        if r.get("status") in ("resolved", "invalidated"):
            counts[r["status"]] += 1
            continue
        term = r.get("term")
        itype = r.get("issue_type")
        new_status, why, ents, ev = None, None, [], []
        if itype == "missing_entity":
            res = api.resolve_entity(term)["resolution"]
            if res["resolution_status"] != "UNRESOLVED":
                new_status = "resolved"
                ents = [c["entity_id"] for c in res["candidates"]]
                why = "现在可解析为 %s（status=%s）" % (ents, res["resolution_status"])
                ev = [e["passage_id"] for c in res["candidates"]
                      for e in (api.get_concept(c["entity_id"])["evidence"]
                                if ent_concept(c["entity_id"]) else [])][:3]
        elif itype == "missing_terminology_mapping":
            ev_ = api.terminology_lookup(term)
            if (ev_.get("resolution") or {}).get("candidates"):
                new_status, why = "resolved", "现在已有受控映射"
                ents = [e["entity_id"] for e in ev_["resolution"]["entities"]]
        elif itype == "entity_collision":
            res = api.resolve_entity(term)["resolution"]
            if res["resolution_status"] != "ENTITY_COLLISION":
                new_status = "resolved"
                why = "碰撞已不再复现（status=%s）→ %s" % (res["resolution_status"], ents)
                ents = [c["entity_id"] for c in res["candidates"]]
        if new_status:
            row = update_status(iid, new_status, resolution_commit=commit,
                                resolved_entity_ids=ents, evidence=ev, reason=why)
            updated.append(row)
        else:
            still_open.append(r)
    if log is not None:
        log.extend(updated)
    return updated, still_open


def ent_concept(eid):
    """该 id 是不是概念实体（用于给「已解决」的缺口补证据段号）。"""
    try:
        import ontology_v4a1 as onto
        return bool(onto.entity(eid)) or eid.startswith("concept.")
    except Exception:
        return eid.startswith("concept.")


def stats():
    rows = list(_load_existing().values())
    by_type = {}
    for r in rows:
        by_type[r["issue_type"]] = by_type.get(r["issue_type"], 0) + 1
    by_status = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {"total": len(rows), "by_type": by_type, "by_status": by_status,
            "queue": os.path.relpath(QUEUE, VAULT),
            "all_candidate": all(r["status"] == "candidate" for r in rows),
            "any_canonical_change_proposed": any(
                r.get("canonical_change_proposed") for r in rows)}


def read_all():
    return list(_load_existing().values())


if __name__ == "__main__":
    import sys as _sys
    for flag, fn in (("--prune", prune), ("--recheck", recheck)):
        if flag in _sys.argv:
            log = []
            gone = fn(log)
            for r in gone:
                print("  removed %-24s %r  ← %s"
                      % (r.get("issue_type"), r.get("term"), r["_removed_because"]))
            print("%s：%d 行；剩余 %d 行" % (flag, len(gone), stats()["total"]))
    print(json.dumps(stats(), ensure_ascii=False, indent=1))
