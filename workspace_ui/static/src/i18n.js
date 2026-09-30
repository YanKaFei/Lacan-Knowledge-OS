// i18n.js — P5D-004：**唯一**的运行时 locale 真源与翻译器。
//
// 单向链路（§4.2，禁止多套互相独立的状态）：
//
//     #ui-locale-select ──input──▶ setLocale() ──▶ state.locale   ← canonical runtime locale
//                                                    ├─▶ t(key) ──▶ 组件重渲染
//                                                    ├─▶ localStorage（持久化）
//                                                    └─▶ <html lang>（BCP 47：zh-CN / en）
//
// 纪律：
//   * Layer A（产品 UI 文案）走 t()；Layer B（语料原文 / 引文 / canonical 标签 / 书目 metadata /
//     用户笔记）**不**经过本模块，绝不改写（UI localization ≠ scholarly translation）。
//   * 缺失 key 的确定性 fallback：requested locale → default locale → **可读兜底**（key 文本本身），
//     绝不把 undefined / null / "translation.missing.foo" 显示给用户（§9）。
import { MESSAGES, FALLBACK_LOCALE, SUPPORTED_LOCALES } from './i18n_messages.js';

const STORAGE_KEY = 'lacan.uiLocale';           // 唯一 key，value schema：'en' | 'zh'
const HTML_LANG = { en: 'en', zh: 'zh-CN' };    // §8：与应用当前语言一致的合法 BCP 47
const DEBUG = () => !!(window && window.__I18N_DEBUG__);

const state = { locale: FALLBACK_LOCALE };
const subscribers = [];
const missing = [];

export function supportedLocales() { return SUPPORTED_LOCALES.slice(); }
export function currentLocale() { return state.locale; }
export function htmlLangFor(locale) { return HTML_LANG[locale] || HTML_LANG[FALLBACK_LOCALE]; }

/** locale value schema 归一化：'zh' / 'zh-CN' / 'zh-Hans' / 'zh_CN' → 'zh'；'en*' → 'en'；其它 → null。 */
export function normalizeLocale(raw) {
  if (!raw) return null;
  const v = String(raw).trim().toLowerCase().replace(/_/g, '-');
  if (v === 'zh' || v.startsWith('zh-')) return 'zh';
  if (v === 'en' || v.startsWith('en-')) return 'en';
  return null;
}

/**
 * 初始 locale 优先级（§7/§9 的确定性回退链）：
 *   1. URL 参数 `?uiLocale=en|zh`（显式覆盖：可分享的深链，也供自动化把语言钉死）
 *   2. localStorage 已存值（**只接受合法值**；非法值安全忽略）
 *   3. 浏览器语言 → 默认 locale
 */
export function detectInitialLocale() {
  let fromUrl = null;
  try { fromUrl = normalizeLocale(new URLSearchParams(location.search).get('uiLocale')); }
  catch (e) { fromUrl = null; }
  if (fromUrl) return fromUrl;
  try {
    const stored = normalizeLocale(localStorage.getItem(STORAGE_KEY));
    if (stored) return stored;
  } catch (e) { /* storage 不可用：退回浏览器语言 */ }
  let nav = null;
  try { nav = (navigator.languages && navigator.languages[0]) || navigator.language; } catch (e) { nav = null; }
  return normalizeLocale(nav) || FALLBACK_LOCALE;
}

function interpolate(msg, params) {
  let out = String(msg);
  for (const [k, v] of Object.entries(params || {})) {
    out = out.split('{' + k + '}').join(v === null || v === undefined ? '' : String(v));
  }
  return out;
}

/**
 * 翻译。缺失 key 时**确定性**回退：requested → default locale → 可读兜底（key 本身）。
 * 绝不返回 undefined / null / 伪 key（§9）。
 */
export function t(key, params) {
  const dict = MESSAGES[state.locale] || {};
  let msg = dict[key];
  if (msg === undefined || msg === null || msg === '') {
    const def = MESSAGES[FALLBACK_LOCALE] || {};
    msg = def[key];
    if (msg === undefined || msg === null) {
      missing.push(key);
      if (DEBUG()) console.warn('[i18n] missing key:', key, 'for locale', state.locale);
      msg = String(key);                        // 可读兜底（不静默假装翻译存在）
    }
  }
  return params ? interpolate(msg, params) : msg;
}

function persist(locale) {
  try { localStorage.setItem(STORAGE_KEY, locale); } catch (e) { /* 功能不依赖 storage */ }
}

/** 同步静态 DOM：`data-i18n="key"`（textContent）或 `data-i18n-attr="aria-label"`（属性）。 */
export function applyStaticDom(root) {
  const host = root || document;
  host.querySelectorAll('[data-i18n]').forEach((el) => {
    const key = el.getAttribute('data-i18n');
    const msg = t(key);
    const attr = el.getAttribute('data-i18n-attr');
    if (attr) el.setAttribute(attr, msg);
    else el.textContent = msg;
  });
  host.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
    el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder')));
  });
}

function syncDocument(locale) {
  document.documentElement.setAttribute('lang', htmlLangFor(locale));
}

/** 切换 locale：没有第二套状态，控件只是这个状态的**输入**。 */
export function setLocale(raw, opts = {}) {
  const locale = normalizeLocale(raw) || FALLBACK_LOCALE;
  const changed = locale !== state.locale;
  state.locale = locale;
  persist(locale);
  syncDocument(locale);
  applyStaticDom();
  if (changed || opts.force) {
    for (const fn of subscribers) {
      try { fn(locale); } catch (e) { console.error('[i18n] locale subscriber failed', e); }
    }
  }
  return locale;
}

export function onLocaleChange(fn) {
  subscribers.push(fn);
  return () => {
    const i = subscribers.indexOf(fn);
    if (i >= 0) subscribers.splice(i, 1);
  };
}

export function missingKeys() { return missing.slice(); }

/** 启动：恢复持久化 locale（或按浏览器语言），并同步静态 DOM + <html lang>。 */
export function initI18n() {
  setLocale(detectInitialLocale(), { force: true });
  return state.locale;
}
