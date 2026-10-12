"""把 out/pareto.json 注入 web/template.html，产出自包含的 web/index.html。"""
import os, json

ROOT = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(ROOT, "web", "template.html")
OUT = os.path.join(ROOT, "web", "index.html")
DATA = os.path.join(ROOT, "out", "pareto.json")


# 前端需要的字段（保持 snake_case，前端读取口径统一）
FIELDS = ("v_tank", "price_thresh", "v_off_frac", "dose",
          "cost", "cost_total", "cost_dose", "cost_dose_fixed",
          "cost_dose_energy", "cost_chem", "energy",
          "min_ctap", "max_age", "forced_vol")


def _slim(p):
    return {k: p[k] for k in FIELDS if k in p}


def main():
    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    with open(TPL, encoding="utf-8") as f:
        html = f.read()
    if "__PARETO_JSON__" not in html:
        print("模板中没有占位符 __PARETO_JSON__，跳过注入")
        data = "{}"
    else:
        with open(DATA, encoding="utf-8") as f:
            data = json.load(f)
        # 只保留前端需要的字段，减小体积
        slim = dict(
            meta=dict(baseline=data["meta"]["baseline"], grid=data["meta"]["grid"],
                      c_limit=data["meta"]["c_limit"], generated=data["meta"]["generated"]),
            points=[_slim(p) for p in data["points"]],
            front=[_slim(p) for p in data["front"]],
        )
        data = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
    html = html.replace("__PARETO_JSON__", data)
    # OG 分享图：本地预览用相对路径；部署时设 SITE_URL 生成绝对地址（爬虫更可靠）
    site = os.environ.get("SITE_URL", "").rstrip("/")
    og = (site + "/og.png") if site else "og.png"
    html = html.replace("__OG_IMAGE__", og)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("已生成 %s（%.1f KB，自包含，双击即可打开）" % (OUT, os.path.getsize(OUT) / 1024))
    print("  og:image = %s（设环境变量 SITE_URL 可生成绝对地址）" % og)


if __name__ == "__main__":
    main()
