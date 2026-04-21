"""领域数据结构定义。

这里集中声明 miniMaster 运行时最核心的几类对象。把这些对象抽成 dataclass 有利于：
- 让状态字段一目了然；
- 在不同模块之间传递时保持结构稳定；
- 方便后续用 `asdict()` 直接转成 Prompt 或日志需要的 payload。
"""

from dataclasses import dataclass
from typing import Any

TERMINAL_TASK_STATUSES = {"DONE", "FAILED", "BLOCKED"}


@dataclass
class Task:
    """任务卡片。

    可以把它理解成 Planner 与 Executor 之间共享的最小任务契约：
    Planner 负责生成和调整任务卡片，Executor/Validator 则围绕这张卡片推进。
    """
    task_name: str  # 任务标题，也是大多数本地查找和日志展示使用的主键。
    goal: str = ""  # 这项任务想回答什么问题。
    scope: str = ""  # 任务边界，防止执行阶段无限外扩。
    done_when: str = ""  # 完成条件，会进一步被拆成 completion checklist。
    deliverable: str = ""  # 最终应交付什么产物或说明。
    task_status: str = "PENDING"  # 当前生命周期状态。
    task_conclusion: str = ""  # Executor 提交的阶段性或最终结论。
    attempt_count: int = 0  # 当前任务已经执行过多少轮。
    last_feedback: str = ""  # 最近一次失败、阻塞或重试提示。
    recovery_reason: str = ""  # 若任务被 retry，记录为什么允许恢复。


@dataclass
class MemoryToolCall:
    """工作记忆里保存的“某一步做了什么调用”。"""
    tool_name: str  # 调用了哪个工具或哪种系统反馈。
    parameters: object  # 调用时传了什么参数。


@dataclass
class MemoryEntry:
    """工作记忆中的单步记录。

    一条记忆通常由三部分组成：
    - step: 第几步
    - tool_call: 调用了什么
    - result: 得到了什么结果
    """
    step: int  # 第几步。
    tool_call: MemoryToolCall  # 这一步做了什么。
    result: object  # 这一步拿到了什么结果。


@dataclass
class AgentAction:
    """模型返回的一次结构化动作。"""
    think: str  # 模型自带的简短推理说明，用于日志而不是业务判断。
    tool: str  # 本轮选择的动作名。
    parameters: dict  # 该动作对应的参数。


@dataclass
class AgentRuntime:
    """一次程序运行期间共享的总状态容器。

    `Runtime` 不是业务对象本身，而是 orchestration 层的“上下文背包”：
    主循环、执行器、验证器、工具系统都会从这里取自己需要的共享依赖。
    """
    user_query: str  # 本次运行要解决的用户输入。
    model_name: str  # 当前使用的模型名。
    llm_timeout_seconds: int  # 单次模型请求超时。
    client: Any  # LLM SDK client。
    tool_service: Any  # 全部工具的统一注册与执行入口。
    todo_list: Any  # 当前运行中的任务面板。
    planner_memory: Any  # Planner 专属工作记忆。
    generator_memory: Any  # Executor 专属工作记忆。
    validation_memory: Any  # Validator 专属工作记忆。
    skill_store: Any  # 可查询的 skill 仓库。
    started_at_monotonic: float  # 本次运行开始时的 monotonic 时间戳。
    retry_archive_by_task: dict[str, list[str]]  # 每个任务的历史重试摘要。
    max_plan_iterations: int = 8  # 顶层规划轮数上限。
    max_planner_research_steps: int = 3  # 单轮规划中允许的只读侦察步数。
    max_generator_steps: int = 20  # 单轮执行允许的最大步数。
    max_validate_steps: int = 8  # 单轮验证允许的最大步数。
    max_task_retries: int = 3  # 单个任务最多允许重试几轮。
    max_total_runtime_seconds: int = 600  # 整个程序的总运行预算。
