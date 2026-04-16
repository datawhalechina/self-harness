"""miniMaster 的提示词模块统一导出入口。

这个文件本身不承载复杂逻辑，主要作用是把提示词构造、动作策略、
响应解析这几类能力集中导出，方便主程序按统一接口导入。
这样做可以减少 `main_agent.py` 中的导入细节，让教学示例更聚焦于
“Agent 如何协作”，而不是被零散的模块路径分散注意力。
"""

from .builders import (
    build_execution_context_block,
    build_generator_prompt,
    build_plan_prompt,
    build_runtime_environment_block,
    build_summary_prompt,
    build_validate_prompt,
    build_workspace_block,
)
from .policies import (
    get_generator_policy,
    get_plan_policy,
    get_validate_policy,
    render_policy_text,
)
from .protocol import build_openai_tools, decode_agent_tool_call

__all__ = [
    "build_execution_context_block",
    "build_generator_prompt",
    "build_plan_prompt",
    "build_runtime_environment_block",
    "build_summary_prompt",
    "build_validate_prompt",
    "build_workspace_block",
    "build_openai_tools",
    "decode_agent_tool_call",
    "get_generator_policy",
    "get_plan_policy",
    "get_validate_policy",
    "render_policy_text",
]
