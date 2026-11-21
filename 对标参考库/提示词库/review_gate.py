#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审核签核器 —— 让「人类只负责审核」真正闭环。

**问题**
制作包里的 5 个审核点是 md 里的 `- [ ]` 方框。人的勾选：
  · 机器读不了（没法判断能不能进下一步）
  · 无痕（下次打开不知道上次审到哪、改了什么）
  · 无约束（可以没审就开工）

**本脚本提供**
  · `--status`  读回当前审核状态（已过几关 / 卡在哪 / 该关该看什么）
  · `--checklist` 只打印 5 关的审核要点清单（不读制作包，审之前先看这个）
  · `--sign ID --verdict 通过|修改|暂停 [--note "..."]`
                写回一次裁决，带时间戳与备注，追加到审核日志
  · `--sign-all 通过`  一次签完 5 关（省去逐条敲命令）
  · `--gate G3`  门禁检查：5 关没过完 → 拒绝放行（退出码 2）
  · `--reset`   重置

**为什么要有审核要点清单**
「人类只负责审核」要成立，人得知道每关该看什么。
只报「未通过：①剧情审核」等于让人凭感觉点头——闸拦住了流程，
却没告诉人这一关到底在考什么。清单全部取自本项目实战踩过的坑
（见 SKILL.md 生产铁律），不是通用套话。

**状态存在哪**
制作包同目录 `_审核状态.json`（不污染制作包本身）。
零 import 体系模块，纯本地文件，拷走即带走。

**用法**
    python review_gate.py 制作包.md --status
    python review_gate.py 制作包.md --checklist
    python review_gate.py 制作包.md --sign ① --verdict 通过
    python review_gate.py 制作包.md --sign ③ --verdict 修改 --note "环境栏混入非敦煌元素"
    python review_gate.py 制作包.md --gate G3
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

# 5 个审核点（与流水线输出一致）
#
# **这里是 5 关的唯一真源**，`shortfilm_pipeline.py` 直接 import 本表生成
# 制作包里的审核清单，不再自己抄一份。抄第二份就多一个会过时的地方——
# 实测两份已经漂移过（一边写「logline / 三幕 / 钩子」，另一边少一关）。
#
# 第 4 个元素是**审核要点清单**：以前写了但从没显示给审核人
# （`show()` 里是 `for gid, name, _desc in GATES`，直接丢掉了）。
# 「人类只负责审核」要成立，人至少得知道每关该看什么——
# 只报「未通过：①剧情审核」等于让人凭感觉点头。
# 要点全部来自本项目实战踩过的坑（见 SKILL.md 生产铁律），不写通用套话。
GATES = [
    ("①", "剧情审核", "logline / 三幕 / 钩子是否成立", [
        "logline 一句话讲清：谁、要什么、被什么拦住、代价是什么",
        "三幕各自有转折，不是三段平铺陈述",
        "前 3 秒就有钩子（开场即矛盾或异象，不是在交代背景）",
        "结局兑现 logline 的承诺，不烂尾",
    ]),
    ("②", "脚本审核", "逐场景别 / 台词 / 时长是否合理", [
        "每场有明确场景目标，不是气氛描述或空镜堆砌",
        "台词读得完（看一眼字数就知道念不念得动）",
        "时长换算成立：总时长 ÷ 镜数 = 单镜秒数，单镜不低于 2 秒",
        "场次数与 --duration 相称（60 秒不该塞进 40 个镜头）",
    ]),
    ("③", "分镜审核", "首帧提示词能否直接出图", [
        "首帧提示词零占位符，用的是库内实词（不是模型自己编的词）",
        "**画风不打架**：没有 INS风/纯欲风/胶片摄影 这类与本片画风矛盾的词"
        "（制作包「已拦下的不适用词」一节列了被过滤掉哪些，逐条对一眼）",
        "**主体是人是物**：主体栏是人物不是地名，镜头里没有多出来的第二个人",
        "每镜首帧来自人工过目过的资产；上一镜的模型末帧不得直接当下一镜首帧",
        "链长：每 3–5 镜回锚一次人工资产（防身份漂移）",
        "负向词带上了，且与本片风格不打架",
        "平台语法没串台：各家结构各用各的，不混写",
    ]),
    ("④", "技法审核", "光影 / 构图 / 调色是否匹配情绪", [
        "技法是库内现取的，不是临时编的",
        "光影方向全片统一（不会一场顺光一场逆光无交代）",
        "构图有明确意图（框住主体、制造压迫或留白），不是随手排",
        "调色服务于该场情绪，不是全片一个色调",
    ]),
    ("⑤", "清单审核", "素材与工作量是否可执行", [
        "需要的素材库里都有（没有「还得先去下载」这种隐藏工作量）",
        "镜头数 × 单镜抽卡次数在可接受范围",
        "不可控环节已标出（平台排队、版权音乐、演员档期）",
        "G6 有抽卡失败回退链，知道不达标时按哪级往下走",
        "缺素材的地方标了「需补素材」而不是含糊过去",
    ]),
]

VERDICTS = ("通过", "修改", "暂停")


def checkpoints_md():
    """制作包里的单行版审核清单（给 Markdown 用）。

    完整逐条清单不进制作包——那会让文档胖一大截却没人逐条读。
    制作包里给一行摘要 + 指向 `--checklist` 看细则。
    """
    return ["{} {}：{}".format(g[0], g[1], g[2]) for g in GATES]


def content_fingerprint(pack_md):
    """制作包内容指纹——用于检测「改了参数重跑但文件名没变」。

    只取**实质内容**（分镜提示词 + 台词 + 声音计划），不取时间戳，
    否则每次重跑都算「变了」，旧裁决被无意义作废。
    片段用**明确的下一个标题**截断，不能用 '---'（它会匹配到标题下的
    水平线，导致片段被截成空）。
    """
    try:
        text = open(pack_md, encoding="utf-8").read()
    except Exception:  # noqa: BLE001
        return ""
    # (起始标题, 结束标题) —— 结束标题必须在文中确实出现
    spans = [
        ("### 分镜速查", "### 库内实词"),
        ("## ③ 脚本", "## ④ 分镜"),
        ("### 声音与字幕计划", "## ⑥"),
    ]
    picks = []
    for start, end in spans:
        i = text.find(start)
        if i < 0:
            continue
        j = text.find(end, i + len(start))
        if j < 0:
            j = min(len(text), i + 4000)   # 找不到就用固定长度兜底
        picks.append(text[i:j])
    blob = "\n".join(picks)
    if not blob.strip():
        return ""
    return hashlib.md5(blob.encode("utf-8")).hexdigest()[:12]


def state_path(pack_md):
    d = os.path.dirname(os.path.abspath(pack_md))
    base = os.path.splitext(os.path.basename(pack_md))[0]
    return os.path.join(d, "_{}_审核状态.json".format(base))


def load(sp):
    if os.path.exists(sp):
        try:
            return json.load(open(sp, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"topic": "", "gates": {}}


def save(sp, st):
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def sync_fingerprint(st, pack_md):
    """检测制作包内容是否已变。变了就作废旧的「通过」裁决。

    为什么必须这么做：改了风格/时长/题材重跑，文件名往往不变，
    但内容全换了。旧裁决还显示「通过」比丢失更危险——
    人会以为已经审过，实际审的是上一版。
    """
    fp = content_fingerprint(pack_md)
    old = st.get("fingerprint")
    changed = bool(old) and old != fp
    if changed:
        for gid, g in st["gates"].items():
            if g.get("verdict") == "通过":
                g["verdict"] = "需重审"
                g["note"] = (g.get("note", "") + " ｜内容已变，旧裁决作废").strip(" ｜")
    st["fingerprint"] = fp
    return changed


def show_checklist(only=None, indent="  "):
    """打印审核要点清单。`only` 为空则打印全部 5 关。"""
    for gid, name, _desc, items in GATES:
        if only and gid not in only:
            continue
        print("{}{} {}（{}）".format(indent, gid, name, _desc))
        for it in items:
            print("{}  - {}".format(indent, it))


def show(st, pack_md):
    print("审核状态：{}\n".format(pack_md))
    print("{:<4s} {:<10s} {:<6s} {}".format("关", "项目", "裁决", "备注/时间"))
    print("-" * 78)
    done = 0
    for gid, name, _desc, _items in GATES:
        g = st["gates"].get(gid) or {}
        v = g.get("verdict", "未审")
        note = g.get("note", "")
        ts = g.get("at", "")
        if v == "通过":
            done += 1
        line = "{:<4s} {:<10s} {:<6s} {}".format(gid, name, v, note)
        if ts:
            line += "  [{}]".format(ts)
        print(line)
    print("-" * 78)
    print("已通过 {}/{} 关".format(done, len(GATES)))
    blocked = [g[0] for g in GATES
               if (st["gates"].get(g[0]) or {}).get("verdict") != "通过"]
    if blocked:
        print("未通过：{}".format("、".join(
            g[0] + g[1] for g in GATES if g[0] in blocked)))
        # 未过的关卡直接把「该看什么」摊开——只报关卡名等于让人凭感觉点头
        print("\n以下关卡该看什么：")
        show_checklist(only=blocked)
        print("\n（只看某几关的完整清单：--checklist）")
    return done, len(GATES)


def main():
    ap = argparse.ArgumentParser(description="制作包审核签核与门禁")
    ap.add_argument("pack", help="制作包 md 路径")
    ap.add_argument("--status", action="store_true", help="查看审核状态")
    ap.add_argument("--sign", help="关卡编号，如 ① ② ③ ④ ⑤")
    ap.add_argument("--verdict", choices=VERDICTS, help="裁决")
    ap.add_argument("--note", default="", help="备注（修改/暂停时建议写）")
    ap.add_argument("--gate", help="门禁名：G3/G4/G6，未审完则拒绝放行")
    ap.add_argument("--reset", action="store_true", help="重置全部审核状态")
    ap.add_argument("--sign-all", choices=VERDICTS,
                    help="一次签完 5 关（省去逐条敲命令）")
    ap.add_argument("--checklist", action="store_true",
                    help="只打印 5 关的审核要点清单（不读制作包）")
    args = ap.parse_args()

    if args.checklist:
        print("审核要点清单（每关该看什么）\n")
        show_checklist(indent="")
        return 0

    if not os.path.exists(args.pack):
        print("找不到制作包：{}".format(args.pack), file=sys.stderr)
        return 1

    sp = state_path(args.pack)

    if args.reset:
        st = load(sp)
        st["gates"] = {}
        save(sp, st)
        print("已重置审核状态")
        return 0

    # 一次签完 5 关 —— 审核是「一步动作」，不该让人敲 5 条命令
    if args.sign_all:
        st = load(sp)
        if sync_fingerprint(st, args.pack):
            print("⚠ 制作包内容已变，旧裁决作废。")
        ts = time.strftime("%Y-%m-%d %H:%M")
        for gid, name, _d, _items in GATES:
            st["gates"][gid] = {
                "verdict": args.sign_all,
                "note": args.note or "批量签核",
                "at": ts,
            }
        save(sp, st)
        print("已签完 {} 关：{}".format(len(GATES), args.sign_all))
        if args.note:
            print("  备注：{}".format(args.note))
        return 0

    if args.sign:
        if not args.verdict:
            print("签核需要 --verdict（通过/修改/暂停）", file=sys.stderr)
            return 1
        # 接受 ① 或 1；全角圈号不是 isdigit()，要按字符判断
        gid = args.sign.strip()
        valid = [g[0] for g in GATES]
        if gid in valid:
            pass
        elif gid.isdigit() and 1 <= int(gid) <= 5:
            gid = valid[int(gid) - 1]
        else:
            print("关卡编号无效：{}（应为 {} 或 1-5）".format(
                gid, " ".join(valid)), file=sys.stderr)
            return 1
        st = load(sp)
        if not st.get("topic"):
            with open(args.pack, encoding="utf-8") as f:
                first = f.readline().strip()
            st["topic"] = re.sub(r"^#\s*AI 短片制作包：\s*", "", first)
        # 签核前先同步指纹：若内容已变，明确告知要重审
        if sync_fingerprint(st, args.pack):
            pending = [g[0] for g in GATES
                       if (st["gates"].get(g[0]) or {}).get("verdict") == "需重审"]
            if pending:
                print("⚠ 检测到制作包内容已变，以下关卡需重审：{}".format(
                    "、".join(pending)))
        st["gates"][gid] = {
            "verdict": args.verdict,
            "note": args.note,
            "at": time.strftime("%Y-%m-%d %H:%M"),
        }
        save(sp, st)
        print("{} {} → {}".format(gid, dict((g[0], g[1]) for g in GATES)[gid],
                                  args.verdict))
        if args.note:
            print("  备注：{}".format(args.note))
        return 0

    st = load(sp)
    changed = sync_fingerprint(st, args.pack)
    if changed:
        save(sp, st)
        print("⚠ 制作包内容已变，旧裁决已作废为「需重审」。\n")
    done, total = show(st, args.pack)

    if args.gate:
        if done == total:
            print("\n门禁 {}：放行 ✓".format(args.gate))
            return 0
        print("\n门禁 {}：拒绝放行 ✗（{}/{} 关已通过）".format(args.gate, done, total))
        print("  每关该看什么：python review_gate.py {} --checklist"
              .format(os.path.basename(args.pack)))
        print("  逐条签核　　：python review_gate.py {} --sign X --verdict 通过"
              .format(os.path.basename(args.pack)))
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
