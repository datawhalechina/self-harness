from dataclasses import dataclass
from typing import Any, Union


@dataclass
class Task:
    task_name: str
    task_status: str = "PENDING"
    task_conclusion: str = ""


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
class AgentActionError:
    error: str
    raw_response: str


@dataclass
class AgentProtocolSuccess:
    payload: AgentAction
    raw_response: str
    ok: bool = True


@dataclass
class AgentProtocolFailure:
    error: str
    raw_response: str
    ok: bool = False


@dataclass
class AgentRuntime:
    user_query: str
    model_name: str
    client: Any
    tool_service: Any
    tool_result_cache: dict[str, object]
    todo_list: Any
    generator_memory: Any
    validation_memory: Any


AgentProtocolResult = Union[AgentProtocolSuccess, AgentProtocolFailure]
