#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""情绪词硬闸 · 情绪词必须已翻译成物理量 —— AGENTS.md §8.1 的落地实现。

**为什么需要**
§8.1 立了规则：提示词里出现「愤怒 / 悲伤 / 电影感 / 氛围感」等情绪词，
必须已被翻译成画面可指认的物理量（眉间收紧、嘴角朝向、光比、焦段……），
否则模型只能拿平均值猜 —— 中庸就是这么来的。
规则比对标件更严，但一直没有实现：没有任何脚本扫过提示词，
「品位靠记忆，不靠闸门」。本闸就是那个闸门。

**查什么**
扫项目 04-镜头/ 下全部提示词（.md/.txt，与切点均质度闸同一发现策略）：
  ① 把提示词按大标点（。；！？与换行）切成小句；
  ② 小句命中情绪词表 → 同句必须至少出现一个物理量标记
     （§8.1 十五维翻译表的落点词汇：眉间/嘴角/光比/焦段/画左/饱和度……）；
  ③ 只有情绪词、没有任何物理量落点 → FAIL，报出文件与小句原文。

**边界**
  · 这是启发式：管「情绪词不得裸奔」，不判定翻译质量本身；
  · 看向/目光/视线/朝向/纹理是弱标记，必须再绑定具体部位、方位或数值；
  · 同句出现落点不等于该落点真在描述情绪，不能替代生成探针与完整回放；
  · 只扫提示词正文。导演意图层（立项/分镜文档）允许出现情绪词，不进本闸；
  · 已归档失败项目不阻断（与项目合规闸同一语义）。

**用法**
    python tools/check_emotion_words.py <项目目录>
    python tools/check_emotion_words.py            # 扫全部在制项目
    python tools/check_emotion_words.py --selftest

**退出码**：0 全绿 / 1 有裸奔情绪词 / 2 用法或自检失败
"""
import argparse
import glob as _glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

from _film_gate_waivers import tally_line   # noqa: E402  (同目录，脚本运行时在 sys.path)

# ---- 情绪词表（AGENTS.md §8.1「不要写」列 + 工作单 A6，两处合一）----
EMOTION_WORDS = (
    "愤怒", "悲伤", "紧张", "高级感", "质感好", "电影感", "氛围感",
    "有张力", "很真实", "凌乱", "狼狈", "憔悴", "阴郁", "精致", "破旧",
    "战后", "有味道", "异域感", "心虚", "压迫感",
)
EMOTION_RE = re.compile("|".join(re.escape(w) for w in EMOTION_WORDS))

# ---- 物理量标记（§8.1 十五维翻译表的落点词汇，每维至少一项可指认事实）----
PHYSICAL_MARKERS = (
    "眉间", "眉头", "眉心", "嘴角", "下颌", "眼睑", "瞳孔", "咬肌", "面部肌肉",
    "发梢", "发缕", "发丝", "刘海", "发际",
    "褶皱", "垂坠", "织纹", "起球", "磨损", "缝线",
    "材质", "尺寸", "哑光", "反光", "握持", "缺口", "氧化",
    "污渍", "水渍", "血渍", "浸湿", "泥点", "灰尘",
    "擦伤", "淤青", "疤痕", "妆容", "脱妆",
    "主光", "补光", "轮廓光", "顶光", "侧光", "底光", "逆光", "受光",
    "背光", "光比", "色温", "高度角", "方位", "入射",
    "能见度", "湿度", "雾气", "雨滴", "扬尘", "云层", "天际线", "地貌",
    "植被", "人工痕迹", "地面材质",
    "画左", "画右", "银幕", "轴线",
    "机位", "俯拍", "仰拍", "平视", "鸟瞰", "焦段", "焦距", "景深",
    "虚化", "畸变", "像差", "缓推", "缓拉", "dolly", "track", "pan",
    "tilt", "crane", "orbit", "push in", "pull out", "zoom",
    "饱和度", "明度", "色相", "对比度", "冷调", "暖调",
    "范围", "边界", "走向", "面积", "深浅", "新旧", "力度", "速度",
    "角度", "高度", "距离", "方向", "轨迹", "位移", "厘米", "毫米",
)
PHYSICAL_RE = re.compile(
    "|".join(re.escape(w) for w in PHYSICAL_MARKERS), re.I)
WEAK_MARKERS = ("看向", "目光", "视线", "朝向", "纹理")
WEAK_RE = re.compile("|".join(WEAK_MARKERS), re.I)
GENERIC_QUANTIFIERS = {
    "范围", "角度", "速度", "高度", "距离", "方向", "力度",
    "面积", "深浅", "新旧", "走向", "边界", "轨迹", "位移",
}
CONCRETE_LOCUS_RE = re.compile(
    r"眉|眼|嘴角|下颌|手指|肩|背|头发|发梢|服装|道具|门|地面|画左|画右|"
    r"主光|补光|轮廓光|焦段|焦距|景深|色温|色相|饱和度|明度|材质|"
    r"\d+(?:\.\d+)?\s*(?:°|度|厘米|毫米|米|秒|s|%)", re.I)


def has_physical_locus(clause):
    """强落点直接成立；弱落点和通用量词必须绑定具体事实。"""
    concrete = [m.group(0) for m in PHYSICAL_RE.finditer(clause)
                if m.group(0) not in GENERIC_QUANTIFIERS]
    if concrete:
        return True
    if (WEAK_RE.search(clause) or any(q in clause for q in GENERIC_QUANTIFIERS)):
        return bool(CONCRETE_LOCUS_RE.search(clause))
    return False

# 小句切分：大标点与换行（逗号不断句 —— 物理量落点常在同句逗号后）
CLAUSE_RE = re.compile(r"[。；;！!？?\n]+")

# 教学式否定：「不写情绪词（"悲伤""欢快"）」这类在教规则/引用的不算裸奔
NEGATION_RE = re.compile(r"不写|不要写|避免|禁止|勿|别写|不得出现|不出现")

# 已归档失败项目：不阻断（与 check_project_conformance 同一语义）
FAIL_MARK_RE = re.compile(r"##\s*失败裁决")

PROMPT_EXT = {".md", ".txt"}


def split_clauses(text):
    """切成小句并剥掉行首字段标签（如 `overall_soundscape:`）。"""
    out = []
    for c in CLAUSE_RE.split(text):
        c = c.strip()
        if not c:
            continue
        # 去掉「字段名:」只剩标签本身的行不查（标签不是提示词正文）
        out.append(c)
    return out


def find_violations(text):
    """返回 [(情绪词, 小句原文)] —— 命中情绪词且同句无物理量标记。"""
    hits = []
    for clause in split_clauses(text):
        for m in EMOTION_RE.finditer(clause):
            lo = max(0, m.start() - 60)
            hi = min(len(clause), m.end() + 60)
            window = clause[lo:hi]
            if has_physical_locus(window):
                continue
            # 教学式否定豁免：词前紧邻「不写/避免/禁止」等 = 在教规则，不是裸奔
            pre = clause[max(0, m.start() - 12):m.start()]
            if NEGATION_RE.search(pre):
                continue
            hits.append((m.group(0), clause[:80]))
    return hits


def discover_prompt_files(proj):
    """发现项目内全部提示词文件（与切点均质度闸同一策略）。"""
    files = []
    seen = set()
    for sub in ("04-镜头/prompts", "04-镜头/提示词", "prompts"):
        d = os.path.join(proj, *sub.split("/"))
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                fp = os.path.join(d, fn)
                if os.path.splitext(fn)[1].lower() in PROMPT_EXT and fp not in seen:
                    seen.add(fp)
                    files.append(fp)
    lens_root = os.path.join(proj, "04-镜头")
    if os.path.isdir(lens_root):
        for fp in sorted(_glob.glob(os.path.join(lens_root, "**", "*"),
                                    recursive=True)):
            if os.path.isfile(fp) and os.path.splitext(fp)[1].lower() in PROMPT_EXT \
                    and fp not in seen:
                seen.add(fp)
                files.append(fp)
    return files


def _is_archived(proj):
    summary = os.path.join(proj, "项目状态摘要.md")
    if not os.path.isfile(summary):
        return False
    try:
        with open(summary, encoding="utf-8", errors="replace") as f:
            return bool(FAIL_MARK_RE.search(f.read()))
    except OSError:
        return False


def analyse(proj):
    """返回 (violations, facts)。violations = [(文件, 情绪词, 小句)]。"""
    violations = []
    n_files = 0
    for fp in discover_prompt_files(proj):
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        if not text.strip():
            continue
        n_files += 1
        for word, clause in find_violations(text):
            violations.append((os.path.relpath(fp, proj), word, clause))
    facts = {"提示词文件数": n_files, "违规数": len(violations)}
    return violations, facts


def discover_projects():
    """与切点均质度闸同一项目发现策略。"""
    root = SYSTEM_ROOT
    candidates = []
    container = os.path.join(root, "00-视频项目")
    if os.path.isdir(container):
        candidates.extend(
            os.path.join(container, n) for n in sorted(os.listdir(container))
            if os.path.isdir(os.path.join(container, n)))
    candidates.extend(
        os.path.join(root, n) for n in sorted(os.listdir(root))
        if os.path.isdir(os.path.join(root, n))
        and (n.endswith("项目") or n.startswith("《")))
    out, seen = [], set()
    for p in candidates:
        if p in seen or os.path.abspath(p) == os.path.abspath(container):
            continue
        seen.add(p)
        if os.path.basename(p).startswith("_"):
            continue  # 工作区目录（对标调研等）不是片子
        out.append(p)
    return out


def audit_all():
    """扫全部在制项目。无参数必须真扫（return 0 = 永远绿，是假绿）。"""
    projs = discover_projects()
    if not projs:
        print("[未评估] 未发现在制项目（无 04-镜头/），本闸没有可判对象")
        return 0
    active_bad, arch_bad, unevaluated = [], [], []
    ok_n = 0
    for p in projs:
        violations, facts = analyse(p)
        name = os.path.basename(p)
        arch = _is_archived(p)
        if facts["提示词文件数"] == 0:
            # D3：没有可扫对象 = 未评估（不再打印成「✓ 跳过」，但也不阻断）
            unevaluated.append(name)
            print("  {:<28s} [未评估] 无提示词文件".format(name))
            continue
        tag = "✗ {} 处".format(len(violations)) if violations else "✓"
        print("  {:<28s} 提示词 {} 份 {} {}".format(
            name, facts["提示词文件数"], tag, "[归档]" if arch else ""))
        if violations:
            (arch_bad if arch else active_bad).append((name, violations))
        else:
            ok_n += 1
    for name, violations in active_bad:
        print("\n⚠ {}：".format(name))
        for fp, word, clause in violations[:10]:
            print("   ✗ [{}] 「{}」：{}".format(word, fp, clause))
        if len(violations) > 10:
            print("   … 另有 {} 处".format(len(violations) - 10))
    if arch_bad:
        print("\n· 归档失败项目（已记录不阻断，计入未评估）：")
        for name, violations in arch_bad:
            print("  {}：{} 处".format(name, len(violations)))
    if unevaluated:
        print("· 未评估项目（无提示词文件）：{}".format("、".join(unevaluated)))
    n_uneval = len(unevaluated) + len(arch_bad)
    if active_bad:
        print("\n  修法：把情绪词翻译成 §8.1 十五维表里某一维的可指认物理量"
              "（面部写眉间/嘴角/下颌，光线写主光方位/光比……），"
              "或标注为意图层、不进提示词正文。")
        print(tally_line(ok_n, 0, n_uneval, len(active_bad)))
        return 1
    if n_uneval:
        print("⚠ " + tally_line(ok_n, 0, n_uneval) +
              "　—— 有未评估项，不算全绿")
        return 0
    print("✓ 在制项目提示词情绪词全部已翻译或不存在（{} 个项目）".format(ok_n))
    return 0


def selftest():
    """反例必须被抓、正例不得误报。"""
    ok = True

    def _run(text):
        return find_violations(text)

    # 反例 1：裸情绪词 → 必须抓
    v = _run("她感到十分愤怒，转身离开。")
    if not any(w == "愤怒" for w, _ in v):
        print("[自检失败] 裸「愤怒」未被抓：{}".format(v))
        ok = False
    else:
        print("[自检通过] 裸「愤怒」被抓")

    # 反例 2：另一个裸情绪词 + 跨句物理量不算数（必须同句）→ 必须抓
    v = _run("眉间紧锁。\n她的眼神里有明显的杀意和愤怒。")
    if not any(w == "愤怒" for w, _ in v):
        print("[自检失败] 跨句物理量不应豁免「愤怒」：{}".format(v))
        ok = False
    else:
        print("[自检通过] 跨句物理量不豁免（同句才算翻译）")

    # 正例 1：情绪词 + 同句物理量 → 放行
    v = _run("她 anger 地瞪着对方：眉间紧锁、嘴角下拉，愤怒写在脸上。")
    if v:
        print("[自检失败] 已翻译的「愤怒」被误报：{}".format(v))
        ok = False
    else:
        print("[自检通过] 同句带眉间/嘴角的「愤怒」放行")

    # 正例 2：全片无情绪词 → 放行
    v = _run("[Shot 1] At 00:00.000, slow dolly in. "
             "A woman stands by the door, 主光从画左 45 度入射。")
    if v:
        print("[自检失败] 干净提示词被误报：{}".format(v))
        ok = False
    else:
        print("[自检通过] 干净提示词不误报")

    # 反例 3：英文混排中的情绪词 → 必须抓
    v = _run("整体画面要有电影感，cinematic lighting everywhere.")
    if not any(w == "电影感" for w, _ in v):
        print("[自检失败] 裸「电影感」未被抓：{}".format(v))
        ok = False
    else:
        print("[自检通过] 裸「电影感」被抓")

    # 正例 4：教学式否定（「不写情绪词（"悲伤"）」在教规则）→ 放行
    v = _run("注意：不写情绪词（\"悲伤\"\"欢快\"），一律翻译成物理量。")
    if v:
        print("[自检失败] 教学式否定被误报：{}".format(v))
        ok = False
    else:
        print("[自检通过] 教学式否定（引号内情绪词）不误报")

    # 正例 3：电影感 + 同句焦段/景深落点 → 放行
    v = _run("镜头用 85mm 长焦、浅景深，电影感来自焦外虚化而非情绪词。")
    if v:
        print("[自检失败] 已翻译的「电影感」被误报：{}".format(v))
        ok = False
    else:
        print("[自检通过] 同句带焦段/景深的「电影感」放行")

    # 反例 5：通用量词不能单独冒充物理落点
    v = _run("画面很紧张，范围很大，角度很高，速度很快。")
    if not any(w == "紧张" for w, _ in v):
        print("[自检失败] 空泛范围/角度/速度绕过了情绪词闸：{}".format(v))
        ok = False
    else:
        print("[自检通过] 空泛范围/角度/速度被抓")

    # 正例 5：通用量词绑定部位和数值时放行
    v = _run("她很紧张，眉间收紧 3 毫米，下颌角度 15°，视线朝画右。")
    if v:
        print("[自检失败] 具体部位/数值被误报：{}".format(v))
        ok = False
    else:
        print("[自检通过] 通用量词绑定具体部位/数值后放行")

    for text in ("她愤怒地看向他。", "他愤怒，阴影很重。", "他愤怒，纹理粗糙。"):
        v = _run(text)
        if not v:
            print("[自检失败] 弱词单独冒充物理落点：{}".format(text))
            ok = False
        else:
            print("[自检通过] 弱词单独冒充物理落点被抓：{}".format(text))
    v = _run("她心虚，视线停在画右门口 2 秒。")
    if v:
        print("[自检失败] 弱词绑定具体落点后被误报：{}".format(v))
        ok = False
    else:
        print("[自检通过] 弱词绑定具体落点后放行")

    # 反例 4：项目级集成 —— 临时项目里放一份裸情绪词提示词 → analyse 必须抓
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "04-镜头", "prompts"))
        with open(os.path.join(td, "04-镜头", "prompts", "S01.md"),
                  "w", encoding="utf-8") as f:
            f.write("[Shot 1] 她看起来很悲伤。\n")
        with open(os.path.join(td, "04-镜头", "prompts", "S02.md"),
                  "w", encoding="utf-8") as f:
            f.write("[Shot 1] 她嘴角上扬、眼睑微抬，喜悦写在脸上。\n")
        violations, facts = analyse(td)
        if len(violations) != 1 or violations[0][1] != "悲伤":
            print("[自检失败] 项目级集成应只抓 1 处「悲伤」，实际：{}".format(
                violations))
            ok = False
        else:
            print("[自检通过] 项目级集成：裸「悲伤」被抓、带物理量的放行")

    import contextlib
    import io
    container = os.path.join(SYSTEM_ROOT, "00-视频项目")
    os.makedirs(container, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=container) as good, tempfile.TemporaryDirectory(dir=container) as empty:
        os.makedirs(os.path.join(good, "04-镜头", "prompts"))
        with open(os.path.join(good, "04-镜头", "prompts", "S01.md"), "w", encoding="utf-8") as f:
            f.write("她嘴角上扬、眼睑微抬，喜悦写在脸上。")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            audit_all()
        if "[未评估]" not in stdout.getvalue() or os.path.basename(empty) not in stdout.getvalue():
            print("[自检失败] 混合项目空项目被隐藏：{}".format(stdout.getvalue()))
            ok = False
        else:
            print("[自检通过] 混合项目空项目逐项未评估")

    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(description="情绪词硬闸：情绪词必须已翻译成物理量")
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
    violations, facts = analyse(a.project)
    print("提示词文件 {} 份，违规 {} 处".format(
        facts["提示词文件数"], facts["违规数"]))
    for fp, word, clause in violations[:20]:
        print("  ✗ [{}] {}：{}".format(word, fp, clause))
    if facts["提示词文件数"] == 0:
        # D3：没有可判对象 = 未评估，不是通过（exit 0 不阻断）
        print("[未评估] 无提示词文件可扫，本闸不表态")
        return 0
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
