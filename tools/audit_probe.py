"""针对审计疑点的实测取证（不猜测，用真实浏览器与 Node 验证）。"""
import asyncio, os, json
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ 的上一级 = 项目根
URL = 'file://' + os.path.join(ROOT, 'web', 'index.html').replace('\\', '/')


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={'width': 1440, 'height': 1000})
        await pg.goto(URL)
        await pg.wait_for_timeout(1500)

        print('=' * 74)
        print('疑点1：前沿点(scanner, dt=1/30,nDays=2) 与 当前方案点(dt=1/60,nDays=3) 口径不一致')
        r = await pg.evaluate('''()=>{
          // 取前沿第一行参数，套用到滑杆，比较 KPI 与表格里的数值差
          const tr=document.querySelector('#tbl tbody tr');
          const p={vt:tr.dataset.vt, th:tr.dataset.th, vf:tr.dataset.vf, ds:tr.dataset.ds};
          const cells=[...tr.querySelectorAll('td')].map(t=>t.textContent.trim());
          document.getElementById('s_vtank').value=p.vt;
          document.getElementById('s_th').value=p.th;
          document.getElementById('s_voff').value=p.vf;
          document.getElementById('s_dose').value=p.ds;
          document.getElementById('s_vtank').dispatchEvent(new Event('input',{bubbles:true}));
          return {params:p, tableRow:cells.slice(4,9),
                  kpiTotal:document.getElementById('k_total').textContent.trim(),
                  kpiCost:document.getElementById('k_cost').textContent.trim(),
                  kpiDose:document.getElementById('k_dose').textContent.trim()};
        }''')
        print('  参数', r['params'])
        print('  表格 [提升电费,补氯成本,总成本,vs基线,最低余氯] =', r['tableRow'])
        print('  KPI  总成本=%s 提升电费=%s 补氯成本=%s' % (r['kpiTotal'], r['kpiCost'], r['kpiDose']))

        print('=' * 74)
        print('疑点2：Pareto 图例 4 项，但"余氯内控目标"线是否真的画出？')
        r2 = await pg.evaluate('''()=>{
          const s=document.querySelector('#pareto svg');
          const paths=[...s.querySelectorAll('path')].map(e=>({stroke:e.getAttribute('stroke'),
            dash:e.getAttribute('stroke-dasharray'),d:(e.getAttribute('d')||'').slice(0,40)}));
          const lines=[...s.querySelectorAll('line')].map(e=>e.getAttribute('stroke'));
          const texts=[...s.querySelectorAll('text')].map(e=>e.textContent);
          return {greenPaths:paths.filter(p=>p.stroke==='#00A65A'),
                  greenLines:lines.filter(x=>x==='#00A65A').length,
                  hasTargetLabel:texts.some(t=>/内控目标/.test(t)),
                  yRangeTexts:texts.filter(t=>/^0\\./.test(t))};
        }''')
        print('  绿色(内控目标) path 数:', len(r2['greenPaths']))
        print('  绿色 line 数:', r2['greenLines'])
        print('  图中是否有"内控目标"文字:', r2['hasTargetLabel'])
        print('  y 轴刻度文字:', r2['yRangeTexts'])

        print('=' * 74)
        print('疑点3：灰底"峰时段"带是否跟随"避峰阈值"滑杆？')
        r3 = await pg.evaluate('''()=>{
          const grab=()=>{const s=document.querySelector('#ch_p svg');
            return [...s.querySelectorAll('rect')].filter(e=>e.getAttribute('fill')==='#FF4D00').length;};
          const band=()=>{const s=document.querySelector('#ch_v svg');
            return [...s.querySelectorAll('rect')].filter(e=>e.getAttribute('fill')==='#ECEEF0').length;};
          const before={orange:grab(), grey:band()};
          document.getElementById('s_th').value='0.65';
          document.getElementById('s_th').dispatchEvent(new Event('input',{bubbles:true}));
          const after={orange:grab(), grey:band()};
          document.getElementById('s_th').value='1.05';
          document.getElementById('s_th').dispatchEvent(new Event('input',{bubbles:true}));
          return {before, after};
        }''')
        print('  阈值 1.05 时：橙柱 %d 根，灰底带 %d 块' % (r3['before']['orange'], r3['before']['grey']))
        print('  阈值 0.65 时：橙柱 %d 根，灰底带 %d 块  <- 灰底带应随阈值变化' % (r3['after']['orange'], r3['after']['grey']))

        print('=' * 74)
        print('疑点4：双量纲共轴——液位(m³)与流量(m³/h)是否同一 y 刻度？')
        r4 = await pg.evaluate('''()=>{
          const s=document.querySelector('#ch_v svg');
          const yt=[...s.querySelectorAll('text')].map(e=>({x:+e.getAttribute('x'),y:+e.getAttribute('y'),t:e.textContent}));
          const ylabels=yt.filter(e=>e.x<50&&/^[\\d.]+$/.test(e.t)).map(e=>e.t);
          // 橙色虚线（补水流量）的最高 y 坐标 vs 图示区顶
          const orange=[...s.querySelectorAll('path')].find(e=>e.getAttribute('stroke')==='#FF4D00');
          const d=orange.getAttribute('d');
          const ys=[...d.matchAll(/[ML]([\\d.]+) ([\\d.]+)/g)].map(m=>+m[2]);
          const blue=[...s.querySelectorAll('path')].find(e=>e.getAttribute('stroke')==='#0057FF');
          const ysb=[...blue.getAttribute('d').matchAll(/[ML]([\\d.]+) ([\\d.]+)/g)].map(m=>+m[2]);
          return {yLabels:ylabels, orangeYmin:Math.min(...ys), blueYmin:Math.min(...ysb),
                  orangeYmax:Math.max(...ys), blueYmax:Math.max(...ysb)};
        }''')
        print('  y 轴刻度:', r4['yLabels'], '（对应液位 0~55 m³）')
        print('  橙色虚线(补水流量) y 范围: %.0f ~ %.0f' % (r4['orangeYmin'], r4['orangeYmax']))
        print('  蓝色实线(液位)     y 范围: %.0f ~ %.0f' % (r4['blueYmin'], r4['blueYmax']))

        print('=' * 74)
        print('疑点5：一次滑杆拖动触发几次 refresh（input+change 双绑定）')
        r5 = await pg.evaluate('''()=>{
          let n=0; const orig=window.refresh; // refresh 是函数声明，挂在全局
          const t0=performance.now();
          for(let i=0;i<20;i++){
            const e=document.getElementById('s_vtank');
            e.value=String(60+ (i%10)*5);
            e.dispatchEvent(new Event('input',{bubbles:true}));
          }
          return {ms:Math.round(performance.now()-t0)};
        }''')
        print('  连续 20 次 input 事件总耗时: %d ms（每次约 %.1f ms）' % (r5['ms'], r5['ms'] / 20))

        await b.close()


asyncio.run(main())
