#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分镜结构闸（手动）· 运镜结构审计 —— 抓「单镜好看、拼起来像 PPT」。

**为什么需要**
一次失败复盘记下的病因（locked/fixed 占主导、静帧轻推变成主体路线），
某失败样片原样复发：静止 86%、最长连击 14 镜、空镜/插入镜 0。
规则写在文档里不等于被执行 —— 本工具把导演规则变成可数的结构检查。

**与 check_shot_duration_variance.py 的分工（互不替代）**
  · 切点均质度闸：管「时长」维度 —— 节拍器、长短刀、生成内多刀
  · 本闸：管「运镜结构」维度 —— 静止占比、静止连击、镜型配比、平均时长

**阈值来源（不是拍脑袋）**
对 历史样本 16 条公认优秀 AI 成片逐帧实测推导，
方法、数据与推导过程见本文件阈值注释与 `--selftest` 反例。
叙事型实测：静止 20–43%（中位 29%）、连击 1–7（中位 3）、均长 1.9–4.7s。
**画册式短片（如一部 100% 静止仍成立的画册式短片）对本闸全部豁免，人工确认片型后放行。**

**查什么**（对象是 `03-分镜/分镜表.md`）
  ① 静止机位占比（叙事片 >50% 退出码 1；意象片豁免）
  ② 最长连续静止段（叙事片 >5 镜退出码 1，理想 ≤3；意象片豁免）
  ③ 平均镜头时长（2.0–5.5s）
  ④ 等距切点占比（≤40%）
  ⑤ 镜型配比缺口（只记录，不生成补拍清单，不为过闸插镜）
  运镜只读摄影机路径/机位字段，主体动作与台词中的推/拉/摇不算运镜。

**用法**
    python tools/check_shot_structure.py <项目目录或分镜表.md> [--json]
    python tools/check_shot_structure.py            # 扫全部在制项目（归档豁免）
    python tools/check_shot_structure.py --selftest

**退出码**：0 通过（镜型偏少不失败）/ 1 有超标项 / 2 用法或自检失败

**注册状态**：已注册进 run_all_checks 常驻闸（`运镜结构-真片` 无参扫全部
在制项目 + `运镜结构-selftest`）。
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

FAIL_MARK_RE = re.compile(r"##\s*失败裁决")

from _art_exception import waiver_note
from _film_gate_waivers import load_waivers, is_waived
from _film_type import read_film_type

GATE = "运镜结构-真片"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------------------------------------------------------------------
# 配方常量：一集成片的镜头结构配额
# 数值来源：2026-10 对 历史样本 16 条公认优秀 AI 成片的逐帧实测
#（方法与数据见本文件阈值注释，
#  测量工具：外部 seek 项目/05_工作流与Skills/harvest/shot_metrics_probe.py）。
# 叙事型参考片实测：静止占比 20–43%（中位 29%）、最长静止连击 1–7（中位 3）、
# 平均镜头时长 1.9–4.7s（中位 3.2s）。
# 阈值 = 实测上限 + 余量。2026-10-31 起，叙事片静止占比与连续静止超线
# 改为退出码 1：原先只提醒，静止 86%、连击 14 镜的失败样片仍能进 G4。
# ---------------------------------------------------------------------------

# 理想运镜配额（软目标，用于文案与建议，不做硬判定）
MOVEMENT_QUOTA = {
    "固定": 0.30,
    "推拉": 0.25,
    "横移摇": 0.15,
    "跟拍": 0.15,
    "升降环绕": 0.10,
    "手持": 0.05,
}

# 叙事片静止机位占比硬线：实测最高 43.1%，超过 50% 退出码 1。
# 意象片豁免。2026-10-31 起由提醒改为硬失败。
STATIC_RATIO_WARN = 0.50

SHOT_TYPE_QUOTA = {
    "主叙事": 0.40,
    "反应": 0.20,
    "插入细节": 0.15,
    "空镜": 0.12,
    "过渡": 0.13,
}

# 叙事片连续静止硬线。短片实测上限 5 镜，理想 ≤3。超过 5 镜退出码 1。
# 意象片豁免。更长的片子若必须超过 5 镜，走豁免登记，不把此项改回提醒。
MAX_CONSECUTIVE_STATIC = 5
MAX_CONSECUTIVE_STATIC_IDEAL = 3

# 时长健康区间（秒）。实测叙事型中位 3.2s、范围 1.9–4.7s。
DURATION_TARGET = {
    "mean_min": 2.0,
    "mean_max": 5.5,
    "min_floor": 0.8,
    "max_ceiling": 9.0,
    # 相邻镜头时长比：低于这个值说明切点等距，节奏僵
    "adjacent_ratio": 1.5,
}

# ---- 等距切点口径（D5c：唯一实现，check_shot_duration_variance 直接 import）----
# 两个闸曾对同一批时长给出相反结论：结构闸判「等距切点 89% 超标」EXIT=1，
# 时长闸只看 std 与长短刀，19 镜 × 2.9s 的等距表 std=0 才红、2.9s 恰好
# 落在长短刀带内就全绿。数字只在这里定义一次，另一处导入，防两处漂移。
FLAT_PAIR_RATIO = DURATION_TARGET["adjacent_ratio"]   # 相邻时长比 < 1.5 = 一对「几乎等长」
FLAT_PAIR_MAX = 0.40                                  # 等距对占比 > 40% = 节奏失败


def flat_pairs_count(durations):
    """相邻两镜时长比 < FLAT_PAIR_RATIO 的对数。"""
    n = 0
    for a, b in zip(durations, durations[1:]):
        try:
            a, b = float(a), float(b)
        except (TypeError, ValueError):
            continue
        if a <= 0 or b <= 0:
            continue
        if max(a, b) / min(a, b) < FLAT_PAIR_RATIO:
            n += 1
    return n


def flat_ratio(durations):
    """等距切点占比 = 等距对数 / (镜数-1)；单镜返回 0。"""
    if len(durations) < 2:
        return 0.0
    return flat_pairs_count(durations) / (len(durations) - 1)

MOVEMENT_KEYWORDS = [
    ("手持", ["手持", "肩扛", "呼吸感", "微晃", "晃动", "不稳定"]),
    ("升降环绕", ["环绕", "环拍", "绕", "升降", "俯仰", "上升", "下降", " crane"]),
    ("跟拍", ["跟拍", "跟随", "跟摄", "跟着", "追随"]),
    ("横移摇", ["横移", "平移", "侧移", "摇", "摇摄", "扫过", "掠过"]),
    ("推拉", ["推近", "推进", "微推", "推", "拉远", "后退", "拉近", "拉"]),
    ("固定", ["固定", "静止", "不动", "三脚架"]),
]

EMPTY_SHOT_HINTS = ["空镜", "环境", "氛围", "风景", "无人", "静物", "外景",
                    "天空", "街景", "窗外", "房间空", "空无一"]
INSERT_HINTS = ["特写", "局部", "手指", "手部", "物件", "细节", "纹理"]
REACTION_HINTS = ["反应", "看向", "愣", "怔", "沉默", "停顿", "眼神", "表情"]
TRANSITION_HINTS = ["过渡", "过场", "接力", "转场", "切入", "淡入"]


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

def parse_table(path):
    """解析首个含镜头 ID 列的 markdown 表格。"""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    tables, current = [], []
    for ln in lines:
        s = ln.strip()
        if s.startswith("|"):
            current.append([c.strip() for c in s.strip("|").split("|")])
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)

    for table in tables:
        if len(table) < 2:
            continue
        header = table[0]
        normalized = {re.sub(r"[\s（）()]", "", h) for h in header}
        if not normalized.intersection({"剪辑镜头ID", "镜头ID", "镜号"}):
            continue
        rows = []
        for cells in table[1:]:
            if re.fullmatch(r"[-: ]+", "".join(cells)):
                continue
            if len(cells) < len(header):
                cells += [""] * (len(header) - len(cells))
            rows.append(dict(zip(header, cells[: len(header)])))
        return header, rows
    return [], []


def _pick(row, *names):
    """按候选列名取值，忽略列名中的空格与序号。"""
    norm = {re.sub(r"[\s（）()]", "", k): v for k, v in row.items()}
    for n in names:
        for cand in (n, n.replace("剪辑", ""), n + "编号"):
            c = re.sub(r"[\s（）()]", "", cand)
            if c in norm:
                return norm[c]
    for k in norm:
        for n in names:
            if re.sub(r"[\s（）()]", "", n) in k:
                return norm[k]
    return ""


def to_float(v, default=0.0):
    m = re.search(r"-?\d+(?:\.\d+)?", str(v or ""))
    return float(m.group()) if m else default


# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------

def detect_movement(row):
    """只从摄影机与机位字段识别运镜，避免主体动作词污染。"""
    text = " ".join([_pick(row, "摄影机路径", "运镜", "镜头运动", "机位/焦段", "机位", "焦段")])
    for label, kws in MOVEMENT_KEYWORDS:
        for kw in kws:
            if kw in text:
                return label
    return "未标注"


def classify_shot(row, duration):
    """启发式镜头类型分类，置信度低时返回 待确认。"""
    func = _pick(row, "本镜叙事功能", "叙事功能")
    scale = _pick(row, "景别")
    action = _pick(row, "主体动作", "动作")
    dialogue = _pick(row, "台词", "台词/声音")

    blob = f"{func} {scale} {action}"

    if any(h in blob for h in EMPTY_SHOT_HINTS):
        return "空镜"
    if any(h in scale for h in INSERT_HINTS) and not dialogue:
        return "插入细节"
    if any(h in blob for h in REACTION_HINTS):
        return "反应"
    if any(h in func for h in TRANSITION_HINTS):
        return "过渡"
    if dialogue or duration >= 4.0:
        return "主叙事"
    return "待确认"


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------

def audit(rows, film_type="叙事"):
    shots = []
    for r in rows:
        sid = _pick(r, "剪辑镜头ID", "镜头ID", "镜号")
        if not sid:
            continue
        dur = to_float(_pick(r, "时长"))
        mv = detect_movement(r)
        shots.append({
            "id": sid,
            "duration": dur,
            "movement": mv,
            "type": classify_shot(r, dur),
            "scale": _pick(r, "景别"),
            "function": _pick(r, "本镜叙事功能", "叙事功能"),
        })

    n = len(shots)
    if n == 0:
        return None

    total = sum(s["duration"] for s in shots)
    mean = total / n if n else 0

    # 运镜分布
    mv_count = {}
    for s in shots:
        mv_count[s["movement"]] = mv_count.get(s["movement"], 0) + 1

    # 镜头类型分布
    tp_count = {}
    for s in shots:
        tp_count[s["type"]] = tp_count.get(s["type"], 0) + 1

    # 连续静止段
    runs, cur = [], 0
    for s in shots:
        if s["movement"] in ("固定", "未标注"):
            cur += 1
        else:
            if cur > 0:
                runs.append(cur)
            cur = 0
    if cur > 0:
        runs.append(cur)

    # 相邻时长比：统计"时长几乎一样"的相邻对（口径见 flat_pairs_count）
    flat_pairs = flat_pairs_count([s["duration"] for s in shots])

    return {
        "shot_count": n,
        "total_duration": round(total, 1),
        "mean_duration": round(mean, 2),
        "movement_count": mv_count,
        "type_count": tp_count,
        "static_runs": runs,
        "max_static_run": max(runs) if runs else 0,
        "flat_pairs": flat_pairs,
        "shots": shots,
        "film_type": film_type,
    }


def build_findings(res):
    """生成诊断结论与量化缺口。"""
    n = res["shot_count"]
    film_type = res.get("film_type", "叙事")
    findings = []

    # 1 运镜配额
    static_n = res["movement_count"].get("固定", 0) + res["movement_count"].get("未标注", 0)
    static_ratio = static_n / n if n else 0
    imagery = film_type == "意象"
    static_pass = imagery or static_ratio <= STATIC_RATIO_WARN
    findings.append({
        "项": "静止机位占比",
        "当前": f"{static_n}/{n} = {static_ratio:.0%}",
        "目标": "意象片允许静止占主导" if imagery else f"≤ {STATIC_RATIO_WARN:.0%}（叙事型实测上限 43%）",
        "判定": "通过" if static_pass else "超标",
        "缺口": 0 if static_pass else max(0, int(static_n - n * STATIC_RATIO_WARN)),
        "说明": "意象片静止镜头由立意与构图承担节奏，不因此失败。" if imagery
                else "叙事片超过 50% 即不进入 G4，打回重拆；不靠插入空镜过闸。",
    })

    # 2 连续静止
    run_pass = imagery or res["max_static_run"] <= MAX_CONSECUTIVE_STATIC
    findings.append({
        "项": "最长连续静止段",
        "当前": f"{res['max_static_run']} 镜",
        "目标": "意象片不设连击硬线" if imagery else f"≤ {MAX_CONSECUTIVE_STATIC} 镜（理想 ≤{MAX_CONSECUTIVE_STATIC_IDEAL}，实测中位）",
        "判定": "通过" if run_pass else "超标",
        "缺口": 0 if run_pass else max(0, res["max_static_run"] - MAX_CONSECUTIVE_STATIC),
        "说明": "意象片连续静止不因此失败。" if imagery
                else "叙事片连击超过 5 镜即不进入 G4，打回重拆这场的刀，不为配额补镜。",
    })

    # 3 平均时长
    mean = res["mean_duration"]
    lo, hi = DURATION_TARGET["mean_min"], DURATION_TARGET["mean_max"]
    findings.append({
        "项": "平均镜头时长",
        "当前": f"{mean:.2f}s",
        "目标": f"{lo}–{hi}s",
        "判定": "通过" if lo <= mean <= hi else "偏长" if mean > hi else "偏短",
        "缺口": 0,
        "说明": "单镜装下一个完整动作会导致平均时长偏长。正确做法是把一个动作切成多刀。",
    })

    # 4 等距切点
    flat = res["flat_pairs"] / max(1, n - 1)
    findings.append({
        "项": "等距切点占比",
        "当前": f"{res['flat_pairs']}/{max(1, n - 1)} = {flat:.0%}",
        "目标": f"≤ {FLAT_PAIR_MAX:.0%}",
        "判定": "通过" if flat <= FLAT_PAIR_MAX else "超标",
        "缺口": 0,
        "说明": "相邻镜头时长接近（比值<1.5）说明切点是按信息量均分的，而非按动作切。",
    })

    # 5 镜头类型配比
    for tp, q in SHOT_TYPE_QUOTA.items():
        cnt = res["type_count"].get(tp, 0)
        target = int(round(n * q))
        gap = target - cnt
        if gap > 0:
            findings.append({
                "项": f"「{tp}」镜数量",
                "当前": f"{cnt} 镜 ({cnt / n:.0%})",
                "目标": f"{target} 镜 ({q:.0%})",
                "判定": "偏少" if gap > 0 else "通过",
                "缺口": gap,
                "说明": {
                    "空镜": "数量只记录。缺了就重拆这场的刀，不为配额补一段无因果的空镜。",
                    "插入细节": "数量只记录。局部特写必须承接已有动作或道具，不为配额硬插。",
                    "反应": "数量只记录。反应镜必须接在已有台词或动作之后，不为配额硬插。",
                    "过渡": "数量只记录。场与场的衔接用已写明的接力，不为配额硬插。",
                    "主叙事": "数量只记录。占比高说明这场还没拆出停顿，打回重拆。",
                }.get(tp, ""),
            })

    return findings


# 补拍清单已停用（2026-10-31）：镜型缺口打回重拆，不再建议插入无因果的空镜。


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def render_text(res, findings, path):
    L = []
    A = L.append
    A("=" * 68)
    A("分镜质感审计报告")
    A("=" * 68)
    A(f"文件：{path}")
    A(f"镜头数：{res['shot_count']}    总时长：{res['total_duration']}s    "
      f"平均：{res['mean_duration']}s")
    A("")

    A("-" * 68)
    A("一、运镜分布（现状）")
    A("-" * 68)
    for k, v in sorted(res["movement_count"].items(), key=lambda x: -x[1]):
        bar = "█" * int(v / max(1, res["shot_count"]) * 40)
        A(f"  {k:<8} {v:>3} 镜  {bar}")
    A("")

    A("-" * 68)
    A("二、镜头类型分布（启发式，仅供参考）")
    A("-" * 68)
    for k, v in sorted(res["type_count"].items(), key=lambda x: -x[1]):
        A(f"  {k:<8} {v:>3} 镜  ({v / res['shot_count']:.0%})")
    A("")

    A("-" * 68)
    A("三、诊断结论")
    A("-" * 68)
    for f in findings:
        mark = {"通过": "[OK]", "超标": "[!!]", "偏少": "[!!]",
                "偏长": "[!!]", "偏短": "[!!]"}.get(f["判定"], "[?]")
        A(f"{mark} {f['项']}")
        A(f"     当前 {f['当前']}   目标 {f['目标']}   判定 {f['判定']}")
        if f["说明"]:
            A(f"     → {f['说明']}")
    A("")

    A("-" * 68)
    A("四、导演复核（结构事实，不是自动补拍配额）")
    A("-" * 68)
    A("  · 叙事片静止占比超过 50% 或连续静止超过 5 镜：退出码 1，打回重拆")
    A("  · 镜型偏少只记录，不生成补拍清单，也不为配额插空镜或反应镜")
    A("  · 意象片允许静止占主导，不因此失败")
    A("  · 若动作只有结果态，回到分镜补齐开始—过程—结果，不靠后期抖动伪装运动")
    A("  · 可用 J-cut / L-cut 或声音标点改善衔接，但不替代缺失的动作与表演")
    A("=" * 68)
    return "\n".join(L)


# ---------------------------------------------------------------------------
# 无参模式：扫全部在制项目（归档失败项目豁免，与 check_hook_density.py 同款）
# ---------------------------------------------------------------------------

def find_storyboard(proj):
    for rel in ("03-分镜/分镜表.md", "03-分镜/分镜表.txt",
                "02-分镜与镜头/分镜表.md"):
        fp = os.path.join(proj, *rel.split("/"))
        if os.path.isfile(fp):
            return fp
    return None


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
    unevaluated = [os.path.basename(p) for p in all_projs if not find_storyboard(p)]
    for name in unevaluated:
        print("  {:<28s} [未评估] 无分镜表".format(name))
    if not projs:
        print("[未评估] 未发现带 03-分镜/分镜表.md 的在制项目，本闸没有可判对象")
        return 0
    active_bad, arch_bad, waived = [], [], []
    for p in projs:
        name = os.path.basename(p)
        sb = find_storyboard(p)
        arch = _is_archived(p)
        header, rows = parse_table(sb)
        film_type, film_source = read_film_type(p)
        res = audit(rows, film_type) if rows else None
        if not res:
            hard = [{"项": "分镜表结构", "当前": "未解析到镜头行",
                     "目标": "主表含 镜号/时长 等列（模板结构）", "判定": "超标"}]
            wvd = is_waived(waivers, name, GATE)
            tag = ("WAIVED（分镜表结构不合模板，已登记豁免）" if wvd
                   else "✗ 分镜表结构不合模板（未解析到镜头）")
            print("  {:<28s} {}".format(name, tag))
            if wvd:
                waived.append(name)
            elif arch:
                arch_bad.append((name, hard))
            else:
                active_bad.append((name, hard))
            continue
        findings = build_findings(res)
        hard = [f for f in findings if f["判定"] in ("超标", "偏长", "偏短")]
        still_note = waiver_note(p, "静止比例")
        if still_note.startswith("艺术破例生效"):
            hard = [f for f in hard if f["项"] not in ("静止机位占比", "最长连续静止段")]
            print("    · {}".format(still_note))
        elif still_note:
            print("    · {}".format(still_note))
        wvd = bool(hard) and is_waived(waivers, name, GATE)
        if wvd:
            tag = "WAIVED（{} 条超标，已登记豁免）".format(len(hard))
        else:
            tag = "✗ {} 条超标".format(len(hard)) if hard else "✓"
        print("  {:<28s} 镜数={:<3d} {}".format(name, res["shot_count"], tag))
        if hard:
            if wvd:
                waived.append(name)
            elif arch:
                arch_bad.append((name, hard))
            else:
                active_bad.append((name, hard))
    for name, hard in active_bad:
        print("\n⚠ {}：".format(name))
        for f in hard[:8]:
            print("   ✗ {}：当前 {}（目标 {}）".format(f["项"], f["当前"], f["目标"]))
        if len(hard) > 8:
            print("   … 另有 {} 条".format(len(hard) - 8))
    if arch_bad:
        print("\n· 归档失败项目（已记录不阻断）：")
        for name, hard in arch_bad:
            print("  {}：{} 条超标".format(name, len(hard)))
    if waived:
        print("\n· 已豁免（WAIVED，登记于 tools/_film_gate_waivers.yaml）：{}"
              .format("、".join(waived)))
    if active_bad:
        print("\n  修法：叙事片打回重拆。静止占比 ≤50%、最长静止连击 ≤5、"
              "平均时长 2.0–5.5s、等距切点 ≤40%。不要为过闸插入空镜或反应镜。")
        if waived:
            print("· 豁免计数：{} 个项目 WAIVED；未豁免仍红：{}".format(
                len(waived), "、".join(n for n, _ in active_bad)))
        return 1
    print("✓ 在制项目运镜结构全部合格")
    if waived:
        print("· 豁免计数：{} 个项目在本闸 WAIVED".format(len(waived)))
    return 0


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

_SELFTEST_HEALTHY = """| 镜号 | 时长 | 机位/焦段 | 景别 | 本镜叙事功能 | 主体动作 | 台词 |
|---|---|---|---|---|---|---|
| S01 | 1.2s | 固定 35mm | 特写 | 起始局部 | 手指摩挲纸边 | |
| S02 | 2.5s | 推进 35mm | 中景 | 发展 | 她抬头看向窗外 | |
| S03 | 1.5s | 横移 50mm | 空镜 | 空镜·氛围 | 窗外光斑移动 | |
| S04 | 3.0s | 跟拍 35mm | 中景 | 发展 | 她起身走向门口 | 等等我 |
| S05 | 1.0s | 手持 35mm | 特写 | 反应·表情 | 他愣住，眼神偏移 | |
| S06 | 2.0s | 环绕 24mm | 全景 | 过渡·转场 | 走廊尽头光影变化 | |
| S07 | 3.5s | 推近 50mm | 中近景 | 结果 | 她停下来回头 | 你真的要走？ |
"""

_SELFTEST_SICK = """| 镜号 | 时长 | 机位/焦段 | 景别 | 本镜叙事功能 | 主体动作 | 台词 |
|---|---|---|---|---|---|---|
| S01 | 5.5s | 固定 35mm | 中景 | 主叙事 | 她说出决定 | 我要走了 |
| S02 | 5.5s | 固定 35mm | 中景 | 主叙事 | 他沉默 | 你想清楚了？ |
| S03 | 5.5s | 固定 35mm | 中景 | 主叙事 | 她点头 | 想清楚了 |
| S04 | 5.5s | 固定 35mm | 中景 | 主叙事 | 他站起来 | 站起来 |
| S05 | 5.5s | 固定 35mm | 中景 | 主叙事 | 她拿包 | 拿起包 |
| S06 | 5.5s | 固定 35mm | 中景 | 主叙事 | 她开门 | 开门 |
| S07 | 5.5s | 固定 35mm | 中景 | 主叙事 | 她离开 | 我走了 |
"""


def _run_selftest():
    """内置两表自检：健康表必须全结构通过，病表必须抓出静止超标与连击。"""
    import io
    import tempfile

    ok = True
    for name, text, film_type, expected_static, expected_run in [
        ("健康表", _SELFTEST_HEALTHY, "叙事", "通过", "通过"),
        ("病表", _SELFTEST_SICK, "叙事", "超标", "超标"),
        ("意象病表", _SELFTEST_SICK, "意象", "通过", "通过"),
    ]:
        fd, tmp = tempfile.mkstemp(suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            _h, rows = parse_table(tmp)
        finally:
            os.remove(tmp)
        res = audit(rows, film_type)
        if res is None:
            print(f"[selftest][失败] {name}: 未解析出镜头")
            return 2
        findings = build_findings(res)
        by_item = {f["项"]: f["判定"] for f in findings}
        static_status = by_item.get("静止机位占比")
        run_status = by_item.get("最长连续静止段")
        if static_status != expected_static or run_status != expected_run:
            print(f"[selftest][失败] {name}: 静止={static_status}(期望{expected_static}) "
                  f"连击={run_status}(期望{expected_run})")
            ok = False
        else:
            print(f"[selftest][通过] {name}: 静止={static_status} 连击={run_status}")
    movement_cases = [
        ({"机位/焦段": "固定 35mm", "主体动作": "他推开门，拉过椅子坐下"}, "固定", "动作词不冒充运镜"),
        ({"摄影机路径": "推进", "主体动作": "他站住"}, "推拉", "摄影机路径生效"),
    ]
    for row, expected, name in movement_cases:
        actual = detect_movement(row)
        if actual != expected:
            print(f"[selftest][失败] {name}: {actual} != {expected}")
            ok = False
        else:
            print(f"[selftest][通过] {name}")
    reaction = classify_shot({"本镜叙事功能": "反应·表情", "主体动作": "他愣住", "台词/声音": ""}, 1.2)
    if reaction != "反应":
        print(f"[selftest][失败] 短反应镜被归为{reaction}")
        ok = False

    import contextlib
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "00-立项"))
        os.makedirs(os.path.join(td, "03-分镜"))
        with open(os.path.join(td, "00-立项", "风格提案.md"), "w", encoding="utf-8") as f:
            f.write("片型：意象\n")
        with open(os.path.join(td, "03-分镜", "分镜表.md"), "w", encoding="utf-8") as f:
            f.write("| 项目 | 值 |\n|---|---|\n| 片名 | 测试 |\n\n" + _SELFTEST_HEALTHY)
        argv = sys.argv
        stdout = io.StringIO()
        try:
            sys.argv = ["check_shot_structure.py", td, "--json"]
            with contextlib.redirect_stdout(stdout):
                rc = main()
            payload = json.loads(stdout.getvalue())
            if rc != 0 or payload["summary"].get("film_type") != "意象" or payload.get("suggestions"):
                print(f"[selftest][失败] 单项目真实入口: rc={rc}, output={stdout.getvalue()}")
                ok = False
            else:
                print("[selftest][通过] 单项目真实入口读取片型并跳过前置表")
        except Exception as exc:
            print(f"[selftest][失败] 单项目真实入口异常: {type(exc).__name__}: {exc}")
            ok = False
        finally:
            sys.argv = argv
    original = discover_projects
    stdout = io.StringIO()
    try:
        globals()["discover_projects"] = lambda: []
        with contextlib.redirect_stdout(stdout):
            audit_all()
        if not stdout.getvalue().startswith("[未评估]"):
            print(f"[selftest][失败] 无项目必须明确未评估: {stdout.getvalue()}")
            ok = False
        else:
            print("[selftest][通过] 无项目明确未评估")
        with tempfile.TemporaryDirectory() as good, tempfile.TemporaryDirectory() as empty:
            os.makedirs(os.path.join(good, "03-分镜"))
            with open(os.path.join(good, "03-分镜", "分镜表.md"), "w", encoding="utf-8") as f:
                f.write(_SELFTEST_HEALTHY)
            globals()["discover_projects"] = lambda: [good, empty]
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                audit_all()
            if "[未评估]" not in stdout.getvalue() or os.path.basename(empty) not in stdout.getvalue():
                print(f"[selftest][失败] 混合项目空项目被隐藏: {stdout.getvalue()}")
                ok = False
            else:
                print("[selftest][通过] 混合项目空项目逐项未评估")
    finally:
        globals()["discover_projects"] = original
    if not ok:
        return 2
    print("[selftest] 全部通过")
    return 0


def main():
    ap = argparse.ArgumentParser(description="分镜结构闸（运镜结构审计）")
    ap.add_argument("storyboard", nargs="?", default=None,
                    help="分镜表 .md 路径，或项目目录（自动找 03-分镜/分镜表.md）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--selftest", action="store_true",
                    help="内置样例自检（不调模型、不读外部文件）")
    args = ap.parse_args()

    if args.selftest:
        return _run_selftest()

    target = args.storyboard
    if not target:
        return audit_all()
    if os.path.isdir(target):
        candidate = os.path.join(target, "03-分镜", "分镜表.md")
        if os.path.isfile(candidate):
            target = candidate
        else:
            print(f"[错误] 项目目录下未找到 {candidate}", file=sys.stderr)
            return 2
    if not os.path.isfile(target):
        print(f"[错误] 找不到文件：{target}", file=sys.stderr)
        return 2

    header, rows = parse_table(target)
    if not rows:
        print("[错误] 未解析到表格数据", file=sys.stderr)
        return 2

    stage_dir = os.path.dirname(os.path.abspath(target))
    project = (os.path.dirname(stage_dir)
               if os.path.basename(stage_dir) in ("03-分镜", "02-分镜与镜头")
               else stage_dir)
    film_type, film_source = read_film_type(project)
    res = audit(rows, film_type)
    if not res:
        print("[错误] 未找到镜头 ID 列", file=sys.stderr)
        return 2

    findings = build_findings(res)

    if args.json:
        print(json.dumps({
            "summary": {k: v for k, v in res.items() if k != "shots"},
            "findings": findings,
        }, ensure_ascii=False, indent=2))
    else:
        print(render_text(res, findings, target))
    # 退出码：叙事片静止占比、连续静止、等距切点、平均时长超线 → 1
    # 镜型偏少不失败
    hard_fail = any(f["判定"] in ("超标", "偏长", "偏短") for f in findings)
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
