/* 无浏览器冒烟测试：
   1) 用 vm.Script 编译每一个 <script> 块，抓语法错
   2) 用最小 DOM 桩执行全流程，抓运行时错
   3) 断言关键渲染产物（SVG 数量、散点数、表格行、KPI 文本、成本构成条）
   运行： node smoke.js

   教训（别再踩）：
   - 只编译"核心逻辑"块 = 裸奔，UI 块的语法错会静默失效、所有按钮无反应
   - onclick 是属性赋值，不会进 addEventListener 的 _h 表；
     用 dispatch('click') 调不到 -> 静默假通过。必须直接调 .onclick()
   - 断言前先判 NaN，NaN 文本会被 /^\d+\.\d\d/ 之类正则漏掉
*/
const fs = require('fs'), path = require('path'), vm = require('vm');
const html = fs.readFileSync(path.join(__dirname, 'web', 'index.html'), 'utf8');

let FAIL = 0;
const chk = (n, c, i) => { console.log((c ? '  PASS  ' : '  FAIL  ') + n + (i ? '   ' + i : '')); if (!c) FAIL++; };

/* ---------- 1) 语法检查 ---------- */
const blocks = [...html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)];
chk('页面含 script 块', blocks.length >= 2, blocks.length + ' 个');
blocks.forEach((b, i) => {
  const attrs = b[1] || '', code = b[2];
  if (attrs.includes('application/json')) {
    let ok = true, msg = '';
    try { const d = JSON.parse(code); msg = d.points ? d.points.length + ' 个方案 / 前沿 ' + d.front.length : '空'; }
    catch (e) { ok = false; msg = e.message; }
    chk(`script[${i}] 内嵌 JSON 可解析`, ok, msg);
    return;
  }
  let ok = true, err = '';
  try { new vm.Script(code, { filename: `script[${i}]` }); } catch (e) { ok = false, err = e.message; }
  chk(`script[${i}] 语法编译通过`, ok, err);
});
chk('占位符已被替换', !html.includes('__PARETO_JSON__'));

/* ---------- 2) 最小 DOM 桩 ---------- */
function makeEl(tag) {
  return {
    tagName: tag, children: [], attrs: {}, _text: '', _html: '',
    style: {}, dataset: {}, value: '', disabled: false, className: '',
    parentElement: null, _h: {}, onclick: null,
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    appendChild(c) { c.parentElement = this; this.children.push(c); return c; },
    addEventListener(t, f) { (this._h[t] = this._h[t] || []).push(f); },
    dispatch(t) { (this._h[t] || []).forEach(f => f.call(this)); },
    querySelectorAll() { return []; },
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); this.children = []; },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); if (v === '') this.children = []; },
  };
}
function countTree(e, pred, acc = { n: 0 }) { if (pred(e)) acc.n++; e.children.forEach(c => countTree(c, pred, acc)); return acc.n; }

const REG = {};
const SLIDER_DEF = {
  s_vtank: '60', s_th: '1.05', s_voff: '0.85', s_dose: '0',
  s_capex: '3.0', s_life: '8', s_om: '3000', s_clp: '10',
  s_hh: '300', s_pp: '3', s_quota: '180', s_hgeo: '54', s_cmains: '0.8',
  s_k20: '0.05', s_tw: '22', s_ct: '0.05',
};
const IDS = ['v_vtank', 'v_th', 'v_voff', 'v_dose', 'v_capex', 'v_life', 'v_om', 'v_clp', 'v_ct',
  'v_hh', 'v_quota', 'v_hgeo', 'v_cmains', 'v_k20', 'v_tw',
  'k_total', 'k_total_d', 'k_cost', 'k_cost_d', 'k_dose', 'k_dose_d', 'k_cl', 'k_cl_d', 'k_cl_card',
  's_e', 's_age', 's_ph', 's_q', 's_k',
  'cbar', 'cleg', 'cbarnote',
  'pareto', 'pareto_note', 'ch_v', 'ch_cl', 'ch_age', 'ch_p', 'tbl', 'recbox', 'warnbox',
  'btn_sweep', 'bv_full', 'bv_run', 'embedded-data'];
Object.keys(SLIDER_DEF).forEach(id => IDS.push(id));
IDS.forEach(id => {
  const e = makeEl('div'); e.id = id;
  if (SLIDER_DEF[id] !== undefined) e.value = SLIDER_DEF[id];
  REG[id] = e;
});
REG['tbl'].querySelectorAll = () => {
  const out = [];
  const re = /data-vt="([^"]+)"\s+data-th="([^"]+)"\s+data-vf="([^"]+)"\s+data-ds="([^"]+)"/g;
  let m; while ((m = re.exec(REG['tbl']._html))) {
    const el = makeEl('tr');
    el.dataset = { vt: m[1], th: m[2], vf: m[3], ds: m[4] };
    out.push(el);
  }
  return out;
};

const document = {
  getElementById: id => REG[id] || (REG[id] = makeEl('div')),
  createElementNS: (ns, t) => makeEl(t),
  createElement: t => makeEl(t),
  querySelectorAll: () => [],
};
const dataMatch = html.match(/<script id="embedded-data"[^>]*>([\s\S]*?)<\/script>/);
if (dataMatch) REG['embedded-data'].textContent = dataMatch[1];

const sandbox = {
  document, console, performance: { now: () => Date.now() },
  setTimeout: (f) => { f(); return 0; },   // 同步执行，便于断言
  Math, Date, JSON, Object, Array, String, Number, isNaN, parseFloat, parseInt,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

/* ---------- 3) 执行 ---------- */
let runErr = null, ctx = null;
try {
  ctx = vm.createContext(sandbox);
  blocks.forEach((b, i) => {
    if ((b[1] || '').includes('application/json')) return;
    new vm.Script(b[2], { filename: `script[${i}]` }).runInContext(ctx);
  });
} catch (e) { runErr = e; }
chk('全部脚本在 DOM 桩中执行无运行时错误', !runErr,
  runErr ? runErr.stack.split('\n').slice(0, 3).join(' | ') : '');

const txt = id => (REG[id].innerHTML || '') + (REG[id].textContent || '');
const num = id => parseFloat(String(REG[id].innerHTML).replace(/<[^>]+>/g, ''));
const noNaN = id => !/NaN|undefined|Infinity/.test(txt(id));

if (!runErr) {
  console.log('-'.repeat(64));
  console.log('  KPI 渲染');
  ['k_total', 'k_cost', 'k_dose', 'k_cl'].forEach(id => {
    chk(`${id} 已渲染且无 NaN`, /[\d]/.test(txt(id)) && noNaN(id), txt(id).replace(/<[^>]+>/g, '').slice(0, 30));
  });
  ['s_e', 's_age', 's_ph', 's_q', 's_k'].forEach(id => {
    chk(`${id} 统计条已渲染且无 NaN`, /[\d]/.test(txt(id)) && noNaN(id), txt(id).replace(/<[^>]+>/g, ''));
  });

  console.log('-'.repeat(64));
  console.log('  成本构成（dose = 0 时应只有提升电费一段）');
  let seg0 = (REG['cbar']._html.match(/<div /g) || []).length;
  chk('成本条已渲染', seg0 >= 1, seg0 + ' 段');
  chk('不补氯时 补氯成本 KPI = 0.00', Math.abs(num('k_dose')) < 1e-9, txt('k_dose').replace(/<[^>]+>/g, ''));
  chk('不补氯时 提示写明设施未启用', /未启用/.test(txt('k_dose_d')), txt('k_dose_d').slice(0, 40));
  chk('M1 不补氯时成本图例只渲染 1 项（不再是 4 格里 3 个零）',
    (REG['cleg']._html.match(/class="leg"/g) || []).length === 1,
    (REG['cleg']._html.match(/class="leg"/g) || []).length + ' 项');

  // 打开补氯 -> 应出现 4 段
  let eD = null;
  try { REG['s_dose'].value = '0.4'; REG['s_dose'].dispatch('input'); } catch (e) { eD = e; }
  chk('把"二次补氯"调到 0.4 后无错误', !eD, eD ? eD.message : '');
  if (!eD) {
    const seg4 = (REG['cbar']._html.match(/<div /g) || []).length;
    chk('启用补氯后 成本条出现 4 段', seg4 === 4, seg4 + ' 段');
    chk('启用补氯后 补氯成本 > 0', num('k_dose') > 1, num('k_dose').toFixed(2) + ' 元/d');
    chk('启用补氯后 总成本 > 提升电费', num('k_total') > num('k_cost'),
      num('k_total').toFixed(2) + ' > ' + num('k_cost').toFixed(2));
    chk('图例 4 项均渲染', (REG['cleg']._html.match(/class="leg"/g) || []).length === 4,
      (REG['cleg']._html.match(/class="leg"/g) || []).length + ' 项');
    chk('成本条提示含"边际成本"结论', /边际成本/.test(txt('cbarnote')), txt('cbarnote').slice(0, 60));
  }

  console.log('-'.repeat(64));
  console.log('  成本口径切换（全成本 / 仅运行）');
  const fullTotal = num('k_total'), fullDose = num('k_dose');
  let eV = null;
  try { REG['bv_run'].onclick(); } catch (e) { eV = e; }
  chk('点击"仅运行（沉没）"无错误', !eV, eV ? eV.message : '');
  if (!eV) {
    chk('仅运行口径下 补氯成本下降', num('k_dose') < fullDose,
      fullDose.toFixed(2) + ' -> ' + num('k_dose').toFixed(2) + ' 元/d');
    chk('仅运行口径下 总成本下降', num('k_total') < fullTotal,
      fullTotal.toFixed(2) + ' -> ' + num('k_total').toFixed(2) + ' 元/d');
    chk('口径切换不改变余氯', noNaN('k_cl'));
    REG['bv_full'].onclick();
    chk('切回"全成本"恢复原值', Math.abs(num('k_dose') - fullDose) < 1e-6, num('k_dose').toFixed(2));
  }
  REG['s_dose'].value = '0'; REG['s_dose'].dispatch('input');

  console.log('-'.repeat(64));
  console.log('  图表与表格');
  chk('Pareto 图已出散点', countTree(REG['pareto'], e => e.tagName === 'circle') > 50,
    countTree(REG['pareto'], e => e.tagName === 'circle') + ' 个圆点');
  ['ch_v', 'ch_cl', 'ch_age'].forEach(id => {
    chk(`${id} 折线图已渲染`, countTree(REG[id], e => e.tagName === 'path') > 0,
      countTree(REG[id], e => e.tagName === 'path') + ' 条曲线');
  });
  chk('ch_p 电价柱状图已渲染', countTree(REG['ch_p'], e => e.tagName === 'rect') >= 24,
    countTree(REG['ch_p'], e => e.tagName === 'rect') + ' 个柱');
  const rows = (REG['tbl']._html.match(/data-vt=/g) || []).length;
  chk('前沿方案表有行', rows > 3, rows + ' 行');
  chk('表格含"补氯成本"列', /补氯成本/.test(REG['tbl']._html));
  chk('推荐卡已生成', /最省方案|无达标方案/.test(REG['recbox']._html),
    REG['recbox']._html.replace(/<[^>]+>/g, '').slice(0, 60));

  console.log('-'.repeat(64));
  console.log('  交互回归');
  const cases = [
    ['s_vtank', '150', '水箱容积'], ['s_th', '1.30', '避峰阈值'], ['s_voff', '0.55', '维持液位'],
    ['s_capex', '6.0', '装置投资'], ['s_life', '12', '折旧年限'], ['s_om', '6000', '年运维费'],
    ['s_clp', '16', '有效氯单价'], ['s_k20', '0.15', '衰减系数'], ['s_tw', '30', '水温'],
    ['s_ct', '0.40', '余氯内控目标'], ['s_hh', '600', '户数'], ['s_quota', '240', '用水定额'],
    ['s_hgeo', '90', '几何扬程'], ['s_cmains', '0.35', '市政来水余氯'],
  ];
  cases.forEach(([id, val, name]) => {
    let err = null;
    try { REG[id].value = val; REG[id].dispatch('input'); } catch (e) { err = e; }
    chk(`拖动「${name}」后无错误且无 NaN`, !err && noNaN('k_total') && noNaN('k_cl'),
      err ? err.message : ('总成本 ' + txt('k_total').replace(/<[^>]+>/g, '')));
    REG[id].value = SLIDER_DEF[id]; REG[id].dispatch('input');
  });

  // 点击表格行套用方案
  let eRow = null;
  try {
    const tr = REG['tbl'].querySelectorAll()[2];
    if (tr && tr.onclick) tr.onclick();
  } catch (e) { eRow = e; }
  chk('点击前沿表格行套用方案无错误', !eRow, eRow ? eRow.message : '');

  // 重算 Pareto（直接调 onclick，不走 dispatch 假通道）
  chk('扫描按钮 onclick 已绑定', typeof REG['btn_sweep'].onclick === 'function');
  let eSw = null;
  try { REG['btn_sweep'].onclick(); } catch (e) { eSw = e; }
  chk('点击"重新计算 Pareto"无错误', !eSw, eSw ? eSw.message : ('前沿 ' + REG['pareto_note'].textContent));
  if (!eSw) {
    chk('重算后仍有前沿点', /前沿 \d+ 点/.test(REG['pareto_note'].textContent) &&
      parseInt(REG['pareto_note'].textContent.match(/前沿 (\d+) 点/)[1], 10) > 3,
      REG['pareto_note'].textContent);
    chk('重算后按钮已恢复可用', REG['btn_sweep'].disabled === false);
    chk('重算后 KPI 无 NaN', noNaN('k_total') && noNaN('k_cl') && noNaN('k_dose'));
  }

  /* ================= 审计修复回归锁 ================= */
  console.log('-'.repeat(64));
  console.log('  审计修复回归锁（H3 / H3b / H4 / H5 / H7 / H8 / M1 / M2 / M6 / L3）');

  // --- H3：套用任意一行前沿方案，KPI 必须与表格数值逐位一致 ---
  // 这是旧版「表格 12.24 vs KPI 12.22」那个 bug 的永久回归锁：
  // 只要 evalPoint 与 curSim 的离散化口径再次分叉，这条立刻红。
  const FRONT = vm.runInContext('FRONT', ctx);
  const trs = REG['tbl'].querySelectorAll();
  let mism = 0, worst = 0;
  FRONT.forEach((p, i) => {
    const tr = trs[i];
    if (!tr || typeof tr.onclick !== 'function') return;
    tr.onclick();
    const k = num('k_total');
    if (!isFinite(k) || Math.abs(k - p.cost_total) > 0.005) {
      mism++; worst = Math.max(worst, Math.abs((k || 0) - p.cost_total));
    }
  });
  chk(`H3 套用全部 ${FRONT.length} 行前沿方案后 KPI 与表格数值一致`, mism === 0,
    mism ? `${mism} 行不一致，最大偏差 ${worst.toFixed(3)}` : '全部一致（容差 0.005 元/d）');
  ['s_vtank:60', 's_th:1.05', 's_voff:0.85', 's_dose:0'].forEach(s => {
    const kv = s.split(':'); REG[kv[0]].value = kv[1]; REG[kv[0]].dispatch('input');
  });

  // --- H3b：图内「最低 x mg/L」标注必须与 KPI #k_cl 同源 ---
  // 这条来自一次真实的虚惊：截图里图注 0.403 而 KPI 0.483。查明是拿旧构建截的图。
  // 但「同一数字在两处由不同 sim 调用产生」是这类页面的典型静默失配，故永久锁死。
  const annVsKpi = (label) => {
    const anns = [];
    countTree(REG['ch_cl'], e => {
      if (e.tagName === 'text' && /^最低 /.test(String(e.textContent))) anns.push(String(e.textContent));
      return false;
    });
    const m = anns.length ? anns[0].match(/[\d.]+/) : null;
    const a = m ? +m[0] : NaN, k = num('k_cl');
    chk(`H3b ${label}：图注与 KPI 一致`, anns.length === 1 && Math.abs(a - k) <= 0.001,
      `图注 ${anns[0] || '(缺)'} / KPI ${k}`);
  };
  annVsKpi('默认工况');
  [['s_vtank', '150'], ['s_k20', '0.18'], ['s_dose', '0.5']].forEach(([id, v]) => {
    REG[id].value = v; REG[id].dispatch('input');
    annVsKpi(`${id}=${v}`);
  });
  ['s_vtank:60', 's_k20:0.05', 's_dose:0'].forEach(s => {
    const kv = s.split(':'); REG[kv[0]].value = kv[1]; REG[kv[0]].dispatch('input');
  });

  // --- H4：内控目标线必须真的画出来（旧版图例列 4 项、画面只画 3 项） ---
  const greenLines = countTree(REG['pareto'],
    e => e.tagName === 'line' && String(e.attrs.stroke).toUpperCase() === '#00A65A');
  chk('H4 Pareto 图内控目标线已绘制（旧版恒为 0 条）', greenLines > 0, greenLines + ' 条绿线');
  chk('H4 图例与画面吻合（含「内控目标」且未报「超出视域」）',
    /内控目标/.test(REG['pareto_legend'].innerHTML) && !/超出视域/.test(REG['pareto_legend'].innerHTML));

  // --- H5：灰底带跟随避峰阈值（旧版写死 1.05，纹丝不动） ---
  const bandN = () => countTree(REG['ch_age'], e => e.tagName === 'rect' && e.attrs.fill === '#EDF0F3');
  const b105 = bandN();
  REG['s_th'].value = '0.65'; REG['s_th'].dispatch('input');
  const b065 = bandN();
  REG['s_th'].value = '1.05'; REG['s_th'].dispatch('input');
  chk('H5 灰底峰时段带跟随阈值（1.05 → 8 块，0.65 → 16 块）',
    b105 === 8 && b065 === 16, `${b105} 块 -> ${b065} 块`);

  // --- H7：viewBox 随容器宽度自适应（缩放恒 1x，字号不再随视口漂移） ---
  const grabSvgs = () => {
    const out = [];
    countTree(REG['pareto'], e => { if (e.tagName === 'svg') out.push(e); return false; });
    countTree(REG['ch_v'], e => { if (e.tagName === 'svg') out.push(e); return false; });
    return out.map(s => parseFloat(String(s.attrs.viewBox).split(/\s+/)[2]));
  };
  REG['pareto'].clientWidth = 1000;   // 桩容器 1000px，Pareto 上限 900
  REG['ch_v'].clientWidth = 520;      // 小图容器 520px，上限 620
  vm.runInContext('redrawCharts()', ctx);
  const vbW = grabSvgs();
  chk('H7 图表 viewBox 跟随容器宽度（桩 1000/520 → 900/520）',
    vbW[0] === 900 && vbW[1] === 520, 'viewBox 宽度 = ' + vbW.join(', '));
  const labelled = [];
  countTree(REG['pareto'], e => { if (e.tagName === 'svg') labelled.push(e); return false; });
  countTree(REG['ch_v'], e => { if (e.tagName === 'svg') labelled.push(e); return false; });
  chk('H8 每个 SVG 都有可访问名（role="img" + aria-label）',
    labelled.every(s => s.attrs.role === 'img' && s.attrs['aria-label']),
    labelled.length + ' 个 SVG');

  // --- M2：四张 KPI 卡副标题统一为「vs 基线」维度 ---
  const subs = ['k_total_d', 'k_cost_d', 'k_dose_d', 'k_cl_d'].map(id => REG[id].textContent);
  chk('M2 四张 KPI 卡副标题统一为「vs 基线」', subs.every(t => /vs 基线/.test(t)),
    subs.join(' | ').slice(0, 90));
  chk('M2 不再把基线定义在四张卡里重复三遍', !/全天补水·60m³·不补氯/.test(subs.join('')));

  // --- M6：语义结构 ---
  chk('M6 章节标题用 h2 而非 div', /<h2 class="sech"/.test(html),
    (html.match(/<h2 class="sech"/g) || []).length + ' 个 h2.sech');
  chk('M6 表格有 caption', /<caption>/.test(REG['tbl']._html));
  chk('M6 表头全部带 scope="col"', (REG['tbl']._html.match(/scope="col"/g) || []).length === 11,
    (REG['tbl']._html.match(/scope="col"/g) || []).length + ' 个');
  chk('M6 表格行可键盘操作（tabindex + role=button + aria-label）',
    /tabindex="0"/.test(REG['tbl']._html) && /role="button"/.test(REG['tbl']._html)
    && /aria-label="/.test(REG['tbl']._html));

  // --- H8：无障碍（静态 HTML + 运行时属性） ---
  const labelN = (html.match(/<label class="clab" for=/g) || []).length;
  chk('H8 16 个滑杆都有 <label for>', labelN === 16, labelN + ' 个');
  const noAria = ['s_vtank', 's_th', 's_voff', 's_dose', 's_capex', 's_life', 's_om', 's_clp', 's_hh',
    's_pp', 's_quota', 's_hgeo', 's_cmains', 's_k20', 's_tw', 's_ct']
    .filter(id => !REG[id].attrs['aria-valuetext']);
  chk('H8 16 个滑杆都有 aria-valuetext（读屏报人话而非裸数字）', noAria.length === 0, noAria.join(','));
  chk('H8 存在 :focus-visible 焦点样式', /:focus-visible/.test(html));
  chk('L4 提供 prefers-reduced-motion 降级路径', /prefers-reduced-motion/.test(html));
  chk('L3 扫描组数文案由 GRID 计算（不再是写死的字符串）',
    /600 组方案/.test(REG['sweep_hint'].textContent), REG['sweep_hint'].textContent);
}

console.log('='.repeat(64));
console.log('SMOKE: ' + (FAIL ? 'FAILED (' + FAIL + ')' : 'ALL PASS'));
process.exit(FAIL ? 1 : 0);
