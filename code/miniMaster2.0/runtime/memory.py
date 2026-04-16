import json

from dataclasses import asdict

from app.agent_types import MemoryEntry, MemoryToolCall


DEFAULT_WORKING_MEMORY_MAX_CHARS = 12000
MEMORY_TEXT_PREVIEW_CHARS = 600
MEMORY_LINE_PREVIEW_CHARS = 240
MEMORY_LIST_PREVIEW_ITEMS = 6
MEMORY_DICT_PREVIEW_ITEMS = 16
MEMORY_MAX_DEPTH = 4
MEMORY_RESULT_HARD_LIMIT = 3500


def truncate_text(text, limit: int = MEMORY_TEXT_PREVIEW_CHARS) -> str:
    """把超长文本裁成适合放进 Prompt 记忆的预览片段。"""
    normalized_text = str(text)
    if len(normalized_text) <= limit:
        return normalized_text
    return f"{normalized_text[:limit]} ...(已截断，原始长度 {len(normalized_text)} 字符)"


def compact_for_memory(value, depth: int = 0):
    """把任意工具输入/输出压缩成更适合放进工作记忆的结构。"""
    if depth >= MEMORY_MAX_DEPTH:
        return truncate_text(json.dumps(value, ensure_ascii=False), limit=MEMORY_LINE_PREVIEW_CHARS)

    if isinstance(value, dict):
        compacted = {}
        items = list(value.items())

        for key, item_value in items[:MEMORY_DICT_PREVIEW_ITEMS]:
            if key == "matches" and isinstance(item_value, list):
                compacted[key] = [
                    compact_for_memory(match, depth + 1)
                    for match in item_value[:MEMORY_LIST_PREVIEW_ITEMS]
                ]
                omitted_matches = len(item_value) - MEMORY_LIST_PREVIEW_ITEMS
                if omitted_matches > 0:
                    compacted["matches_omitted"] = omitted_matches
                continue

            if key in {"stdout", "stderr", "content", "error", "message"} and isinstance(item_value, str):
                compacted[key] = truncate_text(item_value, limit=MEMORY_TEXT_PREVIEW_CHARS)
                continue

            if key == "line_content" and isinstance(item_value, str):
                compacted[key] = truncate_text(item_value, limit=MEMORY_LINE_PREVIEW_CHARS)
                continue

            compacted[key] = compact_for_memory(item_value, depth + 1)

        omitted_keys = len(items) - MEMORY_DICT_PREVIEW_ITEMS
        if omitted_keys > 0:
            compacted["_omitted_key_count"] = omitted_keys
        return compacted

    if isinstance(value, (list, tuple)):
        preview = [compact_for_memory(item, depth + 1) for item in value[:MEMORY_LIST_PREVIEW_ITEMS]]
        omitted_items = len(value) - MEMORY_LIST_PREVIEW_ITEMS
        if omitted_items > 0:
            preview.append(f"... 其余 {omitted_items} 项已省略")
        return preview

    if isinstance(value, str):
        return truncate_text(value, limit=MEMORY_TEXT_PREVIEW_CHARS)

    return value


def prepare_memory_result(tool_name: str, result):
    """把工具结果裁剪到适合继续喂给模型的大小。"""
    compacted = compact_for_memory(result)
    compacted_text = json.dumps(compacted, ensure_ascii=False)
    if len(compacted_text) <= MEMORY_RESULT_HARD_LIMIT:
        return compacted

    if isinstance(compacted, dict) and isinstance(compacted.get("matches"), list):
        trimmed_matches = dict(compacted)
        matches_preview = trimmed_matches["matches"][:3]
        trimmed_matches["matches"] = matches_preview
        trimmed_matches["matches_omitted"] = trimmed_matches.get("matches_omitted", 0) + max(
            0, len(compacted["matches"]) - len(matches_preview)
        )
        compacted = trimmed_matches
        compacted_text = json.dumps(compacted, ensure_ascii=False)
        if len(compacted_text) <= MEMORY_RESULT_HARD_LIMIT:
            return compacted

    return {
        "success": bool(result.get("success")) if isinstance(result, dict) else True,
        "note": f"{tool_name} 工具结果过长，已压缩为摘要",
        "preview": truncate_text(compacted_text, limit=MEMORY_RESULT_HARD_LIMIT),
    }


class WorkingMemory:
    """工作记忆管理类。"""

    def __init__(self, keep_latest_n: int = 3, max_chars: int = DEFAULT_WORKING_MEMORY_MAX_CHARS):
        self.memories: list[MemoryEntry] = []
        self.keep_latest_n = keep_latest_n
        self.max_chars = max_chars
        self.summary = ""

    def add_memory(self, step: int, tool_name: str, parameters: dict, result):
        self.memories.append(
            MemoryEntry(
                step=step,
                tool_call=MemoryToolCall(
                    tool_name=tool_name,
                    parameters=compact_for_memory(parameters),
                ),
                result=prepare_memory_result(tool_name, result),
            )
        )

    def get_all_memories_payload(self) -> list[dict]:
        return [asdict(memory) for memory in self.memories]

    def get_prompt_context(self) -> str:
        context = ""
        if self.summary:
            context += f"【早期步骤摘要】:\n{self.summary}\n\n"

        context += "【执行步骤】:\n" + json.dumps(self.get_all_memories_payload(), ensure_ascii=False, indent=2)
        return context

    def get_all_memories(self):
        return self.memories.copy()

    def check_needs_summary(self) -> bool:
        current_length = len(self.get_prompt_context())
        return current_length > self.max_chars and len(self.memories) > self.keep_latest_n

    def get_memories_to_summarize(self) -> list:
        if self.check_needs_summary():
            return [asdict(memory) for memory in self.memories[:-self.keep_latest_n]]
        return []

    def commit_summary(self, new_summary: str):
        self.summary = new_summary
        self.memories = self.memories[-self.keep_latest_n:]

    def clear_memories(self):
        self.memories = []
        self.summary = ""
