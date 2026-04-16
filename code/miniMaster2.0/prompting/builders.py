"""三层 Agent 循环所需的提示词构造函数。

这里把 Plan、Generator、Validate 以及记忆压缩摘要所需的 Prompt
分别封装成独立函数，目的是让主循环代码更清晰。主程序只需要准备
上下文数据，再调用这里的方法拼出最终提示词即可。
"""

from __future__ import annotations

import json


def build_workspace_block(workspace_path: str) -> str:
    """构造可注入 Prompt 的工作目录说明文本。

    工作目录不仅影响工具实际怎样解析相对路径，也会影响模型如何理解
    “当前目录”“这里”“本项目”这类自然语言。把它明确写进 Prompt 后，
    Agent 在处理文件定位任务时会更稳定，不容易把“当前目录”误解成别处。
    """
    normalized_workspace = (workspace_path or ".").strip()
    lines = [
        f"当前工作目录是：{normalized_workspace}",
        "当用户提到“当前目录”“这里”“本项目目录”时，默认指这个工作目录。",
        "未特别说明时，工具中的相对路径都会相对于这个工作目录解析。",
        "如果用户明确要求桌面、用户目录或其他位置，可以使用绝对路径、~/... 或环境变量路径。",
    ]
    return "\n".join(f"- {line}" for line in lines)


def build_runtime_environment_block(system_name: str, command_shell: str) -> str:
    """构造可注入 Prompt 的运行环境说明文本。

    运行环境本身属于“执行上下文”，不应该在 Prompt 模板里直接写死。
    因此这里单独提供一个构造函数，由主程序把当前系统与底层命令 shell
    传进来，再生成一段统一的说明文本，供多个 Prompt 复用。
    """
    normalized_system = (system_name or "Unknown").strip()
    normalized_shell = (command_shell or "shell").strip()

    lines = [
        f"当前运行环境是 {normalized_system}。",
        f"bash 工具当前通过 {normalized_shell} 执行命令。",
        "如果任务是列目录、找文件、搜文本，优先使用 glob / grep / read 这类专用工具，不要先默认使用 bash。",
    ]

    if normalized_system.lower() == "windows":
        lines.append(
            "如果确实要用 bash 查看目录，可使用 ls 或 Get-ChildItem；"
            "如果要包含隐藏项，请使用 Get-ChildItem -Force，不要使用 ls -a。"
        )
    else:
        lines.append(
            "如果确实要用 bash 查看目录，可使用 ls；"
            "如果要包含隐藏项，可使用 ls -a。"
        )

    return "\n".join(f"- {line}" for line in lines)


def build_execution_context_block(workspace_path: str, system_name: str, command_shell: str) -> str:
    """构造统一的执行上下文说明文本。

    Agent 在做文件定位和命令选择时，真正依赖的是一整套“执行现场信息”，
    而不是彼此分散的几段提示。这里把工作目录、系统类型和底层 shell
    合并成一个统一块，可以让 Prompt 结构更紧凑，也能减少主程序中
    分别拼接多段环境说明的重复代码。
    """
    workspace_block = build_workspace_block(workspace_path)
    runtime_block = build_runtime_environment_block(system_name, command_shell)
    return "\n".join([
        "【工作目录信息】",
        workspace_block,
        "",
        "【运行环境信息】",
        runtime_block,
    ])


def build_plan_prompt(
    user_query: str,
    tasks: list,
    policy_text: str,
) -> str:
    """构造 Plan-Agent 使用的提示词。

    这个提示词的重点不是让模型“直接做事”，而是让它先判断当前输入
    到底属于哪一类：是简单回复即可，还是需要进入任务规划与调度。
    这里还会把当前任务列表和允许的动作一并交给模型，帮助它在已有
    状态基础上做出下一步决策，而不是每轮都从零开始猜。
    """
    return f"""
你是一个规划智能体，你的任务是判断“现在最合适的下一步动作”。

<user_query>
{user_query}
</user_query>

<tasks>
{tasks}
</tasks>

<available_actions>
{policy_text}
</available_actions>

<user_facing_capabilities>
- 搜索文件和代码内容
- 读取文件内容
- 写入或编辑文件
- 执行命令
- 在完成后做基本验证
</user_facing_capabilities>

<instructions>
1. 先判断用户输入属于哪一类：
   - 简单问候、闲聊、咨询能力、询问工具：直接使用 respond_to_user。
   - 明确要求完成某个任务：优先使用 init_tasks / add_task 组织任务，再决定是否调用 subagent_tool。
2. 像“你好”“在吗”“你是谁”“你能做什么”“你有哪些工具可以使用？”这类输入，都是正常且完整的输入，不能误判成“消息截断”或“用户没发完”。
3. 只有当输入明显是残缺片段、乱码，或者语义确实无法判断时，才可以说明信息不足。不要把正常短句误判为异常输入。
4. 如果用户问“你有什么工具”“你能做什么”，要按照 <user_facing_capabilities> 从用户视角回答，不要复述 init_tasks、add_task、subagent_tool 这类内部调度动作。
5. 使用 respond_to_user 时，语气要自然、简洁、友好，像一个会帮忙的助教，不要生硬，不要先讲规则。
6. 对“你好”“在吗”“你是谁”“你能做什么”“你有哪些工具可以使用？”这类正常短句，回复里不要出现“消息被截断”“信息不完整”“请补充上下文”“你是不是还没发完”这类说法。
7. 只要用户在请求你“查看、列出、搜索、读取、创建、写入、修改、编辑、删除、运行、分析、检查”中的任意一种动作，就应视为任务请求，而不是闲聊。
8. 像“请查看当前目录都有什么文件”“帮我读一下 xxx.py”“在桌面创建一个 txt”这类句子，即使很短，也属于明确任务，不能使用 respond_to_user。
9. 如果用户提到“当前目录”“这里”“本项目目录”，默认按系统消息中给出的工作目录理解。
10. 如果 tasks 中已经存在语义相同或几乎相同的任务，不要重复调用 add_task 创建重复任务。
11. 如果当前 tasks 为空，且用户只是问候或提问，不要为了凑流程而强行创建任务。
12. 如果用户输入里有明确的编号步骤，优先按原顺序一一抽取任务；一个编号项通常对应一个 task。
13. 对编号清单里的任务名称，优先保留用户原句中的关键动作、对象、路径、文件名和约束，只做最小必要压缩，不要改写成泛化目标。
14. 禁止把具体交付改写成空泛分类。例如，用户要求“查看目录、搜索关键字、写报告、创建桌面文件、再次验证”，不能改成“代码质量检查、依赖检查、功能测试”。
15. 当 tasks 已经存在未完成任务时，优先围绕已有任务继续推进；如果要使用 subagent_tool，默认优先选择列表中第一个未完成任务。
16. 如果 tasks 中已经存在未完成任务，禁止再次调用 init_tasks 重新初始化整张任务表。此时只能在已有任务基础上选择 subagent_tool、update_task_status、add_task 或 respond_to_user。
17. 如果 tasks 非空，而你仍然重复调用 init_tasks，会被视为错误决策；你必须改为推进已有任务，而不是重复规划。
18. 不要手写 JSON、Markdown 或 XML；请直接调用一个最合适的函数。
19. 每一轮只调用一个函数。
</instructions>

<examples>
示例 1：用户输入“你好”时，应直接调用 `respond_to_user(message="你好！我是 miniMaster，可以帮你查找文件、读取内容、修改代码，也可以执行一些命令。你现在想让我做什么？")`，不要说“消息可能被截断”或“请补充上下文”。

示例 2：用户输入“你有哪些工具可以使用？”时，应调用 `respond_to_user(...)`，从用户视角介绍能力，不要暴露内部调度动作，也不要说“你的问题不完整”。

示例 3：用户输入“帮我看看 main_agent.py 里有没有重复代码”时，应调用 `init_tasks(tasks=["检查 main_agent.py 中是否存在重复代码"])`。

示例 4：用户输入“请查看当前目录都有什么文件”时，应调用 `init_tasks(tasks=["列出当前目录下的文件和文件夹"])`。

示例 5：用户输入“请帮我在桌面创建一个测试txt文档，内容是123456”时，应调用 `init_tasks(tasks=["在桌面创建测试.txt 并写入 123456"])`。

示例 6：如果用户给出明确编号清单，就应调用 `init_tasks(...)` 按原顺序保留这些任务，不要泛化改写。

示例 7：如果 tasks 已经不是空列表，例如已经有 ["查看目录", "搜索关键字", "写报告"] 这些未完成任务，此时禁止再次调用 `init_tasks(...)`；应该调用 `subagent_tool(task_name="查看目录")` 或推进其他现有任务。

示例 8：错误示范。对于“查看目录、搜索关键字、写报告、创建桌面文件、再次验证”这类清单，不能把任务改成“检查项目代码质量、验证项目依赖、测试关键功能”。

</examples>
""".strip()


def build_generator_prompt(
    user_query: str,
    current_task: dict,
    working_memory: str,
    base_tools: str,
    search_tools: str,
    policy_text: str,
) -> str:
    """构造 Generator-Agent 使用的提示词。

    Generator-Agent 是真正执行任务的一层，所以提示词里除了用户原始
    问题外，还要给它当前子任务、工作记忆、可用工具和动作约束。
    这样模型就能结合最近做过的事继续推进，减少重复搜索、重复读取、
    或者走回头路的情况。
    """
    return f"""
你是一个执行智能体，你的任务是执行具体任务并生成内容。

<user_query>
{user_query}
</user_query>

<current_task>
{current_task}
</current_task>

<working_memory>
{working_memory}
</working_memory>

<available_tools>
【基础工具】
{base_tools}

【搜索工具】
{search_tools}
</available_tools>

<available_actions>
{policy_text}
</available_actions>

<instructions>
1. <user_query> 仅提供全局背景，你当前真正要完成的是 <current_task>。
2. 禁止因为 <user_query> 里还包含后续步骤，就提前去写报告、创建文件、做最终验证，或执行其他尚未轮到的任务。
3. 如果某条信息只对后续任务有用，但不是完成当前 task 的必要条件，就不要现在处理。
4. 每一步执行前都要参考 <working_memory>，避免重复尝试无效路径。
5. 当用户提到“当前目录”“这里”“本项目目录”时，默认按系统消息中给出的工作目录理解。
6. 未特别说明时，优先使用相对于工作目录的相对路径；只有目标明确在工作目录外时，再使用绝对路径或 `~/...` 路径。
7. 优先使用最贴合任务的专用工具逐步推进，不要跳步。例如：找文件优先 glob，搜文本优先 grep，读内容优先 read。
8. 必须认真区分工具成功和失败。如果某一步 `success=False`，不能把这一步描述成已经成功完成。
9. 如果任务目标最终已经满足，但过程并不是“新建成功”“删除成功”“修改成功”，结论就要如实表述为“已确认存在”“已确认内容正确”“已完成覆盖写入”等，不要夸大。
10. 当某一步工具已经给出了足够明确的证据时，可以直接整理结论，不要为了“多做一步”重复执行无意义操作。
11. 任务完成后，使用 update_task_conclusion 提交最终结论。
12. 不要手写 JSON、Markdown 或 XML；请直接调用一个最合适的函数。
13. 每一轮只调用一个函数。
14. 如果 <working_memory> 中最近一条 system_feedback 来自验证失败，你下一步必须直接回应这条失败原因，不能忽略它去重复之前的动作。
15. 回应验证失败只有两种有效方式：补充新的、能够覆盖缺失条件的证据；或者修改结论，让结论和现有证据严格一致。
16. 如果你的下一步既没有补到新的有效证据，也没有实质性修正结论，就属于无效动作。
17. 所谓“实质性修正结论”，是指修正事实表述，例如把“已创建”改成“已确认存在”、把“已验证完成”改成“已完成写入但仍缺少某项校验”。
18. 如果验证失败原因指出“缺少某项验证”或“结论与证据不一致”，你必须优先解决这个具体问题，不要重复读取、重复搜索，或再次提交同一份结论。
19. 如果现有证据已经足够支持当前任务完成，应直接调用 update_task_conclusion 给出准确结论，而不是继续调用不会产生新信息的工具。
</instructions>

<function_call_example>
例如，需要先定位目标文件再读取内容时，应直接调用
`grep(pattern="execute_runtime_tool", path=".", recursive=true)`。

如果上一条 system_feedback 指出“缺少文件非空验证”，那么下一步应优先调用
`read(file_path="目标文件")` 之类能够补足该条件的工具，而不是再次提交相同的
`update_task_conclusion(...)`。
</function_call_example>
""".strip()


def build_validate_prompt(
    task: dict,
    task_history: str,
    working_memory: list,
    base_tools: str,
    search_tools: str,
    policy_text: str,
) -> str:
    """构造 Validate-Agent 使用的提示词。

    Validate-Agent 的职责不是继续完成任务，而是独立检查任务结果是否
    真的满足要求。因此这里重点提供“当前任务结果”和“验证阶段的记忆”，
    并限制它最终必须通过 `validate_tool` 给出明确结论，保证验证环节
    能形成稳定闭环。
    """
    return f"""
你是一个测试验证智能体，你的任务是验证当前 task 的完成是否有效。

<task>
{task}
</task>

<task_history>
{task_history}
</task_history>

<working_memory>
{working_memory}
</working_memory>

<available_tools>
【基础工具】
{base_tools}

【搜索工具】
{search_tools}
</available_tools>

<available_actions>
{policy_text}
</available_actions>

<instructions>
1. 先阅读 <task_history>，确认 Generator 实际执行了哪些步骤，哪些成功，哪些失败。
2. 如果需要，再使用工具验证任务结果。
3. 当任务涉及“当前目录”“这里”“本项目目录”时，默认按系统消息中给出的工作目录理解。
4. 优先使用和任务最匹配的验证工具，不要因为 bash 失败就忽略其他已经足够可靠的验证方式。
5. 当某个工具已经能直接验证任务要求时，不必强行换另一种工具重复验证。
6. 你不仅要检查“最终状态是否满足任务”，还要检查 <task> 中的结论表述是否和 <task_history> 一致。
7. 如果最终状态满足要求，但结论把“已存在”说成“已创建”、把失败写成成功、把未验证内容写成已验证，也必须判定为 `无效`，要求 Generator 改写成更准确的结论。
8. 如果还有关键条件没有核实完，就继续调用工具，不要提前输出 `validate_tool`。
9. 只有当全部要求都已验证完成时，才能把状态标记为 `有效`。如果 reason 里还写着“需要进一步检查”“下一步验证”，说明当前还不能判定为 `有效`。
10. 你每次决定是否继续调用工具前，都必须先判断：当前是否还存在“尚未被现有证据覆盖的验证条件”。
11. 如果现有证据已经足以覆盖全部验证条件，必须立即调用 validate_tool 收口，禁止为了谨慎继续重复验证已经成立的事实。
12. 只有当下一次工具调用能够补充新的验证条件、带来新的信息时，才允许继续调用工具；如果不会产生新信息，就不应继续调用。
13. 如果 <working_memory> 中已经有成功的验证结果，并且该结果已经直接证明某项条件成立，那么这项条件视为已验证，不得重复验证。
14. 当你继续调用工具时，必须明确自己要补的是“此前尚未验证的条件”，而不是重复确认已经成立的事实。
15. 如果 <working_memory> 已经出现相同工具、相同参数、相同目标的重复验证，不要继续机械重复；应直接基于现有证据调用 validate_tool，或明确指出仍缺少哪一项条件。
16. 常见可以直接收口的情况包括但不限于：bash 执行 Test-Path 且结果为 True，说明路径存在；read 成功读取目标文件且内容非空，说明文件存在且非空；glob 成功找到目标文件或目录，说明目标存在。
17. 如果你判定为 `无效`，reason 必须明确指出“缺少哪一项条件”或“结论与哪条证据不一致”；不要只写笼统的“需要进一步验证”。
18. 如果你判定为 `有效`，reason 必须明确说明哪些条件已经被哪些现有证据覆盖。
19. 最终必须通过 validate_tool 提交验证结论。
20. 不要手写 JSON、Markdown 或 XML；请直接调用一个最合适的函数。
21. 每一轮只调用一个函数。
</instructions>

<function_call_example>
当你已经确认结果符合要求时，应直接调用
`validate_tool(status="有效", reason="目标内容存在，且结果与任务要求一致")`。

如果你已经执行过 `bash(command="Test-Path ...")` 且结果为 True，下一步应直接调用
`validate_tool(...)`，不要再次执行同一个 Test-Path。

如果你已经执行过 `read(file_path="agent_test_report.md")` 且 success=True、content 非空，
下一步也应直接调用 `validate_tool(...)`，不要再次读取同一文件。
</function_call_example>
""".strip()


def build_summary_prompt(summary: str, pending_memories: list) -> str:
    """构造旧记忆压缩时使用的提示词。

    当执行轨迹越来越长时，直接把全部历史都塞给模型会让上下文膨胀。
    这个方法负责把已有摘要和即将滑出窗口的旧记录一起交给模型，请它
    提炼成更短的文字摘要，从而为长期任务保留关键信息，同时控制上下文
    长度不失控。
    """
    return f"""
你是一个记忆压缩助手。请将以下早期工具执行记录压缩成一段简短摘要。

<existing_summary>
{summary}
</existing_summary>

<pending_memories>
{json.dumps(pending_memories, ensure_ascii=False)}
</pending_memories>

<instructions>
1. 保留关键信息：尝试了哪些工具、完成了哪些事情、出现了什么重要失败。
2. 省略重复输出和无关细节。
3. 输出纯文本摘要，不要输出 JSON。
</instructions>
""".strip()
