"""不同 Agent 角色可用动作的策略定义。

这个模块的作用是把“某个 Agent 可以做什么、每个动作需要什么参数”
集中写成结构化配置。这样主程序和提示词系统都可以复用同一份规则，
避免出现“Prompt 里写的是一套规则，代码里校验的是另一套规则”的问题。
"""

from __future__ import annotations

import json
from typing import Any

from tools.core import ToolSpec


def _action_spec(name: str, description: str, schema: dict[str, Any] | None = None) -> ToolSpec:
    """把 Agent 动作定义统一成 ToolSpec。"""
    return ToolSpec(
        name=name,
        description=description,
        category="agent_control",
        input_schema=schema or {"type": "object", "properties": {}},
        singleton=True,
    )


def _display_schema(spec: ToolSpec) -> dict[str, Any] | None:
    """隐藏仅用于占位的空对象 schema。"""
    if spec.input_schema == {"type": "object", "properties": {}}:
        return None
    return spec.input_schema


def get_plan_policy() -> dict:
    """返回 Plan-Agent 的动作策略。

    Plan-Agent 负责做高层调度，所以这里只开放任务初始化、任务补充、
    状态更新、下发子任务，以及直接回复用户这几类动作。这样可以把
    “规划”与“执行”清晰分开，避免 Plan-Agent 直接越权调用底层工具。
    """
    return {
        "actions": [
            _action_spec(
                "init_tasks",
                "初始化任务列表",
                {
                    "type": "object",
                    "properties": {
                        "tasks": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["tasks"],
                },
            ),
            _action_spec(
                "add_task",
                "添加单个任务",
                {
                    "type": "object",
                    "properties": {
                        "task_name": {"type": "string"},
                    },
                    "required": ["task_name"],
                },
            ),
            _action_spec(
                "update_task_status",
                "更新任务状态",
                {
                    "type": "object",
                    "properties": {
                        "task_name": {"type": "string"},
                        "status": {"type": "string", "enum": ["PENDING", "DONE", "FAILED"]},
                    },
                    "required": ["task_name", "status"],
                },
            ),
            _action_spec(
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
            _action_spec(
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
        ]
    }


def get_generator_policy() -> dict:
    """返回 Generator-Agent 的动作策略。

    Generator-Agent 负责真正推进任务，因此这里主要开放文件读写、
    文本编辑、文件搜索、文本搜索和命令执行等底层能力。同时额外保留
    `update_task_conclusion`，让它在认为任务完成时能把结果正式提交给
    上层调度器。
    """
    return {
        "actions": [
            _action_spec("bash", "执行 shell 命令"),
            _action_spec("read", "读取文件内容"),
            _action_spec("write", "写入文件内容"),
            _action_spec("edit", "替换文件中的文本"),
            _action_spec("glob", "按模式查找文件"),
            _action_spec("grep", "搜索文本内容"),
            _action_spec(
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
        ]
    }


def get_validate_policy() -> dict:
    """返回 Validate-Agent 的动作策略。

    Validate-Agent 只做核查，不负责产出最终内容，所以这里保留的是
    “读取、搜索、执行检查命令”这类偏验证性的动作，并强制通过
    `validate_tool` 输出最终判断。这样的限制能让验证层保持独立，
    减少它和执行层职责混淆。
    """
    return {
        "actions": [
            _action_spec("bash", "执行 shell 命令"),
            _action_spec("read", "读取文件内容"),
            _action_spec("glob", "按模式查找文件"),
            _action_spec("grep", "搜索文本内容"),
            _action_spec(
                "validate_tool",
                "提交验证结论",
                {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["有效", "无效"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["status"],
                },
            ),
        ]
    }


def render_policy_text(policy: dict) -> str:
    """把结构化策略渲染成适合放进 Prompt 的文本。

    模型看到的通常是一段自然语言提示，而不是 Python 字典。因此这个
    方法会把动作名、动作说明、参数 schema 组织成可读文本，方便直接
    填入 Prompt 中。这样既保留了策略配置的结构化优势，也兼顾了模型
    读取提示词时的易理解性。
    """
    blocks = []
    for action in policy["actions"]:
        blocks.append(f"- {action.name}: {action.description}")
        schema = _display_schema(action)
        if schema:
            blocks.append(f"  Input schema: {json.dumps(schema, ensure_ascii=False)}")
    return "\n".join(blocks)
