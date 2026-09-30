// project.js — Research Project 视图（Phase 4D.5 §8–§11/§50/§72）
//
// 纪律：
//   * 用户内容（笔记 / 假设 / 问题）按 untrusted 渲染：只用 textContent（§60）；
//   * revision 冲突必须显式呈现（WORKSPACE_CONFLICT），不静默重试；
//   * 「Add to Project」从 Research / Explorer / History 三处复用同一个对话框（§45–§47）。
import { h, mount } from './dom.js';
import { api } from './api.js';
import { navigate } from './router.js';
import { exportBar } from './export.js';
import { t } from './i18n.js';
import { teachEmpty } from './teach.js';

const $ = (id) => document.getElementById(id);
let CTX = {};

export function setProjectContext(ctx) { CTX = { ...CTX, ...ctx }; }

function muted(t) { return h('p', { class: 'muted', text: t }); }
function kv(rows) {
  const list = [];
  for (const [k, v] of rows) {
    if (v === null || v === undefined || v === '') continue;
    list.push(h('dt', { text: k }), h('dd', { text: String(v) }));
  }
  return list.length ? h('dl', { class: 'kv' }, list) : null;
}
function go(next) { navigate(next); }

// ─────────────────────────────────────────────────────────── 项目列表
async function renderProjects(params) {
  const data = await api.projects.list({ status: params.status, tag: params.tag,
    query: params.query });
  const box = h('section', { class: 'explorer-view', id: 'project-list' });
  box.appendChild(h('div', { class: 'explorer-head' }, [
    h('h1', { class: 'explorer-title', text: t('projects.research-projects') }),
    h('span', { class: 'tag', text: `${data.total} projects` }),
  ]));
  box.appendChild(h('p', { class: 'muted', text:
    t('projects.a-project-is-a-user-workspace-object-it-organize--full') }));

  box.appendChild(createForm());
  box.appendChild(h('div', { class: 'chips' }, [
    h('button', { class: 'link-btn', type: 'button', text: t('projects.all'),
      onclick: () => go({ view: 'projects' }) }),
    h('button', { class: 'link-btn', type: 'button', text: 'ACTIVE',
      onclick: () => go({ view: 'projects', status: 'ACTIVE' }) }),
    h('button', { class: 'link-btn', type: 'button', text: 'ARCHIVED',
      onclick: () => go({ view: 'projects', status: 'ARCHIVED' }) }),
  ]));

  if (!data.items.length) {
    // P5D-005 §10：空状态必须能教用户 —— 说明 + 两个真实动作
    box.appendChild(teachEmpty(t('projects.no-projects-yet'), t('projects.empty.body'),
      [[t('projects.empty.create'), '/projects'],
       [t('projects.empty.learn'), '/help/projects']],
      { id: 'projects-empty', actionIds: ['projects-empty-create', 'projects-empty-learn'] }));
    return box;
  }
  const ul = h('ul', { class: 'project-list' });
  for (const p of data.items) {
    ul.appendChild(h('li', { class: 'project-row', dataset: { project: p.project_id } }, [
      h('button', { class: 'row-main', type: 'button',
        onclick: () => go({ view: 'project', id: p.project_id }) }, [
        h('span', { class: 'row-label', text: p.title }),
        h('span', { class: 'row-id', text: p.project_id }),
        h('span', { class: 'row-aliases', text: (p.tags || []).join(' · ') }),
      ]),
      h('span', { class: 'row-meta' }, [
        h('span', { class: 'tag ' + (p.status === 'ARCHIVED' ? 'is-warn' : 'is-ok'),
          text: p.status }),
        h('span', { class: 'tag', text: `rev ${p.revision}` }),
        h('span', { class: 'tag', text: `${p.counts.research_runs} runs` }),
        h('span', { class: 'tag', text: `${p.counts.saved_passages} passages` }),
        h('span', { class: 'tag', text: `${p.counts.open_questions} open Q` }),
      ]),
    ]));
  }
  box.appendChild(ul);
  return box;
}

function createForm() {
  // Phase 5A（P5A-003 同类）：输入框不能只靠 placeholder —— 必须有显式可访问名。
  const titleLab = h('label', { class: 'sr-only', id: 'project-title-label',
    for: 'project-title', text: t('projects.project-title') });
  const descLab = h('label', { class: 'sr-only', id: 'project-desc-label',
    for: 'project-desc', text: t('projects.project-description-optional') });
  const tagsLab = h('label', { class: 'sr-only', id: 'project-tags-label',
    for: 'project-tags', text: t('projects.project-tags-comma-separated') });
  const title = h('input', { class: 'explorer-input', id: 'project-title', type: 'text',
    'aria-labelledby': 'project-title-label',
    placeholder: t('projects.project-title-e-g') });
  const desc = h('input', { class: 'explorer-input', id: 'project-desc', type: 'text',
    'aria-labelledby': 'project-desc-label',
    placeholder: t('projects.description-optional') });
  const tags = h('input', { class: 'explorer-input', id: 'project-tags', type: 'text',
    'aria-labelledby': 'project-tags-label',
    placeholder: t('projects.tags-comma-separated') });
  const status = h('span', { class: 'muted', id: 'project-create-status' });
  const form = h('form', { class: 'explorer-form', id: 'project-create-form',
    onsubmit: async (e) => {
      e.preventDefault();
      status.textContent = 'Creating…';
      const res = await api.projects.create({ title: title.value,
        description: desc.value,
        tags: tags.value.split(',').map((s) => s.trim()).filter(Boolean) });
      if (res.kind === 'project_created') go({ view: 'project', id: res.project.project_id });
      else status.textContent = res.title || res.code || 'failed';
    } }, [titleLab, title, descLab, desc, tagsLab, tags,
    h('button', { class: 'btn', type: 'submit', id: 'create-project-btn',
      text: t('projects.create-project') }), status]);
  return h('div', { class: 'card' }, [h('h2', { text: t('projects.new-project') }), form]);
}

// ─────────────────────────────────────────────────────────── 项目详情
async function renderProject(params) {
  const d = await api.projects.detail(params.id, params.tab || 'overview');
  if (d.kind === 'error') {
    return h('section', { class: 'explorer-view' }, [
      h('h1', { class: 'explorer-title', text: d.title || 'Project' }),
      h('p', { class: 'section-body', text: d.body || '' })]);
  }
  if (params.link_ref) d.legacy_link_target = params.link_ref;
  if ((params.tab || '') === 'bibliography') {
    // 只列出 **reviewed** 条目作为可挂接目标（candidate 不可挂，§12/§33）
    try {
      const r = await fetch('/api/explore/bibliography?review_status=reviewed&limit=100',
        { headers: { Accept: 'application/json' } }).then((x) => x.json());
      setProjectContext({ reviewedItems: (r.items || []).map((i) => ({
        bibliographic_id: i.bibliographic_id, title: i.title })) });
    } catch (e) { setProjectContext({ reviewedItems: [] }); }
  }
  const p = d.project;
  const box = h('section', { class: 'explorer-view', id: 'project-detail' });
  box.appendChild(h('div', { class: 'explorer-head' }, [
    h('h1', { class: 'explorer-title', id: 'project-title-text', text: p.title }),
    h('span', { class: 'row-id', text: p.project_id }),
    h('span', { class: 'tag ' + (p.status === 'ARCHIVED' ? 'is-warn' : 'is-ok'),
      text: p.status }),
    h('span', { class: 'tag', text: `rev ${p.revision}` }),
  ]));

  // 二级导航（§50）
  const nav = h('div', { class: 'subnav', id: 'project-subnav' });
  for (const t of d.tabs) {
    const active = (params.tab || 'overview') === t.id;
    nav.appendChild(h('button', { class: 'subnav-item' + (active ? ' is-active' : ''),
      type: 'button', dataset: { tab: t.id },
      text: t.label + (t.primary ? '' : ' ·'),
      onclick: () => go({ view: 'project', id: p.project_id, tab: t.id }) }));
  }
  box.appendChild(nav);

  if (d.broken_references && d.broken_references.length) {
    box.appendChild(h('div', { class: 'notice is-warn', id: 'broken-references' }, [
      h('h3', { text: `Broken reference (${d.broken_references.length})` }),
      h('p', { text: t('projects.these-ids-are-kept-and-shown-as-broken-nothing-i')
        + d.broken_references.join(', ') })]));
  }

  const tab = params.tab || 'overview';
  if (tab === 'overview') box.appendChild(overviewTab(d));
  else if (tab === 'questions') box.appendChild(questionsTab(d));
  else if (tab === 'research') box.appendChild(researchTab(d));
  else if (tab === 'evidence') box.appendChild(evidenceTab(d));
  else if (tab === 'notes') box.appendChild(notesTab(d));
  else if (tab === 'questions_open') box.appendChild(openQuestionsTab(d));
  else if (tab === 'hypotheses') box.appendChild(hypothesesTab(d));
  else if (tab === 'bibliography') box.appendChild(bibliographyTab(d));
  else if (tab === 'activity') box.appendChild(activityTab(d));
  return box;
}

function overviewTab(d) {
  const p = d.project;
  const card = h('div', { class: 'card', id: 'tab-overview' }, [
    h('h2', { text: t('bibliography.overview') }),
    kv([['Description', p.description], ['Created', p.created_at],
        ['Updated', p.updated_at], ['Status', p.status],
        ['Tags', (p.tags || []).join(', ')], ['Revision', p.revision]]),
    h('p', { class: 'muted', text: d.note }),
  ]);
  const c = d.summary.counts;
  card.appendChild(h('ul', { class: 'counts-list' }, [
    h('li', { text: `${c.research_runs} research runs` }),
    h('li', { text: `${c.saved_passages} saved passages` }),
    h('li', { text: `${c.open_questions} open questions` }),
    h('li', { text: `${c.saved_concepts} concepts · ${c.saved_seminars} seminars · `
      + `${c.saved_terms} terms` }),
    h('li', { text: `${c.notes} notes · ${c.hypotheses} hypotheses · `
      + `${c.bibliography_refs} bibliography refs` }),
  ]));
  card.appendChild(h('p', { class: 'muted', text:
    t('projects.these-are-workspace-counts-there-is-no-research--full') }));
  card.appendChild(projectActions(d));
  const expHost = h('div', { class: 'export-host', id: 'project-export-host' });
  card.appendChild(expHost);
  exportBar({ source_type: 'research_project', project_id: p.project_id },
    { host: expHost, previewHost: expHost }).then((node) => mount(expHost, node));
  return card;
}

function projectActions(d) {
  const p = d.project;
  const status = h('span', { class: 'muted', id: 'project-action-status' });
  const bar = h('div', { class: 'action-bar' }, [
    h('button', { class: 'btn btn-ghost', type: 'button', id: 'export-manifest',
      text: t('projects.export-project-manifest-json'),
      onclick: async () => {
        const res = await api.projects.manifest(p.project_id);
        const box = h('pre', { class: 'raw', id: 'manifest-json',
          text: JSON.stringify(res.manifest, null, 1).slice(0, 20000) });
        document.getElementById('tab-overview').appendChild(box);
      } }),
    h('button', { class: 'btn btn-ghost', type: 'button', id: 'obsidian-sync',
      text: t('projects.sync-obsidian-project-hub'),
      onclick: async () => {
        const res = await api.projects.obsidianSync(p.project_id);
        status.textContent = res.ok ? `Hub: ${res.note}` : (res.body || 'failed');
      } }),
    p.status === 'ACTIVE'
      ? h('button', { class: 'btn btn-ghost', type: 'button', id: 'archive-project',
          text: t('projects.archive-project'),
          onclick: async () => {
            const res = await api.projects.archive(p.project_id, p.revision);
            status.textContent = res.kind === 'project_archived'
              ? 'Archived (nothing was deleted)' : (res.title || res.code);
          } })
      : h('button', { class: 'btn btn-ghost', type: 'button', id: 'restore-project',
          text: t('projects.restore-to-active'),
          onclick: async () => {
            const res = await api.projects.restore(p.project_id, p.revision);
            status.textContent = res.kind === 'project_restored' ? 'Active again'
              : (res.title || res.code);
          } }),
    status,
  ]);
  return bar;
}

function questionsTab(d) {
  const p = d.project;
  const card = h('div', { class: 'card', id: 'tab-questions' }, [
    h('h2', { text: t('projects.research-questions') }),
    h('p', { class: 'muted', text:
      t('projects.open-researched-deferred-are-project-management--full') }),
  ]);
  const ul = h('ul', { class: 'plain-list' });
  for (const q of p.research_questions) {
    ul.appendChild(h('li', { dataset: { question: q.question_id } }, [
      h('span', { class: 'tag', text: q.status }),
      h('span', { text: ' ' + q.text }),
      h('button', { class: 'link-btn', type: 'button', text: t('home.research'),
        onclick: () => runQuestion(p, q) }),
      h('button', { class: 'link-btn', type: 'button', text: t('projects.defer'),
        onclick: () => setStatus(p, q.question_id, 'DEFERRED') }),
      h('button', { class: 'link-btn', type: 'button', text: t('projects.reopen'),
        onclick: () => setStatus(p, q.question_id, 'OPEN') }),
    ]));
  }
  if (!p.research_questions.length) ul.appendChild(h('li', { class: 'muted',
    text: t('projects.no-questions-yet') }));
  card.appendChild(ul);
  const text = h('input', { class: 'explorer-input', id: 'new-question',
    placeholder: t('projects.new-research-question') });
  card.appendChild(h('form', { class: 'explorer-form', onsubmit: (e) => {
    e.preventDefault();
    api.projects.add(p.project_id, p.revision, 'question', { text: text.value })
      .then(() => go({ view: 'project', id: p.project_id, tab: 'questions' }));
  } }, [text, h('button', { class: 'btn', type: 'submit', text: t('projects.add-question') })]));
  return card;
}

async function setStatus(p, questionId, status) {
  await api.projects.add(p.project_id, p.revision, 'question_status',
    { text: questionId, status });
}

async function runQuestion(p, q) {
  const btnStatus = document.getElementById('project-question-status');
  if (btnStatus) btnStatus.textContent = 'Researching via the frozen core…';
  const res = await api.projects.research(p.project_id, p.revision, q.text,
    q.question_id);
  if (CTX.onProjectAnswer) CTX.onProjectAnswer(res);
  if (btnStatus) {
    btnStatus.textContent = res.stored && res.stored.kind === 'project_run_added'
      ? `Run stored · ${res.answer_state}` : (res.code || 'failed');
  }
  go({ view: 'project', id: p.project_id, tab: 'research' });
}

function researchTab(d) {
  const p = d.project;
  const card = h('div', { class: 'card', id: 'tab-research' }, [
    h('h2', { text: `Research runs (${d.runs.length})` }),
    h('p', { class: 'muted', text:
      t('projects.every-run-is-an-immutable-snapshot-of-the-finals--full') }),
    h('p', { class: 'muted', text: `Snapshot verification: ${d.verify.overall}`,
      id: 'verify-status' }),
  ]);
  if (!d.runs.length) card.appendChild(muted('No runs yet. Use a question above.'));
  for (const r of d.runs) {
    const item = h('article', { class: 'run-item', dataset: { run: r.run_id } }, [
      h('div', { class: 'pi-head' }, [
        h('span', { class: 'tag ' + (r.is_abstention ? 'is-warn'
          : (r.is_qualified ? 'is-candidate' : 'is-ok')), text: r.answer_state }),
        r.is_qualified ? h('span', { class: 'tag', text: t('projects.qualified-answer') }) : null,
        h('span', { class: 'row-id', text: r.run_id }),
        h('span', { class: 'muted', text: (r.created_at || '').slice(0, 19) }),
      ]),
      h('p', { class: 'pi-snippet', text: r.question }),
      h('div', { class: 'pi-meta muted', text:
        `${r.citation_ids.length} citations · ${r.claim_count} claims · `
        + `provider ${r.provider || '—'} · hash ${String(r.source_answer_hash).slice(0, 12)}` }),
      h('div', { class: 'action-bar' }, [
        h('button', { class: 'btn btn-ghost', type: 'button', text: t('projects.view-stored-answer'),
          onclick: () => viewStoredRun(p.project_id, r.run_id) }),
        h('button', { class: 'btn btn-ghost', type: 'button', text: t('projects.add-second-run-to-compare'),
          onclick: () => go({ view: 'project', id: p.project_id, tab: 'research',
            compare: r.run_id }) }),
      ]),
    ]);
    if ((r.limitations || []).length) {
      item.appendChild(h('details', { class: 'fold' }, [
        h('summary', { text: `Limitations (${r.limitations.length})` }),
        h('ul', {}, r.limitations.map((t) => h('li', { text: t }))),
        h('button', { class: 'btn btn-ghost', type: 'button', id: 'to-open-question',
          text: t('projects.create-open-question-from-missing-information'),
          onclick: async () => {
            await api.projects.add(p.project_id, p.revision, 'open_question',
              { text: r.limitations[0], origin: 'created_from_limitation',
                run_id: r.run_id, limitation: r.limitations[0] });
            go({ view: 'project', id: p.project_id, tab: 'questions_open' });
          } }),
      ]));
    }
    if (r.is_abstention) {
      item.appendChild(h('p', { class: 'muted', text:
        t('projects.this-run-abstained-it-is-stored-as-abstained-nev') }));
    }
    card.appendChild(item);
  }
  return card;
}

async function viewStoredRun(projectId, runId) {
  const res = await api.projects.search(projectId, '');
  const d = await api.projects.detail(projectId, 'research');
  const host = document.getElementById('tab-research');
  const run = (d.runs || []).find((x) => x.run_id === runId);
  if (!host || !run) return;
  const box = h('pre', { class: 'raw', id: 'stored-run-json',
    text: JSON.stringify({ run_id: run.run_id, answer_state: run.answer_state,
      is_abstention: run.is_abstention, citations: run.citation_ids,
      claims: run.claim_count, limitations: run.limitations,
      source_answer_hash: run.source_answer_hash }, null, 1) });
  host.appendChild(box);
  return res;
}

function evidenceTab(d) {
  const p = d.project;
  const card = h('div', { class: 'card', id: 'tab-evidence' }, [
    h('h2', { text: t('projects.evidence-references') }),
    h('p', { class: 'muted', text:
      t('projects.only-stable-ids-are-stored-the-passage-concept-t--full') }),
  ]);
  const groups = [['saved_passages', t('bibliography.passages'), 'passage'],
    ['saved_concepts', t('explore.concepts'), 'concept'],
    ['saved_seminars', t('bibliography.seminars'), 'seminar'],
    ['saved_terms', 'Terms', 'term']];
  for (const [field, label, kind] of groups) {
    const rows = p[field] || [];
    const g = h('div', { class: 'ref-group', id: 'refs-' + kind }, [
      h('h3', { text: `${label} (${rows.length})` }),
    ]);
    if (!rows.length) g.appendChild(muted('—'));
    else {
      const ul = h('ul', { class: 'plain-list' });
      for (const r of rows) {
        ul.appendChild(h('li', { dataset: { ref: r.id } }, [
          h('button', { class: 'link-btn', type: 'button', text: r.id,
            onclick: () => openReferent(kind, r.id) }),
          r.broken ? h('span', { class: 'tag is-warn', text: t('projects.broken-reference') }) : null,
          r.referent_label ? h('span', { class: 'muted',
            text: ' ' + String(r.referent_label).slice(0, 90) }) : null,
          r.user_note ? h('span', { class: 'rel-note', text: ' — ' + r.user_note }) : null,
          h('button', { class: 'link-btn', type: 'button', text: t('projects.remove'),
            onclick: async () => {
              await api.projects.remove(p.project_id, p.revision, kind, r.id);
              go({ view: 'project', id: p.project_id, tab: 'evidence' });
            } }),
        ]));
      }
      g.appendChild(ul);
    }
    card.appendChild(g);
  }
  return card;
}

function openReferent(kind, id) {
  if (kind === 'passage') return go({ view: 'passage', id });
  if (kind === 'concept') return go({ view: 'concept', id });
  if (kind === 'seminar') return go({ view: 'seminar', id });
  if (kind === 'term') return go({ view: 'term', term: id });
  return null;
}

function notesTab(d) {
  const p = d.project;
  const card = h('div', { class: 'card', id: 'tab-notes' }, [
    h('h2', { text: `Notes (${(p.notes || []).length})` }),
    h('p', { class: 'muted', text:
      t('projects.free-text-notes-never-enter-the-scholarly-eviden') }),
  ]);
  for (const n of p.notes || []) {
    card.appendChild(h('details', { class: 'fold', open: '', dataset: { note: n.note_id } }, [
      h('summary', { text: n.title || n.note_id }),
      h('p', { class: 'section-body', text: n.text }),
      h('span', { class: 'muted', text: (n.created_at || '').slice(0, 19) }),
    ]));
  }
  const title = h('input', { class: 'explorer-input', id: 'note-title',
    placeholder: t('projects.note-title-optional') });
  const text = h('textarea', { class: 'explorer-input', id: 'note-text', rows: 3,
    placeholder: t('projects.note-text-markdown-allowed') });
  card.appendChild(h('form', { class: 'explorer-form', onsubmit: async (e) => {
    e.preventDefault();
    await api.projects.add(p.project_id, p.revision, 'note',
      { title: title.value, text: text.value });
    go({ view: 'project', id: p.project_id, tab: 'notes' });
  } }, [title, text, h('button', { class: 'btn', type: 'submit', text: t('projects.add-note') })]));
  return card;
}

function openQuestionsTab(d) {
  const p = d.project;
  const card = h('div', { class: 'card', id: 'tab-open-questions' }, [
    h('h2', { text: `Open Questions (${(p.open_questions || []).length})` }),
    h('p', { class: 'muted', text:
      t('projects.an-open-question-is-a-research-question-with-a-r--full') }),
  ]);
  const ul = h('ul', { class: 'plain-list' });
  for (const q of p.open_questions || []) {
    ul.appendChild(h('li', { dataset: { open_question: q.question_id } }, [
      h('span', { class: 'tag is-corpus', text: q.origin }),
      q.run_id ? h('span', { class: 'muted', text: ` from ${q.run_id}` }) : null,
      h('span', { text: ' ' + q.text }),
    ]));
  }
  card.appendChild(ul);
  const text = h('input', { class: 'explorer-input', id: 'open-question-text',
    placeholder: t('projects.new-open-question') });
  card.appendChild(h('form', { class: 'explorer-form', onsubmit: async (e) => {
    e.preventDefault();
    await api.projects.add(p.project_id, p.revision, 'open_question',
      { text: text.value, origin: 'user_created' });
    go({ view: 'project', id: p.project_id, tab: 'questions_open' });
  } }, [text, h('button', { class: 'btn', type: 'submit', text: t('projects.add-open-question') })]));
  return card;
}

function hypothesesTab(d) {
  const p = d.project;
  const card = h('div', { class: 'card', id: 'tab-hypotheses' }, [
    h('h2', { text: `User hypotheses (${(p.hypotheses || []).length})` }),
    h('div', { class: 'notice is-warn' }, [
      h('h3', { text: t('projects.user-hypothesis-not-validated-by-the-scholarly-c') }),
      h('p', { text: t('projects.hypotheses-are-user-workspace-objects-they-are-n--full') })]),
  ]);
  for (const hyp of p.hypotheses || []) {
    card.appendChild(h('article', { class: 'hyp-item', dataset: { hypothesis: hyp.hypothesis_id } }, [
      h('p', { class: 'section-body', text: hyp.text }),
      h('span', { class: 'tag is-warn', text: t('projects.not-validated') }),
      h('button', { class: 'btn btn-ghost', type: 'button', text: t('projects.test-with-corpus'),
        onclick: async () => {
          const q = `请检验以下假设是否有语料支持，并给出可核证的反例或限制：${hyp.text}`;
          const res = await api.projects.research(p.project_id, p.revision, q, null);
          if (CTX.onProjectAnswer) CTX.onProjectAnswer(res);
          go({ view: 'project', id: p.project_id, tab: 'research' });
        } }),
    ]));
  }
  const text = h('input', { class: 'explorer-input', id: 'hypothesis-text',
    placeholder: t('projects.new-hypothesis-user-object') });
  card.appendChild(h('form', { class: 'explorer-form', onsubmit: async (e) => {
    e.preventDefault();
    await api.projects.add(p.project_id, p.revision, 'hypothesis', { text: text.value });
    go({ view: 'project', id: p.project_id, tab: 'hypotheses' });
  } }, [text, h('button', { class: 'btn', type: 'submit', text: t('projects.add-hypothesis') })]));
  return card;
}

function bibliographyTab(d) {
  const p = d.project;
  const pb = d.project_bibliography || {};
  const all = pb.project_bibliography_refs || [];
  const reviewed = all.filter((r) => !r.user_supplied);          // §20 组 1
  const userSupplied = all.filter((r) => r.user_supplied);        // §20 组 2
  const legacy = pb.legacy_user_supplied_refs || [];              // §20 组 3
  const notLinkable = d.bibliography_candidates_not_linkable || [];
  const card = h('div', { class: 'card', id: 'tab-bibliography' }, [
    h('h2', { text: t('projects.project-bibliography') }),
    h('p', { class: 'muted', text:
      t('projects.a-bibliographyref-is-a-user-reference-management--full--full--full') }),
  ]);

  // §20 组 1 — Reviewed references（挂接 registry，只存 stable id）
  card.appendChild(h('section', { class: 'bib-ref-group', id: 'pbg-reviewed' }, [
    h('h3', { text: `Reviewed references (${reviewed.length})` }),
    reviewed.length ? h('ul', { class: 'bib-refs' }, reviewed.map((r) => h('li', {
      'data-bib-id': r.bibliographic_id, class: 'bib-ref-row' }, [
      h('strong', { text: r.title || r.bibliographic_id }),
      h('span', { class: 'muted', text: '  ' + r.bibliographic_id + ' · '
        + (r.metadata_completeness || '—') + ' · reviewed' }),
      h('p', { class: 'muted', text: t('projects.referenced-by-id-the-registry-stays-the-source-o--full') }),
    ]))) : h('p', { class: 'muted', id: 'pbg-reviewed-empty',
      text: t('projects.no-registry-item-linked-yet-use-link-to-bibliogr') }),
  ]));

  // §20 组 2 — User-supplied references（bibliographic_id = null）
  card.appendChild(h('section', { class: 'bib-ref-group', id: 'pbg-user-supplied' }, [
    h('h3', { text: `User-supplied references (${userSupplied.length})` }),
    h('p', { class: 'muted', text: t('projects.bibliographic-id-null-user-supplied-true-stored--full') }),
    userSupplied.length ? h('ul', { class: 'bib-refs' }, userSupplied.map((r) => h('li', {
      'data-bib-id': r.bibliographic_id || '', class: 'bib-ref-row' }, [
      h('span', { text: (r.title || r.bibliographic_id || '(untitled)') }),
      h('span', { class: 'muted', text: t('projects.user-supplied-not-from-the-registry') }),
    ]))) : h('p', { class: 'muted', id: 'pbg-user-empty', text: t('projects.none') }),
  ]));

  // §20 组 3 + §21 — Unlinked legacy references（read-only adapter + 显式 Link）
  card.appendChild(h('section', { class: 'bib-ref-group', id: 'pbg-legacy' }, [
    h('h3', { text: `Unlinked legacy references (${legacy.length})` }),
    h('p', { class: 'muted', text: t('projects.read-only-adapter-for-free-text-references-creat--full') }),
    legacy.length ? h('ul', { class: 'bib-refs' }, legacy.map((r) => h('li', {
      'data-ref-id': r.ref_id, class: 'bib-ref-row' }, [
      h('span', { text: (r.title || '(untitled)') + ' — ' + (r.author || '—')
        + ' · ' + (r.year || '—') }),
      h('span', { class: 'muted', text: r.linked_bibliographic_id
        ? ('  linked → ' + r.linked_bibliographic_id)
        : '  [legacy record · not linked]' }),
      r.linked_bibliographic_id ? null : h('button', {
        type: 'button', class: 'link-btn', 'data-link-ref': r.ref_id,
        text: t('projects.link-to-bibliographic-item'),
        onclick: () => go({ view: 'project', id: p.project_id, tab: 'bibliography',
                            link_ref: r.ref_id }) }),
    ]))) : h('p', { class: 'muted', id: 'pbg-legacy-empty', text: t('projects.none') }),
  ]));

  // 说明：candidate **不可**挂接（不是第四组，只是解释为什么有些条目选不到）
  if (notLinkable.length) {
    card.appendChild(h('p', { class: 'muted', id: 'pbg-not-linkable',
      text: t('projects.not-offered-as-link-targets-because-they-are-can')
        + notLinkable.map((c) => c.bibliographic_id).join(', ') }));
  }

  // §21：显式 Link（reviewed registry 条目）
  card.appendChild(h('form', { class: 'explorer-form', id: 'pbg-link-form',
    onsubmit: async (e) => {
      e.preventDefault();
      const sel = document.getElementById('pbg-bib-select');
      if (!sel || !sel.value) return;
      await api.projects.addBibliographicItem(p.project_id, p.revision, sel.value);
      go({ view: 'project', id: p.project_id, tab: 'bibliography' });
    } }, [h('label', { for: 'pbg-bib-select', text: t('projects.link-to-bibliographic-item') }),
           linkPicker()]));

  // 用户自由输入（仍是 user_supplied，绝不自动匹配）
  const title = h('input', { class: 'explorer-input', id: 'bib-title',
    placeholder: t('explore.title') });
  const author = h('input', { class: 'explorer-input', id: 'bib-author',
    placeholder: t('projects.author-optional') });
  const year = h('input', { class: 'explorer-input', id: 'bib-year',
    placeholder: t('projects.year-optional') });
  card.appendChild(h('form', { class: 'explorer-form', onsubmit: async (e) => {
    e.preventDefault();
    await api.projects.add(p.project_id, p.revision, 'bibliography',
      { title: title.value, author: author.value, year: year.value });
    go({ view: 'project', id: p.project_id, tab: 'bibliography' });
  } }, [title, author, year,
    h('button', { class: 'btn', type: 'submit', text: t('projects.add-your-own-reference') })]));

  if (d.legacy_link_target) card.appendChild(legacyLinkForm(d));
  return card;
}

// §11：显式 Link —— 把一条 legacy 自由文本 ref 关联到 reviewed registry 条目
function legacyLinkForm(d) {
  const p = d.project;
  return h('form', { class: 'explorer-form', id: 'pbg-legacy-link-form',
    onsubmit: async (e) => {
      e.preventDefault();
      const sel = document.getElementById('pbg-legacy-target');
      if (!sel || !sel.value) return;
      await api.projects.linkLegacyRef(p.project_id, p.revision,
        d.legacy_link_target, sel.value);
      go({ view: 'project', id: p.project_id, tab: 'bibliography' });
    } }, [
    h('p', { class: 'muted', text: t('projects.link-reference') + d.legacy_link_target
      + ' to a reviewed registry item (an explicit action; the original text is kept).' }),
    linkPicker('pbg-legacy-target'),
    h('button', { class: 'btn', type: 'submit', text: t('projects.confirm-link') }),
  ]);
}

function linkPicker(id) {
  const sel = h('select', { class: 'explorer-input', id: id || 'pbg-bib-select' }, [
    h('option', { value: '', text: t('projects.select-a-reviewed-bibliographic-item') }),
    ...(CTX.reviewedItems || []).map((i) => h('option', {
      value: i.bibliographic_id,
      text: i.title + ' (' + i.bibliographic_id + ')' })),
  ]);
  return sel;
}

function activityTab(d) {
  return h('div', { class: 'card', id: 'tab-activity' }, [
    h('h2', { text: t('projects.activity') }),
    h('p', { class: 'muted', text: d.timeline.label }),
    h('ol', { class: 'chain' }, (d.timeline.items || []).map((e) => h('li', {
      class: 'chain-step' }, [
      h('span', { class: 'chain-step-name', text: e.kind }),
      h('span', { class: 'muted', text: String(e.at || '').slice(0, 19) }),
      h('span', { text: String(e.label || '').slice(0, 160) }),
    ]))),
  ]);
}

// ─────────────────────────────────────────────────────────── Add to Project（§45–§47）
export async function addToProjectDialog(opts) {
  // opts: {kind, id, label, note, runView, requestMeta, historyFile, questionId}
  const list = await api.projects.list({ status: 'ACTIVE' });
  const wrap = h('div', { class: 'card add-to-project', id: 'add-to-project' }, [
    h('h2', { text: t('explore.add-to-project') }),
    h('p', { class: 'muted', text:
      t('projects.projects-organize-references-they-are-never-evid--full') }),
  ]);
  if (!list.items.length) {
    wrap.appendChild(muted('No active project yet — create one in Projects.'));
    return wrap;
  }
  const sel = h('select', { class: 'explorer-select', id: 'add-to-project-select' },
    list.items.map((p) => h('option', { value: `${p.project_id}::${p.revision}`,
      text: `${p.title} (rev ${p.revision})` })));
  const status = h('span', { class: 'muted', id: 'add-to-project-status' });
  wrap.appendChild(h('div', { class: 'explorer-form' }, [sel,
    h('button', { class: 'btn', type: 'button', id: 'add-to-project-btn',
      text: t('projects.add'), onclick: async () => {
        const [pid, rev] = sel.value.split('::');
        status.textContent = 'Adding…';
        let res;
        if (opts.runView) {
          res = await api.projects.addRun(pid, rev, opts.runView, opts.requestMeta,
            opts.questionId);
        } else if (opts.historyFile) {
          res = await api.projects.addHistoryRun(pid, rev, opts.historyFile);
        } else {
          res = await api.projects.add(pid, rev, opts.kind,
            { id: opts.id, note: opts.note, text: opts.text });
        }
        status.textContent = (res.kind && res.kind.startsWith('project_'))
          ? `Added (${opts.kind || 'run'})` : (res.title || res.code || 'failed');
      } }), status]));
  return wrap;
}

/** QA 深链：用**过期的 revision** 真发一次 archive，把 409 的真实文案显示出来。
 *  与 4D.2 的 ?autorun=1 / 4D.4 的 ?auto=… 同一思路：它只做用户本来会做的动作。 */
async function runStaleArchive(params, project) {
  if (params.stale !== '1') return;
  const res = await api.projects.archive(project.project_id,
    Math.max(1, project.revision - 1));
  const host = document.getElementById('project-action-status');
  if (!host) return;
  host.textContent = res.title ? `${res.title} ${res.body || ''}` : (res.kind || res.code);
  const bar = host.parentElement;
  if (bar) {
    const notice = h('div', { class: 'notice is-err', id: 'revision-conflict' }, [
      h('h3', { text: res.title || 'WORKSPACE_CONFLICT' }),
      h('p', { text: res.body || '' }),
      h('p', { class: 'muted', text:
        `expected revision ${res.expected_revision} · actual ${res.actual_revision}` }),
    ]);
    bar.parentElement.appendChild(notice);
  }
}


export async function renderProjectsRoot(params) {
  const host = $('explorer');
  mount(host, h('p', { class: 'muted', text: t('explore.loading') }));
  let node;
  try {
    node = params.id ? await renderProject(params) : await renderProjects(params);
  } catch (e) {
    node = h('section', { class: 'explorer-view' }, [
      h('h1', { class: 'explorer-title', text: t('projects.project-request-failed') }),
      h('p', { class: 'section-body', text: String(e && e.message || e) })]);
  }
  mount(host, node);
  if (params.id) await runStaleArchive(params, (node && node.__project) || null
    || (await api.projects.detail(params.id, params.tab || 'overview')).project);
  document.body.dataset.projectView = params.id ? 'project' : 'projects';
  document.body.dataset.projectReady = '1';
  return node;
}
