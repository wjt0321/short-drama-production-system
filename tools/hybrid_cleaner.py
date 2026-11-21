#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
剧本清理器 v4（规则层 + 模型层）
================================
EP02 实测教训（本脚本的立论依据）:
  v2 检查器模式（全文→清单）: Qwen 给 9 条，4 条 left==right，无效。
  v3 逐组重写 batch=6: 模型重编号 → 内容错位（一组被换成别组答案）。
  v3 逐组重写 batch=1: 模型输出格式不稳，20/23 解析失败。

  共同根因：让 9B 模型做「长文本 → 结构化输出」的链路，不可靠。
  正确架构 = 规则做确定性清理，模型只处理规则解决不了的疑难句：
    阶段1 规则层：分句级删/剥高置信度心理副词与比喻 —— 零风险、可审计
    阶段2 模型层：只把规则没吃掉的「疑难段」逐条送模型，一次一条
    阶段3 校验层：台词与因果四句逐字比对 + 禁词复检

用法:
    python hybrid_cleaner.py <输入稿> <输出稿> [--model gemma] [--no-model]
"""
import argparse
import json
import os
import re
import subprocess
import time

LMS = os.path.join(os.environ.get("USERPROFILE", ""), ".lmstudio", "bin", "lms.exe")
MODEL_KEYS = {
    "qwen": "qwen3.5-9b-uncensored-hauhaucs-aggressive",
    "gemma": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
}
CTX = "8192"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

PAREN_RE = re.compile(r"（([^（）]*)）")
QUOTE_RE = re.compile(r"(?:“[^”]*”|‘[^’]*’|\"[^\"]*\")")
CAUSAL_LINE_RE = re.compile(r"^[ \t]*(因为|所以|但是|于是)\s*[:：]")
CAUSAL_WORDS = ("因为", "所以", "但是", "于是")

# ---------------------------------------------------------------- 阶段1：规则
# STRIP_RULES: 只删匹配片段，保留主干
STRIP_RULES = [
    # 比喻
    ("比喻-仿佛", r"，?仿佛[^，]*"),
    ("比喻-像是", r"，?像是[^，]*"),
    ("比喻-像是", r"，?像是[^，]*"),
    ("比喻-似是", r"，?似是[^，]*"),
    ("比喻-犹如", r"，?犹如[^，]*"),
    ("比喻-宛如", r"，?宛如[^，]*"),
    ("比喻-好像", r"，?好像[^，]*"),
    ("比喻-般", r"，?[^，]{0,6}般(?=[，。]|$)"),
    # 心理推断
    ("推断-试图", r"，?试图[^，]*"),
    ("推断-似应", r"，?似乎应当[^，]*"),
    ("推断-像是", r"，?像是[^，]*"),
    ("推断-仿佛在", r"，?仿佛在[^，]*"),
    # 替观众下结论
    ("模式切换", r"，?从[^，]*切换到[^，]*模式"),
    ("定格在", r"，?最终定格在[^，]*"),
    ("交汇的区域", r"，?[^，]*交汇的区域"),
    ("目光锁定", r"，?目光锁定在[^，]*区域"),
    ("眼神闪过", r"，?眼[神里]*闪过[^，]*"),
    # 心理副词短语
    ("带着一种", r"，?带着一种[^，]*"),
    ("带着一丝", r"，?带着一丝[^，]*"),
    ("带着不容置疑", r"，?带着不容置疑[^，]*"),
    ("带着疲惫", r"，?带着[^，]*疲惫[^，]*"),
    ("语气带着", r"，?语气[中]?带着[^，]*"),
    ("声音带着", r"，?声音带着[^，]*"),
    ("说话带着", r"，?说话带着[^，]*"),
    ("眼神带着", r"，?眼神带着[^，]*"),
    ("一种不可", r"，?一种[^，]*不可[^，]*"),
    ("一种无不可", r"，?一种[^，]*无[^，]*"),
    ("一种气氛", r"，?一种气氛[^，]*"),
    ("一种感觉", r"，?一种感觉[^，]*"),
    ("一个高科技", r"，?一个[^，]*高科技[^，]*"),
    ("意味深长", r"，?意味深长地?"),
    ("不易察觉", r"不易察觉的"),
    ("不易察觉", r"不易察觉地?"),
    ("不可察觉", r"不可察觉的"),
    ("明显变浅", r"，?明显变浅[^，]*"),
    ("几乎要触碰", r"，?几乎要触碰[^，]*"),
    # 副词（可拍但冗余）
    ("副词-微微", r"微微"),
    ("副词-缓缓", r"缓缓"),
    ("副词-轻轻", r"轻轻"),
    ("副词-极慢", r"极慢"),
    ("副词-略微", r"略微"),
    ("副词-轻微", r"轻微"),
    ("副词-慵懒地", r"慵懒地"),
    ("副词-放松地", r"放松地"),
    ("副词-随意地", r"随意地"),
    ("副词-缓慢地", r"缓慢地"),
    ("副词-直勾勾地", r"直勾勾地"),
    ("副词-随着动作", r"随着动作"),
    ("副词-微微飘", r"微微飘"),
    ("副词-眯起", r"微微眯起"),
    ("副词-挺直", r"挺直"),
    # 声音/神态类副词（可拍但冗余）
    ("副词-声音低沉", r"，?声音低沉"),
    ("副词-声音平稳", r"，?声音平稳"),
    ("副词-语速均匀", r"，?语速均匀"),
    ("副词-眼神凌厉", r"，?眼神[上]?凌厉"),
    # 散文词：「一丝」「一抹」「那抹」「那点」这类不可量化的修饰
    ("散文词-一丝", r"，?眼底闪过一丝[^，]*"),
    ("散文词-一丝2", r"一丝[^，、]{0,4}(?:的)?光芒"),
    ("散文词-一抹", r"一抹"),
    ("散文词-那抹", r"那抹"),
    ("散文词-那点", r"那点"),
    ("散文词-极浅的弧度", r"，?嘴角向上牵起一个极浅的弧度"),
    ("散文词-微小的晃动", r"，?靛蓝发夹随着头部微小的晃动而闪烁"),
    ("散文词-微小的", r"微小的"),
    ("散文词-缓缓合拢", r"缓缓"),
    ("散文词-极慢", r"极慢"),
    ("散文词-悬停", r"手指悬停(在)?(快门键上方)?"),
    ("散文词-眼角余光", r"眼角余光"),
    ("散文词-眸光", r"眸光"),
    ("散文词-淡淡", r"淡淡"),
    ("散文词-幽幽", r"幽幽"),
    ("散文词-悄然", r"悄然"),
    ("散文词-无声地", r"无声地"),
    ("散文词-默默地", r"默默地"),
    ("副词-念念有词", r"，?嘴里念念有词"),
    ("副词-念念有词2", r"，?念念有词"),
    ("副词-审慎", r"，?动作比白天更慢、更审慎"),
    ("副词-审慎2", r"，?更审慎"),
    ("副词-僵硬", r"，?身体僵硬了一下"),
    ("副词-泛白", r"，?指节泛白"),
    ("副词-瞬间", r"瞬间"),
    ("副词-猛地", r"猛地"),
    ("副词-本能地", r"本能地"),
    ("副词-极慢地", r"极慢地"),
    ("副词-小心翼翼", r"小心翼翼"),
    ("副词-小心翼翼地", r"小心翼翼地"),
    ("语气中残留", r"，\s*语气[中]?\s*$"),
]

# 规则跑完后需要补回 / 修正的细节
POST_FIXUPS = [
    ("嘴角缓慢而微扬", "嘴角微扬"),
    ("然后、地", "然后"),
    ("，地", ""),
]

# DROP_RULES: 整段删除（整段本身就是在替观众解释或纯心理）
DROP_RULES = [
    ("指尖颤抖", r"，?指尖[^，]*颤抖"),
    ("动作精准到位", r"，?动作精准到位"),
    ("动作X而Y", r"，?动作[^，]*而[^，]*"),
    ("呼吸变浅", r"，?他的呼吸[^，]*"),
    ("目光慵懒", r"，?目光慵懒[^，]*"),
    ("轻松地倚靠", r"，?身体放松地倚靠[^，]*"),
    ("动作放松", r"，?动作[^，]*放松"),
    ("语气强调", r"，?语气[^，]*强调"),
    ("语气得意", r"，?语气[^，]*得意"),
    ("语气调侃", r"，?语气[^，]*调侃"),
    ("动作刻意", r"，?动作[^，]*刻意"),
    ("动作熟练", r"，?动作[^，]*熟练"),
    ("动作犹豫", r"，?动作[^，]*犹豫"),
    ("眼神柔和", r"，?眼神[^，]*柔和"),
    ("眼神锐利", r"，?眼神[^，]*锐利"),
    ("目光停驻", r"，?目光[^，]*停驻[^，]*"),
    ("注视很久", r"，?注视[^，]*很久"),
]

# 规则层吃完后仍残留的特征 → 属于「疑难段」，交给模型。
# 注意：这里判的是"规则处理后仍带可疑质感"的组，不是"是否还有禁词"。
# 人工终审的做法不只是删词，还包括：合并相邻动作、把抽象描述换成具体动作、
# 把"解释性"整段换成"可拍"的替代动作（如"呼吸变浅+模式切换" → "俯身凑近"）。
# 这些只有语义模型能做，所以残留判定要覆盖"仍带叙事腔/解释腔"的组。
RESIDUAL_RE = re.compile(
    r"意味深长|不易察觉|仿佛|似是|犹如|宛如|好像|似乎|试图|"
    r"带着一种|带着一丝|带着不容|语气[中]?带着|眼神中闪过|"
    r"定格在|切换到|交汇的区域|一种不可|一种气氛|一种感觉|"
    r"慵懒|洒脱|仪式感|从容|克制|优雅|沉静|拉开|复杂|"
    r"沉重|笃定|玩味|戏谑|微妙的|难以言喻|"
    r"高深莫测|意味不明|不容置疑|理所当然|显而易见|"
    r"微微|缓缓|轻轻|极慢|略微|轻微|严格|精准|放松|随意|"
    r"仪式|与生俱来|浑然天成|"
    # 解释腔 / 叙事腔（人工终审重点替换的正是这些）
    r"没有看|而是将|投向了|重新聚焦|投来|扫过|来回切换|模式|"
    r"僵硬|泛白|明显|本能地|瞬间|猛地|审慎|念念有词|嘀咕|喃喃|"
    r"胸腔起伏|指尖悬停|悬停在|碰了碰纸角|指节|隐约|"
    r"紧绷|绷着|迟疑|犹豫不决|欲言又止|"
    r"低语|轻声|柔声|冷冷地|淡淡地"
)

# 因果四句的词级修正（只换词，不动语义骨架）
CAUSAL_FIXUPS = [
    ("试图构建", "要搭"),
    ("试图用", "用"),
    ("仿佛启动了某种高科技雷达", ""),
    ("彻底打乱逻辑闭环", "彻底打乱逻辑"),
    ("字迹工整却无人署名", "字迹工整，没署名"),
]

# 正文模式专用：只删「词」，绝不删整个分句（避免破坏句子结构 / 吞掉台词前的引导语）
BODY_SAFE_RULES = [
    ("微小的", r"微小的"),
    ("极浅的", r"极浅的"),
    ("稳稳地", r"稳稳地"),
    ("缓缓", r"缓缓"),
    ("轻微", r"轻微"),
    ("精准", r"精准"),
    ("刻意", r"刻意"),
    ("审慎", r"审慎"),
    ("极慢", r"极慢"),
    ("小心翼翼", r"小心翼翼"),
    ("一丝", r"一丝"),
    ("一抹", r"一抹"),
    ("那抹", r"那抹"),
    ("淡淡的", r"淡淡的"),
    ("幽幽的", r"幽幽的"),
    ("凝滞", r"凝滞"),
    ("笃定", r"笃定"),
    ("意味深长", r"意味深长"),
    ("不易察觉", r"不易察觉"),
    ("慵懒", r"慵懒"),
    ("洒脱", r"洒脱"),
    ("仪式感", r"仪式感"),
    ("从容", r"从容"),
    ("优雅", r"优雅"),
    ("沉静", r"沉静"),
    ("玩味", r"玩味"),
    ("戏谑", r"戏谑"),
    ("沉重", r"沉重"),
    ("犹豫", r"犹豫"),
    ("迟疑", r"迟疑"),
    ("欲言又止", r"欲言又止"),
    ("念念有词", r"念念有词"),
    ("喃喃", r"喃喃"),
    ("嘀咕", r"嘀咕"),
    ("本能地", r"本能地"),
    ("猛地", r"猛地"),
    ("瞬间", r"瞬间"),
    ("明显", r"明显"),
    ("异常", r"异常"),
    ("缓缓地", r"缓缓地"),
    ("静静地", r"静静地"),
    ("默默地看着", r"默默地看着"),
    ("眼底闪过", r"眼底闪过[^，]*光芒"),
    ("眼底闪过2", r"眼底闪过"),
    ("指尖悬", r"指尖悬停[^，]{0,6}"),
    ("悬停", r"悬停(?=快门键)"),
    ("微微", r"微微"),
]

# 收尾：删剩下的悬空碎片。注意：不能吃掉正常分隔逗号。
TAIL_CLEANUPS = [
    (r"，\s*(?:声音|动作|眼神|嘴角|目光|表情|语气|姿态|神态|气质)\s*$", ""),
    (r"，\s*(?:中|的)?\s*$", ""),
    (r"(?<=[\u4e00-\u9fff])地(?=[，。]|$)", ""),
    (r"(?<=[\u4e00-\u9fff])地(?=、)", ""),
    (r"地、", "、"),
    (r"，\s*地(?=[，。]|$)", ""),
]

# 括号组专用收尾：只修「主语后紧跟逗号」这一种悬挂
# 形如「（他，目光紧盯着…」→「（他目光紧盯着…」
# 只在括号模式用 —— 正文里 "他，扶住桌沿" 这种是正常停顿，删了就毁句。
PAREN_TAIL_CLEANUPS = [
    (r"^([\u4e00-\u9fff]{1,3})，", r"\1"),
]


def apply_rules(inner):
    """对一段括号内容应用规则，返回 (新内容, 命中记录[])"""
    hits = []
    out = inner
    for name, pat in STRIP_RULES:
        new = re.sub(pat, "", out)
        if new != out:
            hits.append({"rule": name, "action": "strip", "before": out, "after": new})
            out = new
    for name, pat in DROP_RULES:
        new = re.sub(pat, "", out)
        if new != out:
            hits.append({"rule": name, "action": "drop", "before": out, "after": new})
            out = new
    for pat, rep in TAIL_CLEANUPS:
        new = re.sub(pat, rep, out)
        if new != out:
            hits.append({"rule": "收尾", "action": "tail", "before": out, "after": new})
            out = new
    for pat, rep in PAREN_TAIL_CLEANUPS:
        new = re.sub(pat, rep, out)
        if new != out:
            hits.append({"rule": "括号收尾", "action": "tail", "before": out, "after": new})
            out = new
    for old, new in POST_FIXUPS:
        if old in out:
            hits.append({"rule": "修整", "action": "fix", "before": out, "after": out.replace(old, new)})
            out = out.replace(old, new)
    out = re.sub(r"，{2,}", "，", out)
    out = re.sub(r"^，|，$", "", out)
    out = re.sub(r"，\s*$", "", out)
    out = re.sub(r"、\s*$", "", out)
    return out.strip(), hits


def _removed_crosses_comma(before, after):
    """判断这次删除是否吃掉了引号（引号永远不能碰）。"""
    if len(before) == len(after):
        return False
    i = 0
    while i < min(len(before), len(after)) and before[i] == after[i]:
        i += 1
    j = 0
    while j < min(len(before) - i, len(after) - i) and before[len(before) - 1 - j] == after[len(after) - 1 - j]:
        j += 1
    removed = before[i:len(before) - j]
    return any(c in removed for c in "“”\"'‘’")


def _removed_has_comma(before, after):
    """被删片段里含逗号 → 说明规则在删「整个分句」，正文中不安全，拒绝。"""
    if len(before) == len(after):
        return False
    i = 0
    while i < min(len(before), len(after)) and before[i] == after[i]:
        i += 1
    j = 0
    while j < min(len(before) - i, len(after) - i) and before[len(before) - 1 - j] == after[len(after) - 1 - j]:
        j += 1
    removed = before[i:len(before) - j]
    return any(c in removed for c in "，,;；、")


def apply_rules_soft(inner):
    """正文模式（无括号）：只做 strip，不做 drop。

    正文的 drop 风险太大——「，目光扫过冰箱内部」删掉整段会毁掉动作。
    只删修饰词这类确定性安全的操作。

    ⚠️ 关键安全约束：引号内的台词**一个字都不能碰**。
    所以所有规则只在「引号外的片段」上执行，规则本身的正则不允许跨引号。
    """
    hits = []
    # 切出引号保护区
    spans = [(m.start(), m.end()) for m in QUOTE_RE.finditer(inner)]
    segs = []
    pos = 0
    for a, b in spans:
        if a > pos:
            segs.append((pos, a))
        pos = b
    if pos < len(inner):
        segs.append((pos, len(inner)))

    out_parts = []
    for a, b in segs:
        seg = inner[a:b]
        s = seg
        for name, pat in BODY_SAFE_RULES:
            t = re.sub(pat, "", s)
            if t != s:
                # 台词保护：引号数量必须不变
                if t.count("“") != s.count("“") or t.count("”") != s.count("”"):
                    continue
                if t.count('"') != s.count('"'):
                    continue
                # 引号前不能是汉字（那说明正文被并进了台词）
                def qp(x):
                    o = []
                    for mm in re.finditer(r'[“""]', x):
                        p = x[:mm.start()].rstrip()
                        o.append(p[-1] if p else "")
                    return o
                if any(re.match(r"[一-鿿]", c or "") for c in qp(t)):
                    continue
                hits.append({"rule": name, "action": "strip", "before": s, "after": t})
                s = t
        out_parts.append(s)
    out = ""
    prev_end = 0
    for (a, b), part in zip(segs, out_parts):
        out += inner[prev_end:a] + part
        prev_end = b
    out += inner[prev_end:]
    out = re.sub(r"，{2,}", "，", out)
    out = re.sub(r"，\s*。", "。", out)
    out = re.sub(r"。\s*。", "。", out)
    return out.strip(), hits


# ---------------------------------------------------------------- 段落切分
def split_paragraphs(text):
    """把正文切成「段落单元」：一行一段。
    **因果四句整行不参与**（它们是绝对保护区，见 is_protected_line）。
    返回 [(start, end, content)]，content 含首尾标点。
    """
    out = []
    offset = 0
    for line in text.split("\n"):
        if line.strip() and not CAUSAL_LINE_RE.match(line.strip()):
            out.append((offset, offset + len(line), line))
        offset += len(line) + 1
    return out


def has_residual(s):
    return bool(RESIDUAL_RE.search(s))


# ---------------------------------------------------------------- 阶段2：模型
PROMPT = """你是剧本表演提示的改写员。把下面这个括号片段重写成**纯动作**。

【片段】（{INNER}）

【要做的事】
1. 删掉修饰情绪的词（意味深长、不易察觉的得意、带着一丝疲惫的坚持、微微前倾、端详、仪式感、洒脱、慵懒、从容、优雅、沉静、笃定、玩味、戏谑、沉重、复杂、放松、随意、精准、慢慢、轻轻、缓缓、略微、轻微、瞬间、猛地、审慎、念念有词 等）
2. 删掉比喻（仿佛…、像是…、犹如…、宛如…、好像…、般）
3. 删掉心理推断（试图…、似乎应当…、仿佛在权衡…、像是被…）
4. 删掉替观众下结论的说明（把心理、意图、氛围、关系写出来的那句话）
5. 把抽象描述换成**具体可拍的动作**。例如：
   - 「他的呼吸明显变浅了一点，眼神从"调查"模式切换到"困惑"模式」→ 「他俯身，鼻尖凑近冰箱缝隙」
   - 「他的目光在"便签"和"半空酸奶"之间来回切换」→ 「他伸手，指腹在便签边沿压了一下，抽回手」
   - 「她没有看阿哲，而是将视线投向了远处的墙角」→ 「她侧身，目光重新落回酸奶」
6. 长句子裁掉冗余实词，只留动作

【不要做的事】
- 不要新增原文没有的动作，也不要改变动作的走向
- 不要改动动作主体
- 不要写台词、心理标签、镜头参数
- 不要写括号、冒号、换行符
- 如果原文已经没有需要改的地方，就**原样输出**。不要为了改而改。

【输出格式】
只输出重写后的内容，一行，不要括号、不要编号、不要解释：

重写后的内容

【示例】
片段：（他低声自语，声音像是从喉咙深处挤出来的，带着一丝疲惫的坚持）
输出：他低头对着手机

片段：（他伸出右手，指尖悬停在纸张上方，仿佛在衡量是否该触碰它，然后轻轻地、极慢地碰了碰纸角，动作带着一种仪式感）
输出：他伸出右手，指尖停在纸角上方，没有碰下去

片段：（他抬头看向窗外，语气中带着一丝疲惫的坚持）
输出：他抬头看向窗外
"""


def _lms_env():
    env = os.environ.copy()
    if "LMSTUDIO_API_KEY" not in env:
        keyfile = os.path.join(
            os.environ.get("USERPROFILE", ""), ".lmstudio", ".internal", "lms-key-2"
        )
        if os.path.exists(keyfile):
            with open(keyfile, encoding="utf-8") as f:
                env["LMSTUDIO_API_KEY"] = f.read().strip()
    return env


def lms(*args, timeout=900):
    try:
        r = subprocess.run([LMS, *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           env=_lms_env(), timeout=timeout)
        return ANSI.sub("", r.stdout or "")
    except FileNotFoundError:
        raise SystemExit(f"找不到 lms.exe: {LMS}")
    except subprocess.TimeoutExpired:
        return ""


def load_model(model):
    for key in MODEL_KEYS.values():
        lms("unload", key)
    time.sleep(2)
    lms("load", model, "--gpu", "max", "--context-length", CTX, "-y")
    ident = model.split("/")[-1]
    for _ in range(40):
        if ident in lms("ps"):
            return True
        time.sleep(2)
    raise RuntimeError(f"模型加载超时: {model}")


def strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", s).replace("\r\n", "\n")


def strip_outer_parens(s):
    s = s.strip()
    for _ in range(2):
        if len(s) >= 2 and s[0] in "(（[【" and s[-1] in ")）]】":
            s = s[1:-1].strip()
    return s


def model_rewrite(inner, model):
    prompt = PROMPT.replace("{INNER}", inner)
    raw = strip_ansi(lms("chat", model, "-p", prompt, "-y", "--reasoning", "off"))
    for l in (x.strip() for x in raw.split("\n")):
        if not l or l.startswith("```"):
            continue
        if re.match(r"^\d+\s*[|｜]", l):
            l = re.split(r"[|｜]", l, 1)[1].strip()
        l = strip_outer_parens(l)
        if not l or l in ("无需修改", "N/A", "无", "不需要修改"):
            continue
        return l
    return None


PARA_PROMPT = """你是短剧剧本的改写员。下面是一段短剧正文（含动作描写与台词）。

【段落】
{PARA}

【要做的事】
1. 删掉修饰情绪的词（意味深长、不易察觉的得意、带着一丝疲惫的坚持、微微、缓缓、轻轻、
   略微、轻微、极慢、缓缓地、慵懒、洒脱、仪式感、从容、优雅、沉静、笃定、玩味、戏谑、
   沉重、复杂、放松、随意、精准、审慎、明显、瞬间、猛地、本能地、念念有词、小心翼翼、
   刻意、用力、缓缓地 等）
2. 删掉比喻（仿佛…、像是…、犹如…、宛如…、好像…、般）
3. 删掉心理推断（试图…、似乎…、仿佛在权衡…）
4. 删掉替观众下结论的说明（把心理、意图、氛围写出来的那句话）
5. 把抽象描述换成**具体可拍的动作**

【绝对不能动的】
- **引号里的台词，一个字都不能改**（包括标点）
- 场景头、人物行、「因为/所以/但是/于是」四句，不要碰

【输出格式】
只输出改写后的这一段，一行，不要编号、不要解释、不要换行：

改写后的段落
"""


def model_rewrite_paragraph(para, model):
    prompt = PARA_PROMPT.replace("{PARA}", para)
    raw = strip_ansi(lms("chat", model, "-p", prompt, "-y", "--reasoning", "off"))
    for l in (x.strip() for x in raw.split("\n")):
        if not l or l.startswith("```"):
            continue
        if re.match(r"^\d+\s*[|｜]", l):
            l = re.split(r"[|｜]", l, 1)[1].strip()
        if l:
            return l
    return None


def validate_paragraph(new, old):
    """正文段落校验：台词必须逐字保留"""
    if not new:
        return False, "空输出"
    if len(new) > len(old) + 40:
        return False, "太长"
    old_q = QUOTE_RE.findall(old)
    new_q = QUOTE_RE.findall(new)
    if old_q != new_q:
        return False, "台词被改动"
    # 引号总数必须一致（配对不能被打乱）
    if sum(old.count(c) for c in "“”‘’\"") != sum(new.count(c) for c in "“”‘’\""):
        return False, "引号数量变化"
    # 引号前不能是汉字（正文被并进台词）
    for m in QUOTE_RE.finditer(new):
        p = new[:m.start()].rstrip()
        if p and re.match(r"[一-鿿]", p[-1]):
            return False, "引号前是汉字（台词被吞）"
    if CAUSAL_LINE_RE.match(new.strip()):
        return False, "改动的是因果四句"
    if any(c in new for c in "（）[]【】"):
        return False, "含括号"
    # 防造词：只拦关键动词/形容词的凭空出现（3 字块连续匹配对正常改写太严）
    NEW_WORD_RE = re.compile(r"缩回|推开|攥紧|抚过|摩挲|撩起|挑眉|耸肩|侧首|垂眸|抬眸")
    for m in NEW_WORD_RE.finditer(new):
        if m.group(0) not in old:
            return False, "疑似造词: %s" % m.group(0)
    return True, ""


def validate(new, old):
    if not new:
        return False, "空输出"
    if len(new) > len(old) + 12:
        return False, "太长"
    if new.startswith(CAUSAL_WORDS):
        return False, "因果四句"
    if any(c in new for c in "()（）[]【】"):
        return False, "含括号"
    # 防造词：模型输出里的连续 3 字块，若原文完全没有出现过则可疑
    # （只看 3 字块，避免"念念有词"这类正常改写被误杀）
    for i in range(len(new) - 2):
        if new[i:i + 3] not in old:
            return False, "疑似造词: %s" % new[i:i + 3]
    return True, ""


# ---------------------------------------------------------------- 校验层
def signature(text):
    paren_spans = [(m.start(), m.end()) for m in PAREN_RE.finditer(text)]
    quotes = [m.group(0) for m in QUOTE_RE.finditer(text)
              if not any(a <= m.start() < b for a, b in paren_spans)]
    causal = [l.strip() for l in text.split("\n") if CAUSAL_LINE_RE.match(l.strip())]
    return quotes, causal


def quote_contexts(text):
    """每个**台词引号**（不含括号内的表演提示引号）前面紧邻的非空白字符序列。

    口径必须与 signature() 一致：括号内的引号不算台词引号，
    否则两处计数不同会误判。
    """
    paren_spans = [(m.start(), m.end()) for m in PAREN_RE.finditer(text)]
    ctx = []
    for m in re.finditer(r"[“”‘’\"]", text):
        if any(a <= m.start() < b for a, b in paren_spans):
            continue
        p = text[:m.start()].rstrip()
        ctx.append(p[-1] if p else "")
    return ctx


def _ctx_preserved(src_ctx, out_ctx):
    """引号前结构是否仍然合法：
    ① 每个**开引号**前紧邻的不是汉字（否则正文被并进了台词）
    ② 开引号/闭引号的数量与配对关系不变
    """
    if len(src_ctx) != len(out_ctx):
        return False
    han = re.compile(r"[一-鿿]")
    for a, b in zip(src_ctx, out_ctx):
        # 只有开引号（“ ‘ " 里的第一个）才需要检查前字
        if a in ("“", "‘") and han.match(b or ""):
            return False
    return True


def clean(text, model="gemma", do_model=True, verbose=True):
    """核心清理逻辑，返回 (清理后正文, 报告字典)。可直接被流水线 import 复用。"""
    src_q, src_c = signature(text)
    groups = [(m.start(), m.end(), m.group(1)) for m in PAREN_RE.finditer(text)]
    if verbose:
        print("括号表演提示组: %d" % len(groups))

    # ---- 阶段1：规则 ----
    rule_out, rule_hits = {}, []
    for i, (s, e, inner) in enumerate(groups, 1):
        new, hits = apply_rules(inner)
        if hits:
            rule_out[i] = new
            rule_hits.append({"idx": i, "old": inner, "new": new, "rules": hits})
    if verbose:
        print("阶段1 规则干预: 命中 %d 组" % len(rule_hits))

    # 阶段2 路由：看规则处理**之后**的残留，而不是原文。
    # 原文含残留但规则已吃干净的 → 不送模型（模型只会把已经干净的地方改坏）。
    # 规则把整段清空的 → 必须送模型，否则等于无声删内容。
    residual = []
    for i, (s, e, inner) in enumerate(groups, 1):
        cur = rule_out.get(i, inner)
        if not cur.strip() or has_residual(cur):
            residual.append(i)
    if verbose:
        print("阶段2 模型干预: 规则后仍残留 %d 组" % len(residual))

    model_out, dropped = {}, []
    if residual and do_model:
        mkey = MODEL_KEYS[model]
        load_model(mkey)
        for n, i in enumerate(residual, 1):
            # 规则把整段清空的组，必须把**原文**喂给模型（否则模型没东西可改）
            cur = rule_out.get(i) or groups[i - 1][2]
            new = model_rewrite(cur, mkey)
            if new is None:
                dropped.append({"idx": i, "old": cur, "reason": "无输出"})
                continue
            ok, why = validate(new, cur)
            if ok:
                model_out[i] = new
            else:
                dropped.append({"idx": i, "old": cur, "new": new, "reason": why})
                if verbose:
                    print("  ✗ 第%d组丢弃 [%s]: %s" % (i, why, new[:40]))
            if verbose:
                print("  阶段2 %d/%d" % (n, len(residual)), flush=True)

    # ---- 正文模式（无括号组）：逐段规则 strip + 模型重写 ----
    body_out, body_hits, body_residual = "", [], []
    if not groups:
        if verbose:
            print("未发现括号表演提示组 → 切换正文模式")
        paras = split_paragraphs(text)
        para_rule = {}
        for pi, (ps, pe, content) in enumerate(paras, 1):
            new, hits = apply_rules_soft(content)
            if hits:
                para_rule[pi] = new
                body_hits.append({"idx": pi, "old": content, "new": new})
        for pi, (ps, pe, content) in enumerate(paras, 1):
            cur = para_rule.get(pi, content)
            if has_residual(cur):
                body_residual.append(pi)
        if verbose:
            print("正文模式 规则干预: %d 段 | 待模型处理: %d 段"
                  % (len(body_hits), len(body_residual)))
        para_model = {}
        if body_residual and do_model:
            mkey = MODEL_KEYS[model]
            if not residual:
                load_model(mkey)
            for n, pi in enumerate(body_residual, 1):
                cur = para_rule.get(pi, paras[pi - 1][2])
                new = model_rewrite_paragraph(cur, mkey)
                if new is None:
                    dropped.append({"idx": pi, "old": cur, "reason": "无输出"})
                    continue
                ok, why = validate_paragraph(new, cur)
                if ok:
                    para_model[pi] = new
                else:
                    dropped.append({"idx": pi, "old": cur, "new": new, "reason": why})
                    if verbose:
                        print("  ✗ 第%d段丢弃 [%s]" % (pi, why))
                        print("     OLD: %s" % cur[:90])
                        print("     NEW: %s" % new[:90])
                if verbose:
                    print("  正文 %d/%d" % (n, len(body_residual)), flush=True)
        # 回写正文段落（从后往前）
        body_out = text
        for pi in range(len(paras) - 1, -1, -1):
            ps, pe, content = paras[pi]
            new = para_model.get(pi + 1)
            if new is None:
                new = para_rule.get(pi + 1)
            if new is None:
                continue
            body_out = body_out[:ps] + new + body_out[pe:]
        out = body_out
        rule_hits = body_hits
        model_out = {k: v for k, v in para_model.items()}

    # ---- 回写（从后往前，避免偏移失效）----
    # 优先级：模型层 > 规则层。模型是在规则结果上改的，必须用模型结果。
    if groups:
        out = text
        for i in range(len(groups) - 1, -1, -1):
            gi = i + 1
            s, e, inner = groups[i]
            new = model_out.get(gi)
            if new is None:
                new = rule_out.get(gi)
            if new is None:
                continue
            if not new.strip():
                # 整段清空：把括号整体去掉，保留正文
                out = out[:s] + out[e:]
                continue
            out = out[:s] + "（" + new + "）" + out[e:]

    out_q, out_c = signature(out)
    ok_q, ok_c = out_q == src_q, out_c == src_c
    src_ctx = quote_contexts(text)
    out_ctx = quote_contexts(out)
    # 台词引号总数必须不变（配对不能被打乱）
    ok_marks = len(src_q) == len(out_q)
    ok_ctx = _ctx_preserved(src_ctx, out_ctx) and ok_marks
    if not (ok_q and ok_ctx):
        # 台词被改动或台词前的结构被破坏 —— 硬红线，整体回滚
        if verbose:
            print("⚠ 台词被改动或引号前结构被破坏，整体回滚")
            if not ok_q:
                print("   台词内容变化：")
                for x, y in zip(src_q, out_q):
                    if x != y:
                        print("     - %s" % x[:60])
                        print("     + %s" % y[:60])
            else:
                print("   引号前结构变化：")
                for i, (x, y) in enumerate(zip(src_ctx, out_ctx)):
                    if x != y:
                        print("     #%d  %r -> %r" % (i + 1, x, y))
                if len(src_ctx) != len(out_ctx):
                    print("   引号数量 %d -> %d" % (len(src_ctx), len(out_ctx)))
        out = text
        out_q, out_c = src_q, src_c
        ok_q, ok_c = True, True
        rule_hits, model_out = [], {}

    # ---- 阶段4：因果四句的比喻清理（词级，不动语义骨架）----
    # 人工终审稿把「试图构建」→「要搭」、「仿佛启动了某种高科技雷达」整句删掉。
    # 四句是受保护区，不能整句重写；但里面确实藏着比喻和心理推断词，
    # 所以只做**词级**的确定性别名替换。
    # ⚠ 仅在「括号模式」下生效：正文模式的四句是绝对保护区。
    causal_fixups = []
    if groups:
        for old, new in CAUSAL_FIXUPS:
            if old in out:
                n = out.count(old)
                out = out.replace(old, new)
                causal_fixups.append({"old": old, "new": new, "times": n})
    # 删词后可能留下悬空逗号
    out = re.sub(r"，\s*，", "，", out)
    out = re.sub(r"，(?=\s*$)", "", out, flags=re.M)
    out = re.sub(r"，\s*。", "。", out)
    out = re.sub(r"。\s*。", "。", out)
    if causal_fixups:
        out_q2, out_c2 = signature(out)
        # 四句变了是允许的（只改词），但台词一个字都不许动
        if out_q2 != src_q:
            out = text  # 回滚：台词被动过，绝不接受
            ok_q = True
        else:
            ok_c = out_c2 == src_c  # 四句有词级改动则如实标记

    report = {
        "applied": rule_hits,
        "model": model_out,
        "dropped": dropped,
        "causal_fixups": causal_fixups,
        "verify": {"dialogue_identical": ok_q, "causal_identical": ok_c,
                   "quote_context_intact": ok_ctx,
                   "dialogue_count": len(src_q), "dialogue_after": len(out_q),
                   "causal_count": len(src_c), "causal_after": len(out_c)},
    }
    return out, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("infile")
    ap.add_argument("outfile")
    ap.add_argument("--model", default="gemma", choices=list(MODEL_KEYS))
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    with open(args.infile, encoding="utf-8") as f:
        text = f.read()

    out, report = clean(text, model=args.model, do_model=not args.no_model)

    with open(args.outfile, "w", encoding="utf-8") as f:
        f.write(out)
    rp = args.report or (os.path.splitext(args.outfile)[0] + "_report.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    v = report["verify"]
    print("\n已写入: %s" % args.outfile)
    print("台词逐字一致: %s (%s->%s) | 因果四句一致: %s (%s->%s)"
          % (v["dialogue_identical"], v["dialogue_count"], v["dialogue_after"],
             v["causal_identical"], v["causal_count"], v["causal_after"]))
    if report["causal_fixups"]:
        print("因果四句词级修正: %s" % "; ".join(
            "%s→%s(x%d)" % (f["old"], f["new"], f["times"]) for f in report["causal_fixups"]))
    print("\n--- 阶段1 规则干预 ---")
    for h in report["applied"]:
        print("  ✓ [%d] %s\n      => %s" % (h["idx"], h["old"], h["new"]))
    if report["model"]:
        print("\n--- 阶段2 模型干预 ---")
        for i, new in sorted(report["model"].items()):
            print("  ✓ [%d] => %s" % (i, new))


if __name__ == "__main__":
    main()
