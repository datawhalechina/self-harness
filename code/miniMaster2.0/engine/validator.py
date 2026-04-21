"""验证循环。

这是 miniMaster 的第三层循环，作用是把“执行器声称自己完成了任务”再独立检查一遍。
它的关键价值不在于更聪明，而在于：
- 角色分离：执行和评估不由同一条思路负责到底；
- 标准显式：验证围绕 completion checklist 逐项判断；
- 失败可回流：验证反馈会被写回 Generator，驱动下一轮补证据。
"""

from __future__ import annotations

from domain.task_requirements import build_completion_checklist
from domain.types import AgentRuntime
from engine.guards import ConsecutiveActionGuard, build_repeated_action_feedback
from engine.support import (
    LOGGER,
    build_validation_stall_feedback,
    execute_runtime_tool,
    has_runtime_time_left,
    push_generator_feedback,
    push_validation_feedback,
)
from llm.prompting.builders import build_validate_prompt
from llm.prompting.policies import render_actions_text
from llm.prompting.protocol import build_openai_tools
from llm.runner import request_agent_action
from memory.prompt_context import build_validator_prompt_context


def _normalize_requirement_list(value: object) -> list[str]:
    """把 validate_tool 返回的条目列表压成去重后的标准文本。"""
    if not isinstance(value, list):
        return []

    normalized_items: list[str] = []
    seen: set[str] = set()
    for item in value:
        # 统一压缩多余空白，便于后面和 checklist 做集合比较。
        normalized_item = " ".join(str(item or "").split()).strip()
        if not normalized_item or normalized_item in seen:
            continue
        normalized_items.append(normalized_item)
        seen.add(normalized_item)
    return normalized_items


def _build_requirement_partition_feedback(
    *,
    unknown_items: list[str],
    unclassified_items: list[str],
    overlapping_items: list[str],
) -> str:
    """在验证器分类不完整时，生成发回 Generator 的纠偏提示。"""
    lines = [
        "验证器给出的完成项分类不完整或不一致。",
        "请严格按照 completion_checklist 的原文，把每一项逐项归类到 covered_requirements 或 missing_requirements。",
    ]
    if unknown_items:
        lines.append("出现了不在 completion_checklist 中的条目：")
        lines.extend(f"- {item}" for item in unknown_items)
    if unclassified_items:
        lines.append("以下完成项尚未被分类：")
        lines.extend(f"- {item}" for item in unclassified_items)
    if overlapping_items:
        lines.append("以下完成项同时出现在 covered_requirements 和 missing_requirements 中：")
        lines.extend(f"- {item}" for item in overlapping_items)
    return "\n".join(lines)


def run_validate_loop(
    runtime: AgentRuntime,
    task_name: str,
    generator_step: int,
    stage_context: dict,
) -> tuple[bool, str]:
    """循环执行 Validate-Agent，并返回是否通过以及对应反馈。

    这层循环的一个设计重点是“最后一步强制收口”：
    验证器到了最后一步后，不再允许继续 read/glob/grep/bash，只能直接调用
    `validate_tool` 给出判定，防止验证阶段无限拖延。
    """
    # 取出 Validator 阶段的静态配置。
    role_context = stage_context["validator"]
    agent_name = role_context["agent_name"]
    # 每次开始验证前，都先清空上一次验证残留的 working memory。
    runtime.validation_memory.clear_memories()
    validate_action_guard = ConsecutiveActionGuard()
    max_validate_steps = runtime.max_validate_steps
    # 预先准备“只能 validate_tool”的动作集合，供最后一步切换。
    validate_only_actions = tuple(action for action in role_context["actions"] if action.name == "validate_tool")
    validate_only_tools = build_openai_tools(validate_only_actions, runtime.tool_service.get_tool_spec)
    validate_only_policy_text = render_actions_text(validate_only_actions)

    for validation_step in range(1, max_validate_steps + 1):
        if not has_runtime_time_left(runtime):
            feedback = (
                f"总运行时间已达到预算上限（{runtime.max_total_runtime_seconds} 秒），"
                "验证阶段被中止。"
            )
            push_generator_feedback(runtime, generator_step, feedback)
            return False, feedback

        LOGGER.agent_step(agent_name, validation_step, icon="🔍", indent="    ")
        # 每一步都重新读取任务，保证读到的是最新结论。
        task = runtime.todo_list.get_task_by_name(task_name)
        # 给 Validator 准备 checklist、task_history 和验证 working memory。
        memory_context = build_validator_prompt_context(runtime, task)
        if validation_step == max_validate_steps:
            # 最后一步切换到“必须直接判定”的模式。
            memory_context["validation_status"] = (
                "这已经是验证阶段最后一步。你必须基于现有 task_history 与 working_memory 直接调用 validate_tool，"
                "不能再继续 read / glob / grep / bash。"
            )
            available_actions = validate_only_actions
            available_tools = validate_only_tools
            policy_text = validate_only_policy_text
        else:
            memory_context["validation_status"] = (
                f"当前是验证阶段第 {validation_step} / {max_validate_steps} 步。"
                "优先用已有证据收口；只有在确实缺关键条件时才继续验证。"
            )
            available_actions = role_context["actions"]
            available_tools = role_context["openai_tools"]
            policy_text = role_context["policy_text"]

        # 根据当前模式生成对应 Prompt。
        val_prompt = build_validate_prompt(
            task=runtime.todo_list.to_payload(task),
            memory_context=memory_context,
            base_tools=stage_context["base_tools"],
            search_tools=stage_context["search_tools"],
            policy_text=policy_text,
        )
        action = request_agent_action(
            prompt=val_prompt,
            system_prompt=stage_context["system_prompt"],
            actions=available_actions,
            tools=available_tools,
            agent_name=agent_name,
            model_name=runtime.model_name,
            client=runtime.client,
            timeout_seconds=runtime.llm_timeout_seconds,
            log_indent="    ",
        )
        LOGGER.agent_tool_selection(
            agent_name,
            action.tool,
            action.parameters,
            icon="🛠️",
            indent="    ",
        )

        if action.tool != "validate_tool" and validate_action_guard.is_repeated(action):
            # 与 Executor 一样，验证器重复动作时不立刻崩掉，而是给它一条结构化纠偏反馈。
            reason = build_repeated_action_feedback(
                agent_name,
                action,
                "请不要继续重复验证；应基于现有证据直接给出 validate_tool 结论，"
                "或要求 Executor 提供更可验证的结果。",
            )
            validation_feedback = (
                "你刚刚重复了同一个验证动作。\n"
                f"具体问题：{reason}\n"
                "请先判断现有验证证据是否已经覆盖 done_when。\n"
                "如果已经覆盖，下一步必须直接调用 validate_tool。\n"
                "如果仍未覆盖，请明确还缺哪一项条件，再补充新的验证证据。"
            )
            push_validation_feedback(runtime, validation_step, validation_feedback)
            LOGGER.error(reason, indent="    ")
            continue

        if action.tool != "validate_tool":
            # 只对非最终判定动作做重复检测，因为 validate_tool 本来就是收口动作。
            validate_action_guard.remember(action)

        if action.tool != "validate_tool":
            # 非 validate_tool 时，说明 Validator 还在继续取验证证据。
            result = execute_runtime_tool(runtime, action.tool, action.parameters, log_prefix="    ")
            runtime.validation_memory.add_memory(validation_step, action.tool, action.parameters, result)
            LOGGER.tool_result(result, indent="    ", label="验证工具执行结果")
            continue

        # 下面开始解析 validate_tool 的结构化输出。
        status = action.parameters.get("status")
        reason = action.parameters.get("reason", "未知错误")
        covered_requirements = _normalize_requirement_list(action.parameters.get("covered_requirements"))
        missing_requirements = _normalize_requirement_list(action.parameters.get("missing_requirements"))
        # completion_checklist 来自任务的 done_when + deliverable 归一化结果。
        completion_checklist = build_completion_checklist(task)
        checklist_items = _normalize_requirement_list(completion_checklist)
        # 后续全部转成集合，是为了做“漏项 / 重叠 / 非法条目”的确定性检查。
        checklist_set = set(checklist_items)
        covered_set = set(covered_requirements)
        missing_set = set(missing_requirements)
        overlapping_items = sorted(covered_set & missing_set)
        unknown_items = sorted((covered_set | missing_set) - checklist_set)
        unclassified_items = sorted(checklist_set - (covered_set | missing_set))

        # Validator 的输出本身也要经过本地确定性检查，避免模型“口头上说覆盖了”
        # 但实际没把 checklist 分对。
        if checklist_items and (unknown_items or unclassified_items or overlapping_items):
            generator_feedback = _build_requirement_partition_feedback(
                unknown_items=unknown_items,
                unclassified_items=unclassified_items,
                overlapping_items=overlapping_items,
            )
            push_generator_feedback(runtime, generator_step, generator_feedback)
            LOGGER.error("验证失败，将返回 Generator 重试", indent="    ")
            return False, generator_feedback

        if status == "有效" and missing_requirements:
            # “有效”与“仍有缺项”在逻辑上冲突，因此直接视为验证失败。
            missing_text = "；".join(missing_requirements)
            generator_feedback = (
                "验证器判定逻辑不一致：一边给出 `有效`，一边仍报告了未完成项。\n"
                f"仍缺项：{missing_text}\n"
                "请补齐这些完成项的证据，或直接改写结论，避免把未完成项写成已完成。"
            )
            push_generator_feedback(runtime, generator_step, generator_feedback)
            LOGGER.error("验证失败，将返回 Generator 重试", indent="    ")
            return False, generator_feedback

        if status == "有效" and checklist_items and covered_set != checklist_set:
            # 即便 missing_requirements 恰好为空，也必须保证 checklist 全量被覆盖。
            generator_feedback = (
                "验证器给出了 `有效`，但并未把 completion_checklist 中的全部完成项都标记为已覆盖。\n"
                "只有当清单中的每一项都被证据覆盖时，才能判定为 `有效`。"
            )
            push_generator_feedback(runtime, generator_step, generator_feedback)
            LOGGER.error("验证失败，将返回 Generator 重试", indent="    ")
            return False, generator_feedback

        LOGGER.validation_result(status, reason, indent="    ")

        if status == "有效":
            LOGGER.success("验证通过！", indent="    ")
            return True, reason

        # 验证失败时，最重要的是把“失败原因”翻译成下一轮 Generator 能直接执行的提示。
        missing_text = ""
        if missing_requirements:
            missing_text = "\n仍缺的完成项：\n- " + "\n- ".join(missing_requirements)
        generator_feedback = (
            "验证失败，需要针对下面的具体问题调整。\n"
            f"失败原因：{reason}\n"
            "请先判断这是“缺少验证条件”还是“结论表述与现有证据不一致”。\n"
            "如果是缺少验证条件，请补充新的证据来覆盖该条件。\n"
            "如果是结论表述不一致，请直接改写结论，使结论与现有证据严格一致。\n"
            f"{missing_text}\n"
            "下一步必须直接回应这条失败原因，不要重复之前已经做过且没有产生新信息的动作。"
        )
        push_generator_feedback(runtime, generator_step, generator_feedback)
        LOGGER.error("验证失败，将返回 Generator 重试", indent="    ")
        return False, generator_feedback

    feedback = (
        f"{agent_name} 达到最大验证步数（{max_validate_steps} 步），任务仍未收口。"
        "\n请基于现有证据直接收敛结论，或补充更直接的新证据。"
    )
    push_generator_feedback(runtime, generator_step, feedback)
    LOGGER.error(feedback, indent="    ")
    return False, feedback
