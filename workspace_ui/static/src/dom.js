// dom.js — 极小的安全 DOM 构建器。**只用 createElement/textContent**，
// 绝不对不可信内容使用 innerHTML（§37：用户问题与 corpus 文本都是 untrusted）。

export function h(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = String(v);          // 永远走 textContent
    else if (k === 'html') continue;                            // 显式忽略，防误用
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else el.setAttribute(k, String(v));
  }
  for (const c of [].concat(children)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return el;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

export function mount(node, ...children) {
  clear(node);
  for (const c of children) if (c) node.appendChild(c);
  return node;
}

// 把长文本按行渲染成段落（仍为纯文本节点）
export function paragraphs(text) {
  const out = [];
  for (const line of String(text || '').split('\n')) {
    const t = line.trim();
    if (!t) continue;
    out.push(h('p', { text: t }));
  }
  return out;
}

// 高亮 quoted span：**纯文本节点切分**，不用 innerHTML
export function highlight(text, span) {
  const txt = String(text || '');
  if (!span) return [document.createTextNode(txt)];
  const i = txt.indexOf(span);
  if (i < 0) return [document.createTextNode(txt)];
  return [
    document.createTextNode(txt.slice(0, i)),
    h('mark', { class: 'qspan', text: span }),
    document.createTextNode(txt.slice(i + span.length)),
  ];
}
