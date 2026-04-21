"""固定三个 Agent 的可用动作定义。"""

from __future__ import annotations

import json
from typing import Any, Sequence

from tools.core.types import ToolSpec


def _action(name: str, description: str, schema: dict[str, Any] | None = None) -> ToolSpec:
    """把 Agent 动作定义统一成 ToolSpec。

    这样“控制动作”和“真实工具”都能复用同一种结构描述，便于后续统一渲染成
    Prompt 文本和 OpenAI tools schema。
    """
    return ToolSpec(
        name=name,
        description=description,
        category="agent_control",
        input_schema=schema or {"type": "object", "properties": {}},
    )


def _display_schema(spec: ToolSpec) -> dict[str, Any] | None:
    """隐藏仅用于占位的空对象 schema。"""
    if spec.input_schema == {"type": "object", "properties": {}}:
        return None
    return spec.input_schema


PLAN_ACTIONS: tuple[ToolSpec, ...] = (
    # Planner 允许少量只读侦察，但真正修改文件的动作不在这里开放。
    _action("read", "只读读取文件内容，用于规划前侦察"),
    _action("glob", "只读查找文件和目录，用于规划前侦察"),
    _action("grep", "只读搜索文本内容，用于规划前侦察"),
    _action(
        "init_tasks",
        "初始化任务列表",
        {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "task_name": {"type": "string"},
                                    "goal": {"type": "string"},
                                    "scope": {"type": "string"},
                                    "done_when": {"type": "string"},
                                    "deliverable": {"type": "string"},
                                },
                                "required": ["task_name"],
                            },
                        ]
                    },
                },
            },
            "required": ["tasks"],
        },
    ),
    _action(
        "add_task",
        "添加单个任务",
        {
            "type": "object",
            "properties": {
                "task_name": {"type": "string"},
                "goal": {"type": "string"},
                "scope": {"type": "string"},
                "done_when": {"type": "string"},
                "deliverable": {"type": "string"},
            },
            "required": ["task_name"],
        },
    ),
    _action(
        "subagent_tool",
        "将任务交给执行智能体",
        {
            "type": "object",
            "properties": {
                "task_name": {
                    "type": "string",
                    "description": "要执行的任务名称",
                },
            },
            "required": ["task_name"],
        },
    ),
    _action(
        "retry_task",
        "显式恢复一个 FAILED 或 BLOCKED 任务，并记录恢复原因",
        {
            "type": "object",
            "properties": {
                "task_name": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["task_name", "reason"],
        },
    ),
    _action(
        "split_task",
        "把一个过大或已卡住的任务替换成若干更小的子任务",
        {
            "type": "object",
            "properties": {
                "target_task_name": {"type": "string"},
                "reason": {"type": "string"},
                "subtasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task_name": {"type": "string"},
                            "goal": {"type": "string"},
                            "scope": {"type": "string"},
                            "done_when": {"type": "string"},
                            "deliverable": {"type": "string"},
                        },
                        "required": ["task_name"],
                    },
                },
            },
            "required": ["target_task_name", "reason", "subtasks"],
        },
    ),
    _action(
        "respond_to_user",
        "直接回复用户，不进入任务调度",
        {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
            },
            "required": ["message"],
        },
    ),
)

EXECUTOR_ACTIONS: tuple[ToolSpec, ...] = (
    # Executor 拿到的是“完成任务”的职责，因此既能读、搜，也能改文件和提交结论。
    _action("bash", "执行 shell 命令"),
    _action("read", "读取文件内容"),
    _action("write", "写入文件内容"),
    _action("edit", "替换文件中的文本"),
    _action("glob", "按模式查找文件"),
    _action("grep", "搜索文本内容"),
    _action(
        "update_task_conclusion",
        "提交任务完成结论",
        {
            "type": "object",
            "properties": {
                "conclusion": {"type": "string"},
            },
            "required": ["conclusion"],
        },
    ),
)

VALIDATOR_ACTIONS: tuple[ToolSpec, ...] = (
    # Validator 只允许验证型只读操作和最终 validate_tool，不允许 write/edit。
    _action("bash", "执行 shell 命令"),
    _action("read", "读取文件内容"),
    _action("glob", "按模式查找文件"),
    _action("grep", "搜索文本内容"),
    _action(
        "validate_tool",
        "提交验证结论",
        {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["有效", "无效"]},
                "reason": {"type": "string"},
                "covered_requirements": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "missing_requirements": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["status", "covered_requirements", "missing_requirements"],
        },
    ),
)


def render_actions_text(actions: Sequence[ToolSpec]) -> str:
    """把动作列表渲染成适合放进 Prompt 的文本。"""
    blocks = []
    for action in actions:
        blocks.append(f"- {action.name}: {action.description}")
        schema = _display_schema(action)
        if schema:
            blocks.append(f"  Input schema: {json.dumps(schema, ensure_ascii=False)}")
    return "\n".join(blocks)
