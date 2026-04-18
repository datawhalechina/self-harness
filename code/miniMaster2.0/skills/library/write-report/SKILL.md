---
name: write-report
description: 当任务目标是输出报告、总结、说明文档或基于现有证据整理结构化文字交付时使用。
tags: [report, summary, writing]
---

# Write Report

## Overview

这个 skill 用来把已经收集到的证据整理成结构化输出，并控制结论与证据的一致性。

## Workflow

1. 先检查当前证据是否足够支撑目标报告。
2. 先列结构，再填内容，不要边想边堆段落。
3. 每个结论都尽量对应到已知证据；证据不足时先补证据，不要硬写。
4. 如果用户要求生成文件，优先参考 `assets/` 中的模板资源。
5. 最终输出要区分“已确认事实”“基于证据的判断”“仍待确认事项”。
6. 默认把自己视为“结果沉淀器”，不是“重新分析整个项目的主执行器”。
7. 在早期阶段优先做报告骨架、章节占位、补入已验证发现；不要因为要写报告就主动接管大范围取证。
8. 如果当前还有多个具体分析任务尚未完成，除非只是补一小段已验证内容，否则不要反复 `glob/grep/read` 整个项目，也不要反复通读完整报告文件。

## Resource Guide

- 需要更细的写作结构时，按需读取 `skills/library/write-report/references/report-structure.md`。
- 需要快速生成 Markdown 报告骨架时，可运行 `skills/library/write-report/scripts/render_report_stub.py`。
- 需要现成模板时，可参考 `skills/library/write-report/assets/report-template.md`。

## Output Expectations

- 结论要直接回答用户问题，不要只罗列过程。
- 如果存在风险、缺口或未验证项，要单独指出。
- 不要把猜测、习惯性推断或未来计划写成已经验证的事实。
