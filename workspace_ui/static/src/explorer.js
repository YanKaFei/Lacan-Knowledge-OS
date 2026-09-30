// explorer.js — Concept / Passage / Seminar / Terminology Explorer（Phase 4D.4）
//
// 纪律（写进代码，不靠注释提醒）：
//   * 只用 h()/textContent 构建 DOM：corpus 文本与用户输入都是 untrusted（§63）；
//   * ontology 事实与 corpus 事实**视觉上分开标注**（§33）；
//   * 0 结果只说「当前 browse 条件下没有匹配段落」（§66），不是弃权（§65）；
//   * 每个视图都能从 URL 状态直接到达，Back 由浏览器处理（§49/§50）。
import { h, mount } from './dom.js';
import { api } from './api.js';
import { navigate } from './router.js';
import { addToProjectDialog } from './project.js';
import { citationMenu, exportBar } from './export.js';
import { t } from './i18n.js';
import { teachEmpty } from './teach.js';

let CTX = { onPrefill: null };

export function setExplorerContext(ctx) { CTX = { ...CTX, ...ctx }; }

const TAG_ONT = 'tag is-ontology';
const TAG_CORPUS = 'tag is-corpus';

function tagOntology(text) { return h('span', { class: TAG_ONT, text }); }
function tagCorpus(text) { return h('span', { class: TAG_CORPUS, text }); }
function muted(text) { return h('p', { class: 'muted', text }); }
function notice(title, body, kind) {
  return h('div', { class: 'notice' + (kind ? ' ' + kind : '') }, [
    h('h2', { text: title }), body ? h('p', { text: body }) : null]);
}
function kv(rows) {
  const list = [];
  for (const [k, v] of rows) {
    if (v === null || v === undefined || v === '') continue;
    list.push(h('dt', { text: k }), h('dd', { text: String(v) }));
  }
  return list.length ? h('dl', { class: 'kv' }, list) : null;
}
function linkBtn(label, onClick, cls) {
  return h('button', { class: 'link-btn' + (cls ? ' ' + cls : ''), type: 'button',
    text: label, onclick: onClick });
}
function go(next) { mount(document.getElementById('explorer'), h('p', { class: 'muted', text: t('explore.loading') })); navigate(next); }

async function copyText(text, statusEl) {
  try {
    await navigator.clipboard.writeText(text);
    if (statusEl) statusEl.textContent = 'Copied';
  } catch (e) {
    if (statusEl) statusEl.textContent = 'Copy unavailable — select the text manually';
  }
}

// ─────────────────────────────────────────────────────────── 概念列表
async function renderConcepts(params) {
  const data = await api.explore('concepts', {
    query: params.query, status: params.status, layer: params.layer,
    cursor: params.cursor, limit: 25,
  });
  const box = h('section', { class: 'explorer-view', id: 'explorer-concepts' });
  box.appendChild(h('div', { class: 'explorer-head' }, [
    h('h1', { class: 'explorer-title', text: t('explore.concepts') }),
    h('span', { class: 'tag', text: `${data.total} concepts` }),
  ]));
  box.appendChild(h('p', { class: 'muted', text:
    t('explore.concept-records-come-from-two-layers-canonical-o--full') }));

  // Phase 5A（P5A-003）：不能只靠 placeholder —— 必须有显式可访问名。
  const searchLabelId = 'concept-search-label';
  const label = h('label', { class: 'sr-only', id: searchLabelId, for: 'concept-search',
    text: t('explore.search-concepts-by-label-alias-or-id') });
  const input = h('input', { class: 'explorer-input', id: 'concept-search',
    type: 'search', value: params.query || '',
    'aria-labelledby': searchLabelId,
    placeholder: t('explore.search-label-alias-id') });
  const form = h('form', { class: 'explorer-form', onsubmit: (e) => {
    e.preventDefault();
    go({ view: 'concepts', query: input.value });
  } }, [input, h('button', { class: 'btn', type: 'submit', text: t('bibliography.search') }),
    linkBtn('all', () => go({ view: 'concepts' }))]);
  box.appendChild(form);
  box.appendChild(h('div', { class: 'chips' }, [
    linkBtn('all layers', () => go({ view: 'concepts', query: params.query })),
    linkBtn('ontology', () => go({ view: 'concepts', query: params.query, layer: 'ontology' })),
    linkBtn('catalog', () => go({ view: 'concepts', query: params.query, layer: 'catalog' })),
  ]));

  const ul = h('ul', { class: 'concept-list' });
  for (const it of data.items) {
    ul.appendChild(h('li', { class: 'concept-row' }, [
      h('button', { class: 'row-main', type: 'button',
        onclick: () => go({ view: 'concept', id: it.concept_id }) }, [
        h('span', { class: 'row-label', text: it.preferred_label }),
        h('span', { class: 'row-id', text: it.concept_id }),
        h('span', { class: 'row-aliases', text: (it.aliases || []).join(' · ') }),
      ]),
      h('span', { class: 'row-meta' }, [
        ...(it.layers || []).map((l) => h('span', {
          class: 'tag ' + (l === 'ontology' ? 'is-ontology' : 'is-catalog'), text: l })),
        h('span', { class: 'tag', text: `${it.relations_n} relations` }),
        it.reviewed_relations_n
          ? h('span', { class: 'tag is-reviewed', text: `${it.reviewed_relations_n} reviewed` })
          : null,
        h('span', { class: 'tag', text: `${it.seminars_n} seminars` }),
        it.review_status ? h('span', { class: 'tag', text: it.review_status }) : null,
      ]),
    ]));
  }
  box.appendChild(ul);
  box.appendChild(pager(data.page, (c) => go({ view: 'concepts', query: params.query,
    status: params.status, layer: params.layer, cursor: c })));
  return box;
}

function pager(page, onNext) {
  const p = page || {};
  const row = h('div', { class: 'pager' }, [
    h('span', { class: 'muted', text:
      `${p.returned || 0} shown${p.total !== undefined ? ' / ' + p.total + ' total' : ''}` +
      (p.exhaustive ? ' · exhaustive server-side filter' : '') }),
  ]);
  if (p.order) row.appendChild(h('span', { class: 'muted', text: `order: ${p.order}` }));
  if (p.next_cursor) {
    row.appendChild(h('button', { class: 'btn btn-ghost', type: 'button', id: 'next-page',
      text: t('bibliography.next-page'), onclick: () => onNext(p.next_cursor) }));
  }
  return row;
}

// ─────────────────────────────────────────────────────────── 概念详情
async function renderConcept(params) {
  const d = await api.explore('concept', { id: params.id });
  if (d.kind === 'error') return errorBox(d);
  const box = h('section', { class: 'explorer-view', id: 'explorer-concept' });
  const hd = d.header;
  box.appendChild(h('div', { class: 'explorer-head' }, [
    h('h1', { class: 'explorer-title', id: 'concept-title', text: hd.preferred_label }),
    h('span', { class: 'row-id', text: hd.concept_id }),
  ]));
  box.appendChild(kv([
    ['Aliases', (hd.aliases || []).join(' · ')],
    ['Ontology status', hd.ontology_status],
    ['Ontology version', hd.ontology_version],
    [t('explore.field-review-status'), hd.review_status],
    [t('bibliography.layers'), (hd.layers || []).join(', ')],
    ['Entity role', hd.entity_role],
    ['Authority level', hd.authority_level],
    ['FR / ZH / EN', [hd.fr, hd.zh, hd.en].filter(Boolean).join(' / ')],
  ]));

  // A. Canonical Reference
  const cr = d.canonical_reference;
  const crBox = h('div', { class: 'card' }, [
    h('h2', {}, [h('span', { text: t('explore.canonical-reference') }), ' ', tagOntology('ontology')]),
    cr.canonical_definition
      ? h('div', { class: 'section-body' }, [h('p', { text: cr.canonical_definition })])
      : notice('No canonical definition recorded.',
        'The ontology has not recorded a definition for this concept. Nothing is '
        + 'generated here to fill the gap.'),
  ]);
  if (cr.usage_note) crBox.appendChild(h('details', { class: 'fold' }, [
    h('summary', { text: t('explore.usage-note-canonical') }),
    h('div', { class: 'section-body' }, [h('p', { text: cr.usage_note })])]));
  if (cr.misreadings) crBox.appendChild(h('details', { class: 'fold' }, [
    h('summary', { text: t('explore.misreadings-canonical') }),
    h('div', { class: 'section-body' }, [h('p', { text: cr.misreadings })])]));
  box.appendChild(crBox);

  // B. Relations（reviewed / candidate 分开）
  box.appendChild(relationsBox(d.relations));

  // mini graph
  box.appendChild(graphBox(d.graph));

  // C. Evidence（ontology 记录的段落）
  const ev = d.evidence;
  box.appendChild(h('div', { class: 'card' }, [
    h('h2', {}, [h('span', { text: t('explore.evidence') }), ' ', tagOntology(ev.mode)]),
    h('p', { class: 'muted', text: ev.label }),
    (ev.sample || []).length
      ? h('ul', { class: 'plain-list' }, ev.sample.map((pid) => h('li', {},
          [passageLink(pid)])))
      : notice('No ontology-recorded passages for this concept.',
        'Browse the corpus by form instead — the attestation block below does exactly '
        + 'that, with its own (corpus) label.'),
  ]));

  // corpus attestation
  box.appendChild(attestationBox(d.attestation));

  // D. Seminar distribution
  box.appendChild(distributionBox(d.seminar_distribution));

  // E. Diachronic
  box.appendChild(diachronicBox(d.diachronic));

  if ((d.states || []).length) {
    box.appendChild(h('div', { class: 'card' }, [
      h('h2', {}, [h('span', { text: t('explore.period-states') }), ' ', tagOntology('catalog')]),
      h('ul', { class: 'plain-list' }, d.states.map((s) => h('li', {
        text: `${s.period || '—'} · ${s.period_label || ''} ${s.definition ? '— ' + String(s.definition).slice(0, 160) : ''}` }))),
    ]));
  }

  box.appendChild(researchActionsBox(d.research_actions, d.header));

  // Obsidian / saved research
  box.appendChild(obsidianBox(d.obsidian, 'concept', d.header.concept_id));
  box.appendChild(addToProjectBox('concept', d.header.concept_id));
  // 概念详情也提供 Export（以 JSON/Markdown 形式带走这个概念的引用集合）
  const cExpHost = h('div', { id: 'export-host' });
  box.appendChild(cExpHost);
  exportBar({ source_type: 'saved_passage', source_id: d.evidence.sample[0]
    || 'passage.S11.unknown.P2253' }, { host: cExpHost, previewHost: cExpHost })
    .then((node) => mount(cExpHost, node));
  box.appendChild(savedBox(d.saved_research));
  box.appendChild(muted(d.note));
  return box;
}

function relationsBox(rel) {
  const card = h('div', { class: 'card', id: 'relations' }, [
    h('h2', {}, [h('span', { text: t('explore.relations') }), ' ', tagOntology('canonical ontology')]),
    h('p', { class: 'muted', text: rel.note }),
  ]);
  const group = (title, rows, klass) => {
    if (!rows.length) return null;
    return h('div', { class: 'rel-group ' + klass }, [
      h('h3', { text: `${title} (${rows.length})` }),   // 卡片内子分组（父级 h2）
      h('ul', { class: 'plain-list' }, rows.map((r) => h('li', { class: 'rel-row' }, [
        h('code', { class: 'rel-pred', text: r.predicate }),
        h('span', { class: 'rel-arrow', text: r.direction === 'out' ? '→' : '←' }),
        h('button', { class: 'link-btn', type: 'button', text: r.other_label,
          onclick: () => go({ view: 'concept', id: r.other_id }) }),
        h('span', { class: 'tag', text: r.review_status || 'unknown' }),
        h('span', { class: 'muted', text: r.ontology_source || '' }),
        r.evidence && r.evidence.note
          ? h('span', { class: 'rel-note', text: r.evidence.note }) : null,
      ]))),
    ]);
  };
  const rev = group('Reviewed', rel.reviewed, 'is-reviewed');
  const cand = group('Candidate (not canonical)', rel.candidate, 'is-candidate');
  if (rev) card.appendChild(rev);
  if (cand) card.appendChild(cand);
  if (!rel.reviewed_n) {
    card.appendChild(notice('No reviewed canonical relation recorded for this concept.',
      rel.candidate_n
        ? `${rel.candidate_n} candidate relation(s) exist in the ontology but are not `
          + 'reviewed, so they are not drawn into the canonical graph.'
        : 'The ontology records no relation for this concept.'));
  }
  return card;
}

function graphBox(g) {
  if (!g) return h('div');
  const card = h('div', { class: 'card', id: 'concept-graph' }, [
    h('h2', {}, [h('span', { text: t('explore.concept-graph-1-hop') }), ' ',
      tagOntology(`reviewed only`) ]),
    h('p', { class: 'muted', text: g.note || '' }),
  ]);
  if (!g.edges.length) {
    card.appendChild(notice(g.empty_note || 'No reviewed edge.',
      g.candidate_edges_n ? `${g.candidate_edges_n} candidate edge(s) exist and are `
        + 'listed below for inspection — they are NOT drawn.' : null));
  } else {
    card.appendChild(svgGraph(g));
  }
  if ((g.candidate_edges || []).length) {
    const rows = g.candidate_edges.map((e) => h('tr', {}, [
      h('td', {}, [h('code', { text: e.predicate })]),
      h('td', { text: `${e.from} → ${e.to}` }),
      h('td', {}, [h('span', { class: 'tag', text: e.review_status || '' })]),
      h('td', { class: 'muted', text: (e.evidence || {}).note || '' }),
      h('td', {}, [h('span', { class: 'tag is-corpus', text: t('explore.not-drawn') })]),
    ]));
    card.appendChild(h('details', { class: 'fold' }, [
      h('summary', { text: `Candidate edges (${g.candidate_edges_n}) — explainable, not drawn` }),
      h('table', { class: 'edge-table' }, [
        h('thead', {}, h('tr', {}, [h('th', { text: t('explore.predicate') }),
          h('th', { text: t('explore.edge') }), h('th', { text: t('explore.status') }),
          h('th', { text: t('explore.evidence-2') }), h('th', { text: t('explore.graph') })])),
        h('tbody', {}, rows)]),
    ]));
  }
  return card;
}

function svgGraph(g) {
  const NS = 'http://www.w3.org/2000/svg';
  const W = 640, H = 260, cx = W / 2, cy = H / 2, r = 90;
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('class', 'mini-graph');
  const others = g.edges.map((e) => (e.from === g.concept_id ? e.to : e.from));
  const uniq = [...new Set(others)];
  const pos = { [g.concept_id]: [cx, cy] };
  uniq.forEach((id, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, uniq.length) - Math.PI / 2;
    pos[id] = [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  });
  for (const e of g.edges) {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) continue;
    const line = document.createElementNS(NS, 'line');
    line.setAttribute('x1', a[0]); line.setAttribute('y1', a[1]);
    line.setAttribute('x2', b[0]); line.setAttribute('y2', b[1]);
    line.setAttribute('class', 'edge');
    svg.appendChild(line);
  }
  for (const [id, p] of Object.entries(pos)) {
    const c = document.createElementNS(NS, 'circle');
    c.setAttribute('cx', p[0]); c.setAttribute('cy', p[1]);
    c.setAttribute('r', id === g.concept_id ? 10 : 6);
    c.setAttribute('class', id === g.concept_id ? 'node is-selected' : 'node');
    svg.appendChild(c);
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', p[0]); t.setAttribute('y', p[1] + (id === g.concept_id ? -16 : 20));
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('class', 'node-label');
    const label = (g.nodes.find((n) => n.id === id) || {}).label || id;
    t.textContent = String(label).slice(0, 22);
    svg.appendChild(t);
  }
  return svg;
}

function attestationBox(a) {
  const card = h('div', { class: 'card', id: 'attestation' }, [
    h('h2', {}, [h('span', { text: t('explore.corpus-attestation') }), ' ', tagCorpus(a.source)]),
    h('p', { class: 'muted', text: `${a.label} · ${a.mode}` }),
    h('table', { class: 'data-table' }, [
      h('thead', {}, h('tr', {}, [h('th', { text: t('explore.written-form') }),
        h('th', { text: t('explore.source-2') }), h('th', { text: t('explore.passages') })])),
      h('tbody', {}, (a.items || []).map((r) => h('tr', { class: r.zero ? 'zero-row' : '' }, [
        h('td', { text: r.form }),
        h('td', { class: 'muted', text: r.source || '' }),
        h('td', { text: r.zero ? 'Zero corpus attestation' : String(r.hits) }),
      ]))),
    ]),
  ]);
  return card;
}

function distributionBox(dist) {
  if (!dist || !dist.total) return h('div');
  const max = Math.max(...dist.seminars.map((s) => s.passages), 1);
  return h('div', { class: 'card', id: 'distribution' }, [
    h('h2', {}, [h('span', { text: t('explore.seminar-distribution') }), ' ', tagCorpus(dist.mode)]),
    h('p', { class: 'muted', text: dist.label || '' }),
    h('ul', { class: 'bars' }, dist.seminars.map((s) => h('li', { class: 'bar-row' }, [
      h('span', { class: 'bar-label', text: s.seminar.replace('seminar.', '') }),
      h('span', { class: 'bar', style: `width:${Math.round(100 * s.passages / max)}%` }),
      h('span', { class: 'bar-value', text: String(s.passages) }),
    ]))),
  ]);
}

function diachronicBox(d) {
  if (!d || !d.points.length) return h('div');
  return h('div', { class: 'card', id: 'diachronic' }, [
    h('h2', {}, [h('span', { text: t('explore.diachronic-view') }), ' ', tagCorpus(d.mode)]),
    h('p', { class: 'muted', text: d.note }),
    h('table', { class: 'data-table' }, [
      h('thead', {}, h('tr', {}, [h('th', { text: t('evidence-inspector.year') }), h('th', { text: t('evidence-inspector.seminar') }),
        h('th', { text: t('explore.passages') })])),
      h('tbody', {}, d.points.map((p) => h('tr', {}, [
        h('td', { text: p.year ? String(p.year) : 'unknown' }),
        h('td', {}, [passageLinkSeminar(p.seminar)]),
        h('td', { text: String(p.passages) }),
      ]))),
    ]),
    h('div', { class: 'action-bar' }, [
      h('button', { class: 'btn btn-ghost', type: 'button', id: 'diachronic-research',
        text: t('explore.research-diachronically'),
        onclick: () => prefill(`请给出该概念在语料各时期的表述变化，并附各阶段语料依据。`) }),
    ]),
  ]);
}

function researchActionsBox(actions, header) {
  const bar = h('div', { class: 'action-bar', id: 'research-actions' });
  for (const a of (actions || [])) {
    bar.appendChild(h('button', { class: 'btn btn-ghost', type: 'button',
      dataset: { action: a.id }, text: a.label,
      onclick: () => prefill(buildQuestion(a, header)) }));
  }
  return h('div', { class: 'card' }, [
    h('h2', { text: t('explore.research-from-this-concept') }),
    h('p', { class: 'muted', text:
      t('explore.these-buttons-only-pre-fill-a-research-request-e--full') }),
    bar]);
}

function buildQuestion(a, header) {
  const label = header.preferred_label || header.concept_id;
  if (a.id === 'research') return `请给出 ${label} 的工作定义、关键区分与语料证据。`;
  if (a.id === 'compare') return `请把 ${label} 与另一个概念做区分：需要哪些关键分野与语料依据？`;
  if (a.id === 'diachronic') return `${label} 在语料各时期（按研讨班）如何表述？请给各阶段证据。`;
  if (a.id === 'translation') return `中文语料里 ${label} 有哪些译法？这些译名差异意味着什么？`;
  return (a.request && a.request.question) || label;
}

function prefill(question) {
  if (CTX.onPrefill) CTX.onPrefill(question);
  else go({ q: question });
}

function passageLink(pid) {
  return h('button', { class: 'cite', type: 'button', text: pid,
    onclick: () => go({ view: 'passage', id: pid }) });
}
function passageLinkSeminar(sid) {
  return h('button', { class: 'cite', type: 'button', text: sid,
    onclick: () => go({ view: 'seminar', id: sid }) });
}

/** §46：Explorer → Project（保存 stable id；不复制 canonical 内容）。 */
function addToProjectBox(entityType, entityId) {
  const kindMap = { concept: 'concept', passage: 'passage', seminar: 'seminar',
    term: 'term' };
  const kind = kindMap[entityType] || entityType;
  const status = h('span', { class: 'muted', id: 'add-to-project-status' });
  return h('div', { class: 'card', id: 'add-to-project' }, [
    h('h2', { text: t('explore.add-to-project') }),
    h('p', { class: 'muted', text:
      t('explore.saves-the-stable-id-into-a-user-workspace-projec') }),
    h('div', { class: 'action-bar' }, [
      h('button', { class: 'btn btn-ghost', type: 'button', id: 'add-to-project-btn',
        text: t('explore.add-to-project'), onclick: async (e) => {
          const box = await addToProjectDialog({ kind, id: entityId });
          e.target.parentElement.appendChild(box);
        } }),
      status,
    ]),
  ]);
}

function obsidianBox(ob, entityType, entityId) {
  const card = h('div', { class: 'card', id: 'obsidian-action' }, [
    h('h2', { text: 'Obsidian' }),
  ]);
  if (!ob || !ob.available) {
    card.appendChild(muted('Obsidian adapter unavailable: ' + ((ob || {}).reason || '')));
    return card;
  }
  card.appendChild(kv([['Note', ob.note], ['Managed by adapter', ob.managed ? 'yes' : 'no']]));
  const bar = h('div', { class: 'action-bar' });
  if (ob.exists && ob.obsidian_uri) {
    bar.appendChild(h('a', { class: 'link-btn', href: ob.obsidian_uri, text: t('explore.open-in-obsidian') }));
  }
  bar.appendChild(h('button', { class: 'btn btn-ghost', type: 'button',
    id: 'create-note-btn', text: ob.exists ? 'Create a new snapshot note' : 'Create Reference Note',
    onclick: async (e) => {
      e.target.disabled = true;
      const res = await api.exploreCreateNote(entityType, entityId);
      const st = h('span', { class: 'muted' });
      e.target.parentElement.appendChild(st);
      if (res.ok) {
        st.textContent = `Saved: ${res.note || ''}`;
        if (res.obsidian_uri) {
          e.target.parentElement.appendChild(h('a', { class: 'link-btn',
            href: res.obsidian_uri, text: t('explore.open-in-obsidian') }));
        }
      } else { st.textContent = 'Save failed: ' + (res.detail || res.error || ''); }
    } }));
  card.appendChild(bar);
  card.appendChild(muted(ob.note_policy || ''));
  return card;
}

function savedBox(saved) {
  if (!saved) return h('div');
  const card = h('div', { class: 'card', id: 'saved-research' }, [
    h('h2', { text: `Saved research (${saved.total})` }),
    h('p', { class: 'muted', text: t('explore.source') + saved.source }),
  ]);
  if (!saved.items.length) {
    card.appendChild(muted('No saved research links to this entity yet.'));
  } else {
    const rows = saved.items.map((it) => h('li', {}, [
      h('span', { text: `${it.research_id} · ${it.answer_state || ''} · `
        + `${(it.saved_at || '').slice(0, 16)}` }),
      h('span', { class: 'muted', text: ' ' + (it.research_note || '') }),
    ]));
    card.appendChild(h('ul', { class: 'plain-list' }, rows));
  }
  return card;
}

// ─────────────────────────────────────────────────────────── 段落检索
async function renderPassages(params) {
  const data = await api.explore('passages', {
    query: params.query, seminar: params.seminar, language: params.language,
    source_layer: params.layer, provenance: params.provenance,
    formalism: params.formalism, concept: params.concept, cursor: params.cursor,
    limit: params.limit || 20,
  });
  const box = h('section', { class: 'explorer-view', id: 'explorer-passages' });
  box.appendChild(h('div', { class: 'explorer-head' }, [
    h('h1', { class: 'explorer-title', text: t('bibliography.passages') }),
    h('span', { class: 'tag', text: data.label || '' }),
  ]));
  if (data.dense_banner) {
    box.appendChild(h('div', { class: 'banner', id: 'dense-banner' }, [
      h('strong', { text: t('explore.dense-semantic-retrieval-unavailable') }),
      h('span', { text: t('explore.lexical-retrieval-active') })]));
  }
  box.appendChild(passageFilterForm(params, data.filters_spec));

  if (data.zero_note) {
    // P5D-005 §10：零结果也要能教用户（原来的英文硬编码说明已被替换）
    box.appendChild(teachEmpty(t('search.empty.title'), t('search.empty.body'),
      [[t('search.empty.how'), '/help/explore'],
       [t('search.empty.try-research'), '/research']],
      { id: 'explore-zero', actionIds: ['explore-zero-help', 'explore-zero-research'] }));
  }
  const list = h('ul', { class: 'passage-list' });
  for (const it of (data.items || [])) list.appendChild(passageRow(it));
  box.appendChild(list);
  box.appendChild(pager(data.page, (c) => go({ ...params, cursor: c })));
  return box;
}

function selectField(id, label, options, value, onChange) {
  const sel = h('select', { class: 'explorer-select', id }, [
    h('option', { value: '', text: label }),
    ...options.map((o) => h('option', { value: o.id, text: o.label || o.id,
      selected: value === o.id ? 'selected' : null })),
  ]);
  if (onChange) sel.addEventListener('change', () => onChange(sel.value));
  return h('label', { class: 'explorer-field' }, [h('span', { text: label }), sel]);
}

function passageFilterForm(params, spec) {
  const send = (patch) => {
    const next = { view: 'passages' };
    for (const [k, v] of Object.entries({ ...params, ...patch })) {
      if (['view', 'cursor', 'limit'].includes(k)) continue;
      if (v) next[k] = v;
    }
    go(next);
  };
  const q = h('input', { class: 'explorer-input', id: 'passage-query', type: 'search',
    value: params.query || '', placeholder: t('explore.query-exact-substring-over-the-corpus') });
  return h('form', { class: 'explorer-form is-grid', onsubmit: (e) => {
    e.preventDefault(); send({ query: q.value, cursor: '' });
  } }, [
    h('label', { class: 'explorer-field' }, [h('span', { text: t('explore.query') }), q]),
    selectField('f-seminar', 'seminar', spec.seminars || [], params.seminar,
      (v) => send({ seminar: v, cursor: '' })),
    selectField('f-language', 'language', spec.languages || [], params.language,
      (v) => send({ language: v, cursor: '' })),
    selectField('f-layer', 'source layer', spec.source_layers || [], params.layer,
      (v) => send({ layer: v, cursor: '' })),
    selectField('f-prov', 'provenance', spec.provenance || [], params.provenance,
      (v) => send({ provenance: v, cursor: '' })),
    selectField('f-formalism', 'formalism (regex-detected)',
      (spec.formalism_patterns || []).map((p) => ({ id: p, label: p })),
      params.formalism, (v) => send({ formalism: v, cursor: '' })),
    h('div', { class: 'explorer-field' }, [
      h('button', { class: 'btn', type: 'submit', text: t('explore.browse-corpus') }),
      linkBtn('reset', () => go({ view: 'passages' }))]),
  ]);
}

function passageRow(it) {
  const li = h('li', { class: 'passage-item', dataset: { passage: it.passage_id } }, [
    h('div', { class: 'pi-head' }, [
      h('button', { class: 'cite', type: 'button', text: it.passage_id,
        onclick: () => go({ view: 'passage', id: it.passage_id }) }),
      h('span', { class: 'tag', text: it.language }),
      h('span', { class: 'tag', text: it.source_layer }),
      h('span', { class: 'tag', text: it.text_role || '' }),
      it.provenance_status === 'SOURCE_TRACE_INCOMPLETE'
        ? h('span', { class: 'tag is-warn', text: t('explore.trace-incomplete') }) : null,
    ]),
    h('p', { class: 'pi-snippet', text: it.snippet || '' }),
    h('div', { class: 'pi-meta muted', text:
      `${it.seminar} · ${it.session} · lesson ${it.lesson === null ? '—' : it.lesson}` }),
  ]);
  return li;
}

// ─────────────────────────────────────────────────────────── 段落详情
async function renderPassage(params) {
  const d = await api.explore('passage', { id: params.id, before: params.before || 2,
    after: params.after || 2 });
  if (d.kind === 'error') return errorBox(d);
  const p = d.passage;
  const box = h('section', { class: 'explorer-view is-reading', id: 'explorer-passage' });

  // §13：原文优先 —— 正文先出现，占视觉中心；metadata 一律在其后。
  box.appendChild(h('div', { class: 'passage-reader' }, [
    h('div', { class: 'pr-label', text:
      `${(p.passage_id || '').split('.')[1]} · ${(p.passage_id || '').split('.').pop()}` }),
    p.provenance_status === 'SOURCE_TRACE_INCOMPLETE'
      ? h('div', { class: 'trace-warn', id: 'trace-incomplete',
          text: d.trace_incomplete_note || 'SOURCE_TRACE_INCOMPLETE' }) : null,
    h('blockquote', { class: 'pr-text', id: 'passage-text', text: p.text || '' }),
    h('div', { class: 'pr-actions' }, [
      h('button', { class: 'btn btn-ghost', type: 'button', id: 'save-passage-btn',
        text: t('explore.save-passage-to-obsidian'),
        onclick: async (e) => {
          e.target.disabled = true;
          const res = await api.obsidianSavePassage(p.passage_id);
          e.target.disabled = false;
          const st = h('span', { class: 'muted' });
          e.target.parentElement.appendChild(st);
          st.textContent = res.ok ? `Saved (${res.status}) ${res.note || ''}`
            : 'Save failed: ' + (res.detail || res.error || '');
        } }),
      h('button', { class: 'btn btn-ghost', type: 'button', id: 'copy-citation',
        text: t('explore.copy-citation'),
        onclick: (e) => copyText(d.citation.full, e.target.nextElementSibling) }),
      h('span', { class: 'muted', id: 'copy-status' }),
      h('button', { class: 'btn btn-ghost', type: 'button', id: 'open-context',
        text: t('explore.open-context'),
        onclick: () => openContextPanel(p.passage_id) }),
      h('button', { class: 'btn btn-ghost', type: 'button', id: 'research-passage',
        text: t('explore.research-this-passage'),
        onclick: () => prefill(d.research_actions[0].request.question) }),
    ]),
  ]));

  box.appendChild(contextBox(d, params));
  box.appendChild(kv([
    ['Passage id', p.passage_id], ['Seminar', p.seminar], ['Session', p.session],
    ['Lesson', p.lesson === null ? '—' : p.lesson], [t('topbar.language'), p.language],
    ['Source layer', p.source_layer], ['Text role', p.text_role], [t('explore.field-status'), p.status],
    [t('bibliography.provenance'), p.provenance_status], [t('explore.field-witness'), p.witness],
    ['Canonical', p.canonical ? 'yes' : 'no'], ['Review status', p.review_status],
    ['Session date', p.session_date ? `${p.session_date} (${p.session_date_precision})` : null],
  ]));

  box.appendChild(traceBox(d.trace));
  box.appendChild(witnessBox(d.witnesses));
  box.appendChild(languageBox(d.languages));
  box.appendChild(citationBox(d.citation));
  // §52/§53：Citation 菜单 + Export Passage（citation 一律由后端 formatter 生成）
  const citHost = h('div', { id: 'citation-menu-host' });
  box.appendChild(citHost);
  citationMenu(p.passage_id).then((node) => mount(citHost, node));
  const expHost = h('div', { id: 'export-host' });
  box.appendChild(expHost);
  exportBar({ source_type: 'saved_passage', source_id: p.passage_id,
    include_context: 2 }, { host: expHost, previewHost: expHost })
    .then((node) => mount(expHost, node));
  box.appendChild(obsidianBox(d.obsidian, 'passage', p.passage_id));
  box.appendChild(addToProjectBox('passage', p.passage_id));
  box.appendChild(savedBox(d.saved_research));
  return box;
}

function contextBox(d, params) {
  const ctx = d.context || { items: [] };
  const card = h('div', { class: 'card', id: 'context' }, [
    h('h2', {}, [h('span', { text: `Context (±${ctx.before || 0}/${ctx.after || 0})` }),
      ' ', tagCorpus('corpus order')]),
    h('p', { class: 'muted', text:
      `Session ${ctx.session || '—'} · ${ctx.session_total || 0} passages · reading in `
      + 'corpus order (never the whole corpus at once).' }),
  ]);
  const items = ctx.items || [];
  const at = ctx.target_index === null || ctx.target_index === undefined
    ? -1 : ctx.target_index;
  const step = (delta) => {
    const i = at + delta;
    if (i < 0 || i >= items.length) return;
    go({ view: 'passage', id: items[i].passage_id, before: ctx.before, after: ctx.after });
  };
  const bar = h('div', { class: 'action-bar' }, [
    h('button', { class: 'btn btn-ghost', type: 'button', id: 'ctx-prev', text: t('explore.previous'),
      disabled: at <= 0 ? 'disabled' : null, onclick: () => step(-1) }),
    h('button', { class: 'btn btn-ghost', type: 'button', id: 'ctx-next', text: t('explore.next'),
      disabled: (at < 0 || at >= items.length - 1) ? 'disabled' : null,
      onclick: () => step(1) }),
  ]);
  for (const n of [2, 5, 10]) {
    bar.appendChild(h('button', { class: 'btn btn-ghost', type: 'button',
      text: `±${n}`, onclick: () => go({ view: 'passage', id: d.passage.passage_id,
        before: n, after: n }) }));
  }
  bar.appendChild(h('button', { class: 'btn btn-ghost', type: 'button', id: 'open-session',
    text: t('explore.open-session'), onclick: () => go({ view: 'session', id: ctx.session }) }));
  card.appendChild(bar);
  card.appendChild(h('ol', { class: 'ctx-list', start: 1 }, items.map((x) => h('li', {
    class: 'ctx-item' + (x.is_target ? ' is-target' : ''),
    dataset: { passage: x.passage_id } }, [
    h('button', { class: 'ctx-id', type: 'button', text: x.passage_id,
      onclick: () => go({ view: 'passage', id: x.passage_id, before: ctx.before, after: ctx.after }) }),
    h('span', { class: 'ctx-text', text: (x.text || '').slice(0, 400) }),
  ]))));
  return card;
}

function traceBox(tr) {
  if (!tr) return h('div');
  const card = h('div', { class: 'card', id: 'source-trace' }, [
    h('h2', {}, [h('span', { text: t('explore.trace-source') }), ' ', tagOntology('canonical store')]),
    h('p', { class: 'muted', text:
      `trace status: ${tr.trace_status || '—'}${tr.complete ? '' : ' · incomplete'}` }),
  ]);
  card.appendChild(h('ol', { class: 'chain' }, (tr.chain || []).map((s) => h('li', {
    class: 'chain-step' + (s.present ? '' : ' is-broken') }, [
    h('span', { class: 'chain-step-name', text: s.step }),
    h('span', { class: 'chain-step-id', text: s.id || '(none recorded)' }),
    h('span', { class: 'muted', text: s.label || '' }),
    s.present ? null : h('span', { class: 'tag is-warn', text: t('explore.break') }),
  ]))));
  if ((tr.broken_at || []).length || (tr.trace_missing || []).length) {
    card.appendChild(notice('Source trace incomplete',
      `Break: ${(tr.broken_at || []).join(', ') || '—'} · missing: `
      + `${(tr.trace_missing || []).join(', ') || '—'}. Nothing is filled in to hide the gap.`,
      'is-warn'));
  }
  if (tr.witness_note) card.appendChild(muted(tr.witness_note));
  return card;
}

function witnessBox(w) {
  if (!w) return h('div');
  const card = h('div', { class: 'card', id: 'witnesses' }, [
    h('h2', {}, [h('span', { text: t('bibliography.witnesses') }), ' ', tagOntology('passage store')]),
    h('p', { class: 'muted', text: w.note || '' }),
  ]);
  card.appendChild(h('table', { class: 'data-table' }, [
    h('thead', {}, h('tr', {}, [h('th', { text: t('evidence-inspector.witness') }), h('th', { text: t('explore.kind') }),
      h('th', { text: t('evidence-inspector.language') }), h('th', { text: t('explore.link-role') }),
      h('th', { text: t('explore.edition') })])),
    h('tbody', {}, (w.linked || []).map((x) => h('tr', {}, [
      h('td', { text: x.witness_id }), h('td', { text: x.witness_kind || '' }),
      h('td', { text: x.language || '' }), h('td', { text: x.link_role || '' }),
      h('td', { class: 'muted', text: x.edition || '' })]))),
  ]));
  if ((w.unlinked_witnesses || []).length) {
    card.appendChild(h('details', { class: 'fold', open: '' }, [
      h('summary', { text: `Other witnesses in the corpus (${w.unlinked_witnesses.length}) — not linked to this passage` }),
      h('table', { class: 'data-table' }, [
        h('thead', {}, h('tr', {}, [h('th', { text: t('evidence-inspector.witness') }), h('th', { text: t('explore.kind') }),
          h('th', { text: t('evidence-inspector.language') }), h('th', { text: t('explore.link-state') })])),
        h('tbody', {}, w.unlinked_witnesses.map((x) => h('tr', {}, [
          h('td', { text: x.witness_id }), h('td', { text: x.witness_kind || '' }),
          h('td', { text: x.language || '' }),
          h('td', {}, [h('span', { class: 'tag is-warn', text: x.passage_link_state })])]))),
      ]),
      muted('A witness is not a translation, and neither is the canonical passage identity.'),
    ]));
  }
  return card;
}

function languageBox(l) {
  if (!l) return h('div');
  const card = h('div', { class: 'card', id: 'languages' }, [
    h('h2', { text: t('explore.language-translation') }),
    kv([[t('topbar.language'), l.language],
        ['Languages in this session', (l.available_languages || []).join(', ')]]),
    h('p', { class: 'muted', text: l.policy || '' }),
  ]);
  if (!l.aligned_available) {
    card.appendChild(notice('No aligned realization available.', l.note, 'is-warn'));
  } else {
    card.appendChild(h('ul', { class: 'plain-list' }, l.aligned.map((a) => h('li', {
      text: JSON.stringify(a) }))));
  }
  return card;
}

function citationBox(c) {
  const card = h('div', { class: 'card', id: 'citation' }, [
    h('h2', { text: t('explore.copy-citation-2') }),
    h('p', { class: 'cite-short', id: 'citation-short', text: c.short }),
    h('pre', { class: 'raw', id: 'citation-full', text: c.full }),
    muted(c.note || ''),
  ]);
  const bar = h('div', { class: 'action-bar' }, [
    h('button', { class: 'btn btn-ghost', type: 'button', text: t('explore.copy-short'),
      onclick: (e) => copyText(c.short, e.target.nextElementSibling) }),
    h('span', { class: 'muted' }),
    h('button', { class: 'btn btn-ghost', type: 'button', text: t('explore.copy-full-provenance'),
      onclick: (e) => copyText(c.full, e.target.nextElementSibling) }),
    h('span', { class: 'muted' }),
    h('button', { class: 'btn btn-ghost', type: 'button', text: t('explore.copy-passage-id'),
      onclick: (e) => copyText(c.passage_id, e.target.nextElementSibling) }),
    h('span', { class: 'muted' }),
  ]);
  card.appendChild(bar);
  return card;
}

async function openContextPanel(passageId) {
  const el = document.getElementById('inspector');
  const body = document.getElementById('inspector-body');
  el.hidden = false;
  mount(body, h('p', { class: 'muted', text: t('explore.loading-context') }));
  const d = await api.explore('passage', { id: passageId, before: 5, after: 5 });
  mount(body, h('div', {}, [
    h('h2', { text: `Context · ${passageId}` }),
    h('ol', { class: 'ctx-list' }, (d.context.items || []).map((x) => h('li', {
      class: 'ctx-item' + (x.is_target ? ' is-target' : '') }, [
      h('span', { class: 'ctx-id', text: x.passage_id }),
      h('span', { class: 'ctx-text', text: (x.text || '').slice(0, 400) })]))),
  ]));
}

// ─────────────────────────────────────────────────────────── 研讨班
async function renderSeminars() {
  const data = await api.explore('seminars', { limit: 50 });
  const box = h('section', { class: 'explorer-view', id: 'explorer-seminars' });
  box.appendChild(h('div', { class: 'explorer-head' }, [
    h('h1', { class: 'explorer-title', text: t('bibliography.seminars') }),
    h('span', { class: 'tag', text: `${data.total} seminars` })]));
  box.appendChild(h('p', { class: 'muted', text: data.title_policy }));
  box.appendChild(h('table', { class: 'data-table' }, [
    h('thead', {}, h('tr', {}, [h('th', { text: t('evidence-inspector.seminar') }), h('th', { text: t('explore.title') }),
      h('th', { text: t('explore.years') }), h('th', { text: t('explore.sessions') }),
      h('th', { text: t('explore.passages') }), h('th', { text: t('explore.languages') })])),
    h('tbody', {}, data.items.map((s) => h('tr', {}, [
      h('td', {}, [h('button', { class: 'cite', type: 'button', text: s.seminar_id,
        onclick: () => go({ view: 'seminar', id: s.seminar_id }) })]),
      h('td', { text: s.title || '—' }),
      h('td', { text: [s.year_from, s.year_to].filter(Boolean).join('–') }),
      h('td', { text: String(s.sessions_n) }),
      h('td', { text: String(s.passages_n) }),
      h('td', { class: 'muted', text: (s.languages || []).map((x) => x[0]).join(', ') }),
    ]))),
  ]));
  return box;
}

async function renderSeminar(params) {
  const d = await api.explore('seminar', { id: params.id });
  if (d.kind === 'error') return errorBox(d);
  const m = d.metadata;
  const box = h('section', { class: 'explorer-view', id: 'explorer-seminar' });
  box.appendChild(h('div', { class: 'explorer-head' }, [
    h('h1', { class: 'explorer-title', id: 'seminar-title',
      text: m.title || m.seminar_id }),
    h('span', { class: 'row-id', text: m.seminar_id }),
    m.title_missing ? h('span', { class: 'tag is-warn', text: t('explore.no-canonical-title') }) : null,
  ]));
  box.appendChild(kv([
    ['Roman', m.roman], ['French title', m.title_fr],
    ['Years', [m.year_from, m.year_to].filter(Boolean).join('–')],
    ['Lessons', m.lessons],
    ['Languages', (m.languages || []).map((x) => `${x[0]} (${x[1]})`).join(', ')],
    [t('bibliography.provenance'), (m.provenance || []).map((x) => `${x[0]} (${x[1]})`).join(', ')],
  ]));

  // Sessions
  const sBox = h('div', { class: 'card', id: 'sessions' }, [
    h('h2', { text: `Sessions (${d.sessions.length})` }),
    h('p', { class: 'muted', text: t('explore.sessions-read-in-lesson-order-a-session-without--full') })]);
  sBox.appendChild(h('ul', { class: 'plain-list' }, d.sessions.map((s) => h('li', {}, [
    h('button', { class: 'link-btn', type: 'button',
      text: `${s.lesson === null ? '—' : 'L' + String(s.lesson).padStart(2, '0')} · ${s.session_id}`,
      onclick: () => go({ view: 'session', id: s.session_id }) }),
    h('span', { class: 'tag', text: `${s.passage_count || 0} passages` }),
    s.lesson_missing ? h('span', { class: 'tag is-warn', text: t('explore.no-lesson-number') }) : null,
  ]))));
  box.appendChild(sBox);

  // Concepts（两种计数分开）
  const c = d.concepts;
  box.appendChild(h('div', { class: 'card', id: 'seminar-concepts' }, [
    h('h2', {}, [h('span', { text: t('explore.concepts') }), ' ', tagOntology(c.mode)]),
    h('p', { class: 'muted', text: c.label || '' }),
    (c.items || []).length
      ? h('ul', { class: 'plain-list' }, c.items.map((x) => h('li', {}, [
          h('button', { class: 'link-btn', type: 'button', text: x.preferred_label,
            onclick: () => go({ view: 'concept', id: x.concept_id }) }),
          h('span', { class: 'tag', text: `${x.ontology_evidence_in_seminar_n} ontology-recorded` })])))
      : muted('The ontology records no evidence passages in this seminar.'),
    h('h3', {}, [h('span', { text: t('explore.corpus-occurrence') }), ' ', tagCorpus(c.attestation.mode)]),
    h('p', { class: 'muted', text: c.attestation.label }),
    h('ul', { class: 'plain-list' }, (c.attestation.items || []).map((x) => h('li', {}, [
      h('span', { text: x.preferred_label }),
      h('span', { class: 'tag is-corpus', text: `${x.passages} passages` })]))),
  ]));

  // Passages
  box.appendChild(h('div', { class: 'card', id: 'seminar-passages' }, [
    h('h2', { text: `Passages (first ${d.passages.length})` }),
    h('ul', { class: 'passage-list' }, d.passages.map((it) => passageRow(it))),
    h('div', { class: 'action-bar' }, [
      h('button', { class: 'btn btn-ghost', type: 'button', text: t('explore.browse-all-passages'),
        onclick: () => go({ view: 'passages', seminar: m.seminar_id }) })]),
  ]));

  // Formalisms
  box.appendChild(h('div', { class: 'card', id: 'formalisms' }, [
    h('h2', {}, [h('span', { text: t('explore.formalism-index') }), ' ', tagCorpus(d.formalisms.method)]),
    h('p', { class: 'muted', text: t('explore.detected-by-deterministic-pattern-match-over-rea--full--full') }),
    h('table', { class: 'data-table' }, [
      h('thead', {}, h('tr', {}, [h('th', { text: t('explore.form') }), h('th', { text: t('explore.passages') }),
        h('th', { text: t('explore.pattern') }), h('th', { text: t('explore.detected-by') })])),
      h('tbody', {}, (d.formalisms.items || []).map((f) => h('tr', {}, [
        h('td', { text: f.formalism }),
        h('td', {}, [h('button', { class: 'link-btn', type: 'button', text: String(f.passages),
          onclick: () => go({ view: 'passages', seminar: m.seminar_id, formalism: f.formalism }) })]),
        h('td', {}, [h('code', { text: f.pattern })]),
        h('td', { class: 'muted', text: f.detected_by || '' }),
      ]))),
    ]),
  ]));

  // Cases / persons（如实说明缺什么）
  const cp = d.cases_persons;
  box.appendChild(h('div', { class: 'card', id: 'cases-persons' }, [
    h('h2', { text: t('explore.cases-persons') }),
    cp.available
      ? h('ul', { class: 'plain-list' }, cp.items.map((x) => h('li', { text: x.label || x.id })))
      : muted(cp.note),
  ]));

  box.appendChild(h('div', { class: 'action-bar' }, [
    h('button', { class: 'btn btn-ghost', type: 'button', id: 'ask-seminar',
      text: t('explore.ask-about-this-seminar'),
      onclick: () => prefill(`在 ${m.seminar_id}（${m.title || ''}）中，某个主题是如何被论述的？`
        + '请给出来源层可核的段落。') })]));
  box.appendChild(obsidianBox(d.obsidian, 'seminar', m.seminar_id));
  box.appendChild(addToProjectBox('seminar', m.seminar_id));
  box.appendChild(savedBox(d.saved_research));
  return box;
}

// ─────────────────────────────────────────────────────────── 阅读模式
async function renderSession(params) {
  const d = await api.explore('session', { id: params.id, cursor: params.cursor,
    limit: params.limit || 10 });
  const box = h('section', { class: 'explorer-view is-reading-mode', id: 'explorer-session' });
  box.appendChild(h('div', { class: 'reading-head' }, [
    h('h1', { class: 'explorer-title', text: `Reading mode · ${params.id}` }),
    h('span', { class: 'tag', text: `page of ${d.page.total} passages` }),
    linkBtn('← back to seminar', () => go({ view: 'seminar',
      id: (params.id.split('.').slice(0, 2).join('.')) })),
  ]));
  box.appendChild(h('p', { class: 'muted', text:
    t('explore.continuous-reading-in-corpus-order-save-passage--full') }));
  for (const it of (d.items || [])) {
    box.appendChild(h('article', { class: 'reading-item', dataset: { passage: it.passage_id } }, [
      h('div', { class: 'ri-head' }, [
        h('span', { class: 'ri-id', text: it.passage_id }),
        h('span', { class: 'tag', text: it.language }),
        h('span', { class: 'tag', text: it.source_layer }),
        it.provenance_status === 'SOURCE_TRACE_INCOMPLETE'
          ? h('span', { class: 'tag is-warn', text: t('explore.trace-incomplete') }) : null,
      ]),
      h('blockquote', { class: 'ri-text', text: it.snippet || '' }),
      h('div', { class: 'ri-actions' }, [
        h('button', { class: 'btn btn-ghost', type: 'button', text: t('evidence-inspector.save-passage'),
          onclick: async (e) => {
            e.target.disabled = true;
            const res = await api.obsidianSavePassage(it.passage_id);
            e.target.disabled = false;
            e.target.textContent = res.ok ? t('nav.saved') : t('research.save-failed');
          } }),
        h('button', { class: 'btn btn-ghost', type: 'button', text: t('explore.copy-citation'),
          onclick: (e) => copyText(`${it.passage_id} — ${it.seminar} · ${it.session} · `
            + `${it.source_layer} · ${it.provenance_status}`, e.target.nextElementSibling) }),
        h('span', { class: 'muted' }),
        h('button', { class: 'btn btn-ghost', type: 'button', text: t('explore.open-context'),
          onclick: () => go({ view: 'passage', id: it.passage_id }) }),
      ]),
    ]));
  }
  box.appendChild(pager(d.page, (c) => go({ view: 'session', id: params.id, cursor: c })));
  return box;
}

// ─────────────────────────────────────────────────────────── 术语
async function renderTerminology(params) {
  const data = await api.explore('terminology', { query: params.query,
    cursor: params.cursor, limit: 25 });
  const box = h('section', { class: 'explorer-view', id: 'explorer-terminology' });
  box.appendChild(h('div', { class: 'explorer-head' }, [
    h('h1', { class: 'explorer-title', text: t('explore.terminology') }),
    h('span', { class: 'tag', text: `${data.total} forms` })]));
  box.appendChild(h('p', { class: 'muted', text: data.zones_note }));
  const q = h('input', { class: 'explorer-input', id: 'term-search', type: 'search',
    value: params.query || '', placeholder: t('explore.term-fr-zh-en') });
  box.appendChild(h('form', { class: 'explorer-form', onsubmit: (e) => {
    e.preventDefault(); go({ view: 'terminology', query: q.value }); } },
    [q, h('button', { class: 'btn', type: 'submit', text: t('bibliography.search') }),
      linkBtn('Réel / réalité control', () => go({ view: 'term', control: 'reel_realite' }))]));
  box.appendChild(h('table', { class: 'data-table' }, [
    h('thead', {}, h('tr', {}, [h('th', { text: t('explore.form') }), h('th', { text: t('explore.entity') }),
      h('th', { text: t('explore.layer') }), h('th', { text: t('explore.mapping-2') })])),
    h('tbody', {}, data.items.map((r) => h('tr', {}, [
      h('td', {}, [h('button', { class: 'cite', type: 'button', text: r.term,
        onclick: () => go({ view: 'term', term: r.term }) })]),
      h('td', { class: 'muted', text: r.entity_id }),
      h('td', {}, [h('span', { class: 'tag ' + (r.layer === 'ontology'
        ? 'is-ontology' : 'is-catalog'), text: r.layer })]),
      h('td', {}, [h('span', { class: 'tag', text: r.has_reviewed_mapping
        ? 'reviewed mapping' : 'no reviewed mapping' })]),
    ]))),
  ]));
  box.appendChild(pager(data.page, (c) => go({ view: 'terminology', query: params.query,
    cursor: c })));
  return box;
}

async function renderTerm(params) {
  if (params.control === 'reel_realite') return renderReelRealite();
  const d = await api.explore('term', { term: params.term });
  if (d.kind === 'error') return errorBox(d);
  const box = h('section', { class: 'explorer-view', id: 'explorer-term' });
  box.appendChild(h('div', { class: 'explorer-head' }, [
    h('h1', { class: 'explorer-title', id: 'term-title', text: d.query }),
    h('span', { class: 'tag', text: `${d.entities.length} matching entities` })]));
  if (d.ambiguous) {
    box.appendChild(notice('This written form matches more than one entity.',
      'They are listed separately and are not merged: alias collapse is refused.'));
  }
  box.appendChild(h('div', { class: 'card' }, [
    h('h2', { text: t('explore.entities') }),
    h('ul', { class: 'plain-list' }, d.entities.map((e) => h('li', {}, [
      h('button', { class: 'link-btn', type: 'button', text: e.preferred_label || e.concept_id,
        onclick: () => go({ view: 'concept', id: e.concept_id }) }),
      h('span', { class: 'row-id', text: e.concept_id }),
      h('span', { class: 'tag', text: e.match_kind }),
      h('span', { class: 'tag', text: e.review_status || '' })]))),
  ]));
  box.appendChild(mappingZone(d));
  box.appendChild(attestationZone(d));
  box.appendChild(interpretationZone(d));
  if ((d.distinct_from || []).length) {
    box.appendChild(h('div', { class: 'card', id: 'distinct-from' }, [
      h('h2', {}, [h('span', { text: t('explore.distinctions-recorded-in-the-ontology') }), ' ',
        tagOntology('review_status shown')]),
      h('ul', { class: 'plain-list' }, d.distinct_from.map((x) => h('li', {}, [
        h('code', { text: x.predicate }),
        h('span', { text: ` ${x.subject} → ${x.object}` }),
        h('span', { class: 'tag', text: x.review_status || '' }),
        x.note ? h('span', { class: 'rel-note', text: x.note }) : null]))),
    ]));
  }
  box.appendChild(addToProjectBox('term', d.query));
  box.appendChild(muted(d.no_alias_collapse_note));
  return box;
}

function mappingZone(d) {
  const m = d.mapping;
  const card = h('div', { class: 'card zone-mapping', id: 'zone-mapping' }, [
    h('h2', {}, [h('span', { text: t('explore.mapping') }), ' ', tagOntology(m.source)]),
    h('p', { class: 'muted', text: m.warning }),
  ]);
  card.appendChild(h('table', { class: 'data-table' }, [
    h('thead', {}, h('tr', {}, [h('th', { text: t('explore.form') }), h('th', { text: t('explore.entity') }),
      h('th', { text: t('explore.mapping-record') }), h('th', { text: t('explore.status') })])),
    h('tbody', {}, m.rows.map((r) => h('tr', {}, [
      h('td', { text: r.form }),
      h('td', { class: 'muted', text: r.entity_id || '—' }),
      h('td', { class: 'muted', text: (r.mapping || []).map((x) =>
        x.source || (x.target_form || '')).join(' / ') }),
      h('td', {}, [h('span', { class: 'tag', text: r.has_reviewed_mapping
        ? 'reviewed' : 'not reviewed' })]),
    ]))),
  ]));
  return card;
}

function attestationZone(d) {
  const a = d.attestation;
  const card = h('div', { class: 'card zone-attestation', id: 'zone-attestation' }, [
    h('h2', {}, [h('span', { text: t('explore.attestation') }), ' ', tagCorpus(a.source)]),
    h('p', { class: 'muted', text: `${a.mode}. ${a.warning}` }),
  ]);
  card.appendChild(h('table', { class: 'data-table' }, [
    h('thead', {}, h('tr', {}, [h('th', { text: t('explore.form') }), h('th', { text: t('explore.passages') }),
      h('th', { text: t('explore.co-alias-forms-same-entity') })])),
    h('tbody', {}, a.rows.map((r) => h('tr', { class: r.zero ? 'zero-row' : '',
      dataset: { form: r.form } }, [
      h('td', { text: r.form }),
      h('td', { class: r.zero ? 'zero-cell' : '', text: r.zero
        ? 'Zero corpus attestation' : String(r.hits) }),
      h('td', { class: 'muted', text: (r.co_forms || []).join(' · ') }),
    ]))),
  ]));
  return card;
}

function interpretationZone(d) {
  const i = d.interpretation;
  return h('div', { class: 'card zone-interpretation', id: 'zone-interpretation' }, [
    h('h2', {}, [h('span', { text: t('explore.interpretation') }), ' ',
      h('span', { class: 'tag', text: t('explore.not-generated') })]),
    h('p', { class: 'muted', text: i.note }),
    h('div', { class: 'action-bar' }, [
      h('button', { class: 'btn btn-ghost', type: 'button', id: 'translation-research',
        text: i.action.label,
        onclick: () => prefill(`中文语料里 ${d.entities[0].preferred_label} 有哪些译法？`
          + '这些译名差异意味着什么？') })]),
  ]);
}

async function renderReelRealite() {
  const d = await api.explore('term', { control: 'reel_realite' });
  const box = h('section', { class: 'explorer-view', id: 'explorer-reel-realite' });
  box.appendChild(h('div', { class: 'explorer-head' }, [
    h('h1', { class: 'explorer-title', text: 'Réel / réalité control' }),
    d.distinct_entities
      ? h('span', { class: 'tag is-ok', text: t('explore.two-distinct-entities') })
      : h('span', { class: 'tag is-warn', text: t('explore.collapsed-investigate') })]));
  box.appendChild(h('p', { class: 'muted', text: d.note }));
  const side = (title, v, id) => h('div', { class: 'card control-side', id }, [
    h('h2', { text: title }),
    kv([['query', v.query], ['entities', (v.entities || []).map((e) => e.concept_id).join(', ')]]),
    h('table', { class: 'data-table' }, [
      h('thead', {}, h('tr', {}, [h('th', { text: t('explore.written-form') }),
        h('th', { text: t('explore.passages') })])),
      h('tbody', {}, (v.attestation || []).map((r) => h('tr', { class: r.zero ? 'zero-row' : '' }, [
        h('td', { text: r.form }),
        h('td', { class: r.zero ? 'zero-cell' : '', text: r.zero
          ? 'Zero corpus attestation' : String(r.hits) })]))),
    ]),
  ]);
  box.appendChild(h('div', { class: 'control-grid' }, [
    side('le Réel', d.reel, 'control-reel'),
    side('réalité', d.realite, 'control-realite'),
  ]));
  return box;
}

// ─────────────────────────────────────────────────────────── Saved（Obsidian manifests）
async function renderSaved() {
  const d = await api.obsidianList();
  const box = h('section', { class: 'explorer-view', id: 'explorer-saved' });
  box.appendChild(h('div', { class: 'explorer-head' }, [
    h('h1', { class: 'explorer-title', text: t('explore.saved-research') }),
    h('span', { class: 'tag', text: `${(d.items || []).length} manifests` })]));
  box.appendChild(h('p', { class: 'muted', text:
    t('explore.read-from-the-workspace-obsidian-manifests-writt--full') }));
  if (!(d.items || []).length) box.appendChild(muted('Nothing saved yet.'));
  else box.appendChild(h('table', { class: 'data-table' }, [
    h('thead', {}, h('tr', {}, [h('th', { text: t('explore.research') }), h('th', { text: t('explore.state') }),
      h('th', { text: t('explore.saved-at') }), h('th', { text: t('explore.note') })])),
    h('tbody', {}, d.items.map((m) => h('tr', {}, [
      h('td', { text: m.research_id || '' }),
      h('td', {}, [h('span', { class: 'tag', text: m.answer_state || '' })]),
      h('td', { class: 'muted', text: String(m.saved_at || '').slice(0, 16) }),
      h('td', { class: 'muted', text: m.research_note || '' }),
    ]))),
  ]));
  return box;
}


// ─────────────────────────────────────────────────────────── 入口
function errorBox(view) {
  return h('section', { class: 'explorer-view' }, [
    h('h1', { class: 'explorer-title', text: view.title || 'Not found' }),
    h('p', { class: 'section-body', text: view.body || '' }),
  ]);
}

export async function renderExplorer(params) {
  const host = document.getElementById('explorer');
  mount(host, h('p', { class: 'muted', text: t('explore.loading') }));
  let node;
  try {
    switch (params.view) {
      case 'concepts': node = await renderConcepts(params); break;
      case 'concept': node = await renderConcept(params); break;
      case 'passages': node = await renderPassages(params); break;
      case 'passage': node = await renderPassage(params); break;
      case 'seminars': node = await renderSeminars(params); break;
      case 'seminar': node = await renderSeminar(params); break;
      case 'session': node = await renderSession(params); break;
      case 'terminology': node = await renderTerminology(params); break;
      case 'term': node = await renderTerm(params); break;
      case 'saved': node = await renderSaved(params); break;
      default: node = errorBox({ title: t('explore.unknown-explorer-view') });
    }
  } catch (e) {
    node = errorBox({ title: t('explore.explorer-request-failed'), body: String(e && e.message || e) });
  }
  mount(host, node);
  document.body.dataset.explorerView = params.view || '';
  document.body.dataset.explorerReady = '1';           // 浏览器烟测/截图用
  return node;
}
