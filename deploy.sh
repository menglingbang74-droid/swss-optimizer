#!/usr/bin/env bash
# =============================================================================
#  一键上线脚本（推送 + 开启 GitHub Pages + 等待部署完成）
#
#  用法（在 Git Bash 里，于项目根目录执行）：
#      bash deploy.sh
#
#  它会依次做：
#    1. 校验 token 与仓库（确认用户名/仓库名对得上）
#    2. 配置 git remote（token 不写入 .git/config）
#    3. push 到 main
#    4. 调 GitHub API 把 Pages 源设为 "GitHub Actions"
#    5. 轮询 Actions 运行结果，成功后打印线上地址
#
#  从未把 token 写进任何文件、任何 URL、任何 shell 历史。
#  跑完请到 https://github.com/settings/tokens 确认这个 token，用完即可删除。
# =============================================================================
set -uo pipefail

DEFAULT_OWNER="menglingbang74-droid"
DEFAULT_REPO="swss-optimizer"
BRANCH="main"

say()  { printf '%s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
hr()   { printf '%s\n' "-----------------------------------------------------------------------"; }

command -v git  >/dev/null 2>&1 || { bad "找不到 git"; exit 1; }
command -v curl >/dev/null 2>&1 || { bad "找不到 curl"; exit 1; }

hr
say "SWSS Optimizer · 一键上线"
hr

# ---------- 1. 收集信息 ----------
read -r -p "GitHub 用户名 [${DEFAULT_OWNER}]: " OWNER
OWNER="${OWNER:-$DEFAULT_OWNER}"
read -r -p "仓库名       [${DEFAULT_REPO}]: " REPO
REPO="${REPO:-$DEFAULT_REPO}"
say ""
say "将推送到： https://github.com/${OWNER}/${REPO}"
warn "仓库名会直接出现在简历链接里，别用 AI- 这类截断名。"
say ""
read -r -p "确认继续？(y/N) " yes
case "$yes" in [yY]*) ;; *) say "已取消。"; exit 0 ;; esac

say ""
say "请粘贴 Personal Access Token（classic）："
say "  必须勾 repo 和 workflow 两个权限 —— 少了 workflow，"
say "  含 .github/workflows/ 的提交会被 GitHub 拒绝。"
say "  到 https://github.com/settings/tokens 生成，用完记得删掉。"
say "（输入时不显示）"
read -r -s TOKEN
say ""
[ -n "${TOKEN:-}" ] || { bad "没读到 token，退出。"; exit 1; }
if [ "$TOKEN" = "USE_API" ]; then
  warn "检测到占位输入。若你的网络访问不了 github.com，请改用："
  say  "     python deploy_api.py --owner ${OWNER} --repo ${REPO}"
  exit 0
fi

# ---------- 2. 校验 token 与仓库 ----------
hr
say "1) 校验 token 与仓库"
API="https://api.github.com"
me=$(curl -s -H "Authorization: Bearer ${TOKEN}" -H "Accept: application/vnd.github+json" \
        "${API}/user" | python -c "import sys,json;d=json.load(sys.stdin);print(d.get('login') or d.get('message',''))" 2>/dev/null)
if [ -z "$me" ]; then
  bad "token 无效或网络不通（API 没返回登录名）。"
  exit 1
fi
ok "token 有效，登录为 ${me}"
if [ "$me" != "$OWNER" ]; then
  warn "token 属于 ${me}，但你要推到 ${OWNER} —— 如果不一致，push 会失败。"
fi

repo_json=$(curl -s -H "Authorization: Bearer ${TOKEN}" -H "Accept: application/vnd.github+json" \
                "${API}/repos/${OWNER}/${REPO}")
repo_check=$(printf '%s' "$repo_json" | python -c "
import sys,json
try: d=json.load(sys.stdin)
except Exception: print('PARSE'); raise SystemExit
if 'full_name' in d: print('OK ' + d['full_name'] + ' private=' + str(d.get('private')))
else: print('ERR ' + str(d.get('message')))
" 2>/dev/null)
case "$repo_check" in
  OK*) ok "仓库存在：${repo_check#OK }" ;;
  *)   bad "读不到仓库：${repo_check#ERR }"; say "     确认仓库名没写错，或先到 GitHub 建一个空仓库。"; exit 1 ;;
esac

# ---------- 3. 配 remote + push ----------
hr
say "2) 推送代码"
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  bad "当前目录不是 git 仓库。请在项目根目录执行本脚本。"; exit 1
fi
git remote remove origin >/dev/null 2>&1 || true
git remote add origin "https://github.com/${OWNER}/${REPO}.git"
ok "remote origin -> ${OWNER}/${REPO}"

# token 只经由临时 askpass 传入，不落盘、不进 URL、不进进程参数列表
ASKPASS="$(mktemp)"
trap 'rm -f "$ASKPASS"; unset TOKEN' EXIT
cat > "$ASKPASS" <<'EOS'
#!/bin/sh
printf '%s\n' "$GH_DEPLOY_TOKEN"
EOS
chmod +x "$ASKPASS"
export GH_DEPLOY_TOKEN="$TOKEN"
export GIT_ASKPASS="$ASKPASS"
export GIT_TERMINAL_PROMPT=0

if git push -u origin "$BRANCH" 2>&1 | sed 's/^/     /'; then
  ok "已推送到 ${BRANCH}"
else
  bad "push 失败。常见原因：token 没勾 repo 权限 / 仓库名不对 / token 属于另一个账号。"
  exit 1
fi

# ---------- 4. 开启 Pages（source = GitHub Actions） ----------
hr
say "3) 开启 GitHub Pages"
code=$(curl -s -o /tmp/_pages_resp -w '%{http_code}' -X POST \
  -H "Authorization: Bearer ${TOKEN}" -H "Accept: application/vnd.github+json" \
  "${API}/repos/${OWNER}/${REPO}/pages" \
  -d '{"build_type":"workflow"}')
case "$code" in
  201|204) ok "Pages 已开启（build_type=workflow）" ;;
  409)     ok "Pages 本来就已开启，跳过" ;;
  403)     warn "API 权限不够（token 可能只勾了 public_repo）。"
           say  "     请手动设一次：仓库 Settings -> Pages -> Source 选 'GitHub Actions'，只需点一次。" ;;
  *)       warn "开启 Pages 返回 HTTP ${code}：$(head -c 200 /tmp/_pages_resp)"
           say  "     请手动设一次：仓库 Settings -> Pages -> Source 选 'GitHub Actions'。" ;;
esac
rm -f /tmp/_pages_resp

# ---------- 5. 等部署 ----------
hr
say "4) 等待 Actions 部署（最多 5 分钟）"
sleep 8
RUN_ID=""
for i in $(seq 1 30); do
  RUN_ID=$(curl -s -H "Authorization: Bearer ${TOKEN}" -H "Accept: application/vnd.github+json" \
    "${API}/repos/${OWNER}/${REPO}/actions/runs?per_page=1&branch=${BRANCH}" \
    | python -c "
import sys,json
try:
    d=json.load(sys.stdin)
    runs=d.get('workflow_runs') or []
    print(runs[0]['id'] if runs else '')
except Exception: print('')
" 2>/dev/null)
  [ -n "$RUN_ID" ] && break
  printf '    等待 workflow 出现… (%d/30)\r' "$i"
  sleep 6
done

if [ -z "$RUN_ID" ]; then
  warn "没等到 workflow。可能 Actions 被禁用，或 push 没触发。"
  say  "  到 https://github.com/${OWNER}/${REPO}/actions 看一眼。"
else
  ok "找到运行 #${RUN_ID}"
  for i in $(seq 1 40); do
    st=$(curl -s -H "Authorization: Bearer ${TOKEN}" -H "Accept: application/vnd.github+json" \
      "${API}/repos/${OWNER}/${REPO}/actions/runs/${RUN_ID}" \
      | python -c "
import sys,json
try:
    d=json.load(sys.stdin); print(d.get('status',''), d.get('conclusion') or '')
except Exception: print('unknown ')
" 2>/dev/null)
    printf '    %s\r' "$st"
    case "$st" in
      completed\ success*)  say ""; ok "部署成功"; break ;;
      completed\ *)         say ""; bad "部署失败：${st}"; 
        say "  日志： https://github.com/${OWNER}/${REPO}/actions/runs/${RUN_ID}"; break ;;
    esac
    sleep 7
  done
fi

# ---------- 6. 收尾 ----------
hr
say "线上地址"
say "   https://${OWNER}.github.io/${REPO}/"
say ""
say "  （Pages 首次生效可能要多等 1-2 分钟。若 404，先刷新再等一会。）"
say ""
say "收尾提醒"
say "  • 验证没问题后，到 https://github.com/settings/tokens 删掉刚才这个 token。"
say "  • 本地 remote 已配好，以后改完代码只需： git push"
unset TOKEN GH_DEPLOY_TOKEN
hr
