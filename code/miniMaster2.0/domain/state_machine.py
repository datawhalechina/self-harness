"""任务状态机。

这个模块的目标是把“任务状态能否这样变化”写成显式规则，而不是散落在各处 if 判断里。
对教学来说，这能帮助读者看到：
- 状态本身是有限集合；
- 不同 actor 允许做的状态迁移并不一样；
- 一旦任务进入终态，就应该受到更严格的保护。
"""

from __future__ import annotations

from domain.types import TERMINAL_TASK_STATUSES, Task


class TaskStateTransitionError(ValueError):
    """非法任务状态迁移。"""


def _normalized_actor(actor: object) -> str:
    """把 actor 统一归一成小写非空字符串。"""
    normalized = str(actor or "system").strip().lower()
    return normalized or "system"


def _normalized_status(status: object) -> str:
    """把任务状态统一归一成大写字符串。"""
    return str(status or "").strip().upper()


def _can_transition(current_status: str, new_status: str, actor: str) -> bool:
    """集中声明合法状态迁移规则。

    这里最重要的教学点是：不是所有模块都能任意改状态。
    例如：
    - planner 只负责调度，不直接改任务状态；
    - retry 只能把 FAILED/BLOCKED 拉回 PENDING；
    - runner 才负责真正的执行态推进。
    """
    if current_status == new_status:
        # 原地写回同一状态被视为幂等，不报错。
        return True

    if actor == "bootstrap":
        # 启动阶段允许直接构造出任意合法初始状态。
        return new_status in {"PENDING", "RUNNING", "DONE", "FAILED", "BLOCKED"}

    if actor == "planner":
        # Planner 只负责调度，不直接改状态。
        return False

    if actor == "retry":
        # retry 是一条特殊恢复通道，只允许 FAILED/BLOCKED -> PENDING。
        return current_status in {"FAILED", "BLOCKED"} and new_status == "PENDING"

    if actor == "runner":
        # runner 才拥有标准的执行态推进权限。
        return (
            (current_status == "PENDING" and new_status == "RUNNING")
            or (current_status == "RUNNING" and new_status in {"DONE", "FAILED", "BLOCKED"})
        )

    if actor == "system":
        # system 是兜底控制者，但也只允许有限的安全迁移。
        return (
            (current_status in {"PENDING", "RUNNING"} and new_status == "BLOCKED")
            or (current_status == "PENDING" and new_status == "RUNNING")
            or (current_status == "RUNNING" and new_status in {"FAILED", "DONE"})
        )

    return False


def transition_task_status(task: Task, new_status: str, *, actor: str = "system") -> bool:
    """对单个任务执行受控状态迁移。

    这个函数是状态变更的唯一入口。谁想改任务状态，都应该通过它先过一遍规则检查。
    """
    # 先把旧状态、新状态和 actor 都规整成可比较的标准文本。
    current_status = _normalized_status(getattr(task, "task_status", ""))
    normalized_status = _normalized_status(new_status)
    normalized_actor = _normalized_actor(actor)

    if not normalized_status:
        raise TaskStateTransitionError("任务新状态不能为空")

    if current_status in TERMINAL_TASK_STATUSES and normalized_status != current_status and normalized_actor != "retry":
        # 终态默认不可再次修改，除非走显式 retry 恢复通道。
        raise TaskStateTransitionError(
            f"终态任务不能被 actor={normalized_actor} 从 {current_status} 改到 {normalized_status}"
        )

    if not _can_transition(current_status, normalized_status, normalized_actor):
        raise TaskStateTransitionError(
            f"非法状态迁移: actor={normalized_actor}, {current_status} -> {normalized_status}"
        )

    # 只有在所有检查都通过后，才真正落到对象字段上。
    task.task_status = normalized_status
    return True
