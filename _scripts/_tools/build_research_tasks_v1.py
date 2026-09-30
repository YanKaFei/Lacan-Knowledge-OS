#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_research_tasks_v1.py — Phase 4B §3–§5：建立**真实研究任务集**

为什么 gold 由脚本推导而不是手写
────────────────────────────────
手写 gold 段号 = 用我的记忆冒充知识库事实。这里的做法与 Phase 3 的 gold 推导同源：
为每个任务声明**词面 needle（按 lane / 语言 / 研讨班）**，在 canonical store 上现算
并**逐个核对段号真实存在**，再按研讨班分层抽样。

匹配规则（写死在代码里，可复核）
────────────────────────────────
* NFKC → 去撇号/连字符 → 去变音 → 去标点 → 小写 → **再去掉空白**
  （去空白是刻意的：实测同一术语在语料里有 `plus-de-jouir` / `plus de jouir` 两种写法，
   不去空白会漏掉 167 段中的大部分）。
* 按 `language` 过滤；按 `seminar` 限定时只在该期内取样。
* 分层抽样：每期 ≤3 条、每 lane ≤20 条（与 Phase 3 gold 同法，避免偏向低期号）。

不可答任务（J 类）
──────────────────
**不填 gold**，而是记录 `no_gold_reason` + **实测 needle 计数**（证明「库里确实没有」，
而不是我猜的）。`review_status` 一律 `script_assisted_unreviewed`：
没有第二个人工标注者，就不假装有。

产物
────
    _data/eval/research_tasks_v1.jsonl       全量（含 gold，供 evaluator）
    _data/eval/research_tasks_v1.public.jsonl 公开视图（Agent 只看得到这些字段）
    _data/eval/research_tasks_v1.gold_derivation.json  推导审计（needle 计数等）

用法
────
    python3 build_research_tasks_v1.py [--check]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
STORE = os.path.join(VAULT, "_data", "passage_store")
EVAL = os.path.join(VAULT, "_data", "eval")
TASKS = os.path.join(EVAL, "research_tasks_v1.jsonl")
PUBLIC = os.path.join(EVAL, "research_tasks_v1.public.jsonl")
DERIV = os.path.join(EVAL, "research_tasks_v1.gold_derivation.json")

PER_SEMINAR_CAP = 3
PER_LANE_CAP = 20
ACCEPTABLE_CAP = 40

_APOS = re.compile(r"['’`]")
_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)

PUBLIC_FIELDS = ("task_id", "question", "language", "task_type",
                 "required_capabilities", "split")
GOLD_FIELDS = ("expected_entities", "desirable_entities", "expected_periods_declared",
               "lane_eval_sets",
               "expected_operations",
               "expected_seminars",
               "expected_periods", "answerability", "gold_evidence",
               "acceptable_evidence", "forbidden_shortcuts", "evaluation_notes",
               "review_status", "gold_derivation")


def squash(s):
    """宽容归一化 + **去空白**（见模块说明）。

    ⚠️ Phase 4C.1-A（§A4）：本函数**冻结**，因为 `research_tasks_v1.jsonl`
    由它推导，必须逐字节可复现。它删除标点后去空白，会把原本分开的 token
    粘成一个词（实测：`rt-J02` 的 `frmi` 来自 URL `univ-rennes1.fr/michel`）。
    修正后的、token 边界安全的归一化在 **`gold_normalization.py`**（`contains_v2`），
    只用于新的推导（gold lane audit / gold_v2），不再用于 v1。
    审计产物：`_data/eval/gold_lane_audit_v1.jsonl`。
    """
    s = unicodedata.normalize("NFKC", str(s))
    s = _APOS.sub("", s)
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    s = _NONWORD.sub("", s).lower()
    return re.sub(r"\s+", "", s)


# ─────────────────────────────────────────────────────────────────────────
# 任务 spec：27 个真实研究问题（10 类），19 dev + 8 holdout
# gold_lanes: 每 lane 一组 needle；lane 名会写进 gold_derivation 供复核
# ─────────────────────────────────────────────────────────────────────────

T = []


def task(tid, ttype, lang, q, *, ent=(), sem=(), per=(), ops=(), caps=(),
         ans="SUPPORTED", lanes=(), acceptable=(), forbid=(), notes="",
         split="dev", no_gold=None, desirable=()):
    T.append(dict(task_id=tid, task_type=ttype, language=lang, question=q,
                  expected_entities=list(ent), desirable_entities=list(desirable), expected_seminars=list(sem),
                  expected_periods=list(per), expected_operations=list(ops),
                  required_capabilities=list(caps), answerability=ans,
                  gold_lanes=[{"lane": n, "needles": w, "language": lg,
                               "seminar": sm}
                              for (n, w, lg, sm) in lanes],
                  acceptable_needles=list(acceptable),
                  forbidden_shortcuts=list(forbid), evaluation_notes=notes,
                  split=split, no_gold_reason=no_gold))


# ── A. Concept Definition（3）
task("rt-A01", "concept_definition", "zh",
     "拉康所谓的 objet petit a 到底是什么？请区分不同时期对它定位的差别。",
     ent=["concept.objet-petit-a"], per=["1956-1959", "1964-1966", "1972-1976"],
     ops=["resolve_entity", "find_concept_evidence", "trace_concept", "get_context",
          "trace_source"],
     caps=["multi_step", "period_coverage", "entity_resolution", "source_trace"],
     lanes=[("fr_core", ["objet petit a", "objet a"], "fr", None),
            ("zh_core", ["对象a", "对象 a", "客体小a"], "zh", None)],
     acceptable=["objet petit a", "objet a", "对象a", "客体小a", "小客体a", "objet (a)"],
     forbid=["把 objet a 与普通 objet 混为一谈",
             "只用一期（如 S10）的段落就给出「拉康的定义是」",
             "把中文 recovered 译文当作已闭合的 primary source"],
     notes="要求至少覆盖两个 period，并把 L1 法文原文与 L2 中译分层。",
     split="dev")

task("rt-A02", "concept_definition", "fr",
     "Qu'est-ce que la jouissance chez Lacan, et en quoi l'usage du terme change-t-il "
     "entre les années 1950 et les années 1970 ?",
     ent=["concept.jouissance"],
     per=["1953-1958", "1959-1966", "1972-1976"],
     ops=["resolve_entity", "find_concept_evidence", "trace_concept", "get_context"],
     caps=["multi_step", "period_coverage", "entity_resolution"],
     lanes=[("fr_core", ["jouissance"], "fr", None)],
     acceptable=["jouissance", "jouir", "快感", "享受"],
     forbid=["只引用一期", "把 jouissance 与 plaisir 当作同义词"],
     notes="holdout：法语概念定义 + 历时要求。", split="holdout")

task("rt-A03", "concept_definition", "fr",
     "Comment Lacan définit-il le désir dans les années 1957-1960, et de quoi le "
     "distingue-t-il ?",
     ent=["concept.desir"], per=["1956-1959"],
     sem=["seminar.S05", "seminar.S06"],
     ops=["resolve_entity", "find_concept_evidence", "get_concept", "get_context"],
     caps=["multi_step", "entity_resolution", "distinction_preservation"],
     lanes=[("fr_core", ["desir"], "fr", None),
            ("fr_s06", ["desir"], "fr", "seminar.S06")],
     acceptable=["desir", "desir du desir", "欲望"],
     forbid=["把 désir 与 besoin/demande 混同"],
     notes="与 A01 的差别：限定在 1957-1960 的欲望辩证法。", split="dev")

# ── B. Concept Relation（3）
task("rt-B01", "concept_relation", "zh",
     "desire、demand 和 need 三者是什么关系？请分别给出各自的证据。",
     ent=["concept.desir", "concept.demande", "concept.besoin"],
     ops=["resolve_entity", "compare_concepts", "find_concept_evidence", "get_context"],
     caps=["multi_step", "separate_lanes", "distinction_preservation"],
     lanes=[("lane_desir", ["desir"], "fr", None),
            ("lane_demande", ["demande"], "fr", None),
            ("lane_besoin", ["besoin"], "fr", None)],
     acceptable=["desir", "demande", "besoin", "要求", "需要", "欲望"],
     forbid=["把三个词拼成一个 query 做一次检索后直接总结",
             "把 besoin→demande→désir 说成同义改写"],
     notes="必须三条独立 lane（§16）。v4a1 已补齐 demande/besoin 实体。",
     split="dev")

task("rt-B02", "concept_relation", "fr",
     "Quel est le rapport entre signifiant et signifié chez Lacan, et pourquoi "
     "faut-il les distinguer ?",
     ent=["concept.signifiant", "concept.signifie"],
     ops=["resolve_entity", "compare_concepts", "find_concept_evidence"],
     caps=["multi_step", "separate_lanes", "distinction_preservation"],
     lanes=[("lane_signifiant", ["signifiant"], "fr", None),
            ("lane_signifie", ["signifie"], "fr", None)],
     acceptable=["signifiant", "signifie", "能指", "所指"],
     forbid=["把 signifié 与 signifiant 当同一个东西",
             "忽略 signifié 的 accent（法语动词 signifie ≠ 名词 signifié）"],
     notes="v4a1 的 exact-first 匹配正是为这一对做的。", split="dev")

task("rt-B03", "concept_relation", "zh",
     "Réel 与 réalité 为什么必须区分？它们在拉康那里各指什么？",
     ent=["concept.le-reel", "concept.realite"],
     ops=["resolve_entity", "compare_concepts", "find_concept_evidence"],
     caps=["multi_step", "separate_lanes", "distinction_preservation"],
     lanes=[("lane_reel", ["le reel", "reel"], "fr", None),
            ("lane_realite", ["realite"], "fr", None)],
     acceptable=["reel", "realite", "实在界", "现实"],
     forbid=["把 Real 说成「现实」", "把 réalité 当作 Real 的另一种拼写"],
     notes="v4a1 新建 concept.realite；旧层只有 le-reel。", split="holdout")

# ── C. Diachronic（3）
task("rt-C01", "diachronic_development", "zh",
     "Real 这个概念从早期拉康到晚期 Borromean teaching 发生了什么变化？",
     ent=["concept.le-reel", "concept.reel-symbolique-imaginaire-r-s-i"],
     per=["1953-1958", "1964-1966", "1972-1976"],
     sem=["seminar.S22", "seminar.S23"],
     ops=["resolve_entity", "trace_concept", "find_concept_evidence", "get_context"],
     caps=["multi_step", "period_coverage", "diachronic_grouping"],
     lanes=[("fr_early", ["le reel"], "fr", "seminar.S01"),
            ("fr_mid", ["le reel"], "fr", "seminar.S11"),
            ("fr_late", ["le reel"], "fr", "seminar.S22"),
            ("fr_borromean", ["borromeen", "borromee"], "fr", "seminar.S23")],
     acceptable=["le reel", "reel", "borromeen", "borromee", "r s i", "实在界"],
     forbid=["只找一课的段落就声称覆盖整个演变",
             "把 R.S.I. 的拓扑化当作早期定义"],
     notes="必须覆盖 ≥3 个 period；period_coverage 会被评估。", split="holdout")

task("rt-C02", "diachronic_development", "zh",
     "objet a 在拉康教学中的角色经历了哪些阶段？",
     ent=["concept.objet-petit-a"], per=["1956-1959", "1962-1967", "1972-1976"],
     sem=["seminar.S04", "seminar.S10", "seminar.S20"],
     ops=["resolve_entity", "trace_concept", "find_concept_evidence"],
     caps=["multi_step", "period_coverage", "diachronic_grouping"],
     lanes=[("fr_s04", ["objet petit a", "objet a"], "fr", "seminar.S04"),
            ("fr_s10", ["objet petit a", "objet a"], "fr", "seminar.S10"),
            ("fr_s20", ["objet petit a", "objet a"], "fr", "seminar.S20")],
     acceptable=["objet petit a", "objet a", "对象a", "客体小a"],
     forbid=["用同一期的多个段落冒充多个时期"],
     notes="三个期各取 lane，检查是否真的按 period 分组。", split="dev")

task("rt-C03", "diachronic_development", "fr",
     "Comment la notion de jouissance se transforme-t-elle entre L'éthique (S7) "
     "et Encore (S20) ?",
     ent=["concept.jouissance"], per=["1959-1960", "1972-1973"],
     sem=["seminar.S07", "seminar.S20"],
     ops=["resolve_entity", "trace_concept", "find_concept_evidence", "get_context"],
     caps=["multi_step", "period_coverage", "diachronic_grouping"],
     lanes=[("fr_s07", ["jouissance"], "fr", "seminar.S07"),
            ("fr_s20", ["jouissance"], "fr", "seminar.S20")],
     acceptable=["jouissance", "jouir", "快感"],
     forbid=["把 S7 与 S20 的用法直接当同一件事"],
     notes="两个期各一条 lane；比较两期的定位差异（不是判矛盾）。", split="dev")

# ── D. Seminar-specific（3）
task("rt-D01", "seminar_specific", "zh",
     "Seminar XI 中 gaze/regard 是如何与 objet a 发生关系的？",
     ent=["concept.gaze", "concept.objet-petit-a"], sem=["seminar.S11"],
     per=["1964-1964"],
     ops=["resolve_entity", "search_passages", "find_concept_evidence",
          "compare_concepts", "get_context", "terminology_lookup"],
     caps=["multi_step", "terminology_mapping", "seminar_constraint",
           "context_aware_resolution"],
     lanes=[("fr_s11_regard", ["regard"], "fr", "seminar.S11"),
            ("zh_s11_ning", ["凝视"], "zh", "seminar.S11"),
            ("fr_s11_objet", ["objet petit a", "objet a"], "fr", "seminar.S11")],
     acceptable=["regard凝视", "凝视", "regard", "objet a", "objet petit a"],
     forbid=["把 S11 内所有 regard 都说成 Lacanian gaze",
             "直接宣布 S11 是「论凝视的研讨班」而不给证据",
             "不使用 v4a1 的 controlled_term_mapping"],
     notes="§18 专项回归：context-scoped regard + 凝视 lane + objet a lane。",
     split="dev")

task("rt-D02", "seminar_specific", "fr",
     "Dans L'éthique de la psychanalyse (S7), quel rôle joue la jouissance dans "
     "l'expérience analytique ?",
     ent=["concept.jouissance"], sem=["seminar.S07"], per=["1959-1960"],
     ops=["resolve_entity", "search_passages", "find_concept_evidence", "get_context"],
     caps=["multi_step", "seminar_constraint"],
     lanes=[("fr_s07", ["jouissance"], "fr", "seminar.S07")],
     acceptable=["jouissance", "desir", "chose"],
     forbid=["把 S7 的 jouissance 与 S20 的 jouissance 直接合并"],
     notes="单一期约束下必须报约束是否真的被满足。", split="dev")

task("rt-D03", "seminar_specific", "fr",
     "Dans Encore (S20), comment Lacan articule-t-il jouissance féminine et pas-tout ?",
     ent=["concept.jouissance", "concept.jouissance-feminine", "concept.pas-tout"],
     sem=["seminar.S20"], per=["1972-1973"],
     ops=["resolve_entity", "search_passages", "find_concept_evidence", "get_context"],
     caps=["multi_step", "seminar_constraint", "multi_lane"],
     lanes=[("fr_s20_jf", ["jouissance feminine"], "fr", "seminar.S20"),
            ("fr_s20_pastout", ["pas-tout", "pas tout"], "fr", "seminar.S20")],
     acceptable=["jouissance feminine", "pas tout", "pas-tout", "femme"],
     forbid=["把 pas-tout 当作经验描述而不是逻辑量词"],
     notes="holdout：两个 lane（jouissance féminine + pas-tout）。", split="holdout")

# ── E. Case（2）
task("rt-E01", "case_research", "zh",
     "Schreber 在拉康的精神病理论中承担什么理论功能？",
     ent=["concept.le-president-schreber", "concept.psychose"],
     desirable=["concept.forclusion-verwerfung"],
     sem=["seminar.S03"], per=["1955-1956"],
     ops=["resolve_entity", "find_concept_evidence", "search_passages", "get_context",
          "trace_source"],
     caps=["multi_step", "case_evidence", "entity_resolution"],
     lanes=[("fr_schreber", ["schreber"], "fr", None),
            ("fr_s03_verwerfung", ["verwerfung", "forclusion"], "fr", "seminar.S03")],
     acceptable=["schreber", "forclusion", "verwerfung", "psychose", "施雷伯"],
     forbid=["把 Schreber 的回忆录当临床事实而不区分文本层次"],
     notes="实测：schreber 310 段（S03 内 267）；S03 内 verwerfung 44 段 / forclusion 仅 2 段"
           "（S03 主要用 Verwerfung，forclusion 全库 43 段）—— 术语选择本身是证据问题。",
     split="dev")

task("rt-E02", "case_research", "zh",
     "Dora 这个个案在拉康的转移与对象关系中起什么作用？",
     ent=["concept.le-cas-dora", "concept.transfert"],
     sem=["seminar.S04", "seminar.S08"], per=["1956-1957", "1960-1961"],
     ops=["resolve_entity", "find_concept_evidence", "trace_concept", "get_context"],
     caps=["multi_step", "case_evidence", "period_coverage"],
     lanes=[("fr_dora_s04", ["dora"], "fr", "seminar.S04"),
            ("fr_dora_s08", ["dora"], "fr", "seminar.S08")],
     acceptable=["dora", "transfert", "objet"],
     forbid=["只取一期", "把 Dora 个案当作诊断结论"],
     notes="holdout：两个期 + 个案。", split="holdout")

# ── F. Freud → Lacan（2）
task("rt-F01", "freud_to_lacan", "fr",
     "Comment Lacan réinterprète-t-il la pulsion (Trieb) freudienne ?",
     ent=["concept.pulsion"],
     sem=["seminar.S07", "seminar.S11"], per=["1959-1960", "1964-1964"],
     ops=["resolve_entity", "find_concept_evidence", "search_passages", "get_context"],
     caps=["multi_step", "source_layer_separation", "entity_resolution"],
     lanes=[("fr_pulsion", ["pulsion"], "fr", None),
            ("fr_trieb", ["trieb"], "fr", None),
            ("zh_pulsion", ["冲动", "驱力"], "zh", None)],
     acceptable=["pulsion", "trieb", "冲动", "驱力", "freud"],
     forbid=["把 Freud 的原话与 Lacan 的重读混为一层",
             "在没有法文原文时声称「拉康原文说」"],
     notes="必须分层：Freud 概念（二手陈述） vs Lacan 文本证据 vs 综合。",
     split="dev")

task("rt-F02", "freud_to_lacan", "zh",
     "Lacan 如何重新处理 Freud 的 Verneinung（否定/否认）？",
     ent=["concept.verneinung"],
     sem=["seminar.S01", "seminar.S03"], per=["1953-1954", "1955-1956"],
     ops=["resolve_entity", "find_concept_evidence", "search_passages", "get_context"],
     caps=["multi_step", "source_layer_separation"],
     lanes=[("fr_verneinung", ["verneinung"], "fr", None),
            ("fr_denegation", ["denegation"], "fr", None)],
     acceptable=["verneinung", "denegation", "negation", "否定"],
     forbid=["把 Verneinung 与 dénégation 当作同一个词"],
     notes="holdout：两个法文形式要分开取证据。", split="holdout")

# ── G. Philosophy → Lacan（2）
task("rt-G01", "philosophy_to_lacan", "zh",
     "黑格尔的主人—奴隶辩证法如何进入拉康的欲望理论？",
     ent=["concept.desir"],
     sem=["seminar.S02", "seminar.S17"], per=["1954-1955", "1969-1970"],
     ops=["resolve_entity", "search_passages", "find_concept_evidence", "get_context"],
     caps=["multi_step", "source_layer_separation", "period_coverage"],
     lanes=[("fr_hegel", ["hegel"], "fr", None),
            ("fr_maitre_esclave", ["maitre", "esclave"], "fr", "seminar.S17")],
     acceptable=["hegel", "maitre", "esclave", "dialectique", "黑格尔", "主人", "奴隶"],
     forbid=["把黑格尔的原话当作拉康的论断",
             "在语料不足时给出「拉康认为」的定论"],
     notes="holdout：哲学来源与拉康文本必须分层；不足时允许 PARTIALLY_SUPPORTED。",
     split="holdout")

task("rt-G02", "philosophy_to_lacan", "zh",
     "Descartes 的 cogito 在拉康的主体理论里被如何处理？",
     ent=["concept.sujet", "concept.moi"],
     sem=["seminar.S14", "seminar.S15"], per=["1966-1967", "1967-1968"],
     ops=["resolve_entity", "find_concept_evidence", "search_passages", "get_context"],
     caps=["multi_step", "source_layer_separation", "distinction_preservation"],
     lanes=[("fr_cogito", ["cogito"], "fr", None),
            ("fr_descartes", ["descartes"], "fr", None)],
     acceptable=["cogito", "descartes", "sujet", "笛卡尔", "主体"],
     forbid=["把 cogito 与 sujet 当作同一个东西（sujet 是分裂的）"],
     notes="要求区分 sujet 与 moi（v4a1 新建 concept.moi）。", split="dev")

# ── H. Topology / Matheme（2）
task("rt-H01", "topology_matheme", "zh",
     "波罗米结（nœud borroméen）在拉康晚期如何用来表达 R.S.I. 的结构？",
     ent=["concept.reel-symbolique-imaginaire-r-s-i", "concept.sinthome"],
     sem=["seminar.S22", "seminar.S23"], per=["1974-1975", "1975-1976"],
     ops=["resolve_entity", "find_concept_evidence", "search_passages", "get_context"],
     caps=["multi_step", "topology_evidence", "period_coverage"],
     lanes=[("fr_borromee", ["borromeen", "borromee"], "fr", None),
            ("zh_borromee", ["波罗米", "博罗米"], "zh", None)],
     acceptable=["borromeen", "borromee", "noeud", "波罗米", "三环", "rs i"],
     forbid=["把拓扑结的数学性质与临床论断混为一谈",
             "声称某处「图示」而给不出段号"],
     notes="语料里 borromee 499 段、中文 510 段 —— 覆盖良好。", split="dev")

task("rt-H02", "topology_matheme", "fr",
     "Que exprime la formule $ ◊ a dans la structure du fantasme ?",
     ent=["concept.fantasme", "concept.objet-petit-a"],
     sem=["seminar.S14"], per=["1966-1967"],
     ops=["resolve_entity", "find_concept_evidence", "search_passages", "get_context"],
     caps=["multi_step", "matheme_evidence", "seminar_constraint"],
     lanes=[("fr_fantasme_s14", ["fantasme"], "fr", "seminar.S14"),
            ("fr_objet_s14", ["objet petit a", "objet a"], "fr", "seminar.S14")],
     acceptable=["fantasme", "objet a", "losange", "matheme"],
     forbid=["把 $ ◊ a 翻译成自然语言后当作拉康原话引用"],
     notes="公式的书写形式在转写文本里可能不统一；必须如实报不确定。",
     split="dev")

# ── I. Translation / Terminology（3）
task("rt-I01", "translation_terminology", "zh",
     "为什么 jouissance 不能简单翻译成 pleasure？",
     ent=["concept.jouissance"],
     ops=["resolve_entity", "terminology_lookup", "find_concept_evidence",
          "get_context"],
     caps=["multi_step", "terminology_mapping", "source_layer_separation"],
     lanes=[("fr_jouissance", ["jouissance"], "fr", None),
            ("zh_term", ["快感", "享受", "原乐"], "zh", None)],
     acceptable=["jouissance", "plaisir", "快感", "享受", "原乐"],
     forbid=["把 jouissance 与 plaisir 当作同义词",
             "用英译 pleasure 反推法文原义"],
     notes="中文译名在语料里不统一（快感/享受/原乐），必须如实报。", split="dev")

task("rt-I02", "translation_terminology", "zh",
     "Réel 与 réalité 为什么必须在术语层区分开？",
     ent=["concept.le-reel", "concept.realite"],
     ops=["resolve_entity", "terminology_lookup", "compare_concepts"],
     caps=["multi_step", "terminology_mapping", "separate_lanes"],
     lanes=[("fr_reel", ["le reel"], "fr", None),
            ("fr_realite", ["realite"], "fr", None),
            ("zh_pair", ["实在界", "现实"], "zh", None)],
     acceptable=["reel", "realite", "实在界", "现实"],
     forbid=["把实在界与现实当作可互换的译名"],
     notes="与 B03 的差别：这里要求给出译名学论证（术语层而非概念层为主）。",
     split="dev")

task("rt-I03", "translation_terminology", "zh",
     "中文语料里 jouissance 有「快感」「享受」「原乐」等译法，这些译名差异意味着什么？",
     ent=["concept.jouissance"],
     ops=["resolve_entity", "search_passages", "terminology_lookup", "get_context"],
     caps=["multi_step", "terminology_mapping", "cross_language"],
     lanes=[("zh_kuai", ["快感"], "zh", None),
            ("zh_xiang", ["享受"], "zh", None),
            ("zh_yuan", ["原乐"], "zh", None)],
     acceptable=["快感", "享受", "原乐", "jouissance"],
     forbid=["把三种译名说成「同一个词的三种写法」而不给段号",
             "编造某一译名的首次出现时间"],
     notes="holdout。实测：`快感` 85 段、`享受` 52 段、**`原乐` 0 段** —— "
           "「原乐」这个常被提到的译名在本语料里**完全没有出现**；"
           "Agent 必须如实报告「无语料支持」，不得凭通识把它说成已确立译名。",
     split="holdout")

# ── J. Insufficient / Unanswerable（4）
task("rt-J01", "insufficient_unanswerable", "zh",
     "莫比乌斯带（Möbius strip）为什么适合表示拉康的主体？请给出原文依据。",
     ent=[], ops=["resolve_entity", "search_passages"],
     caps=["abstention"],
     ans="INSUFFICIENT_EVIDENCE",
     lanes=[], acceptable=[],
     forbid=["用模型通识代替语料证据", "把 borroméen 的材料当作 Möbius 的证据"],
     notes="实测：`moebius` 全库仅 1 段（S06），`bande de moebius` 0 段 —— 语料里"
           "几乎没有 Möbius 带的法文材料（拓扑词主要是 borroméen 499 段）。",
     split="holdout")

task("rt-J02", "insufficient_unanswerable", "zh",
     "拉康如何看待 fMRI 等当代神经科学影像研究？",
     ent=[], ops=["resolve_entity", "search_passages"],
     caps=["abstention"],
     ans="INSUFFICIENT_EVIDENCE",
     lanes=[("zh_frmi", ["frmi"], "zh", None)],
     acceptable=["cerveau", "imagerie cerebrale"],
     forbid=["用 1950-1980 语料之外的常识回答", "把「脑」的一般提及当作对该问题的回答"],
     notes="实测：`frmi` 3 段（全部 zh/S13，属旁及提及）；`neuroscience(s)` **0 段**；"
           "`cerveau` 18 段 / `imagerie cérébrale` 20 段只是普通「脑/影像」义，"
           "**不构成**对 fMRI 研究的回应。语料时间跨度 1953-1980。", split="dev")

task("rt-J03", "insufficient_unanswerable", "zh",
     "拉康 1953 年 11 月 18 日那场报告的确切时间、地点与在场者是谁？",
     ent=[], ops=["search_passages", "get_passage", "trace_source"],
     caps=["abstention"],
     ans="INSUFFICIENT_EVIDENCE",
     lanes=[], acceptable=[],
     forbid=["编造日期/地点/人名", "把年份区间当作确切日期"],
     notes="实测：canonical store 里所有 passage 的 session_date 均为 unknown，"
           "语料只提供 year_from/year_to —— 本库结构上无法回答确切日期。",
     split="dev")

task("rt-J04", "insufficient_unanswerable", "zh",
     "拉康与维特根斯坦之间是否有直接的文本往来或通信？",
     ent=[], ops=["resolve_entity", "search_passages", "get_context"],
     caps=["abstention"],
     ans="PARTIALLY_SUPPORTED",
     lanes=[("fr_witt", ["wittgenstein"], "fr", None)],
     acceptable=["wittgenstein", "维特根斯坦"],
     forbid=["把旁及提及当作「直接往来」的证据", "编造通信记录"],
     notes="实测：`wittgenstein` 19 段 / 7 期，全部是旁及提及；"
           "没有任何「通信/书信」层证据 → 只能说部分支持（提及存在，往来无据）。",
     split="dev")


# ─────────────────────────────────────────────────────────────────────────

def load_passages():
    rows = []
    p = os.path.join(STORE, "passages.jsonl")
    with open(p, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            rows.append((d["id"], d.get("seminar_id"), d.get("language"),
                         squash(d.get("raw_text") or "")))
    return rows


def derive(rows, needles, language=None, seminar=None,
           per_seminar=PER_SEMINAR_CAP, cap=PER_LANE_CAP):
    ns = [squash(n) for n in needles if squash(n)]
    hits = []
    for pid, sem, lang, text in rows:
        if language and lang != language:
            continue
        if seminar and sem != seminar:
            continue
        if any(n in text for n in ns):
            hits.append((pid, sem, lang))
    by_sem = defaultdict(list)
    for h in hits:
        by_sem[h[1] or "unknown"].append(h)
    picked = []
    for sem in sorted(by_sem):
        picked.extend(by_sem[sem][:per_seminar])
    return picked[:cap], len(hits), len(by_sem)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    rows = load_passages()
    known = {r[0] for r in rows}
    # 知识库真实期段（seminar → year_from-year_to）—— 期望期段必须用它，
    # 否则 gold 里的 "1956-1959" 这类**手写桶**与语料实际产出的 "1956-1957"
    # 对不上，period_coverage 会被系统性压低（第一版就是这样）。
    sem_period = {}
    with open(os.path.join(STORE, "seminars.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                sem_period[d["id"]] = "%s-%s" % (d.get("year_from"), d.get("year_to"))
    out, derivation = [], []
    for t in T:
        gold, accept = [], []
        lane_info = []
        lane_eval = {}
        for lane in t["gold_lanes"]:
            got, n_hits, n_sem = derive(rows, lane["needles"], lane["language"],
                                        lane["seminar"])
            # 评测集：**尽量全量**（单期 lane 常常几百条），只在 >400 时才分层抽样。
            # 第一版无脑每期取 10 条，等于把参考集变成「store 顺序最早的那 10 条」，
            # 召回率被系统性压到接近 0（那测的是抽样规则，不是检索质量）。
            full, _n, _s = derive(rows, lane["needles"], lane["language"],
                                  lane["seminar"], per_seminar=40, cap=400)
            lane_eval[lane["lane"]] = [g[0] for g in full]
            lane_info.append({"lane": lane["lane"], "needles": lane["needles"],
                              "language": lane["language"], "seminar": lane["seminar"],
                              "passages": [g[0] for g in got],
                              "hits_total": n_hits, "seminars_hit": n_sem})
            for pid, _s, _l in got:
                if pid not in gold:
                    gold.append(pid)
        if t["acceptable_needles"]:
            got, n_hits, n_sem = derive(rows, t["acceptable_needles"],
                                        cap=ACCEPTABLE_CAP, per_seminar=3)
            accept = [g[0] for g in got]
        for pid in gold + accept:
            assert pid in known, "gold 段号不存在：%s" % pid
        row = {k: t[k] for k in ("task_id", "question", "language", "task_type",
                                 "desirable_entities",
                                 "expected_entities", "expected_operations",
                                 "expected_seminars", "expected_periods",
                                 "required_capabilities", "answerability",
                                 "forbidden_shortcuts", "evaluation_notes", "split")}
        # 期望期段：若 lane 限定了 seminar，就用这些 seminar 的**真实**期段
        lane_sems = [l["seminar"] for l in t["gold_lanes"] if l.get("seminar")]
        if lane_sems:
            row["expected_periods_declared"] = t["expected_periods"]
            row["expected_periods"] = sorted({sem_period[s] for s in lane_sems
                                              if s in sem_period})
        row["gold_evidence"] = gold
        row["lane_eval_sets"] = lane_eval
        row["acceptable_evidence"] = accept
        row["review_status"] = "script_assisted_unreviewed"
        row["schema_version"] = "research-task/v1"
        row["gold_derivation"] = {
            "method": ("canonical store 归一化（含去空白）子串匹配 + 按研讨班分层抽样"
                       "（每期≤3、每 lane≤%d）+ 段号存在性核对" % PER_LANE_CAP),
            "lanes": lane_info,
            "no_gold_reason": t.get("no_gold_reason"),
        }
        if t["answerability"] == "INSUFFICIENT_EVIDENCE" and not gold:
            row["gold_derivation"]["no_gold_reason"] = (
                "语料层不支撑该问题；见 evaluation_notes 的实测 needle 计数")
        out.append(row)
        derivation.append({"task_id": t["task_id"], "answerability": t["answerability"],
                           "gold_n": len(gold), "acceptable_n": len(accept),
                           "lanes": lane_info})
    pub = [{k: r[k] for k in PUBLIC_FIELDS} for r in out]
    if a.check:
        have = [json.loads(l) for l in open(TASKS, encoding="utf-8") if l.strip()] \
            if os.path.isfile(TASKS) else []
        if json.dumps(have, ensure_ascii=False, sort_keys=True) != \
           json.dumps(out, ensure_ascii=False, sort_keys=True):
            print("research_tasks_v1.jsonl 与 spec 不一致（重跑本脚本）")
            return 1
        print("research tasks 与 spec 一致：%d 个任务（dev %d / holdout %d）"
              % (len(out), sum(1 for r in out if r["split"] == "dev"),
                 sum(1 for r in out if r["split"] == "holdout")))
        return 0
    os.makedirs(EVAL, exist_ok=True)
    for path, data in ((TASKS, out), (PUBLIC, pub)):
        with open(path, "w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    with open(DERIV, "w", encoding="utf-8") as f:
        json.dump({"schema_version": "research-task-derivation/v1",
                   "tasks": derivation}, f, ensure_ascii=False, indent=1)
        f.write("\n")
    tcount = Counter(r["task_type"] for r in out)
    print("wrote %s（%d 个任务：dev %d / holdout %d）"
          % (os.path.relpath(TASKS, VAULT), len(out),
             sum(1 for r in out if r["split"] == "dev"),
             sum(1 for r in out if r["split"] == "holdout")))
    print("  任务类型：%s" % dict(tcount))
    print("  answerability：%s" % dict(Counter(r["answerability"] for r in out)))
    print("  无 gold 的任务：%s" % [r["task_id"] for r in out if not r["gold_evidence"]])
    print("  gold 段号总数：%d（全部通过存在性核对）"
          % sum(len(r["gold_evidence"]) for r in out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
