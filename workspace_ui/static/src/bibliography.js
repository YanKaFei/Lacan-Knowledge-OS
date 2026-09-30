// bibliography.js — Final Daily Use：Bibliography Explorer（只读 + Zotero 文件导入）
//
// 纪律：
//  * citation 一律经服务端**唯一** CitationRenderer；不可用时**给出原因**（§2/§3）。
//  * candidate 永远不可引用（§4），显式标 NEEDS REVIEW / NOT CITABLE。
//  * reviewed ≠ metadata complete：三者（review / completeness / capabilities）**分开显示**（§5）。
//  * 链条只显示真实存在的层；Not linked 不隐藏（§7）。
import { h, mount } from './dom.js';
import { t } from './i18n.js';
import { teachEmpty } from './teach.js';

const NOTICE = 'Bibliographic metadata only. Citations are offered only when verified '
  + 'metadata exists — publisher, year, ISBN and page numbers are never invented.';
const CAP_KEY = { internal: 'internal_full', provenance: 'provenance',
  chicago: 'chicago', apa: 'apa', mla: 'mla', bibtex: 'bibtex' };
const CHAIN_LAYERS = ['Passage Realization', 'Witness', 'Edition',
                      'Bibliographic Item', 'Corpus Source'];

async function get(url) {
  const r = await fetch(url, { headers: { 'Accept': 'application/json' } });
  return r.json();
}
async function post(url, body) {
  const r = await fetch(url, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.json();
}

export async function renderBibliography(host, st) {
  const wrap = h('section', { class: 'card', id: 'bibliography-explorer' });
  wrap.appendChild(h('h2', { text: t('bibliography.bibliography') }));
  wrap.appendChild(h('p', { class: 'muted', id: 'bibliography-notice', text: NOTICE }));
  wrap.appendChild(importPanel());

  const form = h('div', { class: 'bib-filters' }, [
    h('label', { for: 'bib-q', text: t('bibliography.search') }),
    h('input', { id: 'bib-q', type: 'search', value: st.q || '' }),
    h('label', { for: 'bib-status', text: t('bibliography.review') }),
    h('select', { id: 'bib-status' }, [
      h('option', { value: '', text: t('bibliography.any') }),
      h('option', { value: 'reviewed', text: t('bibliography.reviewed') }),
      h('option', { value: 'needs_review', text: t('bibliography.needs-review') }),
    ]),
    h('button', { type: 'button', class: 'btn', id: 'bib-search', text: t('bibliography.search'),
      onclick: () => go({ q: val('bib-q'), review_status: val('bib-status'),
                          id: null, cursor: '0' }) }),
  ]);
  if (st.review_status) form.querySelector('#bib-status').value = st.review_status;
  wrap.appendChild(form);

  const listHost = h('div', { id: 'bibliography-list' });
  const detailHost = h('div', { id: 'bibliography-detail' });
  wrap.appendChild(listHost);
  wrap.appendChild(detailHost);
  mount(host, wrap);

  const qs = new URLSearchParams();
  for (const k of ['q', 'author', 'year', t('evidence-inspector.language'), 'item_type', 'review_status']) {
    if (st[k]) qs.set(k, st[k]);
  }
  qs.set('cursor', st.cursor || '0');
  qs.set('limit', '20');
  let res;
  try { res = await get('/api/explore/bibliography?' + qs.toString()); }
  catch (e) { listHost.appendChild(h('p', { class: 'muted', text: t('bibliography.load-failed') })); return; }

  const ul = h('ul', { class: 'bib-list', id: 'bib-items' });
  if (!(res.items || []).length) {
    listHost.appendChild(teachEmpty(t('search.empty.title'), t('search.empty.body'),
      [[t('projects.empty.learn'), '/help/bibliography'],
       [t('search.empty.try-research'), '/help/troubleshooting']],
      { id: 'bib-empty', actionIds: ['bib-empty-help', 'bib-empty-trouble'] }));
    return;
  }
  for (const it of (res.items || [])) {
    const isCand = it.review_status !== 'reviewed';
    const li = h('li', {}, [
      h('button', { type: 'button', class: 'link-btn bib-row',
                    'data-bib-id': it.bibliographic_id,
                    'data-review': it.review_status,
                    text: (it.title || it.bibliographic_id)
                      + (isCand ? '  [NEEDS REVIEW · NOT CITABLE]' : '  [reviewed]'),
                    onclick: () => go(Object.assign({}, st, { id: it.bibliographic_id })) }),
      h('span', { class: 'muted', text: '  ' + it.bibliographic_id + ' · '
        + it.item_type + ' · ' + (it.metadata_completeness || '') }),
    ]);
    ul.appendChild(li);
  }
  listHost.appendChild(ul);
  const pg = res.page || {};
  listHost.appendChild(h('p', { class: 'muted', id: 'bib-page',
    text: t('bibliography.offset') + pg.offset + ' returned=' + pg.returned + ' total=' + pg.total }));
  if (pg.next_offset !== null && pg.next_offset !== undefined) {
    listHost.appendChild(h('button', { type: 'button', class: 'btn btn-ghost',
      id: 'bib-next', text: t('bibliography.next-page'),
      onclick: () => go(Object.assign({}, st, { id: null,
                                                cursor: String(pg.next_offset) })) }));
  }
  if (st.id) await renderDetail(detailHost, st, res.items || []);
}

async function renderDetail(host, st, pageItems) {
  let d;
  try { d = await get('/api/explore/bibliography_item?id=' + encodeURIComponent(st.id)); }
  catch (e) { host.appendChild(h('p', { class: 'muted', text: t('bibliography.detail-failed') })); return; }
  const it = d.item || {};
  const isCand = it.review_status !== 'reviewed';
  const box = h('article', { class: 'card', id: 'bibliography-detail-card' });
  box.appendChild(h('h3', { text: it.title || it.bibliographic_id }));

  // §4：candidate 横幅
  if (isCand) {
    box.appendChild(h('div', { class: 'notice is-warn', id: 'bib-candidate-banner' }, [
      h('strong', { text: t('bibliography.needs-review-not-citable') }),
      h('p', { class: 'muted', text: t('bibliography.this-record-has-not-been-promoted-to-reviewed--full') }),
    ]));
  }

  // Overview
  box.appendChild(h('h4', { text: t('bibliography.overview') }));
  const rows = [['bibliographic_id', it.bibliographic_id], ['item_type', it.item_type],
    ['authors', (it.authors || []).join(', ') || '—'],
    ['publisher', it.publisher || '—'], ['publication_year', it.publication_year || '—'],
    [t('explore.edition'), it.edition || '—'], [t('evidence-inspector.language'), it.language || '—']];
  box.appendChild(h('dl', { class: 'kv' }, rows.flatMap(([k, v]) => [
    h('dt', { text: k }), h('dd', { text: String(v) })])));

  // §5：三者分开显示
  box.appendChild(h('h4', { text: t('bibliography.review-status') }));
  box.appendChild(h('p', { id: 'bib-review-status',
    text: it.review_status + (it.review_basis ? ' (' + it.review_basis + ')' : '') }));
  box.appendChild(h('h4', { text: t('bibliography.metadata-completeness') }));
  box.appendChild(h('p', { id: 'bib-metadata-completeness',
    text: it.metadata_completeness || '—' }));
  box.appendChild(h('p', { class: 'muted', id: 'bib-reviewed-not-complete',
    text: t('bibliography.reviewed-does-not-mean-bibliographically-complet') }));

  // §3：Citation Availability（含原因）；§4：candidate **不**展示样式清单
  const ca = await get('/api/explore/citation_availability?id='
    + encodeURIComponent(it.bibliographic_id));
  box.appendChild(h('h4', { text: t('bibliography.citation-availability') }));
  if (isCand) {
    box.appendChild(h('p', { class: 'muted', id: 'bib-not-citable',
      text: t('bibliography.no-citation-style-is-offered-for-this-record-it--full--full') }));
  } else {
    const availRows = (ca.rows || []).map((r) => h('li', {
      class: 'bib-avail-row', 'data-style': r.style,
      id: 'bib-avail-' + r.style, 'data-status': r.status,
      text: r.label + ' — ' + r.status + (r.reason ? (' · why: ' + r.reason) : '')
    }));
    box.appendChild(h('ul', { class: 'bib-avail', id: 'bib-availability' }, availRows));
    if (ca.soft_missing_note) {
      box.appendChild(h('p', { class: 'muted', id: 'bib-soft-missing',
        text: ca.soft_missing_note }));
    }
    box.appendChild(h('p', { class: 'muted', id: 'bib-internal-note',
      text: (ca.internal_note || '') }));
  }

  // 链条（§7/§8/§9）：只显示真实存在的层
  const wit = (d.witnesses || [])[0] || null;
  let chain = null;
  if (wit) {
    try { chain = await get('/api/explore/bibliography_chain?witness_id='
      + encodeURIComponent(wit.witness_id)); } catch (e) { chain = null; }
  }
  const samplePassage = ((chain && chain.passage_realization
    && chain.passage_realization.sample_passage_ids) || [])[0] || null;

  // §8/§9：段落现实（客观计数，绝不假装有 passage）
  const pr = ca.passage_realizations || {};
  const passageTotal = (pr.total !== undefined && pr.total !== null)
    ? pr.total : (wit ? wit.passage_count : 0);
  box.appendChild(h('p', { id: 'bib-passage-realizations', 'data-total': passageTotal,
    text: t('bibliography.passage-realizations') + Number(passageTotal).toLocaleString('en-US') }));

  // Citation copy（§2–§5）：只对服务端声明 available 的样式开放按钮
  if (!isCand) {
    const ready = (ca.rows || []).filter((r) => r.available && r.status === 'READY');
    const citeOut = h('p', { class: 'bib-citation', id: 'bib-citation' });
    box.appendChild(h('div', { class: 'bib-cite-buttons' }, ready.map((r) =>
      h('button', { type: 'button', class: 'btn btn-ghost', 'data-style': r.style,
        id: 'bib-cite-' + r.style, text: t('bibliography.copy') + r.label,
        onclick: async () => {
          const q = '/api/explore/bibliography_citation?id='
            + encodeURIComponent(it.bibliographic_id) + '&style='
            + encodeURIComponent(r.style)
            + (samplePassage ? ('&passage_id=' + encodeURIComponent(samplePassage)) : '');
          const res = await get(q);
          citeOut.textContent = res.available ? res.text
            : ('unavailable: ' + (res.reason || 'metadata incomplete'));
        } }))));
    if (passageTotal > 0 && wit) {                      // §9：Staferla 可浏览段落
      box.appendChild(h('button', { type: 'button', class: 'btn btn-ghost',
        id: 'bib-browse-passages', text: t('bibliography.browse-passages'),
        onclick: () => go({ view: 'passages' }) }));
    }
    const blockedPassage = (ca.rows || []).filter((r) => !r.available
      && /passage/i.test(String(r.reason || '')));
    if (blockedPassage.length) {
      box.appendChild(h('p', { class: 'muted', id: 'bib-no-passage',
        text: t('bibliography.not-offered-no-linked-passagerealization')
          + blockedPassage.map((r) => r.label).join(', ')
          + ' — Passage Realizations = 0. That is a fact about the evidence, not an '
          + 'empty slot waiting to be filled.' }));
    }
    box.appendChild(citeOut);
  }

  box.appendChild(h('h4', { text: t('bibliography.layers') }));
  const chainRows = CHAIN_LAYERS.map((label) => {
    let v = 'Not linked';
    if (label === 'Passage Realization') {
      v = wit ? (wit.passage_count + ' passages'
        + (wit.passage_count ? '' : ' — Not linked (0 passages)')) : 'Not linked';
    } else if (label === 'Witness') v = wit ? wit.witness_id : 'Not linked';
    else if (label === 'Edition') v = (wit && wit.edition_id) || 'Not linked';
    else if (label === 'Bibliographic Item') v = it.bibliographic_id;
    else if (label === 'Corpus Source') {
      v = (chain && chain.corpus_source) || (wit && wit.corpus_source_id) || 'Not linked';
    }
    return h('li', { class: 'bib-chain-row', id: 'bib-chain-' + label.replace(/ /g, '-'),
                     text: label + ': ' + v });
  });
  box.appendChild(h('ul', { class: 'bib-chain', id: 'bib-chain' }, chainRows));
  if (chain && (chain.missing_layers || []).length) {
    box.appendChild(h('p', { class: 'muted', id: 'bib-missing-layers',
      text: t('bibliography.missing-layers-shown-as-is-never-filled-in')
        + chain.missing_layers.join(', ') }));
  }
  // §8：Seuil 控制
  if (wit && wit.witness_id === 'witness.fr.seuil-pdf') {
    box.appendChild(h('p', { class: 'muted', id: 'bib-seuil-note',
      text: t('bibliography.this-witness-is-known-to-the-system-but-the-cano--full--full') }));
  }
  // §10：中文 recovered（学术限制，不是 error）
  if (wit && wit.witness_kind === 'translation') {
    box.appendChild(h('p', { class: 'notice', id: 'bib-trace-incomplete',
      text: t('bibliography.source-trace-incomplete-this-text-is-available-f--full--full') }));
  }

  box.appendChild(h('h4', { text: t('bibliography.editions') }));
  box.appendChild(h('ul', { id: 'bib-editions' }, (d.editions || []).map((e) =>
    h('li', { id: 'bib-edition-' + e.edition_id,
      text: e.edition_id + ' · page_locator_available=' + e.page_locator_available
        + ' · publisher=' + (e.publisher || '—') + ' · year=' + (e.year || '—') }))));
  box.appendChild(h('h4', { text: t('bibliography.witnesses') }));
  box.appendChild(h('ul', { id: 'bib-witnesses' }, (d.witnesses || []).map((w) =>
    h('li', { id: 'bib-witness-' + w.witness_id,
      text: w.witness_id + ' (' + w.witness_kind + ') · passages=' + w.passage_count
        + ' · ' + w.passage_realization_state }))));
  box.appendChild(h('h4', { text: t('bibliography.passages') }));
  const sample = (chain && chain.passage_realization
    && chain.passage_realization.sample_passage_ids) || [];
  box.appendChild(h('ul', { id: 'bib-passages' }, sample.length
    ? sample.map((p) => h('li', { text: p }))
    : [h('li', { class: 'muted', id: 'bib-passages-none',
                 text: t('bibliography.not-linked-0-passages-from-this-witness') })]));

  box.appendChild(h('h4', { text: t('bibliography.seminars') }));
  box.appendChild(h('ul', { id: 'bib-seminars' }, [h('li', { class: 'muted',
    id: 'bib-seminars-note',
    text: t('bibliography.seminar-id-published-edition-no-seminar-link-rec') })]));
  box.appendChild(h('h4', { text: t('bibliography.projects') }));
  box.appendChild(h('p', { class: 'muted', id: 'bib-projects',
    text: t('bibliography.add-this-item-to-a-project-from-the-projects-vie') }));
  box.appendChild(h('h4', { text: t('bibliography.provenance') }));
  box.appendChild(h('pre', { class: 'bib-provenance', id: 'bib-provenance',
    text: JSON.stringify({ provenance: d.provenance,
      metadata_provenance: d.metadata_provenance }, null, 1).slice(0, 1200) }));
  host.appendChild(box);
}

// ───────────────────────────────────────────── Zotero 文件导入（§13–§18）
function importPanel() {
  const box = h('details', { class: 'fold', id: 'bib-import-panel' }, [
    h('summary', { text: t('bibliography.import-zotero-csl-json') }),
  ]);
  box.appendChild(h('p', { class: 'muted', text:
    t('bibliography.supported-csl-json-better-bibtex-json-imported-i--full') }));
  box.appendChild(h('div', { class: 'bib-import-controls' }, [
    h('label', { for: 'bib-import-file', text: t('bibliography.select-file') }),
    h('input', { id: 'bib-import-file', type: 'file',
                 accept: '.json,.bibtex,.bib,application/json' }),
    h('label', { for: 'bib-import-source', text: t('bibliography.format') }),
    h('select', { id: 'bib-import-source' }, [
      h('option', { value: 'csl-json', text: 'CSL JSON' }),
      h('option', { value: 'better-bibtex', text: 'Better BibTeX JSON' }),
    ]),
    h('button', { type: 'button', class: 'btn', id: 'bib-import-preview',
                  text: t('bibliography.preview'), onclick: () => doImport(false) }),
    h('button', { type: 'button', class: 'btn btn-primary', id: 'bib-import-commit',
                  text: t('bibliography.import-as-candidate'), onclick: () => doImport(true) }),
  ]));
  box.appendChild(h('div', { id: 'bib-import-preview-out' }));
  box.appendChild(h('div', { id: 'bib-import-result' }));
  return box;
}

async function doImport(commit) {
  const f = document.getElementById('bib-import-file');
  const out = document.getElementById('bib-import-preview-out');
  const res = document.getElementById('bib-import-result');
  out.replaceChildren();
  res.replaceChildren();
  if (!f || !f.files || !f.files.length) {
    out.appendChild(h('p', { class: 'muted', text: t('bibliography.no-file-selected') }));
    return;
  }
  const text = await f.files[0].text();
  const source = val('bib-import-source') || 'csl-json';
  const r = await post('/api/bibliography/import',
    { text: text, source: source, mode: commit ? 'commit' : 'preview' });
  if (r.kind === 'error') {
    out.appendChild(h('p', { class: 'muted', id: 'bib-import-error',
      text: (r.code || 'error') + ': ' + (r.body || '') }));
    return;
  }
  out.appendChild(h('p', { class: 'muted', id: 'bib-import-counts',
    text: t('bibliography.candidates') + r.counts.candidates + ' · duplicates=' + r.counts.duplicates
      + ' · conflicts=' + r.counts.conflicts + ' · rejected=' + r.counts.rejected }));
  if (r.preview) {
    out.appendChild(h('table', { class: 'bib-preview', id: 'bib-import-preview-table' }, [
      h('tr', {}, [h('th', { text: t('bibliography.title') }), h('th', { text: t('bibliography.author') }),
                   h('th', { text: t('bibliography.year') }), h('th', { text: t('bibliography.identifier') }),
                   h('th', { text: t('bibliography.duplicate') }), h('th', { text: t('bibliography.conflict') })]),
      ...r.preview.map((p) => h('tr', { class: 'bib-preview-row',
        'data-candidate': p.candidate_id }, [
        h('td', { text: p.title || '—' }),
        h('td', { text: (p.authors || []).join(', ') || '—' }),
        h('td', { text: p.year || '—' }),
        h('td', { text: p.identifier || '—' }),
        h('td', { text: dupLabel(r.duplicates, p.candidate_id) }),
        h('td', { text: conflictLabel(r.conflicts, p.candidate_id) })]))]));
  }
  if ((r.duplicates || []).length) {
    out.appendChild(h('ul', { id: 'bib-import-duplicates' }, r.duplicates.map((d) =>
      h('li', { 'data-kind': d.kind, text: (d.kind === 'EXACT_KEY'
        ? 'Strong duplicate' : 'Possible duplicate') + ' (' + d.dedup_key_kind
        + ') — auto_merged=' + d.auto_merged }))));
  }
  if ((r.conflicts || []).length) {
    out.appendChild(h('ul', { id: 'bib-import-conflicts' }, r.conflicts.map((c) =>
      h('li', { 'data-code': c.code, text: c.code + ' · ' + c.field + ' = '
        + Object.entries(c.values).map(([v, ids]) => v + ' (' + ids.join(',') + ')').join(' vs ')
        + ' · ' + c.resolution + ' · auto_overwrite=' + c.auto_overwrite }))));
  }
  if ((r.rejected || []).length) {
    out.appendChild(h('ul', { id: 'bib-import-rejected' }, r.rejected.map((x) =>
      h('li', { class: 'muted', text: t('bibliography.rejected') + x.reason }))));
  }
  if (commit) {
    res.appendChild(h('p', { class: 'notice', id: 'bib-import-message',
      text: (r.message || 'Imported as candidate. Not automatically canonicalized.')
        + '  (candidate store: ' + (r.candidate_store || '—') + ')' }));
  }
}

function dupLabel(dups, cid) {
  const d = (dups || []).find((x) => (x.members || []).indexOf(cid) >= 0);
  if (!d) return 'No duplicate found';
  return d.kind === 'EXACT_KEY' ? 'Strong duplicate' : 'Possible duplicate';
}
function conflictLabel(conflicts, cid) {
  const c = (conflicts || []).find((x) =>
    Object.values(x.values || {}).some((ids) => (ids || []).indexOf(cid) >= 0));
  return c ? (c.code + ' (' + c.field + ')') : '—';
}
function val(id) { const e = document.getElementById(id); return e ? e.value : ''; }
function go(next) {
  import('./router.js').then((R) => R.navigate(Object.assign({ view: 'bibliography' }, next)));
}
