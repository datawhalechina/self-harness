"""启动装配层。

这一层负责把“可以运行”之前需要准备的对象组装起来，例如：
- LLM client
- ToolService
- SkillStore
- WorkingMemory
- AgentRuntime

可以把它类比成后端应用里的 composition root。
"""
