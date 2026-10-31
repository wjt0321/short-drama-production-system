# -*- coding: utf-8 -*-
"""项目片型读取：G0 风格提案优先，兼容旧项目剧本字段。"""
import os
import re

FILM_TYPES = ("叙事", "意象")
_FILM_RE = re.compile(r"片型\s*[:：]\s*[*`\s]*(叙事|意象)")

def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""

def read_film_type(project):
    """返回 (片型, 来源)。G0 风格提案优先，无声明按叙事。"""
    candidates = (
        (os.path.join(project, "00-立项", "风格提案.md"), "G0风格提案"),
        (os.path.join(project, "01-剧本", "剧本.md"), "G1剧本兼容"),
    )
    for path, source in candidates:
        m = _FILM_RE.search(_read(path))
        if m:
            return m.group(1), source
    return "叙事", "默认"

def is_imagery(project):
    return read_film_type(project)[0] == "意象"
