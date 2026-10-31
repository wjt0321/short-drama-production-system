#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成片风格检索器（离线，纯本地，零联网）。

**内部实现**：Agent 公开入口是 `tools/select_reference.py style`（本脚本不直接对外）。

输入题材描述 → 扫描显式配置的外部 seek 成片清单 → 给出 2–4 个候选，
含作品名、风格类型、视频路径、抽帧目录与代表帧，供用户挑选后再做探针。

**定位原则**：只描述"从本地成片库找风格"这一能力，不调用任何外部厂商接口；
路径相对脚本推算，把项目整体搬到别的电脑/盘也能跑。

清单字段（外部库 02_视觉素材/视频/<分组>/_清单.json）：
  tag 标签, title 作品名, kind 风格类型, file 视频文件名,
  frames_dir 抽帧目录(相对清单), res 分辨率, dur 时长,
  lighting 光照(光源/软硬/方向/色温), palette 色调, lens 视角/焦段,
  note 借鉴点, url 原始链接。
  新作品入库时 lighting/palette/lens 应尽量填写，供场景图与首帧直接参考。

用法：
    python tools/find_style.py "古风书生女子相遇"
    python tools/find_style.py "乡土写实" --top 4 --format json
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SYSTEM_ROOT, "外部参考库", "提示词库"))
try:
    import lib_locator  # noqa: E402
except ImportError:  # 外部参考库为可选组件，未随包提供
    lib_locator = None

VIDEO_ROOT = ""


def load_all_works():
    """读取显式配置的外部库中的成片清单。"""
    global VIDEO_ROOT
    root = lib_locator.seek_root() if lib_locator is not None else None
    if not root:
        raise RuntimeError("未配置外部 seek 库；如需维护性检索，请显式设置 AI_SEEK_ROOT")
    VIDEO_ROOT = os.path.join(root, "02_视觉素材", "视频")
    works = []
    for manifest in glob.glob(os.path.join(VIDEO_ROOT, "*", "_清单.json")):
        group = os.path.basename(os.path.dirname(manifest))
        try:
            data = json.load(open(manifest, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in data:
            item = dict(item)
            item.setdefault("group", group)
            item["_manifest_dir"] = os.path.dirname(manifest)
            works.append(item)
    return works


def rep_frames(item, k=3):
    """从抽帧目录取 k 张代表帧（首/中/末）。"""
    fd = item.get("frames_dir", "")
    if not fd:
        return []
    abs_fd = os.path.normpath(os.path.join(item["_manifest_dir"], fd))
    if not os.path.isdir(abs_fd):
        return []
    imgs = sorted(f for f in os.listdir(abs_fd)
                  if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
    if not imgs:
        return []
    if len(imgs) <= k:
        pick = imgs
    else:
        idx = [round(i * (len(imgs) - 1) / (k - 1)) for i in range(k)]
        pick = [imgs[i] for i in sorted(set(idx))]
    return [os.path.join(abs_fd, p) for p in pick]


def score(item, query):
    """简单关键词匹配分：命中 kind/title/tag/note。"""
    text = " ".join(str(item.get(k, "")) for k in
                    ("kind", "title", "tag", "note", "group"))
    if not query.strip():
        return 1
    return sum(1 for ch in set(query) if ch in text)


def main():
    ap = argparse.ArgumentParser(description="本地成片风格检索（离线）")
    ap.add_argument("query", nargs="?", default="", help="题材/风格描述")
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--format", choices=["md", "json"], default="md")
    args = ap.parse_args()

    try:
        works = load_all_works()
    except RuntimeError as exc:
        print("✗ {}".format(exc), file=sys.stderr)
        return 1
    ranked = sorted(works, key=lambda w: score(w, args.query), reverse=True)
    candidates = [w for w in ranked if score(w, args.query) > 0][:args.top]
    # 命中不足时，至少把库内已有风格补上（让用户看到全部可选方向）
    if len(candidates) < min(2, len(works)):
        for w in works:
            if w not in candidates:
                candidates.append(w)
            if len(candidates) >= args.top:
                break

    rows = []
    for w in candidates:
        rows.append({
            "tag": w.get("tag", ""),
            "kind": w.get("kind", ""),
            "title": w.get("title", ""),
            "video": os.path.join(w["_manifest_dir"], w.get("file", "")),
            "frames": rep_frames(w),
            "lighting": w.get("lighting", ""),
            "palette": w.get("palette", ""),
            "lens": w.get("lens", ""),
            "note": w.get("note", ""),
        })

    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    print("# 风格候选（本地成片 · 离线检索）\n")
    print("题材：{}　|　库内成片 {} 部\n".format(args.query or "（未指定）", len(works)))
    for i, r in enumerate(rows, 1):
        print("{}. **{}** —— {}".format(i, r["tag"], r["kind"]))
        print("   - 作品：{}".format(r["title"]))
        print("   - 视频：{}".format(r["video"]))
        if r["lighting"]:
            print("   - 光照：{}".format(r["lighting"]))
        if r["palette"]:
            print("   - 色调：{}".format(r["palette"]))
        if r["lens"]:
            print("   - 视角/焦段：{}".format(r["lens"]))
        if r["frames"]:
            print("   - 代表帧：")
            for f in r["frames"]:
                print("       · {}".format(f))
        if r["note"]:
            print("   - 借鉴点：{}".format(r["note"]))
        print("")
    print("用法：挑一个方向 → 用《导演视觉圣经》§1.0 做 1–2 个风格探针 → 并排比对通过再量产。")


if __name__ == "__main__":
    sys.exit(main())
