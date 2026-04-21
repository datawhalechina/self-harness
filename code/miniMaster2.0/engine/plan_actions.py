"""处理 Planner 返回的控制动作。

Planner 负责“想”，但真正的任务列表修改、任务执行触发和用户回复，
都由本地代码在这里落地。这样做的好处是：
- 模型可以提出控制意图；
- 但真正的状态修改仍由确定性代码把关。
"""

from __future__ import annotations

from domain.types import AgentAction, AgentRuntime, Task, TERMINAL_TASK_STATUSES
from engine.runner import run_task
from engine.support import LOGGER
from memory.session import SessionMemoryManager


def _get_task_name(task_item: object) -> str:
    """从字符串或对象任务里提取并清洗 task_name。"""
    if isinstance(task_item, dict):
        return " ".join(str(task_item.get("task_name", "")).split()).strip()
    return " ".join(str(task_item or "").split()).strip()


def _normalize_text_field(task_item: dict, field_name: str) -> str:
    """统一压缩任务文本字段里的多余空白。"""
    return " ".join(str(task_item.get(field_name, "")).split()).strip()


def _normalize_init_tasks(task_list: list) -> list[dict]:
    """对 Planner 输出做最小必要清洗，不再注入隐式任务。

    这个函数只做“收口格式”的工作，不偷偷补全业务含义。
    这样便于教学时区分：
    - 哪些内容来自模型的明确决策；
    - 哪些内容只是本地代码做的格式规范化。
    """
    normalized_tasks: list[dict] = []

    for item in task_list:
        # 如果 Planner 只给了字符串任务名，就先包成统一对象结构。
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
    """把 add_task 动作参数整理成和 init_tasks 同构的任务对象。"""
    return {
        "task_name": plan_params.get("task_name", ""),
        "goal": str(plan_params.get("goal", "")).strip(),
        "scope": str(plan_params.get("scope", "")).strip(),
        "done_when": str(plan_params.get("done_when", "")).strip(),
        "deliverable": str(plan_params.get("deliverable", "")).strip(),
    }


def _select_next_task(tasks: list[Task]) -> Task | None:
    """按最直观的状态顺序选择下一个任务。

    当前调度策略非常简单：
    - 如果有 RUNNING，优先续跑它；
    - 否则取第一个 PENDING。

    这也提醒读者：miniMaster 的重点在 harness 结构，而不是复杂调度算法。
    """
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
            # Planner 指定了任务名时，只接受仍可执行的 PENDING/RUNNING 任务。
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
    """处理一次 Plan-Agent 返回的控制动作。

    返回值语义：
    - `True`: 顶层主循环应停止（典型场景是 `respond_to_user`）
    - `False`: 主循环继续
    """
    # 模型选择了哪个控制动作。
    plan_tool = action.tool
    # 该动作附带的参数。
    plan_params = action.parameters

    # 只要还有任何任务不在终态，就视为“存在未完成任务”。
    has_unfinished_tasks = any(task.task_status not in TERMINAL_TASK_STATUSES for task in runtime.todo_list.get_all_tasks())
    if plan_tool == "init_tasks" and has_unfinished_tasks:
        # 有未完成任务时重新 init_tasks 很危险，会把已有调度上下文冲掉，因此本地直接拦截。
        LOGGER.warning("当前已有未完成任务，已在本地拦截重复 init_tasks。")
        return False

    if plan_tool == "init_tasks":
        # init_tasks 会整体初始化一版任务草案。
        task_list = plan_params.get("tasks", [])
        normalized_tasks = _normalize_init_tasks(task_list)
        runtime.todo_list.init_tasks(normalized_tasks)
        LOGGER.success(f"已初始化任务列表: {normalized_tasks}")
        return False

    if plan_tool == "add_task":
        # add_task 只处理单个新任务，因此先转成与 init_tasks 相同的 payload 结构。
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
                # add_task 不是 replace 语义，所以同名任务会被静默忽略而不是覆盖。
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
        # retry_task 的本地校验重点是：任务必须存在、当前必须在 FAILED/BLOCKED、且必须给出恢复原因。
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
        # split_task 会用一组新子任务替换原任务。
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

        # 子任务先做格式归一化，再进入冲突检查。
        normalized_subtasks = _normalize_init_tasks(subtasks)
        if not normalized_subtasks:
            LOGGER.warning(f"任务 '{target_task_name}' 的子任务列表为空，已忽略拆分。")
            return False

        for subtask in normalized_subtasks:
            # 子任务名如果跟父任务完全相同，等于没有真正拆开。
            if subtask["task_name"] == target_task_name:
                LOGGER.warning("split_task 生成的子任务名不能与原任务名完全相同。")
                return False

        if not runtime.todo_list.replace_task_with_subtasks(target_task_name, normalized_subtasks):
            LOGGER.warning(
                f"任务 '{target_task_name}' 拆分失败。请检查子任务名称是否为空、重复，"
                "或与现有任务冲突。"
            )
            return False

        # 旧任务已经不存在，它积累的 retry 归档也应该一并删除。
        runtime.retry_archive_by_task.pop(target_task_name, None)
        LOGGER.success(f"已将任务 '{target_task_name}' 拆分为 {len(normalized_subtasks)} 个子任务。")
        LOGGER.info(f"拆分原因: {reason}")
        for index, subtask in enumerate(normalized_subtasks, start=1):
            LOGGER.info(f"  {index}. {subtask['task_name']}")
        return False

    if plan_tool == "respond_to_user":
        # 这一动作意味着 Planner 认为不需要再进入任务流。
        message = plan_params.get("message", "")
        if message:
            LOGGER.user_message(message)
        return True

    if plan_tool == "subagent_tool":
        # Planner 可以明确指定要执行哪个任务，也可以把选择权交给默认 scheduler。
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
        # 真正的执行工作会转入 runner 层，再由它串起 Generator + Validator。
        run_task(runtime, scheduled_task.task_name, stage_context, session_memory)
        return False

    return False
