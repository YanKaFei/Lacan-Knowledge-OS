// home.js — P5D-005 首页（任务型信息架构）+ Explore 首页 + Obsidian 打开
//
// 首页回答两件事：① 这是什么 ② 我现在可以用它做什么。
// 一切入口都是**真实 <a href="/…">**（可新标签打开、可复制、可键盘走），
// 由 router.wireLinks() 在同一页面内无刷新切换。
// System Status / Recent 仍然存在（Gate F6 契约），但**下移**到任务之后。
import { h, mount } from './dom.js';
import { t } from './i18n.js';
import { goTo } from './router.js';

async function get(url) {
  const r = await fetch(url, { headers: { 'Accept': 'application/json' } });
  return r.json();
}

// §29 的显示顺序（8 层）
const LAYER_LABEL = {
  core: 'Scholarly Core', mcp: 'MCP', corpus: 'Corpus', workspace: 'Workspace',
  explorer: 'Explorer', obsidian: 'Obsidian', provider: 'Real LLM Provider',
  bibliography: 'Bibliography Registry',
};

// ── 6 张任务卡（§4）：标题 / 说明 / CTA / 真实链接
// 每组都写全 key（**不做字符串拼接**）：i18n 检查器才能逐条核对调用点。
const TASKS = [
  ['home.card.research.title', 'home.card.research.desc', 'home.card.research.cta',
   '/research', 'home-research'],
  ['home.card.explore.title', 'home.card.explore.desc', 'home.card.explore.cta',
   '/explore', 'home-explore'],
  ['home.card.concepts.title', 'home.card.concepts.desc', 'home.card.concepts.cta',
   '/explore?view=concepts', 'home-concepts'],
  ['home.card.entities.title', 'home.card.entities.desc', 'home.card.entities.cta',
   '/persons', 'home-entities'],
  ['home.card.projects.title', 'home.card.projects.desc', 'home.card.projects.cta',
   '/projects', 'home-projects'],
  ['home.card.bibliography.title', 'home.card.bibliography.desc',
   'home.card.bibliography.cta', '/bibliography', 'home-bibliography'],
];

// ── 一次完整研究的六个步骤（§5）：每一步都是可点链接
const FLOW = [
  ['home.flow.1', 'nav.research', '/research'],
  ['home.flow.2', 'inspector.title', '/help/evidence'],
  ['home.flow.3', 'nav.explore', '/explore'],
  ['home.flow.4', 'nav.projects', '/projects'],
  ['home.flow.5', 'nav.bibliography', '/bibliography'],
  ['home.flow.6', 'nav.obsidian', '/help/obsidian'],
];

const QUICK = ['home.quick.1', 'home.quick.2', 'home.quick.3',
               'home.quick.4', 'home.quick.5', 'home.quick.6'];

function link(cls, href, id, label) {
  return h('a', { class: cls, href, id: id || null, text: label });
}

export async function renderHome(host, st) {
  const root = h('section', { class: 'home', id: 'home-view' });

  // ── Hero（§3）
  const hero = h('header', { class: 'home-hero', id: 'home-hero' }, [
    h('h1', { class: 'home-title', id: 'home-title', text: 'Lacan Knowledge OS' }),
    h('p', { class: 'home-sub', id: 'home-sub',
             text: t('home.corpus-grounded-scholarly-research-workspace') }),
    h('p', { class: 'home-lede', id: 'home-lede', text: t('home.hero.lede') }),
    h('div', { class: 'home-hero-cta' }, [
      link('btn btn-primary', '/research', 'hero-start-research',
           t('home.hero.cta-research')),
      link('btn', '/help/getting-started', 'hero-first-time',
           t('home.hero.cta-first-time')),
    ]),
  ]);
  root.appendChild(hero);

  // ── 你想做什么？（§4）
  const tasks = h('section', { class: 'home-section', id: 'home-tasks' }, [
    h('h2', { text: t('home.tasks.title') }),
    h('div', { class: 'home-cards', id: 'home-cards' },
      TASKS.map(([titleKey, descKey, ctaKey, href, id]) => h('a', {
        class: 'task-card', href, id }, [
        h('h3', { class: 'task-card-title', text: t(titleKey) }),
        h('p', { class: 'task-card-desc', text: t(descKey) }),
        h('span', { class: 'task-card-cta', text: t(ctaKey) + ' →' }),
      ]))),
  ]);
  // 文献流程一行（保留既有 i18n key：Bibliography → Inspect Metadata → …）
  tasks.appendChild(h('p', { class: 'muted', id: 'home-bib-flow',
    text: t('home.bibliography-inspect-metadata--full') }));
  root.appendChild(tasks);

  // ── 一次完整研究如何进行（§5）
  const flow = h('section', { class: 'home-section', id: 'home-flow' }, [
    h('h2', { text: t('home.flow.title') }),
    h('p', { class: 'muted', id: 'home-flow-summary',
             text: t('home.explore-research-inspect-evidence--full') }),
    h('ol', { class: 'home-flow-steps', id: 'home-flow-steps' },
      FLOW.map(([labelKey, moduleKey, href], i) => h('li', { class: 'flow-step' }, [
        h('span', { class: 'flow-step-n', text: String(i + 1) }),
        h('a', { class: 'flow-step-link', href, id: 'home-flow-' + (i + 1),
                 text: t(labelKey) }),
        h('span', { class: 'flow-step-module', text: t(moduleKey) }),
      ]))),
    h('p', { class: 'notice', id: 'home-flow-note', text: t('home.flow.note') }),
  ]);
  root.appendChild(flow);

  // ── Quick Start（§6）
  const quick = h('section', { class: 'home-section', id: 'home-quickstart' }, [
    h('h2', { text: t('home.quick.title') }),
    h('ol', { class: 'home-quick-steps', id: 'home-quick-steps' },
      QUICK.map((k, i) => h('li', { id: 'home-quick-' + (i + 1), text: t(k) }))),
    h('p', { class: 'help-link-row' }, [
      link('link-btn', '/help/getting-started', 'home-quickstart-cta',
           t('home.quick.cta') + ' →')]),
  ]);
  root.appendChild(quick);

  // ── 模块动作（Open Obsidian 契约 id 保留）
  root.appendChild(h('div', { class: 'home-actions', id: 'home-module-actions' }, [
    h('button', { class: 'btn', id: 'home-open-obsidian', text: t('home.open-obsidian'),
                  onclick: () => openObsidian() }),
    h('a', { class: 'link-btn', id: 'home-help-link', href: '/help',
             text: t('help.button') }),
  ]));

  // ── System Status（Gate F6 契约：id 与 8 层都在；放在任务之后、可折叠）
  const statusBox = h('details', { class: 'card', id: 'system-status' }, [
    h('summary', { text: t('home.system-status') }),
    h('ul', { class: 'status-list', id: 'status-list' },
      [h('li', { class: 'muted', text: t('home.loading') })]),
    h('p', { class: 'muted', id: 'bib-health', text: '' }),
    h('button', { class: 'btn btn-ghost', id: 'home-refresh', text: t('home.refresh'),
                  onclick: () => refreshStatus(statusBox) }),
  ]);
  root.appendChild(statusBox);

  const recent = h('div', { class: 'card' }, [
    h('h2', { text: t('home.recent') }),
    h('div', { id: 'recent-research' }, [h('p', { class: 'muted', text: t('home.loading') })]),
    h('div', { id: 'recent-projects' }, []),
  ]);
  root.appendChild(recent);

  // 引用能力的如实说明（保留既有 i18n key）
  root.appendChild(h('p', { class: 'muted', id: 'home-help-note',
    text: t('home.formal-bibliographic-citations-chicago-apa-mla-b--full') }));

  mount(host, root);
  await refreshStatus(statusBox);
  await renderRecent();
}

async function refreshStatus(box) {
  const list = box.querySelector('#status-list');
  try {
    const s = await get('/api/status');
    const layers = s.layers || {};
    list.replaceChildren(...Object.keys(LAYER_LABEL).map((k) => h('li', {
      class: 'status-row', 'data-layer': k, id: 'status-' + k,
      text: LAYER_LABEL[k] + ': ' + (layers[k] || 'UNKNOWN') })));
    const reg = s.bibliography_registry || {};
    box.querySelector('#bib-health').textContent = reg.registry
      ? ('Bibliography Registry ' + reg.registry + ' · items ' + reg.items
         + ' · reviewed ' + reg.reviewed + ' · candidates ' + reg.candidates
         + ' · editions ' + reg.editions)
      : 'Bibliography Registry UNAVAILABLE';
    // §30：provider 不可用**不**阻塞本地功能
    box.setAttribute('data-provider', layers.provider || 'UNKNOWN');
  } catch (e) {
    list.replaceChildren(h('li', { class: 'muted', text: t('home.status-unavailable') }));
  }
}

async function renderRecent() {
  const rh = document.getElementById('recent-research');
  const ph = document.getElementById('recent-projects');
  if (!rh || !ph) return;
  try {
    const hist = await get('/api/history?limit=5');
    const items = (hist.items || hist.entries || []).slice(0, 5);
    rh.replaceChildren(...(items.length ? items.map((it, i) => h('button', {
      class: 'link-btn', id: 'recent-item-' + (it.file || it.id || i),
      text: (it.question || it.title || it.id || '').slice(0, 80),
      onclick: () => goTo('/research?q=' + encodeURIComponent(it.question || '')) }))
      : [h('p', { class: 'muted', text: t('home.no-research-yet') })]));
  } catch (e) { rh.replaceChildren(h('p', { class: 'muted', text: t('home.no-research-yet') })); }
  try {
    const pj = await get('/api/projects');
    const items = (pj.items || []).slice(0, 5);
    ph.replaceChildren(...(items.length ? items.map((it) => h('button', {
      class: 'link-btn', text: it.title || it.project_id,
      onclick: () => goTo('/projects?id=' + encodeURIComponent(it.project_id)) }))
      : [h('p', { class: 'muted', text: t('home.no-projects-yet') })]));
  } catch (e) { ph.replaceChildren(h('p', { class: 'muted', text: t('home.no-projects-yet') })); }
}

// §32：一键打开当前 configured vault。
//   * 用隐藏 <a> 点击而不是 location.href —— 自定义协议不应把 SPA 页面卸载掉；
//   * 失败/未配置时写页内提示（**不**用 alert：阻塞式弹窗对键盘与自动化都不友好）。
export async function openObsidian() {
  const box = document.getElementById('obsidian-status');
  const say = (text) => {
    if (box) { box.textContent = text; box.hidden = false; }
  };
  let r = {};
  try { r = await get('/api/obsidian/status'); }
  catch (e) { say('Obsidian status unavailable — use Check Lacan Knowledge OS.command'); return; }
  const uri = r.vault_uri || r.open_uri || r.obsidian_uri;
  if (!uri) {
    say(t('home.obsidian-no-uri')
        + ' ' + (r.workspace_root || r.active_root
                 || (r.detection || {}).default_workspace_root || 'unknown'));
    return;
  }
  const a = document.createElement('a');
  a.href = uri;
  a.rel = 'noopener';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  a.remove();
  say('Opening Obsidian…');
}

const EXPLORE = [
  ['concepts', t('explore.concepts'), '?view=concepts'],
  ['persons', t('nav.persons'), '?view=entities&kind=person'],
  ['cases', t('nav.cases'), '?view=entities&kind=case'],
  ['seminars', t('bibliography.seminars'), '?view=seminars'],
  ['passages', t('bibliography.passages'), '?view=passages'],
  ['terminology', t('explore.terminology'), '?view=terminology'],
  ['bibliography', t('nav.bibliography'), '?view=bibliography'],
];

export function renderExplore(host) {
  const root = h('section', { class: 'explore-home', id: 'explore-view' });
  root.appendChild(h('h1', { class: 'home-title', text: t('home.explore') }));
  root.appendChild(h('p', { class: 'home-sub',
    text: t('home.read-only-browse-over-the-local-corpus-and-regis') }));
  root.appendChild(h('div', { class: 'home-actions', id: 'explore-list' },
    EXPLORE.map(([key, label, href]) => h('button', {
      class: 'btn', id: 'explore-' + key, 'data-explore': key, text: label,
      onclick: () => go(paramsOf(href)) }))));
  root.appendChild(h('p', { class: 'muted', id: 'explore-note',
    text: t('nav.exploreNote') }));
  mount(host, root);
}

function paramsOf(href) {
  const q = new URLSearchParams(href.replace(/^\?/, ''));
  const out = {};
  for (const [k, v] of q.entries()) out[k] = v;
  return out;
}

function go(next) {
  import('./router.js').then((R) => R.navigate(next));
}
