# memory 目录作用分析

## 初步判断

`memory` 目录不是摆设，确实在主流程里被使用。

- `bootstrap/runtime.py` 在构造 `AgentRuntime` 时直接创建了 `planner_memory`、`generator_memory`、`validation_memory` 和 `retry_archive_by_task`
- `memory/prompt_context.py` 会把这些 memory 组织成 Planner、Executor、Validator 各自看到的 prompt 上下文
- `engine/validator.py` 还会显式导入并调用 `build_validator_prompt_context`，说明验证阶段也依赖这套 memory

## 四类 memory 的作用

### 1. `planner_memory`

`planner_memory` 是规划阶段的工作记忆。

- 在 `bootstrap/runtime.py` 中初始化为 `WorkingMemory(keep_latest_n=6)`
- 在 `memory/prompt_context.py` 的 `build_plan_prompt_context()` 里，Planner 会读取 `runtime.planner_memory.get_all_memories()` 判断自己是否已经有侦察结果
- 同一个函数还会把 `runtime.planner_memory.get_prompt_context(view="planner")` 注入 `planner_working_memory`

所以它的作用是：保存 Planner 的侦察和规划上下文，帮助后续继续细化任务，而不是每次从零开始想。

### 2. `generator_memory`

`generator_memory` 是执行阶段的工作记忆。

- `build_executor_prompt_context()` 会把 `runtime.generator_memory.get_prompt_context(view="generator")` 注入 Executor 的 `working_memory`
- `memory/session.py` 里的 `reset_generator_memory()` 会为当前任务重置一份新的执行记忆
- `compact_generator_memory()` 会在需要时压缩旧执行记忆
- `build_validator_prompt_context()` 又把 `runtime.generator_memory.get_prompt_context(view="generator")` 作为 `task_history` 提供给 Validator

所以它的作用是：记录执行阶段的步骤、工具调用结果和反馈，既供当前执行继续使用，也供验证阶段回看执行历史。

### 3. `validation_memory`

`validation_memory` 是验证阶段的工作记忆。

- `build_validator_prompt_context()` 会把 `runtime.validation_memory.get_prompt_context(view="validation")` 注入 Validator 的 `working_memory`
- `engine/validator.py` 在 `run_validate_loop()` 一开始会先执行 `runtime.validation_memory.clear_memories()`
- 同一个循环里，Validator 每做一次验证动作，都会执行 `runtime.validation_memory.add_memory(...)` 记录验证过程
- `memory/session.py` 在归档重试历史时也会把验证阶段留下的 memory 一并纳入摘要

所以它的作用是：记录验证阶段已经确认了什么、还缺什么、最近做过哪些验证动作。

### 4. `retry_archive_by_task`

`retry_archive_by_task` 是按任务名保存的重试归档。

- `bootstrap/runtime.py` 中它初始化为空字典
- `memory/session.py` 的 `capture_retry_archive()` 会把上一轮的执行记忆、验证记忆、任务反馈、临时结论压成摘要后写入 `runtime.retry_archive_by_task[task.task_name]`
- 同一个文件里还限制只保留最近 `RETRY_ARCHIVE_LIMIT = 2` 轮
- `build_executor_prompt_context()` 会通过 `session_memory.get_retry_history_prompt(task_name)` 把这些历史摘要重新喂给下一轮 Executor

所以它的作用是：让任务失败重试时带着上一轮的有效证据和失败路径继续，而不是完全重来。

## 这套 memory 是单次运行还是跨重启持久化

结论：**单次运行内有效，不是跨重启持久化。**

依据：

- `bootstrap/runtime.py` 每次启动都会重新创建新的 `WorkingMemory()` 和空的 `retry_archive_by_task`
- `memory/session.py` 的类注释就写着“管理本次运行内的 session memory”
- `memory/working_memory.py` 内部主要是 `self.memories` 列表和 `self.summary` 字符串，没有看到把 memory 写入文件、数据库或外部存储的逻辑

这意味着 Python 进程结束后，这些 memory 会跟着 runtime 一起消失。

## 本次实际读取过的文件路径

基于这次日志中出现的 `read` 行为去重后，实际读取过：

1. `bootstrap/runtime.py`
2. `memory/prompt_context.py`
3. `memory/session.py`
4. `memory/working_memory.py`
5. `engine/validator.py`

## 小结

这套 `memory` 的核心价值不是“长期记忆”，而是给 Planner、Executor、Validator 和 retry 流程提供运行时上下文。

- `planner_memory` 管规划侦察
- `generator_memory` 管执行历史
- `validation_memory` 管验证历史
- `retry_archive_by_task` 管按任务归档的重试摘要

因此它是有用的，而且是这套多阶段执行链路里真实参与工作的内存层。
