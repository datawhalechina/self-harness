from tools.core import ToolService

from prompting import (
    build_openai_tools,
    build_execution_context_block,
    get_generator_policy,
    get_plan_policy,
    get_validate_policy,
    render_policy_text,
)


PLAN_POLICY = get_plan_policy()
GENERATOR_POLICY = get_generator_policy()
VALIDATE_POLICY = get_validate_policy()
PLAN_POLICY_TEXT = render_policy_text(PLAN_POLICY)
GENERATOR_POLICY_TEXT = render_policy_text(GENERATOR_POLICY)
VALIDATE_POLICY_TEXT = render_policy_text(VALIDATE_POLICY)


def build_shared_agent_system_prompt(tool_service: ToolService) -> str:
    """构造各阶段共用的 system prompt。"""
    return build_execution_context_block(**tool_service.get_prompt_execution_context())


def get_available_tool_prompts(tool_service: ToolService):
    """获取可注入 Prompt 的工具说明文本。"""
    base_tools = tool_service.render_prompt(category="base")
    search_tools = tool_service.render_prompt(category="search")
    return base_tools, search_tools


def build_stage_context(tool_service: ToolService) -> dict:
    """构造流程编排阶段需要的静态上下文。"""
    shared_system_prompt = build_shared_agent_system_prompt(tool_service)
    base_tool_prompts, search_tool_prompts = get_available_tool_prompts(tool_service)
    return {
        "shared_system_prompt": shared_system_prompt,
        "plan_openai_tools": build_openai_tools(PLAN_POLICY),
        "generator_openai_tools": build_openai_tools(GENERATOR_POLICY, tool_service.get_tool_spec),
        "validate_openai_tools": build_openai_tools(VALIDATE_POLICY, tool_service.get_tool_spec),
        "base_tool_prompts": base_tool_prompts,
        "search_tool_prompts": search_tool_prompts,
    }
