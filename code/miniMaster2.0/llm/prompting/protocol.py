"""Agent 动作协议与原生 function call 适配工具。

这个模块负责把模型原始输出转成程序可以安全处理的结构化结果，
并统一复用同一套动作合法性校验规则。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Sequence

from domain.types import AgentAction
from tools.core.types import ToolSpec


def build_openai_tools(
    actions: Sequence[ToolSpec],
    tool_spec_getter: Optional[Callable[[str], Optional[ToolSpec]]] = None,
) -> List[Dict[str, Any]]:
    """把动作策略转换成 OpenAI Chat Completions 可直接使用的 tools 定义。

    对于像 `respond_to_user`、`validate_tool` 这样的内部控制动作，schema
    直接来自动作定义；对于 `read`、`grep` 这类真实运行时工具，则优先从
    工具注册表读取其原生输入 schema，避免 Prompt 和工具实现再次分叉。
    """
    tools: List[Dict[str, Any]] = []

    for action in actions:
        action_name = action.name
        if not action_name:
            continue

        description = action.description
        schema = _has_explicit_schema(action)
        effective_spec = action

        if schema is None and tool_spec_getter is not None:
            # 对 read/grep 这类真实工具，优先从工具注册表取 schema，
            # 避免动作定义和工具实现出现两套参数规范。
            tool_spec = tool_spec_getter(action_name)
            if tool_spec:
                effective_spec = tool_spec
                description = description or tool_spec.description
                schema = tool_spec.input_schema

        if schema is None:
            raise ValueError(f"动作 '{action_name}' 缺少 schema，无法构造原生 function tool")

        tools.append(
            {
                "type": "function",
                "function": {
                    "name": effective_spec.name,
                    "description": description,
                    "parameters": schema,
                },
            }
        )

    return tools


def decode_agent_tool_call(message: Any, actions: Sequence[ToolSpec]) -> AgentAction:
    """把原生 function call 消息解析成统一动作结构，并按动作列表校验。

    当前主循环约定每轮只允许模型选择一个动作，因此这里会要求消息中
    恰好存在一个 tool_call。解析出的参数仍会继续复用既有的 schema
    校验逻辑，保证从“文本 JSON 协议”迁移到“原生 function call”后，
    动作合法性约束不会丢失。
    """
    # 当前主循环规定“一轮只允许一个动作”，因此这里也做强约束。
    tool_calls = list(getattr(message, "tool_calls", None) or [])
    raw_response = _serialize_message(message)

    if not tool_calls:
        _raise_invalid("模型未返回 function call", raw_response)

    if len(tool_calls) != 1:
        _raise_invalid("模型一次只能返回一个 function call", raw_response)

    tool_call = tool_calls[0]
    function_payload = getattr(tool_call, "function", None)
    tool_name = getattr(function_payload, "name", "")
    raw_arguments = getattr(function_payload, "arguments", "") or "{}"

    try:
        parameters = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        _raise_invalid(f"function call 参数 JSON 解析失败: {exc}", raw_response)

    if not isinstance(parameters, dict):
        _raise_invalid("function call 参数必须是 JSON 对象", raw_response)

    payload = {
        "think": getattr(message, "content", "") or "",
        "tool": tool_name,
        "parameters": parameters,
    }
    return validate_agent_payload(payload, actions, raw_response)


def validate_agent_payload(payload: Dict[str, Any], actions: Sequence[ToolSpec], raw_response: str) -> AgentAction:
    """根据策略检查已解析出的动作载荷是否合法。

    这里会重点确认三件事：第一，`tool`、`parameters` 等字段本身格式
    是否正确；第二，当前动作是否属于允许动作；第三，如果该动作定义了
    schema，参数内容是否满足最基本的类型与枚举约束。只有全部通过，
    才会把结果标记为可执行。
    """
    think = payload.get("think", "")
    tool = payload.get("tool", "")
    parameters = payload.get("parameters", {})

    if think and not isinstance(think, str):
        _raise_invalid("字段 'think' 必须是字符串", raw_response)

    if not isinstance(tool, str) or not tool.strip():
        _raise_invalid("字段 'tool' 必须是非空字符串", raw_response)

    if not isinstance(parameters, dict):
        _raise_invalid("字段 'parameters' 必须是对象", raw_response)

    allowed_actions = {action.name: action for action in actions}
    if tool not in allowed_actions:
        _raise_invalid(
            f"不允许的动作 '{tool}'，允许的动作有: {sorted(allowed_actions.keys())}",
            raw_response,
        )

    schema = _has_explicit_schema(allowed_actions[tool])
    if schema:
        validation_error = validate_schema(parameters, schema)
        if validation_error:
            _raise_invalid(f"动作 '{tool}' 参数不合法: {validation_error}", raw_response)

    return AgentAction(
        think=think,
        tool=tool,
        parameters=parameters,
    )


def validate_schema(params: Dict[str, Any], schema: Dict[str, Any]) -> str | None:
    """对动作参数做一层轻量级 schema 校验。

    这里没有引入完整 JSON Schema 库，而是只实现教学示例当前真正需要的
    几类校验：必填字段、字段类型、枚举值，以及可选的额外字段限制。
    这样代码更容易读懂，也足够支撑 miniMaster 当前的动作协议。
    """
    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])

    for field_name in required_fields:
        if field_name not in params:
            return f"缺少必填字段: {field_name}"

    if schema.get("additionalProperties") is False:
        unexpected = sorted(set(params.keys()) - set(properties.keys()))
        if unexpected:
            return f"存在未定义字段: {unexpected}"

    for field_name, value in params.items():
        field_schema = properties.get(field_name)
        if not field_schema:
            continue

        expected_type = field_schema.get("type")
        if expected_type and not _matches_type(expected_type, value):
            return f"字段 '{field_name}' 期望类型为 '{expected_type}'"

        enum_values = field_schema.get("enum")
        if enum_values is not None and value not in enum_values:
            return f"字段 '{field_name}' 必须是 {enum_values} 之一"

    return None


def _matches_type(expected_type: str, value: Any) -> bool:
    """判断一个值是否符合简化后的 schema 类型定义。

    由于这里只覆盖最常见的 JSON 类型，所以实现保持轻量。单独拆成
    私有函数后，`validate_schema` 的主体逻辑会更清楚，学生也更容易看懂
    “参数校验”到底是怎么一步步完成的。
    """
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


def _has_explicit_schema(spec: ToolSpec) -> Optional[Dict[str, Any]]:
    """区分“显式 schema”与默认空对象 schema。

    空对象 schema 在这里被视为“未声明参数结构”，这样上层就还有机会去工具注册表里补全。
    """
    schema = spec.input_schema
    if schema == {"type": "object", "properties": {}}:
        return None
    return schema


def _raise_invalid(error: str, raw_response: str) -> None:
    """抛出统一格式的解析错误，便于上层直接展示。"""
    raise ValueError(f"{error}\n原始响应:\n{raw_response}")


def _serialize_message(message: Any) -> str:
    """把 ChatCompletionMessage 中的关键信息整理成便于排错的字符串。"""
    payload = {
        "content": getattr(message, "content", "") or "",
        "tool_calls": [],
    }

    for tool_call in list(getattr(message, "tool_calls", None) or []):
        function_payload = getattr(tool_call, "function", None)
        payload["tool_calls"].append(
            {
                "id": getattr(tool_call, "id", ""),
                "name": getattr(function_payload, "name", ""),
                "arguments": getattr(function_payload, "arguments", ""),
            }
        )

    return json.dumps(payload, ensure_ascii=False)
