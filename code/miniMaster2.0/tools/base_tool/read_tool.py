"""读取文件内容的基础工具。"""

import os

from tools.core import BaseTool, ToolResult, ToolSpec


class ReadTool(BaseTool):
    """默认按行分段读取，也支持显式指定行范围。"""
    DEFAULT_CHUNK_SIZE = 200

    spec = ToolSpec(
        name="read",
        description="读取文件内容，默认按行分段返回，并以当前工作目录为基准解析相对路径。",
        category="base",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "chunk_size": {"type": "integer", "default": 200},
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    )

    def run(self, tool_input: dict) -> ToolResult:
        """读取指定文件；若未指定完整范围，则默认返回一个分段。

        这里会先把相对路径解析到 workspace，再检查文件是否存在并执行读取。
        这样模型在调用 `read` 时，无论当前进程从哪里启动，都能稳定读取到
        预期目录中的文件。
        """
        file_path = str(tool_input["file_path"])
        start_line = tool_input.get("start_line")
        end_line = tool_input.get("end_line")
        chunk_size = int(tool_input.get("chunk_size", self.DEFAULT_CHUNK_SIZE))
        resolved_path = self.resolve_path(file_path)

        if chunk_size <= 0:
            return ToolResult(success=False, data={"content": ""}, error="chunk_size must be greater than 0")

        if not os.path.exists(resolved_path):
            return ToolResult(success=False, data={"content": ""}, error=f"File not found: {file_path}")

        if not os.path.isfile(resolved_path):
            return ToolResult(success=False, data={"content": ""}, error=f"Not a file: {file_path}")

        total_lines = self._count_lines(resolved_path)

        if total_lines == 0:
            return ToolResult(
                success=True,
                data={
                    "content": "",
                    "total_lines": 0,
                    "start_line": 0,
                    "end_line": 0,
                    "has_more": False,
                    "next_start_line": None,
                },
            )

        normalized_start_line = max(1, int(start_line) if start_line is not None else 1)
        if normalized_start_line > total_lines:
            return ToolResult(
                success=False,
                data={"content": "", "total_lines": total_lines},
                error=f"start_line {normalized_start_line} is greater than total_lines {total_lines}",
            )

        if end_line is not None:
            normalized_end_line = int(end_line)
        elif start_line is not None:
            normalized_end_line = normalized_start_line + chunk_size - 1
        else:
            normalized_end_line = chunk_size

        if normalized_end_line < normalized_start_line:
            return ToolResult(
                success=False,
                data={"content": "", "total_lines": total_lines},
                error="end_line must be greater than or equal to start_line",
            )

        normalized_end_line = min(total_lines, normalized_end_line)
        content = self._read_line_range(resolved_path, normalized_start_line, normalized_end_line)
        has_more = normalized_end_line < total_lines

        return ToolResult(
            success=True,
            data={
                "content": content,
                "total_lines": total_lines,
                "start_line": normalized_start_line,
                "end_line": normalized_end_line,
                "has_more": has_more,
                "next_start_line": normalized_end_line + 1 if has_more else None,
            },
        )

    def _count_lines(self, file_path: str) -> int:
        """先统计总行数，便于后续按稳定范围分段读取。"""
        with open(file_path, "r", encoding="utf-8") as file_obj:
            return sum(1 for _ in file_obj)

    def _read_line_range(self, file_path: str, start_line: int, end_line: int) -> str:
        """按 1-based 行号范围惰性读取文件内容。"""
        collected_lines = []
        with open(file_path, "r", encoding="utf-8") as file_obj:
            for line_number, line in enumerate(file_obj, 1):
                if line_number < start_line:
                    continue
                if line_number > end_line:
                    break
                collected_lines.append(line)
        return "".join(collected_lines)
