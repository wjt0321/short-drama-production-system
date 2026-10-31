#!/usr/bin/env python3
"""Static preflight checks for platform video prompts.

This tool does not choose a vendor. It only enforces the prompt contract selected
by the caller and rejects obvious platform-syntax mixing before generation.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable


SORA_ALIASES = {"sora", "sora2", "sora-2", "sora 2"}
H3_ALIASES = {"h3", "minimax-h3", "minimax_h3"}
NATURAL_LANGUAGE_PLATFORMS = {
    "runway", "runway-gen4", "runway-gen4.5", "veo", "veo3", "veo3.1",
    "luma", "dream-machine", "firefly", "firefly-video", "kling", "kling3",
    "pixverse", "vidu", "jimeng", "即梦",
}
SEEDANCE_ALIASES = {"seedance", "seedance2", "seedance-2", "seedance2.0"}


def _normalise(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def _contains_any(text: str, values: Iterable[str]) -> bool:
    return any(value.lower() in text.lower() for value in values)


def _field_value(prompt: str, field: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(field)}\s*:\s*(.*?)(?=^\s*[A-Za-z_][A-Za-z0-9_ ]*\s*:|\Z)", prompt, re.S)
    return match.group(1).strip() if match else ""


def _has_dialogue_like_soundscape(value: str) -> bool:
    if not value:
        return False
    # A negative guard such as “no dialogue” is a restriction, not dialogue
    # content. The actual hard rule is that spoken content must not be placed
    # in overall_soundscape; callers should still prefer positive sound-only
    # wording in production prompts.
    cleaned = re.sub(r"\b(?:no|without|free of)\s+(?:dialogue|speech|talking)\b", "", value, flags=re.I)
    patterns = (
        r"\bspeaking\b",
        r"\bsays\b",
        r"\bspeaks\b",
        r"\bthe dialogue\b",
        r"\bthe line\b",
        r"\bvoice answering\b",
        r"\bvoice speaking\b",
        r"对白",
        r"台词",
        r"说话",
        r"说：",
    )
    return any(re.search(pattern, cleaned, re.I) for pattern in patterns)


def validate_prompt(platform: str, prompt: str, mode: str | None = None) -> dict:
    platform_key = _normalise(platform)
    errors: list[str] = []
    warnings: list[str] = []

    if platform_key in SORA_ALIASES:
        errors.append("Sora 已从当前生产路由移除；如需使用 API，必须作为新实现重新核验和登记。")
        return {"valid": False, "platform": platform, "mode": mode, "errors": errors, "warnings": warnings}

    # Prevent H3's structured DSL from being silently sent to natural-language platforms.
    h3_markers = (
        "integrated_multimodal_description:",
        "overall_soundscape:",
        "non_diegetic_music:",
        "subject_definitions:",
        "retention_analysis:",
    )
    if platform_key not in H3_ALIASES and _contains_any(prompt, h3_markers):
        errors.append("检测到 H3 固定字段；当前平台适配器不是 H3，禁止串用 H3 DSL。")
    if platform_key not in H3_ALIASES and re.search(r"\[Shot\s+\d+\]\s+At\s+\d", prompt, re.I):
        errors.append("检测到 H3 时间戳镜头语法；自然语言平台不能默认套用 [Shot N] At ...。")

    if platform_key in H3_ALIASES:
        selected_mode = _normalise(mode or "base")
        if selected_mode in {"ref2va", "ref", "reference", "reference2video"}:
            required = ("subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music")
            for field in required:
                if not re.search(rf"(?im)^\s*{re.escape(field)}\s*:", prompt):
                    errors.append(f"H3 Ref2VA 缺少固定字段：{field}。")
            description = _field_value(prompt, "detailed_description")
            if _has_dialogue_like_soundscape(description) and "<d>" not in description:
                errors.append("H3 Ref2VA 的对白意图必须进入 detailed_description，并使用 <d> 标签。")
        else:
            required = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")
            for field in required:
                if not re.search(rf"(?im)^\s*{re.escape(field)}\s*:", prompt):
                    errors.append(f"H3 Base 缺少固定字段：{field}。")
            if "integrated_multimodal_description:" in prompt and not re.search(r"\[Shot\s+1\]", prompt, re.I):
                errors.append("H3 Base 的 integrated_multimodal_description 必须从 [Shot 1] 开始。")
        if re.search(r"(?im)^\s*(Scene|Speaker and Dialogue|Diegetic Sound|Overall Soundscape|Non-Diegetic Music|Audio Restrictions)\s*:", prompt):
            errors.append("检测到自定义六段标题；它们不是 H3 官方字段，必须映射到 H3 Base/Ref2VA 结构。")
        if "<d>" in prompt and not re.search(r"\(S\d+\)", prompt):
            errors.append("H3 对白包含 <d> 但缺少 (S1)/(S2) 说话人标记。")
        if re.search(r"@(?:Image|Video|Audio)\s*\d+", prompt, re.I):
            errors.append("检测到 Seedance/即梦 @Image/@Video/@Audio 句柄；H3 应使用 <Picture N>/<Video N>/<Audio N>。")
        soundscape = _field_value(prompt, "overall_soundscape")
        if _has_dialogue_like_soundscape(soundscape):
            errors.append("H3 的 overall_soundscape 只能写环境声、物声和非语言人声，不得写对白或台词文本。")
        if re.search(r"(?im)^\s*Audio Restrictions\s*:", prompt):
            warnings.append("Audio Restrictions 是项目约束说明，不是 H3 官方固定字段；请将关键限制改写为正向画面/声音描述。")
        if not re.search(r"<d>.*?</d>", prompt, re.S) and _has_dialogue_like_soundscape(prompt):
            warnings.append("提示词含对白意图但未发现 <d> 标签；若本镜是对白镜，应补入 H3 对白标签。")

    if platform_key in SEEDANCE_ALIASES:
        if re.search(r"\bNEGATIVE\s*:", prompt, re.I):
            errors.append("Seedance 的 NEGATIVE: 不是当前可依赖的官方字段；改用正向约束行。")
        if re.search(r"(?im)^\s*(integrated_multimodal_description|overall_soundscape|non_diegetic_music)\s*:", prompt):
            errors.append("Seedance 不应直接套用 H3 三字段；请使用当前 Seedance 入口的素材句柄和自然语言分段。")
        if "@Image1" in prompt or "@Video1" in prompt or "@Audio1" in prompt:
            warnings.append("@Image1/@Video1/@Audio1 只在已登记的 Seedance 接口句柄中使用；不要复制到即梦入口。")

    if platform_key in {"jimeng", "即梦"} and re.search(r"@(?:Image|Video|Audio)\s*\d+", prompt, re.I):
        errors.append("即梦不能自动套用 Seedance 的 @Image/@Video/@Audio 句柄；按当前即梦入口声明素材。")

    if platform_key in {"pixverse", "vidu"} and re.search(r"Ai-trace-id|积分状态|credit\s*status", prompt, re.I):
        errors.append("追踪 ID、积分或账户状态不是视频提示词内容，不得写入提示词契约。")

    return {"valid": not errors, "platform": platform, "mode": mode, "errors": errors, "warnings": warnings}


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    raise SystemExit("必须提供 --prompt 或 --prompt-file")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--mode")
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = validate_prompt(args.platform, _read_prompt(args), args.mode)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        state = "PASS" if result["valid"] else "FAIL"
        print(f"[{state}] {result['platform']} {result.get('mode') or ''}".strip())
        for item in result["errors"]:
            print(f"ERROR: {item}")
        for item in result["warnings"]:
            print(f"WARN: {item}")
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
