#!/usr/bin/env python3
"""快速校验 miniMaster skill package 结构。"""

from __future__ import annotations

import argparse
import sys

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills.store import validate_skill_directory


DEFAULT_LIBRARY_ROOT = PROJECT_ROOT / "skills" / "library"


def validate_many(skill_dirs: list[Path]) -> int:
    """批量校验多个 skill 目录，并汇总退出码。"""
    exit_code = 0
    for skill_dir in skill_dirs:
        is_valid, message = validate_skill_directory(skill_dir)
        status = "OK" if is_valid else "ERROR"
        print(f"[{status}] {skill_dir}: {message}")
        if not is_valid:
            exit_code = 1
    return exit_code


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="Validate one or more miniMaster skill packages.")
    parser.add_argument("skill_path", nargs="?", help="Path to a single skill directory.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all skill packages under miniMaster's bundled library.",
    )
    return parser.parse_args()


def main() -> int:
    """脚本入口。"""
    args = parse_args()

    if args.all:
        skill_dirs = [path for path in sorted(DEFAULT_LIBRARY_ROOT.iterdir()) if path.is_dir()]
        return validate_many(skill_dirs)

    if not args.skill_path:
        print("Usage: python skills/scripts/quick_validate.py <skill_directory> or --all")
        return 1

    return validate_many([Path(args.skill_path).resolve()])


if __name__ == "__main__":
    raise SystemExit(main())
