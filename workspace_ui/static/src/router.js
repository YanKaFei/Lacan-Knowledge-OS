// router.js — 产品的 URL 状态与浏览器历史（§37/§49/§50 + P5D-005 真实产品路由）
//
// 两层同时成立：
//   1. **真实路径路由**（P5D-005）：/research /explore /projects /bibliography
//      /persons /cases /zotero /help /help/<slug>。这些是服务端 SPA 路由，
//      可直接分享、可新标签打开；页面里的 <a href="/…"> 走 goTo() 无刷新切换。
//   2. **查询参数状态**（4D.4 既有，保持向后兼容）：?view=concepts / ?inspect=…
//      / ?q=… / ?seminar=… 等仍然完全有效；`?view=` 优先于路径默认值。
//
// 深链（研究态）保持 4D.2 语义：q / inspect / autorun 指向 Research。

export const EXPLORER_VIEWS = new Set(
  ['concepts', 'concept', 'passages', 'passage', 'seminars', 'seminar',
   'session', 'terminology', 'term', 'saved', 'projects', 'project',
   'entities', 'bibliography']);

// 路径**已经**表达了这些视图 → 不必再带 ?view=（避免两处真源）。
// ⚠️ /explore 只表示"Explore 首页"：concepts / passages / saved 等子视图必须带 ?view=，
//    否则 navigate() 写出的 URL 会丢掉子视图（实测踩过：概念检索提交后回到 Explore 首页）。
const PATH_IMPLIED_VIEWS = new Set(
  ['home', 'help', 'projects', 'project', 'bibliography', 'entities', 'research',
   'explore']);

export const HOME_VIEWS = new Set(['home', 'explore']);

/** 路径 → 视图默认值（产品真实路由）。 */
export function pathState(pathname) {
  const parts = (pathname || '/').replace(/\/+$/, '').split('/').filter(Boolean);
  if (!parts.length) return { view: 'home' };
  const head = parts[0];
  if (head === 'help') {
    return parts[1] ? { view: 'help', topic: decodeURIComponent(parts[1]) }
                    : { view: 'help' };
  }
  if (head === 'home') return { view: 'home' };
  if (head === 'research') return { view: null };
  if (head === 'explore') return { view: 'explore' };
  if (head === 'projects') return { view: 'projects' };
  if (head === 'bibliography') return { view: 'bibliography' };
  if (head === 'zotero') return { view: 'bibliography', import: '1' };
  if (head === 'persons') return { view: 'entities', kind: 'person' };
  if (head === 'cases') return { view: 'entities', kind: 'case' };
  return { view: 'home' };
}

/** 视图 → 产品路径（导航时写进地址栏的规范形式）。 */
export function pathFor(next) {
  const n = next || {};
  const v = n.view;
  if (v === 'help') return n.topic ? '/help/' + encodeURIComponent(n.topic) : '/help';
  if (v === 'home') return '/home';
  if (v === 'explore') return '/explore';
  if (v === 'projects' || v === 'project') return '/projects';
  if (v === 'bibliography') return '/bibliography';
  if (v === 'entities') return n.kind === 'case' ? '/cases' : '/persons';
  if (v === 'research' || v === null || v === undefined) return '/research';
  if (EXPLORER_VIEWS.has(v)) return '/explore';
  return location.pathname;
}

/** 当前模块（供 contextual help 用）：路径优先，查询参数 view 其次。 */
export function contextModule(st) {
  const s = st || state();
  const q = new URLSearchParams(location.search).get('view');
  if (q) return q;
  if (s.view === 'help') return 'help';
  if (s.view === null || s.view === undefined) return 'research';
  if (s.view === 'home') return 'home';
  if (s.view === 'entities') return 'entities';
  if (s.view === 'projects' || s.view === 'project') return 'projects';
  if (s.view === 'bibliography') return 'bibliography';
  if (s.view === 'explore') return 'explore';
  return s.view || 'home';
}

/** 合并后的状态：路径默认值 + 查询参数（查询参数优先，保持旧深链语义）。 */
export function state() {
  const q = Object.fromEntries(new URLSearchParams(location.search).entries());
  const merged = Object.assign({}, pathState(location.pathname), q);
  if (q.view === '') delete merged.view;
  return merged;
}

export function isExplorer(s) {
  return EXPLORER_VIEWS.has((s || state()).view);
}

// 研究深链优先：带 q= 或 inspect= 时按 4D.2 的行为走
export function isResearch(s) {
  const st = s || state();
  return !!(st.q || st.inspect) && !isExplorer(st);
}

// 由路径与查询解释出来的"路由键"不进 query（它们已经在路径里了）
const PATH_KEYS = new Set(['view', 'topic']);
const DROP_KEYS = new Set(['kind']);      // entities 的 kind 由路径表达（persons/cases）

function url(next, keep) {
  const cur = new URLSearchParams(location.search);
  const out = new URLSearchParams();
  for (const k of keep || []) if (cur.get(k)) out.set(k, cur.get(k));
  const n = next || {};
  const dropView = PATH_IMPLIED_VIEWS.has(n.view) || n.view === null || n.view === undefined;
  for (const [k, v] of Object.entries(n)) {
    if (v === null || v === undefined || v === '') continue;
    if (PATH_KEYS.has(k)) {
      if (k === 'topic') continue;                 // topic 只走路径
      if (dropView) continue;                      // view 由路径表达
    }
    if (DROP_KEYS.has(k) && (n.view === 'entities')) continue;
    out.set(k, String(v));
  }
  const s = out.toString();
  return pathFor(n) + (s ? '?' + s : '');
}

const _handlers = [];

function _fire() {
  const st = state();
  for (const fn of _handlers) {
    try { fn(st); } catch (e) { /* 单个视图渲染失败不应打断导航 */ }
  }
  return st;
}

export function navigate(next, opts = {}) {
  const target = url(next, opts.keep || []);
  if (opts.replace) history.replaceState({ view: next.view }, '', target);
  else history.pushState({ view: next.view }, '', target);
  // ⚠️ 实测踩过：只 pushState 不派发 → 点概念行时 URL 变了、页面却纹丝不动
  return _fire();
}

/** 直接打开一个产品路径（页面里的真实 <a href="/…"> 点击走这里）。 */
export function goTo(href, opts = {}) {
  const u = new URL(href, location.origin);
  const target = u.pathname + (u.search || '') + (u.hash || '');
  if (opts.replace) history.replaceState({}, '', target);
  else history.pushState({}, '', target);
  return _fire();
}

/** 注册内部导航处理器：**pushState 也要触发一次渲染**，不只 popstate。 */
export function onNavigate(handler) {
  _handlers.push(handler);
}

export function onPop(handler) {
  window.addEventListener('popstate', () => handler(state()));
}

/** 拦截页面内 `<a href="/…">` 的左键点击 → 无刷新导航（中键/新标签仍走浏览器原生行为）。 */
export function wireLinks(root) {
  const host = root || document;
  host.addEventListener('click', (e) => {
    if (e.defaultPrevented || e.button !== 0) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a) return;
    if (a.target || a.hasAttribute('download') || a.dataset.native === '1') return;
    const href = a.getAttribute('href') || '';
    if (!href.startsWith('/')) return;                    // 外链/协议链接不拦
    const u = new URL(a.href, location.origin);
    if (u.origin !== location.origin) return;
    e.preventDefault();
    goTo(u.pathname + u.search + u.hash);
  });
}
