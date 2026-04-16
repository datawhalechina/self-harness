"""
组合工具系统各组件的门面层。

ToolService 面向上层暴露一个稳定入口，把发现、实例化、执行和渲染
这些细节都封装起来。
"""

import os
import platform
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from .base import BaseTool
from .catalog import ToolCatalog
from .discover import PROJECT_ROOT, discover_tools
from .types import ToolContext, ToolSpec


class ToolService:
    """为工具发现、渲染和执行提供稳定入口。"""

    def __init__(
        self,
        catalog: ToolCatalog,
        context: ToolContext,
    ):
        self.catalog = catalog
        self.context = context
        self._singletons: Dict[str, BaseTool] = {}

    @classmethod
    def bootstrap(cls, workspace: Optional[str] = None) -> "ToolService":
        """按默认约定完成整套工具系统装配。"""
        catalog = ToolCatalog()
        discover_tools(catalog)

        # 若调用方未显式传入工作目录，则退化到当前进程目录或项目根目录。
        default_workspace = workspace or os.getcwd() or str(Path(PROJECT_ROOT))
        context = ToolContext(
            workspace=default_workspace,
            system_name=platform.system(),
        )
        return cls(catalog=catalog, context=context)

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
        specs = self.catalog.list_specs(category=category)
        return "\n".join(self.render_spec(spec) for spec in specs)

    def list_tool_names(self) -> List[str]:
        """列出所有已注册工具名称。"""
        return self.catalog.list_tool_names()

    def get_tool(self, name: str) -> BaseTool:
        """返回工具实例，供兼容层或高级调用方直接访问。"""
        spec = self.catalog.get_spec(name)
        builder = self.catalog.get_builder(name)

        if spec is None or builder is None:
            raise KeyError(name)

        if spec.singleton:
            if name not in self._singletons:
                self._singletons[name] = builder(context=self.context)
            return self._singletons[name]

        return builder(context=self.context)

    def get_tool_class(self, name: str) -> Optional[Type[BaseTool]]:
        """返回工具类本身，而不是实例。"""
        return self.catalog.get_builder(name)

    def get_tool_spec(self, name: str) -> Optional[ToolSpec]:
        """返回工具的结构化静态定义。"""
        return self.catalog.get_spec(name)

    def get_tools_by_category(self) -> Dict[str, List[str]]:
        """按原始分类聚合工具名称。"""
        return self.catalog.get_categories()

    def render_spec(self, spec: ToolSpec) -> str:
        """把单个 ToolSpec 渲染成 Prompt 中可直接使用的文本块。"""
        return (
            f"- {spec.name}: {spec.description}\n"
            f"  Input schema: {json.dumps(spec.input_schema, ensure_ascii=False)}"
        )

    def get_runtime_environment_context(self) -> Dict[str, str]:
        """返回当前工具系统所对应的运行环境上下文。

        Prompt 需要知道“当前系统是什么”和“命令工具实际通过什么 shell 执行”。
        这些信息本质上属于工具系统自身的运行事实，因此由 ToolService 对外
        统一提供，比在主循环或兼容层中手工判断更稳妥。
        """
        command_shell = self._get_command_shell_name()
        system_name = self.context.system_name or platform.system()
        return {
            "system_name": system_name,
            "command_shell": command_shell,
        }

    def get_prompt_execution_context(self) -> Dict[str, str]:
        """返回 Prompt 层常用的统一执行上下文字段。

        Prompt 需要的并不是孤立的某一个环境值，而是一组彼此配合的事实：
        当前工作目录在哪里、系统是什么、命令实际通过什么 shell 执行。
        把这组字段在工具系统内部一次性整理好，可以减少上层主循环自己
        东拼西凑环境信息的重复工作。
        """
        runtime_context = self.get_runtime_environment_context()
        return {
            "workspace_path": self.get_workspace_path(),
            "system_name": runtime_context["system_name"],
            "command_shell": runtime_context["command_shell"],
        }

    def get_workspace_path(self) -> str:
        """返回当前工具系统共享的工作目录。

        相对路径解析、命令执行 cwd 以及“当前目录”语义都依赖这一路径。
        因此由 ToolService 统一对外暴露，比让上层模块各自维护更稳妥。
        """
        return self.context.workspace

    def _get_command_shell_name(self) -> str:
        """从 bash 工具定义中读取实际使用的底层命令 shell。

        这里优先复用 bash 工具类自身暴露的静态信息，而不是在 Service 层
        再写一遍平台判断逻辑。这样底层 shell 的知识仍然归 bash 工具所有，
        Service 只负责组织并向上层暴露。
        """
        bash_tool_class = self.get_tool_class("bash")
        if bash_tool_class and hasattr(bash_tool_class, "get_command_shell_name"):
            return bash_tool_class.get_command_shell_name()
        return "shell"
