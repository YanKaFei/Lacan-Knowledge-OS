import { t } from './i18n.js';
// api.js — 产品 API 客户端（UI → workspace_ui.server → MCP → core）
async function j(url, opts) {
  const r = await fetch(url, opts);
  const body = await r.json().catch(() => ({ kind: 'error', code: 'INTERNAL_ERROR',
    title: t('research.malformed-response'), body: 'The API returned non-JSON.' }));
  if (!r.ok && body && body.kind !== 'error') {
    return { kind: 'error', code: 'INTERNAL_ERROR', title: t('research.request-failed'),
             body: `HTTP ${r.status}`, research_disabled: false, advanced: {} };
  }
  return body;
}

export const api = {
  status: () => j('/api/status'),
  research: (payload) => j('/api/research', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  passage: (id, before, after, span) => j(
    `/api/passage?id=${encodeURIComponent(id)}&before=${before}&after=${after}` +
    (span ? `&span=${encodeURIComponent(span)}` : '')),
  context: (id, before, after) => j(
    `/api/context?id=${encodeURIComponent(id)}&before=${before}&after=${after}`),
  search: (q, limit = 10) => j(
    `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  obsidianStatus: () => j('/api/obsidian/status'),
  obsidianSaveResearch: (payload) => j('/api/obsidian/save_research', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  obsidianSavePassage: (passageId) => j('/api/obsidian/save_passage', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ passage_id: passageId }),
  }),
  obsidianList: () => j('/api/obsidian/list'),
  history: (limit = 50, offset = 0) => j(`/api/history?limit=${limit}&offset=${offset}`),
  historyItem: (file) => j(`/api/history/item?file=${encodeURIComponent(file)}`),

  // ── 真实 provider（产品层设置 / 连通性自检 / 长请求作业化）
  providerSettings: () => j('/api/provider/settings'),
  providerSave: (payload) => j('/api/provider/settings', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  providerTest: (payload = {}) => j('/api/provider/test', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  researchJob: (payload) => j('/api/research/job', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  researchJobStatus: (id, withResult = false) => j(
    `/api/research/job?id=${encodeURIComponent(id)}${withResult ? '&result=1' : ''}`),

  // ── Explorer（4D.4，只读浏览）
  explore: (path, params = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v === null || v === undefined || v === '') continue;
      qs.set(k, String(v));
    }
    const s = qs.toString();
    return j(`/api/explore/${path}${s ? '?' + s : ''}`);
  },
  exploreCreateNote: (entityType, entityId) => j('/api/explore/obsidian_create', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
  }),

  // ── Research Projects（4D.5）：写入只经 project_api → USER_WORKSPACE
  projects: {
    list: (params = {}) => {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v) qs.set(k, String(v));
      const s2 = qs.toString();
      return j(`/api/projects${s2 ? '?' + s2 : ''}`);
    },
    detail: (id, tab = 'overview') => j(
      `/api/projects/detail?id=${encodeURIComponent(id)}&tab=${encodeURIComponent(tab)}`),
    verify: (id) => j(`/api/projects/verify?id=${encodeURIComponent(id)}`),
    search: (id, query) => j(
      `/api/projects/search?id=${encodeURIComponent(id)}&query=${encodeURIComponent(query)}`),
    compare: (id, a, b) => j(`/api/projects/compare?id=${encodeURIComponent(id)}` +
      `&a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
    manifest: (id) => j(`/api/projects/manifest?id=${encodeURIComponent(id)}`),
    create: (payload) => j('/api/projects/create', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload) }),
    update: (payload) => j('/api/projects/update', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload) }),
    archive: (id, expectedRevision) => j('/api/projects/archive', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: id, expected_revision: expectedRevision }) }),
    restore: (id, expectedRevision) => j('/api/projects/restore', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: id, expected_revision: expectedRevision }) }),
    add: (id, expectedRevision, kind, payload) => j('/api/projects/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: id, expected_revision: expectedRevision,
        kind, payload }) }),
    remove: (id, expectedRevision, kind, itemId) => j('/api/projects/remove', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: id, expected_revision: expectedRevision,
        kind, item_id: itemId }) }),
    addRun: (id, expectedRevision, view, requestMeta, questionId) => j('/api/projects/add_run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: id, expected_revision: expectedRevision, view,
        request_meta: requestMeta || null, project_question_id: questionId || null }) }),
    addHistoryRun: (id, expectedRevision, file) => j('/api/projects/add_history_run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: id, expected_revision: expectedRevision, file }) }),
    research: (id, expectedRevision, question, questionId, extra = {}) => j(
      '/api/projects/research', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: id, expected_revision: expectedRevision,
          question, project_question_id: questionId || null, ...extra }) }),
    obsidianSync: (id) => j('/api/projects/obsidian_sync', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: id }) }),
    addBibliographicItem: (id, expectedRevision, bibliographicId, userNote) => j(
      '/api/projects/add_bibliographic_item', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: id, expected_revision: expectedRevision,
          bibliographic_id: bibliographicId, user_note: userNote || null }) }),
    linkLegacyRef: (id, expectedRevision, refId, bibliographicId) => j(
      '/api/projects/link_legacy_ref', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: id, expected_revision: expectedRevision,
          ref_id: refId, bibliographic_id: bibliographicId }) }),
  },

  // ── Export & Citation（4D.6）：citation 只能由 formatter 生成
  exportMenu: () => j('/api/export/menu'),
  exportPreview: (payload) => j('/api/export/preview', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload) }),
  exportRun: (payload) => j('/api/export/run', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload) }),
  exportCitation: (id, style) => j(
    `/api/export/citation?id=${encodeURIComponent(id)}` +
    (style ? `&style=${encodeURIComponent(style)}` : '')),
  exportVerify: (path) => j(`/api/export/verify?path=${encodeURIComponent(path)}`),
  exportList: () => j('/api/export/list'),
};
