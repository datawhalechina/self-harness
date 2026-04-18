#!/usr/bin/env python3
"""Generate a simple Markdown report outline from a title and sections."""

from __future__ import annotations

import sys

from pathlib import Path


def build_outline(title: str, sections: list[str]) -> str:
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
