---
name: inspect-codebase
description: 当任务需要理解项目结构、定位实现入口、梳理模块职责，或在修改前先建立代码上下文时使用。
tags: [codebase, analysis, search]
---

# Inspect Codebase

## Overview

这个 skill 用来帮助执行层先建立项目上下文，再进入更具体的读取、修改或总结任务。

## Workflow

1. 先查看顶层目录，再判断项目的大致边界和主要模块。
2. 每个侦察任务里，目录树脚本或顶层 listing 最多做 1 次；拿到边界后就转向 `glob` / `grep` / `read`，不要反复列目录。
3. 优先用 `glob` 和 `grep` 缩小范围，不要一开始就大面积 `read`。
4. 只有在确定目标文件后，才读取最小必要片段；通常 1 个入口文件 + 2 到 5 个关键实现文件就足够支撑模块说明。
5. 如果 `done_when` 已经能被当前证据覆盖，就直接整理结论；不要为了“更完整”继续漫游式读取。
6. 结论必须基于已经读到或搜到的证据，不要把猜测当事实。
7. 如果用户后续还要修改代码，把关键入口、配置文件和依赖关系记录清楚。

## Resource Guide

- 需要快速列出有限深度目录树时，可运行 `skills/library/inspect-codebase/scripts/print_tree.py`。
- 推荐命令形式：`python skills/library/inspect-codebase/scripts/print_tree.py . --depth 2`，也兼容旧写法 `python skills/library/inspect-codebase/scripts/print_tree.py . 2`。
- 需要更细的排查顺序时，按需读取 `skills/library/inspect-codebase/references/inspection-patterns.md`。

## Output Expectations

- 输出目录结构时，优先保留和当前任务相关的部分。
- 输出实现位置时，尽量给出文件路径、关键函数或类名。
- 如果没有直接读到某个 dataclass 字段、函数签名或返回值，就不要把它写进结论。
- 对分析类任务，允许输出“基于当前已读文件可确认的结论 + 尚未展开的部分”，这比编造完整细节更好。
- 如果仍然缺少证据，要明确指出“还没读到哪些文件”。
