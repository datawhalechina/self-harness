import json
from dataclasses import dataclass, field

from domain.types import AgentAction

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
    max_history: int = 4
    repeat_threshold: int = 2
    recent_signatures: list[str] = field(default_factory=list)

    def is_repeated(self, action: AgentAction) -> bool:
        """判断当前动作在最近若干步内是否已经重复出现。"""
        signature = build_action_signature(action)
        required_prior_matches = max(1, self.repeat_threshold - 1)
        return self.recent_signatures.count(signature) >= required_prior_matches

    def remember(self, action: AgentAction):
        """记录最近若干次动作签名。"""
        self.recent_signatures.append(build_action_signature(action))
        if len(self.recent_signatures) > self.max_history:
            self.recent_signatures = self.recent_signatures[-self.max_history:]

    def reset(self):
        """清空最近动作记录。"""
        self.recent_signatures.clear()


def build_repeated_action_feedback(agent_name: str, action: AgentAction, guidance: str) -> str:
    """生成统一的重复动作反馈。"""
    return (
        f"{agent_name} 重复发出了相同动作：tool={action.tool}, "
        f"parameters={_stable_payload(action.parameters)}。{guidance}"
    )
