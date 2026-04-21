"""
所有工具共享的统一基类。

这个基类把工具系统里最容易重复的三件事集中处理：
1. 持有并暴露静态 ToolSpec 元信息
2. 在进入具体 run() 逻辑前做轻量参数校验
3. 把不同风格的返回值统一整理成上层可直接消费的 dict
"""

from __future__ import annotations
import os
from abc import ABC, abstractmethod
from typing import Any, Dict

from .types import ToolContext, ToolResult, ToolSpec


class BaseTool(ABC):
    """集中处理参数校验和结果归一化的工具基类。

    子类只需要声明 spec 并实现 run()，不必重复编写公共控制流。
    """

    # 子类必须覆盖这个类属性，用来声明工具名称、分类、参数结构等静态信息。
    spec: ToolSpec = None

    def __init__(self, context: ToolContext = None):
        """挂载共享上下文，例如工作目录和系统信息。"""
        if not isinstance(self.spec, ToolSpec):
            raise ValueError(f"{self.__class__.__name__} 必须定义名为 spec 的 ToolSpec")
        self.context = context or ToolContext()

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def description(self) -> str:
        return self.spec.description

    @property
    def category(self) -> str:
        return self.spec.category

    @property
    def input_schema(self) -> Dict[str, Any]:
        return self.spec.input_schema

    def validate(self, params: Dict[str, Any]) -> None:
        """按照 ToolSpec 中声明的简化 schema 做运行前校验。"""
        if not isinstance(params, dict):
            raise TypeError("工具参数必须是字典")

        # ToolSpec 里的 input_schema 会作为这次校验的依据。
        schema = self.input_schema
        properties = schema.get("properties", {})
        required_fields = schema.get("required", [])

        # 先检查缺失的必填字段，避免具体工具内部再做重复空值判断。
        for field_name in required_fields:
            if field_name not in params:
                raise ValueError(f"缺少必填字段: {field_name}")

        # 如果 schema 明确禁止额外字段，则在这里提前拦截拼写错误或脏参数。
        if schema.get("additionalProperties") is False:
            unexpected = sorted(set(params.keys()) - set(properties.keys()))
            if unexpected:
                raise ValueError(f"存在未定义字段: {unexpected}")

        for field_name, value in params.items():
            field_schema = properties.get(field_name)
            if not field_schema:
                # 未声明 schema 的字段在 additionalProperties=True 时直接放过。
                continue
            self._validate_field(field_name, value, field_schema)

    def resolve_path(self, path: str) -> str:
        """把路径参数解析成基于 workspace 的绝对路径。

        工具层允许模型传入相对路径，例如 `main.py`、`./docs`、`logs/*.txt`。
        同时也允许更贴近用户习惯的 `~/Desktop/test.txt`、`%USERPROFILE%\\Desktop`
        这类写法，因此这里会先展开用户目录和环境变量。
        为了保证所有工具对“当前目录”的理解一致，这里统一以
        `self.context.workspace` 为基准解析路径；如果传入的本来就是绝对路径，
        则原样返回。
        """
        if not path:
            # 空路径默认落回 workspace，自然对应“当前目录”语义。
            return self.context.workspace or os.getcwd()

        expanded_path = os.path.expandvars(os.path.expanduser(path))

        if os.path.isabs(expanded_path):
            # 绝对路径直接标准化后返回。
            return os.path.abspath(expanded_path)

        workspace = self.context.workspace or os.getcwd()
        # 相对路径统一挂到 workspace 下，确保所有工具解释一致。
        return os.path.abspath(os.path.join(workspace, expanded_path))

    def relativize_path(self, path: str) -> str:
        """尽量把绝对路径还原成相对 workspace 的展示路径。

        工具内部通常会把路径解析成绝对路径，便于稳定访问文件系统；
        但返回给 Agent 时，过长的绝对路径不够直观。因此这里会在路径位于
        workspace 内部时，尽量转回相对路径，便于模型阅读和总结。
        """
        workspace = self.context.workspace or os.getcwd()
        absolute_path = os.path.abspath(path)
        workspace_path = os.path.abspath(workspace)

        try:
            common_path = os.path.commonpath([absolute_path, workspace_path])
        except ValueError:
            # 不在同一盘符等情况下，commonpath 可能报错，此时直接返回绝对路径。
            return absolute_path

        if common_path != workspace_path:
            # 路径不在 workspace 内时，也保留绝对路径。
            return absolute_path

        relative_path = os.path.relpath(absolute_path, workspace_path)
        return "." if relative_path == "." else relative_path

    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行标准流程：校验参数 -> 运行工具 -> 归一化结果。

        这一步把所有工具执行都收敛成同一控制流，是整个工具系统可维护性的关键。
        """
        self.validate(params)
        result = self.run(dict(params))
        return self.normalize_result(result)

    def normalize_result(self, result: Any) -> Dict[str, Any]:
        """把 ToolResult 整理成统一的对外字典格式。"""
        if not isinstance(result, ToolResult):
            raise TypeError(
                f"{self.__class__.__name__}.run() 必须返回 ToolResult，实际返回 {type(result).__name__}"
            )

        # `success` 总是固定放在最前面，便于上层统一读取。
        payload = {"success": result.success, **result.data}
        if result.error is not None:
            payload["error"] = result.error
        return payload

    def _validate_field(self, field_name: str, value: Any, field_schema: Dict[str, Any]) -> None:
        """校验单个字段的类型和枚举范围。"""
        expected_type = field_schema.get("type")
        if expected_type and not self._matches_type(expected_type, value):
            raise TypeError(
                f"字段 '{field_name}' 期望类型为 '{expected_type}'，实际为 '{type(value).__name__}'"
            )

        enum_values = field_schema.get("enum")
        if enum_values is not None and value not in enum_values:
            raise ValueError(f"字段 '{field_name}' 必须是 {enum_values} 之一")

    def _matches_type(self, expected_type: str, value: Any) -> bool:
        """实现一套覆盖当前工具系统需求的基础 JSON 类型映射。"""
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "object":
            return isinstance(value, dict)
        return True

    @abstractmethod
    def run(self, params: Dict[str, Any]) -> Any:
        """执行工具自身的具体逻辑。"""
        raise NotImplementedError
