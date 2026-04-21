"""把运行时状态渲染成 Prompt 需要的记忆视图。

同一份底层状态，对 Planner、Executor、Validator 来说关心点并不相同：
- Planner 关注任务进展和项目边界理解
- Executor 关注当前任务、retry 历史和当前工作记忆
- Validator 关注 checklist、task_history 和验证证据

因此这里并不简单返回原始对象，而是根据角色重组视图。
"""

from __future__ import annotations

from domain.task_requirements import render_completion_checklist
from domain.types import AgentRuntime, Task
from memory.session import SessionMemoryManager
from skills.store import render_skills_for_prompt


def _truncate(text: str, max_chars: int = 240) -> str:
    """把文本压成适合 Prompt 摘要展示的长度。"""
    # 先压成单行紧凑文本，避免换行在 Prompt 中占太多上下文。
    normalized_text = " ".join(str(text or "").split()).strip()
    if len(normalized_text) <= max_chars:
        return normalized_text
    return f"{normalized_text[: max_chars - 3]}..."


def _render_done_task_summaries(tasks: list[Task], limit: int = 4) -> str:
    """提炼最近完成任务的结论，帮助 Planner 建立累计项目理解。"""
    # 只挑已完成任务，因为它们的结论已经通过验证，稳定性更高。
    completed_tasks = [task for task in tasks if task.task_status == "DONE"]
    if not completed_tasks:
        return "当前还没有已完成任务。"

    rendered_lines = []
    for task in completed_tasks[-limit:]:
        # 结论通常比较长，因此进一步截断成可读摘要。
        conclusion = _truncate(task.task_conclusion or "已完成，但尚未记录明确结论。")
        rendered_lines.append(f"- {task.task_name}: {conclusion}")
    return "\n".join(rendered_lines)


def _render_failed_task_signals(tasks: list[Task], limit: int = 4) -> str:
    """提炼失败/阻塞信号，让 Planner 避免重复踩坑。"""
    # FAILED / BLOCKED 任务能告诉 Planner 哪些路径已经卡住。
    blocked_or_failed_tasks = [task for task in tasks if task.task_status in {"FAILED", "BLOCKED"}]
    if not blocked_or_failed_tasks:
        return "当前没有 FAILED / BLOCKED 任务。"

    rendered_lines = []
    for task in blocked_or_failed_tasks[-limit:]:
        feedback = _truncate(task.last_feedback or "没有记录直接失败原因。")
        rendered_lines.append(f"- {task.task_name} [{task.task_status}]: {feedback}")
    return "\n".join(rendered_lines)


def _render_project_understanding(tasks: list[Task], limit: int = 4) -> str:
    """从已完成任务中抽取“已经确认过的项目事实”。"""
    evidence_lines = []
    for task in reversed(tasks):
        # 只从 DONE 任务里抽取事实，避免把尚未验证的临时结论混进项目理解。
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
    # 只要 planner_memory 非空，就说明 Planner 已经做过至少一次侦察。
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
        # 最近完成任务的稳定结论。
        "done_task_summaries": _render_done_task_summaries(tasks),
        # 最近失败/阻塞信号。
        "failed_task_signals": _render_failed_task_signals(tasks),
        # 当前已经确认过的项目边界理解。
        "current_project_understanding": _render_project_understanding(tasks),
        # Planner 工作记忆的专用视图。
        "planner_working_memory": runtime.planner_memory.get_prompt_context(view="planner"),
        # 当前到底是“初始建任务”还是“侦察后细化任务”。
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
        # 可用 skills 在执行阶段才真正有价值，因为是否启用 skill 由 Executor 自主判断。
        "available_skills": render_skills_for_prompt(runtime.skill_store.load_all()),
        # 当前任务的逐项完成清单。
        "completion_checklist": render_completion_checklist(task),
        # 该任务历史重试摘要。
        "retry_history": session_memory.get_retry_history_prompt(task_name),
        # 当前执行阶段 working memory 视图。
        "working_memory": runtime.generator_memory.get_prompt_context(view="generator"),
    }


def build_validator_prompt_context(runtime: AgentRuntime, task: Task | None) -> dict[str, str]:
    """构造 Validator 需要的 prompt 上下文。"""
    return {
        # 验证器也围绕同一份 completion checklist 工作。
        "completion_checklist": render_completion_checklist(task),
        # task_history 实际上复用的是 Generator 的执行 working memory。
        "task_history": runtime.generator_memory.get_prompt_context(view="generator"),
        # working_memory 则是 Validator 自己新增的验证证据。
        "working_memory": runtime.validation_memory.get_prompt_context(view="validation"),
    }
