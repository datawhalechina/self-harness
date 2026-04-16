import os

from dotenv import load_dotenv
from openai import OpenAI
from langsmith.wrappers import wrap_openai

from app.agent_types import AgentRuntime
from runtime import ToDoList, WorkingMemory
from tools.core import ToolService


def create_client_from_env():
    """从环境变量读取配置并构造 OpenAI 客户端。"""
    api_key = os.environ.get("API_KEY")
    base_url = os.environ.get("BASE_URL")
    model_name = os.environ.get("MODEL_NAME", "deepseek-chat")

    if not api_key:
        print("错误: 未设置 API_KEY 环境变量")
        print("请在 .env 文件中设置: API_KEY=your_api_key_here")
        exit(1)

    if not base_url:
        print("错误: 未设置 BASE_URL 环境变量")
        print("请在 .env 文件中设置: BASE_URL=https://api.example.com")
        exit(1)

    client = wrap_openai(OpenAI(
        api_key=api_key,
        base_url=base_url,
    ))
    return client, model_name


def create_tool_service() -> ToolService:
    """构造运行时工具服务。"""
    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ToolService.bootstrap(workspace=workspace)


def read_user_query() -> str:
    """读取并校验用户输入。"""
    user_query = input("请输入你的任务/查询: ").strip()
    if not user_query:
        print("查询不能为空，退出程序。")
        exit(1)
    return user_query


def build_runtime(user_query: str, model_name: str, client, tool_service: ToolService) -> AgentRuntime:
    """构造运行期状态容器。"""
    return AgentRuntime(
        user_query=user_query,
        model_name=model_name,
        client=client,
        tool_service=tool_service,
        tool_result_cache={},
        todo_list=ToDoList(),
        generator_memory=WorkingMemory(),
        validation_memory=WorkingMemory(),
    )


def bootstrap_runtime() -> AgentRuntime:
    """完成入口阶段的环境初始化并返回 runtime。"""
    load_dotenv()
    client, model_name = create_client_from_env()
    user_query = read_user_query()
    tool_service = create_tool_service()
    return build_runtime(
        user_query=user_query,
        model_name=model_name,
        client=client,
        tool_service=tool_service,
    )
