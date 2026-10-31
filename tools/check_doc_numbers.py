#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档数字防漂移检查器。

**为什么需要**
素材库会持续增长，文档里手写的「50642 条提示词 / 1234 张封面 / 28 条成片」
迟早会和磁盘对不上。这次审计就发现 25 处过时数字（其中「4600条提示词」
从 5 轮采集前就没更新过）。

**用法**
    python check_doc_numbers.py            # 只检查，报错退出码 1
    python check_doc_numbers.py --fix      # 自动修正

放进体系的 tools/ 里，跑在 validate_system.py 之前或旁边都行。
数据资产目录和 `00-视频项目/` 私人项目不参与改写，只检查体系文档里引用的数字。
"""
import argparse
import io
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(SCRIPT_DIR)          # 体系根
LIB = os.path.join(SYSTEM_ROOT, "外部参考库")
# 外部素材库只在显式设置 AI_SEEK_ROOT 时参与维护性统计；未随包提供时只查文档数字与闸表。
sys.path.insert(0, os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库"))
try:
    import lib_locator  # noqa: E402
except ImportError:  # 外部参考库为可选组件，未随包提供
    lib_locator = None
# `_归档` 是已封存的历史项目/调研原始件，不进在制数字统计（与 `00-视频项目` 同理）。
SKIP_DIRS = {".git", "__pycache__", "node_modules", "docs", "模板", "00-视频项目", "_归档"}
# 只跳过「素材数据」子目录（重、不含文档），**不能**跳过 外部参考库 整个目录——
# 总览 00_总览.md 就在里面，恰恰是最需要被检查的。
# 外部参考库是可选数据项目，里面的 .md 同样不是体系文档（它有自己的索引与日志）。
SKIP_SUBPATHS = (
    os.path.join("外部参考库", "提示词库", "封面"),
    os.path.join("外部参考库", "提示词库", "comfy工作流"),
    os.path.join("外部参考库", "提示词库", "官方ComfyUI工作流"),
    os.path.join("外部参考库", "视觉素材"),
)


def measure():
    """统计可选外部库的规模；未配置时返回未启用状态。"""
    truth = {"external_available": False, "prompts": 0, "records": 0,
             "tech": 0, "covers": 0, "videos": 0, "stills": 0}
    if lib_locator is None:
        return truth
    lib_root = lib_locator.lib_root()
    if not lib_root:
        return truth
    truth["external_available"] = True
    p = lib_locator.prompts_path()
    if p and os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            truth["records"] += 1
            truth["prompts"] += record.get("prompt_count",
                                           len(record.get("items") or []))

    def count(root, exts):
        n = 0
        for _r, _d, files in os.walk(root or ""):
            n += sum(1 for f in files if os.path.splitext(f)[1].lower() in exts)
        return n

    tech_md = os.path.join(lib_root, "短片制作技巧检索表.md")
    if os.path.isfile(tech_md):
        for line in io.open(tech_md, encoding="utf-8"):
            match = re.search(r"含技法的 prompts：(\d+)", line)
            if match:
                truth["tech"] = int(match.group(1))
                break
    truth["covers"] = count(lib_locator.covers_dir(),
                             {".png", ".jpg", ".jpeg", ".webp"})
    truth["videos"] = count(os.path.join(lib_root, "..", "..", "02_视觉素材", "视频"), {".mp4"})
    truth["stills"] = count(os.path.join(lib_root, "..", "..", "02_视觉素材", "图像"), {".png", ".jpg", ".jpeg", ".webp"})
    return truth


def count_gates():
    """编排器实际会跑多少道闸 —— 以 run_all_checks.py 的注册为准。

    注意：闸分两处注册 —— `gates = [ ... ]` 列表字面量 + `gates.append((...))`，
    **只数 append 会漏掉前 5 道**（实测栽过：数到 8，实际 13）。
    所以两种都数。
    """
    rac = os.path.join(SCRIPT_DIR, "run_all_checks.py")
    if not os.path.exists(rac):
        return 0
    t = io.open(rac, encoding="utf-8").read()
    # 条件闸（如「闸集合完备性」只在缺维度时才 append）不算常驻闸，
    # 否则常态全量覆盖时它比实际运行数多算一道，文档闸表永远对不上。
    n_append = len([name for name in re.findall(r'gates\.append\(\("([^"]+)"[^\n]*', t)
                    if name != "闸集合完备性"])
    # 列表字面量里的元组：`("名称", ...)`，出现在 gates = [ ... ] 块内
    lit = re.search(r"gates\s*=\s*\[(.*?)\n\s*\]", t, re.S)
    n_literal = len(re.findall(r'\(\s*"[^"]+"\s*,', lit.group(1))) if lit else 0
    return n_append + n_literal


def known_gate_names():
    """编排器里**真实注册**的闸名集合（与 count_gates 同一处解析，不另设名单）。

    用来识别「闸表」：文档里哪些表格行在列闸。名单从代码来而不是从文档来，
    否则文档写错名字就等于把自己的错误当成标准。
    """
    rac = os.path.join(SCRIPT_DIR, "run_all_checks.py")
    if not os.path.exists(rac):
        return set()
    t = io.open(rac, encoding="utf-8").read()
    names = {name for name in re.findall(r'gates\.append\(\("([^"]+)"', t)
             if name != "闸集合完备性"}
    lit = re.search(r"gates\s*=\s*\[(.*?)\n\s*\]", t, re.S)
    if lit:
        names |= set(re.findall(r'\(\s*"([^"]{2,10})"\s*,', lit.group(1)))
    return names


def _cell_name(s):
    """表格首格 → 干净的闸名（去掉 markdown 强调与首尾空格）。"""
    return s.strip().strip("*").strip()


def scan_gate_tables(text):
    """找出文本里所有「闸表」，返回 (行数, 编号列表)。

    闸表 = 表格行中首格是真实闸名的那些行（≥3 行才算表，避免误伤普通表格）。

    **为什么要泛化到所有文件**：
    原实现只查 `命令速查.md`，于是 README 里那张只有 5 行的旧闸表
    从来没被看过——而它恰恰是最容易过时的副本。
    同时**编号表和无编号表都要抓**：
      - 编号表少一行 → 编号集合不等于 1..N
      - 无编号表只列 5 个 → 行数不等于 N
    「标题写对了、清单少了 9 行」比全错更难靠肉眼发现。
    """
    names = known_gate_names()
    if not names:
        return [], []
    numbers, plain = [], []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        m = re.match(r"^\|\s*(\d{1,2})\s*\|\s*([^|]+?)\s*\|", line)
        if m and _cell_name(m.group(2)) in names:
            numbers.append(int(m.group(1)))
            continue
        m2 = re.match(r"^\|\s*([^|]+?)\s*\|\s*[^|]*\|", line)
        if m2 and _cell_name(m2.group(1)) in names:
            plain.append(_cell_name(m2.group(1)))
    return numbers, plain


# 中文数字串 / 出现在数字串**之前**就说明这是序数或量词、不是闸数的字
_CN_DIGITS = "零一二三四五六七八九十"
_NOT_A_COUNT = "第任何每某该另本这那"
# 枚举分隔符：前面是这些字符时，当前数字是清单里的一项，不是总数
_ENUM_SEP = "、，,和与及"


def _gate_rule(n):
    """闸数规则：把「N 闸 / N 道闸 / 中文数字闸」一律重写成真实闸数 n。

    **不解析原数字**——解析中文数字要另写一套转换表，还会写错。
    只要位置匹配到就重写，天然幂等（已是 n 就原样不动）。

    判定「这次匹配到底算不算在数闸」靠回看上下文，不用后顾断言：
    先往回吃掉紧邻的中文数字串，再看它前面一个字是不是 `_NOT_A_COUNT`。
      - 「第一道闸」「十四道闸」→ 回看到「第」→ 比喻义，放过
      - 「任一闸」「任何一闸」→ 回看到「任/何」→ 量词，放过
      - 「五个闸」「12 闸」→ 前面是标点或空格 → 真的在数闸，重写
    """
    # 注意用拼接而不是 .format —— 正则里的 {1,2} 会被当成占位符炸掉（实测踩过）
    rx = re.compile(r"\d{1,2}\s*个?\s*道?闸|["
                    + _CN_DIGITS + r"]{1,3}\s*个?\s*道?闸")

    def _repl(m):
        pre = m.string[:m.start()]
        i = len(pre)
        while i > 0 and pre[i - 1] in _CN_DIGITS:
            i -= 1
        head = pre[i - 1] if i > 0 else ""
        if head and head in _NOT_A_COUNT:
            return m.group(0)
        # 枚举写法：「第 3、4、8、9 道闸」= 依次列四道闸，不是说「9 道闸」。
        # 前面带顿号/逗号说明这是清单里的一项，**别去改它**——
        # 误改实测踩过：把「第 3、4、8、9 道闸」里的 9 改成了 15。
        if head in _ENUM_SEP:
            return m.group(0)
        return "{} 道闸".format(n)

    return (rx, _repl)


def build_rules(t):
    n_gates = count_gates()
    rules = [
        (re.compile(r"\b\d+\s*(?:道|个)闸"), "{} 道闸".format(n_gates)),
        (re.compile(r"\b\d+\s*道闸"), "{} 道闸".format(n_gates)),
    ]
    if t["external_available"]:
        rules.extend([
            (re.compile(r"\b\d{4,6}\s*条(?:国风)?提示词\b"), "{} 条提示词".format(t["prompts"])),
            (re.compile(r"提示词库\s*\d{4,6}\s*条"), "提示词库 {} 条".format(t["prompts"])),
            (re.compile(r"\b\d{3,4}\s*张封面"), "{} 张封面".format(t["covers"])),
            (re.compile(r"\b\d{1,3}\s*条成片"), "{} 条成片".format(t["videos"])),
            (re.compile(r"\b\d{3,4}\s*张(?:高清)?静帧"), "{} 张高清静帧".format(t["stills"])),
            (re.compile(r"\b\d{3,5}\s*作品"), "{} 作品".format(t["records"])),
            (re.compile(r"\b\d{4,6}\s*条含技法提示词"), "{} 条含技法提示词".format(t["tech"])),
        ])
    return rules


def main():
    ap = argparse.ArgumentParser(description="检查文档里的库规模数字是否与磁盘一致")
    ap.add_argument("--fix", action="store_true", help="自动修正")
    args = ap.parse_args()

    truth = measure()
    print("磁盘实况: {}".format(truth))
    rules = build_rules(truth)
    n_real = count_gates()

    problems = []
    table_problems = []
    for root, dirs, files in os.walk(SYSTEM_ROOT):
        dirs[:] = [d for d in dirs
                   if d not in SKIP_DIRS
                   and os.path.relpath(os.path.join(root, d), SYSTEM_ROOT)
                   not in SKIP_SUBPATHS]
        for fn in files:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, SYSTEM_ROOT)
            t = io.open(p, encoding="utf-8", errors="replace").read()
            o = t
            for rx, rep in rules:
                t = rx.sub(rep, t)
            if t != o:
                problems.append(rel)
                if args.fix:
                    io.open(p, "w", encoding="utf-8").write(t)
                    t = o  # 已写回，闸表判定用原文即可（闸数不影响闸名识别）

            # 闸表**行数**必须等于实际闸数，且编号必须是 1..N 无缺口。
            # 实测栽过两次：
            #   ① 加过新闸，标题自动更新成新数，表格还停在旧行数
            #      ——标题对、清单缺，比全错更难靠肉眼发现。
            #   ② 原实现只看 命令速查.md，README 里那张 5 行的旧表从没人看过。
            # 现在**所有 md 都扫**，编号表与无编号表一起抓。
            numbers, plain = scan_gate_tables(t)
            n_rows = len(numbers) if numbers else len(plain)
            if n_rows >= 3:                      # ≥3 行才算「闸表」，避免误伤普通表
                missing = sorted(set(range(1, n_real + 1)) - set(numbers)) \
                    if numbers else list(range(1, n_real + 1))
                if n_rows != n_real or (numbers and missing):
                    table_problems.append(
                        (rel, n_rows, n_real, missing[:6]))

    if not problems and not table_problems:
        print("✓ 所有文档数字与磁盘一致")
        return 0

    if problems:
        print("{} {} 个文件的数字与磁盘不符:".format(
            "已修正" if args.fix else "✗", len(problems)))
        for f in problems:
            print("  - {}".format(f))

    if table_problems:
        print("✗ 闸表与实际闸数不符:")
        for rel, n_rows, n_real_, missing in table_problems:
            print("  - {}：表里 {} 行，实际 {} 道闸{}".format(
                rel, n_rows, n_real_,
                "，缺编号 " + "、".join(str(x) for x in missing) if missing else ""))
        print("  修法：在该文件的闸表里补/删行（闸名以 run_all_checks.py 注册为准），"
              "或在 run_all_checks.py 里加/删 gates")

    if problems and not table_problems:
        print("\n数字部分可用 --fix 自动修正；闸表缺行要手工补（补不进去，只能加行）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())


