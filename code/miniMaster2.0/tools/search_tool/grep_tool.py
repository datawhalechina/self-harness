"""基于正则表达式的文本搜索工具。"""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import re
import shutil
import subprocess

from tools.core.base import BaseTool
from tools.core.types import ToolResult, ToolSpec


class GrepTool(BaseTool):
    """在文件或目录树中搜索文本，优先复用 ripgrep 的忽略规则。"""
    DEFAULT_CHUNK_SIZE = 200
    IGNORE_FILE_NAMES = (".gitignore", ".ignore", ".rgignore")

    spec = ToolSpec(
        name="grep",
        description=(
            "在文件或目录中按正则搜索文本内容，默认以当前工作目录为起点；"
            "若系统已安装 rg，则会自动遵循 .gitignore/.ignore/.rgignore 等忽略规则。"
        ),
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
        """搜索文本模式；若可用，优先走 rg 后端以复用 ignore 规则。

        设计成“两级后端”是这个工具最关键的教学点：
        - 有 rg 时：优先获得更快速度和更接近开发者习惯的 ignore 语义
        - 没 rg 时：仍能用 Python 保底，保证项目可运行
        """
        # 正则模式本身。
        pattern = str(tool_input["pattern"])
        # 搜索起点；默认是当前 workspace。
        path = str(tool_input.get("path", "."))
        # 可选的文件名过滤条件，例如 `*.py`。
        include_pattern = tool_input.get("include_pattern")
        # 是否区分大小写。
        case_sensitive = tool_input.get("case_sensitive", False)
        # 是否递归搜索子目录。
        recursive = tool_input.get("recursive", True)
        # 最多返回多少条命中。
        max_results = int(tool_input.get("max_results", 40))
        # Python 回退实现里按多少行一个块去扫描。
        chunk_size = int(tool_input.get("chunk_size", self.DEFAULT_CHUNK_SIZE))
        # 把相对路径解析成稳定绝对路径。
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

        # 优先尝试 rg 后端。
        rg_result = self._run_with_ripgrep(
            pattern=pattern,
            resolved_path=resolved_path,
            include_pattern=include_pattern,
            case_sensitive=case_sensitive,
            recursive=recursive,
            max_results=max_results,
        )
        if rg_result is not None:
            return rg_result

        # rg 不可用时，走纯 Python 保底实现。
        return self._run_with_python(
            pattern=pattern,
            path=path,
            resolved_path=resolved_path,
            include_pattern=include_pattern,
            case_sensitive=case_sensitive,
            recursive=recursive,
            max_results=max_results,
            chunk_size=chunk_size,
        )

    def _run_with_ripgrep(
        self,
        *,
        pattern: str,
        resolved_path: str,
        include_pattern,
        case_sensitive: bool,
        recursive: bool,
        max_results: int,
    ) -> ToolResult | None:
        """若 rg 可用，则优先用它执行搜索并继承 ignore 规则。"""
        # 只有系统里真的安装了 rg，才能走高性能后端。
        rg_path = shutil.which("rg")
        if not rg_path:
            return None

        if not os.path.exists(resolved_path):
            return ToolResult(
                success=False,
                data={"matches": [], "total_matches": 0, "files_searched": 0},
                error=f"Path not found: {path}",
            )

        # `--json` 让我们能够稳定解析结构化输出，而不是依赖文本 grep 格式。
        command = [
            rg_path,
            "--json",
            "--line-number",
            "--color",
            "never",
        ]
        command.append("--case-sensitive" if case_sensitive else "--ignore-case")

        if include_pattern:
            # rg 的 `--glob` 用于做文件名筛选。
            command.extend(["--glob", str(include_pattern)])

        if not recursive and os.path.isdir(resolved_path):
            # 非递归目录搜索时，把最大深度限制到 1。
            command.extend(["--max-depth", "1"])

        # 先追加正则模式，再追加目标路径。
        command.append(pattern)
        command.append(self._build_search_target(resolved_path))

        process = subprocess.Popen(
            command,
            cwd=self.context.workspace or os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        matches = []  # 累积的统一命中结果。
        files_started = 0  # rg 告知已经开始搜索了多少文件。
        summary_searches = None  # 结束时 summary 里给出的搜索文件数。
        terminated_early = False  # 是否因为达到 max_results 而主动提前终止。

        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    # 万一出现异常行，直接跳过，不让整次搜索失败。
                    continue

                message_type = payload.get("type")
                data = payload.get("data", {})

                if message_type == "begin":
                    # begin 事件表示 rg 开始处理一个新文件。
                    files_started += 1
                    continue

                if message_type == "summary":
                    # summary 事件通常出现在尾部，包含统计信息。
                    summary_searches = data.get("stats", {}).get("searches")
                    continue

                if message_type != "match":
                    # 这里只关心真正的 match 事件，其他事件全部忽略。
                    continue

                file_path = self._extract_rg_text(data.get("path"))
                line_number = data.get("line_number", 0)
                line_content = self._extract_rg_text(data.get("lines")).rstrip("\n\r")
                submatches = data.get("submatches", [])

                # rg 的一条 match 里可能包含多个子命中，因此这里继续展开成多条统一记录。
                for submatch in submatches:
                    matches.append(
                        {
                            "file": self.relativize_path(self._resolve_match_path(file_path)),
                            "line_number": line_number,
                            "line_content": line_content,
                            "matched_text": self._extract_rg_text(submatch.get("match")),
                        }
                    )
                    if len(matches) >= max_results:
                        # 达到上限就主动 kill 进程，避免继续浪费搜索时间。
                        terminated_early = True
                        process.kill()
                        break

                if terminated_early:
                    break
        finally:
            # `communicate()` 用来收尾并拿到 stderr，同时尽量补抓 summary。
            stdout_tail, stderr_output = process.communicate()
            if stdout_tail and summary_searches is None:
                for raw_line in stdout_tail.splitlines():
                    try:
                        payload = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("type") == "summary":
                        summary_searches = payload.get("data", {}).get("stats", {}).get("searches")
                        break

        # rg 返回码 0 表示有命中，1 表示没命中，这两种都不算失败。
        returncode = process.returncode
        if not terminated_early and returncode not in (0, 1):
            return ToolResult(
                success=False,
                data={"matches": [], "total_matches": 0, "files_searched": 0},
                error=self._normalize_rg_error(stderr_output, pattern),
            )

        # 如果拿到了 summary 统计就优先用它，否则退回 begin 事件计数。
        files_searched = summary_searches if isinstance(summary_searches, int) else files_started
        return ToolResult(
            success=True,
            data={"matches": matches, "total_matches": len(matches), "files_searched": files_searched},
        )

    def _run_with_python(
        self,
        *,
        pattern: str,
        path: str,
        resolved_path: str,
        include_pattern,
        case_sensitive: bool,
        recursive: bool,
        max_results: int,
        chunk_size: int,
    ) -> ToolResult:
        """当 rg 不可用时，回退到 Python 搜索，并尽量跳过 ignore 路径。"""
        try:
            # Python 回退实现会自己编译正则。
            flags = 0 if case_sensitive else re.IGNORECASE
            compiled_pattern = re.compile(pattern, flags)
        except re.error as exc:
            return ToolResult(
                success=False,
                data={"matches": [], "total_matches": 0, "files_searched": 0},
                error=f"Invalid regex: {exc}",
            )

        matches = []  # 收集命中结果。
        files_searched = 0  # 实际扫描过的文件数。

        if os.path.isfile(resolved_path):
            # 指向单个文件时，待搜索文件集就只有它自己。
            files_to_search = [resolved_path]
        elif os.path.isdir(resolved_path):
            # 指向目录时，需要先根据 ignore 规则和 include_pattern 收集文件。
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
                # 仍按 chunk 逐段扫，避免大文件一次性全读进内存。
                total_lines = self._count_lines(file_path)
                if total_lines == 0:
                    files_searched += 1
                    continue

                for chunk_start in range(1, total_lines + 1, chunk_size):
                    chunk_end = min(total_lines, chunk_start + chunk_size - 1)
                    for line_number, line in self._iter_line_range(file_path, chunk_start, chunk_end):
                        for match in compiled_pattern.finditer(line):
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
                # 只有完整走过该文件后，才把 files_searched +1。
                files_searched += 1
            except (PermissionError, IOError):
                # 某些文件可能无权限或读取失败，跳过即可。
                continue

        return ToolResult(
            success=True,
            data={"matches": matches, "total_matches": len(matches), "files_searched": files_searched},
        )

    def _collect_files(self, directory, include_pattern, recursive):
        """根据递归开关、include_pattern 和 ignore 规则收集待搜索文件。"""
        ignore_rules = self._load_ignore_rules()
        files = []
        if recursive:
            for root, dirnames, filenames in os.walk(directory):
                # 先原地过滤子目录，避免继续深入被忽略的路径。
                dirnames[:] = [
                    dirname
                    for dirname in dirnames
                    if not self._should_ignore_path(os.path.join(root, dirname), is_dir=True, ignore_rules=ignore_rules)
                ]
                for filename in filenames:
                    if include_pattern and not fnmatch.fnmatch(filename, include_pattern):
                        continue
                    file_path = os.path.join(root, filename)
                    if self._should_ignore_path(file_path, is_dir=False, ignore_rules=ignore_rules):
                        continue
                    files.append(file_path)
            return files

        for item in os.listdir(directory):
            # 非递归时只看当前目录这一层。
            item_path = os.path.join(directory, item)
            if self._should_ignore_path(item_path, is_dir=os.path.isdir(item_path), ignore_rules=ignore_rules):
                continue
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

    def _build_search_target(self, resolved_path: str) -> str:
        """尽量把搜索目标转成相对 workspace 的路径，方便 rg 继承 ignore 规则。"""
        workspace = os.path.abspath(self.context.workspace or os.getcwd())
        absolute_target = os.path.abspath(resolved_path)
        try:
            common_path = os.path.commonpath([workspace, absolute_target])
        except ValueError:
            return absolute_target

        if common_path != workspace:
            return absolute_target

        relative_target = os.path.relpath(absolute_target, workspace)
        return "." if relative_target == "." else relative_target

    def _resolve_match_path(self, match_path: str) -> str:
        """把 rg 返回的路径恢复成稳定绝对路径。"""
        if not match_path:
            return self.context.workspace or os.getcwd()
        if os.path.isabs(match_path):
            return os.path.abspath(match_path)
        return os.path.abspath(os.path.join(self.context.workspace or os.getcwd(), match_path))

    def _extract_rg_text(self, value) -> str:
        """从 rg JSON 输出里提取 text/bytes 字段。"""
        if isinstance(value, dict):
            if "text" in value:
                return str(value["text"])
            if "bytes" in value:
                try:
                    return base64.b64decode(value["bytes"]).decode("utf-8", errors="replace")
                except Exception:
                    return ""
        return str(value or "")

    def _normalize_rg_error(self, stderr_output: str, pattern: str) -> str:
        """统一格式化 rg 后端错误。"""
        error_text = " ".join(str(stderr_output or "").split()).strip()
        if error_text:
            return f"rg search failed: {error_text}"
        return f"rg search failed for pattern: {pattern}"

    def _load_ignore_rules(self) -> list[str]:
        """从 workspace 根目录读取简单 ignore 规则。"""
        workspace = self.context.workspace or os.getcwd()
        rules: list[str] = []
        for ignore_file_name in self.IGNORE_FILE_NAMES:
            ignore_file_path = os.path.join(workspace, ignore_file_name)
            if not os.path.isfile(ignore_file_path):
                continue
            try:
                with open(ignore_file_path, "r", encoding="utf-8", errors="ignore") as file_obj:
                    for raw_line in file_obj:
                        line = raw_line.strip()
                        if not line or line.startswith("#"):
                            continue
                        rules.append(line)
            except OSError:
                continue
        return rules

    def _should_ignore_path(self, path: str, *, is_dir: bool, ignore_rules: list[str]) -> bool:
        """判断路径是否应该在 Python 回退搜索里被忽略。"""
        workspace = os.path.abspath(self.context.workspace or os.getcwd())
        absolute_path = os.path.abspath(path)
        try:
            relative_path = os.path.relpath(absolute_path, workspace)
        except ValueError:
            return False

        normalized = relative_path.replace("\\", "/")
        if normalized == ".":
            return False

        parts = [part for part in normalized.split("/") if part]
        # 隐藏路径默认直接忽略，和大多数代码搜索习惯一致。
        if any(part.startswith(".") for part in parts):
            return True

        # ignore 规则会按顺序覆盖，后面的规则可以翻转前面的结果。
        ignored = False
        for rule in ignore_rules:
            is_negated = rule.startswith("!")
            pattern = rule[1:] if is_negated else rule
            if self._matches_ignore_rule(normalized, parts, pattern, is_dir):
                ignored = not is_negated
        return ignored

    def _matches_ignore_rule(self, normalized_path: str, parts: list[str], pattern: str, is_dir: bool) -> bool:
        """实现一组足够支撑教学示例的 ignore 规则匹配。"""
        normalized_pattern = pattern.replace("\\", "/").strip()
        if not normalized_pattern:
            return False

        directory_only = normalized_pattern.endswith("/")
        if directory_only:
            normalized_pattern = normalized_pattern.rstrip("/")
            if not normalized_pattern:
                return False

        anchored = normalized_pattern.startswith("/")
        normalized_pattern = normalized_pattern.lstrip("/")

        candidates = [normalized_path]
        if "/" not in normalized_pattern:
            candidates.extend(parts)
        else:
            segments = normalized_path.split("/")
            for index in range(len(segments)):
                candidates.append("/".join(segments[index:]))

        matched = any(fnmatch.fnmatch(candidate, normalized_pattern) for candidate in candidates)
        if not matched and not anchored and "/" in normalized_pattern:
            matched = fnmatch.fnmatch(normalized_path, f"*/{normalized_pattern}")

        if directory_only:
            if is_dir and matched:
                return True
            return any(fnmatch.fnmatch(part, normalized_pattern) for part in parts[:-1])

        return matched
