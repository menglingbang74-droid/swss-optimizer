"""审计取证 2：重算前沿后的口径一致性、数据规模、元信息缺失。"""
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
        print('A) 内嵌数据规模 & 与按钮文案「600 组方案」是否一致')
        r = await pg.evaluate('''()=>{
          const d=JSON.parse(document.getElementById('embedded-data').textContent);
          return {points:d.points.length, front:d.front.length,
                  note:document.getElementById('pareto_note').textContent,
                  btnHint:document.querySelector('#btn_sweep').nextElementSibling.textContent.trim(),
                  grid:d.meta.grid, generated:d.meta.generated,
                  base:d.meta.baseline};
        }''')
        print('  内嵌 points=%d  front=%d' % (r['points'], r['front']))
        print('  图上标注:', r['note'])
        print('  按钮提示:', r['btnHint'])
        print('  网格格数 = 6×5×5×4 = %d（理论）' % (6 * 5 * 5 * 4))
        print('  数据生成时间:', r['generated'])
        print('  基线:', r['base'])

        print('=' * 74)
        print('B) 点击「重新计算 Pareto 前沿」后：表格数值 vs KPI（口径 dt/nDays 不一致）')
        await pg.click('#btn_sweep')
        for _ in range(80):
            await pg.wait_for_timeout(500)
            if not await pg.eval_on_selector('#btn_sweep', 'e=>e.disabled'):
                break
        r2 = await pg.evaluate('''()=>{
          const tr=document.querySelector('#tbl tbody tr');
          const p={vt:tr.dataset.vt, th:tr.dataset.th, vf:tr.dataset.vf, ds:tr.dataset.ds};
          const cells=[...tr.querySelectorAll('td')].map(t=>t.textContent.trim());
          document.getElementById('s_vtank').value=p.vt;
          document.getElementById('s_th').value=p.th;
          document.getElementById('s_voff').value=p.vf;
          document.getElementById('s_dose').value=p.ds;
          document.getElementById('s_vtank').dispatchEvent(new Event('input',{bubbles:true}));
          return {params:p, rowCells:cells,
            kpiTotal:document.getElementById('k_total').textContent.trim(),
            kpiCost:document.getElementById('k_cost').textContent.trim(),
            kpiCl:document.getElementById('k_cl').textContent.trim(),
            note:document.getElementById('pareto_note').textContent};
        }''')
        print('  参数', r2['params'])
        print('  表格行:', r2['rowCells'])
        print('  KPI: 总成本=%s 提升电费=%s 最低余氯=%s' % (r2['kpiTotal'], r2['kpiCost'], r2['kpiCl']))
        print('  重算后标注:', r2['note'])
        # 蓝色"当前方案"标记是否落在橙色前沿上
        r3 = await pg.evaluate('''()=>{
          const s=document.querySelector('#pareto svg');
          const circles=[...s.querySelectorAll('circle')].map(e=>({
            cx:+(e.getAttribute('cx')), cy:+(e.getAttribute('cy')), r:+e.getAttribute('r'),
            fill:e.getAttribute('fill'), stroke:e.getAttribute('stroke')}));
          const blue=circles.filter(c=>c.fill==='#0057FF'||c.stroke==='#0057FF');
          const orange=circles.filter(c=>c.fill==='#FF4D00');
          let nearest=null;
          blue.forEach(bl=>{orange.forEach(o=>{
            const d=Math.hypot(bl.cx-o.cx, bl.cy-o.cy);
            if(!nearest||d<nearest.d) nearest={d:+d.toFixed(2), bx:+bl.cx.toFixed(1),
              by:+bl.cy.toFixed(1), ox:+o.cx.toFixed(1), oy:+o.cy.toFixed(1)};});});
          return {nBlue:blue.length, nOrange:orange.length, nearest};
        }''')
        print('  蓝点 %d 个 / 橙点 %d 个；蓝点到最近橙点距离: %s px' % (r3['nBlue'], r3['nOrange'], r3['nearest']))

        print('=' * 74)
        print('C) head 元信息 / SEO / 分享卡')
        r4 = await pg.evaluate('''()=>{
          const m={};
          ['description','og:title','og:description','og:image','theme-color','author'].forEach(k=>{
            m[k]=document.querySelector('meta[name="'+k+'"]')?1:(document.querySelector('meta[property="'+k+'"]')?1:0);});
          return {metas:m, lang:document.documentElement.lang,
                  favicon:!!document.querySelector('link[rel*="icon"]'),
                  title:document.title, h1:document.querySelectorAll('h1').length,
                  h2:document.querySelectorAll('h2').length,
                  tables:document.querySelectorAll('table').length,
                  tableHasCaption:!!document.querySelector('table caption'),
                  thScope:document.querySelectorAll('th[scope]').length};
        }''')
        print('  lang=%s  favicon=%s  h1 数=%d  h2 数=%d' % (r4['lang'], r4['favicon'], r4['h1'], r4['h2']))
        print('  meta 存在性:', r4['metas'])
        print('  title:', r4['title'])
        print('  table 数=%d  caption=%s  th[scope] 数=%d' % (r4['tables'], r4['tableHasCaption'], r4['thScope']))

        print('=' * 74)
        print('D) 表单可访问性：滑杆是否有 <label for> / aria')
        r5 = await pg.evaluate('''()=>{
          const out=[];
          document.querySelectorAll('input[type=range]').forEach(e=>{
            out.push({id:e.id, label:document.querySelector('label[for="'+e.id+'"]')?1:0,
              ariaLabel:e.getAttribute('aria-label')||null, ariaValueText:e.getAttribute('aria-valuetext')||null});});
          return out;
        }''')
        print('  滑杆总数 %d；带 label[for] 的：%d' % (len(r5), sum(x['label'] for x in r5)))
        print('  带 aria-label 的：%d；带 aria-valuetext 的：%d'
              % (sum(1 for x in r5 if x['ariaLabel']), sum(1 for x in r5 if x['ariaValueText'])))
        print('  示例:', r5[:2])

        print('=' * 74)
        print('E) 图表 SVG 是否有可访问名称')
        r6 = await pg.evaluate('''()=>{
          const out=[];
          document.querySelectorAll('svg').forEach((s,i)=>{
            out.push({i:i, role:s.getAttribute('role')||null, aria:s.getAttribute('aria-label')||null,
              title:!!s.querySelector('title'), desc:!!s.querySelector('desc')});});
          return out;
        }''')
        print(' %d 个 SVG；带 role/aria/title/desc 的：%d'
              % (len(r6), sum(1 for x in r6 if x['role'] or x['aria'] or x['title'] or x['desc'])))
        await b.close()


asyncio.run(main())
