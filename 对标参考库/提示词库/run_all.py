#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键出全套制作材料（编排器）。

**为什么需要**
前面拆成了 4 个脚本（流水线 + G3 + G4 + G6），每次要手敲四条命令。
但目标写的是「自动完成这一系列的动作，人类只负责审核」——
**手敲四条命令不算自动**。

本脚本是薄编排层：跑一次流水线，依次调用三个导出器，产出四份材料。
不复制任何业务逻辑，各脚本仍可单独使用。

**用法**
    python run_all.py "敦煌飞天 复仇" --style 工笔 --mood 肃杀 --duration 60
    python run_all.py "题材A" "题材B" --out ./项目A --dry-run
    python run_all.py --batch topics.txt --out ./批量

**产出**
    制作包.md / 制作包.json      —— 人看（含执行摘要、审核签核）
    G3分镜表.md                  —— 分镜用（24 字段）
    G4生成段.md                  —— 出图到视频的执行记录
    G6剪辑装配单.md              —— 剪辑用（稳定 ID + 逐帧时码）

**设计原则**
  · 零 import 体系模块，纯调用同目录脚本
  · 默认 dry-run？——不。生成材料是低风险本地写盘，**默认执行**，
    但支持 --dry-run 预览文件名
  · 任一步失败即停，不吞错误
"""
import argparse
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(HERE, "shortfilm_pipeline.py")
EXPORTERS = [
    ("G3分镜表", "export_g3_storyboard.py"),
    ("G4生成段", "export_g4_generation.py"),
    ("G6剪辑装配单", "export_g6_assembly.py"),
]


def run(cmd, dry=False):
    if dry:
        return 0, " ".join(os.path.basename(c) for c in cmd[:2])
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print("  ✗ 失败: {}".format(os.path.basename(cmd[1])))
        print((p.stderr or p.stdout or "")[:500])
        return p.returncode, None
    return 0, (p.stdout or p.stderr or "").strip().split("\n")[-1]


def safe(name):
    for c in '\\/:*?"<>|':
        name = name.replace(c, "_")
    return name[:24]


def one_topic(topic, style, mood, duration, outdir, dry=False, route='drama'):
    tag = safe(topic)
    route_args = ['--route', route]
    os.makedirs(outdir, exist_ok=True)
    print("\n【{}】".format(topic))

    # 1. 流水线（JSON，供后续导出器消费）
    js = os.path.join(outdir, "制作包_{}.json".format(tag))
    rc, msg = run([sys.executable, PIPE, topic, "--style", style,
                   "--duration", str(duration), "--format", "json",
                   "--out", outdir] + (["--mood", mood] if mood else []) + route_args, dry)
    if rc:
        return rc
    print("  1/5 制作包.json   {}".format(msg or ""))

    # 2. 制作包 md（人看）
    rc, msg = run([sys.executable, PIPE, topic, "--style", style,
                   "--duration", str(duration), "--out", outdir]
                  + (["--mood", mood] if mood else []) + route_args, dry)
    if rc:
        return rc
    print("  2/5 制作包.md     {}".format(msg or ""))

    # 3~5. 三张体系表
    for i, (label, script) in enumerate(EXPORTERS, 3):
        out = os.path.join(outdir, "{}_{}.md".format(label, tag))
        rc, msg = run([sys.executable, os.path.join(HERE, script), js, "--out", out], dry)
        if rc:
            return rc
        print("  {}/5 {:<14s} {}".format(i, label, msg or ""))
    return 0


def main():
    ap = argparse.ArgumentParser(description="一键出全套制作材料")
    ap.add_argument("topics", nargs="*", help="题材")
    ap.add_argument("--batch", help="一行一个题材的文件")
    ap.add_argument("--style", default="写实")
    ap.add_argument("--mood", default=None)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--out", default="./制作材料", help="输出目录")
    ap.add_argument('--route', default='custom', help='Free-form project type; not a fixed route restriction')
    ap.add_argument("--dry-run", action="store_true", help="只显示将要做什么")
    args = ap.parse_args()

    topics = list(args.topics)
    if args.batch:
        for line in open(args.batch, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                topics.append(line)
    if not topics:
        ap.error("请给题材（位置参数 或 --batch）")

    print("=" * 62)
    print("一键出材料：{} 个题材｜风格 {}｜时长 {}s".format(
        len(topics), args.style, args.duration))
    print("输出目录: {}".format(os.path.abspath(args.out)))
    print("=" * 62)

    if len(topics) == 1:
        rc = one_topic(topics[0], args.style, args.mood, args.duration,
                       args.out, args.dry_run, args.route)
    else:
        rc = 0
        for t in topics:
            d = os.path.join(args.out, safe(t))
            rc |= one_topic(t, args.style, args.mood, args.duration, d, args.dry_run, args.route)

    if rc:
        print("\n有步骤失败。")
        return rc
    print("\n" + "=" * 62)
    print("草案材料导出完成。全权委托时Agent自主定稿制作；以下签核仅供用户要求人工审核时选用。")
    if len(topics) == 1:
        # 必须按本次题材精算路径，不能 glob 取 mds[0]：
        # 输出目录里攒了多个题材时，mds[0] 是历史遗留那个，
        # 会把"下一步"指到别的题材的包装上，让人签错件。
        pack = os.path.join(os.path.abspath(args.out),
                            "制作包_{}.md".format(safe(topics[0])))
        if not os.path.isfile(pack):
            pack = "<制作包.md>"
    else:
        pack = "<各子目录>/制作包_*.md"
    print("  1. 先看每关该审什么（别凭感觉点头）：")
    print("       python review_gate.py \"{}\" --checklist".format(pack))
    print("  2. 看完清单逐条签：")
    print("       python review_gate.py \"{}\" --sign ① --verdict 通过".format(pack))
    print("  3. 仅阶段审核模式：5关签核后进入G3：")
    print("       python review_gate.py \"{}\" --gate G3".format(pack))
    print("  4. Agent按需求定稿，依次出图、视频、声音、剪辑；检查实际结果并修具体问题，无需production.json")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
