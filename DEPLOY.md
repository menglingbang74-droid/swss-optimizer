# 上线操作清单

目标：把本地这个项目推到 GitHub，开启 GitHub Pages，拿到一个**能点开的链接**——
简历上唯一有价值的就是这个链接。

当前状态：本地 `main` 有 3 个提交，工作区干净，**尚未配置 remote、尚未推送**。

---

## 0. 先解决仓库名（重要）

你账号下现在有 3 个仓库，都是空的：

| 仓库 | 状态 |
|---|---|
| `-` | 空 · 名字是坏的 |
| `AI-` | 空 · 名字是坏的 |
| `campus-job-targeting` | 空 · 名字正常 |

`-` 和 `AI-` 看着像创建时被截断了。**仓库名会直接出现在简历链接里**：

```
https://menglingbang74-droid.github.io/AI-/                ← 面试官会愣一下
https://menglingbang74-droid.github.io/swss-optimizer/     ← 直接说明这是什么
```

**推荐**：把 `AI-` 重命名成 `swss-optimizer`（不用重建，历史和设置都保留）
> `AI-` 仓库页 → **Settings** → 顶部 **Rename** → 填 `swss-optimizer` → Rename

另外两个坏名字的仓库顺手删掉或改名，别留在主页上。

> 重命名**不影响**已经推上去的内容，Pages 地址会跟着仓库名自动变。
> 所以「先推后改名」也没问题，顺序随意。

---

## 1. 拿 token（两条路都需要，1 分钟）

1. 打开 <https://github.com/settings/tokens> → **Generate new token (classic)**
2. Note 填 `deploy`，Expiration 选 **7 天**（用完就过期，最安全）
3. **勾两个权限**：
   - ☑ `repo`（读写仓库内容）
   - ☑ `workflow`（**必需**——不勾的话，含 `.github/workflows/pages.yml` 的提交会被 GitHub 直接拒绝）
4. Generate → 复制那串 `ghp_...`

验证完成后到同一页面 **把这个 token 删掉**。

---

## 2. 选一条路

### 路线 A：我代跑（你只需把 token 发我）

我这边（沙箱）**能访问 `api.github.com`，但访问不到 `github.com`**——
出口代理会拦掉 git 的 CONNECT 隧道，实测 `git push` 报
`CONNECT tunnel failed, response 502`。所以在这个环境里 `git push` 不可用。

因此我改用 **GitHub Git Data API**（blobs → tree → commit → ref）把内容放上去，
效果等价，已写好脚本：`deploy_api.py`。

你把 token 发我，我执行：

```bash
python deploy_api.py --owner menglingbang74-droid --repo swss-optimizer
```

它会：校验 token 与权限 → 上传 24 个文件 → 建提交 → 建/更新 `main` →
开启 Pages（source = GitHub Actions）→ 打印仓库与在线地址。

> 想先看它要动什么、不写入任何东西：加 `--dry-run`。

### 路线 B：你自己跑（推荐，你本机 `github.com` 是通的）

```bash
# 项目根目录，Git Bash 里执行
bash deploy.sh
```

脚本会把「校验 token → 配 remote → push → 开启 Pages → 轮询部署 → 打印链接」全串起来，
**token 不写入任何文件 / URL / shell 历史**。

### 路线 C：完全手动

```bash
git remote add origin https://github.com/menglingbang74-droid/swss-optimizer.git
git push -u origin main     # 弹登录：用户名填 GitHub 用户名，密码填 token
```

**然后必须手动开一次 Pages**（A、B 两条路都会帮你做）：

> 仓库 → **Settings** → 左侧 **Pages** → **Source** 选 **GitHub Actions**

不设这一步，CI 的 `deploy` 步骤会失败并报
`Get Pages site failed. Please verify that the repository has Pages enabled`。

---

## 3. 部署后自查（30 秒）

1. 打开 <https://menglingbang74-droid.github.io/swss-optimizer/>
   - Pages 首次生效可能等 1–2 分钟，**404 先刷新再等一会**
2. 页面上拖两个滑杆、点一次「重新计算 Pareto」，确认不死锁
3. 看 Actions 是否全绿：`https://github.com/<用户名>/<仓库>/actions`
   - 流水线里有一道**质量闸门**：`verify.py`（模型自测 + Python/JS 交叉校验 + DOM 冒烟）
     不过就不会部署。**看到红色 = 代码有问题，不是网络问题。**
4. 把链接贴到手机浏览器开一次，确认移动端排版正常

---

## 4. 以后怎么更新

```bash
python verify.py --browser            # 改完先本地自检
python run_v1.py && python build.py   # 若改了 template.html，必须重新构建
git add -A && git commit -m "..." && git push
```

CI 会自动重新生成数据、构建、再部署。

---

## 5. CI 做了什么（可讲给面试官）

`.github/workflows/pages.yml`：

```
checkout → Python 3.11 + Node 20 → pip install -r requirements.txt
        → python verify.py            ← 质量闸门，不过就不部署
        → python run_v1.py            ← 重新扫 600 组方案
        → python build.py             ← 注入数据，产出单文件 index.html
        → upload-pages-artifact → deploy-pages
```

顺带一提：`og:image` 在 CI 里会用 `SITE_URL` 生成**绝对地址**
（`https://<用户名>.github.io/<仓库>/og.png`），这样发到微信/群里有缩略图。
本地构建时它是相对路径 `og.png`，属正常现象。

---

## 6. 为什么项目里有**两个**部署脚本

| 脚本 | 用在哪 | 走什么通道 |
|---|---|---|
| `deploy.sh` | 你自己的电脑 | `git push`（HTTPS） |
| `deploy_api.py` | AI 沙箱 / 任何 `github.com` 被拦的网络 | GitHub Git Data API |

两者做的事一样（推内容 + 开 Pages），只是传输层不同。**平时用 `deploy.sh` 就够了**，
`deploy_api.py` 是沙箱环境下的替代通路，留着也无害。

---

## 7. 关于署名

已把署名写进本仓库的**本地** git 配置（只影响这个仓库）：

```
MENG LING BANG <320177544+menglingbang74-droid@users.noreply.github.com>
```

用的是 GitHub 的 noreply 邮箱，**不会暴露你的真实邮箱**。
已有的 3 个提交作者也已一并改成这个（尚未推送，重写无副作用）。

想换成别的名字/邮箱：

```bash
git config user.name "你想显示的名字"
git config user.email "你的邮箱"
```

同时把 `LICENSE` 第一行的署名一起改掉。
