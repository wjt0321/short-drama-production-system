#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目合规闸（ROUTE/DUR/STATE/PROMPT/DIR/TPL/MOTION 系列）—— 真实项目状态 vs 磁盘产物、空模板/关键交接件、
标准目录 vs 旁路目录、提示词可发现性、静帧/数字运动/冻结占比、
时长分布模式值与窄带、刀型白名单、提示词防错合同启发式、生成段执行字段。

**为什么需要这道闸**
其余闸只查「文件之间说法一致不一致」、「闸自身没坏」、「素材库健康」。
**没有一道闸专门回答**「这个项目本身合不合规」：
  · 真实项目状态摘要说「通过」但磁盘上关键交付件全无 → 谁也不会发现
  · 提示词写到 `04-镜头/prompts/` 之外的旁路目录 → 视频生成脚本读不到
  · 刀型列填了「中刀/呼吸/过场」等模板白名单以外的值 → check_shot_duration
    只认「短刀/常规/长刀」，会把它们当「没填」
  · 时长集中在 4-6 秒窄带 → 切点均质度闸只对 `<4` 镜的极短片不报警，
    5-12 镜「都差不多」的模式值没被识别
  · 提示词全在堆叠负面约束（「No / never / no text or subtitle appears」）
    而完全没写动作或运镜 → 模型收到的是「防错合同」而不是「导演调度」
  · 静帧 + 数字运动占比超阈值 → 退路 E（Ken Burns）悄悄承担主体叙事

**与已有闸的关系**
  · 与 `check_shot_duration_variance.py` 互补：本闸查「项目合规」，
    切点均质度闸查「切点节奏」。同一问题可能在两处都报，但要修就修一处。
  · 与 `check_emotion_words.py` 互补：本闸查「项目状态/产物」是否真实，
    情绪词闸查「提示词正文有没有裸奔情绪词」（AGENTS.md §8.1 落地）。
  · 本闸是「项目闸」（按项目运行）；「闸的闸」由 run_all_checks 的
    闸集合完备性声明覆盖，不再有单独的指纹清单。

**已归档失败项目**（项目状态摘要含 `失败裁决` 节 且 标了失败类型/归档路径）：
  · 不因「状态/磁盘不一致」判 FAIL —— 失败归档天然不一致。
  · **但仍报告失败特征**，让用户看到这项目目前状态、失败类型和已停止的范围。
  · 退出码：发现严重问题 1；纯告警 0；空目录 0。

**用法**
    python tools/check_project_conformance.py                       # 扫全部活跃项目
    python tools/check_project_conformance.py --project <项目目录>     # 单项目
    python tools/check_project_conformance.py --json                  # JSON 输出
    python tools/check_project_conformance.py --selftest              # 内置自检

**退出码**：0 全绿或仅告警 / 1 有阻断项 / 2 用法或自检失败
"""
import argparse
import glob as _glob
import json
import os
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

from _film_gate_waivers import load_waivers, is_waived, tally_line

GATE = "项目合规-真片"

# ---- 白名单与阈值（与 `02-分镜与镜头/分镜工作流.md` 对齐）----
# 刀型白名单（D8 三档，与模板 / AGENTS.md §三 对齐）：
#   短刀 ≤2s（过渡、过场）/ 常规 2–4s（承接、正常推进）/ 长刀 4–8s（信息或情绪重）
# 「中刀/重点/过场/呼吸/普通」等仍是「没做轻重判断」的伪装，照旧算未知值。
KNIFE_WHITELIST = ("短刀", "常规", "长刀")
# 时长窄带：模式值落在 [4.0, 6.0] 区间且 ≥70% 镜数集中 → 节拍器。
NARROW_BAND = (4.0, 6.0)
NARROW_BAND_RATIO = 0.70
# 静帧 + 数字运动占比超阈值 → 退路 E 承担主体叙事。
# 叙事类题材若超过 50% 镜头没动起来，等于把「生成」退化成「会动的静帧」。
STATIC_RATIO = 0.50
# 防错合同提示词阈值：负面约束占镜头提示词正文 15% 以上 → 合同式反模式。
# 阈值不宜过高：实测合同式反模式的提示词正文通常就 50–100 词，
# 「No / never / doesn't / doesn't change」密集出现 8+ 次即属典型征兆。
CONTRACT_DENSITY = 0.15
# 生成段执行字段缺失阈值：模板必填 9 项缺失率 ≥ 30%。
SEG_FIELD_MISSING_RATIO = 0.30
# 路径白名单：项目内的标准目录；其他都属于「旁路目录」/历史来源。
STANDARD_DIRS = {
    "00-立项", "01-剧本", "02-资产", "03-分镜", "04-镜头", "05-音频",
    "06-成片",
}
# 关键交接件：项目状态摘要说通过/失败时必须在磁盘上存在。
KEY_DELIVERABLES_ACTIVE = (
    "项目状态摘要.md", "执行清单.md", "03-分镜/分镜表.md",
    "04-镜头/镜头提示词.md", "06-成片/剪辑装配单.md",
    "06-成片/成片质检表.md",
)

# ---- 提示词可发现性 ----
PROMPT_EXTS = {".md", ".txt"}
SHOT_RE = re.compile(r"\[Shot\s+\d+\]", re.I)
AT_RE = re.compile(r"[Aa]t\s+00:\d{2}\.\d{3}")
I2VA_TAG_RE = re.compile(r"integrated_multimodal_description\s*:", re.I)
I2VA_HDR_RE = re.compile(r"For the target video", re.I)

# ---- 防错合同启发式 ----
# 真实提示词里出现这些模式 + 没有配套的运镜/动作描述 → 合同式反模式。
CONTRACT_MARKERS = re.compile(
    r"\b(?:No|never|no\s+\w+|doesn't|does\s+not|"
    r"doesn'?t|cannot|can'?t|won'?t|will\s+not)\b",
    re.I,
)
# 「起止状态相同」的强模式：首尾描述一致就是「没发生动作」。
SAME_STATE_RE = re.compile(
    r"(?:same\s+(?:as|with)|stays\s+the\s+same|remains\s+the\s+same|"
    r"does\s+not\s+change|never\s+changes|identical\s+from\s+the\s+first)",
    re.I,
)
# 「摄影机路径」应有模式：起点/过程/终点、推进、摇移、跟踪。
CAM_PATH_RE = re.compile(
    r"\b(?:dolly|track|pan|tilt|crane|orbit|"
    r"push[- ]?in|pull[- ]?out|zoom[- ]?(?:in|out)|"
    r"slowly|steadily|ease[- ]?in|ease[- ]?out)\b",
    re.I,
)

# ---- 演员调度 / 运动学合同启发式（非阻断 WARN） ----
# 来源：
#       `04-视频生成/平台提示词契约.md` §一.9。
# 触发条件：提示词段含「交互动作强信号」+ 缺对应运动合同字段。

# 交互动作强信号（任一即可触发检查）
# 注意：英文动词允许第三人称 -s 后缀（walks / picks / sits ...）
INTERACTION_MARKERS = re.compile(
    r"\b(?:pick(?:\s*up|es?\s+up)?|put\s+down|grab|hold|carry|push(?:es)?|"
    r"cart|pushcart|walk(?:s|\s+(?:forward|backward|toward|away))?|"
    r"run(?:s)?|turn(?:s)?\s+around|sit(?:s)?\s+down|stand(?:s)?\s+up|"
    r"step(?:s)?\s+(?:forward|back)|"
    r"hand(?:s)?\s+(?:over|reach)|touch|press|pull|open|close|"
    r"ride|drive|wheel|骑|推|拉|走|跑|坐|站|转|拿|放|捡|推车|握手|开门|关门|坐下|起身)\b",
    re.I,
)
# 接触动词（手 / 道具）
CONTACT_MARKERS = re.compile(
    r"\b(?:contact|grip(?:s)?|grasp(?:s|ed)?|pinch(?:es)?|hold(?:s)?|"
    r"夹住|握住|捏住|抓住|承重)\b",
    re.I,
)
# 运动合同 9 字段标识（提示词里出现这些关键词算「填了」）
MOTION_FIELDS = {
    "屏幕坐标与向量": re.compile(
        r"(?:屏幕坐标|屏幕向量|screen\s+(?:coord|position|vector))",
        re.I),
    "主体初始朝向": re.compile(
        r"(?:主体初始朝向|初始朝向|主体朝向|body\s+facing)",
        re.I),
    "移动方向与世界坐标": re.compile(
        r"(?:移动方向|世界坐标|world\s+(?:coord|direction))",
        re.I),
    "脚步/重心": re.compile(
        r"(?:脚步|重心|步态|起步脚|承重脚|footwork|gait)",
        re.I),
    "手-道具接触": re.compile(
        r"(?:手[-\s]*道具接触|接触点|承重方式|hand[-\s]*prop)",
        re.I),
    "道具/轮子从属运动": re.compile(
        r"(?:道具[·/\s]?轮子|从属运动|车轮耦合|链式运动|wheel\s+coupling)",
        re.I),
    "摄影机方向与主体相对速度": re.compile(
        r"(?:摄影机方向|相对速度|镜头相对|camera\s+relative)",
        re.I),
    "轴线/视线": re.compile(
        r"(?:轴线|视线接力|screen\s+direction|axis|sightline)",
        re.I),
    "结束状态": re.compile(
        r"(?:结束状态|end\s+state|终点坐标)",
        re.I),
}


def _read(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _has_fail_marker(text):
    """项目状态摘要里是否有失败裁决节（说明项目已归档为失败案例）。"""
    if not text:
        return False, None
    # 「失败裁决」节存在 = 已归档失败；
    # 同时确认含「归档」字样，避免「失败风险」类讨论被误判。
    if re.search(r"##\s*失败裁决", text) and "归档" in text:
        # 「失败类型：」「失败类型:」兼容全/半角冒号
        m_type = re.search(r"失败类型\s*[:：]\s*(\S+?)(?:\n|$)", text)
        m_arch = re.search(r"归档\s*[:：]\s*[`']?([^`'\n]+)[`']?", text)
        return True, {
            "类型": (m_type.group(1).strip() if m_type else "?"),
            "归档路径": (m_arch.group(1).strip() if m_arch else "?"),
        }
    return False, None


def _list_projects():
    """扫全部活跃项目（00-视频项目/ + 根目录旧项目兼容）。

    「项目是部片子」的最低判据：带《》片名，或至少存在一个影视产物
    （状态摘要/分镜表/04-镜头/01-剧本）。`_` 开头的是工作区目录
    （对标调研、试验场），不是片子，不进来 —— 否则调研夹缺张状态
    摘要也把真片闸 permanent 干红（实测栽过）。
    """
    out = []
    markers = ("项目状态摘要.md", "03-分镜/分镜表.md", "04-镜头", "01-剧本")

    def _looks_like_project(full, name):
        if name.startswith("_"):
            return False
        if name.startswith("《"):
            return True
        return any(os.path.exists(os.path.join(full, m)) for m in markers)

    container = os.path.join(SYSTEM_ROOT, "00-视频项目")
    if os.path.isdir(container):
        for n in sorted(os.listdir(container)):
            full = os.path.join(container, n)
            if os.path.isdir(full) and _looks_like_project(full, n):
                out.append(full)
    # 兼容根目录旧项目
    for n in sorted(os.listdir(SYSTEM_ROOT)):
        if n in {"00-视频项目", "模板", "外部参考库", "tools",
                 "archive", "docs", "__pycache__"}:
            continue
        full = os.path.join(SYSTEM_ROOT, n)
        if os.path.isdir(full) and (n.endswith("项目") or n.startswith("《")):
            if full not in out and _looks_like_project(full, n):
                out.append(full)
    return out


# ====================================================================
# 子检查：每个返回一个 List[(level, code, msg)]
# level: "FAIL" / "WARN" / "INFO"
# ====================================================================

def check_state_vs_disk(proj):
    """真实项目状态 vs 磁盘产物一致性。

    逻辑：
      · 项目状态摘要的「当前关卡 / 状态 / 任务」字段与磁盘关键交付件是否对得上。
      · 状态摘要不存在 → 缺失标记 WARN。
      · 已归档失败项目 → 这一项不阻断（FAIL → INFO），失败特征另报。
    """
    out = []
    summary = os.path.join(proj, "项目状态摘要.md")
    body = _read(summary)
    archived, arch_info = _has_fail_marker(body)

    if not body:
        out.append(("FAIL", "STATE-01",
                    "项目状态摘要.md 缺失，无法判断项目状态"))
        return out

    # 找到声明的当前关卡
    m_gate = re.search(r"当前关卡[::]\s*(\S+)", body)
    declared_gate = m_gate.group(1) if m_gate else None
    m_status = re.search(r"当前状态[::]\s*([^\n]+)", body)
    declared_status = (m_status.group(1).strip() if m_status else "")

    # 关键交付件存在性
    missing = []
    for rel in KEY_DELIVERABLES_ACTIVE:
        if not os.path.exists(os.path.join(proj, rel)):
            missing.append(rel)
    if missing and not archived:
        # 活跃项目缺关键交付件 → FAIL
        out.append(("FAIL", "STATE-02",
                    "声明 {} 时缺失关键交接件：{}".format(
                        declared_status or "?", "、".join(missing[:4]))))
    elif missing and archived:
        # 归档失败项目允许缺失（部分可能未生成）
        out.append(("INFO", "STATE-02",
                    "归档失败项目可接受缺失：{}".format(
                        "、".join(missing[:4]))))

    # 关卡 vs 磁盘：G3+ 应有分镜表与镜头提示词
    if declared_gate in ("G3", "G4", "G5", "G6") \
            and not os.path.exists(os.path.join(proj, "03-分镜", "分镜表.md")):
        if not archived:
            out.append(("FAIL", "STATE-03",
                        "声明当前关卡 {} 但 03-分镜/分镜表.md 不存在"
                        .format(declared_gate)))
        else:
            out.append(("INFO", "STATE-03",
                        "归档失败项目缺分镜表（已记录）"))
    if declared_gate in ("G4", "G5", "G6") \
            and not os.path.exists(os.path.join(proj, "04-镜头", "镜头提示词.md")):
        if not archived:
            out.append(("FAIL", "STATE-04",
                        "声明当前关卡 {} 但 04-镜头/镜头提示词.md 不存在"
                        .format(declared_gate)))
        else:
            out.append(("INFO", "STATE-04",
                        "归档失败项目缺镜头提示词（已记录）"))

    if archived:
        out.append(("INFO", "STATE-ARCH",
                    "项目已归档为失败案例：类型={} 归档={}".format(
                        arch_info["类型"] if arch_info else "?",
                        arch_info["归档路径"] if arch_info else "?")))

    return out


def check_empty_templates(proj):
    """空模板检测：模板字段为空、未填写关键字段。

    关注：
      · 项目状态摘要的「已通过决策」表全空
      · 执行清单的关卡状态全未开始
    """
    out = []
    summary_body = _read(os.path.join(proj, "项目状态摘要.md"))
    archived, _ = _has_fail_marker(summary_body)

    # 已通过决策表
    m = re.search(r"##\s*已通过决策(.*?)(?=\n##|\Z)", summary_body, re.S)
    if m:
        tbl = m.group(1)
        rows = [ln for ln in tbl.splitlines()
                if ln.strip().startswith("|") and "---" not in ln
                and "事项" not in ln and "决策" not in ln
                and ln.count("|") > 3]
        if not rows:
            level = "INFO" if archived else "WARN"
            out.append((level, "TPL-01",
                        "项目状态摘要的「已通过决策」表全空 —— 可能只是新项目"))

    # 执行清单关卡状态：所有 G0–G6 都是「未开始」但项目状态说「G6 通过」
    cl = _read(os.path.join(proj, "执行清单.md"))
    m_gate_status = re.search(
        r"(?:关卡状态|G\d).*?\n((?:\|\s*[A-Z]?\d\s*\|.*?\n){2,})", cl)
    if m_gate_status and summary_body:
        tbl = m_gate_status.group(1)
        not_started = sum(1 for ln in tbl.splitlines()
                          if "|" in ln and "未开始" in ln)
        if not_started >= 6 and re.search(r"G6", summary_body) \
                and "通过" in summary_body:
            out.append(("FAIL", "TPL-02",
                        "项目状态摘要声明含 G6 通过，但执行清单 6 个关卡仍为「未开始」"))

    return out


def check_standard_dirs(proj):
    """标准目录 vs 旁路目录。

    关注：项目内有项目状态摘要/分镜表等关键文件，但目录命名不在 STANDARD_DIRS。
    比如把镜头提示词放到 `镜头素材/` 或 `H3_提示词/` —— 生成脚本读不到。
    """
    out = []
    archived = _has_fail_marker(_read(os.path.join(proj, "项目状态摘要.md")))[0]
    # 取项目根的子目录
    try:
        subdirs = [n for n in os.listdir(proj)
                   if os.path.isdir(os.path.join(proj, n))]
    except OSError:
        return out
    # 兼容：带前导数字的标准目录也算合规
    standard_prefixed = set()
    for s in STANDARD_DIRS:
        for sub in subdirs:
            # `02-分镜` 或 `分镜` 都接受
            if sub == s or sub.endswith("-" + s) or s in sub:
                standard_prefixed.add(sub)
    bypass = [s for s in subdirs
              if not any(s == sd or s.endswith("-" + sd) or sd in s
                         for sd in STANDARD_DIRS)
              and s not in {".git", "__pycache__", "node_modules",
                            "失败案例", "失败复盘"}
              and not s.startswith(".")]
    if bypass:
        level = "INFO" if archived else "WARN"
        out.append((level, "DIR-01",
                    "项目内发现非标准目录：{} —— "
                    "若为历史来源可保留，若为现行产物请迁入标准目录".format(
                        "、".join(sorted(bypass)[:5]))))
    return out


def check_prompt_discovery(proj):
    """提示词可发现性：递归扫 + 按内容发现。

    关注：
      · 项目声明「H3 I2VA 提示词已在 04-镜头/prompts/」但文件实际写在旁路目录
      · 文件名后缀不在白名单（.md/.txt）但内容是 I2VA 提示词 → 按内容发现
      · `04-镜头/prompts/` 目录不存在但 `04-镜头/镜头提示词.md` 含分镜 + I2VA 段
    """
    out = []
    archived = _has_fail_marker(_read(os.path.join(proj, "项目状态摘要.md")))[0]
    # 列出所有项目内 .md/.txt
    found = []
    for root, _dirs, files in os.walk(proj):
        if any(seg in root for seg in ("__pycache__", ".git", "失败案例")):
            continue
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in PROMPT_EXTS:
                continue
            p = os.path.join(root, fn)
            body = _read(p)
            if I2VA_TAG_RE.search(body) or I2VA_HDR_RE.search(body):
                found.append(p)

    if not found:
        # 没有 I2VA 提示词 —— 也许还在 G2 之前，不是问题
        out.append(("INFO", "PROMPT-01",
                    "项目内未发现 I2VA 提示词（G4 未启动或非 I2VA 路线）"))
        return out

    # 是否至少有一个落在 04-镜头/ 标准目录或其内子目录
    in_std = [p for p in found
              if os.sep + "04-镜头" + os.sep in p
              or os.sep + "镜头" + os.sep in p]
    out_of_std = [p for p in found if p not in in_std]
    if out_of_std:
        level = "INFO" if archived else "WARN"
        out.append((level, "PROMPT-02",
                    "提示词写在 04-镜头 之外：{} —— "
                    "生成脚本按标准目录发现时可能读不到".format(
                        "、".join(os.path.relpath(p, proj) for p in out_of_std[:3]))))

    return out


def check_route_distribution(proj):
    """静帧 / 数字运动 / 冻结占比。

    读 06-成片/剪辑装配单.md 的轨道表，统计：
      · 「数字轻推」「Ken Burns」「静帧」类 → 静帧 + 数字运动
      · 「尾帧冻结」「冻结」 → 冻结凑时长
    占比 > STATIC_RATIO → FAIL（活跃）/ WARN（归档）。
    """
    out = []
    body = _read(os.path.join(proj, "06-成片", "剪辑装配单.md"))
    archived = _has_fail_marker(_read(os.path.join(proj, "项目状态摘要.md")))[0]

    if not body:
        return out

    # 解析轨道表（取「素材文件/版本」与「速度」两列做启发式）
    rows = []
    for line in body.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        # 剪辑装配单轨道表至少 9 列：轨道 + 镜头ID + 素材 + 源入点 + 源出点 +
        # 时间线入点 + 时间线出点 + 速度 + 转场
        if len(cells) < 9:
            continue
        if cells[0] == "轨道":
            header = cells
            continue
        if not cells[0].startswith("V"):
            continue
        rows.append(cells)

    if not rows:
        return out

    n = len(rows)
    static = 0
    frozen = 0
    for r in rows:
        mat = r[header.index("素材文件/版本")] if "素材文件/版本" in header else ""
        speed = r[header.index("速度")] if "速度" in header else ""
        if "静帧" in mat or "静帧" in speed or "数字轻推" in speed \
                or "Ken Burns" in speed or "zoompan" in speed.lower():
            static += 1
        if "冻结" in speed or "尾帧冻结" in speed:
            frozen += 1
    static_ratio = static / n
    frozen_ratio = frozen / n

    if static_ratio >= STATIC_RATIO:
        level = "INFO" if archived else "FAIL"
        out.append((level, "ROUTE-01",
                    "静帧 + 数字运动占 {}/{} = {:.0%}（阈值 {:.0%}）—— "
                    "退路 E 承担主体叙事，缺真实生成动作".format(
                        static, n, static_ratio, STATIC_RATIO)))
    if frozen_ratio >= 0.25:
        level = "INFO" if archived else "WARN"
        out.append((level, "ROUTE-02",
                    "尾帧冻结占 {}/{} = {:.0%}（阈值 25%）—— "
                    "冻结凑时长是 PPT 感的常见来源".format(
                        frozen, n, frozen_ratio)))
    return out


def check_duration_distribution(proj):
    """时长分布模式值与 4-6 秒窄带。

    不查「方差」（切点均质度闸已查），查「模式值集中在 4-6 秒窄带」——
    这是「时长被模型档位反向塑形」的另一种典型模式。
    """
    out = []
    # 复用切点均质度闸的解析
    sys.path.insert(0, HERE)
    import check_shot_duration_variance as v
    durs, _fps, src = v.parse_durations_from_storyboard(proj)
    archived = _has_fail_marker(_read(os.path.join(proj, "项目状态摘要.md")))[0]

    if not durs:
        return out
    n = len(durs)
    in_band = sum(1 for d in durs
                  if NARROW_BAND[0] <= d <= NARROW_BAND[1])
    ratio = in_band / n
    # 模式值（众数）
    cnt = Counter(round(d, 1) for d in durs)
    mode_val, mode_n = cnt.most_common(1)[0]
    mode_ratio = mode_n / n

    if n >= 4 and ratio >= NARROW_BAND_RATIO:
        level = "INFO" if archived else "FAIL"
        out.append((level, "DUR-01",
                    "{}/{} 镜时长落在 [{:.1f},{:.1f}]s 窄带内（占比 {:.0%}）—— "
                    "时长被模型档位反向塑形，节拍器风险".format(
                        in_band, n, NARROW_BAND[0], NARROW_BAND[1], ratio)))
    if n >= 4 and mode_ratio >= 0.40 and abs(mode_val - 5.0) < 1.0:
        level = "INFO" if archived else "WARN"
        out.append((level, "DUR-02",
                    "时长众数 {:.2f}s 出现 {}/{} 镜（{:.0%}）—— "
                    "可疑：模型单次上限 ≈ 5s 的产物特征".format(
                        mode_val, mode_n, n, mode_ratio)))
    return out


def check_knife_whitelist(proj):
    """刀型白名单 + 时长交叉。

    关注（D8 三档口径）：
      · 刀型列含「短刀/常规/长刀」以外的值 → WARN
      · 刀型与时长不匹配 → WARN（自相矛盾）：
        短刀 ≤2s / 常规 2–4s / 长刀 4–8s，±KNIFE_BAND_SLACK 容错
    """
    out = []
    sys.path.insert(0, HERE)
    import check_shot_duration_variance as v
    knife = v.parse_knife_col(proj)
    archived = _has_fail_marker(_read(os.path.join(proj, "项目状态摘要.md")))[0]

    if not knife["found"]:
        # 没刀型列 → 留给切点均质度闸
        return out

    # 解析刀型列每行的值，识别非白名单值
    path = _glob.glob(os.path.join(proj, "03-分镜", "分镜表.md"))
    if not path:
        return out
    bad_vals = Counter()
    with open(path[0], encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if "刀型" in " ".join(cells) and any("刀型" == c for c in cells):
                continue
            for c in cells:
                if c and c not in KNIFE_WHITELIST and c in (
                    "长刀", "短刀", "中刀", "重点", "过场", "呼吸", "普通"):
                    bad_vals[c] += 1
                    break

    if bad_vals:
        level = "INFO" if archived else "WARN"
        out.append((level, "KNIFE-01",
                    "刀型列含白名单以外的值：{} —— "
                    "「{}」是「没做轻重判断」的伪装".format(
                        "、".join("{}×{}".format(k, v)
                                  for k, v in bad_vals.most_common(3)),
                        "/".join(k for k in bad_vals))))

    # 时长 × 刀型交叉
    durs, _fps, _src = v.parse_durations_from_storyboard(proj)
    if durs:
        # 逐行刀型：先由表头定位「刀型」列序号，再按该列取每一行的值。
        # 旧写法要求「数据行里也出现『刀型』三个字」才继续，实际只有表头行能过，
        # knife_per_row 恒为空 → cross_bad 恒为 0，KNIFE-02 是死代码。
        # （D8 补测三档时暴露：常规 写在 5.5s 也不报警。）
        knife_per_row = []
        knife_col = -1
        with open(path[0], encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s.startswith("|"):
                    continue
                cells = [c.strip() for c in s.strip("|").split("|")]
                if knife_col < 0:
                    for i, c in enumerate(cells):
                        if "刀型" in c:
                            knife_col = i
                            break
                    continue      # 表头行本身不是数据行
                if knife_col >= len(cells):
                    continue
                if all(set(c) <= set("-: ") and c for c in cells):
                    continue      # 分隔行 `|---|---|`
                val = cells[knife_col]
                if val and val not in ("刀型", "镜数", "镜号", "镜头", "时长"):
                    knife_per_row.append(val)
        cross_bad = 0
        cross_by_type = Counter()
        for k, d in zip(knife_per_row, durs):
            band = v.KNIFE_BANDS.get(k)
            if not band:
                continue
            lo, hi = band
            if d < lo - v.KNIFE_BAND_SLACK or d > hi + v.KNIFE_BAND_SLACK:
                cross_bad += 1
                cross_by_type["{}@{}s".format(k, round(d, 2))] += 1
        if cross_bad:
            level = "INFO" if archived else "WARN"
            out.append((level, "KNIFE-02",
                        "{} 行刀型与时长自相矛盾（三档应为："
                        "短刀 ≤2s / 常规 2–4s / 长刀 4–8s，±{:.1f}s 容错）：{}"
                        .format(cross_bad, v.KNIFE_BAND_SLACK,
                                "、".join("{}×{}".format(k, v)
                                          for k, v
                                          in cross_by_type.most_common(3)))))

    return out


def check_prompt_contract(proj):
    """提示词防错合同启发式（WARN 级，不阻断）。

    对每个 I2VA 提示词：
      · 「No / never / doesn't」等负面约束计数
      · 「起止状态相同」强模式计数
      · 「摄影机路径」模式计数
    判定：负面约束占正文 35%+ 且 没有任何摄影机路径模式 → WARN。
    """
    out = []
    sys.path.insert(0, HERE)
    archived = _has_fail_marker(_read(os.path.join(proj, "项目状态摘要.md")))[0]

    # 列出所有 I2VA 提示词文件
    files = []
    for root, _dirs, fns in os.walk(proj):
        if any(seg in root for seg in ("__pycache__", ".git", "失败案例")):
            continue
        for fn in fns:
            if os.path.splitext(fn)[1].lower() not in PROMPT_EXTS:
                continue
            p = os.path.join(root, fn)
            body = _read(p)
            if I2VA_TAG_RE.search(body) or I2VA_HDR_RE.search(body):
                files.append(p)
    if not files:
        return out

    bad = 0
    total = 0
    same_state = 0
    for p in files:
        body = _read(p)
        # 提取 integrated_multimodal_description 段
        m = re.search(
            r"integrated_multimodal_description\s*:(.*?)(?:overall_soundscape|"
            r"non_diegetic_music|\Z)",
            body, re.S | re.I)
        seg = m.group(1) if m else body
        seg = seg.strip()
        if not seg:
            continue
        total += 1
        words = len(seg.split())
        neg = len(CONTRACT_MARKERS.findall(seg))
        cam = len(CAM_PATH_RE.findall(seg))
        same = len(SAME_STATE_RE.findall(seg))
        if same:
            same_state += 1
        # 合同式：负面 ≥ 35% 且没有摄影机路径
        density = neg / words if words else 0
        if density >= CONTRACT_DENSITY and cam == 0:
            bad += 1
    if total and bad / total >= 0.30:
        out.append(("WARN", "PROMPT-CT",
                    "{}/{} 个提示词负面约束占比 ≥ {:.0%} 且无摄影机路径 —— "
                    "防错合同式反模式，模型收到的是「禁止清单」而不是「导演调度」".format(
                        bad, total, CONTRACT_DENSITY)))
    if same_state:
        out.append(("WARN", "PROMPT-SS",
                    "{} 个提示词含「起止状态相同」表述 —— "
                    "首尾一致 = 没发生动作，模型只能输出几乎静帧的画面".format(
                        same_state)))
    return out


def check_segment_execution_fields(proj):
    """生成段执行字段检查。

    模板 `04-镜头/镜头提示词.md` 必填的「摄影执行字段」9 项：
      镜头叙事功能 / 主要观看重点 / 起始状态 / 动作目标与结束状态 /
      运镜起点/过程/终点 / 焦点与焦点变化 / 屏幕方向/轴线 /
      时间码节拍 / 生成段拆分理由
    缺失率 ≥ 30% → WARN。
    """
    out = []
    body = _read(os.path.join(proj, "04-镜头", "镜头提示词.md"))
    archived = _has_fail_marker(_read(os.path.join(proj, "项目状态摘要.md")))[0]
    if not body:
        return out

    required = [
        "镜头叙事功能", "主要观看重点", "起始状态", "动作目标与结束状态",
        "运镜起点/过程/终点", "焦点与焦点变化", "屏幕方向/轴线",
        "时间码节拍", "生成段拆分理由",
    ]
    missing = [k for k in required if k not in body]
    miss_rate = len(missing) / len(required)
    if miss_rate >= SEG_FIELD_MISSING_RATIO:
        out.append(("WARN", "SEG-01",
                    "镜头提示词缺摄影执行字段 {} 项（缺失率 {:.0%}）—— "
                    "执行字段不齐，生成段落到动作/运镜执行容易失锚".format(
                        len(missing), miss_rate)))
    return out


def check_motion_contract(proj):
    """演员调度 / 运动学合同 启发式（非阻断 WARN）。

    来源：
          `04-视频生成/平台提示词契约.md` §一.9、
          `02-分镜与镜头/分镜工作流.md` §生成前运动设计闸 第 8 项。

    触发：提示词段（镜头提示词正文 / I2VA 段 / 分镜表行）含「交互动作强信号」
    （如 walk / push / pickup / turn around / wheel / sit down 等），
    但缺对应的运动合同字段 → 报 MOTION-CT WARN。

    4 项独立 WARN：
      MOTION-CT  交互动作段缺 ≥3 个核心字段（屏幕坐标 / 朝向 / 脚步 / 接触）
      MOTION-WHL 含「推车 / wheel / ride」类词但缺「车轮耦合 / 链式运动」字段
      MOTION-CC  含接触动词但缺「接触点 / 承重」字段
      MOTION-FF  含转身 / 走 / 跑类词但缺「正向机械示例」（堆叠 `no / doesn't`）

    状态：活跃项目 = WARN（不阻断）；归档项目 = INFO（保留失败特征）。
    """
    out = []
    archived = _has_fail_marker(_read(os.path.join(proj, "项目状态摘要.md")))[0]

    # 列出项目内的提示词段（含 I2VA / 镜头提示词 / 分镜表行）
    bodies = []
    p_lenshottxt = os.path.join(proj, "04-镜头", "镜头提示词.md")
    p_story = os.path.join(proj, "03-分镜", "分镜表.md")

    for root, _dirs, fns in os.walk(proj):
        if any(seg in root for seg in ("__pycache__", ".git", "失败案例")):
            continue
        for fn in fns:
            if os.path.splitext(fn)[1].lower() not in PROMPT_EXTS:
                continue
            p = os.path.join(root, fn)
            body = _read(p)
            if I2VA_TAG_RE.search(body) or I2VA_HDR_RE.search(body):
                bodies.append(body)
    # 镜头提示词正文（不一定含 I2VA tag）
    shot_body = _read(p_lenshottxt)
    if shot_body:
        bodies.append(shot_body)
    # 分镜表正文（每行作为一段）
    story_body = _read(p_story)
    if story_body:
        bodies.append(story_body)

    if not bodies:
        return out

    # 聚合：含交互动作强信号的段
    interactive_segments = []
    for b in bodies:
        if INTERACTION_MARKERS.search(b):
            interactive_segments.append(b)
    if not interactive_segments:
        return out

    # 聚合各字段出现次数（只要任一段含即算填了）
    field_counts = {name: 0 for name in MOTION_FIELDS}
    for seg in interactive_segments:
        for name, pat in MOTION_FIELDS.items():
            if pat.search(seg):
                field_counts[name] += 1

    # ---- MOTION-CT：交互段缺 ≥3 个核心字段（屏幕坐标 / 朝向 / 脚步 / 接触）----
    core_fields = ["屏幕坐标与向量", "主体初始朝向", "脚步/重心", "手-道具接触"]
    core_missing = [f for f in core_fields if field_counts[f] == 0]
    if len(core_missing) >= 3:
        level = "INFO" if archived else "WARN"
        out.append((level, "MOTION-CT",
                    "{} 个交互动作段缺核心运动合同字段 {}（缺 {} / {}）—— "
                    "状态差/摄影机路径/接力是必要条件，但仅靠它们镜头仍会失败"
                    "（一次 S03 实证）。补 §一.9 9 项".format(
                        len(interactive_segments),
                        "、".join(core_missing),
                        len(core_missing), len(core_fields))))

    # ---- MOTION-WHL：含「推车 / wheel / ride」但缺车轮耦合 ----
    wheel_seg = [s for s in interactive_segments
                 if re.search(r"\b(?:cart|pushcart|wheel|ride|drive|推车|骑)\b", s, re.I)]
    if wheel_seg and field_counts["道具/轮子从属运动"] == 0:
        level = "INFO" if archived else "WARN"
        out.append((level, "MOTION-WHL",
                    "{} 个推车 / 持物移动段缺「车轮耦合 / 链式运动」字段 —— "
                    "手把→踏步→身体→轮转→远景视差 五项方向不一致会让人物倒退 / "
                    "车轮反转（一次 S03 实证）".format(
                        len(wheel_seg))))

    # ---- MOTION-CC：含接触动词但缺接触点 / 承重 ----
    contact_seg = [s for s in interactive_segments
                   if CONTACT_MARKERS.search(s)]
    if contact_seg and field_counts["手-道具接触"] == 0:
        level = "INFO" if archived else "WARN"
        out.append((level, "MOTION-CC",
                    "{} 个接触动词段缺「手-道具接触点 / 承重」字段 —— "
                    "写「拿起杯子」不够；要写「拇指+食指夹杯柄、中指+无名指承杯底」".format(
                        len(contact_seg))))

    # ---- MOTION-FF：堆叠 `no / doesn't` 合同 + 缺正向机械示例 ----
    bad_neg = 0
    for seg in interactive_segments:
        # 找 integrated_multimodal_description 段更精准，但本启发式粗一点
        m = re.search(
            r"integrated_multimodal_description\s*:(.*?)(?:overall_soundscape|"
            r"non_diegetic_music|\Z)",
            seg, re.S | re.I)
        seg_text = m.group(1) if m else seg
        neg = len(CONTRACT_MARKERS.findall(seg_text))
        if neg >= 3:
            bad_neg += 1
    if bad_neg and field_counts["主体初始朝向"] == 0 and field_counts["脚步/重心"] == 0:
        level = "INFO" if archived else "WARN"
        out.append((level, "MOTION-FF",
                    "{} 个交互动作段堆叠 `no / doesn't / never` 类合同 "
                    "且缺正向机械示例 —— CFG=1 / Wan2.2 / H3 会复制关键词，"
                    "改正向（转身=头→肩→髋；行走=脚落地/承重；拿物=手指闭合/接触）".format(
                        bad_neg)))

    return out


# ====================================================================
# 聚合 + 主入口
# ====================================================================

def analyse(proj):
    """返回 (fail, warn, info, archived, arch_info)。

    简化：所有子检查只返回 List[(level, code, msg)]，
    archived/arch_info 由 analyse 自己从项目状态摘要统一解析，
    避免「不同子函数返回不同元数」导致解构错位。
    """
    all_fail, all_warn, all_info = [], [], []
    archived, arch_info = _has_fail_marker(_read(os.path.join(proj, "项目状态摘要.md")))

    for fn in (check_state_vs_disk, check_empty_templates,
               check_standard_dirs, check_prompt_discovery,
               check_route_distribution, check_duration_distribution,
               check_knife_whitelist, check_prompt_contract,
               check_segment_execution_fields,
               check_motion_contract):
        items = fn(proj)
        for lvl, code, msg in items:
            if lvl == "FAIL" and not archived:
                # 活跃项目：FAIL 阻断
                all_fail.append((code, msg))
            elif lvl == "FAIL":
                # 归档失败项目：FAIL → INFO，不阻断，但报告失败特征
                all_info.append((code, msg))
            elif lvl == "WARN":
                if archived:
                    all_info.append((code, msg))
                else:
                    all_warn.append((code, msg))
            else:
                all_info.append((code, msg))
    return all_fail, all_warn, all_info, archived, arch_info


def project_status(proj):
    """综合状态描述。"""
    fail, warn, info, archived, arch_info = analyse(proj)
    if archived and not fail:
        return "归档失败（已记录，不阻断）"
    if fail:
        return "FAIL（{} 项）".format(len(fail))
    if warn:
        return "WARN（{} 项）".format(len(warn))
    if info:
        return "PASS + INFO"
    return "PASS"


def _print_row(name, fail, warn, info, archived, arch_info):
    """单项目一行。"""
    if archived:
        tag = "归档失败（已记录）"
    elif fail:
        tag = "FAIL {} 项".format(len(fail))
    elif warn:
        tag = "WARN {} 项".format(len(warn))
    elif info:
        tag = "PASS ({} INFO)".format(len(info))
    else:
        tag = "PASS"
    print("  {:<30s} {}".format(name, tag))
    if archived and arch_info:
        print("      归档路径：{}".format(arch_info.get("归档路径", "?")))
    for code, msg in fail[:6]:
        print("      [FAIL] {}  {}".format(code, msg[:90]))
    for code, msg in warn[:4]:
        print("      [WARN] {}  {}".format(code, msg[:90]))
    for code, msg in info[:2]:
        print("      [INFO] {}  {}".format(code, msg[:80]))


def main():
    ap = argparse.ArgumentParser(
        description="项目合规闸（真实项目状态/产物/合规性）")
    ap.add_argument("--project", help="单项目目录（不传则扫全部）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.project:
        if not os.path.isdir(args.project):
            print("目录不存在：{}".format(args.project))
            return 2
        projs = [args.project]
    else:
        projs = _list_projects()
        if not projs:
            print("[未评估] 未发现 00-视频项目/ 下的在制项目，本闸没有可判对象")
            return 0

    if args.json:
        out = []
        for p in projs:
            fail, warn, info, archived, arch_info = analyse(p)
            out.append({
                "项目": os.path.basename(p),
                "路径": p,
                "已归档失败": archived,
                "归档信息": arch_info,
                "fail": [{"code": c, "msg": m} for c, m in fail],
                "warn": [{"code": c, "msg": m} for c, m in warn],
                "info": [{"code": c, "msg": m} for c, m in info],
            })
        print(json.dumps(out, ensure_ascii=False, indent=2))
        # 退出码：归档项目不阻断
        any_active_fail = any(
            len(o["fail"]) > 0 and not o["已归档失败"] for o in out)
        return 1 if any_active_fail else 0

    print("=" * 68)
    print("项目合规闸（活跃 {} 个，归档失败不阻断）".format(len(projs)))
    print("=" * 68)
    # 豁免登记只在无参全扫（非 --project 定点）模式生效
    waivers, werrors = ({}, []) if args.project else load_waivers()
    for e in werrors:
        print("⚠ " + e)
    active_fail, active_fail_names = 0, []
    waived = []
    n_arch = 0          # 归档失败项目：不算通过，也不算阻断 → 记「未评估」
    for p in projs:
        name = os.path.basename(p)
        fail, warn, info, archived, arch_info = analyse(p)
        wvd = bool(fail) and not archived and is_waived(waivers, name, GATE)
        _print_row(name, fail, warn, info, archived, arch_info)
        if wvd:
            print("      → WAIVED：FAIL 已登记豁免（tools/_film_gate_waivers.yaml），不计入失败")
            waived.append(name)
        elif fail and not archived:
            active_fail += 1
            active_fail_names.append(name)
        elif fail and archived:
            n_arch += 1
    print("-" * 68)
    # D4：汇总行 + 结论句必须与「通过/WAIVED/未评估/失败」四栏一致。
    # 旧版在没有豁免时也印「✓ 所有活跃项目无阻断项」，而归档失败项目明明
    # 没被判过——那是把「没判到」说成「判合格」。
    ok_n = len(projs) - len(waived) - n_arch - active_fail
    if waived:
        print("· 已豁免（WAIVED，登记于 tools/_film_gate_waivers.yaml）：{}"
              .format("、".join(waived)))
    if active_fail:
        print("✗ 活跃项目有 {} 个不通过：{}；归档失败项目已单独报告但不计入失败".format(
            active_fail, "、".join(active_fail_names)))
        print(tally_line(ok_n, len(waived), n_arch, active_fail))
        return 1
    print(tally_line(ok_n, len(waived), n_arch))
    if waived or n_arch:
        print("⚠ 有豁免/未评估（归档失败 {} 个），不算全绿".format(n_arch))
        return 0
    print("✓ 所有 {} 个活跃项目无阻断项".format(ok_n))
    return 0


# ====================================================================
# 自检：四类反例 + 两类正例
# ====================================================================

def _make_project(root, layout="conformant"):
    """构造临时项目结构。layout 决定内容。"""
    os.makedirs(root, exist_ok=True)
    summary = os.path.join(root, "项目状态摘要.md")
    checklist = os.path.join(root, "执行清单.md")
    storyboard = os.path.join(root, "03-分镜", "分镜表.md")
    prompt_summary = os.path.join(root, "04-镜头", "镜头提示词.md")
    assembly = os.path.join(root, "06-成片", "剪辑装配单.md")

    for d in ("00-立项", "01-剧本", "02-资产", "03-分镜",
              "04-镜头", "05-音频", "06-成片"):
        os.makedirs(os.path.join(root, d), exist_ok=True)

    if layout == "conformant":
        with open(summary, "w", encoding="utf-8") as f:
            f.write("# 项目状态摘要\n\n## 当前状态\n\n- 当前关卡：G6\n- "
                    "当前状态：通过\n")
            f.write("\n## 已通过决策\n\n| 事项 | 决策 |\n|---|---|\n"
                    "| 风格 | 工笔 |\n| 时长 | 60s |\n")
        with open(checklist, "w", encoding="utf-8") as f:
            f.write("# 执行清单\n\n## 关卡状态\n\n| 关卡 | 状态 |\n"
                    "|---|---|\n| G6 | 通过 |\n")
        # 合规分镜表：刀型白名单 + 时长宽窄搭配
        sb = ("| 镜 | 时段 | 刀型 | 景别 |\n|---|---|---|---|\n"
              "| S01 | 0.00–1.20 | 短刀 | 中景 |\n"
              "| S02 | 1.20–5.20 | 长刀 | 近景 |\n"
              "| S03 | 5.20–7.50 | 短刀 | 特写 |\n"
              "| S04 | 7.50–11.80 | 长刀 | 中景 |\n"
              "| S05 | 11.80–13.50 | 短刀 | 全景 |\n"
              "| S06 | 13.50–17.00 | 长刀 | 近景 |\n")
        Path(storyboard).write_text(sb, encoding="utf-8")
        # 合规提示词：含摄影机路径 + 9 项运动合同 + 无负面约束
        with open(prompt_summary, "w", encoding="utf-8") as f:
            f.write("# 镜头提示词\n\n## 摄影执行字段\n\n| 字段 | 值 |\n"
                    "|---|---|\n| 镜头叙事功能 | 揭示 |\n"
                    "| 主要观看重点 | 人物走入 |\n| 起始状态 | 门口 |\n"
                    "| 动作目标与结束状态 | 桌前 |\n| 运镜起点/过程/终点 | A→B→C |\n"
                    "| 焦点与焦点变化 | 浅景深 |\n| 屏幕方向/轴线 | 维持 |\n"
                    "| 时间码节拍 | 0-2-4 |\n| 生成段拆分理由 | 长 |\n\n")
            # 9 项运动合同（让 MOTION-* 不报警）
            f.write("## 演员调度与运动学合同\n\n"
                    "- 屏幕坐标与向量：从画面左侧 1/3 移向右侧 1/3\n"
                    "- 主体初始朝向：脸朝镜头偏右 30°\n"
                    "- 移动方向与世界坐标：沿画面右侧从前景走向远景\n"
                    "- 脚步/重心：起步脚、承重脚、落脚方向\n"
                    "- 手-道具接触点/承重/解除：右手拇指与食指夹住门把手\n"
                    "- 道具/轮子从属运动：手把→踏步→身体→远景视差\n"
                    "- 摄影机方向与主体相对速度：摄影机跟拍、远景动\n"
                    "- 轴线/视线：视线看向画面右侧同伴\n"
                    "- 结束状态：站在桌前、面向镜头\n\n")
            f.write("integrated_multimodal_description: slow dolly in\n"
                    "overall_soundscape: ok\n")
        # 合规装配单：100% 镜都是真实生成
        with open(assembly, "w", encoding="utf-8") as f:
            f.write("# 剪辑装配单\n\n| 轨道 | 剪辑镜头ID | 素材文件/版本 | "
                    "源入点 | 源出点 | 时间线入点 | 时间线出点 | 速度 | 转场 |\n"
                    "|---|---|---|---|---|---|---|---|---|\n"
                    "| V1 | S01 | clip/S01.mp4 | 0 | 1.2 | 0 | 1.2 | 100% | 硬切 |\n"
                    "| V1 | S02 | clip/S02.mp4 | 0 | 4.0 | 1.2 | 5.2 | 100% | 硬切 |\n"
                    "| V1 | S03 | clip/S03.mp4 | 0 | 2.3 | 5.2 | 7.5 | 100% | 硬切 |\n"
                    "| V1 | S04 | clip/S04.mp4 | 0 | 4.3 | 7.5 | 11.8 | 100% | 硬切 |\n")
        # 合规质检表
        Path(os.path.join(root, "06-成片", "成片质检表.md")).write_text(
            "# 成片质检表\n\n## G6 裁决\n\n- [x] 通过\n", encoding="utf-8")
    elif layout == "failed_film":
        # 失败片式：缺刀型、时长窄带、静帧为主、负面合同
        with open(summary, "w", encoding="utf-8") as f:
            f.write("# 项目状态摘要\n\n## 当前状态\n\n- 当前关卡：G6\n- "
                    "当前状态：通过\n")  # 故意声明通过（场景冲突）
            f.write("\n## 已通过决策\n\n| 事项 | 决策 |\n|---|---|\n\n")
        Path(checklist).write_text("# 执行清单\n", encoding="utf-8")
        # 分镜表：刀型用了「中刀」（白名单外），时长全在 4.5–5.5 窄带
        sb = ("| 镜 | 时段 | 刀型 | 景别 |\n|---|---|---|---|\n"
              "| S01 | 0.00–5.17 | 中刀 | 中景 |\n"
              "| S02 | 5.17–10.34 | 中刀 | 近景 |\n"
              "| S03 | 10.34–15.51 | 中刀 | 特写 |\n"
              "| S04 | 15.51–20.68 | 中刀 | 中景 |\n"
              "| S05 | 20.68–25.85 | 中刀 | 全景 |\n"
              "| S06 | 25.85–31.02 | 中刀 | 近景 |\n")
        Path(storyboard).write_text(sb, encoding="utf-8")
        # 镜头提示词：含完整执行字段（让 SEG-01 不报警），但有合同式反模式
        with open(prompt_summary, "w", encoding="utf-8") as f:
            f.write("# 镜头提示词\n\n## 摄影执行字段\n\n| 字段 | 值 |\n"
                    "|---|---|\n| 镜头叙事功能 | 揭示 |\n"
                    "| 主要观看重点 | 人物走入 |\n| 起始状态 | 门口 |\n"
                    "| 动作目标与结束状态 | 桌前 |\n| 运镜起点/过程/终点 | A→B→C |\n"
                    "| 焦点与焦点变化 | 浅景深 |\n| 屏幕方向/轴线 | 维持 |\n"
                    "| 时间码节拍 | 0-2-4 |\n| 生成段拆分理由 | 长 |\n\n")
            # 堆叠大量负面约束，让密度超阈值
            f.write("integrated_multimodal_description: [Shot 1] "
                    "The camera remains locked. No new person enters. "
                    "No text or subtitle appears. No eye emits light. "
                    "No weapon-like beam appears. No pipe becomes a handle. "
                    "No tool appears. No extra person or text appears. "
                    "No explosion occurs. No electric injury. "
                    "No extra limb, person, text or object appears. "
                    "The corridor geometry does not change.\n")
        # 装配单：4/6 = 67% 静帧 + 数字轻推（触发 ROUTE-01）
        with open(assembly, "w", encoding="utf-8") as f:
            f.write("# 剪辑装配单\n\n| 轨道 | 剪辑镜头ID | 素材文件/版本 | "
                    "源入点 | 源出点 | 时间线入点 | 时间线出点 | 速度 | 转场 |\n"
                    "|---|---|---|---|---|---|---|---|---|\n"
                    "| V1 | S01 | 静帧 | 0 | 5 | 0 | 5 | 数字轻推 | 硬切 |\n"
                    "| V1 | S02 | 静帧 | 0 | 5 | 5 | 10 | 数字轻推 | 硬切 |\n"
                    "| V1 | S03 | 静帧 | 0 | 5 | 10 | 15 | 数字轻推 | 硬切 |\n"
                    "| V1 | S04 | 静帧 | 0 | 5 | 15 | 20 | 数字轻推 | 硬切 |\n"
                    "| V1 | S05 | clip/S05.mp4 | 0 | 5 | 20 | 25 | 100% | 硬切 |\n"
                    "| V1 | S06 | clip/S06.mp4 | 0 | 5 | 25 | 30 | 100% | 硬切 |\n")
        # 故意不写质检表（缺关键交付件 → STATE-02）
    elif layout == "archived_failure":
        # 归档失败：声明失败裁决、归档路径、状态与磁盘可不一致
        with open(summary, "w", encoding="utf-8") as f:
            f.write("# 项目状态摘要\n\n## 当前状态\n\n- 当前关卡：G6\n- "
                    "当前状态：v01失败已归档\n")
            f.write("\n## 失败裁决\n\n- 失败版本：v01\n"
                    "- 失败类型：PPT感\n- 归档：06-成片/失败案例/v01/\n")
            f.write("\n## 已通过决策\n\n| 事项 | 决策 |\n|---|---|\n")
        # 故意不写分镜表 / 不写提示词（模拟「失败归档后停止依赖」）
        # 但保留剪辑装配单里的静帧特征
        os.makedirs(os.path.join(root, "06-成片", "失败案例", "v01"), exist_ok=True)
        with open(assembly, "w", encoding="utf-8") as f:
            f.write("# 剪辑装配单\n\n| 轨道 | 剪辑镜头ID | 素材文件/版本 | "
                    "源入点 | 源出点 | 时间线入点 | 时间线出点 | 速度 | 转场 |\n"
                    "|---|---|---|---|---|---|---|---|---|\n"
                    "| V1 | S01 | 静帧 | 0 | 5 | 0 | 5 | 数字轻推 | 硬切 |\n")
        Path(os.path.join(root, "06-成片", "成片质检表.md")).write_text(
            "# 成片质检表\n\n## G6 裁决\n\n- [x] 失败归档\n", encoding="utf-8")
    elif layout == "pure_template":
        # 仅复制模板：所有关键字段空白
        Path(summary).write_text(
            "# 项目状态摘要\n\n## 当前状态\n\n## 已通过决策\n\n"
            "| 事项 | 决策 |\n|---|---|\n\n", encoding="utf-8")
        Path(checklist).write_text("# 执行清单\n", encoding="utf-8")
        # 分镜表：单行 S01，时长 5.17（窄带内）
        sb = ("| 镜号 | 时段 | 刀型 |\n|---|---|---|\n| S01 | 0.00–5.17 | 长刀 |\n")
        Path(storyboard).write_text(sb, encoding="utf-8")
        Path(prompt_summary).write_text("# 镜头提示词\n", encoding="utf-8")
        # 模板预填的剪辑装配单 S01 行（速度=数字轻推）
        Path(assembly).write_text(
            "# 剪辑装配单\n\n| 轨道 | 剪辑镜头ID | 素材文件/版本 | 源入点 | 源出点 "
            "| 时间线入点 | 时间线出点 | 速度 | 转场 |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| V1 | S01 | . | 0 | 0 | 0 | 0 | 100% | 硬切 |\n", encoding="utf-8")
        Path(os.path.join(root, "06-成片", "成片质检表.md")).write_text(
            "# 成片质检表\n\n## G6 裁决\n\n- [x] 待填\n", encoding="utf-8")
    elif layout == "bypass_dir":
        # 旁路目录：提示词写在非标准目录
        os.makedirs(os.path.join(root, "H3_提示词"), exist_ok=True)
        Path(os.path.join(root, "H3_提示词", "s01.txt")).write_text(
            "integrated_multimodal_description: ok\n", encoding="utf-8")
        # 标准目录关键件都齐
        with open(summary, "w", encoding="utf-8") as f:
            f.write("# 项目状态摘要\n\n## 当前状态\n\n- 当前关卡：G4\n- "
                    "当前状态：进行中\n")
            f.write("\n## 已通过决策\n\n| 事项 | 决策 |\n|---|---|\n"
                    "| 风格 | 工笔 |\n")
        Path(checklist).write_text(
            "# 执行清单\n\n## 关卡状态\n\n| 关卡 | 状态 |\n|---|---|\n| G4 | 进行中 |\n",
            encoding="utf-8")
        sb = "| 镜 | 时段 | 刀型 | 景别 |\n|---|---|---|---|\n| S01 | 0.00–5.0 | 长刀 | 中景 |\n"
        Path(storyboard).write_text(sb, encoding="utf-8")
        # 关键件都齐
        Path(prompt_summary).write_text("# 镜头提示词\n", encoding="utf-8")
        Path(assembly).write_text(
            "# 剪辑装配单\n\n| 轨道 | 剪辑镜头ID | 素材文件/版本 | 源入点 | 源出点 "
            "| 时间线入点 | 时间线出点 | 速度 | 转场 |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| V1 | S01 | clip/S01.mp4 | 0 | 5 | 0 | 5 | 100% | 硬切 |\n",
            encoding="utf-8")
        Path(os.path.join(root, "06-成片", "成片质检表.md")).write_text(
            "# 成片质检表\n\n## G6 裁决\n\n- [x] 待填\n", encoding="utf-8")
    elif layout == "motion_gap":
        """演员调度 / 运动学合同缺失：含交互动作但缺 §一.9 9 项 → 触发 MOTION-* WARN。
        用于测试 `check_motion_contract` 与回归保护。
        """
        with open(summary, "w", encoding="utf-8") as f:
            f.write("# 项目状态摘要\n\n## 当前状态\n\n- 当前关卡：G4\n- "
                    "当前状态：进行中\n")
            f.write("\n## 已通过决策\n\n| 事项 | 决策 |\n|---|---|\n"
                    "| 风格 | 工笔 |\n| 时长 | 60s |\n")
        Path(checklist).write_text(
            "# 执行清单\n\n## 关卡状态\n\n| 关卡 | 状态 |\n|---|---|\n| G4 | 进行中 |\n",
            encoding="utf-8")
        sb = "| 镜 | 时段 | 刀型 | 景别 |\n|---|---|---|---|\n| S01 | 0.00–5.0 | 长刀 | 中景 |\n"
        Path(storyboard).write_text(sb, encoding="utf-8")
        # 镜头提示词：含交互动作强信号（walks / picks / sits / grips / cart / push）
        # + 堆叠 no / doesn't + 缺 §一.9 9 项
        with open(prompt_summary, "w", encoding="utf-8") as f:
            f.write("# 镜头提示词\n\n## 摄影执行字段\n\n| 字段 | 值 |\n"
                    "|---|---|\n| 镜头叙事功能 | 揭示 |\n"
                    "| 主要观看重点 | 人物走入 |\n| 起始状态 | 门口 |\n"
                    "| 动作目标与结束状态 | 桌前 |\n| 运镜起点/过程/终点 | A→B→C |\n"
                    "| 焦点与焦点变化 | 浅景深 |\n| 屏幕方向/轴线 | 维持 |\n"
                    "| 时间码节拍 | 0-2-4 |\n| 生成段拆分理由 | 长 |\n\n")
            # 触发 MOTION-CT（缺 4 核心字段）+ MOTION-WHL（推车）+ MOTION-CC（接触）
            # + MOTION-FF（堆叠 no / doesn't）
            f.write("integrated_multimodal_description: [Shot 1] The woman "
                    "walks toward the door and picks up the cup, then sits "
                    "down. She grips the cup handle and pushes the cart. "
                    "No backward step. No sliding. No freeze. No jitter.\n")
        Path(assembly).write_text(
            "# 剪辑装配单\n\n| 轨道 | 剪辑镜头ID | 素材文件/版本 | 源入点 | 源出点 "
            "| 时间线入点 | 时间线出点 | 速度 | 转场 |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| V1 | S01 | clip/S01.mp4 | 0 | 5 | 0 | 5 | 100% | 硬切 |\n",
            encoding="utf-8")
        Path(os.path.join(root, "06-成片", "成片质检表.md")).write_text(
            "# 成片质检表\n\n## G6 裁决\n\n- [x] 待填\n", encoding="utf-8")
    return root


def selftest():
    """5 类覆盖：失败片式 / 纯模板 / 合规 / 归档失败 / 旁路目录。"""
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        # ---- 1. 合规样例 → 不应阻断 ----
        p = _make_project(os.path.join(td, "conformant"), "conformant")
        fail, warn, info, archived, _ = analyse(p)
        if fail:
            print("[自检失败] 合规样例被误报 FAIL：")
            for c, m in fail:
                print("   -", c, m)
            ok = False
        else:
            print("[自检通过] 合规样例无阻断项（warn={}, info={}）".format(
                len(warn), len(info)))

        # ---- 2. 失败片式 → 应有 FAIL（静帧/时长窄带）+ WARN（刀型未知/合同式）----
        p = _make_project(os.path.join(td, "failed"), "failed_film")
        fail, warn, info, archived, _ = analyse(p)
        fail_codes = {c for c, _ in fail}
        warn_codes = {c for c, _ in warn}
        want_fail = {"ROUTE-01", "DUR-01"}
        want_warn = {"KNIFE-01", "PROMPT-CT"}
        miss_fail = want_fail - fail_codes
        miss_warn = want_warn - warn_codes
        if miss_fail or miss_warn:
            print("[自检失败] 失败片式缺关键项：")
            if miss_fail:
                print("   缺 FAIL: {}（实际 {}）".format(
                    miss_fail, sorted(fail_codes)))
            if miss_warn:
                print("   缺 WARN: {}（实际 {}）".format(
                    miss_warn, sorted(warn_codes)))
            ok = False
        else:
            print("[自检通过] 失败片式被抓住：FAIL={} WARN={}".format(
                sorted(fail_codes), sorted(warn_codes)))

        # ---- 3. 归档失败项目 → 不应 FAIL（STATE 系列转 INFO），仍报告失败特征 ----
        p = _make_project(os.path.join(td, "archived"), "archived_failure")
        fail, warn, info, archived, arch = analyse(p)
        if not archived:
            print("[自检失败] 归档失败项目未被识别为归档")
            ok = False
        elif fail:
            print("[自检失败] 归档失败项目被错误阻断 FAIL：")
            for c, m in fail:
                print("   -", c, m)
            ok = False
        elif not arch or "PPT" not in str(arch):
            print("[自检失败] 归档失败项目的失败特征未被报告：{}".format(arch))
            ok = False
        else:
            print("[自检通过] 归档失败项目不阻断，失败特征保留：{}".format(
                arch.get("类型")))

        # ---- 4. 纯模板 → 应有 TPL/SEG 提示（INFO/WARN）----
        p = _make_project(os.path.join(td, "template"), "pure_template")
        fail, warn, info, archived, _ = analyse(p)
        # 已通过决策表为空 → TPL-01；缺执行字段 → SEG-01
        all_codes = {c for c, _ in (fail + warn + info)}
        need = {"TPL-01", "SEG-01"}
        if not need & all_codes:
            print("[自检失败] 纯模板未被识别（缺 TPL/SEG）：{}".format(all_codes))
            ok = False
        else:
            print("[自检通过] 纯模板被发现：codes={}".format(
                sorted(all_codes)[:5]))

        # ---- 5. 旁路目录 → DIR-01 / PROMPT-02 ----
        p = _make_project(os.path.join(td, "bypass"), "bypass_dir")
        fail, warn, info, archived, _ = analyse(p)
        all_codes = {c for c, _ in (fail + warn + info)}
        if "DIR-01" not in all_codes and "PROMPT-02" not in all_codes:
            print("[自检失败] 旁路目录未被识别：{}".format(all_codes))
            ok = False
        else:
            print("[自检通过] 旁路目录被发现：codes={}".format(
                sorted(all_codes)[:5]))

        # ---- 6. 运动合同缺失 → MOTION-CT / MOTION-WHL / MOTION-CC / MOTION-FF ----
        p = _make_project(os.path.join(td, "motion"), "motion_gap")
        fail, warn, info, archived, _ = analyse(p)
        warn_codes = {c for c, _ in warn}
        want_motion = {"MOTION-CT", "MOTION-WHL", "MOTION-CC", "MOTION-FF"}
        miss_motion = want_motion - warn_codes
        if miss_motion:
            print("[自检失败] 运动合同缺失未被识别（缺 {}）：实际 {}".format(
                miss_motion, sorted(warn_codes)))
            ok = False
        else:
            print("[自检通过] 运动合同缺失被发现：{}".format(
                sorted(want_motion)))

        # ---- 7. D8 三档：常规 属白名单（不报 KNIFE-01），越档写成 5.5s 必须报 KNIFE-02 ----
        # 旧版这条分支的逐行取刀型是死代码（只留表头行），越档永远不响；
        # 这里同时锁住「常规 不再被当未知值」和「时长×刀型交叉真的跑得起来」。
        p = _make_project(os.path.join(td, "knife_band"), "conformant")
        sb = ("| 镜号 | 时段 | 刀型 | 景别 |\n|---|---|---|---|\n"
              "| S01 | 0.00–1.20 | 短刀 | 中景 |\n"
              "| S02 | 1.20–4.20 | 常规 | 近景 |\n"
              "| S03 | 4.20–9.70 | 常规 | 特写 |\n"     # 常规写在 5.5s → 越档
              "| S04 | 9.70–10.50 | 短刀 | 全景 |\n"
              "| S05 | 10.50–15.00 | 长刀 | 中景 |\n"
              "| S06 | 15.00–17.40 | 常规 | 近景 |\n")
        Path(os.path.join(p, "03-分镜", "分镜表.md")).write_text(sb, encoding="utf-8")
        fail, warn, info, archived, _ = analyse(p)
        all_codes = {c for c, _ in (fail + warn + info)}
        if "KNIFE-02" not in all_codes:
            print("[自检失败] 常规 写成 5.5s 未报 KNIFE-02（逐行刀型没取到）：{}"
                  .format(sorted(all_codes)))
            ok = False
        elif "KNIFE-01" in all_codes:
            print("[自检失败] 三档白名单误判：「常规」被当未知值（KNIFE-01）")
            ok = False
        else:
            print("[自检通过] 三档越档被抓住（KNIFE-02），且「常规」不报 KNIFE-01")

    print("=" * 68)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
