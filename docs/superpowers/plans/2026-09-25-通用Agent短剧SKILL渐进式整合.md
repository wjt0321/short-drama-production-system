# 通用 Agent 短剧 SKILL 渐进式整合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将 `短剧导演台/` 中与平台和脚手架无关的短剧方法论抽取到通用 Agent SKILL，加入候选决策和渐进加载机制，验证后删除原始导入目录。

**Architecture:** 保留现有 `SKILL.md` 作为唯一正文入口；新增一份通用生产规范承载抽取后的跨阶段原则；现有阶段文档只吸收对应方法，不复制大段平台资料。项目运行状态通过模板中的 `项目状态摘要.md` 增量维护，机器识别通过 `skill-manifest.json` 辅助。

**Tech Stack:** Markdown、JSON、Python/PowerShell 静态检查；不接入平台 API，不引入运行时依赖。

## Global Constraints

- 不修改或吸收 ComfyUI 脚手架、Python 脚本、工作流 JSON。
- 不吸收平台/API/价格/线路/登录/账户资料。
- 忽略编程、财务、合同、PPT、电商、学术、邮件等无关资料。
- 保留中文正文和目录；`SKILL.md` 是唯一规范正文入口，manifest 只做识别辅助。
- 不确定时提供 2–4 个候选项；高代价选择必须记录用户/Agent 决策者。
- 默认渐进加载，不要求 Agent 读取全量资料。
- 只有抽取、融合、验证完成后才删除 `短剧导演台/`。

---

### Task 1: 提取源资料并建立内容映射

**Files:**
- Read: `短剧导演台/TokenGo参考资产/04-短剧专用/短剧专用资产包.md`
- Read: `短剧导演台/TokenGo参考资产/03-技能库/短剧与漫剧/短剧单集分镜助手.md`
- Read: `短剧导演台/TokenGo参考资产/03-技能库/短剧与漫剧/分镜转视频提示词.md`
- Read: `短剧导演台/TokenGo参考资产/03-技能库/短剧与漫剧/短剧角色设计.md`
- Read: `短剧导演台/TokenGo参考资产/03-技能库/短剧与漫剧/角色设计三视图.md`
- Read: `短剧导演台/TokenGo参考资产/03-技能库/短剧与漫剧/电影级分镜运镜提示词.md`
- Read: `短剧导演台/TokenGo参考资产/03-技能库/短剧与漫剧/视频动作复刻与角色迁移.md`
- Read: `短剧导演台/TokenGo参考资产/06-机制档案/01-Agent运行逻辑全解.md`
- Read: `短剧导演台/TokenGo参考资产/06-机制档案/03-质量归因与真实成片质检.md`
- Create: `资料提取记录.md`

- [x] 分块读取上述文件，不加载全量 196 个 Markdown。
- [x] 记录每个候选来源的可吸收规则、重复项和排除原因。
- [x] 确认没有把平台和脚手架内容带入抽取结果。

### Task 2: 建立通用 Agent 总控规范与识别 manifest

**Files:**
- Create: `通用Agent短剧生产规范.md`
- Create: `skill-manifest.json`
- Modify: `SKILL.md`
- Modify: `README.md`

- [x] 写入 L0–L4 渐进加载协议。
- [x] 写入候选项协议、选择者规则和默认推荐规则。
- [x] 写入弹性拆镜、生成段、首尾状态、资产锁和质量循环。
- [x] manifest 指向 `SKILL.md`，声明 `zh-CN` 和通用 Agent 范围。

### Task 3: 将方法融入现有阶段文档

**Files:**
- Modify: `AGENTS.md`
- Modify: `从这里开始.md`
- Modify: `02-分镜与镜头/分镜叙事工作流.md`
- Modify: `02-分镜与镜头/跨镜连续性与帧链法.md`
- Modify: `03-角色与视觉资产/多镜头角色一致性.md`
- Modify: `03-角色与视觉资产/场景与道具资产.md`
- Modify: `模板/短剧项目模板/README.md`
- Create: `模板/短剧项目模板/项目状态摘要.md`

- [x] 在 G0–G6 协议中加入候选决策和渐进加载要求。
- [x] 在分镜文档中加入真实镜头/生成段区分和弹性拆镜。
- [x] 在连续性文档中加入首状态/尾状态快照。
- [x] 在资产和模板中加入项目状态摘要与局部加载字段。

### Task 4: 做通用性、引用和渐进加载验证

**Files:**
- Modify: `tools/validate_system.py`
- Modify: `tools/validate-体系.py`
- Modify: `tools/validate_system.ps1`
- Modify: `README.md`

- [x] 检查 manifest 的 entry 存在且为 `SKILL.md`。
- [x] 检查新总控规范包含候选项和 L0–L4。
- [x] 检查项目状态摘要模板存在。
- [x] 检查当前正文不引用 `短剧导演台/` 作为运行依赖。
- [x] 检查平台/脚手架/无关内容没有被写入新增通用规范。
- [x] 运行 Python 和 PowerShell 两种验证入口。

### Task 5: 删除原始导入目录

**Files:**
- Delete: `短剧导演台/`（仅在 Task 1–4 全部通过后）

- [x] 复核提取记录和新增文件。
- [x] 复核删除目标的绝对路径严格位于当前工作区内。
- [x] 删除 `短剧导演台/`。
- [x] 删除后再次运行全量验证，确认主体系无断引用。

## Verification Checklist

- [x] Python/PowerShell 文档验证均退出码 0。
- [x] `skill-manifest.json` JSON 可解析，entry 为 `SKILL.md`。
- [x] 新增通用规范不含 ComfyUI、TokenGo、平台价格、线路或 API 依赖。
- [x] 新增通用规范包含候选项协议和 L0–L4 加载层级。
- [x] 模板包含 `项目状态摘要.md`。
- [x] `短剧导演台/` 删除后，所有现存 Markdown 引用仍可解析。

## 完成记录

- 完成日期：2026-09-25
- 独立复审：CLEAN
- 验证：两个 Python 入口、两个 PowerShell 入口及 Windows PowerShell 中文包装器均退出码 0。
