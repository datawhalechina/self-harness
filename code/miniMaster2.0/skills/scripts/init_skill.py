#!/usr/bin/env python3
"""Initialize a new miniMaster skill package."""

from __future__ import annotations

import argparse
import sys

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills.store import SKILL_NAME_PATTERN, validate_skill_directory


DEFAULT_LIBRARY_ROOT = PROJECT_ROOT / "skills" / "library"

SKILL_TEMPLATE = """---
name: {skill_name}
description: TODO - 说明这个 skill 在什么任务下使用，以及它能提供什么帮助。
tags: [{tag_hint}]
---

# {skill_title}

## Overview

[TODO: 用 1 到 2 句话说明这个 skill 的用途。]

## Workflow

1. [TODO: 写出第一步。]
2. [TODO: 写出第二步。]
3. [TODO: 写出第三步。]

## Resource Guide

- 需要确定性脚本时，查看 `scripts/`。
- 需要补充说明文档时，查看 `references/`。
- 需要模板或产出资源时，查看 `assets/`。
"""

SCRIPT_TEMPLATE = '''#!/usr/bin/env python3
"""Example helper script for {skill_name}."""


def main():
    print("Replace this helper with a real workflow script.")


if __name__ == "__main__":
    main()
'''

REFERENCE_TEMPLATE = """# Reference Notes

在这里补充只应按需读取的详细资料，例如：

- 领域规则
- API 说明
- 复杂流程拆解
"""

ASSET_TEMPLATE = """# Asset Placeholder

把模板、样例数据、图标或其他输出资源放在这里。
"""


def title_case_skill_name(skill_name: str) -> str:
    return " ".join(part.capitalize() for part in skill_name.split("-"))


def ensure_valid_skill_name(skill_name: str):
    if not SKILL_NAME_PATTERN.match(skill_name):
        raise ValueError("skill 名称必须使用小写字母、数字和短横线。")
    if skill_name.startswith("-") or skill_name.endswith("-") or "--" in skill_name:
        raise ValueError("skill 名称不能以短横线开头/结尾，也不能包含连续短横线。")


def write_text_file(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def init_skill(skill_name: str, library_root: Path) -> Path:
    ensure_valid_skill_name(skill_name)
    skill_dir = library_root / skill_name
    if skill_dir.exists():
        raise FileExistsError(f"Skill directory already exists: {skill_dir}")

    skill_dir.mkdir(parents=True, exist_ok=False)
    (skill_dir / "scripts").mkdir()
    (skill_dir / "references").mkdir()
    (skill_dir / "assets").mkdir()

    skill_title = title_case_skill_name(skill_name)
    write_text_file(
        skill_dir / "SKILL.md",
        SKILL_TEMPLATE.format(
            skill_name=skill_name,
            skill_title=skill_title,
            tag_hint=f"{skill_name}, workflow",
        ),
    )
    write_text_file(skill_dir / "scripts" / "example.py", SCRIPT_TEMPLATE.format(skill_name=skill_name))
    write_text_file(skill_dir / "references" / "notes.md", REFERENCE_TEMPLATE)
    write_text_file(skill_dir / "assets" / "template.md", ASSET_TEMPLATE)
    return skill_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize a new miniMaster skill package.")
    parser.add_argument("skill_name", help="Skill name in hyphen-case, for example: inspect-api")
    parser.add_argument(
        "--path",
        default=str(DEFAULT_LIBRARY_ROOT),
        help="Target skills library directory. Defaults to miniMaster's bundled library.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_root = Path(args.path).resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    try:
        skill_dir = init_skill(args.skill_name.strip(), target_root)
    except Exception as exc:
        print(exc)
        return 1

    is_valid, message = validate_skill_directory(skill_dir)
    print(f"Created skill package: {skill_dir}")
    print(message)
    return 0 if is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
