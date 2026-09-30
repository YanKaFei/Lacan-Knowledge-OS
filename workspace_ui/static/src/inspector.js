// inspector.js — Evidence Inspector（§15–§18）：passage / quoted span / context /
// provenance / L1·L2 / SOURCE_TRACE_INCOMPLETE。全部走 API，纯文本渲染。
import { h, mount, highlight, paragraphs } from './dom.js';
import { api } from './api.js';
import { t } from './i18n.js';

let current = { id: null, before: 3, after: 3, span: null };

export function closeInspector(ui) {
  const side = document.getElementById('inspector');
  side.hidden = true;
  document.getElementById('layout').classList.remove('inspector-open');
  ui && ui.focusAsk && ui.focusAsk();
}

export async function openInspector(citation, ui) {
  current = { id: citation.passage_id, before: 3, after: 3, span: citation.quoted_span || null };
  const side = document.getElementById('inspector');
  side.hidden = false;
  document.getElementById('layout').classList.add('inspector-open');
  const body = document.getElementById('inspector-body');
  mount(body, h('div', { class: 'loading' }, [
    h('span', { class: 'spinner' }), h('span', { text: t('evidence-inspector.loading-evidence') })]));
  const v = await api.passage(current.id, current.before, current.after, current.span);
  renderPanel(v, body);
  document.getElementById('inspector-close').focus();
}

export function renderPanel(v, body) {
  if (!v || v.kind === 'error') {
    mount(body, h('div', { class: 'notice is-err' }, [
      h('h4', { text: (v && v.title) || 'Evidence unavailable' }),
      h('p', { text: (v && v.body) || '' })]));
    return;
  }
  const p = v.passage || {};
  const sl = v.source_layer || {};
  const nodes = [];
  nodes.push(h('div', { class: 'answer-head' }, [
    h('span', { class: 'state-badge', text: v.citation_label || p.passage_id }),
    sl.tag ? h('span', { class: `tag ${sl.code === 'L2_RECOVERED' ? 'is-l2' : 'is-l1'}`,
      text: sl.tag, title: sl.label || '' }) : null,
    sl.label ? h('span', { class: 'muted', text: sl.label }) : null,
  ]));
  nodes.push(h('dl', { class: 'kv' }, [
    h('dt', { text: 'passage_id' }), h('dd', { text: p.passage_id || '' }),
    h('dt', { text: t('evidence-inspector.seminar') }), h('dd', { text: p.seminar || '' }),
    h('dt', { text: t('evidence-inspector.session') }), h('dd', { text: p.session || '' }),
    h('dt', { text: t('evidence-inspector.year') }), h('dd', { text: [p.year_from, p.year_to].filter(Boolean).join('–') }),
    h('dt', { text: t('evidence-inspector.language') }), h('dd', { text: p.language || '' }),
    h('dt', { text: t('evidence-inspector.witness') }), h('dd', { text: p.witness || '' }),
    h('dt', { text: t('evidence-inspector.provenance') }), h('dd', { text: p.trace_status || '' }),
  ]));
  nodes.push(h('h3', { text: t('evidence-inspector.original-passage') }));
  nodes.push(h('div', { class: 'passage-text' }, highlight(p.text || '', v.quoted_span)));
  if (v.quoted_span) {
    nodes.push(h('h3', { text: t('evidence-inspector.quoted-span') }));
    nodes.push(h('div', { class: 'passage-text' }, [h('span', { text: v.quoted_span })]));
  }
  if (v.trace_incomplete) {
    nodes.push(h('div', { class: 'notice is-warn' }, [
      h('h4', { text: t('evidence-inspector.source-trace-incomplete') }),
      h('p', { text: v.trace_incomplete_note || '' })]));
  }
  // context
  nodes.push(h('h3', { text: t('evidence-inspector.context') }));
  nodes.push(h('div', { class: 'ctx-controls', id: 'ctx-controls' },
    [[0, 0], [2, 2], [5, 5], [10, 10]].map(([b, a]) => h('button', {
      type: 'button', text: `±${b === 0 ? 0 : b}`,
      'aria-pressed': String(b === current.before),
      onclick: () => reloadContext(b, a, body),
    }))));
  nodes.push(renderContext(v));
  // provenance chain
  if (v.provenance) {
    nodes.push(h('h3', { text: t('evidence-inspector.source-chain') }));
    nodes.push(renderChain(v.provenance));
  }
  nodes.push(h('h3', { text: t('evidence-inspector.translation') }));
  nodes.push(h('p', { class: 'muted', text: v.aligned_translation_note || '' }));
  nodes.push(h('div', { class: 'ctx-controls' }, [
    h('button', { type: 'button', id: 'save-passage-btn', text: t('evidence-inspector.save-passage'),
      onclick: () => savePassage(v, body) }),
  ]));
  nodes.push(h('div', { id: 'save-passage-status' }));
  mount(body, ...nodes);
}

function renderContext(v) {
  const wrap = h('div');
  for (const c of v.context || []) {
    const focus = c.passage_id === v.passage && false;   // 焦点条目单独标
    wrap.appendChild(h('div', {
      class: 'ctx-item' + (c.passage_id === (v.passage || {}).passage_id ? ' is-focus' : ''),
    }, [
      h('span', { class: 'ctx-id', text: c.passage_id || '' }),
      h('span', { text: (c.text || '').slice(0, 600) }),
    ]));
  }
  if (!(v.context || []).length) wrap.appendChild(h('p', { class: 'muted', text: t('evidence-inspector.no-context-window') }));
  return wrap;
}

function renderChain(prov) {
  const items = [];
  if (prov.corpus_source) items.push(['CorpusSource', prov.corpus_source]);
  if (prov.witness) items.push(['Witness', prov.witness]);
  if (prov.passage_realization) items.push(['PassageRealization', prov.passage_realization]);
  if (prov.seminar) items.push(['Seminar', prov.seminar]);
  if (prov.session) items.push(['Session', prov.session]);
  if (prov.edition) items.push(['Edition', prov.edition]);
  if (prov.trace_status) items.push(['Trace status', prov.trace_status]);
  const ul = h('ul', { class: 'chain' });
  for (const [k, val] of items) {
    ul.appendChild(h('li', {}, [h('span', { class: 'tag', text: k }),
      h('span', { text: String(val) })]));
  }
  if (!items.length) ul.appendChild(h('li', { text: t('evidence-inspector.no-provenance-fields-available') }));
  return ul;
}

async function reloadContext(before, after, body) {
  current.before = before; current.after = after;
  const v = await api.passage(current.id, before, after, current.span);
  renderPanel(v, body);
}

async function savePassage(v, body) {
  const out = await api.obsidianSavePassage(v.passage.passage_id);
  const { renderSaveResult } = await import('./render.js');
  const target = document.getElementById('save-passage-status') || body;
  renderSaveResult(target, out);
}

export function currentTarget() { return { ...current }; }
