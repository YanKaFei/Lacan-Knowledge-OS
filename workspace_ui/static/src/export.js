// export.js — Export & Citation UI（Phase 4D.6 §50–§55）
//
// 纪律：
//   * 预览只能是后端 ExportDocument 的渲染结果（§55）——前端**不生成**任何摘要；
//   * citation 字符串只能来自 formatter（§54）；capability=false 的样式**不显示**按钮（§21）；
//   * 所有文本走 textContent（corpus / 用户内容都是 untrusted，§33）。
import { h, mount } from './dom.js';
import { api } from './api.js';
import { t } from './i18n.js';

const $ = (id) => document.getElementById(id);
let MENU = null;

function muted(t) { return h('p', { class: 'muted', text: t }); }

export async function exportMenu() {
  if (!MENU) MENU = await api.exportMenu();
  return MENU;
}

/** 研究答案上的 Export 菜单（Markdown / JSON / HTML / Bundle） */
export async function exportBar(payload, opts = {}) {
  const menu = await exportMenu();
  const status = h('span', { class: 'muted', id: 'export-status' });
  const bar = h('div', { class: 'action-bar', id: 'export-actions' }, [
    h('span', { class: 'muted', text: t('export.export') }),
  ]);
  for (const f of menu.formats) {
    bar.appendChild(h('button', {
      class: 'btn btn-ghost', type: 'button', id: `export-${f.id}`,
      dataset: { format: f.id }, text: f.label,
      onclick: async () => {
        status.textContent = `Exporting ${f.label}…`;
        // §47：标准导出只含用户可见面（学术内容 + 学术限制）。
        const res = await api.exportRun({ ...payload, format: f.id, include_audit: false });
        if (res.kind === 'export_result') {
          status.textContent = `Exported → ${res.file || res.rel_dir}`;
          const box = h('div', { class: 'notice', id: 'export-result' }, [
            h('h4', { text: `${f.label} export ready` }),
            h('p', { text: res.file || res.rel_dir }),
            res.zip ? h('p', { class: 'muted', text: `zip: ${res.zip}` }) : null,
            h('p', { class: 'muted', text: `payload hash ${res.export_payload_hash}` }),
          ]);
          const old = document.getElementById('export-result');
          if (old) old.remove();
          (opts.host || document.getElementById('result')).appendChild(box);
        } else {
          status.textContent = `${res.code || 'EXPORT_FAILED'}: ${res.title || ''}`;
        }
      },
    }));
  }
  bar.appendChild(h('button', {
    class: 'btn btn-ghost', type: 'button', id: 'export-preview-btn', text: t('bibliography.preview'),
    onclick: async () => {
      const res = await api.exportPreview({ ...payload, format: 'markdown' });
      const host = opts.previewHost || document.getElementById('result');
      const old = document.getElementById('export-preview');
      if (old) old.remove();
      host.appendChild(h('div', { class: 'card', id: 'export-preview' }, [
        h('h3', { text: `Export preview (${res.format}) · ${res.document.answer_state}` }),
        h('p', { class: 'muted', text:
          t('export.preview-renders-the-exportdocument-itself-no-ext') }),
        h('pre', { class: 'raw', text: (res.text || '').slice(0, 20000) }),
      ]));
    },
  }));
  bar.appendChild(status);
  // ★ Phase 5A §46：Audit Bundle —— 把校验器诊断/验证轨迹作为独立审计文件随包，
  //   供方法学审计；**标准导出正文不含它们**（presentation taxonomy: AUDIT_DIAGNOSTIC）。
  bar.appendChild(h('button', {
    class: 'btn btn-ghost', type: 'button', id: 'export-audit-bundle',
    text: t('export.audit-bundle'),
    title: t('export.include-validator-diagnostics-rejected-claims-va'),
    onclick: async () => {
      status.textContent = 'Exporting Audit Bundle…';
      const res = await api.exportRun({ ...payload, format: 'bundle', include_audit: true });
      if (res.kind === 'export_result') {
        status.textContent = `Exported → ${res.rel_dir}`;
        const box = h('div', { class: 'notice', id: 'export-result' }, [
          h('h4', { text: t('export.audit-bundle-ready') }),
          h('p', { text: res.rel_dir }),
          h('p', { class: 'muted', text: t('export.contains-audit-rejected-claims-json--full') }),
          h('p', { class: 'muted', text: `payload hash ${res.export_payload_hash}` }),
        ]);
        const old = document.getElementById('export-result');
        if (old) old.remove();
        (opts.host || document.getElementById('result')).appendChild(box);
      } else {
        status.textContent = `Export failed: ${res.code || res.kind}`;
      }
    },
  }));
  return bar;
}

/** Citation 菜单（§53）：只显示 capabilities 允许的样式 */
export async function citationMenu(passageId, opts = {}) {
  const data = await api.exportCitation(passageId);
  if (data.kind === 'error') {
    return h('div', { class: 'card' }, [muted(data.title || 'Citation unavailable')]);
  }
  const status = h('span', { class: 'muted', id: 'citation-status' });
  const card = h('div', { class: 'card', id: 'citation-menu' }, [
    h('h3', { text: `Citation · ${passageId}` }),
    h('p', { class: 'muted', text: data.record.kind === 'internal_scholarly'
      ? 'Internal scholarly citation (passage id / seminar / source layer / witness / provenance).'
      : '' }),
  ]);
  const rows = h('ul', { class: 'plain-list' });
  for (const s of data.styles) {
    const li = h('li', { dataset: { style: s.id } }, [
      h('span', { class: 'tag', text: s.id }),
    ]);
    if (s.available) {
      li.appendChild(h('span', { text: ' ' + s.text }));
      li.appendChild(h('button', {
        class: 'link-btn', type: 'button', text: t('export.copy'),
        onclick: async (e) => {
          try {
            await navigator.clipboard.writeText(s.text);
            status.textContent = `Copied (${s.id})`;
          } catch (err) { status.textContent = 'Clipboard unavailable'; }
        },
      }));
    } else {
      // §21/§54：不可用的样式不显示按钮，只说明原因
      li.appendChild(h('span', { class: 'muted',
        text: `  unavailable — ${s.reason || 'BIBLIOGRAPHIC_METADATA_INCOMPLETE'}` }));
    }
    rows.appendChild(li);
  }
  card.appendChild(rows);
  card.appendChild(status);
  return card;
}

/** 导出列表 + bundle 校验状态（Visual QA：Bundle verification status） */
export async function exportListCard() {
  const data = await api.exportList();
  const card = h('div', { class: 'card', id: 'export-list' }, [
    h('h3', { text: `Exports (${data.total})` }),
    h('p', { class: 'muted', text: `Root: ${data.path}（USER_WORKSPACE）` }),
  ]);
  const ul = h('ul', { class: 'plain-list' });
  for (const item of (data.items || []).slice(0, 25)) {
    const li = h('li', {}, [
      h('span', { class: 'tag', text: item.is_dir ? 'bundle' : 'file' }),
      h('span', { text: ' ' + item.name }),
    ]);
    if (item.is_dir) {
      const st = h('span', { class: 'muted', id: 'verify-' + item.name });
      li.appendChild(h('button', {
        class: 'link-btn', type: 'button', text: t('export.verify'),
        onclick: async () => {
          const v = await api.exportVerify(item.name);
          st.textContent = ` → ${v.status}`;
          st.className = v.status === 'VERIFIED' ? 'tag is-ok' : 'tag is-warn';
        },
      }));
      li.appendChild(st);
    }
    ul.appendChild(li);
  }
  card.appendChild(ul);
  return card;
}
