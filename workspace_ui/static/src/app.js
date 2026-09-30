// app.js — Workspace 装配：状态栏 / 研究提交 / 历史 / 高级面板 / 可访问性。
import { h, mount } from './dom.js';
import { api } from './api.js';
import { renderAnswer, renderError, renderAdvanced, renderSaveResult } from './render.js';
import { renderHelp, helpModules } from './help.js';
import { teachEmpty } from './teach.js';
import { openInspector, closeInspector } from './inspector.js';
import { renderExplorer, setExplorerContext } from './explorer.js';
import { isExplorer, isResearch, navigate, onNavigate, onPop, state, HOME_VIEWS,
         contextModule, wireLinks } from './router.js';
import { renderProjectsRoot, setProjectContext, addToProjectDialog } from './project.js';
import { exportBar, citationMenu, exportListCard } from './export.js';
import { openObsidian } from './home.js';
import { initI18n, setLocale, currentLocale, onLocaleChange, t }
  from './i18n.js';

const $ = (id) => document.getElementById(id);
const app = { busy: false, researchDisabled: false, cancelled: false, lastView: null,
              providerSettings: null, providerDirty: false };

// ── P5D-004 修复：Research language 控件的单一真源 + 即时反馈 + 持久化
//    修复前：`#language-select` 只在提交时被读一次，**没有** change handler、
//    没有状态、没有持久化、没有任何可见反馈 —— 用户点/选之后看不到任何反应。
//    现在：一个真源（storage + select 同步），change 时立即更新可见状态并写 localStorage。
const LANG_KEY = 'lacan.researchLanguage';
const LANG_LABEL = { any: null, zh: '中文', fr: 'Français', en: 'English' };
const langState = { value: 'any' };

function langStatusText(v) {
  // 'any' 的显示名与下拉选项共用同一个 key，避免"选项写自动、状态行写 Auto"
  const label = v === 'any' ? t('lang.auto') : (LANG_LABEL[v] || v);
  return t('research.languageStatus', { label: label, code: v });
}

function applyLang(v) {
  const sel = $('language-select');
  langState.value = v;
  if (sel && sel.value !== v) sel.value = v;                 // 单一真源 → 控件同步
  const note = $('language-status');
  if (note) {                                                 // 即时可见反馈（aria-live）
    note.textContent = langStatusText(v);
    note.dataset.language = v;
  }
  try { localStorage.setItem(LANG_KEY, v); } catch (e) { /* storage 不可用时不影响功能 */ }
}

function researchLanguage() { return langState.value; }

function refreshLangStatus() {
  const note = $('language-status');
  if (note) note.textContent = langStatusText(langState.value);
}

function wireResearchLanguage() {
  const sel = $('language-select');
  if (!sel) return;
  let stored = 'any';
  try {
    const raw = localStorage.getItem(LANG_KEY);
    if (raw && Array.from(sel.options).some((o) => o.value === raw)) stored = raw;
  } catch (e) { stored = 'any'; }
  applyLang(stored);                                          // 启动即恢复（reload / 新页面保持）
  sel.addEventListener('change', () => applyLang(sel.value));
  sel.addEventListener('input', () => applyLang(sel.value));
}

// ── 视图切换：Research 与 Explorer 互斥显示（§4/§50）
//    导航用 pushState，Back 交给浏览器 popstate —— 不自己造一套历史。
function showView(name) {
  const bigOn = (name === 'home' || name === 'explore' || name === 'help');
  const explorerOn = isExplorer({ view: name }) || name === 'explorer'
    || name === 'projects' || name === 'project';
  if (bigOn) {
    $('home-view').hidden = name !== 'home';
    $('explore-view').hidden = name !== 'explore';
    if ($('help-view')) $('help-view').hidden = name !== 'help';
    $('ask-view').hidden = true;
    $('result').hidden = true;
    $('advanced-panel').hidden = true;
    $('explorer').hidden = true;
    for (const b of document.querySelectorAll('.nav-item[data-view]')) {
      const on = b.dataset.view === name;
      if (on) { b.setAttribute('aria-current', 'page'); } else { b.removeAttribute('aria-current'); }
    }
    return;
  }
  $('home-view').hidden = true;
  $('explore-view').hidden = true;
  if ($('help-view')) $('help-view').hidden = true;
  $('ask-view').hidden = explorerOn;
  $('result').hidden = true;
  $('advanced-panel').hidden = true;
  $('explorer').hidden = !explorerOn;
  // Phase 5A：导航项的可访问状态（aria-current）与实际视图保持一致
  for (const b of document.querySelectorAll('.nav-item[data-view]')) {
    const on = b.dataset.view === name;
    if (on) { b.setAttribute('aria-current', 'page'); } else { b.removeAttribute('aria-current'); }
    b.classList.toggle('is-active', explorerOn && b.dataset.view === name);
  }
  $('nav-research').classList.toggle('is-active', !explorerOn);
  $('nav-history').classList.remove('is-active');
}

function applyState(st) {
  updateContextualHelp(st);
  if (st.view === 'help') {
    showView('help');
    renderHelp($('help-view'), st);
    return true;
  }
  if (st.view === 'home') {
    showView('home');
    import('./home.js').then((M) => M.renderHome($('home-view'), st));
    return true;
  }
  if (st.view === 'explore') {
    showView('explore');
    import('./home.js').then((M) => M.renderExplore($('explore-view')));
    return true;
  }
  if (st.view === 'bibliography') {
    showView('bibliography');
    import('./bibliography.js').then((M) => M.renderBibliography($('explorer'), st));
    return true;
  }
  if (st.view === 'entities') {
    showView('entities');
    import('./entities.js').then((M) => M.renderEntities($('explorer'), st));
    return true;
  }
  if (st.view === 'projects' || st.view === 'project') {
    showView(st.view);
    renderProjectsRoot(st);
    return true;
  }
  if (isExplorer(st)) {
    showView(st.view);
    renderExplorer(st);
    return true;
  }
  showView('research');
  if (isResearch(st) || st.q) {
    if (st.q) $('question-input').value = st.q;
    return false;
  }
  return false;
}

// ── §9 模块内 contextual help：href 永远指向**当前模块专属**帮助页。
//    映射来自 /api/help/content（服务端唯一真源），不在前端另抄一份。
const HELP_MODULES = { map: null };

let _helpModulesLoading = null;

/** ★ 后台加载（**不阻塞首屏**）：拿不到就保持 /help 兜底，拿到后立即更新 href。 */
function loadHelpModules() {
  if (_helpModulesLoading) return _helpModulesLoading;
  _helpModulesLoading = helpModules().then((m) => {
    HELP_MODULES.map = m;
    updateContextualHelp(state());
    return m;
  }).catch(() => null);
  return _helpModulesLoading;
}

function updateContextualHelp(st) {
  const el = $('contextual-help');
  if (!el) return;
  const m = (HELP_MODULES.map || {})[contextModule(st)] || { help: '/help' };
  el.setAttribute('href', m.help || '/help');
  el.dataset.module = contextModule(st);
}

function setStatus(st) {
  const dot = $('status-dot');
  const connected = !!st.mcp_connected;
  dot.className = 'status-dot ' + (connected ? 'is-ok' : 'is-off');
  $('status-text').textContent = connected ? 'MCP Connected' : 'MCP Offline';
  $('freeze-text').textContent = st.core_freeze_verified
    ? `Core Freeze Verified · ${(st.core_freeze || {}).freeze_version || ''}`
    : 'Core freeze: NOT verified';
  $('version-text').textContent =
    `${(st.server || {}).name || ''} ${(st.server || {}).version || ''}`.trim();
  // Phase 5A §41/§42：provider 是**独立一层**状态；DEGRADED ≠ 产品故障。
  const prov = st.provider || {};
  const ptxt = $('provider-text');
  if (ptxt) {
    ptxt.textContent = prov.state === 'READY'
      ? 'Provider: ready'
      : (prov.state === 'UNAVAILABLE' ? 'Provider: unavailable (offline/mock still works)'
                                      : 'Provider: offline/mock (degraded, offline research OK)');
    ptxt.dataset.state = prov.state || 'UNKNOWN';
  }
  app.researchDisabled = !!st.research_disabled;
  $('ask-btn').disabled = app.busy || app.researchDisabled;
  if (app.researchDisabled) {
    $('ask-note').textContent = connected
      ? 'Research disabled: core integrity check failed.'
      : 'Research disabled: MCP interface offline.';
  }
}

function setBusy(on) {
  app.busy = on;
  $('ask-btn').disabled = on || app.researchDisabled;
  $('cancel-btn').hidden = !on;
  if (!on) {
    stopWait();
    askNote('');
  }
}

// ── 等待体验（产品层，**不编造进度**）
//    真实 LLM 的一次往返可能 45–60s+：过去整页只是"假死"，用户不知道在等什么。
//    现在只报**可观测**的东西：真实已耗时 + 中性的阶段说明 + 一个真的能用的取消。
const WAIT = { timer: null, t0: 0 };

function askNote(text) {
  const n = $('ask-note');
  if (n) n.textContent = text || '';
}

function waitTick() {
  const sec = Math.round((Date.now() - WAIT.t0) / 1000);
  const n = $('ask-note');
  if (!n) return;
  n.textContent = t('research.waiting', { s: String(sec) });
  n.dataset.elapsedSeconds = String(sec);       // 测试/无障碍可读的真实计时
}

function startWait() {
  stopWait();
  WAIT.t0 = Date.now();
  waitTick();
  WAIT.timer = setInterval(waitTick, 1000);
}

function stopWait() {
  if (WAIT.timer) { clearInterval(WAIT.timer); WAIT.timer = null; }
}

/** 长请求作业化：只轮询**真实状态**（RUNNING/DONE/FAILED）与真实耗时。 */
async function runAsJob(payload, token) {
  const started = await api.researchJob(payload);
  if (!started || !started.job_id) return started;
  const jid = started.job_id;
  for (;;) {
    await new Promise((r) => setTimeout(r, 1000));
    if (app.cancelled || app.pending !== token) return { view: null };
    let st;
    try {
      st = await api.researchJobStatus(jid);
    } catch (e) {
      st = { status: 'FAILED', error: String(e && e.message || e) };
    }
    if (st.status === 'DONE') {
      const full = await api.researchJobStatus(jid, true);
      const out = full && full.result;
      if (out && out.view) return out;
      return { view: { kind: 'error', code: 'INTERNAL_ERROR',
                       title: t('research.empty-response'), body: '' } };
    }
    if (st.status === 'FAILED') {
      return { view: { kind: 'error', code: 'INTERNAL_ERROR',
                       title: t('research.request-failed'),
                       body: String(st.error || ''), advanced: {} } };
    }
  }
}

async function submit(question) {
  if (!question || question.trim().length < 4) {
    mount($('result'), renderError({ code: 'INVALID_REQUEST',
      title: t('research.please-enter-a-question-at-least-4-characters'), body: '' }));
    $('result').hidden = false;
    return;
  }
  setBusy(true);
  app.cancelled = false;
  const token = Date.now();
  app.pending = token;
  const provider = $('provider-select').value;
  const freshEl = $('fresh-toggle');
  const payload = {
    question, mode: $('mode-select').value,
    provider, language: researchLanguage(),
    fresh: !!(freshEl && freshEl.checked),      // "忽略缓存"= 产品层不读缓存，重算一次
  };
  startWait();
  let out;
  try {
    // 真实 LLM 走作业化路径（HTTP 立刻返回，前端每秒更新真实耗时）；
    // mock 是确定性快路径，仍走单次请求，行为与以前一致。
    out = provider === 'llm' ? await runAsJob(payload, token)
                             : await api.research(payload);
  } catch (e) {
    out = { view: { kind: 'error', code: 'INTERNAL_ERROR',
      title: t('research.could-not-reach-the-workspace-api'), body: String(e && e.message || e) } };
  }
  if (app.cancelled || app.pending !== token) return;   // cancel = stop waiting
  setBusy(false);
  const view = out.view || { kind: 'error', code: 'INTERNAL_ERROR', title: t('research.empty-response') };
  app.lastView = view;
  renderResult(view);
  if (out.saved && !out.saved.error) loadHistory();
  if (view.kind === 'error' && view.research_disabled) setStatus({ mcp_connected: true,
    core_freeze_verified: false, research_disabled: true });
}

// ── Provider 设置面板（产品层）：模型/端点可改，密钥不经产品 API
function renderProviderState(s) {
  app.providerSettings = s || app.providerSettings;
  const cur = app.providerSettings || {};
  const cred = $('provider-cred-state');
  if (cred) {
    cred.textContent = cur.credentials_present
      ? t('provider.credPresent', { source: cur.credential_source || 'env' })
      : t('provider.credAbsent');
    cred.dataset.credentials = cur.credentials_present ? 'present' : 'absent';
  }
  const cap = $('provider-call-cap');
  if (cap) cap.textContent = t('provider.callCap', { seconds: String(cur.call_timeout_s || 120) });
}

async function loadProviderSettings() {
  let s;
  try { s = await api.providerSettings(); } catch (e) { return null; }
  if (!s || s.kind === 'error') return null;
  const m = $('provider-model');
  const b = $('provider-base-url');
  if (m && !app.providerDirty) m.value = s.model || '';
  if (b && !app.providerDirty) b.value = s.base_url || '';
  renderProviderState(s);
  return s;
}

/** 错误卡上的可操作按钮：只做后端**显式声明**的动作，不自动重发。 */
function wireErrorActions() {
  document.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest && e.target.closest('[data-error-action]');
    if (!btn) return;
    const id = btn.getAttribute('data-error-action');
    if (id === 'provider_settings') {
      const panel = $('provider-panel');
      if (panel) { panel.open = true; panel.scrollIntoView({ block: 'nearest' }); }
      loadProviderSettings();
    } else if (id === 'retry_once') {
      submit($('question-input').value);
    }
  });
}

function wireProvider() {
  const pSave = $('provider-save');
  if (pSave) pSave.addEventListener('click', async () => {
    const host = $('provider-test-out');
    if (host) host.textContent = t('provider.saving');
    const out = await api.providerSave({
      model: ($('provider-model').value || '').trim(),
      base_url: ($('provider-base-url').value || '').trim(),
    });
    app.providerDirty = false;
    if (!host) return;
    if (out && out.kind === 'error') {
      host.textContent = t('provider.saveFailed', { detail: out.body || out.code || '' });
      return;
    }
    host.textContent = t('provider.saved')
      + (out && out.mcp_restarted === false
         ? ' · ' + t('provider.restartFailed', { detail: out.restart_error || '' }) : '');
    loadProviderSettings();
  });
  const pTest = $('provider-test');
  if (pTest) pTest.addEventListener('click', async () => {
    const host = $('provider-test-out');
    if (host) host.textContent = t('provider.testing');
    const r = await api.providerTest({});
    if (!host) return;
    if (r && r.ok) {
      host.textContent = t('provider.testOk', { model: r.model || '', seconds: String(r.latency_s) });
    } else {
      host.textContent = t('provider.testFail', {
        detail: [(r && r.code) || '', (r && r.detail) || ''].filter(Boolean).join(' — ') });
    }
  });
  for (const id of ['provider-model', 'provider-base-url']) {
    const el = $(id);
    if (el) el.addEventListener('input', () => { app.providerDirty = true; });
  }
  const psel = $('provider-select');
  if (psel) psel.addEventListener('change', () => {
    // 选到真实 LLM 但没有凭据：提前说清楚（**不**用模型知识兜底这条也不变）
    if (psel.value !== 'llm') return;
    if (app.providerSettings && !app.providerSettings.credentials_present
        && !app.busy && !app.researchDisabled) {
      askNote(t('provider.llmNoCredentials'));
    }
  });
}

function renderResult(view) {
  showView('research');
  const result = $('result');
  const adv = $('advanced-panel');
  mount(result);
  mount(adv);
  if (view.kind === 'error') {
    mount(result, renderError(view));
    result.hidden = false;
    if (view.advanced && Object.keys(view.advanced).length) {
      mount(adv, renderAdvanced(view)); adv.hidden = false;
    } else { adv.hidden = true; }
    return;
  }
  mount(result, renderAnswer(view, {
    // P5D-004：把**实际发出去**的 question language 显示在答案头部，
    // 让该控件的效果在 Research 流程里可见（产品展示自己发送的参数，不改核心语义）。
    requestLanguage: researchLanguage(),
    onCitation: (c) => openInspector(c, { focusAsk: () => $('question-input').focus() }),
    onSaveResearch: (v) => saveResearch(v),
    onAddToProject: (v) => addResearchToProject(v),
    onExport: async (host, v) => {
      // 预览/导出都基于**同一个** view 对象：由后端重新构造 ExportDocument
      const bar = await exportBar({
        source_type: 'research_run', view: v, source_id: (v.advanced || {}).request_id,
      }, { host: $('result'), previewHost: $('result') });
      mount(host, bar);
    },
  }));
  result.hidden = false;
  // 路由透明度（P5A-004）：把「为什么是这个答案状态」放进 Advanced（可见、不打扰）。
  //   ABSTAINED / INSUFFICIENT_EVIDENCE 是**证据驱动**的学术结果，由冻结的证据充分性阶段决定；
  //   provider / mode 不改变该判断（也**不是**错误）。
  try {
    const sum = view.summary || {};
    view.advanced = Object.assign({}, view.advanced, {
      answer_state: view.state,
      answer_permission: view.answer_permission,
      evidence_state: sum.evidence_state,
      execution_state: sum.execution_state,
      presentation_note: 'ABSTAINED / INSUFFICIENT_EVIDENCE 是证据驱动的学术结果，不是错误。',
    });
  } catch (e) { /* 透明度是附加信息，失败不影响主答案 */ }
  mount(adv, renderAdvanced(view));
  adv.hidden = false;
}

async function saveResearch(view) {
  const btn = $('save-research-btn');
  const status = $('save-status');
  if (btn) btn.disabled = true;
  if (status) status.textContent = 'Saving…';
  const payload = {
    question: view.question, mode: $('mode-select').value,
    provider: $('provider-select').value, language: researchLanguage(),
  };
  const res = await api.obsidianSaveResearch(payload);
  if (status) status.textContent = res.ok ? t('nav.saved') : t('research.save-failed');
  if (btn) btn.disabled = false;
  if (view.advanced) view.advanced.obsidian_uri = res.obsidian_uri || null;
  renderSaveResult($('obsidian-actions') || $('result'), res);
  return res;
}

async function addResearchToProject(view) {
  const box = await addToProjectDialog({
    kind: 'run', label: view.question, runView: view,
    requestMeta: { mode: $('mode-select').value, provider: $('provider-select').value },
  });
  const host = $('result');
  const old = document.getElementById('add-to-project');
  if (old) old.remove();
  host.appendChild(box);
}

/** History → Project（§47）：把已有快照加入项目，**不重新调用 LLM**。 */
async function addHistoryToProject(file, question) {
  const box = await addToProjectDialog({ kind: 'history', label: question,
    historyFile: file });
  const host = $('explorer');
  host.hidden = false;
  mount(host, h('section', { class: 'explorer-view' }, [
    h('h1', { class: 'explorer-title', text: t('research.add-history-snapshot-to-project') }),
    h('p', { class: 'muted', text: question || '' }), box]));
  document.body.dataset.projectReady = '1';
}

async function loadHistory() {
  const list = $('history-list');
  const data = await api.history(50, 0);
  mount(list);
  if (!(data.items || []).length) {
    // P5D-005 §10：空历史也要能教用户
    list.appendChild(h('li', {}, teachEmpty(t('history.empty.title'), t('history.empty.body'),
      [[t('history.empty.start'), '/research'],
       [t('projects.empty.learn'), '/help/getting-started']],
      { id: 'history-empty', actionIds: ['history-empty-start', 'history-empty-help'] })));
    return;
  }
  for (const it of data.items || []) {
    list.appendChild(h('li', {}, h('button', {
      class: 'history-item', type: 'button', title: it.question,
      onclick: () => loadHistoryItem(it.file),
    }, [
      h('span', { class: 'hi-q', text: it.question || '(no question)' }),
      h('span', { class: 'hi-meta',
        text: `${it.state_label || ''} · ${it.citations_n || 0} citations · ${(it.saved_at || '').slice(0, 16)}` }),
    ])));
    list.appendChild(h('li', {}, h('button', {
      class: 'link-btn', type: 'button', id: 'history-to-project',
      text: t('explore.add-to-project'), title: t('research.add-this-stored-snapshot-to-a-project-no-llm-cal'),
      onclick: () => addHistoryToProject(it.file, it.question),
    })));
  }
  if (!(data.items || []).length) {
    list.appendChild(h('li', { class: 'muted', text: t('research.no-saved-research-yet') }));
  }
}

async function loadHistoryItem(file) {
  const rec = await api.historyItem(file);
  if (!rec || rec.error) return;
  if (rec.request && rec.request.question) $('question-input').value = rec.request.question;
  renderResult(rec.answer);
}

function wireLocale() {
  const sel = $('ui-locale-select');
  if (!sel) return;
  sel.value = currentLocale();                      // 控件只是 canonical locale 的输入
  sel.addEventListener('change', () => setLocale(sel.value));
}

function wire() {
  wireLocale();
  wireResearchLanguage();
  wireProvider();
  wireErrorActions();
  wireLinks(document);          // §5：页面里的 <a href="/…"> 走无刷新导航
  $('ask-btn').addEventListener('click', () => submit($('question-input').value));
  $('cancel-btn').addEventListener('click', () => {
    app.cancelled = true;                         // 仅停止等待；不杀后端（§23）
    setBusy(false);
    askNote(t('research.stoppedWaiting'));
  });
  $('question-input').addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit($('question-input').value);
  });
  for (const b of document.querySelectorAll('.chip-btn')) {
    b.addEventListener('click', () => {
      $('question-input').value = b.dataset.q || b.textContent;
      submit($('question-input').value);
    });
  }
  for (const b of document.querySelectorAll('.nav-item[data-view]')) {
    if (b.tagName !== 'BUTTON') continue;      // 真链接交给 wireLinks()（无刷新导航）
    b.addEventListener('click', () => navigate({ view: b.dataset.view }));
  }
  if ($('nav-research').tagName === 'BUTTON') {
    $('nav-research').addEventListener('click', () => navigate({ view: 'research' }));
  }
  // §32：侧边栏 Obsidian 一键打开（与首页 Open Obsidian 同一个动作）
  if ($('nav-obsidian')) {
    $('nav-obsidian').addEventListener('click', () => openObsidian());
  }
  $('nav-history').addEventListener('click', () => {
    const p = $('history-panel');
    p.hidden = !p.hidden;
    $('nav-history').classList.toggle('is-active', !p.hidden);
    if (!p.hidden) loadHistory();
  });
  $('history-refresh').addEventListener('click', loadHistory);
  $('inspector-close').addEventListener('click', () => closeInspector({}));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeInspector({ focusAsk: () => $('question-input').focus() });
  });
  $('nav-exports').addEventListener('click', async () => {
    const host = $('explorer');
    host.hidden = false;
    showView('exports');
    const card = await exportListCard();
    mount(host, h('section', { class: 'explorer-view', id: 'exports-view' }, [
      h('h1', { class: 'explorer-title', text: t('research.exports') }), card]));
    document.body.dataset.exportsReady = '1';
  });
  $('nav-status').addEventListener('click', async () => {
    const st = await api.status();
    mount($('advanced-panel'), renderAdvanced({ advanced: {
      mcp_connected: st.mcp_connected, core_freeze_verified: st.core_freeze_verified,
      freeze_version: (st.core_freeze || {}).freeze_version,
      checked_at: st.checked_at, research_disabled: st.research_disabled } }));
    $('advanced-panel').hidden = false;
  });
  $('nav-search').addEventListener('click', async () => {
    const q = prompt('Passage search (Advanced)');
    if (!q) return;
    const res = await api.search(q, 10);
    const box = h('div', { class: 'card' }, [
      h('h3', { text: `Search: ${q} (dense_available=${res.dense_available})` }),
      h('ul', {}, (res.results || []).map((r) => h('li', {}, [
        h('button', { class: 'cite', type: 'button', text: r.label,
          onclick: () => openInspector({ passage_id: r.passage_id }, {}) }),
        h('span', { text: ' ' + (r.snippet || '').slice(0, 160) })])))]);
    mount($('result'), box); $('result').hidden = false;
  });
}

(async function boot() {
  initI18n();                                        // 先定 locale，再装配任何文案
  onLocaleChange(() => {                             // §4.1：不刷新页面即可见变化
    if (app.lastView && !$('result').hidden) renderResult(app.lastView);
    applyState(state());                             // Help 正文同理随语言即时切换
    const sel = $('ui-locale-select');
    if (sel) sel.value = currentLocale();
    refreshLangStatus();
    renderProviderState(app.providerSettings);       // provider 面板的动态文案同样即时切换
  });
  wire();
  setProjectContext({
    onProjectAnswer: (res) => {                 // 项目内研究：把答案显示在 Research 视图
      showView('research');
      if (res && res.view) { app.lastView = res.view; renderResult(res.view); }
    },
  });
  setExplorerContext({
    onPrefill: (question) => {                 // Explorer → Research 预填（不自动执行）
      navigate({ view: 'research' });
      showView('research');
      $('question-input').value = question;
      $('question-input').focus();
    },
  });
  onPop((st) => { applyState(st); });
  onNavigate((st) => { applyState(st); });   // 站内导航同样要重绘
  const st = await api.status();
  setStatus(st);
  await loadProviderSettings();                      // 真实 provider 的生效设置（密钥只报有没有）
  loadHelpModules();                                 // §9 contextual help 的模块映射（后台加载）
  const params = new URLSearchParams(location.search);
  // 证据深链（可分享）：?inspect=passage.S05.unknown.L05.P0056&span=...
  const inspect = params.get('inspect');
  if (inspect) {
    openInspector({ passage_id: inspect, quoted_span: params.get('span') || null }, {});
  }
  // 初始状态 = 路径路由 + 查询参数（见 router.state()）。
  // ★ P5D-005：默认落在**任务型首页**；只有研究深链（q / inspect / autorun）或
  //   显式视图才直接进对应模块。旧深链 `?view=…` 的语义完全不变。
  const initial = state();
  const researchDeepLink = !!(initial.q || initial.inspect || initial.autorun);
  if (researchDeepLink) {
    applyState({ ...initial, view: null });
  } else if (isExplorer(initial) || HOME_VIEWS.has(initial.view)
             || ['help', 'projects', 'project', 'bibliography', 'entities',
                 'research'].includes(initial.view)) {
    applyState(initial);
  } else {
    applyState({ ...initial, view: 'home' });
  }
  const q = params.get('q');
  if (q) {
    $('question-input').value = q;
    if (params.get('mode')) $('mode-select').value = params.get('mode');
    if (params.get('provider')) $('provider-select').value = params.get('provider');
    if (params.get('autorun') === '1') {
      await submit(q);
      if (params.get('save') === '1' && app.lastView && app.lastView.kind === 'answer') {
        await saveResearch(app.lastView);
      }
    }
  }
  await runAuto(params);                          // 深链自动化（等价于人在页面上点）
  document.body.dataset.ready = '1';              // 浏览器烟测用：JS 已装配
})();

// runAuto — 烟测/截图用的**交互等价**钩子（与 4D.2 的 ?autorun=1 同一思路）：
// 它只做用户本来会做的动作（填表 + 提交 / 点第一个结果 / 进控制案例），
// 不改变任何业务逻辑，也不新增数据路径。
async function runAuto(params) {
  const auto = params.get('auto');
  if (!auto) return;
  const wait = async (sel, tries = 60) => {
    for (let i = 0; i < tries; i += 1) {
      const el = document.querySelector(sel);
      if (el) return el;
      await new Promise((r) => setTimeout(r, 100));
    }
    return null;
  };
  if (auto === 'concept_search') {
    const input = await wait('#concept-search');
    if (!input) return;
    input.value = params.get('query') || '';
    input.form.dispatchEvent(new Event('submit', { cancelable: true }));
    await wait('#explorer-concept');
  } else if (auto === 'first_passage') {
    const btn = await wait('.passage-item .cite');
    if (btn) btn.click();
    await wait('#explorer-passage');
  } else if (auto === 'first_result_concept') {
    const btn = await wait('.concept-row .row-main');
    if (btn) btn.click();
    await wait('#explorer-concept');
  } else if (auto === 'control') {
    const btn = await wait('.chips .link-btn');
    if (btn) btn.click();
    await wait('#explorer-term');
  }
}
