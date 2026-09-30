// help.js — P5D-005 Help Center（/help、/help/<topic>）
//
// 纪律：
//   * **单一词典**：正文全部由既有 `t()` 渲染（不新建 locale 系统，§17）；
//   * **不虚构**：正文里的 `{{ui:KEY}}` 会被替换成产品**真实**标签（当前 locale），
//     引用不存在的 key 会被 build/link 检查抓出来；
//   * **原文不翻译**：kind=source 的块直接显示 API 给的文本，不经过词典；
//   * 全部用 DOM 节点构建（无 innerHTML），键盘可达，链接都是真实 `<a href="/…">`。
import { h, mount } from './dom.js';
import { t } from './i18n.js';

const CACHE = { doc: null, at: 0 };
const UI_REF = /\{\{ui:([A-Za-z0-9._\-]+)\}\}/g;

async function loadDoc() {
  if (CACHE.doc && Date.now() - CACHE.at < 60000) return CACHE.doc;
  const r = await fetch('/api/help/content', { headers: { 'Accept': 'application/json' } });
  CACHE.doc = await r.json();
  CACHE.at = Date.now();
  return CACHE.doc;
}

/** 把带 `{{ui:KEY}}` 的文案渲染成 DOM 节点（引用处用 <code class="ui-ref">）。 */
export function resolveRich(text) {
  const out = [];
  const s = String(text == null ? '' : text);
  let last = 0, m;
  UI_REF.lastIndex = 0;
  while ((m = UI_REF.exec(s)) !== null) {
    if (m.index > last) out.push(document.createTextNode(s.slice(last, m.index)));
    out.push(h('code', { class: 'ui-ref', text: t(m[1]) }));
    last = m.index + m[0].length;
  }
  if (last < s.length) out.push(document.createTextNode(s.slice(last)));
  return out;
}

function richP(text, cls) {
  const p = h('p', { class: cls || '' });
  for (const n of resolveRich(text)) p.appendChild(n);
  return p;
}

function hrefWithQuery(href, query) {
  if (!query) return href;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) qs.set(k, String(v));
  return href + (href.includes('?') ? '&' : '?') + qs.toString();
}

function block(b) {
  const key = b.key;
  switch (b.kind) {
    case 'h2':
      return h('h2', { id: b.anchor || null, text: t(key) });
    case 'h3':
      return h('h3', { id: b.anchor || null, text: t(key) });
    case 'p':
      return richP(t(key));
    case 'callout':
      return h('div', { class: 'notice' + (b.tone === 'warn' ? ' is-warn' : '') },
        [richP(t(key))]);
    case 'ul':
    case 'ol': {
      const host = h(b.kind === 'ul' ? 'ul' : 'ol', { class: 'help-list' });
      for (const k of b.item_keys || []) {
        const li = h('li');
        for (const n of resolveRich(t(k))) li.appendChild(n);
        host.appendChild(li);
      }
      return host;
    }
    case 'dl': {
      const dl = h('dl', { class: 'help-dl' });
      for (const it of b.items || []) {
        const dt = h('dt');
        for (const n of resolveRich(t(it.term_key))) dt.appendChild(n);
        const dd = h('dd');
        for (const n of resolveRich(t(it.desc_key))) dd.appendChild(n);
        dl.appendChild(dt); dl.appendChild(dd);
      }
      return dl;
    }
    case 'link':
      return h('p', { class: 'help-link-row' }, [
        h('a', { class: 'link-btn', href: hrefWithQuery(b.href, b.query),
                 text: t(b.key) })]);
    case 'source':
      // Layer B：原文不翻译、不经过词典
      return h('pre', { class: 'help-source', text: b.text });
    default:
      return null;
  }
}

function topicList(doc, current) {
  const side = h('nav', { class: 'help-side', 'aria-label': t('help.topics') });
  side.appendChild(h('p', { class: 'help-side-title', text: t('help.topics') }));
  const search = h('input', { type: 'search', class: 'explorer-input', id: 'help-search',
    'aria-label': t('help.searchAria'), placeholder: t('help.search') });
  side.appendChild(search);
  const listHost = h('div', { id: 'help-topic-list' });
  side.appendChild(listHost);
  const empty = h('p', { class: 'muted', id: 'help-no-topics', hidden: true,
    text: t('help.no-topics') });
  side.appendChild(empty);

  const render = (needle) => {
    listHost.replaceChildren();
    let shown = 0;
    for (const sec of doc.sections || []) {
      const pages = (sec.pages || []).map((s) => doc.pages.find((p) => p.slug === s))
        .filter(Boolean)
        .filter((p) => !needle || (t(p.title_key) + ' ' + t(p.summary_key))
          .toLowerCase().includes(needle));
      if (!pages.length) continue;
      listHost.appendChild(h('p', { class: 'help-side-section', text: t(sec.title_key) }));
      const ul = h('ul', { class: 'help-side-list' });
      for (const p of pages) {
        const on = p.slug === current;
        ul.appendChild(h('li', {}, [h('a', {
          class: 'help-side-link' + (on ? ' is-current' : ''),
          href: '/help/' + p.slug, text: t(p.title_key),
          'aria-current': on ? 'page' : null })]));
        shown += 1;
      }
      listHost.appendChild(ul);
    }
    empty.hidden = shown > 0;
  };
  search.addEventListener('input', () => render(search.value.trim().toLowerCase()));
  render('');
  return side;
}

function bodyFor(doc, page) {
  const article = h('article', { class: 'help-body', id: 'help-article' });
  article.appendChild(h('h1', { class: 'help-title', text: t(page.title_key) }));
  article.appendChild(richP(t(page.summary_key), 'help-summary'));
  for (const b of page.blocks || []) {
    const node = block(b);
    if (node) article.appendChild(node);
  }
  return article;
}

function pager(doc, page) {
  const order = doc.pages.map((p) => p.slug);
  const i = order.indexOf(page.slug);
  const prev = i > 0 ? doc.pages[i - 1] : null;
  const next = i >= 0 && i < doc.pages.length - 1 ? doc.pages[i + 1] : null;
  const bar = h('div', { class: 'help-pager', id: 'help-pager' }, [
    prev ? h('a', { class: 'btn btn-ghost', id: 'help-prev',
                    href: '/help/' + prev.slug,
                    text: '← ' + t(prev.title_key) }) : h('span'),
    h('a', { class: 'btn btn-ghost', id: 'help-back', href: '/help',
             text: t('help.back-to-help') }),
    next ? h('a', { class: 'btn btn-ghost', id: 'help-next',
                    href: '/help/' + next.slug,
                    text: t(next.title_key) + ' →' }) : h('span'),
  ]);
  return bar;
}

function moduleBackLink(page) {
  if (!page.module_help) return null;
  return h('p', { class: 'help-back-module-row' }, [
    h('a', { class: 'link-btn', id: 'help-back-module', href: page.module_href || '/',
             text: t('help.back-to-module') })]);
}

/** 模块 → contextual help 目标（服务端唯一真源的只读副本，供 app.js 使用）。 */
export async function helpModules() {
  const doc = await loadDoc();
  return doc.modules || {};
}

export async function renderHelp(host, st) {
  const root = h('section', { class: 'help', id: 'help-view' });
  let doc;
  try {
    doc = await loadDoc();
  } catch (e) {
    mount(host, root);
    root.appendChild(h('div', { class: 'notice is-err' }, [
      h('h2', { text: t('help.load-failed') })]));
    return;
  }
  const slug = st && st.topic ? String(st.topic) : null;
  const page = slug ? doc.pages.find((p) => p.slug === slug) : null;

  const layout = h('div', { class: 'help-layout' });
  layout.appendChild(topicList(doc, slug));

  if (slug && !page) {
    const box = h('article', { class: 'help-body', id: 'help-article' }, [
      h('h1', { class: 'help-title', text: t('help.topic-not-found') }),
      richP(t('help.topic-not-found-body')),
      h('p', { class: 'help-link-row' }, [
        h('a', { class: 'link-btn', href: '/help', text: t('help.back-to-help') })]),
    ]);
    layout.appendChild(box);
    root.appendChild(layout);
    mount(host, root);
    return;
  }

  if (!page) {
    const box = h('article', { class: 'help-body', id: 'help-article' }, [
      h('h1', { class: 'help-title', text: t(doc.index.title_key) }),
      richP(t(doc.index.intro_key)),
      h('h2', { id: 'topics', text: t('help.topics') }),
    ]);
    for (const sec of doc.sections || []) {
      box.appendChild(h('h3', { text: t(sec.title_key) }));
      const ul = h('ul', { class: 'help-topic-grid' });
      for (const s of sec.pages || []) {
        const p = doc.pages.find((x) => x.slug === s);
        if (!p) continue;
        ul.appendChild(h('li', {}, [h('a', { class: 'help-topic-card',
          href: '/help/' + p.slug }, [
          h('strong', { text: t(p.title_key) }),
          h('span', { class: 'muted', text: t(p.summary_key) })])]));
      }
      box.appendChild(ul);
    }
    layout.appendChild(box);
    root.appendChild(layout);
    mount(host, root);
    return;
  }

  layout.appendChild(bodyFor(doc, page));
  root.appendChild(layout);
  const back = moduleBackLink(page);
  if (back) root.appendChild(back);
  root.appendChild(pager(doc, page));
  mount(host, root);
}
