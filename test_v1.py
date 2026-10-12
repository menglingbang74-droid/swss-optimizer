"""核心模型自测：解析解对照 + 守恒校验 + 策略方向性 + 水箱容积约束。
运行： python test_v1.py
"""
import sys, os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from swss.model import simulate, DEFAULTS, HOURLY_PATTERN, tariff_vector

FAIL = []


def chk(name, cond, info=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("   " + info if info else ""))
    if not cond:
        FAIL.append(name)


PR = tariff_vector()
M_ALL = np.ones(24, dtype=int)
M_SHARP = np.where(PR >= 1.30, 0, 1)      # 只避尖峰 19–21
M_PEAK = np.where(PR >= 1.05, 0, 1)       # 避峰+尖峰
M_VALLEY = np.zeros(24, dtype=int)        # 只谷时段补水
M_VALLEY[0:7] = 1
M_VALLEY[23] = 1

print("=" * 72)
print("1) 解析解对照：零流量工况下 余氯指数衰减 / 水龄线性增长")
r = simulate(dict(quota_L=0.0, mask=np.zeros(24, dtype=int), dose=0.0,
                  n_days=1, t_water=20.0))
k = DEFAULTS['k20']
c_ana = DEFAULTS['c_mains'] * np.exp(-k * 24.0)
chk("余氯 C(24h) 与 exp(-kT) 一致", abs(r['rec']['C'][-1] - c_ana) < 1e-3,
    "数值 %.6f  解析 %.6f  k=%.4f /h" % (r['rec']['C'][-1], c_ana, k))
chk("水龄 A(24h) ≈ 24h（零流量）", abs(r['rec']['A'][-1] - 24.0) < 0.05,
    "数值 %.4f h" % r['rec']['A'][-1])

print("=" * 72)
print("2) 守恒校验（关闭衰减 k=0，全天补水）")
r2 = simulate(dict(mask=M_ALL, n_days=1, k20=0.0, dose=0.0))
rec = r2['rec']
dt = rec['t'][1] - rec['t'][0]
bal = (rec['Qin'][1:].sum() - rec['D'][1:].sum()) * dt
dv = rec['V'][-1] - rec['V'][0]
chk("水量平衡 Σ(Qin−D)·dt = ΔV", abs(bal - dv) < 1e-6, "ΔV=%.6f 平衡=%.6f" % (dv, bal))
m1 = rec['V'][-1] * rec['C'][-1]
mass = (rec['V'][0] * rec['C'][0]
        + (rec['Qin'][1:] * DEFAULTS['c_mains']).sum() * dt
        - (rec['D'][1:] * rec['C'][:-1]).sum() * dt)
chk("氯质量守恒（k=0）", abs(mass - m1) < 1e-2 * max(m1, 1e-9),
    "期末=%.4f 平衡推得=%.4f" % (m1, mass))

print("=" * 72)
print("3) 基线量级与准稳态收敛")
rb = simulate(dict(mask=M_ALL))
chk("日用水量 = 300户×3人×180L = 162 m3/d", abs(rb['q_daily'] - 162.0) < 1e-6, "%.2f" % rb['q_daily'])
chk("日提升总量 ≈ 日用水量（±2%）",
    abs(rb['rec']['Qin'].sum() * dt - rb['q_daily']) < 0.02 * rb['q_daily'],
    "ΣQin·dt=%.2f m3" % (rb['rec']['Qin'].sum() * dt))
chk("能耗量级合理 (15~32 kWh/d)", 15 < rb['energy'] < 32, "%.2f kWh/d" % rb['energy'])
chk("电费量级合理 (8~30 元/d)", 8 < rb['cost'] < 30, "%.2f 元/d" % rb['cost'])
chk("准稳态收敛（全周期日均 ≈ 准稳态日，±5%）",
    abs(rb['cost_all'] - rb['cost']) < 0.05 * rb['cost'],
    "全周期 %.3f vs 准稳态 %.3f 元/d" % (rb['cost_all'], rb['cost']))

print("=" * 72)
print("4) 策略方向性：避峰越激进 → 电费越低、末端余氯越低、水龄越长")
rows = []
for nm, mk in [("全天补水", M_ALL), ("避尖峰", M_SHARP), ("避峰+尖峰", M_PEAK), ("只谷时段", M_VALLEY)]:
    rows.append((nm, simulate(dict(mask=mk))))
print("  %-12s %9s %9s %11s %10s %10s %10s" % ("策略", "电费元/d", "kWh/d", "最低余氯", "最大水龄h", "平均水龄h", "被迫补m3"))
for nm, r in rows:
    print("  %-12s %9.2f %9.2f %11.4f %10.2f %10.2f %10.2f"
          % (nm, r['cost'], r['energy'], r['min_ctap'], r['max_age'], r['mean_age'], r['forced_vol']))
forced = [r['forced_vol'] for _, r in rows]
chk("避峰越激进 → 被迫在峰时段补水越多（低液位保护触发）",
    all(forced[i] <= forced[i + 1] for i in range(len(forced) - 1)),
    " -> ".join("%.1f" % f for f in forced))
chk("所有策略均不缺水（低液位强制补水保障安全）", all(r['feasible'] for _, r in rows),
    "最大 unmet=%.4f m3" % max(r['unmet'] for _, r in rows))
dE = abs(rows[-1][1]['energy'] - rows[0][1]['energy']) / rows[0][1]['energy']
dC = abs(rows[-1][1]['cost'] - rows[0][1]['cost']) / rows[0][1]['cost']
chk("能耗变化 << 电费变化（错峰省的是电费，不是电）", dE < dC,
    "|ΔE|/E=%.1f%%  <  |Δ费用|/费用=%.1f%%" % (100 * dE, 100 * dC))

print("-" * 72)
print("4b) 避峰深度的 U 型：不是越激进越好，过度避峰会反弹")
depths = [(9.9, "不避峰"), (1.30, "避尖峰"), (1.05, "避峰+尖峰"), (0.65, "连平段也避"), (0.35, "只谷时段")]
dc = []
for th, nm in depths:
    r = simulate(dict(mask=np.where(PR >= th, 0, 1)))
    dc.append(r['cost'])
    print("  %-12s 阈值 %5.2f 元 : 电费 %6.2f 元/d | 被迫补 %6.1f m3/d | 最低余氯 %.4f"
          % (nm, th, r['cost'], r['forced_vol'], r['min_ctap']))
i_best = int(np.argmin(dc))
chk("存在最优避峰深度（U 型，最优点不在两端）", 0 < i_best < len(dc) - 1,
    "最优 = 阈值 %.2f 元（第 %d 档）" % (depths[i_best][0], i_best + 1))
chk("过度避峰电费回升（低于适度避峰）", dc[-1] > dc[i_best],
    "只谷时段 %.2f > 最优 %.2f 元/d" % (dc[-1], dc[i_best]))
chk("适度避峰确实省电费", dc[i_best] < dc[0], "%.2f < %.2f 元/d" % (dc[i_best], dc[0]))

print("-" * 72)
print("4c) 核心权衡轴：维持液位 ↑ → 电费 ↓ 且 末端余氯 ↓（单调）")
lv = []
for f in (0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95):
    lv.append((f, simulate(dict(mask=M_PEAK, v_off_frac=f))))
print("  %8s %9s %11s %10s %10s" % ("维持液位", "电费元/d", "最低余氯", "平均水龄h", "被迫补m3"))
for f, r in lv:
    print("  %8.2f %9.2f %11.4f %10.2f %10.2f" % (f, r['cost'], r['min_ctap'], r['mean_age'], r['forced_vol']))
c2 = [r['cost'] for _, r in lv]
q2 = [r['min_ctap'] for _, r in lv]
a2 = [r['mean_age'] for _, r in lv]
chk("维持液位 ↑ → 电费单调下降", all(c2[i] > c2[i + 1] for i in range(len(c2) - 1)),
    " -> ".join("%.2f" % x for x in c2))
chk("维持液位 ↑ → 末端最低余氯单调下降", all(q2[i] > q2[i + 1] for i in range(len(q2) - 1)),
    " -> ".join("%.4f" % x for x in q2))
chk("维持液位 ↑ → 平均水龄单调上升", all(a2[i] < a2[i + 1] for i in range(len(a2) - 1)),
    " -> ".join("%.2f" % x for x in a2))

print("=" * 72)
print("5) 水箱容积约束：水箱越小，错峰收益被'低液位强制补水'吃掉越多")
sav60 = []
for vt in (40.0, 60.0, 90.0, 120.0):
    r_all = simulate(dict(mask=M_ALL, v_tank=vt))
    r_pk = simulate(dict(mask=M_PEAK, v_tank=vt))
    sav = 100 * (1 - r_pk['cost'] / r_all['cost'])
    sav60.append(sav)
    print("  水箱 %5.0f m3 : 全天 %.2f 元/d -> 避峰 %.2f 元/d | 省 %.1f%% | 被迫补 %5.2f m3/d | 最低余氯 %.4f"
          % (vt, r_all['cost'], r_pk['cost'], sav, r_pk['forced_vol'], r_pk['min_ctap']))
chk("水箱越大，避峰省钱比例越高（单调）",
    all(sav60[i] < sav60[i + 1] for i in range(len(sav60) - 1)),
    " -> ".join("%.1f%%" % s for s in sav60))
chk("小水箱被迫在峰时段补水（错峰失效）",
    simulate(dict(mask=M_PEAK, v_tank=40.0))['forced_vol']
    > simulate(dict(mask=M_PEAK, v_tank=120.0))['forced_vol'],
    "40m3 被迫补 %.2f m3/d vs 120m3 %.2f m3/d"
    % (simulate(dict(mask=M_PEAK, v_tank=40.0))['forced_vol'],
       simulate(dict(mask=M_PEAK, v_tank=120.0))['forced_vol']))

print("=" * 72)
print("6) 补氯的影响")
r0 = simulate(dict(mask=M_PEAK, dose=0.0))
r1 = simulate(dict(mask=M_PEAK, dose=0.4))
chk("投加 0.4 mg/L 提升末端最低余氯", r1['min_ctap'] > r0['min_ctap'],
    "%.4f -> %.4f mg/L" % (r0['min_ctap'], r1['min_ctap']))
chk("投加后衰减系数增大（文献：补氯后衰减速率增大）", r1['k_used'] > r0['k_used'],
    "%.5f -> %.5f /h" % (r0['k_used'], r1['k_used']))

print("=" * 72)
print("7) 水温敏感性（夏季 vs 冬季）")
rs = simulate(dict(mask=M_PEAK, t_water=28.0))
rw = simulate(dict(mask=M_PEAK, t_water=8.0))
chk("夏季(28C)末端余氯低于冬季(8C)", rs['min_ctap'] < rw['min_ctap'],
    "夏 %.4f < 冬 %.4f mg/L（k: %.4f vs %.4f /h）"
    % (rs['min_ctap'], rw['min_ctap'], rs['k_used'], rw['k_used']))

print("=" * 72)
print("8) 用水曲线")
chk("逐时用水率之和 = 1", abs(HOURLY_PATTERN.sum() - 1.0) < 1e-12)
chk("晚高峰(19时) > 5×凌晨(3时)", HOURLY_PATTERN[19] > 5 * HOURLY_PATTERN[3])

print("=" * 72)
print("9) 成本分解：补氯设施折旧/运维 + 计量泵电耗 + 次氯酸钠药剂费")
r_0 = simulate(dict(mask=M_PEAK, dose=0.0))
r_1 = simulate(dict(mask=M_PEAK, dose=0.1))
r_2 = simulate(dict(mask=M_PEAK, dose=0.2))
r_8 = simulate(dict(mask=M_PEAK, dose=0.8))
print("  %6s %10s %10s %10s %10s %10s %11s" % ("投加量", "提升电费", "折旧+运维", "计量泵电", "药剂费", "总成本", "最低余氯"))
for nm, r in [("0.0", r_0), ("0.1", r_1), ("0.2", r_2), ("0.8", r_8)]:
    print("  %6s %10.2f %10.2f %10.3f %10.3f %10.2f %11.4f"
          % (nm, r['cost'], r['cost_dose_fixed'], r['cost_dose_energy'], r['cost_chem'],
             r['cost_total'], r['min_ctap']))

chk("不补氯时 补氯成本为 0（设施未启用，折旧不计入）",
    r_0['cost_dose'] == 0.0 and abs(r_0['cost_total'] - r_0['cost']) < 1e-9,
    "补氯成本 %.4f 元/d" % r_0['cost_dose'])
amort = DEFAULTS['dose_capex'] / (DEFAULTS['dose_life_yr'] * 365.0)
om_d = DEFAULTS['dose_om_yr'] / 365.0
chk("全成本口径：固定支出 = 折旧 + 年运维",
    abs(r_2['cost_dose_fixed'] - (amort + om_d)) < 1e-9,
    "%.4f = %.4f + %.4f 元/d" % (r_2['cost_dose_fixed'], amort, om_d))
chk("药剂费与投加量成正比（0.4 是 0.2 的两倍）",
    abs(r_8['cost_chem'] / r_2['cost_chem'] - 4.0) < 0.02,
    "0.8/0.2 = %.3f（投加量比 4×）" % (r_8['cost_chem'] / r_2['cost_chem']))
chk("药剂费 = 投加量 × 泵送水量 ÷ 1000 × 有效氯单价",
    abs(r_2['cost_chem'] - 0.2 * r_2['vol_pumped'] / 1000.0 * DEFAULTS['cl_price']) < 1e-9,
    "%.4f 元/d" % r_2['cost_chem'])
chk("泵送水量 ≈ 日用水量（无溢流）",
    abs(r_2['vol_pumped'] - r_2['q_daily']) < 0.02 * r_2['q_daily'],
    "%.2f vs %.2f m3/d" % (r_2['vol_pumped'], r_2['q_daily']))
mean_price = float(np.mean([PR[int(i)] for i in range(24)]))
chk("计量泵电耗 ≈ 功率 × 运行时长",
    abs(r_2['energy_dose'] - DEFAULTS['dose_pump_kw'] * r_2['pump_hours']) < 1e-6,
    "%.4f kWh/d = %.2f kW × %.2f h" % (r_2['energy_dose'], DEFAULTS['dose_pump_kw'], r_2['pump_hours']))

step_on = r_1['cost_total'] - r_0['cost_total']          # 0 -> 0.1 mg/L
step_up = r_8['cost_total'] - r_1['cost_total']          # 0.1 -> 0.8 mg/L
chk("补氯是成本阶跃，不是连续调节（启用成本 >> 加量成本）",
    step_on > 5 * step_up and step_on > 10.0,
    "启用 +%.2f 元/d（其中固定 %.2f） vs 0.1→0.8 再加 %.2f 元/d"
    % (step_on, r_1['cost_dose_fixed'], step_up))
chk("前置结论：补氯固定支出量级与主泵电费相当（同量级，不可忽略）",
    0.5 * r_0['cost'] < r_1['cost_dose_fixed'] < 3.0 * r_0['cost'],
    "固定 %.2f 元/d vs 主泵电费 %.2f 元/d" % (r_1['cost_dose_fixed'], r_0['cost']))

r_run = simulate(dict(mask=M_PEAK, dose=0.2, cost_view='run'))
chk("仅运行口径：折旧不计入，固定支出 = 年运维",
    abs(r_run['cost_dose_fixed'] - om_d) < 1e-9,
    "%.4f 元/d" % r_run['cost_dose_fixed'])
chk("仅运行口径总成本 < 全成本口径",
    r_run['cost_total'] < r_2['cost_total'],
    "%.2f < %.2f 元/d" % (r_run['cost_total'], r_2['cost_total']))
chk("两种口径都不改变余氯（成本口径不影响水质）",
    abs(r_run['min_ctap'] - r_2['min_ctap']) < 1e-12)

print("-" * 72)
print("9b) 余氯内控目标调高 → 补氯从'不划算'变成'必须'")
for tgt in (0.05, 0.55, 0.60):
    need = [d for d in (0.0, 0.2, 0.4, 0.8)
            if simulate(dict(mask=M_PEAK, v_tank=40.0, v_off_frac=0.85, dose=d))['min_ctap'] >= tgt]
    print("  内控目标 %.2f mg/L : 满足的投加量 = %s" % (tgt, need if need else "无"))
lo = simulate(dict(mask=M_PEAK, v_tank=40.0, v_off_frac=0.85, dose=0.0))
chk("内控目标 0.05 时 不补氯即可达标（默认工况余氯不是瓶颈）",
    lo['min_ctap'] >= 0.05, "最低余氯 %.4f mg/L" % lo['min_ctap'])

print("=" * 72)
print("10) 边界工况：满溢守恒 + 水质超标判定")
print("-" * 72)
print("10a) 小水箱 + 目标液位设到满容积 + 泵能力富余 → 触发溢流")
r_ov = simulate(dict(v_tank=30.0, v_off_frac=1.0, q_pump=45.0, mask=M_ALL, n_days=3, dose=0.0))
dt_ov = r_ov['rec']['t'][1] - r_ov['rec']['t'][0]
bal_ov = (r_ov['rec']['Qin'][1:].sum() - r_ov['rec']['D'][1:].sum()) * dt_ov
dv_ov = r_ov['rec']['V'][-1] - r_ov['rec']['V'][0]
print("  水箱 30 m3 / 目标液位 100%% / 泵 45 m3/h ：溢流 %.2f m3/d（占日用水 %.0f%%），V 峰 %.2f m3"
      % (r_ov['overflow'], 100 * r_ov['overflow'] / r_ov['q_daily'], r_ov['rec']['V'].max()))
chk("溢流分支确实被触发", r_ov['overflow'] > 0, "溢流 %.2f m3/d" % r_ov['overflow'])
chk("溢流工况下水量平衡 Σ(Qin−D)·dt = ΔV 仍成立（进水被正确截断）",
    abs(bal_ov - dv_ov) < 1e-6,
    "ΔV=%.6f  平衡=%.6f" % (dv_ov, bal_ov))

print("-" * 72)
print("10b) 大水箱 + 仅谷时段补水 + 高衰减 → 停留时间过长、末端余氯低于限值")
r_bad = simulate(dict(v_tank=150.0, v_off_frac=0.90, mask=M_VALLEY,
                      k20=0.20, t_water=32.0, dose=0.0))
print("  水箱 150 m3 / 仅 23–7 补水 / k20=0.20 / 32C ：最低余氯 %.4f mg/L，最大水龄 %.1f h"
      % (r_bad['min_ctap'], r_bad['max_age']))
chk("末端最低余氯 < GB 5749 限值 0.05 mg/L", r_bad['min_ctap'] < DEFAULTS['c_limit'],
    "%.4f < %.2f mg/L（k=%.4f /h）" % (r_bad['min_ctap'], DEFAULTS['c_limit'], r_bad['k_used']))
chk("低于限值的时间占比 frac_below > 0", r_bad['frac_below'] > 0,
    "%.1f%% 的时段低于限值" % (100 * r_bad['frac_below']))
r_good = simulate(dict(mask=M_PEAK, k20=0.02, t_water=12.0, dose=0.0))
chk("低温 + 低衰减 → 全程达标（frac_below = 0）", r_good['frac_below'] == 0.0,
    "最低余氯 %.4f mg/L" % r_good['min_ctap'])

print("=" * 72)
print("RESULT: " + ("ALL PASS" if not FAIL else "FAILED -> " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
