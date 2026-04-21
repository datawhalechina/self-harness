"""单次运行内的 session 级记忆管理。

WorkingMemory 更偏向“当前阶段正在看的局部上下文”，而 SessionMemoryManager 负责
跨重试轮次保留必要经验，例如：
- 上一轮结论
- 上一轮失败原因
- 上一轮执行/验证证据摘要
"""

from __future__ import annotations

from domain.types import AgentRuntime, Task
from memory.working_memory import DEFAULT_WORKING_MEMORY_MAX_CHARS, WorkingMemory

RETRY_ARCHIVE_LIMIT = 2


class SessionMemoryManager:
    """管理本次运行内的 session memory。"""

    def __init__(self, runtime: AgentRuntime):
        # manager 本身不持久化数据，只是围绕 runtime 中的几个 memory 做编排。
        self.runtime = runtime

    def reset_generator_memory(self):
        """为当前任务重新初始化一份执行记忆。

        每轮重试都应该有一份干净的 Generator working memory，
        避免把上轮细碎轨迹原封不动带入下一轮。
        """
        self.runtime.generator_memory = WorkingMemory(
            keep_latest_n=6,
            max_chars=DEFAULT_WORKING_MEMORY_MAX_CHARS,
        )

    def capture_retry_archive(self, task: Task | None):
        """在 retry 前压缩上一轮执行/验证经验，供下一轮复用。"""
        if task is None:
            return

        # 下面这些信号会决定“上一轮是否值得归档”。
        generator_has_memories = bool(self.runtime.generator_memory.get_all_memories())
        validation_has_memories = bool(self.runtime.validation_memory.get_all_memories())
        task_feedback = str(task.last_feedback or "").strip()
        task_conclusion = str(task.task_conclusion or "").strip()
        if not any([generator_has_memories, validation_has_memories, task_feedback, task_conclusion]):
            return

        archive_sections = []
        if task.attempt_count > 0:
            archive_sections.append(f"【上一轮尝试编号】\n- 第 {task.attempt_count} 轮尝试")
        if task_conclusion:
            archive_sections.append(f"【上一轮临时结论】\n- {task_conclusion}")
        if task_feedback:
            archive_sections.append(f"【上一轮未收口的直接原因】\n- {task_feedback}")
        if generator_has_memories:
            archive_sections.append(self.runtime.generator_memory.render_for_retry_summary(label="执行"))
        if validation_has_memories:
            archive_sections.append(self.runtime.validation_memory.render_for_retry_summary(label="验证"))

        # 把多个归档片段拼成一段完整重试摘要。
        archive_text = "\n\n".join(section for section in archive_sections if section.strip())
        if not archive_text:
            return

        # 每个任务单独维护自己的重试归档列表。
        archives = self.runtime.retry_archive_by_task.setdefault(task.task_name, [])
        if archives and archives[-1] == archive_text:
            # 如果最新摘要和上次完全一样，就不重复追加。
            return

        archives.append(archive_text)
        # 只保留最近几轮历史，避免重试上下文无限膨胀。
        self.runtime.retry_archive_by_task[task.task_name] = archives[-RETRY_ARCHIVE_LIMIT:]

    def get_retry_history_prompt(self, task_name: str, limit: int = RETRY_ARCHIVE_LIMIT) -> str:
        """读取当前任务最近几轮失败尝试的压缩摘要。"""
        archives = self.runtime.retry_archive_by_task.get(task_name, [])
        if not archives:
            return "当前还没有上一轮尝试摘要。"

        # 只取最近几轮，保持 Prompt 聚焦。
        selected_archives = archives[-limit:]
        rendered_sections = []
        start_index = len(archives) - len(selected_archives) + 1
        for offset, archive in enumerate(selected_archives, start=start_index):
            rendered_sections.append(f"【历史尝试 {offset}】\n{archive}")
        return "\n\n".join(rendered_sections)

    def compact_generator_memory(self) -> bool:
        """在执行阶段需要时压缩旧记忆。"""
        # 这里直接委托给 WorkingMemory，自身不重复实现压缩逻辑。
        return self.runtime.generator_memory.compact_old_memories()
