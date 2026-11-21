#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可重复执行的脱敏打包管线。

流程：只清空 `_release/staging/` → 按白名单复制暂存区 → 逐条脱敏改写（每条旧串
必须存在，否则报错停止）→ 生成 `requirements.txt` 与 `声明与许可边界.md` →
禁用词扫描 → 功能自检 → 打 zip。`_release/` 下的其他文件不属于清理范围。

原则：
  · 原仓库文件只读，任何改写只发生在 `_release/staging/` 里；
  · 每条改写都断言旧串存在，源文件漂移时立刻失败，不静默漏改；
  · 禁用词扫描与功能自检在脚本内执行，不通过就不生成 zip。

用法：
    python tools/pack_release.py            # 全流程
    python tools/pack_release.py --no-zip   # 只做暂存与校验
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "_release"
STAGE = RELEASE / "staging" / "短剧成片体系"
VERSION = "v1.0.0"
DATE = "2026-10-22"
ZIP_PATH = RELEASE / f"短剧成片体系-{VERSION}-{DATE}.zip"
TOP_DIR = "短剧成片体系"

# ---------------------------------------------------------------- 打包范围
ROOT_FILES = [
    "README.md",
    "AGENTS.md", "SKILL.md", "skill-manifest.json", "从这里开始.md",
    "命令速查.md", "能力登记.md", "导演视觉圣经.md",
    "技术资产_通用.md", "技术资产_H3.md", "技术资产_ComfyUI.md",
    ".gitattributes",
]
INCLUDE_DIRS = [
    "01-创意与剧本", "02-分镜与镜头", "03-角色与视觉资产", "04-视频生成",
    "05-音频", "06-后期与发布", "07-端到端管线", "模板", "tools",
]
EXCLUDE_DIR_NAMES = {
    ".git", "_归档", "__pycache__", "00-视频项目", "docs", "对标参考库",
    "archive", "档案馆", "_release", "AISHELL-3_研究样本",
}
EXCLUDE_REL_DIRS = {
    "05-音频/参考音色库/AISHELL-3_研究样本",
}
EXCLUDE_FILES = {
    "tools/pack_release.py",
    "tools/check_source_archive.py",
    # 本地草稿，含本机路径，不进入公开包
    "01-创意与剧本/本地模型剧本生成模板.md",
    "tools/dual_model_drama.py",
    "tools/hybrid_cleaner.py",
    "tools/双模型接力编剧流水线.md",
    "tools/第3棒审校清理_规则加模型三层架构.md",
}
EXCLUDE_SUFFIXES = {
    ".wav", ".mp3", ".flac", ".png", ".jpg", ".jpeg", ".webp",
    ".mp4", ".mov", ".pyc", ".zip",
}
EXCLUDE_PATTERNS = [r"^\.env$", r"^cookies.*\.txt$", r"^.*state.*\.json$"]
TEXT_SUFFIXES = {
    ".md", ".py", ".json", ".yaml", ".yml", ".txt", ".ps1", ".gitattributes",
    ".csv", ".toml", ".ini",
}

# ---------------------------------------------------------------- 改写清单
# 每条 (相对路径, 旧串, 新串)。旧串必须存在，否则整包失败。
SPEC = [
    # —— 参考项目名 ——
    ("技术资产_H3.md",
     "✅ `《千里江山》` 就是这样把 1280×736 送到 1920×1080 交付的",
     "✅ 一部 27 镜 / 120 秒的已完成单片就是这样把 1280×736 送到 1920×1080 交付的"),
    ("技术资产_H3.md",
     "《千里江山》27 镜跑通了这条路线。",
     "一部 27 镜 / 120 秒的已完成单片跑通了这条路线。"),
    ("技术资产_通用.md",
     "> 本文是《汴河浮生》四次生产中**踩出来的环境事实**。",
     "> 本文是四次生产中**踩出来的环境事实**。"),
    ("技术资产_通用.md",
     "：《千里江山》27 镜 / 120 秒 / 1080p 交付",
     "：一部 27 镜 / 120 秒 / 1080p 交付的已完成单片"),
    ("技术资产_通用.md",
     "**FZYaoTi**（方正姚体）44px `&H00C4A882` |",
     "**FZYaoTi**（方正姚体）44px `&H00C4A882`；商用需自行购买字体授权 |"),
    ("技术资产_通用.md",
     "| 采集爬虫工程 | `能力登记.md` | 含 LiblibAI / TokenGo 采集脚本与其 venv |\n", ""),
    ("技术资产_通用.md",
     "| 采集器 Skill 说明 | 采集工程内 `agent-skill/` 下 | 登录态采集模式（headful 浏览器 + 被动捕获） |\n", ""),

    # —— 豁免登记：删除片名条目，留注释示例 ——
    ("tools/_film_gate_waivers.yaml",
     """waivers:
  - project: 《千里江山》
    gates: [切点均质度-真片, 项目合规-真片, 逐秒覆盖-真片, 锚点链-真片, hook密度-真片, 风格锁-真片, 运镜结构-真片]
    reason: 2026-10-12 前立项，G0–G6 已跑通并归档资产，不回补新列
    # 依据：项目目录及其首批文件的创建时间 = 2026-10-03 20:28（该目录在
    # .gitignore 第 39 行内，无 git 记录可查）。若与实际立项日不符请改这里。
    立项日: 2026-10-03
    until: 2026-12-31""",
     """waivers: []
# 需要豁免时的示例（取消注释并填真实字段；新项目一律不得豁免）：
# waivers:
#   - project: 《示例片名》
#     gates: [切点均质度-真片, 项目合规-真片, 逐秒覆盖-真片, 锚点链-真片, hook密度-真片, 风格锁-真片, 运镜结构-真片]
#     reason: 2026-10-12 前立项，不回补新列
#     立项日: 2026-10-01
#     until: 2026-12-31"""),
    ("tools/check_hook_density.py",
     "实测《千里江山》就是这么被误判的", "实测旧结构主表就是这么被误判的"),
    ("tools/check_hook_density.py",
     "2026-10-18 修：《千里江山》曾被这样误判", "2026-10-18 修：旧结构主表曾被这样误判"),
    ("tools/check_style_lock.py",
     "（《第一次呼吸》锁 = 285 汉字 + 39 个标点 = 324",
     "（一次实测中 285 汉字 + 39 个标点 = 324"),
    ("tools/check_style_lock.py",
     "（《第一次呼吸》实测：`关键帧提示词.md` 179 字、",
     "（一次实测中：`关键帧提示词.md` 179 字、"),
    ("tools/check_shot_duration_variance.py",
     "实测代价：《协议三》13 个切点间隔", "实测代价：某旧片 13 个切点间隔"),
    ("tools/check_shot_duration_variance.py",
     "而同机器的《万象》在 12 秒生成段内", "而同机器的另一部已完成片在 12 秒生成段内"),
    ("tools/check_shot_duration_variance.py",
     "① 万象表前有信息表", "① 旧结构表前有信息表"),
    ("tools/check_shot_duration_variance.py",
     "② 万象还有 ", "② 旧结构表还有 "),
    ("tools/check_shot_duration_variance.py",
     "③ 协议三/上元灯轮的表格行", "③ 旧结构表/另一部旧片的表格行"),
    ("tools/check_shot_duration_variance.py",
     "参考：万象 G003 用 6 处 At 切点", "参考：旧片 G003 用 6 处 At 切点"),
    ("tools/check_shot_duration_variance.py",
     "（万象就是这种写法）", "（旧结构表就是这种写法）"),
    ("tools/check_project_conformance.py",
     "# 《协议三》《万象》类题材若超过 50% 镜头没动起来",
     "# 叙事类题材若超过 50% 镜头没动起来"),
    ("tools/test_project_discovery.py",
     'self.project("00-视频项目/《万象》")', 'self.project("00-视频项目/《测试片》")'),
    ("tools/check_shot_structure.py",
     "方法、数据与推导过程见 `对标参考库/优秀AI短片镜头结构实测-2026-10.md`。",
     "方法、数据与推导过程见本文件阈值注释与 `--selftest` 反例。"),
    ("tools/check_shot_structure.py",
     "**画册式短片（如《守护神》100% 静止）对本闸全部豁免",
     "**画册式短片（如一部 100% 静止仍成立的画册式短片）对本闸全部豁免"),
    ("tools/check_shot_structure.py",
     "#（方法与数据见 `对标参考库/优秀AI短片镜头结构实测-2026-10.md`，",
     "#（方法与数据见本文件阈值注释，"),
    ("05-音频/配音与音效设计.md",
     "> 佐证：《子鼠》片尾字幕列配音、作曲、声音设计、拟音、录音五个岗位",
     "> 佐证：一部获奖 AI 短片的片尾字幕列配音、作曲、声音设计、拟音、录音五个岗位"),
    ("06-后期与发布/成片与字幕.md",
     "**标杆实测（2026-10）**：《合龙》全片平均 12.2 镜/分钟",
     "**标杆实测（2026-10）**：两部实测成片——17 分钟长片全片平均 12.2 镜/分钟"),
    ("06-后期与发布/成片与字幕.md",
     "；《小白》33 镜/分钟。", "；33 镜每分钟的短片则走另一种密度。"),
    ("05-音频/参考音色库/README.md",
     "> **体系定位**：这里保存 SOP 侧的历史研究样本与许可记录，不再作为 IndexTTS 首选范例。"
     "当前主参考音放在本机 IndexTTS 项目的 `examples/wenetspeech4tts_官方参考音/`，可被 IndexTTS 直接读取；"
     "实际仓库位置以项目《能力登记.md》为准。",
     "> **体系定位**：这里保存 SOP 侧的历史研究样本与许可记录，不再作为首选范例。"
     "当前主参考音由使用者自备（例如选用 TTS 实现自带的示例参考音目录）；"
     "实际位置以项目《能力登记.md》为准。"),
    ("05-音频/参考音色库/README.md",
     "> **AISHELL-3 权威清单是子目录的 `manifest.json`**；临时采集文件不作权威。",
     "> **AISHELL-3 权威清单是子目录的 `manifest.json`**（该子目录为研究许可样本，**不随本包提供**）；临时文件不作权威。"),
    ("05-音频/参考音色库/README.md",
     "- `AISHELL-3_研究样本/`：8 条 AISHELL-3 单句 WAV（8 个不同说话人，各 1 条，5.6–8.3 秒，44.1kHz 单声道 PCM）。",
     "- `AISHELL-3_研究样本/`：8 条 AISHELL-3 单句 WAV（8 个不同说话人，各 1 条，5.6–8.3 秒，44.1kHz 单声道 PCM）。"
     "**该目录为 research_only 许可样本，不随本包提供**；下面的字段与授权说明只用于说明口径。"),
    ("05-音频/参考音色库/README.md",
     "  入库的只有 `manifest.json`（元数据+sha256，可校验本地文件完整性）与说明文档。",
     "  本文档随包提供；`manifest.json` 与 WAV 属研究样本，不在本包内。"),
    ("05-音频/背景音乐生成.md",
     "缺独立动作音效时用固定音效库或 Stable Audio。",
     "缺独立动作音效时用固定音效库或 Stable Audio，或等价能力实现。"),

    # —— 第三方来源 / 项目名 ——
    ("07-端到端管线/片型全流程.md",
     "> 本文件 2026-10-12 由《真人短剧全流程（LibTV 公式版）》与《小说漫剧全流程》合并：",
     "> 本文件 2026-10-12 由「真人短剧全流程」与「小说漫剧全流程」两份底稿合并："),
    ("07-端到端管线/片型全流程.md",
     "## 二、真人短剧全流程（LibTV 公式版）", "## 二、真人短剧全流程"),
    ("07-端到端管线/片型全流程.md",
     "> 来源：B站《LibTV保姆级教程》BV1VB3Y61E13（九儿老师课程，截图核对版）\n", ""),
    ("07-端到端管线/片型全流程.md",
     "> 原教程使用过的工具链保留为来源背景：LibTV + Seedance 2.0 / Kling可灵 / 即梦AI / 豆包AI / 哩布哩布AI。这不是本体系的选型要求，生产实现查项目能力登记。",
     "> 原教程用过的工具链只作来源背景，不构成选型要求；生产实现查项目《能力登记.md》。"),
    ("07-端到端管线/片型全流程.md",
     "（含案例：《王爷的专属试菜员》上元节街市 / 王府后墙 / 后厨）",
     "（含案例：上元节街市 / 府邸后墙 / 后厨）"),
    ("07-端到端管线/片型全流程.md",
     "来源为 2025-2026 年开源端到端管线与漫剧管线（BigBanana、Toonflow、waoowaoo、魔因漫创、智剧通、LocalMiniDrama 等）的共性实践；",
     "来源为 2025–2026 年多个开源端到端管线与漫剧管线的共性实践；"),
    ("07-端到端管线/片型全流程.md",
     "开源工业管线（BigBanana 的 Script-to-Asset-to-Keyframe）的共同结论：",
     "开源工业化管线的共同结论："),
    ("07-端到端管线/片型全流程.md",
     "LibTV 式画布已被多个开源工具（LocalMiniDrama、Toonflow）验证为长剧管理的最佳形态。",
     "画布视图已被多个开源管线验证为长剧管理的最佳形态。"),
    ("02-分镜与镜头/分镜工作流.md",
     "> 借鉴开源工业化管线（BigBanana 的 Script-to-Asset-to-Keyframe 工作流）与国际社区 2026 年共识：",
     "> 借鉴开源工业化管线的共同实践与国际社区 2026 年共识："),
    ("02-分镜与镜头/分镜工作流.md",
     "研究依据见 `对标参考库/开源短剧提示词与运动合同研究-2026-10.md`。",
     "研究依据（来源研究档不随本包提供）。"),
    ("01-创意与剧本/短剧编剧引擎.md",
     "方法借鉴开源漫剧管线（Toonflow / waoowaoo / LocalMiniDrama 的共同实践）：",
     "方法借鉴开源漫剧管线的共同实践："),
    ("06-后期与发布/成片与字幕.md",
     "部分开源管线（ArcReel、LocalMiniDrama 一类）支持把素材与粗剪时间轴**导出为剪映草稿**",
     "部分开源端到端管线支持把素材与粗剪时间轴**导出为剪映草稿**"),
    ("03-角色与视觉资产/角色一致性.md",
     "1. Curious Refuge / Tyler Smith，《The Ultimate Guide to Creating Consistent AI Characters》：先角色参考",
     "1. 公开教程一（2024–2025）：先角色参考"),
    ("03-角色与视觉资产/角色一致性.md",
     "2. Curious Refuge，《6 Easy Steps》：身份LoRA训练样本",
     "2. 公开教程二（2024–2025）：身份LoRA训练样本"),
    ("03-角色与视觉资产/角色一致性.md",
     "3. Dave Clark接受IndieWire采访（2025-05-20）：讨论使用多个参考元素控制面孔、衣服和地点",
     "3. 一篇媒体采访（2024–2025）：讨论使用多个参考元素控制面孔、衣服和地点"),
    ("03-角色与视觉资产/角色造型与写真.md",
     '它由原"超写实人像摄影大师"和"真实感人像摄影专家"两份 skill 合并而成（源文件不属于当前项目目录）。',
     "它由两份高度重叠的人像摄影方法资料合并而成（源文件不属于当前项目目录）。"),
    ("03-角色与视觉资产/角色造型与写真.md",
     '该分支由两份高度重叠的人像 skill 合并而成（历史来源：原"超写实人像摄影大师"与"真实感人像摄影专家"，源文件不属于当前项目目录）',
     "该分支由两份高度重叠的人像摄影方法资料合并而成（源文件不属于当前项目目录）"),
    ("02-分镜与镜头/导演构图库.md",
     "本库 80 种构图整理自《80种导演级专业镜头构图提示词》",
     "本库 80 种构图整理自 80 条常见导演构图范式"),
    ("导演视觉圣经.md",
     "（对标《梦华录》《清平乐》等真实古装剧的摄影质感）",
     "（对标头部古装剧的摄影质感）"),
    ("导演视觉圣经.md",
     "| 《繁花》雨夜霓虹 |", "| 雨夜霓虹（暗青底 + 霓虹红点缀） |"),
    ("03-角色与视觉资产/题材取材与角色卡.md",
     "外部 seek 数据不属于普通制作入口。", "外部参考数据不属于普通制作入口。"),

    # —— 外部参考库 / docs 断指针（正文） ——
    ("02-分镜与镜头/导演品位与理论底座.md",
     "（见 `对标参考库/开源导演技能体系研究-2026-10.md`）",
     "（方法来源研究档不随本包提供）"),
    ("02-分镜与镜头/导演品位与理论底座.md",
     "- **对照**：`对标参考库/方法论/光线设计库.md`、`导演视觉圣经.md` 照明卡。",
     "- **对照**：`导演视觉圣经.md` 照明卡。"),
    ("02-分镜与镜头/导演品位与理论底座.md",
     "见 `对标参考库/开源导演技能体系研究-2026-10.md` §3.8、§3.9。",
     "来源研究档不随本包提供；纪律本身以本节为准。"),
    ("02-分镜与镜头/机位与运镜.md",
     "（见 `对标参考库/开源导演技能体系研究-2026-10.md`）",
     "（方法来源研究档不随本包提供）"),
    ("02-分镜与镜头/机位与运镜.md",
     "详见 `对标参考库/方法论/光线设计库.md` 与 `导演视觉圣经.md` 照明卡。",
     "详见 `导演视觉圣经.md` 照明卡。"),
    ("03-角色与视觉资产/场景与道具资产.md",
     "光型和层次取法见 `对标参考库/方法论/光线设计库.md`",
     "光型和层次取法见 `导演视觉圣经.md` 照明卡"),
    ("03-角色与视觉资产/角色资产参考板.md",
     "公开方法背景见 `对标参考库/人物场景一致性公开来源.md`",
     "公开方法背景（来源记录不随本包提供）"),
    ("04-视频生成/平台提示词契约.md",
     "来源研究档：`对标参考库/生视频HUB与ComfyUI官方案例研究-2026-10.md`、`对标参考库/开源短剧提示词与运动合同研究-2026-10.md`。",
     "来源研究档不随本包提供。"),
    ("04-视频生成/平台提示词契约.md",
     "> 来源与许可证：`对标参考库/开源短剧提示词与运动合同研究-2026-10.md`。",
     "> 来源与许可证：研究档不随本包提供；许可边界见根目录 `声明与许可边界.md`。"),
    ("04-视频生成/平台提示词契约.md",
     "`02-分镜与镜头/影视视听语言速查.md`、`对标参考库/方法论/光线设计库.md`",
     "`02-分镜与镜头/影视视听语言速查.md`、`导演视觉圣经.md` 照明卡"),
    ("04-视频生成/平台提示词契约.md",
     "- 研究依据（跨平台通用做法） → `对标参考库/生视频HUB与ComfyUI官方案例研究-2026-10.md`",
     "- 研究依据（跨平台通用做法） → 来源研究档不随本包提供"),
    ("04-视频生成/平台提示词契约.md",
     "- 研究依据（演员调度 / 运动学合同） → `对标参考库/开源短剧提示词与运动合同研究-2026-10.md`",
     "- 研究依据（演员调度 / 运动学合同） → 来源研究档不随本包提供"),
    ("04-视频生成/平台提示词契约.md",
     "- 实证依据（一次 S03 A/B 实测 结论）已归纳进 `对标参考库/开源短剧提示词与运动合同研究-2026-10.md`；",
     "- 实证依据（一次 S03 A/B 实测结论）已归纳进 `02-分镜与镜头/分镜工作流.md` 与 `04-视频生成/重抽与回退决策.md`；"),
    ("04-视频生成/视频实现适配.md",
     "研究依据 → `对标参考库/生视频HUB与ComfyUI官方案例研究-2026-10.md`（每节末附\"来源\"指针，不再随机跳转）。",
     "研究依据为作者的历史研究记录，不随本包提供；每节末的\"来源\"指针仅供作者回溯。"),
    ("04-视频生成/重抽与回退决策.md",
     "> 来源：项目实测结论已归纳进 `对标参考库/开源短剧提示词与运动合同研究-2026-10.md`；本通用决策表不依赖私人项目路径。",
     "> 来源：项目实测结论已归纳进本文件；研究档不随本包提供，本通用决策表不依赖私人项目路径。"),
    ("04-视频生成/适配登记/国际模型与通用迁移.md",
     "光源层次用`对标参考库/方法论/光线设计库.md`",
     "光源层次用`导演视觉圣经.md` 照明卡"),
    ("06-后期与发布/成片与字幕.md",
     "（沿用 `对标参考库/方法论/光线设计库.md`）", "（沿用 `导演视觉圣经.md` 照明卡）"),
    ("07-端到端管线/生产证据与片型路线.md",
     "| `对标参考库/方法论/光线设计库.md`、`导演视觉圣经.md`照明卡 |",
     "| `导演视觉圣经.md` 照明卡 |"),
    ("模板/短剧项目模板/04-镜头/镜头提示词.md",
     "研究依据：`对标参考库/开源短剧提示词与运动合同研究-2026-10.md`、`04-视频生成/平台提示词契约.md` §一.9。",
     "研究依据：`04-视频生成/平台提示词契约.md` §一.9 与 `02-分镜与镜头/分镜工作流.md` §生成前运动设计闸。"),
    ("模板/短剧项目模板/06-成片/成片质检表.md",
     "研究依据见 `对标参考库/开源短剧提示词与运动合同研究-2026-10.md`、",
     "研究依据见 "),
    ("tools/check_project_conformance.py",
     "# 来源：`对标参考库/开源短剧提示词与运动合同研究-2026-10.md`、",
     "# 来源："),
    ("tools/check_project_conformance.py",
     "    来源：`对标参考库/开源短剧提示词与运动合同研究-2026-10.md`、",
     "    来源："),
    ("tools/test_project_conformance.py",
     "    来源：`对标参考库/开源短剧提示词与运动合同研究-2026-10.md`、",
     "    来源："),
    ("tools/run_all_checks.py",
     "    # （见 对标参考库/优秀AI短片镜头结构实测-2026-10.md）。",
     "    # （阈值出处见 check_shot_structure.py 的阈值注释）。"),

    # —— SKILL / AGENTS / 从这里开始 / 能力登记 / 命令速查 ——
    ("SKILL.md",
     "理解目标 → seek 检索并实际查看真实参考 → 自主立项/定风格",
     "理解目标 → 检索并实际查看真实参考 → 自主立项/定风格"),
    ("SKILL.md",
     "**内部实现**（脚本保留用于维护和回归，不为普通 Agent 暴露为入口）：`对标参考库/提示词库/` 下的",
     "**内部实现**（历史维护资料，**不随本包提供**，不为普通 Agent 暴露为入口）：原内部提示词库的"),
    ("SKILL.md",
     "；素材定位统一由内部 `lib_locator.py` 完成。实现清单、限制与验证记录见 `能力登记.md`。",
     "；素材定位由内部 `lib_locator.py` 完成。实现清单、限制与验证记录见 `能力登记.md`。"),
    ("SKILL.md",
     "历史完整说明和旧签核流程保存在 `docs/经验保全/2026-10-03/原文/01-创意与剧本/AI短片全链路流水线.md`，仅供追溯，不作为当前指令。",
     "历史完整说明和旧签核流程不随本包提供，仅供追溯，不作为当前指令。"),
    ("SKILL.md",
     "| 选题、对标、回本、产能（**连载 / 商用才做**，单片默认跳过） | `docs/连载运营/立项对标拆解.md` |",
     "| 选题、对标、回本、产能（**连载 / 商用才做**，单片默认跳过） | 连载/商用立项对标方法论（不随本包提供） |"),
    ("SKILL.md",
     "| 成片像翻页、静止镜头过多、硬切对不上、生成段整段接进成片 | `AGENTS.md`「成片生成裁决」+ `对标参考库/优秀AI短片镜头结构实测-2026-10.md` + `tools/check_shot_structure.py` + `tools/check_assembly_usage.py` |",
     "| 成片像翻页、静止镜头过多、硬切对不上、生成段整段接进成片 | `AGENTS.md`「成片生成裁决」+ `tools/check_shot_structure.py` + `tools/check_assembly_usage.py` |"),
    ("SKILL.md",
     "| 光源层次、方向、阴影和变化理由 | `对标参考库/方法论/光线设计库.md` |",
     "| 光源层次、方向、阴影和变化理由 | `导演视觉圣经.md` 照明卡 |"),
    ("SKILL.md",
     "| 首集数据、连载放行与止损 | `docs/连载运营/首集验证与止损.md` |",
     "| 首集数据、连载放行与止损 | 连载首集验证方法论（不随本包提供） |"),
    ("SKILL.md",
     "文档责任边界、来源分级、历史经验保留和去耦检查见 `docs/知识库维护清单.md`。",
     "文档责任边界、来源分级与去耦检查以本文件与 `AGENTS.md` 的规则为准。"),
    ("AGENTS.md",
     "（`docs/连载运营/立项对标拆解.md`）", "（连载/商用立项对标方法论不随本包提供）"),
    ("AGENTS.md",
     "按 `docs/连载运营/首集验证与止损.md` 做 24h/72h 首集验证",
     "按连载首集验证方法论（不随本包提供）做 24h/72h 首集验证"),
    ("AGENTS.md",
     "详见 `docs/经验保全/跨镜身份一致性事故档案-2026-10.md`（展开版复盘，2026-10-12 由 `07-端到端管线/` 移入；核心代价已写在本节，目检依据不依赖外链）。",
     "（展开版复盘不随本包提供；核心代价已写在本节，目检依据不依赖外链）。"),
    ("AGENTS.md",
     "跨项目访问只能经环境变量显式指定（如 `AI_SEEK_ROOT` / `AI_SHORTDRAMA_HOME`），且不设时体系必须独立运行。",
     "外部参考库为可选组件，未随本包提供；如另行接入，跨项目访问只能经环境变量显式指定（如 `AI_SEEK_ROOT`），且不设时体系必须独立运行。"),
    ("从这里开始.md",
     "；连载/商用立项对标（对标/回本）见 `docs/连载运营/立项对标拆解.md`",
     "；连载/商用立项对标方法论（对标/回本）不随本包提供"),
    ("从这里开始.md",
     "；连载型首集验证与止损见 `docs/连载运营/首集验证与止损.md`",
     "；连载型首集验证与止损方法论不随本包提供"),
    ("从这里开始.md",
     "`对标参考库/` 只作为体系内部的方法论与历史研究档案，不是风格模板。",
     "外部参考库为可选组件，本包不含；它只作为方法论与历史研究档案，不是风格模板。"),
    ("从这里开始.md",
     "职责与维护边界见 `docs/知识库维护清单.md`（体系维护元文档，做片时不需要加载）。",
     "维护元文档不随本包提供；做片时不需要加载。"),
    ("从这里开始.md",
     "Agent 根据需求、剧本、导演视觉圣经和当前项目资产自主形成风格；体系不默认读取外部 seek 库，也不把外部样片当作风格模板。若维护者明确需要维护外部采集项目，使用 `AI_SEEK_ROOT` 显式指定其根目录，并在独立项目内执行维护命令。",
     "Agent 根据需求、剧本、导演视觉圣经和当前项目资产自主形成风格；外部参考库为可选组件，未随本包提供，体系不依赖它，也不把外部样片当作风格模板。"),
    ("从这里开始.md",
     "外部源档案核验（显式传根目录，项目不保存绝对路径）：\n\n```powershell\npython tools/check_source_archive.py --root \"<源档案目录>\"\n```\n\n",
     ""),
    ("从这里开始.md",
     "素材增长后跑一次数字一致性检查（磁盘为唯一真值）：",
     "> 改完文档后跑一次数字一致性检查（磁盘为唯一真值）："),
    ("能力登记.md",
     "外部参考库是独立数据项目，不属于短剧体系能力登记。它自行维护采集器、登录态、下载、清洗、索引与采集侧自检；短剧生产不默认读取它，也不由 `tools/run_all_checks.py` 验证。",
     "外部参考库为可选独立数据项目，未随本包提供；短剧生产不默认读取它，本体系不依赖它，也不由 `tools/run_all_checks.py` 验证。"),
    ("能力登记.md",
     "只有维护者明确设置 `AI_SEEK_ROOT` 时，才可运行外部参考维护脚本；这不构成普通做片入口。",
     "外部参考维护脚本属可选组件，未随本包提供，不构成普通做片入口。"),
    ("能力登记.md", "「敦煌飞天 复仇」", "「江南书生夜雨」"),
    ("命令速查.md",
     "> `seek库` 已迁出体系，只有维护者显式配置 `AI_SEEK_ROOT` 后才可运行独立维护脚本。",
     "> 外部参考库为可选组件，未随本包提供；本体系独立运行。"),
    ("命令速查.md",
     "| 外部 seek 维护库路径诊断（可选） | `AI_SEEK_ROOT=... python 对标参考库/提示词库/lib_locator.py` |\n",
     ""),
    ("命令速查.md",
     "`seek库` 已位于体系外，是独立知识采集项目。短剧生产默认不读取它，也不把它作为风格或审美依据；确需维护采集项目时，在外部项目目录按其 README 操作，并显式设置 `AI_SEEK_ROOT`。",
     "外部参考库为可选组件，未随本包提供。短剧生产不读取它，也不把它作为风格或审美依据；本体系独立运行。"),
    ("命令速查.md",
     "| 外部参考维护诊断（维护者专用） | 先设置 `AI_SEEK_ROOT`，再运行 `python tools/select_reference.py check` |\n",
     ""),
    ("命令速查.md",
     "（见 `对标参考库/优秀AI短片镜头结构实测-2026-10.md`）。",
     "（阈值出处见 `tools/check_shot_structure.py` 的阈值注释）。"),
    ("命令速查.md",
     "| 演员调度 / 运动学合同 9 项研究档 | `对标参考库/开源短剧提示词与运动合同研究-2026-10.md` |\n", ""),
    ("命令速查.md",
     "| 跨平台通用导演方法研究档 | `对标参考库/生视频HUB与ComfyUI官方案例研究-2026-10.md` |\n", ""),
    ("模板/短剧项目模板/00-立项/对标拆解表.md",
     "> 方法论见 `docs/连载运营/立项对标拆解.md`（连载 / 商用才做，单片默认跳过）；",
     "> 方法论不随本包提供（连载 / 商用才做，单片默认跳过）；"),
    ("模板/短剧项目模板/00-立项/立项决策表.md",
     "## 对标拆解（立项前必填，方法论见 `docs/连载运营/立项对标拆解.md`）",
     "## 对标拆解（立项前必填；方法论不随本包提供）"),
    ("模板/短剧项目模板/00-立项/立项决策表.md",
     "## 回本测算（立项闸门，方法论见 `docs/连载运营/立项对标拆解.md` §5）",
     "## 回本测算（立项闸门；方法论不随本包提供）"),
    ("模板/短剧项目模板/06-成片/发布包.md",
     "判定线参考 `docs/连载运营/首集验证与止损.md`",
     "判定线方法论不随本包提供"),
    ("模板/短剧项目模板/06-成片/复盘一页.md",
     "## 首集验证结论（连载型必填，方法论见 `docs/连载运营/首集验证与止损.md`）",
     "## 首集验证结论（连载型必填；方法论不随本包提供）"),

    # —— 平台与实现资料 ——
    ("04-视频生成/适配登记/H3与即梦语法.md",
     "### 3.7 官方示例（T2VA，雨中古风女子）\n",
     "### 3.7 官方示例（T2VA，雨中古风女子）\n\n"
     "> 来源：MiniMax-H3 官方仓库 h3-prompt-writing 文档（2026-10 核验），引用仅作兼容性说明。\n"),
    ("04-视频生成/ComfyUI官方视频工作流速查.md",
     "description: LiblibAI 官方维护的 118 个 ComfyUI 视频工作流模板速查（文生视频/图生视频/首尾帧/视频重绘/角色替换/姿态迁移等），含选型决策树、模型依赖、默认参数与导入方法。",
     "description: 118 个 ComfyUI 官方视频工作流模板的索引与获取入口（文生视频/图生视频/首尾帧/视频重绘/角色替换/姿态迁移等），含选型决策树、模型依赖、默认参数与导入方法。本包只提供索引，不随附模板 JSON。"),
    ("04-视频生成/ComfyUI官方视频工作流速查.md",
     "**本文件解决的是**：本地 ComfyUI 跑视频时，**用哪个现成工作流**。118 个官方模板已全部下载为可直接导入的 JSON，实际可用模板的位置与版本以项目《能力登记.md》为准；外部采集库不属于制作 Agent 的默认输入。",
     "**本文件解决的是**：本地 ComfyUI 跑视频时，**用哪个现成工作流**。本文件提供官方模板索引与获取入口，不随附模板 JSON；实际可用模板的位置与版本以项目《能力登记.md》为准。"),
    ("04-视频生成/ComfyUI官方视频工作流速查.md",
     "官方 118 个模板覆盖了绝大多数形态，直接导入改提示词即可。",
     "官方 118 个模板覆盖了绝大多数形态，按索引取得模板后直接改提示词即可。"),
    ("04-视频生成/ComfyUI官方视频工作流速查.md",
     "**采集说明**：118 个模板来自 LiblibAI 官方 ComfyUI 工作流库，采集时间 2026-09-30。\n本目录只保留可直接使用的产出物（workflow JSON + 清单）；采集与整理脚本属于素材库侧的维护工具，不随体系分发。需要更新模板时重新采集后覆盖本目录即可。",
     "**获取说明**：118 个模板来自官方 ComfyUI 工作流库（索引核验 2026-09-30）。本包只提供索引与获取入口，不随附 workflow JSON；需要模板时从官方来源取得，并按项目《能力登记.md》登记版本与参数。"),
    ("04-视频生成/视频实现适配.md",
     "## 0B. 本机能力（项目环境硬事实，不是供应商规格）\n\n> **不得假定**：本节只列**当前本机已经具备**的能力与**已安装**的模型/节点。未列入的能力在 SOP 中视为不可用，需走升级规则（§0C）。",
     "## 0B. 本机能力（作者实测环境记录，买家需按自己环境重新登记；不是供应商规格）\n\n> **不得假定**：本节只列**作者实测环境中已经具备**的能力与**已安装**的模型/节点，是记录，不是承诺。买家必须按自己环境重新登记后才可据此判断可用性；未列入的能力在 SOP 中视为不可用，需走升级规则（§0C）。"),
    ("04-视频生成/适配登记/国际模型与通用迁移.md",
     "**本机仅 H3 + Wan2.2 5B 已就绪**；",
     "**作者实测环境仅 H3 + Wan2.2 5B 已就绪（买家需按自己环境重新登记）**；"),

    # —— 路径与商标杂项 ——
    ("tools/audio_noise_diag.py",
     r"    E:\\AI\\ComfyUI\\.venv\\Scripts\\python.exe   （此处为说明，勿写进代码）",
     "    本机任意带 numpy 的 Python 3.10+ 解释器   （此处为说明，勿写进代码）"),
    ("tools/wan22_test.py",
     '"""Wan 2.2 TI2V-5B 实测脚本（直接走 ComfyUI HTTP API，不依赖 MCP）。',
     '"""Wan 2.2 TI2V-5B 实测脚本（开发/实测脚本，非生产入口；直接走 ComfyUI HTTP API，不依赖 MCP）。'),
    ("tools/wan22_test.py",
     '    python run_wan.py --preset draft      # 草稿档 832x480 / 81帧\n'
     '    python run_wan.py --preset final      # 正式档 1280x704 / 121帧\n'
     '    python run_wan.py --preset draft --no-lora   # 不用 Turbo LoRA（20步对照）',
     '    python wan22_test.py --preset draft      # 草稿档 832x480 / 81帧\n'
     '    python wan22_test.py --preset final      # 正式档 1280x704 / 121帧\n'
     '    python wan22_test.py --preset draft --no-lora   # 不用 Turbo LoRA（20步对照）'),
    ("tools/wan22_test.py",
     'HOST = "http://127.0.0.1:8188"',
     'HOST = os.environ.get("COMFYUI_HOST", "http://127.0.0.1:8188")'),
    ("tools/subtitle_burn.py",
     '    exe = shutil.which("ffmpeg")\n    if exe:\n        return exe',
     '    for name in ("ffmpeg", "ffmpeg.exe"):\n        exe = shutil.which(name)\n        if exe:\n            return exe'),
    ("tools/subtitle_burn.py",
     '    ffprobe = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe")\n    if not os.path.isfile(ffprobe):\n        return None',
     '    stem = os.path.splitext(ffmpeg)[0]\n    ffprobe = None\n    for cand in (stem + ".exe", stem):\n        if os.path.isfile(cand) and os.path.basename(cand).startswith("ffprobe"):\n            ffprobe = cand\n            break\n    if not ffprobe:\n        return None'),

    ("tools/check_shot_structure.py",
     "# 叙事片静止机位占比硬线：实测最高 43.1%（山海经），超过 50% 退出码 1。",
     "# 叙事片静止机位占比硬线：实测最高 43.1%，超过 50% 退出码 1。"),
    ("tools/selfcheck_system.py",
     r"于是「制作包.json 里写死了 E:\AI\...」这种违规，",
     "于是「制作包.json 里写死了绝对盘符路径」这种违规，"),
    ("tools/selfcheck_system.py",
     r"那会让 `cover=E:\x` 溜过去。",
     r"那会让 `cover=<盘符>:\x` 溜过去。"),
    ("01-创意与剧本/题材风格与平台库.md",
     "立项前用 `docs/连载运营/立项对标拆解.md` 按目标平台当期榜单验证",
     "立项前按目标平台当期榜单验证"),
    ("01-创意与剧本/题材风格与平台库.md",
     "请以 `docs/连载运营/立项对标拆解.md` 的当期采集为准",
     "请以公开榜单的当期数据为准"),
    ("tools/validate_system.py",
     "# 归档（_归档/、docs/）与私人项目（00-视频项目/）不在此列",
     "# 归档目录与私人项目（00-视频项目/）不在此列"),
    ("03-角色与视觉资产/角色一致性.md",
     "（来源链接见`对标参考库/人物场景一致性公开来源.md`）",
     "（来源链接不随本包提供）"),
    ("03-角色与视觉资产/角色一致性.md",
     "（来源链接见上述来源记录）", "（来源链接不随本包提供）"),
    ("07-端到端管线/片型全流程.md",
     "> 本版公式均与视频截图逐字核对，可直接复制使用",
     "> 本版公式已与原始示例逐条核对，可直接复制使用"),
    ("05-音频/参考音色库/README.md",
     "- 两套样本都仅用于本地研究与试听比较，不是商业成品音色库。",
     "- 两类参考音都仅用于本地研究与试听比较，不是商业成品音色库。"),
    # —— validate_system：断言依赖清理 ——
    ("tools/validate_system.py",
     "EXCLUDED_DIRS = {'.git', 'docs', '短剧导演台', '00-视频项目', '_归档',\n                 '_release', 'archive', '.superpowers'}",
     "EXCLUDED_DIRS = {'.git', 'docs', '00-视频项目', '_归档',\n                 '_release', 'archive', '.superpowers'}"),
    ("tools/validate_system.py",
     "# seek库＝挂载的数据项目（见 对标参考库/00_总览.md），其内部文档自带外部\n"
     "# 链接、绝对路径与远端文件名，不是本体系的运行时 SOP；与 对标参考库/ 同级",
     "# 外部参考库＝可选挂载的数据项目（不随本包提供），其内部文档自带外部\n"
     "# 链接、绝对路径与远端文件名，不是本体系的运行时 SOP；与外部参考库同级"),
    ("tools/validate_system.py",
     " '03-角色与视觉资产/场景与道具资产.md','docs/知识库维护清单.md',\n"
     " '模板/短剧项目模板/项目状态摘要.md','tools/check_source_archive.py',",
     " '03-角色与视觉资产/场景与道具资产.md',\n"
     " '模板/短剧项目模板/项目状态摘要.md',"),
    ("tools/validate_system.py",
     "    for forbidden in ['TokenGo','平台 API','供应商线路','登录态','登录资料',",
     "    for forbidden in ['平台 API','供应商线路','登录态','登录资料',"),
    ("tools/validate_system.py",
     "if (ROOT/'短剧导演台').exists(): errors.append('source directory 短剧导演台 must be removed')\n\n", ""),
    ("tools/validate_system.py",
     "\nfor doc in runtime_docs:\n    if doc.exists() and '短剧导演台/' in doc.read_text(encoding='utf-8'):\n        errors.append(f'{doc.relative_to(ROOT)}: runtime dependency references source directory')\n", "\n"),
    ("tools/run_all_checks.py",
     '    ex = os.path.join(SYSTEM_ROOT, "对标参考库", "提示词库", "示例")\n'
     '    if not os.path.isdir(ex):\n'
     '        return False, "示例目录不存在"',
     '    ex = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库", "示例")\n'
     '    if not os.path.isdir(ex):\n'
     '        return True, "外部参考库未随包提供（样例新鲜度闸 N/A）"'),
    ("tools/run_all_checks.py",
     '    _p = os.path.join(SYSTEM_ROOT, "对标参考库", "提示词库")\n'
     '    if _p not in sys.path:\n'
     '        sys.path.insert(0, _p)\n'
     '    import lib_locator',
     '    _p = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库")\n'
     '    if _p not in sys.path:\n'
     '        sys.path.insert(0, _p)\n'
     '    try:\n'
     '        import lib_locator\n'
     '    except ImportError:\n'
     '        return True, "外部参考库未随包提供（闸的自检 N/A）"'),
    ("tools/run_all_checks.py",
     '            msg = "未找到（外部 seek 维护闸需显式设置 AI_SEEK_ROOT）" \\\n'
     '                if "素材库" in name else "未找到"',
     '            msg = "未找到（外部参考库未随包提供）" \\\n'
     '                if "素材库" in name else "未找到"'),
    ("tools/run_all_checks.py",
     '            ignore=shutil.ignore_patterns(\n'
     '                "*.mp4", "*.png", "*.jpg", "*.jpeg", "*.webp",\n'
     '                "*.wav", "*.mp3", "*.flac",\n'
     '                "__pycache__", ".git", "00-视频项目", "_归档", "seek库"))',
     '            ignore=shutil.ignore_patterns(\n'
     '                "*.mp4", "*.png", "*.jpg", "*.jpeg", "*.webp",\n'
     '                "*.wav", "*.mp3", "*.flac",\n'
     '                "__pycache__", ".git", "00-视频项目", "_归档", "外部参考库"))'),
    ("tools/check_doc_numbers.py",
     'LIB = os.path.join(SYSTEM_ROOT, "对标参考库")\n'
     '# 外部素材库只在显式设置 AI_SEEK_ROOT 时参与维护性统计。\n'
     'sys.path.insert(0, os.path.join(SYSTEM_ROOT, "对标参考库", "提示词库"))\n'
     'import lib_locator  # noqa: E402',
     'LIB = os.path.join(SYSTEM_ROOT, "外部参考库")\n'
     '# 外部素材库只在显式设置 AI_SEEK_ROOT 时参与维护性统计；未随包提供时只查文档数字与闸表。\n'
     'sys.path.insert(0, os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库"))\n'
     'try:\n'
     '    import lib_locator  # noqa: E402\n'
     'except ImportError:  # 外部参考库为可选组件，未随包提供\n'
     '    lib_locator = None'),
    ("tools/check_doc_numbers.py",
     "# 只跳过「素材数据」子目录（重、不含文档），**不能**跳过 对标参考库 整个目录——\n"
     "# 总览 00_总览.md 就在里面，恰恰是最需要被检查的。\n"
     "# seek库 是采集工程，里面的 .md 同样不是体系文档（它有自己的索引与日志）。",
     "# 只跳过「素材数据」子目录（重、不含文档），**不能**跳过 外部参考库 整个目录——\n"
     "# 总览 00_总览.md 就在里面，恰恰是最需要被检查的。\n"
     "# 外部参考库是可选数据项目，里面的 .md 同样不是体系文档（它有自己的索引与日志）。"),
    ("tools/check_doc_numbers.py",
     '    truth = {"external_available": False, "prompts": 0, "records": 0,\n'
     '             "tech": 0, "covers": 0, "videos": 0, "stills": 0}\n'
     '    lib_root = lib_locator.lib_root()',
     '    truth = {"external_available": False, "prompts": 0, "records": 0,\n'
     '             "tech": 0, "covers": 0, "videos": 0, "stills": 0}\n'
     '    if lib_locator is None:\n'
     '        return truth\n'
     '    lib_root = lib_locator.lib_root()'),
    ("tools/check_prompt_quality.py",
     'LIB = os.path.join(SYSTEM_ROOT, "对标参考库", "提示词库")\n'
     'sys.path.insert(0, LIB)\n'
     'import lib_locator  # noqa: E402',
     'LIB = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库")\n'
     'sys.path.insert(0, LIB)\n'
     'try:\n'
     '    import lib_locator  # noqa: E402\n'
     'except ImportError:  # 外部参考库为可选组件，未随包提供\n'
     '    lib_locator = None'),
    ("tools/check_prompt_quality.py",
     '    if not os.path.exists(PIPE):\n'
     '        print("✗ 找不到 {}".format(PIPE), file=sys.stderr)\n'
     '        return 1',
     '    if lib_locator is None or not os.path.exists(PIPE):\n'
     '        print("外部参考库未随包提供，语料质量闸不适用（N/A）。")\n'
     '        return 0'),
    ("tools/check_prompt_quality.py",
     "'敦煌飞天 复仇'", "'江南书生夜雨'"),
    ("tools/check_security_perf.py",
     'LIB = os.path.join(SYSTEM_ROOT, "对标参考库", "提示词库")',
     'LIB = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库")'),
    ("tools/check_security_perf.py",
     '"敦煌飞天 复仇"', '"江南书生夜雨"'),
    ("tools/check_asset_alignment.py",
     'LIB = os.path.join(SYSTEM_ROOT, "对标参考库", "提示词库")\n'
     'sys.path.insert(0, LIB)\n'
     'import lib_locator  # noqa: E402',
     'LIB = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库")\n'
     'sys.path.insert(0, LIB)\n'
     'try:\n'
     '    import lib_locator  # noqa: E402\n'
     'except ImportError:  # 外部参考库为可选组件，未随包提供\n'
     '    lib_locator = None'),
    ("tools/check_asset_alignment.py",
     '    raw = lib_locator.lib_root()',
     '    raw = lib_locator.lib_root() if lib_locator is not None else None'),
    ("tools/selfcheck_system.py",
     'LIB = os.path.join(SYSTEM_ROOT, "对标参考库", "提示词库")\n'
     'sys.path.insert(0, LIB)\n'
     'import lib_locator  # noqa: E402',
     'LIB = os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库")\n'
     'sys.path.insert(0, LIB)\n'
     'try:\n'
     '    import lib_locator  # noqa: E402\n'
     'except ImportError:  # 外部参考库为可选组件，未随包提供\n'
     '    lib_locator = None'),
    ("tools/selfcheck_system.py",
     '    checks = []\n    tmp = tempfile.mkdtemp(prefix="sysport_")',
     '    if lib_locator is None or not os.path.isdir(LIB):\n'
     '        print("外部参考库未随包提供，本闸不适用（N/A）；体系其余闸不受影响。")\n'
     '        return 0\n\n'
     '    checks = []\n    tmp = tempfile.mkdtemp(prefix="sysport_")'),
    ("tools/find_style.py",
     'sys.path.insert(0, os.path.join(SYSTEM_ROOT, "对标参考库", "提示词库"))\n'
     'import lib_locator  # noqa: E402',
     'sys.path.insert(0, os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库"))\n'
     'try:\n'
     '    import lib_locator  # noqa: E402\n'
     'except ImportError:  # 外部参考库为可选组件，未随包提供\n'
     '    lib_locator = None'),
    ("tools/find_style.py",
     '    root = lib_locator.seek_root()',
     '    root = lib_locator.seek_root() if lib_locator is not None else None'),
    ("tools/test_pipeline_edge.py",
     'TMP = os.environ.get(\'TEMP\', \'.\')',
     'TMP = os.environ.get(\'TEMP\', \'.\')\n\n'
     'if not os.path.isdir(LIB):\n'
     '    print(\'外部参考库未随包提供，流水线边界测试不适用（N/A）。\')\n'
     '    raise SystemExit(0)'),
    ("tools/test_pipeline_edge.py", "'敦煌'", "'江南'"),
    ("tools/test_select_reference.py",
     'ROOT = os.path.abspath(os.path.join(HERE, ".."))',
     'ROOT = os.path.abspath(os.path.join(HERE, ".."))\n'
     'EXTERNAL_LIB = os.path.join(ROOT, "外部参考库", "提示词库")'),
    ("tools/test_select_reference.py",
     '{"prompt": "敦煌飞天", "negativePrompt": ""', '{"prompt": "江南书生夜雨图", "negativePrompt": ""'),
    ("tools/test_select_reference.py",
     'run_cli(["prompt", "敦煌", "--top", "1", "--format", "json"], self.env)',
     'run_cli(["prompt", "江南", "--top", "1", "--format", "json"], self.env)'),
    ("tools/test_select_reference.py",
     'run_cli(["prompt", "敦煌", "--type", "Checkpoint"], self.env)',
     'run_cli(["prompt", "江南", "--type", "Checkpoint"], self.env)'),
    ("tools/test_select_reference.py",
     'if __name__ == "__main__":\n    unittest.main()',
     'if __name__ == "__main__":\n'
     '    if not os.path.isdir(EXTERNAL_LIB):\n'
     '        print("外部参考库未随包提供，参考查询入口测试不适用（N/A）。")\n'
     '        raise SystemExit(0)\n'
     '    unittest.main()'),
    (".gitattributes",
     '# Preserve exact source snapshots, including original line endings.\n'
     '"docs/经验保全/**/原文/**" -text\n',
     '# Preserve exact source snapshots, including original line endings.\n'),
]

# 全局替换：旧串 → 新串；min_total 为全暂存区最少命中总数（防源文件漂移）
TOKENS = [
    ("繁花系", "光影叙事系", 8),
    ("`对标参考库/开源短剧提示词与运动合同研究-2026-10.md`", "（研究档不随本包提供）", 0),
    ("`对标参考库/开源导演技能体系研究-2026-10.md`", "（研究档不随本包提供）", 0),
    ("`对标参考库/生视频HUB与ComfyUI官方案例研究-2026-10.md`", "（研究档不随本包提供）", 0),
    ("`对标参考库/优秀AI短片镜头结构实测-2026-10.md`", "（实测记录不随本包提供）", 0),
    ("`对标参考库/人物场景一致性公开来源.md`", "（来源记录不随本包提供）", 0),
    ("`对标参考库/方法论/光线设计库.md`", "`导演视觉圣经.md` 照明卡", 0),
    ("对标参考库", "外部参考库", 1),
    ("seek库", "外部参考库", 1),
    ("AI_SHORTDRAMA_HOME", "", 0),
    ("繁花", "光影叙事", 0),
    ("敦煌飞天 复仇", "江南书生夜雨", 0),
]

# 禁用词（大小写不敏感）；命中必须为 0
FORBIDDEN = [
    "千里江山", "第一次呼吸", "离谱日常", "万象", "协议三", "汴河浮生",
    "王爷的专属试菜员", "备份母亲", "合龙", "子鼠", "守护神", "梦华录",
    "清平乐", "繁花", "LibTV", "九儿", "BigBanana", "Toonflow", "waoowaoo",
    "LocalMiniDrama", "ArcReel", "魔因漫创", "智剧通", "Curious Refuge",
    "Tyler Smith", "Dave Clark", "seek库", "短剧导演台", "TokenGo", "wxb",
    "E:\\", "E:/AI", "C:\\Users", "D:\\Qwenclaw", "BV1", "敦煌飞天",
    "对标参考库",
]
# 作为题材词合法保留的禁用词（逐条人工判断后登记）
ALLOWED_CONTEXT = {
    "山海经": {"02-分镜与镜头/分镜工作流.md", "03-角色与视觉资产/题材取材与角色卡.md"},
}


def log(msg):
    print(msg, flush=True)


def fail(msg):
    print("FAIL: " + msg, flush=True)
    raise SystemExit(1)


def is_excluded_file(rel):
    name = Path(rel).name
    for pat in EXCLUDE_PATTERNS:
        if re.match(pat, name):
            return True
    return False


def collect_sources():
    """按白名单产出 (源路径, 相对路径)。"""
    out = []
    for f in ROOT_FILES:
        p = ROOT / f
        if not p.is_file():
            fail("白名单文件缺失：" + f)
        out.append((p, f))
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            fail("白名单目录缺失：" + d)
        for dirpath, dirnames, filenames in os.walk(base):
            cur = Path(dirpath)
            rel_dir = cur.relative_to(ROOT).as_posix()
            dirnames[:] = sorted(
                x for x in dirnames
                if x not in EXCLUDE_DIR_NAMES
                and f"{rel_dir}/{x}" not in EXCLUDE_REL_DIRS
            )
            for fn in sorted(filenames):
                p = cur / fn
                rel = p.relative_to(ROOT).as_posix()
                if rel in EXCLUDE_FILES or is_excluded_file(rel):
                    continue
                if p.suffix.lower() in EXCLUDE_SUFFIXES:
                    continue
                out.append((p, rel))
    return out


def stage_files(sources):
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    for src, rel in sources:
        dst = STAGE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def read_text(path):
    return path.read_text(encoding="utf-8")


def write_text(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")


def apply_spec():
    """逐条改写；旧串不存在即报错（防源文件漂移后静默漏改）。"""
    cache = {}
    applied = {}
    for rel, old, new in SPEC:
        p = STAGE / rel
        if not p.exists():
            fail(f"改写目标不在暂存区：{rel}")
        if rel not in cache:
            cache[rel] = read_text(p)
        text = cache[rel]
        if old not in text:
            fail(f"旧串不存在（源文件可能已漂移）：{rel} :: {old[:60]!r}")
        text = text.replace(old, new)
        cache[rel] = text
        applied[rel] = applied.get(rel, 0) + 1
    for rel, text in cache.items():
        write_text(STAGE / rel, text)
    return applied


def apply_tokens():
    """全局 token 替换，只处理文本文件。"""
    applied = {}
    totals = {old: 0 for old, _n, _m in TOKENS}
    for p in sorted(STAGE.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = p.relative_to(STAGE).as_posix()
        text = read_text(p)
        orig = text
        for old, new, _min in TOKENS:
            n = text.count(old)
            if n:
                text = text.replace(old, new)
                totals[old] += n
                applied[rel] = applied.get(rel, 0) + n
        if text != orig:
            write_text(p, text)
    for old, _new, min_total in TOKENS:
        if totals[old] < min_total:
            fail(f"全局 token 命中不足：{old!r} 期望≥{min_total}，实际 {totals[old]}")
    return applied, totals


def fix_manifest():
    """skill-manifest.json：去掉指向不随包内容的路由，并校验 JSON 合法。"""
    p = STAGE / "skill-manifest.json"
    data = json.loads(read_text(p))
    loading = data.get("loading", {})
    old = loading.get("on_demand_only", "")
    want = "研究档、适配资料、历史项目与归档不默认加载，由路由按需引入；默认加载集只含轻量入口"
    if "对标参考库" not in old and "外部参考库" not in old:
        fail("skill-manifest.json on_demand_only 未按预期包含研究档说明")
    loading["on_demand_only"] = want
    data["loading"] = loading
    write_text(p, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    # 独立复验：JSON 合法 + 关键字段仍在
    reloaded = json.loads(read_text(p))
    for key in ("schema_version", "name", "entry", "protocol", "gates"):
        if key not in reloaded:
            fail("skill-manifest.json 改写后缺字段：" + key)
    subprocess.run([sys.executable, "-m", "json.tool", str(p)],
                   check=True, stdout=subprocess.DEVNULL)


def write_extras():
    """生成 requirements.txt 与 声明与许可边界.md。"""
    req = """# 仅供 tools/ 下的检查闸使用；体系文档本身不依赖任何第三方库。
# 安装：pip install -r requirements.txt
PyYAML>=6.0
numpy>=1.24
"""
    write_text(STAGE / "requirements.txt", req)

    notice = """# 声明与许可边界

## 商标与平台名称

文中出现的平台与模型名称（包括但不限于 MiniMax、Seedance、即梦、Kling、Veo、
Runway、Luma、ComfyUI 等）均为各自权利人的商标或产品名称，仅用于兼容性说明与
方法描述，不表示任何形式的合作、授权或背书。具体字段、参数、额度与许可条款以
各平台官方文档为准。

## 硬件与环境记录

`技术资产_通用.md`、`技术资产_H3.md`、`技术资产_ComfyUI.md`、`能力登记.md` 以及各适配资料中的硬件型号、地址示例、机时数字、
分辨率与耗时，均为作者本人在特定环境下的实测记录，不是对买家环境的承诺或规格
保证。买家必须按自己的硬件、软件版本与账号条件重新登记并实测后再排产。

## 第三方语料与音频

本包不包含任何第三方抓取语料、第三方研究许可音频或研究样本文件。
`05-音频/参考音色库/` 仅提供索引与授权说明文档，其中的研究样本目录不随包分发；
正式项目使用参考音时必须自行取得书面授权，并登记进项目《素材与授权台账.md》。

## 外部参考库

原体系中可选的外部参考库（独立数据项目）不随本包提供。依赖它的维护闸在未配置
时会显式打印 `N/A` 并跳过，这不影响体系本身的运行与成片流程。

## 字体

文中提到的中文字体（如方正系列）仅说明可用的字体类型。商用前必须自行购买或取得
相应字体授权，本包不附带任何字体文件。
"""
    write_text(STAGE / "声明与许可边界.md", notice)


def scan_forbidden():
    hits = {}
    for p in sorted(STAGE.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = p.relative_to(STAGE).as_posix()
        text = read_text(p)
        low = text.lower()
        for w in FORBIDDEN:
            n = low.count(w.lower())
            if n:
                hits.setdefault(w, []).append((rel, n))
    # 山海经：仅允许作为题材词出现在登记文件里
    for p in sorted(STAGE.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = p.relative_to(STAGE).as_posix()
        n = read_text(p).count("山海经")
        if n:
            if rel not in ALLOWED_CONTEXT["山海经"]:
                hits.setdefault("山海经", []).append((rel, n))
            else:
                log(f"  允许保留：山海经 作为题材词出现在 {rel}（{n} 处，已人工确认）")
    return hits


def check_docs_paths():
    """docs/ 只允许出现在第三方 URL 里。"""
    bad = []
    for p in sorted(STAGE.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = p.relative_to(STAGE).as_posix()
        for i, line in enumerate(read_text(p).splitlines(), 1):
            if "docs/" not in line:
                continue
            if re.search(r"(?:[A-Za-z0-9.-]+\.(?:com|io|org|ai|dev|net)|://)[^\s]*docs/", line):
                continue
            bad.append(f"{rel}:{i}: {line.strip()[:90]}")
    return bad


def run_cmd(args, cwd=None):
    p = subprocess.run(args, cwd=str(cwd or STAGE), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=900)
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


def verify_runtime():
    checks = [
        ("结构校验 validate_system", [sys.executable, "tools/validate_system.py"]),
        ("hook密度 selftest", [sys.executable, "tools/check_hook_density.py", "--selftest"]),
        ("运镜结构 selftest", [sys.executable, "tools/check_shot_structure.py", "--selftest"]),
        ("风格锁 selftest", [sys.executable, "tools/check_style_lock.py", "--selftest"]),
        ("切点均质度 selftest", [sys.executable, "tools/check_shot_duration_variance.py", "--selftest"]),
        ("项目合规 selftest", [sys.executable, "tools/check_project_conformance.py", "--selftest"]),
        ("情绪词 selftest", [sys.executable, "tools/check_emotion_words.py", "--selftest"]),
        ("字幕烧录 selftest", [sys.executable, "tools/subtitle_burn.py", "--selftest"]),
        ("H3参考参数 selftest", [sys.executable, "tools/h3_ref_validator.py", "--selftest"]),
        ("文档数字 check_doc_numbers", [sys.executable, "tools/check_doc_numbers.py"]),
        ("豁免登记可解析", [sys.executable, "-c",
                          "import sys; sys.path.insert(0,'tools');"
                          "import _film_gate_waivers as w; print(w.load_waivers())"]),
    ]
    failures = []
    for name, cmd in checks:
        rc, out = run_cmd(cmd)
        tail = [x for x in out.strip().splitlines() if x.strip()]
        log(f"  {'OK  ' if rc == 0 else 'FAIL'} {name}: {tail[-1][:90] if tail else ''}")
        if rc != 0:
            failures.append((name, tail[-6:]))
    return failures


def clean_stage_artifacts():
    """自检会在暂存区生成 __pycache__ 等副产物；打包前必须清理。"""
    removed = []
    for p in sorted(STAGE.rglob("__pycache__")):
        shutil.rmtree(p, ignore_errors=True)
        removed.append(p.relative_to(STAGE).as_posix())
    for name in (".perf_tmp", ".pytest_cache"):
        q = STAGE / name
        if q.exists():
            shutil.rmtree(q, ignore_errors=True)
            removed.append(name)
    return removed


def build_zip():
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    files = sorted(p for p in STAGE.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            rel = p.relative_to(STAGE).as_posix()
            info = zipfile.ZipInfo(f"{TOP_DIR}/{rel}", date_time=(2026, 10, 22, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.flag_bits |= 0x800  # UTF-8 文件名，避免解压成乱码
            zf.writestr(info, p.read_bytes())
    return len(files), ZIP_PATH.stat().st_size


def main():
    parser = argparse.ArgumentParser(description="可重复执行的脱敏打包管线")
    parser.add_argument("--no-zip", action="store_true", help="只做暂存与校验")
    args = parser.parse_args()
    no_zip = args.no_zip
    log("== 1/7 清理 staging ==")
    if STAGE.parent.exists():
        shutil.rmtree(STAGE.parent)
    RELEASE.mkdir(parents=True, exist_ok=True)

    log("== 2/7 复制白名单到暂存区 ==")
    sources = collect_sources()
    stage_files(sources)
    log(f"  暂存 {len(sources)} 个文件 → {STAGE.relative_to(ROOT).as_posix()}")

    log("== 3/7 逐条脱敏改写 ==")
    applied = apply_spec()
    token_applied, token_totals = apply_tokens()
    fix_manifest()
    write_extras()
    n_spec = sum(applied.values())
    n_token = sum(token_applied.values())
    total = n_spec + n_token
    log(f"  定向改写 {n_spec} 条 / 全局替换 {n_token} 处；涉及 {len(set(applied) | set(token_applied))} 个文件")
    for rel in sorted(set(applied) | set(token_applied)):
        log(f"    {rel}: {applied.get(rel, 0) + token_applied.get(rel, 0)}")

    log("== 4/7 禁用词扫描 ==")
    hits = scan_forbidden()
    docs_bad = check_docs_paths()
    if hits:
        for w, lst in hits.items():
            log(f"  ✗ {w}: {sum(n for _r, n in lst)} 处")
            for rel, n in lst:
                log(f"      {rel} x{n}")
        fail("禁用词未清零")
    log("  全部禁用词 0 命中")
    if docs_bad:
        for line in docs_bad:
            log("  ✗ docs/ 非 URL 引用：" + line)
        fail("docs/ 断指针未清理")
    log("  docs/ 仅剩第三方 URL 引用")

    log("== 5/7 功能自检 ==")
    failures = verify_runtime()
    if failures:
        for name, tail in failures:
            log(f"  --- {name}")
            for line in tail:
                log("      " + line)
        fail("功能自检未通过")
    log("  功能自检全部通过")

    log("== 6/7 说明文件 ==")
    for f in ("requirements.txt", "声明与许可边界.md"):
        p = STAGE / f
        log(f"  {f}: {p.stat().st_size} bytes")

    if no_zip:
        log("== 7/7 跳过打包（--no-zip）==")
        return 0

    log("== 7/7 打包 zip ==")
    removed = clean_stage_artifacts()
    if removed:
        log("  清理自检副产物：" + "、".join(removed))
    n_files, size = build_zip()
    log(f"  {ZIP_PATH.name}: {n_files} 个文件, {size / 1024:.1f} KB")
    log(f"  路径：{ZIP_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
