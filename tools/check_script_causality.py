#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剧本因果闸 · G1 剧本"像 PPT、看不懂在讲什么"的落地检查。

**为什么需要**
其余真片闸都从 G3 分镜表起查，G1 剧本没有任何一道闸。旧剧本模板每场五块
并列槽位（场景头 / 人物 / 动作与表演 / 台词 / 本场结束状态），结构上就是一页
幻灯片：五块平行的格子产出五块平行的内容，场与场之间只有时间先后、没有
因为所以。实测两份试片剧本：一份正文写满"刀 1｜0.0–3.0s / 低机位 0.5 米 /
光比 2:1"，另一份标题就叫"视听脚本（90 秒 · 22 刀）"——G1 是唯一还能便宜
改故事的阶段，读者却只读得到参数。

**查什么**（对象是 `01-剧本/剧本.md`）
  ① 片型：头部声明 `片型：叙事 / 意象`，二选一（未声明按叙事查）。
  ② 叙事片每个「## 场景」都有「本场因果」四句：因为 / 所以 / 但是 / 于是，
     且「因为」「但是」不是空话（然后 / 接着 / 遇到困难 / 无 / 同上 / 略 …）。
     第 2 场起，「因为」不许写"—"（开场之外都必须有前置原因）。
  ③ 道具翻转不是每集配额；若填写 `〔道具名：第一次＝… ／ 第二次＝…〕`，两半都必须填实。
  ④ 意象片「意象变奏」表：至少一个意象出现 ≥3 次，且「意味着」去重 ≥3。
  ⑤ 正文（场景/幕段落内）不含执行参数：刀号、时间码、机位、光比、焦段、
     景别、色温、`mm`。
  ⑥ 「朗读测试」已做：复述者 + 三问（谁想要什么 / 被什么挡住 / 最后卡在哪）
     填实，判定 = 通过。

**边界**
  · 只证明"剧本写出了因果、没塞参数、有人在读之前独立复述过"，不证明故事
    好看——好看靠朗读测试的人，不靠正则。
  · 不查「于是→因为」语义是否真的接上（正则判不了语义）；接没接上由朗读
    测试兜底。
  · 只扫模板改造后的剧本：`项目状态摘要.md` 里 `立项日：YYYY-MM-DD` 早于
    SCRIPT_CUTOVER 的项目记"未评估"（旧模板没有这些槽位，不追溯）；没写
    立项日时以剧本文件修改日期代替——旧剧本一旦重新编辑，就按新规则查。
  · 已归档失败项目不阻断。

**用法**
    python tools/check_script_causality.py <项目目录>
    python tools/check_script_causality.py            # 扫全部在制项目
    python tools/check_script_causality.py <项目目录> --force
                                                      # 存量项目强制按当前模板查
    python tools/check_script_causality.py --selftest

**定点与全扫同一口径**：两种调用都先过 `eligibility()` 的追溯判断——剧本/立项日
早于 `SCRIPT_CUTOVER` 的项目一律记「未评估」。要强制查存量项目，用 `--force`，
输出里会明写「强制评估」。以前定点分支直接 `analyse()` 跳过这个判断，同一个项目
「全扫说不归我管、定点判 13 条不合格」，两个 Agent 各跑一种会拿相反结论做下一步。

**退出码**：0 全绿（含「未评估」跳过）/ 1 有缺项 / 2 用法或自检失败
"""
import argparse
import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)

from _film_gate_waivers import load_waivers, is_waived, tally_line
from _film_type import read_film_type

GATE = "剧本因果-真片"
# 剧本模板加入因果槽位的日期；之前立项的项目用的是旧模板，不追溯。
SCRIPT_CUTOVER = datetime.date(2026, 10, 19)

FAIL_MARK_RE = re.compile(r"##\s*失败裁决")
INCEPTION_RE = re.compile(r"立项日[期]?\s*[:：]\s*\**\s*(\d{4}-\d{2}-\d{2})")
GENRE_RE = re.compile(r"片型\s*[:：]\s*\**\s*(叙事|意象)(?!\s*/)")
SCENE_HEAD_RE = re.compile(r"^##\s*(场景|幕)")
H2_RE = re.compile(r"^##\s")
CAUSE_KEYS = ("因为", "所以", "但是", "于是")
CAUSE_LINE_RE = re.compile(r"^\s*[-*]?\s*\**(因为|所以|但是|于是)\**\s*[:：]\s*(.*)$")
# 空话：写了等于没写的「因为/但是」
HOLLOW_RE = re.compile(
    r"^(?:[—\-–/／…\.。、\s]*|无|没有|暂无|同上|略|待定|待补|TBD|然后.*|接着.*|"
    r"之后.*|随后.*|遇到困难|遇到阻碍|遇到问题|出现问题|发生意外)$", re.I)
PLACEHOLDER_RE = re.compile(r"^[（(].*[）)]$")
FIELD_RE = re.compile(r"^\s*[-*]?\s*\**([^：:]+)\**\s*[:：]\s*(.*?)\s*$")
VIABILITY_FIELDS = ("主角当集目标", "核心阻力", "失败的代价")
VIABILITY_ANTI = ("他想要什么", "什么阻力", "待填", "填写", "某人", "某物", "一个目标", "核心阻力")
PROP_FLIP_RE = re.compile(r"〔([^〔〕：:]+)[：:]\s*第一次\s*[＝=]\s*([^／/〕]*)[／/]\s*"
                          r"第二次\s*[＝=]\s*([^〕]*)〕")
# 执行参数黑名单（只在场景/幕正文里查；引导说明里提到这些词是在禁止它们）
EXEC_PARAM_RES = (
    ("刀号", re.compile(r"刀\s*\d+|第\s*\d+\s*刀|\d+\s*刀\b")),
    ("时间码", re.compile(r"\d+(?:\.\d+)?\s*[–\-~～至]\s*\d+(?:\.\d+)?\s*s\b")),
    ("机位", re.compile(r"机位")),
    ("光比", re.compile(r"光比")),
    ("焦段", re.compile(r"焦段|\d{2,3}\s*mm\b")),
    ("景别", re.compile(r"景别|特写|近景|中景|全景|远景")),
    ("色温", re.compile(r"色温|\d{4}\s*K\b")),
)
READ_QS = ("谁想要什么", "被什么挡住", "最后卡在哪")


def find_script(proj):
    for rel in ("01-剧本/剧本.md", "01-剧本/剧本.txt"):
        fp = os.path.join(proj, *rel.split("/"))
        if os.path.isfile(fp):
            return fp
    return None


def _strip_md(s):
    return s.strip().strip("*").strip()


def _hollow(v):
    v = _strip_md(v)
    return not v or bool(HOLLOW_RE.match(v)) or bool(PLACEHOLDER_RE.match(v))


def read_named_fields(txt):
    fields = {}
    for line in txt.splitlines():
        m = FIELD_RE.match(line)
        if m and m.group(1).strip() in VIABILITY_FIELDS:
            fields[m.group(1).strip()] = m.group(2).strip()
    return fields

def viability_issues(txt, genre):
    if genre == "意象":
        m = re.search(r"立意语域\s*[:：]\s*(.*)", txt)
        v = (m.group(1).strip() if m else "")
        if _hollow(v) or v in ("（本片希望观众用什么语域理解它：生活观察 / 寓言 / 诗性影像 / 其他）",):
            return ["⑦ 意象片缺「立意语域」—— 意象变奏必须能回指本片的理解语域"]
        return []
    fields = read_named_fields(txt)
    issues = []
    hints = {
        "主角当集目标": "他想要什么、为谁、什么时限",
        "核心阻力": "谁/什么在阻止、用什么手段",
        "失败的代价": "失败后会失去什么、影响谁或哪项关系",
    }
    for field in VIABILITY_FIELDS:
        v = _strip_md(fields.get(field, ""))
        if _hollow(v) or len(v) < 8 or any(x in v for x in VIABILITY_ANTI):
            issues.append("⑦ {}「{}」不构成成立性信息：需要具体到{}".format(
                field, v or "未填", hints[field]))
    return issues


def split_sections(txt):
    """[(标题, 正文行列表)]，按 `## ` 切。"""
    secs, cur = [], None
    for line in txt.splitlines():
        if H2_RE.match(line):
            cur = (line.strip(), [])
            secs.append(cur)
        elif cur is not None:
            cur[1].append(line)
    return secs


def _body_lines(lines):
    """去掉引用块（> 说明）与代码块，只留作者写的正文。"""
    out, fence = [], False
    for ln in lines:
        if ln.strip().startswith("```"):
            fence = not fence
            continue
        if fence or ln.lstrip().startswith(">"):
            continue
        out.append(ln)
    return out


def analyse(proj):
    problems, facts = [], {}
    fp = find_script(proj)
    if not fp:
        problems.append("未找到 01-剧本/剧本.md —— 无法做剧本因果检查")
        facts["剧本"] = None
        return problems, facts
    with open(fp, encoding="utf-8", errors="replace") as f:
        txt = f.read()
    facts["剧本"] = os.path.relpath(fp, proj)

    genre, genre_source = read_film_type(proj)
    facts["片型"] = genre + "（{}）".format(genre_source)

    secs = split_sections(txt)
    scenes = [(h, _body_lines(ls)) for h, ls in secs if SCENE_HEAD_RE.match(h)]
    facts["场数"] = len(scenes)
    if not scenes:
        problems.append("① 没有任何「## 场景 NN」段 —— 剧本按场写，不按刀写")
        return problems, facts

    # ⑤ 执行参数
    hits = {}
    for h, ls in scenes:
        body = "\n".join([h] + ls)
        for label, rx in EXEC_PARAM_RES:
            if rx.search(body):
                hits.setdefault(label, []).append(h.lstrip("# ").strip())
    for label, where in hits.items():
        problems.append("⑤ 正文出现执行参数「{}」（{}）—— 剧本不是分镜，参数移到 G3"
                        .format(label, "、".join(where[:3]) +
                                ("…" if len(where) > 3 else "")))

    viability = viability_issues(txt, genre)
    problems.extend(viability)
    facts["成立性检查"] = "通过" if not viability else "未通过"

    if genre == "叙事":
        # ② 每场因果四句
        n_ok = 0
        for idx, (h, ls) in enumerate(scenes):
            name = h.lstrip("# ").strip()
            got = {}
            for ln in ls:
                cm = CAUSE_LINE_RE.match(ln)
                if cm and cm.group(1) not in got:
                    got[cm.group(1)] = cm.group(2)
            missing = [k for k in CAUSE_KEYS if k not in got]
            if missing:
                problems.append("② {} 缺「本场因果」的 {} —— 先填因为/所以/但是/于是"
                                "再写戏".format(name, "/".join(missing)))
                continue
            bad = []
            for k in ("所以", "于是"):
                if _hollow(got[k]):
                    bad.append(k)
            if _hollow(got["但是"]):
                bad.append("但是")
            v = _strip_md(got["因为"])
            if idx == 0:
                if v and not re.fullmatch(r"[—\-–\s]*", v) and _hollow(v):
                    bad.append("因为")
            elif _hollow(v):
                bad.append("因为")
            if bad:
                problems.append("② {} 的「{}」是空话或未填 —— 这是「然后」型场次："
                                "写出上一场的哪件事、谁具体挡住他".format(
                                    name, "/".join(sorted(set(bad),
                                                          key=CAUSE_KEYS.index))))
            else:
                n_ok += 1
        facts["因果完整场数"] = n_ok

        # ③ 道具翻转
        flips = [(p, a, b) for p, a, b in PROP_FLIP_RE.findall(txt)
                 if not _hollow(p) and not _hollow(a) and not _hollow(b)
                 and _strip_md(p) != "道具名"]
        facts["道具翻转"] = len(flips)
        if not flips and PROP_FLIP_RE.search(txt):
            problems.append("③ 道具翻转仍是模板或空话 —— 若使用道具翻转，两半都必须填实："
                            "〔道具名：第一次＝… ／ 第二次＝…〕")
    else:
        # ④ 意象变奏
        rows = {}
        for h, ls in secs:
            if "意象变奏" not in h:
                continue
            for ln in _body_lines(ls):
                s = ln.strip()
                if not s.startswith("|"):
                    continue
                cells = [c.strip() for c in s.strip("|").split("|")]
                if len(cells) < 4 or cells[0] in ("意象", "") or \
                        set(cells[0]) <= set("-: "):
                    continue
                if _hollow(cells[3]):
                    continue
                rows.setdefault(cells[0], set()).add(cells[3])
        best = max((len(v) for v in rows.values()), default=0)
        facts["意象变奏"] = {k: len(v) for k, v in rows.items()}
        if best < 3:
            problems.append("④ 意象片没有成立的变奏 —— 至少一个意象出现 ≥3 次，"
                            "且每次「意味着」都不同（当前最多 {} 种）".format(best))

    # ⑥ 朗读测试
    rsec = [ls for h, ls in secs if "朗读测试" in h]
    if not rsec:
        problems.append("⑥ 缺「朗读测试」—— 找新上下文读者只读场景部分，复述三问")
    else:
        body = _body_lines(rsec[0])
        kv = {}
        for ln in body:
            mm = re.match(r"^\s*[-*]?\s*\**([^:：*]+?)\**\s*[:：]\s*(.*)$", ln)
            if mm:
                key = re.sub(r"（[^）]*）", "", mm.group(1)).strip()
                kv[key] = mm.group(2)
        required = ("意象如何逐次递进",) if genre == "意象" else READ_QS
        lack = [q for q in ("复述者",) + required if _hollow(kv.get(q, ""))]
        verdict = _strip_md(kv.get("判定", ""))
        if lack:
            problems.append("⑥ 朗读测试未做完：{} 未填".format("/".join(lack)))
        elif verdict != "通过":
            problems.append("⑥ 朗读测试判定为「{}」—— 复述和作者意图对不上就改剧本，"
                            "不改答案".format(verdict or "空"))
    return problems, facts


def _inception(proj):
    """(日期, 来源)。优先 `立项日`，缺失时用剧本文件修改日期。"""
    summary = os.path.join(proj, "项目状态摘要.md")
    if os.path.isfile(summary):
        try:
            with open(summary, encoding="utf-8", errors="replace") as f:
                m = INCEPTION_RE.search(f.read())
            if m:
                return datetime.date.fromisoformat(m.group(1)), "立项"
        except (OSError, ValueError):
            pass
    fp = find_script(proj)
    if fp:
        return datetime.date.fromtimestamp(os.path.getmtime(fp)), "剧本修改"
    return None, None


def _is_archived(proj):
    summary = os.path.join(proj, "项目状态摘要.md")
    if not os.path.isfile(summary):
        return False
    try:
        with open(summary, encoding="utf-8", errors="replace") as f:
            return bool(FAIL_MARK_RE.search(f.read()))
    except OSError:
        return False


def eligibility(proj):
    """(是否纳入本闸评估, 说明)。剧本模板改造日之前的剧本按设计不追溯。"""
    d, src = _inception(proj)
    if d is not None and d < SCRIPT_CUTOVER:
        return False, "{} {} 早于剧本模板改造 {}".format(src, d, SCRIPT_CUTOVER)
    return True, ""


def judge(proj, force=False):
    """定点评估一个项目，返回 (状态, 附注, problems, facts)。

    状态 ∈ "ok" / "bad" / "unevaluated"。**定点与全扫共用 `eligibility()`**：
    早于改造日的项目默认记「未评估」；`force=True`（命令行 `--force`）才强制
    按当前模板评估，并在附注里写明这是强制评估。
    """
    eligible, why = eligibility(proj)
    if not eligible and not force:
        return "unevaluated", why, [], {}
    problems, facts = analyse(proj)
    note = "强制评估：忽略追溯豁免（{}）".format(why) if not eligible else ""
    return ("bad" if problems else "ok"), note, problems, facts


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
    with_script = [p for p in all_projs if find_script(p)]
    unevaluated = [os.path.basename(p) + "（无剧本）"
                   for p in all_projs if p not in with_script]
    projs = []
    for p in with_script:
        eligible, why = eligibility(p)
        if not eligible:
            unevaluated.append("{}（{}）".format(os.path.basename(p), why))
        else:
            projs.append(p)
    if not projs:
        print("· 未评估：{}".format("、".join(unevaluated) or "无"))
        print("[未评估] 没有按新剧本模板立项的在制项目，本闸没有可判对象")
        return 0
    active_bad, arch_bad, waived = [], [], []
    ok_n = 0
    for p in projs:
        problems, facts = analyse(p)
        name = os.path.basename(p)
        wvd = bool(problems) and is_waived(waivers, name, GATE)
        tag = ("WAIVED（{} 条，已登记豁免）".format(len(problems)) if wvd
               else ("✗ {} 条".format(len(problems)) if problems else "✓"))
        print("  {:<28s} 场数={:<3d} {}".format(name, facts.get("场数", 0), tag))
        if not problems:
            ok_n += 1
        elif wvd:
            waived.append(name)
        elif _is_archived(p):
            arch_bad.append((name, problems))
        else:
            active_bad.append((name, problems))
    for name, problems in active_bad:
        print("\n⚠ {}：".format(name))
        for x in problems[:8]:
            print("   ✗ " + x[:120])
        if len(problems) > 8:
            print("   … 另有 {} 条".format(len(problems) - 8))
    if arch_bad:
        print("\n· 归档失败项目（已记录不阻断，计入未评估）：")
        for name, problems in arch_bad:
            print("  {}：{} 条".format(name, len(problems)))
    if waived:
        print("\n· 已豁免（WAIVED）：{}".format("、".join(waived)))
    if unevaluated:
        print("· 未评估：{}".format("、".join(unevaluated)))
    n_uneval = len(unevaluated) + len(arch_bad)
    if active_bad:
        print("\n  修法：按 模板/短剧项目模板/01-剧本/剧本.md 每场先填因为/所以/但是/于是；"
              "参数移到 G3；若用道具翻转就填实含义变化；找新上下文读者做朗读测试。")
        print(tally_line(ok_n, len(waived), n_uneval, len(active_bad)))
        return 1
    if waived or n_uneval:
        print("⚠ " + tally_line(ok_n, len(waived), n_uneval) +
              "　—— 有豁免/未评估，不算全绿")
        return 0
    print("✓ 在制项目剧本因果全部合格（{} 个项目）".format(ok_n))
    print(tally_line(ok_n, 0, 0))
    return 0


GOOD = """# G1 单集剧本
- 片型：叙事

## 叙事决策锁定
- 主角当集目标：阿哲要在今晚十点前抓到真正挤牙膏的人，替室友洗清嫌疑
- 核心阻力：小满拒绝配合，第三个人还会趁夜进入客厅销毁牙膏
- 失败的代价：阿哲错过唯一的取证机会，室友会继续被群里认定为小偷

## 场景 01
**场景头：** 内 · 合租客厅 · 日
**本场因果：**
- 因为：—
- 所以：阿哲把被挤瘪的牙膏拍在茶几上，要小满当场承认
- 但是：小满说她根本不用这支，她用的是电动牙刷配的那支
- 于是：阿哲认定还有第三个人在用，决定做实验抓人

**戏：**
阿哲把牙膏管竖起来，像举一支试管。他要的是一个能写进群公告的数字。
阿哲："从中间挤，计时。"

## 场景 02
**场景头：** 内 · 楼道 · 日
**本场因果：**
- 因为：实验证明挤法和小满对不上，阿哲认定是二房东阿凯
- 所以：阿哲拿着租客公约敲开阿凯的门
- 但是：阿凯根本不刷牙，他嚼口香糖
- 于是：头顶通风口一响，橘猫叼着一支带牙印的同款牙膏掉下来

**戏：**
阿哲把公约翻到第七条，手指压在上面。阿凯嚼着口香糖，看都没看。

## 道具翻转
- 〔牙膏：第一次＝室友不守规矩的证据 ／ 第二次＝阿哲冤枉了所有人的证据〕

## 朗读测试
- 复述者：新上下文 Agent 2026-10-19
- 谁想要什么：阿哲想抓到乱挤牙膏的人
- 被什么挡住：每个嫌疑人都有不在场的理由
- 最后卡在哪：真凶是猫，他刚把公约拍在二房东门上
- 判定：通过
"""


def selftest():
    import tempfile
    ok = True

    def run(content, summary=None):
        td = tempfile.mkdtemp()
        os.makedirs(os.path.join(td, "01-剧本"))
        with open(os.path.join(td, "01-剧本", "剧本.md"), "w", encoding="utf-8") as f:
            f.write(content)
        if summary:
            with open(os.path.join(td, "项目状态摘要.md"), "w", encoding="utf-8") as f:
                f.write(summary)
        return td, analyse(td)

    def expect(label, content, tag, must=True):
        nonlocal ok
        _td, (problems, _f) = run(content)
        hit = any(p.startswith(tag) for p in problems)
        if hit != must:
            print("[自检失败] {}：{}".format(label, problems))
            ok = False
        else:
            print("[自检通过] {}".format(label))

    # 正例：完整剧本 → 零问题
    _td, (problems, facts) = run(GOOD)
    if problems:
        print("[自检失败] 合规剧本被误报：{}".format(problems))
        ok = False
    else:
        print("[自检通过] 合规剧本（两场因果闭合 + 道具翻转 + 朗读通过）未误报")

    # 反例：旧五槽模板（PPT 结构）→ ② 缺因果
    old = ("## 场景 01\n**场景头：** 内 · 客厅 · 日\n**人物：** 阿哲\n"
           "**动作与表演：** 阿哲挤牙膏\n**台词：** 阿哲：\"计时。\"\n"
           "**本场结束状态：** 实验开始\n")
    expect("旧五槽模板（无因果）被抓", old, "②")

    # 反例：「但是」填空话
    expect("「但是：遇到困难」被抓",
           GOOD.replace("但是：小满说她根本不用这支，她用的是电动牙刷配的那支",
                        "但是：遇到困难"), "②")

    # 反例：第 2 场「因为」写然后
    expect("第 2 场「因为：然后他去了楼道」被抓",
           GOOD.replace("因为：实验证明挤法和小满对不上，阿哲认定是二房东阿凯",
                        "因为：然后他去了楼道"), "②")

    # 反例：模板占位（括号说明原样留着）
    expect("模板括号占位未改被抓",
           GOOD.replace("所以：阿哲拿着租客公约敲开阿凯的门",
                        "所以：（他为此做了什么——一个看得见的动作）"), "②")

    # 反例：正文塞执行参数
    expect("正文「刀 1｜0.0–3.0s 低机位 光比 2:1 35mm」被抓",
           GOOD.replace("阿哲把牙膏管竖起来，像举一支试管。",
                        "刀 1｜0.0–3.0s：低机位，光比 2:1，35mm。"), "⑤")

    # 正例：引用块里讲"禁止写机位"不算违规
    expect("引用块里的禁令说明不误报",
           GOOD.replace("## 场景 01\n", "## 场景 01\n> 禁止写机位、光比、景别。\n"),
           "⑤", must=False)

    # 道具不是每集配额；没有道具不拦，占位道具仍拦
    expect("没有道具翻转不强行拦截",
           GOOD.replace("- 〔牙膏：第一次＝室友不守规矩的证据 ／ "
                        "第二次＝阿哲冤枉了所有人的证据〕", ""), "③", must=False)
    expect("道具翻转模板原样未改被抓",
           GOOD.replace("〔牙膏：第一次＝室友不守规矩的证据 ／ "
                        "第二次＝阿哲冤枉了所有人的证据〕",
                        "〔道具名：第一次＝（它当时意味着什么） ／ "
                        "第二次＝（现在意味着什么）〕"), "③")

    # 反例：朗读测试未做 / 判不通过
    expect("朗读测试缺失被抓", GOOD.split("## 朗读测试")[0], "⑥")
    expect("朗读测试判定不通过被抓",
           GOOD.replace("- 判定：通过", "- 判定：不通过"), "⑥")
    expect("朗读测试复述者空被抓",
           GOOD.replace("- 复述者：新上下文 Agent 2026-10-19", "- 复述者："), "⑥")

    # 意象片：变奏 ≥3 且意思不同 → 放行；三次意思相同 → 抓
    img_base = ("- 片型：意象\n\n## 幕一\n纯黑里一粒光，像心跳。\n\n"
                "## 意象变奏\n| 意象 | 第几次 | 出现在 | 这一次它意味着 |\n"
                "|---|---|---|---|\n"
                "| 呼吸 | 1 | 幕一 | {a} |\n| 呼吸 | 2 | 幕二 | {b} |\n"
                "| 呼吸 | 3 | 幕三 | {c} |\n\n"
                "## 朗读测试\n- 复述者：真人 2026-10-19\n"
                "- 谁想要什么：宇宙想醒过来\n- 被什么挡住：黑暗和寂静\n"
                "- 最后卡在哪：婴儿第一次哭出声\n- 判定：通过\n")
    expect("意象片变奏递进放行",
           img_base.format(a="宇宙诞生", b="生命出现", c="一个人出生"), "④",
           must=False)
    expect("意象片三次同义被抓",
           img_base.format(a="生命", b="生命", c="生命"), "④")
    expect("意象片不要求因果四句",
           img_base.format(a="宇宙诞生", b="生命出现", c="一个人出生"), "②",
           must=False)

    # 立项日早于改造日 → 不纳入全扫（未评估），晚于则纳入
    _td, _ = run(old, "- 立项日：2026-10-13\n")
    d, _src = _inception(_td)
    if d is None or not d < SCRIPT_CUTOVER:
        print("[自检失败] 旧立项日应被识别为改造前：{}".format(d))
        ok = False
    else:
        print("[自检通过] 改造前立项的项目识别为未评估（不追溯旧模板）")
    _td, _ = run(old)
    os.utime(os.path.join(_td, "01-剧本", "剧本.md"), (0, 0))
    d, src = _inception(_td)
    if src != "剧本修改" or not d < SCRIPT_CUTOVER:
        print("[自检失败] 无立项日时应回落到剧本修改日期：{} {}".format(d, src))
        ok = False
    else:
        print("[自检通过] 无立项日时以剧本修改日期判断新旧")

    # 定点与全扫同一口径（2026-10-19 修：定点分支曾直接 analyse()，绕过追溯判断，
    # 同一个存量项目「全扫说不归我管、定点判 13 条不合格」，两个 Agent 结论相反）
    _td, _ = run(old, "- 立项日：2026-10-13\n")
    st, _note, probs, _f = judge(_td)
    if st != "unevaluated" or probs:
        print("[自检失败] 定点默认口径应与全扫一致（旧项目记未评估）：{} {}".format(st, probs))
        ok = False
    else:
        print("[自检通过] 定点默认与全扫同口径：改造前项目记未评估")
    st, note, probs, _f = judge(_td, force=True)
    if st != "bad" or not any(p.startswith("②") for p in probs) or "强制评估" not in note:
        print("[自检失败] --force 应强制判不合格并标注口径：{} {} {}".format(st, note, probs))
        ok = False
    else:
        print("[自检通过] --force 强制评估存量项目（判②缺因果，并标注强制口径）")
    _td, _ = run(GOOD)
    st, note, probs, _f = judge(_td)
    if st != "ok" or probs or note:
        print("[自检失败] 新项目定点应正常判绿：{} {} {}".format(st, note, probs))
        ok = False
    else:
        print("[自检通过] 新项目定点判绿（加口径后没有误跳过）")

    # 模板对齐：原样复制体系模板 → 必须被抓（空槽 = 未写）；
    # 把模板槽位按样例填实 → 必须放行。证明闸认的字段就是模板给的字段，
    # 模板改了字段名而闸没跟上时这里会红。
    tpl = os.path.join(SYSTEM_ROOT, "模板", "短剧项目模板", "01-剧本", "剧本.md")
    if not os.path.isfile(tpl):
        print("[自检失败] 找不到剧本模板：{}".format(tpl))
        return 2
    with open(tpl, encoding="utf-8") as f:
        tpl_txt = f.read()
    _td, (problems, facts) = run(tpl_txt)
    if facts.get("场数", 0) < 2 or not any(p.startswith("②") for p in problems):
        print("[自检失败] 空模板应解析出 ≥2 场且报 ② 未填：{} {}".format(facts, problems))
        ok = False
    elif any(p.startswith("⑤") for p in problems):
        print("[自检失败] 模板自身的说明文字触发了执行参数误报：{}".format(problems))
        ok = False
    else:
        print("[自检通过] 空模板被抓（{} 场未填），且模板说明不误报参数".format(
            facts["场数"]))
    filled = tpl_txt.replace("- 片型：叙事 / 意象", "- 片型：叙事")
    filled = filled.replace("- 主角当集目标：", "- 主角当集目标：阿哲要在今晚十点前抓到挤牙膏的人", 1)
    filled = filled.replace("- 核心阻力：", "- 核心阻力：小满拒绝配合且第三个人会销毁证据", 1)
    filled = filled.replace("- 失败的代价：", "- 失败的代价：室友会继续被冤枉而证据消失", 1)
    for k, v in (("因为：（上一场留下的事，或他此刻非做不可的理由）", "因为：—"),
                 ("所以：（他为此做了什么——一个看得见的动作）", "所以：阿哲把牙膏拍在茶几上"),
                 ("但是：（谁或什么挡住他；挡法要具体，\"遇到困难\"不算）",
                  "但是：小满说她不用这支"),
                 ("于是：（状态变成什么——它就是下一场的「因为」）",
                  "于是：阿哲决定做实验抓人")):
        filled = filled.replace(k, v, 1)
    filled = re.sub(r"- 因为：\n", "- 因为：实验指向二房东\n", filled, count=1)
    filled = re.sub(r"- 所以：\n", "- 所以：阿哲敲开阿凯的门\n", filled, count=1)
    filled = re.sub(r"- 但是：\n", "- 但是：阿凯不刷牙\n", filled, count=1)
    filled = re.sub(r"- 于是：\n", "- 于是：橘猫叼着牙膏掉下来\n", filled, count=1)
    filled = filled.replace("〔道具名：第一次＝（它当时意味着什么） ／ 第二次＝（现在意味着什么）〕",
                            "〔牙膏：第一次＝室友的罪证 ／ 第二次＝冤枉人的罪证〕")
    filled = filled.replace("- 失败的代价：", "- 失败的代价：阿哲会错过当晚抓住真凶的唯一机会，室友也会被继续冤枉", 1)
    for k, v in (("复述者", "新上下文 Agent"), ("谁想要什么", "阿哲想抓人"),
                 ("被什么挡住", "嫌疑人都不是"), ("最后卡在哪", "真凶是猫"),
                 ("判定", "通过")):
        filled = re.sub(r"(?m)^- {}(?:（[^）]*）)?：.*$".format(k), "- {}：{}".format(k, v),
                        filled, count=1)
    _td, (problems, _f) = run(filled)
    if problems:
        print("[自检失败] 按模板槽位填实后仍被报：{}".format(problems))
        ok = False
    else:
        print("[自检通过] 按模板槽位填实后放行（闸与模板字段一致）")
    image = tpl_txt.replace("- 片型：叙事 / 意象", "- 片型：意象")
    image = re.sub(r"(?m)^- 立意语域：.*$", "- 立意语域：诗性影像", image, count=1)
    for n, meaning in ((1, "陌生"), (2, "归途"), (3, "选择")):
        image = image.replace("| | {} | | |".format(n), "| 光 | {} | 幕{} | {} |".format(n, n, meaning))
    for k, v in (("复述者", "新上下文 Agent"), ("意象如何逐次递进", "光从陌生变成归途再变成选择"), ("判定", "通过")):
        image = re.sub(r"(?m)^- {}（仅片型＝意象）：.*$".format(k), "- {}（仅片型＝意象）：{}".format(k, v), image, count=1)
    image = re.sub(r"(?m)^- 复述者：.*$", "- 复述者：新上下文 Agent", image, count=1)
    image = re.sub(r"(?m)^- 判定：.*$", "- 判定：通过", image, count=1)
    _td, (problems, _f) = run(image)
    if problems:
        print("[自检失败] 意象片朗读递进被误报：{}".format(problems))
        ok = False
    else:
        print("[自检通过] 意象片只填朗读递进即可")
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(description="剧本因果闸：因果四句 + 无执行参数 + 道具翻转 + 朗读测试")
    ap.add_argument("project", nargs="?", help="项目目录（省略则扫全部在制项目）")
    ap.add_argument("--force", action="store_true",
                    help="定点模式强制按当前模板评估，忽略「旧模板不追溯」豁免")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.project:
        return audit_all()
    if not os.path.isdir(a.project):
        print("目录不存在：{}".format(a.project))
        return 2
    status, note, problems, facts = judge(a.project, force=a.force)
    print("  口径：{}".format("--force 强制评估（忽略追溯豁免）" if a.force
                           else "与全扫同一套追溯判断"))
    if status == "unevaluated":
        print("  [未评估] {}".format(note))
        print("  　该项目的剧本早于剧本模板改造日，按设计不追溯本闸；"
              "要强制按当前模板查，加 --force")
        return 0
    if note:
        print("  注：{}".format(note))
    for k, v in facts.items():
        print("  {}：{}".format(k, v))
    for p in problems[:20]:
        print("  ✗ " + p)
    if len(problems) > 20:
        print("  … 另有 {} 条".format(len(problems) - 20))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
