#!/usr/bin/env python3
"""Print a shallow directory tree for quick repository inspection."""

from __future__ import annotations

import argparse
import sys

from pathlib import Path


def _should_skip(path: Path) -> bool:
    name = path.name
    if name == "__pycache__":
        return True
    if name.startswith("."):
        return True
    if path.is_file() and path.suffix in {".pyc", ".pyo"}:
        return True
    return False


def _walk(current_path: Path, current_depth: int, max_depth: int):
    if current_depth > max_depth:
        return

    indent = "  " * current_depth
    if current_depth == 0:
        print(current_path.resolve())

    for child in sorted(current_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if _should_skip(child):
            continue
        suffix = "/" if child.is_dir() else ""
        print(f"{indent}- {child.name}{suffix}")
        if child.is_dir():
            _walk(child, current_depth + 1, max_depth)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments while keeping backward compatibility.

    Supported forms:
    1. `python print_tree.py ROOT --depth 2`
    2. `python print_tree.py ROOT 2`
    """
    parser = argparse.ArgumentParser(
        description="Print a shallow directory tree for quick repository inspection.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Root directory to inspect. Defaults to the current directory.",
    )
    parser.add_argument(
        "legacy_depth",
        nargs="?",
        type=int,
        help="Legacy positional depth argument kept for backward compatibility.",
    )
    parser.add_argument(
        "--depth",
        "-d",
        type=int,
        help="Maximum directory depth to print.",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args(sys.argv[1:])
    root_arg = args.root
    max_depth = args.depth if args.depth is not None else args.legacy_depth
    if max_depth is None:
        max_depth = 2

    root_path = Path(root_arg).resolve()
    if not root_path.exists():
        raise SystemExit(f"Path not found: {root_path}")
    if not root_path.is_dir():
        raise SystemExit(f"Not a directory: {root_path}")

    _walk(root_path, current_depth=0, max_depth=max_depth)


if __name__ == "__main__":
    main()
