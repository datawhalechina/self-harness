from dataclasses import dataclass, field


@dataclass(frozen=True)
class Skill:
    """从目录化 skill package 中加载出的 skill 定义。"""

    name: str
    description: str
    root_dir: str
    relative_root_dir: str
    skill_md_path: str
    relative_skill_md_path: str
    instructions: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    scripts: tuple[str, ...] = field(default_factory=tuple)
    references: tuple[str, ...] = field(default_factory=tuple)
    assets: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_instructions(self) -> bool:
        """标记当前对象是否已经加载了 SKILL.md 正文。"""
        return bool(self.instructions.strip())
