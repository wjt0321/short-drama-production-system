#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""切点均质度闸 · 均质度与生成内多刀 —— 抓「一片节拍器」。

**为什么需要**
`技术资产_通用.md` §五（质检闸的元规则）早就写下要「抓标准差不足」，
但 `tools/` 下从未实现。而旧的「产物自洽」闸检查的是
「同一镜在三份文件里说法相等」——它对「13 镜全是 5.17s」
**永远返回绿色**，因为零方差是最自洽的状态（该闸已删）。

实测代价：某旧片 13 个切点间隔 mean=min=max=5.167s、std=0.0000，
成片被判「拼接上去的视频有如 PPT，难以入眼」；
而同机器的另一部已完成片在 12 秒生成段内切出 1.04–5.46s 的 18 刀，就能看。

**查什么**（对象是 `03-分镜/分镜表.md` 与 `04-镜头/prompts/`）
  ① 切点间隔标准差：std 过小 → 节拍器（一片一个频率）
  ② 长短刀并存：全片既要有 < 1.5s 的快刀，也要有 > 3s 的长刀
  ③ 生成内多刀：一份提示词必须出现 ≥2 个**不同**的 Shot 编号
     且带 `At 00:mm.mmm` 切点声明
     ⚠️ 只数 `[Shot N]` 的出现次数会误判 —— 单镜模板会反复写 `[Shot 1]`
  ④ 扩展名无关：提示词可能是 `.md` 也可能是 `.txt`，两者都要扫
     （按 `.md` 过滤会漏掉全部 `.txt` 提示词，造成假阴性）

**用法**
    python tools/check_shot_duration_variance.py <项目目录>
    python tools/check_shot_duration_variance.py <项目目录> --json
    python tools/check_shot_duration_variance.py --selftest

**退出码**：0 全绿 / 1 有问题 / 2 用法或自检失败
"""
import argparse
import io
import json
import os
import re
import sys

# ---- 阈值（可由项目 07-工具 覆盖）------------------------------------------
STD_WARN = 0.20        # 切点间隔标准差低于此值 -> 节拍器告警（秒）
FAST_MAX = 1.50        # 至少一把刀要短于此值（秒）
SLOW_MIN = 3.00        # 至少一把刀要长于此值（秒）
MIN_CUTS = 4           # 刀数少于此值不做方差判定（短片无意义）
KNIFE_BANDS = {"短刀": (0.0, 2.0), "常规": (2.0, 4.0), "长刀": (4.0, 8.0)}
KNIFE_BAND_SLACK = 0.5

SHOT_RE = re.compile(r"\[Shot\s+(\d+)\]", re.I)
CUT_RE = re.compile(r"[Aa]t\s+00:(\d{2})\.(\d{3})")
# 归档判定：复用 check_project_conformance 的语义，
# 状态摘要含「## 失败裁决」+「归档」字样 = 归档失败项目，不阻断。
FAIL_MARK_RE = re.compile(r"##\s*失败裁决")

from _film_gate_waivers import load_waivers, is_waived, tally_line
from _film_type import read_film_type

# D5c：等距切点口径不在这里另写一份，直接取 check_shot_structure 的实现
# （此前两闸各说各话：结构闸 89% 等距 → EXIT=1，时长闸同输入 → EXIT=0）
import check_shot_structure as _struct

GATE = "切点均质度-真片"
# D8：刀型三档（模板已改三档）——短刀 ≤2s / 常规 2–4s / 长刀 4–8s。
# 「普通」保留为旧模板遗留值（仍是未知值），「中刀/中性」等不认。
KNIFE_WHITELIST = ("短刀", "常规", "长刀")
# 分镜表里时长有多种写法，都要认：
#   `0.00–5.17` / `5.17-10.34`  —— 时间码区间（最可靠，减出来就是时长）
#   `5.17s` / `5.17 秒` / `时长 5.17`
#   `124 帧` @ fps           —— 帧数换算
RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[–—~-]\s*(\d+(?:\.\d+)?)")
DUR_SEC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s|秒)\b")
DUR_FRAME_RE = re.compile(r"(\d+)\s*帧")
FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps", re.I)
# 单镜段摄影执行标记：起点/过程/结果 + 摄影机路径动词。
# 多刀/多镜生成段必须用 [Shot N] + At 00:mm.mmm；
# 单镜段允许只有一个 Shot，但必须显式写出「起点→过程→结果」三段式，
# 否则模型只能输出「镜头从 A 看到 A」= 静帧。
SHOT_PATH_RE = re.compile(
    r"(?:起点|过程|过程与终点|过程->终点|过程→终点|"
    r"起始状态|结束状态|动作目标|运镜[起终]点|运镜过程|运镜终点|"
    r"dolly|track(?:ing)?|pan|tilt|crane|orbit|steadicam|"
    r"push[- ]?in|pull[- ]?out|zoom[- ]?(?:in|out)|"
    r"缓推|缓拉|推近|拉远|跟拍|环绕|横摇|纵摇|升降|起幅|落幅|运动路径|"
    r"camera\s+(?:moves|starts|ends|push|pulls|tracks))",
    re.I,
)
# 表头里出现过这些词才算「时长/时间码」列，避免把 0.00–0.50 类的
# 无关区间（如渐变时长、景深范围）误当镜头时长
TIMEHDR_RE = re.compile(r"时间|时长|时段|时间码|区间")
PROMPT_EXT = {".md", ".txt"}


def _f(v):
    """容错转浮点。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_archived(proj):
    """项目是否已归档为失败案例（活跃项目才阻断）。"""
    summary = os.path.join(proj, "项目状态摘要.md")
    if not os.path.isfile(summary):
        return False
    try:
        with open(summary, encoding="utf-8", errors="replace") as f:
            body = f.read()
    except OSError:
        return False
    return bool(FAIL_MARK_RE.search(body)) and "归档" in body


def parse_cuts_from_prompts(proj):
    """扫全部提示词，返回 [(文件名, 不同Shot编号数, 切点秒列表, 文件全文)]。

    发现策略（按优先级回退，每条只算一次）：
      1) 固定子目录：04-镜头/prompts、04-镜头/提示词、prompts
      2) 内容发现：递归扫 04-镜头/ 下 .md/.txt，含 `[Shot N]` 才采纳
         （解决 H3_提示词/、prompts_v01/、s01.txt 等旁路目录漏扫）

    第 4 元素（全文）供单镜段「起点→过程→结果」标记检查使用；
    若调用方只关心前 3 项，用 `_, distinct, cuts, _ = prompts[i]`。
    """
    out = []
    seen = set()

    def _add(path, fn):
        if path in seen:
            return
        seen.add(path)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                t = f.read()
        except OSError:
            return
        if not SHOT_RE.search(t):
            return  # 不是提示词（无 Shot 编号）—— 内容过滤
        distinct = len({int(x) for x in SHOT_RE.findall(t)})
        cuts = [int(a) + int(b) / 1000.0 for a, b in CUT_RE.findall(t)]
        out.append((fn, distinct, sorted(set(cuts)), t))

    # 1) 固定目录
    for sub in ("04-镜头/prompts", "04-镜头/提示词", "prompts"):
        d = os.path.join(proj, *sub.split("/"))
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if os.path.splitext(fn)[1].lower() not in PROMPT_EXT:
                    continue
                _add(os.path.join(d, fn), fn)

    # 2) 内容发现：递归扫整个 04-镜头/（覆盖 H3_提示词/、s01.txt 等）
    lens_root = os.path.join(proj, "04-镜头")
    if os.path.isdir(lens_root):
        import glob as _glob
        for fp in sorted(_glob.glob(os.path.join(lens_root, "**", "*"),
                                    recursive=True)):
            if not os.path.isfile(fp):
                continue
            if os.path.splitext(fp)[1].lower() not in PROMPT_EXT:
                continue
            _add(fp, os.path.relpath(fp, proj))
    return out


def parse_durations_from_storyboard(proj):
    """从分镜表读逐镜时长（秒）。

    优先级：时间码区间（减出时长） > 显式秒数 > 帧数/fps 换算。
    只统计表头含「时间/时长」列的那些行，避免把无关区间当成镜长。
    """
    for rel in ("03-分镜/分镜表.md", "03-分镜/分镜表.txt",
                "02-分镜与镜头/分镜表.md"):
        fp = os.path.join(proj, *rel.split("/"))
        if not os.path.isfile(fp):
            continue
        with open(fp, encoding="utf-8", errors="replace") as f:
            txt = f.read()
        fps_m = FPS_RE.search(txt)
        fps = _f(fps_m.group(1)) if fps_m else 24.0

        # ---- 用「结构」而不是「关键词」定位分镜表 ----
        # 踩过的坑（三片各中一个）：
        #   ① 旧结构表前有信息表 `| 总时长 | 48.00 秒 |`，含「时长」二字；
        #   ② 旧结构表还有 `| 生成段 | 4 段，每段 12.00 秒 |`，能凑出 4 个 12.0s；
        #   ③ 旧结构表/另一部旧片的表格行**带前导缩进**，且表头叫「时段」不是「时长」。
        # 关键词定位怎么做都会漏一个。改用结构判据：
        #   一个 markdown 表格 = 连续以 `|` 开头的行；
        #   它的【数据行】应当以镜头 ID 开头（**S01** / S01 / G001 / 1）；
        #   在合格表格里，挑「能解析出最多镜长」的那一列。
        SHOTID = re.compile(r"^\*{0,2}(?:G|S)?\d{1,3}\*{0,2}$", re.I)

        # 先切出所有 markdown 表格
        tables = []
        tbl = None
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

        def _extract(cells):
            """从一个候选列里抽取镜长（秒）。"""
            got = []
            for cell in cells:
                v = None
                rm = RANGE_RE.search(cell)
                if rm:
                    a, b = _f(rm.group(1)), _f(rm.group(2))
                    if a is not None and b is not None and 0.2 <= b - a <= 30.0:
                        v = round(b - a, 4)
                if v is None and len(cell) <= 24:
                    m = DUR_SEC_RE.search(cell)
                    if m:
                        x = _f(m.group(1))
                        if x and 0.2 <= x <= 30.0:
                            v = x
                if v is None:
                    fm = DUR_FRAME_RE.search(cell)
                    if fm and fps:
                        x = _f(fm.group(1))
                        if x and 0.2 <= x / fps <= 30.0:
                            v = round(x / fps, 4)
                if v is not None:
                    got.append(v)
            return got

        best = []
        for t in tables:
            if len(t) < 3:
                continue
            header = t[0]
            # 哪些列是「镜头 ID 列」：该列在数据行里大量命中 SHOTID
            body = [r for r in t[1:]
                    if not all(set(c) <= set("-: ") for c in r)]
            if not body:
                continue
            id_cols = []
            for i in range(len(header)):
                hits = sum(1 for r in body
                           if i < len(r) and SHOTID.match(r[i]))
                if hits >= max(3, len(body) * 0.6):
                    id_cols.append(i)
            if not id_cols:
                continue          # 这个表没有镜头 ID 列 → 不是分镜表
            # 在这张表里试每一列，取能解析出最多镜长的
            for i in range(len(header)):
                got = _extract([r[i] for r in body if i < len(r)])
                if len(got) > len(best):
                    best = got

        if best:
            return best, fps, rel
    return [], 24.0, None


def analyse(proj):
    """返回 (problems, facts)。"""
    problems, facts = [], {}
    durs, fps, src = parse_durations_from_storyboard(proj)
    prompts = parse_cuts_from_prompts(proj)
    film_type, film_type_source = read_film_type(proj)

    facts["分镜表"] = src
    facts["片型"] = f"{film_type}（{film_type_source}）"
    facts["fps"] = fps
    facts["镜数"] = len(durs)

    # ---- ①② 镜间时长方差 ----
    if len(durs) >= MIN_CUTS:
        mn, mx = min(durs), max(durs)
        mean = sum(durs) / len(durs)
        var = sum((d - mean) ** 2 for d in durs) / len(durs)
        std = var ** 0.5
        facts["镜长秒"] = {"min": round(mn, 4), "max": round(mx, 4),
                          "mean": round(mean, 4), "std": round(std, 4)}
        if film_type == "意象":
            facts["片型路由"] = "意象片：不以商业短剧均质度/长短刀配额判定"
        else:
            if std < STD_WARN:
                problems.append(
                    "① 镜间时长均质：std={:.4f}s (< {:.2f}s)，"
                    "min={:.3f} max={:.3f} —— 全片一个节奏，会像 PPT。"
                    "参考：分镜工作流.md「默认5秒、平均分配和固定镜头数量"
                    "都不能代替判断」".format(std, STD_WARN, mn, mx))
            if mn >= FAST_MAX:
                problems.append(
                    "② 无短促句：最短的刀也有 {:.3f}s（分布参考 ≤{:.2f}s）—— "
                    "全片没有一句「短促」的话".format(mn, FAST_MAX))
            if mx <= SLOW_MIN:
                problems.append(
                    "② 无停留句：最长的刀也只有 {:.3f}s（分布参考 >{:.2f}s）—— "
                    "全片没有一句「停留」的话".format(mx, SLOW_MIN))
            fr = _struct.flat_ratio(durs)
            facts["等距切点占比"] = round(fr, 4)
            if fr > _struct.FLAT_PAIR_MAX:
                problems.append(
                    "② 切点等距：相邻镜时长比 <{:.1f} 的占 {:.0%}（> {:.0%} 上限）—— "
                    "时长是按信息量均分的，不是按动作切的。"
                    "参考：check_shot_structure.py 同口径判定".format(
                        _struct.FLAT_PAIR_RATIO, fr, _struct.FLAT_PAIR_MAX))

    # ---- ③ 生成内多刀 / 单镜段 ----
    # 规则（与成片质检表对齐）：
    #   · 多刀/多镜生成段 → 必须有 ≥2 个不同 Shot 编号 + At 切点声明
    #   · 单镜段 → 允许只写 1 个 Shot，但必须显式声明「起点→过程→结果」，
    #     任何摄影机运动动词（推/拉/摇/移/跟/缓推/缓拉/跟拍/环绕/dolly/track…）
    #     或起点/过程/终点 模板字段都属于达标标记
    # 这条规则替代旧的「每条提示词都强制 ≥2 个 Shot」——
    # 后者会把单镜段静帧写成「提示词违规」。
    if prompts:
        best = max((d for _, d, _, _ in prompts), default=0)
        tot_cuts = sum(len(c) for _, _, c, _ in prompts)
        facts["提示词数"] = len(prompts)
        facts["单文件最大不同Shot编号"] = best
        facts["切点声明总数"] = tot_cuts
        if best >= 2:
            # 多刀/多镜段：要求 At 切点声明
            if tot_cuts == 0:
                problems.append(
                    "③ 多镜段有 ≥2 个 Shot 编号但无 `At 00:mm.mmm` 切点声明 —— "
                    "只写编号模型不知道何时切，需补时间戳")
        else:
            # 单镜段：每条提示词都必须有 起点→过程→结果 标记
            missing = [fn for fn, d, _, t in prompts
                       if not SHOT_PATH_RE.search(t)]
            if missing:
                problems.append(
                    "③ 单镜段缺「起点→过程→结果」摄影路径声明：{} —— "
                    "单镜段必须显式给出摄影机起幅→过程→落幅（如「缓推」「"
                    "dolly in」「运镜起点/过程/终点」等），否则模型输出静帧。"
                    "多镜段则需 ≥2 个 Shot 编号 + `At 00:mm.mmm` 切点。"
                    "参考：旧片 G003 用 6 处 At 切点（1.4–1.6s）"
                    .format("、".join(sorted(set(missing))[:5])))
    else:
        problems.append("③ 未找到提示词文件（已查 04-镜头/prompts，含 .md/.txt）")

    # ---- ④ 刀型列：必须存在，且三档里至少用出两种 ----
    # 用户的规则是「重要的长一点，不重要的短一点」。这条规则要能落地，
    # 分镜表就必须逐刀回答「这一刀重不重要」——`刀型` 列就是那个答案。
    # D8：三档 = 短刀(≤2s) / 常规(2–4s) / 长刀(4–8s)。
    # 没有这一列 = 没人做过判断；整列一个值 = 假填空，等同于没做判断。
    # 白名单外的值（如「普通」「中刀」「中性」）也算未知：说明用了旧模板。
    knife = parse_knife_col(proj)
    facts["刀型列"] = knife["found"]
    if knife["found"]:
        facts["刀型分布"] = knife["counts"]
        if knife["unknowns"]:
            facts["刀型未知"] = knife["unknowns"]
            unk_preview = "、".join(sorted(knife["unknowns"])[:5])
            problems.append(
                "⑤ 刀型含白名单外值（{} 行）：{} —— "
                "白名单仅「{}」。参考：分镜表模板 03-分镜/分镜表.md"
                .format(knife["unknown_total"], unk_preview,
                        "/".join(KNIFE_WHITELIST)))
        if knife["total"] >= MIN_CUTS:
            if len(knife["counts"]) < 2:
                only = next(iter(knife["counts"]), "?")
                problems.append(
                    "④ 刀型单一：{} 行全是「{}」—— 说明没逐刀判断轻重。"
                    "规则：有新信息/情绪重 → 长刀；过渡/过场 → 短刀"
                    .format(knife["total"], only))
    else:
        problems.append(
            "④ 分镜表缺 `刀型` 列（也没找到 `本刀新信息`）—— "
            "「重要的长、不重要的短」这条规则没有落点，"
            "缺了它时长必然回到平均分配。"
            "参考：模板/短剧项目模板/03-分镜/分镜表.md")

    return problems, facts


def parse_knife_col(proj):
    """从分镜表里读出 `刀型` 列的取值分布。

    返回 {"found": bool, "counts": {值: 行数}, "total": int,
          "unknowns": {值: 行数}, "unknown_total": int}
    """
    import glob as _glob
    hits = _glob.glob(os.path.join(proj, "03-分镜", "分镜表.md"))
    if not hits:
        hits = _glob.glob(os.path.join(proj, "**", "分镜表.md"), recursive=True)
    if not hits:
        return {"found": False, "counts": {}, "total": 0,
                "unknowns": {}, "unknown_total": 0}

    counts, total = {}, 0
    unknowns, unknown_total = {}, 0
    found = False
    knife_col = -1
    with open(hits[0], encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells:
            continue
        # 表头：定位刀型列序号
        if not found:
            for i, c in enumerate(cells):
                if "刀型" in c:
                    found = True
                    knife_col = i
                    break
            continue
        if knife_col < 0 or knife_col >= len(cells):
            continue
        # 跳过 markdown 分隔行（如 `|---|---|`）
        if all(set(c) <= set("-: ") and c for c in cells):
            continue
        v = cells[knife_col]
        if not v or set(v) <= set("-: "):
            continue  # 留空 / 仅分隔符也不算未知
        # 跳过明显是子表表头的列名标签（如「| 刀型 | 镜数 | 镜号 |」里的「刀型」）
        if v in {"刀型", "镜数", "镜号", "镜头", "时长", "镜头时长"}:
            continue
        if v in KNIFE_WHITELIST:
            counts[v] = counts.get(v, 0) + 1
            total += 1
        else:
            unknowns[v] = unknowns.get(v, 0) + 1
            unknown_total += 1
    return {"found": found, "counts": counts, "total": total,
            "unknowns": unknowns, "unknown_total": unknown_total}


def selftest():
    """反自检：故意造一个「全 5.17s + 单刀」的样例，闸门必须报警。

    样例刻意复刻真实分镜表的三个坑：
      ① 表格行**前导缩进**（"  | S01 | 0.00–5.17 |"）
      ② 表头用「**时段**」而非「时长」，值是**时间码区间**而非秒数
      ③ 分镜表**前面还有一个信息小表**含「总时长」（旧结构表就是这种写法）
    这三点曾分别让本闸对真片读出「镜数=0」的假阴性。
    """
    import tempfile

    def write_storyboard(td, durs_or_ranges, with_info_table=True,
                         knife=None):
        os.makedirs(os.path.join(td, "03-分镜"), exist_ok=True)
        head = ""
        if with_info_table:
            head = ("| 项 | 值 |\n|---|---|\n| 总时长 | 48.00 秒 |\n"
                    "| 生成段 | 4 段 |\n\n")
        if knife:
            rows = ["| 镜号 | 时段 | 刀型 |", "|---|---|---|"]
        else:
            rows = ["| 镜号 | 时段 | 景别 |", "|---|---|---|"]
        t = 0.0
        for i, d in enumerate(durs_or_ranges, 1):
            if knife:
                rows.append("  | **S{:02d}** | {:.2f}–{:.2f} | {} |".format(
                    i, t, t + d, knife[(i - 1) % len(knife)]))
            else:
                rows.append("  | **S{:02d}** | {:.2f}–{:.2f} | 中景 |".format(
                    i, t, t + d))
            t += d
        with open(os.path.join(td, "03-分镜", "分镜表.md"), "w", encoding="utf-8") as f:
            f.write("> 每镜 124 帧 / 5.17s @24fps\n" + head + "\n".join(rows))

    ok = True
    # ---- 反例 1：13 镜全 5.17s + 提示词只声明一刀 -> 必须报警 ----
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "04-镜头", "prompts"))
        write_storyboard(td, [5.17] * 13)
        with open(os.path.join(td, "04-镜头", "prompts", "S01.txt"), "w", encoding="utf-8") as f:
            f.write("[Shot 1] a still shot\n[Shot 1] template scaffolding\n")
        problems, facts = analyse(td)
        assert facts["镜数"] == 13, "缩进/时段表头解析失败：镜数={}".format(
            facts["镜数"])
        hit = [p for p in problems if p[0] in ("①", "②", "③")]
        if len(hit) < 3:
            print("[自检失败] 均质样例应触发 ①②③，实际 {} 条：".format(len(hit)))
            for p in problems:
                print("   -", p)
            ok = False
        else:
            print("[自检通过] 均质样例被抓住：镜数=13 std={} 编号={}".format(
                facts["镜长秒"]["std"], facts["单文件最大不同Shot编号"]))

    # ---- 反例 2：有长短刀 + 多刀 + 刀型列 -> 必须放行 ----
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "04-镜头", "prompts"))
        write_storyboard(td, [2.0, 0.8, 4.0, 1.2, 3.5, 0.9, 2.8],
                         knife=["长刀", "短刀"])
        with open(os.path.join(td, "04-镜头", "prompts", "G001.md"), "w", encoding="utf-8") as f:
            f.write("[Shot 1] a\n[Shot 2] At 00:01.600, cut to b\n"
                    "[Shot 3] At 00:03.200, cut to c\n")
        problems, facts = analyse(td)
        if problems:
            print("[自检失败] 正常样例被误报：")
            for p in problems:
                print("   -", p)
            ok = False
        else:
            print("[自检通过] 正常样例（长短刀 std={} + 多刀 + 刀型列）未误报".format(
                facts["镜长秒"]["std"]))

    # ---- 反例 4：切片型列 -> 必须报警（规则没有落点）----
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "04-镜头", "prompts"))
        write_storyboard(td, [2.0, 0.8, 4.0, 1.2, 3.5, 0.9, 2.8], knife=None)
        with open(os.path.join(td, "04-镜头", "prompts", "G001.md"), "w", encoding="utf-8") as f:
            f.write("[Shot 1] a\n[Shot 2] At 00:01.600, cut to b\n")
        problems, facts = analyse(td)
        if not [p for p in problems if p.startswith("④")]:
            print("[自检失败] 缺刀型列应报 ④，实际：")
            for p in problems:
                print("   -", p)
            ok = False
        else:
            print("[自检通过] 缺刀型列被抓住（时长再漂亮也判为没做判断）")

    # ---- 反例 5：刀型整列一个值 -> 必须报警（假填空）----
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "04-镜头", "prompts"))
        write_storyboard(td, [2.0, 0.8, 4.0, 1.2, 3.5, 0.9, 2.8],
                         knife=["长刀"])
        with open(os.path.join(td, "04-镜头", "prompts", "G001.md"), "w", encoding="utf-8") as f:
            f.write("[Shot 1] a\n[Shot 2] At 00:01.600, cut to b\n")
        problems, facts = analyse(td)
        if not [p for p in problems if p.startswith("④")]:
            print("[自检失败] 刀型整列同值应报 ④，实际：")
            for p in problems:
                print("   -", p)
            ok = False
        else:
            print("[自检通过] 刀型整列同值被抓住（全填长刀 = 等于没判断）")

    # ---- 反例 3：.md 与 .txt 提示词都必须扫到 ----
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "04-镜头", "prompts"))
        write_storyboard(td, [2.0, 0.8, 4.0, 1.2, 3.5, 0.9, 2.8])
        with open(os.path.join(td, "04-镜头", "prompts", "S01_ref2va.txt"), "w", encoding="utf-8") as f:
            f.write("[Shot 1] a\n[Shot 2] At 00:01.600, cut to b\n")
        problems, facts = analyse(td)
        if facts.get("切点声明总数", 0) != 1:
            print("[自检失败] .txt 提示词未被扫描（切点={}）".format(
                facts.get("切点声明总数")))
            ok = False
        else:
            print("[自检通过] .txt 提示词被正确扫描（按 .md 过滤会假阴性）")
    # ---- 反例 6：等距节拍器（每刀比上一刀长 45%）-> 必须报警 ----
    # std 反而很大（1.6s 量级），① 均质判定抓不到；长短刀两档也都齐（有 1.4s 的
    # 短刀、5.8s 的长刀），旧版 ② 同样抓不到。这类"匀速加速阶梯"是排比句式的
    # 节奏，结构闸按「相邻镜时长比 <1.5」判 100% 等距超标，本闸必须同口径。
    # 顺带覆盖 D8：三档白名单里「常规」不再是未知值（⑤ 不该出现）。
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "04-镜头", "prompts"))
        write_storyboard(td, [1.4, 2.0, 2.9, 4.1, 5.8],
                         knife=["短刀", "常规", "长刀", "常规", "短刀"])
        with open(os.path.join(td, "04-镜头", "prompts", "G001.md"), "w", encoding="utf-8") as f:
            f.write("[Shot 1] a\n[Shot 2] At 00:01.400, cut to b\n")
        problems, facts = analyse(td)
        hit = [p for p in problems if p.startswith("② 切点等距")]
        unk = [p for p in problems if p.startswith("⑤")]
        if not hit:
            print("[自检失败] 等距节拍器（相邻比 1.45 全片）未被 ② 抓住，实际：")
            for p in problems:
                print("   -", p)
            ok = False
        elif unk:
            print("[自检失败] 三档白名单误判：「常规」被当成未知值 —— {}".format(unk[0]))
            ok = False
        else:
            print("[自检通过] 等距节拍器被抓住（等距占比={}，std={} 反而很大）"
                  .format(facts.get("等距切点占比"), facts["镜长秒"]["std"]))
    return 0 if ok else 2


def discover_projects():
    """自动找出视频项目容器内项目，并兼容根目录旧项目。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = []
    try:
        # 新约定：所有新项目都放在根目录的 00-视频项目/ 下；只扫这一层，
        # 避免把项目内部的素材子目录误认成项目。
        container = os.path.join(root, "00-视频项目")
        if os.path.isdir(container):
            candidates.extend(
                os.path.join(container, n)
                for n in sorted(os.listdir(container))
                if os.path.isdir(os.path.join(container, n))
            )
        # 兼容已有项目：迁移前仍可放在体系根目录。
        candidates.extend(
            os.path.join(root, n)
            for n in sorted(os.listdir(root))
            if os.path.isdir(os.path.join(root, n))
            and (n.endswith("项目") or n.startswith("《"))
        )
    except OSError:
        pass

    out = []
    seen = set()
    for p in candidates:
        if p in seen or os.path.abspath(p) == os.path.abspath(container):
            continue
        seen.add(p)
        if not os.path.basename(p).startswith("_"):
            out.append(p)
    return out


def audit_all(as_json=False):
    """无参数模式：扫全部在制项目。

    **为什么无参数要真扫真片，而不是打印帮助**：
    `run_all_checks.py` 调用每道闸时**不传任何参数**，只看退出码。
    如果无参数就 return 0（或打印帮助），这道闸在总闸里等于**永远绿**——
    又一个「假绿」。所以无参数必须真的去扫项目并如实返回结论。

    **退出码语义**：
      0 = 扫过，活跃项目全合规（或仅归档失败项目异常，已记录）
      1 = 扫过，活跃项目有不合格项（总闸登记为 skippable，不挡别人回归）
    区分依据：项目状态摘要含「## 失败裁决 + 归档」= 归档失败，不阻断。
    """
    waivers, werrors = load_waivers()
    if not as_json:
        for e in werrors:
            print("⚠ " + e)
    projs = discover_projects()
    if not projs:
        print("[未评估] 未发现在制项目（无 03-分镜/分镜表.md），本闸没有可判对象")
        return 0
    active_bad, arch_bad, waived = [], [], []
    for p in projs:
        name = os.path.basename(p)
        if not os.path.isfile(os.path.join(p, "03-分镜", "分镜表.md")):
            print("  {:<28s} [未评估] 无分镜表".format(name))
            continue
        problems, facts = analyse(p)
        std = (facts.get("镜长秒") or {}).get("std")
        arch = _is_archived(p)
        wvd = bool(problems) and not arch and is_waived(waivers, name, GATE)
        if problems:
            if wvd:
                waived.append((name, problems))
            elif arch:
                arch_bad.append((name, problems))
            else:
                active_bad.append((name, problems))
        if not as_json:
            if wvd:
                tag = "WAIVED（{} 条，已登记豁免）".format(len(problems))
            else:
                tag = "✗ {} 条".format(len(problems)) if problems else "✓"
            arch_mark = " [归档]" if arch else ""
            print("  {:<28s} 镜数={:<3s} std={} {}{}".format(
                name, str(facts.get("镜数")), std, tag, arch_mark))
    if active_bad:
        print("")
        print("⚠ 以下活跃项目切点节奏不合格：")
        for name, problems in active_bad:
            print("  {}：".format(name))
            for x in problems:
                print("     ✗ " + x[:100])
    if arch_bad:
        print("")
        print("· 归档失败项目（已记录不阻断）：")
        for name, problems in arch_bad:
            print("  {}：".format(name))
            for x in problems:
                print("     ✗ " + x[:100])
    if waived and not as_json:
        print("")
        print("· 已豁免（WAIVED，登记于 tools/_film_gate_waivers.yaml）：{}"
              .format("、".join(n for n, _ in waived)))
    if active_bad or arch_bad:
        print("")
        print("  修法看 命令速查.md 切点均质度闸一节；核心两条：")
        print("    ① 刀长要有长有短（别整片一个数）")
        print("    ② 提示词里用 [Shot 2] At 00:03.500 写生成内多刀")
        # 汇总口径统一（D4）：未评估 = 扫到但读不出镜头的项目（归档失败计入其中）
        n_uneval = len(arch_bad)
        ok_n = len(projs) - len(waived) - len(arch_bad) - len(active_bad)
        print(tally_line(ok_n, len(waived), n_uneval, len(active_bad)))
        return 1 if active_bad else 0
    ok_n = len(projs) - len(waived)
    n_uneval = len(projs) - ok_n - len(waived)
    if waived or n_uneval:
        print("⚠ " + tally_line(ok_n, len(waived), n_uneval) +
              "　—— 有豁免/未评估，不算全绿")
        return 0
    print("✓ {} 个在制项目切点节奏全部合格".format(ok_n))
    print(tally_line(ok_n, 0, 0))
    return 0


def main():
    ap = argparse.ArgumentParser(description="切点均质度与生成内多刀闸")
    ap.add_argument("project", nargs="?", help="项目目录（省略则扫全部在制项目）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--all", action="store_true", help="显式扫全部在制项目")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.project or a.all:
        return audit_all(as_json=a.json)
    if not os.path.isdir(a.project):
        print("目录不存在：{}".format(a.project))
        return 2

    problems, facts = analyse(a.project)
    if a.json:
        print(json.dumps({"problems": problems, "facts": facts},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print("切点均质度闸 · 切点均质度与生成内多刀")
        print("项目：{}".format(a.project))
        print("=" * 62)
        for k, v in facts.items():
            print("  {}：{}".format(k, v))
        print("-" * 62)
        if problems:
            for p in problems:
                print("  ✗ " + p)
        else:
            print("  ✓ 切点有长短、提示词下发多刀 —— 通过")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
