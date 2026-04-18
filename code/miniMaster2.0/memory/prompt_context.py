from __future__ import annotations

from domain.task_requirements import render_completion_checklist
from domain.types import AgentRuntime, Task
from memory.session import SessionMemoryManager
from skills.store import render_skills_for_prompt


def _truncate(text: str, max_chars: int = 240) -> str:
    normalized_text = " ".join(str(text or "").split()).strip()
    if len(normalized_text) <= max_chars:
        return normalized_text
    return f"{normalized_text[: max_chars - 3]}..."


def _render_done_task_summaries(tasks: list[Task], limit: int = 4) -> str:
    completed_tasks = [task for task in tasks if task.task_status == "DONE"]
    if not completed_tasks:
        return "当前还没有已完成任务。"

    rendered_lines = []
    for task in completed_tasks[-limit:]:
        conclusion = _truncate(task.task_conclusion or "已完成，但尚未记录明确结论。")
        rendered_lines.append(f"- {task.task_name}: {conclusion}")
    return "\n".join(rendered_lines)


def _render_failed_task_signals(tasks: list[Task], limit: int = 4) -> str:
    blocked_or_failed_tasks = [task for task in tasks if task.task_status in {"FAILED", "BLOCKED"}]
    if not blocked_or_failed_tasks:
        return "当前没有 FAILED / BLOCKED 任务。"

    rendered_lines = []
    for task in blocked_or_failed_tasks[-limit:]:
        feedback = _truncate(task.last_feedback or "没有记录直接失败原因。")
        rendered_lines.append(f"- {task.task_name} [{task.task_status}]: {feedback}")
    return "\n".join(rendered_lines)


def _render_project_understanding(tasks: list[Task], limit: int = 4) -> str:
    evidence_lines = []
    for task in reversed(tasks):
        if task.task_status != "DONE":
            continue

        conclusion = str(task.task_conclusion or "").strip()
        if not conclusion:
            continue

        evidence_lines.append(f"- 来自任务《{task.task_name}》: {_truncate(conclusion)}")
        if len(evidence_lines) >= limit:
            break

    if not evidence_lines:
        return "当前还没有稳定的项目理解；如果用户请求覆盖范围大或边界不清，优先补充侦察任务。"

    evidence_lines.reverse()
    return "\n".join(evidence_lines)


def build_plan_prompt_context(runtime: AgentRuntime) -> dict[str, str]:
    """构造 Planner 需要的 prompt 上下文。"""
    tasks = runtime.todo_list.get_all_tasks()
    has_planner_research = bool(runtime.planner_memory.get_all_memories())
    if not tasks:
        planner_phase = (
            "当前处于初始规划阶段：系统里还没有任务。"
            "你应先根据 user_query 直接产出第一版任务列表，或在明显属于闲聊时直接回复用户。"
            "此阶段不要先做项目侦察。"
        )
    elif has_planner_research:
        planner_phase = (
            "当前处于任务细化阶段：系统里已经有一版初始任务，而且你已经拿到了一些项目侦察结果。"
            "请优先检查这些侦察结果是否应该改变任务结构；默认先 add_task 或 split_task，"
            "如果当前侦察还只覆盖局部目录，先补齐主要顶层模块边界，再决定是否执行。"
            "只有当你能明确说明现有任务已经与已发现的模块边界或执行链路足够贴合时，才交给 executor。"
        )
    else:
        planner_phase = (
            "当前处于任务细化阶段：系统里已经有一版初始任务。"
            "请把现有任务当作可修订草案；你可以先做少量只读侦察，再用 add_task / split_task 细化，"
            "优先做一次低成本的顶层盘点，不要一开始就钻进少数子目录。"
            "最后再决定是否交给 executor 执行。"
        )
    return {
        "done_task_summaries": _render_done_task_summaries(tasks),
        "failed_task_signals": _render_failed_task_signals(tasks),
        "current_project_understanding": _render_project_understanding(tasks),
        "planner_working_memory": runtime.planner_memory.get_prompt_context(view="planner"),
        "planner_phase": planner_phase,
    }


def build_executor_prompt_context(
    runtime: AgentRuntime,
    session_memory: SessionMemoryManager,
    task: Task | None,
) -> dict[str, str]:
    """构造 Executor 需要的 prompt 上下文。"""
    task_name = task.task_name if task else ""
    return {
        "available_skills": render_skills_for_prompt(runtime.skill_store.load_all()),
        "completion_checklist": render_completion_checklist(task),
        "retry_history": session_memory.get_retry_history_prompt(task_name),
        "working_memory": runtime.generator_memory.get_prompt_context(view="generator"),
    }


def build_validator_prompt_context(runtime: AgentRuntime, task: Task | None) -> dict[str, str]:
    """构造 Validator 需要的 prompt 上下文。"""
    return {
        "completion_checklist": render_completion_checklist(task),
        "task_history": runtime.generator_memory.get_prompt_context(view="generator"),
        "working_memory": runtime.validation_memory.get_prompt_context(view="validation"),
    }
