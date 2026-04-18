from __future__ import annotations

from llm.prompting.builders import build_execution_context_block
from llm.prompting.policies import (
    EXECUTOR_ACTIONS,
    PLAN_ACTIONS,
    VALIDATOR_ACTIONS,
    render_actions_text,
)
from llm.prompting.protocol import build_openai_tools
from tools.core.service import ToolService

PLANNER_RESEARCH_ACTION_NAMES = {"read", "glob", "grep"}


def _build_agent_name(stage_name: str) -> str:
    return f"{stage_name.capitalize()}-Agent"


def _build_stage_role(
    *,
    stage_name: str,
    actions,
    uses_runtime_tool_specs: bool,
    tool_service: ToolService,
) -> dict:
    """构造单个固定阶段的静态上下文。"""
    tool_spec_getter = tool_service.get_tool_spec if uses_runtime_tool_specs else None
    return {
        "agent_name": _build_agent_name(stage_name),
        "actions": actions,
        "policy_text": render_actions_text(actions),
        "openai_tools": build_openai_tools(actions, tool_spec_getter),
    }


def build_stage_context(tool_service: ToolService) -> dict:
    """构造流程编排阶段需要的静态上下文。"""
    planner_role = _build_stage_role(
        stage_name="planner",
        actions=PLAN_ACTIONS,
        uses_runtime_tool_specs=True,
        tool_service=tool_service,
    )
    planner_control_actions = tuple(
        action for action in PLAN_ACTIONS
        if action.name not in PLANNER_RESEARCH_ACTION_NAMES
    )
    planner_role["control_actions"] = planner_control_actions
    planner_role["control_policy_text"] = render_actions_text(planner_control_actions)
    planner_role["control_openai_tools"] = build_openai_tools(
        planner_control_actions,
        tool_service.get_tool_spec,
    )

    return {
        "system_prompt": build_execution_context_block(**tool_service.get_prompt_execution_context()),
        "base_tools": tool_service.render_prompt(category="base"),
        "search_tools": tool_service.render_prompt(category="search"),
        "planner": planner_role,
        "executor": _build_stage_role(
            stage_name="executor",
            actions=EXECUTOR_ACTIONS,
            uses_runtime_tool_specs=True,
            tool_service=tool_service,
        ),
        "validator": _build_stage_role(
            stage_name="validator",
            actions=VALIDATOR_ACTIONS,
            uses_runtime_tool_specs=True,
            tool_service=tool_service,
        ),
    }
