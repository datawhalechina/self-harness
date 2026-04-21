"""工作记忆系统。

这是 miniMaster 里最体现“上下文工程”思想的模块之一。它并不追求保存完整日志，
而是追求把“接下来最有帮助的信息”保留下来，因此做了三件事：
1. 记录每一步工具调用和结果
2. 把过长结果裁剪成模型可承受的摘要
3. 在上下文超限时，把更早的步骤压成稳定 summary
"""

from __future__ import annotations

from dataclasses import asdict
import json

from domain.types import MemoryEntry, MemoryToolCall


DEFAULT_WORKING_MEMORY_MAX_CHARS = 12000
# 下面这组常量控制记忆裁剪策略。它们集中声明在顶部，便于教学时观察
# “Prompt 可读性”和“保留证据完整度”之间的取舍。
MEMORY_TEXT_PREVIEW_CHARS = 600
MEMORY_LINE_PREVIEW_CHARS = 240
MEMORY_LIST_PREVIEW_ITEMS = 6
MEMORY_DICT_PREVIEW_ITEMS = 16
MEMORY_MAX_DEPTH = 4
MEMORY_RESULT_HARD_LIMIT = 3500
MEMORY_RECENT_STEP_LIMIT = 6
MEMORY_FEEDBACK_LIMIT = 3
MEMORY_VALIDATION_EVIDENCE_LIMIT = 6
MEMORY_ENTRY_LINE_LIMIT = 240
MEMORY_READ_SNIPPET_CHARS = 500
MEMORY_BASH_OUTPUT_CHARS = 400
MEMORY_SEARCH_HIT_PREVIEW = 3
MEMORY_GLOB_PREVIEW_ITEMS = 12
MEMORY_SUMMARY_ITEM_LIMIT = 4
MEMORY_SUMMARY_MAX_CHARS = 2400


class WorkingMemory:
    """工作记忆管理类。"""

    def __init__(self, keep_latest_n: int = 3, max_chars: int = DEFAULT_WORKING_MEMORY_MAX_CHARS):
        # 还没有被压缩掉的“近期逐步记忆”。
        self.memories: list[MemoryEntry] = []
        # 超过这个数量后，较早步骤就有资格被压缩成 summary。
        self.keep_latest_n = keep_latest_n
        # 整份工作记忆允许占用的最大字符预算。
        self.max_chars = max_chars
        # 更早历史会被压成这一段摘要文本。
        self.summary = ""

    def add_memory(self, step: int, tool_name: str, parameters: dict, result):
        """记录一步新记忆，并先对参数/结果做面向 Prompt 的压缩。"""
        # 参数先压缩，避免把大对象原样塞进记忆。
        compacted_parameters = compact_for_memory(parameters)
        self.memories.append(
            MemoryEntry(
                # 记录发生在第几步。
                step=step,
                tool_call=MemoryToolCall(
                    # 记录动作名。
                    tool_name=tool_name,
                    # 记录压缩后的参数。
                    parameters=compacted_parameters,
                ),
                # 结果会按工具类型定制压缩。
                result=prepare_memory_result(tool_name, compacted_parameters, result),
            )
        )

    def get_all_memories_payload(self) -> list[dict]:
        """以可序列化形式返回全部记忆。"""
        return [asdict(memory) for memory in self.memories]

    def get_all_memories(self):
        """返回记忆对象副本。"""
        return self.memories.copy()

    def get_feedback_memories(self, limit: int | None = None) -> list[MemoryEntry]:
        """返回最近的系统反馈记忆。"""
        # system_feedback 是一类特殊记忆，不代表真实工具执行。
        feedbacks = [memory for memory in self.memories if is_feedback_entry(memory)]
        if limit is None:
            return feedbacks
        return feedbacks[-limit:]

    def get_recent_tool_memories(self, limit: int | None = None) -> list[MemoryEntry]:
        """返回最近的非反馈执行记忆。"""
        # 这里会过滤掉 system_feedback，只保留真实行动轨迹。
        steps = [memory for memory in self.memories if not is_feedback_entry(memory)]
        if limit is None:
            return steps
        return steps[-limit:]

    def get_latest_feedback(self) -> MemoryEntry | None:
        """返回最近一条系统反馈。"""
        feedbacks = self.get_feedback_memories(limit=1)
        return feedbacks[-1] if feedbacks else None

    def render_for_generator_prompt(self) -> str:
        """把工作记忆渲染成更利于 Generator 决策的上下文视图。

        这个视图强调：
        - 当前最紧急的 system feedback
        - 最近执行证据
        - 更早阶段的摘要
        """
        sections = []
        latest_feedback = self.get_latest_feedback()
        if latest_feedback is not None:
            # 最新反馈单独提升优先级，让 Executor 一眼看到当前最该处理的问题。
            sections.append(
                "【当前最优先响应的问题】\n"
                f"- {build_result_summary('system_feedback', latest_feedback.result)}"
            )

        recent_feedbacks = self.get_feedback_memories(limit=MEMORY_FEEDBACK_LIMIT)
        if recent_feedbacks:
            history_feedbacks = recent_feedbacks[:-1] if latest_feedback is not None else recent_feedbacks
            if history_feedbacks:
                sections.append(
                    "【最近收到的系统反馈】\n"
                    + render_bullets(
                        [
                            build_memory_entry_line(entry)
                            for entry in history_feedbacks
                        ],
                        empty_line="当前没有更早的系统反馈。",
                    )
                )

        if self.summary:
            # 更早历史已经被压成摘要，不再逐条展开。
            sections.append(f"【早期步骤摘要】\n{self.summary}")

        recent_steps = self.get_recent_tool_memories(limit=MEMORY_RECENT_STEP_LIMIT)
        sections.append(
            "【最近执行步骤】\n"
            + render_bullets(
                [build_memory_entry_line(entry) for entry in recent_steps],
                empty_line="当前还没有执行步骤。",
            )
        )
        return "\n\n".join(sections)

    def render_for_validation_prompt(self) -> str:
        """把验证记忆渲染成“验证条件视图”。

        相比 Generator 视图，它会额外把最近动作区分成：
        - 已验证成功的证据
        - 暂时失败或暴露缺口的线索
        """
        sections = []
        latest_feedback = self.get_latest_feedback()
        if latest_feedback is not None:
            sections.append(
                "【当前最优先处理的验证问题】\n"
                f"- {build_result_summary('system_feedback', latest_feedback.result)}"
            )

        recent_feedbacks = self.get_feedback_memories(limit=MEMORY_FEEDBACK_LIMIT)
        if recent_feedbacks:
            history_feedbacks = recent_feedbacks[:-1] if latest_feedback is not None else recent_feedbacks
            if history_feedbacks:
                sections.append(
                    "【最近收到的验证反馈】\n"
                    + render_bullets(
                        [
                            build_memory_entry_line(entry)
                            for entry in history_feedbacks
                        ],
                        empty_line="当前没有更早的验证反馈。",
                    )
                )

        if self.summary:
            sections.append(f"【更早的验证摘要】\n{self.summary}")

        recent_steps = self.get_recent_tool_memories(limit=MEMORY_VALIDATION_EVIDENCE_LIMIT)
        validated_lines = []
        missing_lines = []
        recent_action_lines = []

        for entry in recent_steps:
            # 每条最近验证动作都会被转成统一摘要行。
            summary_line = build_memory_entry_line(entry)
            recent_action_lines.append(summary_line)

            result = entry.result if isinstance(entry.result, dict) else {}
            # success=True 视为已经确认的证据。
            if result.get("success") is True:
                validated_lines.append(summary_line)
            # success=False 则视为缺口或失败线索。
            elif result.get("success") is False:
                missing_lines.append(summary_line)

        sections.append(
            "【已验证条件与证据】\n"
            + render_bullets(
                validated_lines,
                empty_line="当前还没有已确认的验证证据。",
            )
        )
        sections.append(
            "【仍待补充的验证线索】\n"
            + render_bullets(
                missing_lines,
                empty_line="暂未出现明确缺口，请结合 <task> 与 <task_history> 判断是否仍有未覆盖条件。",
            )
        )
        sections.append(
            "【最近验证动作】\n"
            + render_bullets(
                recent_action_lines,
                empty_line="当前还没有执行验证动作。",
            )
        )
        return "\n\n".join(sections)

    def render_for_planner_prompt(self) -> str:
        """把规划阶段的侦察结果渲染成简洁上下文。"""
        sections = []
        latest_feedback = self.get_latest_feedback()
        if latest_feedback is not None:
            sections.append(
                "【当前最优先处理的规划问题】\n"
                f"- {build_result_summary('system_feedback', latest_feedback.result)}"
            )

        recent_feedbacks = self.get_feedback_memories(limit=MEMORY_FEEDBACK_LIMIT)
        if recent_feedbacks:
            history_feedbacks = recent_feedbacks[:-1] if latest_feedback is not None else recent_feedbacks
            if history_feedbacks:
                sections.append(
                    "【最近收到的规划反馈】\n"
                    + render_bullets(
                        [
                            build_memory_entry_line(entry)
                            for entry in history_feedbacks
                        ],
                        empty_line="当前没有更早的规划反馈。",
                    )
                )

        if self.summary:
            sections.append(f"【更早侦察摘要】\n{self.summary}")

        recent_steps = self.get_recent_tool_memories(limit=MEMORY_RECENT_STEP_LIMIT)
        if recent_steps:
            # Planner 更关心最新 observation，因此单独高亮最后一条。
            sections.append(
                "【最近一次侦察 observation】\n"
                f"- {build_memory_entry_line(recent_steps[-1])}"
            )
        sections.append(
            "【最近规划侦察】\n"
            + render_bullets(
                [build_memory_entry_line(entry) for entry in recent_steps],
                empty_line="当前还没有规划侦察记录。",
            )
        )
        return "\n\n".join(sections)

    def render_for_retry_summary(self, label: str = "执行") -> str:
        """把本轮记忆压成适合下次 retry 复用的摘要。"""
        sections = []
        if self.summary:
            sections.append(f"【更早{label}摘要】\n{self.summary}")

        recent_steps = self.get_recent_tool_memories(limit=MEMORY_RECENT_STEP_LIMIT)
        successful_lines = []
        failed_lines = []
        for entry in recent_steps:
            summary_line = build_memory_entry_line(entry)
            result = entry.result if isinstance(entry.result, dict) else {}
            # 成功/失败分开保存，是为了下一轮既知道什么能复用，也知道什么别再重试。
            if result.get("success") is False:
                failed_lines.append(summary_line)
            else:
                successful_lines.append(summary_line)

        recent_feedbacks = self.get_feedback_memories(limit=MEMORY_FEEDBACK_LIMIT)
        feedback_lines = [build_memory_entry_line(entry) for entry in recent_feedbacks]

        sections.append(
            f"【上一轮{label}已获得的事实与证据】\n"
            + render_bullets(
                successful_lines,
                empty_line=f"上一轮{label}还没有留下明确可复用的成功证据。",
            )
        )
        sections.append(
            f"【上一轮{label}不要重复的路径】\n"
            + render_bullets(
                failed_lines + feedback_lines,
                empty_line=f"上一轮{label}还没有暴露出明显的失败路径。",
            )
        )
        return "\n\n".join(sections)

    def get_prompt_context(self, view: str = "generator") -> str:
        """按不同视图渲染 prompt 上下文。"""
        if view == "planner":
            return self.render_for_planner_prompt()
        if view == "generator":
            return self.render_for_generator_prompt()
        if view == "validation":
            return self.render_for_validation_prompt()
        raise ValueError(f"未知工作记忆视图: {view}")

    def compact_old_memories(self) -> bool:
        """在上下文超限时，把较早步骤压成确定性摘要。

        压缩策略是“保留最近若干步原文 + 把更早内容总结成摘要”，
        这比简单丢弃旧步骤更适合长时运行场景。
        """
        if len(self.memories) <= self.keep_latest_n:
            return False

        # 先粗略估算“当前 summary + 全部 memories”占多少字符。
        context_length = len(
            safe_json(
                {
                    "summary": self.summary,
                    "memories": self.get_all_memories_payload(),
                }
            )
        )
        if context_length <= self.max_chars:
            return False

        # 只把较早部分压缩，最近 keep_latest_n 步原样保留。
        older_entries = self.memories[:-self.keep_latest_n]
        self.commit_summary(build_compacted_summary(self.summary, older_entries))
        return True

    def commit_summary(self, new_summary: str):
        """提交新摘要，并只保留最近未压缩的几步。"""
        self.summary = new_summary
        self.memories = self.memories[-self.keep_latest_n:]

    def clear_memories(self):
        """清空当前工作记忆。"""
        self.memories = []
        self.summary = ""


def truncate_text(text, limit: int = MEMORY_TEXT_PREVIEW_CHARS) -> str:
    """把超长文本裁成适合放进 Prompt 记忆的预览片段。"""
    normalized_text = str(text)
    if len(normalized_text) <= limit:
        return normalized_text
    return f"{normalized_text[:limit]} ...(已截断，原始长度 {len(normalized_text)} 字符)"


def compact_for_memory(value, depth: int = 0):
    """把任意工具输入/输出压缩成更适合放进工作记忆的结构。

    这里不是简单截断，而是按数据类型做差异化压缩：
    - dict: 只保留前若干字段，并对关键字段单独裁剪
    - list: 只保留前若干项
    - str: 截成预览片段
    """
    if depth >= MEMORY_MAX_DEPTH:
        # 嵌套太深时直接转成字符串预览，防止复杂对象递归爆炸。
        return truncate_text(json.dumps(value, ensure_ascii=False, default=str), limit=MEMORY_LINE_PREVIEW_CHARS)

    if isinstance(value, dict):
        compacted = {}
        items = list(value.items())

        for key, item_value in items[:MEMORY_DICT_PREVIEW_ITEMS]:
            if key == "matches" and isinstance(item_value, list):
                # 搜索命中列表通常最容易暴涨，因此单独限制预览条数。
                compacted[key] = [
                    compact_for_memory(match, depth + 1)
                    for match in item_value[:MEMORY_LIST_PREVIEW_ITEMS]
                ]
                omitted_matches = len(item_value) - MEMORY_LIST_PREVIEW_ITEMS
                if omitted_matches > 0:
                    compacted["matches_omitted"] = omitted_matches
                continue

            if key in {"stdout", "stderr", "content", "error", "message"} and isinstance(item_value, str):
                # 这些字段最可能很长，因此优先按文本规则裁剪。
                compacted[key] = truncate_text(item_value, limit=MEMORY_TEXT_PREVIEW_CHARS)
                continue

            if key == "line_content" and isinstance(item_value, str):
                # 单行文本预览长度可以更短一些。
                compacted[key] = truncate_text(item_value, limit=MEMORY_LINE_PREVIEW_CHARS)
                continue

            compacted[key] = compact_for_memory(item_value, depth + 1)

        omitted_keys = len(items) - MEMORY_DICT_PREVIEW_ITEMS
        if omitted_keys > 0:
            # 保留“省略了多少字段”的痕迹，提醒模型这不是完整对象。
            compacted["_omitted_key_count"] = omitted_keys
        return compacted

    if isinstance(value, (list, tuple)):
        # 列表和元组统一按“预览前若干项 + 省略说明”处理。
        preview = [compact_for_memory(item, depth + 1) for item in value[:MEMORY_LIST_PREVIEW_ITEMS]]
        omitted_items = len(value) - MEMORY_LIST_PREVIEW_ITEMS
        if omitted_items > 0:
            preview.append(f"... 其余 {omitted_items} 项已省略")
        return preview

    if isinstance(value, str):
        return truncate_text(value, limit=MEMORY_TEXT_PREVIEW_CHARS)

    return value


def _compact_line(text: str, limit: int = MEMORY_ENTRY_LINE_LIMIT) -> str:
    """把多行文本压缩成适合单行展示的摘要。"""
    return truncate_text(" ".join(str(text or "").split()), limit=limit)


def is_feedback_entry(entry: MemoryEntry) -> bool:
    """判断某条记忆是否属于系统反馈。"""
    return entry.tool_call.tool_name == "system_feedback"


def safe_json(value) -> str:
    """稳定地把对象序列化成字符串。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def _prepare_read_result(parameters: dict, result: dict) -> dict:
    """把 read 工具结果压成“文件 + 行号 + 片段”的摘要结构。"""
    success = bool(result.get("success"))
    if not success:
        return {
            "success": False,
            "file_path": parameters.get("file_path", ""),
            "error": truncate_text(result.get("error", ""), limit=MEMORY_LINE_PREVIEW_CHARS),
        }

    # 这些字段能帮助后续 Prompt 知道“这次到底读到了文件哪一段”。
    start_line = result.get("start_line")
    end_line = result.get("end_line")
    total_lines = result.get("total_lines")
    line_range = ""
    if start_line is not None and end_line is not None and total_lines is not None:
        line_range = f"{start_line}-{end_line}/{total_lines}"

    return {
        "success": True,
        "file_path": parameters.get("file_path", ""),
        "line_range": line_range,
        "has_more": bool(result.get("has_more")),
        "snippet": truncate_text(result.get("content", ""), limit=MEMORY_READ_SNIPPET_CHARS),
    }


def _prepare_grep_result(result: dict) -> dict:
    """把 grep 工具结果压成“命中概览”而不是完整命中列表。"""
    success = bool(result.get("success"))
    if not success:
        return {
            "success": False,
            "error": truncate_text(result.get("error", ""), limit=MEMORY_LINE_PREVIEW_CHARS),
        }

    matches = result.get("matches", []) or []
    hits_preview = []
    for match in matches[:MEMORY_SEARCH_HIT_PREVIEW]:
        # 只取少数命中，保留文件、行号、命中文本和行内容预览。
        file_path = match.get("file", "")
        line_number = match.get("line_number", "?")
        matched_text = match.get("matched_text", "")
        line_content = _compact_line(match.get("line_content", ""), limit=160)
        hits_preview.append(f"{file_path}:{line_number} 命中 {matched_text} | {line_content}")

    omitted = max(0, int(result.get("total_matches", len(matches))) - len(hits_preview))
    payload = {
        "success": True,
        "total_matches": result.get("total_matches", len(matches)),
        "files_searched": result.get("files_searched"),
        "hits_preview": hits_preview,
    }
    if omitted > 0:
        payload["hits_omitted"] = omitted
    return payload


def _prepare_glob_result(result: dict) -> dict:
    """把 glob 工具结果压成文件/目录计数与少量预览。"""
    success = bool(result.get("success"))
    if not success:
        return {
            "success": False,
            "error": truncate_text(result.get("error", ""), limit=MEMORY_LINE_PREVIEW_CHARS),
        }

    files = result.get("files", []) or []
    directories = result.get("directories", []) or []
    return {
        "success": True,
        "total_files": result.get("total_files", len(files)),
        "total_directories": result.get("total_directories", len(directories)),
        "files_preview": files[:MEMORY_GLOB_PREVIEW_ITEMS],
        "directories_preview": directories[:MEMORY_GLOB_PREVIEW_ITEMS],
    }


def _prepare_bash_result(result: dict) -> dict:
    """把 bash 工具结果压成 returncode 与 stdout/stderr 预览。"""
    success = bool(result.get("success"))
    payload = {
        "success": success,
        "returncode": result.get("returncode"),
    }

    stdout_text = str(result.get("stdout", "") or "")
    stderr_text = str(result.get("stderr", "") or "")
    if stdout_text.strip():
        payload["stdout_preview"] = truncate_text(stdout_text, limit=MEMORY_BASH_OUTPUT_CHARS)
    if stderr_text.strip():
        payload["stderr_preview"] = truncate_text(stderr_text, limit=MEMORY_BASH_OUTPUT_CHARS)
    if not success and "error" in result:
        payload["error"] = truncate_text(result.get("error", ""), limit=MEMORY_LINE_PREVIEW_CHARS)
    return payload


def prepare_memory_result(tool_name: str, parameters: dict, result):
    """把工具结果裁剪到适合继续喂给模型的大小。"""
    if tool_name == "system_feedback":
        # 系统反馈本来就是给模型读的自然语言，直接截成可接受长度即可。
        return truncate_text(result, limit=MEMORY_TEXT_PREVIEW_CHARS)

    if isinstance(result, dict):
        if tool_name == "read":
            return _prepare_read_result(parameters, result)
        if tool_name == "grep":
            return _prepare_grep_result(result)
        if tool_name == "glob":
            return _prepare_glob_result(result)
        if tool_name == "bash":
            return _prepare_bash_result(result)

    compacted = compact_for_memory(result)
    compacted_text = safe_json(compacted)
    if len(compacted_text) <= MEMORY_RESULT_HARD_LIMIT:
        return compacted

    if isinstance(compacted, dict) and isinstance(compacted.get("matches"), list):
        # 对搜索类结果再做一轮专门缩减，避免大批量命中把上下文塞满。
        trimmed_matches = dict(compacted)
        matches_preview = trimmed_matches["matches"][:3]
        trimmed_matches["matches"] = matches_preview
        trimmed_matches["matches_omitted"] = trimmed_matches.get("matches_omitted", 0) + max(
            0, len(compacted["matches"]) - len(matches_preview)
        )
        compacted = trimmed_matches
        compacted_text = safe_json(compacted)
        if len(compacted_text) <= MEMORY_RESULT_HARD_LIMIT:
            return compacted

    return {
        # 即便压得很狠，也尽量保留 success 信号。
        "success": bool(result.get("success")) if isinstance(result, dict) else True,
        "note": f"{tool_name} 工具结果过长，已压缩为摘要",
        "preview": truncate_text(compacted_text, limit=MEMORY_RESULT_HARD_LIMIT),
    }


def build_result_summary(tool_name: str, result) -> str:
    """把单条记忆结果压成适合 prompt 阅读的一行摘要。"""
    if tool_name == "system_feedback":
        return _compact_line(result, limit=220)

    if not isinstance(result, dict):
        return _compact_line(result, limit=220)

    # 绝大多数工具摘要都会先展示一个成败标记。
    success = result.get("success")
    status_text = "成功" if success else "失败"

    if tool_name == "read":
        summary_parts = [status_text]
        if result.get("file_path"):
            summary_parts.append(f"文件={result['file_path']}")
        if result.get("line_range"):
            summary_parts.append(f"行号={result['line_range']}")
        if result.get("snippet"):
            summary_parts.append(f"片段={_compact_line(result['snippet'], limit=140)}")
        if not success and result.get("error"):
            summary_parts.append(f"错误={result['error']}")
        return "；".join(summary_parts)

    if tool_name == "grep":
        summary_parts = [status_text, f"命中={result.get('total_matches', 0)}"]
        if result.get("files_searched") is not None:
            summary_parts.append(f"检索文件={result.get('files_searched')}")
        hits = result.get("hits_preview", [])
        if hits:
            summary_parts.append(f"摘要={_compact_line(' | '.join(hits), limit=150)}")
        if not success and result.get("error"):
            summary_parts.append(f"错误={result['error']}")
        return "；".join(summary_parts)

    if tool_name == "glob":
        summary_parts = [
            status_text,
            f"文件={result.get('total_files', 0)}",
            f"目录={result.get('total_directories', 0)}",
        ]
        files_preview = result.get("files_preview", [])
        directories_preview = result.get("directories_preview", [])
        preview_items = files_preview + directories_preview
        if preview_items:
            summary_parts.append(f"预览={_compact_line(', '.join(preview_items), limit=320)}")
        if not success and result.get("error"):
            summary_parts.append(f"错误={result['error']}")
        return "；".join(summary_parts)

    if tool_name == "bash":
        summary_parts = [status_text, f"returncode={result.get('returncode')}"]
        if result.get("stdout_preview"):
            summary_parts.append(f"stdout={_compact_line(result['stdout_preview'], limit=140)}")
        if result.get("stderr_preview"):
            summary_parts.append(f"stderr={_compact_line(result['stderr_preview'], limit=140)}")
        if result.get("error"):
            summary_parts.append(f"错误={result['error']}")
        return "；".join(summary_parts)

    summary_parts = [status_text]
    if result.get("note"):
        summary_parts.append(_compact_line(result["note"], limit=120))
    if result.get("preview"):
        summary_parts.append(f"摘要={_compact_line(result['preview'], limit=140)}")
    elif result.get("error"):
        summary_parts.append(f"错误={_compact_line(result['error'], limit=140)}")
    else:
        summary_parts.append(_compact_line(safe_json(result), limit=180))
    return "；".join(summary_parts)


def build_tool_call_summary(entry: MemoryEntry) -> str:
    """生成单条记忆的工具调用摘要。"""
    tool_name = entry.tool_call.tool_name
    if tool_name == "system_feedback":
        return f"step {entry.step} | system_feedback"

    parameters_text = _compact_line(safe_json(entry.tool_call.parameters), limit=120)
    return f"step {entry.step} | {tool_name}({parameters_text})"


def build_memory_entry_line(entry: MemoryEntry) -> str:
    """把单条记忆渲染成统一的一行摘要。"""
    return f"{build_tool_call_summary(entry)} -> {build_result_summary(entry.tool_call.tool_name, entry.result)}"


def render_bullets(lines: list[str], empty_line: str) -> str:
    """把若干行文本渲染成 bullet 列表。"""
    if not lines:
        return f"- {empty_line}"
    return "\n".join(f"- {line}" for line in lines)


def render_limited_bullets(lines: list[str], limit: int, empty_line: str) -> str:
    """把较长列表压成有限的 bullet 预览。"""
    if not lines:
        return f"- {empty_line}"

    selected_lines = lines[-limit:]
    rendered_lines = [f"- {line}" for line in selected_lines]
    omitted_count = len(lines) - len(selected_lines)
    if omitted_count > 0:
        rendered_lines.insert(0, f"- 更早还有 {omitted_count} 条记录已省略")
    return "\n".join(rendered_lines)


def build_compacted_summary(existing_summary: str, entries: list[MemoryEntry]) -> str:
    """把较早的执行记录压成稳定、可读的本地摘要。

    压缩后的摘要仍然区分两类信息：
    - 已确认的事实
    - 失败路径与反馈
    这样下一轮模型不仅知道“以前看到了什么”，还知道“哪些路不要再走”。
    """
    fact_lines = []
    issue_lines = []
    for entry in entries:
        summary_line = build_memory_entry_line(entry)
        if is_feedback_entry(entry):
            issue_lines.append(summary_line)
            continue

        result = entry.result if isinstance(entry.result, dict) else {}
        if result.get("success") is False:
            issue_lines.append(summary_line)
        else:
            fact_lines.append(summary_line)

    sections = []
    if existing_summary:
        sections.append(f"【更早摘要】\n{truncate_text(existing_summary, limit=900)}")
    sections.append(
        "【已确认的早期事实】\n"
        + render_limited_bullets(
            fact_lines,
            limit=MEMORY_SUMMARY_ITEM_LIMIT,
            empty_line="当前没有可复用的早期事实。",
        )
    )
    sections.append(
        "【早期失败与反馈】\n"
        + render_limited_bullets(
            issue_lines,
            limit=MEMORY_SUMMARY_ITEM_LIMIT,
            empty_line="当前没有需要特别避开的早期失败。",
        )
    )
    return truncate_text("\n\n".join(sections), limit=MEMORY_SUMMARY_MAX_CHARS)


__all__ = [
    "DEFAULT_WORKING_MEMORY_MAX_CHARS",
    "WorkingMemory",
]
