# miniMaster

本项目是一个极简的实例，着重展示如何通过任务建模、动作协议、工作记忆和验证闭环，让 Agent 在较长流程里保持稳定推进。

## 1. Tool 设计

### 1.1 基础系统工具 (Base Tools)

`base_tool` 目录提供 Agent 与系统交互的基础能力：

* **Bash Tool**：执行命令，命令会以 `ToolContext.workspace` 为当前目录运行，并根据系统环境选择合适的底层 shell。
* **Read Tool**：读取文件内容，支持按行范围读取，适合做局部代码检查和最少必要取证。
* **Write Tool**：写入文件内容，支持创建或覆盖文件，并在需要时自动创建父目录。
* **Edit Tool**：在已有文件上做精确替换，适合小范围修改代码或文档。

这些工具都继承统一的 `BaseTool`，因此在路径解析、参数校验和错误包装上保持一致。

### 1.2 搜索检索工具 (Search Tools)

`search_tool` 目录提供文件和文本检索能力：

* **Glob Tool**：按通配符查找文件，支持递归搜索，适合做目录盘点和文件发现。
* **Grep Tool**：按正则表达式搜索文本，支持目录递归和结果结构化返回，适合做符号定位和交叉取证。

在实际使用时，Planner、Executor、Validator 都会优先依赖这类专用搜索工具，而不是一开始就退回到 bash。

### 1.3 工具核心层 (Tool Core)

`tools/core/` 是工具系统的管理框架，负责统一登记、实例化和执行工具。具体工具只需要关心自己的业务逻辑，而公共问题（工具上下文、执行入口、Prompt 渲染）则交给核心层处理。

* **BaseTool**：所有工具的基类，负责参数校验、路径解析和统一执行包装。
* **ToolSpec / ToolContext**：分别定义工具的静态元信息与运行时上下文。
* **ToolService**：为上层提供稳定入口，统一完成工具实例化、Prompt 渲染和工具执行。
* **BUILTIN_TOOLS**：项目内置的固定工具集，包含 `bash / read / write / edit / glob / grep` 六个工具。

这层设计的价值在于：主循环不需要分别知道每个工具怎么创建，只需要依赖一个稳定的 `ToolService` 入口。

### 1.4 统一的接口设计

所有工具遵循一致的接口规范：

* **结构化元信息**：通过 `ToolSpec` 声明工具名称、说明、分类和输入 schema。
* **统一执行上下文**：所有工具共享 `ToolContext`，统一理解工作目录、系统类型和命令环境。
* **标准化执行流程**：业务逻辑封装在 `run()` 方法中，对外统一通过 `execute()` 调用。
* **统一服务入口**：主程序通过 `ToolService` 使用工具系统，不再手写分散的注册与调度逻辑。
* **控制动作分流**：像 `init_tasks`、`split_task`、`retry_task`、`update_task_conclusion`、`validate_tool` 这类动作由主循环处理，真实文件/搜索/命令能力才进入工具执行链。

---

## 2. Prompt 设计与动作协议 (Prompting)

在 miniMaster 里，Prompt 不再是散落在主循环里的长字符串，而是被拆到 `llm/prompting/` 模块中统一管理。这样做的核心目的，是让**角色职责、动作边界、输出协议**三件事保持一致，避免“Prompt 里写一套、代码里校验另一套”。

### 2.1 Prompt 构造层

`builders.py` 负责构造不同阶段的 Prompt：

* **`build_workspace_block()`**：构造工作目录说明，让模型正确理解“当前目录”“这里”“本项目目录”等说法。
* **`build_runtime_environment_block()`**：构造运行环境说明，明确系统类型和底层 shell。
* **`build_execution_context_block()`**：把工作目录和运行环境合并成统一的 system prompt 上下文。
* **`build_plan_prompt()`**：为 Planner-Agent 生成调度提示词，让它决定是初始化任务、拆分任务还是推进已有任务。
* **`build_generator_prompt()`**：为 Executor-Agent 生成执行提示词，把当前任务、completion checklist、retry history、working memory 和工具说明组合起来。
* **`build_validate_prompt()`**：为 Validator-Agent 生成验证提示词，要求它独立判断结论是否真的成立。

这层的关键不在于“Prompt 写得长不长”，而在于：不同角色看到的上下文必须不同。

### 2.2 动作策略层

`policies.py` 负责定义每一类 Agent 可以做什么，不同角色拥有不同的动作边界：

* **Planner-Agent**：可使用 `read / glob / grep` 做有限侦察，也可使用 `init_tasks / add_task / split_task / retry_task / subagent_tool / respond_to_user` 做任务调度。
* **Executor-Agent**：可使用 `bash / read / write / edit / glob / grep` 完成任务，并通过 `update_task_conclusion` 提交阶段结论。
* **Validator-Agent**：可使用 `bash / read / glob / grep` 做补充核查，但最终必须通过 `validate_tool` 输出验证结论。

这种设计的好处很直接：Planner 不越权去改文件，Validator 不偷偷完成任务，Executor 也不能跳过验证层直接宣布任务已经彻底完成。

### 2.3 原生 function call 协议

这里不依赖手写 XML 标签或自由格式文本，而是调用模型的原生 function call 能力。`protocol.py` 负责完成三件事：

* 把结构化动作策略转换成模型可调用的 `tools` 定义；
* 解析模型返回的 function call；
* 根据 policy 和 schema 校验动作是否合法。

这意味着模型输出的不是一段“看起来像工具调用”的文本，而是真正可被程序直接解析、验证和执行的结构化动作。这样不仅减少了格式漂移，也让主循环逻辑更清晰。

### 2.4 统一的模型调用入口

`llm/runner.py` 把“发起模型请求 -> 拿到 function call -> 校验动作合法性”这一整套流程统一封装为 `request_agent_action()`。主循环只需要在不同阶段准备好 Prompt、policy 和 tool schema，就能得到一个合法的 `AgentAction`。

从教学角度看，这一步非常关键。因为它把“调用模型”从“编排逻辑”里拆了出来，使读者在阅读 `engine/main_loop.py`、`engine/runner.py` 和 `engine/validator.py` 时，可以更专注地理解 Agent 的协作过程，而不是被 API 细节分散注意力。

---

## 3. 状态管理与动态工作记忆 (State Management)

在 Harness 的设计中，状态和记忆管理非常重要。系统既要知道每个任务当前处于什么状态，也要记得自己已经做过哪些动作、遇到过什么反馈、验证到了哪些条件。否则 Agent 很容易在长流程里走回头路，或者把尚未确认的事情写成结论。

在这套实现里，状态管理被拆成了两层：

* **宏观层面**：由 `ToDoList` 维护整张任务看板；
* **微观层面**：由 `WorkingMemory` 和 `SessionMemoryManager` 维护规划、执行、验证和重试时需要看到的近期轨迹。

下面是 `WorkingMemory` 的核心思路：

```python
class WorkingMemory:
    def __init__(self, keep_latest_n: int = 3, max_chars: int = DEFAULT_WORKING_MEMORY_MAX_CHARS):
        self.memories = []
        self.keep_latest_n = keep_latest_n
        self.max_chars = max_chars
        self.summary = ""

    def add_memory(self, step: int, tool_name: str, parameters: dict, result):
        self.memories.append(
            MemoryEntry(
                step=step,
                tool_call=MemoryToolCall(
                    tool_name=tool_name,
                    parameters=compact_for_memory(parameters),
                ),
                result=prepare_memory_result(tool_name, parameters, result),
            )
        )

    def get_prompt_context(self, view: str = "generator") -> str:
        ...

    def compact_old_memories(self) -> bool:
        ...
```

这段实现展示了两个重要点：

1. 工具结果在写入 memory 前就会先做裁剪；
2. memory 并不是简单的原始日志堆叠，而是要根据 Planner / Executor / Validator 的不同需求渲染成不同视图。

### 3.1 记忆控制策略

1. **单次结果先压缩**
   `compact_for_memory()` 和 `prepare_memory_result()` 会先把超长的 `stdout`、`content`、匹配列表等结果压缩成适合放进 Prompt 的预览结构，避免单次工具输出直接撑爆上下文。
2. **超过阈值再做摘要**
   当 `WorkingMemory` 的整体长度超过 `max_chars`，系统会把较早的执行记录压成确定性摘要，并只保留最近几步完整轨迹。
3. **不同角色看到不同视图**
   `get_prompt_context(view="planner" | "generator" | "validation")` 会为规划、执行、验证分别输出不同格式的上下文，而不是让所有角色共用一份混杂日志。
4. **失败经验会进入重试归档**
   `SessionMemoryManager` 会把执行记忆、验证记忆、最近反馈和临时结论压成 retry archive，供后续继续使用。

### 3.2 任务状态管理

`domain/todo.py` 中的 `ToDoList` 不再只是一个简单列表，而是整个流程中的状态看板：

* 负责初始化任务列表；
* 负责保存 `task_name / goal / scope / done_when / deliverable` 等任务卡片字段；
* 负责维护 `PENDING / RUNNING / DONE / FAILED / BLOCKED` 等状态；
* 负责记录每个任务的结论、最近反馈、重试原因与尝试次数；
* 负责把任务对象转换成 Prompt 可直接使用的 payload。

另外，`domain/state_machine.py` 还额外对状态迁移做了受控约束，例如：

* Planner 不能随意直接改任务状态；
* Runner 只能按 `PENDING -> RUNNING -> DONE/FAILED/BLOCKED` 的路径推进；
* `retry_task` 只能把 `FAILED / BLOCKED` 的任务恢复成 `PENDING`。

这种设计的价值在于：Planner-Agent、Executor-Agent、Validator-Agent 虽然职责不同，但都围绕同一份任务状态展开工作，不会各自维护一套互相漂移的任务视图。

---

## 4. 多智能体编排 (multi-agent Orchestration)

miniMaster 采用的是**“规划-执行-验证”三层嵌套循环**的多智能体协作架构。各个 Agent 遵循“观察-决策-行动”的模式，但又通过结构化动作协议、状态管理、重复动作防护和验证闭环保证行为边界。

### 4.1 Plan-Agent (全局调度)

Planner-Agent 是整个系统的调度者。它不直接完成任务，而是判断用户输入属于哪一类，再决定下一步动作：

* 如果只是问候、闲聊、咨询能力，就直接 `respond_to_user`；
* 如果是明确任务，就通过 `init_tasks` 或 `add_task` 组织任务；
* 如果发现原任务过大或需要分轮推进，就使用 `split_task`；
* 如果某个任务失败后还值得继续，就通过 `retry_task` 恢复；
* 如果当前已经有足够清晰的任务，就使用 `subagent_tool` 推进执行。

这让顶层循环既能处理复杂任务，也能自然处理简单问答，不必把所有输入都硬塞进任务系统。

### 4.2 Generator-Agent (执行者)

当 `subagent_tool` 被触发后，系统进入 Executor 内层循环。它是真正执行任务的角色，会反复在“选动作 -> 执行工具 -> 把结果写入工作记忆”之间循环。

在这套实现里，Executor 除了能调用基础工具和搜索工具，还多了几层稳定性设计：

* **completion checklist 驱动收口**：在决定是否 `update_task_conclusion` 之前，会先参考当前任务的完成清单。
* **重复动作拦截**：如果连续发出完全相同的动作，系统会写回反馈，要求它直接回应缺口或尽快收口。
* **retry history 复用**：如果任务曾经失败，后续执行会先看到前一次归档下来的失败原因和有效证据。
* **执行接近上限时强制收口**：当步数接近上限时，Prompt 会明确要求基于现有证据整理结论，而不是继续漫游式阅读。

当 Executor 认为任务已经完成时，它不能直接把任务标记为 done，而是必须通过 `update_task_conclusion` 提交结论，再交给验证层判断。

### 4.3 Validate-Agent (评估者)

Validator-Agent 的职责不是继续做任务，而是检查“当前结论是否真的被现有证据支持”。它会读取当前任务、completion checklist、执行历史和验证阶段工作记忆，必要时再调用 `read`、`grep`、`glob`、`bash` 做补充核查，最后必须通过 `validate_tool` 输出 `有效` 或 `无效`。

在这套实现里，Validator 还有两个重要约束：

* 它需要把 completion checklist 的每一项明确归类到 `covered_requirements` 或 `missing_requirements`；
* 如果已经有足够证据，就必须尽快 `validate_tool` 收口，不能反复做相同验证。

如果判定为 `无效`，系统不会简单报错结束，而是把失败原因写回任务反馈和 memory，再让 Executor 在后续执行中优先回应这条具体缺口。

### 4.4 编排细节

在 `engine/main_loop.py`、`engine/plan_actions.py`、`engine/runner.py` 和 `engine/validator.py` 中，除了三层循环本身，当前实现还补充了几项很关键的工程细节：

* **共享 stage context**：把 system prompt、可用工具 schema、工具说明文本统一提前构造，减少循环内重复组装。
* **受控任务状态迁移**：任务的进入、完成、失败、阻塞和恢复都要走显式状态机。
* **任务级 memory 重置与压缩**：执行和验证阶段的 memory 会在任务开始或重试时被重置、压缩和归档。
* **重复动作防护**：Planner、Executor、Validator 都有对应的重复动作检测和反馈机制。
* **验证结果回流执行层**：Validator 的失败原因不是只打印出来，而是会回流成后续执行必须直接回应的 system feedback。

这就形成了一个真正的**纠错闭环（Feedback Loop）**：

* Planner 负责把问题拆对；
* Executor 负责把证据拿全；
* Validator 负责把“看起来完成”与“真的完成”区分开；
* 如果没有完成，系统会把缺口精确地送回到后续执行。

## 5.使用示例：
输入：
```aiignore
请判断当前项目里的 memory 目录是否真的有用，说明 planner_memory、generator_memory、validation_memory、retry_archive_by_task 的作用，并回答这套 memory 是单次运行内有效还是跨重启持久化有效。
```

log：
```aiignore
📋 Planner-Agent 选择工具: init_tasks
📋 参数: {'tasks': [{'task_name': '分析 memory 目录作用', ...}]}
✅ 已初始化任务列表: [{'task_name': '分析 memory 目录作用', ...}]

📋 Planner-Agent 选择工具: read
📋 参数: {'file_path': 'C:\\Users\\25853\\Desktop\\self-harness\\code\\miniMaster2.0\\bootstrap\\runtime.py'}
✅ 规划侦察结果: {'success': True, 'content': 'import os\\nimport time\\n...', 'total_lines': 107}
📋 Planner-Agent 选择工具: split_task
📋 参数: {'target_task_name': '分析 memory 目录作用', ...}

  🛠️ Executor-Agent 选择工具: read
  🛠️ 参数: {'file_path': 'bootstrap/runtime.py'}
  ✅ 工具执行结果: {'success': True, 'content': 'import os\\nimport time\\n...', 'total_lines': 107}

  🛠️ Executor-Agent 选择工具: read
  🛠️ 参数: {'file_path': 'memory/prompt_context.py'}
  ✅ 工具执行结果: {'success': True, 'content': 'from __future__ import annotations\\n...', 'total_lines': 115}

  🛠️ Executor-Agent 选择工具: update_task_conclusion
  🛠️ 参数: {'conclusion': 'memory 目录在运行时被直接使用，并参与 Planner、Executor、Validator 的上下文组织。'}

    🛠️ Validator-Agent 选择工具: grep
    🛠️ 参数: {'pattern': 'from memory.prompt_context import', 'path': 'engine/validator.py', 'recursive': False}
    ✅ 验证工具执行结果: {'success': True, 'matches': [{'file': 'engine\\validator.py', 'line_number': 18, 'line_content': 'from memory.prompt_context import build_validator_prompt_context', 'matched_text': 'from memory.prompt_context import'}]}

    🛠️ Validator-Agent 选择工具: validate_tool
    🛠️ 参数: {'status': '有效', 'reason': '现有证据已完整覆盖所有完成项：validator 通过 build_validator_prompt_context 获取验证所需的 memory 上下文。', 'covered_requirements': ['能够说明 validator 是否使用 memory 数据及其使用方式', '验证器与 memory 关联分析报告'], 'missing_requirements': []}
    ✅ 验证通过！
```


生成结果:
```aiignore
memory 目录作用分析

初步判断：`memory` 目录不是摆设，确实在主流程里被使用。
- `bootstrap/runtime.py` 在构造 `AgentRuntime` 时直接创建了 `planner_memory`、`generator_memory`、`validation_memory` 和 `retry_archive_by_task`
- `memory/prompt_context.py` 会把这些 memory 组织成 Planner、Executor、Validator 各自看到的 prompt 上下文
- `engine/validator.py` 还会显式导入并调用 `build_validator_prompt_context`，说明验证阶段也依赖这套 memory

持久化判断：**单次运行内有效，不是跨重启持久化。**

小结：这套 `memory` 的核心价值不是“长期记忆”，而是给 Planner、Executor、Validator 和 retry 流程提供运行时上下文。
```

完整日志可见：
- [`case3/log.txt`](../../code/miniMaster2.0/use_case/case3/log.txt)

完整结果可见：
- [`case3/res.md`](../../code/miniMaster2.0/use_case/case3/res.md)
