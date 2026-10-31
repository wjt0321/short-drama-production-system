#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""select_reference —— 可选外部 seek 数据维护入口（薄包装，纯标准库）。

边界：外部参考库 是体系外的独立采集项目，不是短剧生产默认输入。只有维护者显式设置 AI_SEEK_ROOT 后，才使用本工具检查或查询它：
底层分别复用两个内部实现脚本（不复制算法）：

  · style  → tools/find_style.py               （本地成片风格候选：视频/代表帧/光照/色调）
  · prompt → 外部参考库/提示词库/auto_select_cards.py （liblib 提示词选卡，item 级）

  · check  → 用 lib_locator 体检生产侧可消费的 seek 数据：seek_root / prompts.jsonl /
             封面目录 / 成片清单，并输出记录数、item 提示词数、本地封面数、成片清单数。
             不检查采集脚本、登录态或采集日志；它们属于独立 seek 项目。只读本地，不联网。

**资源纪律**：输出里的来源 URL 仅作追溯，不等于已取得资源；本地返回的文件
（封面图 / 成片视频 / 代表帧）才是已取得的资源，Agent 必须实际查看本地文件。

退出码：0 正常 / 1 资源缺失或底层脚本失败 / 2 用法错误。
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.abspath(os.path.join(HERE, ".."))

FIND_STYLE = os.path.join(HERE, "find_style.py")
AUTO_SELECT = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库", "auto_select_cards.py")
LIB_LOCATOR = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库", "lib_locator.py")

EPILOG = """\
资源纪律：输出中的来源 URL 仅作追溯，不等于已取得资源；
本地返回的封面/视频/代表帧才是已取得的资源，选风格时必须实际查看本地文件。
外部参考库 是外部可选数据源，不是短剧生产默认输入；做片入口见 从这里开始.md / AGENTS.md。
"""


def _run(script, argv, no_hit_markers=()):
    """原样转交内部实现脚本：透传 stdout/stderr；底层失败透传其退出码；
    底层成功但输出含 no_hit_markers（如无命中提示）时返回 1，让"没找到"可被脚本感知。"""
    if not os.path.isfile(script):
        print("✗ 内部实现脚本缺失：{}".format(script), file=sys.stderr)
        return 1
    p = subprocess.run([sys.executable, script] + argv,
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.stdout:
        sys.stdout.write(p.stdout)
    if p.stderr:
        sys.stderr.write(p.stderr)
    if p.returncode != 0:
        return p.returncode
    for m in no_hit_markers:
        if m in p.stderr:
            return 1
    return 0


def _load_lib_locator():
    spec = importlib.util.spec_from_file_location("lib_locator", LIB_LOCATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_find_style():
    spec = importlib.util.spec_from_file_location("find_style", FIND_STYLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmd_check(_args):
    """体检 seek 数据源（只读本地，不联网）。0 全过 / 1 有缺失。"""
    if not os.path.isfile(LIB_LOCATOR):
        print("✗ 定位器缺失：{}".format(LIB_LOCATOR), file=sys.stderr)
        return 1
    loc = _load_lib_locator()
    seek_root = loc.seek_root()
    lib_root = loc.lib_root()
    prompts = loc.prompts_path()
    covers = loc.covers_dir()

    ok = True
    if seek_root:
        print("✓ seek_root   ：{}".format(seek_root))
    elif lib_root:
        print("· seek_root   ：独立挂载（生产数据已由 AI_SEEK_RAWLIB 定位）")

    n_rec = n_items = None
    if not (lib_root and prompts and os.path.isfile(prompts)):
        print("✗ 未定位 prompts.jsonl（可设 AI_SEEK_RAWLIB）", file=sys.stderr)
        ok = False
    else:
        print("✓ lib_root    ：{}".format(lib_root))
        n_rec = 0
        n_items = 0
        try:
            with open(prompts, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    n_rec += 1
                    n_items += len(rec.get("items") or [])
        except (OSError, ValueError) as exc:
            print("✗ prompts.jsonl 解析失败：{}".format(exc), file=sys.stderr)
            return 1
        if n_rec == 0:
            print("✗ prompts.jsonl 无记录", file=sys.stderr)
            ok = False

    n_cov = None
    if not (covers and os.path.isdir(covers)):
        print("✗ 未定位封面目录", file=sys.stderr)
        ok = False
    else:
        n_cov = len([f for f in os.listdir(covers)
                     if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))])

    n_works = 0
    # 只有显式配置外部库根目录时才检查成片清单；RAWLIB 夹具可独立验证提示词数据。
    if os.environ.get("AI_SEEK_ROOT") and os.path.isfile(FIND_STYLE):
        try:
            n_works = len(_load_find_style().load_all_works())
        except Exception as exc:  # noqa: BLE001
            print("✗ 成片清单读取失败：{}".format(exc), file=sys.stderr)
            ok = False

    print("-" * 40)
    print("记录数 {} ｜ item 提示词数 {} ｜ 本地封面数 {} ｜ 成片清单数 {}".format(
        n_rec if n_rec is not None else "—",
        n_items if n_items is not None else "—",
        n_cov if n_cov is not None else "—",
        n_works))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="select_reference",
        description="可选外部 seek 数据维护入口（本地、零网络；URL 仅追溯）",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command")

    sp = sub.add_parser("style", help="本地成片风格候选（复用 find_style.py）",
                        epilog=EPILOG)
    sp.add_argument("query", help="题材/风格描述")
    sp.add_argument("--top", type=int, default=4)
    sp.add_argument("--format", choices=("md", "json"), default="md")

    pp = sub.add_parser("prompt", help="提示词选卡（复用 auto_select_cards.py）",
                        epilog=EPILOG)
    pp.add_argument("queries", nargs="+", help="题材描述或关键词（可多个）")
    pp.add_argument("--top", type=int, default=8)
    pp.add_argument("--format", choices=("md", "json"), default="json",
                    help="默认 json，保留完整提示词、负向词、参数和本地资源路径")
    pp.add_argument("--type", choices=("LORA", "图片模板", "Checkpoint"),
                    help="限定资源类型")
    pp.add_argument("--topic-type", help="按题材维度限定（人物/场景/光影/镜头/调色/氛围/构图/动作/国风元素）")
    pp.add_argument("--tech", help="按短片制作技巧限定（镜头语言/光影/调色/构图/场景氛围/剪辑节奏）")

    sub.add_parser("check", help="体检显式配置的外部 seek 数据（只读本地）")

    args = ap.parse_args(argv)
    if not args.command:
        ap.print_help()
        return 2

    if args.command == "check":
        return cmd_check(args)

    if args.command == "style":
        argv2 = [args.query, "--top", str(args.top), "--format", args.format]
        return _run(FIND_STYLE, argv2)

    # prompt
    argv2 = list(args.queries) + ["--top", str(args.top), "--format", args.format]
    if args.type:
        argv2 += ["--type", args.type]
    if args.topic_type:
        argv2 += ["--topic-type", args.topic_type]
    if args.tech:
        argv2 += ["--tech", args.tech]
    return _run(AUTO_SELECT, argv2, no_hit_markers=("没命中任何卡片",))


if __name__ == "__main__":
    sys.exit(main())
