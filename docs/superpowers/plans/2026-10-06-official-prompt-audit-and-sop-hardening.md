# 官方提示词规范审计与非耦合 SOP 重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 核验并重构短剧成片体系中的视频提示词规范，使官方规则、产品能力、本机实测与社区经验分层，移除已关停的 Sora，并用生成前校验阻止平台语法串台和 H3 对白协议绕行。

**Architecture:** 保留通用导演意图层，不把任何供应商写成全局强绑定；每个平台进入独立适配记录，注明适用模型/入口、证据等级、当前状态和限制。对固定结构型实现提供轻量静态校验，对自然语言型实现只校验禁止误用的字段和容量，不伪造统一 DSL。

**Tech Stack:** Markdown 知识库、Python 3 标准库、现有 `tools/run_all_checks.py` 检查链、pytest（如现有测试环境支持）。

## Global Constraints

- 删除 Sora 在当前生产路由、平台表、提示词模板和适配索引中的占位，不保留其占用空间的正文；历史复盘仅在确有必要时保留“已移除”迁移说明。
- 不绑定单一供应商；通用 Agent 只读取能力、输入输出、证据等级和适用入口。
- 任何“官方规范”必须有官方来源和核验日期；本机实测、社区经验、未核验内容不得冒充官方。
- H3 必须区分 Base 模式与 Ref2VA；禁止把自定义六段标题写成 H3 官方字段。
- 不覆盖当前工作区已有未提交修改：`04-视频生成/视频实现适配参考.md` 与 `05-音频/背景音乐生成.md`。
- 每个代码行为变更先写失败测试，再实现，再跑全套检查。

---

### Task 1: 建立官方规范审计表与证据等级

**Files:**
- Create: `04-视频生成/官方提示词规范审计.md`
- Modify: `04-视频生成/视频实现适配参考.md`（只在后续任务按审计结论更新）

**Interfaces:**
- Produces: 每个平台的当前状态、适配类型、官方/产品/实测/社区证据等级、来源、限制和允许硬编码范围。

- [ ] 收录 H3、Seedance、即梦、Kling、Veo、Runway、Luma、Firefly、Vidu、PixVerse、ComfyUI 本地；Sora 不进入生产审计表。
- [ ] 为每个平台填写官方来源、核验日期（2026-10-06）、提示词类型、引用/参考素材方式、音频能力、负面提示能力、时长/分辨率限制和当前 SOP 结论。
- [ ] 明确“固定结构型 / 多模态句柄型 / 自然语言运动型 / 节点工作流型”四类。
- [ ] 将无法找到一手官方依据的内容标为 `UNVERIFIED` 或 `EMPIRICAL`，不再写为官方规则。

### Task 2: 修正平台适配正文并移除 Sora

**Files:**
- Modify: `04-视频生成/视频实现适配参考.md`
- Modify: `04-视频生成/平台提示词模板.md`
- Modify: `04-视频生成/Seedance工业级提示词.md`
- Modify: `04-视频生成/Seedance场景模板速查.md`
- Modify: `SKILL.md`
- Modify: `从这里开始.md`

**Interfaces:**
- Consumes: `官方提示词规范审计.md`。
- Produces: 通用 Agent 可读的非耦合入口与平台适配正文。

- [ ] 删除 Sora 平台表、提示词公式、路由和详细适配正文；不再把 Sora 当成生产候选。
- [ ] H3 分离 Base 三字段和 Ref2VA 结构；对白标签、参考标签与声音字段各归其位。
- [ ] 删除或改写“官方六段式”“官方五层公式”等未经官方固定字段支持的表述。
- [ ] Seedance 与即梦分开；Seedance 的素材句柄不能自动套给即梦。
- [ ] 将 Kling、Veo、Runway、Luma、Firefly、Vidu 的产品控件/工作流能力与真正提示词语法分开。
- [ ] 将 PixVerse 的追踪字段、积分状态等从提示词规范移出并标记未核验。
- [ ] 为每个平台增加“禁止误用”和“仅经验，不得写成官方”说明。

### Task 3: 为提示词校验器写失败测试

**Files:**
- Create: `tools/test_validate_video_prompt.py`
- Test: 现有 `tools/test_*.py` 约定

**Interfaces:**
- Produces: `validate_video_prompt.py` 预期行为的可执行测试。

- [ ] 测试 H3 合法 Base 提示词通过。
- [ ] 测试 H3 缺少固定字段失败。
- [ ] 测试 H3 对白写入 `overall_soundscape` 失败。
- [ ] 测试 H3 混入 Seedance `@Image1` 或自定义“Audio Restrictions”官方字段声明时发出错误/警告。
- [ ] 测试自然语言平台拒绝伪造 `[Shot N] At ...` 或 H3 固定字段，但允许正常自然语言提示词。
- [ ] 测试 Sora 作为平台名直接失败。
- [ ] 先运行测试，确认它们因校验器尚不存在而失败。

### Task 4: 实现平台提示词生成前校验

**Files:**
- Create: `tools/validate_video_prompt.py`
- Modify: `tools/run_all_checks.py`（仅在适合的现有闸位置接入）
- Modify: `命令速查.md`（增加调用示例）

**Interfaces:**
- Consumes: JSON 或文本提示词、平台/模型/模式参数。
- Produces: 机器可读结果；违规时非零退出码，警告与错误分离。

- [ ] 使用 Python 标准库实现，不引入新依赖。
- [ ] 提供 `--platform`、`--mode`、`--prompt-file`、`--json` 参数。
- [ ] H3 检查 Base/Ref2VA、字段完整性、参考标签、对白标签、声音字段冲突和平台串台。
- [ ] Seedance/Vidu/Kling 检查素材句柄、模式声明和禁止的假字段；不把推荐写法强行当解析器。
- [ ] Veo/Runway/Luma/Firefly 检查固定 DSL 串台、无效负面清单和超容量结构；保留自然语言自由度。
- [ ] Sora 返回明确“平台已从生产路由移除”的错误。
- [ ] 校验器只负责执行契约，不负责替 Agent 选择供应商。
- [ ] 运行 Task 3 测试转绿。

### Task 5: 把音频路线和提示词契约接入项目模板

**Files:**
- Modify: `模板/短剧项目模板/执行清单.md`
- Modify: `AGENTS.md`
- Modify: `通用Agent短剧生产规范.md`
- Modify: `05-音频/音频生产清单.md`
- Modify: `05-音频/配音审核包.md`

**Interfaces:**
- Produces: G4/G5 可追踪的实现、声音来源、口型策略和探针状态。

- [ ] 新增 `平台/实现`、`提示词契约`、`音频来源`、`口型策略`、`对白探针`字段。
- [ ] 规定对白镜必须在批量前完成至少一母一女（或实际角色两条）探针。
- [ ] 明确 H3 原生对白失败时先走“协议修正/重新探针”，不能直接静默切换外挂 TTS。
- [ ] 外挂 TTS 必须明确登记为另一路线，并记录 onset 对齐和试听结果。
- [ ] G6 “技术封装通过”与“声音体验通过”分开，不允许响度/峰值正常代替听感验收。

### Task 6: 更新全局与项目能力登记口径

**Files:**
- Modify: `能力登记.md`
- Modify: **（原《备份母亲》项目，已归档移出）**（仅补失败案例引用，不重写项目生产事实）
- Modify: **（同上）**（如需要，纠正当前状态冲突）

- [ ] 全局登记新增证据等级和当前核验日期字段说明。
- [ ] 项目登记明确 H3 生产对白提示词未通过官方标签契约，官方结构化对白只完成小样验证。
- [ ] 不把 indexTTS 或 H3 写成全体系默认实现。
- [ ] 纠正项目状态摘要的“顶部通过/后文失败”冲突，保持历史版本但只有一个当前状态。

### Task 7: 验证、审阅和提交

**Files:**
- No new source files; inspect full diff.

- [ ] 运行 `python tools/test_validate_video_prompt.py` 或项目测试入口。
- [ ] 运行 `python tools/run_all_checks.py`。
- [ ] 检索仓库中残留的 Sora、伪官方字段、平台串台表述。
- [ ] 检查当前工作区原有两处未提交修改未被覆盖，必要时人工合并。
- [ ] 检查 Markdown 链接、路径、标题和机器路由一致。
- [ ] 只在验证通过后提交一个清晰的 Git commit。
