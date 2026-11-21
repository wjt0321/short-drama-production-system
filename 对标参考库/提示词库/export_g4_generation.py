#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G4 生成段提示词记录导出器。

**为什么需要**
体系 G4 是「首帧资产 → 视频」的关键中间环节，有自己的记录模板
（`模板/短剧项目模板/04-镜头/镜头提示词.md`）：生成段 ID、摄影执行字段
（运镜起点/过程/终点、焦点变化、屏幕方向、时间码节拍、拆分理由）、
参数引用、版本记录。

上一轮做到 G3（分镜表）和 G6（剪辑装配）跳过了 G4——**中间断了一节，
出图到视频之间的执行依据没有落纸面**。

本脚本从流水线分镜产物补齐 G4：每个生成段一份，含运镜三段式拆解、
焦点策略、轴线、节拍。

**设计原则**
  · 零 import 体系模块，只按字段名对齐
  · 不编造：能力登记 ID、资产版本、失败预算等需人工/实际执行后填
  · 竖屏安全区、画幅按通用短视频规格给默认值并标注

**用法**
    python export_g4_generation.py 制作包.json --out G4生成段.md
    python export_g4_generation.py --pipeline "敦煌飞天 复仇" --out G4生成段.md
"""
import argparse
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 摄影执行字段（与体系 G4 模板一致）
SHOT_FIELDS = [
    "镜头叙事功能", "主要观看重点", "起始状态", "动作目标与结束状态",
    "运镜起点/过程/终点", "焦点与焦点变化", "屏幕方向/轴线",
    "时间码节拍", "生成段拆分理由",
]

# 景别 → 焦点策略（AI 出图/出视频最常翻车的就是焦点）
FOCUS_RULES = {
    "大远景": "全景深，画面各层都要实；避免浅景深把远景糊掉",
    "远景":   "中等景深，主体略虚化以突出，环境保留可辨轮廓",
    "全景":   "全身清晰，背景适度虚化分离",
    "中景":   "焦点在面部/主体，背景虚化但不喧宾夺主",
    "近景":   "浅景深，焦点严格锁在双眼平面",
    "特写":   "极浅景深，只焦点在面部或道具，前后景全部虚化",
    "大特写": "微距级浅景深，焦点在极细节（如瞳孔/纹理），慎用易糊",
}

# 运镜起点/过程/终点：把「运镜意图」拆成三段可执行描述
MOVE_PARTS = {
    "固定":     ("机位锁定不动", "静待主体动作完成", "保持不动收尾"),
    "缓推":     ("起点：较远景别全景", "过程：匀速向前推近主体", "终点：停在近景/特写"),
    "缓慢拉远": ("起点：近景或中景", "过程：匀速向后拉", "终点：停在大远景交代环境"),
    "拉远":     ("起点：主体近景", "过程：匀速拉远", "终点：大远景，反衬孤独"),
    "横移":     ("起点：主体侧位", "过程：平行横移跟随", "终点：停在新主体位置"),
    "跟拍":     ("起点：主体后方同框", "过程：跟随主体移动", "终点：与主体同侧停下"),
    "环绕":     ("起点：主体正面 0°", "过程：绕主体旋转 180°", "终点：主体背面收"),
    "缓慢跟拍": ("起点：主体侧后", "过程：稳定跟随", "终点：主体正面"),
    "固定机位承载对话": ("机位锁定，正反打", "人物对话，视线平齐", "台词说完停住"),
}


def move_triplet(move_text):
    """把运镜意图拆成 起点/过程/终点。"""
    head = (move_text or "固定").split("，")[0]
    return MOVE_PARTS.get(head, (head, "按意图执行", "终点回到稳定构图"))


def build_segments(boards):
    segs = []
    cursor = 0
    for b in boards:
        n = b["scene"]
        dur = b.get("seconds", 0)
        start, end = cursor, cursor + dur
        cursor = end
        start_p, mid_p, end_p = move_triplet(b.get("camera_intent"))
        size = b.get("shot_size", "")
        # 屏幕方向：按幕给轴线，避免跳轴
        axis = {
            "第一幕": "正轴（观众与主体同侧），建立空间关系",
            "第二幕": "守正轴；需要越轴时插入一个过渡镜头",
            "第三幕": "回到正轴，收束空间关系",
        }.get(b.get("act_short"), "正轴")
        segs.append({
            "gid": b.get('generation_id', 'G{:03d}'.format(n)),
            "sids": "S{:02d}".format(n),
            "n": n,
            "size": size,
            "dur": dur,
            "tc": "{:02d}:{:02d}-{:02d}:{:02d}".format(
                start // 60, start % 60, end // 60, end % 60),
            "func": b.get("narrative_function", ""),
            "focus": FOCUS_RULES.get(size, "焦点在主体，背景虚化"),
            "focus_change": _focus_change(size),
            "move": (start_p, mid_p, end_p),
            "axis": axis,
            "split": _split_reason(b, dur),
            "prompt": b.get("first_frame_prompt_flow", ""),
            "dialogue": b.get("dialogue", ""),
            "gear": "{} / {}".format(b.get("camera_position", ""), b.get("focal_length", "")),
            "costume": b.get("costume", ""),
            "place": b.get("place", ""),
            "light": b.get("light", ""),
        })
    grouped = {}
    for seg in segs:
        if seg['gid'] not in grouped:
            grouped[seg['gid']] = seg
        else:
            existing = grouped[seg['gid']]
            existing['sids'] += ', ' + seg['sids']
            existing['dur'] += seg['dur']
            existing['prompt'] += '\n' + seg['prompt']
            existing['dialogue'] += '\n' + seg['dialogue']
            existing['tc'] = existing['tc'].split('-')[0] + '-' + seg['tc'].split('-')[-1]
            existing['split'] = '共享生成段；按已定内容连续呈现，检查段内动作与衔接'
    return list(grouped.values())


def _focus_change(size):
    return {
        "大远景": "焦点不变，全画面实焦",
        "远景": "由环境移向主体（单一转移）",
        "全景": "由下至上跟随全身（简单跟随）",
        "中景": "锁主体，焦点不动",
        "近景": "锁双眼，焦点不动",
        "特写": "锁面部，浅景深",
        "大特写": "锁极细节，慎用连续变焦避免抽帧",
    }.get(size, "焦点在主体")


def _split_reason(b, dur):
    """为什么单独成一个生成段。"""
    act = b.get("act_short", "")
    size = b.get("shot_size", "")
    parts = []
    if dur >= 12:
        parts.append("时长 {}s 偏长，单段生成更稳".format(dur))
    if size in ("特写", "大特写"):
        parts.append("特写景别与相邻镜头运动方式不同，拆开避免一致性漂移")
    if act == "第二幕":
        parts.append("冲突段，失败重抽代价高，单独成段便于回退")
    if not parts:
        parts.append("景别与运镜相对独立，可独立生成/重抽")
    return "；".join(parts)


def render(topic, segs, total):
    L = []
    L.append("# G4 生成段提示词记录：{}\n".format(topic))
    L.append("> 由 `export_g4_generation.py` 自动生成。共 **{}** 个生成段，总时长 {} 秒。".format(
        len(segs), int(total)))
    L.append("> **已填**：生成段/镜头 ID、时码、运镜三段式、焦点策略、轴线、拆分理由、首帧提示词。")
    L.append("> **待人工填**：能力登记 ID、资产版本、锚句版本、实际输出文件、失败预算结果。\n")

    for s in segs:
        L.append("## {} （对应 {}）\n".format(s["gid"], s["sids"]))
        L.append("| 字段 | 项目值 |")
        L.append("|---|---|")
        L.append("| 镜头叙事功能 | {} |".format(s["func"]))
        L.append("| 主要观看重点 | {} |".format(s["focus_change"]))
        L.append("| 起始状态 | {} |".format(s["place"]))
        L.append("| 动作目标与结束状态 | {} |".format(
            (s["prompt"].split(",")[3] if len(s["prompt"].split(",")) > 3 else "主体动作完成")))
        L.append("| 运镜起点/过程/终点 | {} → {} → {} |".format(*s["move"]))
        L.append("| 焦点与焦点变化 | {}；{} |".format(s["focus"], s["focus_change"]))
        L.append("| 屏幕方向/轴线 | {} |".format(s["axis"]))
        L.append("| 时间码节拍 | {}（{}s） |".format(s["tc"], s["dur"]))
        L.append("| 生成段拆分理由 | {} |".format(s["split"]))
        L.append("| 机位/焦段 | {} |".format(s["gear"]))
        L.append("| 能力登记 ID | 待人工填 |")
        L.append("| 角色/场景/道具/锚句版本 | 待人工填 |")
        L.append("| 画幅/分辨率/帧率 | 竖屏 9:16 / 1080x1920 / 24fps（按需改） |")
        L.append("| 声音要求 | 见 G6 剪辑装配单同镜头 FX/配音 ID |")
        L.append("")
        L.append("**首帧提示词**（通过后原文存这里）：\n")
        L.append("```text")
        L.append(s["prompt"])
        L.append("```\n")
        if s["dialogue"]:
            L.append("**台词**：{}\n".format(s["dialogue"]))
        L.append("| 版本 | 修改原因 | 输出素材文件 | 结果 | 是否通过 |")
        L.append("|---|---|---|---|---|")
        L.append("| v1 | 初版 | 待填 | 待填 | 待裁决 |")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="导出成体系 G4 生成段提示词记录")
    ap.add_argument("src", nargs="?", help="流水线 JSON 产物")
    ap.add_argument("--pipeline", help="直接跑流水线并导出")
    ap.add_argument("--style", default="写实")
    ap.add_argument("--mood", default=None)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--out", help="输出 md 路径")
    args = ap.parse_args()

    if args.pipeline:
        spec = importlib.util.spec_from_file_location(
            "sfp", os.path.join(HERE, "shortfilm_pipeline.py"))
        sfp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sfp)
        import lib_locator
        _pj = lib_locator.prompts_path()
        recs = sfp.load_records(_pj) if _pj else []
        r = sfp.run_pipeline(args.pipeline, args.duration, args.style,
                             args.mood, "分镜", recs, "")
        topic, boards = args.pipeline, r["storyboard"]
    elif args.src:
        d = json.load(open(args.src, encoding="utf-8"))
        d = d[0] if isinstance(d, list) else d
        topic, boards = d["topic"], d.get("storyboard") or []
    else:
        ap.error("请给 src 或 --pipeline")

    if not boards:
        print("没有分镜数据", file=sys.stderr)
        return 1

    segs = build_segments(boards)
    body = render(topic, segs, sum(b.get("seconds", 0) for b in boards))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(body)
        print("已写出 {}".format(args.out))
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
