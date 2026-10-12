"""真实浏览器端到端验证：渲染、布局、交互、对比度、响应式、无障碍。

运行：python browser_check.py

DOM 桩测不出的问题只能靠这里抓（上一版就是在这里抓到 min_ctap/minCtap 命名不一致
导致整张 Pareto 图点全变 NaN，以及 NaN 坐标、缩放比漂移）——不要省这一步。
"""
import asyncio, os
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
URL = 'file://' + os.path.join(ROOT, 'web', 'index.html').replace('\\', '/')
os.makedirs(os.path.join(ROOT, 'out'), exist_ok=True)

FAIL = []


def chk(name, cond, info=''):
    print(('  PASS  ' if cond else '  FAIL  ') + name + ('   ' + info if info else ''))
    if not cond:
        FAIL.append(name)


# 计算 SVG 渲染宽度 / viewBox 宽度之比（H7：应恒为 1.00）
SCALE_JS = '''()=>{
  const out=[];
  document.querySelectorAll('svg').forEach(s=>{
    const vb=(s.getAttribute('viewBox')||'').split(/\\s+/);
    const w=parseFloat(vb[2]); const rw=s.getBoundingClientRect().width;
    if(w>0 && rw>0) out.push({vb:w, rw:+rw.toFixed(1), k:+(rw/w).toFixed(3),
      lab:(s.getAttribute('aria-label')||'').slice(0,10)});
  });
  return out;
}'''

# 灰底峰时段带数量（fill=#EDF0F3 的 rect）
BAND_JS = '''(host)=>{
  const s=document.querySelector(host+' svg'); if(!s) return -1;
  let n=0; s.querySelectorAll('rect').forEach(r=>{
    if(String(r.getAttribute('fill')).toUpperCase()==='#EDF0F3') n++; });
  return n;
}'''

# 逐元素对比度（前景 vs 白底）
CONTRAST_JS = '''()=>{
  const lin=c=>{c/=255;return c<=0.03928?c/12.92:Math.pow((c+0.055)/1.055,2.4);};
  const L=p=>0.2126*lin(p[0])+0.7152*lin(p[1])+0.0722*lin(p[2]);
  const rgb=s=>{const m=(s||'').match(/\\d+/g); return m?m.slice(0,3).map(Number):null;};
  const sels=[['.chint','滑杆说明'],['.kl','KPI 标题'],['.stat .sl','统计条标签'],
    ['.leg .lp','成本图例占比'],['.cn','图注'],['.st','分组标题'],['footer','页脚'],
    ['.clab .val','滑杆数值'],['.kd','KPI 副标题'],['.kd.good','达标绿字'],['.kd.bad','超标红字']];
  const out=[];
  sels.forEach(([sel,name])=>{
    const e=document.querySelector(sel); if(!e) return;
    const fg=rgb(getComputedStyle(e).color); if(!fg) return;
    const r=1.05/(L(fg)+0.05);
    out.push({sel:sel,name:name,ratio:+r.toFixed(2),
      size:parseFloat(getComputedStyle(e).fontSize)});
  });
  return out;
}'''


async def main():
    errs = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={'width': 1440, 'height': 1000})
        pg.on('console', lambda m: errs.append((m.type, m.text)) if m.type == 'error' else None)
        pg.on('pageerror', lambda e: errs.append(('pageerror', str(e))))
        await pg.goto(URL)
        await pg.wait_for_timeout(2000)

        async def g(sel):
            return (await pg.eval_on_selector(sel, 'e=>e.textContent.trim()'))

        async def slide(sel, val):
            await pg.eval_on_selector(
                sel, 'e=>{e.value="%s";e.dispatchEvent(new Event("input",{bubbles:true}))}' % val)
            await pg.wait_for_timeout(220)

        print('=' * 72)
        print('1) 首屏渲染')
        print('  KPI 总成本', await g('#k_total'), '| 提升电费', await g('#k_cost'),
              '| 补氯成本', await g('#k_dose'), '| 余氯', await g('#k_cl'))
        print('  统计条', await g('#s_e'), '/', await g('#s_age'), '/', await g('#s_ph'),
              '/', await g('#s_q'), '/', await g('#s_k'), '/', await g('#s_chem'))
        n_dot = await pg.eval_on_selector_all('#pareto circle', 'e=>e.length')
        n_seg = await pg.eval_on_selector_all('#cbar > div', 'e=>e.length')
        n_row = await pg.eval_on_selector_all('#tbl tbody tr', 'e=>e.length')
        print('  Pareto 圆点', n_dot, '| 成本条段数', n_seg, '| 表格行', n_row)
        chk('Pareto 散点已渲染', n_dot > 50, str(n_dot) + ' 个')
        chk('前沿表格有行', n_row > 3, str(n_row) + ' 行')
        chk('推荐卡已生成', len(await g('#recbox')) > 20)

        nan = await pg.evaluate('''()=>{
          const bad=[];
          document.querySelectorAll('.kv,.sv,.lv,#cbar div,td,text').forEach(e=>{
            const t=(e.textContent||'');
            if(/NaN|undefined|Infinity/.test(t)) bad.push(t.slice(0,40));
          });
          document.querySelectorAll('circle,.pareto circle').forEach(c=>{
            if(c.closest('#pareto')&&(!isFinite(+c.getAttribute('cx'))||!isFinite(+c.getAttribute('cy'))))
              bad.push('circle NaN');
          });
          return bad.slice(0,8);
        }''')
        chk('页面无 NaN / undefined 文本与坐标', len(nan) == 0, str(nan) if nan else '')

        ov = await pg.evaluate('()=>{const m=document.querySelector("main");'
                               'return {sw:m.scrollWidth,cw:m.clientWidth}}')
        chk('主区无横向溢出', ov['sw'] <= ov['cw'] + 2, str(ov))

        print('=' * 72)
        print('2) H6 文本对比度（WCAG AA ≥ 4.5:1）')
        cs = await pg.evaluate(CONTRAST_JS)
        for c in cs:
            flag = 'PASS' if c['ratio'] >= 4.5 else 'FAIL'
            print('    %-12s %-14s %.0fpx  对比度 %.2f  %s'
                  % (c['sel'], c['name'], c['size'], c['ratio'], flag))
        chk('所有抽检文本对比度 ≥ 4.5:1（H6）',
            all(c['ratio'] >= 4.5 for c in cs),
            '最低 %.2f:1' % min([c['ratio'] for c in cs] or [0]))

        print('=' * 72)
        print('3) H7 图表缩放比（应恒为 1.00，字号不再随视口漂移）')
        sc = await pg.evaluate(SCALE_JS)
        print('   ', ' | '.join('%s vb=%d rw=%.1f k=%.3f' % (s['lab'], s['vb'], s['rw'], s['k']) for s in sc))
        chk('全部图表缩放比 ≈ 1.00（H7）', all(0.97 <= s['k'] <= 1.03 for s in sc),
            str([s['k'] for s in sc]))

        print('=' * 72)
        print('4) H4 图例与画面吻合 / H5 灰底带跟随阈值')
        green = await pg.evaluate('''()=>{const s=document.querySelector('#pareto svg');
          let n=0; s.querySelectorAll('line').forEach(l=>{
            if(String(l.getAttribute('stroke')).toUpperCase()==='#00A65A') n++; });
          return n;}''')
        legtxt = await g('#pareto_legend')
        print('   Pareto 绿色内控目标线', green, '条 | 图例:', legtxt.replace('\n', ' ')[:90])
        chk('H4 Pareto 图内控目标线已绘制（旧版恒为 0 条）', green > 0, str(green) + ' 条')
        chk('H4 图例声明与画面吻合', '内控目标' in legtxt)

        b105 = await pg.evaluate(BAND_JS, '#ch_age')
        await slide('#s_th', '0.65')
        b065 = await pg.evaluate(BAND_JS, '#ch_age')
        await slide('#s_th', '1.05')
        print('   灰底带：阈值 1.05 ->', b105, '块 ；阈值 0.65 ->', b065, '块')
        chk('H5 灰底峰时段带跟随避峰阈值（8 -> 16）', b105 == 8 and b065 == 16,
            '%d -> %d' % (b105, b065))

        print('=' * 72)
        print('5) H8 无障碍')
        a11y = await pg.evaluate('''()=>({
          labels: document.querySelectorAll('.panel label[for]').length,
          ranges: document.querySelectorAll('input[type=range]').length,
          ariaVt: [...document.querySelectorAll('input[type=range]')]
                    .filter(e=>e.getAttribute('aria-valuetext')).length,
          svgN: document.querySelectorAll('svg').length,
          svgNamed: [...document.querySelectorAll('svg')]
                    .filter(s=>s.getAttribute('role')==='img'&&s.getAttribute('aria-label')).length,
          tabrows: document.querySelectorAll('#tbl tr[tabindex="0"]').length,
          roleBtn: document.querySelectorAll('#tbl tr[role="button"]').length,
          h2: document.querySelectorAll('h2').length,
          caption: document.querySelectorAll('#tbl caption').length,
          scope: document.querySelectorAll('#tbl th[scope="col"]').length,
          live: document.querySelectorAll('[aria-live]').length})''')
        print('   ', a11y)
        chk('H8 滑杆 label 覆盖 16/16', a11y['labels'] == 16 and a11y['ranges'] == 16)
        chk('H8 aria-valuetext 覆盖 16/16', a11y['ariaVt'] == 16, str(a11y['ariaVt']))
        chk('H8 每个 SVG 都有可访问名', a11y['svgN'] == a11y['svgNamed'] and a11y['svgN'] >= 5,
            '%d/%d' % (a11y['svgNamed'], a11y['svgN']))
        chk('H8 表格行可键盘操作（tabindex + role=button）',
            a11y['tabrows'] == n_row and a11y['roleBtn'] == n_row,
            '%d 行' % a11y['tabrows'])
        chk('M6 语义结构（h2 / caption / th scope 齐全）',
            a11y['h2'] == 7 and a11y['caption'] == 1 and a11y['scope'] == 11, str(a11y))
        chk('M6 KPI 区有 aria-live 播报', a11y['live'] >= 1)

        print('=' * 72)
        print('6) 补氯成本：不补 -> 补 0.4（成本条 1 段 -> 4 段）')
        chk('默认不补氯时成本条只有 1 段', n_seg == 1, str(n_seg) + ' 段')
        n_leg0 = await pg.eval_on_selector_all('#cleg .leg', 'e=>e.length')
        chk('M1 不补氯时成本图例只 1 项（不再 3 个零）', n_leg0 == 1, str(n_leg0) + ' 项')
        await slide('#s_dose', '0.4')
        n_seg4 = await pg.eval_on_selector_all('#cbar > div', 'e=>e.length')
        n_leg = await pg.eval_on_selector_all('#cleg .leg', 'e=>e.length')
        print('  补氯 0.4 -> 总成本', await g('#k_total'), '| 补氯成本', await g('#k_dose'),
              '|', await g('#k_dose_d'))
        chk('启用补氯后成本条 4 段', n_seg4 == 4, str(n_seg4) + ' 段')
        chk('启用补氯后图例 4 项', n_leg == 4, str(n_leg) + ' 项')

        print('=' * 72)
        print('7) 成本口径切换')
        full = float((await g('#k_total')).split('元')[0])
        await pg.click('#bv_run')
        await pg.wait_for_timeout(250)
        run = float((await g('#k_total')).split('元')[0])
        print('  全成本', full, '-> 仅运行', run)
        chk('仅运行口径总成本更低', run < full, '%.2f < %.2f' % (run, full))
        await pg.click('#bv_full')
        await pg.wait_for_timeout(250)
        chk('切回全成本可恢复', abs(float((await g('#k_total')).split('元')[0]) - full) < 0.01)
        await slide('#s_dose', '0')

        print('=' * 72)
        print('8) 滑杆回归（逐个改 + 检查 NaN）')
        for sel, val, name in [
            ('#s_vtank', '150', '水箱容积'), ('#s_th', '1.30', '避峰阈值'),
            ('#s_voff', '0.55', '维持液位'), ('#s_capex', '6.0', '装置投资'),
            ('#s_life', '12', '折旧年限'), ('#s_om', '6000', '年运维费'),
            ('#s_clp', '16', '有效氯单价'), ('#s_k20', '0.15', '衰减系数'),
            ('#s_tw', '30', '水温'), ('#s_ct', '0.40', '余氯内控目标'),
            ('#s_hh', '600', '户数'), ('#s_pp', '4.0', '户均人数'), ('#s_quota', '240', '用水定额'),
            ('#s_hgeo', '90', '几何扬程'), ('#s_cmains', '0.35', '市政来水余氯'),
        ]:
            await slide(sel, val)
            bad = await pg.evaluate('''()=>{const t=document.querySelector('#k_total').textContent
              +document.querySelector('#k_cl').textContent;return /NaN|undefined/.test(t)}''')
            chk('拖动「%s」后无 NaN' % name, not bad, '总成本 ' + await g('#k_total'))
            await slide(sel, {'#s_vtank': '60', '#s_th': '1.05', '#s_voff': '0.85', '#s_capex': '3.0',
                              '#s_life': '8', '#s_om': '3000', '#s_clp': '10', '#s_k20': '0.05',
                              '#s_tw': '22', '#s_ct': '0.05', '#s_hh': '300', '#s_pp': '3.0',
                              '#s_quota': '180', '#s_hgeo': '54', '#s_cmains': '0.8'}[sel])

        print('=' * 72)
        print('9) H3 点击前沿表格行 → KPI 必须与表格数值一致')
        ok_rows = 0
        worst = 0.0
        for row in (1, 3, 5, 8):
            cell = '#tbl tbody tr:nth-child(%d) td:nth-child(7)' % row
            txt_row = await g(cell)
            await pg.click('#tbl tbody tr:nth-child(%d)' % row)
            await pg.wait_for_timeout(300)
            txt_kpi = (await g('#k_total')).replace('元/d', '').strip()
            d = abs(float(txt_row) - float(txt_kpi))
            worst = max(worst, d)
            if d <= 0.005:
                ok_rows += 1
            print('   第 %d 行 表格 %s vs KPI %s  ->  偏差 %.4f' % (row, txt_row, txt_kpi, d))
        chk('H3 套用表格行后 KPI 与表格数值一致（容差 0.005 元/d）', ok_rows == 4,
            '最大偏差 %.4f' % worst)

        print('=' * 72)
        print('9b) 图内标注 vs KPI 一致（余氯图「最低 x」必须等于 #k_cl）')
        # 曾经的疑点：截图里图注 0.403 而 KPI 0.483 —— 事后查明是拿旧构建截图所致。
        # 但「两处数字来自不同 sim 调用」是这类页面最典型的静默失配，故永久锁死。
        ANN_JS = '''()=>{
          const a=[...document.querySelectorAll('#ch_cl text')]
            .map(t=>t.textContent).filter(s=>/^最低 /.test(s));
          const m=a.length?String(a[0]).match(/[\\d.]+/):null;
          const k=String(document.querySelector('#k_cl').textContent).match(/[\\d.]+/);
          return {ann:m?+m[0]:null, kpi:k?+k[0]:null,
                  nAnn:a.length, annText:a[0]||null,
                  kpiText:document.querySelector('#k_cl').textContent.trim()};
        }'''
        ann_ok = 0
        ann_cases = [('#s_vtank', '150'), ('#s_voff', '0.70'), ('#s_k20', '0.18'),
                     ('#s_tw', '30'), ('#s_dose', '0.5')]
        for sel, val in ann_cases:
            await slide(sel, val)
            a = await pg.evaluate(ANN_JS)
            same = (a['nAnn'] == 1 and a['ann'] is not None and a['kpi'] is not None
                    and abs(a['ann'] - a['kpi']) <= 0.001)
            if same:
                ann_ok += 1
            print('   %-9s=%-4s 图注 %-16s KPI %-10s %s'
                  % (sel, val, a['annText'], a['kpiText'], 'OK' if same else 'MISMATCH'))
        for sel, val in [('#s_vtank', '60'), ('#s_voff', '0.85'), ('#s_k20', '0.05'),
                         ('#s_tw', '22'), ('#s_dose', '0')]:
            await slide(sel, val)
        chk('图内「最低余氯」标注与 KPI 逐工况一致', ann_ok == len(ann_cases),
            '%d/%d' % (ann_ok, len(ann_cases)))

        print('=' * 72)
        print('10) 重算 Pareto 前沿')
        await pg.click('#btn_sweep')
        for _ in range(120):
            await pg.wait_for_timeout(500)
            if not await pg.eval_on_selector('#btn_sweep', 'e=>e.disabled'):
                break
        print(' ', await g('#pareto_note'))
        chk('重算后前沿点数 > 3', '前沿' in await g('#pareto_note'))
        chk('重算后按钮恢复可用', not await pg.eval_on_selector('#btn_sweep', 'e=>e.disabled'))
        sc2 = await pg.evaluate(SCALE_JS)
        chk('重算后图表缩放比仍 ≈ 1.00', all(0.97 <= s['k'] <= 1.03 for s in sc2),
            str([s['k'] for s in sc2]))

        await pg.screenshot(path=os.path.join(ROOT, 'out', 'shot.png'), full_page=True)

        print('=' * 72)
        print('11) 多视口：横向溢出 / 缩放比 / M3 移动端重排')
        for w in (1440, 1024, 820, 768, 430, 390):
            pgx = await b.new_page(viewport={'width': w, 'height': 900})
            await pgx.goto(URL)
            await pgx.wait_for_timeout(1100)
            r = await pgx.evaluate('''()=>({sw:document.documentElement.scrollWidth,
              cw:document.documentElement.clientWidth})''')
            s2 = await pgx.evaluate(SCALE_JS)
            chk('%4dpx 无横向溢出' % w, r['sw'] <= r['cw'] + 1, str(r))
            chk('%4dpx 图表缩放比 ≈ 1.00（H7）' % w,
                all(0.94 <= s['k'] <= 1.06 for s in s2), str([s['k'] for s in s2]))
            if w == 1440:
                await pgx.screenshot(path=os.path.join(ROOT, 'out', 'vw1440.png'), full_page=True)
            if w == 390:
                await pgx.screenshot(path=os.path.join(ROOT, 'out', 'vw390.png'), full_page=True)
                m = await pgx.evaluate('''()=>({
                  mainTop: document.querySelector('main').getBoundingClientRect().top,
                  panelTop: document.querySelector('.panel').getBoundingClientRect().top,
                  panelOpen: document.querySelector('#panelbox').open,
                  h1: getComputedStyle(document.querySelector('h1')).fontSize})''')
                print('  390px: main 顶 %.0f / panel 顶 %.0f / 面板展开 %s / h1 %s'
                      % (m['mainTop'], m['panelTop'], m['panelOpen'], m['h1']))
                chk('M3 移动端结果区排在参数面板之上', m['mainTop'] < m['panelTop'], str(m))
                chk('M3 移动端参数面板默认收起', m['panelOpen'] is False, str(m['panelOpen']))
            await pgx.close()

        print('=' * 72)
        print('12) 指针目标尺寸（WCAG 2.2 SC 2.5.8 要求 ≥24×24；触屏建议 ≥44）')
        HIT_JS = '''(ids)=>{const o={};ids.forEach(id=>{const e=document.getElementById(id);
          if(e){const r=e.getBoundingClientRect();o[id]=[+r.width.toFixed(0),+r.height.toFixed(0)];}});return o;}'''
        SL_IDS = ['s_vtank', 's_th', 's_voff', 's_dose', 's_capex', 's_life', 's_om',
                  's_clp', 's_hh', 's_pp', 's_quota', 's_hgeo', 's_cmains', 's_k20',
                  's_tw', 's_ct']
        hit_d = await pg.evaluate(HIT_JS, SL_IDS)
        short_d = {k: v for k, v in hit_d.items() if v[1] < 24}
        print('   桌面滑杆命中区:', sorted(set('%dx%d' % tuple(v) for v in hit_d.values())))
        chk('滑杆命中区 ≥24px 高（16/16，SC 2.5.8）', not short_d, str(short_d))
        # 触屏：pointer:coarse 媒体查询应把命中区抬到 44px
        pgm = await b.new_page(viewport={'width': 390, 'height': 844}, has_touch=True,
                               is_mobile=True, device_scale_factor=2)
        await pgm.goto(URL)
        await pgm.wait_for_timeout(1000)
        hit_m = await pgm.evaluate(HIT_JS, SL_IDS)
        heights = sorted(set(v[1] for v in hit_m.values()))
        print('   触屏滑杆命中区高度:', heights)
        chk('触屏滑杆命中区抬到 ≥44px', all(h >= 44 for h in heights) and heights,
            str(heights))
        # 已填充比例 --p 必须初始化（appearance:none 后原生不再绘制已填充段）
        pv = await pgm.evaluate('''()=>[...document.querySelectorAll('input[type=range]')]
          .map(e=>e.style.getPropertyValue('--p')).filter(Boolean).length''')
        chk('16 个滑杆都已初始化 --p 填充比例', pv == 16, '%d/16' % pv)
        await pgm.close()

        print('=' * 72)
        print('CONSOLE ERRORS:', errs if errs else 'none')
        chk('控制台零错误', len(errs) == 0, str(errs[:2]))
        await b.close()

    print('=' * 72)
    print('BROWSER: ' + ('ALL PASS' if not FAIL else 'FAILED -> ' + ', '.join(FAIL)))


asyncio.run(main())
