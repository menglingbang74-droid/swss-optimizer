"""一键跑完整验证链（顺序不可换：xcheck.py 必须先跑，才有 xcheck.json）。

用法：
    python verify.py            # 跑前四层（不需要浏览器）
    python verify.py --browser  # 额外跑 Chromium 端到端（需先装 playwright）

顺序有依赖：
    test_v1.py            模型自测
    xcheck.py   -> out/xcheck.json    Python 侧基准值
    xcheck.js                        读上面那个文件，逐字段比对 JS 实现
    smoke.js                         DOM 桩：语法 + 运行时 + 交互回归
    browser_check.py                 真实浏览器（可选）
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(label, cmd, cwd=ROOT, must=True):
    print('\n' + '=' * 72)
    print('>>> ' + label)
    print('    ' + ' '.join(cmd))
    print('=' * 72)
    p = subprocess.run(cmd, cwd=cwd)
    ok = p.returncode == 0
    if not ok and must:
        print('\n!! 上一步失败，后续依赖它，已中止。')
        sys.exit(1)
    return ok


def main():
    with_browser = '--browser' in sys.argv
    run('1/5 Python 模型自测', [PY, 'test_v1.py'])
    run('2/5 Python 侧基准值', [PY, 'xcheck.py'])
    run('3/5 Python <-> JS 交叉校验', ['node', 'xcheck.js'])
    run('4/5 DOM 桩冒烟', ['node', 'smoke.js'])
    if with_browser:
        run('5/5 真实浏览器端到端', [PY, 'browser_check.py'])
    else:
        print('\n(跳过 5/5 浏览器测试；加 --browser 开启)')
    print('\n' + '=' * 72)
    print('VERIFY: ALL PASS' + ('' if with_browser else '（未含浏览器层）'))
    print('=' * 72)


if __name__ == '__main__':
    main()
