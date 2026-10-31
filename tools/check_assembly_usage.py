#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成片剪用闸：装配单有没有裁，成片帧差是不是还在翻页。

分镜表写了「缓推」不能证明成片在动。本闸查两件事：

  ① 剪辑装配单的画面行：使用时长（源出点−源入点）是否等于素材全长。
     可判定行达到 4 行，且未裁比例超过一半 → 退出码 1。
     素材全长优先读文件（ffprobe），否则读备注里的「素材全长 Ns」。
  ② 06-成片/ 下的成片 mp4：48×27 灰度、4fps 帧差。
     叙事片静止镜头占比超过 50%，或连续静止超过 5 镜 → 退出码 1。
     意象片的帧差静止不因此失败。

没有装配单、也没有成片时打印未评估，退出码 0。
有画面行但既没有文件也没有「素材全长」时，裁切部分打印未核验。
协议见 AGENTS.md「成片生成裁决」。未评估、未核验不得写成 G6 通过。

用法
    python tools/check_assembly_usage.py <项目目录>
    python tools/check_assembly_usage.py            # 扫全部在制项目
    python tools/check_assembly_usage.py --selftest

退出码：0 通过，或全库扫描时的未评估 / 1 未裁、成片帧差超线，或点名项目时未核验 / 2 用法或自检失败
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

from _film_gate_waivers import is_waived, load_waivers  # noqa: E402
from _film_type import read_film_type  # noqa: E402

GATE = "成片剪用-真片"
TOL = 0.25
MIN_JUDGED = 4
UNTRIMMED_MAX = 0.50
STATIC_RATIO_MAX = 0.50
MAX_STATIC_RUN = 5
STATIC_DIFF = 2.0
CUT_DIFF = 25.0
FRAME_W = 48
FRAME_H = 27

FAIL_MARK_RE = re.compile(r"##\s*失败裁决")
FULL_LEN_RE = re.compile(r"素材全长\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:s|秒)")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def parse_tc(text):
    """时间码或秒数 → 秒。空值返回 None。"""
    s = (text or "").strip()
    if not s or set(s) <= set("-—:"):
        return None
    m = re.fullmatch(r"(\d+):(\d+):(\d+(?:\.\d+)?)", s)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.fullmatch(r"(\d+):(\d+(?:\.\d+)?)", s)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:s|秒)?", s)
    if m:
        return float(m.group(1))
    return None


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_assembly(text):
    """读装配单里的 V1 画面行。返回 dict 列表。"""
    lines = text.splitlines()
    header_idx = None
    header = None
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        cells = _cells(line)
        if "源入点" in cells and "源出点" in cells and "轨道" in cells:
            header_idx = i
            header = cells
            break
    if header is None:
        return []
    idx = {name: n for n, name in enumerate(header)}

    def col(cells, name, default=""):
        n = idx.get(name)
        if n is None or n >= len(cells):
            return default
        return cells[n]

    rows = []
    for line in lines[header_idx + 1:]:
        if not line.strip().startswith("|"):
            break
        cells = _cells(line)
        if not cells or set("".join(cells)) <= set("-: "):
            continue
        track = col(cells, "轨道")
        sid = col(cells, "剪辑镜头ID") or col(cells, "镜号")
        if track.upper() != "V1":
            continue
        if not sid or sid in ("剪辑镜头ID", "镜号"):
            continue
        remark = col(cells, "备注")
        full = None
        m = FULL_LEN_RE.search(remark)
        if m:
            full = float(m.group(1))
        rows.append({
            "id": sid,
            "file": col(cells, "素材文件/版本"),
            "src_in": parse_tc(col(cells, "源入点")),
            "src_out": parse_tc(col(cells, "源出点")),
            "full_remark": full,
            "remark": remark,
        })
    return rows


def used_seconds(row):
    if row["src_in"] is None or row["src_out"] is None:
        return None
    dur = row["src_out"] - row["src_in"]
    if dur <= 0:
        return None
    return dur


def trim_verdict(pairs, tol=TOL, min_rows=MIN_JUDGED, limit=UNTRIMMED_MAX):
    """pairs: (used, full)。full 为空的行不参与判定。

    返回 (failed, ratio_or_None, n_bad, n_judged)。
    可判定行不足 min_rows 时不失败，避免把一条长镜头判成没剪。
    """
    judged = [(u, f) for u, f in pairs if u is not None and f is not None and f > 0]
    if not judged:
        return False, None, 0, 0
    bad = sum(1 for u, f in judged if abs(u - f) <= tol)
    ratio = bad / len(judged)
    failed = len(judged) >= min_rows and ratio > limit
    return failed, ratio, bad, len(judged)


def classify_shots(diffs, static_max=STATIC_DIFF, cut_min=CUT_DIFF):
    """相邻帧平均绝对差 → (静止占比, 最长静止连击, 镜头数)。

    差 ≥ cut_min 视为切点。切点之间的镜头，中位差 < static_max 视为静止。
    没有帧差时无法测量，返回 (None, None, 0)。
    """
    if not diffs:
        return None, None, 0
    shots = []
    cur = []
    for d in diffs:
        if d >= cut_min:
            if cur:
                shots.append(cur)
                cur = []
        else:
            cur.append(d)
    if cur:
        shots.append(cur)
    if not shots:
        return 0.0, 0, len(diffs)
    flags = []
    for sample in shots:
        ordered = sorted(sample)
        median = ordered[len(ordered) // 2]
        flags.append(median < static_max)
    run = cur_run = 0
    for flag in flags:
        if flag:
            cur_run += 1
            run = max(run, cur_run)
        else:
            cur_run = 0
    return sum(flags) / len(flags), run, len(flags)


def pixel_problems(ratio, run, n_shots, film_type):
    if film_type == "意象" or ratio is None:
        return []
    problems = []
    if n_shots and ratio > STATIC_RATIO_MAX:
        problems.append("成片帧差静止占比 {:.0%}（{} 镜里）超过 50%".format(ratio, n_shots))
    if run > MAX_STATIC_RUN:
        problems.append("成片帧差连续静止 {} 镜，超过 5 镜".format(run))
    return problems


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    env = os.environ.get("FFMPEG_BIN")
    if env and os.path.isfile(env):
        return env
    guess = os.path.normpath(os.path.join(
        HERE, "..", "..", "ComfyUI", "tools", "ffmpeg", "bin", "ffmpeg.exe"))
    return guess if os.path.isfile(guess) else None


def find_ffprobe(ffmpeg):
    if not ffmpeg:
        return None
    stem = os.path.splitext(ffmpeg)[0]
    folder = os.path.dirname(ffmpeg)
    base = os.path.basename(stem)
    for cand in (
        os.path.join(folder, "ffprobe.exe"),
        os.path.join(folder, "ffprobe"),
        stem.replace(base, "ffprobe") + ".exe",
        stem.replace(base, "ffprobe"),
    ):
        if os.path.isfile(cand):
            return cand
    return shutil.which("ffprobe")


def probe_duration(ffprobe, path):
    if not ffprobe or not path or not os.path.isfile(path):
        return None
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def resolve_media(project, raw):
    raw = (raw or "").strip().strip("`")
    if not raw or raw in ("-", "—"):
        return None
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    cand = os.path.normpath(os.path.join(project, raw.replace("\\", "/")))
    if os.path.isfile(cand):
        return cand
    return None


def find_final_videos(project):
    folder = os.path.join(project, "06-成片")
    if not os.path.isdir(folder):
        return []
    names = []
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith(".mp4") and not name.startswith("_"):
            names.append(os.path.join(folder, name))
    preferred = [p for p in names if "成片" in os.path.basename(p)]
    return preferred or names


def frame_diffs(ffmpeg, video):
    """抽出 4fps 小灰度帧，返回相邻帧平均绝对差。失败返回 (None, 原因)。"""
    cmd = [
        ffmpeg, "-v", "error", "-i", video,
        "-vf", "fps=4,scale={}:{},format=gray".format(FRAME_W, FRAME_H),
        "-f", "rawvideo", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "抽帧失败：{}".format(type(exc).__name__)
    if result.returncode != 0:
        err = (result.stderr or b"").decode("utf-8", "replace").strip()
        return None, err.splitlines()[-1] if err else "ffmpeg 抽帧失败"
    raw = result.stdout or b""
    stride = FRAME_W * FRAME_H
    if stride <= 0 or len(raw) < stride * 2:
        return None, "成片抽帧不足，无法测量"
    n = len(raw) // stride
    diffs = []
    prev = raw[:stride]
    for i in range(1, n):
        cur = raw[i * stride:(i + 1) * stride]
        acc = 0
        for a, b in zip(prev, cur):
            acc += abs(a - b)
        diffs.append(acc / stride)
        prev = cur
    return diffs, ""


def find_assembly(project):
    path = os.path.join(project, "06-成片", "剪辑装配单.md")
    return path if os.path.isfile(path) else None


def _is_archived(project):
    summary = os.path.join(project, "项目状态摘要.md")
    if not os.path.isfile(summary):
        return False
    try:
        with open(summary, encoding="utf-8", errors="replace") as handle:
            return bool(FAIL_MARK_RE.search(handle.read()))
    except OSError:
        return False


def discover_projects():
    container = os.path.join(SYSTEM_ROOT, "00-视频项目")
    if not os.path.isdir(container):
        return []
    return [
        os.path.join(container, name)
        for name in sorted(os.listdir(container))
        if os.path.isdir(os.path.join(container, name)) and not name.startswith("_")
    ]


def evaluate_project(project, ffmpeg=None, ffprobe=None):
    """返回 (status, messages)。status: pass / fail / unevaluated / unverified。"""
    assembly = find_assembly(project)
    videos = find_final_videos(project)
    if not assembly and not videos:
        return "unevaluated", ["无剪辑装配单，也无成片 mp4"]

    messages = []
    failed = False
    unverified = False
    film_type, _source = read_film_type(project)

    if assembly:
        with open(assembly, encoding="utf-8", errors="replace") as handle:
            rows = parse_assembly(handle.read())
        if not rows:
            unverified = True
            messages.append("装配单没有可判定的 V1 行")
        else:
            pairs = []
            for row in rows:
                used = used_seconds(row)
                full = None
                media = resolve_media(project, row["file"])
                if media:
                    full = probe_duration(ffprobe, media)
                if full is None:
                    full = row["full_remark"]
                pairs.append((used, full))
            trim_failed, ratio, n_bad, n_judged = trim_verdict(pairs)
            if n_judged == 0:
                unverified = True
                messages.append("V1 行缺少素材全长（文件或备注「素材全长 Ns」），裁切未核验")
            elif trim_failed:
                failed = True
                messages.append("未裁 {}/{} = {:.0%}，超过一半".format(n_bad, n_judged, ratio))
            else:
                messages.append("裁切 {}/{} 行未用满全长，未裁 {:.0%}".format(
                    n_judged - n_bad, n_judged, ratio))
    else:
        unverified = True
        messages.append("无剪辑装配单，裁切未核验")

    if videos:
        if not ffmpeg:
            failed = True
            messages.append("已有成片但找不到 ffmpeg，无法做帧差")
        else:
            for video in videos:
                diffs, err = frame_diffs(ffmpeg, video)
                if diffs is None:
                    failed = True
                    messages.append("{}：{}".format(os.path.basename(video), err))
                    continue
                ratio, run, n_shots = classify_shots(diffs)
                problems = pixel_problems(ratio, run, n_shots, film_type)
                if problems:
                    failed = True
                    messages.extend("{}：{}".format(os.path.basename(video), item) for item in problems)
                else:
                    shown = "豁免" if film_type == "意象" else "{:.0%} / 连击 {}".format(ratio or 0, run or 0)
                    messages.append("{} 帧差 {}".format(os.path.basename(video), shown))
    if failed:
        return "fail", messages
    if unverified:
        return "unverified", messages
    return "pass", messages


def audit_all():
    waivers, werrors = load_waivers()
    for err in werrors:
        print("⚠ " + err)
    projects = discover_projects()
    if not projects:
        print("[未评估] 未发现在制项目，本闸没有可判对象")
        return 0
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe(ffmpeg)
    active_bad = []
    n_pass = n_waived = n_unevaluated = 0
    for project in projects:
        name = os.path.basename(project)
        status, messages = evaluate_project(project, ffmpeg, ffprobe)
        if status == "unevaluated":
            n_unevaluated += 1
            print("  {:<28s} [未评估] {}".format(name, messages[0] if messages else ""))
            continue
        if status == "unverified":
            n_unevaluated += 1
            print("  {:<28s} [未核验] {}".format(name, "；".join(messages)))
            continue
        if status == "fail":
            if _is_archived(project):
                print("  {:<28s} 归档失败（不阻断） {}".format(name, "；".join(messages)))
                continue
            if is_waived(waivers, name, GATE):
                n_waived += 1
                print("  {:<28s} WAIVED {}".format(name, "；".join(messages)))
                continue
            active_bad.append((name, messages))
            print("  {:<28s} ✗ {}".format(name, "；".join(messages)))
            continue
        n_pass += 1
        print("  {:<28s} ✓ {}".format(name, "；".join(messages)))
    if active_bad:
        print("\n  修法：同场用审核末帧接下一镜；装配单写下源入点/源出点，短刀从生成段里裁。")
        print("  叙事片成片帧差静止占比须 ≤50%，连续静止须 ≤5 镜。")
        return 1
    if n_pass == 0 and n_waived == 0:
        print("[未评估] 没有可判的成片或装配单")
        return 0
    print("✓ 在制成片剪用检查通过（通过 {} / 未评估 {} / WAIVED {}）".format(
        n_pass, n_unevaluated, n_waived))
    return 0


def _run_selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        if cond:
            print("[selftest][通过] " + name)
        else:
            print("[selftest][失败] " + name)
            ok = False

    healthy = [
        (2.0, 5.17),
        (1.2, 5.17),
        (1.5, 5.17),
        (2.4, 5.17),
    ]
    failed, ratio, n_bad, n_judged = trim_verdict(healthy)
    check("四行都裁过应通过", (not failed) and n_bad == 0 and n_judged == 4)

    sick = [(5.17, 5.17)] * 4
    failed, ratio, n_bad, n_judged = trim_verdict(sick)
    check("四行都用满全长应失败", failed and n_bad == 4 and abs(ratio - 1) < 1e-9)

    half = [(5.17, 5.17), (5.17, 5.17), (2.0, 5.17), (2.0, 5.17)]
    failed, ratio, _bad, _n = trim_verdict(half)
    check("恰好一半未裁不叫多数", not failed and abs(ratio - 0.5) < 1e-9)

    failed, _ratio, _bad, n_judged = trim_verdict([(5.17, 5.17)])
    check("不足 4 行不把一条长镜头判成没剪", (not failed) and n_judged == 1)

    failed, ratio, _bad, n_judged = trim_verdict([(None, None), (1.0, None)])
    check("没有全长则未核验", ratio is None and n_judged == 0 and not failed)

    text = """
| 轨道 | 剪辑镜头ID | 素材文件/版本 | 源入点 | 源出点 | 备注 |
|---|---|---|---|---|---|
| V1 | S01 | a.mp4 | 00:00:00.000 | 00:00:02.000 | 素材全长 5.17s |
| V2 | S01b | b.mp4 | 00:00:00.000 | 00:00:05.170 | 素材全长 5.17s |
| V1 | S02 | c.mp4 | 1.0s | 3.5s | 素材全长 5.17秒 |
"""
    rows = parse_assembly(text)
    check("只收 V1 且读出两条", len(rows) == 2 and rows[0]["id"] == "S01")
    check("时间码与备注全长", abs(used_seconds(rows[0]) - 2) < 1e-6 and rows[1]["full_remark"] == 5.17)

    ratio, run, n_shots = classify_shots([0.2] * 12)
    check("缓慢几乎不动算一个静止镜头", ratio == 1 and run == 1 and n_shots == 1)
    problems = pixel_problems(ratio, run, n_shots, "叙事")
    check("叙事片单镜头静止占比超线", bool(problems))
    check("意象片帧差静止不失败", pixel_problems(ratio, run, n_shots, "意象") == [])

    diffs = []
    for _ in range(6):
        diffs.extend([0.2, 0.2, 40])
    ratio, run, n_shots = classify_shots(diffs)
    check("六段静止以切点分开", n_shots == 6 and run == 6 and ratio == 1)
    check("连击超过 5 镜失败", bool(pixel_problems(ratio, run, n_shots, "叙事")))

    mixed = [8, 8, 8, 40, 0.2, 0.2, 40, 8, 8]
    ratio, run, n_shots = classify_shots(mixed)
    check("运动镜头不算静止连击", run <= 1 and ratio is not None and ratio < 0.5)

    check("没有帧差不假装测过", classify_shots([]) == (None, None, 0))

    if not ok:
        return 2
    print("[selftest] 全部通过")
    return 0


def main():
    ap = argparse.ArgumentParser(description="成片剪用闸：装配单裁切与成片帧差")
    ap.add_argument("project", nargs="?", default=None, help="项目目录")
    ap.add_argument("--selftest", action="store_true", help="内置样例自检")
    args = ap.parse_args()
    if args.selftest:
        return _run_selftest()
    if not args.project:
        return audit_all()
    if not os.path.isdir(args.project):
        print("[错误] 不是项目目录：{}".format(args.project), file=sys.stderr)
        return 2
    ffmpeg = find_ffmpeg()
    status, messages = evaluate_project(args.project, ffmpeg, find_ffprobe(ffmpeg))
    label = {"pass": "通过", "fail": "失败", "unevaluated": "未评估", "unverified": "未核验"}[status]
    print("[{}] {}".format(label, "；".join(messages)))
    # 点名项目时，未核验不得当成通过。全库扫描仍把未核验记为未评估，避免空项目阻断。
    if status == "fail" or status == "unverified":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
