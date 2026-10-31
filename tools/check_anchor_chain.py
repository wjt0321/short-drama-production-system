#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""锚点链闸 · 空间锚点四子项 + 镜间接续链闭合 —— A2/A3 的落地实现。

**为什么需要**
旧模板写「不锁死屏幕方向」——方向恰好反了：不写死地标在本帧的画面位置，
跨镜漂移就无法检测，重抽日志只能记一句"场景漂移"，说不出哪根轴漂了。
同时 `镜前状态`/`镜后状态`/`对下一镜约束` 三列早就存在，却从没校验器逐行读，
填了不等于闭合。官方 skill 的两道自检（锚点一致性 / 链闭合）在这里合一实现。

**查什么**（对象是 `03-分镜/分镜表.md`）
A2 空间锚点（每镜 `### Sxx` 节内必填四子项）：
  · 固定地标 —— 命名地标 + 画面相对位置（例：门框=画面右侧三分之一）
  · 人物位置（机位视角）—— 每角色 左/中/右 + 前/中/后景 + 朝向 + 初始姿态
  · 退场人物状态 —— 上镜在场本镜不在场的人：离屏位置 + 原因
  · 光位基线 —— 主光/补光/轮廓光方向（继承场景卡）+ 本镜调整项
  同场次连续两镜的 `固定地标` 值必须一致；不一致必须写连续性说明
  （含 `移至/随镜头/→` 之一），否则 FAIL。

A3 衔接链（读主表三列）：
  · 同场次内 本镜 `镜后状态` → 下一镜 `镜前状态` 必须都非空（闭合）；
  · `镜后状态` 含 `HARD CUT` 时，本镜 `对下一镜约束` 必须写明原因（≥4 字）；
  · 跨场次（场次列值不同）不查链 —— 场间允许重锚（帧链法 2.3 同一语义）。

**边界**
  · 锚点块格式以模板「空间锚点」节为准；旧项目没有 → 判缺，退出码 1；
  · 语义级翻转检测（眼神/站位/道具/光位到底漂没漂）超出启发式能力，
    本闸管结构闭合；语义核对靠 02-分镜与镜头/跨镜连续性与帧链法.md 的人审项；
  · 已归档失败项目不阻断。

**用法**
    python tools/check_anchor_chain.py <项目目录>
    python tools/check_anchor_chain.py            # 扫全部在制项目
    python tools/check_anchor_chain.py --selftest

**退出码**：0 全绿 / 1 有断链缺锚 / 2 用法或自检失败
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

FAIL_MARK_RE = re.compile(r"##\s*失败裁决")

from _film_gate_waivers import load_waivers, is_waived

GATE = "锚点链-真片"

# `### S01（…）` 节标题
SHOTSEC_HDR_RE = re.compile(r"^\s*#{2,4}\s*\*{0,2}(S\d{1,3}|G\d{1,3})\*{0,2}"
                            r"(?:[（(]\s*[^)）]*[)）])?\s*$", re.I)
MAIN_ID_RE = re.compile(r"^\*{0,2}(?:S|G)\d{1,3}\*{0,2}$")
# 连续性说明标记：地标值变了时必须带其一
CONTINUITY_MARKS = ("移至", "随镜头", "→", "跟随", "环绕", "推拉", "摇移")
STATE_STOPWORDS = {"镜头", "状态", "开始", "结束", "画面", "保持", "同上", "无", "不变", "进入", "离开"}
STATE_TOKEN_RE = re.compile(r"[A-Za-z][\w-]+|[\u4e00-\u9fff]{2,}")
# 四子项行首标签（容忍全半角冒号与空格）
ANCHOR_KEYS = ("固定地标", "人物位置", "退场人物状态", "光位基线")


def find_storyboard(proj):
    for rel in ("03-分镜/分镜表.md", "03-分镜/分镜表.txt",
                "02-分镜与镜头/分镜表.md"):
        fp = os.path.join(proj, *rel.split("/"))
        if os.path.isfile(fp):
            return fp
    return None


def parse_main_rows(txt):
    """读主表行：{镜头ID: {"场次":v, "镜前状态":v, "镜后状态":v, "对下一镜约束":v}}
    并返回有序 ID 列表。列按表头名定位，找不到的列不查。"""
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
    rows, order = {}, []
    for t in tables:
        if len(t) < 2:
            continue
        header = t[0]
        id_col = None
        colmap = {}
        for i, h in enumerate(header):
            hs = h.strip("* ")
            if id_col is None and (MAIN_ID_RE.match(hs) or hs == "剪辑镜头ID"):
                id_col = i
            for key in ("场次", "镜前状态", "镜后状态", "对下一镜约束", "接力"):
                if hs == key or (key in hs and len(hs) <= len(key) + 4):
                    colmap.setdefault(key, i)
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
            sid = sid.upper()
            rows[sid] = {k: (row[i].strip() if i < len(row) else "")
                         for k, i in colmap.items()}
            order.append(sid)
        if rows:
            break  # 第一张合格主表即可
    return rows, order


def parse_anchor_blocks(txt):
    """解析每镜 `### Sxx` 节内的四子项。返回 {镜头ID: {键: 值}}。"""
    anchors = {}
    cur_id = None
    for line in txt.splitlines():
        m = SHOTSEC_HDR_RE.match(line)
        if m:
            cur_id = m.group(1).upper()
            anchors[cur_id] = {}
            continue
        if cur_id is None:
            continue
        s = line.strip().lstrip("-*• ").strip()
        for key in ANCHOR_KEYS:
            if s.startswith(key) and ("：" in s[:len(key) + 2] or ":" in s[:len(key) + 2]):
                val = re.split(r"[:：]", s, maxsplit=1)[1].strip()
                anchors[cur_id][key] = val
    return anchors


def _state_tokens(value):
    """提取人物、位置、道具等可复现词，过滤纯结构词。"""
    return {t.lower() for t in STATE_TOKEN_RE.findall(value or "")
            if t not in STATE_STOPWORDS and len(t) >= 2}


def analyse(proj):
    problems, facts = [], {}
    fp = find_storyboard(proj)
    if not fp:
        problems.append("未找到 03-分镜/分镜表.md —— 无法做锚点链检查")
        facts["分镜表"] = None
        return problems, facts
    with open(fp, encoding="utf-8", errors="replace") as f:
        txt = f.read()
    facts["分镜表"] = os.path.relpath(fp, proj)

    rows, order = parse_main_rows(txt)
    anchors = parse_anchor_blocks(txt)
    facts["主镜数"] = len(order)
    facts["锚点块数"] = len(anchors)

    if not order:
        problems.append("主表未解析到任何剪辑镜头 ID —— 表结构不符合模板")
        return problems, facts

    # ---- A2：四子项必填 + 同场景地标一致 ----
    for sid in order:
        a = anchors.get(sid, {})
        for key in ANCHOR_KEYS:
            if not a.get(key):
                problems.append("① {} 缺空间锚点 `{}` —— 四子项必填：固定地标/"
                                "人物位置/退场人物状态/光位基线".format(sid, key))
    n_landmark_mismatch = 0
    for prev, cur in zip(order, order[1:]):
        prev_scene = rows.get(prev, {}).get("场次", "")
        cur_scene = rows.get(cur, {}).get("场次", "")
        if prev_scene and cur_scene and prev_scene != cur_scene:
            continue  # 跨场次：场间允许重锚
        la, lb = anchors.get(prev, {}).get("固定地标"), anchors.get(cur, {}).get("固定地标")
        if la and lb and la != lb:
            if not any(m in lb for m in CONTINUITY_MARKS):
                n_landmark_mismatch += 1
                problems.append(
                    "② {}→{} 固定地标不一致且无连续性说明：{} vs {} —— "
                    "同场景连续两镜地标必须一致，变了要写明怎么变的"
                    "（例：`门框随镜头左环绕由右侧三分之一移至中央`）"
                    .format(prev, cur, la[:24], lb[:24]))
    facts["地标不一致对数"] = n_landmark_mismatch

    # ---- A3：衔接链闭合（同场次内）+ HARD CUT 纪律（每镜都查，含末镜）----
    n_open = 0
    for prev, cur in zip(order, order[1:]):
        prev_scene = rows.get(prev, {}).get("场次", "")
        cur_scene = rows.get(cur, {}).get("场次", "")
        if prev_scene and cur_scene and prev_scene != cur_scene:
            continue
        after = rows.get(prev, {}).get("镜后状态", "")
        before = rows.get(cur, {}).get("镜前状态", "")
        if not after or not before:
            n_open += 1
            problems.append(
                "③ {}→{} 衔接链断开：{}镜后状态{} / {}镜前状态{} —— "
                "同场次内每镜的镜后状态与下一镜镜前状态必须都填，链才闭合"
                .format(prev, cur,
                        prev, "空" if not after else "有",
                        cur, "空" if not before else "有"))
        elif not (_state_tokens(after) & _state_tokens(before)):
            n_open += 1
            problems.append(
                "③ {}→{} 状态内容无可识别接续：镜后「{}」/镜前「{}」—— "
                "至少共享人物、位置或道具词；若确有跳变请写 HARD CUT 原因"
                .format(prev, cur, after[:40], before[:40]))
        relay = rows.get(prev, {}).get("接力", "")
        if not relay:
            problems.append(
                "⑤ {}→{} 缺 `接力`：同场次连续镜必须写动作/视线/遮挡/形状/光线/声音等接力机制"
                .format(prev, cur))
    for sid in order:
        after = rows.get(sid, {}).get("镜后状态", "")
        if "HARD CUT" in after.upper():
            reason = rows.get(sid, {}).get("对下一镜约束", "")
            if len(reason) < 4:
                problems.append(
                    "④ {} 标了 HARD CUT 但 `对下一镜约束` 未写原因 —— "
                    "任何站位/道具/光位的翻转必须显式标 HARD CUT + 原因"
                    "（例：`HARD CUT — 时间跳 2 小时`）".format(sid))
    facts["断链对数"] = n_open
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
    unevaluated = [os.path.basename(p) for p in all_projs if not find_storyboard(p)]
    for name in unevaluated:
        print("  {:<28s} [未评估] 无分镜表".format(name))
    if not projs:
        print("[未评估] 未发现带 03-分镜/分镜表.md 的在制项目，本闸没有可判对象")
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
        print("  {:<28s} 镜数={:<3d} {}".format(name, facts.get("主镜数", 0), tag))
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
        print("\n  修法：分镜表按模板为每镜填「空间锚点」四子项；同场景地标变化写"
              "连续性说明；镜前/镜后状态链闭合。参考 模板/短剧项目模板/03-分镜/分镜表.md。")
        if waived:
            print("· 豁免计数：{} 个项目 WAIVED；未豁免仍红：{}".format(
                len(waived), "、".join(n for n, _ in active_bad)))
        return 1
    print("✓ 在制项目锚点链全部闭合")
    if waived:
        print("· 豁免计数：{} 个项目在本闸 WAIVED".format(len(waived)))
    return 0


def selftest():
    ok = True
    import tempfile

    def _write(td, body):
        os.makedirs(os.path.join(td, "03-分镜"), exist_ok=True)
        with open(os.path.join(td, "03-分镜", "分镜表.md"), "w",
                  encoding="utf-8") as f:
            f.write(body)

    def _anchors(landmark, extra=""):
        return ("- 固定地标：{}\n- 人物位置：阿珍=画左/中景/侧身朝右\n"
                "- 退场人物状态：无\n- 光位基线：主光窗光画左 45°（继承 LOC-01）{}\n"
                ).format(landmark, extra)

    MAIN = ("| 剪辑镜头ID | 场次 | 镜前状态 | 镜后状态 | 对下一镜约束 |\n"
            "|---|---|---|---|---|\n"
            "| S01 | 场1 | 未定 | 手握门把 | 承接 |\n"
            "| S02 | 场1 | 手握门把 | 门半开 | 承接 |\n")

    # 反例 1：S02 缺四子项 → 必抓
    with tempfile.TemporaryDirectory() as td:
        body = (MAIN + "\n### S01（0–4s）\n" + _anchors("门框=画面右侧三分之一") +
                "\n### S02（0–2s）\n- 固定地标：门框=画面右侧三分之一\n")
        _write(td, body)
        problems, _ = analyse(td)
        if not any("②" not in p and "①" in p and "S02" in p for p in problems):
            print("[自检失败] 缺四子项应报 ①，实际：{}".format(problems[:3]))
            ok = False
        else:
            print("[自检通过] 缺四子项被抓")

    # 反例 2：同场景地标不一致且无说明 → 必抓
    with tempfile.TemporaryDirectory() as td:
        body = (MAIN + "\n### S01（0–4s）\n" + _anchors("门框=画面右侧三分之一") +
                "\n### S02（0–2s）\n" + _anchors("门框=画面左侧"))
        _write(td, body)
        problems, _ = analyse(td)
        if not any("②" in p for p in problems):
            print("[自检失败] 地标不一致应报 ②，实际：{}".format(problems[:3]))
            ok = False
        else:
            print("[自检通过] 地标漂移被抓（无连续性说明）")

    # 正例 1：地标变化但写了随镜头说明 → 放行该项
    with tempfile.TemporaryDirectory() as td:
        body = (MAIN + "\n### S01（0–4s）\n" + _anchors("门框=画面右侧三分之一") +
                "\n### S02（0–2s）\n" +
                _anchors("门框随镜头左环绕由右侧三分之一移至中央"))
        _write(td, body)
        problems, _ = analyse(td)
        if any(p.startswith("②") for p in problems):
            print("[自检失败] 连续性说明应豁免 ②：{}".format(problems[:3]))
            ok = False
        else:
            print("[自检通过] 带连续性说明的地标变化放行")

    # 反例 3：断链（S02 镜前状态空）→ 必抓
    with tempfile.TemporaryDirectory() as td:
        main2 = MAIN.replace("| S02 | 场1 | 手握门把 |", "| S02 | 场1 |  |")
        body = (main2 + "\n### S01（0–4s）\n" + _anchors("门框=画面右侧三分之一") +
                "\n### S02（0–2s）\n" + _anchors("门框=画面右侧三分之一"))
        _write(td, body)
        problems, _ = analyse(td)
        if not any("③" in p for p in problems):
            print("[自检失败] 断链应报 ③，实际：{}".format(problems[:3]))
            ok = False
        else:
            print("[自检通过] 断链被抓（镜前状态空）")

    # 反例 4：HARD CUT 无原因 → 必抓
    with tempfile.TemporaryDirectory() as td:
        main2 = MAIN.replace("| 门半开 | 承接 |", "| 门半开 HARD CUT |  |")
        body = (main2 + "\n### S01（0–4s）\n" + _anchors("门框=画面右侧三分之一") +
                "\n### S02（0–2s）\n" + _anchors("门框=画面右侧三分之一"))
        _write(td, body)
        problems, _ = analyse(td)
        if not any("④" in p for p in problems):
            print("[自检失败] HARD CUT 无原因应报 ④，实际：{}".format(problems[:3]))
            ok = False
        else:
            print("[自检通过] HARD CUT 无原因被抓")

    # 正例 2：跨场次断链不查 + 全合规 → 放行
    with tempfile.TemporaryDirectory() as td:
        main2 = MAIN.replace("| S02 | 场1 |", "| S02 | 场2 |")
        body = (main2 + "\n### S01（0–4s）\n" + _anchors("门框=画面右侧三分之一") +
                "\n### S02（0–2s）\n" + _anchors("床=画面中央"))
        _write(td, body)
        problems, _ = analyse(td)
        if problems:
            print("[自检失败] 跨场次应全放行，实际：{}".format(problems[:3]))
            ok = False
        else:
            print("[自检通过] 跨场次重锚不查链、全合规放行")
    import contextlib
    import io
    original = discover_projects
    stdout = io.StringIO()
    try:
        globals()["discover_projects"] = lambda: []
        with contextlib.redirect_stdout(stdout):
            audit_all()
        if not stdout.getvalue().startswith("[未评估]"):
            print("[自检失败] 无项目必须明确未评估：{}".format(stdout.getvalue()))
            ok = False
        else:
            print("[自检通过] 无项目明确未评估")
        with tempfile.TemporaryDirectory() as good, tempfile.TemporaryDirectory() as empty:
            body = (MAIN + "\n### S01（0–4s）\n" + _anchors("门框=画面右侧三分之一") +
                    "\n### S02（0–2s）\n" + _anchors("门框=画面右侧三分之一"))
            _write(good, body)
            globals()["discover_projects"] = lambda: [good, empty]
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                audit_all()
            if "[未评估]" not in stdout.getvalue() or os.path.basename(empty) not in stdout.getvalue():
                print("[自检失败] 混合项目空项目被隐藏：{}".format(stdout.getvalue()))
                ok = False
            else:
                print("[自检通过] 混合项目空项目逐项未评估")
    finally:
        globals()["discover_projects"] = original
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(description="锚点链闸：空间锚点四子项 + 镜前/镜后链闭合")
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
