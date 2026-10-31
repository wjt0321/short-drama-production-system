#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语料质量闸 · 分镜提示词抽样 —— 分镜提示词是不是真能喂给出图模型。

**为什么需要**
流水线补了一批语料后，我抽查 5 个题材就说"效果明显"。
换成 12 题材 × 3 镜 = 36 镜后，干净率只有 **61%**，暴露出三类问题：
  ① 兜底把**景别说明文字**当成了动作（`人物在环境中，交代位置关系`）
  ② 逗号切分留下**半句碎片**（`。东方美学`、`带细腻。CCD`）
  ③ **媒介词**错进材质栏（`80年代国产剪纸动画`、`CCD颗粒噪点`）

修完 94%。但抽样脚本是一次性的——不固化就会复发。

**判定标准**（每一项都可能导致出图模型误解）
  · 内部说明泄漏：景别/构图说明文字不该出现在画面描述里
  · 半句碎片：句末标点、逗号并列残片
  · 画质/规格词：`高清` `8K` `壁纸` 出图时无用
  · 抽象表述：`似乎` `非常` `充满活力` 之类空话
  · 人物指代：`人物` `角色` 不该出现在九段画面描述里
  · 纯色词：单独一个颜色名不是有效描述

**用法**
    python tools/check_prompt_quality.py
    python tools/check_prompt_quality.py --json
"""
import argparse
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)
LIB = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库")
sys.path.insert(0, LIB)
try:
    import lib_locator  # noqa: E402
except ImportError:  # 外部参考库为可选组件，未随包提供
    lib_locator = None
PIPE = os.path.join(LIB, "shortfilm_pipeline.py")

# 12 个题材 × 3 镜 = 36 个镜头（覆盖热门与冷门）
TOPICS = ['江南书生夜雨', '深山道士 山鬼', '书生 进京赶考', '将军 沙场',
          '宫廷 夜宴', '剑客 复仇', '水墨 山水', '非遗 皮影',
          '花妖 缠绵', '狐仙 报恩', '神怪 志异', '国漫 少年']

# 判废规则：类别 → 正则
BAD = {
    # 景别/构图的说明文字，是给人看的，不是画面
    '内部说明': r"人物在环境中|交代位置关系|视线平齐|背景虚化|主体居中|"
                r"对白为主|情绪戏|动作戏|承担|交代场景|前景有遮挡物",
    # 逗号切分留下的半句。
    # 注意：`**，`并**列**的完整短语是合法的（"细腻线条，绢本设色"），
    # 只有「句末标点」或「以标点收尾」才是碎片。
    '半句碎片': r"[。．！？!?…～~]|[，,、；;：:][^\u4e00-\u9fff]*$",
    # 画质规格，出图无用
    '画质规格': r"高清|超清|分辨率|壁纸|\d+[kK]\b|质量",
    # 空话
    '抽象空话': r"似乎|非常|充满活力|和谐平衡|东方美学|质感。",
    # 人物指代
    '人物指代': r"^(人物|角色|主体|少女|男子|女子)$",
    # 纯色
    '纯色词': r"^(朱红|石青|石绿|藏蓝|墨黑|雪白|赤金|金色|银色)$",
}


# ---------------------------------------------------------------- 过滤器自检
# **为什么抽样不够**：抽样用固定的 12 题材 × 工笔 × 空灵。实测把情绪过滤和
# 人物名词表整个关掉，36 个镜头照样 100% 干净、退出码 0——那些规则在这个
# 抽样里**一次都没开火**。一条从不触发的规则等于没有规则。
# 所以补一组**已知坏词/已知好词**的对照：直接问过滤器本身，
# 不依赖语料里恰好出现什么词。
FILTER_PROBES = [
    # (说明, 判定函数, 该返回 True)
    ("画风冲突·现代网红标签", "conflict", "INS风"),
    ("画风冲突·摄影质感", "conflict", "胶片摄影"),
    ("画风冲突·美妆修图", "conflict", "真人皮肤质感细腻"),
    ("画风冲突·现代都市地标", "conflict", "上海中心大厦"),
    ("情绪冲突·肃杀片里有笑", "mood", "面带笑意"),
    ("情绪冲突·温情片里有厮杀", "mood", "厮杀"),
    ("主体错位·孩童顶替书生", "role", "孩童头戴草帽"),
    ("主体错位·艄公顶替书生", "role", "艄公戴斗笠持竹篙"),
    ("主体错位·旅人顶替道士", "role", "手持灯笼的古风旅人"),
    # 卡片级调性：素材库里混着现代网红/电商模特 LoRA，
    # 东方古典片选到就是参考锚点跑偏。
    ("选卡·调���不符的网红卡", "card", "F.1男神极致写实拍摄风格小红书生活男生男模"),
    ("选卡·电商模特卡", "card", "古风女模电商展示模特图"),
]
# 反向对照：这些是**该放行**的合法词。放错了就是过滤过头，
# 好词被拦 = 提示词越来越空洞，同样是缺陷。
FILTER_OK_PROBES = [
    ("放行·水墨质感", "conflict", "宣纸纹理，墨色浓淡干湿"),
    ("放行·古典地标", "conflict", "亭台楼阁"),
    ("放行·肃杀片里的冷峻神态", "mood", "垂眸冷视"),
    ("放行·温情片里的微笑", "mood", "浅笑"),
    ("放行·主体本人的身份", "role", "月白棉麻长衫"),
    ("放行·国风插画卡", "card", "国风插画-山川绘影"),
    ("放行·古风书生卡", "card", "FLUX.古风书生装扮"),
]


def probe_filters(sfp):
    """返回失败列表：空列表 = 过滤器行为正确。"""
    bad = []
    conflict = sfp._conflict_rx("工笔")
    shasha = re.compile(sfp.MOOD_CONFLICT["肃杀"])
    wenqing = re.compile(sfp.MOOD_CONFLICT["温情"])
    subj = "书生"
    card_rx = re.compile("|".join(sfp.CARD_CONFLICT))

    for desc, kind, word in FILTER_PROBES:
        if kind == "conflict":
            got = bool(conflict and conflict.search(word))
        elif kind == "mood":
            got = bool(shasha.search(word) or wenqing.search(word))
        elif kind == "card":
            got = bool(card_rx.search(word))
        else:
            got = any(ro in word for ro in sfp._OTHER_ROLE if ro not in subj)
        if not got:
            bad.append("{}：`{}` 没被拦下".format(desc, word))

    for desc, kind, word in FILTER_OK_PROBES:
        if kind == "conflict":
            blocked = bool(conflict and conflict.search(word))
        elif kind == "mood":
            blocked = bool(shasha.search(word) or wenqing.search(word))
        elif kind == "card":
            blocked = bool(card_rx.search(word))
        else:
            blocked = any(ro in word for ro in sfp._OTHER_ROLE if ro not in subj)
        if blocked:
            bad.append("{}：`{}` 被误拦".format(desc, word))
    return bad


def main():
    ap = argparse.ArgumentParser(description="语料质量抽样闸")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="打印每个镜头")
    args = ap.parse_args()

    if lib_locator is None or not os.path.exists(PIPE):
        print("外部参考库未随包提供，语料质量闸不适用（N/A）。")
        return 0

    spec = importlib.util.spec_from_file_location("sfp", PIPE)
    sfp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sfp)
    recs = sfp.load_records(lib_locator.prompts_path() or "")
    if not recs:
        print("✗ 提示词库为空，跳过", file=sys.stderr)
        return 0

    # 过滤器自检先跑：它不依赖语料，能保证「过滤器本身还活着」
    probe_bad = probe_filters(sfp)
    print("过滤器自检：{} 项应拦 + {} 项应放行 → {}".format(
        len(FILTER_PROBES), len(FILTER_OK_PROBES),
        "全部正确" if not probe_bad else "{} 项不对".format(len(probe_bad))))
    for b in probe_bad:
        print("  ✗ {}".format(b))

    from collections import Counter
    issues = Counter()
    total = 0
    samples = {}

    for t in TOPICS:
        r = sfp.run_pipeline(t, 45, "工笔", "空灵", "分镜", recs, "封面")
        toks = [x for x in re.split(r"[\s,，、/]+", t) if x]
        topic_roles = [x for x in toks
                       if any(r in x for r in sfp.ROLE_WORDS)]
        conflict_rx = re.compile("|".join(sfp.STYLE_CONFLICT["工笔"]))
        mood_rx = re.compile(sfp.MOOD_CONFLICT["空灵"])
        for b in (r.get("storyboard") or [])[:3]:
            total += 1
            p = b["nine_parts"]
            subj = (p.get("主体") or "").strip()
            vals = {
                "服饰": p.get("服饰细节", ""),
                "环境": p.get("环境背景", ""),
                "动作": p.get("动作/神态", ""),
                "光影": (p.get("光影氛围", "") or "").split("，")[0],
                "材质": p.get("材质肌理", ""),
            }
            flags = []
            for slot, v in vals.items():
                if not v:
                    continue
                for name, pat in BAD.items():
                    if re.search(pat, v):
                        flags.append("{}:{}".format(slot, name))
                        issues[name] += 1
                        samples.setdefault(name, []).append(
                            (t, slot, v))
                # ---- 画风冲突：语料挖到的是「高赞词」，不是「合拍风词」。
                # 工笔片里混进 INS风/纯欲风/上海中心大厦，两条画风信号打架，
                # 出图模型只能二选一，抽卡率直接起飞。
                if conflict_rx.search(v):
                    flags.append("{}:画风冲突".format(slot))
                    issues["画风冲突"] += 1
                    samples.setdefault("画风冲突", []).append((t, slot, v))
                # ---- 主体错位：词里冒出**别人**的身份。
                # 主体是书生、服饰却写「孩童头戴草帽」，出图会多画一个人。
                if any(ro in v for ro in sfp._OTHER_ROLE
                       if ro not in subj):
                    flags.append("{}:主体错位".format(slot))
                    issues["主体错位"] += 1
                    samples.setdefault("主体错位", []).append((t, slot, v))
                # ---- 情绪冲突：动作/神态与本片情绪相悖。
                # 「诡谲」恐怖片里出现「面带笑意」，观众当场出戏 → 必重抽。
                if slot == "动作" and mood_rx.search(v):
                    flags.append("动作:情绪冲突")
                    issues["情绪冲突"] += 1
                    samples.setdefault("情绪冲突", []).append((t, slot, v))
            # ---- 主体必须是「人」：题材里有人物身份词时必须取到它。
            # 回退成「取第一个词」会让「江南 书生 夜雨」的主体变成地名「江南」。
            if topic_roles and subj != topic_roles[0]:
                flags.append("主体:未取人物身份词")
                issues["主体取成地名"] += 1
                samples.setdefault("主体取成地名", []).append(
                    (t, "主体", subj))
            if args.verbose:
                print("  {:<12s} S{:02d} {:4s} {} | 服饰={} | 环境={} | 动作={}".format(
                    t, b["scene"], b["shot_size"],
                    ("⚠ " + ",".join(flags)) if flags else "",
                    vals["服饰"][:12], vals["环境"][:12], vals["动作"][:12]))

    # ---- 技法方案检查：逐镜都有、且氛围与情绪一致 ----
    # 实测：第 5 步原本只返回「正则 + 命中数」（检索索引，不是技法方案），
    # 且氛围列是库内前 N 个命中词——诡谲片里给出「史诗」「空灵」这种
    # 上一轮刚禁掉的词。技法必须**落到每一镜**才叫「写技巧」。
    tech_bad = []
    for topic, style, mood in (("深山道士 志怪", "水墨", "诡谲"),
                               ("江南 书生 夜雨", "水墨", "温情"),
                               ("江南书生夜雨", "工笔", "肃杀")):
        _r = sfp.run_pipeline(topic, 60, style, mood, "技巧", recs, "封面")
        _ps = (_r.get("techniques") or {}).get("per_shot") or []
        _shots = len(_r.get("storyboard") or [])
        if len(_ps) != _shots:
            tech_bad.append("{} {}/{}：逐镜技法 {} 条，镜头 {} 个".format(
                topic, mood, style, len(_ps), _shots))
        _allow = set(sfp.MOOD_ATMOSPHERE.get(mood) or [])
        for _t in _ps:
            for _k in ("光影", "构图", "调色", "氛围", "运镜"):
                if not (_t.get(_k) or "").strip():
                    tech_bad.append("{} S{}：{} 为空".format(
                        topic, _t.get("shot"), _k))
            if _allow and _t.get("氛围") not in _allow:
                tech_bad.append("{} S{}：氛围「{}」不属于 {} 的情绪词表".format(
                    topic, _t.get("shot"), _t.get("氛围"), mood))
    for x in tech_bad:
        print("  ✗ 技法方案：{}".format(x))
        issues["技法方案"] = issues.get("技法方案", 0) + 1

    clean = total - sum(issues.values())
    rate = clean * 100.0 / total if total else 0

    # ---- 选卡检查：东方古典片不该选到现代网红/电商模特类 LoRA，且不能重复 ----
    # 实测：水墨江南片选中过「F.1男神极致写实拍摄风格小红书生活男生男模」，
    # 而且同一张还连续占了两个名额（素材库有同名不同记录）。
    card_bad, card_dup, card_few = [], [], []
    card_rx = re.compile("|".join(sfp.CARD_CONFLICT))
    for topic, style in (("江南 书生 夜雨", "水墨"), ("江南书生夜雨", "工笔")):
        _r = sfp.run_pipeline(topic, 45, style, "空灵", "选卡", recs, "封面")
        _names = []
        for c in (_r.get("cards") or []):
            _names.append(c.get("name") or "")
            blob = "{} {} {}".format(c.get("name") or "",
                                     " ".join(c.get("tags") or []),
                                     c.get("prompt_sample") or "")
            if card_rx.search(blob):
                card_bad.append("{} → {}".format(topic, c.get("name")))
        if len(_names) != len(set(_names)):
            card_dup.append("{} → 有重复".format(topic))
        # **也要防「滤过头」**：过滤一旦坏成「全滤掉」，前两条检查都看不见
        # （0 张卡里当然没有调性不符的卡）。实测把 CARD_CONFLICT 置空，
        # `"|".join(())` 得空串 → 空正则匹配一切 → 所有卡被滤光 → 检查照过。
        # 所以必须同时要求**确实选出了足够多的卡**。
        if len(_names) < 3:
            card_few.append("{} → 只选出 {} 张（过滤过头？）".format(
                topic, len(_names)))
    for x in card_bad:
        print("  ✗ 选到调性不符的卡：{}".format(x))
        issues["选卡调性冲突"] = issues.get("选卡调性冲突", 0) + 1
    for x in card_dup:
        print("  ✗ 选卡重复：{}".format(x))
        issues["选卡重复"] = issues.get("选卡重复", 0) + 1
    for x in card_few:
        print("  ✗ {}".format(x))
        issues["选卡滤过头"] = issues.get("选卡滤过头", 0) + 1

    # 阈值：97%。
    # 实测：注入「内部说明泄漏」→ 94%，注入「半句碎片回来」→ 86%，
    # 85% 阈值两者都放过。过滤规则一旦被改弱，干净率是**断崖式**下跌的，
    # 所以阈值要贴着基线（100%）设，而不是取一个宽松的中间值。
    THRESHOLD = 97.0
    # 两个条件都要满足才算通过：抽样干净率达标 **且** 过滤器自检全对。
    # 只看干净率会漏掉「规则已失效但抽样恰好没触发」——实测过：
    # 把情绪过滤整个关掉，36 镜照样 100% 干净。
    ok = (rate >= THRESHOLD) and not probe_bad and not card_bad and not card_dup \
        and not card_few and not tech_bad

    if args.json:
        print(json.dumps({
            "ok": ok, "total_shots": total, "clean": clean,
            "clean_rate": round(rate, 1), "threshold": THRESHOLD,
            "issues": dict(issues),
            "samples": {k: v[:2] for k, v in samples.items()},
        }, ensure_ascii=False, indent=2))
    else:
        print("=" * 70)
        print("语料质量抽样：{} 题材 × 3 镜 = {} 个镜头".format(len(TOPICS), total))
        print("=" * 70)
        for name, c in issues.most_common():
            print("  {:8s} {:3d} 个".format(name, c))
            for t, slot, v in samples.get(name, [])[:2]:
                print("      e.g. {} {}/{} = {}".format(t, slot, name, v[:24]))
        print("-" * 70)
        print("干净镜头 {}/{} ({:.0f}%)　阈值 {:.0f}%".format(
            clean, total, rate, THRESHOLD))
        if probe_bad:
            print("\n✗ 过滤器自检不过——{} 项不符合预期。"
                  "过滤规则可能被改弱或改过头了。".format(len(probe_bad)))
        elif card_bad or card_dup or card_few or tech_bad:
            print("\n✗ 检查不过——选卡调性不符 {} 张、重复 {} 处、滤过头 {} 处、"
                  "技法方案问题 {} 处。"
                  .format(len(card_bad), len(card_dup), len(card_few),
                          len(tech_bad)))
        elif ok:
            print("✓ 语料质量达标")
        else:
            print("\n✗ 低于阈值——多半是 _clean_seg 的过滤规则被改弱了，或语料清洗退化了。")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
