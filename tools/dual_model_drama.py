#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双模型接力编剧流水线 v2
=========================
Qwen3.5-9B（结构 + 因果四句 + 台词）
  → Gemma-4-E4B（表演层加厚）
  → hybrid_cleaner.py（审校清理：规则层 + 模型层 + 校验层）

第 3 棒为什么换掉（EP02 实测，三种失败方案）：
  ① Qwen 直接改写长稿 → 几乎不动，还把「因为/所以/但是/于是」四句整句删掉。
  ② 检查器模式（全文→清单）→ 模型按整句重写，吞台词（「按流程来，先立项。」被删）、
     改四句（「彻底打乱逻辑闭环」→「打乱」）。
  ③ 逐组重写 batch>1 → 模型每批重新编号，内容整体错位（一组被换成别组答案）。
  正解 = 规则做确定性清理 → 模型只处理规则残留的疑难段 → 强制台词逐字校验。

用法:
    python dual_model_drama.py <任务文件> [输出目录]

任务文件: 第一行起写题材与人物设定即可(自由文本), 会被注入第 1 棒。
输出: 输出目录下 step1_qwen.txt / step2_gemma.txt / step3_cleaned.txt / final.txt
"""
import subprocess
import sys
import os
import time
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hybrid_cleaner as HC

LMS = os.path.join(os.environ.get("USERPROFILE", ""), ".lmstudio", "bin", "lms.exe")
QWEN = "qwen3.5-9b-uncensored-hauhaucs-aggressive"
# 注意：google/gemma-4-e4b 这个 key 在本机已不存在（用户清理了 google/gemma-4-e4b-it），
# 现役可用的 Gemma 是 HauhauCS 的 uncensored 版。用前先 `lms ls` 确认 key 存在。
GEMMA = "gemma-4-e4b-uncensored-hauhaucs-aggressive"
CTX = "8192"

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def lms(*args):
    """调用 lms CLI, 返回清洗过 ANSI 的 stdout"""
    try:
        r = subprocess.run(
            [LMS, *args],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        return ANSI.sub("", r.stdout or "")
    except FileNotFoundError:
        raise SystemExit(f"找不到 lms.exe: {LMS}\n请确认 LM Studio 已安装并在 PATH 配置中。")


def load(model):
    """卸载所有模型后加载指定模型, 等待就绪"""
    lms("unload", QWEN)
    lms("unload", GEMMA)
    time.sleep(2)
    lms("load", model, "--gpu", "max", "--context-length", CTX, "-y")
    key = model.split("/")[-1]
    for _ in range(40):
        if key in lms("ps"):
            print(f"    [loaded] {model}  ctx={CTX}", flush=True)
            return
        time.sleep(2)
    raise RuntimeError(f"模型加载超时: {model}")


def chat(model, prompt, outfile):
    """加载模型 -> 生成 -> 存盘 -> 返回正文"""
    load(model)
    txt = lms("chat", model, "-p", prompt, "-y", "--reasoning", "off")
    txt = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", txt).replace("\r\n", "\n").strip("\n")
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(txt)
    return txt


STEP1 = """【任务】为一部短剧写第 1 集的第 1 场和第 2 场。
【设定】{SPEC}
【格式】每场按此顺序：场景 N：地点／时间／内外 → 因为： → 所以： → 但是： → 于是： → 戏：（动作与台词交织的段落，台词前标说话人）
【纪律】1. 只写这两场，无大纲无说明 2.「因为」必须是上一场留下的具体事 3.「但是」写清谁挡住主角 4.「于是」成为下一场「因为」 5. 戏是连续段落不是五块并列格子 6. 台词口语化短句，至少一句不推进剧情只暴露人的台词 7. 不写解释性旁白与情绪标签 8. 结尾落在未完成状态 9. 全文 700 字以内
"""

STEP2 = """【任务】下面是短剧初稿，结构与因果链已成立。**只做表演层增强**，不改结构、场次、人物关系、剧情走向。
【初稿】{DRAFT}
【要求】1. 人物名单封闭：只允许出现原初稿中的人，不得新增或替换任何角色 2. 四句因果链一字不改 3. 场号/时间/地点不动 4. 引号里的台词原句保留，只在台词前补表演提示（语气/动作/停顿） 5. 重点加厚：站位、视线、接触、遮挡、受力、微表情、手上动作 6. 台词里不出现镜头参数 7. 不写解释性旁白与情绪标签 8. **禁止使用心理副词**："带着一丝…""仿佛…""像是…""似乎…""试图…"一律不用，改写成纯动作 9. **全文 750 字以内**（留出改写余量） 10. 只输出增强后剧本本身，无说明文字
"""

FINAL_CHECK = """
═══════════════════════════════════════════
⚠️  必看：第 3 棒仍会漏两类问题，请人工终审

①「试图…」式心理推断 —— 把心理伪装成动作
   漏网例："试图用亲近感压制她的审视"
   改法：直接写他做了什么
   对："身体前倾，手臂搭上桌沿"
   错："试图用亲近感压制她的审视"

② 残留的比喻句 / 散文词
   漏网例："眼底那抹不易察觉的冷光"（"那抹"是散文词）
   改法："他眼底闪过一丝冷光"

判定口诀：把"像/仿佛/似乎/试图/带着一种…的…"全圈出来，
不能直接拍出来的，一律改成动作或删掉。

④ 结构层：第 3 棒只管表演层措辞，**不碰因果链的逻辑**。
   「因为→所以」接不上、「但是」没写清谁挡住主角，仍要人工改。
═══════════════════════════════════════════
"""


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)

    spec_file = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else "."
    os.makedirs(outdir, exist_ok=True)

    with open(spec_file, encoding="utf-8") as f:
        spec = f.read()

    print("[1/3] Qwen 出结构 + 因果四句 + 台词 …", flush=True)
    s1 = chat(QWEN, STEP1.format(SPEC=spec), os.path.join(outdir, "step1_qwen.txt"))

    print("[2/3] Gemma 加厚表演层 …", flush=True)
    s2 = chat(GEMMA, STEP2.format(DRAFT=s1), os.path.join(outdir, "step2_gemma.txt"))

    print("[3/3] hybrid_cleaner 审校清理（规则层 → 模型层 → 校验层）…", flush=True)
    s3, report = HC.clean(s2, model="gemma", do_model=True)

    with open(os.path.join(outdir, "step3_cleaned.txt"), "w", encoding="utf-8") as f:
        f.write(s3)

    final = os.path.join(outdir, "final.txt")
    with open(final, "w", encoding="utf-8") as f:
        f.write(s3)

    v = report["verify"]
    print(f"\n完成 → {final}")
    print("规则干预 %d 组 | 模型干预 %d 组 | 丢弃 %d 组"
          % (len(report["applied"]), len(report.get("model", {})), len(report["dropped"])))
    print("台词逐字一致: %s (%s→%s) | 因果四句逐字一致: %s"
          % (v.get("dialogue_identical"), v.get("dialogue_count"),
             v.get("dialogue_after"), v.get("causal_identical")))
    if v.get("ERROR"):
        print("⚠ %s" % v["ERROR"])
    print(FINAL_CHECK)


if __name__ == "__main__":
    main()
