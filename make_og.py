"""生成社交分享图 web/og.png（1200x630）。运行：python make_og.py

用同一套视觉系统渲染一张静态卡片再截图，避免手工出图与页面风格漂移。
修改配色/文案后重跑一次即可。
"""
import os
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "web", "og.png")

CARD = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>
*{margin:0;padding:0;box-sizing:border-box}
body{width:1200px;height:630px;background:#fff;overflow:hidden;
  font-family:"Inter","Helvetica Neue",Arial,"Microsoft YaHei",sans-serif;
  color:#0B0B0C;display:flex;flex-direction:column;position:relative}
.rule{height:14px;background:#FF4D00}
.wrap{flex:1;padding:54px 64px 0;display:flex;flex-direction:column}
.brand{display:flex;align-items:baseline;gap:14px;font-size:19px;font-weight:800;
  letter-spacing:.16em;text-transform:uppercase}
.brand i{width:13px;height:13px;background:#FF4D00;display:block;transform:translateY(-1px)}
.brand span{color:#6B7078;font-weight:600;letter-spacing:.08em}
h1{font-size:70px;line-height:1.06;letter-spacing:-.025em;font-weight:800;margin-top:30px}
h1 em{font-style:normal;color:#FF4D00}
.sub{margin-top:20px;font-size:23px;line-height:1.5;color:#4A4E56;max-width:900px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:#E4E7EB;
  border-top:1px solid #E4E7EB;border-bottom:1px solid #E4E7EB;margin-top:auto}
.kpi{background:#fff;padding:24px 26px 26px;position:relative}
.kpi:before{content:"";position:absolute;left:0;top:0;width:52px;height:4px;background:#FF4D00}
.kpi .l{font-size:14px;color:#6B7078;font-weight:700;letter-spacing:.04em}
.kpi .v{font-size:44px;font-weight:800;letter-spacing:-.02em;margin-top:9px;
  font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
.kpi .v u{text-decoration:none;font-size:17px;font-weight:700;color:#6B7078;margin-left:5px}
.kpi .d{font-size:14px;margin-top:7px;font-weight:700;color:#00703C}
.kpi .d.n{color:#4A4E56}
.foot{height:56px;display:flex;align-items:center;justify-content:space-between;
  padding:0 64px;background:#0B0B0C;color:#fff;font-size:16px;letter-spacing:.02em}
.foot b{color:#FF4D00}
.foot span{color:#B9BEC6;font-size:14px}
</style></head><body>
<div class="rule"></div>
<div class="wrap">
  <div class="brand"><i></i>SWSS Optimizer<span>二次供水泵房 · 多目标优化</span></div>
  <h1>错峰蓄水 <em>&harr;</em> 余氯衰减<br>把四笔钱算在同一张图上</h1>
  <div class="sub">浏览器内实时运行的二次供水泵房策略比选器：主泵电费 / 补氯设施折旧 / 计量泵电耗 / 药剂费，
    与用户端余氯、水箱水龄一起构成 Pareto 前沿。</div>
</div>
<div class="kpis">
  <div class="kpi"><div class="l">日总成本（推荐方案）</div>
    <div class="v">12.15<u>元/d</u></div><div class="d">比基线省 34.1%</div></div>
  <div class="kpi"><div class="l">用户端最低余氯</div>
    <div class="v">0.366<u>mg/L</u></div><div class="d">GB 5749 达标</div></div>
  <div class="kpi"><div class="l">补氯是否必要</div>
    <div class="v">阶跃<u>决策</u></div><div class="d n">+19 元/d，余氯仅 +0.04</div></div>
</div>
<div class="foot"><div>0 依赖 · 单文件 · 打开即算</div>
  <div><b>600</b> 组方案扫描 &nbsp;·&nbsp; <span>Python ⇄ JS 双向交叉校验</span></div></div>
</body></html>"""


def main():
    tmp = os.path.join(ROOT, "out", "_og_card.html")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(CARD)
    url = "file:///" + tmp.replace("\\", "/")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1200, "height": 630},
                        device_scale_factor=1)
        pg.goto(url, wait_until="load")
        pg.wait_for_timeout(350)
        pg.screenshot(path=OUT, clip={"x": 0, "y": 0, "width": 1200, "height": 630})
        b.close()
    os.remove(tmp)
    print("已生成 %s（%.1f KB）" % (OUT, os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
