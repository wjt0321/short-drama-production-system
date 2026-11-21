# Seek Library Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move `seek库` out of the short-drama system and remove its default role in production guidance and system validation, while retaining an explicit external maintenance bridge.

**Architecture:** `E:\AI\seek库` becomes an independent data project. The short-drama system remains self-contained; optional seek maintenance code can access the external project only through `AI_SEEK_ROOT` and never through project-relative fallback paths. Production entry documents describe autonomous style decisions without reference-library retrieval.

**Tech Stack:** Markdown, Python standard library, PowerShell filesystem operations.

**Spec:** User request in the active conversation; repository `AGENTS.md` external-project boundary.

## Global Constraints

- Do not overwrite an existing `E:\AI\seek库` directory.
- Do not modify historical evidence under `docs/经验保全/` or `archive/`.
- Do not introduce absolute paths into runtime documents or source code.
- The system checks must pass without `AI_SEEK_ROOT` configured.

### Task 1: Move the external data project

**Files:** `seek库/` → `E:\AI\seek库`

- [x] Verify the destination does not exist.
- [x] Move the complete directory, including its nested Git metadata.
- [x] Verify the source is absent and destination contents are present.

### Task 2: Remove project-relative seek coupling

**Files:** `对标参考库/提示词库/lib_locator.py`, `tools/check_asset_alignment.py`, `tools/check_doc_numbers.py`, `tools/check_security_perf.py`, `tools/check_uncommitted.py`, `tools/run_all_checks.py`, `tools/validate_system.py`, `tools/check_project_conformance.py`

- [x] Make external library discovery explicit-only through `AI_SEEK_ROOT`.
- [x] Make system checks skip optional external-data checks cleanly.
- [x] Remove project-local seek ignore rules and fallback paths.

### Task 3: Remove production guidance that tells the Agent to consult seek

**Files:** `从这里开始.md`, `命令速查.md`, `docs/知识库维护清单.md`, `对标参考库/00_总览.md`, `04-视频生成/ComfyUI官方视频工作流速查.md`, `AGENTS.md`, `.gitignore`

- [x] State that style is derived by the Agent from the project brief and visual principles.
- [x] Remove seek as a production reference/query route.
- [x] Keep historical research language only where it documents past measurement provenance.

### Task 4: Verify independence

- [x] Run Python syntax compilation for changed scripts.
- [x] Run the repository system validation and relevant unit tests with `AI_SEEK_ROOT` unset.
- [x] Search active files for project-relative seek paths and forbidden default references.
- [x] Verify the moved repository and current system Git status.

