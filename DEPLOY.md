# 上线操作清单

目标：把本地这个项目推到 GitHub，开启 GitHub Pages，拿到一个**能点开的链接**——
简历上唯一有价值的就是这个链接。

> **状态：✅ 已完成（2026-10-12）。**
> - 线上地址：<https://menglingbang74-droid.github.io/swss-optimizer/>
> - 仓库：<https://github.com/menglingbang74-droid/swss-optimizer>
> - 方式：路线 A（Git Data API）· commit `c8fcf7909b70` · CI run #1 的 build + deploy 全绿
> - 用过的 token 已提醒作废（见第 8 节）
>
> 本文档保留，用于**以后更新**或换机重来。

---

## 0. 仓库名（✅ 已完成）

`AI-` 已重命名为 **`swss-optimizer`**，内容已推送到该仓库。

账号下还剩两个空仓库：`-`（名字仍是坏的，**建议删掉**）、`campus-job-targeting`（另一个项目要用）。

**为什么要改**：仓库名会直接出现在简历链接里 ——

```
https://menglingbang74-droid.github.io/AI-/                ← 面试官会愣一下
https://menglingbang74-droid.github.io/swss-optimizer/     ← 一眼说明这是什么
```

---

## 1. 拿 token（两条路都需要，1 分钟）

1. 打开 <https://github.com/settings/tokens> → **Generate new token (classic)**
2. Note 填 `deploy`，Expiration 选 **7 天**（用完就过期，最安全）
3. **勾两个权限**：
   - ☑ `repo`（读写仓库内容）
   - ☑ `workflow`（**必需**——不勾的话，含 `.github/workflows/pages.yml` 的提交会被 GitHub 直接拒绝）
4. Generate → 复制那串 `ghp_...`

验证完成后到同一页面 **把这个 token 删掉**。

> **别走错页面**：GitHub 现在的默认入口是 `Fine-grained tokens`，那个要勾的是
> Repository access = `Only select repositories` → 选 `swss-optimizer`，
> 再把 **Contents / Workflows / Pages** 三项都设成 `Read and write`（Account permissions 一律不动）。
>
> 两条路都能用，但**推荐 classic**，原因很实际：classic 会在响应头里回传 `X-OAuth-Scopes`，
> `deploy_api.py` 因此能在推代码**之前**就发现 `workflow` 没勾；
> 细粒度 token 不回传该头，只能等推 blob 时被 403 打回来才发现。

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

它会：校验 token 与权限 →（空仓库则先激活）→ 上传 25 个文件 → 建提交 →
建/更新 `main` → 开启 Pages（source = GitHub Actions）→ 打印仓库与在线地址。

> 想先看它要动什么、不写入任何东西：加 `--dry-run`。

**踩过的坑（已修进脚本）**：零提交的空仓库上，`POST /git/blobs` 会返回
`409 Git Repository is empty.` —— 空仓库的对象库还没激活，整个 Git Data API 都用不了。
所以脚本现在会先用 **Contents API** 写一个文件（`README.md`）产生首个提交把仓库激活，
之后再走正常流程。因此远端历史是 2 个提交（`初始化仓库` + 真正的初始提交），属正常现象。

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

### ⚠️ 首次上线是用 API 推的，本机 `git push` 前要先对齐一次

首次上线走的是 Git Data API，它把全部内容压成了**一个**提交，
与你本机原来的 4 个提交是**两条互不相关的历史**。
因此本机第一次 `git push` 会被拒（non-fast-forward）。先做一次对齐：

```bash
git remote add origin https://github.com/menglingbang74-droid/swss-optimizer.git   # 若还没有 remote
git fetch origin
git reset --hard origin/main     # 本机对齐远端；内容一致，只是历史被归并
```

之后 `git push` 恢复正常。

> 想保住本机那 4 个提交就先 `git branch local-history-backup` 再 reset；
> 或者干脆继续用 `python deploy_api.py ...` 推——它每次把本地全部文件重建成一个 tree
> 挂到远端最新提交上，**不依赖两边历史一致**。
> （注意：这个沙箱里 `github.com` 不通，所以对齐动作必须在**你自己的电脑**上做。）

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

---

## 8. 实际执行记录与环境限制（2026-10-12 留档）

**做了什么**

| 步骤 | 结果 |
|---|---|
| 推送内容 | 25 个文件 / 433 KB → `main` @ `c8fcf7909b70` |
| CI | run #1 ·build ✅·deploy ✅ |
| 部署状态 | `deployments/{id}/statuses` → `state=success`，`environment_url=https://menglingbang74-droid.github.io/swss-optimizer/` |
| Pages 配置 | `GET /pages` → 200 · `build_type=workflow` · `public=true` |

**⚠️ 一条重要限制：AI 沙箱打不开链接**

出口代理放行 `api.github.com` / `codeload.github.com`，但**整个 `github.io` 域名被拦**：

```
menglingbang74-droid.github.io     DNS 能解析（185.199.111.153），TLS 握手被掐 → curl 000
electron.github.io   （对照组）    → 同样 000
cli.github.io        （对照组）    → 同样 000
```

对照组证明这是**域名级拦截**，不是站点本身的问题。第三方抓取通道（r.jina.ai / allorigins / corsproxy）也都不通。

**所以：线上页面是否真的能打开，必须由本机浏览器确认一次。**
上面那三条 API 证据是能拿到的最强间接证明，但**它不等于「打开看过」**。
第一次面试演示前，务必自己过一遍：

1. 桌面浏览器打开线上地址 → KPI 卡片正常显示
2. 拖两个滑杆、点一次「重新计算 Pareto」→ 不死锁、数值跟着变
3. 手机浏览器再开一次 → 排版正常（结果区在参数区上方）
4. 把链接粘到微信里发给自己 → 能出缩略图（验证 `og:image` 的绝对地址生效）

**其它已验证可用的 API 端点（供以后参考）**

| 用途 | 端点 | 备注 |
|---|---|---|
| 确认仓库存在 | `GET /repos/{o}/{r}` | |
| 读 Pages 配置 | `GET /repos/{o}/{r}/pages` | **必须带 token**，匿名请求会误报 404 |
| 确认部署成功 | `GET /repos/{o}/{r}/deployments` → `/statuses` | 从这个接口能拿到真实线上地址 |
| 看 CI 结论 | `GET /repos/{o}/{r}/actions/runs` | 带上 `/jobs` 可看每一步 |

**两个会骗人的「空返回」**

- `git ls-remote <url>` 在这个网络下会**静默失败并返回空 + exit 0**，
  看起来像「仓库存在但为空」。**判断仓库是否存在只能用 `GET /repos/{o}/{r}`。**
- `git push` 在此环境永远会失败（`CONNECT tunnel failed, response 502`），
  别在它上面浪费时间——直接用 `deploy_api.py`。

