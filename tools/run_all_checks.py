#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全闸自检 —— 改完代码跑这一条就够。

**为什么需要这条命令**
上轮修参数校验时，我插入一个函数把 `find_cover` 的定义行覆盖了，
导致所有正常调用报 `NameError`。是靠完整回归才发现的。

**常驻闸，各管一件事（数量与清单以 `命令速查.md` 为准，这里不写死）**

每一道查什么、对应哪个工具，看根目录 `命令速查.md` 的闸表——
**那份是唯一真源，这里不再抄一份**。抄第二份就多一个会过时的地方：
本文件的 docstring 就已经过时过一次（写着「五个闸」，表里还漏了 6/7/8 三道）。
加闸时只改两处——`main()` 里的 gates、以及 `命令速查.md` 的表，
「数字一致」闸会核对两边行数一致，对不上直接失败。

**用法**
    python tools/run_all_checks.py
    python tools/run_all_checks.py --quick    # 跳过最慢的边界测试

任一闸不过 → 退出码 1。
"""
import argparse
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

# D3：「未评估」不是「合格」。退出码 0 但输出说明没有可判对象时记 SKIP。
UNEVAL_RE = re.compile(r"\[未评估\]|未评估\s*[1-9]\d*|本闸跳过|没有可判对象|未发现在制项目")


def _classify_result(returncode, output):
    if returncode != 0:
        return "FAIL"
    if UNEVAL_RE.search(output or ""):
        return "SKIP"
    return "OK"

def check_samples():
    """存档样例必须与当前代码输出一致。

    背景：改完代码后忘记重生成 `示例/`，存档就会悄悄过期。
    实际发生过——制作包.md 落后于代码（少了 review_gate 提示），
    而我在好几轮里都声称「样例已更新」。
    """
    ex = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库", "示例")
    if not os.path.isdir(ex):
        return True, "外部参考库未随包提供（样例新鲜度闸 N/A）"
    import tempfile
    import shutil
    tmp = tempfile.mkdtemp(prefix="samplecmp_")
    try:
        lib = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库")
        p = subprocess.run(
            [sys.executable, os.path.join(lib, "run_all.py"),
             "江南书生夜雨", "--style", "工笔", "--mood", "肃杀",
             "--duration", "60", "--out", tmp],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600)
        if p.returncode != 0:
            return False, "重跑失败"
        stale = []
        for f in sorted(os.listdir(tmp)):
            a, b = os.path.join(ex, f), os.path.join(tmp, f)
            if not os.path.exists(a):
                stale.append(f + "(缺)")
                continue
            if open(a, encoding="utf-8").read() != open(b, encoding="utf-8").read():
                stale.append(f)
        if stale:
            return False, "{} 份已过期，重跑 run_all.py --out 示例".format(len(stale))
        return True, "{} 份与当前代码一致".format(len(os.listdir(tmp)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_relocation():
    """把项目复制到临时位置，验证搬走后依然自洽。

    **这是「拿到哪里都能用」的端到端实证**：
    前面的可移植性闸只验证「清空环境变量后仍能跑」，
    这一闸验证「整个目录搬到别处，代码不会指回原处」。

    做法：复制可提交的体系代码与文档（排除大素材、独立 seek 数据源和
    `.gitignore` 全量排除的私人项目）到 temp，在副本里跑结构校验，
    并确认路径层指向副本自身。项目搬家另做项目级检查。
    """
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="relocate_")
    dst = os.path.join(tmp, "sys_copy")
    try:
        shutil.copytree(
            SYSTEM_ROOT, dst,
            ignore=shutil.ignore_patterns(
                "*.mp4", "*.png", "*.jpg", "*.jpeg", "*.webp",
                "*.wav", "*.mp3", "*.flac",
                "__pycache__", ".git", "00-视频项目", "_归档", "外部参考库"))
        # ① 副本里结构校验必须过
        p = subprocess.run(
            [sys.executable, os.path.join(dst, "tools", "validate_system.py")],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600, cwd=dst)
        if p.returncode != 0:
            tail = [l for l in ((p.stdout or "") + (p.stderr or "")).split("\n") if l.strip()]
            return False, "副本校验失败：" + (tail[-1][:50] if tail else "")
        # ② 副本的路径层必须指向副本自己，不是原目录
        probe = (
            "import os,sys,json\n"
            "sys.path.insert(0, {tools!r})\n"
            "import importlib.util\n"
            "spec=importlib.util.spec_from_file_location('rac', {rac!r})\n"
            "m=importlib.util.module_from_spec(spec)\n"
            "try: spec.loader.exec_module(m)\n"
            "except SystemExit: pass\n"
            "print(m.SYSTEM_ROOT)\n"
        ).format(tools=os.path.join(dst, "tools"),
                 rac=os.path.join(dst, "tools", "run_all_checks.py"))
        p2 = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            timeout=200, cwd=dst)
        got = (p2.stdout or "").strip().split("\n")[-1] if p2.stdout else ""
        if os.path.abspath(SYSTEM_ROOT).lower() in got.lower():
            return False, "副本仍指向原目录"
        if "sys_copy" not in got:
            return False, "副本未自定位: {}".format(got[:40])
        # ③ 副本里的脚本不得含原目录的绝对路径（实测漏洞：只查路径层自定位不够）
        leaked = []
        orig_norm = os.path.abspath(SYSTEM_ROOT).lower().replace("\\", "/")
        orig_bs = os.path.abspath(SYSTEM_ROOT).lower().replace("/", "\\")
        for root2, _d2, files2 in os.walk(dst):
            for fn2 in files2:
                if not fn2.endswith((".py", ".md", ".json", ".ps1")):
                    continue
                p2 = os.path.join(root2, fn2)
                try:
                    body = io.open(p2, encoding="utf-8",
                                   errors="replace").read().lower()
                except OSError:
                    continue
                # 注意：**不豁免本文件**。曾经把 run_all_checks.py 排除在泄漏检查外，
                # 结果写死的 `外部 seek 项目路径/...` 就藏在被豁免的文件里，搬家闸永远抓不到。
                # 给违规开后门，等于让最该被查的那份代码免检。
                if orig_norm in body or orig_bs in body:
                    leaked.append(os.path.relpath(p2, dst))
        if leaked:
            return False, "{} 个文件写死了原目录: {}".format(
                len(leaked), leaked[:2])
        return True, "搬到临时位置后校验通过、路径自定位正确、无写死原路径"
    except Exception as exc:  # noqa: BLE001
        return False, "{}: {}".format(type(exc).__name__, str(exc)[:50])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def meta_check():
    """闸的自检 —— 防止「检查者自己坏了却装作没事」。

    **发现的漏洞**：把 `check_doc_numbers.py` 改成永远 `return 0`，
    它就会报「所有文档数字与磁盘一致」，编排器只看退出码，**识破不了**。
    这是自检体系里最隐蔽的失效方式。

    **对策**：编排器不信任子进程的自述，独立复算关键断言。
    这里做两件子进程做不到的事：
      1. 直接数磁盘上的封面数，与文档里写的数比对
      2. 确认每个闸脚本存在且非空
    """
    import re as _re
    problems = []

    classify_cases = [
        (1, "✓ 在制项目全部合格", "FAIL"),
        (0, "✓ 在制项目全部合格", "OK"),
        (0, "项目列表\n[未评估] 没有可判对象", "SKIP"),
        (0, "✓ 未发现在制项目，本闸跳过", "SKIP"),
        (0, "汇总：通过 2 / WAIVED 0 / 未评估 1", "SKIP"),
    ]
    for rc, output, expected in classify_cases:
        actual = _classify_result(rc, output)
        if actual != expected:
            problems.append(f"结果分类 {output!r}: {actual} != {expected}")

    import ast
    source = ast.parse((os.path.join(HERE, "validate_system.py") and
                        open(os.path.join(HERE, "validate_system.py"), encoding="utf-8").read()))
    excluded = set()
    for node in ast.walk(source):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EXCLUDED_DIRS"
                                               for t in node.targets):
            excluded = ast.literal_eval(node.value)
    required_excluded = {"_release", "archive", ".superpowers"}
    if not required_excluded.issubset(excluded):
        problems.append("结构校验未排除构建/历史/暂存目录：" + str(sorted(required_excluded - set(excluded))))

    import tempfile
    import contextlib
    import pack_release
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        pack_release.RELEASE = Path(td) / "_release"
        pack_release.STAGE = Path(td) / "_release" / "staging" / "短剧成片体系"
        pack_release.STAGE.mkdir(parents=True)
        marker = Path(td) / "_release" / "staging" / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        old_argv = sys.argv
        try:
            sys.argv = ["pack_release.py", "--no-zipp"]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    rc = pack_release.main()
                except SystemExit as exc:
                    rc = exc.code
            if rc != 2 or not marker.is_file():
                problems.append("发布工具未知参数未在清理前拒绝")
        finally:
            sys.argv = old_argv

    import check_shot_duration_variance
    import check_per_second_coverage
    import check_style_lock
    import check_retro_writeback
    mixed_modules = [
        (check_shot_duration_variance, "discover_projects"),
        (check_per_second_coverage, "discover_projects"),
        (check_style_lock, "discover_projects"),
        (check_retro_writeback, "projects"),
    ]
    for module, attr in mixed_modules:
        original = getattr(module, attr)
        try:
            with tempfile.TemporaryDirectory() as good, tempfile.TemporaryDirectory() as empty:
                (Path(good) / "03-分镜").mkdir()
                (Path(good) / "03-分镜" / "分镜表.md").write_text(
                    "| 剪辑镜头ID | 时长 |\n|---|---|\n| S01 | 2s |\n", encoding="utf-8")
                setattr(module, attr, lambda: [good, empty])
                stdout = io.StringIO()
                old_argv = sys.argv
                try:
                    with contextlib.redirect_stdout(stdout):
                        if hasattr(module, "audit_all"):
                            module.audit_all()
                        else:
                            sys.argv = [module.__name__]
                            module.main()
                finally:
                    sys.argv = old_argv
                if "[未评估]" not in stdout.getvalue() or os.path.basename(empty) not in stdout.getvalue():
                    problems.append(f"混合项目未评估被隐藏：{module.__name__}")
        finally:
            setattr(module, attr, original)

    # ① 闸脚本存在且非空
    for name, p in (("validate_system", os.path.join(HERE, "validate_system.py")),
                    ("check_doc_numbers", os.path.join(HERE, "check_doc_numbers.py")),
                    ("selfcheck_system", os.path.join(HERE, "selfcheck_system.py")),
                    ("test_pipeline_edge", os.path.join(HERE, "test_pipeline_edge.py"))):
        if not os.path.isfile(p) or os.path.getsize(p) < 200:
            problems.append("{} 缺失或过小".format(name))

    # ② 独立复算：封面数（不信 check_doc_numbers 的自述）
    _p = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库")
    if _p not in sys.path:
        sys.path.insert(0, _p)
    try:
        import lib_locator
    except ImportError:
        return True, "外部参考库未随包提供（闸的自检 N/A）"
    if problems:
        return False, "；".join(problems[:3])
    if not lib_locator.lib_root():
        return True, "外部参考库未配置，跳过外部数据复算"
    cov = lib_locator.covers_dir() or ""
    n_cov = 0
    if os.path.isdir(cov):
        n_cov = len([f for f in os.listdir(cov)
                     if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))])
    else:
        problems.append("封面目录不存在")

    # ③ 独立复算：jsonl 条数
    n_rec = 0
    jp = lib_locator.prompts_path() or ""
    if os.path.exists(jp):
        with open(jp, encoding="utf-8") as f:
            n_rec = sum(1 for line in f if line.strip())
    else:
        problems.append("prompts.jsonl 不存在")

    # ④ 总览里写的数必须与实算一致
    ov = os.path.join(SYSTEM_ROOT, "外部参考库", "00_总览.md")
    if os.path.exists(ov) and n_cov and n_rec:
        t = io.open(ov, encoding="utf-8").read()
        m_cov = _re.search(r"(\d{3,4})\s*张封面", t)
        m_rec = _re.search(r"(\d{3,5})\s*作品", t)
        if m_cov and int(m_cov.group(1)) != n_cov:
            problems.append("总览写 {} 张封面，磁盘是 {} 张".format(
                m_cov.group(1), n_cov))
        if m_rec and int(m_rec.group(1)) != n_rec:
            problems.append("总览写 {} 作品，磁盘是 {} 条".format(
                m_rec.group(1), n_rec))

    if problems:
        return False, "；".join(problems[:3])
    return True, "封面 {} 张 / 作品 {} 条（独立复算一致）".format(n_cov, n_rec)


def main():
    ap = argparse.ArgumentParser(description="全闸自检（改完代码跑这条）")
    ap.add_argument("--quick", action="store_true", help="跳过最慢的边界测试")
    ap.add_argument("--system-only", action="store_true",
                    help="只跑体系自检闸（改代码后用这个；跳过所有 -真片 闸）")
    ap.add_argument("--films-only", action="store_true",
                    help="只跑 -真片 闸（做片时用这个；跳过体系自检）")
    args = ap.parse_args()

    gates = [
        ("结构校验", os.path.join(HERE, "validate_system.py"), False),
        ("数字一致", os.path.join(HERE, "check_doc_numbers.py"), False),
        ("体系可移植", os.path.join(HERE, "selfcheck_system.py"), False),
        ("流水线边界", os.path.join(HERE, "test_pipeline_edge.py"), True),
    ]
    # 样例新鲜度与「闸的自检」不跑子进程，直接在主进程算
    gates.append(("样例新鲜度", "INLINE", True))
    gates.append(("闸的自检", "META", True))
    gates.append(("搬家验证", "RELOC", True))
    gates.append(("语料质量", os.path.join(HERE, "check_prompt_quality.py"), True))
    gates.append(("安全性能", os.path.join(HERE, "check_security_perf.py"), True))
    gates.append(("素材对齐", os.path.join(HERE, "check_asset_alignment.py"), True))
    # 未提交改动只提醒不失败 —— 正在改东西时未提交是正常状态
    gates.append(("未提交提醒", os.path.join(HERE, "check_uncommitted.py"), True))

    # —— 真片扫描（本体进常驻路径，闸真的检查片子，不是只跑反例自检）——
    # 这组「-真片」闸扫 00-视频项目/ 里的真实项目：切点节奏、项目合规、情绪词、
    # 逐秒覆盖、锚点链、hook 密度、风格锁、运镜结构。
    # 在制项目有问题时这里会红 —— 这是有意设计：片子的问题不该只对 Agent 可见。
    gates.append(("切点均质度-真片",
                  [sys.executable, os.path.join(HERE, "check_shot_duration_variance.py")],
                  True))
    gates.append(("项目合规-真片",
                  [sys.executable, os.path.join(HERE, "check_project_conformance.py")],
                  True))
    gates.append(("情绪词闸-真片",
                  [sys.executable, os.path.join(HERE, "check_emotion_words.py")],
                  True))
    gates.append(("逐秒覆盖-真片",
                  [sys.executable, os.path.join(HERE, "check_per_second_coverage.py")],
                  True))
    gates.append(("锚点链-真片",
                  [sys.executable, os.path.join(HERE, "check_anchor_chain.py")],
                  True))
    gates.append(("hook密度-真片",
                  [sys.executable, os.path.join(HERE, "check_hook_density.py")],
                  True))
    gates.append(("风格锁-真片",
                  [sys.executable, os.path.join(HERE, "check_style_lock.py")],
                  True))
    gates.append(("运镜结构-真片",
                  [sys.executable, os.path.join(HERE, "check_shot_structure.py")],
                  True))
    # G1 剧本是唯一还能便宜改故事的阶段，此前没有任何一道闸查它；
    # 「剧本像 PPT、看不懂在讲什么」的病根在剧本模板，不在分镜。
    gates.append(("剧本因果-真片",
                  [sys.executable, os.path.join(HERE, "check_script_causality.py")],
                  True))

    gates.append(("G3成立性-真片",
                  [sys.executable, os.path.join(HERE, "check_shot_viability.py")],
                  True))
    gates.append(("复盘回写-真片",
                  [sys.executable, os.path.join(HERE, "check_retro_writeback.py")],
                  True))
    gates.append(("成片剪用-真片",
                  [sys.executable, os.path.join(HERE, "check_assembly_usage.py")],
                  True))
    gates.append(("种子活到成片-真片",
                  [sys.executable, os.path.join(HERE, "check_seed_survival.py")],
                  True))

    # —— 以下为校验器自身的反例回归（selftest）——
    # 真片扫描在上面三道已经常驻；这里再各跑一遍 selftest，防的是
    # 「检查器自己坏了却装作没事」（反例必须被抓、正例不得误报）。
    # 「13 镜全是 5.17s」曾能一路全绿，就是因为只查文件间一致性、
    # 没有任何一道查片子本身的节奏。
    gates.append(("切点均质度-selftest",
                  [sys.executable, os.path.join(HERE, "check_shot_duration_variance.py"),
                   "--selftest"], True))

    # 项目合规闸（活跃项目状态 vs 磁盘、刀型白名单、合同式反模式等）。
    # 同样只跑 selftest；真实项目合规见 命令速查.md 的 `check_project_conformance`。
    gates.append(("项目合规-selftest",
                  [sys.executable, os.path.join(HERE, "check_project_conformance.py"),
                   "--selftest"], True))
    gates.append(("情绪词闸-selftest",
                  [sys.executable, os.path.join(HERE, "check_emotion_words.py"),
                   "--selftest"], True))
    gates.append(("逐秒覆盖-selftest",
                  [sys.executable, os.path.join(HERE, "check_per_second_coverage.py"),
                   "--selftest"], True))
    gates.append(("锚点链-selftest",
                  [sys.executable, os.path.join(HERE, "check_anchor_chain.py"),
                   "--selftest"], True))
    gates.append(("hook密度-selftest",
                  [sys.executable, os.path.join(HERE, "check_hook_density.py"),
                   "--selftest"], True))
    gates.append(("风格锁-selftest",
                  [sys.executable, os.path.join(HERE, "check_style_lock.py"),
                   "--selftest"], True))

    # 参考查询唯一入口闸（select_reference 路由/透传/封面映射/缺资源）。
    # 防止「文档引用的查询入口悄悄坏掉」——历史上曾出现入口不存在的问题。
    gates.append(("参考查询入口-selftest",
                  os.path.join(HERE, "test_select_reference.py"), True))
    gates.append(("提示词契约-selftest",
                  os.path.join(HERE, "test_validate_video_prompt.py"), True))

    # 运镜结构闸：静止占比 / 最长静止连击 / 镜型配比 / 平均时长。
    # 补的缺口与「切点均质度」互补：后者管时长维度（节拍器、长短刀），
    # 本闸管运镜结构维度 —— 这才是「拼起来像 PPT」的直接病因。
    # 阈值不是拍脑袋：由 历史样本 16 条优秀成片逐帧实测推导
    # （阈值出处见 check_shot_structure.py 的阈值注释）。
    # 真片扫描在上面以「运镜结构-真片」常驻；这里再跑校验器自身回归。
    gates.append(("运镜结构-selftest",
                  [sys.executable, os.path.join(HERE, "check_shot_structure.py"),
                   "--selftest"], True))
    gates.append(("成片剪用-selftest",
                  [sys.executable, os.path.join(HERE, "check_assembly_usage.py"),
                   "--selftest"], True))

    # 字幕烧录闸：事件表解析 / 关键词强调色 / 自动断行 / 双预设参数 / 时间码转换。
    # 保护的是转换器逻辑本身（回归即拦）；真实烧录用
    # `python tools/subtitle_burn.py <项目目录> --preset drama --burn`。
    gates.append(("字幕烧录-selftest",
                  [sys.executable, os.path.join(HERE, "subtitle_burn.py"),
                   "--selftest"], True))
    gates.append(("剧本因果-selftest",
                  [sys.executable, os.path.join(HERE, "check_script_causality.py"),
                   "--selftest"], True))

    gates.append(("G3成立性-selftest",
                  [sys.executable, os.path.join(HERE, "check_shot_viability.py"),
                   "--selftest"], True))
    gates.append(("复盘回写-selftest",
                  [sys.executable, os.path.join(HERE, "check_retro_writeback.py"),
                   "--selftest"], True))
    gates.append(("种子活到成片-selftest",
                  [sys.executable, os.path.join(HERE, "check_seed_survival.py"),
                   "--selftest"], True))
    gates.append(("H3参考参数-selftest",
                  [sys.executable, os.path.join(HERE, "h3_ref_validator.py"),
                   "--selftest"], True))

    # 闸集合的「完备性」自检：关键维度必须有闸覆盖。
    # 为什么要显式声明：闸的存在与否如果只活在脑子里，删一道、或忘记加一道，
    # 都不会有人发现（实测栽过：加了三道新闸忘了登记，闸被删时无人知晓）。
    # 声明出来 = 关键维度变成**代码里的硬要求**，不是备忘。
    REQUIRED = {
        "结构/外链/断链": "结构校验",
        "文档数字 vs 磁盘": "数字一致",
        "闸数量 vs 文档": "数字一致",       # 同一道闸覆盖两个维度
        "可移植（体系）": "体系可移植",
        "极端/非法输入": "流水线边界",
        "产物与代码同步": "样例新鲜度",
        "检查者可信": "闸的自检",
        "整体搬家": "搬家验证",
        "内容质量": "语料质量",
        "安全/性能": "安全性能",
        "素材与候选表": "素材对齐",
        "切点节奏（长短刀/生成内多刀·真片）": "切点均质度-真片",
        "未提交改动": "未提交提醒",
        "项目合规（状态/刀型/合同/旁路·真片）": "项目合规-真片",
        "情绪词已翻译物理量（真片提示词）": "情绪词闸-真片",
        "秒级指令覆盖（五要素/无空隙·真片）": "逐秒覆盖-真片",
        "空间锚点与衔接链（四子项/闭合·真片）": "锚点链-真片",
        "叙事回报密度（hook 词表/密度·真片）": "hook密度-真片",
        "全局风格锁注入（字符串化/逐条原文·真片）": "风格锁-真片",
        "参考查询唯一入口（路由/封面映射/缺资源）": "参考查询入口-selftest",
        "平台提示词契约（字段/语法不串用）": "提示词契约-selftest",
        "运镜结构（静止占比/连击/镜型配比·真片）": "运镜结构-真片",
        "运镜结构校验器自身回归": "运镜结构-selftest",
        "成片剪用（装配单裁切/成片帧差·真片）": "成片剪用-真片",
        "成片剪用校验器自身回归": "成片剪用-selftest",
        "字幕管线（事件表→ASS→烧录转换正确性）": "字幕烧录-selftest",
        "剧本因果（因果四句/无执行参数/道具翻转/朗读测试·真片）": "剧本因果-真片",
        "G3成立性（动作容量/旁白占比/视觉自证预警·真片）": "G3成立性-真片",
        "剧本因果校验器与模板字段对齐": "剧本因果-selftest",
        "G3成立性校验器自身回归": "G3成立性-selftest",
        "复盘回写（结论→文件:行）": "复盘回写-真片",
        "复盘回写校验器自身回归": "复盘回写-selftest",
        "种子活到成片（物件或话语还在画面里）": "种子活到成片-真片",
        "种子活到成片校验器自身回归": "种子活到成片-selftest",
        "H3参考参数（17k+5/9图/3视频/5s-10s）": "H3参考参数-selftest",
    }
    have = set(g[0] for g in gates)
    missing_dims = [d for d, g in REQUIRED.items() if g not in have]
    if missing_dims:
        print("✗ 闸集合不完备，缺这些维度的闸：{}".format("、".join(missing_dims)))
        gates.append(("闸集合完备性", "INCOMPLETE", True))   # 标记为失败项
    else:
        print("✓ 闸集合完备：{} 个关键维度全覆盖".format(len(REQUIRED)))

    if args.quick:
        gates = [g for g in gates if not (g[2] and "边界" in g[0])]

    # 双开关：改代码只看体系自检 / 做片只看真片闸；默认（不加开关）全跑，
    # 设计意图不变——片子的问题不该只对做片的 Agent 可见。
    # 注意：REQUIRED 完备性检查在上面过滤之前已跑，两个开关不影响它。
    if args.system_only and args.films_only:
        print("✗ --system-only 与 --films-only 互斥")
        return 2
    if args.system_only:
        gates = [g for g in gates if not g[0].endswith("-真片")]
    if args.films_only:
        gates = [g for g in gates if g[0].endswith("-真片")]

    print("=" * 68)
    print("全闸自检" + ("（quick：跳过慢测）" if args.quick else ""))
    print("=" * 68)

    results = []
    for name, path, skippable in gates:
        if path == "INLINE":
            ok, msg = check_samples()
            results.append((name, ok, msg, "OK" if ok else "FAIL"))
            print("{} {:<12s} {}".format("OK  " if ok else "FAIL", name, msg))
            continue
        if path == "META":
            ok, msg = meta_check()
            results.append((name, ok, msg, "OK" if ok else "FAIL"))
            print("{} {:<12s} {}".format("OK  " if ok else "FAIL", name, msg))
            continue
        if path == "RELOC":
            ok, msg = check_relocation()
            results.append((name, ok, msg, "OK" if ok else "FAIL"))
            print("{} {:<12s} {}".format("OK  " if ok else "FAIL", name, msg))
            continue
        # 路径可以是「字符串」（单纯脚本）或「列表 [exe, script, ...args]」
        # （带 --selftest 等参数）。后者让框架只跑反例自检、不扫真实项目。
        if isinstance(path, list):
            cmd, script = path[0], path[1]
            extra_args = path[2:]
        else:
            cmd, script, extra_args = sys.executable, path, []
        if not script or not os.path.isfile(script):
            msg = "未找到（外部参考库未随包提供）" \
                if "素材库" in name else "未找到"
            # 跳过**不等于通过**——否则会出现「假绿」：报 5/5 但实际只跑了 4 项
            results.append((name, False, msg, "SKIP"))
            print("SKIP {:<12s} {}".format(name, msg))
            continue
        try:
            # **必须传 cwd**：素材库侧的自检脚本用相对位置找项目根，
            # 继承体系的 cwd 会让它定位到错误的地方（实测导致「素材库可移植」假失败）
            child_cwd = (os.path.dirname(script)
                         if os.path.dirname(script) != HERE else None)
            p = subprocess.run([cmd, script] + extra_args, capture_output=True,
                               text=True, encoding="utf-8",
                               errors="replace", timeout=900, cwd=child_cwd)
            out = ((p.stdout or "") + (p.stderr or "")).strip()
            tail = [l for l in out.split("\n") if l.strip()]
            ok = p.returncode == 0
            status = _classify_result(p.returncode, out)
            if status == "SKIP":
                results.append((name, False, tail[-1].strip()[:46], "SKIP"))
                print("SKIP {:<12s} {}".format(name, tail[-1].strip()[:46]))
                continue
            results.append((name, ok, tail[-1].strip()[:46] if tail else "", status))
            print("{} {:<12s} {}".format("OK  " if ok else "FAIL", name,
                                          tail[-1].strip()[:46] if tail else ""))
        except subprocess.TimeoutExpired:
            results.append((name, False, "超时", "FAIL"))
            print("FAIL {:<12s} 超时".format(name))

    print("-" * 68)
    nok = sum(1 for _n, ok, _e, _s in results if ok and _s == "OK")
    nskip = sum(1 for _n, _ok, _e, s in results if s == "SKIP")
    nfail = sum(1 for _n, _ok, _e, s in results if s == "FAIL")
    print("通过 {}/{}　（跳过 {}，失败 {}）".format(nok, len(results), nskip, nfail))
    if nfail:
        print("\n✗ 有闸失败。先修再继续——别带着坏状态往下做。")
        return 1
    if nskip:
        print("\n⚠ 有闸被跳过，不算全绿。缺的那项需要人工确认。")
        return 1
    print("\n✓ 全绿。可以继续。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
