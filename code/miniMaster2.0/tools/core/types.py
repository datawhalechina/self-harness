"""工具系统共享的数据结构定义。"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ToolSpec:
    """描述工具静态元信息。

    它回答的是“这个工具叫什么、做什么、属于哪类、需要什么输入”。
    """

    name: str
    description: str
    category: str
    input_schema: Dict[str, Any]


@dataclass
class ToolContext:
    """描述工具实例共享的运行时上下文。

    所有工具都共享同一个 workspace 和 system_name，确保它们对执行环境的理解一致。
    """

    workspace: str = "."
    system_name: str = ""


@dataclass
class ToolResult:
    """描述新工具推荐使用的统一执行结果格式。"""

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
