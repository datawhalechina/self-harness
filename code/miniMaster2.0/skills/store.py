from __future__ import annotations

import re

from pathlib import Path

from skills.types import Skill


FRONTMATTER_DELIMITER = "---"
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")
ALLOWED_FRONTMATTER_FIELDS = {"name", "description", "tags", "license"}


class SkillPackageError(ValueError):
    """skill package 结构或元数据不合法时抛出的异常。"""


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_scalar_value(raw_value: str) -> str:
    return _strip_matching_quotes(raw_value.strip())


def _parse_list_value(raw_value: str) -> list[str]:
    inner = raw_value.strip()[1:-1].strip()
    if not inner:
        return []
    return [_parse_scalar_value(item) for item in inner.split(",") if item.strip()]


def parse_frontmatter(frontmatter_text: str) -> dict[str, object]:
    """解析 SKILL.md 顶部的极简 frontmatter。"""
    metadata: dict[str, object] = {}
    current_list_key: str | None = None

    for line_number, raw_line in enumerate(frontmatter_text.splitlines(), start=1):
        stripped_line = raw_line.strip()
        if not stripped_line:
            continue

        if current_list_key and stripped_line.startswith("- "):
            current_values = metadata.setdefault(current_list_key, [])
            if not isinstance(current_values, list):
                raise SkillPackageError(f"frontmatter 第 {line_number} 行的列表结构无效。")
            current_values.append(_parse_scalar_value(stripped_line[2:]))
            continue

        current_list_key = None
        if ":" not in raw_line:
            raise SkillPackageError(f"frontmatter 第 {line_number} 行缺少 ':'。")

        key, raw_value = raw_line.split(":", 1)
        normalized_key = key.strip()
        normalized_value = raw_value.strip()
        if not normalized_key:
            raise SkillPackageError(f"frontmatter 第 {line_number} 行的字段名为空。")

        if normalized_value.startswith("[") and normalized_value.endswith("]"):
            metadata[normalized_key] = _parse_list_value(normalized_value)
            continue

        if normalized_value:
            metadata[normalized_key] = _parse_scalar_value(normalized_value)
            continue

        metadata[normalized_key] = []
        current_list_key = normalized_key

    return metadata


def split_frontmatter_and_body(document_text: str) -> tuple[dict[str, object], str]:
    """把 SKILL.md 拆成 frontmatter 和 markdown 正文。"""
    if not document_text.startswith(f"{FRONTMATTER_DELIMITER}\n"):
        raise SkillPackageError("SKILL.md 缺少 YAML frontmatter 起始分隔符 '---'。")

    parts = document_text.split(f"\n{FRONTMATTER_DELIMITER}\n", 1)
    if len(parts) != 2:
        raise SkillPackageError("SKILL.md 缺少 YAML frontmatter 结束分隔符 '---'。")

    frontmatter_text = parts[0][len(FRONTMATTER_DELIMITER) + 1:]
    body = parts[1].strip()
    return parse_frontmatter(frontmatter_text), body


def _normalize_string_list(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()

    if isinstance(value, str):
        normalized = value.strip()
        return (normalized,) if normalized else ()

    if isinstance(value, list):
        normalized_items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise SkillPackageError(f"frontmatter 字段 '{field_name}' 中只能包含字符串。")
            normalized_item = item.strip()
            if normalized_item:
                normalized_items.append(normalized_item)
        return tuple(normalized_items)

    raise SkillPackageError(f"frontmatter 字段 '{field_name}' 必须是字符串或字符串列表。")


def _normalize_required_string(metadata: dict[str, object], field_name: str) -> str:
    value = metadata.get(field_name)
    if not isinstance(value, str):
        raise SkillPackageError(f"frontmatter 缺少必填字段 '{field_name}'，或字段类型不是字符串。")

    normalized = value.strip()
    if not normalized:
        raise SkillPackageError(f"frontmatter 字段 '{field_name}' 不能为空。")
    return normalized


def _collect_resource_files(skill_dir: Path, folder_name: str) -> tuple[str, ...]:
    resource_dir = skill_dir / folder_name
    if not resource_dir.exists():
        return ()
    if not resource_dir.is_dir():
        raise SkillPackageError(f"{resource_dir} 必须是目录。")

    files = []
    for path in sorted(resource_dir.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        files.append(path.relative_to(skill_dir).as_posix())
    return tuple(files)


def _render_root_path(path: Path, workspace_root: Path | None) -> str:
    if workspace_root is None:
        return str(path)

    try:
        return path.relative_to(workspace_root).as_posix()
    except ValueError:
        return str(path)


def load_skill_from_directory(
    skill_dir: str | Path,
    workspace_root: str | Path | None = None,
    include_instructions: bool = True,
) -> Skill:
    """从单个 skill 目录加载 skill package。"""
    resolved_skill_dir = Path(skill_dir).resolve()
    skill_md_path = resolved_skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        raise SkillPackageError(f"{resolved_skill_dir} 缺少 SKILL.md。")

    document_text = skill_md_path.read_text(encoding="utf-8")
    metadata, body = split_frontmatter_and_body(document_text)

    unexpected_fields = sorted(set(metadata) - ALLOWED_FRONTMATTER_FIELDS)
    if unexpected_fields:
        joined = ", ".join(unexpected_fields)
        raise SkillPackageError(f"SKILL.md frontmatter 含有未支持字段: {joined}")

    name = _normalize_required_string(metadata, "name")
    description = _normalize_required_string(metadata, "description")
    if not SKILL_NAME_PATTERN.match(name) or "--" in name or name.startswith("-") or name.endswith("-"):
        raise SkillPackageError(
            f"skill 名称 '{name}' 不合法；请使用小写字母、数字和短横线。"
        )

    tags = _normalize_string_list(metadata.get("tags"), "tags")
    if not body:
        raise SkillPackageError("SKILL.md 正文不能为空。")

    normalized_workspace_root = Path(workspace_root).resolve() if workspace_root else None
    instructions = body if include_instructions else ""

    return Skill(
        name=name,
        description=description,
        root_dir=str(resolved_skill_dir),
        relative_root_dir=_render_root_path(resolved_skill_dir, normalized_workspace_root),
        skill_md_path=str(skill_md_path),
        relative_skill_md_path=_render_root_path(skill_md_path, normalized_workspace_root),
        instructions=instructions,
        tags=tags,
        scripts=_collect_resource_files(resolved_skill_dir, "scripts"),
        references=_collect_resource_files(resolved_skill_dir, "references"),
        assets=_collect_resource_files(resolved_skill_dir, "assets"),
    )


def validate_skill_directory(skill_dir: str | Path) -> tuple[bool, str]:
    """验证单个 skill 目录是否符合 MVP skill package 结构。"""
    try:
        resolved_skill_dir = Path(skill_dir).resolve()
        if not resolved_skill_dir.exists():
            return False, f"skill 目录不存在: {resolved_skill_dir}"
        if not resolved_skill_dir.is_dir():
            return False, f"skill 路径不是目录: {resolved_skill_dir}"

        skill = load_skill_from_directory(
            resolved_skill_dir,
            workspace_root=resolved_skill_dir.parent.parent,
            include_instructions=True,
        )
        if resolved_skill_dir.name != skill.name:
            return False, (
                f"目录名 '{resolved_skill_dir.name}' 与 frontmatter 中的 name '{skill.name}' 不一致。"
            )
    except SkillPackageError as exc:
        return False, str(exc)

    resource_summary = (
        f"scripts={len(skill.scripts)}, references={len(skill.references)}, assets={len(skill.assets)}"
    )
    return True, f"Skill is valid: {skill.name} ({resource_summary})"


class SkillStore:
    """加载和查询目录化 skill package。"""

    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.workspace_root = self.root.parents[1] if len(self.root.parents) >= 2 else self.root.parent

    def _iter_skill_dirs(self):
        if not self.root.exists():
            return

        for skill_dir in sorted(path for path in self.root.iterdir() if path.is_dir()):
            if (skill_dir / "SKILL.md").exists():
                yield skill_dir

    def load_all(self) -> list[Skill]:
        skills = []
        for skill_dir in self._iter_skill_dirs() or []:
            skills.append(
                load_skill_from_directory(
                    skill_dir,
                    workspace_root=self.workspace_root,
                    include_instructions=False,
                )
            )
        return skills

    def find(self, name: str) -> Skill | None:
        for skill_dir in self._iter_skill_dirs() or []:
            skill = load_skill_from_directory(
                skill_dir,
                workspace_root=self.workspace_root,
                include_instructions=False,
            )
            if skill.name == name:
                return load_skill_from_directory(
                    skill_dir,
                    workspace_root=self.workspace_root,
                    include_instructions=True,
                )
        return None


def _render_resource_counts(skill: Skill) -> str:
    return (
        f"scripts={len(skill.scripts)}, "
        f"references={len(skill.references)}, "
        f"assets={len(skill.assets)}"
    )


def render_skills_for_prompt(skills: list[Skill]) -> str:
    """把全部可用 skills 渲染成适合放进 Prompt 的元数据文本。"""
    if not skills:
        return "当前没有可用 skills。"

    lines = []
    for skill in skills:
        lines.append(f"- {skill.name}: {skill.description}")
        lines.append(f"  目录: {skill.relative_root_dir}")
        lines.append(f"  SKILL.md: {skill.relative_skill_md_path}")
        lines.append(f"  资源概况: {_render_resource_counts(skill)}")
        lines.append("  使用方式: 如果你判断它适合当前 task，先 read 这个 SKILL.md，再按需使用 scripts/ 或 references/。")
        if skill.tags:
            lines.append(f"  标签: {', '.join(skill.tags)}")
    return "\n".join(lines)
