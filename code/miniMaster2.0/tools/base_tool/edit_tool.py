"""基于整文件文本替换的编辑工具。"""

import os

from tools.core.base import BaseTool
from tools.core.types import ToolResult, ToolSpec


class EditTool(BaseTool):
    """按 replacement 列表顺序修改文件内容。"""

    spec = ToolSpec(
        name="edit",
        description="按文本替换规则修改文件内容，默认以当前工作目录为基准解析相对路径。",
        category="base",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "replacements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "original_text": {"type": "string"},
                            "new_text": {"type": "string"},
                            "replace_all": {"type": "boolean", "default": False},
                        },
                        "required": ["original_text", "new_text"],
                    },
                },
            },
            "required": ["file_path", "replacements"],
            "additionalProperties": False,
        },
    )

    def run(self, tool_input: dict) -> ToolResult:
        """先读完整文件，再依次执行替换并一次性回写。

        这里同样会先把相对路径解析到 workspace，保证编辑操作和读取、
        搜索、写入工具对同一个相对路径指向同一个文件，不会因为启动目录
        不同而改错位置。
        """
        file_path = str(tool_input["file_path"])
        replacements = tool_input["replacements"]
        resolved_path = self.resolve_path(file_path)

        if not os.path.exists(resolved_path):
            return ToolResult(
                success=False,
                data={"message": "", "replacements_made": 0},
                error=f"File not found: {file_path}",
            )

        with open(resolved_path, "r", encoding="utf-8") as file_obj:
            content = file_obj.read()

        original_content = content
        total_replacements = 0

        # 替换是顺序执行的：后一个 replacement 会基于前一个 replacement 的结果继续处理。
        for replacement in replacements:
            original_text = replacement.get("original_text", "")
            new_text = replacement.get("new_text", "")
            replace_all = replacement.get("replace_all", False)

            if not original_text:
                continue

            if replace_all:
                # replace_all=True 时统计并替换全部命中项，便于调用方确认修改规模。
                count = content.count(original_text)
                content = content.replace(original_text, new_text)
                total_replacements += count
            elif original_text in content:
                # 默认只替换第一处命中，降低误改风险。
                content = content.replace(original_text, new_text, 1)
                total_replacements += 1

        if content == original_content:
            # 未发生任何改动时仍返回 success=True，表示工具运行成功但内容保持不变。
            return ToolResult(success=True, data={"message": "No changes made", "replacements_made": 0})

        with open(resolved_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(content)

        return ToolResult(
            success=True,
            data={"message": f"Edited {file_path}", "replacements_made": total_replacements},
        )
