#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可选外部素材对齐检查。

seek 数据库已从体系目录移出。未显式配置外部库时，本闸报告跳过并成功返回；
它不再寻找体系内或相邻目录中的隐式副本。
"""
import argparse
import hashlib
import io
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

ORPHAN_THRESHOLD = 1.0


def key(url):
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]


def audit_pair(cov, review):
    if not (os.path.isdir(cov) and os.path.exists(review)):
        return None
    body = io.open(review, encoding="utf-8", errors="replace").read()
    urls = set(re.findall(r"图：\s*(https?://\S+)", body))
    if not urls:
        return None
    disk = set(f[:12] for f in os.listdir(cov)
               if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")))
    url_keys = {key(url) for url in urls}
    return ([url for url in urls if key(url) not in disk],
            [item for item in disk if item not in url_keys],
            len(urls), len(disk))


def main():
    ap = argparse.ArgumentParser(description="检查显式配置的外部素材库与审核表匹配度")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    raw = lib_locator.lib_root() if lib_locator is not None else None
    if not raw:
        payload = {"status": "skipped", "reason": "AI_SEEK_ROOT 未配置"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("外部素材库未配置，素材对齐闸跳过（体系可独立运行）")
        return 0

    result = audit_pair(os.path.join(raw, "封面"),
                        os.path.join(raw, "封面审核表.md"))
    if result is None:
        payload = {"status": "skipped", "reason": "外部素材库缺少封面或审核表"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("外部素材库缺少封面或审核表，素材对齐闸跳过")
        return 0

    missing, orphan, candidates, on_disk = result
    orphan_pct = len(orphan) * 100.0 / on_disk if on_disk else 0
    ok = orphan_pct <= ORPHAN_THRESHOLD
    payload = {"status": "checked", "ok": ok, "candidates": candidates,
               "on_disk": on_disk, "missing": len(missing),
               "orphan": len(orphan), "orphan_pct": round(orphan_pct, 1)}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("候选 {} 张 | 磁盘 {} 张 | 孤儿 {} 张 ({:.1f}%)".format(
            candidates, on_disk, len(orphan), orphan_pct))
        if missing:
            print("缺口（要下没下，可正常）: {} 张".format(len(missing)))
        if orphan and args.verbose:
            print("孤儿示例: {}".format(", ".join(orphan[:3])))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
