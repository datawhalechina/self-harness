from dataclasses import asdict
from typing import Optional

from app.agent_types import Task


class ToDoList:
    """待办事项列表管理类。"""

    def __init__(self):
        self.tasks: list[Task] = []

    def add_task(self, task_name: str, task_status: str = "PENDING", task_conclusion: str = ""):
        self.tasks.append(Task(task_name=task_name, task_status=task_status, task_conclusion=task_conclusion))

    def init_tasks(self, task_list: list):
        for item in task_list:
            if not isinstance(item, str):
                raise TypeError("init_tasks 只接受字符串列表")
            self.add_task(item)

    def update_task_status(self, task_name: str, new_status: str) -> bool:
        for task in self.tasks:
            if task.task_name == task_name:
                task.task_status = new_status
                return True
        return False

    def update_task_conclusion(self, task_name: str, conclusion: str) -> bool:
        for task in self.tasks:
            if task.task_name == task_name:
                task.task_conclusion = conclusion
                return True
        return False

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
