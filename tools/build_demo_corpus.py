#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the **public-domain demo corpus** end to end (passage store → index → ontology → freeze).

两阶段历史（见 docs/DEMO_CORPUS.md）：
  * 阶段 1：段落库 + 词法索引。答案只能弃权（ONTOLOGY_GAP）—— 正确但不好用。
  * 阶段 2（本脚本现在的行为）：补一份**demo 本体层**（`demo-corpus/ontology/spec.json`
    → `_data/ontology/v4a1/`，证据由 build_ontology_v4a1.py 在 demo 段落上现算），
    再按 `unreviewed-corpus` 语料档案冻结（人工验收工件按**声明缺席**处理），
    于是一个没有真实语料的人也能跑通一次完整研究（检索 → 证据 → 断言 → 引文 → 检查器）。

⚠️ 两条边界（脚本会把它们写进产物，不靠文档口头承诺）：
  1. demo 语料**没有人工验收证据** → 状态是 CORPUS_HUMAN_REVIEW_NOT_AVAILABLE，
     不是 SCHOLARLY_CORE_READY；答案不携带人工验收背书。
  2. 冻结内核的来源归属措辞（claim 文字里的说话人）是为参考语料写的，**对本语料不适用**；
     demo 承诺的是检索 / 证据 / 引文 / 检查器 / 本体解析这条链。

Sources (all public domain, fetched from fr.wikisource with their real imprint data):
  * Jules Falret, Études cliniques sur les maladies mentales et nerveuses, Baillière, 1890
  * Alfred Binet, Les Altérations de la personnalité, Félix Alcan, 1892
  * Pierre Janet, Les Névroses, Flammarion, 1909
"""
import argparse
import hashlib, io, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
_ap = argparse.ArgumentParser(description="build the public-domain demo corpus "
                                             "(store → index → ontology → freeze)")
_ap.add_argument("vault", nargs="?", default=REPO,
                 help="目标 vault（缺省 = 本仓库根目录）")
_ap.add_argument("--skip-index", action="store_true", help="只建段落库与本体层")
_ap.add_argument("--skip-freeze", action="store_true", help="不重写 core freeze / 谱系")
_args = _ap.parse_args()
VAULT = os.path.abspath(_args.vault)
SKIP_INDEX = _args.skip_index
SKIP_FREEZE = _args.skip_freeze
SRC = os.path.join(REPO, 'demo-corpus', 'sources')
OUT = os.path.join(VAULT, '_data', 'passage_store')
os.makedirs(OUT, exist_ok=True)
GEN = 'script:demo_corpus.py'
SCHEMA = '1.0.0'

SOURCES = [
    dict(key='falret', seminar='S01', roman='I', file='falret.txt',
         author='Jules Falret', title='Études cliniques sur les maladies mentales et nerveuses',
         zh='精神疾病与神经疾病临床研究', publisher='J. B. Baillière et fils', year=1890,
         url='https://fr.wikisource.org/wiki/Études_cliniques_sur_les_maladies_mentales_et_nerveuses',
         source_id='corpus-source.wikisource-falret', witness='witness.fr.wikisource-falret',
         note='公有领域（作者卒于 1902）。法国临床精神病学经典；拉康受训的临床传统直接上承此脉。'),
    dict(key='binet', seminar='S02', roman='II', file='binet.txt',
         author='Alfred Binet', title='Les Altérations de la personnalité',
         zh='人格的变异', publisher='Félix Alcan', year=1892,
         url='https://fr.wikisource.org/wiki/Les_Altérations_de_la_personnalité_(Binet)',
         source_id='corpus-source.wikisource-binet', witness='witness.fr.wikisource-binet',
         note='公有领域（作者卒于 1911）。癔症与"亚意识行为"的实验心理学；拉康之前的法国心理学脉络。'),
    dict(key='janet', seminar='S03', roman='III', file='janet.txt',
         author='Pierre Janet', title='Les Névroses',
         zh='神经症', publisher='Ernest Flammarion', year=1909,
         url='https://fr.wikisource.org/wiki/Les_Névroses_(Janet)',
         source_id='corpus-source.wikisource-janet', witness='witness.fr.wikisource-janet',
         note='公有领域（作者卒于 1947，法国版权期已届满）。让内的神经症理论：心理衰弱、解离、潜意识固着。'),
]

def norm_text(s):
    s = s.replace('\u00a0', ' ').replace('\u2019', "'")
    s = re.sub(r'[ \t]+', ' ', s)
    return re.sub(r'\n{3,}', '\n\n', s).strip()

def segments(text, target=1100):
    """按段落聚合成 ~1100 字的段落单元（passage）。"""
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if len(p.strip()) > 120]
    out, cur = [], ''
    for p in paras:
        if len(cur) + len(p) + 2 > target and len(cur) > 400:
            out.append(cur.strip()); cur = p
        else:
            cur = (cur + '\n\n' + p).strip()
    if len(cur) > 200:
        out.append(cur.strip())
    return out

passages, realizations, wit_links, sessions, seminars, csources, witnesses = ([] for _ in range(7))
tally = {}
for src in SOURCES:
    path = os.path.join(SRC, src['file'])
    if not os.path.isfile(path):
        print('missing source:', path); continue
    raw = io.open(path, encoding='utf-8').read()
    sha = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    body = norm_text(raw)
    segs = segments(body)
    # 每 ~25 段算一"课"（demo 语料没有课次结构，这是**装订**分组，不是原书章节）
    per_lesson = 25
    n_lessons = max(1, (len(segs) + per_lesson - 1) // per_lesson)
    chars = 0
    lesson_numbers = []
    for li in range(n_lessons):
        lesson_numbers.append(li + 1)
        group = segs[li * per_lesson:(li + 1) * per_lesson]
        sid = 'session.%s.unknown.L%02d' % (src['seminar'], li + 1)
        sessions.append(dict(
            id=sid, type='session', seminar_id='seminar.' + src['seminar'], seminar=src['seminar'],
            lesson=li + 1, languages=['fr'], passage_count=len(group),
            session_date='%d' % src['year'], session_date_precision='year',
            trace_status='COMPLETE', trace_missing=[], year_from=src['year'], year_to=src['year'],
            authority_level='L1', review_status='needs_review', schema_version=SCHEMA,
            generated_by=GEN))
        for pi, seg in enumerate(group, start=1):
            pid = 'passage.%s.unknown.L%02d.P%04d' % (src['seminar'], li + 1, pi)
            chars += len(seg)
            rec = dict(
                id=pid, type='passage', language='fr',
                seminar_id='seminar.' + src['seminar'], session_id=sid,
                lesson=li + 1, sequence_in_session=pi,
                raw_text=seg, normalized_text=seg, canonical=False,
                normalization_operations=[],
                provenance=dict(document_id=src['source_id'], physical_file=src['file'],
                                physical_sha256=sha, physical_source_file=src['file'],
                                physical_source_sha256=sha,
                                physical_source_url=src['url'],
                                edition='%s, %s, %d' % (src['title'], src['publisher'], src['year']),
                                page_locator=None),
                authority_level='L1', review_status='candidate', status='recovered',
                text_role='transcription', trace_status='COMPLETE', trace_missing=[],
                witness_id=src['witness'], source_file_relpath='01_Sources/' + src['file'],
                source_state='upstream_present', translation_id=None,
                session_date='%d' % src['year'], session_date_precision='year',
                year_from=src['year'], year_to=src['year'], schema_version=SCHEMA,
                generated_by=GEN)
            passages.append(rec)
            realizations.append(dict(
                authority_level='L1', corpus_source_id=src['source_id'], generated_by=GEN,
                language='fr', method='native (该段即出自此 witness)', passage_id=pid,
                review_status='candidate', schema_version=SCHEMA, text_role='transcription',
                witness_id=src['witness']))
            wit_links.append(dict(generated_by=GEN, passage_id=pid, schema_version=SCHEMA,
                                  witness_id=src['witness']))
    seminars.append(dict(
        id='seminar.' + src['seminar'], type='seminar',
        slug='%s-%s' % (src['key'], re.sub(r'[^a-z0-9]+', '-', src['title'].lower()).strip('-'))[:60],
        roman=src['roman'], raw_key=src['seminar'].lower(),
        fr_title=src['title'], zh_title=src['zh'],
        lessons=n_lessons, lesson_numbers=lesson_numbers, segments=len(segs), chars=chars,
        year_from=src['year'], year_to=src['year'], status='active',
        review_status='needs_review', authority_level='L1', schema_version=SCHEMA,
        generated_by=GEN))
    csources.append(dict(
        id=src['source_id'], type='corpus_source', kind='print_edition', language='fr',
        name='%s, %s (%s, %d) — Wikisource' % (src['author'], src['title'], src['publisher'], src['year']),
        note=src['note'], url=src['url'], witness_ids=[src['witness']],
        status='recovered', authority_level='L1', canonical=False,
        review_status='needs_review', schema_version=SCHEMA, generated_by=GEN))
    witnesses.append(dict(
        id=src['witness'], type=None, language='fr', corpus_source_id=src['source_id'],
        edition='%s, %s, %d（Wikisource 转录，公有领域）' % (src['title'], src['publisher'], src['year']),
        witness_kind='edition_extract', text_role='transcription', translator=None,
        provenance_note='公有领域文本，取自 fr.wikisource；出版信息（出版社/年份）来自书名页，可回查',
        source_file=src['file'], source_file_sha256=sha, source_state='upstream_present',
        authority_level='L1', canonical=False, status='recovered', schema_version=SCHEMA,
        generated_by=GEN))
    tally[src['key']] = len(segs)

def dump(name, rows):
    with io.open(os.path.join(OUT, name), 'w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
    print('  %-30s %d' % (name, len(rows)))

print('demo store →', OUT)
dump('passages.jsonl', passages)
dump('passage_realizations.jsonl', realizations)
dump('passage_witnesses.jsonl', wit_links)
dump('witnesses.jsonl', witnesses)
dump('sessions.jsonl', sessions)
dump('seminars.jsonl', seminars)
dump('corpus_sources.jsonl', csources)
dump('translations.jsonl', [])
dump('concepts.jsonl', [])
dump('concept_states.jsonl', [])
counts = dict(by_language={'fr': len(passages)}, corpus_sources=len(csources),
              passage_realizations=len(realizations), passage_witness_links=len(wit_links),
              passages=len(passages), seminars=len(seminars), sessions=len(sessions),
              translations=0, witnesses=len(witnesses))
meta = dict(schema='passage-store/v1', generated_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            stamp_mode='demo-public-domain', counts=counts,
            source_root='demo (public domain, fr.wikisource)', source_files=sorted(tally),
            id_scheme=dict(deterministic=True, not_canonical=True),
            not_canonical=True,
            content_hash=hashlib.sha256(json.dumps(counts, sort_keys=True).encode()).hexdigest())
json.dump(meta, io.open(os.path.join(OUT, '_build_meta.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, sort_keys=True)
print('  _build_meta.json  content_hash=%s' % meta['content_hash'][:16])
print('per-source segments:', tally)
print()

# ══════════════════════════════════════════════════════════════════════ 阶段 2 流水线
# 一步一步来，任何一步失败就**停下并报错**（不静默跳过，否则会产出一个半成品语料）。
def sh(cmd, desc, cwd=None):
    print("  → %s" % desc)
    import subprocess
    r = subprocess.run([sys.executable] + cmd, cwd=cwd or VAULT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
        raise SystemExit("FAILED（exit %d）：%s" % (r.returncode, " ".join(cmd)))
    return (r.stdout or "").strip()


def write_index_manifest():
    """重写 `_data/index/INDEX_MANIFEST.json` —— 必须**属于这份语料**。

    为什么必须重写（实测缺陷）：公开版随引擎分发的 INDEX_MANIFEST 是**参考语料**的
    （`passage_count: 249105`、参考 corpus_hash）。demo 构建若不重写它，产物就会
    宣称一份并不存在的语料 —— 既是文档虚构，也让冻结组件 `retrieval_index_lexical`
    看起来「没变」（谱系判定 DATA_VERSION_INCONSISTENT）。
    """
    import hashlib
    pp = os.path.join(OUT, "passages.jsonl")
    h = hashlib.sha256()
    with open(pp, "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            h.update(b)
    corpus_hash = h.hexdigest()
    meta = json.load(io.open(os.path.join(OUT, "_build_meta.json"), encoding="utf-8"))
    doc = {
        "schema_version": "index-manifest/v1",
        "corpus": {
            "passages_jsonl": "_data/passage_store/passages.jsonl",
            "corpus_hash": corpus_hash,
            "passage_count": meta["counts"]["passages"],
            "source_sha256": {k: hashlib.sha256(
                io.open(os.path.join(SRC, "%s.txt" % k), "rb").read()).hexdigest()
                for k in sorted(tally)},
        },
        "indices": [
            {"name": "lexical", "version": "1",
             "artifacts": ["_data/index/lexical.sqlite"],
             "passage_count": meta["counts"]["passages"], "model": None,
             "dimensions": None,
             "tokenizer": {"french": "C_normalized_with_elision_variants",
                           "chinese": "B_bigram",
                           "normalization": "fr: NFKC+去撇号+连字符→空格+去变音; zh: bigram+短语匹配"},
             "build_config_hash": "1e1bf6914bd73c04",
             "rebuild": "python3 _scripts/_tools/build_lexical_index.py"},
            {"name": "alias", "version": "1",
             "artifacts": ["_data/index/alias_index.jsonl"], "passage_count": 0,
             "model": None, "dimensions": None,
             "build_config_hash": "d44ce3af927774d9",
             "rebuild": "python3 _scripts/_tools/build_alias_index.py"},
        ],
        "embedding": None,
        "embedding_note": ("demo 语料**不附带**向量索引：向量运行时不可用，检索走词法路径。"
                           "字段保留以便在可用环境里回填 model/dimensions。"),
        "git_policy": "大型可重建索引不入 git；本 manifest + canonical corpus 可完整重建全部索引",
        "stamp_mode": "deterministic",
        "generated_by": "script:build_demo_corpus.py",
    }
    doc["content_hash"] = hashlib.sha256(json.dumps(
        doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    p = os.path.join(VAULT, "_data", "index", "INDEX_MANIFEST.json")
    with io.open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    print("  INDEX_MANIFEST.json  passage_count=%d corpus_hash=%s"
          % (meta["counts"]["passages"], corpus_hash[:12]))


def write_concept_meta():
    """写一份**属于 demo 的** `_concept_meta.json`。

    为什么必须写：公开版随引擎分发的是**参考语料**的 `_concept_meta.json`
    （`gold_set.expected_total: 53`）。demo 语料没有 Gold Concept Set（实体全部来自本体
    叠加层），若不重写，产物就会宣称一个并不存在的 53 条概念集 —— 文档虚构。
    当前引擎只在 `seed_concepts_and_claims.py` 里写它、运行时不读；这里如实写 demo 的值。
    """
    import hashlib
    doc = {
        "schema_version": "concept-meta/v1",
        "generated_by": "script:build_demo_corpus.py",
        "gold_set": {
            "expected_total": 0, "actual_total": 0,
            "note": ("demo 语料**没有** Gold Concept Set —— 参考语料的 53 条卡片是它自己的"
                     "学科成果，不随引擎分发。demo 的实体全部来自本体叠加层 "
                     "_data/ontology/v4a1/（由 demo-corpus/ontology/spec.json 生成）。"),
        },
        "counts": {"concepts": 0, "concept_states": 0, "alignments": 0, "claims": 0},
        "note": "本文件只描述 demo 语料的概念层状态，不参与评分。",
    }
    doc["content_hash"] = hashlib.sha256(json.dumps(
        doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    p = os.path.join(OUT, "_concept_meta.json")
    with io.open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("  _concept_meta.json  gold_set=0（demo 无 Gold Concept Set）")


def write_terminology_bridge():
    """从 demo 本体层的受控术语映射生成 `_data/terminology_bridge.jsonl`。

    为什么由本脚本生成：引擎的 `build_terminology_bridge.py` 只从 **Gold Concept Set**
    取跨语言写法，而 demo 语料没有 gold 概念集（那是参考语料自己的学科成果）→ 会得到空表。
    demo 的单一真源是 `_data/ontology/v4a1/term_mappings.jsonl`（6 条 fr↔en↔zh 映射，
    全部指向同一 entity），因此这里按引擎自己写明的规则生成 **equivalent** 记录：
    只有「同一 entity_id 的跨语言形式」才生成 equivalent —— 本函数不生成别的类型。
    """
    import hashlib
    mp = os.path.join(VAULT, "_data", "ontology", "v4a1", "term_mappings.jsonl")
    rows = []
    n = 0
    for line in io.open(mp, encoding="utf-8"):
        if not line.strip():
            continue
        m = json.loads(line)
        n += 1
        rows.append({
            "schema_version": "terminology-bridge/v1",
            "term_id": "tb.demo.%s.%s.%s.%03d" % (m["entity_id"].split(".", 1)[1],
                                                  m["source_language"],
                                                  m["target_language"], n),
            "source_form": m["source_form"],
            "source_language": m["source_language"],
            "target_form": m["target_form"],
            "target_language": m["target_language"],
            "entity_id": m["entity_id"],
            "relation_type": "equivalent",
            "status": "active",
            "review_status": "candidate",
            "source": "ontology.v4a1:%s" % m["mapping_id"],
            "notes": ("由 demo 本体层的受控术语映射推出：两侧指向**同一个** entity "
                      "（%s），因此属于允许用于查询扩展的 equivalent 记录。"
                      % m["entity_id"]),
        })
    p = os.path.join(VAULT, "_data", "terminology_bridge.jsonl")
    with io.open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print("  terminology_bridge.jsonl  %d 条（全部 equivalent，来自本体层映射）" % len(rows))


def write_vector_manifest():
    """demo 不附带生产向量索引 —— 写一份**诚实**的说明性 manifest（检索走词法路径）。"""
    meta = json.load(io.open(os.path.join(OUT, "_build_meta.json"), encoding="utf-8"))
    p = os.path.join(VAULT, "_data", "index", "vector", "VECTOR_INDEX_MANIFEST.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    doc = {
        "schema_version": "vector-index-manifest/v1",
        "status": "NOT_BUILT",
        "index_type": None, "index_version": None, "dimensions": None,
        "normalization": None, "embedding_provider": None, "model": None,
        "model_revision": None, "max_input": None, "build_config_hash": None,
        "passage_count": meta["counts"]["passages"],
        "corpus_hash": meta["content_hash"],
        "generated_by": "script:build_demo_corpus.py",
        "blocked_reason": ("demo 语料不附带生产向量索引：向量运行时（onnxruntime/numpy/"
                           "tokenizers）不可用时无法执行 multilingual ONNX 模型。"
                           "检索走词法（FTS）路径；这是 demo 的**显式**基线，不是缺陷。"),
        "rebuild": "（运行时可用后）python3 _scripts/_tools/build_full_vector_index.py --build",
        "gate_12_full_corpus": {
            "passed": False,
            "criteria": {"model_metadata_recorded": False, "index_reproducible": False,
                         "zh_fr_recall_gt_0": False, "contrastive_acceptable": False,
                         "adjudicated_gold_results": False},
            "note": "demo 语料不主张任何向量检索能力"},
        "registry": [],
    }
    with io.open(p, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("  vector/VECTOR_INDEX_MANIFEST.json  status=NOT_BUILT（诚实基线）")


DATA_COMPONENTS = ("passage_store_version", "passage_store_passages_sha256",
                   "retrieval_index_lexical", "retrieval_index_vector",
                   "ontology_version", "corpus_inventory_hash")


def write_declarations(before):
    """数据版本变化声明：before 取自**上一份**（参考语料）冻结 manifest，after 现场复算。"""
    import core_freeze as CF
    after = {k: CF.compute(*CF.SPEC[k]) for k in DATA_COMPONENTS}
    deps = {"passage_store": "REBUILT", "lexical_index": "REBUILT",
            "vector_index": "REBUILT", "corpus_inventory": "CHANGED",
            "graph_cache": "UNCHANGED_BY_DESIGN"}
    rows = []
    for k in DATA_COMPONENTS:
        rows.append({
            "component": k,
            "before_hash": (before.get("components") or {}).get(k),
            "after_hash": after[k],
            "reason": ("安装 demo 语料（公有领域临床文本：Falret 1890 / Binet 1892 / Janet 1909）："
                       "段落库、索引、本体层、语料清单全部重建。学术语义组件（代码单元）未变。"),
            "source_diff": {"added": ["demo-corpus/sources/*.txt（已随仓库分发）"],
                            "removed": [], "modified": [],
                            "note": "demo 语料与参考语料无关；本声明只解释数据版本变化。"},
            "ingestion_status": "INGESTED",
            "dependent_artifacts": deps,
            "canonical_passage_store_changed": True,
            "scholarly_semantic_hashes_unchanged": True,
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    p = os.path.join(VAULT, "_data", "core_freeze", "data_version_declarations.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with io.open(p, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": "data-version-declarations/v1",
                   "generated_by": "script:build_demo_corpus.py",
                   "declarations": rows}, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    print("  data_version_declarations.json  %d 条（%s）" % (len(rows), ", ".join(DATA_COMPONENTS)))


print()
print("=== 阶段 2：索引 / 本体层 / 语料档案 ===")
sys.path.insert(0, os.path.join(VAULT, "_scripts", "_tools"))

# ── 冻结前的「上一份 manifest」：没有它就没法写 before_hash（不猜）
FREEZE_FILE = os.path.join(VAULT, "_data", "core_freeze",
                           "scholarly_core_freeze_v1.json")
before_manifest = {}
if os.path.isfile(FREEZE_FILE):
    before_manifest = json.load(io.open(FREEZE_FILE, encoding="utf-8"))
BEFORE_IS_REFERENCE = bool(before_manifest) and \
    (before_manifest.get("corpus_profile") or "reference") == "reference"

if SKIP_INDEX:
    print("  （--skip-index：跳过索引重建）")
else:
    sh([os.path.join("_scripts", "_tools", "build_lexical_index.py")], "词法索引（FTS）")
    sh([os.path.join("_scripts", "_tools", "build_alias_index.py"), "--quiet"],
       "别名词表索引（实体解析用）")
sh([os.path.join("_scripts", "inventory_corpus.py"), "--source", "demo-corpus/sources",
    "--out", "_data"], "语料清单（corpus_inventory.json）")
write_concept_meta()
write_index_manifest()
write_vector_manifest()

# ── 本体层：spec 是**随仓库分发**的作者层；产物由引擎的生成器现算
spec_src = os.path.join(VAULT, "demo-corpus", "ontology", "spec.json")
if not os.path.isfile(spec_src):
    raise SystemExit("缺 demo 本体 spec：%s" % spec_src)
onto_dir = os.path.join(VAULT, "_data", "ontology", "v4a1")
os.makedirs(onto_dir, exist_ok=True)
import shutil
shutil.copy2(spec_src, os.path.join(onto_dir, "spec.json"))
print("  → 本体层 spec.json（%d 实体）" % len(
    json.load(io.open(spec_src, encoding="utf-8"))["entities"]))
sh([os.path.join("_scripts", "_tools", "build_ontology_v4a1.py")], "生成本体层（证据现算）")
out = sh([os.path.join("_scripts", "_tools", "validate_ontology_v4a1.py"), "--verify"],
         "校验本体层（必须 0 error）")
assert "0 error" in out or "OK" in out, out[-500:]
# 术语桥必须在**本体层生成之后**写（它读的是 term_mappings.jsonl）
write_terminology_bridge()

# ── 语料档案：无人工验收证据 → 声明缺席；研究可运行，但不带人工背书
if SKIP_FREEZE:
    print("  （--skip-freeze：跳过冻结）")
else:
    print()
    print("=== 语料档案（unreviewed-corpus）与谱系 ===")
    if not BEFORE_IS_REFERENCE:
        raise SystemExit("上一份 freeze 不是 reference 档案（%r）：本脚本只用于"
                         "「参考语料 → demo 语料」这一步，避免覆盖别人的档案"
                         % (before_manifest.get("corpus_profile"),))
    write_declarations(before_manifest)
    sh([os.path.join("_scripts", "_tools", "core_freeze.py"), "--build",
        "--profile", "unreviewed-corpus"], "冻结（档案 unreviewed-corpus）")
    hist = os.path.join(VAULT, "_data", "core_freeze", "history",
                        "scholarly_core_freeze_v1.demo-corpus.json")
    os.makedirs(os.path.dirname(hist), exist_ok=True)
    shutil.copy2(FREEZE_FILE, hist)
    seg_file = os.path.join(VAULT, "_data", "core_freeze", "segments.json")
    with io.open(seg_file, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": "freeze-segments/v1",
                   "generated_by": "script:build_demo_corpus.py",
                   "note": "在参考谱系之后追加 demo 语料的基线段（不改参考历史）",
                   "segments": [{"phase": "demo-corpus",
                                 "manifest": "history/scholarly_core_freeze_v1.demo-corpus.json"}]},
                  fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    sh([os.path.join("_scripts", "_tools", "freeze_lineage.py"), "--build"], "冻结谱系（追加 demo 段）")
    out = sh([os.path.join("_scripts", "_tools", "freeze_lineage.py"), "--verify"],
             "校验谱系（semantic 必须为 0）")
    print("  " + out.replace("\n", "\n  "))

# ── 收尾：把边界写给用户，而不是留给文档口头承诺
print()
print("demo 语料就绪（%d 段 / %d 课次 / %d 研讨会 / %d 本体实体）" % (
    len(passages), len(sessions), len(seminars),
    len(json.load(io.open(os.path.join(onto_dir, "MANIFEST.json"), encoding="utf-8"))
        .get("entity_ids") or [])))
print("  语料档案 corpus_profile = unreviewed-corpus")
print("  冻结状态 = CORPUS_HUMAN_REVIEW_NOT_AVAILABLE（**不是** SCHOLARLY_CORE_READY）")
print("  ⚠️ 本语料没有人工验收证据；冻结内核的 claim 归属措辞是为参考语料写的，对本语料不适用。")
print("      demo 承诺的是：检索 / 证据 / 引文 / 检查器 / 本体解析这条链。")
print()
print("下一步（任选其一）：")
print("  python3 -m workspace_ui.server.cli --port 3090     # 网页（/research 里问下面的例子）")
print("  bash _scripts/runtime/start_lacan_os.sh            # launcher（会跑冻结/谱系门）")
print("  例子问题（法文，demo 语料里证据最足）：Comment la suggestion agit-elle dans l'hystérie ?")
