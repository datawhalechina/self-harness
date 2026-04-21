"""领域模型层。

这一层只关心“系统中有哪些核心概念”，例如：
- Task
- AgentRuntime
- MemoryEntry
- 任务状态迁移规则
- 完成标准 checklist 的归一化

它不直接依赖具体的 LLM 调用和工具执行，因此适合放置最稳定的业务规则。
"""
