from __future__ import annotations

from domain.types import AgentRuntime, Task
from engine.guards import ConsecutiveActionGuard, build_repeated_action_feedback
from engine.support import (
    LOGGER,
    build_generator_stall_feedback,
    execute_runtime_tool,
    has_runtime_time_left,
    is_task_terminal,
    push_generator_feedback,
)
from engine.validator import run_validate_loop
from llm.prompting.builders import build_generator_prompt
from llm.runner import request_agent_action
from memory.prompt_context import build_executor_prompt_context
from memory.session import SessionMemoryManager


def _build_runtime_timeout_feedback(runtime: AgentRuntime, detail: str) -> str:
    return f"总运行时间已达到预算上限（{runtime.max_total_runtime_seconds} 秒），{detail}"


def _block_task_for_runtime_timeout(runtime: AgentRuntime, task_name: str, detail: str) -> bool:
    if has_runtime_time_left(runtime):
        return False

    feedback = _build_runtime_timeout_feedback(runtime, detail)
    runtime.todo_list.update_task_status(task_name, "BLOCKED", actor="runner")
    runtime.todo_list.update_last_feedback(task_name, feedback)
    LOGGER.warning(feedback)
    return True


def _get_task_or_warn(runtime: AgentRuntime, task_name: str, warning_message: str) -> Task | None:
    task = runtime.todo_list.get_task_by_name(task_name)
    if task is None:
        LOGGER.warning(warning_message)
    return task


def _handle_terminal_task(task_name: str, task: Task) -> bool:
    if not is_task_terminal(task):
        return False

    guidance = "DONE 任务无需再次执行。"
    if task.task_status in {"FAILED", "BLOCKED"}:
        guidance = "如需恢复这个任务，请先调用 retry_task 并说明恢复原因。"
    feedback = str(task.last_feedback or "").strip()
    if feedback:
        guidance = f"{guidance} 最近反馈：{feedback}"
    LOGGER.warning(f"任务 '{task_name}' 当前状态为 {task.task_status}，已拦截直接执行。{guidance}")
    return True


def run_generator_step(
    runtime: AgentRuntime,
    task: Task,
    step: int,
    stage_context: dict,
    session_memory: SessionMemoryManager,
):
    """执行一次 Generator-Agent 决策。"""
    role_context = stage_context["executor"]
    agent_name = role_context["agent_name"]
    LOGGER.agent_step(agent_name, step, icon="🔧", indent="  ")
    session_memory.compact_generator_memory()
    memory_context = build_executor_prompt_context(runtime, session_memory, task)
    if step >= runtime.max_generator_steps:
        memory_context["execution_status"] = (
            "这已经是执行阶段最后一步。你必须基于已有证据直接调用 update_task_conclusion。"
            "如果仍有缺口，请在结论里明确写出哪些部分已经确认、哪些部分仍不确定；"
            "不要再继续调用工具。"
        )
    elif step >= runtime.max_generator_steps - 2:
        memory_context["execution_status"] = (
            f"当前执行已接近步数上限（第 {step} / {runtime.max_generator_steps} 步）。"
            "优先判断现有证据是否已经覆盖 done_when；如果已经基本覆盖，请尽快整理结论并收口。"
        )
    else:
        memory_context["execution_status"] = (
            f"当前是执行阶段第 {step} / {runtime.max_generator_steps} 步。"
            "只为弥补当前最关键缺口而取证，不要为了更完整而漫游式阅读。"
        )

    generator_prompt = build_generator_prompt(
        user_query=runtime.user_query,
        current_task=runtime.todo_list.to_payload(task),
        memory_context=memory_context,
        base_tools=stage_context["base_tools"],
        search_tools=stage_context["search_tools"],
        policy_text=role_context["policy_text"],
    )
    action = request_agent_action(
        prompt=generator_prompt,
        system_prompt=stage_context["system_prompt"],
        actions=role_context["actions"],
        tools=role_context["openai_tools"],
        agent_name=agent_name,
        model_name=runtime.model_name,
        client=runtime.client,
        timeout_seconds=runtime.llm_timeout_seconds,
        log_indent="  ",
    )
    LOGGER.agent_tool_selection(
        agent_name,
        action.tool,
        action.parameters,
        icon="🛠️",
        indent="  ",
    )
    return action


def _handle_repeated_generator_action(
    runtime: AgentRuntime,
    task_name: str,
    generator_step: int,
    action,
    executor_agent_name: str,
) -> bool:
    feedback = build_repeated_action_feedback(
        executor_agent_name,
        action,
        "请更换动作；如果现有证据已经足够，请直接整理结论并调用 update_task_conclusion。",
    )
    push_generator_feedback(runtime, generator_step, feedback)
    runtime.todo_list.update_last_feedback(task_name, feedback)
    LOGGER.warning(feedback, indent="  ")

    stall_feedback = build_generator_stall_feedback(
        f"{executor_agent_name} 连续重复相同动作，当前没有新的执行信息。"
    )
    push_generator_feedback(runtime, generator_step, stall_feedback)
    runtime.todo_list.update_last_feedback(task_name, stall_feedback)
    LOGGER.warning(stall_feedback, indent="  ")
    return True


def _handle_generator_tool_action(
    runtime: AgentRuntime,
    task_name: str,
    generator_step: int,
    action,
):
    result = execute_runtime_tool(runtime, action.tool, action.parameters, log_prefix="  ")
    runtime.generator_memory.add_memory(generator_step, action.tool, action.parameters, result)
    LOGGER.tool_result(result, indent="  ")

    if isinstance(result, dict) and result.get("success") is False:
        error_message = result.get("error", "未知错误")
        runtime.todo_list.update_last_feedback(task_name, f"最近一次工具调用失败：{error_message}")


def _complete_task(runtime: AgentRuntime, task_name: str):
    runtime.todo_list.update_task_status(task_name, "DONE", actor="runner")
    runtime.todo_list.update_last_feedback(task_name, "")
    runtime.generator_memory.clear_memories()
    runtime.validation_memory.clear_memories()
    LOGGER.task_completed(task_name)


def _handle_generator_conclusion(
    runtime: AgentRuntime,
    task_name: str,
    generator_step: int,
    action,
    executor_agent_name: str,
    stage_context: dict,
) -> str:
    conclusion = action.parameters.get("conclusion", "")
    runtime.todo_list.update_task_conclusion(task_name, conclusion)
    LOGGER.task_conclusion(executor_agent_name, conclusion, indent="  ")

    is_valid, validation_feedback = run_validate_loop(
        runtime,
        task_name,
        generator_step,
        stage_context,
    )
    if is_valid:
        _complete_task(runtime, task_name)
        return "done"

    runtime.todo_list.update_last_feedback(task_name, validation_feedback)
    LOGGER.retry_focus(validation_feedback, indent="  ")
    LOGGER.task_retrying(task_name, executor_agent_name)
    return "retry"


def _run_single_retry(
    runtime: AgentRuntime,
    task_name: str,
    executor_agent_name: str,
    stage_context: dict,
    session_memory: SessionMemoryManager,
) -> str:
    generator_action_guard = ConsecutiveActionGuard()

    for generator_step in range(1, runtime.max_generator_steps + 1):
        if _block_task_for_runtime_timeout(runtime, task_name, "当前任务被标记为 BLOCKED。"):
            return "blocked"

        current_task = _get_task_or_warn(runtime, task_name, f"任务执行过程中丢失任务: {task_name}")
        if current_task is None:
            return "abort"

        action = run_generator_step(
            runtime,
            current_task,
            generator_step,
            stage_context,
            session_memory,
        )
        if generator_action_guard.is_repeated(action):
            _handle_repeated_generator_action(runtime, task_name, generator_step, action, executor_agent_name)
            continue

        generator_action_guard.remember(action)
        if action.tool != "update_task_conclusion":
            _handle_generator_tool_action(runtime, task_name, generator_step, action)
            continue

        return _handle_generator_conclusion(
            runtime,
            task_name,
            generator_step,
            action,
            executor_agent_name,
            stage_context,
        )

    feedback = (
        f"{executor_agent_name} 达到最大执行步数（{runtime.max_generator_steps} 步），"
        "任务未能收口。"
    )
    runtime.todo_list.update_last_feedback(task_name, feedback)
    LOGGER.warning(feedback)
    return "retry"


def _mark_task_failed(runtime: AgentRuntime, task_name: str):
    current_task = runtime.todo_list.get_task_by_name(task_name)
    final_feedback = current_task.last_feedback if current_task else ""
    if not final_feedback:
        final_feedback = "任务在重试预算耗尽后仍未完成。"

    runtime.todo_list.update_task_status(task_name, "FAILED", actor="runner")
    runtime.todo_list.update_last_feedback(task_name, final_feedback)
    LOGGER.task_failed(task_name, final_feedback)


def run_task(
    runtime: AgentRuntime,
    task_name: str,
    stage_context: dict,
    session_memory: SessionMemoryManager,
):
    """执行单个任务，内部串起 Generator 与 Validate。"""
    task = runtime.todo_list.get_task_by_name(task_name)
    if not task:
        LOGGER.warning(f"未找到任务: {task_name}")
        return
    if _handle_terminal_task(task_name, task):
        return

    executor_agent_name = stage_context["executor"]["agent_name"]
    LOGGER.task_started(task_name, task)
    runtime.todo_list.update_task_status(task_name, "RUNNING", actor="runner")
    runtime.todo_list.update_last_feedback(task_name, "")

    for retry_index in range(1, runtime.max_task_retries + 1):
        if _block_task_for_runtime_timeout(runtime, task_name, "当前任务被标记为 BLOCKED。"):
            return

        current_task = _get_task_or_warn(runtime, task_name, f"任务执行过程中丢失任务: {task_name}")
        if current_task is None:
            return

        session_memory.capture_retry_archive(current_task)
        runtime.todo_list.increment_attempt_count(task_name)
        session_memory.reset_generator_memory()
        LOGGER.task_retry(executor_agent_name, retry_index)

        retry_outcome = _run_single_retry(
            runtime,
            task_name,
            executor_agent_name,
            stage_context,
            session_memory,
        )
        if retry_outcome in {"done", "blocked", "abort"}:
            return

    _mark_task_failed(runtime, task_name)
