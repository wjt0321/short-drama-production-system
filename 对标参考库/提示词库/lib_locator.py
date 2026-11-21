#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可选外部素材库定位器。

短剧体系本身不依赖任何外部参考库。只有维护者明确设置 ``AI_SEEK_ROOT``
时，维护脚本才会访问独立的 seek 数据项目；不再根据体系目录或相邻目录
猜测素材库位置，避免外部数据悄悄进入生产流程。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_LIB_SUB = ("05_工作流与Skills", "liblib提示词库")
_HARVEST_SUB = ("05_工作流与Skills", "harvest")


def _first_existing(cands, marker):
    for c in cands:
        if not c:
            continue
        c = os.path.abspath(c)
        if os.path.isfile(os.path.join(c, marker)):
            return c
    return None


def seek_root():
    """返回显式配置的外部库根目录；未配置时返回 None。"""
    env = (os.environ.get("AI_SEEK_ROOT") or "").strip()
    if env and os.path.isdir(os.path.join(env, *_LIB_SUB)):
        return os.path.abspath(env)
    return None


def lib_root():
    """返回外部提示词库目录；未显式配置或标记文件不存在时返回 None。"""
    raw = (os.environ.get("AI_SEEK_RAWLIB") or "").strip()
    root = seek_root()
    return _first_existing([
        raw,
        os.path.join(root, *_LIB_SUB) if root else None,
    ], "prompts.jsonl")


def harvest_root():
    """返回外部采集脚本目录；未显式配置或标记文件不存在时返回 None。"""
    harvest = (os.environ.get("AI_SEEK_HARVEST") or "").strip()
    root = seek_root()
    return _first_existing([
        harvest,
        os.path.join(root, *_HARVEST_SUB) if root else None,
    ], "selfcheck_portable.py")


def prompts_path():
    root = lib_root()
    return os.path.join(root, "prompts.jsonl") if root else None


def covers_dir():
    root = lib_root()
    return os.path.join(root, "封面") if root else None


def require(what, path):
    if not path:
        print("找不到外部素材库的{}；体系生产不依赖该库。".format(what),
              file=sys.stderr)
        print("如需运行维护脚本，请显式设置 AI_SEEK_ROOT。", file=sys.stderr)
        sys.exit(1)
    return path


def self_test():
    print("PROJECT_ROOT   =", PROJECT_ROOT)
    print("seek_root      =", seek_root())
    print("lib_root       =", lib_root())
    print("harvest_root   =", harvest_root())
    configured = bool(os.environ.get("AI_SEEK_ROOT") or
                      os.environ.get("AI_SEEK_RAWLIB") or
                      os.environ.get("AI_SEEK_HARVEST"))
    ok = not configured or (bool(lib_root()) and bool(harvest_root()))
    print("→", "外部库未配置，体系独立运行" if not configured and ok
          else ("全部就位" if ok else "显式配置不完整"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test())
