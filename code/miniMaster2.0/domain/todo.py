"""待办任务列表管理。

如果把 `Task` 看成单张任务卡片，那么 `ToDoList` 就是卡片集合的本地仓库。
它负责：
- 新建任务
- 初始化任务列表
- 查找任务
- 更新结论、反馈和尝试次数
- 触发受控状态迁移
- 把一个大任务替换为多个子任务

注意它本身并不负责“决定该执行哪个任务”，那属于 engine 层调度逻辑。
"""

from dataclasses import asdict
from typing import Optional

from domain.state_machine import TaskStateTransitionError, transition_task_status
from domain.types import Task


class ToDoList:
    """待办事项列表管理类。"""

    def __init__(self):
        # 任务列表按 Planner 生成/调整的顺序保存，便于调度和展示。
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
        """集中封装 Task 构造，确保所有入口生成的字段格式一致。"""
        return Task(
            # task_name 不在这里额外改写，尽量保留上游传入的业务含义。
            task_name=task_name,
            goal=goal,
            scope=scope,
            done_when=done_when,
            deliverable=deliverable,
            # 状态统一转成大写，避免后续比较时出现 `pending` / `PENDING` 混用。
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
        """向任务列表尾部追加单个任务。"""
        # 通过 `_build_task()` 统一进栈，避免多入口产生格式漂移。
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
        """用 Planner 给出的初始任务列表填充本地任务面板。

        这里支持字符串和对象两种形式，是为了兼容更宽松的模型输出；
        但进入系统内部后，都会被规整成统一的 Task 结构。
        """
        for item in task_list:
            if isinstance(item, str):
                # 纯字符串任务只会填充 task_name，其余字段保持默认值。
                self.add_task(item)
                continue

            if not isinstance(item, dict):
                raise TypeError("init_tasks 只接受字符串或任务对象列表")

            # task_name 是任务对象的唯一硬要求。
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
        """按任务名定位任务，并委托状态机完成合法性检查。"""
        for task in self.tasks:
            if task.task_name == task_name:
                try:
                    # 真正的状态规则全部交给 state_machine，ToDoList 只做定位和委托。
                    return transition_task_status(task, new_status, actor=actor)
                except TaskStateTransitionError:
                    return False
        return False

    def update_task_status(self, task_name: str, new_status: str, *, actor: str = "system") -> bool:
        """保留一个更直观的别名，方便上层调用。"""
        return self.transition_task_status(task_name, new_status, actor=actor)

    def update_task_conclusion(self, task_name: str, conclusion: str) -> bool:
        """更新任务结论。

        结论由 Executor 生成，但是否真正“完成”还要交给 Validator 判断。
        """
        for task in self.tasks:
            if task.task_name == task_name:
                # 结论可以反复覆盖，因为一次任务可能经历多轮“执行 -> 验证失败 -> 改写结论”。
                task.task_conclusion = conclusion
                return True
        return False

    def increment_attempt_count(self, task_name: str) -> bool:
        """记录当前任务已经尝试过多少轮。"""
        for task in self.tasks:
            if task.task_name == task_name:
                # attempt_count 由 runner 在每轮执行前自增。
                task.attempt_count += 1
                return True
        return False

    def update_last_feedback(self, task_name: str, feedback: str) -> bool:
        """保存最近一次失败、阻塞或重试提示。"""
        for task in self.tasks:
            if task.task_name == task_name:
                # 这里只保留“最近一次”反馈，是为了让 Prompt 聚焦当前最该处理的问题。
                task.last_feedback = feedback
                return True
        return False

    def retry_task(self, task_name: str, reason: str) -> bool:
        """把 FAILED / BLOCKED 任务恢复为 PENDING，并清空执行痕迹。

        这是显式恢复动作，不是偷偷重跑。恢复原因会被保留下来，便于后续 Prompt 参考。
        """
        for task in self.tasks:
            if task.task_name == task_name:
                # 只有失败或阻塞任务才有“恢复”的意义。
                if str(task.task_status).strip().upper() not in {"FAILED", "BLOCKED"}:
                    return False
                try:
                    # 恢复动作必须走受控状态迁移。
                    transition_task_status(task, "PENDING", actor="retry")
                except TaskStateTransitionError:
                    return False
                # 恢复后把执行痕迹清零，让下一轮从干净状态重新开始。
                task.attempt_count = 0
                task.last_feedback = ""
                task.recovery_reason = reason
                return True
        return False

    def replace_task_with_subtasks(self, target_task_name: str, subtasks: list[dict]) -> bool:
        """把一个任务原地替换成多个子任务。

        “原地”的意思是尽量保留原任务所在位置，这样任务面板顺序仍大体反映 Planner 的原始意图。
        """
        if not subtasks:
            return False

        # 先找到原任务所在位置，后面会在这里原地替换。
        target_index = None
        for index, task in enumerate(self.tasks):
            if task.task_name == target_task_name:
                target_index = index
                break
        if target_index is None:
            return False

        # 拆分时要同时防止两类冲突：
        # 1. 与列表中其他既有任务重名
        # 2. 新子任务彼此重名
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

            # seen_names 用来防止同一批子任务内部重名。
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

        # 用切片拼接是最直接的“原地替换”方式：前半保留、插入子任务、后半续接。
        self.tasks = self.tasks[:target_index] + replacement_tasks + self.tasks[target_index + 1:]
        return True

    def get_all_tasks(self):
        """返回任务列表副本，避免调用方直接改写内部列表。"""
        return self.tasks.copy()

    def get_all_tasks_payload(self) -> list[dict]:
        """把任务列表转成更适合日志和 Prompt 的字典结构。"""
        return [asdict(task) for task in self.tasks]

    def get_task_by_name(self, task_name: str):
        """按任务名查找单个任务。"""
        for task in self.tasks:
            if task.task_name == task_name:
                return task
        return None

    def to_payload(self, task: Optional[Task]) -> Optional[dict]:
        """把单个任务安全地转成 payload；空任务直接返回 None。"""
        if task is None:
            return None
        return asdict(task)
