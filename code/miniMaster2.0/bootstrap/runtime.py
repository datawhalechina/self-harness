"""运行时装配入口。

本模块的职责不是“执行任务”，而是在程序真正开始前，先把运行期需要共享的
对象都准备好。这样主循环只需要接收一个 `AgentRuntime`，就能访问到：
- 用户查询
- LLM client
- 工具系统
- 待办任务列表
- 三类工作记忆
- skill 仓库

教学上，这种写法有两个价值：
1. 把“依赖创建”与“业务执行”分离，方便定位系统边界。
2. 让 `AgentRuntime` 成为显式的共享状态容器，避免到处传零散参数。
"""

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
    """读取正整数配置；为空、非法或非正数时都回退到默认值。"""
    # 先把环境变量读成字符串并去掉空白，避免后面 `int()` 时被奇怪空格干扰。
    raw_value = str(os.environ.get(env_key, "")).strip()
    # 没配时直接回退默认值，不把“缺省配置”视为错误。
    if not raw_value:
        return default
    try:
        # 只有真正可解析成整数的值才继续向下走。
        parsed = int(raw_value)
    except ValueError:
        # 配错格式时也回退默认值，保证启动阶段更稳。
        return default
    # 再额外要求必须是正数，避免 0 或负数把预算类配置搞坏。
    return parsed if parsed > 0 else default


def create_client_from_env():
    """从环境变量读取配置并构造 OpenAI 客户端。

    这里把“配置读取”和“client 创建”放在一起，是因为它们天然属于同一阶段：
    没有合法配置，就不应该继续进入主循环。
    """
    # API 访问凭证。
    api_key = os.environ.get("API_KEY")
    # 兼容不同供应商或代理地址。
    base_url = os.environ.get("BASE_URL")
    # 模型名允许从环境变量切换，便于同一套 harness 复用不同模型。
    model_name = os.environ.get("MODEL_NAME", "deepseek-chat")
    # 超时预算会直接传给 SDK。
    llm_timeout_seconds = _read_env_int("LLM_TIMEOUT_SECONDS", 120)

    if not api_key:
        print("错误: 未设置 API_KEY 环境变量")
        print("请在 .env 文件中设置: API_KEY=your_api_key_here")
        exit(1)

    if not base_url:
        print("错误: 未设置 BASE_URL 环境变量")
        print("请在 .env 文件中设置: BASE_URL=https://api.example.com")
        exit(1)

    # 这里额外用 LangSmith wrapper 包一下，目的是让后续模型调用能被追踪。
    client = wrap_openai(OpenAI(
        # 认证信息由 SDK 在请求时带出去。
        api_key=api_key,
        # base_url 允许指向第三方兼容接口。
        base_url=base_url,
    ))
    return client, model_name, llm_timeout_seconds


def create_tool_service() -> ToolService:
    """构造运行时工具服务。

    workspace 取 miniMaster2.0 根目录，这样所有工具对“相对路径”的理解都会一致。
    """
    # `bootstrap/runtime.py` 的上上级目录正好就是 miniMaster2.0 根目录。
    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ToolService.bootstrap(workspace=workspace)


def create_skill_store(tool_service: ToolService) -> SkillStore:
    """构造目录化 skill package 存储。"""
    # skill library 放在当前 workspace 下，跟代码一同分发。
    root = os.path.join(tool_service.get_workspace_path(), "skills", "library")
    return SkillStore(root=root)


def read_user_query() -> str:
    """读取并校验用户输入。

    这里依然用最简单的终端输入，是因为 miniMaster 关注点在 harness，
    而不是交互界面本身。
    """
    # 先读原始输入，再把首尾空白去掉。
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
    """构造运行期状态容器。

    注意这里一次性创建了三套 WorkingMemory：
    - planner_memory: 记录规划阶段的侦察与反馈
    - generator_memory: 记录执行阶段的证据链
    - validation_memory: 记录验证阶段的检查过程

    这样不同角色不会共享一锅混杂上下文，而是各自维护面向本阶段的记忆视图。
    """
    return AgentRuntime(
        # 用户当前这次输入的问题，是整个运行的起点。
        user_query=user_query,
        # 模型名称会用于日志展示和真实调用。
        model_name=model_name,
        # 单次模型调用超时。
        llm_timeout_seconds=llm_timeout_seconds,
        # 已经创建好的 LLM client。
        client=client,
        # 统一的工具注册与执行入口。
        tool_service=tool_service,
        # Planner 后续会把任务草案写进这里。
        todo_list=ToDoList(),
        # Planner 记忆保留得稍多一点，因为它要靠少量侦察反复修订任务结构。
        planner_memory=WorkingMemory(keep_latest_n=6),
        # Executor 的执行轨迹记忆。
        generator_memory=WorkingMemory(),
        # Validator 的独立验证轨迹记忆。
        validation_memory=WorkingMemory(),
        # 当前 workspace 下可用的 skill 仓库。
        skill_store=create_skill_store(tool_service),
        # 用 monotonic 时钟做总预算统计，避免系统时间被用户改动影响。
        started_at_monotonic=time.monotonic(),
        # 记录每个任务的历史重试摘要。
        retry_archive_by_task={},
    )


def bootstrap_runtime() -> AgentRuntime:
    """完成入口阶段的环境初始化并返回 runtime。"""
    # `.env` 只是配置来源之一；真正参与后续运行的是已经读入内存的 runtime。
    load_dotenv()
    # 先拿到模型 client 和模型配置。
    client, model_name, llm_timeout_seconds = create_client_from_env()
    # 再读取本次用户输入。
    user_query = read_user_query()
    # 然后装配工具系统。
    tool_service = create_tool_service()
    # 最后把上面这些对象打包成统一 runtime。
    return build_runtime(
        user_query=user_query,
        model_name=model_name,
        llm_timeout_seconds=llm_timeout_seconds,
        client=client,
        tool_service=tool_service,
    )
