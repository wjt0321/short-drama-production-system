#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G6 复盘回写弱闸：复盘结论必须指向真实文件与行号。"""
import argparse, os, re, sys
HERE=os.path.dirname(os.path.abspath(__file__)); SYSTEM_ROOT=os.path.dirname(HERE)
TARGET_RE=re.compile(r"(?P<path>[^|：:]+?)[：:](?P<line>\d+)")
FAIL_RE=re.compile(r"##\s*失败裁决")

def archived(project):
    p=os.path.join(project,"项目状态摘要.md")
    try: return bool(FAIL_RE.search(open(p,encoding="utf-8",errors="replace").read()))
    except OSError: return False

def projects():
    root=os.path.join(SYSTEM_ROOT,"00-视频项目")
    if not os.path.isdir(root): return []
    return [os.path.join(root,n) for n in sorted(os.listdir(root)) if os.path.isdir(os.path.join(root,n)) and not n.startswith("_")]

def check_project(project):
    fp=os.path.join(project,"06-成片","复盘一页.md")
    if not os.path.isfile(fp): return [], {"状态":"未评估","复盘":None}
    lines=open(fp,encoding="utf-8",errors="replace").read().splitlines(); problems=[]; checked=0
    in_table=False
    for i,line in enumerate(lines):
        if "| # | 结论" in line: in_table=True; continue
        if not in_table or not line.strip().startswith("|") or set(line.strip("| -:").strip())==set(): continue
        cells=[c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells)<4 or not cells[0].isdigit(): continue
        conclusion,target,done=cells[1],cells[2],cells[3]; checked+=1
        if not conclusion or conclusion in {"结论（一句话）",""}: problems.append(f"第{i+1}行复盘结论为空") ; continue
        m=TARGET_RE.search(target)
        if not m: problems.append(f"第{i+1}行缺少回写目标 path:line：{target}"); continue
        rel=m.group("path").strip().strip('`'); line_no=int(m.group("line"))
        full=rel if os.path.isabs(rel) else os.path.join(project,rel)
        if not os.path.isfile(full): full=os.path.join(SYSTEM_ROOT,rel)
        if not os.path.isfile(full): problems.append(f"第{i+1}行目标文件不存在：{rel}"); continue
        target_lines=open(full,encoding="utf-8",errors="replace").read().splitlines()
        if not 1<=line_no<=len(target_lines): problems.append(f"第{i+1}行目标行号越界：{rel}:{line_no}"); continue
        # 弱匹配：结论至少有一个有意义的中文/英文关键词落在目标行；仅验证落点，不替代人审。
        words=[w for w in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", conclusion) if w not in {"下一集","观众反馈","必须修改"}]
        if words and not any(w in target_lines[line_no-1] for w in words): problems.append(f"第{i+1}行目标存在但关键词未命中：{rel}:{line_no}")
        if "[x]" not in done.lower() and "[√]" not in done: problems.append(f"第{i+1}行未标记已改：{target}")
    if checked==0: problems.append("复盘表没有可检查的回写行")
    return problems,{"状态":"已检查","复盘":os.path.relpath(fp,project),"条目":checked}

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td,"06-成片")); open(os.path.join(td,"AGENTS.md"),"w",encoding="utf-8").write("旁白占比限制\n")
        open(os.path.join(td,"06-成片","复盘一页.md"),"w",encoding="utf-8").write("| # | 结论（一句话） | 回写到（文件:行） | 已改 |\n|---|---|---|---|\n| 1 | 旁白占比限制 | AGENTS.md:1 | [x] |\n")
        probs,_=check_project(td)
        if probs: print("[自检失败] 合法回写误报：",probs); return 2
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td,"06-成片")); open(os.path.join(td,"06-成片","复盘一页.md"),"w",encoding="utf-8").write("| # | 结论（一句话） | 回写到（文件:行） | 已改 |\n|---|---|---|---|\n| 1 | 没写目标 | | |\n")
        probs,_=check_project(td)
        if not probs: print("[自检失败] 缺失目标未被抓"); return 2
    print("[自检通过] 合法回写放行，缺失目标被抓"); return 0

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("project",nargs="?"); ap.add_argument("--selftest",action="store_true"); a=ap.parse_args()
    if a.selftest:return selftest()
    ps=[a.project] if a.project else projects()
    if not ps: print("[未评估] 未发现带 06-成片/复盘一页.md 的在制项目"); return 0
    bad=0
    for p in ps:
        if archived(p): print("  {}：归档项目跳过".format(os.path.basename(p))); continue
        probs,facts=check_project(p); print("  {}：{}".format(os.path.basename(p),facts))
        if facts.get("状态") == "未评估": print("  {}：[未评估] 无复盘一页".format(os.path.basename(p)))
        for x in probs: print("  ✗ "+x)
        bad+=bool(probs)
    return 1 if bad else 0
if __name__=="__main__":sys.exit(main())
