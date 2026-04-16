"""按 glob 模式查找文件和目录。"""

import glob as glob_module
import os

from tools.core import BaseTool, ToolResult, ToolSpec


class GlobTool(BaseTool):
    """封装 glob 搜索，并把文件与目录分别返回。"""

    spec = ToolSpec(
        name="glob",
        description="按通配符模式查找文件和目录，默认以当前工作目录为起点。",
        category="search",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "recursive": {"type": "boolean", "default": True},
                "include_hidden": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "default": 1000},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    )

    def run(self, tool_input: dict) -> ToolResult:
        """执行 glob 匹配，并根据是否隐藏文件进行二次过滤。

        相对模式会统一基于 workspace 解析，这样模型在不同工具之间使用
        `.`、`*`、`src/**/*.py` 这类写法时，看到的都是同一个“当前目录”。
        返回结果时再尽量转回相对路径，便于模型继续阅读和总结。
        """
        pattern = str(tool_input["pattern"])
        recursive = tool_input.get("recursive", True)
        include_hidden = tool_input.get("include_hidden", False)
        max_results = int(tool_input.get("max_results", 1000))
        resolved_pattern = self.resolve_path(pattern)

        matches = glob_module.glob(resolved_pattern, recursive=recursive)
        matches.sort()
        # 先限制总结果数，避免模型一次拿到过长列表。
        matches = matches[:max_results]

        files = []
        directories = []

        for match in matches:
            if not include_hidden:
                # glob 本身对隐藏路径控制有限，这里按路径片段再做一次过滤。
                parts = match.split(os.sep)
                if any(part.startswith(".") and part not in [".", ".."] for part in parts):
                    continue

            if os.path.isfile(match):
                files.append(self.relativize_path(match))
            elif os.path.isdir(match):
                directories.append(self.relativize_path(match))

        return ToolResult(
            success=True,
            data={
                "files": files,
                "directories": directories,
                "total_files": len(files),
                "total_directories": len(directories),
            },
        )
