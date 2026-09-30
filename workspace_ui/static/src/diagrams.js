// diagrams.js — P5D-005 UI 升级：产品内**原生 SVG 示意图**（Home hero / Help Center）。
//
// 为什么不用 <img src="*.svg">：
//   * 语言切换必须**即时**（P5D-004：不刷新页面即可见变化）。图片里的文字是烘焙死的，
//     英文图会留在中文界面上；
//   * 单一词典纪律：所有可见文字都走 t(字面量 key)（**不做变量拼 key**，
//     否则 build_i18n.py --check 看不见调用点，diagram 审计无法逐条核对）；
//   * 主题一致性：颜色全部走 main.css 的 `--bg/--ink/--line/--accent` 变量，
//     图与正文永远不会两套色。
//
// 尺寸纪律（**这条决定字看不看得清**）：
//   viewBox 宽度按它在页面里的**真实渲染宽度**取（Help 正文列 ≈ 600，首页 hero ≈ 900），
//   于是缩放系数 ≈ 1.0，字号就是屏幕上量到的字号 —— 不是被压扁的 0.8 倍。
//
// 纪律：
//   * **所有 key 都是字面量**（形如 diagram.<图名>.<字段>），无动态拼接；
//   * 机器 token（段号/课次 id/witness id/API 路径/状态名）是 §17 Layer B：
//     其词典条目 status = intentional_source_text（en = zh = 原样），**不翻译**；
//   * 位置坐标全部写死（无测量、无随机），同一份代码在任何机器上像素一致。
import { t } from './i18n.js';

const NS = 'http://www.w3.org/2000/svg';

/** 产品内置示意图的名字（服务端 help_view.DIAGRAMS 必须与此一致，测试守这条边界）。 */
export const DIAGRAM_NAMES = ['architecture', 'evidence-chain', 'workflow'];

function node(tag, attrs = {}) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    el.setAttribute(k, String(v));
  }
  return el;
}

/** 面板 / 线 / 箭头 / 文字（文字**只**用 textContent，值来自 t()）。 */
const box = (x, y, w, h, tone) => node('rect', {
  x, y, width: w, height: h, rx: 6,
  class: 'd-panel' + (tone ? ' is-' + tone : '') });
const rule = (x1, y, x2) => node('path', { d: `M${x1} ${y} H ${x2}`, class: 'd-rule' });
const txt = (x, y, value, cls, anchor) => {
  const el = node('text', { x, y, class: cls,
    'text-anchor': anchor === 'end' ? 'end' : null });
  el.textContent = String(value);
  return el;
};

function canvas(name, w, h, alt) {
  const svg = node('svg', {
    viewBox: `0 0 ${w} ${h}`, class: 'diagram diagram-' + name, role: 'img',
    'aria-label': alt, focusable: 'false', xmlns: NS });
  const mid = 'd-arrow-' + name;
  const marker = node('marker', { id: mid, viewBox: '0 0 10 10', refX: 8, refY: 5,
    markerWidth: 6, markerHeight: 6, orient: 'auto' });
  marker.appendChild(node('path', { d: 'M0 0 L10 5 L0 10 z', class: 'd-arrow-head' }));
  const defs = node('defs');
  defs.appendChild(marker);
  svg.appendChild(defs);
  const arrow = (d) => node('path', { d, class: 'd-arrow', 'marker-end': `url(#${mid})` });
  return { svg, arrow };
}

// ── 1. workflow（首页 hero；viewBox 900 ≈ 渲染宽度）
//    六个步骤一行（每步 137px：序号 / 名称 / 一句说明 / 路由）+ 两栏结果面板。
function workflow() {
  const { svg, arrow } = canvas('workflow', 900, 262,
    t('diagram.workflow.alt'));
  const W = 137, GAP = 15, Y = 22, H = 104;
  const xs = [0, 1, 2, 3, 4, 5].map((i) => 2 + i * (W + GAP));

  // 逐条字面量调用（**不**用 t(变量)），i18n 审计要看得见每个调用点。
  const titles = [
    t('diagram.workflow.step.1.title'), t('diagram.workflow.step.2.title'),
    t('diagram.workflow.step.3.title'), t('diagram.workflow.step.4.title'),
    t('diagram.workflow.step.5.title'), t('diagram.workflow.step.6.title'),
  ];
  const subs = [
    t('diagram.workflow.step.1.sub'), t('diagram.workflow.step.2.sub'),
    t('diagram.workflow.step.3.sub'), t('diagram.workflow.step.4.sub'),
    t('diagram.workflow.step.5.sub'), t('diagram.workflow.step.6.sub'),
  ];
  const routes = [
    t('diagram.workflow.step.1.route'), t('diagram.workflow.step.2.route'),
    t('diagram.workflow.step.3.route'), t('diagram.workflow.step.4.route'),
    t('diagram.workflow.step.5.route'), t('diagram.workflow.step.6.route'),
  ];
  xs.forEach((x, i) => {
    svg.appendChild(box(x, Y, W, H, i === 0 ? 'accent' : null));
    svg.appendChild(txt(x + 14, Y + 26, String(i + 1).padStart(2, '0'), 'd-num'));
    svg.appendChild(txt(x + 14, Y + 52, titles[i], 'd-h'));
    svg.appendChild(txt(x + 14, Y + 72, subs[i], 'd-s'));
    svg.appendChild(txt(x + 14, Y + 90, routes[i], 'd-mono'));
    if (i < xs.length - 1) svg.appendChild(arrow(`M${x + W + 2} 74 H ${x + W + 13}`));
  });

  const panels = [
    [2, null, 'supported'],
    [455, 'warn', 'nonanswer'],
  ];
  const rows = [
    [t('diagram.workflow.supported.title'), 'd-h'],
    [t('diagram.workflow.supported.tokens1'), 'd-mono'],
    [t('diagram.workflow.supported.tokens2'), 'd-mono'],
    [t('diagram.workflow.supported.note'), 'd-note'],
  ];
  const rows2 = [
    [t('diagram.workflow.nonanswer.title'), 'd-h'],
    [t('diagram.workflow.nonanswer.tokens1'), 'd-mono'],
    [t('diagram.workflow.nonanswer.tokens2'), 'd-mono'],
    [t('diagram.workflow.nonanswer.note'), 'd-note'],
  ];
  panels.forEach(([x, tone], i) => {
    svg.appendChild(box(x, 146, 443, 104, tone));
    const r = i === 0 ? rows : rows2;
    svg.appendChild(txt(x + 16, 172, r[0][0], r[0][1]));
    svg.appendChild(txt(x + 16, 196, r[1][0], r[1][1]));
    svg.appendChild(txt(x + 16, 214, r[2][0], r[2][1]));
    svg.appendChild(txt(x + 16, 238, r[3][0], r[3][1]));
  });
  return svg;
}

// ── 2. evidence-chain（Help › Evidence；viewBox 600 ≈ 正文列宽）
//    四条纵列卡片（答案 → 断言 → 段落 → 课次），下面见证本、再下面证据检查器。
function evidenceChain() {
  const { svg, arrow } = canvas('evidence-chain', 600, 556,
    t('diagram.evidence-chain.alt'));
  svg.appendChild(txt(4, 20, t('diagram.evidence-chain.title'), 'd-title'));

  const cards = [
    [34, 'accent', t('diagram.evidence-chain.answer.title'),
      t('diagram.evidence-chain.answer.sub'), null],
    [104, null, t('diagram.evidence-chain.claim.title'),
      t('diagram.evidence-chain.claim.sub'), null],
    [174, 'accent', t('diagram.evidence-chain.passage.title'),
      t('diagram.evidence-chain.passage.sub'),
      t('diagram.evidence-chain.passage.id')],
    [244, null, t('diagram.evidence-chain.session.title'),
      t('diagram.evidence-chain.session.sub'),
      t('diagram.evidence-chain.session.id')],
  ];
  cards.forEach(([y, tone, title, sub, id]) => {
    svg.appendChild(box(4, y, 592, 54, tone));
    svg.appendChild(txt(20, y + 24, title, 'd-h'));
    svg.appendChild(txt(20, y + 42, sub, 'd-s'));
    if (id) svg.appendChild(txt(580, y + 33, id, 'd-mono', 'end'));
    if (y > 34) svg.appendChild(arrow(`M300 ${y - 16} V ${y - 2}`));
  });

  svg.appendChild(box(4, 316, 592, 104));
  svg.appendChild(txt(20, 340, t('diagram.evidence-chain.witness.title'), 'd-h'));
  svg.appendChild(txt(20, 360, t('diagram.evidence-chain.witness.sub'), 'd-s'));
  svg.appendChild(txt(20, 378, t('diagram.evidence-chain.witness.ids1'), 'd-mono'));
  svg.appendChild(txt(20, 394, t('diagram.evidence-chain.witness.ids2'), 'd-mono'));
  svg.appendChild(txt(20, 412, t('diagram.evidence-chain.witness.warn'), 'd-warn'));

  svg.appendChild(box(4, 436, 592, 112));
  svg.appendChild(txt(20, 460, t('diagram.evidence-chain.inspector.title'), 'd-h'));
  svg.appendChild(txt(20, 482, t('diagram.evidence-chain.inspector.sub'), 'd-s'));
  svg.appendChild(txt(20, 502, t('diagram.evidence-chain.inspector.api'), 'd-mono'));
  svg.appendChild(txt(20, 524, t('diagram.evidence-chain.inspector.note1'), 'd-note'));
  svg.appendChild(txt(20, 540, t('diagram.evidence-chain.inspector.note2'), 'd-note'));
  return svg;
}

// ── 3. architecture（Help 首页；viewBox 600 ≈ 正文列宽）
//    竖排四层：进入界面 → 产品层 → 边界 → 冻结内核 → 语料。
function architecture() {
  const { svg, arrow } = canvas('architecture', 600, 556,
    t('diagram.architecture.alt'));

  svg.appendChild(box(4, 12, 592, 76));
  svg.appendChild(txt(20, 36, t('diagram.architecture.agents.title'), 'd-h'));
  svg.appendChild(txt(20, 56, t('diagram.architecture.agents.sub'), 'd-s'));
  svg.appendChild(txt(20, 74, t('diagram.architecture.agents.mono1'), 'd-mono'));
  svg.appendChild(txt(200, 74, t('diagram.architecture.agents.mono2'), 'd-mono'));
  svg.appendChild(arrow('M300 88 V 102'));

  svg.appendChild(box(4, 102, 592, 76));
  svg.appendChild(txt(20, 126, t('diagram.architecture.entry.title'), 'd-h'));
  svg.appendChild(txt(20, 146, t('diagram.architecture.entry.mono1'), 'd-mono'));
  svg.appendChild(txt(240, 146, t('diagram.architecture.entry.mono2'), 'd-mono'));
  svg.appendChild(txt(20, 164, t('diagram.architecture.entry.mono3'), 'd-mono'));
  svg.appendChild(arrow('M300 178 V 192'));

  svg.appendChild(box(4, 192, 592, 104));
  svg.appendChild(txt(20, 216, t('diagram.architecture.product.title'), 'd-h'));
  svg.appendChild(txt(20, 236, t('diagram.architecture.product.sub'), 'd-s'));
  svg.appendChild(txt(20, 254, t('diagram.architecture.product.paths1'), 'd-mono'));
  svg.appendChild(txt(20, 270, t('diagram.architecture.product.paths2'), 'd-mono'));
  svg.appendChild(txt(20, 288, t('diagram.architecture.product.note'), 'd-note'));

  svg.appendChild(rule(4, 312, 596));
  svg.appendChild(txt(20, 330, t('diagram.architecture.boundary'), 'd-mono d-accent'));

  svg.appendChild(box(4, 340, 592, 96, 'core'));
  svg.appendChild(txt(20, 364, t('diagram.architecture.core.title'), 'd-h'));
  svg.appendChild(txt(20, 384, t('diagram.architecture.core.sub'), 'd-s'));
  svg.appendChild(txt(20, 404, t('diagram.architecture.core.verify1'), 'd-mono'));
  svg.appendChild(txt(20, 420, t('diagram.architecture.core.verify2'), 'd-mono'));
  svg.appendChild(arrow('M300 436 V 450'));

  svg.appendChild(box(4, 450, 592, 98, 'warn'));
  svg.appendChild(txt(20, 474, t('diagram.architecture.corpus.title'), 'd-h'));
  svg.appendChild(txt(20, 494, t('diagram.architecture.corpus.sub'), 'd-s'));
  svg.appendChild(txt(20, 514, t('diagram.architecture.corpus.note1'), 'd-warn'));
  svg.appendChild(txt(20, 532, t('diagram.architecture.corpus.note2'), 'd-warn'));
  return svg;
}

const BUILD = {
  architecture,
  'evidence-chain': evidenceChain,
  workflow,
};

/** 拿一个示意图元素；未知名字返回 null（**不抛**异常，避免整页崩掉）。 */
export function diagram(name) {
  const fn = BUILD[String(name)];
  return fn ? fn() : null;
}
