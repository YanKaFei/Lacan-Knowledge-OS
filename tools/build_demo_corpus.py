#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a public-domain demo corpus in the Lacan Knowledge OS passage-store schema.

Sources (all public domain, fetched from fr.wikisource with their real imprint data):
  * Jules Falret, Études cliniques sur les maladies mentales et nerveuses, Baillière, 1890
  * Alfred Binet, Les Altérations de la personnalité, Félix Alcan, 1892
  * Pierre Janet, Les Névroses, Flammarion, 1909
"""
import argparse
import hashlib, io, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
VAULT = sys.argv[1] if len(sys.argv) > 1 else REPO
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
print('next (not yet done — see docs/DEMO_CORPUS.md):')
print('  1. python3 _scripts/_tools/build_lexical_index.py')
print('  2. tiny ontology layer for the demo terms (entities/relations/term_mappings)')
print('     without it the core abstains with reason ONTOLOGY_GAP — correct behaviour,')
print('     but it means the demo cannot yet produce a VALIDATED answer.')
