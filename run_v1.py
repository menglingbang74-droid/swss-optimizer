"""扫描决策空间，求 Pareto 前沿，导出 out/pareto.json（供前端 demo 直接使用）。

决策变量：
  v_tank        水箱容积 m3            —— 决定调蓄能力（=避峰能力）
  price_thresh  允许补水的最高电价 元/kWh —— 决定避峰深度
  v_off_frac    维持液位（占水箱容积）    —— 决定日常存水量
  dose          二次补氯投加量 mg/L     —— 决定水质补偿强度（同时也是成本阶跃开关）

目标： min 日总成本(元/d)   max 末端最低余氯(mg/L)
  日总成本 = 主泵提升电费 + 补氯设施日均固定支出(折旧+运维) + 计量泵电耗 + 次氯酸钠药剂费
约束： 不缺水；末端最低余氯 ≥ 内控目标（默认取 GB 5749 限值 0.05 mg/L，作为"达标"筛选）
"""
import sys, os, json, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from swss.model import simulate, DEFAULTS, tariff_vector

PR = tariff_vector()

GRID = dict(
    v_tank=[40.0, 60.0, 80.0, 100.0, 120.0, 150.0],
    price_thresh=[9.9, 1.30, 1.05, 0.80, 0.65],
    v_off_frac=[0.40, 0.55, 0.70, 0.85, 0.95],
    dose=[0.0, 0.2, 0.4, 0.8],
)


def mask_from(threshold):
    return np.where(PR >= threshold, 0, 1).astype(int)


def pareto_mask(cost, quality):
    """返回 True 表示 Pareto 非支配（cost 越小越好，quality 越大越好）"""
    n = len(cost)
    cost = np.asarray(cost, float)
    qual = np.asarray(quality, float)
    keep = np.ones(n, bool)
    for i in range(n):
        if not keep[i]:
            continue
        dom = (cost <= cost[i]) & (qual >= qual[i]) & ((cost < cost[i]) | (qual > qual[i]))
        dom[i] = False
        if dom.any():
            keep[i] = False
    # 去掉完全重复的点
    seen = set()
    for i in range(n):
        if keep[i]:
            key = (round(cost[i], 4), round(qual[i], 6))
            if key in seen:
                keep[i] = False
            else:
                seen.add(key)
    return keep


def main():
    t0 = time.time()
    pts = []
    for vt in GRID['v_tank']:
        for th in GRID['price_thresh']:
            for vf in GRID['v_off_frac']:
                for ds in GRID['dose']:
                    r = simulate(dict(v_tank=vt, mask=mask_from(th), v_off_frac=vf, dose=ds))
                    if not r['feasible']:
                        continue
                    pts.append(dict(
                        v_tank=vt, price_thresh=th, v_off_frac=vf, dose=ds,
                        cost=round(r['cost'], 3), cost_total=round(r['cost_total'], 3),
                        cost_dose=round(r['cost_dose'], 3),
                        cost_dose_fixed=round(r['cost_dose_fixed'], 3),
                        cost_dose_energy=round(r['cost_dose_energy'], 4),
                        cost_chem=round(r['cost_chem'], 4),
                        energy=round(r['energy'], 3),
                        min_ctap=round(r['min_ctap'], 4), mean_ctap=round(r['mean_ctap'], 4),
                        frac_below=round(r['frac_below'], 4),
                        max_age=round(r['max_age'], 2), mean_age=round(r['mean_age'], 2),
                        forced_vol=round(r['forced_vol'], 2),
                    ))
    print("扫描完成 %d 个可行方案，用时 %.1f s" % (len(pts), time.time() - t0))

    cost = [p['cost_total'] for p in pts]
    qual = [p['min_ctap'] for p in pts]
    keep = pareto_mask(cost, qual)
    front = [pts[i] for i in range(len(pts)) if keep[i]]
    front.sort(key=lambda p: p['cost_total'])
    print("Pareto 前沿 %d 个点" % len(front))

    # 基线：全天补水、维持液位 0.85、水箱 60 m3、不补氯（= 改造前现状）
    base = simulate(dict(mask=np.ones(24, int), v_off_frac=0.85, v_tank=60.0, dose=0.0))
    print("基线: 总成本 %.2f 元/d（提升电费 %.2f）| 能耗 %.2f kWh/d | 末端最低余氯 %.4f mg/L | 最大水龄 %.2f h"
          % (base['cost_total'], base['cost'], base['energy'], base['min_ctap'], base['max_age']))

    # 推荐：在达标(min_ctap >= 限值)的方案里，总成本最低者
    ok = [p for p in pts if p['min_ctap'] >= DEFAULTS['c_limit']]
    best = min(ok, key=lambda p: p['cost_total']) if ok else None
    if best:
        print("推荐（达标且最省）: 水箱 %.0f m3 | 避峰阈值 %.2f | 维持液位 %.2f | 补氯 %.1f mg/L"
              " -> 总成本 %.2f 元/d（省 %.1f%%）| 末端最低余氯 %.4f mg/L"
              % (best['v_tank'], best['price_thresh'], best['v_off_frac'], best['dose'],
                 best['cost_total'], 100 * (1 - best['cost_total'] / base['cost_total']),
                 best['min_ctap']))

    # 三条代表性策略的逐时曲线（用于前端绘制与人工核对）
    def trace(tag, **kw):
        r = simulate(kw)
        a = r['rec']
        return dict(tag=tag, cost=r['cost'], cost_total=r['cost_total'], energy=r['energy'],
                    min_ctap=r['min_ctap'],
                    max_age=r['max_age'], forced_vol=r['forced_vol'],
                    V=[round(x, 2) for x in a['V'][::10]],
                    C=[round(x, 4) for x in a['C'][::10]],
                    Ctap=[round(x, 4) for x in a['Ctap'][::10]],
                    A=[round(x, 2) for x in a['A'][::10]],
                    Qin=[round(x, 2) for x in a['Qin'][::10]],
                    D=[round(x, 2) for x in a['D'][::10]])

    traces = [
        trace("基线：全天补水", mask=np.ones(24, int), v_off_frac=0.85, v_tank=60.0, dose=0.0),
        trace("适度避峰（阈值1.05）", mask=mask_from(1.05), v_off_frac=0.85, v_tank=60.0, dose=0.0),
    ]
    if best:
        traces.append(trace("推荐方案", v_tank=best['v_tank'], mask=mask_from(best['price_thresh']),
                            v_off_frac=best['v_off_frac'], dose=best['dose']))

    out = dict(
        meta=dict(
            generated=time.strftime("%Y-%m-%d %H:%M:%S"),
            price=list(np.round(PR, 3)),
            baseline=dict(cost=round(base['cost'], 3), cost_total=round(base['cost_total'], 3),
                          energy=round(base['energy'], 3),
                          min_ctap=round(base['min_ctap'], 4), max_age=round(base['max_age'], 2),
                          q_daily=round(base['q_daily'], 2)),
            recommend=best,
            grid=GRID, c_limit=DEFAULTS['c_limit'],
            econ=dict(dose_capex=DEFAULTS['dose_capex'], dose_life_yr=DEFAULTS['dose_life_yr'],
                      dose_om_yr=DEFAULTS['dose_om_yr'], dose_pump_kw=DEFAULTS['dose_pump_kw'],
                      cl_price=DEFAULTS['cl_price'], cost_view=DEFAULTS['cost_view']),
            n_points=len(pts), n_front=len(front),
        ),
        points=pts,
        front=front,
        traces=traces,
    )
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "pareto.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("已导出 %s（%.1f KB）" % (path, os.path.getsize(path) / 1024))


if __name__ == "__main__":
    main()
