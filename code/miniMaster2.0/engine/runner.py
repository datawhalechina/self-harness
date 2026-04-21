"""任务执行与重试主循环。

这一层是 miniMaster 的第二层循环，负责围绕单个任务驱动 Executor-Agent：
- 让 Executor 逐步取证
- 在适当时机提交任务结论
- 调用 Validator 做独立复核
- 若验证失败，则带着反馈进入下一轮重试
"""

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
    """统一生成总预算耗尽时的提示文案。"""
    return f"总运行时间已达到预算上限（{runtime.max_total_runtime_seconds} 秒），{detail}"


def _block_task_for_runtime_timeout(runtime: AgentRuntime, task_name: str, detail: str) -> bool:
    """若总运行预算已耗尽，则把当前任务标为 BLOCKED 并返回 True。"""
    if has_runtime_time_left(runtime):
        return False

    # 一旦总预算耗尽，当前任务就不再适合继续尝试，而应显式标记为阻塞。
    feedback = _build_runtime_timeout_feedback(runtime, detail)
    runtime.todo_list.update_task_status(task_name, "BLOCKED", actor="runner")
    runtime.todo_list.update_last_feedback(task_name, feedback)
    LOGGER.warning(feedback)
    return True


def _get_task_or_warn(runtime: AgentRuntime, task_name: str, warning_message: str) -> Task | None:
    """读取当前任务；若任务意外丢失则记录告警。"""
    task = runtime.todo_list.get_task_by_name(task_name)
    if task is None:
        LOGGER.warning(warning_message)
    return task


def _handle_terminal_task(task_name: str, task: Task) -> bool:
    """阻止对终态任务直接再次执行。"""
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
    """执行一次 Generator-Agent 决策。

    这里会根据当前已经走到第几步，动态调整 `execution_status`，
    用 Prompt 明确告诉模型“现在应该继续取证，还是必须收口”。
    """
    # 拿到 Executor 阶段的动作白名单和名字。
    role_context = stage_context["executor"]
    agent_name = role_context["agent_name"]
    LOGGER.agent_step(agent_name, step, icon="🔧", indent="  ")
    # 在请求模型前，先尝试压缩过长的旧执行记忆。
    session_memory.compact_generator_memory()
    # Prompt 上下文来自 task、working memory、retry history 和可用 skills。
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

    # 把当前任务及其执行上下文拼成 Prompt。
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
    """处理 Executor 重复动作，把两类反馈都写回 generator memory。"""
    feedback = build_repeated_action_feedback(
        executor_agent_name,
        action,
        "请更换动作；如果现有证据已经足够，请直接整理结论并调用 update_task_conclusion。",
    )
    # 第一条反馈：直接指出“你重复了同一动作”。
    push_generator_feedback(runtime, generator_step, feedback)
    runtime.todo_list.update_last_feedback(task_name, feedback)
    LOGGER.warning(feedback, indent="  ")

    # 除了指出“你重复了”，还要给出“为什么这会让执行停滞”的更高层反馈。
    stall_feedback = build_generator_stall_feedback(
        f"{executor_agent_name} 连续重复相同动作，当前没有新的执行信息。"
    )
    # 第二条反馈：指出重复的后果是“当前没有新信息”。
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
    """执行非结论类动作，并把结果写进 Generator 工作记忆。"""
    # 先走真实工具执行链。
    result = execute_runtime_tool(runtime, action.tool, action.parameters, log_prefix="  ")
    # 再把执行结果压成适合后续 Prompt 继续使用的记忆条目。
    runtime.generator_memory.add_memory(generator_step, action.tool, action.parameters, result)
    LOGGER.tool_result(result, indent="  ")

    if isinstance(result, dict) and result.get("success") is False:
        # 工具失败时，把错误写到任务卡的 last_feedback，供后续重试优先处理。
        error_message = result.get("error", "未知错误")
        runtime.todo_list.update_last_feedback(task_name, f"最近一次工具调用失败：{error_message}")


def _complete_task(runtime: AgentRuntime, task_name: str):
    """在验证通过后，把任务收束到 DONE 并清空阶段性记忆。"""
    # 先把任务推进到 DONE。
    runtime.todo_list.update_task_status(task_name, "DONE", actor="runner")
    # 通过验证后，旧反馈就没有保留价值了。
    runtime.todo_list.update_last_feedback(task_name, "")
    # 任务已经完成，执行/验证记忆清空，避免串到下一任务。
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
    """处理 Executor 提交的结论，并立即触发 Validator 复核。"""
    # Executor 最终交付的是文本结论，而不是直接改任务状态。
    conclusion = action.parameters.get("conclusion", "")
    runtime.todo_list.update_task_conclusion(task_name, conclusion)
    LOGGER.task_conclusion(executor_agent_name, conclusion, indent="  ")

    # 提交结论后立刻进入独立验证闭环。
    is_valid, validation_feedback = run_validate_loop(
        runtime,
        task_name,
        generator_step,
        stage_context,
    )
    if is_valid:
        _complete_task(runtime, task_name)
        return "done"

    # 验证失败不会直接把任务标成 FAILED，而是先带着反馈回到重试循环。
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
    """执行单轮尝试，直到任务完成、阻塞、丢失或需要再次重试。"""
    # 用于拦截本轮尝试里的重复动作。
    generator_action_guard = ConsecutiveActionGuard()

    for generator_step in range(1, runtime.max_generator_steps + 1):
        if _block_task_for_runtime_timeout(runtime, task_name, "当前任务被标记为 BLOCKED。"):
            return "blocked"

        # 每一步都重新从 todo_list 取任务，避免使用到陈旧引用。
        current_task = _get_task_or_warn(runtime, task_name, f"任务执行过程中丢失任务: {task_name}")
        if current_task is None:
            return "abort"

        # 让 Executor 决定当前这一步做什么。
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

        # 只有不重复的动作才会写进 guard 历史。
        generator_action_guard.remember(action)
        if action.tool != "update_task_conclusion":
            _handle_generator_tool_action(runtime, task_name, generator_step, action)
            continue

        # 一旦走到 `update_task_conclusion`，本轮尝试就转入“提交结论 -> 验证”。
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
    """当重试预算耗尽后，把任务最终标记为 FAILED。"""
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
    """执行单个任务，内部串起 Generator 与 Validate。

    这是第二层循环的入口。最外层的 Planner 只负责决定“该不该执行这个任务”，
    真正怎样执行、失败后怎样重试，都在这里处理。
    """
    # 先从任务面板里取到目标任务。
    task = runtime.todo_list.get_task_by_name(task_name)
    if not task:
        LOGGER.warning(f"未找到任务: {task_name}")
        return
    if _handle_terminal_task(task_name, task):
        return

    # 后续日志会反复使用 Executor 的名字。
    executor_agent_name = stage_context["executor"]["agent_name"]
    LOGGER.task_started(task_name, task)
    # 真正开始执行前，把任务从 PENDING 推到 RUNNING。
    runtime.todo_list.update_task_status(task_name, "RUNNING", actor="runner")
    # 新任务开始执行时，先清空旧反馈。
    runtime.todo_list.update_last_feedback(task_name, "")

    for retry_index in range(1, runtime.max_task_retries + 1):
        if _block_task_for_runtime_timeout(runtime, task_name, "当前任务被标记为 BLOCKED。"):
            return

        current_task = _get_task_or_warn(runtime, task_name, f"任务执行过程中丢失任务: {task_name}")
        if current_task is None:
            return

        # 每次新尝试前，先把上一轮已经积累的经验压缩归档，供下一轮 Prompt 使用。
        session_memory.capture_retry_archive(current_task)
        # 这次尝试正式开始，attempt_count +1。
        runtime.todo_list.increment_attempt_count(task_name)
        # 重新给本轮创建干净的 Generator working memory。
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
