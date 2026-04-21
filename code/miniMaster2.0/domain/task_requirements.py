"""把任务完成条件归一化成 checklist。

很多任务会同时包含 `done_when` 和 `deliverable`，而且用户或 Planner 写出来的形式
并不总是规整的列表。这个模块的作用就是把这些自然语言描述尽量拆成若干可核对项，
方便 Validator 逐条判断“哪些已覆盖、哪些还缺证据”。
"""

from __future__ import annotations

import re

from domain.types import Task


MAX_REQUIREMENT_ITEMS = 8
_INLINE_ENUM_MARKER_PATTERN = re.compile(r"\s*([①②③④⑤⑥⑦⑧⑨⑩])\s*")
_LEADING_LIST_MARKER_PATTERN = re.compile(
    r"^\s*(?:[-*•]|[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.)、]|[一二三四五六七八九十]+[.)、])\s*"
)


def _normalize_text(text: str) -> str:
    """压缩多余空白，便于去重和比较。"""
    return " ".join(str(text or "").split()).strip()


def _split_requirement_text(text: str) -> list[str]:
    """尽量从自然语言要求中切出更细的完成项。

    它会依次处理：
    - 多行文本
    - 行首列表符号
    - 行内序号
    - 过长逗号串联句子的再次拆分
    """
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    normalized = _INLINE_ENUM_MARKER_PATTERN.sub(r"\n\1 ", normalized)

    raw_parts: list[str] = []
    for raw_line in normalized.split("\n"):
        line = _LEADING_LIST_MARKER_PATTERN.sub("", raw_line).strip()
        if not line:
            continue
        raw_parts.extend(re.split(r"[；;]+", line))

    candidates: list[str] = []
    for raw_part in raw_parts:
        candidate = _normalize_text(raw_part)
        if not candidate:
            continue

        comma_count = candidate.count("，") + candidate.count(",")
        if comma_count >= 2:
            split_parts = [_normalize_text(part) for part in re.split(r"[，,]+", candidate)]
            meaningful_parts = [part for part in split_parts if len(part) >= 6]
            if len(meaningful_parts) >= 2:
                candidates.extend(meaningful_parts)
                continue

        candidates.append(candidate)

    return candidates


def build_completion_checklist(task: Task | None) -> list[str]:
    """把任务完成条件归一成便于逐项核对的清单。"""
    if task is None:
        return []

    ordered_candidates: list[str] = []
    ordered_candidates.extend(_split_requirement_text(task.done_when))
    ordered_candidates.extend(_split_requirement_text(task.deliverable))

    checklist: list[str] = []
    seen: set[str] = set()
    # 顺序很重要：优先保留写在前面的要求，让 checklist 更接近原始任务意图。
    for candidate in ordered_candidates:
        normalized_candidate = _normalize_text(candidate)
        if not normalized_candidate or normalized_candidate in seen:
            continue
        if normalized_candidate.endswith((":", "：")):
            continue
        checklist.append(normalized_candidate)
        seen.add(normalized_candidate)
        if len(checklist) >= MAX_REQUIREMENT_ITEMS:
            break
    return checklist


def render_completion_checklist(task: Task | None) -> str:
    """把 checklist 渲染成可直接塞进 Prompt 的 bullet 文本。"""
    checklist = build_completion_checklist(task)
    if not checklist:
        return "当前任务没有可拆分的完成清单；请直接以 task.done_when 和 deliverable 为准。"
    return "\n".join(f"- {item}" for item in checklist)
