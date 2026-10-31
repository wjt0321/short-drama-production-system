#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""未提交提醒闸：只检查当前短剧体系工作区。"""
import argparse
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)


def git_status(root):
    if not os.path.isdir(os.path.join(root, ".git")):
        return None, None
    try:
        p = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
        if p.returncode != 0:
            return None, None
        return [line for line in p.stdout.splitlines() if line.strip()], None
    except Exception as exc:  # noqa: BLE001
        return None, "{}: {}".format(type(exc).__name__, str(exc)[:40])


def main():
    ap = argparse.ArgumentParser(description="未提交改动提醒")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="有未提交改动就退出码 1（默认只提醒）")
    args = ap.parse_args()
    lines, err = git_status(SYSTEM_ROOT)
    if err:
        result = [("体系", None, "git 调用失败: " + err)]
    elif lines is None:
        result = [("体系", None, "未启用版本控制")]
    else:
        result = [("体系", len(lines), lines)]
    dirty = sum(n or 0 for _tag, n, _detail in result)

    if args.json:
        print(json.dumps({"repos": [{"name": tag, "dirty": n,
                                      "files": (detail or [])[:10]}
                                     for tag, n, detail in result],
                          "total_dirty": dirty}, ensure_ascii=False, indent=2))
    else:
        print("=" * 70)
        print("未提交改动提醒")
        print("=" * 70)
        for tag, n, detail in result:
            if n is None:
                print("  ?  {:<8s} {}".format(tag, detail))
            elif n == 0:
                print("  ✓ {:<8s} 工作区干净".format(tag))
            else:
                print("  ⚠ {:<8s} {} 个文件改了没提交".format(tag, n))
                for line in (detail or [])[:6]:
                    print("       " + line[:70])
        print("-" * 70)
        print("✓ 体系工作区检查完成" if not dirty else
              "提醒：改动没提交就没有回滚点。")
    return 1 if args.strict and dirty else 0


if __name__ == "__main__":
    raise SystemExit(main())
