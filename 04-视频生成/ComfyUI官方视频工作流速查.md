---
name: ComfyUI官方视频工作流速查
description: 118 个 ComfyUI 官方视频工作流模板的索引与获取入口（文生视频/图生视频/首尾帧/视频重绘/角色替换/姿态迁移等），含选型决策树、模型依赖、默认参数与导入方法。本包只提供索引，不随附模板 JSON。第4阶段「视频生成」在本地 ComfyUI 出片时的首选形态来源——先选模板再改提示词，不要从零搭节点。
---

> **按需适配资料**：本文件保留具体实现/来源的操作方法、语法与经验，不是所有项目的前置条件。只有选择相应实现或资料源时才加载；未选实现先按通用方法和《能力登记.md》决策。版本参数沿用原记录，2026-10-03 仅整理边界，未重新核验；实际执行前确认当前能力、成本和授权，不能将教程中的品牌、账号、路径或规格写回通用模板。


> **体系定位**：本 skill 属于【短剧成片体系】第 4 阶段「视频生成」。上游：02-分镜与镜头（拆好的镜头）、03-角色与视觉资产（角色定妆与场景设定）；下游：05-音频、06-后期与发布。
> **配套**：`视频实现适配.md`（历史实现提示词语法，使用前复核）、`Seedance适配.md`（量产路线）、`重抽与回退决策.md`（出废片怎么办）。
> **本文件解决的是**：本地 ComfyUI 跑视频时，**用哪个现成工作流**。本文件提供官方模板索引与获取入口，不随附模板 JSON；实际可用模板的位置与版本以项目《能力登记.md》为准。

# ComfyUI 官方视频工作流速查

## 零、先说结论

**不要从零搭 ComfyUI 视频工作流。** 官方 118 个模板覆盖了绝大多数形态，按索引取得模板后直接改提示词即可。

先按本文件的镜头形态决策树确定所需工作流类型，再通过能力登记确认本机对应模板是否已落地。制作 Agent 不进入外部采集库挑选风格或脚本；缺模板时按能力路由协议处理，不在制作流程中临时运行采集器。

每个 JSON 都是标准 ComfyUI workflow 格式，**采用 `definitions.subgraphs` 子图结构，需 ComfyUI 0.20+**。直接拖进画布即可展开。

---

## 一、按镜头形态选模板（决策树）

先看第 2 阶段拆出来的镜头属于哪一类，再对号入座：

| 你的镜头形态 | 选这个模板 | 节点数 |
|---|---|---|
| 一句话生成一段视频（无首帧） | `Text to Video (LTX-2.5)` | 43 |
| 一句话生成一段视频（要 LoRA 控制） | `Video Generation (LTX-2.3 IC-LoRA)` | 31 |
| 已有首帧，要动起来 | `Image to Video (LTX-2.5)` | 48 |
| 已有首帧，要人物跳舞 | `Image to Video (Wan Dancer)` | 72 |
| 已有首帧，要精确动作迁移 | `Pose to Video (LTX 2.0)` | 41 |
| 已有首帧 + 尾帧 | `First & Last Frame to Video (LTX-2.5)` | 40 |
| 只有首帧，模型走 Wan | `First-Last-Frame to Video` | 33 |
| 局部重绘（换脸/换衣/去路人） | `Video Inpaint (VOID)` | 41 |
| 局部重绘（Wan 路线） | `Video Inpainting (Wan2.1 VACE)` | 40 |
| Wan 路线首尾帧 | `FLF2V (Wan2.1 VACE)` | 38 |
| 整体视频编辑 | `Video Edit (Bernini-R)` | 39 |
| 单图编辑（出分镜板时用） | `Image Edit (Bernini-R)` | 37 |
| 把 A 角色的动作搬到 B 角色 | `Character Replacement (SCAIL-2 Base)` | 43 |
| 角色替换要长时长 | `Character Replacement (SCAIL-2 Extend)` | 46 |
| 角色替换要省显存 | `Character Replacement (SCAIL-2 Int8 Base)` | 43 |
| 从深度图生成视频 | `Depth to Video (ltx 2.0)` | 57 |
| 从边缘图生成视频（保住轮廓） | `Canny to Video (LTX 2.0)` | 40 |
| 图像转姿态再生成 | `Image to Pose Map (SDPose-OOD)` | — |
| 抠像 | `Image Segmentation (SAM3)` / `Video Segmentation (SAM3)` | — |
| 深度估计 | `Image Depth Estimation (MoGe)` / `Video Depth Estimation (MoGe)` | — |
| 法线估计 | `Image Normal Estimation (Marigold V2)` | — |
| 出图（分镜首帧） | `Text to Image` / `Text to Image (Anima)` | — |
| 配乐生成 | `Audio Generation (Stable Audio 3 Medium)` | — |
| 拼九宫格 | `Crop Images 3x3` | — |
| 超分前处理 | `Unsharp Mask` / `Sharpen` | — |
| 调色 | `Color Balance` / `Color Curves` / `Hue and Saturation` | — |
| 亮度对比 | `Brightness and Contrast` | — |
| 大图切片推理 | `Split Image Grid to Tiles` | — |

---

## 二、三条主力路线的取舍

体系里视频生成有三条路，**先决定走哪条，再选模板**：

### 路线 A：云端平台（即梦 / Seedance / H3）
- 优点：不用管模型和显存，出片快
- 缺点：单次时长受限（H3 单次只吃 4–15 秒，见 `02-分镜与镜头/分镜工作流.md` §十一 弹性拆镜与生成段规划）
- 对应文档：`Seedance适配.md`、`平台提示词契约.md`

### 路线 B：本地 ComfyUI（本文件）
- 优点：模型自控、工作流可存可复用、出片成本是电费
- 缺点：要装模型、吃显存、调节点
- **选模板原则**：形态对上就直接用官方模板，别自己接

### 路线 C：零成本路线（剪辑拼镜头）
- 优点：完全免费
- 缺点：没有真正的运动生成
- 适用：`02-分镜与镜头` 拆出来的镜头里，静态美术镜头占多数时

---

## 三、模板里自带的东西（别忽略）

每个模板的 `widgets_values` 里已经预填了三类信息，直接抄：

1. **模型文件名** — 精确到 `.safetensors`，照着准备模型
   例：`wan2.2_dancer_14b_global_fp8_scaled.safetensors`
2. **默认提示词** — 官方给的示范值，是该形态的提示词骨架
   例：`Latin Dance 拉丁舞`
3. **默认参数** — 分辨率、时长、步数等起始值

节点数差异很大（20–72），**节点多不等于效果好**。选的时候看形态匹配度，不看节点数。

---

## 四、导入与改写步骤

1. 把对应 JSON 拖进 ComfyUI 画布（需 ComfyUI 0.20+，低版本会因不支持子图而加载失败）
2. 检查 `Load Checkpoint` / `UNETLoader` 节点引用的模型文件是否已下载到 `models/` 对应目录
3. **先跑一次默认参数**，确认能出片，再改提示词——不要一上来就调参数
4. 改提示词时，参考体系内 `平台提示词契约.md` 的中文分段写法
5. 出片参数不满意，走 `重抽与回退决策.md` 的判断流程，不要盲目重抽

---

## 五、显存与速度的现实预期

| 路线 | 模型 | 参考体量 |
|---|---|---|
| LTX 系列 | LTX-2.3 / 2.5 | 轻量，速度优先 |
| Wan 系列 | wan2.2 dancer 14B fp8 | 较重，需要较大显存 |
| SCAIL-2 | Base / Extend / Int8 | Int8 是省显存变体 |
| VACE | Wan2.1 VACE | 较重 |

官方模板多已用 `fp8_scaled` 量化权重，**下载时认准 fp8 后缀**，能省一半以上显存。

---

## 六、配套资源

- 模板能力与本机落地状态：查项目《能力登记.md》；具体实现由项目能力登记维护，不在 SOP 固定外部数据源路径。
- 配套提示词素材：由 Agent 根据导演意图、平台契约和项目资产自主编写，并通过提示词预检；不默认调用外部提示词库。
- 分镜九宫格与批量出图：`02-分镜与镜头/分镜工作流.md` §十四

---

**获取说明**：118 个模板来自官方 ComfyUI 工作流库（索引核验 2026-09-30）。本包只提供索引与获取入口，不随附 workflow JSON；需要模板时从官方来源取得，并按项目《能力登记.md》登记版本与参数。
