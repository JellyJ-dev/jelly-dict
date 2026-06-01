from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from pathlib import PurePosixPath

import pytest


BLOCKED_TRACKED_SUFFIXES = (".pyc", ".pyo", ".pyd", ".DS_Store")
BLOCKED_TRACKED_SEGMENTS = {
    ".jelly_dict",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "venv",
}
BLOCKED_TRACKED_EXPORT_SUFFIXES = (".apkg", ".tsv", ".xls", ".xlsx")
REQUIRED_GITIGNORE_PATTERNS = {
    ".DS_Store",
    "__pycache__/",
    "*.py[cod]",
    ".venv/",
    "**/.venv/",
    ".pytest_cache/",
    "**/.pytest_cache/",
    ".jelly_dict/",
    "**/.jelly_dict/",
    "*.xlsx",
    "*.apkg",
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
}


def _git_root() -> str:
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        pytest.skip("repository hygiene checks require a git worktree")
    return result.stdout.strip()


def _tracked_files() -> list[str]:
    root = _git_root()
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return [
        path.decode("utf-8", errors="replace")
        for path in result.stdout.split(b"\0")
        if path
    ]


def _is_blocked_tracked_artifact(path: str) -> bool:
    pure_path = PurePosixPath(path)
    if any(part in BLOCKED_TRACKED_SEGMENTS for part in pure_path.parts):
        return True
    if path.endswith(BLOCKED_TRACKED_SUFFIXES):
        return True
    return path.endswith(BLOCKED_TRACKED_EXPORT_SUFFIXES)


def test_generated_artifacts_are_not_tracked():
    blocked = [path for path in _tracked_files() if _is_blocked_tracked_artifact(path)]

    assert blocked == []


def test_gitignore_keeps_local_runtime_artifacts_out_of_commits():
    root = _git_root()
    gitignore_patterns = {
        line.strip()
        for line in (Path(root) / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missed = sorted(REQUIRED_GITIGNORE_PATTERNS - gitignore_patterns)

    assert missed == []


def test_gitignore_keeps_nested_python_cache_out_of_commits():
    root = _git_root()
    sample_paths = [
        "app_files/jelly_dict/app/__pycache__/main.cpython-312.pyc",
        "app_files/jelly_dict/tests/__pycache__/test_models.cpython-312.pyc",
    ]
    missed: list[str] = []
    for path in sample_paths:
        result = subprocess.run(
            ["git", "check-ignore", "-q", path],
            cwd=root,
            timeout=10,
        )
        if result.returncode != 0:
            missed.append(path)

    assert missed == []
