# -*- coding: utf-8 -*-
"""读取导演笔记里「一处不可解释的决定」。

不用这节，就没有破例。用了就必须写成决定、写明它保护的种子，
并且破例闸恰好是 hook收尾、静止比例、色彩情绪 之一。
写坏了不放行，也不占用「每片一处」以外的第二条。
"""
import os
import re

NOTE_REL = os.path.join("06-成片", "导演证据", "导演笔记.md")
HEADING = "## 一处不可解释的决定"
GATES = ("hook收尾", "静止比例", "色彩情绪")
SEED_LABEL = "具体物件或话语"


def han_count(text):
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def section_body(text, heading):
    if heading not in text:
        return None
    body = text.split(heading, 1)[1]
    return re.split(r"\n## ", body, maxsplit=1)[0]


def field(section, label):
    if not section:
        return ""
    match = re.search(
        r"^-[ \t]*" + re.escape(label) + r"[ \t]*[：:][ \t]*(.*)$",
        section, re.M)
    return match.group(1).strip() if match else ""


def seed_value(project):
    """G0「具体物件或话语」里真正写下的那一句。模板说明算没写。"""
    path = os.path.join(project, "00-立项", "风格提案.md")
    if not os.path.isfile(path):
        return ""
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    match = re.search(r"具体物件或话语\s*[：:]\s*(.*)", text)
    if not match:
        return ""
    raw = match.group(1).strip()
    if "：" in raw:
        raw = raw.split("：")[-1].strip()
    elif ":" in raw:
        raw = raw.split(":")[-1].strip()
    if not raw or raw.startswith("一件有来历的东西"):
        return ""
    if han_count(raw) + len(re.findall(r"[A-Za-z0-9]", raw)) < 4:
        return ""
    return raw


def _read_note(project):
    path = os.path.join(project, NOTE_REL)
    if not os.path.isfile(path):
        return ""
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def load_exception(project):
    """返回 status：absent / empty / ok / invalid。只有 ok 才有 gate。"""
    text = _read_note(project)
    section = section_body(text, HEADING)
    if section is None:
        return {"status": "absent", "gate": None, "raw_gate": "", "problems": []}
    decision = field(section, "决定")
    protects = field(section, "保护的种子")
    gate = field(section, "破例闸")
    if not decision and not protects and not gate:
        return {"status": "empty", "gate": None, "raw_gate": "", "problems": []}
    problems = []
    if han_count(decision) < 12:
        problems.append("不可解释的决定不足一句（至少 12 个汉字）")
    seed = seed_value(project)
    if not seed:
        problems.append("用了不可解释的决定，但 G0 具体物件或话语还是空的")
    elif seed not in protects and protects not in seed:
        problems.append("保护的种子没有写上 G0 的物件或话语")
    if gate not in GATES:
        problems.append("破例闸必须正好是 hook收尾、静止比例、色彩情绪 之一")
    return {
        "status": "ok" if not problems else "invalid",
        "gate": gate if not problems and gate in GATES else None,
        "raw_gate": gate,
        "problems": problems,
        "decision": decision,
        "protects": protects,
    }


def exception_gate(project):
    record = load_exception(project)
    if record["status"] == "ok":
        return record["gate"]
    return None


def waiver_note(project, rule):
    """给闸门打印的一行。生效、或点了这条却没写实，才有字。"""
    record = load_exception(project)
    if record["status"] == "ok" and record["gate"] == rule:
        return "艺术破例生效：{}".format(rule)
    if record["status"] == "invalid" and record.get("raw_gate") == rule:
        return "艺术破例没有生效：" + record["problems"][0]
    return ""
