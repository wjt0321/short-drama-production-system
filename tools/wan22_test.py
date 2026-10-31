#!/usr/bin/env python
"""Wan 2.2 TI2V-5B 实测脚本（开发/实测脚本，非生产入口；直接走 ComfyUI HTTP API，不依赖 MCP）。

用法：
    python wan22_test.py --preset draft      # 草稿档 832x480 / 81帧
    python wan22_test.py --preset final      # 正式档 1280x704 / 121帧
    python wan22_test.py --preset draft --no-lora   # 不用 Turbo LoRA（20步对照）

产出：下载到 ./out/ 并打印实际路径与耗时。
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HOST = os.environ.get("COMFYUI_HOST", "http://127.0.0.1:8188")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

MODEL = "wan2.2_ti2v_5B_fp16.safetensors"
CLIP = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VAE = "wan2.2_vae.safetensors"
TURBO_LORA = "Wan22_TI2V_5B_Turbo_lora_rank_64_fp16.safetensors"

NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
    "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
    "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，"
    "杂乱的背景，三条腿，背景人很多，倒着走"
)

# 场景与 H3 第二轮实测（h3_dialog_test.json）完全同源，仅做两点改动：
#   1) 去掉台词与音频描述 —— Wan 无原生音频
#   2) 去掉「左眉浅疤」—— 体系已记录该特征会被渲染成眉上竖痕
PROMPT = (
    "Live-action cinematic photorealistic 35mm film, shallow depth of field, "
    "fine film grain, muted teal-and-amber night palette. "
    "Interior of a tiny late-night noodle stall on a rain-wet street at one in the morning: "
    "a narrow chipped laminate counter, a dented steel stockpot simmering on one burner, "
    "a single bare bulb hanging from a cord swinging slowly, steam curling through warm amber light, "
    "blue neon from a sign across the street reflected in the puddles outside. "
    "A woman in her late twenties, heart-shaped face, shoulder-length black hair tucked behind one ear, "
    "faint freckles across the nose, small gold hoop earrings, a faded olive apron over a white t-shirt "
    "with sleeves rolled to the elbows. "
    "Medium shot, camera at counter height on the customer side, she faces camera straight on for the entire shot. "
    "She slides the steel shutter halfway down behind her, turns back, picks up a rag and wipes the counter slowly, "
    "stops, lays both hands flat on the counter and breathes out, then looks straight into the lens "
    "and gives a small tired smile that fades."
)

FPS = 16  # Wan 系列训练帧率，勿改。改回 24 会让成片加速 1.5 倍。

PRESETS = {
    "draft": dict(width=832, height=480, length=81, steps=4, cfg=1.0,
                  sampler="euler", scheduler="simple", shift=8.0, lora=1.0),
    "final": dict(width=1280, height=704, length=121, steps=4, cfg=1.0,
                  sampler="euler", scheduler="simple", shift=8.0, lora=1.0),
    "final_nolora": dict(width=1280, height=704, length=121, steps=20, cfg=5.0,
                         sampler="uni_pc", scheduler="simple", shift=8.0, lora=None),
}


def build(preset, seed):
    p = PRESETS[preset]
    g = {
        "37": {"class_type": "UNETLoader",
               "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "38": {"class_type": "CLIPLoader",
               "inputs": {"clip_name": CLIP, "type": "wan", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "48": {"class_type": "ModelSamplingSD3",
               "inputs": {"model": ["37", 0], "shift": p["shift"]}},
        "6": {"class_type": "CLIPTextEncode",
               "inputs": {"clip": ["38", 0], "text": PROMPT}},
        "7": {"class_type": "CLIPTextEncode",
               "inputs": {"clip": ["38", 0], "text": NEGATIVE}},
        "55": {"class_type": "Wan22ImageToVideoLatent",
               "inputs": {"vae": ["39", 0], "width": p["width"], "height": p["height"],
                          "length": p["length"], "batch_size": 1}},
        "8": {"class_type": "VAEDecode",
               "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        # ⚠️ fps 必须为 16：Wan 系列模型以 16fps 训练（证据见
        # ComfyUI comfy_extras/nodes_wan.py 中 "model trained with 16 fps" 注释）。
        # 官方模板 video_wan2_2_5B_ti2v.json 的 CreateVideo 填的是 24，会导致
        # 成片被加速 1.5 倍（121帧：真实 7.56s → 封成 5.04s），动作显得急躁。
        "57": {"class_type": "CreateVideo",
               "inputs": {"images": ["8", 0], "fps": FPS}},
        "58": {"class_type": "SaveVideo",
               "inputs": {"video": ["57", 0],
                          "filename_prefix": f"video/WANTEST/{preset}",
                          "format": "auto", "codec": "auto"}},
    }
    model_in = ["48", 0]
    if p["lora"] is not None:
        g["60"] = {"class_type": "LoraLoaderModelOnly",
                   "inputs": {"model": model_in, "lora_name": TURBO_LORA,
                              "strength_model": p["lora"]}}
        model_in = ["60", 0]
    g["3"] = {"class_type": "KSampler",
              "inputs": {"model": model_in, "positive": ["6", 0], "negative": ["7", 0],
                         "latent_image": ["55", 0], "seed": seed,
                         "control_after_generate": "fixed", "steps": p["steps"],
                         "cfg": p["cfg"], "sampler_name": p["sampler"],
                         "scheduler": p["scheduler"], "denoise": 1.0}}
    return g


def post(path, payload):
    req = urllib.request.Request(
        HOST + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def get(path):
    with urllib.request.urlopen(HOST + path, timeout=30) as r:
        return json.load(r)


def submit(prompt, client_id):
    return post("/prompt", {"prompt": prompt, "client_id": client_id})


def wait(pid, log_every=30):
    t0 = time.time()
    last = 0
    while True:
        try:
            h = get("/history/" + pid)
        except Exception:
            h = {}
        if pid in h:
            return h[pid], time.time() - t0
        el = time.time() - t0
        if el - last >= log_every:
            print(f"  ... 运行中 {el:.0f}s", flush=True)
            last = el
        if el > 3600:
            raise TimeoutError("超过 1 小时，放弃")
        time.sleep(5)


def download(item, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    saved = []
    for node_out in item.get("outputs", {}).values():
        for key in ("video", "images", "gifs"):
            for f in node_out.get(key, []) or []:
                fn, sub, typ = f.get("filename"), f.get("subfolder", ""), f.get("type", "output")
                qs = urllib.parse.urlencode({"filename": fn, "subfolder": sub, "type": typ})
                dest = os.path.join(dest_dir, os.path.basename(fn))
                with urllib.request.urlopen(f"{HOST}/view?{qs}", timeout=300) as r, \
                        open(dest, "wb") as fh:
                    fh.write(r.read())
                saved.append(dest)
    return saved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="draft", choices=list(PRESETS))
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    p = PRESETS[a.preset]
    print(f"[配置] {p['width']}x{p['height']} / {p['length']}帧 "
          f"= {p['length']/FPS:.2f}s @ {FPS}fps / {p['steps']}步 / cfg {p['cfg']} / "
          f"{p['sampler']}+{p['scheduler']} / shift {p['shift']} / "
          f"TurboLoRA {p['lora']}")

    g = build(a.preset, a.seed)
    r = submit(g, "wan-test")
    if "error" in r:
        print("[提交失败]", json.dumps(r, ensure_ascii=False)[:1500])
        return 1
    pid = r["prompt_id"]
    print(f"[已提交] prompt_id={pid}")

    item, el = wait(pid)
    print(f"[完成] 耗时 {el:.1f}s")

    status = item.get("status", {})
    if status.get("status_str") == "error":
        for m in status.get("messages", []):
            for sub in m:
                if isinstance(sub, str) and ("Error" in sub or "error" in sub):
                    print("[运行出错]", sub[:1200])
        return 1

    dest = os.path.join(OUT, a.preset + (a.tag and ("_" + a.tag) or ""))
    files = download(item, dest)
    if not files:
        print("[警告] 没有取到产物，原始 outputs：",
              json.dumps(item.get("outputs", {}), ensure_ascii=False)[:800])
        return 1
    for f in files:
        print(f"[产出] {f}  ({os.path.getsize(f)/1048576:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
