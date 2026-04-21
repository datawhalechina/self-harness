"""控制台日志工具。

这些函数和类不参与业务决策，但它们决定了运行过程是否“可观察”。
对教学项目来说，可观察性非常重要，因为读者需要看清楚：
- 每个 Agent 当前在第几步
- 选了什么动作
- 工具返回了什么
- 为什么重试或失败
"""

from __future__ import annotations

from domain.types import AgentAction, Task


def format_short_text(text: str, max_length: int = 120) -> str:
    """把多行或过长文本压缩成便于控制台展示的单行摘要。"""
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3].rstrip()}..."


def print_planner_reason(action: AgentAction, agent_name: str):
    """打印 Planner 的简要决策理由。"""
    reason = format_short_text(action.think, max_length=140)
    if reason:
        print(f"🧠 {agent_name} 判断: {reason}")


def print_task_card(task: Task, indent: str = ""):
    """按任务卡片结构打印关键信息。"""
    print(f"{indent}📝 任务名: {task.task_name}")
    if task.goal:
        print(f"{indent}🎯 目标: {task.goal}")
    if task.scope:
        print(f"{indent}🗂️ 范围: {task.scope}")
    if task.done_when:
        print(f"{indent}✅ 完成标准: {task.done_when}")
    if task.deliverable:
        print(f"{indent}📦 交付物: {task.deliverable}")


def print_task_snapshot(tasks: list[Task], title: str = "当前任务面板"):
    """打印简洁的任务面板快照，方便观察 Planner 的最新状态。"""
    if not tasks:
        print(f"\n📌 {title}: （暂无任务）")
        return

    print(f"\n📌 {title}")
    for index, task in enumerate(tasks, start=1):
        badges = []
        if task.attempt_count:
            badges.append(f"attempts={task.attempt_count}")
        if task.task_conclusion:
            badges.append("已写结论")
        if task.last_feedback:
            badges.append(f"反馈={format_short_text(task.last_feedback, max_length=70)}")

        badge_text = f" | {' | '.join(badges)}" if badges else ""
        print(f"  {index}. [{task.task_status}] {task.task_name}{badge_text}")
        if task.done_when:
            print(f"     完成标准: {format_short_text(task.done_when, max_length=100)}")


def print_retry_focus(feedback: str, indent: str = ""):
    """在重试前高亮下一轮需要直接回应的焦点。"""
    focus = format_short_text(feedback, max_length=180)
    if focus:
        print(f"{indent}🎯 下一轮聚焦: {focus}")


def print_tool_execution_banner(tool_name: str, parameters: dict, workspace_path: str, indent: str = ""):
    """打印工具执行前的关键上下文。"""
    if tool_name != "bash":
        return

    command = format_short_text(parameters.get("command", ""), max_length=220)
    timeout = parameters.get("timeout")

    print(f"{indent}📂 bash cwd: {workspace_path}")
    if timeout is not None:
        print(f"{indent}⏳ bash timeout: {timeout}s")
    if command:
        print(f"{indent}▶️ bash command: {command}")


def print_tool_timing(tool_name: str, elapsed_seconds: float, indent: str = "", cache_hit: bool = False):
    """打印工具执行耗时。"""
    suffix = "（缓存命中）" if cache_hit else ""
    print(f"{indent}⏱️ {tool_name} 耗时: {elapsed_seconds:.2f}s{suffix}")


def summarize_console_value(
    value: object,
    *,
    max_string_length: int = 240,
    max_collection_items: int = 6,
    max_depth: int = 4,
) -> object:
    """把可能很大的工具结果压缩成适合控制台展示的预览对象。"""
    if max_depth <= 0:
        return f"<{type(value).__name__}>"

    if isinstance(value, str):
        display_value = value.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
        if len(display_value) <= max_string_length:
            return display_value
        omitted = len(display_value) - max_string_length
        preview = display_value[:max_string_length].rstrip()
        return f"{preview}...（已截断，省略 {omitted} 个字符）"

    if isinstance(value, dict):
        items = list(value.items())
        summarized = {
            key: summarize_console_value(
                item,
                max_string_length=max_string_length,
                max_collection_items=max_collection_items,
                max_depth=max_depth - 1,
            )
            for key, item in items[:max_collection_items]
        }
        if len(items) > max_collection_items:
            summarized["..."] = f"省略 {len(items) - max_collection_items} 个字段"
        return summarized

    if isinstance(value, list):
        summarized = [
            summarize_console_value(
                item,
                max_string_length=max_string_length,
                max_collection_items=max_collection_items,
                max_depth=max_depth - 1,
            )
            for item in value[:max_collection_items]
        ]
        if len(value) > max_collection_items:
            summarized.append(f"...省略 {len(value) - max_collection_items} 项")
        return summarized

    if isinstance(value, tuple):
        summarized = tuple(
            summarize_console_value(
                item,
                max_string_length=max_string_length,
                max_collection_items=max_collection_items,
                max_depth=max_depth - 1,
            )
            for item in value[:max_collection_items]
        )
        if len(value) > max_collection_items:
            summarized = summarized + (f"...省略 {len(value) - max_collection_items} 项",)
        return summarized

    if isinstance(value, set):
        summarized_items = [
            summarize_console_value(
                item,
                max_string_length=max_string_length,
                max_collection_items=max_collection_items,
                max_depth=max_depth - 1,
            )
            for item in list(value)[:max_collection_items]
        ]
        if len(value) > max_collection_items:
            summarized_items.append(f"...省略 {len(value) - max_collection_items} 项")
        return summarized_items

    return value


def format_tool_result_preview(result: object, max_total_length: int = 700) -> str:
    """把工具结果格式化为单条控制台预览文本。"""
    summarized = summarize_console_value(result)
    preview = repr(summarized)
    if len(preview) <= max_total_length:
        return preview
    omitted = len(preview) - max_total_length
    compact_preview = preview[:max_total_length].rstrip()
    return f"{compact_preview}...（结果预览已截断，省略 {omitted} 个字符）"


class ConsoleLogger:
    """面向主循环的轻量控制台日志接口。

    这个类不维护复杂状态，只负责把主循环中的事件输出整理成统一格式。
    这样 orchestration 可以更专注于“发生了什么”，而不是“怎么打印出来”。
    """

    def stage_header(self, title: str, width: int = 60, line_char: str = "="):
        """打印阶段标题分隔线。"""
        print(f"\n{line_char * width}")
        print(title)
        print(f"{line_char * width}")

    def agent_iteration(self, agent_name: str, iteration: int):
        """打印 Planner 级别的轮次标题。"""
        self.stage_header(f"🔄 {agent_name} 第 {iteration} 次迭代")

    def agent_step(self, agent_name: str, step: int, icon: str, indent: str = ""):
        """打印单步执行标题。"""
        print(f"\n{indent}{icon} {agent_name} 第 {step} 步")

    def agent_tool_selection(
        self,
        agent_name: str,
        tool_name: str,
        parameters: dict,
        icon: str,
        indent: str = "",
    ):
        """打印 Agent 本轮选择的动作及参数。"""
        print(f"{indent}{icon} {agent_name} 选择工具: {tool_name}")
        print(f"{indent}{icon} 参数: {parameters}")

    def info(self, message: str, indent: str = "", icon: str = ""):
        prefix = f"{indent}{icon} " if icon else indent
        print(f"{prefix}{message}")

    def success(self, message: str, indent: str = ""):
        print(f"{indent}✅ {message}")

    def warning(self, message: str, indent: str = ""):
        print(f"{indent}⚠️  {message}")

    def error(self, message: str, indent: str = ""):
        print(f"{indent}❌ {message}")

    def planner_reason(self, action: AgentAction, agent_name: str):
        print_planner_reason(action, agent_name)

    def model_request(self, agent_name: str, model_name: str, timeout_seconds: int, indent: str = ""):
        print(f"{indent}🧠 请求 {agent_name}（model={model_name}, timeout={timeout_seconds}s）")

    def model_response(self, agent_name: str, indent: str = ""):
        print(f"{indent}🧠 {agent_name} 已返回响应")

    def task_started(self, task_name: str, task: Task):
        print(f"\n🚀 开始执行任务: {task_name}")
        print_task_card(task)

    def task_retry(self, agent_name: str, retry_index: int):
        print(f"🔁 {agent_name} 第 {retry_index} 次尝试")

    def tool_execution_banner(self, tool_name: str, parameters: dict, workspace_path: str, indent: str = ""):
        print_tool_execution_banner(tool_name, parameters, workspace_path, indent=indent)

    def tool_timing(self, tool_name: str, elapsed_seconds: float, indent: str = "", cache_hit: bool = False):
        print_tool_timing(tool_name, elapsed_seconds, indent=indent, cache_hit=cache_hit)

    def tool_result(self, result: object, indent: str = "", label: str = "工具执行结果"):
        self.success(f"{label}: {format_tool_result_preview(result)}", indent=indent)

    def task_conclusion(self, agent_name: str, conclusion: str, indent: str = ""):
        print(f"{indent}📝 {agent_name} 完成任务，结论: {conclusion}")

    def validation_result(self, status: str, reason: str, indent: str = ""):
        print(f"{indent}📊 验证结果: {status}, 原因: {reason}")

    def task_completed(self, task_name: str):
        print(f"\n✅ 任务 '{task_name}' 已完成并通过验证！")

    def retry_focus(self, feedback: str, indent: str = ""):
        print_retry_focus(feedback, indent=indent)

    def task_retrying(self, task_name: str, agent_name: str):
        self.warning(f"任务 '{task_name}' 验证未通过，{agent_name} 将继续重试...")

    def task_failed(self, task_name: str, feedback: str):
        self.error(f"任务 '{task_name}' 已失败：{feedback}")

    def user_message(self, message: str):
        print(f"\n💬 {message}")

    def task_snapshot(self, tasks: list[Task], title: str = "当前任务面板"):
        print_task_snapshot(tasks, title=title)

    def task_report(self, tasks: list[Task], title: str):
        """打印任务终态报告。"""
        print(f"\n=== {title} ===")
        for task in tasks:
            print_task_card(task)
            print(f"状态: {task.task_status}")
            print(f"尝试次数: {task.attempt_count}")
            print(f"结论: {task.task_conclusion or '（暂无结论）'}")
            if task.last_feedback:
                print(f"反馈: {task.last_feedback}")
