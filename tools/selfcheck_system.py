#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体系侧可移植性自检；外部 seek 库不是本体系运行前提。

**边界**
  · 外部 seek 项目有自己的维护自检；本文件只查短剧体系侧（生产体系 + 自动化 skill）。

**为什么体系侧也要查**
`run_all.py` / `shortfilm_pipeline.py` / `auto_select_cards.py` 是体系的核心交付物。
它们必须满足两条：
  1. **清空环境变量后仍能跑**（真通用，不靠别人配好环境）
  2. **整项目拷走也能跑**（无素材库时降级产出，不是崩溃）

上一轮在素材库侧的教训是：测试时环境变量是我自己设的，所以"看起来能跑"。
这次把条件写进断言，不再靠记性。

**用法**
    python selfcheck_system.py
    python selfcheck_system.py --json
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))          # <体系>/tools
SYSTEM_ROOT = os.path.dirname(HERE)                        # <体系>
LIB = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库")
sys.path.insert(0, LIB)
try:
    import lib_locator  # noqa: E402
except ImportError:  # 外部参考库为可选组件，未随包提供
    lib_locator = None

AI_VARS = [k for k in os.environ if k.upper().startswith("AI_")]
PROTECT = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE",
           "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH", "COMSPEC",
           "PATHEXT", "PYTHONPATH", "PYTHONHOME", "NUMBER_OF_PROCESSORS"}

CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k.upper() in PROTECT or not k.upper().startswith("AI_")}


def run(cmd, cwd=None, env=None, timeout=280):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout,
                       env=env)
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


def main():
    ap = argparse.ArgumentParser(description="体系侧可移植性自检")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--keep", action="store_true", help="保留临时目录（调试用）")
    args = ap.parse_args()

    if lib_locator is None or not os.path.isdir(LIB):
        print("外部参考库未随包提供，本闸不适用（N/A）；体系其余闸不受影响。")
        return 0

    checks = []
    tmp = tempfile.mkdtemp(prefix="sysport_")

    try:
        # ① 外部参考库可选；未配置时体系仍必须正常运行。
        configured = bool(os.environ.get("AI_SEEK_ROOT") or
                          os.environ.get("AI_SEEK_RAWLIB"))
        checks.append(("外部参考库可选", not configured or bool(lib_locator.lib_root()),
                       "已显式配置且可定位" if configured else "未配置，体系独立运行"))

        # ② 核心脚本齐备
        need = ["run_all.py", "shortfilm_pipeline.py", "auto_select_cards.py",
                "review_gate.py", "export_g3_storyboard.py",
                "export_g4_generation.py", "export_g6_assembly.py"]
        missing = [f for f in need if not os.path.exists(os.path.join(LIB, f))]
        checks.append(("核心脚本齐备", not missing,
                       "缺: {}".format(missing) if missing else
                       "{} 个".format(len(need))))

        # ③ 零厂商语法
        import re
        blob = ""
        for f in need:
            p = os.path.join(LIB, f)
            if os.path.exists(p):
                blob += io.open(p, encoding="utf-8").read()
        v = re.findall(r"即梦|Seedance|可灵|Kling|Runway|Sora|vidu", blob)
        checks.append(("核心脚本零厂商语法", not v, "{} 个".format(len(v))))

        # ④ 零硬编码盘符（可执行代码里）
        ABS = re.compile(r"(?<![A-Za-z0-9:/\\])[A-Za-z]:[\\/]")
        bad = []
        for f in need:
            p = os.path.join(LIB, f)
            if not os.path.exists(p):
                continue
            for ln in io.open(p, encoding="utf-8").read().split("\n"):
                s = ln.strip()
                if s.startswith("#"):
                    continue
                if ABS.search(ln) and '<' not in ln and '$' not in ln:
                    bad.append("{}:{}".format(f, s[:40]))
        checks.append(("核心脚本零硬编码盘符", not bad,
                       "{} 处".format(len(bad)) if bad else "0 处"))

        # ④b 产物文件零绝对路径
        #
        # **为什么必须单独加这一项**（实测踩过的坑）：
        # ④ 只扫 7 个核心脚本，**产物文件不在扫描范围**。
        # 于是「制作包.json 里写死了绝对盘符路径」这种违规，
        # 在可移植性闸里完全隐形 —— 8/8 全绿、退出码 0。
        # 当时能发现，靠的是「样例新鲜度」闸歪打正着（它比的是
        # 样例 == 当前重跑），不是这道闸真的在管这件事。
        # 教训：**扫描范围就是闸的视野，范围外的违规等于没查。**
        #
        # 顺带修掉一个真 bug：产物的 cover 字段原来存绝对路径，
        # 整个项目搬到新盘后重跑，它会跟着变成新盘符 —— 存下来发给别人
        # 就是死链。已在 shortfilm_pipeline.portable_path 改为相对项目根。
        ARTIFACT_DIRS = [os.path.join(LIB, "示例"), LIB]
        # 必须用**捕获组**：下面要用 m.group(1) 取命中的那段路径，
        # 才能回看它前面的上下文做豁免判断。
        # （写成 (?:...) 非捕获组会在第一个违规上直接 IndexError，
        #   闸变成崩溃而不是报错 —— 正反探针当场抓到的。）
        ABS_ART = re.compile(r"[A-Za-z]:[\\/]{1,2}([^\"'\n|,;)\]<>{}]{2,})")
        scanned, bad_art = 0, []
        for d in ARTIFACT_DIRS:
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                # 只看文本产物。JSON 里的 \\ 是转义，要还原再判
                # （否则 Windows 路径 c:\\x 会被当成合法的 \\ 分隔符放过）。
                if not fn.endswith((".md", ".json")) or fn == "_统计.json":
                    continue
                p = os.path.join(d, fn)
                body = io.open(p, encoding="utf-8", errors="replace").read()
                if fn.endswith(".json"):
                    body = body.replace("\\\\", "\\")
                scanned += 1
                for m in ABS_ART.finditer(body):
                    hit = m.group(1)
                    # 产物里的示例文本（如 CLI 助手指令）不算路径依赖
                    if "<" in hit or "$" in hit or "%" in hit:
                        continue
                    # 环境变量赋值（AI_SEEK_ROOT=C:\x）是**用法说明**，
                    # 不是产物数据；拦它属于误报。
                    # 只认"紧邻 = 且变量名是大写/下划线"这一种形态，
                    # 不放宽成"含 = 就跳过"——那会让 `cover=<盘符>:\x` 溜过去。
                    pre = body[max(0, m.start() - 40):m.start()]
                    if re.search(r"[A-Z][A-Z0-9_]{2,}\s*=\s*$", pre):
                        continue
                    # URL 里的协议斜杠（如 https://、file://）不是盘符
                    if re.search(r"[a-z][a-z0-9+.\-]{1,10}:/{1,2}$", pre,
                                 re.I):
                        continue
                    bad_art.append("{}: {}".format(
                        os.path.basename(fn), hit[:48]))
        # **防「滤过头」**：必须真的扫到了产物，否则这一项恒为 0 处、
        # 等于没查（把词表清空导致「滤光所有」也是同一个陷阱）。
        # 判据用"扫到几个文件"而不是"违规几个"——违规可以是 0，
        # 但扫描数不能是 0。
        art_ok = (not bad_art) and scanned >= 4
        checks.append(("产物零绝对路径", art_ok,
                       "{} 处 / 已扫 {} 个文件".format(len(bad_art), scanned)
                       if art_ok or not bad_art else
                       "{} 处（已扫 {} 个）: {}".format(
                           len(bad_art), scanned, bad_art[0])))

        # ⑤ 清空环境变量下 run_all 仍能出全套
        od = os.path.join(tmp, "ra")
        rc, o = run([sys.executable, os.path.join(LIB, "run_all.py"),
                     "自检题材 复仇", "--style", "工笔", "--mood", "肃杀",
                     "--duration", "60", "--out", od],
                    cwd=LIB, env=CLEAN_ENV)
        files = os.listdir(od) if os.path.isdir(od) else []
        need4 = ["制作包", "G3分镜表", "G4生成段", "G6剪辑装配单"]
        miss4 = [n2 for n2 in need4 if not any(n2 in f for f in files)]
        checks.append(("清空环境变量下 run_all 出全套",
                       rc == 0 and not miss4,
                       "{} 份（缺{}）".format(len(files), miss4 or "无")))

        # ⑥ 产物零占位符
        pack = next((os.path.join(od, f) for f in files
                     if f.startswith("制作包") and f.endswith(".md")), None)
        if pack:
            t = io.open(pack, encoding="utf-8").read()
            ph = re.findall(r"按题材推断|参考选卡中的|承接上一场情绪|占位|TODO", t)
            checks.append(("产物零占位符", not ph, "{} 个".format(len(ph))))
        else:
            checks.append(("产物零占位符", False, "没生成制作包"))

        # ⑦ 整个项目拷走 + 无素材库 → 降级而非崩溃
        #
        # **为什么拷整个目录，而不是单个 .py**：
        # 这一关要验的是「素材库缺失时用内置模板兜底」，不是「每个脚本都能单独跑」。
        # 项目铁律是「永远是完整项目，拿到哪里都能用」——单文件不是完整项目。
        # 原来只拷 shortfilm_pipeline.py，等于额外要求「零同模块依赖」；
        # 而流水线要从同目录的 review_gate.py 取 5 关定义（单一真源，不抄第二份），
        # 于是被这一关判死（实测退出码 1）。
        # 关键点仍然保留：**一个素材数据都不拷**，所以「无素材库」是真的。
        pd = os.path.join(tmp, "solo")
        shutil.copytree(
            LIB, pd,
            ignore=shutil.ignore_patterns(
                "prompts.jsonl", "封面", "comfy工作流", "官方ComfyUI工作流",
                "示例", "__pycache__", "*.md", "_统计.json"))
        rc, o = run([sys.executable, os.path.join(pd, "shortfilm_pipeline.py"),
                     "自检 题材", "--duration", "30",
                     "--out", os.path.join(tmp, "solo_out")], env=CLEAN_ENV)
        checks.append(("整项目无库降级运行",
                       rc == 0 and "需补素材" in o,
                       "退出码 {}".format(rc)))

        # ⑧ 审核门禁会真的拦
        if pack:
            rc0, o0 = run([sys.executable, os.path.join(LIB, "review_gate.py"),
                           pack, "--gate", "G3"], cwd=LIB, env=CLEAN_ENV)
            checks.append(("未签核时门禁拒绝", rc0 == 2 and "拒绝放行" in o0,
                           "退出码 {}".format(rc0)))
        else:
            checks.append(("未签核时门禁拒绝", False, "没制作包可测"))
    finally:
        if args.keep:
            print("临时目录保留: {}".format(tmp))
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    npass = sum(1 for _n, ok, _e in checks if ok)
    if args.json:
        print(json.dumps({
            "pass": npass, "total": len(checks),
            "cleared_env_vars": AI_VARS,
            "checks": [{"name": n, "ok": ok, "detail": e} for n, ok, e in checks],
        }, ensure_ascii=False, indent=2))
    else:
        print("=" * 76)
        print("体系侧可移植性自检（清空了 {} 个 AI_* 环境变量）".format(len(AI_VARS)))
        print("=" * 76)
        for name, ok, ev in checks:
            print("{} {:<26s} {}".format("✓" if ok else "✗", name, ev))
        print("-" * 76)
        print("通过 {}/{}".format(npass, len(checks)))
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
