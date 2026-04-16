"""执行 Shell 命令的基础工具。"""

import os
import subprocess

from tools.core import BaseTool, ToolResult, ToolSpec


class BashTool(BaseTool):
    """把命令执行能力适配到统一工具协议。

    这个工具虽然名字叫 `bash`，但实际目标是提供一个“通用命令执行入口”。
    在 Windows 环境下，它会优先通过 PowerShell 执行命令；在类 Unix
    环境下，则通过 bash 执行命令。这样能尽量贴近当前平台的默认用法，
    减少模型因为套用错误命令习惯而频繁失败。
    """

    spec = ToolSpec(
        name="bash",
        description=(
            "执行命令行指令。Windows 环境下优先使用 PowerShell 风格命令；"
            "列目录可用 ls 或 Get-ChildItem，需要包含隐藏项时用 Get-ChildItem -Force。"
        ),
        category="base",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 30},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    )

    @staticmethod
    def get_command_shell_name() -> str:
        """返回当前平台下 `bash` 工具实际使用的底层命令 shell 名称。

        这个信息本质上属于 BashTool 自身的运行知识，因此应由工具层维护，
        而不是由主循环去猜测。这样无论后续底层实现改成 PowerShell、cmd、
        bash 还是其他 shell，Prompt 层都只需要读取工具给出的结论即可。
        """
        if os.name == "nt":
            return "PowerShell"
        return "bash"

    def run(self, tool_input: dict) -> ToolResult:
        """在共享工作目录中执行命令，并返回标准化结果。

        这里会先根据当前操作系统选择合适的底层 shell，再执行传入命令。
        对 Windows 下最常见的一些 Unix 风格列表命令，还会做一层轻量
        兼容转换，尽量避免因为命令习惯差异导致原本简单的任务失败。
        """
        command = str(tool_input["command"])
        timeout = int(tool_input.get("timeout", 30))
        shell_command = self._build_shell_command(command)

        try:
            result = subprocess.run(
                shell_command,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                # 所有命令都以 ToolContext.workspace 为当前目录执行，避免跑到未知位置。
                cwd=self.context.workspace,
            )
            return ToolResult(
                success=result.returncode == 0,
                data={
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                },
            )
        except subprocess.TimeoutExpired:
            # 超时被视为可恢复失败，交由上层 Agent 决定是否重试或换工具。
            return ToolResult(
                success=False,
                data={
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout}s",
                    "returncode": -1,
                },
            )

    def _build_shell_command(self, command: str) -> list[str]:
        """根据当前平台构造底层 shell 调用参数。

        Windows 使用 PowerShell，是为了让 `ls`、`dir`、`Get-ChildItem`
        这类常见命令都能按用户直觉工作；类 Unix 环境则使用 bash，
        继续保持原先“执行一段 shell 命令”的体验。
        """
        if self.get_command_shell_name() == "PowerShell":
            return ["powershell", "-NoProfile", "-Command", command]
        return ["/bin/bash", "-lc", command]
