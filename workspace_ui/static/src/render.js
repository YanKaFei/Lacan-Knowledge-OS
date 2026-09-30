// render.js — FinalScholarlyAnswer 的哑渲染器。
// 只做排版/分组/标签；**不改写** claim、citation、limitation、abstention（§1/§36）。
import { h, mount, paragraphs, highlight } from './dom.js';
import { t } from './i18n.js';

const NON_ANSWER_STATES = new Set(['ABSTAINED']);

export function renderAnswer(view, opts = {}) {
  const card = h('article', { class: 'card', 'data-state': view.state || 'UNKNOWN' });
  card.appendChild(h('div', { class: 'answer-head' }, [
    h('span', { class: `state-badge ${stateClass(view.state)}`, text: view.state_label }),
    view.is_qualified ? h('span', { class: 'tag', text: t('research.qualified-scholarly-answer') }) : null,
    h('span', { class: 'answer-meta', text: view.task_type ? `task: ${view.task_type}` : '' }),
    // P5D-004：展示本次请求实际使用的 question language（产品展示自己发送的参数）
    opts.requestLanguage
      ? h('span', { class: 'answer-meta', id: 'answer-question-language',
                    text: `question language: ${opts.requestLanguage}` })
      : null,
    // ★ 产品层实测溯源（模型 / 真实耗时 / 是否命中缓存 / 发了几次）。
    //   数字全部来自产品层自己的计时与缓存计数，**不是**核心的学术判定。
    provenanceNode(view),
  ]));
  card.appendChild(h('h2', { class: 'answer-q', text: view.question || '' }));   // Phase 5A：页面 h1 之下不得再出 h1

  if (view.is_abstention) {
    card.appendChild(renderAbstention(view));
  } else {
    card.appendChild(renderSections(view));
    card.appendChild(renderClaims(view));
  }
  card.appendChild(renderCitations(view, opts.onCitation));
  card.appendChild(renderLimitations(view));
  card.appendChild(renderWarnings(view));
  if (opts.onSaveResearch || opts.onAddToProject) card.appendChild(renderActions(view, opts));
  if (opts.onExport) {
    const host = h('div', { class: 'export-host', id: 'export-host' });
    card.appendChild(host);
    opts.onExport(host, view);
  }
  return card;
}

/** 产品层实测溯源文本：谁回答的 / 哪个模型 / 等了多久 / 缓存没有 / 发了几次。 */
export function provenanceText(view) {
  const a = (view && view.advanced) || {};
  if (a.provider === undefined && a.wall_ms === undefined) return '';
  const bits = [];
  if (a.provider === 'llm') bits.push(`llm: ${a.provider_model || 'unset model'}`);
  else if (a.provider) bits.push(`${a.provider} adapter (no model call)`);
  if (typeof a.wall_ms === 'number') bits.push(`${(a.wall_ms / 1000).toFixed(1)}s`);
  if (a.cached !== undefined) bits.push(a.cached ? 'served from cache' : 'computed now');
  if (a.fresh_requested) bits.push('forced recompute');
  if (a.attempts > 1) {
    bits.push(`attempts: ${a.attempts}${a.retry_reason ? ` (after ${a.retry_reason})` : ''}`);
  }
  return bits.join(' · ');
}

function provenanceNode(view) {
  return h('span', { class: 'answer-meta', id: 'answer-provenance',
                     text: provenanceText(view) });
}

function renderActions(view, opts) {
  const bar = h('div', { class: 'action-bar', id: 'obsidian-actions' }, [
    h('button', { class: 'btn btn-ghost', type: 'button', id: 'save-research-btn',
      text: t('research.save-to-obsidian'), onclick: () => opts.onSaveResearch(view) }),
    h('span', { class: 'muted', id: 'save-status', text: '' }),
  ]);
  if (opts.onAddToProject) {
    bar.appendChild(h('button', { class: 'btn btn-ghost', type: 'button',
      id: 'add-to-project-research', text: t('explore.add-to-project'),
      onclick: () => opts.onAddToProject(view) }));
  }
  const uri = view.advanced && view.advanced.obsidian_uri;
  if (uri) bar.appendChild(h('a', { class: 'link-btn', href: uri, text: t('explore.open-in-obsidian') }));
  return bar;
}

export function renderSaveResult(target, res) {
  const box = h('div', { class: res.ok ? 'notice' : 'notice is-err' }, [
    h('h3', { text: res.ok ? 'Saved to Obsidian' : 'Could not save to Obsidian' }),
    h('p', { text: res.ok
      ? [res.research_note, (res.status === 'already_saved' ? '(already saved)' : '')]
          .filter(Boolean).join(' ')
      : (res.detail || res.error || 'unknown error') }),
  ]);
  if (res.ok && res.obsidian_uri) {
    box.appendChild(h('a', { class: 'link-btn', href: res.obsidian_uri,
                             text: t('explore.open-in-obsidian') }));
  }
  const parts = [];
  for (const [k, label] of [['passage_notes', 'passages'], ['concept_notes', 'concepts'],
                            ['seminar_notes', 'seminars']]) {
    if ((res[k] || []).length) parts.push(`${res[k].length} ${label}`);
  }
  if (parts.length) box.appendChild(h('p', { class: 'muted', text: t('research.linked') + parts.join(' · ') }));
  target.appendChild(box);
  return box;
}

function stateClass(state) {
  if (state === 'VALIDATED') return 'is-validated';
  if (state === 'VALIDATED_WITH_QUALIFICATIONS') return 'is-qualified';
  // Phase 4E：核心的另外三态（真实 provider 会合法返回）。样式与语义一致：
  // 部分支持 = 警示（同 qualified）；验证失败 / 证据不足 = 错误色。
  if (state === 'PARTIALLY_SUPPORTED') return 'is-qualified';
  if (state === 'VALIDATION_FAILED') return 'is-failed';
  if (state === 'INSUFFICIENT_EVIDENCE') return 'is-failed';
  if (state === 'ABSTAINED') return 'is-abstained';
  return '';
}

function renderSections(view) {
  const wrap = h('div');
  for (const s of view.sections || []) {
    if (s.internal) continue;                        // internal → Advanced（内容不丢）
    wrap.appendChild(h('section', { class: 'section' }, [
      h('h2', { text: s.label }),
      h('div', { class: 'section-body' }, paragraphs(s.text)),
    ]));
  }
  if (view.is_abstention) wrap.appendChild(renderAbstention(view));
  return wrap;
}

function renderAbstention(view) {
  const ab = view.abstention || {};
  const box = h('section', { class: 'section abstain' }, [
    h('h2', { text: t('research.abstention') }),
    h('p', { class: 'abstain-title', text: ab.title || 'Current corpus cannot support a reliable answer' }),
  ]);
  const blocks = [
    ['Why this cannot be answered', ab.categories],
    ['Missing information', ab.missing_information],
    ['Available partial information', ab.available_partial_information],
    ['Sources needed', ab.required_sources],
  ];
  for (const [title, items] of blocks) {
    if (!items || !items.length) continue;
    box.appendChild(h('div', { class: 'abstain-block' }, [
      h('h3', { text: title }),
      h('ul', {}, items.map((t) => h('li', { text: t }))),
    ]));
  }
  if (ab.missing_block) {
    box.appendChild(h('div', { class: 'notice is-warn' }, [
      h('h3', { text: t('research.abstention-block-missing-in-payload') }),
      h('p', { text: t('research.the-core-abstained-but-returned-no-abstention-bl') }),
    ]));
  }
  return box;
}

function renderClaims(view) {
  if (!view.claims || !view.claims.length) return h('div');
  return h('section', { class: 'section' }, [
    h('h2', { text: `Validated claims (${view.claims.length})` }),
    h('ul', { class: 'claim-list' }, view.claims.map((c) => h('li', { class: 'claim' }, [
      h('span', { class: 'tag', text: c.epistemic_label || c.epistemic_status || '' }),
      h('span', { class: 'tag', text: c.claim_type || '' }),
      h('span', { class: 'claim-text', text: c.claim_text }),
    ]))),
  ]);
}

function renderCitations(view, onCitation) {
  if (!view.citations || !view.citations.length) return h('div');
  const row = h('div', { class: 'citations' });
  for (const c of view.citations) {
    const hint = [c.source_layer_tag, c.provenance_status === 'SOURCE_TRACE_INCOMPLETE'
      ? t('explore.trace-incomplete') : null].filter(Boolean).join(' · ');
    const btn = h('button', {
      class: 'cite', type: 'button',
      title: `${c.source_layer_label || c.source_layer || ''}${hint ? ' · ' + hint : ''}`,
      'aria-label': `Open evidence for ${c.passage_id}`,
      dataset: { passage: c.passage_id, span: c.quoted_span || '' },
      onclick: () => onCitation && onCitation(c),
    }, [h('span', { text: c.label }),
        hint ? h('span', { class: 'cite-hint', text: hint }) : null]);
    row.appendChild(btn);
  }
  return h('section', { class: 'section' }, [
    h('h2', { text: `Evidence (${view.citations.length})` }), row]);
}

function renderLimitations(view) {
  if (!view.limitations || !view.limitations.length) return h('div');
  return h('details', { class: 'fold', open: view.is_qualified ? '' : null }, [
    h('summary', { text: `Limitations (${view.limitations.length})` }),
    h('ul', {}, view.limitations.map((t) => h('li', { text: t }))),
  ]);
}

function renderWarnings(view) {
  if (!view.warnings || !view.warnings.length) return h('div');
  const items = view.warnings.map((w) => (typeof w === 'string' ? w
    : `${w.code || 'warning'}${w.message ? ' — ' + w.message : ''}`));
  return h('details', { class: 'fold' }, [
    h('summary', { text: `Warnings (${items.length})` }),
    h('ul', {}, items.map((t) => h('li', { text: t }))),
  ]);
}

export function renderError(view, opts = {}) {
  return h('article', { class: 'card' }, [
    h('div', { class: 'answer-head' }, [
      h('span', { class: 'state-badge is-abstained', text: view.code || 'ERROR' })]),
    h('h2', { class: 'answer-q', text: view.title || t('research.request-failed') }),
    h('p', { class: 'section-body', text: view.body || '' }),
    view.resolution ? h('p', { class: 'muted', text: `Next: ${view.resolution}` }) : null,
    // ★ 可操作的下一步（产品层）：重试一次 / 打开 provider 设置。
    //   只呈现后端**显式声明**的动作，不猜、不自动重发。
    Array.isArray(view.actions) && view.actions.length
      ? h('div', { class: 'action-bar', id: 'error-actions' },
          view.actions.map((a) => h('button', {
            class: 'btn btn-ghost', type: 'button',
            'data-error-action': a.id, text: a.label || a.id })))
      : null,
    view.research_disabled
      ? h('div', { class: 'notice is-err' }, [
          h('h3', { text: t('research.research-disabled-fail-closed') }),
          h('p', { text: t('research.submission-is-disabled-until-the-core-integrity') })])
      : null,
  ]);
}

export function renderAdvanced(view) {
  const a = view.advanced || {};
  const rows = Object.entries(a).filter(([, v]) => v !== null && v !== undefined);
  const box = h('details', { class: 'fold' }, [
    h('summary', { text: t('research.advanced-audit') }),
  ]);
  // ★ Phase 5A（P5A-001/P5A-005）：Audit 面。校验器诊断属 AUDIT_DIAGNOSTIC：
  //   默认不出现在答案正文 / 笔记 / 标准导出，但在这里 **100% 可读**。
  //   措辞刻意中性 —— 剔除 claim 是正常研究流程，**不是错误**。
  const audit = view.audit;
  if (audit && view.audit_available) {
    const m = [
      ['Generated claims', audit.generated_claims_n],
      ['Validated claims', audit.validated_claims_n],
      ['Repaired claims', audit.repaired_claims_n],
      ['Rejected claims', audit.rejected_claims_n],
    ].filter(([, v]) => v !== null && v !== undefined);
    const children = [
      h('p', { class: 'muted', text: t('research.validator-record-scholarly-process-not-an-error--full--full') }),
      h('dl', { class: 'kv' }, m.flatMap(([k, v]) => [h('dt', { text: k }),
                                                      h('dd', { text: String(v) })])),
    ];
    if ((audit.rejected || []).length) {
      const list = h('ul', { class: 'audit-list' }, audit.rejected.map((r) => h('li', {}, [
        h('span', { class: 'tag', text: r.status || 'REJECTED' }), ' ',
        h('span', { text: `${r.claim_id || ''} ` }),
        h('span', { class: 'muted', text: String(r.claim_text || '').slice(0, 200) }),
        r.reason ? h('div', { class: 'muted', text: `reason: ${r.reason}` }) : null,
      ])));
      children.push(h('h3', { text: `Rejected claims (${audit.rejected.length})` }), list);
    }
    if ((audit.repaired || []).length) {
      children.push(h('h3', { text: `Repaired claims (${audit.repaired.length})` }),
        h('ul', { class: 'audit-list' }, audit.repaired.map((r) => h('li', { text:
          `${r.original_claim_id} → ${r.repaired_claim_id}（attempts=${r.attempts}）` }))));
    }
    if (audit.derived_from_legacy) {
      children.push(h('p', { class: 'muted', text:
        t('research.this-is-an-rc1-1-snapshot-diagnostics-are-derive--full') }));
    }
    box.appendChild(h('details', { class: 'fold', open: true }, [
      h('summary', { text: t('research.audit-validator-diagnostics') }), ...children]));
  }
  box.appendChild(h('dl', { class: 'kv' }, rows.flatMap(([k, v]) => [
    h('dt', { text: k }), h('dd', { text: String(v) })])));
  // 全部 section 原文（含 internal）：保证"分组而非隐藏"
  if (view.sections && view.sections.length) {
    for (const s of view.sections) {
      box.appendChild(h('details', { class: 'fold' }, [
        h('summary', { text: `Section verbatim — ${s.label}${s.internal ? ' (internal)' : ''}` }),
        h('div', { class: 'section-body' }, paragraphs(s.text)),
      ]));
    }
  }
  if (view.raw) {
    box.appendChild(h('details', { class: 'fold' }, [
      h('summary', { text: t('research.view-raw-response-read-only') }),
      h('pre', { class: 'raw', text: JSON.stringify(view.raw, null, 1).slice(0, 60000) }),
    ]));
  }
  return box;
}
