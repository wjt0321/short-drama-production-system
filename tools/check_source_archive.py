#!/usr/bin/env python3
"""Read-only integrity check for the user-provided external source archive.

Usage requires an explicit --root. The project never assumes a machine path and
this script never writes to, moves, or deletes anything under the source root.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

EXPECTED = [
    "02-人设库/人设-逐个文件/分镜转视频提示词.md",
    "03-技能库/短剧与漫剧/短剧单集分镜助手.md",
    "03-技能库/短剧与漫剧/短剧角色设计.md",
    "03-技能库/短剧与漫剧/角色设计三视图.md",
    "03-技能库/短剧与漫剧/电影级分镜运镜提示词.md",
    "03-技能库/短剧与漫剧/视频动作复刻与角色迁移.md",
    "04-短剧专用/短剧专用资产包.md",
    "06-机制档案/01-Agent运行逻辑全解.md",
    "06-机制档案/03-质量归因与真实成片质检.md",
]

def main() -> int:
    parser = argparse.ArgumentParser(description="只读核验外部短剧源档案")
    parser.add_argument("--root", required=True, type=Path, help="外部源档案根目录；必须由调用者显式提供")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出摘要")
    args = parser.parse_args()
    root = args.root.expanduser()
    if not root.exists() or not root.is_dir():
        print(f"源档案目录不存在或不是目录: {root}", file=sys.stderr)
        return 2
    missing = [rel for rel in EXPECTED if not (root / rel).is_file()]
    files = sum(1 for p in root.rglob("*") if p.is_file())
    dirs = sum(1 for p in root.rglob("*") if p.is_dir())
    bytes_total = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    result = {"ok": not missing, "expected": len(EXPECTED), "missing": missing,
              "files": files, "dirs": dirs, "bytes": bytes_total}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"源档案核验: {'通过' if result['ok'] else '失败'}")
        print(f"文件数={files} 目录数={dirs} 字节数={bytes_total} 关键文件={len(EXPECTED)}")
        for rel in missing: print(f"缺失: {rel}")
    return 0 if result["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
