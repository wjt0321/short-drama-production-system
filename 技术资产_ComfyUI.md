# 技术资产 · ComfyUI（出图 / BGM / 自动化通道本机实测）

> **执行层档案（2026-10-12 由《技术资产_环境事实.md》按平台拆出）**：原文保留本机使用经验、参数和失败案例，不构成供应商保证或通用生产规范。本次只拆文件，**未重新运行任何工作流**；原记录缺少版本、样本或验证日期时，使用前补核验，不以整理日期充当实测日期。具体实现与路径索引见 `能力登记.md`。
>
> **节号沿用原文件编号**（跳号 = 该节在另外两份文件里），便于旧引用与项目登记逐条对照。
>

## 〇、内核版本口径（2026-10-23 更新）

| 项 | 值 |
|---|---|
| ComfyUI | **0.42.4**（2026-10-23 由 0.37.0 升级；分支 `upgrade-v0424`，回滚点 `master` 保留） |
| torch | **2.11.0+cu130**，升级前后未变 —— **cu128 会让 comfy-kitchen 优化后端失效，H3 从 5 分钟变 27 分钟** |
| 节点总数 | 1582（H3 相关 197） |
| 本地补丁 | `comfy_extras/nodes_minimax_h3.py` 的 `first_frame` 改 `"center"`（防拉伸）。**上游至今未采纳，每次升级 git 会覆盖，升完必查这一行** |
| 0.37→0.42.4 依赖差异 | 仅 8 个包，**不含 torch**；`pip install -r requirements.txt` 前先 `--dry-run` 确认 torch 是 already satisfied |

**0.42.4 带来的本机可用新能力**：H3 LightVAE（解码权重 2677MB→781MB）、Qwen-Image 2.1 Turbo（4 步）、FLUX.2 Klein 4B 本地权重、原生 LoRA Stack、CameraAngle 镜头提示词。

---

> **本文含**：§一 ComfyUI 出图（Qwen-Image2.1）· §三 BGM（YuE2）· §十 Agent 自动化通道（本地 ComfyUI MCP）。
> **其余两份**：MiniMax H3 / Ref2VA 与显存容量 → `技术资产_H3.md`；ffmpeg 装配 / 质检闸元规则 / 脚本转义陷阱 / 耗材路径 / 配音 / 已弃用能力 / 行业实证 → `技术资产_通用.md`（现役生成尺寸 1344×768 与 768×1344 记在该处）。
> 本文只放**环境事实**，不涉及创作判断；路径一律写相对形式，绝对位置见 `能力登记.md`。创作方法论见本体系的 `AGENTS.md`（G0–G6 关卡；通用生产编排规范已并入其中）。

---

## 一、ComfyUI 出图（Qwen-Image2.1）

| 事实 | 说明 |
|---|---|
| **默认出 1024×1024 方图** | 即使提示词写 16:9。必须用 `EmptyLatentImage(width, height)` 显式钉 `1344×768` |
| **`resolution` 不是尺寸开关** | API 模式下 `resolution` 是**必填**（GUI 有默认值，API 没有），但**填它不改变输出尺寸**。省掉会报 `prompt_outputs_failed_validation: Required input is missing: resolution` |
| **API 模式下 `images` 是 autogrow 字典** | 必须传 `{"image_1": ["8", 0]}`；传 list 或 `["节点", 0]` 都不被接受 |
| **验收不能信参数** | 每张出图后立刻 `Image.Width/Height` 打印实测值 |
| 现役权重 | UNET `qwen_image_2.1_int8_convrot.safetensors` / TE `qwen3vl_8b_int8_convrot.safetensors` / VAE `qwen_image_2.1_vae_bf16.safetensors`；KSampler 25 步 / cfg 1 / euler / simple |
| **⭐ Turbo 8 步版（2026-10-23 实测通过，取代 25 步版）** | UNET `qwen_image_2.1_turbo_int8_convrot.safetensors`（6.76GB）；节点链 `UNETLoader → CLIPLoader(qwen_image) → TextEncodeQwenImage21 → EmptyLatentImage → ManualSigmas → KSamplerSelect(euler) → RandomNoise → CFGGuider(cfg=1) → SamplerCustomAdvanced → VAEDecode → SaveImage`；**sigma 串固定 `1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0`**（8 档，不要改成普通 4 步） |
| Turbo 速度 | **1344×768 首图 45.1s（冷启动）/ 12.1s（热启动）**。热启动后单张 12 秒，意味着可以 "出 5 张挑 1 张" 而不心疼 |
| Turbo 出图质量 | 人物立体、光影专业、皮肤纹理真实、**不挂招牌**（前提是场景选无市井的地方——焦土/海底/宫殿）；中文文字仍未验证 |
| **FLUX.2 Klein 4B（2026-10-23 实测通过，采样配置已修正）** | UNET `flux-2-klein-4b.safetensors`（7.22GB）/ TE `qwen_3_4b_fp4_flux2.safetensors`（3.58GB）/ VAE `flux2-vae.safetensors`（0.31GB）；节点链 `UNETLoader → CLIPLoader(type=flux2) → CLIPTextEncode → EmptyFlux2LatentImage → Flux2Scheduler(4~8步) → KSamplerSelect(euler) → RandomNoise → BasicGuider → SamplerCustomAdvanced → VAEDecode → SaveImage` |
| **⚠️ Klein 的两个变体不能混用配置（踩过的坑）** | 本机权重是 **distilled 版**（官方 model card："our fastest distilled model"，推荐 `guidance_scale=1.0` / `num_inference_steps=4`）→ 必须 `BasicGuider` **无 CFG** + 4~8 步。ComfyUI 官方 blueprint `Image Edit (Flux.2 Klein 4B).json` 里的 `CFGGuider(cfg=5)` + `Flux2Scheduler(20步)` 配的是 **`flux-2-klein-base-4b-fp8`**（非蒸馏 base 变体），照抄到这个权重上画面会变成**塑料娃娃**：饱和度 40.8%（错误配置）vs 34.2%（4 步）vs 30.1%（8 步），质感发死、皮肤无软组织感 |
| FLUX.2 Klein 速度 | **1344×768：4 步 33.2s / 8 步 12.1s（热启动）**。8 步是性价比档 |
| **⭐ 生图选型终判（用户 2026-10-23）** | **Qwen-Image 2.1 Turbo 独一档，FLUX.2 Klein 4B 不进任何交付链路。** 用户原话：「生图还是千问独一档，毋庸置疑，flux 不合适」。即使把 Klein 的采样配置改对（无 CFG + 4~8 步），它仍只到「能看的草图」水平，与 Qwen 差距是**档位的差距**，不是参数可调的差距。结论：**本地生图只有一个候选，不要再花时间给 FLUX 找调参。** Klein 权重保留只作对照与 AB 参考 |
| **两个模型怎么分工（同题同尺寸+同 seed 实拍对比，2026-10-23 修正）** | Qwen Turbo → **电影剧照质感**，皮肤有软组织、光比有层次，**入片只用它**；FLUX.2 Klein 4B → 4B 蒸馏模型，官方定位是"亚秒级交互预览"，即使配置正确也**差一档**：人物偏儿童比例、脸是塑料玩偶感、光影层次薄。⚠️ 上一版说它"指令遵循更强、五件标志物一次给全"**不成立**——实测它同样把风火轮画成马车轮、把"bare-chested under a vest"画成穿了红衣 |

### 伪汉字：否定式约束**完全无效**（最重要的一条）

Qwen-Image2.1 对"宋代街市"有**必挂招牌的强先验**。实测**连续 5 张**在门柱/店面出清晰汉字，
而提示词里**已经**写了 `readable characters` / `kanji signage` / `any lettering on banners or signs`，
常量里**已经**写了 `no signboard` —— **一条都没压住**。

**唯一有效的解法是正面改构图（三件套）**：
1. `BARE`：`bare plain weathered grey brick and bare unpainted dark timber` +
   `the surfaces are completely blank, smooth and unmarked` + `nothing at all hangs on the walls`
2. 背景**大光圈虚化**：`thrown far out of focus by a wide aperture so no detail is sharp back there`
3. `BLANK`：`completely blank, completely unmarked, no writing, no characters, no symbols`

**绝对禁止后期 gblur 遮字** —— 实测糊出明显矩形方块边，比有字更假，ffmpeg rc=0 零报错。

**判定尺度**：招牌 ≤20×35 像素且不可辨认 = 可接受；≥40 像素或可辨认字形 = 判废重搓。

---

---

## 三、BGM（YuE2）

| 项 | 值 |
|---|---|
| 权重 | `yue2_3b_int8_convrot.safetensors` + `ar_lora_inst_v3abc_comfyui.safetensors` + `nar_lora_joint_v4_comfyui.safetensors` |
| 歌词 | **必须锁 `[instrumental]`**，改了就出人声 |
| 采样 | 32 步 / cfg 1 / dpm_2 / sgm_uniform（官方配方，不动） |
| 潜空间 | `EmptyYuE2LatentAudio.seconds` 接 `YuE2GenerateMusic` 的 **1 号输出** |
| `top_p` | 最大 1.0（GUI 里的 1.2 是旧值，越界报错） |
| 时长 | 只改 `YuE2GenerateMusic.max_duration` |
| 机时 | 80s 音乐 ≈ 55s 生成 |

### 调性判定（`bh_key.py`，Krumhansl-Schmuckler + Chroma）
**光写 `MAJOR KEY` 不足**，必须写全这四句：
```
MAJOR KEY ONLY, C MAJOR, simple diatonic major harmony,
no modulation, no borrowed chords, definitely NOT minor, no minor tonality
+ "the melody stays clearly in C major"
```
且**先删小调触发器**：`serene / intimate / dusk / quiet / sparse / slow / gentle / mellow / dreamy`

> 实测：只写 `BRIGHT MAJOR KEY, D major` → 仍出 E 小调 r=0.903。
> 写全四句 → C 大调 r=0.951。**不验调性不算完成**，门槛 r > 0.85。

---

---

## 十、Agent 自动化通道（本地 ComfyUI MCP）

> 登记于 2026-10-07：已在本机装好并绑定工作区。
> **同日已手工握手验证通过**（以 stdio 直连调用）：服务正常运行，`server_info` 返回
> ComfyUI `running=true`、地址 `127.0.0.1:8188`、工作区指向本机那份、显卡识别为 RTX 3070 / 8GB，
> 且 python 可执行文件指向**隔离的那个 venv**（证明没污染 ComfyUI 自身环境）。
> **尚未跑过真实出图出视频**（未提交任何工作流），批量效果待实测。
> 本节只记环境事实与踩坑，创作流程不依赖它存在——这是可选实现，不是体系依赖。

| 事实 | 说明 |
|---|---|
| **通道本体** | 官方 `comfy-mcp`（PyPI），底层是 `comfy-cli`；装在**独立虚拟环境**（与 ComfyUI 同级的 `comfy-mcp-env`），**没有污染 ComfyUI 自己的 `.venv`** |
| **工作区绑定** | `comfy set-default <ComfyUI 目录>` 写进 comfy-cli 配置；`comfy which` 可验证指向 |
| **默认启动参数已固化** | `set-default --launch-extras "--lowvram --enable-manager"`，防止默认启动丢掉 8GB 显存优化 |
| **`COMFY_BIN` 必须显式填** | MCP 客户端用自己的精简环境起服务，**不继承 shell 的 PATH**。不填的表现是"每个工具调用都报 comfy not found"，看着像 MCP 坏了，其实是找不到引擎 |
| **ComfyUI 必须先手动启动** | 服务本身不会偷偷起 GPU 进程。用本机自己的启动脚本起（它同时设了 HF/Torch/uv 缓存目录）；**不要让 Agent 调 `launch_comfyui`**——那条路径不带这些环境变量，可能触发权重重新下载 |
| **最常用的四个工具** | `server_info`（确认活没活）→ `validate_workflow`（对活着的 object_info 预检）→ `run_workflow` → `fetch_outputs` |
| **本地相对云端的独家优势** | `search_nodes` / `search_models` 读的是**本机真实安装，含自定义节点**。Agent 装配工作流时不再靠猜通用 ComfyUI 的输入输出 |
| **真实工具清单（本机枚举到 39 个）** | 除上面四个外，值得记的还有：`nodes`（列本机节点）、`node_dependencies` / `workflow_deps`（查工作流缺哪些节点）、`validate_workflow`（跑前预检）、`search_models`、`install_node`、`generate_image`（带 poptle 直出，不用拼工作流）、`job`（查/等/取消）、`fetch_outputs`（拉产出到指定目录） |
| **批量岔干活要用的一组** | `list_workflow_slots` → `set_workflow_slot`（把一份工作流钉成"槽位"）→ `vary_workflow`（在槽位上变参数重跑）。**这是"按分镜批量出图出视频"的现成结构**：先钉住 Qwen Image 2.1 和 H3 各一个槽位，之后每镜只变提示词与 seed，不用重新拼图 |

**为什么值得记**：8GB 显存上跑一次视频三分钟起步，Agent 拼错一个节点输入就白等。
`validate_workflow` 的价值不是省时间，是**不浪费显存**。

---
