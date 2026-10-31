#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字幕烧录器 / Subtitle Burner（G6 手动工具，非闸）

把项目《字幕事件表.md》转成 ASS 字幕文件，并可调用 ffmpeg 硬烧进成片。
规范依据：06-后期与发布/成片与字幕.md §4（两套预设 drama/movie）。

零第三方依赖（标准库）；--burn 需要 ffmpeg（自动定位：PATH → 环境变量 FFMPEG_BIN
→ 体系旁 ComfyUI 自带 tools/ffmpeg/bin）。

用法：
    python tools/subtitle_burn.py <项目目录> [--preset drama|movie]
                                             [--make-ass] [--burn]
                                             [--video 路径] [--out 路径]
    python tools/subtitle_burn.py --selftest

输入：项目目录下 06-成片/字幕事件表.md（模板列见 模板/短剧项目模板/06-成片/）
输出：06-成片/subtitles.ass（--make-ass）与 06-成片/成片_字幕版.mp4（--burn）

事件表约定：
    - 【关键词】在 drama 预设下转强调色（金黄），movie 预设下忽略（只去括号）
    - 断句/换行列：可填断点字符数（如 12 表示在第 12 字后断行）；留空则自动断
    - 样式版本列：v1=主字幕，v2=强调（字号 +15%），v3=旁白（85% 不透明度）
    - 状态列：跳过「废弃」，其余全部纳入；「待审」会逐条警告但仍纳入
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------------------
# 预设参数（规范文档 §2.4；字号/边距按画幅方向分档）
# ---------------------------------------------------------------------------

PRESETS = {
    "drama": {
        "line_limit": 15,                     # 单行汉字上限
        "vertical":   {"size": 66, "margin_v": 280, "outline": 3.5, "shadow": 1},
        "horizontal": {"size": 56, "margin_v": 60,  "outline": 3.0, "shadow": 1},
        "bold": True,
        "keyword_color": "&H00D7FF&",         # 金黄（ASS 为 BGR 序）
        "use_keyword": True,
    },
    "movie": {
        "line_limit": 20,
        "vertical":   {"size": 46, "margin_v": 200, "outline": 1.8, "shadow": 0},
        "horizontal": {"size": 44, "margin_v": 60,  "outline": 1.5, "shadow": 0},
        "bold": False,
        "keyword_color": None,
        "use_keyword": False,
    },
}

# 字体映射（本机已验证；其他环境按规范文档 §2.3「字体性格」自行替换）
FONT_MAIN = "Microsoft YaHei"

WHITE = "&H00FFFFFF&"
BLACK = "&H00000000&"
NARRATION_ALPHA = "&H26"  # 约 15% 透明


# ---------------------------------------------------------------------------
# 事件表解析
# ---------------------------------------------------------------------------

def parse_event_table(path):
    """解析字幕事件表，返回 [{id, shot, text, speaker, tin, tout, break_at, style_ver, status}]。"""
    lines = open(path, encoding="utf-8").read().split("\n")
    rows = []
    for ln in lines:
        s = ln.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return []
    header = rows[0]

    def col(*names):
        for nm in names:
            for i, h in enumerate(header):
                if nm in h:
                    return i
        return None

    idx = {
        "id": col("字幕ID"),
        "text": col("文本"),
        "tin": col("入点"),
        "tout": col("出点"),
        "brk": col("断句", "换行"),
        "ver": col("样式版本"),
        "status": col("状态"),
    }
    if idx["id"] is None or idx["text"] is None or idx["tin"] is None or idx["tout"] is None:
        return None  # 关键列缺失

    events = []
    for cells in rows[2:]:
        def g(k):
            i = idx[k]
            return cells[i] if i is not None and i < len(cells) else ""
        status = g("status")
        if status == "废弃":
            continue
        text = g("text")
        if not text:
            continue
        events.append({
            "id": g("id"),
            "text": text,
            "tin": g("tin"),
            "tout": g("tout"),
            "break_at": g("brk"),
            "ver": g("ver") or "v1",
            "status": status,
        })
    return events


# ---------------------------------------------------------------------------
# 文本处理：关键词、断行
# ---------------------------------------------------------------------------

def ass_time(tc):
    """00:00:00.000 / 00:00:00,000 → 0:00:00.00（ASS 厘秒）"""
    m = re.match(r"(\d+):(\d+):(\d+)[.,](\d+)", tc)
    if not m:
        return None
    h, mnt, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    cs = int(round(int(ms.ljust(3, "0")[:3]) / 10.0))
    if cs == 100:
        s, cs = s + 1, 0
    return f"{h}:{mnt:02d}:{s:02d}.{cs:02d}"


def visual_len(text):
    """近似显示长度：汉字/全角计 1，ASCII 计 0.5。"""
    n = 0.0
    for ch in text:
        n += 1.0 if ord(ch) > 0x2E7F else 0.5
    return n


def apply_keywords(text, preset):
    """【关键词】→ ASS 内联强调色；movie 预设只去括号。"""
    p = PRESETS[preset]
    if not p["use_keyword"]:
        return text.replace("【", "").replace("】", ""), 0
    count = 0

    def repl(m):
        nonlocal count
        count += 1
        return "{\\1c%s}%s{\\1c%s}" % (p["keyword_color"], m.group(1), WHITE)

    return re.sub(r"【(.+?)】", repl, text), count


def break_lines(text, preset, break_at=""):
    """超限时断为两行。断点：断句列指定 > 标点 > 硬断。"""
    limit = PRESETS[preset]["line_limit"]
    plain = text.replace("【", "").replace("】", "")
    if visual_len(plain) <= limit:
        return text
    # 断点候选（在纯文本坐标系里找，再映射回带【】的原文本）
    pos = None
    if break_at.isdigit():
        pos = int(break_at)
    else:
        best = None
        for i, ch in enumerate(plain):
            if ch in "，、；：！？—…" and limit - 5 <= i <= limit + 2:
                best = i + 1
        pos = best if best else limit
    pos = max(1, min(pos, len(plain) - 1))
    # 映射：plain 的第 pos 个字符后 = 原文本（含【】）的对应位置
    seen, cut = 0, len(text)
    for i, ch in enumerate(text):
        if ch in "【】":
            continue
        seen += 1
        if seen == pos:
            cut = i + 1
            break
    return text[:cut] + "\\N" + text[cut:]


# ---------------------------------------------------------------------------
# ASS 生成
# ---------------------------------------------------------------------------

def build_ass(events, preset, res):
    w, h = res
    p = PRESETS[preset]
    geom = p["vertical"] if h > w else p["horizontal"]
    bold = -1 if p["bold"] else 0
    size = geom["size"]

    def style_line(name, sz, alpha_prefix="&H00", b=bold):
        # Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,
        # OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,
        # ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,
        # Alignment, MarginL, MarginR, MarginV, Encoding
        return (
            f"Style: {name},{FONT_MAIN},{sz},{alpha_prefix}FFFFFF,&H000000FF,"
            f"{BLACK},&H64000000,{b},0,0,0,100,100,0.6,0,1,"
            f"{geom['outline']},{geom['shadow']},2,60,60,{geom['margin_v']},1"
        )

    styles = [
        style_line("Main", size),
        style_line("Punch", round(size * 1.15)),
        style_line("Narration", round(size * 0.92), alpha_prefix=NARRATION_ALPHA, b=0),
    ]
    ver2style = {"v1": "Main", "v2": "Punch", "v3": "Narration"}

    out = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {w}",
        f"PlayResY: {h}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
    ] + styles + [
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    skipped, kw_total = 0, 0
    for ev in events:
        t0, t1 = ass_time(ev["tin"]), ass_time(ev["tout"])
        if not t0 or not t1:
            skipped += 1
            continue
        # 先断行（此时只有【】标记，坐标系干净），再上强调色（ASS 标签可跨 \N 生效）
        text = break_lines(ev["text"], preset, ev["break_at"])
        text, kw = apply_keywords(text, preset)
        kw_total += kw
        style = ver2style.get(ev["ver"], "Main")
        out.append(f"Dialogue: 0,{t0},{t1},{style},,0,0,0,,{text}")

    return "\n".join(out) + "\n", skipped, kw_total


# ---------------------------------------------------------------------------
# ffmpeg 定位与烧录
# ---------------------------------------------------------------------------

def find_ffmpeg():
    for name in ("ffmpeg", "ffmpeg.exe"):
        exe = shutil.which(name)
        if exe:
            return exe
    env = os.environ.get("FFMPEG_BIN")
    if env and os.path.isfile(env):
        return env
    # 体系旁 ComfyUI 自带（按脚本相对位置推导，不写死盘符）
    guess = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "ComfyUI", "tools", "ffmpeg", "bin", "ffmpeg.exe")
    guess = os.path.normpath(guess)
    return guess if os.path.isfile(guess) else None


def probe_res(ffmpeg, video):
    stem = os.path.splitext(ffmpeg)[0]
    ffprobe = None
    for cand in (stem + ".exe", stem):
        if os.path.isfile(cand) and os.path.basename(cand).startswith("ffprobe"):
            ffprobe = cand
            break
    if not ffprobe:
        return None
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", video],
            capture_output=True, text=True, timeout=60)
        w, h = r.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except Exception:
        return None


def burn(ffmpeg, video, ass_path, out_path):
    # ass 滤镜对路径字符敏感：复制到临时 ASCII 路径再引用
    tmp_dir = tempfile.mkdtemp(prefix="subtitle_burn_")
    tmp_ass = os.path.join(tmp_dir, "sub.ass")
    shutil.copyfile(ass_path, tmp_ass)
    filt = "ass='" + tmp_ass.replace("\\", "/").replace(":", "\\:") + "'"
    cmd = [ffmpeg, "-y", "-i", video, "-vf", filt,
           "-c:v", "libx264", "-crf", "18", "-preset", "medium",
           "-c:a", "copy", out_path]
    print("[烧录]", " ".join(cmd[:6]), "...")
    r = subprocess.run(cmd)
    return r.returncode


# ---------------------------------------------------------------------------
# 自检（不需要视频文件、不调模型、1 秒内完成）
# ---------------------------------------------------------------------------

SELFTEST_MD = """# G6 字幕事件表

| 字幕ID | 剪辑镜头ID | 文本 | 说话人 | 时间线入点 | 时间线出点 | 断句/换行 | 样式版本 | 状态 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| SUB001 | S01 | 妈，我把你【备份】好了 | 女儿 | 00:00:01.000 | 00:00:03.500 | | v1 | 通过 | |
| SUB002 | S02 | 这句话很长很长很长很长很长很长需要被自动断成两行才行 | 旁白 | 00:00:04.000 | 00:00:07.000 | | v3 | 通过 | |
| SUB003 | S03 | 废弃条目不应出现 | | 00:00:08.000 | 00:00:09.000 | | v1 | 废弃 | |
"""


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  [OK] " if cond else "  [FAIL] ") + name)
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        md = os.path.join(td, "字幕事件表.md")
        open(md, "w", encoding="utf-8").write(SELFTEST_MD)
        events = parse_event_table(md)
        check("解析到 2 条有效事件（废弃被跳过）", events is not None and len(events) == 2)

        ass, skipped, kw = build_ass(events, "drama", (1080, 1920))
        check("含 Script Info / Styles / Events 三段",
              all(s in ass for s in ("[Script Info]", "[V4+ Styles]", "[Events]")))
        check("生成 2 条 Dialogue", ass.count("Dialogue:") == 2)
        check("drama 关键词转强调色", kw == 1 and "{\\1c&H00D7FF&}" in ass)
        check("长句被自动断行（含 \\N）", "\\N" in ass)
        check("drama 竖屏边距 280", ",280,1" in ass)
        check("时间码转厘秒", "0:00:01.00" in ass and "0:00:03.50" in ass)

        ass2, _, kw2 = build_ass(events, "movie", (1920, 1080))
        check("movie 忽略关键词（无强调色、无括号）",
              kw2 == 0 and "【" not in ass2 and "&H00D7FF&" not in ass2)
        check("movie 横屏小字号（44）", ",44," in ass2)

        bad = ass_time("不是时间码")
        check("非法时间码安全返回 None", bad is None)

    print("[自检]", "全部通过" if ok else "存在失败项")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def find_inputs(project):
    base = os.path.join(project, "06-成片")
    table = os.path.join(base, "字幕事件表.md")
    return table if os.path.isfile(table) else None, base


def main():
    ap = argparse.ArgumentParser(description="字幕事件表 → ASS → ffmpeg 硬烧")
    ap.add_argument("project", nargs="?", help="项目目录（含 06-成片/字幕事件表.md）")
    ap.add_argument("--preset", choices=["drama", "movie"], default="drama",
                    help="drama=信息流短剧大字强调（默认）；movie=电影感克制小字")
    ap.add_argument("--make-ass", action="store_true", help="只生成 subtitles.ass")
    ap.add_argument("--burn", action="store_true", help="生成 ASS 并硬烧进成片")
    ap.add_argument("--video", help="成片路径（默认取 06-成片/ 下最新 mp4）")
    ap.add_argument("--out", help="输出路径（默认 06-成片/成片_字幕版.mp4）")
    ap.add_argument("--res", help="画幅 如 1080x1920；--burn 时默认自动探测")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.project:
        ap.error("需要项目目录（或用 --selftest 自检）")
    if not (args.make_ass or args.burn):
        args.make_ass = True  # 默认只生成 ASS，不碰视频

    table, base = find_inputs(args.project)
    if not table:
        print(f"[错误] 未找到字幕事件表：{os.path.join(args.project, '06-成片', '字幕事件表.md')}",
              file=sys.stderr)
        return 2

    events = parse_event_table(table)
    if events is None:
        print("[错误] 字幕事件表缺少关键列（字幕ID/文本/入点/出点）", file=sys.stderr)
        return 2
    if not events:
        print("[错误] 事件表无有效字幕行（全部为空或已废弃）", file=sys.stderr)
        return 2

    pending = [e["id"] for e in events if e["status"] == "待审"]
    if pending:
        print(f"[警告] {len(pending)} 条状态为「待审」仍将纳入：{', '.join(pending[:5])}"
              + (" …" if len(pending) > 5 else ""))

    # 画幅
    res = None
    if args.res:
        m = re.match(r"(\d+)x(\d+)", args.res)
        if m:
            res = (int(m.group(1)), int(m.group(2)))
    ffmpeg = find_ffmpeg() if args.burn else None
    video = args.video
    if args.burn:
        if not ffmpeg:
            print("[错误] 找不到 ffmpeg（PATH / FFMPEG_BIN / 体系旁 ComfyUI 均无果）",
                  file=sys.stderr)
            return 2
        if not video:
            cands = [os.path.join(base, f) for f in os.listdir(base)
                     if f.lower().endswith(".mp4") and "字幕版" not in f]
            if not cands:
                print("[错误] 06-成片/ 下没有可烧录的 mp4，请用 --video 指定", file=sys.stderr)
                return 2
            video = max(cands, key=os.path.getmtime)
            print(f"[信息] 自动选择成片：{os.path.basename(video)}")
        if not res:
            res = probe_res(ffmpeg, video)
    if not res:
        res = (1080, 1920)
        print("[信息] 未指定画幅，按竖屏 1080x1920 生成（可用 --res 覆盖）")

    ass_text, skipped, kw = build_ass(events, args.preset, res)
    ass_path = os.path.join(base, "subtitles.ass")
    open(ass_path, "w", encoding="utf-8-sig").write(ass_text)
    print(f"[OK] ASS 已生成：{ass_path}")
    print(f"     预设 {args.preset} | 画幅 {res[0]}x{res[1]} | 字幕 {len(events)} 条"
          f" | 关键词强调 {kw} 处" + (f" | 时间码异常跳过 {skipped} 条" if skipped else ""))

    if args.burn:
        out = args.out or os.path.join(base, "成片_字幕版.mp4")
        rc = burn(ffmpeg, video, ass_path, out)
        if rc == 0:
            print(f"[OK] 烧录完成：{out}")
        else:
            print(f"[错误] ffmpeg 烧录失败（退出码 {rc}）", file=sys.stderr)
        return rc
    print("[提示] 这是中间产物；确认无误后加 --burn 硬烧进成片")
    return 0


if __name__ == "__main__":
    sys.exit(main())
