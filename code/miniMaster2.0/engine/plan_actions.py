from __future__ import annotations

from domain.types import AgentAction, AgentRuntime, Task, TERMINAL_TASK_STATUSES
from engine.runner import run_task
from engine.support import LOGGER
from memory.session import SessionMemoryManager


def _get_task_name(task_item: object) -> str:
    if isinstance(task_item, dict):
        return " ".join(str(task_item.get("task_name", "")).split()).strip()
    return " ".join(str(task_item or "").split()).strip()


def _normalize_text_field(task_item: dict, field_name: str) -> str:
    return " ".join(str(task_item.get(field_name, "")).split()).strip()


def _normalize_init_tasks(task_list: list) -> list[dict]:
    """对 Planner 输出做最小必要清洗，不再注入隐式任务。"""
    normalized_tasks: list[dict] = []

    for item in task_list:
        normalized_item = {"task_name": _get_task_name(item)} if not isinstance(item, dict) else dict(item)
        task_name = _get_task_name(normalized_item)
        if not task_name:
            continue

        normalized_tasks.append(
            {
                "task_name": task_name,
                "goal": _normalize_text_field(normalized_item, "goal"),
                "scope": _normalize_text_field(normalized_item, "scope"),
                "done_when": _normalize_text_field(normalized_item, "done_when"),
                "deliverable": _normalize_text_field(normalized_item, "deliverable"),
            }
        )

    return normalized_tasks


def _build_single_task_payload(plan_params: dict) -> dict:
    return {
        "task_name": plan_params.get("task_name", ""),
        "goal": str(plan_params.get("goal", "")).strip(),
        "scope": str(plan_params.get("scope", "")).strip(),
        "done_when": str(plan_params.get("done_when", "")).strip(),
        "deliverable": str(plan_params.get("deliverable", "")).strip(),
    }


def _select_next_task(tasks: list[Task]) -> Task | None:
    """按最直观的状态顺序选择下一个任务。"""
    running_tasks = [task for task in tasks if task.task_status == "RUNNING"]
    if running_tasks:
        return running_tasks[0]

    pending_tasks = [task for task in tasks if task.task_status == "PENDING"]
    return pending_tasks[0] if pending_tasks else None


def _select_requested_or_next_task(tasks: list[Task], requested_task_name: str) -> Task | None:
    """优先执行 Planner 指定的任务；否则回退到默认调度顺序。"""
    normalized_requested = " ".join(str(requested_task_name or "").split()).strip()
    if normalized_requested:
        for task in tasks:
            if task.task_name != normalized_requested:
                continue
            if task.task_status in {"PENDING", "RUNNING"}:
                return task
            return None
    return _select_next_task(tasks)


def handle_plan_action(
    runtime: AgentRuntime,
    action: AgentAction,
    stage_context: dict,
    session_memory: SessionMemoryManager,
) -> bool:
    """处理一次 Plan-Agent 返回的控制动作。"""
    plan_tool = action.tool
    plan_params = action.parameters

    has_unfinished_tasks = any(task.task_status not in TERMINAL_TASK_STATUSES for task in runtime.todo_list.get_all_tasks())
    if plan_tool == "init_tasks" and has_unfinished_tasks:
        LOGGER.warning("当前已有未完成任务，已在本地拦截重复 init_tasks。")
        return False

    if plan_tool == "init_tasks":
        task_list = plan_params.get("tasks", [])
        normalized_tasks = _normalize_init_tasks(task_list)
        runtime.todo_list.init_tasks(normalized_tasks)
        LOGGER.success(f"已初始化任务列表: {normalized_tasks}")
        return False

    if plan_tool == "add_task":
        task_payload = _build_single_task_payload(plan_params)
        task_name = task_payload["task_name"]
        if task_name:
            normalized_tasks = _normalize_init_tasks(
                [task_payload],
            )
            if not normalized_tasks:
                LOGGER.warning(f"任务 '{task_name}' 归一化后为空，已忽略。")
                return False

            for normalized_task in normalized_tasks:
                existing_task = runtime.todo_list.get_task_by_name(normalized_task["task_name"])
                if existing_task is not None:
                    continue
                runtime.todo_list.add_task(
                    normalized_task["task_name"],
                    goal=str(normalized_task.get("goal", "")).strip(),
                    scope=str(normalized_task.get("scope", "")).strip(),
                    done_when=str(normalized_task.get("done_when", "")).strip(),
                    deliverable=str(normalized_task.get("deliverable", "")).strip(),
                )
                LOGGER.success(f"已添加任务: {normalized_task['task_name']}")
        return False

    if plan_tool == "retry_task":
        task_name = str(plan_params.get("task_name", "")).strip()
        reason = str(plan_params.get("reason", "")).strip()
        task = runtime.todo_list.get_task_by_name(task_name)
        if not task:
            LOGGER.warning(f"未找到任务: {task_name}")
            return False
        if task.task_status not in {"FAILED", "BLOCKED"}:
            LOGGER.warning(f"任务 '{task_name}' 当前状态为 {task.task_status}，无需使用 retry_task。")
            return False
        if not reason:
            LOGGER.warning(f"任务 '{task_name}' 恢复时必须提供 reason。")
            return False
        if not runtime.todo_list.retry_task(task_name, reason):
            LOGGER.warning(f"任务 '{task_name}' 恢复失败，当前状态迁移不合法。")
            return False
        LOGGER.success(f"已恢复任务 '{task_name}' 为 PENDING，并记录恢复原因。")
        return False

    if plan_tool == "split_task":
        target_task_name = str(plan_params.get("target_task_name", "")).strip()
        reason = str(plan_params.get("reason", "")).strip()
        subtasks = plan_params.get("subtasks", [])
        target_task = runtime.todo_list.get_task_by_name(target_task_name)

        if not target_task:
            LOGGER.warning(f"未找到任务: {target_task_name}")
            return False
        if target_task.task_status not in {"PENDING", "FAILED", "BLOCKED"}:
            LOGGER.warning(
                f"任务 '{target_task_name}' 当前状态为 {target_task.task_status}，"
                "只允许拆分 PENDING / FAILED / BLOCKED 任务。"
            )
            return False
        if not reason:
            LOGGER.warning(f"任务 '{target_task_name}' 拆分时必须提供 reason。")
            return False

        normalized_subtasks = _normalize_init_tasks(subtasks)
        if not normalized_subtasks:
            LOGGER.warning(f"任务 '{target_task_name}' 的子任务列表为空，已忽略拆分。")
            return False

        for subtask in normalized_subtasks:
            if subtask["task_name"] == target_task_name:
                LOGGER.warning("split_task 生成的子任务名不能与原任务名完全相同。")
                return False

        if not runtime.todo_list.replace_task_with_subtasks(target_task_name, normalized_subtasks):
            LOGGER.warning(
                f"任务 '{target_task_name}' 拆分失败。请检查子任务名称是否为空、重复，"
                "或与现有任务冲突。"
            )
            return False

        runtime.retry_archive_by_task.pop(target_task_name, None)
        LOGGER.success(f"已将任务 '{target_task_name}' 拆分为 {len(normalized_subtasks)} 个子任务。")
        LOGGER.info(f"拆分原因: {reason}")
        for index, subtask in enumerate(normalized_subtasks, start=1):
            LOGGER.info(f"  {index}. {subtask['task_name']}")
        return False

    if plan_tool == "respond_to_user":
        message = plan_params.get("message", "")
        if message:
            LOGGER.user_message(message)
        return True

    if plan_tool == "subagent_tool":
        requested_task_name = str(plan_params.get("task_name", "")).strip()
        scheduled_task = _select_requested_or_next_task(runtime.todo_list.get_all_tasks(), requested_task_name)
        if scheduled_task is None:
            if requested_task_name:
                requested_task = runtime.todo_list.get_task_by_name(requested_task_name)
                if requested_task is None:
                    LOGGER.warning(f"Planner 请求执行 '{requested_task_name}'，但未找到该任务。")
                else:
                    LOGGER.warning(
                        f"Planner 请求执行 '{requested_task_name}'，但该任务当前状态为 {requested_task.task_status}，"
                        "不可直接执行。"
                    )
            else:
                LOGGER.warning("当前没有可执行任务；请先初始化任务、补充任务，或恢复 FAILED/BLOCKED 任务。")
            return False
        if requested_task_name and scheduled_task.task_name != requested_task_name:
            LOGGER.warning(
                f"Planner 请求执行 '{requested_task_name}'，但 scheduler 选择了 '{scheduled_task.task_name}'。"
            )
        run_task(runtime, scheduled_task.task_name, stage_context, session_memory)
        return False

    return False
