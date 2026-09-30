#!/usr/bin/env python3
"""Build, verify, open, and automatically quit the local macOS app bundle."""

from __future__ import annotations

import os
import plistlib
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_FILES = PROJECT_ROOT / "app_files"
BUILD_SCRIPT = APP_FILES / "packaging" / "macos" / "build_app.sh"
APP_BUNDLE = APP_FILES / "dist" / "Jelly Dict.app"
EXECUTABLE = APP_BUNDLE / "Contents" / "MacOS" / "jelly-dict"
PLIST = APP_BUNDLE / "Contents" / "Info.plist"
_SMOKE_BASELINE_PIDS: set[int] = set()


def _run(command: list[str], *, timeout: int, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stdout}\n{result.stderr}"
        )


def _owned_processes() -> dict[int, str]:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,command="],
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    owned: dict[int, str] = {}
    root = str(PROJECT_ROOT)
    markers = (
        "jelly-dict",
        "playwright",
        "cliDaemon.js",
        "broker_worker",
        "--remote-debugging-pipe",
    )
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        if root in command and any(marker in command for marker in markers):
            owned[int(pid_text)] = command
    return owned


def _cleanup_spawned_processes() -> None:
    spawned = {
        pid: command
        for pid, command in _owned_processes().items()
        if pid not in _SMOKE_BASELINE_PIDS
    }
    for pid in spawned:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 2.0
    while spawned and time.monotonic() < deadline:
        time.sleep(0.05)
        current = _owned_processes()
        spawned = {pid: command for pid, command in spawned.items() if pid in current}
    for pid in spawned:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    global _SMOKE_BASELINE_PIDS
    if sys.platform != "darwin":
        print("macOS app smoke skipped: non-Darwin host")
        return 0

    before = _owned_processes()
    _SMOKE_BASELINE_PIDS = set(before)
    _run([str(BUILD_SCRIPT)], timeout=180)
    if not EXECUTABLE.is_file() or not os.access(EXECUTABLE, os.X_OK):
        raise RuntimeError(f"bundle executable missing: {EXECUTABLE}")

    plist = plistlib.loads(PLIST.read_bytes())
    if plist.get("CFBundleExecutable") != "jelly-dict":
        raise RuntimeError("bundle executable metadata mismatch")
    _run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(APP_BUNDLE)], timeout=30)
    _run(["/usr/bin/plutil", "-lint", str(PLIST)], timeout=30)

    with tempfile.TemporaryDirectory(prefix="jelly-dict-smoke-") as runtime_home:
        env = os.environ.copy()
        env["JELLY_DICT_HOME"] = runtime_home
        env["JELLY_DICT_SMOKE_QUIT_MS"] = "250"
        _run([str(EXECUTABLE)], timeout=90, env=env)

    deadline = time.monotonic() + 5.0
    leftovers: dict[int, str] = {}
    while time.monotonic() < deadline:
        leftovers = {
            pid: command for pid, command in _owned_processes().items() if pid not in before
        }
        if not leftovers:
            break
        time.sleep(0.1)
    if leftovers:
        detail = "\n".join(f"{pid}: {command}" for pid, command in leftovers.items())
        raise RuntimeError(f"app smoke left owned processes:\n{detail}")

    print("macOS app build/check/open/quit smoke OK; owned process delta 0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        if sys.platform == "darwin":
            _cleanup_spawned_processes()
        print(f"macOS app smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
