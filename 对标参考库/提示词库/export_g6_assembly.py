#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把流水线产物导出成体系 G6 剪辑装配单。

**为什么需要**
体系 G6 的装配单要求「任何进入成片的画面、声音和字幕都必须能追溯到
稳定 ID 与文件版本」。缺了 ID 与时码，剪辑师无法开工，材料就废在最后一步。

本脚本从流水线 JSON 产物直接生成装配单：
  · 画面轨 V1：S01/G001 稳定 ID + 逐帧时间码
  · 声音与字幕：A/FX/BGM/SUB 稳定 ID + 策略
  · 素材文件/版本：留空（需真实出图/录音后回填）

**设计原则**
  · 零 import 体系模块，只按字段名对齐
  · 不编造：音频/视频文件路径一律「待填」，只给 ID 与节拍
  · 带门禁清单：对齐体系自己的时间线门禁项

**用法**
    python export_g6_assembly.py 制作包.json --out 剪辑装配单.md
    python export_g6_assembly.py --pipeline "敦煌飞天 复仇" --out 剪辑装配单.md
"""
import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

FIELDS = [
    "轨道", "剪辑镜头ID", "生成段ID", "素材文件/版本", "源入点", "源出点",
    "时间线入点", "时间线出点", "速度", "转场", "配音ID", "音效事件ID",
    "BGM ID", "字幕ID", "状态", "备注",
]


def tc(sec, ms=0):
    """秒 → HH:MM:SS.mmm"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return "{:02d}:{:02d}:{:02d}.{:03d}".format(h, m, int(s), ms)


def build_rows(boards, sound_plan):
    events = {e["sid"]: e for e in (sound_plan or {}).get("events", [])}
    bgm_id = (sound_plan or {}).get("bgm_id", "BGM001")
    rows = []
    cursor = 0.0
    prev_size = None
    segment_offsets = {}
    for b in boards:
        sid = "S{:02d}".format(b["scene"])
        gid = b.get('generation_id', 'G{:03d}'.format(b['scene']))
        dur = float(b.get("seconds", 0))
        ev = events.get(sid, {})
        source_in = float(b.get('source_in', segment_offsets.get(gid, 0)))
        segment_offsets[gid] = source_in + dur
        # Explicit editing decision wins; no automatic cut at generation boundaries.
        if prev_size is None:
            trans = "硬切（片头）"
        elif b.get('transition'):
            trans = b['transition']
        else:
            trans = '待按内容决定（连续呈现不切镜）'
        prev_size = b.get("shot_size")
        rows.append([
            "V1", sid, gid, "待填",
            tc(source_in), tc(source_in + dur),
            tc(cursor), tc(cursor + dur),
            "100%", trans,
            ev.get("voice_id", "—"), ev.get("fx_id", "—"),
            bgm_id, ev.get("sub_id", "—"),
            "待装配", ev.get("fx_note", ""),
        ])
        cursor += dur
    return rows, cursor


def render(topic, rows, total, sound_plan):
    L = []
    L.append("# G6 剪辑装配单：{}\n".format(topic))
    L.append("> 由 `export_g6_assembly.py` 从流水线产物自动生成。")
    L.append("> **画面/声音/字幕的稳定 ID 与时码已就位；实际文件路径需人工回填。**\n")

    L.append("## 时间线版本与确认\n")
    L.append("- 时间线版本：v0.1（待确认）")
    L.append("- 项目总时长：{} 秒（{:02d}:{:02d}）".format(
        int(total), int(total // 60), int(total % 60)))
    L.append("- 装配状态：未开始")
    L.append("- 用户裁决：待裁决")
    L.append("- 确认日期：")
    L.append("- 最终渲染文件/版本：")
    L.append("- 渲染规格记录：")
    L.append("- 完整回放结果：\n")

    L.append("## 时间线表\n")
    L.append("| " + " | ".join(FIELDS) + " |")
    L.append("|" + "---|" * len(FIELDS))
    for row in rows:
        cells = [str(c).replace("|", "\\|") for c in row]
        L.append("| " + " | ".join(cells) + " |")

    sp = sound_plan or {}
    L.append("\n## 声音与字幕说明\n")
    L.append("**BGM `{}`**：{}\n".format(sp.get("bgm_id", "BGM001"),
                                     sp.get("bgm_note", "待定")))
    L.append("| 镜头 | 配音ID | 字幕ID | 字幕策略 |")
    L.append("|---|---|---|---|")
    for e in sp.get("events", []):
        L.append("| {} | {} | {} | {} |".format(
            e["sid"], e["voice_id"], e["sub_id"], e["sub_note"]))
    L.append("\n> 音频/字幕文件需人工生成或挑选后，把路径写回「素材文件/版本」列。\n")

    L.append("\n## 抽卡失败回退链\n")
    L.append("生成段不合格时按顺序往下走，**不要在原地无限重抽**：\n")
    L.append("| 级别 | 触发条件 | 动作 | 代价 |")
    L.append("|---|---|---|---|")
    for lv, trig, act, cost in [
        ("R1", "动作/表情崩、身份漂移",
         "同一提示词换随机种子重抽，最多 2 次", "低，几分钟"),
        ("R2", "连续 2 次重抽仍不达标",
         "改首帧参考图（图生图修正帧）后再抽", "中，要重做首帧"),
        ("R3", "R2 仍不达标",
         "**降级为静态关键帧 + Ken Burns 推拉摇移变焦**——回忆、独白、过渡段用它反而更有味", "低，保住叙事不丢"),
        ("R4", "该镜是剧情关键、不能降级",
         "换同能力备选实现（降分辨率/换运镜强度重试），并登记原因", "中，可能影响一致"),
        ("R5", "R4 仍不达标",
         "**删镜并把时长补给相邻镜**，或用同场环境镜/空镜替代", "高，要重排时间线"),
    ]:
        L.append("| {} | {} | {} | {} |".format(lv, trig, act, cost))
    L.append("")
    L.append("> **任何一级回退都要在「备注」列登记**（原镜头号、触发了哪级、原因）。")
    L.append("> 删镜（R5）会改变时间线，必须重跑本表而不是手改。\n")

    L.append("## 时间线门禁\n")
    for c in [
        "所有剪辑镜头都能追溯到生成段和素材版本",
        "配音、音效事件、BGM 和字幕分别使用稳定 ID，可反查文件与版本",
        "画面、对白、音效、BGM、字幕的入出点无冲突",
        "变速、转场、裁切与画幅处理已登记",
        "时间线已完整回放，未出现黑帧、闪帧、断声或字幕越界",
        "渲染文件名、规格和校验结果已写入《成片质检表.md》",
    ]:
        L.append("- [ ] {}".format(c))
    L.append("- [ ] 走过的每一级回退都已在「备注」列登记原因")
    L.append("\n## 装配提示\n")
    L.append("- 按实际观看关系选择转场；未指定时只预填硬切草案，不按景别变化自动叠化，粗剪后再调整")
    L.append("- 配音 ID 只给到有台词的镜头；无台词镜留 `—` 是正常的")
    L.append("- 首帧资产需在 G3 通过后才填「素材文件/版本」")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="导出成体系 G6 剪辑装配单")
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
                             args.mood, "清单", recs, "")
        topic = args.pipeline
        boards = r["storyboard"]
        sp = r.get("sound_plan") or {}
    elif args.src:
        d = json.load(open(args.src, encoding="utf-8"))
        d = d[0] if isinstance(d, list) else d
        topic = d["topic"]
        boards = d.get("storyboard") or []
        sp = d.get("sound_plan") or {}
    else:
        ap.error("请给 src 或 --pipeline")

    if not boards:
        print("没有分镜数据", file=sys.stderr)
        return 1

    rows, total = build_rows(boards, sp)
    body = render(topic, rows, total, sp)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(body)
        print("已写出 {}".format(args.out))
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
