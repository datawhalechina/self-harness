"""
工具系统的核心抽象层。

这里统一导出重构后工具框架的关键类型，外部模块只需 import tools.core
即可拿到常用基类、服务层和数据结构。
"""

from .base import BaseTool
from .catalog import ToolCatalog
from .discover import discover_tools
from .service import ToolService
from .types import ToolContext, ToolResult, ToolSpec

__all__ = [
    "BaseTool",
    "ToolCatalog",
    "ToolContext",
    "ToolResult",
    "ToolService",
    "ToolSpec",
    "discover_tools",
]
