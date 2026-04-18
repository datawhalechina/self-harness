from __future__ import annotations

from domain.types import TERMINAL_TASK_STATUSES, Task


class TaskStateTransitionError(ValueError):
    """非法任务状态迁移。"""


def _normalized_actor(actor: object) -> str:
    normalized = str(actor or "system").strip().lower()
    return normalized or "system"


def _normalized_status(status: object) -> str:
    return str(status or "").strip().upper()


def _can_transition(current_status: str, new_status: str, actor: str) -> bool:
    if current_status == new_status:
        return True

    if actor == "bootstrap":
        return new_status in {"PENDING", "RUNNING", "DONE", "FAILED", "BLOCKED"}

    if actor == "planner":
        return False

    if actor == "retry":
        return current_status in {"FAILED", "BLOCKED"} and new_status == "PENDING"

    if actor == "runner":
        return (
            (current_status == "PENDING" and new_status == "RUNNING")
            or (current_status == "RUNNING" and new_status in {"DONE", "FAILED", "BLOCKED"})
        )

    if actor == "system":
        return (
            (current_status in {"PENDING", "RUNNING"} and new_status == "BLOCKED")
            or (current_status == "PENDING" and new_status == "RUNNING")
            or (current_status == "RUNNING" and new_status in {"FAILED", "DONE"})
        )

    return False


def transition_task_status(task: Task, new_status: str, *, actor: str = "system") -> bool:
    """对单个任务执行受控状态迁移。"""
    current_status = _normalized_status(getattr(task, "task_status", ""))
    normalized_status = _normalized_status(new_status)
    normalized_actor = _normalized_actor(actor)

    if not normalized_status:
        raise TaskStateTransitionError("任务新状态不能为空")

    if current_status in TERMINAL_TASK_STATUSES and normalized_status != current_status and normalized_actor != "retry":
        raise TaskStateTransitionError(
            f"终态任务不能被 actor={normalized_actor} 从 {current_status} 改到 {normalized_status}"
        )

    if not _can_transition(current_status, normalized_status, normalized_actor):
        raise TaskStateTransitionError(
            f"非法状态迁移: actor={normalized_actor}, {current_status} -> {normalized_status}"
        )

    task.task_status = normalized_status
    return True
