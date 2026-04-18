"""写入文件内容的基础工具。"""

import os

from tools.core.base import BaseTool
from tools.core.types import ToolResult, ToolSpec


class WriteTool(BaseTool):
    """统一封装覆盖、追加和仅创建三种写入模式。"""

    spec = ToolSpec(
        name="write",
        description="写入文件内容，默认以当前工作目录为基准解析相对路径。",
        category="base",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["overwrite", "append", "create"], "default": "overwrite"},
            },
            "required": ["file_path", "content"],
            "additionalProperties": False,
        },
    )

    def run(self, tool_input: dict) -> ToolResult:
        """根据 mode 选择写入策略，并返回写入字节数。

        写入前会先把目标路径解析到 workspace，并在需要时自动创建父目录。
        这样 Agent 可以直接写 `notes/result.md` 这类相对路径，而不用自己
        先推断进程当前目录到底落在哪。
        """
        file_path = str(tool_input["file_path"])
        content = str(tool_input["content"])
        mode = str(tool_input.get("mode", "overwrite"))
        resolved_path = self.resolve_path(file_path)
        display_path = self.relativize_path(resolved_path)

        file_exists = os.path.exists(resolved_path)

        if mode == "create" and file_exists:
            # create 模式语义是“只在不存在时创建”，因此不能覆盖已有文件。
            return ToolResult(
                success=False,
                data={"message": "", "bytes_written": 0},
                error=f"File exists: {display_path}",
            )

        directory = os.path.dirname(resolved_path)
        if directory and not os.path.exists(directory):
            # 为新文件自动创建父目录，避免调用方额外执行 mkdir。
            os.makedirs(directory, exist_ok=True)

        file_mode = "a" if mode == "append" else "w"
        with open(resolved_path, file_mode, encoding="utf-8") as file_obj:
            file_obj.write(content)

        # 按 UTF-8 编码后的字节数统计，更贴近实际落盘大小。
        bytes_written = len(content.encode("utf-8"))

        if mode == "append" and file_exists:
            message = f"Appended {bytes_written} bytes to {display_path}"
        elif file_exists:
            message = f"Overwrote {display_path} ({bytes_written} bytes)"
        else:
            message = f"Created {display_path} ({bytes_written} bytes)"

        return ToolResult(success=True, data={"message": message, "bytes_written": bytes_written})
