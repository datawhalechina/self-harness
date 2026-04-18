from dataclasses import asdict
from typing import Optional

from domain.state_machine import TaskStateTransitionError, transition_task_status
from domain.types import Task


class ToDoList:
    """待办事项列表管理类。"""

    def __init__(self):
        self.tasks: list[Task] = []

    def _build_task(
        self,
        *,
        task_name: str,
        goal: str = "",
        scope: str = "",
        done_when: str = "",
        deliverable: str = "",
        task_status: str = "PENDING",
        task_conclusion: str = "",
        attempt_count: int = 0,
        last_feedback: str = "",
        recovery_reason: str = "",
    ) -> Task:
        return Task(
            task_name=task_name,
            goal=goal,
            scope=scope,
            done_when=done_when,
            deliverable=deliverable,
            task_status=str(task_status or "PENDING").strip().upper() or "PENDING",
            task_conclusion=task_conclusion,
            attempt_count=attempt_count,
            last_feedback=last_feedback,
            recovery_reason=recovery_reason,
        )

    def add_task(
        self,
        task_name: str,
        goal: str = "",
        scope: str = "",
        done_when: str = "",
        deliverable: str = "",
        task_status: str = "PENDING",
        task_conclusion: str = "",
        attempt_count: int = 0,
        last_feedback: str = "",
        recovery_reason: str = "",
    ):
        self.tasks.append(
            self._build_task(
                task_name=task_name,
                goal=goal,
                scope=scope,
                done_when=done_when,
                deliverable=deliverable,
                task_status=task_status,
                task_conclusion=task_conclusion,
                attempt_count=attempt_count,
                last_feedback=last_feedback,
                recovery_reason=recovery_reason,
            )
        )

    def init_tasks(self, task_list: list):
        for item in task_list:
            if isinstance(item, str):
                self.add_task(item)
                continue

            if not isinstance(item, dict):
                raise TypeError("init_tasks 只接受字符串或任务对象列表")

            task_name = str(item.get("task_name", "")).strip()
            if not task_name:
                raise ValueError("任务对象缺少 task_name")

            self.add_task(
                task_name=task_name,
                goal=str(item.get("goal", "")),
                scope=str(item.get("scope", "")),
                done_when=str(item.get("done_when", "")),
                deliverable=str(item.get("deliverable", "")),
                task_status=str(item.get("task_status", "PENDING")),
                task_conclusion=str(item.get("task_conclusion", "")),
                attempt_count=int(item.get("attempt_count", 0)),
                last_feedback=str(item.get("last_feedback", "")),
                recovery_reason=str(item.get("recovery_reason", "")),
            )

    def transition_task_status(self, task_name: str, new_status: str, *, actor: str = "system") -> bool:
        for task in self.tasks:
            if task.task_name == task_name:
                try:
                    return transition_task_status(task, new_status, actor=actor)
                except TaskStateTransitionError:
                    return False
        return False

    def update_task_status(self, task_name: str, new_status: str, *, actor: str = "system") -> bool:
        return self.transition_task_status(task_name, new_status, actor=actor)

    def update_task_conclusion(self, task_name: str, conclusion: str) -> bool:
        for task in self.tasks:
            if task.task_name == task_name:
                task.task_conclusion = conclusion
                return True
        return False

    def increment_attempt_count(self, task_name: str) -> bool:
        for task in self.tasks:
            if task.task_name == task_name:
                task.attempt_count += 1
                return True
        return False

    def update_last_feedback(self, task_name: str, feedback: str) -> bool:
        for task in self.tasks:
            if task.task_name == task_name:
                task.last_feedback = feedback
                return True
        return False

    def retry_task(self, task_name: str, reason: str) -> bool:
        for task in self.tasks:
            if task.task_name == task_name:
                if str(task.task_status).strip().upper() not in {"FAILED", "BLOCKED"}:
                    return False
                try:
                    transition_task_status(task, "PENDING", actor="retry")
                except TaskStateTransitionError:
                    return False
                task.attempt_count = 0
                task.last_feedback = ""
                task.recovery_reason = reason
                return True
        return False

    def replace_task_with_subtasks(self, target_task_name: str, subtasks: list[dict]) -> bool:
        if not subtasks:
            return False

        target_index = None
        for index, task in enumerate(self.tasks):
            if task.task_name == target_task_name:
                target_index = index
                break
        if target_index is None:
            return False

        existing_names = {
            task.task_name
            for index, task in enumerate(self.tasks)
            if index != target_index
        }
        seen_names: set[str] = set()
        replacement_tasks: list[Task] = []

        for item in subtasks:
            task_name = str(item.get("task_name", "")).strip()
            if not task_name:
                return False
            if task_name in existing_names or task_name in seen_names:
                return False

            seen_names.add(task_name)
            replacement_tasks.append(
                self._build_task(
                    task_name=task_name,
                    goal=str(item.get("goal", "")),
                    scope=str(item.get("scope", "")),
                    done_when=str(item.get("done_when", "")),
                    deliverable=str(item.get("deliverable", "")),
                    task_status=str(item.get("task_status", "PENDING")),
                    task_conclusion=str(item.get("task_conclusion", "")),
                    attempt_count=int(item.get("attempt_count", 0)),
                    last_feedback=str(item.get("last_feedback", "")),
                    recovery_reason=str(item.get("recovery_reason", "")),
                )
            )

        self.tasks = self.tasks[:target_index] + replacement_tasks + self.tasks[target_index + 1:]
        return True

    def get_all_tasks(self):
        return self.tasks.copy()

    def get_all_tasks_payload(self) -> list[dict]:
        return [asdict(task) for task in self.tasks]

    def get_task_by_name(self, task_name: str):
        for task in self.tasks:
            if task.task_name == task_name:
                return task
        return None

    def to_payload(self, task: Optional[Task]) -> Optional[dict]:
        if task is None:
            return None
        return asdict(task)
