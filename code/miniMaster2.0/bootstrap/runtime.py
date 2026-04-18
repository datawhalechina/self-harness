import os
import time

from dotenv import load_dotenv
from openai import OpenAI
from langsmith.wrappers import wrap_openai

from domain.todo import ToDoList
from domain.types import AgentRuntime
from memory.working_memory import WorkingMemory
from skills.store import SkillStore
from tools.core.service import ToolService


def _read_env_int(env_key: str, default: int) -> int:
    raw_value = str(os.environ.get(env_key, "")).strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def create_client_from_env():
    """从环境变量读取配置并构造 OpenAI 客户端。"""
    api_key = os.environ.get("API_KEY")
    base_url = os.environ.get("BASE_URL")
    model_name = os.environ.get("MODEL_NAME", "deepseek-chat")
    llm_timeout_seconds = _read_env_int("LLM_TIMEOUT_SECONDS", 120)

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
    return client, model_name, llm_timeout_seconds


def create_tool_service() -> ToolService:
    """构造运行时工具服务。"""
    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ToolService.bootstrap(workspace=workspace)


def create_skill_store(tool_service: ToolService) -> SkillStore:
    """构造目录化 skill package 存储。"""
    root = os.path.join(tool_service.get_workspace_path(), "skills", "library")
    return SkillStore(root=root)


def read_user_query() -> str:
    """读取并校验用户输入。"""
    user_query = input("请输入你的任务/查询: ").strip()
    if not user_query:
        print("查询不能为空，退出程序。")
        exit(1)
    return user_query


def build_runtime(
    user_query: str,
    model_name: str,
    llm_timeout_seconds: int,
    client,
    tool_service: ToolService,
) -> AgentRuntime:
    """构造运行期状态容器。"""
    return AgentRuntime(
        user_query=user_query,
        model_name=model_name,
        llm_timeout_seconds=llm_timeout_seconds,
        client=client,
        tool_service=tool_service,
        todo_list=ToDoList(),
        planner_memory=WorkingMemory(keep_latest_n=6),
        generator_memory=WorkingMemory(),
        validation_memory=WorkingMemory(),
        skill_store=create_skill_store(tool_service),
        started_at_monotonic=time.monotonic(),
        retry_archive_by_task={},
    )


def bootstrap_runtime() -> AgentRuntime:
    """完成入口阶段的环境初始化并返回 runtime。"""
    load_dotenv()
    client, model_name, llm_timeout_seconds = create_client_from_env()
    user_query = read_user_query()
    tool_service = create_tool_service()
    return build_runtime(
        user_query=user_query,
        model_name=model_name,
        llm_timeout_seconds=llm_timeout_seconds,
        client=client,
        tool_service=tool_service,
    )
