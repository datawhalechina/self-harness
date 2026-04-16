from copy import deepcopy

from app.agent_config import (
    GENERATOR_POLICY,
    GENERATOR_POLICY_TEXT,
    PLAN_POLICY,
    PLAN_POLICY_TEXT,
    VALIDATE_POLICY,
    VALIDATE_POLICY_TEXT,
    build_stage_context,
)
from app.loop_control import (
    CACHEABLE_RUNTIME_TOOLS,
    CACHE_INVALIDATING_RUNTIME_TOOLS,
    ConsecutiveActionGuard,
    build_repeated_action_feedback,
    build_tool_call_signature,
)
from app.agent_runner import call_agent_model, request_agent_action
from app.agent_types import AgentAction, AgentRuntime, Task
from runtime import DEFAULT_WORKING_MEMORY_MAX_CHARS, WorkingMemory

from prompting import (
    build_generator_prompt,
    build_plan_prompt,
    build_summary_prompt,
    build_validate_prompt,
)

CONTROL_ACTIONS = {
    "init_tasks",
    "add_task",
    "update_task_status",
    "subagent_tool",
    "respond_to_user",
    "update_task_conclusion",
    "validate_tool",
}


def is_control_action(tool_name: str) -> bool:
    """判断一个名字是否属于主循环内部处理的控制指令。"""
    return tool_name in CONTROL_ACTIONS


def execute_runtime_tool(runtime: AgentRuntime, tool_name: str, parameters: dict):
    """执行真正的运行时工具。"""
    if is_control_action(tool_name):
        return {"success": False, "error": f"控制指令 '{tool_name}' 不应通过工具执行链调用"}

    cache_key = build_tool_call_signature(tool_name, parameters)
    if tool_name in CACHEABLE_RUNTIME_TOOLS and cache_key in runtime.tool_result_cache:
        cached_result = deepcopy(runtime.tool_result_cache[cache_key])
        if isinstance(cached_result, dict):
            cached_result["_cache_hit"] = True
        return cached_result

    result = runtime.tool_service.execute(tool_name, parameters)

    if tool_name in CACHE_INVALIDATING_RUNTIME_TOOLS:
        runtime.tool_result_cache.clear()
    elif tool_name in CACHEABLE_RUNTIME_TOOLS:
        runtime.tool_result_cache[cache_key] = deepcopy(result)

    return result


def reset_generator_memory(runtime: AgentRuntime):
    """为当前任务重新初始化一份执行记忆。"""
    runtime.generator_memory = WorkingMemory(
        keep_latest_n=6,
        max_chars=DEFAULT_WORKING_MEMORY_MAX_CHARS,
    )


def reset_validation_memory(runtime: AgentRuntime):
    """为当前任务重新初始化一份验证记忆。"""
    runtime.validation_memory = WorkingMemory()


def run_plan_step(runtime: AgentRuntime, iteration: int, stage_context: dict) -> AgentAction:
    """执行一次 Plan-Agent 决策。"""
    print(f"\n{'=' * 60}")
    print(f"🔄 Plan-Agent 第 {iteration + 1} 次迭代")
    print(f"{'=' * 60}")

    plan_prompt = build_plan_prompt(
        user_query=runtime.user_query,
        tasks=runtime.todo_list.get_all_tasks_payload(),
        policy_text=PLAN_POLICY_TEXT,
    )
    plan_action = request_agent_action(
        prompt=plan_prompt,
        system_prompt=stage_context["shared_system_prompt"],
        policy=PLAN_POLICY,
        tools=stage_context["plan_openai_tools"],
        agent_name="Plan-Agent",
        model_name=runtime.model_name,
        client=runtime.client,
    )
    print(f"📋 Plan-Agent 选择工具: {plan_action.tool}")
    print(f"📋 Plan-Agent 参数: {plan_action.parameters}")
    return plan_action


def maybe_summarize_generator_memory(runtime: AgentRuntime):
    """在执行阶段需要时压缩旧记忆。"""
    if not runtime.generator_memory.check_needs_summary():
        return

    pending_memories = runtime.generator_memory.get_memories_to_summarize()
    print("  🧠 检测到记忆滑出窗口，正在进行批量压缩...")
    summary_prompt = build_summary_prompt(
        summary=runtime.generator_memory.summary,
        pending_memories=pending_memories,
    )
    new_summary = call_agent_model(
        prompt=summary_prompt,
        model_name=runtime.model_name,
        client=runtime.client,
        agent_name="Summary-Agent",
    )
    runtime.generator_memory.commit_summary(new_summary)
    print("  ✅ 记忆压缩完成。")


def run_generator_step(runtime: AgentRuntime, task: Task, step: int, stage_context: dict) -> AgentAction:
    """执行一次 Generator-Agent 决策。"""
    print(f"\n  🔧 Generator 第 {step} 步")
    maybe_summarize_generator_memory(runtime)

    generator_prompt = build_generator_prompt(
        user_query=runtime.user_query,
        current_task=runtime.todo_list.to_payload(task),
        working_memory=runtime.generator_memory.get_prompt_context(),
        base_tools=stage_context["base_tool_prompts"],
        search_tools=stage_context["search_tool_prompts"],
        policy_text=GENERATOR_POLICY_TEXT,
    )
    action = request_agent_action(
        prompt=generator_prompt,
        system_prompt=stage_context["shared_system_prompt"],
        policy=GENERATOR_POLICY,
        tools=stage_context["generator_openai_tools"],
        agent_name="Generator-Agent",
        model_name=runtime.model_name,
        client=runtime.client,
    )
    print(f"  🛠️  Generator 选择工具: {action.tool}")
    print(f"  🛠️  参数: {action.parameters}")
    return action


def run_validate_loop(runtime: AgentRuntime, task_name: str, generator_step: int, stage_context: dict) -> bool:
    """循环执行 Validate-Agent，直到给出最终验证结论。"""
    reset_validation_memory(runtime)
    validation_step = 0
    validate_action_guard = ConsecutiveActionGuard()

    while True:
        validation_step += 1
        print(f"\n    🔍 Validate-Agent 第 {validation_step} 步")
        task = runtime.todo_list.get_task_by_name(task_name)

        val_prompt = build_validate_prompt(
            task=runtime.todo_list.to_payload(task),
            task_history=runtime.generator_memory.get_prompt_context(),
            working_memory=runtime.validation_memory.get_all_memories_payload(),
            base_tools=stage_context["base_tool_prompts"],
            search_tools=stage_context["search_tool_prompts"],
            policy_text=VALIDATE_POLICY_TEXT,
        )
        action = request_agent_action(
            prompt=val_prompt,
            system_prompt=stage_context["shared_system_prompt"],
            policy=VALIDATE_POLICY,
            tools=stage_context["validate_openai_tools"],
            agent_name="Validate-Agent",
            model_name=runtime.model_name,
            client=runtime.client,
        )
        print(f"    🛠️  Validate-Agent 选择工具: {action.tool}")
        print(f"    🛠️  参数: {action.parameters}")

        if action.tool != "validate_tool" and validate_action_guard.is_repeated(action):
            reason = build_repeated_action_feedback(
                "Validate-Agent",
                action,
                "请不要继续重复验证；应基于现有证据直接给出 validate_tool 结论，"
                "或要求 Generator 提供更可验证的结果。",
            )
            generator_feedback = (
                "验证阶段未能收口。\n"
                f"具体问题：{reason}\n"
                "请先判断现有证据是否已经覆盖了全部验证条件。\n"
                "如果已经覆盖，请直接整理并修正任务结论，使结论与现有证据一致。\n"
                "如果仍有缺口，请明确还缺少哪一项条件，并补充能够覆盖该条件的新证据。\n"
                "下一步必须直接回应这个缺口，不要重复不会产生新信息的动作。"
            )
            runtime.generator_memory.add_memory(
                generator_step + 1,
                "system_feedback",
                {},
                generator_feedback,
            )
            print(f"    ❌ {reason}")
            return False

        if action.tool != "validate_tool":
            validate_action_guard.remember(action)

        if action.tool != "validate_tool":
            result = execute_runtime_tool(runtime, action.tool, action.parameters)
            runtime.validation_memory.add_memory(validation_step, action.tool, action.parameters, result)
            print(f"    ✅ 验证工具执行结果: {result}")
            continue

        status = action.parameters.get("status")
        reason = action.parameters.get("reason", "未知错误")
        print(f"    📊 验证结果: {status}, 原因: {reason}")

        if status == "有效":
            print("    ✅ 验证通过！")
            return True

        runtime.generator_memory.add_memory(
            generator_step + 1,
            "system_feedback",
            {},
            (
                "验证失败，需要针对下面的具体问题调整。\n"
                f"失败原因：{reason}\n"
                "请先判断这是“缺少验证条件”还是“结论表述与现有证据不一致”。\n"
                "如果是缺少验证条件，请补充新的证据来覆盖该条件。\n"
                "如果是结论表述不一致，请直接改写结论，使结论与现有证据严格一致。\n"
                "下一步必须直接回应这条失败原因，不要重复之前已经做过且没有产生新信息的动作。"
            ),
        )
        print("    ❌ 验证失败，将返回 Generator 重试")
        return False


def run_task(runtime: AgentRuntime, task_name: str, stage_context: dict):
    """执行单个任务，内部串起 Generator 与 Validate。"""
    task = runtime.todo_list.get_task_by_name(task_name)
    if not task:
        print(f"⚠️  未找到任务: {task_name}")
        return

    print(f"\n🚀 开始执行任务: {task_name}")
    print(f"📝 任务详情: {task}")
    reset_generator_memory(runtime)
    generator_action_guard = ConsecutiveActionGuard()
    generator_step = 0

    while True:
        generator_step += 1
        current_task = runtime.todo_list.get_task_by_name(task_name)
        if current_task is None:
            print(f"⚠️  任务执行过程中丢失任务: {task_name}")
            return

        action = run_generator_step(runtime, current_task, generator_step, stage_context)
        if generator_action_guard.is_repeated(action):
            feedback = build_repeated_action_feedback(
                "Generator-Agent",
                action,
                "请更换动作；如果现有证据已经足够，请直接整理结论并调用 update_task_conclusion。",
            )
            runtime.generator_memory.add_memory(generator_step, "system_feedback", {}, feedback)
            print(f"  ⚠️  {feedback}")
            continue

        generator_action_guard.remember(action)
        if action.tool != "update_task_conclusion":
            result = execute_runtime_tool(runtime, action.tool, action.parameters)
            runtime.generator_memory.add_memory(generator_step, action.tool, action.parameters, result)
            print(f"  ✅ 工具执行结果: {result}")
            continue

        conclusion = action.parameters.get("conclusion", "")
        runtime.todo_list.update_task_conclusion(task_name, conclusion)
        print(f"  📝 Generator 完成任务，结论: {conclusion}")

        if run_validate_loop(runtime, task_name, generator_step, stage_context):
            runtime.todo_list.update_task_status(task_name, "DONE")
            runtime.generator_memory.clear_memories()
            runtime.validation_memory.clear_memories()
            print(f"\n✅ 任务 '{task_name}' 已完成并通过验证！")
            return

        print(f"\n⚠️  任务 '{task_name}' 验证未通过，Generator 将继续重试...")


def has_unfinished_tasks(runtime: AgentRuntime) -> bool:
    """判断当前是否还存在未完成任务。"""
    return any(task.task_status != "DONE" for task in runtime.todo_list.get_all_tasks())


def handle_plan_action(runtime: AgentRuntime, action: AgentAction, stage_context: dict) -> bool:
    """处理一次 Plan-Agent 返回的控制动作。"""
    plan_tool = action.tool
    plan_params = action.parameters

    if plan_tool == "init_tasks" and has_unfinished_tasks(runtime):
        print("⚠️  当前已有未完成任务，已在本地拦截重复 init_tasks。")
        return False

    if plan_tool == "init_tasks":
        task_list = plan_params.get("tasks", [])
        runtime.todo_list.init_tasks(task_list)
        print(f"✅ 已初始化任务列表: {task_list}")
        return False

    if plan_tool == "add_task":
        task_name = plan_params.get("task_name", "")
        if task_name:
            runtime.todo_list.add_task(task_name)
            print(f"✅ 已添加任务: {task_name}")
        return False

    if plan_tool == "update_task_status":
        task_name = plan_params.get("task_name", "")
        new_status = plan_params.get("status", "PENDING")
        if task_name:
            runtime.todo_list.update_task_status(task_name, new_status)
            print(f"✅ 已更新任务 '{task_name}' 状态为: {new_status}")
        return False

    if plan_tool == "respond_to_user":
        message = plan_params.get("message", "")
        if message:
            print(f"\n💬 {message}")
        return True

    if plan_tool == "subagent_tool":
        task_name = plan_params.get("task_name")
        run_task(runtime, task_name, stage_context)
        return False

    return False


def print_completed_tasks(runtime: AgentRuntime):
    """打印全部已完成任务的结论。"""
    print("\n=== 所有任务已完成 ===")
    for task in runtime.todo_list.get_all_tasks():
        print(f"任务: {task.task_name}")
        print(f"结论: {task.task_conclusion}")


def run_main_loop(runtime: AgentRuntime, max_iter: int = 30):
    """运行顶层 Plan-Agent 循环。"""
    stage_context = build_stage_context(runtime.tool_service)

    for iteration in range(max_iter):
        action = run_plan_step(runtime, iteration, stage_context)
        should_stop = handle_plan_action(runtime, action, stage_context)
        if should_stop:
            break

        all_tasks = runtime.todo_list.get_all_tasks()
        if all_tasks and all(task.task_status == "DONE" for task in all_tasks):
            print_completed_tasks(runtime)
            break
