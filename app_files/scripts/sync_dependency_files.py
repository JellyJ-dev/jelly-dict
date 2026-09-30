#!/usr/bin/env python3
"""Render or verify requirement/constraint files from dependency policy."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent / "jelly_dict"
sys.path.insert(0, str(APP_DIR))

from app.core.dependency_policy import (  # noqa: E402
    CONSTRAINT_FILES,
    CONSTRAINT_PINS,
    REQUIREMENT_GROUPS,
    SUPPORTED_PYTHON_MINORS,
)


def rendered_files() -> dict[Path, str]:
    rendered = {
        APP_DIR / "requirements.txt": "\n".join(
            rule.requirement for rule in REQUIREMENT_GROUPS["runtime"]
        )
        + "\n",
        APP_DIR / "requirements-tts.txt": "\n".join(
            rule.requirement for rule in REQUIREMENT_GROUPS["tts"]
        )
        + "\n",
    }
    for python_minor in SUPPORTED_PYTHON_MINORS:
        for group in ("runtime", "tts"):
            path = APP_DIR / CONSTRAINT_FILES[python_minor][group]
            header = f"# Generated from app/core/dependency_policy.py for CPython {python_minor}.\n"
            rendered[path] = header + "\n".join(CONSTRAINT_PINS[python_minor][group]) + "\n"
    return rendered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="rewrite generated files instead of only checking them",
    )
    args = parser.parse_args(argv)

    mismatches: list[Path] = []
    for path, expected in rendered_files().items():
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current == expected:
            continue
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
        else:
            mismatches.append(path)

    if mismatches:
        for path in mismatches:
            print(f"dependency file out of date: {path}", file=sys.stderr)
        print("run sync_dependency_files.py --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
