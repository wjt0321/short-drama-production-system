#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把流水线的分镜产物导出成体系 G3 分镜表（24 字段）。

**为什么需要**
`短剧成片体系` 的 G3 阶段有自己的分镜表模板
（`模板/短剧项目模板/03-分镜/分镜表.md`），24 个字段，含机位/焦段、
镜前镜后状态、对下一镜约束、锚句版本、时码等。
流水线原本输出的是自己的展示格式，**接不上体系**——
这就是「两个项目互相补全」没做到的地方。

本脚本做纯粹的**格式对齐**：把流水线结果映射进体系字段。
不知道的字段留空并标注「待人工填」，不编造。

**用法**
    # 从制作包 md 或 json 导出
    python export_g3_storyboard.py 制作包.json --out 分镜表.md
    # 直接从流水线跑并导出
    python export_g3_storyboard.py --pipeline "敦煌飞天 复仇" --out 分镜表.md

**设计原则**
  · 零耦合：不 import 体系任何模块，只按字段名对齐
  · 不编造：填不了的写「待人工填」，让人一眼看出还差什么
  · 可追溯：每行带回原始镜头号，方便回查制作包
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 体系 G3 分镜表的字段顺序（与 模板/短剧项目模板/03-分镜/分镜表.md 一致）
G3_FIELDS = [
    "剪辑镜头ID", "生成段ID", "剧本段落", "场次", "时间线时码",
    "本镜叙事功能", "镜前状态", "镜后状态", "情绪变化", "观众新增信息",
    "对下一镜约束", "景别", "机位/焦段", "主体动作", "台词/声音",
    "首帧资产", "尾帧参考", "锚句版本", "角色版本", "场景版本",
    "道具版本", "素材文件/版本", "状态", "备注",
]

FILL = "待人工填"


def timecode(idx, secs):
    """把「第几镜 + 时长」折成 mm:ss-mm:ss。"""
    start = secs
    end = secs + 0  # 由调用方累加
    return "00:{:02d}-00:{:02d}".format(start // 60, start % 60), end


def build_rows(boards, plot=None):
    """boards: run_pipeline 产出的 storyboard 列表。返回 G3 表格行。"""
    rows = []
    cursor = 0
    for b in boards:
        n = b["scene"]
        start = cursor
        end = cursor + b.get("seconds", 0)
        cursor = end
        tc = "{:02d}:{:02d}-{:02d}:{:02d}".format(
            start // 60, start % 60, end // 60, end % 60)

        act = b.get("act_short", "")
        size = b.get("shot_size", "")
        # 观众新增信息：按景别推「这一镜让观众知道什么」
        new_info = {
            "大远景": "世界规模与基调",
            "远景": "人物与空间的位置关系",
            "全景": "主体正在做什么",
            "中景": "双方在说什么/态度",
            "近景": "主角情绪细节",
            "特写": "关键道具或表情细节",
            "大特写": "观众必须注意的细节",
        }.get(size, FILL)

        # 情绪变化：按幕
        mood_delta = {"第一幕": "建立", "第二幕": "升温", "第三幕": "回落"}.get(act, FILL)


        rows.append([
            "S{:02d}".format(n),                 # 剪辑镜头ID
            b.get('generation_id', 'G{:03d}'.format(n)),  # Draft mapping; may share a segment
            act,                                 # 剧本段落
            "场{}".format(n),                     # 场次
            tc,                                  # 时间线时码
            b.get("narrative_function", FILL),   # 本镜叙事功能
            b.get("state_before", FILL),         # 镜前状态
            b.get('state_after', FILL),           # Actual authored result; never infer from shot size
            mood_delta,                          # 情绪变化
            b.get('new_information', FILL),       # Author supplies actual new information
            b.get('next_relation', FILL),         # Author supplies actual viewing relationship
            size,                                # 景别
            "{} / {}".format(b.get("camera_position", FILL),
                              b.get("focal_length", FILL)),   # 机位/焦段
            (b.get("nine_parts", {}) or {}).get("动作/神态", FILL),   # 主体动作
            b.get("dialogue", FILL) or FILL,     # 台词/声音
            b.get('first_frame_asset', FILL),      # Actual asset, not prompt text
            FILL,                                # 尾帧参考
            FILL,                                # 锚句版本
            FILL,                                # 角色版本
            FILL,                                # 场景版本
            FILL,                                # 道具版本
            FILL,                                # 素材文件/版本
            "待生成",                            # 状态
            "由 shortfilm_pipeline 导出",          # 备注
        ])
    return rows


def render_g3(topic, rows, boards):
    L = []
    L.append("# G3 分镜表：{}\n".format(topic))
    L.append("> 由 `shortfilm_pipeline.py` 产物自动对齐导出（24 字段）。")
    L.append("> **标 `{}` 的字段需要人工补**——流水线不编造，缺什么一目了然。\n".format(FILL))
    L.append("| " + " | ".join(G3_FIELDS) + " |")
    L.append("|" + "---|" * len(G3_FIELDS))
    for row in rows:
        cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in row]
        L.append("| " + " | ".join(cells) + " |")

    # 附：每镜首帧提示词全文（分镜表里塞不下，单独给）
    L.append("\n## 附：逐镜首帧提示词（可直接出图）\n")
    for b in boards:
        L.append("**S{:02d} · {} · {}s**\n".format(
            b["scene"], b["shot_size"], b["seconds"]))
        L.append("```")
        L.append(b.get("first_frame_prompt_flow", ""))
        L.append("```")
        L.append("- 运镜意图：{}".format(b.get("camera_intent", "")))
        L.append("- 负向：{}\n".format(b.get("negative", "")))

    # 通过条件（对齐体系自己的 G3 裁决项）
    L.append("## G3 逐镜通过条件\n")
    for c in [
        "每个剪辑镜头有明确叙事功能并关联生成段",
        "构图、机位、焦段和竖屏安全区明确",
        "角色、场景、道具锚句可追溯（**待补版本号**）",
        "首帧来自已审核资产；尾帧只作下一段参考并需复审",
        "台词、动作、声音和时间码不冲突",
        "素材文件与版本可追溯（**待补**）",
    ]:
        L.append("- [ ] {}".format(c))
    L.append("\n裁决：通过 / 修改（指出项） / 暂停")
    L.append("备注：")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="导出成体系 G3 分镜表（24 字段）")
    ap.add_argument("src", nargs="?", help="流水线 JSON 产物路径")
    ap.add_argument("--pipeline", help="直接跑流水线并导出，参数是题材")
    ap.add_argument("--style", default="写实")
    ap.add_argument("--mood", default=None)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--out", help="输出 md 路径（默认打印到 stdout）")
    args = ap.parse_args()

    if args.pipeline:
        import importlib.util
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
        ap.error("请给 src（JSON 产物）或 --pipeline 题材")

    if not boards:
        print("没有分镜数据可导出", file=sys.stderr)
        return 1

    rows = build_rows(boards)
    body = render_g3(topic, rows, boards)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(body)
        print("已写出 {}".format(args.out))
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
