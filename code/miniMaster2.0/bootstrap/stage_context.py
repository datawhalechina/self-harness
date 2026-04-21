"""构造三类智能体共享的静态阶段上下文。

这里的“静态”指的是：一旦程序启动，这些内容在一次运行里基本不变，例如：
- 每个阶段的 agent 名称
- 可用动作集合
- function call schema
- 工具描述文本
- system prompt 中的执行环境块

把它们提前整理好，可以避免在主循环每一步都重新计算同样的数据。
"""

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
    """把阶段名统一映射成日志和 Prompt 中使用的 agent 名。"""
    return f"{stage_name.capitalize()}-Agent"


def _build_stage_role(
    *,
    stage_name: str,
    actions,
    uses_runtime_tool_specs: bool,
    tool_service: ToolService,
) -> dict:
    """构造单个固定阶段的静态上下文。

    `uses_runtime_tool_specs=True` 的含义是：
    如果某个动作名同时也是实际运行时工具（例如 `read` / `grep`），
    那么它的输入 schema 应优先复用工具层定义，避免 Prompt 协议和工具实现脱节。
    """
    # 有些动作名就是实际工具名（如 `read`），这时需要从工具系统拿到它的原生 schema。
    tool_spec_getter = tool_service.get_tool_spec if uses_runtime_tool_specs else None
    return {
        # 这个名字会同时用于 Prompt 和日志输出。
        "agent_name": _build_agent_name(stage_name),
        # 当前阶段允许模型选择的动作集合。
        "actions": actions,
        # 给 Prompt 阅读的人类可读动作说明。
        "policy_text": render_actions_text(actions),
        # 给 OpenAI function call 用的结构化 tool schema。
        "openai_tools": build_openai_tools(actions, tool_spec_getter),
    }


def build_stage_context(tool_service: ToolService) -> dict:
    """构造流程编排阶段需要的静态上下文。

    其中 planner 会额外拆出一组 `control_*` 动作集合，用来实现“侦察预算耗尽后，
    只能返回控制动作、不能再继续 read/glob/grep”的约束。
    """
    planner_role = _build_stage_role(
        stage_name="planner",
        actions=PLAN_ACTIONS,
        uses_runtime_tool_specs=True,
        tool_service=tool_service,
    )
    # Planner 会被额外拆出一套“不带侦察动作”的纯控制动作集合，
    # 用来在侦察预算耗尽后强制收口。
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
        # system_prompt 只放跨阶段共享的硬环境信息；具体任务上下文放在 user prompt。
        "system_prompt": build_execution_context_block(**tool_service.get_prompt_execution_context()),
        # 基础工具说明会进入 Executor / Validator Prompt。
        "base_tools": tool_service.render_prompt(category="base"),
        # 搜索工具说明同理。
        "search_tools": tool_service.render_prompt(category="search"),
        # Planner 使用上面构造好的双模式角色信息。
        "planner": planner_role,
        # Executor 拥有完整执行动作集合。
        "executor": _build_stage_role(
            stage_name="executor",
            actions=EXECUTOR_ACTIONS,
            uses_runtime_tool_specs=True,
            tool_service=tool_service,
        ),
        # Validator 拥有独立验证动作集合。
        "validator": _build_stage_role(
            stage_name="validator",
            actions=VALIDATOR_ACTIONS,
            uses_runtime_tool_specs=True,
            tool_service=tool_service,
        ),
    }
