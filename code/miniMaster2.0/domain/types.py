from dataclasses import dataclass
from typing import Any

TERMINAL_TASK_STATUSES = {"DONE", "FAILED", "BLOCKED"}


@dataclass
class Task:
    task_name: str
    goal: str = ""
    scope: str = ""
    done_when: str = ""
    deliverable: str = ""
    task_status: str = "PENDING"
    task_conclusion: str = ""
    attempt_count: int = 0
    last_feedback: str = ""
    recovery_reason: str = ""


@dataclass
class MemoryToolCall:
    tool_name: str
    parameters: object


@dataclass
class MemoryEntry:
    step: int
    tool_call: MemoryToolCall
    result: object


@dataclass
class AgentAction:
    think: str
    tool: str
    parameters: dict


@dataclass
class AgentRuntime:
    user_query: str
    model_name: str
    llm_timeout_seconds: int
    client: Any
    tool_service: Any
    todo_list: Any
    planner_memory: Any
    generator_memory: Any
    validation_memory: Any
    skill_store: Any
    started_at_monotonic: float
    retry_archive_by_task: dict[str, list[str]]
    max_plan_iterations: int = 8
    max_planner_research_steps: int = 3
    max_generator_steps: int = 20
    max_validate_steps: int = 8
    max_task_retries: int = 3
    max_total_runtime_seconds: int = 600
