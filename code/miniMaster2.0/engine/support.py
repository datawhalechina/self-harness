"""引擎层通用辅助函数。

这个模块主要做三类事情：
- 提供跨 engine 复用的小判断
- 统一生成反馈文案
- 统一封装真实运行时工具执行入口
"""

from __future__ import annotations

import time

from domain.types import AgentRuntime, Task, TERMINAL_TASK_STATUSES
from utils.console import ConsoleLogger


_CONTROL_ACTIONS = {
    "init_tasks",
    "add_task",
    "subagent_tool",
    "retry_task",
    "split_task",
    "respond_to_user",
    "update_task_conclusion",
    "validate_tool",
}

LOGGER = ConsoleLogger()


def is_task_terminal(task: Task) -> bool:
    """判断任务是否已经进入终态。"""
    return task.task_status in TERMINAL_TASK_STATUSES


def has_runtime_time_left(runtime: AgentRuntime) -> bool:
    """检查总运行时长预算是否还有剩余。"""
    elapsed_seconds = time.monotonic() - runtime.started_at_monotonic
    return elapsed_seconds < runtime.max_total_runtime_seconds


def build_validation_stall_feedback(reason: str) -> str:
    """构造统一的验证阶段未收口反馈。"""
    return (
        "验证阶段未能收口。\n"
        f"具体问题：{reason}\n"
        "请先判断现有证据是否已经覆盖了全部验证条件。\n"
        "如果已经覆盖，请直接整理并修正任务结论，使结论与现有证据一致。\n"
        "如果仍有缺口，请明确还缺少哪一项条件，并补充能够覆盖该条件的新证据。\n"
        "下一步必须直接回应这个缺口，不要重复不会产生新信息的动作。"
    )


def build_generator_stall_feedback(reason: str) -> str:
    """构造统一的执行阶段未收口反馈。"""
    return (
        "执行阶段未能收口。\n"
        f"具体问题：{reason}\n"
        "请先判断现有证据是否已经足够支持 update_task_conclusion。\n"
        "如果已经足够，请直接整理结论并提交，不要继续重复读取或搜索。\n"
        "如果仍有缺口，请只补充能够直接弥补该缺口的新证据。\n"
        "下一步必须直接回应这个缺口，不要重复不会产生新信息的动作。"
    )


def push_generator_feedback(runtime: AgentRuntime, generator_step: int, feedback: str):
    """把反馈写入 Generator 工作记忆，供下一轮直接读取。"""
    # 故意写到 `step + 1`，这样在视觉上更像“下一步先处理这条反馈”。
    runtime.generator_memory.add_memory(generator_step + 1, "system_feedback", {}, feedback)


def push_validation_feedback(runtime: AgentRuntime, validation_step: int, feedback: str):
    """把反馈写入 Validation 工作记忆，供同一轮验证直接读取。"""
    runtime.validation_memory.add_memory(validation_step + 1, "system_feedback", {}, feedback)


def push_planner_feedback(runtime: AgentRuntime, planner_step: int, feedback: str):
    """把反馈写入 Planner 工作记忆，供当前规划轮继续反思。"""
    runtime.planner_memory.add_memory(planner_step + 1, "system_feedback", {}, feedback)


def mark_unfinished_tasks_blocked(runtime: AgentRuntime, feedback: str):
    """把所有未进入终态的任务标记为阻塞。"""
    for task in runtime.todo_list.get_all_tasks():
        if is_task_terminal(task):
            continue
        runtime.todo_list.update_task_status(task.task_name, "BLOCKED", actor="system")
        runtime.todo_list.update_last_feedback(task.task_name, feedback)


def execute_runtime_tool(runtime: AgentRuntime, tool_name: str, parameters: dict, log_prefix: str = ""):
    """执行真正的运行时工具。

    控制动作（如 `init_tasks`、`subagent_tool`）不应该混入工具执行链；
    只有真正访问文件系统/命令行的动作才会走到这里。
    """
    if tool_name in _CONTROL_ACTIONS:
        return {"success": False, "error": f"控制指令 '{tool_name}' 不应通过工具执行链调用"}

    if log_prefix:
        LOGGER.tool_execution_banner(
            tool_name,
            parameters,
            workspace_path=runtime.tool_service.get_workspace_path(),
            indent=log_prefix,
        )

    started_at = time.monotonic()
    result = runtime.tool_service.execute(tool_name, parameters)
    elapsed_seconds = time.monotonic() - started_at
    if log_prefix:
        LOGGER.tool_timing(tool_name, elapsed_seconds, indent=log_prefix)

    return result
