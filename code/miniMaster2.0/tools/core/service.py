"""工具系统的显式注册与运行入口。"""

import json
import os
import platform
from typing import Any, Dict, Optional

from tools.base_tool.bash_tool import BashTool
from tools.base_tool.edit_tool import EditTool
from tools.base_tool.read_tool import ReadTool
from tools.base_tool.write_tool import WriteTool
from tools.search_tool.glob_tool import GlobTool
from tools.search_tool.grep_tool import GrepTool

from .base import BaseTool
from .types import ToolContext, ToolSpec

BUILTIN_TOOLS = (
    BashTool,
    ReadTool,
    WriteTool,
    EditTool,
    GlobTool,
    GrepTool,
)


class ToolService:
    """为固定内置工具提供渲染、实例化和执行能力。"""

    def __init__(
        self,
        tool_classes: tuple[type[BaseTool], ...],
        context: ToolContext,
    ):
        self._tool_classes = {tool_class.spec.name: tool_class for tool_class in tool_classes}
        self.context = context

    @classmethod
    def bootstrap(cls, workspace: Optional[str] = None) -> "ToolService":
        """按固定内置工具集完成装配。"""
        default_workspace = workspace or os.getcwd()
        context = ToolContext(
            workspace=default_workspace,
            system_name=platform.system(),
        )
        return cls(tool_classes=BUILTIN_TOOLS, context=context)

    def execute(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行指定工具，并把常见失败统一收敛成结构化结果。"""
        try:
            tool = self.get_tool(name)
        except KeyError:
            return {"success": False, "error": f"未知工具: '{name}'"}

        try:
            return tool.execute(params)
        except Exception as exc:
            return {"success": False, "error": f"工具执行失败: {str(exc)}"}

    def render_prompt(self, category: Optional[str] = None) -> str:
        """渲染工具说明文本，供 Prompt 直接复用。"""
        specs = self._list_specs(category=category)
        return "\n".join(
            f"- {spec.name}: {spec.description}\n"
            f"  Input schema: {json.dumps(spec.input_schema, ensure_ascii=False)}"
            for spec in specs
        )

    def get_tool(self, name: str) -> BaseTool:
        """返回工具实例，供兼容层或高级调用方直接访问。"""
        tool_class = self._tool_classes.get(name)
        if tool_class is None:
            raise KeyError(name)

        return tool_class(context=self.context)

    def get_tool_spec(self, name: str) -> Optional[ToolSpec]:
        """返回工具的结构化静态定义。"""
        tool_class = self._tool_classes.get(name)
        if tool_class is None:
            return None
        return tool_class.spec

    def get_prompt_execution_context(self) -> Dict[str, str]:
        """返回 Prompt 层常用的统一执行上下文字段。

        Prompt 需要的并不是孤立的某一个环境值，而是一组彼此配合的事实：
        当前工作目录在哪里、系统是什么、命令实际通过什么 shell 执行。
        把这组字段在工具系统内部一次性整理好，可以减少上层主循环自己
        东拼西凑环境信息的重复工作。
        """
        return {
            "workspace_path": self.get_workspace_path(),
            "system_name": self.context.system_name or platform.system(),
            "command_shell": self._get_command_shell_name(),
        }

    def get_workspace_path(self) -> str:
        """返回当前工具系统共享的工作目录。

        相对路径解析、命令执行 cwd 以及“当前目录”语义都依赖这一路径。
        因此由 ToolService 统一对外暴露，比让上层模块各自维护更稳妥。
        """
        return self.context.workspace

    def _get_command_shell_name(self) -> str:
        """返回 bash 工具实际使用的底层命令 shell 名称。"""
        if hasattr(BashTool, "get_command_shell_name"):
            return BashTool.get_command_shell_name()
        return "shell"

    def _list_specs(self, category: Optional[str] = None) -> list[ToolSpec]:
        """返回全部内置工具定义；可按分类过滤。"""
        specs = [tool_class.spec for tool_class in self._tool_classes.values()]
        if category is None:
            return specs
        return [spec for spec in specs if spec.category == category]
