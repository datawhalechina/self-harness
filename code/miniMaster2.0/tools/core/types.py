"""
工具系统共享的数据结构定义。

这些类型把“工具是什么、运行在什么上下文里、结果怎样向外返回”
从具体工具实现里抽离出来，便于整个框架以统一协议协作。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ToolSpec:
    """描述工具静态元信息。

    这里存放的是不会随单次调用变化的数据，例如名称、说明、分类和参数 schema。
    """

    name: str
    description: str
    category: str
    input_schema: Dict[str, Any]
    # 大多数工具都可以复用同一个实例；只有持有瞬时状态时才需要关闭单例。
    singleton: bool = True


@dataclass
class ToolContext:
    """描述工具实例共享的运行时上下文。

    当前主要用于传递工作目录和基础运行环境信息，后续也可以扩展环境变量
    或外部依赖句柄。把这些上下文集中到这里后，工具系统的不同层都能基于
    同一份环境认知工作，避免各处各自猜测“当前到底运行在什么环境里”。
    """

    workspace: str = "."
    system_name: str = ""
    env: Dict[str, str] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """描述新工具推荐使用的统一执行结果格式。"""

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
