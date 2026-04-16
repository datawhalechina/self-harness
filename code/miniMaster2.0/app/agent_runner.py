from openai import OpenAI
from langsmith import traceable

from app.agent_types import AgentAction, AgentActionError
from prompting import decode_agent_tool_call


def require_agent_action(message, policy: dict, agent_name: str):
    """解析并校验某个 Agent 的原生 function call 结果。"""
    result = decode_agent_tool_call(message, policy)
    if result.ok:
        return result.payload

    failure = AgentActionError(error=result.error, raw_response=result.raw_response)

    raise ValueError(
        f"{agent_name} function call 解析失败: {failure.error}\n"
        f"原始响应:\n{failure.raw_response}"
    )


@traceable(name="Agent_Model_Call")
def call_agent_model(prompt: str, model_name: str, client: OpenAI, agent_name: str) -> str:
    """统一发起一次模型调用，并返回模型的文本内容。"""
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}]
    )
    content = response.choices[0].message.content
    return content or ""


@traceable(name="Agent_Function_Call")
def call_agent_function(
    prompt: str,
    system_prompt: str,
    tools: list,
    model_name: str,
    client: OpenAI,
    agent_name: str,
):
    """以原生 function call 方式请求 Agent 输出下一步动作。"""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        tools=tools,
        tool_choice="required",
        parallel_tool_calls=False,
    )
    return response.choices[0].message


def request_agent_action(
    prompt: str,
    system_prompt: str,
    policy: dict,
    tools: list,
    agent_name: str,
    model_name: str,
    client: OpenAI,
) -> AgentAction:
    """完成“调用模型并拿到合法动作”这一整套流程。"""
    message = call_agent_function(prompt, system_prompt, tools, model_name, client, agent_name)
    return require_agent_action(message, policy, agent_name)
