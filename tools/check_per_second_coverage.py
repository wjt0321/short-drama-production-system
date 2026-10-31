#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐秒覆盖闸 · 每秒指令五要素 —— A1 的落地实现。

**为什么需要**
对标 MiniMax 官方 skill 的镜头表：人家的指令拆到「0–1s / 1–2s / …」逐秒块，
每秒必填五要素（动作姿态表情含预备·接触·超调·跟随 / 镜头运动 / 空间位置 /
音频线索含显式 silent / 交给下一秒的状态），且不许留时间空隙。
我们的旧分镜表全是镜头级：一镜 6 秒只有一个「主体动作」格子，
模型拿到的是"这镜讲什么"不是"每一秒身体做什么"，只能用平均动作填满时长——
这就是"机器人在原地划拉两下"的直接成因。

**查什么**（对象是 `03-分镜/分镜表.md`）
  ① 主表每个剪辑镜头 ID 在「逐秒指令」节必须有对应 `### Sxx` 块
  ② 秒块时间轴必须连续覆盖 [0, 镜长]：首行从 0 开始、行与行首尾相接、
     末行结束于镜长；亚秒节拍（`2.0–2.5s`）允许，但不得留空隙或重叠
  ③ 每秒五要素必填：动作/姿态/表情、镜头运动、空间位置、音频线索
     （有意静默写 `silent`，算填写）、交给下一秒的状态
  ④ 镜长读主表「时长」列（`4s`/`4 秒`/`4`）或「时间线时码」区间

**边界**
  · 只有镜头级主表、没有逐秒节的旧项目 → 全部判缺，退出码 1（这就是病根）；
  · 已归档失败项目不阻断（与项目合规闸同一语义）。

**用法**
    python tools/check_per_second_coverage.py <项目目录>
    python tools/check_per_second_coverage.py            # 扫全部在制项目
    python tools/check_per_second_coverage.py --selftest

**退出码**：0 全绿 / 1 有缺秒缺项 / 2 用法或自检失败
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

FAIL_MARK_RE = re.compile(r"##\s*失败裁决")

from _film_gate_waivers import load_waivers, is_waived, tally_line
from _film_type import read_film_type

GATE = "逐秒覆盖-真片"

# 秒块行：` | 0–1s | 动作 | 镜头 | 空间 | 音频 | 交给 | `
SEC_RANGE_RE = re.compile(
    r"^\|\s*(\d+(?:\.\d+)?)\s*[–—~-]\s*(\d+(?:\.\d+)?)\s*s?\s*\|", re.I)
# 五要素列的表头关键词（顺序即列序）
COL_KEYS = ("动作", "镜头", "空间", "音频", "交给")
# D6：纯占位词不算"填了"。
# 旧版只判 `c.strip()` 非空，于是每格填「同上」「同前」「无」「—」的 19 镜表
# 五要素一项不缺、全绿放行——占位词没有可指认的物理量，等于没填。
PLACEHOLDER_CELLS = {
    "无", "无动作", "略", "略过", "待定", "待补", "暂缺", "空",
    "—", "-", "－", "–", "——", "……", "...", "…", "/", "n/a", "na",
    "tbd", "todo", "?", "？", "静止", "hold",
}
# 音频列例外：显式写「无声/silent」是合法的第二要素（AGENTS.md A7 允许无源声道），
# 但「动作/镜头/空间/交给」列写它仍是占位。
AUDIO_BLANK_OK = {"silent", "silent.", "静音", "无声", "无声。", "无音效", "环境底噪"}
# 「指前」词：同一镜内该列前面已经写过可指认内容时，「同上」是合法的连续性标注
# （空间/交接状态本来就常有延续）；前面没写过就是纯占位。
POINTER_CELLS = {"同上", "同上秒", "同前", "如前", "如上一秒", "如前一秒", "同上镜"}
# 黑场秒：这一秒画面本来就是纯黑，空间位置写「无」是事实而不是占位。
BLACK_FRAME_RE = re.compile(r"纯黑|全黑|黑场|黑屏|黑帧|无画面")
PUNCT_ONLY_RE = re.compile(r"^[\s\-－–—~〜_*·。，、,.;；:：／/|]+$")

SHOTSEC_HDR_RE = re.compile(r"^\s*#{2,4}\s*\*{0,2}(S\d{1,3}|G\d{1,3})\*{0,2}"
                            r"(?:[（(]\s*[^)）]*[)）])?\s*$", re.I)
MAIN_ID_RE = re.compile(r"^\*{0,2}(?:S|G)\d{1,3}\*{0,2}$")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_placeholder(cell, idx):
    """判断五要素单元格是否只有占位符（idx = COL_KEYS 下标）。"""
    c = (cell or "").strip()
    if not c:
        return True
    low = c.lower()
    if idx == 3 and low.rstrip("。.") in AUDIO_BLANK_OK:
        return False   # 音频列显式「无声/silent」是合法填写
    if PUNCT_ONLY_RE.match(c):
        return True
    normalized = re.sub(r"[\s。.!！?？]", "", low)
    generic_still = {"静止", "不动", "静止不动", "保持静止", "保持不动", "保持静止不动", "维持现状"}
    if idx == 0 and low.startswith("hold:"):
        detail = low.split(":", 1)[1].strip()
        normalized = re.sub(r"[\s。.!！?？]", "", detail)
        return len(detail) < 4 or normalized in generic_still or detail.rstrip("。.?？") in PLACEHOLDER_CELLS
    if normalized in generic_still:
        return True
    return low.rstrip("。.?？") in PLACEHOLDER_CELLS


def find_storyboard(proj):
    for rel in ("03-分镜/分镜表.md", "03-分镜/分镜表.txt",
                "02-分镜与镜头/分镜表.md"):
        fp = os.path.join(proj, *rel.split("/"))
        if os.path.isfile(fp):
            return fp
    return None


def parse_main_table(txt):
    """从主表读 {镜头ID: 期望镜长秒}。镜长解析不到时值为 None。

    用结构定位（连续 | 行 + 首列是镜头 ID），与切点均质度闸同一思路，
    避免被表前信息表误伤。
    """
    tables, tbl = [], None
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if tbl is None:
                tbl = []
                tables.append(tbl)
            tbl.append(cells)
        else:
            tbl = None

    dur_re1 = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s|秒)\b", re.I)
    dur_re2 = re.compile(r"(\d+(?:\.\d+)?)\s*[–—~-]\s*(\d+(?:\.\d+)?)")
    dur_re3 = re.compile(r"^\d+(?:\.\d+)?$")

    best = {}
    for t in tables:
        if len(t) < 2:
            continue
        header = t[0]
        id_col = dur_col = tc_col = None
        for i, h in enumerate(header):
            if MAIN_ID_RE.match(h.strip("* ")) or h.strip("* ") in ("剪辑镜头ID",):
                if id_col is None:
                    id_col = i
            if "时长" in h and dur_col is None:
                dur_col = i
            if ("时码" in h or "时间线" in h) and tc_col is None:
                tc_col = i
        if id_col is None:
            continue
        for row in t[1:]:
            if id_col >= len(row):
                continue
            sid = row[id_col].strip().strip("*")
            if not MAIN_ID_RE.match(sid):
                continue
            if all(set(c) <= set("-: ") for c in row):
                continue
            d = None
            if dur_col is not None and dur_col < len(row):
                cell = row[dur_col]
                m = dur_re1.search(cell)
                if m:
                    d = _f(m.group(1))
                elif dur_re3.match(cell.strip()):
                    d = _f(cell.strip())
            if d is None and tc_col is not None and tc_col < len(row):
                m = dur_re2.search(row[tc_col])
                if m:
                    a, b = _f(m.group(1)), _f(m.group(2))
                    if a is not None and b is not None and 0.2 <= b - a <= 120:
                        d = round(b - a, 4)
            if 0.2 <= (d or 0) <= 120:
                best[sid.upper()] = d
            elif sid.upper() not in best:
                best[sid.upper()] = None
    return best


def parse_second_blocks(txt):
    """解析 `### Sxx` 节内的逐秒表。返回 {镜头ID: {"rows": [(a,b,[cell...])],
    "ncols": int}}。只认表头含 动作/镜头/空间/音频/交给 关键词的表。"""
    blocks = {}
    cur_id, header, rows = None, None, None
    for line in txt.splitlines():
        m = SHOTSEC_HDR_RE.match(line)
        if m:
            if cur_id and rows is not None:
                blocks[cur_id] = {"rows": rows, "header": header}
            cur_id = m.group(1).upper()
            header, rows = None, None
            continue
        if cur_id is None:
            continue
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(set(c) <= set("-: ") and c for c in cells):
            continue  # 分隔行
        joined = "".join(cells)
        if header is None and all(k in joined for k in COL_KEYS):
            header = cells
            rows = []
            continue
        if rows is not None:
            rm = SEC_RANGE_RE.match(s)
            if rm:
                a, b = _f(rm.group(1)), _f(rm.group(2))
                body = cells[1:]
                rows.append((a, b, body))
    if cur_id and rows is not None:
        blocks[cur_id] = {"rows": rows, "header": header}
    return blocks


def analyse(proj):
    """返回 (problems, facts)。"""
    problems, facts = [], {}
    fp = find_storyboard(proj)
    if not fp:
        facts["分镜表"] = None
        problems.append("未找到 03-分镜/分镜表.md —— 无法做逐秒覆盖检查")
        return problems, facts
    with open(fp, encoding="utf-8", errors="replace") as f:
        txt = f.read()
    facts["分镜表"] = os.path.relpath(fp, proj)
    film_type, film_source = read_film_type(proj)
    facts["片型"] = f"{film_type}（{film_source}）"
    facts["静默语义"] = "silent/无声是明确设计"

    shots = parse_main_table(txt)
    blocks = parse_second_blocks(txt)
    facts["主镜数"] = len(shots)
    facts["逐秒块数"] = len(blocks)

    if not shots:
        problems.append("主表未解析到任何剪辑镜头 ID —— 表结构不符合模板")
        return problems, facts

    n_missing_block, n_gap, n_short, n_elem = 0, 0, 0, 0
    for sid, expect in shots.items():
        blk = blocks.get(sid)
        if blk is None or not blk["rows"]:
            n_missing_block += 1
            problems.append("① {} 缺逐秒指令块 —— 每镜必填 0–1s/1–2s/… 五要素表"
                            .format(sid))
            continue
        rows = sorted(blk["rows"], key=lambda r: (r[0] if r[0] is not None else 1e9))
        # 时间轴连续覆盖
        cursor = 0.0
        gap_here = False
        for a, b, body in rows:
            if a is None or b is None:
                continue
            if a > cursor + 0.011:
                n_gap += 1
                problems.append(
                    "② {} 时间轴有空隙：{:.2f}s 结束后直接跳到 {:.2f}s —— "
                    "每一秒都必须被覆盖，亚秒节拍允许但不得留空档"
                    .format(sid, cursor, a))
                gap_here = True
                break
            if b > a:
                cursor = b
        if gap_here:
            continue
        if expect is not None and abs(cursor - expect) > 0.11:
            n_short += 1
            problems.append(
                "③ {} 秒块覆盖 {:.2f}s ≠ 主表镜长 {:.2f}s —— 覆盖必须恰好等于镜长"
                .format(sid, cursor, expect))
        # 五要素必填（D6）：空 **和** 纯占位词都不算填写；逐行检查，不因第一处
        # 违规就 break（旧版 break 让同一镜后面几秒缺项全部隐身）。
        bad_rows = []
        anchored = [False] * len(COL_KEYS)   # 该列在本镜此前是否已写过可指认内容
        for a, b, body in rows:
            cells = list(body[:len(COL_KEYS)])
            cells += [""] * (len(COL_KEYS) - len(cells))
            holes = []
            for i, c in enumerate(cells):
                norm = (c or "").strip().lower().rstrip("。.?？")
                if norm in POINTER_CELLS and anchored[i]:
                    continue          # 「同上」且前面写过 → 连续性标注，合法
                if (i == 2 and BLACK_FRAME_RE.search(cells[0] or "")
                        and norm in {"无", "无空间", "—", "-"}):
                    continue          # 黑场秒：动作列已写明纯黑，空间写「无」是事实
                if _is_placeholder(c, i):
                    holes.append(COL_KEYS[i])
                else:
                    anchored[i] = True
            if holes:
                bad_rows.append((a, b, holes))
        if bad_rows:
            n_elem += 1
            facts.setdefault("五要素缺项镜头", []).append(sid)
            a0, b0, holes0 = bad_rows[0]
            more = ("；另有 {} 秒块同样缺项".format(len(bad_rows) - 1)
                    if len(bad_rows) > 1 else "")
            problems.append(
                "④ {} 有 {} 个秒块五要素不完整 —— 首个：{:.1f}–{:.1f}s 缺 {}"
                "（「动作/镜头/空间/音频/交给」每项必写可指认内容，"
                "音频无源写 silent；「同上/同前/无/—」不算填写）{}"
                .format(sid, len(bad_rows), a0 or 0, b0 or 0,
                        "/".join(holes0), more))

    facts["缺块镜数"] = n_missing_block
    facts["时间轴空隙镜数"] = n_gap
    facts["覆盖不足镜数"] = n_short
    facts["五要素缺失镜数"] = n_elem
    return problems, facts


def _is_archived(proj):
    summary = os.path.join(proj, "项目状态摘要.md")
    if not os.path.isfile(summary):
        return False
    try:
        with open(summary, encoding="utf-8", errors="replace") as f:
            return bool(FAIL_MARK_RE.search(f.read()))
    except OSError:
        return False


def discover_projects():
    out = []
    container = os.path.join(SYSTEM_ROOT, "00-视频项目")
    if os.path.isdir(container):
        out.extend(os.path.join(container, n) for n in sorted(os.listdir(container))
                   if os.path.isdir(os.path.join(container, n))
                   and not n.startswith("_"))
    return out


def audit_all():
    waivers, werrors = load_waivers()
    for e in werrors:
        print("⚠ " + e)
    all_projs = discover_projects()
    projs = [p for p in all_projs if find_storyboard(p)]
    for p in all_projs:
        if not find_storyboard(p):
            print("  {:<28s} [未评估] 无分镜表".format(os.path.basename(p)))
    if not projs:
        print("[未评估] 未发现在制项目（无 03-分镜/分镜表.md），本闸没有可判对象")
        return 0
    active_bad, arch_bad, waived = [], [], []
    for p in projs:
        problems, facts = analyse(p)
        name = os.path.basename(p)
        arch = _is_archived(p)
        wvd = bool(problems) and is_waived(waivers, name, GATE)
        if wvd:
            tag = "WAIVED（{} 条，已登记豁免）".format(len(problems))
        else:
            tag = "✗ {} 条".format(len(problems)) if problems else "✓"
        print("  {:<28s} 镜数={:<3d} 逐秒块={:<3d} {}".format(
            name, facts.get("主镜数", 0), facts.get("逐秒块数", 0), tag))
        if problems:
            if wvd:
                waived.append(name)
            elif arch:
                arch_bad.append((name, problems))
            else:
                active_bad.append((name, problems))
    for name, problems in active_bad:
        print("\n⚠ {}：".format(name))
        for x in problems[:8]:
            print("   ✗ " + x[:110])
        if len(problems) > 8:
            print("   … 另有 {} 条".format(len(problems) - 8))
    if arch_bad:
        print("\n· 归档失败项目（已记录不阻断）：")
        for name, problems in arch_bad:
            print("  {}：{} 条".format(name, len(problems)))
    if waived:
        print("\n· 已豁免（WAIVED，登记于 tools/_film_gate_waivers.yaml）：{}"
              .format("、".join(waived)))
    if active_bad:
        print("\n  修法：分镜表下方按模板「逐秒指令」节为每镜填 0–1s/1–2s/… 五要素表；"
              "参考 模板/短剧项目模板/03-分镜/分镜表.md。")
        n_uneval = len(arch_bad)
        ok_n = len(projs) - len(waived) - n_uneval - len(active_bad)
        print(tally_line(ok_n, len(waived), n_uneval, len(active_bad)))
        return 1
    ok_n = len(projs) - len(waived)
    n_uneval = len(arch_bad)
    if waived or n_uneval:
        print("⚠ " + tally_line(ok_n, len(waived), n_uneval) +
              "　—— 有豁免/未评估，不算全绿")
        return 0
    print("✓ 在制项目逐秒覆盖全部合格（{} 个项目）".format(ok_n))
    print(tally_line(ok_n, 0, 0))
    return 0


def selftest():
    ok = True
    import tempfile

    GOOD_BLOCK = (
        "### S01（0.0–4.0s）\n\n"
        "| 秒 | 动作/姿态/表情 | 镜头运动 | 空间位置 | 音频线索 | 交给下一秒的状态 |\n"
        "|---|---|---|---|---|---|\n"
        "| 0–1s | 抬手预备 | 固定 | 人在画左，门在画右 | silent | 手抬至肩高 |\n"
        "| 1–2s | 手接触门把，握住 | 推进 | 同上 | 门轴轻响 | 手握紧门把 |\n"
        "| 2–3s | 超调：门被拉过头 | 推进 | 门缝透光 | 门轴响加大 | 门半开 |\n"
        "| 3–4s | 停顿，跟随喘息 | 固定 | 人退半步 | 喘息声 | 门半开，人未定 |\n"
    )

    def _write(td, body):
        os.makedirs(os.path.join(td, "03-分镜"), exist_ok=True)
        with open(os.path.join(td, "03-分镜", "分镜表.md"), "w",
                  encoding="utf-8") as f:
            f.write(body)

    MAIN = ("| 剪辑镜头ID | 时长 |\n|---|---|\n| S01 | 4s |\n| S02 | 2s |\n")

    # 反例 1：S02 缺逐秒块 → 必抓
    with tempfile.TemporaryDirectory() as td:
        _write(td, MAIN + "\n## 逐秒指令\n\n" + GOOD_BLOCK)
        problems, facts = analyse(td)
        if not any("S02" in p and "①" in p for p in problems):
            print("[自检失败] 缺逐秒块应报 ①，实际：{}".format(problems))
            ok = False
        else:
            print("[自检通过] 缺逐秒块被抓（S02 无块）")

    # 反例 2：时间轴空隙（1s 后直接 2s）→ 必抓
    with tempfile.TemporaryDirectory() as td:
        bad = GOOD_BLOCK.replace("| 1–2s |", "| 2–3s |")
        _write(td, MAIN.replace("| S02 | 2s |\n", "") + "\n## 逐秒指令\n\n" + bad)
        problems, facts = analyse(td)
        if not any("②" in p or "③" in p for p in problems):
            print("[自检失败] 时间轴空隙应报 ②/③，实际：{}".format(problems))
            ok = False
        else:
            print("[自检通过] 时间轴空隙被抓")

    # 反例 3：五要素缺项（音频列空）→ 必抓
    with tempfile.TemporaryDirectory() as td:
        bad = GOOD_BLOCK.replace("| 0–1s | 抬手预备 | 固定 | 人在画左，门在画右 | silent |",
                                 "| 0–1s | 抬手预备 | 固定 | 人在画左，门在画右 |  |")
        _write(td, MAIN.replace("| S02 | 2s |\n", "") + "\n## 逐秒指令\n\n" + bad)
        problems, facts = analyse(td)
        if not any("④" in p for p in problems):
            print("[自检失败] 五要素缺项应报 ④，实际：{}".format(problems))
            ok = False
        else:
            print("[自检通过] 五要素缺项被抓（音频列空）")

    # 正例：两镜都合规 → 放行
    with tempfile.TemporaryDirectory() as td:
        good2 = GOOD_BLOCK + (
            "### S02（0.0–2.0s）\n\n"
            "| 秒 | 动作/姿态/表情 | 镜头运动 | 空间位置 | 音频线索 | 交给下一秒的状态 |\n"
            "|---|---|---|---|---|---|\n"
            "| 0–1s | 她定住 | 固定 | 人画左 | silent | 未定 |\n"
            "| 1–2s | 她吸气 | 拉远 | 人画左，门画右 | 吸气声 | 未定 |\n")
        _write(td, MAIN + "\n## 逐秒指令\n\n" + good2)
        problems, facts = analyse(td)
        if problems:
            print("[自检失败] 合规样例被误报：{}".format(problems))
            ok = False
        else:
            print("[自检通过] 合规样例（两镜全覆盖）未误报")

    # 正例 2：亚秒节拍连续（2.0–2.5s 接 2.5–4s）→ 放行
    with tempfile.TemporaryDirectory() as td:
        sub = ("### S01（0.0–4.0s）\n\n"
               "| 秒 | 动作/姿态/表情 | 镜头运动 | 空间位置 | 音频线索 | 交给下一秒的状态 |\n"
               "|---|---|---|---|---|---|\n"
               "| 0–2s | 逼近 | 推进 | 人画左 | silent | 近 |\n"
               "| 2.0–2.5s | 接触门把 | 推进 | 手画右 | 门轴响 | 握住 |\n"
               "| 2.5–4s | 拉开 | 固定 | 门画右 | 门响 | 门开 |\n")
        _write(td, MAIN.replace("| S02 | 2s |\n", "") + "\n## 逐秒指令\n\n" + sub)
        problems, facts = analyse(td)
        if problems:
            print("[自检失败] 亚秒节拍连续被误报：{}".format(problems))
            ok = False
        else:
            print("[自检通过] 亚秒节拍（无空隙）放行")
    # 反例 4（D6）：五要素全是占位词（同上/同前/无/silent/—）→ 必抓
    with tempfile.TemporaryDirectory() as td:
        ph = ("### S01（0.0–4.0s）\n\n"
              "| 秒 | 动作/姿态/表情 | 镜头运动 | 空间位置 | 音频线索 | 交给下一秒的状态 |\n"
              "|---|---|---|---|---|---|\n"
              "| 0–1s | 同上 | 同前 | 无 | silent | — |\n"
              "| 1–2s | 同上 | 同前 | 无 | silent | — |\n")
        _write(td, MAIN.replace("| S02 | 2s |\n", "") + "\n## 逐秒指令\n\n" + ph)
        problems, facts = analyse(td)
        if not any("④" in p for p in problems):
            print("[自检失败] 占位词（同上/同前/无/—）应报 ④，实际：{}".format(problems))
            ok = False
        elif "另有 1 秒块" not in " ".join(problems):
            print("[自检失败] ④ 只报了第一处缺项，后续秒块被 break 吞掉：{}"
                  .format(problems))
            ok = False
        else:
            print("[自检通过] 占位词不算填写，且同一镜的多个缺项秒块都被数到")

    # 正例 3（D6 反向校验）：黑场秒动作列写明「纯黑」→ 空间写「无」不算缺项
    with tempfile.TemporaryDirectory() as td:
        blk = ("### S01（0.0–2.0s）\n\n"
               "| 秒 | 动作/姿态/表情 | 镜头运动 | 空间位置 | 音频线索 | 交给下一秒的状态 |\n"
               "|---|---|---|---|---|---|\n"
               "| 0–1s | 纯黑，无内容 | 固定 | 无 | silent | 纯黑 |\n"
               "| 1–2s | 画面中出现一粒微光 | 固定 | 光点=正中偏下 | silent | 光点悬停 |\n")
        _write(td, MAIN.replace("| S02 | 2s |\n", "").replace(
            "| S01 | 4s |", "| S01 | 2s |") + "\n## 逐秒指令\n\n" + blk)
        problems, facts = analyse(td)
        if problems:
            print("[自检失败] 黑场秒的空间「无」被误判为占位：{}".format(problems))
            ok = False
        else:
            print("[自检通过] 黑场秒（动作列写「纯黑」）的空间「无」不误报")

    if _is_placeholder("hold: 视线停在画右门口，肩膀不动", 0):
        print("[自检失败] 具体 hold 留白被误判为占位")
        ok = False
    elif not _is_placeholder("hold", 0) or not _is_placeholder("静止", 0):
        print("[自检失败] 空 hold 或泛化静止不应算有效动作")
        ok = False
    else:
        print("[自检通过] 具体 hold 放行、空 hold 与泛化静止拦截")
    for text in ("保持静止", "静止不动", "保持不动", "维持现状", "hold: 保持静止"):
        if not _is_placeholder(text, 0):
            print("[自检失败] 泛化静止短语被放行：{}".format(text))
            ok = False
    with tempfile.TemporaryDirectory() as td:
        held = GOOD_BLOCK.replace("停顿，跟随喘息", "hold: 视线停在画右门口，肩膀不动")
        _write(td, MAIN.replace("| S02 | 2s |\n", "") + "\n## 逐秒指令\n\n" + held)
        problems, _ = analyse(td)
        if problems:
            print("[自检失败] 完整分镜中的具体 hold 被误报：{}".format(problems))
            ok = False

    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(description="逐秒覆盖闸：每镜每秒五要素必填、时间轴无空隙")
    ap.add_argument("project", nargs="?", help="项目目录（省略则扫全部在制项目）")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.project or a.all:
        return audit_all()
    if not os.path.isdir(a.project):
        print("目录不存在：{}".format(a.project))
        return 2
    problems, facts = analyse(a.project)
    for k, v in facts.items():
        print("  {}：{}".format(k, v))
    for p in problems[:20]:
        print("  ✗ " + p)
    if len(problems) > 20:
        print("  … 另有 {} 条".format(len(problems) - 20))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
