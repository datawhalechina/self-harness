# miniMaster：最小化 Claude Code Skills 实现

## 6.1 项目概述

miniMaster 是一个最小化的 Claude Code Skills 实现，展示了如何构建一个基于技能（Skills）系统的 AI Agent 框架。通过这个项目，你将理解上下文工程的核心实践：**动态调度**和**按需加载**。

### 核心特性

- ✅ **技能系统**：支持模块化技能（PDF、DOCX、PPTX、XLSX 处理）
- ✅ **工具扩展**：Read、Bash、Write 三个基础工具
- ✅ **安全沙箱**：文件系统访问限制、命令超时保护
- ✅ **透明执行**：完整的思考过程和工具调用日志
- ✅ **容错机制**：API 请求自动重试、异常捕获

### 项目结构

```
code/miniMaster/
├── agent/              # Agent 核心逻辑
│   ├── loop.py        # 执行循环引擎
│   └── prompts.py     # System Prompt 构建
├── tools/             # 工具系统
│   ├── bash.py       # Bash 命令执行
│   ├── read.py       # 文件读取
│   └── write.py      # 文件写入
├── runtime/           # 运行时环境
│   ├── filesystem.py  # 文件系统管理
│   └── subprocess_runner.py  # 子进程运行器
├── skills/            # 技能系统
│   ├── discovery.py   # 技能发现
│   ├── registry.py    # 技能注册表
│   ├── parser.py      # 技能解析器
│   └── catalog.py     # 技能目录渲染
├── config.py          # 配置管理
├── app.py            # 应用组装
├── cli.py            # 命令行接口
└── .claude/skills/   # 技能定义目录
```

---

## 6.2 配置系统

### 6.2.1 环境变量配置

首先创建 `.env` 文件配置 API 参数：

```bash
# .env
MCC_API_BASE="https://api.deepseek.com"
MCC_API_KEY="sk-your-api-key"
MCC_MODEL_NAME="deepseek-chat"
```

### 6.2.2 配置类实现

**文件：`config.py`**

```python
from __future__ import annotations
from dotenv import load_dotenv
load_dotenv()
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    """应用配置数据类"""
    project_dir: Path          # 项目根目录
    home_dir: Path            # 用户主目录
    api_base: str             # API 基础地址
    api_key: str              # API 密钥
    model_name: str           # 模型名称
    max_steps: int = 12       # 最大执行步数
    bash_timeout_sec: int = 20  # Bash 超时时间（秒）
    read_max_bytes: int = 120_000  # 最大读取字节数

    @classmethod
    def from_env(cls) -> "AppConfig":
        """从环境变量加载配置"""
        return cls(
            project_dir=Path(os.getenv("MCC_PROJECT_DIR", os.getcwd())).resolve(),
            home_dir=Path(os.getenv("MCC_HOME_DIR", str(Path.home()))).expanduser().resolve(),
            api_base=os.getenv("MCC_API_BASE", "https://api.openai.com/v1"),
            api_key=os.getenv("MCC_API_KEY", ""),
            model_name=os.getenv("MCC_MODEL_NAME", "gpt-4.1-mini"),
            max_steps=int(os.getenv("MCC_MAX_STEPS", "8")),
            bash_timeout_sec=int(os.getenv("MCC_BASH_TIMEOUT_SEC", "20")),
            read_max_bytes=int(os.getenv("MCC_READ_MAX_BYTES", "120000")),
        )

    def skill_roots(self) -> list[Path]:
        """返回所有技能根目录"""
        return [
            self.project_dir / ".claude" / "skills",
            self.project_dir / ".agents" / "skills",
            self.home_dir / ".claude" / "skills",
            self.home_dir / ".agents" / "skills",
        ]

    def allowed_roots(self) -> list[Path]:
        """返回允许访问的路径根目录（用于安全限制）"""
        roots = [self.project_dir]
        roots.extend(self.skill_roots())
        out: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root.resolve())
            if key not in seen:
                seen.add(key)
                out.append(root.resolve())
        return out
```

**代码解释**：

1. **使用 `dataclass`**：简化配置类的定义，自动生成构造函数
2. **环境变量优先级**：支持通过环境变量覆盖默认值
3. **路径安全处理**：
   - 使用 `resolve()` 转换为绝对路径
   - 使用 `expanduser()` 展开 `~` 符号
4. **多技能源支持**：可以从项目和用户主目录同时加载技能

---

## 6.3 运行时环境

### 6.3.1 文件系统管理

**文件：`runtime/filesystem.py`**

```python
from __future__ import annotations
from pathlib import Path


class FilesystemError(ValueError):
    """文件系统操作异常"""
    pass


class Filesystem:
    """安全的文件系统访问层"""
    
    def __init__(self, project_dir: Path, allowed_roots: list[Path], 
                 read_max_bytes: int = 120_000) -> None:
        self.project_dir = project_dir.resolve()
        self.allowed_roots = [p.resolve() for p in allowed_roots]
        self.read_max_bytes = read_max_bytes

    def _is_allowed(self, path: Path) -> bool:
        """检查路径是否在允许的范围内"""
        path = path.resolve()
        for root in self.allowed_roots:
            # 检查路径是否是某个根目录或其子目录
            if path == root or root in path.parents:
                return True
        return False

    def resolve_path(self, raw_path: str) -> Path:
        """解析并验证路径"""
        path = Path(raw_path).expanduser()
        
        # 相对路径基于项目目录解析
        if not path.is_absolute():
            path = (self.project_dir / path).resolve()
        else:
            path = path.resolve()

        # 安全检查
        if not self._is_allowed(path):
            raise FilesystemError(f"path not allowed: {path}")

        return path

    def read_text(self, raw_path: str) -> dict:
        """读取文件内容"""
        path = self.resolve_path(raw_path)
        
        if not path.exists():
            raise FilesystemError(f"file not found: {path}")
        if not path.is_file():
            raise FilesystemError(f"not a file: {path}")

        raw = path.read_bytes()
        truncated = len(raw) > self.read_max_bytes
        
        # 如果文件过大，截断读取
        if truncated:
            raw = raw[: self.read_max_bytes]

        return {
            "path": str(path),
            "content": raw.decode("utf-8", errors="replace"),
            "truncated": truncated,
        }
```

**关键点**：

- **白名单机制**：只允许访问特定目录下的文件
- **防止路径遍历攻击**：通过 `resolve()` 规范化路径
- **大文件保护**：限制最大读取大小，防止内存溢出

### 6.3.2 子进程运行器

**文件：`runtime/subprocess_runner.py`**

```python
from __future__ import annotations
import os
import subprocess
from pathlib import Path
from .filesystem import Filesystem


class SubprocessRunner:
    """安全的子进程执行器"""
    
    def __init__(self, fs: Filesystem, timeout_sec: int = 20) -> None:
        self.fs = fs
        self.timeout_sec = timeout_sec

    def run(self, command: str, cwd: str | None = None) -> dict:
        """执行 shell 命令"""
        # 确定工作目录
        workdir = self.fs.project_dir if cwd is None else self.fs.resolve_path(cwd)
        
        if not workdir.is_dir():
            raise ValueError(f"cwd is not a directory: {workdir}")

        # 最小化环境变量（安全隔离）
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(Path.home()),
            "PYTHONUNBUFFERED": "1",
        }

        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(workdir),
                env=env,
                text=True,
                capture_output=True,
                timeout=self.timeout_sec,
                stdin=subprocess.DEVNULL,
            )
            return {
                "command": command,
                "cwd": str(workdir),
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as exc:
            # 超时处理
            return {
                "command": command,
                "cwd": str(workdir),
                "exit_code": None,
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "timed_out": True,
            }
```

**安全特性**：

1. **环境变量隔离**：只传递必要的环境变量
2. **超时保护**：防止无限循环或长时间运行的命令
3. **工作目录限制**：只能在允许的目录内执行

---

## 6.4 工具系统

### 6.4.1 Read 工具

**文件：`tools/read.py`**

```python
from __future__ import annotations
import json
from runtime.filesystem import Filesystem


class ReadTool:
    """读取文本文件的工具"""
    name = "Read"
    description = "Read a text file."

    def __init__(self, fs: Filesystem) -> None:
        self.fs = fs

    def prompt_block(self) -> str:
        """生成工具的提示块（用于告诉 LLM 如何使用）"""
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"],
            "additionalProperties": False,
        }
        return f"- {self.name}: {self.description}\n  Input schema: {json.dumps(schema, ensure_ascii=False)}"

    def run(self, tool_input: dict) -> dict:
        """执行读取操作"""
        return self.fs.read_text(str(tool_input["path"]))
```

### 6.4.2 Bash 工具

**文件：`tools/bash.py`**

```python
from __future__ import annotations
import json
from runtime.subprocess_runner import SubprocessRunner


class BashTool:
    """执行 shell 命令的工具"""
    name = "Bash"
    description = "Run a shell command."

    def __init__(self, runner: SubprocessRunner) -> None:
        self.runner = runner

    def prompt_block(self) -> str:
        schema = {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
            },
            "required": ["command"],
            "additionalProperties": False,
        }
        return f"- {self.name}: {self.description}\n  Input schema: {json.dumps(schema, ensure_ascii=False)}"

    def run(self, tool_input: dict) -> dict:
        return self.runner.run(
            command=str(tool_input["command"]),
            cwd=str(tool_input["cwd"]) if "cwd" in tool_input and tool_input["cwd"] else None,
        )
```

### 6.4.3 Write 工具

**文件：`tools/write.py`**

```python
from __future__ import annotations
import json
from pathlib import Path


class WriteTool:
    """写入文件的工具"""
    name = "Write"
    description = "Write content to a file. ALWAYS use this instead of using Bash with echo/cat."

    def __init__(self, fs: Filesystem) -> None:
        self.fs = fs

    def prompt_block(self) -> str:
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to write to"},
                "content": {"type": "string", "description": "The complete text content to write"}
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }
        return f"- {self.name}: {self.description}\n  Input schema: {json.dumps(schema, ensure_ascii=False)}"

    def run(self, tool_input: dict) -> dict:
        path = Path(tool_input["path"]).resolve()
        content = str(tool_input["content"])

        # 自动创建不存在的父目录
        path.parent.mkdir(parents=True, exist_ok=True)
        # 写入文件
        path.write_text(content, encoding="utf-8")

        return {"status": f"Successfully wrote {len(content)} characters to {path}"}
```

**工具设计原则**：

1. **Token 高效**：使用 JSON Schema 清晰描述输入格式
2. **功能单一**：每个工具只做一件事
3. **错误处理**：异常在运行时捕获并返回给 LLM

---

## 6.5 技能系统

### 6.5.1 技能发现

**文件：`skills/discovery.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiscoveredSkill:
    """发现的技能信息"""
    skill_dir: Path        # 技能目录
    skill_md_path: Path    # SKILL.md 文件路径
    source_root: Path      # 来源根目录


def discover_skills(skill_roots: list[Path]) -> list[DiscoveredSkill]:
    """扫描所有技能根目录，发现有效的技能"""
    found: list[DiscoveredSkill] = []

    for root in skill_roots:
        root = root.resolve()
        if not root.exists() or not root.is_dir():
            continue

        # 遍历一级子目录
        for child in sorted(root.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            
            # 检查是否存在 SKILL.md
            skill_md = child / "SKILL.md"
            if skill_md.is_file():
                found.append(
                    DiscoveredSkill(
                        skill_dir=child.resolve(),
                        skill_md_path=skill_md.resolve(),
                        source_root=root,
                    )
                )

    return found
```

### 6.5.2 技能解析器

**文件：`skills/parser.py`**

```python
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
import yaml


# 匹配 YAML frontmatter 和内容
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
# 验证技能名称格式（小写字母、数字、连字符）
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillParseError(ValueError):
    """技能解析异常"""
    pass


@dataclass
class ParsedSkill:
    """解析后的技能信息"""
    name: str              # 技能名称
    description: str       # 技能描述
    body: str             # 技能正文内容
    skill_dir: Path       # 技能目录
    skill_md_path: Path   # SKILL.md 路径
    raw_text: str         # 完整原始文本


def parse_skill_file(skill_md_path: Path) -> ParsedSkill:
    """解析 SKILL.md 文件"""
    skill_md_path = skill_md_path.resolve()

    if skill_md_path.name != "SKILL.md":
        raise SkillParseError(f"not a SKILL.md file: {skill_md_path}")

    raw_text = skill_md_path.read_text(encoding="utf-8", errors="replace")
    
    # 解析 frontmatter
    match = _FRONTMATTER_RE.match(raw_text)
    if not match:
        raise SkillParseError(f"{skill_md_path} missing YAML frontmatter")

    frontmatter_text, body = match.group(1), match.group(2)

    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"invalid YAML frontmatter: {exc}") from exc

    if not isinstance(frontmatter, dict):
        raise SkillParseError("frontmatter must be a mapping")

    # 提取必需字段
    name = str(frontmatter.get("name", "")).strip()
    description = str(frontmatter.get("description", "")).strip()

    if not name:
        raise SkillParseError("missing required field: name")
    if not description:
        raise SkillParseError("missing required field: description")

    # 验证名称格式
    if not _NAME_RE.match(name):
        raise SkillParseError(
            f"invalid skill name '{name}': only lowercase letters, numbers, and hyphens allowed"
        )

    return ParsedSkill(
        name=name,
        description=description,
        body=body.lstrip("\n"),
        skill_dir=skill_md_path.parent,
        skill_md_path=skill_md_path,
        raw_text=raw_text,
    )
```

**SKILL.md 文件格式示例**：

```markdown
---
name: pdf
description: Use this skill whenever the user wants to do anything with PDF files
license: Proprietary. LICENSE.txt has complete terms
---

# PDF Processing Guide

## Overview
This guide covers essential PDF processing operations...

## Quick Start
```python
from pypdf import PdfReader, PdfWriter
# ...
```
```

### 6.5.3 技能注册表

**文件：`skills/registry.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .discovery import DiscoveredSkill
from .parser import SkillParseError, parse_skill_file


@dataclass
class SkillRecord:
    """技能记录"""
    name: str
    description: str
    location: Path
    skill_dir: Path


class SkillRegistry:
    """技能注册表"""
    
    def __init__(self, skills: dict[str, SkillRecord], warnings: list[str]) -> None:
        self._skills = skills
        self.warnings = warnings

    @classmethod
    def build(cls, discovered: list[DiscoveredSkill]) -> "SkillRegistry":
        """从发现的技能构建注册表"""
        skills: dict[str, SkillRecord] = {}
        warnings: list[str] = []

        for item in discovered:
            try:
                parsed = parse_skill_file(item.skill_md_path)
            except SkillParseError as exc:
                # 解析失败的技能跳过并记录警告
                warnings.append(f"skip {item.skill_md_path}: {exc}")
                continue

            record = SkillRecord(
                name=parsed.name,
                description=parsed.description,
                location=parsed.skill_md_path,
                skill_dir=parsed.skill_dir,
            )

            # 极简冲突规则：后发现的忽略
            if record.name in skills:
                warnings.append(
                    f"duplicate skill name '{record.name}', ignore {record.location}"
                )
                continue

            skills[record.name] = record

        return cls(skills, warnings)

    def get(self, name: str) -> SkillRecord | None:
        """获取指定名称的技能"""
        return self._skills.get(name)

    def all(self) -> list[SkillRecord]:
        """获取所有技能（按名称排序）"""
        return sorted(self._skills.values(), key=lambda x: x.name)

    def names(self) -> list[str]:
        """获取所有技能名称"""
        return [s.name for s in self.all()]
```

### 6.5.4 技能目录渲染

**文件：`skills/catalog.py`**

```python
from __future__ import annotations
from xml.sax.saxutils import escape
from .registry import SkillRegistry


def render_skill_catalog(registry: SkillRegistry) -> str:
    """渲染技能目录为 XML 格式"""
    skills = registry.all()
    if not skills:
        return ""

    lines = ["<available_skills>"]
    for skill in skills:
        lines.extend(
            [
                "  <skill>",
                f"    <name>{escape(skill.name)}</name>",
                f"    <description>{escape(skill.description)}</description>",
                f"    <location>{escape(str(skill.location))}</location>",
                "  </skill>",
            ]
        )
    lines.append("</available_skills>")
    return "\n".join(lines)
```

**为什么使用 XML？**

- 结构清晰，易于 LLM 解析
- 可以嵌套复杂信息
- 与 Markdown 正文区分明显

---

## 6.6 Agent 核心

### 6.6.1 System Prompt 构建

**文件：`agent/prompts.py`**

```python
from __future__ import annotations
from skills.catalog import render_skill_catalog
from skills.registry import SkillRegistry


def build_system_prompt(registry: SkillRegistry, tools_text: str) -> str:
    """构建完整的 System Prompt"""
    parts: list[str] = []

    # 1. 核心指令
    parts.append(
        (
            "You are a minimal coding agent with Agent Skills support.\n"
            "You must respond with exactly one JSON object and nothing else.\n\n"
            "Allowed output shapes:\n"
            '{"thought": "reasoning...", "type":"tool_call","tool":"Read|Bash","input":{...}}\n'
            '{"thought": "ready to answer...", "type":"final","content":"..."}\n\n'
            "Rules:\n"
            "1. Always use 'thought' field to explicitly plan steps before action.\n"
            "2. If task requires multiple steps, plan the sequence in 'thought'.\n"
            "3. If task matches a skill description, use Read to load that skill's SKILL.md first.\n"
            "4. Prefer Read for loading skill files and references.\n"
            "5. Use Bash only when execution is actually needed.\n"
            "6. When a skill references relative paths, resolve them relative to skill directory.\n"
            "7. Never output markdown outside of JSON. Only output valid JSON."
        )
    )

    # 2. 可用工具
    parts.append("Available tools:\n" + tools_text)

    # 3. 可用技能目录
    catalog = render_skill_catalog(registry)
    if catalog:
        parts.append("Available skills:\n" + catalog)

    return "\n\n".join(parts)
```

**System Prompt 设计哲学**：

1. **明确输出格式**：强制 JSON，避免解析歧义
2. **强制思考**：要求先输出 `thought` 字段，提高可解释性
3. **渐进式披露**：技能和工具按需加载，避免上下文爆炸

### 6.6.2 Agent 执行循环

**文件：`agent/loop.py`**

```python
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Protocol
from skills.registry import SkillRecord, SkillRegistry


class ModelClient(Protocol):
    """模型客户端协议"""
    def complete(self, system_prompt: str, messages: list[dict[str, str]]) -> str: ...


class Tool(Protocol):
    """工具协议"""
    name: str
    def run(self, tool_input: dict) -> dict: ...


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class AgentLoop:
    """Agent 执行引擎"""
    
    def __init__(
        self,
        model_client: ModelClient,
        registry: SkillRegistry,
        tools: dict[str, Tool],
        system_prompt: str,
        max_steps: int = 8,
    ) -> None:
        self.model_client = model_client
        self.registry = registry
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.messages: list[dict[str, str]] = []

    def run_turn(self, user_text: str) -> str:
        """执行一轮对话"""
        # 1. 拦截并解析所有的 /skill 命令
        activated_skills, rest = self._intercept_slash_skills(user_text)

        # 2. 将激活的技能注入 System Prompt
        for skill in activated_skills:
            skill_text = Path(skill.location).read_text(encoding="utf-8", errors="replace")
            self.messages.append(
                {
                    "role": "system",
                    "content": (
                        f"<activated_skill name=\"{skill.name}\">\n"
                        f"{skill_text}\n"
                        f"</activated_skill>"
                    ),
                }
            )

        # 如果只有 /skill 命令，返回激活的技能名称
        if activated_skills and not rest:
            names = ", ".join(s.name for s in activated_skills)
            return f"Activated skills: {names}"

        # 添加用户消息
        if rest:
            self.messages.append({"role": "user", "content": rest})

        # 3. 执行循环
        for _ in range(self.max_steps):
            # 调用模型
            raw = self.model_client.complete(self.system_prompt, self.messages)
            action = self._parse_json(raw)

            # 打印思考过程
            print("-" * 40)
            if "thought" in action:
                print(f"🤔 [思考]: {action['thought']}")

            # 判断动作类型
            if action["type"] == "final":
                answer = str(action["content"])
                self.messages.append({"role": "assistant", "content": answer})
                return answer

            if action["type"] != "tool_call":
                raise ValueError(f"unknown action type: {action['type']}")

            # 执行工具
            tool_name = str(action["tool"])
            tool_input = action.get("input", {})

            print(f"🛠️  [调用工具]: {tool_name}")
            print(f"📦 [工具参数]: {json.dumps(tool_input, ensure_ascii=False)}")

            if tool_name not in self.tools:
                result = {"ok": False, "error": f"unknown tool: {tool_name}"}
            else:
                try:
                    tool_result = self.tools[tool_name].run(tool_input)
                    result = {"ok": True, "result": tool_result}
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}

            # 记录对话历史
            self.messages.append({"role": "assistant", "content": raw})
            self.messages.append(
                {
                    "role": "user",
                    "content": (
                        f"<tool_result name=\"{tool_name}\">\n"
                        f"{json.dumps(result, ensure_ascii=False, indent=2)}\n"
                        f"</tool_result>\n"
                        "Continue."
                    ),
                }
            )

        raise RuntimeError("max_steps exceeded")

    def _intercept_slash_skills(self, text: str) -> tuple[list[SkillRecord], str]:
        """解析 /skill 命令"""
        words = text.strip().split()
        skills_found: list[SkillRecord] = []
        rest_words: list[str] = []

        parsing_skills = True
        for word in words:
            if parsing_skills and word.startswith("/"):
                name = word[1:].strip()
                skill = self.registry.get(name)
                if skill:
                    skills_found.append(skill)
                else:
                    # 找不到的技能当成普通文本
                    rest_words.append(word)
                    parsing_skills = False
            else:
                rest_words.append(word)
                parsing_skills = False

        return skills_found, " ".join(rest_words)

    def _parse_json(self, text: str) -> dict:
        """解析 JSON 响应"""
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取 JSON 片段
            match = _JSON_RE.search(text)
            if not match:
                raise ValueError(f"model did not return valid JSON: {text}")
            return json.loads(match.group(0))
```

**执行流程详解**：

```
用户输入 → 拦截/skill 命令 → 注入技能内容 → 添加到消息列表
                                    ↓
        ← 达到最大步数？← 记录结果 ← 执行工具 ← 调用模型 ← 构建上下文
                                    ↓
                              返回最终答案
```

---

## 6.7 应用组装

### 6.7.1 模型客户端

**文件：`app.py`（部分）**

```python
import time
import requests


class OpenAICompatibleModelClient:
    """兼容 OpenAI 接口的模型客户端"""
    
    def __init__(self, api_base: str, api_key: str, model_name: str) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name

    def complete(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model_name,
            "temperature": 0,
            "max_tokens": 8192,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }

        # 自动重试机制（3 次）
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{self.api_base}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=300,
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise ValueError(f"API 请求失败，已重试 {max_retries} 次。最后错误：{e}")

                print(f"⚠️  [网络波动] API 连接断开 ({e})，正在进行第 {attempt + 1} 次重试...")
                time.sleep(2)

        content = data["choices"][0]["message"]["content"]
        
        # 处理不同类型的响应
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    chunks.append(item.get("text", ""))
            return "".join(chunks).strip()

        raise ValueError(f"unexpected model content: {content!r}")
```

### 6.7.2 应用构建函数

**文件：`app.py`（完整）**

```python
from __future__ import annotations
from dataclasses import dataclass
from agent.loop import AgentLoop
from agent.prompts import build_system_prompt
from config import AppConfig
from runtime.filesystem import Filesystem
from runtime.subprocess_runner import SubprocessRunner
from skills.discovery import discover_skills
from skills.registry import SkillRegistry
from tools.bash import BashTool
from tools.read import ReadTool


@dataclass
class MiniApp:
    """应用实例"""
    loop: AgentLoop           # Agent 循环引擎
    loaded_skills: list[str]  # 已加载的技能列表
    warnings: list[str]       # 警告信息


def build_app(config: AppConfig) -> MiniApp:
    """构建完整的应用"""
    # 1. 发现并注册技能
    discovered = discover_skills(config.skill_roots())
    registry = SkillRegistry.build(discovered)

    # 2. 创建文件系统
    fs = Filesystem(
        project_dir=config.project_dir,
        allowed_roots=config.allowed_roots(),
        read_max_bytes=config.read_max_bytes,
    )
    
    # 3. 创建子进程运行器
    runner = SubprocessRunner(fs, timeout_sec=config.bash_timeout_sec)

    # 4. 初始化工具
    tools = {
        "Read": ReadTool(fs),
        "Bash": BashTool(runner),
    }

    # 5. 生成 System Prompt
    tools_text = "\n".join(tool.prompt_block() for tool in tools.values())
    system_prompt = build_system_prompt(registry, tools_text)

    # 6. 创建模型客户端
    model_client = OpenAICompatibleModelClient(
        api_base=config.api_base,
        api_key=config.api_key,
        model_name=config.model_name,
    )

    # 7. 创建 Agent 循环
    loop = AgentLoop(
        model_client=model_client,
        registry=registry,
        tools=tools,
        system_prompt=system_prompt,
        max_steps=config.max_steps,
    )

    return MiniApp(
        loop=loop,
        loaded_skills=registry.names(),
        warnings=registry.warnings,
    )
```

---

## 6.8 命令行接口

**文件：`cli.py`**

```python
from __future__ import annotations
import argparse
from pathlib import Path
from app import build_app
from config import AppConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="miniMaster CLI")
    parser.add_argument("--once", type=str, help="Run once and exit.")
    parser.add_argument("--project-dir", type=str, help="Override project dir.")
    parser.add_argument("--api-base", type=str, help="Override API base.")
    parser.add_argument("--api-key", type=str, help="Override API key.")
    parser.add_argument("--model", type=str, help="Override model name.")
    args = parser.parse_args()

    # 从环境变量加载配置
    config = AppConfig.from_env()

    # 命令行参数覆盖
    if args.project_dir:
        config.project_dir = Path(args.project_dir).expanduser().resolve()
    if args.api_base:
        config.api_base = args.api_base
    if args.api_key is not None:
        config.api_key = args.api_key
    if args.model:
        config.model_name = args.model

    # 构建应用
    app = build_app(config)

    # 打印启动信息
    print("mini-claude-code")
    print("loaded skills:", ", ".join(app.loaded_skills) if app.loaded_skills else "(none)")
    if app.warnings:
        print("warnings:")
        for w in app.warnings:
            print(" -", w)

    # 单次运行模式
    if args.once:
        print(app.loop.run_turn(args.once))
        return

    # 交互模式
    print("Type exit to quit.")
    print("Use /skill-name to explicitly activate a skill.")
    
    while True:
        try:
            text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            break

        try:
            result = app.loop.run_turn(text)
            print(result)
        except Exception as exc:
            print("[error]", exc)


if __name__ == "__main__":
    main()
```

---

## 6.9 运行示例

### 6.9.1 安装依赖

```bash
cd code/miniMaster
pip install python-dotenv pyyaml requests
```

### 6.9.2 配置环境变量

```bash
# 编辑 .env 文件
MCC_API_BASE="https://api.deepseek.com"
MCC_API_KEY="sk-your-api-key"
MCC_MODEL_NAME="deepseek-chat"
```

### 6.9.3 运行交互式会话

```bash
python cli.py
```

**示例对话**：

```
mini-claude-code
loaded skills: docx, pdf, pptx, xlsx
Type exit to quit.
Use /skill-name to explicitly activate a skill.

> workspace/Context engineering.pdf 请总结这篇文档的内容
----------------------------------------
🤔 [思考]: 用户要求我总结一个 PDF 文档。我需要先使用 pdf 技能来读取这个文件。让我先查看工作目录中的文件。
🛠️  [调用工具]: Bash
📦 [工具参数]: {"command": "ls -la workspace/", "cwd": "/path/to/project"}
----------------------------------------
🤔 [思考]: 找到了目标 PDF 文件。现在我需要使用 pdf 技能来处理它。让我先读取 pdf 技能的 SKILL.md 文件了解使用方法。
🛠️  [调用工具]: Read
📦 [工具参数]: {"path": "/path/to/.claude/skills/pdf/SKILL.md"}
----------------------------------------
🤔 [思考]: 根据技能指南，我可以使用 pdfplumber 来提取 PDF 文本。让我编写一个 Python 脚本来提取内容并总结。
🛠️  [调用工具]: Bash
📦 [工具参数]: {"command": "python3 -c \"import pdfplumber; ...\"", "cwd": "/path/to/workspace"}
----------------------------------------
🤔 [思考]: 已成功提取 PDF 内容。这是一篇关于"上下文工程"的详细指南。现在我来总结一下核心内容...

这篇文档《Context engineering》是一篇关于"上下文工程"（Context Engineering）的详细指南。以下是核心内容总结：

**一、什么是上下文工程**
- 定义：上下文工程将传统的单一提示词重新概念化为由多个信息组件动态组合而成的结构...
（后续省略）
```

### 6.9.4 显式激活技能

```bash
> /pdf 请帮我合并这三个 PDF 文件：a.pdf, b.pdf, c.pdf
----------------------------------------
🤔 [思考]: 用户想要合并 PDF 文件，并且已经通过/pdf 命令显式激活了 pdf 技能。让我先读取 SKILL.md 了解如何合并 PDF。
🛠️  [调用工具]: Read
📦 [工具参数]: {"path": "/path/to/.claude/skills/pdf/SKILL.md"}
----------------------------------------
🤔 [思考]: 根据 SKILL.md，我可以使用 pypdf 来合并 PDF。让我编写一个 Python 脚本来完成这个任务。
🛠️  [调用工具]: Bash
📦 [工具参数]: {"command": "python3 -c \"from pypdf import PdfWriter, PdfReader; ...\""}
----------------------------------------
✅ 已成功合并 a.pdf, b.pdf, c.pdf 到 merged.pdf
```

---

## 6.10 核心设计原则

### 6.10.1 渐进式披露

```
技能目录（仅名称 + 描述）→ 用户触发需求 → 加载完整 SKILL.md → 执行任务
```

**优势**：
- 节省 Token
- 提高响应速度
- 避免信息过载

### 6.10.2 安全沙箱

```python
# 1. 文件系统白名单
allowed_roots = [project_dir, skill_dirs]

# 2. 环境变量隔离
env = {"PATH": "...", "HOME": "..."}  # 最小化

# 3. 命令超时保护
timeout_sec = 20  # 防止无限循环
```

### 6.10.3 透明化执行

```python
# 打印思考过程
print(f"🤔 [思考]: {action['thought']}")

# 打印工具调用
print(f"🛠️  [调用工具]: {tool_name}")
print(f"📦 [工具参数]: {json.dumps(tool_input)}")
```

---

## 6.11 扩展指南

### 6.11.1 添加新技能

1. 在 `.claude/skills/` 下创建新目录
2. 添加 `SKILL.md` 文件（包含 frontmatter）
3. 重启应用即可自动加载

**示例：添加 image 技能**

```bash
mkdir -p .claude/skills/image
cat > .claude/skills/image/SKILL.md << 'EOF'
---
name: image
description: Process and analyze images using PIL, OpenCV, etc.
---

# Image Processing Guide

## Installation
pip install Pillow opencv-python

## Examples
```python
from PIL import Image
img = Image.open("photo.jpg")
img.show()
```

### 6.11.2 添加新工具

1. 在 `tools/` 目录创建新文件
2. 实现 `prompt_block()` 和 `run()` 方法
3. 在 `app.py` 中注册

**示例：添加 Search 工具**

```python
# tools/search.py
from __future__ import annotations
import json
import requests


class SearchTool:
    name = "Search"
    description = "Search the web for information."

    def prompt_block(self) -> str:
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"],
        }
        return f"- {self.name}: {self.description}\n  Input schema: {json.dumps(schema)}"

    def run(self, tool_input: dict) -> dict:
        query = tool_input["query"]
        # 调用搜索 API
        results = requests.get(f"https://api.example.com/search?q={query}")
        return {"results": results.json()}
```

然后在 `app.py` 中注册：

```python
from tools.search import SearchTool

tools = {
    "Read": ReadTool(fs),
    "Bash": BashTool(runner),
    "Search": SearchTool(),  # 新增
}
```

---

## 6.12 to do
- 开发 Web UI 界面
- 增加记忆系统
- 引入subagent


通过动手实践这个项目，你将深入理解现代 Agent 系统的设计原理和实现细节。
