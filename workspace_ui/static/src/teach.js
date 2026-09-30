// teach.js — P5D-005 §10：教学型空状态。
// 空状态不只报事实：说明这是什么 + 给两个真实动作（动作都是 <a href="/…">）。
import { h } from './dom.js';

/**
 * 教学型空状态：标题 + 说明 + 两个真实动作。
 *
 * ⚠️ 参数是**已翻译的文本**（调用方用 i18n 的 t 助手写字面量 key），不是 key 本身：
 *    动态 key 会被 i18n 构建器的 liveness 判成死条目而丢掉，界面就会漏出 key 文本
 *    （实测踩过：`<h3>projects.no-projects-yet</h3>`）。
 *
 * actions: [[label, href], …]（第一个当成主按钮）。
 */
export function teachEmpty(title, body, actions, opts = {}) {
  const box = h('div', { class: 'empty-teach', id: opts.id || null });
  box.appendChild(h('h3', { text: title }));
  box.appendChild(h('p', { text: body }));
  const bar = h('div', { class: 'empty-actions' });
  (actions || []).forEach(([label, href], i) => {
    bar.appendChild(h('a', {
      class: i === 0 ? 'btn btn-primary' : 'btn btn-ghost',
      href, id: opts.actionIds ? opts.actionIds[i] : null,
      text: label }));
  });
  if (bar.childNodes.length) box.appendChild(bar);
  return box;
}
