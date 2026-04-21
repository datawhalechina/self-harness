#!/usr/bin/env python3
"""根据标题和章节名生成一个简单的 Markdown 报告骨架。"""

from __future__ import annotations

import sys

from pathlib import Path


def build_outline(title: str, sections: list[str]) -> str:
    """把标题和章节列表渲染成 Markdown 模板。"""
    lines = [f"# {title}", ""]
    for section in sections:
        normalized = section.strip()
        if not normalized:
            continue
        lines.append(f"## {normalized}")
        lines.append("")
        lines.append("- TODO")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    """脚本入口。"""
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: python scripts/render_report_stub.py <output_path> <title> [section1] [section2] ..."
        )

    output_path = Path(sys.argv[1]).resolve()
    title = sys.argv[2]
    sections = sys.argv[3:] or ["Overview", "Findings", "Next Steps"]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_outline(title, sections), encoding="utf-8")
    print(f"Wrote report outline to {output_path}")


if __name__ == "__main__":
    main()
