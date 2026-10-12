"""
SWSS Optimizer — 二次供水泵房「错峰蓄水 <-> 余氯衰减」核心模型
构型：高位调蓄水箱(屋顶) + 补水泵(从市政管网提水) + 重力流供水至用户

物理假设：
  1) 水箱按完全混合反应器(CSTR)处理，余氯衰减取一级动力学
  2) 补水泵间歇运行，由液位滞环控制(V_on 开泵 / V_off 停泵)
  3) 泵扬程 = 几何扬程 + 水箱水深 - 市政管网可用压力水头（液位越高越费电）
  4) 用户端余氯 = 水箱出口浓度 * exp(-k * 立管停留时间)

单位：体积 m3，流量 m3/h，时间 h，浓度 mg/L，能耗 kWh，费用 元
"""

import numpy as np

# ---------------------------------------------------------------- 用水曲线
# 住宅逐时用水模式（相对值），取自常见设计资料的住宅时变化曲线形态，代码内归一化。
# 参考取值，工程应用请以 GB 50015《建筑给水排水设计标准》原文核对。
HOURLY_PATTERN = np.array([
    1.0, 0.5, 0.4, 0.4, 0.5, 1.0,   # 0-5
    3.0, 5.5, 5.0, 4.0, 3.5, 3.2,   # 6-11
    4.5, 4.0, 3.2, 3.0, 3.3, 4.0,   # 12-17
    5.5, 6.0, 5.5, 4.5, 3.0, 1.8,   # 18-23
], dtype=float)
HOURLY_PATTERN = HOURLY_PATTERN / HOURLY_PATTERN.sum()   # 归一化，和为 1


def make_demand(q_daily_m3, pattern=HOURLY_PATTERN):
    """返回 24 个时段(小时)的平均用水量 m3/h。q_daily_m3: 最高日用水量 m3/d"""
    return q_daily_m3 * pattern          # 每个元素即该小时的 m3（1h 时段）


def demand_at(demand_hourly, t):
    """t 为小时(浮点)，线性插值得到瞬时流量 m3/h"""
    t = t % 24.0
    i = int(t)
    f = t - i
    a = demand_hourly[i]
    b = demand_hourly[(i + 1) % 24]
    return a * (1 - f) + b * f


# ---------------------------------------------------------------- 分时电价
# 华东地区一般工商业分时电价示例（参考值），demo 内可替换。
# 结构：[(起始小时, 结束小时, 单价元/kWh)]，区间为 [start, end)
TARIFF_DEFAULT = [
    (0, 7, 0.35),      # 谷
    (7, 8, 0.65),      # 平
    (8, 11, 1.05),     # 峰
    (11, 17, 0.65),    # 平
    (17, 19, 1.05),    # 峰
    (19, 21, 1.30),    # 尖峰
    (21, 22, 1.05),    # 峰
    (22, 23, 0.65),    # 平
    (23, 24, 0.35),    # 谷
]


def price_at(t, tariff=TARIFF_DEFAULT):
    h = int(t) % 24
    for s, e, p in tariff:
        if s <= h < e:
            return p
    return tariff[-1][2]


def tariff_vector(tariff=TARIFF_DEFAULT):
    return np.array([price_at(h, tariff) for h in range(24)], dtype=float)


# ---------------------------------------------------------------- 参数默认值
DEFAULTS = dict(
    # --- 小区与建筑 ---
    n_household=300,        # 户数
    persons=3.0,            # 户均人数
    quota_L=180.0,          # 人均最高日用水定额 L/(人·d)，GB 50015 普通住宅 II 型参考区间 130~220
    h_geo=54.0,             # 几何扬程 m（屋顶水箱高于补水泵入口），约 18 层
    p_mains_m=20.0,         # 市政管网可用压力折算水头 m（0.20 MPa）
    # --- 水箱 ---
    v_tank=60.0,            # 水箱总容积 m3
    a_tank_frac=0.42,       # 水箱平面面积 = a_tank_frac × 容积（默认满水深约 2.4 m）
                            # 需特定尺寸时可直接传 a_tank 覆盖
    v_dead_frac=0.08,       # 死水容积占比（不可取用）
    # --- 泵 ---
    q_pump=30.0,            # 补水泵额定流量 m3/h
    eta=0.72,               # 泵+电机+变频综合效率
    # --- 水质 ---
    c_mains=0.8,            # 市政来水余氯 mg/L
    k20=0.05,               # 20C 时一级衰减系数 1/h（参考区间 0.02~0.15，需实测率定）
    theta=1.035,            # 温度系数 van't Hoff（参考区间 1.02~1.05）
    t_water=22.0,           # 水温 C
    beta_dose=0.15,         # 投加量对衰减速率的放大系数 1/(mg/L)（文献：补氯后衰减速率增大）
    tau_riser=0.5,          # 立管停留时间 h
    c_limit=0.05,           # 用户端余氯限值 mg/L（GB 5749 管网末梢 ≥0.05）
    # --- 补氯设施经济性（次氯酸钠投加装置）---
    # 全部为工程参考取值中位，需在 UI 中开放调整；结论对"成本口径"极敏感
    dose_capex=30000.0,     # 补氯装置投资 元（计量泵+储罐+余氯在线仪+自控），参考区间 2~5 万
    dose_life_yr=8.0,       # 折旧年限 a
    dose_om_yr=3000.0,      # 年运维费 元/a（标定、巡检、维护人工）
    dose_pump_kw=0.15,      # 计量泵功率 kW（与补水泵同步运行）
    cl_price=10.0,          # 有效氯单价 元/kg（次氯酸钠有效氯 10% 溶液约 800~1300 元/t 折算）
    cost_view='full',       # 'full'=全成本(含折旧) | 'run'=仅运行成本(折旧视为沉没)
    # --- 控制策略：分时目标液位 ---
    # 允许补水的时段内把水箱维持在 v_off；禁止补水的时段靠存量重力供水。
    # 低液位强制补水(v_guard)为安全优先，与电价无关。
    v_off_frac=0.85,        # 目标维持液位 = v_off_frac × 水箱容积
    v_guard_frac=0.25,      # 强制补水液位 = 死水 + v_guard_frac × 有效容积
    db_frac=0.05,           # 液位死区（占水箱容积），避免泵短周期启停
    # --- 仿真 ---
    dt=1.0 / 60.0,          # 步长 h（1 min）
    n_days=3,               # 仿真天数，取最后一天作为准稳态
)


# ---------------------------------------------------------------- 核心仿真
def simulate(p):
    """运行一次完整仿真。

    真实决策变量（放在 p 里）：
      mask      : 长度 24 的 0/1 数组，1 表示该小时允许开泵补水（缺省=全天允许）
      v_off     : 目标维持液位对应容积 m3（或给 v_off_frac，按容积比例）
      v_guard   : 低液位强制补水保护值 m3（或给 v_guard_frac）
      dose      : 二次补氯投加量 mg/L
    说明：v2 起控制律为「分时目标液位 + 低液位保护」，
          不再使用 v1 的滞环双阈值 v_on/v_off（v_on 已移除）。

    返回 dict，含逐时序列与评价指标。
    """
    d = dict(DEFAULTS)
    d.update(p)
    p = d

    dt = p['dt']
    n_days = p['n_days']
    q_daily = p['n_household'] * p['persons'] * p['quota_L'] / 1000.0   # m3/d
    demand = make_demand(q_daily)

    v_tank = p['v_tank']
    a_tank = p.get('a_tank', p['a_tank_frac'] * v_tank)
    p['a_tank'] = a_tank
    v_dead = v_tank * p['v_dead_frac']
    v_max_usable = v_tank
    v_off = float(np.clip(p.get('v_off', p['v_off_frac'] * v_tank),
                          v_dead + 1.0, v_max_usable))
    v_guard = float(np.clip(p.get('v_guard', v_dead + p['v_guard_frac'] * (v_tank - v_dead)),
                            v_dead + 0.2, min(v_off - 1.0, v_max_usable)))
    db = p['db_frac'] * v_tank
    # mask 缺省 = 全天允许补水（与 baseline_always_on 语义一致），
    # 避免 simulate({}) 抛 KeyError 这种不友好的失败方式
    mask = np.asarray(p.get('mask', np.ones(24, dtype=int)), dtype=int)

    # 衰减系数：温度修正 + 投加量放大
    k_T = p['k20'] * (p['theta'] ** (p['t_water'] - 20.0))
    dose = float(p.get('dose', 0.0))
    k = k_T * (1.0 + p['beta_dose'] * dose)

    c_in = p['c_mains'] + dose          # 进入水箱的余氯（补氯投加在进水管上）
    tau_riser = p['tau_riser']

    # 初始状态：水箱半满、浓度等于来水浓度、水龄 0
    V = 0.5 * (v_guard + v_off)
    C = c_in
    A = 0.0                              # 水龄 h

    n_steps = int(round(24.0 / dt)) * n_days
    # 记录最后一天
    rec_n = int(round(24.0 / dt))
    rec = dict(t=[], V=[], C=[], Ctap=[], A=[], Qin=[], D=[], E=[], price=[])
    first_rec = n_steps - rec_n

    cost = 0.0          # 只累计"准稳态日"（最后一天）的费用/能耗
    energy = 0.0
    cost_all = 0.0      # 全部天数（用于观察收敛）
    energy_all = 0.0
    unmet = 0.0
    overflow = 0.0
    forced_vol = 0.0        # 在禁止补水时段因低液位保护而被迫提升的水量 m3
    pump_on = False

    # --- 补氯侧累计量（准稳态日）---
    dosing = dose > 1e-9                 # 是否启用补氯装置
    vol_pumped = 0.0                     # 准稳态日泵送水量 m3（决定药剂投加基数）
    pump_hours = 0.0                     # 准稳态日补水泵运行小时 h（计量泵同步）
    energy_dose = 0.0                    # 计量泵电耗 kWh/d
    cost_dose_energy = 0.0               # 计量泵电费 元/d

    for i in range(n_steps):
        t = i * dt
        h = t % 24.0
        hour_idx = int(h)

        D = demand_at(demand, h)

        # ---- 补水控制：分时目标液位 ----
        # 优先级：低液位强制补水(安全) > 时段允许 > 维持液位死区
        allowed = bool(mask[hour_idx])
        forced = (V <= v_guard)
        if forced:
            pump_on = True                      # 安全优先，不看电价
        elif not allowed:
            pump_on = False                     # 错峰：禁止补水，靠存量供水
        else:
            if V <= v_off - db:
                pump_on = True
            elif V >= v_off:
                pump_on = False
            # 死区内保持上一状态，避免短周期启停
        q_in = p['q_pump'] if pump_on else 0.0
        if pump_on and not allowed:
            forced_vol += q_in * dt             # 被"低液位保护"吃掉的错峰收益

        # ---- 水量平衡（带容积限幅，并保持质量守恒）----
        v_new = V + (q_in - D) * dt
        d_eff = D                                 # 实际供出的流量
        if v_new > v_max_usable:                  # 溢流：进水被截断
            overflow += (v_new - v_max_usable)
            q_in = max(0.0, (v_max_usable - V) / dt + D)
            v_new = v_max_usable
        if v_new < v_dead:                        # 抽空：只能供出库存，缺口计入 unmet
            d_eff = max(0.0, (V - v_dead) / dt + q_in)
            unmet += (D - d_eff) * dt
            v_new = v_dead
        D = d_eff

        # ---- 能耗（扬程随液位变化）----
        if q_in > 0:
            h_tank = V / p['a_tank']                          # 当前水深 m
            H = p['h_geo'] + h_tank - p['p_mains_m']          # 净扬程 m
            H = max(H, 1.0)
            e = q_in * H / (367.0 * p['eta']) * dt            # kWh
            energy_all += e
            cost_all += e * price_at(h)
            if i >= first_rec:
                energy += e
                cost += e * price_at(h)
                vol_pumped += q_in * dt
                pump_hours += dt
                if dosing:                                  # 计量泵与补水泵同步运行
                    ed = p['dose_pump_kw'] * dt
                    energy_dose += ed
                    cost_dose_energy += ed * price_at(h)
        else:
            e = 0.0

        # ---- 水质：CSTR + 一级衰减 ----
        dVC = (q_in * c_in - D * C - k * V * C) * dt
        VC_new = V * C + dVC
        # ---- 水龄：进水水龄 0，水体自身老化 +V*dt ----
        dVA = (q_in * 0.0 - D * A + V) * dt
        VA_new = V * A + dVA

        V = v_new
        C = VC_new / V if V > 1e-9 else 0.0
        A = VA_new / V if V > 1e-9 else 0.0
        C = max(C, 0.0)

        c_tap = C * np.exp(-k * tau_riser)

        if i >= first_rec:
            rec['t'].append(t - (n_days - 1) * 24.0)
            rec['V'].append(V)
            rec['C'].append(C)
            rec['Ctap'].append(c_tap)
            rec['A'].append(A)
            rec['Qin'].append(q_in)
            rec['D'].append(D)
            rec['E'].append(e)
            rec['price'].append(price_at(h))

    arr = {kk: np.array(vv) for kk, vv in rec.items()}
    ctap = arr['Ctap']
    feasible = (unmet <= 1e-6)

    # ---------------------------------------------------------------- 成本分解
    # 药剂费：投加在进水管上，只对"泵送的水量"投加
    #   dose[mg/L] × V[m3/d] = dose×V [g/d] = dose×V/1000 [kg/d 有效氯]
    dose_mass = dose * vol_pumped / 1000.0           # kg/d 有效氯
    cost_chem = dose_mass * p['cl_price']            # 元/d
    # 补氯设施日均固定支出：投资折旧 + 年运维
    amort = p['dose_capex'] / (p['dose_life_yr'] * 365.0)
    om_d = p['dose_om_yr'] / 365.0
    if not dosing:
        cost_dose_fixed = 0.0
    elif p['cost_view'] == 'run':
        cost_dose_fixed = om_d                       # 已建视角：折旧是沉没成本
    else:
        cost_dose_fixed = amort + om_d               # 新建视角：全成本
    cost_dose = cost_dose_fixed + cost_dose_energy + cost_chem
    cost_total = cost + cost_dose

    return dict(
        rec=arr,
        cost=float(cost),                            # 主泵提升电费（准稳态日）
        cost_total=float(cost_total),                # 日总成本 = 提升电费 + 补氯成本
        cost_dose=float(cost_dose),                  # 补氯侧合计（固定+电耗+药剂）
        cost_dose_fixed=float(cost_dose_fixed),
        cost_dose_energy=float(cost_dose_energy),
        cost_chem=float(cost_chem),
        dose_mass=float(dose_mass),
        vol_pumped=float(vol_pumped),
        pump_hours=float(pump_hours),
        energy=float(energy),                        # kWh/天（准稳态日）
        energy_dose=float(energy_dose),
        cost_all=float(cost_all / max(n_days, 1)),   # 全周期日均（收敛性对照）
        energy_all=float(energy_all / max(n_days, 1)),
        min_ctap=float(ctap.min()) if len(ctap) else 0.0,
        mean_ctap=float(ctap.mean()) if len(ctap) else 0.0,
        frac_below=float((ctap < p['c_limit']).mean()) if len(ctap) else 0.0,
        max_age=float(arr['A'].max()) if len(arr['A']) else 0.0,
        mean_age=float(arr['A'].mean()) if len(arr['A']) else 0.0,
        unmet=float(unmet),
        overflow=float(overflow),
        forced_vol=float(forced_vol),
        v_off=v_off,
        v_guard=v_guard,
        feasible=feasible,
        q_daily=float(q_daily),
        k_used=float(k),
    )


# ---------------------------------------------------------------- 基线策略
# v1 的滞环双阈值辅助函数 baseline_always_on() 已移除：
# 控制律改为「分时目标液位」后它不再被任何模块调用，
# 且其中设置的 v_on 是无人读取的死参数。
# 基线工况现在直接表达为：simulate(dict(mask=np.ones(24, int), v_off_frac=0.85,
#                                      v_tank=60.0, dose=0.0))
