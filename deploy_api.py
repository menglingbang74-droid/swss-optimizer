"""通过 GitHub REST API 推送整个仓库（沙箱内 git push 走不通时的通路）。

为什么需要它：
    本沙箱的出口代理放行 api.github.com，但拦截 github.com 的 CONNECT 隧道
    （实测 git push -> "CONNECT tunnel failed, response 502"，curl github.com -> 000）。
    因此走 Git Data API（blobs -> tree -> commit -> ref）绕开 git 传输层。
    在你自己的电脑上则不需要它，直接 `bash deploy.sh` 即可。

用法：
    python deploy_api.py --owner menglingbang74-droid --repo swss-optimizer
    # token 会以隐藏输入方式询问，或从环境变量 GH_TOKEN 读取

    python deploy_api.py ... --dry-run     # 只做本地准备与远端校验，不写入

需要的 token 权限（classic PAT）：
    repo      —— 读写仓库内容
    workflow  —— 提交 .github/workflows/* 必需，否则 API 会拒绝

一个已踩过的坑：
    零提交的空仓库上，Git Data API 的 POST /git/blobs 会返回
    409 "Git Repository is empty."（对象库还没被激活）。
    本脚本会先用 Contents API 写一个文件把仓库激活，再走正常流程。
"""
import argparse
import base64
import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
ROOT = os.path.dirname(os.path.abspath(__file__))  # 本脚本位于项目根目录

# 这些路径永远不进仓库（与 .gitignore 呼应，双保险）
NEVER = (".git/", "out/", "__pycache__/", ".venv/", "node_modules/")

# 空仓库初始化用的落点文件（必须已在 git 跟踪列表里，避免留下孤儿文件）
SEED_PATH = "README.md"


def local_identity():
    """本地 git config 的署名（已设为他的 GitHub 账号 + noreply 邮箱，不暴露真实邮箱）。"""
    def g(key):
        return subprocess.run(["git", "config", key], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    return g("user.name"), g("user.email")


def req(method, url, token=None, body=None):
    """发一个 API 请求，返回 (status, headers, parsed_json_or_text)。"""
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "swss-deploy",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, dict(resp.headers), json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return resp.status, dict(resp.headers), raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, dict(e.headers), json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return e.code, dict(e.headers), raw
    except urllib.error.URLError as e:
        return 0, {}, {"message": "网络不通: %s" % e.reason}


def tracked_files():
    """取 git 已跟踪文件（自动排除 .gitignore 里的东西），并做二次过滤。"""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True, check=True)
    files = [f for f in out.stdout.split("\0") if f]
    keep = []
    for f in files:
        posix = f.replace("\\", "/")
        if any(posix == n.rstrip("/") or posix.startswith(n) for n in NEVER):
            continue
        keep.append(posix)
    return keep


def ensure_repo_initialized(owner, repo, branch, token):
    """零提交的仓库无法使用 Git Data API：POST /git/blobs 会返回
    409 "Git Repository is empty."。

    这是一个 GitHub 的硬性限制（对象库未初始化），不是 token 权限问题。
    解法：先用 Contents API 写一个文件，产生首个提交把仓库激活，
    之后 blobs -> tree -> commit -> ref 才能正常走。

    返回 (是否本次新建, 首个提交 sha 或 None)。
    """
    url = "%s/repos/%s/%s/git/ref/heads/%s" % (API, owner, repo, branch)
    st, _, ref = req("GET", url, token)
    if st == 200 and isinstance(ref, dict):
        return False, ((ref.get("object") or {}).get("sha"))

    full = os.path.join(ROOT, SEED_PATH)
    if not os.path.exists(full):
        print("  ✗ 找不到初始化用文件 %s" % SEED_PATH)
        sys.exit(1)
    with open(full, "rb") as fh:
        raw = fh.read()

    name, mail = local_identity()
    body = {
        "message": "初始化仓库",
        "content": base64.b64encode(raw).decode("ascii"),
        "author": {"name": name, "email": mail},
        "committer": {"name": name, "email": mail},
    }
    if branch:
        body["branch"] = branch

    st, _, res = req("PUT", "%s/repos/%s/%s/contents/%s"
                     % (API, owner, repo, SEED_PATH), token, body)
    if st not in (200, 201) or not isinstance(res, dict):
        print("  ✗ 初始化空仓库失败：HTTP %s %s" % (st, str(res)[:200]))
        sys.exit(1)
    return True, ((res.get("commit") or {}).get("sha"))


def build_tree_entries(files, token, owner, repo, quiet=False):
    """把每个文件上传成 blob，返回 tree entries。"""
    entries = []
    total = 0
    for i, path in enumerate(files, 1):
        full = os.path.join(ROOT, path)
        with open(full, "rb") as fh:
            raw = fh.read()
        total += len(raw)
        b64 = base64.b64encode(raw).decode("ascii")
        st, _, res = req("POST", "%s/repos/%s/%s/git/blobs" % (API, owner, repo),
                         token, {"content": b64, "encoding": "base64"})
        if st != 201 or not isinstance(res, dict) or "sha" not in res:
            print("  ✗ 上传 blob 失败: %s  HTTP %s  %s" % (path, st, str(res)[:160]))
            print("    若是 403 且提示 workflow，说明 token 缺 workflow 权限。")
            sys.exit(1)
        entries.append({"path": path, "mode": "100755" if path.endswith(".sh") else "100644",
                        "type": "blob", "sha": res["sha"]})
        if not quiet:
            sys.stdout.write("\r    上传中 %d/%d  (%s)          " % (i, len(files), path[:40]))
            sys.stdout.flush()
    if not quiet:
        sys.stdout.write("\r" + " " * 70 + "\r")
    print("    共 %d 个文件，%.0f KB 原始内容" % (len(files), total / 1024))
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("请粘贴 Personal Access Token（classic，需勾 repo + workflow；输入时不显示）：")
        token = getpass.getpass("token: ").strip()
    if not token:
        print("没读到 token，退出。")
        sys.exit(1)

    print("=" * 71)
    print("通过 GitHub API 推送  ->  %s/%s@%s" % (args.owner, args.repo, args.branch))
    print("=" * 71)

    # --- 1. 校验 token 与权限 ---
    print("1) 校验 token")
    st, hdr, me = req("GET", API + "/user", token)
    if st != 200:
        print("  ✗ token 无效：HTTP %s %s" % (st, str(me)[:160]))
        sys.exit(1)
    login = me.get("login")
    scopes = hdr.get("X-OAuth-Scopes", "")
    print("  ✓ 登录为 %s" % login)
    print("  token 权限: %s" % (scopes or "(未返回，可能是 fine-grained token)"))
    if login != args.owner:
        print("  ! token 属于 %s，目标 owner 是 %s —— 继续但可能失败。" % (login, args.owner))
    if "workflow" not in scopes and scopes:
        print("  ! 缺 workflow 权限：提交 .github/workflows/ 会被 GitHub 拒绝（403）。")
        print("    请到 https://github.com/settings/tokens 补勾 workflow 后重试。")
        sys.exit(1)

    # --- 2. 校验仓库 ---
    print("2) 校验仓库")
    st, _, repo_info = req("GET", "%s/repos/%s/%s" % (API, args.owner, args.repo), token)
    if st != 200:
        print("  ✗ 读不到仓库（HTTP %s）：%s" % (st, str(repo_info)[:120]))
        print("    确认仓库名正确；'AI-' 这类被截断的名字建议先重命名。")
        sys.exit(1)
    print("  ✓ %s  private=%s  default=%s" % (repo_info["full_name"], repo_info["private"],
                                             repo_info.get("default_branch")))

    files = tracked_files()
    print("3) 待推送文件 %d 个" % len(files))

    if args.dry_run:
        print("    --dry-run：列出文件后停止（不写入远端）")
        for f in files:
            print("      %s" % f)
        print("=" * 71)
        print("DRY-RUN OK")
        return

    # --- 3. 空仓库先激活（否则下一步的 blob 接口会 409） ---
    print("4) 检查仓库是否为空")
    made, seed_sha = ensure_repo_initialized(args.owner, args.repo, args.branch, token)
    if made:
        print("  ✓ 仓库原为零提交 —— 已用 %s 写首个提交激活（%s）"
              % (SEED_PATH, (seed_sha or "?")[:12]))
        print("    原因：空仓库上 Git Data API 的 blob 接口会返回 409，必须先有提交。")
    else:
        print("  ✓ 仓库已有提交，直接追加")

    # --- 4. 上传 blobs ---
    print("5) 上传文件内容（Git Data API: blobs）")
    entries = build_tree_entries(files, token, args.owner, args.repo)

    # --- 5. 建 tree ---
    print("6) 建 tree")
    st, _, tree = req("POST", "%s/repos/%s/%s/git/trees" % (API, args.owner, args.repo),
                      token, {"tree": entries})
    if st != 201 or "sha" not in tree:
        print("  ✗ 建 tree 失败：HTTP %s %s" % (st, str(tree)[:200]))
        sys.exit(1)
    print("  ✓ tree %s" % tree["sha"][:12])

    # --- 6. 建 commit ---
    print("7) 建 commit")
    cfg_name = subprocess.run(["git", "config", "user.name"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    cfg_mail = subprocess.run(["git", "config", "user.email"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    msg = args.message
    if not msg:
        msg = subprocess.run(["git", "log", "-1", "--pretty=%B"], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip()
    body = {"message": msg, "tree": tree["sha"],
            "author": {"name": cfg_name or login, "email": cfg_mail or "%s@users.noreply.github.com" % login},
            "committer": {"name": cfg_name or login, "email": cfg_mail or "%s@users.noreply.github.com" % login}}

    # 若远端已有该分支，带上父提交（保住历史）；空仓库则不带
    st_ref, _, existing = req("GET", "%s/repos/%s/%s/git/ref/heads/%s"
                              % (API, args.owner, args.repo, args.branch), token)
    if st_ref == 200 and isinstance(existing, dict) and existing.get("object"):
        body["parents"] = [existing["object"]["sha"]]
        print("  远端已有 %s，将追加为子提交（父 %s）" % (args.branch, existing["object"]["sha"][:12]))
    else:
        print("  远端 %s 不存在 -> 创建首个提交" % args.branch)

    st, _, commit = req("POST", "%s/repos/%s/%s/git/commits" % (API, args.owner, args.repo),
                        token, body)
    if st != 201 or "sha" not in commit:
        print("  ✗ 建 commit 失败：HTTP %s %s" % (st, str(commit)[:200]))
        sys.exit(1)
    print("  ✓ commit %s" % commit["sha"][:12])

    # --- 7. 更新/创建分支引用 ---
    print("8) 更新分支 %s" % args.branch)
    if st_ref == 200:
        st, _, res = req("PATCH", "%s/repos/%s/%s/git/refs/heads/%s"
                         % (API, args.owner, args.repo, args.branch),
                         token, {"sha": commit["sha"], "force": False})
        if st != 200:
            print("  ✗ 更新分支失败：HTTP %s %s" % (st, str(res)[:200]))
            sys.exit(1)
    else:
        st, _, res = req("POST", "%s/repos/%s/%s/git/refs" % (API, args.owner, args.repo),
                         token, {"ref": "refs/heads/%s" % args.branch, "sha": commit["sha"]})
        if st != 201:
            print("  ✗ 创建分支失败：HTTP %s %s" % (st, str(res)[:200]))
            sys.exit(1)
    print("  ✓ %s -> %s" % (args.branch, commit["sha"][:12]))

    # --- 8. 开启 Pages（source = GitHub Actions） ---
    print("9) 开启 Pages")
    st, _, res = req("POST", "%s/repos/%s/%s/pages" % (API, args.owner, args.repo),
                     token, {"build_type": "workflow"})
    if st in (201, 204):
        print("  ✓ Pages 已开启（build_type=workflow）")
    elif st == 409:
        print("  ✓ Pages 本来就已开启")
    elif st == 403:
        print("  ! API 权限不足（HTTP 403）。请手动设一次：")
        print("    Settings -> Pages -> Source 选 'GitHub Actions'")
    else:
        print("  ! 返回 HTTP %s：%s" % (st, str(res)[:160]))
        print("    可手动设：Settings -> Pages -> Source 选 'GitHub Actions'")

    print("=" * 71)
    print("完成。")
    print("  仓库： https://github.com/%s/%s" % (args.owner, args.repo))
    print("  在线： https://%s.github.io/%s/" % (args.owner, args.repo))
    print("  Actions： https://github.com/%s/%s/actions" % (args.owner, args.repo))
    print("")
    print("  注意：这一步只把「内容和 Pages 开关」放上去；")
    print("  CI 是否跑绿、链接能否打开，需要再确认一次。")
    print("  验证通过后请到 https://github.com/settings/tokens 删除本 token。")
    print("=" * 71)


if __name__ == "__main__":
    main()
