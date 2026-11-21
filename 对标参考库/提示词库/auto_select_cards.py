#!/usr/bin/env python3
"""国风 AI 短片素材选卡器 — 通用版（不耦合到本地路径）。

**内部实现**：Agent 公开入口是 `python tools/select_reference.py prompt ...`
（本脚本不直接对外；路径经 lib_locator 定位到 seek库 真实数据）。

输入题材描述 → 在本地素材库里挑出最相关的 N 条提示词 + 封面图，
输出一张张"卡片"，可直接拿来改写。

**设计原则**：
  1. **零耦合**——不写死任何绝对路径，全部用 `os.path.dirname(__file__)` 推算；
     任何路径都可用 `--prompts` / `--covers` 参数覆盖
  2. **通用输入**——题材描述可以是关键词、一段话、内置题材名；
     不假设分词、不假设库大小、不假设题材表
  3. **多维筛选**——可按资源类型（LORA/图片模板/Checkpoint）、按题材维度
     （人物/场景/光影/镜头/调色）过滤
  4. **可重定位**——脚本放进任何目录都能跑（路径全相对）
  5. **技法可检索**——除了按题材选卡，还可按「短片制作技巧」选卡
     （镜头语言/光影/调色/构图/场景氛围/剪辑节奏），`--list-tech` 看覆盖量

**默认素材库布局**（与本脚本同目录）：
   ./prompts.jsonl        机读全量
   ./封面/<md5[:12]>.<ext>  封面图（按 URL md5 命名）

**用法**：
   # 单题材
   python auto_select_cards.py "敦煌飞天"
   # 多题材，一次输出多张表
   python auto_select_cards.py "国风女角色" "三视图" --top 5
   # 用内置题材名（不限文案）
   python auto_select_cards.py --topic "神话志怪" --top 10 --out cards.md
   # 批量查询（每行一条题材）
   python auto_select_cards.py --query-file query.txt
   # 限定资源类型与题材维度
   python auto_select_cards.py "逆光" --type 图片模板 --topic-type 光影
   # 只按短片制作技巧挑（不指定题材）
   python auto_select_cards.py "逆光剪影" --tech 光影 --top 10
   # 看库里各技法维度覆盖了多少（诊断）
   python auto_select_cards.py --list-tech
   # 完全自定义路径
   python auto_select_cards.py "敦煌" --prompts /some/path/p.jsonl --covers /tmp/covers

**JSON 输出**（给脚本消费）：
   python auto_select_cards.py "敦煌" --format json --top 5

**评分**：
  - 关键词命中权重：name×5 + tags×3 + prompt×1
  - 命中为 0 的记录直接淘汰（防止"高赞 ≠ 主题"刷掉相关性）
  - 质量加分：likeCount / 100
"""
import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter


# ---------- 默认定位：素材库（统一由 lib_locator 探测）----------
# 旧版这里曾是「库就在脚本旁边」；现在外部 seek 项目通过显式定位访问，
# 所以不再在多个文件里各写一份路径。
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
import lib_locator  # noqa: E402

SCRIPT_DIR = _SCRIPT_DIR
DEFAULT_PROMPTS = lib_locator.prompts_path() or os.path.join(
    SCRIPT_DIR, "prompts.jsonl")
DEFAULT_COVERS = lib_locator.covers_dir() or os.path.join(SCRIPT_DIR, "封面")
DEFAULT_QUERY = os.path.join(SCRIPT_DIR, "_query.txt")

# ---------- 题材维度（可被 --topic-type 限定） ----------
TOPIC_DIMENSIONS = {
    "人物": r"人物|角色|少女|女子|少年|肖像|立绘|三视图|表情|男主|女主",
    "场景": r"场景|建筑|宫殿|寺庙|园林|夜景|室内|城池|街道|荒野|楼阁|山谷",
    "光影": r"光影|逆光|侧光|体积光|丁达尔|光斑|阴影|烛光|剪影|月光|阳光",
    "镜头": r"广角|长焦|微距|鱼眼|航拍|dolly|推拉|zoom|景深|特写|一镜|手持|跟拍",
    "调色": r"青橙|莫兰迪|赛博|胶片|冷色|暖色|高级灰|LUT|低饱|复古",
    "氛围": r"神秘|安静|紧张|温馨|孤独|情绪|史诗|诡异|空灵|肃杀",
    "构图": r"构图|三分法|对称|框架|留白|引导线|中心|对角",
    "动作": r"奔跑|飞跃|舞剑|挥剑|弹琴|对弈|战斗|舞|转身|飞跃",
    "国风元素": r"敦煌|水墨|志怪|神话|非遗|仙侠|皮影|刺绣|汉服|古琴|茶道",
}

# ---------- 题材正向别名表（输入文本→展开关键词）----------
TOPIC_ALIASES = [
    ("敦煌飞天", r"敦煌|飞天|藻井|石窟|莫高|壁画|飞仙"),
    ("水墨国画", r"水墨|国画|写意|工笔|留白|宣纸|Sumi[e]?|Ink"),
    ("神话志怪", r"山海经|神话|志怪|仙侠|修仙|妖|鬼|狐|龙|传奇|异兽"),
    ("非遗民俗", r"非遗|皮影|剪纸|刺绣|苗绣|青花|陶瓷|傩|唐卡|扎染|蜡染"),
    ("国漫古风", r"国漫|古风|新国风|汉服|唐装|国风"),
    ("人物三视图", r"立绘|三视图|人物|角色|少女|男主|女主|肖像"),
    ("宫殿寺庙", r"宫殿|寺庙|园林|城池|古建"),
    ("场景夜景", r"夜景|夜空|霓虹|月色|星夜"),
    ("分镜故事板", r"分镜|故事板|分镜头|storyboard|shot.?list|九宫格"),
]

# ---------- 短片制作技巧表（可被 --tech 限定） ----------
# 六大类：镜头语言 / 光影 / 调色 / 构图 / 场景氛围 / 剪辑节奏。
# 用途：按「要什么镜头、什么光」直接选卡，而不只是按题材选卡。
TECHNIQUE_DIMENSIONS = {
    "镜头语言": r"广角|长焦|微距|鱼眼|航拍|俯瞰|鸟瞰|dolly|推拉|推镜|拉镜|zoom|"
                 r"景深|特写|近景|中景|全景|远景|一镜|手持|跟拍|摇镜|环绕|移轴|"
                 r"macro|aerial|drone|fisheye|tilt.?shift|close.?up|wide|low.?angle|"
                 r"俯拍|仰拍|荷兰角|过肩|主观视角|POV|运镜",
    "光影": r"光影|逆光|侧光|顺光|顶光|底光|体积光|丁达尔|耶稣光|光束|光柱|"
            r"光斑|散景|bokeh|阴影|剪影|silhouette|烛光|月光|阳光|霓虹|伦勃朗|"
            r"轮廓光|边缘光|环形光|高反差|明暗对比|低调|暗调|高调|亮调|柔光|漫射|"
            r"硬光|黄金时刻|金色时刻|蓝色时刻|暮色|god.?ray|volumetric|rim.?light|"
            r"backlight|moonlight|candle|neon|bloom|辉光|过曝|曝光",
    "调色": r"青橙|teal|莫兰迪|morandi|日系|和风|胶片|film|kodak|富士|复古|"
            r"赛博朋克|cyberpunk|暗黑|哥特|gothic|赛璐璐|cel.?shad|油画|oil|"
            r"水墨|ink|高级灰|低饱|低饱和|冷色|暖色|色调|配色|调色|LUT|"
            r"色彩|饱和|色温|白平衡|色调映射|colour|color|grading|palette",
    "构图": r"构图|三分法|rule.?of.?thirds|对称|symmetry|引导线|leading.?line|"
            r"框架构图|门框|中心构图|居中|留白|negative.?space|极简|极简主义|"
            r"前景虚化|虚化|景深|层次|前中后景|前景|中景|背景|俯拍构图|"
            r"网格|对角|斜线|框景|遮挡|负空间|composition|framing|depth",
    "场景氛围": r"夜景|夜|雨景|雨|雪景|雪|雾景|雾|霾|古战场|战场|废墟|断壁|"
               r"烟尘|烟雾|尘|烈焰|火焰|燃烧|雷电|闪电|雷暴|沙尘|雾凇|"
               r"结界|灵气|仙气|神秘|安静|紧张|温馨|孤独|情绪|史诗|诡异|空灵|"
               r"肃杀|压抑|宁静|热闹|荒凉|繁华|破败|"
               r"night|rain|snow|fog|mist|ruins|smoke|fire|flame|lightning|storm|"
               r"atmosphere|mood|ambience",
    "剪辑节奏": r"蒙太奇|montage|跳切|jump.?cut|平行剪辑|交叉剪辑|"
               r"升格|降格|慢动作|慢镜头|slow.?motion|"
               r"定格|关键帧|转场|长镜头|一镜到底",
}


def load_records(path):
    if not os.path.exists(path):
        sys.exit(f"找不到 {path}；可用 --prompts 指定，或确认 lib_locator 能定位到 seek库"
                 f"（Agent 公开入口：python tools/select_reference.py prompt ...）")
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    return out


def find_cover(cover_url, covers_dir):
    if not cover_url or not covers_dir or not os.path.isdir(covers_dir):
        return None
    h = hashlib.md5(cover_url.encode()).hexdigest()[:12]
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = os.path.join(covers_dir, h + ext)
        if os.path.exists(p):
            return p
    return None


def _bigrams(text):
    """把中文长词切成 2-gram：库内提示词很少写「航拍俯瞰」这种复合词，
    多数只写「航拍」或「俯瞰」。切 bigram 才能命中。"""
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", text)
    if len(cjk) < 3:
        return []
    return [cjk[i:i + 2] for i in range(len(cjk) - 1)]


def expand_query(q):
    """用户输入 → 关键词列表。

    顺序：内置别名表 → 逗号/空白分词 → 中文 2-gram 兜底。
    2-gram 是为了命中「航拍俯瞰」这类复合词（库内只写「航拍」或「俯瞰」）。
    """
    out = []
    for label, pat in TOPIC_ALIASES:
        if re.search(pat, q, re.I):
            out.extend(re.findall(pat, q, re.I))
    if not out:
        for t in re.split(r"[\s,，、;；/]+", q):
            t = t.strip()
            if 1 < len(t) <= 16:
                out.append(t)
    # 复合词补 bigram（不论走不走别名表，都补）
    extra = []
    for k in list(out):
        extra.extend(_bigrams(k))
    out.extend(extra)
    if not out:
        out = [q]
    seen, kws = set(), []
    for k in out:
        if k and k not in seen:
            seen.add(k)
            kws.append(k)
    return kws


def _item_hit_score(rec, item, kws):
    """单条 item 的可解释命中分；记录名/标签作为公共上下文。"""
    name = (rec.get("name") or "").lower()
    tags_l = " ".join((t or "").lower() for t in (rec.get("tags") or []))
    prompt_l = (item.get("prompt") or "").lower()
    hit = 0
    for k in kws:
        kl = k.lower()
        if kl in name:
            hit += 5
        elif kl in tags_l:
            hit += 3
        elif kl in prompt_l:
            hit += 1
    return hit


def best_item(rec, kws):
    """返回真正命中查询的 item，避免记录命中却固定输出第一条无关提示词。"""
    items = rec.get("items") or [{}]
    return max(items, key=lambda item: _item_hit_score(rec, item, kws))


def score_record(rec, kws):
    best = max((_item_hit_score(rec, it, kws)
                for it in (rec.get("items") or [{}])), default=0)
    if best == 0:
        return 0.0
    return best + (rec.get("likeCount") or 0) * 0.01


def passes_filters(rec, type_filter, topic_type, tech_filter=None):
    if type_filter:
        mtn = (rec.get("modelTypeName") or "").strip()
        if mtn != type_filter:
            return False
    if topic_type:
        pat = TOPIC_DIMENSIONS.get(topic_type)
        if not pat:
            return True
        text = " ".join([rec.get("name") or ""]
                       + list(rec.get("tags") or [])
                       + [it.get("prompt", "") for it in (rec.get("items") or [])])
        if not re.search(pat, text, re.I):
            return False
    if tech_filter:
        pat = TECHNIQUE_DIMENSIONS.get(tech_filter)
        if pat:
            text = " ".join([rec.get("name") or ""]
                           + list(rec.get("tags") or [])
                           + [it.get("prompt", "") for it in (rec.get("items") or [])])
            if not re.search(pat, text, re.I):
                return False
    return True


def format_md(queries, results, covers_dir):
    """results: [(query, kws, scored)]"""
    L = []
    for q, kws, picked in results:
        L.append(f"\n## 题材：「{q}」\n")
        L.append(f"关键词：{', '.join(kws)}　|　返回 {len(picked)} 条\n")
        if not picked:
            L.append("> （库里没有命中这条题材的素材，建议换个说法或扩量关键词）\n")
            continue
        L.append("| # | 类型 | 名字 | 标签 | 提示词（节选） | 封面 | 来源 |")
        L.append("|---|---|---|---|---|---|---|")
        for i, (sc, r) in enumerate(picked, 1):
            it = best_item(r, kws)
            cover = find_cover(it.get("cover"), covers_dir)
            cover_cell = (os.path.relpath(cover, lib_locator.PROJECT_ROOT)
                          if cover else "—")
            tags = "、".join((r.get("tags") or [])[:4]) or "—"
            p_short = re.sub(r"\s+", " ", (it.get("prompt") or "")[:120])
            if len(it.get("prompt") or "") > 120: p_short += "…"
            L.append(
                f"| {i} | {r.get('modelTypeName') or '—'} | {r.get('name') or '—'} "
                f"| {tags} | {p_short} | `{cover_cell}` | `liblib#{r.get('uuid')}` |"
            )
        L.append("")
        L.append("### 用法建议")
        L.append("")
        L.append("- **拆结构**：把提示词按「主体 + 时代 + 服饰 + 动作 + 环境 + 构图 + 光影 + 材质 + 风格 + 画质」九段拆")
        L.append("- **换内容**：保留结构骨架，把人物/服饰/场景换成你剧本里的设定")
        L.append("- **负向基线**：低分辨率, 模糊, 变形, 多余手指, 肢体错乱, 水印, 文字")
        L.append("- **多卡组合**：挑 3–5 张主题相同但视角/构图不同的卡片，对应一个镜头的不同尝试")
        L.append("")
    return "".join(L)


def format_json(queries, results, covers_dir):
    payload = []
    for q, kws, picked in results:
        cards = []
        for sc, r in picked:
            it = best_item(r, kws)
            cards.append({
                "score": round(sc, 3),
                "uuid": r.get("uuid"),
                "name": r.get("name"),
                "modelType": r.get("modelTypeName"),
                "tags": r.get("tags") or [],
                "prompt": it.get("prompt"),
                "negativePrompt": it.get("negativePrompt"),
                "samplingMethod": it.get("samplingMethod"),
                "samplingStep": it.get("samplingStep"),
                "cfgScale": it.get("cfgScale"),
                "seed": it.get("seed"),
                "source_url": r.get("url"),
                "source_note": "仅用于追溯，不等于已取得资源",
                "cover_path": find_cover(it.get("cover"), covers_dir),
            })
        payload.append({"query": q, "keywords": kws, "cards": cards})
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description="国风 AI 短片素材选卡（通用版）")
    ap.add_argument("queries", nargs="*", help="题材描述或关键词（可多个）")
    ap.add_argument("--topic", help="题材名（与内置题材表匹配）")
    ap.add_argument("--query-file", help="一行一个题材的查询文件")
    ap.add_argument("--top", type=int, default=8, help="返回多少张卡片")
    ap.add_argument("--type", choices=("LORA", "图片模板", "Checkpoint"),
                    help="限定资源类型")
    ap.add_argument("--topic-type", choices=sorted(TOPIC_DIMENSIONS.keys()),
                    help="按题材维度限定（人物/场景/光影/镜头/调色/氛围/构图/动作/国风元素）")
    ap.add_argument("--tech", choices=sorted(TECHNIQUE_DIMENSIONS.keys()),
                    help="按短片制作技巧限定（镜头语言/光影/调色/构图/场景氛围/剪辑节奏）")
    ap.add_argument("--list-tech", action="store_true",
                    help="列出库内各技巧维度的覆盖量（诊断用）")
    ap.add_argument("--prompts", help="自定义 prompts.jsonl 路径（默认与脚本同目录）")
    ap.add_argument("--covers", help="自定义封面目录路径（默认与脚本同目录/封面）")
    ap.add_argument("--out", help="输出文件路径（默认打印到 stdout）")
    ap.add_argument("--format", choices=("md", "json"), default="md",
                    help="输出格式：md（Markdown 表格）或 json（供脚本消费）")
    args = ap.parse_args()

    prompts_path = args.prompts or DEFAULT_PROMPTS
    covers_dir = args.covers or DEFAULT_COVERS

    records = load_records(prompts_path)

    if args.list_tech:
        rows = []
        for dim, pat in sorted(TECHNIQUE_DIMENSIONS.items()):
            n = 0
            p = re.compile(pat, re.I)
            for r in records:
                text = " ".join([r.get("name") or ""]
                               + list(r.get("tags") or [])
                               + [it.get("prompt", "") for it in (r.get("items") or [])])
                if p.search(text):
                    n += 1
            rows.append((dim, n))
        print(f"# 库内 {len(records)} 条记录 | 各技法维度覆盖量", file=sys.stderr)
        rows.sort(key=lambda x: -x[1])
        for dim, n in rows:
            bar = "█" * min(40, n * 40 // max(1, rows[0][1]))
            print(f"{dim:8s} {n:6d}  {bar}")
        return

    queries = list(args.queries)
    if args.topic: queries.append(args.topic)
    if args.query_file:
        for line in open(args.query_file, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                queries.append(line)
    if not queries:
        ap.error("请提供题材描述（位置参数 / --topic / --query-file / --list-tech）")

    print(f"# 库内 {len(records)} 条记录  |  来源 {prompts_path}", file=sys.stderr)

    results = []
    empty_queries = []
    for q in queries:
        kws = expand_query(q)
        pool = [r for r in records if passes_filters(r, args.type, args.topic_type, args.tech)]
        scored = [(score_record(r, kws), r) for r in pool]
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda x: -x[0])
        if not scored:
            empty_queries.append(q)
        results.append((q, kws, scored[: args.top]))

    # 没命中时给**可执行的建议**，不要只丢一张空表让人以为工具坏了
    if empty_queries:
        hint = ["", "=" * 62, "以下查询没命中任何卡片：", ""]
        for q in empty_queries:
            hint.append("  「{}」".format(q))
        hint += [
            "",
            "怎么改进（按有效性排序）：",
            "  1. 用**素材库里真实存在的词**。先看看库里有什么：",
            "       python auto_select_cards.py --list-tech        # 各技法维度覆盖量",
            "       或直接翻 外部 seek 项目/05_工作流与Skills/liblib提示词库/提示词库.md（按题材分节）",
            "  2. 题材要具体。'国风山水' 有效；'，。！？' / 'abc123' 无效——",
            "   纯标点与纯数字不参与匹配。",
            "  3. 去掉筛选条件再试：--type / --topic-type / --tech 会缩小候选池，",
            "     叠加后可能全被过滤掉。",
            "  4. 换个近义词：'赛博' 试试 '科幻' / '未来'。",
            "=" * 62,
            "",
        ]
        print("\n".join(hint), file=sys.stderr)

    body = format_md(queries, results, covers_dir) if args.format == "md" else format_json(queries, results, covers_dir)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"已写出 {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(body)


if __name__ == "__main__":
    main()