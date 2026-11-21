# 《第一次呼吸》动态视频实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 Remotion 与 HyperFrames 把《第一次呼吸》的冻结剧本、分镜和源图制作成 90 秒横屏动态成片。

**Architecture:** Remotion 作为最终渲染时间线，使用 React 组件表达 22 刀和视觉层；HyperFrames 作为并行 HTML/GSAP 动效源稿，负责设计预览与音频响应验证。程序化 WAV 作为双引擎共用的连续音频轨。

**Tech Stack:** Remotion 4, React, HyperFrames 0.8, GSAP, Python wave synthesis, FFmpeg.

## Global Constraints

- 画幅固定为 1920×1080，30fps，时长 90 秒。
- 使用项目冻结的四张源图，不改变 G0 风格锁和 G3 镜头节奏。
- 音频为一条连续轨，包含心跳、呼吸、低频持续音和环境层。
- 交付前必须运行 Remotion bundle、HyperFrames lint/check 和 FFprobe 质检。

### Task 1: 建立双引擎项目

**Files:**
- Create: `00-视频项目/《第一次呼吸》/06-成片/remotion/package.json`
- Create: `00-视频项目/《第一次呼吸》/06-成片/remotion/src/Root.jsx`
- Create: `00-视频项目/《第一次呼吸》/06-成片/remotion/src/index.jsx`
- Create: `00-视频项目/《第一次呼吸》/06-成片/hyperframes/index.html`
- Create: `00-视频项目/《第一次呼吸》/06-成片/hyperframes/DESIGN.md`

- [x] 建立 Remotion composition `FirstBreath`，注册 2700 帧、30fps、1920×1080。
- [x] 建立 HyperFrames root composition `first-breath`，登记 90 秒、3 条轨道与场景时间属性。

### Task 2: 实现镜头视觉

**Files:**
- Create: `00-视频项目/《第一次呼吸》/06-成片/remotion/src/FirstBreath.jsx`
- Read: `00-视频项目/《第一次呼吸》/03-分镜/分镜表.md`
- Read: `00-视频项目/《第一次呼吸》/00-立项/风格提案.md`

- [x] 把 22 刀映射为 Remotion shot components。
- [x] 加入粒子、颗粒、扫描线、暗角、推拉、视差和光带转场。
- [x] 使用源图完成星云、细胞、城市、瞳孔的主要视觉锚定。

### Task 3: 生成与接入声音

**Files:**
- Create: `00-视频项目/《第一次呼吸》/06-成片/remotion/scripts/generate_audio.py`
- Create: `00-视频项目/《第一次呼吸》/06-成片/remotion/public/audio/first-breath-mix.wav`
- Create: `00-视频项目/《第一次呼吸》/06-成片/hyperframes/audio-data.json`

- [x] 生成 90 秒 48kHz 双声道 WAV。
- [x] 将音频接入 Remotion，并从音频生成 HyperFrames 帧级能量数据。
- [x] 在 HyperFrames 中用 RMS 能量调制粒子幅度。

### Task 4: 验证与交付

**Files:**
- Create: `00-视频项目/《第一次呼吸》/06-成片/成片_v1.mp4`
- Create: `00-视频项目/《第一次呼吸》/06-成片/导演证据/ffprobe.json`
- Create: `00-视频项目/《第一次呼吸》/06-成片/导演证据/抽帧/*.jpg`

- [x] Remotion bundle 通过。
- [x] Remotion 抽帧通过。
- [x] HyperFrames lint 无错误，check 无错误。
- [x] FFprobe 确认 H.264、1920×1080、30fps、90 秒和 AAC 双声道。
- [x] 抽查 0s、55s、85s、89s 画面。
