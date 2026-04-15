import os
import json
import re
from dotenv import load_dotenv
from openai import OpenAI
from langsmith import traceable
from langsmith.wrappers import wrap_openai

# 导入工具注册表
from utils.get_tools import get_registry, execute_tool as execute_registered_tool


class ToDoList:
    """待办事项列表管理类。

    Plan-Agent 只通过这里维护任务状态，避免把任务调度信息散落在主循环中。
    """

    def __init__(self):
        self.tasks = []

    def add_task(self, task_name: str, task_status: str = "PENDING", task_conclusion: str = ""):
        self.tasks.append({
            "task_name": task_name,
            "task_status": task_status,
            "task_conclusion": task_conclusion
        })

    def init_tasks(self, task_list: list):
        for item in task_list:
            if isinstance(item, str):
                self.add_task(item)
            elif isinstance(item, dict):
                self.add_task(item.get("task_name", ""), item.get("task_status", "PENDING"),
                              item.get("task_conclusion", ""))

    def update_task_status(self, task_name: str, new_status: str) -> bool:
        for task in self.tasks:
            if task["task_name"] == task_name:
                task["task_status"] = new_status
                return True
        return False

    def update_task_conclusion(self, task_name: str, conclusion: str) -> bool:
        for task in self.tasks:
            if task["task_name"] == task_name:
                task["task_conclusion"] = conclusion
                return True
        return False

    def get_all_tasks(self):
        return self.tasks.copy()

    def get_task_by_name(self, task_name: str):
        for task in self.tasks:
            if task["task_name"] == task_name:
                return task
        return None

class WorkingMemory:
    """工作记忆管理类。

    这里不追求严格的 token 计算，而是用字符数做近似控制，在成本和效果之间取平衡。
    """

    def __init__(self, keep_latest_n: int = 3, max_chars: int = 45000):
        self.memories = []
        # 触发压缩时，保留最后几个步骤的完整 JSON 不被压缩（保持当前工作的连贯性）
        self.keep_latest_n = keep_latest_n
        # 触发阈值：20k token 大约等于 40000~50000 个字符
        self.max_chars = max_chars
        self.summary = ""

    def add_memory(self, step: int, tool_name: str, parameters: dict, result: any):
        """添加新记忆（不限制单个结果长度，只管全局长度）"""
        self.memories.append({
            "step": step,
            "tool_call": {"tool_name": tool_name, "parameters": parameters},
            "result": result
        })

    def get_prompt_context(self) -> str:
        """组装给 Agent 看的完整上下文"""
        context = ""
        if self.summary:
            context += f"【早期步骤摘要】:\n{self.summary}\n\n"

        # 只要没超限，Agent 就能看到所有步骤的完整内容
        context += "【执行步骤】:\n" + json.dumps(self.memories, ensure_ascii=False, indent=2)
        return context

    def get_all_memories(self):
        """兼容其他组件调用"""
        return self.memories.copy()

    def check_needs_summary(self) -> bool:
        """核心策略：判断当前上下文是否超过了 20k Token (即 max_chars)"""
        current_length = len(self.get_prompt_context())
        # 只有长度超标，且记忆数量大于我们要保留的底线时，才触发压缩
        return current_length > self.max_chars and len(self.memories) > self.keep_latest_n

    def get_memories_to_summarize(self) -> list:
        """获取需要被压缩的庞大旧记忆"""
        if self.check_needs_summary():
            # 取出除了最后 keep_latest_n 步之外的所有早期记忆，打包送去压缩
            return self.memories[:-self.keep_latest_n]
        return []

    def commit_summary(self, new_summary: str):
        """用大模型返回的摘要覆盖旧摘要，并清理掉已被压缩的冗长数据"""
        self.summary = new_summary
        # 只保留最后 keep_latest_n 步的详细记忆，腾出大量空间
        self.memories = self.memories[-self.keep_latest_n:]

    def clear_memories(self):
        self.memories = []
        self.summary = ""
# ==========================================
# 辅助函数
# ==========================================
def parse_model_output(response_text: str):
    """
    解析模型输出的 <think>, <tool>, <parameter> 标签
    返回: tool_name, parameters_dict
    """
    # 提取 <think> 标签内容（可选，用于调试）
    think_match = re.search(r'<think>(.*?)</think>', response_text, re.DOTALL)
    think_content = think_match.group(1).strip() if think_match else ""

    # 提取 <tool> 标签内容
    tool_match = re.search(r'<tool>(.*?)</tool>', response_text, re.DOTALL)
    tool_name = tool_match.group(1).strip() if tool_match else ""

    # 提取 <parameter> 标签内容
    param_match = re.search(r'<parameter>(.*?)</parameter>', response_text, re.DOTALL)
    param_content = param_match.group(1).strip() if param_match else ""

    # 解析参数为 dict
    parameters = {}
    if param_content:
        try:
            parameters = json.loads(param_content)
        except json.JSONDecodeError:
            # 如果不是合法 JSON，作为字符串处理
            parameters = {"raw": param_content}

    return tool_name, parameters


# 初始化工具注册表（全局单例）
tool_registry = get_registry()

# 这些名称虽然长得像 tool，但本质上属于主循环内部控制指令，
# 不应该落到统一的工具执行链里，否则会把调度逻辑和真实工具混在一起。
CONTROL_ACTIONS = {
    "init_tasks",
    "add_task",
    "update_task_status",
    "subagent_tool",
    "update_task_conclusion",
    "validate_tool",
}


def is_control_action(tool_name: str) -> bool:
    """判断当前名称是否属于由主循环直接处理的控制指令。"""
    return tool_name in CONTROL_ACTIONS


def execute_runtime_tool(tool_name: str, parameters: dict):
    """
    执行真正的可执行工具。
    控制指令必须在对应循环中直接处理，不应进入通用工具执行链。
    """
    if is_control_action(tool_name):
        return {"success": False, "error": f"控制指令 '{tool_name}' 不应通过工具执行链调用"}

    # 所有真实工具都统一交给注册表执行，便于后续继续替换底层实现而不改主循环。
    return execute_registered_tool(tool_name, parameters)


def get_available_tool_prompts():
    """获取执行阶段和验证阶段共用的工具描述。"""
    # 这里继续沿用旧分类名，是为了兼容 ToolPromptRenderer 里的别名转换逻辑。
    base_tools = tool_registry.get_all_tools_prompt(category="base_tool")
    search_tools = tool_registry.get_all_tools_prompt(category="search_tool")
    return base_tools, search_tools


# ==========================================
# Agent LLM 调用封装 (用于 LangSmith 追踪)
# ==========================================
@traceable(name="1_Plan-Agent_Brain")
def call_plan_agent(prompt: str, model_name: str, client: OpenAI) -> str:
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


@traceable(name="2_Generator-Agent_Execution")
def call_generator_agent(prompt: str, model_name: str, client: OpenAI) -> str:
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


@traceable(name="3_Validate-Agent_Review")
def call_validate_agent(prompt: str, model_name: str, client: OpenAI) -> str:
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


# ==========================================
# 主体逻辑
# ==========================================
if __name__ == "__main__":
    load_dotenv()

    # 从环境变量读取配置（与 .env 文件保持一致）
    API_KEY = os.environ.get("API_KEY")
    BASE_URL = os.environ.get("BASE_URL")
    MODEL_NAME = os.environ.get("MODEL_NAME", "deepseek-chat")

    # 检查必需的环境变量
    if not API_KEY:
        print("错误: 未设置 API_KEY 环境变量")
        print("请在 .env 文件中设置: API_KEY=your_api_key_here")
        exit(1)

    if not BASE_URL:
        print("错误: 未设置 BASE_URL 环境变量")
        print("请在 .env 文件中设置: BASE_URL=https://api.example.com")
        exit(1)

    client = wrap_openai(OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL,
    ))

    # 获取用户输入的查询
    user_query = input("请输入你的任务/查询: ").strip()
    if not user_query:
        print("查询不能为空，退出程序。")
        exit(1)

    to_do_list = ToDoList()
    generator_memory = WorkingMemory()
    validation_memory = WorkingMemory()
    max_iter = 30

    # 🟢 第一层循环：Plan-Agent (任务规划与调度)
    for i in range(max_iter):
        print(f"\n{'=' * 60}")
        print(f"🔄 Plan-Agent 第 {i + 1} 次迭代")
        print(f"{'=' * 60}")

        # 1. 组装 Plan-Agent Prompt
        plan_prompt = f"""
你是一个规划智能体，你的任务是根据用户的 需求 维护和调度当前工作状态。

<user query>
{user_query}
</user query>

<tasks>
{to_do_list.get_all_tasks()}
</tasks>

<available tools>
- init_tasks: 初始化任务列表
  Input schema: {{"type": "object", "properties": {{"tasks": {{"type": "array", "items": {{"type": "string"}}}}}}, "required": ["tasks"]}}

- add_task: 添加单个任务，当任务全部完成还无法满足用户需求时，增加任务
  Input schema: {{"type": "object", "properties": {{"task_name": {{"type": "string"}}}}, "required": ["task_name"]}}

- update_task_status: 更新任务状态，若任务经过了验证，则设置任务状态为done
  Input schema: {{"type": "object", "properties": {{"task_name": {{"type": "string"}}, "status": {{"type": "string", "enum": ["PENDING", "DONE", "FAILED"]}}}}, "required": ["task_name", "status"]}}

- subagent_tool: 你不需要主动完成具体任务，而是将任务交给子agent执行
  Input schema: {{"type": "object", "properties": {{"task_name": {{"type": "string", "description": "要执行的任务名称"}}}}, "required": ["task_name"]}}
</available tools>

<attention>
利用你所拥有的tool，完成用户的需求
你的能力有限，无法完全完成特别复杂的任务，比如部署服务器、创建数据库等等
你只是一个助手，不要把问题复杂化，简洁明了的完成用户的需求即可
不需要做测试
</attention>

<output format>
    <think>你的思考内容：分析当前状态，选择合适工具</think>
    <tool>你要使用的工具名称</tool>
    <parameter>{{"参数名": "参数值"}}  </parameter>
</output format>
"""

        # 修改为调用带有 traceable 的函数
        plan_content = call_plan_agent(plan_prompt, MODEL_NAME, client)
        plan_tool, plan_params = parse_model_output(plan_content)

        print(f"📋 Plan-Agent 选择工具: {plan_tool}")
        print(f"📋 Plan-Agent 参数: {plan_params}")

        # 2. Plan-Agent 工具路由
        if plan_tool == "init_tasks":
            # 初始化任务列表
            task_list = plan_params.get("tasks", [])
            to_do_list.init_tasks(task_list)
            print(f"✅ 已初始化任务列表: {task_list}")
            continue

        elif plan_tool == "add_task":
            # 添加单个任务
            task_name = plan_params.get("task_name", "")
            if task_name:
                to_do_list.add_task(task_name)
                print(f"✅ 已添加任务: {task_name}")
            continue

        elif plan_tool == "update_task_status":
            # 更新任务状态
            task_name = plan_params.get("task_name", "")
            new_status = plan_params.get("status", "PENDING")
            if task_name:
                to_do_list.update_task_status(task_name, new_status)
                print(f"✅ 已更新任务 '{task_name}' 状态为: {new_status}")
            continue

        elif plan_tool == "subagent_tool":
            curr_task_name = plan_params.get("task_name")
            curr_task = to_do_list.get_task_by_name(curr_task_name)

            if not curr_task:
                print(f"⚠️  未找到任务: {curr_task_name}")
                continue

            print(f"\n🚀 开始执行任务: {curr_task_name}")
            print(f"📝 任务详情: {curr_task}")

            # 🟡 第二层循环：Generator (任务执行与生成)
            generator_memory = WorkingMemory(keep_latest_n=8, max_chars=80000)
            gen_step = 0
            max_gen_iter = 20  # Generator 单任务最大迭代次数，防止验证失败时无限重试

            while True:
                gen_step += 1
                print(f"\n  🔧 Generator 第 {gen_step} 步")

                if gen_step > max_gen_iter:
                    print(f"  ⚠️  Generator 达到最大迭代次数 {max_gen_iter}，强制结束当前任务")
                    to_do_list.update_task_status(curr_task_name, "DONE")
                    break  # 结束第二层循环，回到第一层循环 (Plan-Agent)

                if generator_memory.check_needs_summary():
                    pending_memories = generator_memory.get_memories_to_summarize()
                    print(f"  🧠 检测到记忆滑出窗口，正在进行批量压缩...")

                    # 早期工具记录会持续累积，这里把“旧摘要 + 新滑出窗口内容”合并成更短摘要，
                    # 让 Generator 在长任务下仍能保留关键轨迹而不至于 Prompt 爆炸。
                    summary_prompt = f"""你是一个记忆压缩助手。请将以下早期的工具执行记录压缩成一段简短的摘要。
                保留关键信息：尝试了什么工具、完成了什么任务，结论是什么。

                现有的早期摘要：{generator_memory.summary}

                需要合并的新记录：
                {json.dumps(pending_memories, ensure_ascii=False)}
                """
                    new_summary = call_generator_agent(summary_prompt, MODEL_NAME, client)
                    generator_memory.commit_summary(new_summary)
                    print(f"  ✅ 记忆压缩完成。")

                # 获取工具描述（动态生成）
                base_tools, search_tools = get_available_tool_prompts()

                generator_prompt = f"""
你是一个执行智能体，你的任务是执行具体任务并生成内容。

<user query>
{user_query}
</user query>

<current task>
{curr_task}
</current task>

<working memory>
{generator_memory.get_prompt_context()}
</working memory>

<available tools>
【基础工具】
{base_tools}

【搜索工具】
{search_tools}

【任务管理】
- update_task_conclusion: 任务完成时调用，传入参数为任务完成的结论
  Input schema: {{"type": "object", "properties": {{"conclusion": {{"type": "string"}}}}, "required": ["conclusion"]}}
</available tools>

<instructions>
1.<user query>仅供你参考全局信息，你的任务是完成<current task>
2.每一步执行，你都需要关注<working memory>，你曾经做了什么，再决定下一步做什么
3.你只是一个助手，不要做太复杂的任务，不要把问题复杂化
</instructions>

<output format>
    <think>你的思考内容：分析任务，选择合适的工具，解释为什么</think>
    <tool>你要使用的工具名称（从 available tools 中选择）</tool>
    <parameter>{{"参数名": "参数值"}}  </parameter>
</output format>
"""

                # 修改为调用带有 traceable 的函数
                gen_content = call_generator_agent(generator_prompt, MODEL_NAME, client)
                gen_tool, gen_params = parse_model_output(gen_content)

                print(f"  🛠️  Generator 选择工具: {gen_tool}")
                print(f"  🛠️  参数: {gen_params}")

                if gen_tool != "update_task_conclusion":
                    # 执行普通工具并记录到 Generator 记忆
                    result = execute_runtime_tool(gen_tool, gen_params)
                    generator_memory.add_memory(gen_step, gen_tool, gen_params, result)
                    print(f"  ✅ 工具执行结果: {result}")
                    continue  # 继续第二层循环，Generator 继续工作

                else:
                    # Generator 认为完成了，更新结论
                    conclusion = gen_params.get("conclusion", "")
                    to_do_list.update_task_conclusion(curr_task_name, conclusion)
                    print(f"  📝 Generator 完成任务，结论: {conclusion}")

                    # 🔴 第三层循环：Validate-Agent (结果测试与验证)
                    # 这里重新开启一套独立的验证记忆，避免执行阶段的长上下文污染验证判断。
                    validation_memory.clear_memories()
                    val_step = 0
                    is_valid = False

                    while True:
                        val_step += 1
                        print(f"\n    🔍 Validate-Agent 第 {val_step} 步")
                        # 注意：需要重新获取 task，因为结论刚刚更新了
                        updated_task = to_do_list.get_task_by_name(curr_task_name)

                        # 获取工具描述
                        base_tools, search_tools = get_available_tool_prompts()

                        val_prompt = f"""你是一个测试验证智能体，你的任务是验证当前task的完成是否有效。

<task>
{updated_task}
</task>

<working memory>
{validation_memory.get_all_memories()}
</working memory>

<available tools>
【基础工具】
{base_tools}

【搜索工具】
{search_tools}

【验证工具】
- validate_tool: 验证任务完成是否有效
  Input schema: {{"type": "object", "properties": {{"status": {{"type": "string", "enum": ["有效", "无效"]}}, "reason": {{"type": "string"}}}}, "required": ["status"]}}
</available tools>

<instructions>
1.使用工具验证当前任务是否有效完成
2.调用 validate_tool 给出验证结果
</instructions>

<output format>
    <think>你的思考内容</think>
    <tool>你要使用的工具名称</tool>
    <parameter>{{"参数名": "参数值"}}</parameter>
</output format>
"""

                        # 修改为调用带有 traceable 的函数
                        val_content = call_validate_agent(val_prompt, MODEL_NAME, client)
                        val_tool, val_params = parse_model_output(val_content)

                        print(f"    🛠️  Validate-Agent 选择工具: {val_tool}")
                        print(f"    🛠️  参数: {val_params}")

                        if val_tool != "validate_tool":
                            # 执行验证辅助工具（如搜索、基础测试等）
                            val_result = execute_runtime_tool(val_tool, val_params)
                            validation_memory.add_memory(val_step, val_tool, val_params, val_result)
                            print(f"    ✅ 验证工具执行结果: {val_result}")
                            continue  # 继续第三层循环，直到得出最终验证结果

                        else:
                            # 验证器得出最终结论
                            status = val_params.get("status")  # 假设参数为 "有效" 或 "无效"
                            reason = val_params.get("reason", "未知错误")
                            print(f"    📊 验证结果: {status}, 原因: {reason}")

                            if status == "有效":
                                is_valid = True
                                print(f"    ✅ 验证通过！")
                                break  # 结束第三层循环
                            else:
                                # 验证失败：将错误原因写入 Generator 的记忆中，让其重试
                                generator_memory.add_memory(
                                    gen_step + 1,
                                    "system_feedback",
                                    {},
                                    f"验证失败，请重新调整。原因: {reason}"
                                )
                                is_valid = False
                                print(f"    ❌ 验证失败，将返回 Generator 重试")
                                break  # 结束第三层循环，回到第二层循环 (Generator)

                    # 🔴 第三层循环结束后的处理
                    if is_valid:
                        # 验证通过，更新任务状态为完成，清空记忆
                        to_do_list.update_task_status(curr_task_name, "DONE")
                        generator_memory.clear_memories()
                        validation_memory.clear_memories()
                        print(f"\n✅ 任务 '{curr_task_name}' 已完成并通过验证！")
                        break  # 结束第二层循环，回到第一层循环 (Plan-Agent)
                    else:
                        # 验证未通过，继续第二层循环 (Generator 继续基于新的 feedback 工作)
                        print(f"\n⚠️  任务 '{curr_task_name}' 验证未通过，Generator 将继续重试...")
                        continue

        else:
            # 未知工具，跳过
            continue

        # 检查是否所有任务都已完成
        all_tasks = to_do_list.get_all_tasks()
        if all_tasks and all(task["task_status"] == "DONE" for task in all_tasks):
            print("\n=== 所有任务已完成 ===")
            for task in all_tasks:
                print(f"任务: {task['task_name']}")
                print(f"结论: {task['task_conclusion']}")
            break

    print("\n程序结束。")
