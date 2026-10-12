"""视觉审计：多宽度渲染 + 溢位 + 字号 + 对比度 + 触控目标。
运行：python audit_visual.py
"""
import asyncio, os, json
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ 的上一级 = 项目根
URL = 'file://' + os.path.join(ROOT, 'web', 'index.html').replace('\\', '/')
OUT = os.path.join(ROOT, 'out')

WIDTHS = [(1440, 1000), (1280, 900), (1024, 900), (820, 900), (768, 900), (430, 900), (390, 844)]


def lum(rgb):
    def f(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        print('=' * 74)
        print('A) 多宽度横向溢位与截图')
        for w, h in WIDTHS:
            pg = await b.new_page(viewport={'width': w, 'height': h}, device_scale_factor=1)
            errs = []
            pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
            pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)))
            await pg.goto(URL)
            await pg.wait_for_timeout(1500)
            r = await pg.evaluate('''()=>{
              const de=document.documentElement;
              const wide=[];
              document.querySelectorAll('body *').forEach(e=>{
                const b=e.getBoundingClientRect();
                if(b.width>0 && b.right > de.clientWidth+1) wide.push(
                  (e.tagName+'.'+(e.className||'').toString().split(' ')[0]).slice(0,42)
                  +' right='+Math.round(b.right));
              });
              return {sw:de.scrollWidth, cw:de.clientWidth,
                      wide:[...new Set(wide)].slice(0,6),
                      h1:getComputedStyle(document.querySelector('h1')).fontSize};
            }''')
            flag = 'OK ' if r['sw'] <= r['cw'] + 1 else 'OVERFLOW'
            print('  %4dpx  doc scrollW=%4d clientW=%4d  %s  h1=%s  %s'
                  % (w, r['sw'], r['cw'], flag, r['h1'], r['wide'] if r['wide'] else ''))
            if errs:
                print('         console errors:', errs[:2])
            await pg.screenshot(path=os.path.join(OUT, 'vw%d.png' % w), full_page=True)
            await pg.close()

        # 图表内文字的有效像素尺寸（viewBox 缩放后）
        print('=' * 74)
        print('B) SVG 图表文字有效字号（viewBox 缩放后）')
        for w in (1440, 768, 390):
            pg = await b.new_page(viewport={'width': w, 'height': 900})
            await pg.goto(URL)
            await pg.wait_for_timeout(1400)
            r = await pg.evaluate('''()=>{
              const out=[];
              [['#pareto','Pareto'],['#ch_v','液位图'],['#ch_cl','余氯图']].forEach(([sel,nm])=>{
                const svg=document.querySelector(sel+' svg');
                if(!svg) return;
                const box=svg.getBoundingClientRect();
                const vb=svg.viewBox.baseVal;
                const scale=box.width/vb.width;
                const t=svg.querySelector('text');
                const fs=t?parseFloat(getComputedStyle(t).fontSize):0;
                out.push(nm+' 容器'+Math.round(box.width)+'px 缩放'+scale.toFixed(2)+'x 基准'+fs+'px -> 有效'+(fs*scale).toFixed(1)+'px');
              });
              return out;
            }''')
            print('  %4dpx:' % w)
            for x in r:
                print('     ', x)
            await pg.close()

        print('=' * 74)
        print('C) 文本对比度（WCAG AA 正文需 ≥4.5:1）')
        pg = await b.new_page(viewport={'width': 1440, 'height': 1000})
        await pg.goto(URL)
        await pg.wait_for_timeout(1400)
        samples = await pg.evaluate('''()=>{
          const pick=[];
          const sel=['.chint','.kl','.kd','.stat .sl','.leg .lp','.cn','footer','.tag','.sub',
                     '.sech','.st','.box.b-y','.note','td','th','.leg .lt'];
          sel.forEach(s=>{const e=document.querySelector(s); if(!e) return;
            const cs=getComputedStyle(e);
            // 找最近的实底背景
            let bg=cs.backgroundColor, p=e;
            while((bg==='rgba(0, 0, 0, 0)'||bg==='transparent')&&p.parentElement){
              p=p.parentElement; bg=getComputedStyle(p).backgroundColor;}
            pick.push({s:s, fg:cs.color, bg:bg, size:cs.fontSize, weight:cs.fontWeight});});
          return pick;
        }''')

        def parse(c):
            c = c.replace('rgba(', '').replace('rgb(', '').replace(')', '')
            v = [float(x) for x in c.split(',')[:3]]
            return tuple(int(x) for x in v)

        fails = []
        for s in samples:
            try:
                r = ratio(parse(s['fg']), parse(s['bg']))
            except Exception:
                continue
            size = float(s['size'].replace('px', ''))
            large = size >= 18 or (size >= 14 and int(s['weight']) >= 700)
            need = 3.0 if large else 4.5
            ok = r >= need
            print('  %-12s %s on %s  %.0fpx w%s  对比度 %.2f  需≥%.1f  %s'
                  % (s['s'], s['fg'], s['bg'], size, s['weight'], r, need, 'PASS' if ok else '**FAIL**'))
            if not ok:
                fails.append((s['s'], round(r, 2), need))
        print('  对比度不达标项:', fails if fails else '无')

        print('=' * 74)
        print('D) 触控目标尺寸（移动端建议 ≥44×44 CSS px）')
        pg2 = await b.new_page(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        await pg2.goto(URL)
        await pg2.wait_for_timeout(1400)
        small = await pg2.evaluate('''()=>{
          const out=[];
          document.querySelectorAll('button,input[type=range],tr[data-vt],.seg button').forEach(e=>{
            const b=e.getBoundingClientRect();
            if(b.width>0&&b.height>0&&(b.height<44||b.width<44))
              out.push((e.tagName+'#'+(e.id||e.className)).slice(0,40)+' '+Math.round(b.width)+'x'+Math.round(b.height));
          });
          return out.slice(0,12);
        }''')
        print('  小于 44px 的交互元素:', small if small else '无')

        print('=' * 74)
        print('E) 移动端关键元素可见性')
        r = await pg2.evaluate('''()=>{
          const q=s=>{const e=document.querySelector(s);if(!e)return null;
            const b=e.getBoundingClientRect();const cs=getComputedStyle(e);
            return {w:Math.round(b.width),h:Math.round(b.height),fs:cs.fontSize,vis:cs.display!=='none'};};
          return {panel:q('.panel'),kpis:q('.kpis'),pareto:q('#pareto'),tbl:q('#tbl'),
                  cbar:q('.cbar'),grid2:q('.grid2'),sweep:q('#btn_sweep'),
                  table_wrap:q('#tbl').w, doc_w:document.documentElement.clientWidth};
        }''')
        print('  ', json.dumps(r, ensure_ascii=False))
        await b.close()


asyncio.run(main())
