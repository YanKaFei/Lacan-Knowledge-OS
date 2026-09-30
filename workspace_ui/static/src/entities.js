// entities.js — Phase 5B：Person / Case Explorer（**只读、只有提及证据**）
//
// 纪律：本视图只呈现 entity_browse_api 的提及证据；
//   不显示、也不请求任何影响 / 理论关系 / 个案分析（§31 no-inference gate）。
import { h, mount } from './dom.js';
import { t } from './i18n.js';

async function get(url) {
  const r = await fetch(url, { headers: { 'Accept': 'application/json' } });
  return r.json();
}

const NOTICE = 'Mention evidence only — appearance in the corpus. '
  + 'This view asserts no influence, no theoretical relation and no case analysis.';

export async function renderEntities(host, st) {
  const kind = st.kind === 'case' ? 'case' : 'person';
  const wrap = h('section', { class: 'card', id: 'entity-explorer' });
  wrap.appendChild(h('h2', { text: t('persons-cases.entities') + (kind === 'case' ? 'Cases' : 'Persons') }));
  wrap.appendChild(h('p', { class: 'muted', id: 'entity-notice', text: NOTICE }));

  const tabs = h('div', { class: 'tabs', role: 'tablist' }, [
    tab('Persons', kind === 'person', () => goto({ kind: 'person', id: null, cursor: null })),
    tab('Cases', kind === 'case', () => goto({ kind: 'case', id: null, cursor: null })),
  ]);
  wrap.appendChild(tabs);

  const listHost = h('div', { id: 'entity-list' });
  const detailHost = h('div', { id: 'entity-detail' });
  wrap.appendChild(listHost);
  wrap.appendChild(detailHost);
  mount(host, wrap);

  const base = kind === 'case' ? '/api/explore/cases' : '/api/explore/persons';
  const q = new URLSearchParams();
  if (st.cursor) q.set('cursor', st.cursor);
  q.set('limit', '20');
  let res;
  try { res = await get(base + '?' + q.toString()); }
  catch (e) { listHost.appendChild(h('p', { class: 'muted', text: t('persons-cases.load-failed') + e })); return; }

  const items = res.items || [];
  if (!items.length) listHost.appendChild(h('p', { class: 'muted', text: t('persons-cases.no-reviewed-entities') }));
  const ul = h('ul', { class: 'entity-list', id: 'entity-items' });
  for (const it of items) {
    const li = h('li', {}, [
      h('button', { type: 'button', class: 'link-btn entity-row',
                    'data-entity-id': it.id,
                    text: (it.label_zh || it.label || it.id) + '  (' + it.mention_count + ' mentions)',
                    onclick: () => goto({ kind, id: it.id, cursor: st.cursor }) }),
      h('span', { class: 'muted', text: '  ' + it.id + ' · ' + it.review_status }),
    ]);
    ul.appendChild(li);
  }
  listHost.appendChild(ul);
  const pg = res.page || {};
  listHost.appendChild(h('p', { class: 'muted', id: 'entity-page',
    text: t('bibliography.offset') + pg.offset + ' returned=' + pg.returned + ' total=' + pg.total }));
  if (pg.next_cursor) {
    listHost.appendChild(h('button', { type: 'button', class: 'btn btn-ghost',
      id: 'entity-next', text: t('bibliography.next-page'),
      onclick: () => goto({ kind, id: null, cursor: pg.next_cursor }) }));
  }
  if (pg.offset > 0) {
    listHost.appendChild(h('button', { type: 'button', class: 'btn btn-ghost',
      id: 'entity-prev', text: t('persons-cases.first-page'), onclick: () => goto({ kind, id: null, cursor: null }) }));
  }

  if (st.id) {
    const ep = kind === 'case' ? '/api/explore/case' : '/api/explore/person';
    let d;
    try { d = await get(ep + '?id=' + encodeURIComponent(st.id)); }
    catch (e) { detailHost.appendChild(h('p', { class: 'muted', text: t('bibliography.detail-failed') })); return; }
    const box = h('article', { class: 'card entity-detail', id: 'entity-detail-card' });
    box.appendChild(h('h3', { text: d.label_zh || d.label || d.id }));
    const rows = [[t('explore.field-id'), d.id], [t('explore.kind'), d.kind], [t('explore.field-review-status-code'), d.review_status],
      ['evidence_kind', d.evidence_kind], ['mentions', d.mention_count],
      ['aliases', (d.aliases || []).join(', ')]];
    if (kind === 'case') rows.push(['subject_person', d.subject_person || '—']);
    box.appendChild(h('dl', { class: 'kv' }, rows.flatMap(([k, v]) => [
      h('dt', { text: k }), h('dd', { text: String(v) })])));
    if (kind === 'case' && d.subject_person) {
      box.appendChild(h('p', { class: 'muted', id: 'entity-separation-note',
        text: t('persons-cases.person-schreber-case-schreber-distinct-entities--full') }));
    }
    const mr = await get('/api/explore/mentions?id=' + encodeURIComponent(d.id) + '&limit=10');
    box.appendChild(h('h4', { text: t('persons-cases.mention-sample') }));
    box.appendChild(h('ul', { class: 'entity-mentions', id: 'entity-mentions' },
      (mr.items || []).map((m) => h('li', { text: m.passage_id + '  ·  ' + (m.language || '')
        + '  ·  ' + (m.authority_level || '') }))));
    detailHost.appendChild(box);
  }
}

function tab(label, active, onclick) {
  return h('button', { type: 'button', class: 'tab' + (active ? ' is-active' : ''),
                       role: 'tab', 'aria-selected': active ? 'true' : 'false',
                       text: label, onclick });
}

function goto(next) {
  import('./router.js').then((R) => R.navigate(Object.assign({ view: 'entities' }, next)));
}
