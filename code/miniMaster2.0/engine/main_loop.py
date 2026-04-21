"""顶层 Planner 主循环。

这是 miniMaster 的第一层循环，负责全局调度：
- 让 Planner 判断下一步该做什么；
- 把 Planner 的控制动作交给本地处理器执行；
- 在预算耗尽、用户已回复、任务全完成等条件下停止。

阅读这个文件时，可以把它当成整个 harness 的“总导演”。
"""

from __future__ import annotations

from bootstrap.stage_context import build_stage_context
from domain.types import AgentAction, AgentRuntime
from engine.guards import ConsecutiveActionGuard, build_repeated_action_feedback
from engine.plan_actions import handle_plan_action
from engine.support import (
    LOGGER,
    execute_runtime_tool,
    has_runtime_time_left,
    mark_unfinished_tasks_blocked,
    push_planner_feedback,
)
from llm.prompting.builders import build_plan_prompt
from llm.runner import request_agent_action
from memory.prompt_context import build_plan_prompt_context
from memory.session import SessionMemoryManager

PLANNER_RESEARCH_ACTIONS = {"read", "glob", "grep"}


def _build_planner_research_status(remaining_steps: int) -> str:
    """把剩余侦察预算翻译成更明确的 Prompt 约束文本。"""
    if remaining_steps > 0:
        return (
            f"当前还可以再做 {remaining_steps} 步只读侦察。"
            "如果你还没有形成项目主要模块的顶层边界清单，优先补齐它；"
            "如果你已经掌握了足够边界信息，就应直接输出控制动作，而不是继续探索。"
        )
    return (
        "规划侦察预算已用尽。"
        "下一步必须直接输出控制动作（如 init_tasks / add_task / split_task / subagent_tool / respond_to_user），"
        "不能继续调用 glob / grep / read。"
    )


def run_plan_step(
    runtime: AgentRuntime,
    iteration: int,
    stage_context: dict,
) -> AgentAction:
    """执行一次 Plan-Agent 决策。

    这个函数内部其实包含两种模式：
    1. 还没有任务时：只能直接初始化任务或回复用户。
    2. 已经有任务时：允许做少量只读侦察，再返回控制动作。
    """
    # 取出 Planner 阶段的静态配置。
    role_context = stage_context["planner"]
    # 统一日志里使用的 agent 名。
    agent_name = role_context["agent_name"]
    LOGGER.agent_iteration(agent_name, iteration + 1)
    # 这一轮最多允许多少步规划侦察。
    max_research_steps = runtime.max_planner_research_steps
    # 当前任务面板是否已经有任务草案。
    has_existing_tasks = bool(runtime.todo_list.get_all_tasks())

    if not has_existing_tasks:
        # 初始阶段不开放侦察预算，强制 Planner 先把用户需求落成任务草案。
        memory_context = build_plan_prompt_context(runtime)
        memory_context["planner_research_status"] = (
            "当前还没有任务，因此本轮不开放规划侦察。"
            "请直接输出初始任务列表，或在明显属于闲聊时直接回复用户。"
        )
        # 初始阶段 Prompt 中不会携带真实侦察上下文，只会强调“先建任务”。
        plan_prompt = build_plan_prompt(
            user_query=runtime.user_query,
            tasks=runtime.todo_list.get_all_tasks_payload(),
            memory_context=memory_context,
            policy_text=role_context["control_policy_text"],
        )
        plan_action = request_agent_action(
            prompt=plan_prompt,
            system_prompt=stage_context["system_prompt"],
            actions=role_context["control_actions"],
            tools=role_context["control_openai_tools"],
            agent_name=agent_name,
            model_name=runtime.model_name,
            client=runtime.client,
            timeout_seconds=runtime.llm_timeout_seconds,
        )
        LOGGER.agent_tool_selection(
            agent_name,
            plan_action.tool,
            plan_action.parameters,
            icon="📋",
        )
        LOGGER.planner_reason(plan_action, agent_name)
        return plan_action

    # 一旦已经进入“有任务”的阶段，Planner 可以在单轮内做一个轻量 ReAct 循环：
    # 侦察 -> 记录 observation -> 再决定是否继续侦察或返回控制动作。
    planner_action_guard = ConsecutiveActionGuard()
    for planner_decision_step in range(1, max_research_steps + 2):
        # 如果规划记忆太长，先把旧侦察压成摘要。
        runtime.planner_memory.compact_old_memories()
        # 第 1 步时 remaining=max_research_steps，之后逐步递减到 0。
        remaining_research_steps = max(0, max_research_steps - (planner_decision_step - 1))
        # 只要预算还剩，就允许 read/glob/grep。
        can_use_research_tools = remaining_research_steps > 0
        # 根据是否还允许侦察，切换完整动作集合或纯控制动作集合。
        available_actions = role_context["actions"] if can_use_research_tools else role_context["control_actions"]
        available_tools = role_context["openai_tools"] if can_use_research_tools else role_context["control_openai_tools"]
        policy_text = role_context["policy_text"] if can_use_research_tools else role_context["control_policy_text"]
        memory_context = build_plan_prompt_context(runtime)
        memory_context["planner_research_status"] = _build_planner_research_status(remaining_research_steps)

        plan_prompt = build_plan_prompt(
            user_query=runtime.user_query,
            tasks=runtime.todo_list.get_all_tasks_payload(),
            memory_context=memory_context,
            policy_text=policy_text,
        )
        plan_action = request_agent_action(
            prompt=plan_prompt,
            system_prompt=stage_context["system_prompt"],
            actions=available_actions,
            tools=available_tools,
            agent_name=agent_name,
            model_name=runtime.model_name,
            client=runtime.client,
            timeout_seconds=runtime.llm_timeout_seconds,
        )
        LOGGER.agent_tool_selection(
            agent_name,
            plan_action.tool,
            plan_action.parameters,
            icon="📋",
        )
        LOGGER.planner_reason(plan_action, agent_name)

        # 给 Planner 记忆生成一个递增 step 编号。
        # 乘以 10 只是为了给同一轮内部的多个子步留出明显间隔，便于日志阅读。
        planner_memory_step = iteration * ((max_research_steps + 1) * 10) + planner_decision_step
        if plan_action.tool in PLANNER_RESEARCH_ACTIONS and planner_action_guard.is_repeated(plan_action):
            # 教学重点：侦察失败时不是立刻报错，而是把“不要重复”这条反馈写回 Planner memory，
            # 让模型在下一步继续自我修正。
            feedback = build_repeated_action_feedback(
                agent_name,
                plan_action,
                "请不要重复同一条侦察；先基于现有 observation 判断是否应 add_task / split_task / retry_task / subagent_tool，"
                "或改用新的侦察动作来补当前缺口。",
            )
            push_planner_feedback(runtime, planner_memory_step, feedback)
            LOGGER.warning(feedback, indent="  ")
            continue

        # 只要返回的已经不是侦察动作，就说明 Planner 已经准备好交出控制权了。
        if plan_action.tool not in PLANNER_RESEARCH_ACTIONS:
            return plan_action

        planner_action_guard.remember(plan_action)
        # 真正执行侦察工具，并把 observation 写回 Planner memory。
        result = execute_runtime_tool(runtime, plan_action.tool, plan_action.parameters, log_prefix="  ")
        runtime.planner_memory.add_memory(
            planner_memory_step,
            plan_action.tool,
            plan_action.parameters,
            result,
        )
        LOGGER.tool_result(result, indent="  ", label="规划侦察结果")

    raise ValueError("Planner 在侦察预算耗尽后仍未返回控制动作")


def run_main_loop(runtime: AgentRuntime, max_iter: int = 30):
    """运行顶层 Plan-Agent 循环。

    这是全系统的最外层预算控制器：
    - 控制最大规划轮数；
    - 控制总运行时间；
    - 在任务全部 DONE 时提前结束；
    - 在预算耗尽时把未完成任务统一标成 BLOCKED。
    """
    # 先把三阶段共享的静态上下文一次性构造好。
    stage_context = build_stage_context(runtime.tool_service)
    # 最终规划轮数取调用方传入值和 runtime 默认预算的较小者。
    plan_iterations = min(max_iter, runtime.max_plan_iterations)
    # session_memory 会在任务重试时保存跨轮摘要。
    session_memory = SessionMemoryManager(runtime=runtime)

    for iteration in range(plan_iterations):
        if not has_runtime_time_left(runtime):
            # 最外层超时意味着整个程序已经没有再继续调度的意义。
            feedback = (
                f"总运行时间已达到预算上限（{runtime.max_total_runtime_seconds} 秒），"
                "未完成任务已标记为 BLOCKED。"
            )
            mark_unfinished_tasks_blocked(runtime, feedback)
            LOGGER.task_report(runtime.todo_list.get_all_tasks(), "运行预算耗尽")
            break

        # 让 Planner 决定当前这轮应该做什么。
        action = run_plan_step(runtime, iteration, stage_context)
        # 再由本地代码把这个控制动作真正落地。
        should_stop = handle_plan_action(
            runtime,
            action,
            stage_context,
            session_memory,
        )
        if runtime.todo_list.get_all_tasks():
            # 每轮结束后都打印一次任务面板，方便观察调度演化。
            LOGGER.task_snapshot(runtime.todo_list.get_all_tasks())
        if should_stop:
            break

        all_tasks = runtime.todo_list.get_all_tasks()
        if all_tasks and all(task.task_status == "DONE" for task in all_tasks):
            # 所有任务都进入 DONE 后，Planner 无需再继续推理下一步。
            LOGGER.task_report(all_tasks, "所有任务已完成")
            break
    else:
        feedback = (
            f"Planner 达到最大规划轮数（{plan_iterations} 轮），"
            "仍有任务未进入终态。"
        )
        mark_unfinished_tasks_blocked(runtime, feedback)
        LOGGER.task_report(runtime.todo_list.get_all_tasks(), "规划预算耗尽")
