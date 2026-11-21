#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剧本去 AI 味 · G1 表达层检查。

只扫项目里的 01-剧本/剧本.md。单次套话只提醒；同一场堆到 3 处、
否定翻转出现 2 次及以上，或出现总结式收尾，才退出码 1。
不判断作者身份，也不替代剧本因果闸。

用法
    python tools/check_script_ai_flavor.py <项目目录>
    python tools/check_script_ai_flavor.py
    python tools/check_script_ai_flavor.py --selftest
"""
from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

RULES = (
    ("not-flip", "否定翻转", re.compile(r"不是[^。！？\n]{1,30}，\s*(?:而是|是)")),
    ("emotion-label", "情绪贴牌", re.compile(
        r"眼神里闪过|眼中闪过一丝|冷笑一声|挑了挑眉|霸气侧漏|绝美|"
        r"(?:他|她|他们)(?:终于)?意识到|(?:他|她)感到一[丝阵股]|"
        r"(?:愤怒|悲伤|高兴|激动)地说")),
    ("summary-close", "总结收尾", re.compile(
        r"原来[，,]?\s*真正的|真正的(?:强大|勇气|意义)是|"
        r"这一刻[，,]?(?:他|她)终于(?:明白|懂得)")),
    ("uplift", "拔高", re.compile(
        r"随着[^。\n]{0,16}的(?:发展|到来)|不仅[^。\n]{0,24}，?\s*更|彰显")),
    ("lecture", "讲义列举", re.compile(r"首先[，、][^。\n]{0,40}其次")),
)

SCENE_SPLIT = re.compile(r"(?=^##\s*(?:场景|幕)\b)", re.M)
SCENE_NAME = re.compile(r"^##\s*((?:场景|幕)\s*\S*)")


def visible_lines(text):
    kept = []
    fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            fence = not fence
            continue
        if fence or line.lstrip().startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept)


def iter_scenes(text):
    parts = [p for p in SCENE_SPLIT.split(text) if p.strip()]
    named = []
    for part in parts:
        match = SCENE_NAME.match(part)
        if match:
            named.append((match.group(1), part))
    if named:
        return named
    return [("全文", text)]


def collect(text):
    hits = []
    for scene, chunk in iter_scenes(visible_lines(text)):
        for rule_id, label, pattern in RULES:
            for match in pattern.finditer(chunk):
                hits.append({
                    "scene": scene,
                    "rule": rule_id,
                    "label": label,
                    "excerpt": match.group(0)[:40],
                })
    return hits


def failures(hits):
    reasons = []
    flips = [h for h in hits if h["rule"] == "not-flip"]
    if len(flips) >= 2:
        reasons.append("否定翻转出现 {} 次".format(len(flips)))
    if any(h["rule"] == "summary-close" for h in hits):
        reasons.append("出现总结式收尾")
    counts = {}
    for hit in hits:
        counts[hit["scene"]] = counts.get(hit["scene"], 0) + 1
    for scene, count in counts.items():
        if count >= 3:
            reasons.append("{} 堆了 {} 处套话".format(scene, count))
    return reasons


def find_script(project):
    path = os.path.join(project, "01-剧本", "剧本.md")
    return path if os.path.isfile(path) else ""


def discover_projects():
    container = os.path.join(SYSTEM_ROOT, "00-视频项目")
    if not os.path.isdir(container):
        return []
    return [
        os.path.join(container, name)
        for name in sorted(os.listdir(container))
        if os.path.isdir(os.path.join(container, name)) and not name.startswith("_")
    ]


def report(name, hits, reasons):
    print("剧本去AI味：{}".format(name))
    if not hits and not reasons:
        print("  通过：可见正文没有命中套话")
        return 0
    for hit in hits[:20]:
        print("  - {} [{}] {}".format(hit["scene"], hit["label"], hit["excerpt"]))
    if len(hits) > 20:
        print("  … 另有 {} 处".format(len(hits) - 20))
    if reasons:
        for reason in reasons:
            print("  ✗ " + reason)
        return 1
    print("  提醒：有套话但没超线，不自动重写")
    return 0


def audit_project(project):
    script = find_script(project)
    if not script:
        print("剧本去AI味：{}".format(os.path.basename(project)))
        print("  [未评估] 没有剧本")
        return 0
    with open(script, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    hits = collect(text)
    return report(os.path.basename(project), hits, failures(hits))


def audit_all():
    projects = [p for p in discover_projects() if find_script(p)]
    if not projects:
        print("[未评估] 未发现在制项目")
        return 0
    code = 0
    for project in projects:
        code = max(code, audit_project(project))
    return code


def selftest():
    ok = True

    def expect(title, text, should_fail):
        nonlocal ok
        failed = bool(failures(collect(text)))
        if failed != should_fail:
            ok = False
            print("[自检失败] {}：期望失败={} 实际失败={}".format(title, should_fail, failed))
        else:
            print("[自检通过] {}".format(title))

    piled = "\n".join([
        "## 场景 01",
        "她感到一阵怒意，冷笑一声，眼神里闪过一丝轻蔑。",
    ])
    one = "\n".join([
        "## 场景 01",
        "他冷笑一声，把牙膏放回杯子里。",
    ])
    two_flips = "\n".join([
        "## 场景 01",
        "他要的不是钱，是说法。",
        "## 场景 02",
        "她推开门，不是来道歉，而是来拿回钥匙。",
    ])
    summary = "\n".join([
        "## 场景 01",
        "他关上灯。原来，真正的强大是学会告别。",
    ])
    clean = "\n".join([
        "## 场景 01",
        "她想让他先开口，这样走的人就不是她。",
        "因为门还开着，所以她把钥匙留在桌上。",
    ])
    quoted = "\n".join([
        "> 原来，真正的强大是一句说明，不要当成正文。",
        "## 场景 01",
        "她把钥匙留在桌上。",
    ])
    expect("一场三处套话失败", piled, True)
    expect("单次冷笑只提醒", one, False)
    expect("两处否定翻转失败", two_flips, True)
    expect("总结收尾失败", summary, True)
    expect("具体心思和因果通过", clean, False)
    expect("引用里的总结句不计数", quoted, False)
    return 0 if ok else 2


def main():
    parser = argparse.ArgumentParser(description="剧本去 AI 味：套话密度，不判断作者身份")
    parser.add_argument("project", nargs="?", help="项目目录；省略则扫描全部在制项目")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if not args.project:
        return audit_all()
    if not os.path.isdir(args.project):
        print("目录不存在：{}".format(args.project))
        return 2
    return audit_project(args.project)


if __name__ == "__main__":
    sys.exit(main())
