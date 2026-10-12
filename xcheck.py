"""Python 侧基准值，供 Node 端 JS 模型交叉校验（确保两端模型完全一致）。"""
import os, json, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from swss.model import simulate, tariff_vector

PR = tariff_vector()
# 覆盖：不同水箱/避峰深度/维持液位/投加量 + 不同经济参数与成本口径
CASES = [
    dict(v_tank=60, th=1.05, v_off_frac=0.85, dose=0.0),
    dict(v_tank=60, th=9.90, v_off_frac=0.85, dose=0.0),
    dict(v_tank=120, th=1.05, v_off_frac=0.95, dose=0.4),
    dict(v_tank=40, th=0.65, v_off_frac=0.40, dose=0.2),
    dict(v_tank=150, th=1.30, v_off_frac=0.55, dose=0.0, k20=0.15, t_water=28),
    dict(v_tank=80, th=1.05, v_off_frac=0.70, dose=0.4, n_household=600, quota_L=220, h_geo=90),
    dict(v_tank=60, th=1.05, v_off_frac=0.85, dose=0.0, c_mains=0.35, t_water=8),
    dict(v_tank=100, th=1.05, v_off_frac=0.85, dose=0.8, dose_capex=50000, dose_life_yr=12,
         dose_om_yr=6000, cl_price=16.0),
    dict(v_tank=100, th=1.05, v_off_frac=0.85, dose=0.3, dose_capex=20000, dose_life_yr=6,
         dose_om_yr=1200, cl_price=6.0, cost_view='run'),
    dict(v_tank=150, th=0.65, v_off_frac=0.40, dose=0.6, cost_view='run', t_water=30, k20=0.12),
]

SCALARS = ("cost", "cost_total", "cost_dose", "cost_dose_fixed", "cost_dose_energy",
           "cost_chem", "dose_mass", "vol_pumped", "pump_hours", "energy_dose",
           "energy", "min_ctap", "mean_ctap", "max_age", "mean_age",
           "forced_vol", "unmet", "overflow", "frac_below", "k_used", "q_daily",
           "v_off", "v_guard")

out = []
for c in CASES:
    p = dict(c)
    th = p.pop("th")
    p["mask"] = np.where(PR >= th, 0, 1).astype(int)
    r = simulate(p)
    row = dict(input=c)
    for k in SCALARS:
        row[k] = float(r[k])
    row["V_first10"] = [round(float(x), 4) for x in r["rec"]["V"][:10]]
    row["C_last5"] = [round(float(x), 5) for x in r["rec"]["C"][-5:]]
    out.append(row)

os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"), exist_ok=True)
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "xcheck.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("已写出 %d 个基准算例 × %d 个指标 -> %s" % (len(out), len(SCALARS), path))
