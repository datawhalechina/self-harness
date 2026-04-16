<h1 align="center">self-harness - 实战指南（⚠️ Alpha内测版）</h1>

<p align="center">
  <img src="docs/images/self-harness.png" alt="self-harness" width="720">
</p>

<p align="center">
  <a href="https://github.com/datawhalechina/self-harness/stargazers">
    <img src="https://img.shields.io/github/stars/datawhalechina/self-harness?style=for-the-badge&label=STARS&color=ff6b6b&labelColor=333" alt="Stars">
  </a>
  <a href="https://github.com/datawhalechina/self-harness/network/members">
    <img src="https://img.shields.io/github/forks/datawhalechina/self-harness?style=for-the-badge&label=FORKS&color=4ecdc4&labelColor=333" alt="Forks">
  </a>
  <br>
  <a href="https://github.com/datawhalechina/self-harness">
    <img src="https://img.shields.io/badge/TUTORIAL-Harness%20Engineering-3498db?style=for-the-badge&labelColor=333" alt="Tutorial">
  </a>
  <a href="https://datawhalechina.github.io/self-harness/">
    <img src="https://img.shields.io/badge/在线阅读-立即开始-2ecc71?style=for-the-badge&labelColor=333" alt="在线阅读">
  </a>
  <br>
  <a href="http://creativecommons.org/licenses/by-nc-sa/4.0/">
    <img src="https://img.shields.io/badge/LICENSE-CC%20BY--NC--SA%204.0-lightgrey?style=for-the-badge&labelColor=333" alt="License">
  </a>
</p>

> [!CAUTION]
> ⚠️ Alpha内测版本警告：此为早期内部构建版本，尚不完整且可能存在错误，欢迎大家提Issue反馈问题或建议。


## 项目简介

本项目是一本关于 **Harness Engineering** 的开源教程，旨在帮助开发者理解和掌握在大模型时代，如何为复杂、长时间运行的 AI 智能体（Agent）构建健壮的底层运行架构。

随着智能体技术的发展，AI 系统的开发范式正在经历深刻的演进：从单次的提示词工程（Prompt Engineering），到动态信息管理的上下文工程（Context Engineering），最终迈向系统级的 Harness Engineering。

本教程包含理论讲解和实践代码两部分：
- **理论部分**：系统介绍提示词工程、上下文工程、harness 的核心概念、设计原则、实现策略。以及为什么会一步步演进到 harness engineering
- **实践部分**：通过 miniMaster 项目（一个最小化的 Harness 实现），展示如何将 Harness 理论应用于实际开发

## 项目受众

本教程适合以下人群：
- **AI 应用开发者**：希望构建更复杂、更智能的 AI 应用系统
- **大模型技术爱好者**：想深入了解 Agent 系统和上下文管理机制
- **Python 开发者**：具备基础 Python 编程能力，想学习 AI 系统工程化实践

通过学习本教程，你将能够：
- 理解上下文工程与提示词工程的本质区别
- 掌握动态上下文管理的核心策略
- 学会设计可扩展的 AI 技能系统
- 动手实现一个最小化的类 Claude Code 系统

## 在线阅读

📖 [https://datawhalechina.github.io/self-harness/](https://datawhalechina.github.io/self-harness/)

## 目录

| 章节名 | 简介 | 状态 |
| :--- | :--- | :--- |
| [第1章 总览](https://github.com/datawhalechina/self-harness/blob/main/docs/chapter1/overview.md) | 总览 | ✅ |
| [第2章 什么是提示词工程](https://github.com/datawhalechina/self-harness/blob/main/docs/chapter2/prompt_engineering.md) | Prompt Engineering 的概念、方法、局限性 | ✅ |
| [第3章 什么是上下文工程](https://github.com/datawhalechina/self-harness/blob/main/docs/chapter3/context_engineering.md) | 上下文工程的概念和方法 | ✅ |
| [第4章 长时运行下的 Harness Engineering](https://github.com/datawhalechina/self-harness/blob/main/docs/chapter4/harness_engineering.md) | 再长时间复杂软件开发中、如何设计 harness 以保证 agent 在长时间的运行中不会出错 | ✅ |
| [第5章 三种工程的演进](https://github.com/datawhalechina/self-harness/blob/main/docs/chapter5/evolution.md) | 这三种工程理论的演进 | ✅ |
| [第6章 miniMaster 实战项目](https://github.com/datawhalechina/self-harness/blob/main/docs/chapter6/miniMaster.md) | 实现一个最小的 harness 系统，包含 Tool 设计、Prompt/动作协议、动态工作记忆与三层嵌套循环架构。快速体验 harness 的设计理念 | ✅ |

## miniMaster 实战项目

miniMaster 是一个最小的 harness 系统实现，展示了如何将上下文工程和 Harness 工程理论应用于实际开发。
在实现上，项目采用了清晰的模块化结构，把启动流程、Prompt 构造、动作协议、运行时状态和工具系统分别拆开，便于理解和扩展。

### 核心特性

- **系统 Tool 设计**：包含基础系统工具（Bash、Read、Write、Edit）和搜索检索工具（Glob、Grep），并通过 `tools/core` 中的 `ToolCatalog + discover_tools + ToolService` 完成统一管理
- **Prompt 与动作协议**：将 Prompt 构造、角色动作策略、原生 function call 协议拆分到 `prompting/` 中，避免 Prompt 和代码校验规则分叉
- **动态工作记忆管理**：不仅支持超长上下文摘要，还会先压缩单次工具结果，减少长任务中的 Prompt 膨胀
- **三层嵌套循环架构**：Plan-Agent（全局调度）→ Generator-Agent（执行者）→ Validate-Agent（评估者），并补充重复动作防护、只读工具缓存与验证收口逻辑，形成更稳定的纠错闭环

### 智能体架构图

![flowchart.png](docs/images/flowchart.png)

### 运行示例

query: 扫描当前目录结构，识别所有项目

部分结果:

plan-agent
```log
============================================================
🔄 Plan-Agent 第 1 次迭代
============================================================
📋 Plan-Agent 选择工具: init_tasks
📋 Plan-Agent 参数: {'tasks': ['扫描当前目录结构，识别所有项目']}
✅ 已初始化任务列表: ['扫描当前目录结构，识别所有项目']

============================================================
🔄 Plan-Agent 第 2 次迭代
============================================================
📋 Plan-Agent 选择工具: subagent_tool
📋 Plan-Agent 参数: {'task_name': '扫描当前目录结构，识别所有项目'}
```
generator-agent
```log
🚀 开始执行任务: 扫描当前目录结构，识别所有项目
📝 任务详情: {'task_name': '扫描当前目录结构，识别所有项目', 'task_status': 'PENDING', 'task_conclusion': ''}

  🔧 Generator 第 1 步
  🛠️  Generator 选择工具: glob
  🛠️  参数: {'pattern': '**/*', 'path': '.', 'recursive': true}
  ✅ 工具执行结果: {'success': True, 'matches': ['app/bootstrap.py', 'app/orchestration.py', 'prompting/builders.py', 'runtime/memory.py', 'tools/base_tool/bash_tool.py', 'tools/core/service.py', 'tools/search_tool/grep_tool.py']}

  🔧 Generator 第 2 步
  🛠️  Generator 选择工具: read
  🛠️  参数: {'file_path': 'main_agent.py'}
  ✅ 工具执行结果: {'success': True, 'content': 'from app.bootstrap import bootstrap_runtime\nfrom app.orchestration import run_main_loop\n...', 'total_lines': 16}

  🔧 Generator 第 3 步
  🛠️  Generator 选择工具: update_task_conclusion
  🛠️  参数: {'conclusion': '当前目录中识别出一个模块化的 miniMaster 项目，核心结构包含 app、prompting、runtime 和 tools 四个主要子系统。main_agent.py 只保留入口职责，真正的编排逻辑位于 app/orchestration.py，工具系统由 tools/core/ToolService 统一管理。'}
  📝 Generator 完成任务，结论: 当前目录中识别出一个模块化的 miniMaster 项目，核心结构包含 app、prompting、runtime 和 tools 四个主要子系统。main_agent.py 只保留入口职责，真正的编排逻辑位于 app/orchestration.py，工具系统由 tools/core/ToolService 统一管理。
```
validate-agent
```log
    🔍 Validate-Agent 第 1 步
    🛠️  Validate-Agent 选择工具: read
    🛠️  参数: {'file_path': 'app/orchestration.py'}
    ✅ 验证工具执行结果: {'success': True, 'content': 'from copy import deepcopy\n...\ndef run_main_loop(runtime: AgentRuntime, max_iter: int = 30):\n...', 'total_lines': 257}

    🔍 Validate-Agent 第 2 步
    🛠️  Validate-Agent 选择工具: validate_tool
    🛠️  参数: {'status': '有效', 'reason': 'glob 与 read 的现有证据已经覆盖目录结构与主编排入口，结论与任务要求一致。'}
    📊 验证结果: 有效, 原因: glob 与 read 的现有证据已经覆盖目录结构与主编排入口，结论与任务要求一致。
    ✅ 验证通过！
```

最终生成的项目报告：[生成的结果](code/miniMaster2.0/use_case/case1/项目报告.md)

### 完整日志

[查看完整执行日志](code/miniMaster2.0/use_case/case1/log.txt)

### 代码结构

```
code/miniMaster2.0/
├── app/
│   ├── bootstrap.py        # 入口初始化，装配 runtime
│   ├── agent_runner.py     # 模型调用与 function call 解析入口
│   ├── agent_config.py     # 各阶段共享配置与静态上下文
│   ├── orchestration.py    # Plan / Generator / Validate 主编排逻辑
│   └── loop_control.py     # 缓存与重复动作防护
├── prompting/
│   ├── builders.py         # Prompt 构造函数
│   ├── policies.py         # 不同 Agent 的动作策略
│   └── protocol.py         # 原生 function call 协议适配
├── runtime/
│   ├── todo.py             # 任务状态管理
│   └── memory.py           # 动态工作记忆管理
├── tools/
│   ├── base_tool/          # 基础系统工具
│   ├── search_tool/        # 搜索检索工具
│   └── core/               # 工具注册、发现与执行服务
├── main_agent.py           # 程序入口
└── requirements.txt        # 依赖包列表
```

## 贡献者名单

| 姓名 | 职责 | GitHub |
| :--- | :--- | :--- |
| 张文星 | 项目负责人、教程设计与实现 | [@funnamer](https://github.com/funnamer) |
| CaptainUniverse_ | 实践项目部分 代码优化 | [@TheCaptainUniverse](https://github.com/TheCaptainUniverse) |

## 参与贡献

- 如果你发现了一些问题，可以提 Issue 进行反馈，如果提完没有人回复你可以联系[保姆团队](https://github.com/datawhalechina/DOPMC/blob/main/OP.md)的同学进行反馈跟进~
- 如果你想参与贡献本项目，可以提 Pull Request，如果提完没有人回复你可以联系[保姆团队](https://github.com/datawhalechina/DOPMC/blob/main/OP.md)的同学进行反馈跟进~
- 如果你对 Datawhale 很感兴趣并想要发起一个新的项目,请按照[Datawhale开源项目指南](https://github.com/datawhalechina/DOPMC/blob/main/GUIDE.md)进行操作即可~

## 已知待完善

- [ ] 主流的 harness 系统应用的 agent 产品解析（比如 NanoBot、OpenHarness 等）

## 关注我们

<div align="center">
<p>扫描下方二维码关注公众号：Datawhale</p>
<img src="https://raw.githubusercontent.com/datawhalechina/pumpkin-book/master/res/qrcode.jpeg" width="180" height="180">
</div>

## LICENSE

<a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/"><img alt="知识共享许可协议" style="border-width:0" src="https://img.shields.io/badge/license-CC%20BY--NC--SA%204.0-lightgrey" /></a><br />本作品采用<a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/">知识共享署名-非商业性使用-相同方式共享 4.0 国际许可协议</a>进行许可。
