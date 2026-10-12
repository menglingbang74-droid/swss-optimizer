/* 用 Node 跑 web/template.html 里的 JS 模型，与 Python 基准值逐项对比。
   运行： node xcheck.js

   注意：Python 用 snake_case、JS 用 camelCase，必须显式映射。
   早期版本直接拿 python 的键去读 JS 返回值，读到 undefined，
   Math.abs(py - undefined) = NaN，NaN > tol 为 false -> 静默"通过"。
   这里对 NaN/undefined 直接判 FAIL，杜绝假通过。 */
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'web', 'template.html'), 'utf8');
const start = html.indexOf('<script>') + '<script>'.length;
const marker = '状态 / UI';
const end = html.indexOf(marker);
if (start < 0 || end < 0) { console.error('无法定位模型代码块'); process.exit(1); }
const code = html.slice(start, html.lastIndexOf('/* =====', end));

const fn = new Function(code + '\n; return {simulate, maskFrom, DEF, HOURLY, PRICE, clamp};');
const M = fn();

const cases = (() => {
  const p = path.join(__dirname, 'out', 'xcheck.json');
  if (!fs.existsSync(p)) {
    console.error('找不到基准值 ' + p);
    console.error('请先运行：python xcheck.py   （它会生成 out/xcheck.json）');
    console.error('out/ 是可再生产物，不随仓库提交，所以新克隆必须按上述顺序执行。');
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(p, 'utf8'));
})();

// [python 键, js 键]
const KEYS = [
  ['cost', 'cost'], ['cost_total', 'costTotal'], ['cost_dose', 'costDose'],
  ['cost_dose_fixed', 'costDoseFixed'], ['cost_dose_energy', 'costDoseEnergy'],
  ['cost_chem', 'costChem'], ['dose_mass', 'doseMass'],
  ['vol_pumped', 'volPumped'], ['pump_hours', 'pumpHours'],
  ['energy_dose', 'energyDose'], ['energy', 'energy'],
  ['min_ctap', 'minCtap'], ['mean_ctap', 'meanCtap'],
  ['max_age', 'maxAge'], ['mean_age', 'meanAge'],
  ['forced_vol', 'forcedVol'], ['unmet', 'unmet'],
  ['overflow', 'overflow'], ['frac_below', 'fracBelow'],
  ['k_used', 'kUsed'], ['q_daily', 'qDaily'],
  ['v_off', 'vOff'], ['v_guard', 'vGuard'],
];

let fail = 0, checked = 0;
const bad = [];

function cmp(label, py, js, tol) {
  checked++;
  if (typeof js !== 'number' || !isFinite(js) || typeof py !== 'number' || !isFinite(py)) {
    fail++; bad.push(`${label}: 非有限值 py=${py} js=${js}`); return;
  }
  const t = Math.max(tol, Math.abs(py) * 2e-3);
  if (Math.abs(py - js) > t) { fail++; bad.push(`${label}: py=${py} js=${js} (tol ${t})`); }
}

cases.forEach((c, idx) => {
  const inp = c.input;
  const P = Object.assign({}, M.DEF, {
    nHousehold: inp.n_household || 300, persons: 3.0,
    quotaL: inp.quota_L || 180, hGeo: inp.h_geo || 54,
    cMains: inp.c_mains === undefined ? 0.8 : inp.c_mains,
    k20: inp.k20 === undefined ? 0.05 : inp.k20,
    tWater: inp.t_water === undefined ? 22 : inp.t_water,
    vTank: inp.v_tank, vOffFrac: inp.v_off_frac, dose: inp.dose,
    doseCapex: inp.dose_capex === undefined ? 30000 : inp.dose_capex,
    doseLifeYr: inp.dose_life_yr === undefined ? 8 : inp.dose_life_yr,
    doseOmYr: inp.dose_om_yr === undefined ? 3000 : inp.dose_om_yr,
    clPrice: inp.cl_price === undefined ? 10 : inp.cl_price,
    costView: inp.cost_view === undefined ? 'full' : inp.cost_view,
    mask: M.maskFrom(inp.th), dt: 1 / 60, nDays: 3
  });
  const r = M.simulate(P);
  const local = [];
  KEYS.forEach(([pk, jk]) => {
    const before = fail;
    cmp(pk, c[pk], r[jk], 1e-4);
    if (fail > before) local.push(bad.pop());
  });
  ['V_first10', 'C_last5'].forEach(k => {
    const py = c[k];
    const arr = r.rec[k === 'V_first10' ? 'V' : 'C'];
    const js = (k === 'V_first10' ? arr.slice(0, 10) : arr.slice(-5))
      .map(x => +x.toFixed(k === 'V_first10' ? 4 : 5));
    checked++;
    const ok = py.every((v, i) => typeof js[i] === 'number'
      && Math.abs(v - js[i]) <= Math.max(1e-3, Math.abs(v) * 5e-3));
    if (!ok) { fail++; local.push(`${k}: py=${py} js=${js}`); }
  });
  const tag = `case${idx + 1} tank=${inp.v_tank} th=${inp.th} voff=${inp.v_off_frac} dose=${inp.dose}`
    + (inp.cost_view ? ` view=${inp.cost_view}` : '');
  console.log((local.length ? '  FAIL  ' : '  PASS  ') + tag
    + (local.length ? '\n         ' + local.join('\n         ') : ''));
  bad.push(...local);
});

console.log('='.repeat(64));
console.log(`交叉校验：${checked - fail}/${checked} 项一致  ->  ` + (fail ? 'FAILED' : 'ALL PASS'));
process.exit(fail ? 1 : 0);
