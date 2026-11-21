#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 短片全链路流水线 —— 一条命令从题材走到可直接制作的清单。

**这个脚本解决什么**
把「想拍一条国风 AI 短片」到「拿到手就能开工」之间的 6 步串成一条命令：
  1. 选卡      从素材库挑出最相关的提示词/技法/构图/光影
  2. 剧情      按题材 + 时长 + 情绪生成 logline / 三幕 / 钩子
  3. 脚本      逐场拆出：景别 / 画面描述 / 台词 / 时长 / 技法标注
  4. 分镜      每场拆成可出图的首帧提示词（九段骨架）+ 运镜意图
  5. 技巧      匹配光影/构图/调色/运镜技法（从技法库现取，不编）
  6. 清单      汇总成制作执行清单（素材 / 技法 / 负向词 / 工作量）

**设计原则（与项目铁律一致）**
  · 通用：零本地路径耦合，全部 `__file__` 推算 + CLI 覆盖
  · 不绑厂商：输出是**中性制作规格**，不写死任何平台/模型的专属语法
  · 可审核：每一步都写进一份 Markdown，人类在审核节点签字
  · 降级不崩：素材库缺失时用内置模板兜底，产出仍然完整（标记为「需补素材」）

**用法**
  # 最简：给题材，出一条 60 秒短片
  python shortfilm_pipeline.py "敦煌飞天 复仇" --duration 60

  # 指定风格与情绪
  python shortfilm_pipeline.py "深山道士" --style 水墨 --mood 肃杀 --duration 90

  # 批量（一行一个题材）
  python shortfilm_pipeline.py --batch topics.txt --out ./out

  # 只跑到某一步
  python shortfilm_pipeline.py "题材" --until 分镜

  # JSON 输出（接后续自动化）
  python shortfilm_pipeline.py "题材" --format json
"""
import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter

# 5 关审核点从 review_gate.py 取，不在本文件抄第二份。
# 抄第二份就会漂移——实测两份已经不一致（这里少一关的措辞还对不上）。
# review_gate.py 是叶子模块（零 import），所以这样依赖方向是安全的。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from review_gate import checkpoints_md  # noqa: E402
import lib_locator  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 素材库位置**不在这里写死**，统一由 lib_locator 探测（环境变量 → 项目内
# seek库 → 同级目录）。合并前这里是「库就在脚本旁边」的老布局，
# 外部 seek 项目已迁出体系，体系侧不再保留媒体副本。
DEFAULT_PROMPTS = lib_locator.prompts_path() or os.path.join(
    SCRIPT_DIR, "prompts.jsonl")
DEFAULT_COVERS = lib_locator.covers_dir() or os.path.join(
    SCRIPT_DIR, "封面")

# ============================================================
# 一、内置创作知识库（通用，不绑厂商）
#    这些是「短片工艺」常识，素材库没有也得能用。
# ============================================================

STYLES = {
    "水墨": {"光线": "柔和漫射，无强阴影", "色彩": "黑白灰为主，点缀朱砂",
           "运镜": "缓推 / 固定为主", "质感": "宣纸纹理，墨色浓淡干湿"},
    "国漫": {"光线": "高对比强轮廓光", "色彩": "浓郁饱和，互补色对撞",
           "运镜": "推进 / 环绕，速度感强", "质感": "厚涂笔触，高饱和"},
    "工笔": {"光线": "均匀平光，无强烈明暗", "色彩": "石青石绿层层罩染",
           "运镜": "固定 / 微移", "质感": "细腻线条，绢本设色"},
    "写实": {"光线": "自然光 / 黄金时刻侧逆光", "色彩": "低饱真实肤色",
           "运镜": "手持 / 斯坦尼康", "质感": "胶片颗粒，真实材质"},
    "赛博": {"光线": "霓虹自发光 + 边缘光", "色彩": "青橙对撞，高饱",
           "运镜": "快速横移 / 甩镜", "质感": "湿滑反射，体积雾"},
}

MOODS = {
    "肃杀": {"色温": "冷", "对比": "高", "节奏": "慢镜头 + 顿帧", "音": "低频鼓点 + 弦乐低音"},
    "空灵": {"色温": "中性偏冷", "对比": "低", "节奏": "长镜头 + 缓推", "音": "空灵铃音 + 气息"},
    "热血": {"色温": "暖", "对比": "高", "节奏": "快切 + 升格", "音": "鼓点密集 + 弦乐推进"},
    "凄美": {"色温": "冷灰", "对比": "中", "节奏": "慢 + 停顿", "音": "独奏 + 环境音"},
    "诡谲": {"色温": "冷绿/紫", "对比": "极高", "节奏": "抖动 + 不规则", "音": "低频嗡鸣 + 突发音"},
    "温情": {"色温": "暖黄", "对比": "低", "节奏": "固定 + 缓", "音": "柔弦 + 环境暖音"},
}

# 三幕结构模板（通用戏剧骨架）
ACT_STRUCTURE = [
    {"act": "第一幕：建置", "pct": 0.25,
     "task": "建立人物处境与世界观，展示『日常』或『失衡前状态』，埋钩子"},
    {"act": "第二幕：对抗", "pct": 0.50,
     "task": "冲突升级，主角付出代价，误会/对抗/追逐/揭示真相"},
    {"act": "第三幕：解决", "pct": 0.25,
     "task": "高潮对决或情感爆发，收束，留余韵与回味"},
]

# 景别 → 构图要点
COMPOSE_BY_SIZE = {
    "大远景": "人物占画面 1/5 以下，环境占主导，前景有遮挡物",
    "远景": "人物占画面 1/3，环境交代位置关系",
    "全景": "人物全身入画，脚下留少量地面",
    "中景": "腰部以上，视线平齐，背景虚化",
    "近景": "胸部以上，面部占画面 1/2",
    "特写": "面部或道具充满画面，浅景深",
    "大特写": "只留眼睛/手/器物，背景完全虚化",
}

# 风格 → 时代设定（填「时代/身份」段，避免占位符）
ERA_BY_STYLE = {
    "水墨": "东方古典·文人水墨语境",
    "国漫": "东方架空·国漫世界观",
    "工笔": "东方古典·工笔重彩语境",
    "写实": "按题材自定的现实/半写实设定",
    "赛博": "近未来·东方科幻设定",
}

# 运镜表（分镜用）
CAMERA_MOVES = [
    ("固定", "静止机位，对话/冥想/庄严", "低"),
    ("缓推", "逼近主体，聚焦注意，悬念累积", "中"),
    ("拉远", "揭示环境规模，反衬孤独", "中"),
    ("横移", "跟随平行运动，交代场景", "中"),
    ("跟拍", "跟随主体移动，代入感强", "高"),
    ("环绕", "绕主体旋转，强调对峙/神性", "高"),
    ("升降", "从地面升到高处（或反之），戏剧化", "高"),
    ("手持", "轻微晃动，临场感/紧张/混乱", "中"),
]

# 「幕 × 景别」→ 推荐运镜。避免整片一个机位。
_CAMERA_PLAN = {
    # 建置：先交代空间，人还没动
    ("第一幕", "大远景"): "拉远揭示环境规模，营造开场气势",
    ("第一幕", "远景"): "横移交代场景与人物位置关系",
    ("第一幕", "中景"): "固定机位承载对话，眼神戏靠表演",
    ("第一幕", "全景"): "缓推靠近人物，注意力收拢",
    ("第一幕", "近景"): "固定，浅景深突出表情",
    ("第一幕", "特写"): "固定特写，情绪伏笔",
    ("第一幕", "大特写"): "固定大特写，埋钩子",
    # 对抗：动起来，跟拍与手持制造临场感
    ("第二幕", "大远景"): "升降拉开战场，纵深感压迫",
    ("第二幕", "远景"): "跟拍追逐，代入感强",
    ("第二幕", "中景"): "环绕对峙双方，强调张力",
    ("第二幕", "全景"): "手持跟拍，动作戏不平稳更真实",
    ("第二幕", "近景"): "缓推逼近面部，压迫感递增",
    ("第二幕", "特写"): "手持特写，冲突爆发点",
    ("第二幕", "大特写"): "固定大特写（武器/眼神），爆发前一秒静止",
    # 解决：收束，回落到稳定
    ("第三幕", "大远景"): "拉远收束，天光破晓留余韵",
    ("第三幕", "远景"): "横移跟随离场背影",
    ("第三幕", "中景"): "固定，情绪平复",
    ("第三幕", "全景"): "缓慢拉远，结束感",
    ("第三幕", "近景"): "固定，泪光特写收情绪",
    ("第三幕", "特写"): "固定特写，尘埃落定",
    ("第三幕", "大特写"): "固定大特写，留白结尾",
}


def _camera_for(act, shot_size, idx, style_move):
    """按幕+景别取运镜；表里没有就按景别给个合理的默认。"""
    key = (act[:3], shot_size)
    if key in _CAMERA_PLAN:
        return _CAMERA_PLAN[key]
    fallback = {
        "大远景": "拉远交代规模", "远景": "横移交代环境",
        "全景": "缓推靠近", "中景": "固定机位",
        "近景": "缓推逼近表情", "特写": "固定特写", "大特写": "固定大特写",
    }
    base = fallback.get(shot_size, "固定机位")
    # 风格给的运镜倾向作为补充信息
    return "{}（风格倾向：{}）".format(base, style_move) if style_move and style_move not in base else base


# 景别表（分镜用）
SHOT_SIZES = [
    ("大远景", "交代环境与规模，气势开场", "8-12%"),
    ("远景", "人物在环境中，交代位置关系", "12%"),
    ("全景", "人物全身动作", "15%"),
    ("中景", "对话主力景别，兼顾动作与表情", "20%"),
    ("近景", "情绪强调，台词常用", "15%"),
    ("特写", "关键表情/道具特写，情绪爆点", "10%"),
    ("大特写", "眼睛/手/器物细节，强情绪", "10%"),
]

# 运镜表（分镜用）
CAMERA_MOVES = [
    ("固定", "静止机位，对话/冥想/庄严", "低"),
    ("缓推", "逼近主体，聚焦注意，悬念累积", "中"),
    ("拉远", "揭示环境规模，反衬孤独", "中"),
    ("横移", "跟随平行运动，交代场景", "中"),
    ("跟拍", "跟随主体移动，代入感强", "高"),
    ("环绕", "绕主体旋转，强调对峙/神性", "高"),
    ("升降", "从地面升到高处（或反之），戏剧化", "高"),
    ("手持", "轻微晃动，临场感/紧张/混乱", "中"),
]

# 九段提示词骨架（出图首帧）
NINE_PARTS = ["主体", "时代/身份", "服饰细节", "动作/神态", "环境背景",
              "构图安排", "光影氛围", "材质肌理", "风格声明"]

NEGATIVE_BASE = ("低分辨率, 模糊, 变形, 多余手指, 肢体错乱, 水印, 文字, "
                 "低质量, 崩坏, 重复")
NEGATIVE_EN = ("lowres, blurry, low quality, worst quality, watermark, signature, "
               "bad anatomy, missing limbs, extra fingers, mutated hands, text")

# ============================================================
# 一之二、台词库（让脚本真能念，不给占位符）
#     按「幕 × 景别」给可直接念的国风短剧对白模板。
#     {S}=主体 {C}=冲突 {L}=地点 {T}=旧物/器物
# ============================================================

DIALOGUE_BANK = {
    ("第一幕", "大远景"): ["天地不仁，{S}亦不过是一枚棋子。", "此处若无风，{L}便是一口枯井。"],
    ("第一幕", "远景"):   ["{S}立于{L}之上，traditionally unaware 危机将至。", "三日前的星象，今夜应验。"],
    ("第一幕", "中景"):   ["你我今日在此，往后便各安天命。", "这{C}，我等了三年。"],
    ("第一幕", "近景"):   ["你说过的，{L}再无人回来。", "此去经年，怕是再见不到了。"],
    ("第一幕", "全景"):   ["风起了。", "有人来了。"],
    ("第一幕", "特写"):   ["（低声）来不及了。", "（指尖微颤）"],
    ("第一幕", "大特写"): ["（特写眼）三、二、一……", "（特写{T}上的裂纹）"],

    ("第二幕", "大远景"): ["{L}之上，风雪掩埋了来路。", "退无可退，唯有一战。"],
    ("第二幕", "远景"):   ["{C}追至此处，避无可避。", "跑了三年，原来一直在原地。"],
    ("第二幕", "中景"):   ["你为何偏要追我至此？", "当年是你亲手种下的{C}，如今却来问我。"],
    ("第二幕", "近景"):   ["我等的不是道歉，是你回来。", "你以为躲得掉？"],
    ("第二幕", "全景"):   ["（拔剑）不必再言。", "（掷出{T}）接住！"],
    ("第二幕", "特写"):   ["血落在雪上，没有声音。", "（喘息）我还能……走多远。"],
    ("第二幕", "大特写"): ["（剑锋映光）", "（瞳孔骤缩）"],

    ("第三幕", "大远景"): ["尘埃落定，{L}重归寂静。", "天光破晓，长夜终尽。"],
    ("第三幕", "远景"):   ["{S}转身，走向{L}的尽头。", "有些答案，不必说出口。"],
    ("第三幕", "中景"):   ["此间事，到此为止了。", "愿来世，不必再见{C}。"],
    ("第三幕", "近景"):   ["我放下了，你也该放下了。", "（轻声）走吧。"],
    ("第三幕", "全景"):   ["（转身）后会无期。", "（合上{T}）"],
    ("第三幕", "特写"):   ["最后一滴泪，落入尘土。", "（闭眼）"],
    ("第三幕", "大特写"): ["（手松开）", "（风停）"],
}

# 景别曲线：整片应当**逐步推近**，每一幕比上一幕更近。
# 建置看得最广（交代世界）→ 对抗推近（压迫递增）→ 解决收到细节（收束）。
# 每幕 2 镜，共 6 镜。词用尽或换结构时回落到 ["中景", "近景"]。
SHOTSIZE_CURVE = {
    "第一幕": ["大远景", "远景"],
    "第二幕": ["全景", "中景"],
    "第三幕": ["近景", "特写"],
}
# 景别的「由远及近」序，用来机器验证曲线确实是收紧的。
# 大远景 < 远景 < 全景 < 中景 < 近景 < 特写 < 大特写
SHOT_TIGHTNESS = {n: i for i, (n, _d, _p) in enumerate(SHOT_SIZES)}

# 主体/冲突/地点/器物 从题材推导
STOPWORDS = set("的 了 与 和 在 是 有 个 之 于 其 而 及 以 也 都 就 又 被 把 对 从 到 上 下 中 为 主题 短片 片子")  # noqa: E501

# 人物身份词：题材里出现这些的才算「画中的人」
# 为什么不能直接取第一个词——那样「江南 书生 夜雨」的主体就成了「江南」，
# 提示词第一段写「主体：江南」，把地名当人物交给出图模型；
# 「长安 夜市 志怪」同理，主体是「长安」。
ROLE_WORDS = (
    "书生", "道士", "道人", "僧人", "和尚", "禅师", "将军", "公子", "姑娘", "女子",
    "少年", "少女", "老者", "老人", "孩童", "童子", "农妇", "舞姬", "皇帝", "太后",
    "公主", "太子", "太监", "侠客", "剑客", "武士", "忍者", "医师", "医者", "船夫",
    "艄公", "掌柜", "幕僚", "镖师", "捕快", "画师", "琴师", "戏子", "飞天", "神女",
    "仙子", "书生", "门生", "账房", "媒人", "乞丐",
)

# 与本片画风**直接矛盾**的风格标签，按风格家族分组。
# 语料是按「跨作品共识度」挖词，挖到的是**高赞词**，不是**合拍风词**——
# 于是水墨片的提示词里会混进「INS风」「纯欲风」这类现代网红风标签。
# 两条画风信号打架，出图模型只能二选一，抽卡率直接起飞。
# 实测产物：S02「INS风」、S03「纯欲风」、S04「薇薇纯欲风」，
# 材质槽还混进「细腻陶瓷水嫩肌肤」「真人皮肤质感细腻」。
STYLE_CONFLICT = {}
# ① 现代网红/商业摄影向的风格标签与胶片质感
_MODERN_TAGS = (
    r"INS风", r"纯欲", r"网红", r"写真", r"韩系", r"手机壁纸", r"水嫩", r"水光肌",
    r"皮肤美白透亮", r"真人皮肤质感", r"陶瓷.{0,4}肌肤", r"棚拍", r"真实摄影",
    r"胶片", r"摄影", r"数码", r"HDR", r"电影质感", r"电影", r"柔焦", r"景深虚化",
    # 现代美妆/商业修图词——在工笔/水墨语境里是「另一套画面语言」
    r"皮肤(?:白皙|光滑|细腻|水嫩|透亮)", r"磨皮", r"瓷肌", r"美颜",
    r"指甲油", r"美甲", r"口红", r"唇釉", r"腮红", r"眼影", r"亮片甲",
)

# 情绪冲突：动作/神态与本片情绪相悖的词。
# 语料挖词不看情绪，于是「诡谲」恐怖片里会出现「面带笑意」「咧嘴大笑」。
# 情绪不对 = 观众出戏 = 抽卡重做，这一条直接打在该死的抽卡率上。
# 情绪 → **正向**氛围词。跟 MOOD_CONFLICT 配套：
# 那边拦掉与情绪相悖的（诡谲片里的「面带笑意」），
# 这边给出与情绪一致的（诡谲片该配「阴森/不祥」，不是「史诗/空灵」）。
# 之前氛围列直接取库内前 N 个命中词，结果是任意的——
# 实测诡谲片里出现「史诗」「空灵」，正是刚被禁掉的那类词。
MOOD_ATMOSPHERE = {
    "肃杀": ["肃杀", "压迫", "凝重", "肃穆", "冷峻", "铁血"],
    "诡谲": ["诡异", "阴森", "不祥", "神秘", "压迫", "鬼气"],
    "凄美": ["凄美", "萧瑟", "哀伤", "悲凉", "清冷", "孤寂"],
    "空灵": ["空灵", "缥缈", "澄澈", "静谧", "通透", "出尘"],
    "热血": ["激昂", "凌厉", "炽烈", "紧绷", "爆发", "决绝"],
    "温情": ["温暖", "柔和", "安宁", "治愈", "静谧", "明亮"],
}

MOOD_CONFLICT = {
    # 注意：**只拦明确的嬉笑/欢庆，不要拦「浅笑」「淡笑」**——
    # 那是克制的神态，在肃杀/凄美片里完全成立。
    # 泛化成 `笑` 会被自检判「误拦」；收得太紧又会漏掉「面带笑意」
    # （实测两次都踩了：先误拦浅笑，再漏掉面带笑意）。
    # 落点：拦 `笑意/笑容/嬉笑/大笑/欢笑`，放行 `浅笑/淡笑/微笑`。
    "肃杀": r"大笑|欢笑|嬉笑|笑意|笑容|喜笑颜开|眉开眼笑|咧嘴|欢庆|"
            r"其乐融融|载歌载舞|灿烂|明媚|暖阳",
    "诡谲": r"大笑|欢笑|嬉笑|笑意|笑容|咧嘴|灿烂|明媚|暖阳|温馨|治愈|撒娇",
    "凄美": r"大笑|欢笑|嬉笑|喜笑颜开|喜庆|热闹|喧闹|载歌载舞|灿烂",
    "空灵": r"嬉闹|打斗|拥挤|喧闹|市井|杂乱",
    "热血": r"慵懒|困倦|静谧|百无聊赖|昏睡",
    "温情": r"厮杀|搏斗|狰狞|暴怒|追杀",
}
# ② 现代都市地标——和水墨/工笔/国漫的古典语境直接打架
_MODERN_PLACE = (
    r"大厦", r"摩天", r"高楼", r"玻璃幕墙", r"写字楼", r"便利店", r"地铁",
    r"天桥", r"红绿灯", r"车流", r"西式", r"哥特", r"巴洛克", r"牛仔",
)
# ③ 槽位里出现「他人身份词」= 主体错位（主体是书生，服饰却写艄公）
#    这是一份**人物名词黑名单**，要尽量全——之前只有 6 个词，
#    结果「手持灯笼的古风旅人」「古风舞姬」这类照样混进来。
_OTHER_ROLE = tuple(ROLE_WORDS) + (
    "旅人", "旅者", "行者", "侠", "武士", "剑客", "刀客", "骑手", "船夫", "艄夫",
    "船娘", "商贩", "货郎", "农夫", "农妇", "猎户", "渔夫", "樵夫", "乞丐",
    "妇人", "汉子", "青年", "中年人", "老人", "妇孺", "仕女", "侍女", "宫女",
    "侍卫", "士兵", "将官", "书生", "幕僚", "门客", "店小二", "掌柜",
    "舞姬", "歌姬", "戏子", "琴师", "画师", "医者", "药师", "仵作", "捕快",
    "孩童", "童子", "婴儿", "新娘", "新郎", "和尚", "尼姑", "道士",
)

# 这三个是东方古典画风，对上面三组一律拦。
# 写实/赛博本来就偏现代摄影，刻意不给它们配冲突表。
for _s in ("水墨", "工笔", "国漫"):
    STYLE_CONFLICT[_s] = _MODERN_TAGS + _MODERN_PLACE


def _pick_keyword(topic, default):
    """从题材里取一个有画面感的词做 {S}。"""
    for t in re.split(r"[\s,，、/]+", topic):
        t = t.strip()
        if len(t) >= 2 and t not in STOPWORDS:
            return t
    return default


def _pick_subject(topic, default="少年"):
    """从题材里挑**画中的人**，而不是第一个词。

    原来用 `_pick_keyword` 取第一个词，于是
      「江南 书生 夜雨」→ 主体「江南」  （地名当人物）
      「长安 夜市 志怪」→ 主体「长安」
    提示词第一段就会写「主体：江南，东方古典设定，宽袖收腰…」——
    出图模型拿到的是一座地名当主体，抽卡必然翻车。
    规则：优先取含人物身份词的词；全都不是就退回中性人物，
    **绝不用地名顶替人物**。
    """
    toks = [t.strip() for t in re.split(r"[\s,，、/]+", topic) if t.strip()]
    for t in toks:
        if any(r in t for r in ROLE_WORDS):
            return t
    return default


def _conflict_rx(style):
    """本片画风的冲突正则；没有配置则返回 None（写实/赛博不拦）。"""
    pats = STYLE_CONFLICT.get(style)
    if not pats:
        return None
    return re.compile("|".join(pats))


def make_dialogue(topic, act, shot_size, scene_index):
    """按幕+景别取一句可直接念的台词，并做变量替换。"""
    S = _pick_subject(topic)
    # 用分词重组而不是 replace 拼接，避免残留双空格/把词切碎
    rest = " ".join(t for t in re.split(r"[\s,，、/]+", topic)
                    if t and t != S) or "宿命"
    bank = DIALOGUE_BANK.get((act[:3], shot_size))
    if not bank:
        # 兜底：找同幕任意景别
        for (a, _ss), lines in DIALOGUE_BANK.items():
            if a == act[:3]:
                bank = lines
                break
    if not bank:
        bank = ["（沉默）"]
    line = bank[scene_index % len(bank)]
    return (line.replace("{S}", S)
                .replace("{C}", rest)
                .replace("{L}", f"{S}之地")
                .replace("{T}", "旧物")
                .replace("traditionally unaware 危机将至", "尚不知危机将至"))


# 表演提示：（转身）（闭眼）（低声）…… 在脚本里是正常的，
# **但绝不能进字幕**——字幕是把观众念出来的字显示在画面上。
_STAGE_DIR = re.compile(r"[（(][^）)]*[）)]")
SUB_MAX = 16          # 单条字幕字数上限，超了就该断句而不是截断


def split_stage_direction(text):
    """把「（提示）台词正文」拆成 (提示, 正文)。

    **为什么必须拆**：DIALOGUE_BANK 里大量台词带全角括号表演提示。
    不拆的话产物里会出现 `对白字幕：（转身）后会无期。`——
    表演提示被当成台词显示在画面上；更糟的是
    `（闭眼）`、`（手松开）` 这类**整条只有提示、没有台词**的镜，
    字幕栏写的就是「对白字幕：（闭眼）」，观众看到的是一句莫名其妙的括号。
    """
    if not text:
        return "", ""
    t = str(text).strip()
    prompt = "".join(_STAGE_DIR.findall(t))
    return prompt, _STAGE_DIR.sub("", t).strip()

# ============================================================
# 二、素材库检索（可选；库不在也能跑）
# ============================================================

TECHNIQUE_MAP = {
    "光影": r"光影|逆光|侧光|体积光|丁达尔|剪影|烛光|月光|柔光|高反差|伦勃朗|轮廓光|低饱|金色时刻|蓝色时刻",
    "构图": r"构图|三分法|黄金分割|对称|引导线|框架|留白|前景虚化|景深|中心构图",
    "调色": r"青橙|莫兰迪|胶片|赛博|暗黑|油画|水墨|赛璐璐|高级灰|色调|饱和",
    "镜头": r"广角|长焦|微距|鱼眼|航拍|景深|特写|俯拍|仰拍|手持|跟拍|环绕|移轴|长曝光|低角度",
    "氛围": r"雾|雨|雪|烟尘|烈焰|雷电|神秘|肃杀|空灵|诡异|孤独|紧张|温馨|史诗|压迫",
}

TOPIC_HINT = {
    "水墨": r"水墨|国画|工笔|写意|留白|宣纸|Sumi|Ink",
    "敦煌": r"敦煌|飞天|藻井|石窟|壁画|莫高",
    "神话": r"神话|山海经|妖|龙|仙|神|异兽|上古",
    "武侠": r"武侠|剑|刀|江湖|侠客|门派|轻功",
    "仙侠": r"仙侠|修仙|灵气|渡劫|飞升|法宝|丹药",
    "非遗": r"非遗|皮影|剪纸|刺绣|陶瓷|青花|唐卡|扎染|傩",
}


def load_records(path):
    if not path or not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    return out


# 卡片级的调性过滤：素材库里混着**现代网红/写真/电商模特**类 LoRA。
# 东方古典片子（水墨/工笔/国漫）选到「F.1男神极致写实拍摄风格小红书生活
# 男生男模」这种参考锚点，调性完全对不上——实测就选中过，而且同一张
# 还因为记录重复而占了两个名额。
# ���是**卡级**过滤，跟提示词词级的 STYLE_CONFLICT 是两码事：
# 这里要拦的是整个资源（名字/标签/提示词都算）。
CARD_CONFLICT = (
    r"小红书", r"男模", r"女模", r"模特", r"电商", r"带货", r"证件照", r"婚纱",
    r"写真", r"网红", r"INS风", r"纯欲", r"韩系", r"男神", r"女神", r"御姐",
    r"萝莉", r"比基尼", r"性感", r"诱惑", r"包臀裙", r"直播",
)


def pick_cards(records, topic, n=6, style=""):
    """按题材从素材库挑卡片。命中 name 权重最高。

    复用 `_topic_tokens` 的权重表：整词命中（3.0）压过 2-gram 命中（1.0），
    避免「深山道士」被「山」这种泛字带偏。

    **两道额外过滤**（都是实测踩出来的）：
      ① 画风/调性冲突卡：东方古典片不该选到现代网红/电商模特类 LoRA。
      ② 去重：素材库里有同名不同记录的卡，不去重会白占一个名额
         （实测「F.1男神…男模」连续出现两次）。
    """
    if not records:
        return []
    weights = _topic_tokens(topic)
    if not weights:
        return []

    banned = re.compile("|".join(CARD_CONFLICT)) if style in (
        "水墨", "工笔", "国漫") else None

    scored = []
    for r in records:
        name = (r.get("name") or "").lower()
        tags = " ".join((t or "").lower() for t in (r.get("tags") or []))
        ptext = " ".join((it.get("prompt") or "")
                         for it in (r.get("items") or [])[:3])
        if banned and banned.search((r.get("name") or "") + " "
                                    + " ".join(r.get("tags") or [])
                                    + " " + ptext):
            continue
        blob = name + " " + tags
        strength = max((w for t, w in weights.items() if t.lower() in blob), default=0.0)
        if not strength:
            ptext = " ".join((it.get("prompt") or "")
                             for it in (r.get("items") or [])[:3])
            strength = max((w for t, w in weights.items()
                            if t.lower() in ptext.lower()), default=0.0)
            if strength:
                strength *= 0.45      # 只在 prompt 里命中的，降权
        if strength:
            scored.append((strength + (r.get("likeCount") or 0) * 0.01, r))
    scored.sort(key=lambda x: -x[0])
    # 去重：同名（或同 uuid）的记录只保留分数最高的那条。
    # 不去重会白占名额——实测「F.1男神…男模」连续出现两次。
    out, seen = [], set()
    for sc, r in scored:
        key = (r.get("name") or "").strip() or (r.get("uuid") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append((sc, r))
        if len(out) >= n:
            break
    return out


def safe_filename(topic, limit=24):
    """题材 → 合法文件名。

    Windows 禁用字符 `\\ / : * ? " < > |`，此外**控制字符/换行/制表**
    也会让路径炸掉（`a\nb` 会把命令拆成两行）。全部替换掉。
    """
    s = str(topic)
    s = re.sub(r'[\\/:*?"<>|\r\n\t\x00-\x1f]', "_", s)
    s = s.strip().strip(".")          # 去掉首尾空白与结尾的点（Windows 不允许）
    s = re.sub(r"_{2,}", "_", s)     # 合并连续下划线
    if not s:
        s = "未命名"
    return s[:limit]


def find_cover(url, covers_dir):
    if not url or not covers_dir or not os.path.isdir(covers_dir):
        return None
    h = hashlib.md5(url.encode()).hexdigest()[:12]
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = os.path.join(covers_dir, h + ext)
        if os.path.exists(p):
            return p
    return None


def portable_path(p):
    """把绝对路径转成**相对项目根**的路径，供写进产物文件。

    **为什么必须转**
    产物（制作包.json）是会被存下来、发出去、换台机器打开的。
    写死本机盘符的话，别人拿到就全是死链。
    实测：整个项目搬到新盘后重跑，JSON 里的 cover 字段会跟着变成
    新盘符 —— 说明它是运行时绝对路径，不是写死，但危害一样。

    相对**项目根**而不是相对脚本目录：库迁出体系之后，
    相对脚本目录会算出带 `..` 的路径，既不直观，又会被
    「安全性能」闸的路径穿越规则当成漏洞报警。

    转不了（不在项目内 / 本来就是相对路径）就原样返回：
    这里只做可移植性收敛，不做正确性判断。
    """
    if not p or not os.path.isabs(p):
        return p
    try:
        rel = os.path.relpath(p, lib_locator.PROJECT_ROOT)
    except ValueError:          # 跨盘符（Windows C: → D:）relpath 会抛
        return p
    if rel.startswith(".." + os.sep) or rel == "..":
        return p               # 在项目外，保持原样（不是本项目该管的事）
    return rel.replace(os.sep, "/")


# ============================================================
# 一之三、语料挖掘：让分镜提示词用**库内真实词汇**，不是占位符
#     从高赞作品的 prompt 里切出「服饰/环境/光影/材质/动作」实词。
#     这就是「借鉴 + 减少抽卡率」——不自己编词，用别人验证过的词。
# ============================================================

# 每个维度的**核心名词**。正则只看这些词，避免「发光」里的「发」被当成服饰。
# 审计发现：原正则太宽导致服饰 22.9% / 环境 16.7% 的词义错位
# （例如「光影在此间自由流转」被塞进动作栏、「闪闪发光的金色羽毛」进了服饰栏）。
VOCAB_CATS = {
    # 必须是穿戴在身上的东西
    "服饰": r"衣|裙|袍|袖|腰带|冠|帽|簪|钗|佩|铠甲|履|靴|披帛|披风|襟|领|扣|"
            r"绣纹|刺绣|锦|纱罗|绸缎|裳|襦|流苏|抹额|头冠|耳坠|项链|手镯|银饰",
    # 必须是场景/景物，不是纹样也不是纯色
    "环境": r"山|水|林|石|崖|谷|寺|庙|宫|城|楼|阁|庭|院|桥|河|海|云|雾|雨|雪|"
            r"风|沙|松|莲|荷|阶|殿|屋|廊|道|亭|塔|原野|田|溪|瀑布|悬崖|远山|云端|云海",
    "光影": r"光|影|阳|烛|月|辉|明|暗|亮|霭|逆光|侧光|轮廓|剪影|色温|辉映|透光|打光|光晕|光斑",
    "材质": r"质感|纹理|裂纹|痕迹|做旧|粗糙|光滑|绢|纸|砂|绒|漆|釉|锈|鎏金|泥金|"
            r"斑驳|颗粒|亚麻|棉麻|丝绒|皮革|石质",
    # 必须是动作/姿态
    "动作": r"立|坐|行|走|跑|飞|舞|挥|举|持|握|转|望|笑|哭|叹|跪|卧|跃|拔|抚|踏|掠|拂|垂|展|垂落|伫立|驻足",
}

# 维度间的**排他词**：某词若命中其他维度的核心特征，就不归本维度。
# 例：「光影在此间自由流转」含「光影」特征 → 不能进动作栏。
_VOCAB_EXCLUDE = {
    "动作": re.compile(r"光|影|色|调|质感|纹理|摄影|镜头|氛围|背景"),
    "环境": re.compile(r"光|影|色|调|质感|纹|衣|裙|袍|袖|冠|簪|氛围|情绪|气氛|感觉"),
    "服饰": re.compile(r"光|影|色|调|背景|环境|氛围|质感|摄影|镜头|羽毛|翅膀"),
    "光影": re.compile(r"衣|裙|袍|袖|冠|簪|立|坐|走|跑|飞|舞|望|笑"),
    "材质": re.compile(r"衣|裙|袍|袖|立|坐|走|飞|舞|望|笑|身姿|身形|"
                      r"动画|漫画|插画|摄影|相机|CCD|像素|渲染|3D|2D|画风"),
}

# 画质/规格/空话类词，出图时用不上，从语料里剔掉
_JUNK = re.compile(
    r"(高清|超清|最高质|高质量|最佳质量|质量高|低质量|壁纸|分辨率|jpg|png|"
    r"\d+\s*[kK]\b|niji|版权|商用|禁止|上传|发布|尺寸|比例|竖版|横版|方形|"
    r"和谐平衡|视觉冲击|艺术效果|呈现|展现出|表现出|营造出|打造|"
    r"无ai|自由发挥|不要|避免|镜头对着|看着镜头|面对镜头|镜头感|"
    r"一致性|保持|注意|建议|适合|可用于|通用)", re.I)

# 纯风格声明（"怪诞小镇漫画风格"），不是可复用的实体词
_STYLE_ONLY = re.compile(r"风格|画风|8宫格|九宫格|分镜|排版|构图模板")
# 抽象/含糊表述，直接贴进提示词效果差
_ABSTRACT = re.compile(r"(气质|似乎|非常|充满活力|和谐|或$|或。|以及|等等|若干|某种)")
# 「整句」型片段（含动词/叙述词/食物描述），贴进提示词会变成一段话而不是标签
_CLAUSE = re.compile(r"(这是一?[张个]|照片|摄影照|画面中|镜头|视角|背景中|"
                     r"孙悟空|哪吒|人物|角色|主体|采用|展现|呈现|描绘|"
                     r"闹|坐在|站在|没入|化作|化为|流苏没|内馅|馅为|粽|食物|口味)")

# 各维度的词长上限：环境/光影是短标签，服饰/材质可以稍长
_CAT_MAXLEN = {"环境": 8, "光影": 9, "动作": 10, "服饰": 12, "材质": 12}

# 维度专属排除：某些词在别的维度是宝贝，在本维度是噪音
# 环境栏最容易被「国风插画 / 古风写真」这类**风格/用途词**污染；
# 也会混进「石青 / 朱红」这类**纯颜色词**（那是材质/色彩，不是场景）
_CAT_EXCLUDE = {
    "环境": re.compile(r"(插画|写真|海报|壁纸|国风|古风|新国风|二次元|概念|"
                       r"原画|设定|素材|模板|屏保|头像|"
                       r"石青|石绿|朱红|藏蓝|泥金|鎏金|金粉|斑斓|多彩|"
                       r"赭石|藤黄|胭脂|石调|点缀$)"),
    "服饰": re.compile(r"(图案|线条|发光|光芒|轮廓|边缘)$"),
    "材质": re.compile(r"(人物|身形|身姿|气质)"),
    "光影": re.compile(r"(人物|身形|身姿|眼神|目光)"),
}

_LABEL = re.compile(r"^(风格|场景|服饰|服装|色彩|配色|发饰|首饰|构图|光影|材质|"
                    r"背景|画质|类型|主题|内容|氛围|状态|效果)\s*[:：]\s*")
_LEAD = re.compile(r"^(采用|使用|为|是|带有|配上|搭配|整体|画面|整体画面)\s*")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_SPLIT = re.compile(r"[,，、;；\n]+")


def _clean_seg(seg, cat=""):
    """把一个片段清洗成可用的短词组。cat 用于维度专属过滤。"""
    s = seg.strip()
    s = _LABEL.sub("", s)
    s = _LEAD.sub("", s)
    s = re.sub(r"^(以|用|取)\s*", "", s)
    s = s.strip(" 　,，.。;；:：")
    # 切开后常残留半个括号 / 半个词，标签类词组不该带这些
    # 注意：全角右括号 ）和半角 ) 都要覆盖
    if re.search(r"[（）()\[\]【】《》<>{}]|\s$", s):
        return ""
    # 逗号切开后常留下「。东方美学」「带细腻。CCD」这种**半句碎片**，
    # 贴进提示词是噪声（实测占残缺词 28%）。见到句末标点直接判废。
    if re.search(r"[。．.，,；;：:！？!?、…—～~]+", s[1:]) or re.search(r"[。．，,、…]$", s):
        return ""
    if not s or not _CJK.search(s):
        return ""
    if _JUNK.search(s) or _STYLE_ONLY.search(s) or _ABSTRACT.search(s) or _CLAUSE.search(s):
        return ""
    ex = _CAT_EXCLUDE.get(cat)
    if ex and ex.search(s):
        return ""
    # 排他词：命中其他维度核心特征 → 词义错位，不归本维度
    ex2 = _VOCAB_EXCLUDE.get(cat)
    if ex2 and ex2.search(s):
        return ""
    # 「A或B」并列写法贴进提示词会打架
    if "或" in s[1:-1]:
        return ""
    if len(s) < 2 or len(s) > _CAT_MAXLEN.get(cat, 12):
        return ""
    return s


def _topic_tokens(topic):
    """题材 → (检索词, 权重)。中文复合词切 2-gram 提高召回，但权重必须低。

    「深山道士」在库里不会原样出现，但「道士」会出现。
    不过 2-gram「山」会命中山水/山景，若与整词「道士」同权，
    就会把大量无关作品捞进来、稀释真正相关的语料。
    所以：整词权重 3.0，2-gram 权重 1.0，题材别名 2.0。
    """
    whole = [t for t in re.split(r"[\s,，、/]+", topic) if len(t) > 1]
    extra = []
    for t in whole:
        cjk = re.sub(r"[^\u4e00-\u9fff]", "", t)
        if len(cjk) >= 3:
            extra.extend(cjk[i:i + 2] for i in range(len(cjk) - 1))
    alias = []
    for key, pat in TOPIC_HINT.items():
        if key in topic:
            alias.extend(re.findall(pat, topic))

    weights = {}
    for t in whole:
        weights[t] = max(weights.get(t, 0), 3.0)
    for t in alias:
        weights[t] = max(weights.get(t, 0), 2.0)
    for t in extra:
        weights[t] = max(weights.get(t, 0), 1.0)
    return weights


def _match_strength(weights, blob):
    """一个作品对题材的相关度：取所有命中词里最高的那个权重。"""
    blob = blob.lower()
    return max((w for t, w in weights.items() if t.lower() in blob), default=0.0)


def mine_vocab(records, topic, n=6):
    """从与题材相关的作品里挖各维度实词。

    **打分 = 跨作品共识度，不是出现次数。**
    这是关键区别：一个作者在同一篇提示词里重复 5 次的词，
    说明不了什么；而 10 个不同作者各写 1 次，说明这是**通行写法**。
    共识度高的词才是「别人验证过能出片」的写法——这正是减少抽卡率的依据。

    具体公式：
        score(词) = Σ over 作品( log(1+点赞) × 命中强度 )
                 + 2.0 × log(1 + 独立作品数)      ← 共识奖励
    返回 {类别: [词, ...]}
    """
    if not records:
        return {}
    pats = _topic_tokens(topic)
    if not pats:
        return {}

    # 找出相关作品，按「整词命中 > 2-gram 命中」分级
    rel = []
    for r in records:
        name = (r.get("name") or "").lower()
        tags = " ".join((t or "").lower() for t in (r.get("tags") or []))
        s = _match_strength(pats, name + " " + tags)
        if s >= 2.0:
            rel.append((r, s))
            continue
        ptext = " ".join((it.get("prompt") or "") for it in (r.get("items") or [])[:2])
        if ptext:
            s = _match_strength(pats, ptext)
            if s > 0:
                rel.append((r, s))
    if not rel:
        return {}

    # 粗排：先按「命中强度 × 点赞」取前 400 篇，保证强命中作品优先进入语料池
    rel.sort(key=lambda x: -(x[0].get("likeCount") or 0) * x[1])
    rel = rel[:400]

    import math
    out = {}
    for cat, pat in VOCAB_CATS.items():
        rx = re.compile(pat)
        score = {}          # 词 -> 累计分
        distinct = {}       # 词 -> 出现过它的独立作品数
        for r, strength in rel:
            # 命中强度越高权重越大：整词命中(3.0) 压过 2-gram 命中(1.0)
            boost = math.log1p(r.get("likeCount") or 0) * strength
            if boost <= 0:
                boost = strength * 0.3   # 零点赞作品也别完全丢掉
            # 同一作品内去重：一次作品里重复 5 次不额外加分
            seen_here = set()
            for it in (r.get("items") or [])[:2]:
                ptext = it.get("prompt") or ""
                if not ptext:
                    continue
                for seg in _SPLIT.split(ptext):
                    c = _clean_seg(seg, cat)
                    if not c or not rx.search(c) or c in seen_here:
                        continue
                    seen_here.add(c)
                    score[c] = score.get(c, 0.0) + boost
                    distinct[c] = distinct.get(c, 0) + 1
        # 共识奖励：被越多**不同作品**用过，越可信
        final = {w: s + 2.0 * math.log1p(distinct.get(w, 0)) for w, s in score.items()}
        top = sorted(final.items(), key=lambda x: -x[1])
        out[cat] = [w for w, _ in top[:n * 3]][:n]
    return out


# ============================================================
# 三、六步流水线
# ============================================================

def step1_cards(topic, records, covers_dir, n=6, style=""):
    """选卡：挑出相关素材作为参考锚点。"""
    picked = pick_cards(records, topic, n, style)
    cards = []
    for sc, r in picked:
        it = (r.get("items") or [{}])[0]
        cards.append({
            "name": r.get("name"),
            "type": r.get("modelTypeName"),
            "tags": (r.get("tags") or [])[:5],
            "prompt_sample": re.sub(r"\s+", " ", (it.get("prompt") or ""))[:150],
            # 存相对项目根的路径，不存绝对路径（见 portable_path 的说明）
            "cover": portable_path(find_cover(it.get("cover"), covers_dir)),
            "source": "liblib#" + (r.get("uuid") or "")[:8],
            "score": round(sc, 2),
        })
    return cards


def step2_plot(topic, duration, mood):
    """剧情：logline + 三幕 + 钩子。"""
    mood = mood or "空灵"
    chars = re.split(r"[\s,，、/]+", topic)
    subject = chars[0] if chars else topic
    conflict = chars[1] if len(chars) > 1 else ("命运" if mood in ("空灵", "凄美") else "宿敌")

    logline = f"一个{subject}，因{conflict}被迫走出安全之地，在归途中明白了{('放下' if mood=='空灵' else '守护' if mood=='热血' else '真相')}。"
    hook = f"开场 {3} 秒钩子：{subject}所依赖的旧物/旧地出现异变，暗示{conflict}降临。"

    # 幕时长必须**加起来正好等于 duration**，不能各幕各自四舍五入。
    # 比例 0.25/0.50/0.25 是精确的，但 round() 逐个取整仍可能多出几秒：
    # 实测 60 秒被拆成 16+30+16=62 秒，且产物里没有任何地方提示「和目标差 2 秒」。
    # 制片交付里时长对不上是要返工的——余数补到最长的一幕，保证和严格等于目标。
    raw = [duration * a["pct"] for a in ACT_STRUCTURE]
    secs = [max(3, int(r)) for r in raw]
    secs[secs.index(max(secs))] += duration - sum(secs)
    acts = [{"act": a["act"], "seconds": s, "task": a["task"]}
            for a, s in zip(ACT_STRUCTURE, secs)]
    return {"logline": logline, "hook": hook, "mood": mood, "acts": acts}


def step3_script(topic, plot, duration, mood, style):
    """脚本：逐场拆景别/画面/台词/时长/技法。"""
    style_kb = STYLES.get(style, STYLES["写实"])
    mood_kb = MOODS.get(mood, MOODS["空灵"])
    scenes = []
    t = 0
    for i, act in enumerate(plot["acts"], 1):
        # 每幕拆 2 场，两场秒数**加起来必须正好等于幕时长**。
        # 同样不能各自 round()：15 秒的幕拆成 7.5+7.5 各进位成 8 → 16 秒，
        # 三幕下来总时长凭空多出 2 秒（实测 60 秒变 62 秒）。
        base = act["seconds"] // 2
        pair = [base, act["seconds"] - base]        # 余数给第二场，和严格守恒
        for j, sec in enumerate(pair, 1):
            ratio = (act["seconds"] / 2) / act["seconds"]
            # 景别走**叙事曲线**，不是机械轮转。
            # 原来用 idx 轮转 SHOT_SIZES，6 镜出来是：
            #   大远景 → 中景 → 远景 → 近景 → 全景 → 特写
            # 先跳进、再跳出、又跳进、再大幅跳出——节奏是乱的，
            # 观众建立不起「越靠近、越紧张」的体感。
            curve = SHOTSIZE_CURVE.get(act["act"][:3]) or ["中景", "近景"]
            want = curve[j - 1] if j - 1 < len(curve) else curve[-1]
            hit = next((s for s in SHOT_SIZES if s[0] == want), SHOT_SIZES[0])
            size, size_note, _ = hit
            scenes.append({
                "no": len(scenes) + 1,
                "act": act["act"],
                "second": j,
                "seconds": sec,
                "shot_size": size,
                "shot_note": size_note,
                "visual": f"（{style}）{topic}｜{size}｜{mood}氛围｜{style_kb['光线']}",
                "dialogue": make_dialogue(topic, act["act"], size, len(scenes)),
                "tech": {
                    "光": style_kb["光线"],
                    "色": style_kb["色彩"],
                    "运": style_kb["运镜"],
                    "质": style_kb["质感"],
                    "情绪": f"{mood_kb['色温']}／对比{mood_kb['对比']}",
                },
            })
            t += sec
    return {"scenes": scenes, "style_kb": style_kb, "mood_kb": mood_kb,
            "audio": mood_kb["音"]}


# 景别 → 机位 / 焦段建议（供体系 G3 分镜表的「机位/焦段」列用）
CAMERA_GEAR = {
    "大远景": ("高机位俯拍或平视远端", "广角 16-24mm"),
    "远景":   ("平视，略低于视线", "标准 35mm"),
    "全景":   ("平视，与胸齐高", "标准 35-50mm"),
    "中景":   ("平视，与眼齐高", "标准 50mm"),
    "近景":   ("平视或微仰", "中长 85mm"),
    "特写":   ("平视正对", "长焦 85-135mm"),
    "大特写": ("正对或微仰，强化压迫", "长焦 135mm+"),
}

# 本镜叙事功能（按幕 + 景别判断这一镜在成片里干什么）
NARRATIVE_FUNC = {
    ("第一幕", "大远景"): "交代世界与规模，建立基调",
    ("第一幕", "远景"): "交代人物处境与位置关系",
    ("第一幕", "中景"): "建立人物关系，展开对话",
    ("第一幕", "全景"): "引入主体动作，注意力收拢",
    ("第一幕", "近景"): "建立人物情绪基调",
    ("第一幕", "特写"): "埋设关键道具或细节伏笔",
    ("第一幕", "大特写"): "强钩子：观众必须注意的细节",
    ("第二幕", "大远景"): "展现冲突规模，提升压迫感",
    ("第二幕", "远景"): "推进冲突/追逐，空间关系交代",
    ("第二幕", "中景"): "核心对峙，信息交换",
    ("第二幕", "全景"): "动作戏主镜，打斗/冲突主体",
    ("第二幕", "近景"): "情绪升温，压迫递增",
    ("第二幕", "特写"): "冲突爆发点",
    ("第二幕", "大特写"): "爆发前一秒静止，制造悬念",
    ("第三幕", "大远景"): "收束全局，留余韵",
    ("第三幕", "远景"): "交代结局状态",
    ("第三幕", "中景"): "情感表达，信息落地",
    ("第三幕", "全景"): "结束动作，转身/离场",
    ("第三幕", "近景"): "情绪落点，观众共情",
    ("第三幕", "特写"): "尘埃落定，细节收束",
    ("第三幕", "大特写"): "留白式结尾",
}

# 镜前/镜后状态（供「对下一镜约束」推导）
STATE_LEAD = {
    "第一幕": "人物处于日常/失衡前状态",
    "第二幕": "人物已付出代价，处境恶化",
    "第三幕": "冲突已解决，情绪平复",
}


def step4_storyboard(topic, script, vocab=None, mood=""):
    """分镜：每场出**可直接出图**的首帧提示词（九段骨架）。

    九段的填充来源：
      · 服饰/环境/光影/材质/动作 → 库内高赞作品挖掘出的真实词汇
      · 时代/身份、风格声明       → 风格与情绪知识库
      · 构图                      → 景别对应
      · 运镜                      → 按「幕 × 景别」从运镜表分配，避免全场一个机位
    素材库缺失时退回内置描述，仍是完整可用的提示词。
    """
    vocab = vocab or {}
    ring = {k: (v or [""]) for k, v in vocab.items()}
    boards = []
    subject = _pick_subject(topic)
    # Frozen costume/place/material anchors may legitimately repeat across shots.
    used_global = set()
    banned = _conflict_rx(script.get("style", ""))
    # 情绪冲突只管「动作/神态」槽——笑不笑这件事由情绪决定，
    # 材质/环境/服饰出现「笑」不构成问题。
    mood_pat = MOOD_CONFLICT.get(mood)
    mood_rx = re.compile(mood_pat) if mood_pat else None
    # 跳过记录用 dict 保序去重：pick() 每镜都会重扫整张词表，
    # 不去重的话同一个词会重复记 N 次，制作包里刷出几十行重复。
    skipped = {}         # (词, 原因) -> 槽位

    def pick(cat, idx):
        """取词，跳过本片已用过的词。词用尽就返回空，交由内置描述兜底
        —— 宁可少一个维度，也不要 6 场反复用同一个词。

        **还要跳过与本片画风冲突的词**：语料按共识度挖出来的是「高赞词」，
        不是「合拍风词」。水墨片里混进「INS风」「纯欲风」，
        两条画风信号打架，出图只能二选一，抽卡率直接起飞。
        """
        v = ring.get(cat) or []
        if not v or not v[0]:
            return ""
        for w in v:
            if w in used_global and cat not in ('服饰', '环境', '材质'):
                continue
            if banned and banned.search(w):
                skipped.setdefault((w, "画风冲突"), cat)
                continue
            # 情绪与神态相悖（诡谲片里「面带笑意」）——观众出戏就等于要重抽
            if cat == "动作" and mood_rx and mood_rx.search(w):
                skipped.setdefault((w, "情绪冲突"), cat)
                continue
            # 任何槽位都不该**引入另一个人**。语料是全库挖的，
            # 会带出「孩童头戴草帽」「艄公戴斗笠持竹篙」这类描述**别人**的词——
            # 主体是书生，出图却画出一个戴草帽的孩童，主体当场错位。
            # 规则：词里若含人物身份词，而该身份不是本片主体 → 拦下。
            for role in _OTHER_ROLE:
                if role in w and role not in subject:
                    skipped.setdefault((w, "主体错位"), cat)
                    break
            else:
                used_global.add(w)
                return w
            continue
        return ""

    for s in script["scenes"]:
        i = s["no"] - 1
        costume = pick("服饰", i) or "着该时代常服"
        place = pick("环境", i) or "开阔地带"
        light = pick("光影", i) or s["tech"]["光"]
        matter = pick("材质", i) or s["tech"]["质"]
        # 兜底不能用 shot_note —— 那是**景别说明文字**（「人物在环境中，交代位置关系」），
        # 塞进提示词等于把内部注释交给出图模型。词用尽就留空，让人补。
        act = pick("动作", i)
        move = _camera_for(s["act"], s["shot_size"], i, s["tech"]["运"])

        parts = {
            "主体": subject,
            "时代/身份": f"{ERA_BY_STYLE.get(script.get('style'), '东方古典')}设定",
            "服饰细节": costume,
            "动作/神态": act,
            "环境背景": place,
            "构图安排": f"{s['shot_size']}，{COMPOSE_BY_SIZE.get(s['shot_size'], '主体居中')}",
            "光影氛围": f"{light}，{s['tech']['情绪']}",
            "材质肌理": matter,
            "风格声明": f"{script['style']}，{s['tech']['色']}",
        }
        prompt_cn = "，".join(f"{k}：{v}" for k, v in parts.items())
        prompt_flow = "，".join(v for v in parts.values() if v)
        act_key = s["act"][:3]
        size = s["shot_size"]
        pos, focal = CAMERA_GEAR.get(size, ("平视", "标准 35mm"))
        boards.append({
            "scene": s["no"],
            "shot_size": size,
            "seconds": s["seconds"],
            "first_frame_prompt_cn": prompt_cn,
            "first_frame_prompt_flow": prompt_flow,
            "nine_parts": parts,
            "camera_intent": move,
            # ---- 供体系 G3 分镜表使用 ----
            "act": s["act"],
            "act_short": act_key,
            "camera_position": pos,
            "focal_length": focal,
            "narrative_function": NARRATIVE_FUNC.get(
                (act_key, size), "{}镜位，交代{}".format(size, act_key)),
            "state_before": STATE_LEAD.get(act_key, ""),
            "dialogue": s.get("dialogue", ""),
            "costume": costume,
            "place": place,
            "light": light,
            "negative": NEGATIVE_BASE,
        })
    # 跳过的词在**全部镜头跑完之后**统一回填。
    # 之前是逐镜 append 时就 `list(skipped)` 快照，结果第 1 镜只带走了
    # 它自己那一刻的记录，后面几镜拦下的词全丢了——要让人看见就得放全。
    for b in boards:
        b["style_skipped"] = [[w, cat, why]
                              for (w, why), cat in skipped.items()]
    return boards


def step5_techniques(plot, records, boards=None, style=""):
    """技巧：**按镜给出可直接执行的技法方案**，不是只给检索索引。

    原来返回 `{"pattern": ..., "from_library": N}` —— 那是**检索索引**，
    不是这部片子的技法方案。用户看到「光影维度 376 条」之后，
    仍然得自己去那 376 条里翻，等于活儿还在人身上，
    不符合「拿去直接制作即可」。
    （而且原实现里算出来的 `matched` 列表从来没被用过，是死代码。）

    改成两层：
      · `per_shot` —— 每镜的 光影/构图/调色/氛围/运镜 具体到词，
        构图按景别给、调色按画风给、光影与氛围用库内实词（已过过滤），
        与首帧提示词里的槽位**同源**，不会出现「提示词写一套、技法表写另一套」。
      · `index` —— 原来的检索索引保留为附表，供人要深挖时用。
    """
    mood = plot["mood"]
    style_kb = STYLES.get(style, STYLES["写实"])
    mood_kb = MOODS.get(mood, MOODS["空灵"])
    banned = _conflict_rx(style)

    # 库内实词（与分镜提示词共用同一批词，保证两边一致）
    light_pool, mood_pool = [], []
    for r in records[:2000]:
        txt = " ".join([r.get("name") or ""] + list(r.get("tags") or [])
                       + [it.get("prompt", "") for it in (r.get("items") or [])][:2])
        for dim_pat, bucket in ((TECHNIQUE_MAP["光影"], light_pool),
                                (TECHNIQUE_MAP["氛围"], mood_pool)):
            for w in re.split(r"[|，,、]", dim_pat):
                w = w.strip()
                if w and w not in bucket and re.search(re.escape(w), txt, re.I):
                    if banned and banned.search(w):
                        continue
                    bucket.append(w)
    mood_rx = re.compile(MOOD_CONFLICT.get(mood, r"$^"))

    # 氛围词：优先用**库内确实出现过**的（可信），否则用情绪自带词表。
    atmos_pool = MOOD_ATMOSPHERE.get(mood) or MOOD_ATMOSPHERE["空灵"]
    lib_words = set()
    for r in records[:2000]:
        txt = " ".join([r.get("name") or ""] + list(r.get("tags") or [])
                       + [it.get("prompt", "") for it in (r.get("items") or [])][:2])
        for w in atmos_pool:
            if w not in lib_words and re.search(re.escape(w), txt, re.I):
                lib_words.add(w)
    # 库内有证的排前面（更贴合这个库），其余按情绪表顺序补齐
    atmos = [w for w in atmos_pool if w in lib_words] + \
            [w for w in atmos_pool if w not in lib_words]

    def take(pool, rx=None, i=0):
        for w in pool[i:]:
            if rx and rx.search(w):
                continue
            return w
        return ""

    per_shot = []
    for i, b in enumerate(boards or []):
        size = b.get("shot_size", "")
        per_shot.append({
            "shot": b.get("scene"),
            "size": size,
            "光影": b.get("light") or take(light_pool, None, i) or style_kb["光线"],
            "构图": COMPOSE_BY_SIZE.get(size, "主体居中"),
            "调色": style_kb["色彩"],
            "氛围": atmos[i % len(atmos)] if atmos else mood,
            "运镜": b.get("camera_intent", ""),
            "叙事功能": b.get("narrative_function", ""),
        })

    index = {}
    for dim, pat in TECHNIQUE_MAP.items():
        from_lib = 0
        for r in records[:2000]:
            txt = " ".join([r.get("name") or ""] + list(r.get("tags") or [])
                           + [it.get("prompt", "") for it in (r.get("items") or [])][:2])
            if re.search(pat, txt, re.I):
                from_lib += 1
        index[dim] = {"pattern": pat[:60], "from_library": from_lib}
    return {"per_shot": per_shot, "index": index}


# 稳定 ID 体系（对齐体系 G3/G6 模板的 S/G/A/FX/BGM/SUB 编号）
def _sid(n):
    return "S{:02d}".format(n)


def _gid(n):
    return "G{:03d}".format(n)


def build_sound_plan(boards, mood=None):
    """按镜分配声音与字幕事件，供体系剪辑装配单使用。

    **只给节奏与位置，不编造音频文件。**
    体系 G6 要求每个声音元素有稳定 ID 可反查——ID 和节拍能自动给，
    实际音频文件必须人来生成/挑选，所以留「待填」。
    """
    mood = mood or "空灵"
    # 情绪 → BGM 走向（给剪辑师方向，不指定具体曲子）
    bgm_plan = {
        "肃杀": "低频鼓点起，弦乐渐进，中段留白，结尾骤停",
        "空灵": "单件乐器（古琴/箫）起，缓慢铺底，尾声渐隐",
        "热血": "密集鼓点，弦乐推高，高潮全奏，尾奏干净收",
        "凄美": "独奏主旋律，环境音垫底，结尾留长混响",
        "诡谲": "低频嗡鸣铺底，不规则音效插入，结尾突静",
        "温情": "柔弦/钢琴，环境暖音，结尾自然收",
    }.get(mood, "按情绪选配乐")

    # 景别 → 音效密度与字幕策略
    plan = []
    for b in boards:
        n = b["scene"]
        size = b.get("shot_size", "")
        # **先剥表演提示再判有没有台词**：整条只有「（闭眼）」这种提示的镜，
        # 不是「有对白」，只是没有正文可念。
        prompt, line = split_stage_direction(b.get("dialogue") or "")
        has_line = bool(line) and "占位" not in line
        if has_line:
            if len(line) > SUB_MAX:
                # 截断会吞掉后半句，字幕缺字是硬伤——标出来让人断句
                sub = "对白字幕（{} 字，需断句）：{}".format(len(line), line)
            else:
                sub = "对白字幕：{}".format(line)
        elif prompt:
            # 纯表演提示镜：明确写「无对白」，不要留「待定」让人猜
            sub = "无对白字幕（纯表演提示 {}，靠画面与环境音）".format(prompt)
        elif size in ("大远景", "远景", "全景"):
            sub = "无字幕（留画面呼吸）"
        else:
            sub = "环境字幕/地名，待定"
        # 大特写/特写强调音效点缀
        if size in ("特写", "大特写"):
            fx = "音效点缀 ×1（关键细节）"
        elif b.get("act_short") == "第二幕":
            fx = "音效 ×2（动作/环境）"
        else:
            fx = "音效 ×1（环境铺底）"
        plan.append({
            "shot": n,
            "sid": _sid(n),
            "gid": _gid(n),
            "seconds": b.get("seconds", 0),
            "voice_id": "A{:03d}".format(n) if has_line else "—",
            "fx_id": "FX{:03d}".format(n),
            "fx_note": fx,
            "sub_id": "SUB{:03d}".format(n) if has_line else "—",
            "sub_note": sub,
        })
    return {"bgm_id": "BGM001", "bgm_note": bgm_plan, "events": plan}


def step6_checklist(topic, plot, script, boards, cards, style, mood):
    """清单：汇总成制作执行清单。"""
    total_sec = sum(s["seconds"] for s in script["scenes"])
    assets = {
        "角色": f"依据「{topic}」出 3 视角定妆（正面/侧面/背面）",
        "场景": f"依据分镜出 {len({b['shot_size'] for b in boards})} 个景别场景首帧",
        "道具": "按剧情挑 2-3 件关键道具特写",
        "首帧总帧数": len(boards),
    }
    workload = {
        "首帧出图": f"{len(boards)} 张（每场 1 张首帧）",
        "视频生成": f"{total_sec} 秒（按 {script['mood_kb']['节奏']}）",
        "配音/音乐": script["audio"],
        "剪辑": f"按三幕 {len({s['act'] for s in script['scenes']})} 段切分",
    }
    return {
        "assets": assets,
        "workload": workload,
        "negatives": {"cn": NEGATIVE_BASE, "en": NEGATIVE_EN},
        "review_checkpoints": checkpoints_md(),
        "cards_used": len(cards),
    }


def run_pipeline(topic, duration, style, mood, until, records, covers_dir, route='custom'):
    steps = ["选卡", "剧情", "脚本", "分镜", "技巧", "清单"]
    limit = steps.index(until) + 1 if until in steps else len(steps)

    result = {"topic": topic, "duration": duration, "style": style,
              "mood": mood or "空灵", "library_records": len(records),
              "route": route, "status": "draft", "production_ready": False,
              "creative_required": "待创作审核：模板与库内词不构成可拍剧本或生产批准"}
    idx = 0

    idx += 1
    result["cards"] = step1_cards(topic, records, covers_dir, 6, style)
    for card in result['cards']:
        card['applicability'] = 'unverified'
        card['production_use'] = False
    if idx >= limit:
        return result

    idx += 1
    result["plot"] = step2_plot(topic, duration, mood)
    if route != 'drama':
        tasks = (['核验原始依据与生活流程', '设计协作或交易的可见过程', '呈现结果与场景关系']
                 if route == 'historical_life' else
                 ['建立视觉母题', '设计对比和变化', '形成情绪落点'])
        result['plot'].update(logline='待创作：' + topic,
                              hook='待设计观看承诺，不自动制造冲突')
        labels = (['依据与流程', '协作与交易', '结果与关系'] if route == 'historical_life'
                  else ['视觉母题', '对比与变化', '情绪落点'])
        for act, task, label in zip(result['plot']['acts'], tasks, labels):
            act['task'] = task
            act['act'] = label
    if idx >= limit:
        return result

    idx += 1
    result["script"] = step3_script(topic, result["plot"], duration, mood, style)
    result["script"]["style"] = style
    if route != 'drama':
        # These are planning slots, not a six-shot shooting prescription.
        scenes = result['script']['scenes'][::2]
        for i, scene in enumerate(scenes):
            scene['no'] = i + 1
            scene['seconds'] = result['plot']['acts'][i]['seconds']
            scene['dialogue'] = ''
            scene['visual'] = '待创作：' + result['plot']['acts'][i]['task']
            scene['shot_size'] = '中景'
        result['script']['scenes'] = scenes
    result['script']['draft_only'] = True
    if idx >= limit:
        return result

    idx += 1
    # 从库内挖真实语料填实分镜（缺库时返回空 dict，内部自动退回内置描述）
    result["vocab"] = mine_vocab(records, topic, n=8)
    result["storyboard"] = step4_storyboard(topic, result["script"],
                                            result["vocab"], mood or "")
    if route != 'drama':
        for board in result['storyboard']:
            board['narrative_function'] = '待创作：' + result['plot']['acts'][board['scene'] - 1]['task']
            board['state_before'] = '待核验具体人物、空间与道具状态'
            board['camera_intent'] = '待依据观看重点确定，不自动按幕运镜'
    if idx >= limit:
        return result

    idx += 1
    result["techniques"] = step5_techniques(
        result["plot"], records, result["storyboard"], style)
    if idx >= limit:
        return result

    idx += 1
    result["sound_plan"] = build_sound_plan(result["storyboard"], mood)
    result["checklist"] = step6_checklist(topic, result["plot"], result["script"],
                                          result["storyboard"], result["cards"],
                                          style, mood)
    result["steps_done"] = steps[:limit]
    return result


# ============================================================
# 四、输出
# ============================================================

def render_summary(r):
    """执行摘要：人扫一眼就知道「要做什么、要花多少、从哪开始」。

    放在制作包最前面。详细六节在下面。
    """
    L = []
    plot = r.get("plot") or {}
    script = r.get("script") or {}
    boards = r.get("storyboard") or []
    chk = r.get("checklist") or {}
    scenes = script.get("scenes") or []

    L.append("## 执行摘要\n")
    L.append("| 项 | 内容 |")
    L.append("|---|---|")
    L.append("| 题材 | {} |".format(r["topic"]))
    L.append("| 规格 | {}风格 / {}情绪 / {}秒 / {} 镜 |".format(
        r["style"], r["mood"], r["duration"], len(boards) or len(scenes)))
    if plot:
        L.append("| 一句话故事 | {} |".format(plot.get("logline", "—")))
    L.append("| 立刻要做 | 出 {} 张首帧 → 每张接视频 → 装配 {} 秒 |".format(
        len(boards), sum(s.get("seconds", 0) for s in scenes)))
    if script.get("audio"):
        L.append("| 声音基调 | {} |".format(script["audio"]))
    if chk.get("workload"):
        L.append("| 配音/配乐 | {} |".format(chk["workload"].get("配音/音乐", "—")))

    hook = plot.get("hook", "") if plot else ""
    # hook 本身已含「开场 3 秒钩子：」前缀，这里不要重复加
    L.append("**开场 3 秒钩子**：{}\n".format(hook.replace("开场 3 秒钩子：", "").strip()))

    # 分镜速查表：一眼看完所有镜头
    if boards:
        L.append("### 分镜速查（照这个顺序出图）\n")
        L.append("| # | 景别 | 时长 | 运镜 | 首帧提示词（纯词序） |")
        L.append("|---|---|---|---|---|")
        for b in boards:
            flow = b.get("first_frame_prompt_flow", "")
            if len(flow) > 96:
                flow = flow[:96] + "…"
            L.append("| {} | {} | {}s | {} | {} |".format(
                b["scene"], b["shot_size"], b["seconds"],
                b["camera_intent"].split("，")[0], flow))
        L.append("")

    # 语料来源
    if r.get("vocab"):
        L.append("### 库内实词（提示词已用这些填实，可按需替换）\n")
        for cat, ws in r["vocab"].items():
            if ws:
                L.append("- **{}**：{}".format(cat, "、".join(ws)))
        L.append("")

    # 被拦下的词：要让人**看得见**，否则会以为素材库里本来就没这些词。
    # 语料是按「跨作品共识度」挖的，挖到的是高赞词，不是合拍风词——
    # 水墨片里混进 INS风/纯欲风/上海中心大厦 时，出图模型会收到两条打架的
    # 信号，抽卡率直接起飞。宁可少一个维度，也不能让画风自相矛盾。
    _sk = (r.get("storyboard") or [{}])[0].get("style_skipped") or []
    if _sk:
        L.append("### 已拦下的不适用词（{} 个，别直接抄进提示词）\n".format(len(_sk)))
        for _cat, _w, _why in _sk:
            L.append("- `{}`（{}）".format(_w, _why))
        L.append("")

    # 历史草案检查项：只保留内容自检，不再把旧 review_gate 暴露成生产入口。
    if chk.get("review_checkpoints"):
        L.append("### 历史草案检查项\n")
        labels = ("剧情：logline、因果和钩子是否成立",
                  "脚本：场景、台词和时长是否合理",
                  "分镜：首帧提示词能否作为草案继续改写",
                  "技法：光影、构图和调色是否服务情绪",
                  "执行：素材与工作量是否可执行")
        for label in labels:
            L.append("- [ ] {}".format(label))
        L.append("")
        L.append("> 这是内部草案生成器的静态样例，不是当前生产入口。当前做片按 "
                 "`从这里开始.md` / `AGENTS.md` 自主推进；需要重新查询参考时运行 "
                 "按剧本、导演视觉圣经和项目资产自主定稿；本脚本仅供历史草案回归。")
    L.append("> 详细拆解见下方六节。**负向词**统一用："
             "{}\n".format((chk.get("negatives") or {}).get("cn", NEGATIVE_BASE)))
    return "\n".join(L)


def render_md(r):
    L = []
    L.append(f"# AI 短片制作包：{r['topic']}\n")
    L.append(f"> 风格 {r['style']}｜情绪 {r['mood']}｜时长 {r['duration']}秒"
             f"｜素材库 {r['library_records']} 条\n")
    L.append(render_summary(r))
    L.append("\n---\n")

    if r.get("cards"):
        L.append("## ① 选卡（素材参考锚点）\n")
        L.append("| # | 名称 | 类型 | 标签 | 提示词节选 | 封面 | 来源 |")
        L.append("|---|---|---|---|---|---|---|")
        for i, c in enumerate(r["cards"], 1):
            # cover 在 step1_cards 阶段已转成相对项目根的路径，这里直接用。
            # （不要再套 relpath：输入已经是相对路径，套上去会按当前 cwd
            #   二次解析，搬到别的目录就指错地方。）
            cov = c.get("cover") or "—"
            L.append(f"| {i} | {c['name']} | {c['type']} | {'、'.join(c['tags']) or '—'} "
                     f"| {c['prompt_sample'][:60]}… | `{cov}` | `{c['source']}` |")
        L.append("")

    if r.get("plot"):
        p = r["plot"]
        L.append("## ② 剧情\n")
        L.append(f"**Logline**：{p['logline']}\n")
        L.append(f"**钩子**：{p['hook']}\n")
        L.append("| 幕 | 时长 | 任务 |")
        L.append("|---|---|---|")
        for a in p["acts"]:
            L.append(f"| {a['act']} | {a['seconds']}s | {a['task']} |")
        L.append("")

    if r.get("script"):
        s = r["script"]
        L.append("## ③ 脚本（逐场）\n")
        L.append("| 场 | 幕 | 时长 | 景别 | 画面 | 台词 | 技法 |")
        L.append("|---|---|---|---|---|---|---|")
        for sc in s["scenes"]:
            tech = f"光:{sc['tech']['光'][:8]}／运:{sc['tech']['运'][:8]}"
            L.append(f"| {sc['no']} | {sc['act'][:3]} | {sc['seconds']}s | {sc['shot_size']} "
                     f"| {sc['visual']} | {sc['dialogue']} | {tech} |")
        L.append(f"\n**音频**：{s['audio']}\n")

    if r.get("storyboard"):
        L.append("## ④ 分镜（首帧提示词，可直接出图）\n")
        if r.get("vocab"):
            L.append("**语料来源**：以下词汇由库内高赞作品挖掘得出（不是编的），"
                     "分镜提示词已用它们填实。\n")
            L.append("| 维度 | 库内实词 |")
            L.append("|---|---|")
            for cat, words in r["vocab"].items():
                if words:
                    L.append("| {} | {} |".format(cat, "、".join(words)))
            L.append("")
        for b in r["storyboard"]:
            L.append(f"### 第 {b['scene']} 场 · {b['shot_size']} · {b['seconds']}s\n")
            L.append(f"**运镜意图**：{b['camera_intent']}\n")
            L.append(f"**首帧提示词（中文·带段标）**：{b['first_frame_prompt_cn']}\n")
            L.append(f"**首帧提示词（纯词序·直接粘贴）**：{b.get('first_frame_prompt_flow', '')}\n")
            L.append(f"**负向**：{b['negative']}\n")

    if r.get("techniques"):
        tech = r["techniques"]
        ps = tech.get("per_shot") or []
        if ps:
            L.append("## ⑤ 技法方案（逐镜，可直接照做）\n")
            L.append("> 光影/构图/调色/氛围/运镜都来自本片已选定的词，与首帧提示词"
                     "**同源**——提示词写一套、技法表写另一套是常见坑。\n")
            L.append("| 镜 | 景别 | 叙事功能 | 光影 | 构图 | 调色 | 氛围 | 运镜 |")
            L.append("|---|---|---|---|---|---|---|---|")
            for t in ps:
                L.append("| S{:02d} | {} | {} | {} | {} | {} | {} | {} |".format(
                    t["shot"] or 0, t["size"], t.get("叙事功能", ""),
                    t["光影"], t["构图"], t["调色"], t["氛围"], t["运镜"]))
            L.append("")
        idx = tech.get("index") or {}
        if idx:
            L.append("<details><summary>附：库内检索索引（要深挖时用）</summary>\n")
            L.append("| 维度 | 库内覆盖 | 检索模式 |")
            L.append("|---|---|---|")
            for dim, info in idx.items():
                L.append(f"| {dim} | {info['from_library']} | `{info['pattern'][:40]}` |")
            L.append("\n</details>\n")
        L.append("")

    if r.get("sound_plan"):
        sp = r["sound_plan"]
        L.append("### 声音与字幕计划（稳定 ID，供剪辑装配用）\n")
        L.append("**BGM `{}`**：{}\n".format(sp["bgm_id"], sp["bgm_note"]))
        L.append("| 镜头 | 时长 | 配音ID | 音效ID | 音效提示 | 字幕ID | 字幕策略 |")
        L.append("|---|---|---|---|---|---|---|")
        for e in sp["events"]:
            L.append("| {} | {}s | {} | {} | {} | {} | {} |".format(
                e["sid"], e["seconds"], e["voice_id"], e["fx_id"],
                e["fx_note"], e["sub_id"], e["sub_note"]))
        L.append("\n> 实际音频/字幕文件需人工生成后回填 ID 对应文件路径。\n")

    if r.get("checklist"):
        c = r["checklist"]
        L.append("## ⑥ 制作执行清单\n")
        L.append("**素材需求**\n")
        for k, v in c["assets"].items():
            L.append(f"- {k}：{v}")
        L.append("\n**工作量**\n")
        for k, v in c["workload"].items():
            L.append(f"- {k}：{v}")
        L.append(f"\n**负向词**\n- 中文：{c['negatives']['cn']}\n- 英文：{c['negatives']['en']}\n")
        L.append("**人工审核节点**\n")
        for cp in c["review_checkpoints"]:
            L.append(f"- {cp}")
        L.append("")

    L.append("---\n")
    L.append("*本包由流水线自动生成，厂商中立。制作时按你所用平台的语法微调首帧提示词即可。*")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="AI 短片全链路流水线（选卡→剧情→脚本→分镜→技巧→清单）")
    ap.add_argument("topics", nargs="*", help="题材描述")
    ap.add_argument("--batch", help="一行一个题材的文件")
    ap.add_argument("--duration", type=int, default=60, help="成片时长（秒），默认 60")
    ap.add_argument("--style", default="写实", choices=sorted(STYLES.keys()),
                    help="风格：" + "/".join(STYLES.keys()))
    ap.add_argument("--mood", default=None, choices=sorted(MOODS.keys()),
                    help="情绪：" + "/".join(MOODS.keys()))
    ap.add_argument("--until", default="清单",
                    choices=["选卡", "剧情", "脚本", "分镜", "技巧", "清单"],
                    help="只跑到某一步")
    ap.add_argument('--route', default='custom',
                    help='Optional free-form project type; agent chooses the actual structure')
    ap.add_argument("--cards", type=int, default=6, help="选卡数量")
    ap.add_argument("--prompts", help="自定义 prompts.jsonl（默认与本脚本同目录）")
    ap.add_argument("--covers", help="自定义封面目录（默认与本脚本同目录/封面）")
    ap.add_argument("--out", help="输出目录（多题材时每题材一个 md）")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    args = ap.parse_args()

    topics = list(args.topics)
    if args.batch:
        for line in open(args.batch, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                topics.append(line)
    if not topics:
        ap.error("请提供题材（位置参数 或 --batch）")

    prompts = args.prompts or DEFAULT_PROMPTS
    covers = args.covers or DEFAULT_COVERS
    records = load_records(prompts)
    if not records:
        print(f"[提示] 未找到素材库 {prompts}，将用内置模板产出（标记需补素材）",
              file=sys.stderr)

    results = []
    for t in topics:
        r = run_pipeline(t, args.duration, args.style, args.mood, args.until,
                         records, covers, args.route)
        r["cards"] = r.get("cards", [])[:args.cards]
        results.append(r)

    if args.format == "json":
        body = json.dumps(results, ensure_ascii=False, indent=2)
    else:
        body = "\n\n---\n\n".join('> 制作草案，不是生产批准。路线：' + r['route'] + '\n> ' + r['creative_required'] + '\n\n' + render_md(r) for r in results)

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        ext = "json" if args.format == "json" else "md"
        if len(results) == 1:
            p = os.path.join(args.out, "制作包_{}.{}".format(
                safe_filename(results[0]['topic']), ext))
        else:
            p = os.path.join(args.out, f"制作包合集.{ext}")
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"已写出 {p}", file=sys.stderr)
    else:
        sys.stdout.write(body)


if __name__ == "__main__":
    main()
