#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""种子活到成片闸。

G0 写下的物件或话语，到成片回放时还要能在导演笔记里被指认。
答「不在」，或答不出来，作品停留在「技术已通过，作品未验证」。
没到成片回放的项目不挡。

同时核一件附属的事：重抽日志里错误类型为「发现」的行，
质量重抽次数必须是 0，修改内容要写到分镜或种子。

用法
    python tools/check_seed_survival.py <项目目录>
    python tools/check_seed_survival.py
    python tools/check_seed_survival.py --selftest

退出码：0 通过或尚无成片回放 / 1 种子没活到画面或发现回写记错 / 2 自检失败
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

from _art_exception import (  # noqa: E402
    field,
    han_count,
    load_exception,
    section_body,
    seed_value,
)

GATE = "种子活到成片-真片"
SEED_HEADING = "## 种子是否还在画面里"
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}
SHOT_RE = re.compile(r"(?:\*\*)?(?:S|G)\d{1,3}(?:\*\*)?$")


def discover_projects():
    root = os.path.join(SYSTEM_ROOT, "00-视频项目")
    if not os.path.isdir(root):
        return []
    return [
        os.path.join(root, name)
        for name in sorted(os.listdir(root))
        if os.path.isdir(os.path.join(root, name)) and not name.startswith("_")
    ]


def at_playback(project):
    summary = os.path.join(project, "项目状态摘要.md")
    if os.path.isfile(summary):
        try:
            text = open(summary, encoding="utf-8", errors="replace").read()
        except OSError:
            text = ""
        if re.search(r"当前关卡：[ \t]*G6(\s|$)", text, re.M):
            return True
    deliver = os.path.join(project, "06-成片")
    if not os.path.isdir(deliver):
        return False
    for dirpath, _dirs, files in os.walk(deliver):
        for name in files:
            if os.path.splitext(name)[1].lower() in VIDEO_EXT:
                return True
    return False


def _note(project):
    path = os.path.join(project, "06-成片", "导演证据", "导演笔记.md")
    if not os.path.isfile(path):
        return ""
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def seed_problems(project):
    problems = []
    seed = seed_value(project)
    if not seed:
        problems.append("G0 具体物件或话语还是空的，成片回放没有种子可对")
        return problems
    section = section_body(_note(project), SEED_HEADING)
    if section is None:
        problems.append("导演笔记缺「种子是否还在画面里」")
        return problems
    quoted = field(section, "种子原文")
    presence = field(section, "还在画面里")
    change = field(section, "意思是否变过")
    shot = field(section, "看见它的镜头")
    status = field(section, "作品状态")
    if seed not in quoted and quoted not in seed:
        problems.append("种子原文没有写上 G0 的物件或话语")
    if presence not in ("在", "不在"):
        problems.append("还在画面里必须写成「在」或「不在」")
        return problems
    if han_count(change) < 8:
        problems.append("意思是否变过要写成能看懂的一句（至少 8 个汉字）")
    if presence == "在":
        if not SHOT_RE.match(shot.strip()):
            problems.append("看见它的镜头要写成 S 或 G 加镜号")
        if "种子仍在画面里" not in status:
            problems.append("作品状态要写上「种子仍在画面里」")
    else:
        if shot.strip() not in ("无",) and not SHOT_RE.match(shot.strip()):
            problems.append("种子不在画面里时，看见它的镜头写「无」")
        if "技术已通过，作品未验证" not in status:
            problems.append("种子不在画面里时，作品状态要写「技术已通过，作品未验证」")
        problems.append("种子不在画面里，G6 不能当作作品通过")
    record = load_exception(project)
    if record["status"] == "invalid":
        problems.extend(record["problems"])
    return problems


def discovery_problems(project):
    path = os.path.join(project, "04-镜头", "重抽日志.md")
    if not os.path.isfile(path):
        return []
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return ["重抽日志打不开"]
    header = None
    problems = []
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if header is None:
            if "错误类型" in cells and "质量重抽次数" in cells:
                header = cells
            continue
        if cells and set("".join(cells)) <= set("-: "):
            continue
        if len(cells) < len(header):
            continue
        row = dict(zip(header, cells))
        if row.get("错误类型", "").strip() != "发现":
            continue
        shot = row.get("镜号/资产号", "")
        if not re.search(r"\d", shot):
            continue
        count = row.get("质量重抽次数", "").strip()
        if count != "0":
            problems.append("发现回写的质量重抽次数必须是 0，当前是 {}".format(count or "空"))
        note = row.get("修改内容", "")
        if "分镜" not in note and "种子" not in note:
            problems.append("发现回写的修改内容要写明回写了哪条分镜，以及它如何更靠近种子")
    return problems


def check_project(project):
    if not at_playback(project):
        return [], {"状态": "留到成片"}
    problems = seed_problems(project) + discovery_problems(project)
    return problems, {"状态": "已检查", "问题": len(problems)}


def audit_all():
    projects = discover_projects()
    if not projects:
        print("[未评估] 未发现在制项目，本闸没有可判对象")
        return 0
    ready = []
    waiting = []
    for project in projects:
        if at_playback(project):
            ready.append(project)
        else:
            waiting.append(os.path.basename(project))
    if waiting:
        print("· 还没到成片回放：{}".format("、".join(waiting)))
    if not ready:
        print("· 在制项目都还没到成片回放，种子问题留到出现成片或当前关卡写明 G6")
        return 0
    bad = 0
    for project in ready:
        problems, _facts = check_project(project)
        name = os.path.basename(project)
        if problems:
            bad += 1
            print("  {:<28s} ✗ {}".format(name, problems[0]))
            for item in problems[1:]:
                print("    ✗ {}".format(item))
        else:
            print("  {:<28s} ✓ 种子仍在画面里".format(name))
    if bad:
        print("\n  修法：回看 G0 的物件或话语。还在画面里，就写在哪一镜、意思变过没有。")
        print("  不在了，作品状态写「技术已通过，作品未验证」，本闸不通过。")
        return 1
    print("✓ 进入成片回放的项目，种子都还在画面里")
    return 0


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _project(root, seed="母亲留下的铜钥匙", gate_line="", presence="在",
             status="种子仍在画面里", shot="S04", change="没变，钥匙还挂在她自己的手上",
             quoted=None, decision="", protects=None, gate="",
             discovery=None, mark_g6=True):
    quoted = seed if quoted is None else quoted
    if protects is None:
        protects = seed if (decision or gate) else ""
    _write(os.path.join(root, "00-立项", "风格提案.md"),
           "片型：叙事\n- 具体物件或话语：{}\n".format(seed))
    if mark_g6:
        _write(os.path.join(root, "项目状态摘要.md"), "- 当前关卡：G6\n")
    note = [
        "# 导演笔记",
        "",
        "## 种子是否还在画面里",
        "",
        "- 种子原文：{}".format(quoted),
        "- 还在画面里：{}".format(presence),
        "- 意思是否变过：{}".format(change),
        "- 看见它的镜头：{}".format(shot),
        "- 作品状态：{}".format(status),
        "",
        "## 一处不可解释的决定",
        "",
        "- 决定：{}".format(decision),
        "- 保护的种子：{}".format(protects),
        "- 破例闸：{}".format(gate),
        "",
    ]
    if gate_line:
        note.append(gate_line)
    _write(os.path.join(root, "06-成片", "导演证据", "导演笔记.md"), "\n".join(note))
    if discovery:
        _write(os.path.join(root, "04-镜头", "重抽日志.md"), discovery)


def selftest():
    import shutil
    import tempfile
    failed = False

    def check(name, cond):
        nonlocal failed
        if cond:
            print("[自检通过] " + name)
        else:
            failed = True
            print("[自检失败] " + name)

    tmp = tempfile.mkdtemp(prefix="seedgate_")
    try:
        early = os.path.join(tmp, "early")
        _project(early, mark_g6=False)
        problems, facts = check_project(early)
        check("没到成片回放不挡", facts["状态"] == "留到成片" and not problems)

        good = os.path.join(tmp, "good")
        _project(good)
        problems, _facts = check_project(good)
        check("种子还在且写实则通过", not problems)

        missing = os.path.join(tmp, "missing")
        _project(missing, quoted="另一把钥匙")
        problems, _facts = check_project(missing)
        check("种子原文对不上被抓住", any("种子原文" in item for item in problems))

        gone = os.path.join(tmp, "gone")
        _project(gone, presence="不在", shot="无",
                 status="技术已通过，作品未验证",
                 change="钥匙没有再出现，意思断在剧本里")
        problems, _facts = check_project(gone)
        check("答不在则不能当作品通过", any("不能当作作品通过" in item for item in problems))

        menu = os.path.join(tmp, "menu")
        _project(menu, presence="在 / 不在")
        problems, _facts = check_project(menu)
        check("模板里的在或不在算没填", any("还在画面里" in item for item in problems))

        bad_exc = os.path.join(tmp, "badexc")
        _project(bad_exc, decision="就想这样", protects="别的东西", gate="hook收尾、静止比例")
        problems, _facts = check_project(bad_exc)
        check("破例写坏被抓住", any("破例闸" in item or "保护的种子" in item or "不足一句" in item
                                   for item in problems))

        ok_exc = os.path.join(tmp, "okexc")
        _project(ok_exc,
                 decision="末镜只留她看着手心，不再揭晓钥匙通向哪里",
                 gate="hook收尾")
        problems, _facts = check_project(ok_exc)
        check("一处写实的破例不另判失败", not problems)

        log = "\n".join([
            "| 时间 | 镜号/资产号 | 能力 | 版本 | 错误类型 | 质量重抽次数 | 技术重试次数 | 回退级别 | 修改内容 | 成本 | 结果 | 用户决策 |",
            "|---|---|---|---|---|---:|---:|---|---|---:|---|---|",
            "| 1104 | S03 | 图生 | v1 | 发现 | 1 | 0 |  | 回写分镜 | 0 | 更近 |  |",
        ])
        bad_log = os.path.join(tmp, "badlog")
        _project(bad_log, discovery=log)
        problems, _facts = check_project(bad_log)
        check("发现回写记成质量重抽被抓住", any("质量重抽次数" in item for item in problems))

        good_log_text = log.replace("| 1 |", "| 0 |", 1)
        good_log = os.path.join(tmp, "goodlog")
        _project(good_log, discovery=good_log_text)
        problems, _facts = check_project(good_log)
        check("发现回写次数为 0 且写了分镜则放行", not problems)

        sys.path.insert(0, HERE)
        import check_hook_density
        hook_root = os.path.join(tmp, "hook")
        _project(hook_root,
                 decision="末镜不揭晓，钥匙的分量停在她没有交出的那一下",
                 gate="hook收尾")
        board = "\n".join([
            "| 镜号 | hook |",
            "|---|---|",
            "| S01 | suspense |",
            "| S02 | expression-beat |",
        ])
        _write(os.path.join(hook_root, "03-分镜", "分镜表.md"), board)
        hooked, _facts = check_hook_density.analyse(hook_root)
        check("末镜破例后不再报收尾强钩", not any(item.startswith("⑥") for item in hooked))
        board_weak = board.replace("suspense", "setup", 1)
        _write(os.path.join(hook_root, "03-分镜", "分镜表.md"), board_weak)
        hooked, _facts = check_hook_density.analyse(hook_root)
        check("开场弱钩在破例后仍失败", any(item.startswith("⑤") for item in hooked))

        import check_style_lock
        color_root = os.path.join(tmp, "color")
        _project(color_root,
                 decision="每场的光跟着钥匙走，不把全片收成同一种情绪尺度",
                 gate="色彩情绪")
        lock = (
            "渲染风格写实水墨，边缘保留纸纹。"
            "造型语言灰蓝棉麻，头身比写实。"
            "发丝有分缕，皮肤保留毛孔。"
            "表演风格少手势，动态风格以步行和停顿为主。"
            "情绪尺度克制，主色灰蓝，点缀色只留铜。"
            "负向约束写成暗部仍能看见布纹。"
        )
        _write(os.path.join(color_root, "00-立项", "风格提案.md"),
               "片型：叙事\n- 具体物件或话语：母亲留下的铜钥匙\n```style-lock\n{}\n```\n".format(lock))
        kept = (
            "渲染风格写实水墨，边缘保留纸纹。"
            "造型语言灰蓝棉麻，头身比写实。"
            "发丝有分缕，皮肤保留毛孔。"
            "表演风格少手势，动态风格以步行和停顿为主。"
            "负向约束写成暗部仍能看见布纹。"
        )
        _write(os.path.join(color_root, "04-镜头", "prompts", "S01.md"),
               "mode: T2V\n" + kept + "\n本镜光色：窗缝里只有一把铜钥匙的反光\n")
        _write(os.path.join(color_root, "04-镜头", "prompts", "S02.md"),
               "mode: T2V\n" + kept + "\n本镜光色：院子里的天光把钥匙压成一块暗斑\n")
        color_problems, _facts = check_style_lock.analyse(color_root)
        check("两条不同的本镜光色可以通过", not color_problems)
        _write(os.path.join(color_root, "04-镜头", "prompts", "S02.md"),
               "mode: T2V\n" + kept + "\n本镜光色：窗缝里只有一把铜钥匙的反光\n")
        color_problems, _facts = check_style_lock.analyse(color_root)
        check("两条相同的本镜光色不通过", any("本镜光色" in item for item in color_problems))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if failed:
        return 2
    print("[自检通过] 种子活到成片")
    return 0


def main():
    parser = argparse.ArgumentParser(description="种子是否还在成片画面里")
    parser.add_argument("project", nargs="?")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.project:
        problems, facts = check_project(args.project)
        print(facts)
        for item in problems:
            print("  ✗ " + item)
        if facts.get("状态") == "留到成片":
            print("· 还没到成片回放，种子问题先留着")
            return 0
        return 1 if problems else 0
    return audit_all()


if __name__ == "__main__":
    sys.exit(main())
