#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""风格锁闸 · 全局视觉风格锁必须真注入每条提示词。

**为什么需要**
`导演视觉圣经.md` §一·补（2026-10-12）立了规则：基线卡压成 ≤300 字「风格锁
字符串」，逐条提示词原文追加。规则落地前，圣经是要读的文档、不是要注入的
字符串——"老周和画面里的人明显不可能成立"却能判过。品位靠记忆，不靠闸门。
本闸就是那个闸门。

**查什么**（2026-10-13 起分模式）
  · 从项目 `00-立项/风格提案.md` 抽取 ```style-lock 块（机器可抽取的格式）；
  · 发现项目内全部提示词文件：路径含 `prompts`/`提示词` 目录、或文件名含
    `提示词`/`prompt` 的 .md/.txt（00-立项/ 除外——那是决策文档，锁就存在那里）；
  · 有提示词但无 style-lock 块 → FAIL（A5 欠账，真红不报绿）；
  · 锁超长（>300 字，不计空白）→ FAIL；
  · **文生模式**（默认，从严）：提示词（空白归一化后）不含锁字符串原文 → FAIL；
  · **图生/多参考模式**（头部 `模式：X`/`mode: X` 声明或含 I2VA/Ref2VA/@图片 等标记）：
    含锁原文 → 过；否则必须含**风格锚句**（锁的第一句），缺锚句 → FAIL。
    依据：MiniMax/Seedance 官方均要求图生模式下风格与外观由参考图承担，
    文本不复述画面（见 `04-视频生成/平台提示词契约.md` §2.4）。

**边界**
  · 匹配语义：文生模式是"原文追加"（一字不改，空白归一化后子串匹配）；
    图生/多参考模式是"锚句在、锁全文在风格提案.md"；
  · 无模式声明也无参考图标记的文件一律按文生从严；
  · 无提示词且无锁 → 视为未启用，跳过（不拦还没起步的项目）；
  · 已归档失败项目不阻断（与情绪词闸同一语义）。

**用法**
    python tools/check_style_lock.py <项目目录>
    python tools/check_style_lock.py            # 扫全部在制项目
    python tools/check_style_lock.py --selftest

**退出码**：0 全绿 / 1 缺注入或欠账 / 2 用法或自检失败
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

from _film_gate_waivers import load_waivers, is_waived, tally_line

GATE = "风格锁-真片"

MAX_LOCK_CHARS = 300        # 工作单 A5：≤300 字（D1 口径：只数汉字/字母/数字）
MIN_LOCK_CHARS = 30         # 少于这个长度基本是糊弄，按无效锁处理
MIN_ANCHOR_CHARS = 10       # 锚句（锁的第一句）低于此长度视为不可校验，退回全文匹配
PROMPT_EXT = {".md", ".txt"}
LOCK_FENCE_RE = re.compile(
    r"```style-lock\s*\n(.*?)```", re.S | re.I)

# 图生/多参考模式判定：显式声明优先（`模式：X` 或 `mode: X`，与
# `04-视频生成/平台提示词契约.md` §五 模板的 # 模式声明 块同一来源），
# 官方语法标记兜底。声明为文生类模式时不再看标记（声明优先）。
MODE_DECLARE_RE = re.compile(
    r"(?:模式|mode)\s*[:：]\s*"
    r"(T2VA?|I2VA?|FL2VA?|L2VA?|Ref2VA|图生|多参考|首尾帧|末帧|参考生(?:视频)?|"
    r"运动参考|视频修改|图像编辑|文生图?|多镜原生)",
    re.I)
REF_MODES = {"i2v", "i2va", "fl2v", "fl2va", "l2v", "l2va", "ref2va",
             "图生", "多参考", "首尾帧", "末帧", "参考生", "参考生视频",
             "运动参考", "视频修改", "图像编辑"}
TEXT_MODES = {"t2v", "t2va", "文生", "文生图", "多镜原生"}
REF_MODE_MARKERS = [
    re.compile(r"For the target video, at 0\.00 seconds", re.I),  # H3 I2VA 官方首行
    re.compile(r"<Picture\s*\d", re.I),                           # H3 Ref2VA 引用标签
    re.compile(r"subject_definitions", re.I),                     # H3 Ref2VA 六段式首字段
    re.compile(r"@图片\s*\d|@Image\s*\d", re.I),                  # Seedance 多参考引用
]


def norm(s):
    """空白归一化：换行/多空格压成单空格。锁和提示词两侧同规则。"""
    return re.sub(r"\s+", " ", s).strip()


def anchor_of(lock):
    """风格锚句 = 锁字符串的第一句（到首个句读或换行为止）。"""
    return re.split(r"[。；;\n]", lock.strip(), maxsplit=1)[0].strip()


# D1 计数口径（2026-10-18）：只数 汉字 + 字母 + 数字，不计中文标点与空白。
# 依据：作者是按「300 字」写满的（一次实测中 285 汉字 + 39 个标点 = 324
# 非空白字符），按非空白字符计数会把写满的作者判死，且标点多少与信息量无关。
LOCK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9]")


def count_lock_chars(s):
    """风格锁字数 = 汉字/字母/数字个数（与 导演视觉圣经 §一·补 同口径）。"""
    return len(LOCK_CHAR_RE.findall(s))


def is_ref_mode(body):
    """该提示词是否为图生/多参考模式（有图像条件承担风格）。
    显式声明优先：声明为文生类模式时不再看语法标记。"""
    m = MODE_DECLARE_RE.search(body)
    if m:
        return m.group(1).lower() in REF_MODES
    return any(rx.search(body) for rx in REF_MODE_MARKERS)


def extract_lock(proj):
    """从 00-立项/风格提案.md 抽 style-lock 块。
    返回 (lock原文 or None, 字数)。字数 = 汉字/字母/数字，不含标点与空白（D1）。"""
    p = os.path.join(proj, "00-立项", "风格提案.md")
    if not os.path.isfile(p):
        return None, 0
    body = open(p, encoding="utf-8", errors="replace").read()
    m = LOCK_FENCE_RE.search(body)
    if not m:
        return None, 0
    lock = m.group(1).strip()
    return lock, count_lock_chars(lock)


# D2 误扫防线（2026-10-18）：这些顶层目录下的 md 不是「文生视觉提示词」。
# 05-音频 是配乐/音效生成指令（情绪形容合法），06-成片 是交付文档。
SKIP_TOP_DIRS = {"05-音频", "06-成片"}
# 指针文件特征：只写「见 x.md」「以 x 为准」「本片指针」「统一权威文件」这类指向。
POINTER_RE = re.compile(
    r"指针|见\s*`[^`]*\.md`|以\s*[^，。；\n]{0,16}为准|(?:唯一|统一)[^。\n]{0,12}权威")
POINTER_BODY_MAX = 200   # 有效正文（去标题/引用/围栏/表格行）低于此数 → 指针文件
POINTER_LINE_MIN = 200   # 最长正文行低于此数 → 没有成段提示词正文 → 指针文件


def meaningful_lines(body):
    """有效正文行：去掉标题行、引用行、代码围栏行与空行。"""
    out = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(">") or s.startswith("```"):
            continue
        out.append(re.sub(r"\s+", "", s))
    return out


def is_pointer_file(body):
    """指针文件：正文只在指向别处，自身没有成段提示词正文。

    扫指针文件只会产出「缺风格锁注入」这种结构性误报——它不是提示词本体，
    本体在它指向的那个文件里（一次实测中：`关键帧提示词.md` 179 字、
    `镜头提示词.md` 466 字全是表格与索引，最长正文行 138 字）。"""
    if not POINTER_RE.search(body):
        return False
    lines = meaningful_lines(body)
    if sum(len(x) for x in lines) < POINTER_BODY_MAX:
        return True
    return max((len(x) for x in lines), default=0) < POINTER_LINE_MIN


def discover_prompt_files(proj, skipped=None):
    """发现项目内全部提示词文件。

    - 跳过 00-立项/（决策文档，锁就存在那里）；
    - 跳过 SKIP_TOP_DIRS 下的一切文件（音频/成片不是文生视觉提示词）；
    - 跳过指针文件（见 is_pointer_file）；
    - 根目录自身（rel == "."）照常扫，`00-立项` 只在真正的顶层子目录上排除
      （D2：旧写法的 rel 判定对根目录恒不命中，是可读性死角，这里显式区分）。
    """
    files = []
    if skipped is None:
        skipped = []
    for dirpath, dirs, fns in os.walk(proj):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules")]
        rel = os.path.relpath(dirpath, proj)
        top = "" if rel == "." else rel.split(os.sep)[0]
        if top == "00-立项" or top in SKIP_TOP_DIRS:
            continue
        hit_dir = any(c in ("prompts", "提示词") for c in rel.split(os.sep))
        for fn in fns:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in PROMPT_EXT:
                continue
            if not (hit_dir or ("提示词" in fn) or ("prompt" in fn.lower())):
                continue
            fp = os.path.join(dirpath, fn)
            body = open(fp, encoding="utf-8", errors="replace").read()
            if is_pointer_file(body):
                skipped.append(os.path.relpath(fp, proj))
                continue
            files.append(fp)
    return sorted(files)


def analyse(proj):
    """返回 (问题列表, 事实dict)。问题为空 = 通过。"""
    problems = []
    lock, lock_n = extract_lock(proj)
    skipped_ptrs = []
    prompt_files = discover_prompt_files(proj, skipped_ptrs)

    if lock is None:
        if prompt_files:
            problems.append(
                "有 {} 个提示词文件，但 00-立项/风格提案.md 无 ```style-lock 块"
                "（A5 欠账：先压风格锁字符串，再逐条原文追加）".format(
                    len(prompt_files)))
        return problems, {"锁字数": 0, "提示词文件数": len(prompt_files),
                          "有锁": False, "指针跳过": len(skipped_ptrs)}

    if lock_n > MAX_LOCK_CHARS:
        problems.append("风格锁 {} 字，超上限 {} 字——回基线卡做减法".format(
            lock_n, MAX_LOCK_CHARS))
    elif lock_n < MIN_LOCK_CHARS:
        problems.append("风格锁仅 {} 字，少于 {} 字下限——九要素没覆盖就是没压透"
                        .format(lock_n, MIN_LOCK_CHARS))

    needle = norm(lock)
    anchor = norm(anchor_of(lock))
    anchor_ok = len(re.sub(r"\s+", "", anchor)) >= MIN_ANCHOR_CHARS
    missing, missing_anchor = [], []
    for fp in prompt_files:
        body = open(fp, encoding="utf-8", errors="replace").read()
        nbody = norm(body)
        if needle in nbody:
            continue
        if is_ref_mode(body) and anchor_ok and anchor in nbody:
            continue  # 图生/多参考：风格由参考图承担，锚句在场即可
        rel = os.path.relpath(fp, proj)
        (missing_anchor if is_ref_mode(body) else missing).append(rel)
    if missing:
        problems.append("{} 个文生模式提示词缺风格锁原文：{}".format(
            len(missing), "、".join(missing[:3]) +
            (" …" if len(missing) > 3 else "")))
    if missing_anchor:
        problems.append("{} 个图生/多参考提示词缺风格锚句（锁的第一句）：{}".format(
            len(missing_anchor), "、".join(missing_anchor[:3]) +
            (" …" if len(missing_anchor) > 3 else "")))
    return problems, {"锁字数": lock_n, "提示词文件数": len(prompt_files),
                      "有锁": True, "缺注入": len(missing) + len(missing_anchor),
                      "指针跳过": len(skipped_ptrs)}


def _is_archived(proj):
    """项目状态摘要含「## 失败裁决」= 归档失败项目，不阻断。"""
    p = os.path.join(proj, "项目状态摘要.md")
    if not os.path.isfile(p):
        return False
    try:
        return "## 失败裁决" in open(
            p, encoding="utf-8", errors="replace").read()
    except OSError:
        return False


def discover_projects():
    """发现 00-视频项目/ 下全部片子（与工作单体系其它真片闸同一策略）。"""
    root = os.path.join(SYSTEM_ROOT, "00-视频项目")
    container = os.path.join(root, "视频项目")  # 兼容旧平铺
    candidates = []
    if os.path.isdir(root):
        candidates.extend(
            os.path.join(root, n) for n in sorted(os.listdir(root))
            if os.path.isdir(os.path.join(root, n)))
    if os.path.isdir(container):
        candidates.extend(
            os.path.join(container, n) for n in sorted(os.listdir(container))
            if os.path.isdir(os.path.join(container, n)))
    out, seen = [], set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        if os.path.basename(p).startswith("_"):
            continue  # 工作区目录（对标调研等）不是片子
        out.append(p)
    return out


def audit_all():
    waivers, werrors = load_waivers()
    for e in werrors:
        print("⚠ " + e)
    projs = discover_projects()
    if not projs:
        print("[未评估] 00-视频项目/ 下未发现在制项目，本闸没有可判对象")
        return 0
    active_bad, arch_bad, unevaluated, waived = [], [], [], []
    ok_n = 0
    for p in projs:
        problems, facts = analyse(p)
        name = os.path.basename(p)
        if facts["提示词文件数"] == 0 and not facts["有锁"]:
            unevaluated.append(name)
            print("  {:<28s} [未评估] 无锁无提示词".format(name))
            continue
        wvd = bool(problems) and is_waived(waivers, name, GATE)
        if wvd:
            tag = "WAIVED（{}，已登记豁免）".format(problems[0])
        else:
            tag = "✓" if not problems else "✗ {}".format(problems[0])
        print("  {:<28s} 锁 {} 字 / 提示词 {} 份　{}".format(
            name, facts["锁字数"], facts["提示词文件数"], tag))
        if problems and not wvd and not _is_archived(p):
            active_bad.append((name, problems))
        elif problems and not wvd:
            arch_bad.append((name, problems))
        elif wvd:
            waived.append(name)
        else:
            ok_n += 1
    n_uneval = len(unevaluated) + len(arch_bad)
    for name, problems in active_bad:
        print("\n⚠ {}：".format(name))
        for x in problems:
            print("   ✗ {}".format(x))
    if waived:
        print("\n· 已豁免（WAIVED，登记于 tools/_film_gate_waivers.yaml）：{}"
              .format("、".join(waived)))
    if arch_bad:
        print("· 归档失败项目（已记录不阻断，计入未评估）：{}".format(
            "、".join(n for n, _ in arch_bad)))
    if unevaluated:
        print("· 未评估项目（无锁无提示词）：{}".format("、".join(unevaluated)))
    if active_bad:
        print("\n  修法：G0 在 00-立项/风格提案.md 压 ```style-lock 字符串（≤300 字、"
              "汉字/字母/数字不含标点、九要素）；文生提示词逐条原文追加全文，"
              "图生/多参考提示词写一句风格锚句（锁的第一句）并在头部声明 `模式：`；"
              "存量项目补锁后重跑 python tools/check_style_lock.py <项目目录>")
        print(tally_line(ok_n, len(waived), n_uneval, len(active_bad)))
        return 1
    if waived or n_uneval:
        print("⚠ " + tally_line(ok_n, len(waived), n_uneval) +
              "　—— 有豁免/未评估，不算全绿")
        return 0
    print("✓ 全部在制项目提示词风格锁注入到位（{} 个项目）".format(ok_n))
    print(tally_line(ok_n, 0, 0))
    return 0


# ---------------------------------------------------------------- 自检
def selftest():
    import shutil
    import tempfile
    fails = []

    def mk(td, lock=None, prompts=None, proposal="00-立项/风格提案.md"):
        os.makedirs(os.path.join(td, "00-立项"), exist_ok=True)
        if lock is not None:
            open(os.path.join(td, proposal), "w", encoding="utf-8").write(
                "# 风格提案\n\n```style-lock\n{}\n```\n".format(lock))
        for rel, body in (prompts or {}).items():
            fp = os.path.join(td, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, "w", encoding="utf-8").write(body)

    LOCK_OK = "渲染：手绘赛璐璐二维，无三渲二塑料感。造型：修身长袍窄肩。头身比 1:6.5。发丝：分组清晰。" \
              "皮肤：哑光无磨皮。表演：克制微表情。动态：预备超调跟随齐全。情绪：冷峻不悲。负向：无对镜头摆拍感。"

    td = tempfile.mkdtemp(prefix="stylelock_")
    case_n = [0]

    def fresh():
        case_n[0] += 1
        d = os.path.join(td, "case{}".format(case_n[0]))
        os.makedirs(d, exist_ok=True)
        return d

    try:
        # ① 锁+全部提示词含锁 → 过
        d = fresh()
        mk(d, LOCK_OK, {
            "04-镜头/prompts/S01.md": "镜头提示词正文……\n" + LOCK_OK + "\n",
            "03-分镜/首帧提示词.md": "首帧描述……" + LOCK_OK,
        })
        ps, fs = analyse(d)
        if ps:
            fails.append("① 全含锁应过：{}".format(ps))

        # ② 有一份提示词缺锁 → FAIL
        d = fresh()
        mk(d, LOCK_OK, {
            "04-镜头/prompts/S01.md": LOCK_OK,
            "04-镜头/prompts/S02.md": "缺锁的提示词",
        })
        ps, fs = analyse(d)
        if not any("缺风格锁" in p for p in ps):
            fails.append("② 缺锁应 FAIL：{}".format(ps))

        # ③ 有提示词无锁块 → FAIL（欠账）
        d = fresh()
        mk(d, None, {"04-镜头/镜头提示词.md": "某提示词"})
        ps, fs = analyse(d)
        if not any("欠账" in p for p in ps):
            fails.append("③ 无锁块应报欠账：{}".format(ps))

        # ④ 锁超长 → FAIL
        d = fresh()
        mk(d, LOCK_OK + "加" * 400,
           {"04-镜头/prompts/S01.md": LOCK_OK + "加" * 400})
        ps, fs = analyse(d)
        if not any("超上限" in p for p in ps):
            fails.append("④ 超长锁应 FAIL：{}".format(ps))

        # ⑤ 锁与提示词换行不同 → 仍应命中（空白归一化）
        d = fresh()
        lock_ml = ("渲染：手绘赛璐璐二维，无三渲二塑料感。造型：修身长袍窄肩。"
                   "头身比 1:6.5。发丝分组清晰。皮肤哑光。表演克制微表情。"
                   "动态预备超调齐全。情绪冷峻。负向无摆拍感。")
        mk(d, lock_ml, {
            "04-镜头/prompts/S01.md":
                "正文 渲染：手绘赛璐璐二维，无三渲二塑料感。造型：修身长袍窄肩。"
                "头身比 1:6.5。发丝分组清晰。皮肤哑光。表演克制微表情。"
                "动态预备超调齐全。情绪冷峻。负向无摆拍感。 尾",
        })
        ps, fs = analyse(d)
        if ps:
            fails.append("⑤ 换行差异应放行：{}".format(ps))

        # ⑥ 无锁无提示词 → 过（未启用）
        d = fresh()
        mk(d, None)
        ps, fs = analyse(d)
        if ps:
            fails.append("⑥ 未启用应过：{}".format(ps))

        ANCHOR = anchor_of(LOCK_OK)  # "渲染：手绘赛璐璐二维，无三渲二塑料感"

        # ⑦ 图生模式（I2VA 官方首行标记）+ 只含锚句 → 过
        d = fresh()
        mk(d, LOCK_OK, {
            "04-镜头/prompts/S01.txt":
                "# 模式：I2VA\nFor the target video, at 0.00 seconds into the "
                "target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
                "integrated_multimodal_description: [Shot 1] " + ANCHOR + " …\n",
        })
        ps, fs = analyse(d)
        if ps:
            fails.append("⑦ 图生+锚句应过：{}".format(ps))

        # ⑧ 图生模式但连锚句都没有 → FAIL（报缺锚句）
        d = fresh()
        mk(d, LOCK_OK, {
            "04-镜头/prompts/S01.txt":
                "# 模式：Ref2VA\nsubject_definitions: <Subject 1> is ...\n"
                "detailed_description: [Shot 1] a man walks.\n",
        })
        ps, fs = analyse(d)
        if not any("缺风格锚句" in p for p in ps):
            fails.append("⑧ 图生缺锚句应 FAIL：{}".format(ps))

        # ⑨ 文生模式（无标记无声明）只写锚句 → 仍 FAIL（从严）
        d = fresh()
        mk(d, LOCK_OK, {
            "04-镜头/prompts/S02.md": "镜头描述……" + ANCHOR + "……",
        })
        ps, fs = analyse(d)
        if not any("缺风格锁原文" in p for p in ps):
            fails.append("⑨ 文生只有锚句应 FAIL：{}".format(ps))

        # ⑩ 契约模板式英文声明（mode: I2V）+ 只含锚句 → 过
        d = fresh()
        mk(d, LOCK_OK, {
            "04-镜头/prompts/S03.md":
                "# 模式声明\nmode: I2V\nreferences: <女主 v2 首帧图>\n\n"
                "镜头描述……" + ANCHOR + "……",
        })
        ps, fs = analyse(d)
        if ps:
            fails.append("⑩ mode: I2V 声明应识别为图生：{}".format(ps))

        # ⑪ 显式声明文生（mode: T2V）但正文混入 Ref2VA 标记 → 声明优先，从严
        d = fresh()
        mk(d, LOCK_OK, {
            "04-镜头/prompts/S04.md":
                "# 模式声明\nmode: T2V\n\n镜头描述 <Picture 1> ……" + ANCHOR,
        })
        ps, fs = analyse(d)
        if not any("缺风格锁原文" in p for p in ps):
            fails.append("⑪ mode: T2V 声明应优先从严：{}".format(ps))

        # ⑫ D1 计数口径：标点不计入字数（300 汉字 + 一堆中文标点 → 不超限）
        d = fresh()
        punct_lock = LOCK_OK + "，" * 250
        mk(d, punct_lock, {"04-镜头/prompts/S01.md": punct_lock})
        ps, fs = analyse(d)
        if ps:
            fails.append("⑫ 标点不该计入 300 字：{}".format(ps))
        # ⑬ D1 但汉字真超限必须仍抓（350 汉字 + 0 标点 → FAIL）
        d = fresh()
        long_lock = "字" * 350
        mk(d, long_lock, {"04-镜头/prompts/S01.md": long_lock})
        ps, fs = analyse(d)
        if not any("超上限" in p for p in ps):
            fails.append("⑬ 汉字超 300 应 FAIL：{}".format(ps))

        # ⑭ D2 指针文件（只写「见 x.md」+ 正文很短）→ 不报缺锁
        d = fresh()
        mk(d, LOCK_OK, {
            "04-镜头/prompts/S01.md": LOCK_OK,
            "04-镜头/镜头提示词.md":
                "# 本片指针\n\n> 提示词统一存放在权威文件：见 `prompts/S01.md`。\n\n"
                "- 本文件只做登记位。\n",
        })
        ps, fs = analyse(d)
        if ps:
            fails.append("⑭ 指针文件不该报缺锁：{}".format(ps))

        # ⑮ D2 但有成段正文的提示词即使含「见 x.md」也必须照抓（防误放行）
        d = fresh()
        mk(d, LOCK_OK, {
            "04-镜头/prompts/S01.md": LOCK_OK,
            "04-镜头/prompts/S02.md":
                "**视频提示词原文**\n\n" + "镜头描述正文段落。" * 40 +
                "\n\n参考：见 `S01.md`。\n",
        })
        ps, fs = analyse(d)
        if not any("缺风格锁原文" in p for p in ps):
            fails.append("⑮ 有正文的提示词不该被当指针放过：{}".format(ps))
    finally:
        shutil.rmtree(td, ignore_errors=True)

    if fails:
        print("[selftest] ✗ {} 项失败：".format(len(fails)))
        for f in fails:
            print("  - " + f)
        return 2
    print("[selftest] 15/15 通过（全含锁/缺锁/欠账/超长/换行归一/未启用/"
          "图生锚句过/图生缺锚句/文生从严/mode英文声明/声明优先于标记/"
          "标点不计字数/汉字超限仍抓/指针文件跳过/有正文不误放行）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="风格锁注入闸")
    ap.add_argument("project", nargs="?", help="单项目目录（不传则扫全部）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.project:
        if not os.path.isdir(args.project):
            print("目录不存在：{}".format(args.project))
            return 2
        problems, facts = analyse(args.project)
        print("=" * 68)
        print("风格锁注入闸：{}".format(os.path.basename(
            os.path.normpath(args.project))))
        print("=" * 68)
        print("锁：{}　提示词文件：{} 份{}".format(
            ("{} 字".format(facts["锁字数"]) if facts["有锁"] else "未定义"),
            facts["提示词文件数"],
            "　（指针文件跳过 {} 份）".format(facts.get("指针跳过", 0))
            if facts.get("指针跳过") else ""))
        print("-" * 68)
        if problems:
            for x in problems:
                print("✗ {}".format(x))
            return 1
        if facts["提示词文件数"] == 0:
            # D3：没有可判对象 = 未评估，不是通过（但仍不阻断，exit 0）
            print("[未评估] 无锁也无提示词（G0 未完成？），本闸没有可判对象")
        else:
            print("✓ 风格锁已注入全部提示词")
        return 0
    return audit_all()


if __name__ == "__main__":
    sys.exit(main())
