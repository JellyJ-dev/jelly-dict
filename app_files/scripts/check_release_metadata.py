#!/usr/bin/env python3
"""Verify that every public release surface matches pyproject.toml."""

from __future__ import annotations

import argparse
import plistlib
import re
import sys
import tomllib
from pathlib import Path


def check_release_metadata(project_root: Path) -> list[str]:
    app_root = project_root / "app_files" / "jelly_dict"
    pyproject_path = app_root / "pyproject.toml"
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        version = str(pyproject["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        return [f"cannot read project version: {exc}"]

    errors: list[str] = []
    if re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version) is None:
        errors.append(f"invalid project version: {version}")

    installer_path = project_root / "app_files" / "scripts" / "install_app.sh"
    readme_path = project_root / "README.md"
    plist_path = project_root / "app_files" / "packaging" / "macos" / "Info.plist"

    try:
        installer = installer_path.read_text(encoding="utf-8")
        assignments = re.findall(r'^JELLY_DICT_VERSION="([^"]+)"$', installer, re.M)
        if assignments != [version]:
            errors.append(
                f"{installer_path}: expected one JELLY_DICT_VERSION={version}, found {assignments}"
            )
    except OSError as exc:
        errors.append(f"{installer_path}: {exc}")

    for path, expected in ((readme_path, f"> **현재 버전: v{version}**"),):
        try:
            if expected not in path.read_text(encoding="utf-8"):
                errors.append(f"{path}: missing release marker {expected!r}")
        except OSError as exc:
            errors.append(f"{path}: {exc}")

    try:
        plist = plistlib.loads(plist_path.read_bytes())
        for key in ("CFBundleShortVersionString", "CFBundleVersion"):
            actual = str(plist.get(key, ""))
            if actual != version:
                errors.append(f"{plist_path}: {key}={actual!r}, expected {version!r}")
    except (OSError, plistlib.InvalidFileException) as exc:
        errors.append(f"{plist_path}: {exc}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root to verify",
    )
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    errors = check_release_metadata(root)
    if errors:
        for error in errors:
            print(f"release metadata mismatch: {error}", file=sys.stderr)
        return 1

    pyproject = tomllib.loads(
        (root / "app_files" / "jelly_dict" / "pyproject.toml").read_text(encoding="utf-8")
    )
    print(f"release metadata OK: {pyproject['project']['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
