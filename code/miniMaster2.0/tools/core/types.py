"""工具系统共享的数据结构定义。"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ToolSpec:
    """描述工具静态元信息。"""

    name: str
    description: str
    category: str
    input_schema: Dict[str, Any]


@dataclass
class ToolContext:
    """描述工具实例共享的运行时上下文。"""

    workspace: str = "."
    system_name: str = ""


@dataclass
class ToolResult:
    """描述新工具推荐使用的统一执行结果格式。"""

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
