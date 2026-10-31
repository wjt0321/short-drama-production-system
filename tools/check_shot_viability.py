#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G3 成立性预警：动作容量与声音对画面自证的最低机器检查。"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)
from _film_type import read_film_type
from check_shot_duration_variance import KNIFE_BANDS, KNIFE_BAND_SLACK

SHOT_ID_RE = re.compile(r"^\*{0,2}(?:S|G)\d{1,3}\*{0,2}$", re.I)
DUR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s|秒)", re.I)
GENERIC_ACTIONS = {"站着", "站立", "走动", "看向", "看着", "坐着", "坐下", "不动", "移动", "等待"}
ACTION_VERBS = re.compile(r"拿|抓|推|拉|走|跑|转身|抬|放|摔|打开|关闭|举|按|写|擦|追|躲|停|坐|站|看|说|喊|哭|笑|回头|伸手|接住|撞|掉落|冲出|进入")

def _norm(k):
    return re.sub(r"[\s（）()/*]", "", k).lower()

def _parse_tables(txt):
    tables=[]; cur=None
    for line in txt.splitlines():
        s=line.strip()
        if s.startswith("|"):
            cells=[c.strip() for c in s.strip("|").split("|")]
            if cur is None: cur=[]; tables.append(cur)
            cur.append(cells)
        else: cur=None
    for table in tables:
        if len(table)<2: continue
        header=table[0]
        id_col=None
        for i,h in enumerate(header):
            if SHOT_ID_RE.match(h) or _norm(h) in {"剪辑镜头id","镜头id","镜号","镜"}: id_col=i; break
        if id_col is None: continue
        rows=[]
        for cells in table[1:]:
            if id_col>=len(cells): continue
            sid=cells[id_col].strip().strip("*")
            if not SHOT_ID_RE.match(sid): continue
            rows.append({header[i]: cells[i] if i<len(cells) else "" for i in range(len(header))})
        if rows: return header, rows
    return [], []

def _pick(row, *names):
    for key,val in row.items():
        nk=_norm(key)
        if any(_norm(n) == nk or _norm(n) in nk for n in names): return val.strip()
    return ""

def _duration(text):
    m=DUR_RE.search(text or "")
    return float(m.group(1)) if m else None

def _action_count(text):
    text=text or ""
    chunks=[x.strip() for x in re.split(r"[，,；;。.!！？?→➡]+|然后|接着|随后|再", text) if x.strip()]
    concrete=[x for x in chunks if ACTION_VERBS.search(x)]
    return max(len(concrete), len(set(ACTION_VERBS.findall(text))))

def _voice_ratio(rows):
    total=0; narrator=0
    for row in rows:
        voice=_pick(row, "台词/声音", "台词", "声音")
        if not voice: continue
        total += len(voice)
        if re.search(r"旁白|narrator|画外音|voice[- ]?over", voice, re.I): narrator += len(voice)
    return narrator / total if total else 0.0

def analyse(project):
    problems=[]; facts={"片型": read_film_type(project)[0], "警告": []}
    path=None
    for rel in ("03-分镜/分镜表.md", "03-分镜/分镜表.txt"):
        fp=os.path.join(project,*rel.split("/"))
        if os.path.isfile(fp): path=fp; break
    if not path:
        return ["未找到 03-分镜/分镜表.md —— 无法做 G3 成立性检查"], facts
    txt=open(path,encoding="utf-8",errors="replace").read()
    header, rows=_parse_tables(txt)
    if not rows:
        return ["主表未解析到镜头行 —— 无法做动作容量检查"], facts
    facts["镜数"]=len(rows)
    limits={"短刀":1,"常规":2,"长刀":3}
    for row in rows:
        sid=_pick(row,"剪辑镜头ID","镜头ID","镜号","镜")
        action=_pick(row,"主体动作","动作")
        knife=_pick(row,"刀型")
        duration=_duration(_pick(row,"时长"))
        if action and knife in limits:
            count=_action_count(action)
            if count > limits[knife]:
                problems.append("{} 动作量 {} 阶段超过{}容量（{}：{}）—— 请拆镜或延长时长".format(sid,count,knife,action,knife))
        if action and action.strip() in GENERIC_ACTIONS:
            facts["警告"].append("{} 主体动作过于泛化「{}」，遮掉台词后画面可能无法自证本镜信息".format(sid,action.strip()))
        if duration is not None and knife in limits:
            lo, hi = KNIFE_BANDS[knife]
            if not lo - KNIFE_BAND_SLACK <= duration <= hi + KNIFE_BAND_SLACK:
                facts["警告"].append("{} 时长 {:.2f}s 与刀型「{}」不匹配，请人工复核".format(sid,duration,knife))
    ratio=_voice_ratio(rows); facts["旁白字符占声音字符比例"]=round(ratio,3)
    if ratio > 0.20:
        problems.append("旁白/画外音占声音文本 {:.0%}，超过默认 20% 上限——必须检查画面能否独立传达关键信息".format(ratio))
    if facts["警告"]:
        facts["视觉自证人工复核"]=len(facts["警告"])
    return problems, facts

def _write(td, body):
    os.makedirs(os.path.join(td,"03-分镜"),exist_ok=True)
    with open(os.path.join(td,"03-分镜","分镜表.md"),"w",encoding="utf-8") as f: f.write(body)

def selftest():
    import tempfile
    ok=True
    bad="""| 剪辑镜头ID | 场次 | 刀型 | 时长 | 主体动作 | 台词/声音 |
|---|---|---|---|---|---|
| S01 | 1 | 短刀 | 2s | 他转身拿起杯子推门跑出并回头喊人 | 旁白：他很紧张。 |
| S02 | 1 | 常规 | 3s | 站着 | 旁白：这里发生了一切。 |
"""
    with tempfile.TemporaryDirectory() as td:
        _write(td,bad); probs,facts=analyse(td)
        if not any("动作量" in p for p in probs) or not any("旁白" in p for p in probs): print("[自检失败] 应抓动作容量和旁白比例：",probs); ok=False
        else: print("[自检通过] 动作容量和旁白比例被抓")
    good="""| 剪辑镜头ID | 场次 | 刀型 | 时长 | 主体动作 | 台词/声音 |
|---|---|---|---|---|---|
| S01 | 1 | 短刀 | 2s | 他抬眼 | 环境声：门轴响 |
| S02 | 1 | 常规 | 3s | 他拿杯子放到桌上 | 对白：我来了 |
"""
    with tempfile.TemporaryDirectory() as td:
        _write(td,good); probs,facts=analyse(td)
        if probs: print("[自检失败] 合规容量误报：",probs); ok=False
        else: print("[自检通过] 合规容量放行")
    for knife, duration, expected in (("短刀", 2.4, False), ("长刀", 4.3, False), ("短刀", 2.6, True)):
        body = "| 剪辑镜头ID | 刀型 | 时长 | 主体动作 | 台词/声音 |\n|---|---|---|---|---|\n| S01 | {} | {}s | 他拿杯子 | 对白：我来了 |\n".format(knife, duration)
        with tempfile.TemporaryDirectory() as td:
            _write(td, body)
            _probs, facts = analyse(td)
            warned = any("不匹配" in w for w in facts["警告"])
            if warned != expected:
                print("[自检失败] 刀型容错 {} {}s：警告={}".format(knife, duration, warned)); ok=False
    import contextlib
    import io
    original = globals().get("discover_projects")
    try:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as empty:
            _write(td, good)
            globals()["discover_projects"] = lambda: [td, empty]
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = audit_all()
            if rc != 0 or os.path.basename(td) not in stdout.getvalue() or "[未评估]" not in stdout.getvalue() or os.path.basename(empty) not in stdout.getvalue():
                print("[自检失败] 混合项目未完整扫描：", rc, stdout.getvalue()); ok=False
            else:
                print("[自检通过] 混合项目健康与空项目均列出")
        globals()["discover_projects"] = lambda: []
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            audit_all()
        if not stdout.getvalue().startswith("[未评估]"):
            print("[自检失败] 无项目必须明确未评估：", stdout.getvalue()); ok=False
    finally:
        globals()["discover_projects"] = original
    return 0 if ok else 2

def discover_projects():
    container = os.path.join(SYSTEM_ROOT, "00-视频项目")
    if not os.path.isdir(container):
        return []
    return [os.path.join(container, name) for name in sorted(os.listdir(container))
            if os.path.isdir(os.path.join(container, name)) and not name.startswith("_")]


def audit_all():
    all_projects = discover_projects()
    projects = [p for p in all_projects
                if os.path.isfile(os.path.join(p, "03-分镜", "分镜表.md"))
                or os.path.isfile(os.path.join(p, "03-分镜", "分镜表.txt"))]
    for project in all_projects:
        if project not in projects:
            print("{}：[未评估] 无分镜表".format(os.path.basename(project)))
    if not projects:
        print("[未评估] 未发现带 03-分镜/分镜表.md 的在制项目，本闸没有可判对象")
        return 0
    failed = False
    for project in projects:
        probs, facts = analyse(project)
        print("{}：镜数={} {}".format(os.path.basename(project), facts.get("镜数", 0),
                                    "✗" if probs else "✓"))
        for problem in probs:
            print("  ✗ " + problem)
        for warning in facts.get("警告", []):
            print("  ⚠ " + warning)
        failed = failed or bool(probs)
    return 1 if failed else 0


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("project",nargs="?"); ap.add_argument("--selftest",action="store_true"); a=ap.parse_args()
    if a.selftest: return selftest()
    if not a.project:
        return audit_all()
    if not os.path.isdir(a.project): print("目录不存在：{}".format(a.project)); return 2
    probs,facts=analyse(a.project)
    for k,v in facts.items(): print("  {}：{}".format(k,v))
    for p in probs: print("  ✗ "+p)
    for w in facts.get("警告",[]): print("  ⚠ "+w)
    return 1 if probs else 0

if __name__=="__main__": sys.exit(main())
