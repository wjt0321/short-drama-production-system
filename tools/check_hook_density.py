#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hook 密度闸 · 叙事回报受控词表 + 分布检查 —— A4 的落地实现。

**为什么需要**
`本刀新信息` 是自由文本，无法校验分布：一部片可以 21 刀每刀都"有新信息"，
但整体没有任何反转或回收。`镜头类型`（主叙事/反应/插入细节/空镜/过渡）管的是
剪辑结构角色，不管叙事回报。对标件的镜头表有一列「Hook Type」受控词表，
并配密度自检：不许连续铺陈没有回报。

**查什么**（对象是 `03-分镜/分镜表.md` 的 `hook` 列）
  ① 硬检查：每镜必填且值在受控词表内；首镜与叙事片末镜必须强 hook。
  ② 节奏提醒：连续铺陈、标签多样性只提示导演复核，不自动判失败。
     不用每三镜必须反转的配额制造机械剧情，也没有备注即豁免通道。

**边界**
  · hook 管「这一镜给观众什么回报」，与 `镜头类型`（剪辑结构角色）互补不替代；
  · 与 `本刀新信息`（自由文本）配套使用：hook 是分类，新信息是内容；
  · 已归档失败项目不阻断。

**用法**
    python tools/check_hook_density.py <项目目录>
    python tools/check_hook_density.py            # 扫全部在制项目
    python tools/check_hook_density.py --selftest

**退出码**：0 通过或仅提醒 / 1 词表、必填或首尾强钩失败 / 2 用法或自检失败
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

FAIL_MARK_RE = re.compile(r"##\s*失败裁决")

from _art_exception import waiver_note
from _film_gate_waivers import load_waivers, is_waived, tally_line
from _film_type import read_film_type

GATE = "hook密度-真片"

HOOK_WHITELIST = ("setup", "visual-joke", "reversal", "reveal", "callback",
                  "suspense", "tender", "chase", "expression-beat", "climax")
PAYOUT_HOOKS = ("reveal", "reversal", "callback")
STRONG_HOOKS = ("visual-joke", "reversal", "reveal", "suspense", "tender")
MAIN_ID_RE = re.compile(r"^\*{0,2}(?:S|G)\d{1,3}\*{0,2}$")
# 镜头 ID 列的合法表头（模板用 `剪辑镜头ID`；老项目用 `镜`/`镜号`，不认就会
# 被误报成"表结构不符合模板"，实测旧结构主表就是这么被误判的）。
ID_HEADER_ALIASES = ("剪辑镜头id", "镜头id", "镜号", "镜", "镜头号", "镜头")
# ⑦ 分布多样性阈值（2026-10-18 补）：已知值 ≥8 时才校验，单一值占比上限 60%。
# 无实测出处，属先验判断（"一种回报铺满全片 = 等于没填"），可被项目复盘校准。
DIVERSITY_MIN_VALUES = 3
DIVERSITY_TOP_MAX = 0.60
DIVERSITY_MIN_SHOTS = 8


def find_storyboard(proj):
    for rel in ("03-分镜/分镜表.md", "03-分镜/分镜表.txt",
                "02-分镜与镜头/分镜表.md"):
        fp = os.path.join(proj, *rel.split("/"))
        if os.path.isfile(fp):
            return fp
    return None


def parse_hook_col(txt):
    """返回 [(镜头ID, hook值或None)]，按主表行序。"""
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
    out = []
    for t in tables:
        if len(t) < 2:
            continue
        header = t[0]
        id_col = hook_col = None
        for i, h in enumerate(header):
            hs = h.strip("* ").lower()
            if id_col is None and (MAIN_ID_RE.match(hs) or hs in ID_HEADER_ALIASES):
                id_col = i
            if hook_col is None and hs in ("hook", "hook类型", "钩子"):
                hook_col = i
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
            if hook_col is None:
                v = None          # 表有镜头行但无 hook 列 → 由 ① 报缺列
            else:
                v = row[hook_col].strip() if hook_col < len(row) else ""
            out.append((sid.upper(), v))
        if out:
            break
    return out


def analyse(proj):
    problems, facts = [], {}
    fp = find_storyboard(proj)
    if not fp:
        problems.append("未找到 03-分镜/分镜表.md —— 无法做 hook 密度检查")
        facts["分镜表"] = None
        return problems, facts
    with open(fp, encoding="utf-8", errors="replace") as f:
        txt = f.read()
    facts["分镜表"] = os.path.relpath(fp, proj)
    film_type, film_type_source = read_film_type(proj)
    facts["片型"] = f"{film_type}（{film_type_source}）"

    rows = parse_hook_col(txt)
    facts["镜数"] = len(rows)
    if not rows:
        problems.append("主表未解析到任何镜头行 —— 表结构不符合模板")
        return problems, facts
    if all(v is None for _i, v in rows):
        problems.append("① 分镜表缺 `hook` 列 —— 每镜必填叙事回报标签，"
                        "受控词表：{}".format("/".join(HOOK_WHITELIST)))
        return problems, facts

    n_empty, n_unknown = 0, {}
    vals = []
    for sid, v in rows:
        if not v:
            n_empty += 1
            problems.append("② {} 的 hook 未填 —— 十选一：{}"
                            .format(sid, "/".join(HOOK_WHITELIST)))
            vals.append(None)
        elif v.lower() in HOOK_WHITELIST:
            vals.append(v.lower())
        else:
            n_unknown[v] = n_unknown.get(v, 0) + 1
            problems.append("③ {} 的 hook `{}` 不在受控词表 —— 只许：{}"
                            .format(sid, v, "/".join(HOOK_WHITELIST)))
            vals.append(None)
    facts["未填"] = n_empty
    if n_unknown:
        facts["词表外"] = n_unknown

    known = [v for v in vals if v]
    if len(known) >= 3:
        reminders = facts.setdefault("节奏提醒", [])
        for i in range(len(vals) - 2):
            window = [v for v in vals[i:i + 3] if v]
            if len(window) == 3 and not any(v in PAYOUT_HOOKS for v in window):
                reminders.append(
                    "第 {}–{} 镜连续铺陈：{}；请导演确认这是有意留白，"
                    "还是缺少叙事回报".format(rows[i][0], rows[i + 2][0], "/".join(window)))
                break
        dist = {}
        for v in known:
            dist[v] = dist.get(v, 0) + 1
        facts["hook分布"] = dist
        if len(known) >= DIVERSITY_MIN_SHOTS:
            top_v, top_n = max(dist.items(), key=lambda kv: kv[1])
            if len(dist) < DIVERSITY_MIN_VALUES:
                reminders.append("全片 hook 只用了 {} 种（{}）；请确认是否标签重复代替了节奏设计"
                                 .format(len(dist), "/".join(dist)))
            elif top_n / float(len(known)) > DIVERSITY_TOP_MAX:
                reminders.append("单一 hook `{}` 占 {}/{}（{:.0%}）；请导演复核回报是否单一"
                                 .format(top_v, top_n, len(known), top_n / float(len(known))))
    if vals and vals[0] and vals[0] not in STRONG_HOOKS:
        problems.append(
            "⑤ 首镜 {} 的 hook 是 `{}` —— 开场必须强钩（visual-joke / "
            "reversal / reveal / suspense / tender）".format(rows[0][0], vals[0]))
    if vals and film_type == "叙事" and vals[-1] and vals[-1] not in STRONG_HOOKS:
        problems.append(
            "⑥ 末镜 {} 的 hook 是 `{}` —— 叙事片收尾必须强钩，不许 chase / "
            "expression-beat / setup 单独撑尾".format(rows[-1][0], vals[-1]))
    elif vals and film_type == "意象" and vals[-1]:
        facts["意象片收尾"] = "允许余味式 hook：" + vals[-1]
    note = waiver_note(proj, "hook收尾")
    if note.startswith("艺术破例生效"):
        problems = [item for item in problems if not item.startswith("⑥")]
        facts["艺术破例"] = note
    elif note:
        facts["艺术破例"] = note
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
    unevaluated = [os.path.basename(p) for p in all_projs if p not in projs]
    if not projs:
        print("[未评估] 未发现带 03-分镜/分镜表.md 的在制项目，本闸没有可判对象")
        if unevaluated:
            print("· 未评估项目（无分镜表）：{}".format("、".join(unevaluated)))
        return 0
    active_bad, arch_bad, waived = [], [], []
    ok_n = 0
    for p in projs:
        problems, facts = analyse(p)
        name = os.path.basename(p)
        arch = _is_archived(p)
        wvd = bool(problems) and is_waived(waivers, name, GATE)
        if wvd:
            tag = "WAIVED（{} 条，已登记豁免）".format(len(problems))
        else:
            tag = "✗ {} 条".format(len(problems)) if problems else "✓"
        print("  {:<28s} 镜数={:<3d} {}".format(name, facts.get("镜数", 0), tag))
        for reminder in facts.get("节奏提醒", []):
            print("    · 节奏提醒：" + reminder)
        if problems:
            if wvd:
                waived.append(name)
            elif arch:
                arch_bad.append((name, problems))
            else:
                active_bad.append((name, problems))
        elif facts.get("镜数", 0) == 0:
            # D3：分镜表存在但读不出镜头 = 未评估，不是通过
            unevaluated.append(name)
        else:
            ok_n += 1
    for name, problems in active_bad:
        print("\n⚠ {}：".format(name))
        for x in problems[:8]:
            print("   ✗ " + x[:110])
        if len(problems) > 8:
            print("   … 另有 {} 条".format(len(problems) - 8))
    if arch_bad:
        print("\n· 归档失败项目（已记录不阻断，计入未评估）：")
        for name, problems in arch_bad:
            print("  {}：{} 条".format(name, len(problems)))
    if waived:
        print("\n· 已豁免（WAIVED，登记于 tools/_film_gate_waivers.yaml）：{}"
              .format("、".join(waived)))
    if unevaluated:
        print("· 未评估项目（分镜表缺失或读不出镜头）：{}".format(
            "、".join(unevaluated)))
    n_uneval = len(unevaluated) + len(arch_bad)
    if active_bad:
        print("\n  修法：分镜表加 `hook` 列并逐镜填受控词表；首尾用强钩。"
              "连续铺陈与标签多样性只作导演复核提醒，不作自动豁免或硬失败。"
              "参考 模板/短剧项目模板/03-分镜/分镜表.md。")
        print(tally_line(ok_n, len(waived), n_uneval, len(active_bad)))
        return 1
    if waived or n_uneval:
        print("⚠ " + tally_line(ok_n, len(waived), n_uneval) +
              "　—— 有豁免/未评估，不算全绿")
        return 0
    print("✓ 在制项目 hook 密度全部合格（{} 个项目）".format(ok_n))
    print(tally_line(ok_n, 0, 0))
    return 0


def selftest():
    ok = True
    import tempfile

    HDR = "| 剪辑镜头ID | hook |\n|---|---|\n"

    def _write(td, rows):
        os.makedirs(os.path.join(td, "03-分镜"), exist_ok=True)
        with open(os.path.join(td, "03-分镜", "分镜表.md"), "w",
                  encoding="utf-8") as f:
            f.write(HDR + "".join("| {} | {} |\n".format(s, h) for s, h in rows))

    # 反例 1：缺 hook 列 → 必抓
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "03-分镜"), exist_ok=True)
        with open(os.path.join(td, "03-分镜", "分镜表.md"), "w",
                  encoding="utf-8") as f:
            f.write("| 剪辑镜头ID | 时长 |\n|---|---|\n| S01 | 4s |\n")
        problems, _ = analyse(td)
        if not any(p.startswith("①") for p in problems):
            print("[自检失败] 缺 hook 列应报 ①：{}".format(problems))
            ok = False
        else:
            print("[自检通过] 缺 hook 列被抓")

    # 反例 2：词表外值 → 必抓
    with tempfile.TemporaryDirectory() as td:
        _write(td, [("S01", "reveal"), ("S02", "fight"), ("S03", "callback")])
        problems, _ = analyse(td)
        if not any(p.startswith("③") and "fight" in p for p in problems):
            print("[自检失败] 词表外值应报 ③：{}".format(problems))
            ok = False
        else:
            print("[自检通过] 词表外值（fight）被抓")

    # 节奏提醒：连续 3 镜无回报钩只提醒，不冒充创作质量硬闸
    with tempfile.TemporaryDirectory() as td:
        _write(td, [("S01", "reveal"), ("S02", "setup"), ("S03", "setup"),
                    ("S04", "chase")])
        problems, facts = analyse(td)
        if any(p.startswith("④") for p in problems) or not facts.get("节奏提醒"):
            print("[自检失败] 连续铺陈应只提醒：{} {}".format(problems, facts))
            ok = False
        else:
            print("[自检通过] 连续 3 镜无回报只提醒")

    # 反例 4：setup 撑开场 + chase 撑收尾 → 必抓
    with tempfile.TemporaryDirectory() as td:
        _write(td, [("S01", "setup"), ("S02", "reveal"), ("S03", "callback"),
                    ("S04", "chase")])
        problems, _ = analyse(td)
        if not any(p.startswith("⑤") for p in problems):
            print("[自检失败] setup 开场应报 ⑤：{}".format(problems))
            ok = False
        if not any(p.startswith("⑥") for p in problems):
            print("[自检失败] chase 收尾应报 ⑥：{}".format(problems))
            ok = False
        if any(p.startswith("⑤") for p in problems) and \
           any(p.startswith("⑥") for p in problems):
            print("[自检通过] 首尾强钩规则被抓")

    # 节奏提醒：全片只填一种 hook 提醒导演复核，不用标签配额代替判断
    with tempfile.TemporaryDirectory() as td:
        _write(td, [("S{:02d}".format(i + 1), "reveal") for i in range(12)])
        problems, facts = analyse(td)
        if any(p.startswith("⑦") for p in problems) or not facts.get("节奏提醒"):
            print("[自检失败] 全片单一 hook 应只提醒：{} {}".format(problems, facts))
            ok = False
        else:
            print("[自检通过] 全片单一 hook（12×reveal）只提醒")

    # 反例 6：镜头 ID 列写 `镜`（老项目表头）+ 无 hook 列 → 必须报 ① 缺列，
    # 不许报"主表未解析到任何镜头行"（2026-10-18 修：旧结构主表曾被这样误判）
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "03-分镜"), exist_ok=True)
        with open(os.path.join(td, "03-分镜", "分镜表.md"), "w",
                  encoding="utf-8") as f:
            f.write("| 镜 | 刀型 | 成片时长 |\n|---|---|---|\n"
                    "| S01 | 长刀 | 5.2s |\n| **S02** | 常规 | 4.4s |\n")
        problems, facts = analyse(td)
        if not any(p.startswith("①") for p in problems):
            print("[自检失败] 老表头（镜）应报 ① 缺 hook 列：{}".format(problems))
            ok = False
        elif facts.get("镜数") != 2:
            print("[自检失败] 老表头应解析出 2 行，实际 {}：{}".format(
                facts.get("镜数"), problems))
            ok = False
        else:
            print("[自检通过] 老表头 `镜` 可解析，且报 ① 缺 hook 列")

    # 正例：密度合规 → 放行
    with tempfile.TemporaryDirectory() as td:
        _write(td, [("S01", "suspense"), ("S02", "setup"), ("S03", "reveal"),
                    ("S04", "tender"), ("S05", "callback"), ("S06", "reveal")])
        problems, facts = analyse(td)
        if problems:
            print("[自检失败] 合规样例被误报：{}".format(problems))
            ok = False
        else:
            print("[自检通过] 合规样例（首 suspense 尾 reveal，回报均匀）未误报")
    with tempfile.TemporaryDirectory() as td:
        _write(td, [("S01", "setup"), ("S02", "chase")])
        problems, _ = analyse(td)
        if not any(p.startswith("⑤") for p in problems) or not any(p.startswith("⑥") for p in problems):
            print("[自检失败] 两镜弱首尾必须被抓：{}".format(problems))
            ok = False
        else:
            print("[自检通过] 两镜弱首尾被抓")
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(description="Hook 密度闸：叙事回报词表 + 密度 + 首尾强钩")
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
