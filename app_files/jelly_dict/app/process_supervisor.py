"""Owned subprocess execution with bounded output and process-group cleanup."""

from __future__ import annotations

import logging
import os
import queue
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    idle_timed_out: bool = False


class _BoundedCapture:
    def __init__(self, limit: int) -> None:
        self._limit = max(1, limit)
        self._chunks: deque[str] = deque()
        self._size = 0

    def append(self, text: str) -> None:
        if not text:
            return
        self._chunks.append(text)
        self._size += len(text)
        while self._size > self._limit and self._chunks:
            overflow = self._size - self._limit
            first = self._chunks[0]
            if len(first) <= overflow:
                self._chunks.popleft()
                self._size -= len(first)
            else:
                self._chunks[0] = first[overflow:]
                self._size -= overflow

    def text(self) -> str:
        return "".join(self._chunks)


class ProcessSupervisor:
    def __init__(
        self,
        *,
        category: str,
        capture_limit: int = 1_000_000,
        terminate_grace_seconds: float = 2.0,
    ) -> None:
        self._category = category
        self._capture_limit = capture_limit
        self._terminate_grace_seconds = max(0.01, terminate_grace_seconds)
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    @property
    def pid(self) -> int | None:
        with self._lock:
            process = self._process
            return process.pid if process is not None else None

    def run(
        self,
        command: Sequence[str],
        *,
        input_text: str | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
        idle_timeout: float | None = None,
        cancel_event: threading.Event | None = None,
        progress: Callable[[str], None] | None = None,
        merge_stderr: bool = False,
    ) -> ProcessResult:
        with self._lock:
            if self._process is not None:
                raise RuntimeError(f"{self._category} process is already active")

        stderr_target = subprocess.STDOUT if merge_stderr else subprocess.PIPE
        popen_kwargs = {
            "stdin": subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": stderr_target,
            "text": True,
            "bufsize": 1,
            "cwd": str(cwd) if cwd is not None else None,
            "env": env,
        }
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True
        elif os.name == "nt":  # pragma: no cover - project targets macOS
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        process = subprocess.Popen(list(command), **popen_kwargs)
        with self._lock:
            self._process = process
        log.info("process start category=%s pid=%s", self._category, process.pid)

        if input_text is not None and process.stdin is not None:
            try:
                process.stdin.write(input_text)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        events: queue.Queue[tuple[str, str | None]] = queue.Queue()
        readers = [
            self._start_reader(process.stdout, "stdout", events),
        ]
        stream_count = 1
        if not merge_stderr:
            readers.append(self._start_reader(process.stderr, "stderr", events))
            stream_count += 1

        stdout = _BoundedCapture(self._capture_limit)
        stderr = _BoundedCapture(self._capture_limit)
        finished_streams = 0
        started = time.monotonic()
        last_output = started
        timed_out = False
        idle_timed_out = False
        cancelled = False
        termination_requested = False

        try:
            while True:
                try:
                    stream, text = events.get(timeout=0.05)
                except queue.Empty:
                    stream = ""
                    text = None
                if stream:
                    if text is None:
                        finished_streams += 1
                    else:
                        last_output = time.monotonic()
                        capture = stdout if stream == "stdout" else stderr
                        capture.append(text)
                        if progress is not None:
                            progress(text.rstrip("\r\n"))

                now = time.monotonic()
                if not termination_requested:
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        termination_requested = True
                    elif timeout is not None and now - started > timeout:
                        timed_out = True
                        termination_requested = True
                    elif (
                        idle_timeout is not None
                        and process.poll() is None
                        and now - last_output > idle_timeout
                    ):
                        timed_out = True
                        idle_timed_out = True
                        termination_requested = True
                    if termination_requested:
                        self._terminate_group(process)

                if (
                    process.poll() is not None
                    and finished_streams >= stream_count
                    and events.empty()
                ):
                    break
        finally:
            if process.poll() is None:
                self._terminate_group(process)
            try:
                process.wait(timeout=self._terminate_grace_seconds)
            except subprocess.TimeoutExpired:
                self._kill_group(process)
                process.wait()
            for reader in readers:
                reader.join(timeout=1.0)
            while True:
                try:
                    stream, text = events.get_nowait()
                except queue.Empty:
                    break
                if text is None:
                    continue
                (stdout if stream == "stdout" else stderr).append(text)
            with self._lock:
                if self._process is process:
                    self._process = None
            log.info(
                "process exit category=%s pid=%s code=%s",
                self._category,
                process.pid,
                process.returncode,
            )

        return ProcessResult(
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=stdout.text(),
            stderr=stderr.text(),
            timed_out=timed_out,
            cancelled=cancelled,
            idle_timed_out=idle_timed_out,
        )

    def cancel(self) -> bool:
        with self._lock:
            process = self._process
        if process is None:
            return True
        self._terminate_group(process)
        return process.poll() is not None

    @staticmethod
    def _start_reader(stream, name: str, events) -> threading.Thread:
        def read() -> None:
            if stream is None:
                events.put((name, None))
                return
            try:
                for line in iter(stream.readline, ""):
                    events.put((name, line))
            finally:
                try:
                    stream.close()
                except OSError:
                    pass
                events.put((name, None))

        thread = threading.Thread(
            target=read,
            name=f"process-output-{name}",
            daemon=True,
        )
        thread.start()
        return thread

    def _terminate_group(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:  # pragma: no cover - project targets macOS
                process.terminate()
            process.wait(timeout=self._terminate_grace_seconds)
            return
        except (ProcessLookupError, PermissionError):
            return
        except subprocess.TimeoutExpired:
            pass
        self._kill_group(process)

    @staticmethod
    def _kill_group(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:  # pragma: no cover - project targets macOS
                process.kill()
        except (ProcessLookupError, PermissionError):
            pass
