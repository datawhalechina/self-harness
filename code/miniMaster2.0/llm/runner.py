"""模型调用入口。

这个模块把“请求模型 + 解析 function call + 统一报错”这套流程封装起来，
让上层 engine 只关心“拿到一个 AgentAction”，而不必关心 OpenAI SDK 细节。
"""

from openai import APITimeoutError, BadRequestError, OpenAI
from langsmith import traceable

from domain.types import AgentAction
from llm.prompting.protocol import decode_agent_tool_call
from utils.console import ConsoleLogger

LOGGER = ConsoleLogger()


def _should_retry_with_auto_tool_choice(exc: BadRequestError) -> bool:
    """判断当前报错是否适合从 required 降级到 auto 后重试。

    某些模型/模式下，`tool_choice="required"` 可能与服务端约束冲突。
    这里做一次有条件降级，是为了提升示例代码在不同后端上的兼容性。
    """
    error_message = str(exc).lower()
    return (
        "tool_choice" in error_message
        and "thinking mode" in error_message
        and ("required" in error_message or "object" in error_message)
    )


@traceable(name="Agent_Function_Call")
def call_agent_function(
    prompt: str,
    system_prompt: str,
    tools: list,
    model_name: str,
    client: OpenAI,
    timeout_seconds: int,
):
    """以原生 function call 方式请求 Agent 输出下一步动作。"""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    request_kwargs = {
        "model": model_name,
        "messages": messages,
        "tools": tools,
        "parallel_tool_calls": False,
        "timeout": timeout_seconds,
    }

    try:
        response = client.chat.completions.create(
            **request_kwargs,
            tool_choice="required",
        )
    except BadRequestError as exc:
        if not _should_retry_with_auto_tool_choice(exc):
            raise

        # 降级并不代表放弃工具调用，只是允许模型在该后端约束下自行决定具体 tool choice。
        response = client.chat.completions.create(
            **request_kwargs,
            tool_choice="auto",
        )

    return response.choices[0].message


def request_agent_action(
    prompt: str,
    system_prompt: str,
    actions,
    tools: list,
    agent_name: str,
    model_name: str,
    client: OpenAI,
    timeout_seconds: int,
    log_indent: str = "",
) -> AgentAction:
    """完成“调用模型并拿到合法动作”这一整套流程。"""
    LOGGER.model_request(agent_name, model_name, timeout_seconds, indent=log_indent)
    try:
        message = call_agent_function(prompt, system_prompt, tools, model_name, client, timeout_seconds)
    except APITimeoutError as exc:
        raise TimeoutError(f"{agent_name} 请求模型超时（{timeout_seconds} 秒）") from exc
    LOGGER.model_response(agent_name, indent=log_indent)
    try:
        # decode 阶段会再次做动作合法性校验，避免把原始模型输出直接当真。
        return decode_agent_tool_call(message, actions)
    except ValueError as exc:
        raise ValueError(f"{agent_name} function call 解析失败: {exc}") from exc
