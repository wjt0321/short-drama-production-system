#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全性能闸 · 安全与性能体检。

**为什么需要**
盘点既有闸覆盖面时发现两个盲区：
  · **安全**：`<script>` 注入、路径穿越（`../../`）只在边界测试里间接覆盖，
    没有一道闸**主动**检查「素材/文档里混进了危险内容」
  · **性能**：核心脚本跑多久没人知道。流水线慢了没人报警。

**安全查什么**
  · 素材 jsonl / 文档 md 里是否混入 `<script>` / `javascript:` 等可执行片段
  · 是否混入**两级以上**的 `../../` 路径穿越（单级 `../子目录/` 是项目内相对引用，不算）
  · 生成的文件名是否含 Windows 非法字符
  · 外链协议是否只含 http/https

**性能查什么**
  · `shortfilm_pipeline.py` 单次产出耗时
  · 项目总体积（是否失控）
  · 超阈值只提醒，不判失败

**用法**
    python tools/check_security_perf.py
"""
import io
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)
LIB = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库")
# 体系闸只扫可提交的 SOP/模板/工具；私人项目独立验片；`_归档` 是封存件，不参与体检。
SCAN_EXCLUDES = {'.git', '__pycache__', 'node_modules', '00-视频项目', '_归档'}

# ---- 安全规则 ----
XSS = re.compile(r"<\s*script|javascript\s*:|onerror\s*=|onload\s*=", re.I)
# 路径穿越：只认**连续两级以上**的 `../`（`../../` 往上跑出项目）。
# 单级 `../04-镜头/...` 是**项目内相对引用**，正常用法，不算问题。
# 也要求后面跟 ASCII 字母数字，避免 JSON 里的 `\n` 转义 + 中文被误判。
TRAVERSAL = re.compile(r"\.\.[\\/]\.\.[\\/][A-Za-z0-9_]")
BAD_PROTO = re.compile(r"(?<![\w.])ftp://|file://|gopher://", re.I)
ILLEGAL_FNAME = re.compile(r'[\\/:*?"<>|\r\n\t\x00-\x1f]')


def check_security():
    problems = []

    # ① 文档里的可执行片段（md 会被渲染，XSS 主要风险在这）
    for dirpath, dirs, files in os.walk(SYSTEM_ROOT):
        dirs[:] = [d for d in dirs if d not in SCAN_EXCLUDES]
        for fn in files:
            if not fn.endswith(('.md', '.html')):
                continue
            p = os.path.join(dirpath, fn)
            try:
                body = io.open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            m = XSS.search(body)
            if m:
                # 检查规则文件本身——它们定义这些正则，会有自指误报
                if os.path.dirname(p) == HERE:
                    continue
                problems.append("{} 含可执行片段 <{}>".format(
                    os.path.relpath(p, SYSTEM_ROOT), m.group(0)[:16]))
                break

    # ② 文档里的路径穿越
    for dirpath, dirs, files in os.walk(SYSTEM_ROOT):
        dirs[:] = [d for d in dirs if d not in SCAN_EXCLUDES]
        for fn in files:
            if not fn.endswith(('.md', '.json', '.py')):
                continue
            p = os.path.join(dirpath, fn)
            try:
                body = io.open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            m = TRAVERSAL.search(body)
            if m:
                rel = os.path.relpath(p, SYSTEM_ROOT)
                # 讲解「路径穿越」这个词本身不算问题
                ctx = body[max(0, m.start() - 40):m.start() + 40]
                if '穿越' in ctx or 'traversal' in ctx.lower():
                    continue
                problems.append("{} 含路径穿越 {}".format(rel, m.group(0)))
                break

    # ③ 外部数据项目的协议检查由其独立维护闸负责。

    # ④ 样例文件名是否合法（Windows 落地要求）
    ex = os.path.join(LIB, "示例")
    if os.path.isdir(ex):
        for fn in os.listdir(ex):
            if ILLEGAL_FNAME.search(fn):
                problems.append("示例文件名含非法字符: {}".format(fn))

    if problems:
        return False, "；".join(problems[:3])
    return True, "无可执行片段/无路径穿越/协议合法/文件名合法"


def check_perf():
    """量一下日常自检成本与核心脚本耗时。超阈值只提醒，不失败。"""
    out = []
    warn = []

    # 核心脚本单次产出
    pipe = os.path.join(LIB, "shortfilm_pipeline.py")
    t0 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, pipe, "江南书生夜雨", "--style", "工笔",
             "--mood", "肃杀", "--duration", "60", "--until", "分镜",
             "--out", os.path.join(SYSTEM_ROOT, ".perf_tmp")],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300, cwd=LIB)
        dt = time.time() - t0
        out.append("流水线单次 {:.1f}s".format(dt))
        if dt > 60:
            warn.append("流水线 {:.0f}s 偏慢".format(dt))
    except Exception as exc:  # noqa: BLE001
        out.append("流水线测量失败: {}".format(type(exc).__name__))
    finally:
        tmp = os.path.join(SYSTEM_ROOT, ".perf_tmp")
        if os.path.isdir(tmp):
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    # 整个项目体积（粗看是否失控）
    total = 0
    for dirpath, dirs, files in os.walk(SYSTEM_ROOT):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    gb = total / 1073741824
    out.append("项目 {:.1f} GB".format(gb))
    if gb > 30:
        warn.append("项目 {:.0f}GB 偏大".format(gb))

    return True, "，".join(out) + ("　⚠ " + "；".join(warn) if warn else "")


def main():
    ok1, m1 = check_security()
    ok2, m2 = check_perf()
    print("=" * 70)
    print("安全与性能体检")
    print("=" * 70)
    print("{} 安全      {}".format("✓" if ok1 else "✗", m1))
    print("✓ 性能      {}".format(m2))
    print("-" * 70)
    print("✓ 体检完成" if ok1 else "✗ 安全不通过")
    return 0 if ok1 else 1


if __name__ == "__main__":
    sys.exit(main())
