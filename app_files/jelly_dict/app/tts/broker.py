from __future__ import annotations

import json
import logging
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

INTERACTIVE_PRIORITY = 0
EXPORT_PRIORITY = 10
BACKGROUND_PRIORITY = 20
_MAX_MESSAGE_BYTES = 1_000_000
_APP_ROOT = Path(__file__).resolve().parents[2]


class TtsBrokerError(RuntimeError):
    pass


class TtsBrokerCancelled(TtsBrokerError):
    pass


class TtsBrokerTimeout(TtsBrokerError):
    pass


@dataclass(order=True)
class _BrokerRequest:
    priority: int
    sequence: int
    payload: dict[str, Any] = field(compare=False)
    timeout: float = field(compare=False)
    cancel_event: threading.Event | None = field(compare=False, default=None)
    done: threading.Event = field(compare=False, default_factory=threading.Event)
    result: dict[str, Any] | None = field(compare=False, default=None)
    error: BaseException | None = field(compare=False, default=None)
    cancelled: threading.Event = field(
        compare=False,
        default_factory=threading.Event,
    )


class TtsBroker:
    """Priority dispatcher for one warm, owned TTS worker process."""

    def __init__(
        self,
        *,
        idle_timeout: float = 60.0,
        command: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._idle_timeout = max(0.05, idle_timeout)
        self._command = command or [sys.executable, "-m", "app.tts.broker_worker"]
        self._extra_env = dict(env or {})
        self._requests: queue.PriorityQueue[_BrokerRequest] = queue.PriorityQueue()
        self._lock = threading.RLock()
        self._process_lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_tail: deque[str] = deque(maxlen=100)
        self._active: _BrokerRequest | None = None
        self._sequence = 0
        self._closed = False
        self._last_activity = time.monotonic()
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop,
            name="jelly-dict-tts-broker",
            daemon=True,
        )
        self._dispatcher.start()

    @property
    def pid(self) -> int | None:
        with self._process_lock:
            process = self._process
            return process.pid if process is not None and process.poll() is None else None

    def request(
        self,
        payload: dict[str, Any],
        *,
        priority: int = INTERACTIVE_PRIORITY,
        timeout: float = 240.0,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _MAX_MESSAGE_BYTES:
            raise TtsBrokerError("TTS broker request exceeds bounded IPC limit")
        with self._lock:
            if self._closed:
                raise TtsBrokerError("TTS broker is closed")
            self._sequence += 1
            request = _BrokerRequest(
                priority,
                self._sequence,
                dict(payload),
                max(0.1, timeout),
                cancel_event,
            )
            self._requests.put(request)

        deadline = time.monotonic() + request.timeout
        while not request.done.wait(timeout=0.05):
            if cancel_event is not None and cancel_event.is_set():
                request.cancelled.set()
                self._interrupt_if_active(request)
            if time.monotonic() >= deadline:
                request.cancelled.set()
                self._interrupt_if_active(request)
                request.error = TtsBrokerTimeout("TTS broker request timed out")
                request.done.set()
                break
        if request.error is not None:
            raise request.error
        return dict(request.result or {})

    def close(self, *, timeout: float = 5.0) -> bool:
        with self._lock:
            if self._closed:
                return self.pid is None and not self._dispatcher.is_alive()
            self._closed = True
            active = self._active
            if active is not None:
                active.cancelled.set()
            while True:
                try:
                    pending = self._requests.get_nowait()
                except queue.Empty:
                    break
                pending.error = TtsBrokerCancelled("TTS broker closed")
                pending.done.set()
        self._terminate_process(graceful=False)
        self._dispatcher.join(timeout=max(0.1, timeout))
        return not self._dispatcher.is_alive() and self.pid is None

    def _dispatch_loop(self) -> None:
        while True:
            with self._lock:
                if self._closed:
                    break
            try:
                request = self._requests.get(timeout=0.05)
            except queue.Empty:
                if (
                    self.pid is not None
                    and time.monotonic() - self._last_activity >= self._idle_timeout
                ):
                    self._terminate_process(graceful=True)
                continue
            if request.done.is_set() or request.cancelled.is_set():
                if not request.done.is_set():
                    request.error = TtsBrokerCancelled("TTS request cancelled")
                    request.done.set()
                continue
            with self._lock:
                self._active = request
            try:
                request.result = self._execute_with_restart(request)
            except BaseException as exc:
                if request.error is None:
                    request.error = exc
            finally:
                with self._lock:
                    if self._active is request:
                        self._active = None
                self._last_activity = time.monotonic()
                request.done.set()
        self._terminate_process(graceful=False)

    def _execute_with_restart(self, request: _BrokerRequest) -> dict[str, Any]:
        last_error: BaseException | None = None
        for attempt in range(2):
            if request.cancelled.is_set():
                raise TtsBrokerCancelled("TTS request cancelled")
            try:
                return self._execute_once(request)
            except (BrokenPipeError, EOFError, OSError, json.JSONDecodeError) as exc:
                last_error = exc
                self._terminate_process(graceful=False)
                if attempt == 0 and not request.cancelled.is_set():
                    log.warning("TTS broker worker crashed; restarting once")
                    continue
                break
        if request.cancelled.is_set():
            raise TtsBrokerCancelled("TTS request cancelled")
        raise TtsBrokerError(f"TTS broker worker failed: {last_error}")

    def _execute_once(self, request: _BrokerRequest) -> dict[str, Any]:
        process = self._ensure_process()
        request_id = uuid.uuid4().hex
        message = dict(request.payload)
        message["id"] = request_id
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if process.stdin is None or process.stdout is None:
            raise BrokenPipeError("TTS broker pipes unavailable")
        process.stdin.write(encoded + "\n")
        process.stdin.flush()
        line = process.stdout.readline(_MAX_MESSAGE_BYTES + 1)
        if not line:
            raise EOFError("TTS broker worker exited")
        if len(line.encode("utf-8")) > _MAX_MESSAGE_BYTES:
            raise OSError("TTS broker response exceeds bounded IPC limit")
        response = json.loads(line)
        if not isinstance(response, dict) or response.get("id") != request_id:
            raise OSError("TTS broker response id mismatch")
        if not response.get("ok", False):
            error_type = str(response.get("error_type") or "TtsWorkerError")
            error = str(response.get("error") or "TTS worker request failed")
            raise TtsBrokerError(f"{error_type}: {error}")
        return response

    def _ensure_process(self) -> subprocess.Popen[str]:
        with self._process_lock:
            process = self._process
            if process is not None and process.poll() is None:
                return process
            env = os.environ.copy()
            env.update(self._extra_env)
            env["PYTHONNOUSERSITE"] = "1"
            python_path = env.get("PYTHONPATH", "")
            app_root = str(_APP_ROOT)
            env["PYTHONPATH"] = (
                app_root if not python_path else f"{app_root}{os.pathsep}{python_path}"
            )
            kwargs: dict[str, Any] = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "bufsize": 1,
                "cwd": str(_APP_ROOT),
                "env": env,
            }
            if os.name == "posix":
                kwargs["start_new_session"] = True
            process = subprocess.Popen(self._command, **kwargs)
            self._process = process
            self._stderr_tail.clear()
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                args=(process,),
                name="jelly-dict-tts-broker-stderr",
                daemon=True,
            )
            self._stderr_thread.start()
            log.info("TTS broker worker started pid=%s", process.pid)
            return process

    def _drain_stderr(self, process: subprocess.Popen[str]) -> None:
        stream = process.stderr
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                self._stderr_tail.append(line.rstrip("\r\n")[-4000:])
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _interrupt_if_active(self, request: _BrokerRequest) -> None:
        with self._lock:
            active = self._active
        if active is request:
            self._terminate_process(graceful=False)

    def _terminate_process(self, *, graceful: bool) -> None:
        with self._process_lock:
            process = self._process
            if process is None:
                return
            if graceful and process.poll() is None and process.stdin is not None:
                try:
                    process.stdin.write(
                        json.dumps({"id": uuid.uuid4().hex, "action": "shutdown"}) + "\n"
                    )
                    process.stdin.flush()
                    process.wait(timeout=2.0)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    pass
            if process.poll() is None:
                _terminate_process_group(process)
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                _kill_process_group(process)
                process.wait()
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            stderr_thread = self._stderr_thread
            if stderr_thread is not None:
                stderr_thread.join(timeout=1.0)
            self._stderr_thread = None
            if self._process is process:
                self._process = None
            log.info("TTS broker worker stopped pid=%s", process.pid)


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:  # pragma: no cover
            process.terminate()
        process.wait(timeout=2.0)
    except (ProcessLookupError, PermissionError):
        return
    except subprocess.TimeoutExpired:
        _kill_process_group(process)


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover
            process.kill()
    except (ProcessLookupError, PermissionError):
        pass


_DEFAULT_BROKER: TtsBroker | None = None
_DEFAULT_LOCK = threading.Lock()


def get_tts_broker() -> TtsBroker:
    global _DEFAULT_BROKER
    with _DEFAULT_LOCK:
        if _DEFAULT_BROKER is None or _DEFAULT_BROKER._closed:
            _DEFAULT_BROKER = TtsBroker()
        return _DEFAULT_BROKER


def close_tts_broker() -> bool:
    global _DEFAULT_BROKER
    with _DEFAULT_LOCK:
        broker = _DEFAULT_BROKER
        _DEFAULT_BROKER = None
    return True if broker is None else broker.close()


class BrokerTtsPipeline:
    """TTSPipeline-compatible APKG adapter backed by the managed worker."""

    def __init__(self, settings: Any, broker: TtsBroker | None = None) -> None:
        self._settings = settings
        self._broker = broker or get_tts_broker()

    def synthesize(
        self,
        text: str,
        language: str,
        batch: Any | None = None,
    ) -> Path | None:
        from app.tts.audio_cache import is_valid_audio_file
        from app.tts.audio_service import cached_audio_path_for_text, tts_configured

        cached = cached_audio_path_for_text(text, language, self._settings)
        if cached is not None:
            path = cached
            engine = (
                self._settings.tts_engine_ja if language == "ja" else self._settings.tts_engine_en
            )
            voice = self._settings.tts_voice_ja if language == "ja" else self._settings.tts_voice_en
            credits = (f"VOICEVOX:{voice.split(':', 1)[-1]}",) if engine == "voicevox" else ()
        else:
            if not tts_configured(self._settings, language):
                return None
            result = self._broker.request(
                {
                    "action": "synthesize_text",
                    "text": text,
                    "language": language,
                    "settings": self._settings.to_dict(),
                },
                priority=EXPORT_PRIORITY,
                timeout=240,
            )
            raw_path = result.get("path")
            path = Path(str(raw_path)).expanduser() if raw_path else None
            if path is None or not is_valid_audio_file(path):
                return None
            credits = tuple(str(item) for item in result.get("credits") or ())
        if batch is not None:
            batch.add_media(path)
            batch.credits.update(credits)
        return path
