---
name: Qwen3-8B-Drama-Thinking 调研结论
description: 对 FutureMa/Qwen3-8B-Drama-Thinking 剧本专用微调模型的完整调研（2026-10-25）。含模型真实性核实、体积与量化可得性、llama.cpp 兼容性、作者自评与 DramaBench 第三方榜单的对照、对你短剧项目的适用性判断与落地步骤。结论：暂不建议引入，与双模型接力流水线重叠且有硬伤。
---

> **定位**：本文件是一次**选型调研的存档**，不是 SOP。规则的唯一权威仍是 `短剧编剧引擎.md`。
> **调研日期**：2026-10-25
> **调研动机**：DeepSeek 推荐该模型为"现成的剧本创作模型"。
> **配套**：`tools/双模型接力编剧流水线.md`（本机已验证的替代方案）。

# 一、结论先行

**暂不建议引入。** 三个硬理由：

1. **功能与既有流水线重叠**——本机 `Qwen3.5-9B + Gemma-4-E4B` 接力流水线已跑通，且更贴你的中文短剧规范。
2. **模型卡自陈不适配**——作者明确写 "❌ Not Recommended For: Comedy/Action Genres"，且训练数据"skews toward melodramatic scenarios"（偏戏剧化），"Less suited for subtle/realistic dialogue"。你的主力项目《离谱日常》是**合租日常喜剧**，正面撞上这条否决项。
3. **获取成本与硬件不匹配**——GGUF 只有 Q8_0（8.11 GB），**单文件就超过你 8GB 显存**，且无 Q4/Q5 降级版；魔搭无 GGUF 镜像，只能走 hf-mirror（实测 3.4 MB/s）。

# 二、模型是真的，参数核实

| 项 | 实测值 |
|---|---|
| 仓库 | `FutureMa/Qwen3-8B-Drama-Thinking`（HF） |
| 下载 / 赞 | 46 / 86（HF）；魔搭 136 下载 |
| 底模 | `Qwen/Qwen3-8B` |
| 训练方式 | **全参数微调**（非 LoRA），ms-swift 框架，DeepSpeed Zero3 |
| 训练数据 | 自建 `custom-drama-thinking-dataset`，6319 条，平均约 5000 tokens |
| 训练开销 | 2×H100 80G，2h46m，3 epoch，$17.86 |
| 关键超参 | max_length 8192、lr 1e-5、`template: qwen3_thinking`、`loss_scale: ignore_empty_think` |
| 语言 | `en` + `zh`（中英双语，模型卡标注） |
| 配套 | `FutureMa/DramaBench` 数据集（265 下载 / 111 赞）+ arXiv:2512.19012（澳门大学 + UCL） |

**模型是真的，中英双语，训练方法规范。** 它是 DeepSeek 推荐里少见的、质量有据可查的一个。

# 三、致命细节：87% 的输出是思考链

作者自陈的限制：

> **Thinking Verbosity**: Generates ~3,400 tokens of thinking (**87% of output**)
> **Incomplete Execution**: Token budget consumed by thinking — many planned scenes not fully generated
> 需要 6,000–8,000 token 限制才能出完整剧本

**这与本机已验证的配置直接冲突。** 本机实测（2026-10-25）：
开着 thinking 写一段 150 字场景，输出 **7217 tokens / 129 秒**；关掉 thinking 只要 **96 tokens / 2.5 秒**，质量无差别。

该模型是**为思考链而生的**（`loss_scale: ignore_empty_think`、训练数据全是带 `<think>` 的样本）。
也就是说：它的强项恰好是本机场景下**最该关掉的东西**。
要用好它，就得接受每场戏花 3000+ token 的思考时间；要在 8192 上下文里出 2 场戏，
思考链会直接吃掉预算——这正是你引擎里"正文不写解释"的反面。

# 四、第三方榜单：它自己没上榜

DramaBench（arXiv:2512.19012，1103 个剧本 / 8824 次评测 / 6 维度 / 252 次显著性检验）
评测的 8 个模型是：

| 排名 | 模型 |
|---|---|
| #1 | GPT-5.2 |
| #2 | Gemini 3 Pro |
| #3 | Qwen3-Max |
| #4 | Claude Opus 4.5 |
| #5 | DeepSeek V3.2 |
| #6 | MiniMax M2 |
| #7 | Kimi K2 Thinking |
| #8 | GLM-4.6 |

**Qwen3-8B-Drama-Thinking 不在其中。** 模型卡上那个 8.1/10 的分数，
作者自己注明是 **LLM-as-a-Judge（用 Claude 当裁判）自评 vs 底模**，
不是独立第三方评测，与 DramaBench 的结论不可比。

DramaBench 的 6 个维度里有 3 个恰好对应你的验收标准，值得借来做自检量表：
Format Standards（格式）、Character Consistency（角色一致性）、
Logic Consistency（逻辑一致性）—— 加上 Emotional Depth、Conflict Handling、Narrative Efficiency。

# 五、硬件与获取

| 项 | 情况 |
|---|---|
| BF16 原始权重 | 15.3 GB（4 个 safetensors） |
| 唯一 GGUF 量化 | `Sorawiz/...-Q8_0-GGUF` = **8.11 GB**（372 下载） |
| 更低量化 | **无**（没有 Q4/Q5/IQ4 版本） |
| 魔搭 | 有 safetensors（136 下载），**无 GGUF** |
| llama.cpp 兼容 | ✅ chat_template 是标准 ChatML，llama.cpp 可解析；`<think>` 标签 llama.cpp 原生支持 |

**8.11 GB 的 Q8_0 单文件 > 你的 8 GB 显存**。要跑必须：
- 用 `Sorawiz` 的 Q8_0（8.11GB）→ 权重占满 8GB 显存，KV cache 无处放 → 需部分层留 CPU
- 或自己从 safetensors 转 Q4（魔搭有 safetensors，39.4 MB/s 很快），但**转出来的质量没有第三方验证**

# 六、为什么本机已有方案更合适

`tools/双模型接力编剧流水线.md` 的三棒设计（Qwen 出结构 → Gemma 加表演 → Qwen 拆比喻）
解决的正是该模型想解决、但做不到位的问题：

| 需求 | Drama-Thinking | 本机三棒流水线 |
|---|---|---|
| 结构与因果链 | ✅ 强（thinking 里有三幕规划） | ✅ Qwen 第 1 棒直接产出四句因果 |
| 表演细节 / 潜台词 | ⚠️ 偏文学化，作者自陈"更直接或文学化，不像口语" | ✅ Gemma 第 2 棒专门加厚 |
| 格式（不写 PPT 五块） | ✅ 强（Fountain 校验，Format 9/10） | ✅ 模板强制连续段落 |
| 角色不跑偏 | ✅ 强 | ✅ 第 2 棒人物名单封闭 + 第 3 棒复核 |
| 速度 | ❌ 每场 3000+ token 思考 | ✅ 60–82 tok/s，全场 3–8 秒 |
| 中式喜剧 / 日常质感 | ❌ 作者明确不推荐 | ✅ Gemma 实测强项 |
| 适配你的因果四句 / 种子落点 | ❌ 无此概念 | ✅ 直接吃你的引擎规范 |

**该模型真正领先的地方只有"结构化思考"**——而你引擎 §10.2 的因果四句模板
已经把这件事标准化了，不需要模型自己在脑子里跑三幕。

# 七、如果还是要试，落地步骤

按这个顺序做，失败可随时停：

1. **从魔搭拉 safetensors 转 Q4**（不要用 8.11GB 的 Q8_0）
   ```
   https://modelscope.cn/models/FutureMa/Qwen3-8B-Drama-Thinking
   ```
   再用 `llama-quantize` 转 `Q4_K_M`（约 5.2 GB，可全量进 8GB 显存）
2. **放进 `E:\models\`**，LM Studio 直接识别
3. **用英文/标准剧集格式测**（它的训练分布是 INT. HOSPITAL ROOM - NIGHT 这类美式标准剧本头），
   拿一个美式对白场景测它跟你现有 Qwen3.5-9B 的差距
4. **用 DramaBench 的 3 个维度自检**：Format / Character Consistency / Logic Consistency
5. **关键对照**：同一素材分别跑
   - 纯 `Qwen3-8B-Drama-Thinking`（thinking on）
   - 纯 `Qwen3.5-9B`（thinking off，你现有的）
   - 本机三棒流水线

   **看"每场戏的实际秒数"和"人物名单是否被动过"**，不要只看文笔。

# 八、给未来的自己

DeepSeek 这类推荐里，**"现成的专用模型"往往是幻觉重灾区**——
本轮实测社区里真正做剧本的模型下载量最高只有 86 次（`SalonbusAI/Qwen2.5-14B-Screenplay-ft`，
原仓库已删只剩孤儿 GGUF）。而这个 Drama-Thinking 之所以靠谱，
是因为它**附带了可独立核验的第三方基准（DramaBench）和论文**。

**筛选专用模型的三条硬标准**（本轮总结，可复用）：

1. 仓库还在吗？只剩量化镜像 = 孤儿 = 不知道拿什么训的
2. 有没有第三方评测？作者自评（LLM-as-Judge）不算
3. 它的**训练分布**和你的项目对得上吗？模型卡 "Not Recommended For" 那栏是硬否决项

第 3 条最容易被忽略——`Comedy/Action Genres` 不推荐这一条，
比任何跑分都更能决定它对你有没有用。
