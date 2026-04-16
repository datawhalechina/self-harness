import json
from dataclasses import dataclass

from app.agent_types import AgentAction


CACHEABLE_RUNTIME_TOOLS = {"glob", "grep", "read"}
CACHE_INVALIDATING_RUNTIME_TOOLS = {"bash", "edit", "write"}


def _stable_payload(value: object) -> str:
    """把参数稳定序列化成适合签名比较的字符串。"""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return repr(value)


def build_tool_call_signature(tool_name: str, parameters: dict) -> str:
    """构造工具调用签名。"""
    return f"{tool_name}:{_stable_payload(parameters)}"


def build_action_signature(action: AgentAction) -> str:
    """构造 Agent 动作签名。"""
    return build_tool_call_signature(action.tool, action.parameters)


@dataclass
class ConsecutiveActionGuard:
    last_signature: str = ""

    def is_repeated(self, action: AgentAction) -> bool:
        """判断当前动作是否与上一个动作完全相同。"""
        signature = build_action_signature(action)
        return bool(self.last_signature) and signature == self.last_signature

    def remember(self, action: AgentAction):
        """记录最近一次动作签名。"""
        self.last_signature = build_action_signature(action)

    def reset(self):
        """清空最近动作记录。"""
        self.last_signature = ""


def build_repeated_action_feedback(agent_name: str, action: AgentAction, guidance: str) -> str:
    """生成统一的重复动作反馈。"""
    return (
        f"{agent_name} 重复发出了相同动作：tool={action.tool}, "
        f"parameters={_stable_payload(action.parameters)}。{guidance}"
    )
