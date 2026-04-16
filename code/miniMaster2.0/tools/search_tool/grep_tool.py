"""基于正则表达式的文本搜索工具。"""

import fnmatch
import os
import re

from tools.core import BaseTool, ToolResult, ToolSpec


class GrepTool(BaseTool):
    """在单个文件或目录树中按分段方式搜索文本模式。"""
    DEFAULT_CHUNK_SIZE = 200

    spec = ToolSpec(
        name="grep",
        description="在文件或目录中按正则搜索文本内容，默认以当前工作目录为起点。",
        category="search",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "include_pattern": {"type": "string"},
                "case_sensitive": {"type": "boolean", "default": False},
                "recursive": {"type": "boolean", "default": True},
                "max_results": {"type": "integer", "default": 40},
                "chunk_size": {"type": "integer", "default": 200},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    )

    def run(self, tool_input: dict) -> ToolResult:
        """编译正则后遍历文件，并把每个命中整理成结构化记录。

        这里会先把传入路径解析到 workspace，再决定是搜索单文件还是整个目录。
        这样 Agent 在不同工具之间切换时，对相对路径的理解能够保持一致。
        """
        pattern = str(tool_input["pattern"])
        path = str(tool_input.get("path", "."))
        include_pattern = tool_input.get("include_pattern")
        case_sensitive = tool_input.get("case_sensitive", False)
        recursive = tool_input.get("recursive", True)
        max_results = int(tool_input.get("max_results", 40))
        chunk_size = int(tool_input.get("chunk_size", self.DEFAULT_CHUNK_SIZE))
        resolved_path = self.resolve_path(path)

        if max_results <= 0:
            return ToolResult(
                success=False,
                data={"matches": [], "total_matches": 0, "files_searched": 0},
                error="max_results must be greater than 0",
            )

        if chunk_size <= 0:
            return ToolResult(
                success=False,
                data={"matches": [], "total_matches": 0, "files_searched": 0},
                error="chunk_size must be greater than 0",
            )

        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            compiled_pattern = re.compile(pattern, flags)
        except re.error as exc:
            # 非法正则不抛异常到框架外，而是作为普通失败结果返回给 Agent。
            return ToolResult(
                success=False,
                data={"matches": [], "total_matches": 0, "files_searched": 0},
                error=f"Invalid regex: {exc}",
            )

        matches = []
        files_searched = 0

        if os.path.isfile(resolved_path):
            files_to_search = [resolved_path]
        elif os.path.isdir(resolved_path):
            files_to_search = self._collect_files(resolved_path, include_pattern, recursive)
        else:
            return ToolResult(
                success=False,
                data={"matches": [], "total_matches": 0, "files_searched": 0},
                error=f"Path not found: {path}",
            )

        for file_path in files_to_search:
            if len(matches) >= max_results:
                break
            try:
                total_lines = self._count_lines(file_path)
                if total_lines == 0:
                    files_searched += 1
                    continue

                for chunk_start in range(1, total_lines + 1, chunk_size):
                    chunk_end = min(total_lines, chunk_start + chunk_size - 1)
                    for line_number, line in self._iter_line_range(file_path, chunk_start, chunk_end):
                        for match in compiled_pattern.finditer(line):
                            # 保留文件、行号、整行文本和实际命中文本，便于后续推理或定位。
                            matches.append(
                                {
                                    "file": self.relativize_path(file_path),
                                    "line_number": line_number,
                                    "line_content": line.rstrip("\n\r"),
                                    "matched_text": match.group(),
                                }
                            )
                            if len(matches) >= max_results:
                                break
                        if len(matches) >= max_results:
                            break
                    if len(matches) >= max_results:
                        break
                files_searched += 1
            except (PermissionError, IOError):
                # 对不可读文件直接跳过，避免一次权限问题终止整个搜索。
                continue

        return ToolResult(
            success=True,
            data={"matches": matches, "total_matches": len(matches), "files_searched": files_searched},
        )

    def _collect_files(self, directory, include_pattern, recursive):
        """根据递归开关和文件名过滤模式收集待搜索文件列表。"""
        files = []
        if recursive:
            for root, _, filenames in os.walk(directory):
                for filename in filenames:
                    if include_pattern and not fnmatch.fnmatch(filename, include_pattern):
                        continue
                    files.append(os.path.join(root, filename))
            return files

        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if not os.path.isfile(item_path):
                continue
            if include_pattern and not fnmatch.fnmatch(item, include_pattern):
                continue
            files.append(item_path)
        return files

    def _count_lines(self, file_path: str) -> int:
        """先统计文件总行数，再按块扫描，避免一次性把全文装入内存。"""
        with open(file_path, "r", encoding="utf-8", errors="ignore") as file_obj:
            return sum(1 for _ in file_obj)

    def _iter_line_range(self, file_path: str, start_line: int, end_line: int):
        """按 1-based 行号范围惰性返回文件片段。"""
        with open(file_path, "r", encoding="utf-8", errors="ignore") as file_obj:
            for line_number, line in enumerate(file_obj, 1):
                if line_number < start_line:
                    continue
                if line_number > end_line:
                    break
                yield line_number, line
