"""Shared QThread task ownership, stale-signal guards, and close policy."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from typing import Any, Literal

from PySide6 import QtCore

log = logging.getLogger(__name__)


class TaskState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    FINISHING = "finishing"
    CANCELLING = "cancelling"
    FAILED = "failed"


class TaskTerminal(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCEL = "cancel"


@dataclass(frozen=True)
class TaskPolicy:
    cooperative_cancel: bool = False
    close_policy: Literal["block", "cancel"] = "block"
    wait_timeout_ms: int = 2000


@dataclass(frozen=True)
class TaskOutcome:
    token: int
    terminal: TaskTerminal
    values: tuple[Any, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class TerminalBinding:
    signal: Any
    terminal: TaskTerminal | Callable[..., TaskTerminal]
    handler: Callable[..., None]


@dataclass(frozen=True)
class SignalBinding:
    signal: Any
    handler: Callable[..., None]


@dataclass
class _ActiveTask:
    token: int
    thread: QtCore.QThread
    worker: QtCore.QObject
    relays: list[_SignalRelay] = field(default_factory=list)
    terminal: TaskOutcome | None = None
    handling_terminal: bool = False
    thread_finished: bool = False


class _SignalRelay(QtCore.QObject):
    """Give dynamic Python callbacks QObject thread affinity."""

    def __init__(self, callback: Callable[..., None]) -> None:
        super().__init__()
        self._callback = callback

    def forward(self, *values) -> None:
        self._callback(*values)


def _return_worker_to_thread(
    worker: QtCore.QObject,
    owner_thread: QtCore.QThread,
    task_name: str,
    *_terminal_values: object,
) -> None:
    """Return a parentless task worker to its owner's thread before deletion."""
    try:
        affinity = worker.thread()
        if affinity is owner_thread:
            return
        moved = worker.moveToThread(owner_thread)
        if moved is False:
            log.warning("%s worker could not return to owner thread", task_name)
    except RuntimeError as exc:
        log.warning("%s worker affinity cleanup failed: %s", task_name, exc)


class TaskSupervisor(QtCore.QObject):
    stateChanged = QtCore.Signal(object)
    terminal = QtCore.Signal(object)

    def __init__(
        self,
        parent: QtCore.QObject | None = None,
        *,
        policy: TaskPolicy | None = None,
        name: str = "task",
    ) -> None:
        super().__init__(parent)
        self._policy = policy or TaskPolicy()
        self._name = name
        self._state = TaskState.IDLE
        self._generation = 0
        self._active: _ActiveTask | None = None
        self._last_outcome: TaskOutcome | None = None

    @property
    def state(self) -> TaskState:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def last_outcome(self) -> TaskOutcome | None:
        return self._last_outcome

    @property
    def thread(self) -> QtCore.QThread | None:
        active = self._active
        return active.thread if active is not None else None

    @property
    def worker(self) -> QtCore.QObject | None:
        active = self._active
        return active.worker if active is not None else None

    def is_current(self, token: int) -> bool:
        active = self._active
        return active is not None and active.token == token

    def is_running(self) -> bool:
        active = self._active
        if active is None:
            return False
        try:
            return active.thread.isRunning() or self._state is not TaskState.IDLE
        except RuntimeError:
            return self._state is not TaskState.IDLE

    def start(
        self,
        worker: QtCore.QObject,
        *,
        run: Callable[[], None],
        terminal_bindings: Sequence[TerminalBinding],
        signal_bindings: Sequence[SignalBinding] = (),
    ) -> int:
        if self._active is not None:
            raise RuntimeError(f"{self._name} is already active")
        if not terminal_bindings:
            raise ValueError("at least one terminal signal is required")

        self._generation += 1
        token = self._generation
        thread = QtCore.QThread(self)
        active = _ActiveTask(token, thread, worker)
        self._active = active
        self._set_state(TaskState.STARTING)

        owner_thread = QtCore.QObject.thread(self)
        worker.moveToThread(thread)
        return_worker_to_owner_thread = partial(
            _return_worker_to_thread,
            worker,
            owner_thread,
            self._name,
        )

        started_relay = _SignalRelay(lambda current=token: self._mark_running(current))
        active.relays.append(started_relay)
        thread.started.connect(started_relay.forward)
        thread.started.connect(run)

        for binding in signal_bindings:
            wrapper = self._signal_wrapper(token, binding.handler)
            relay = _SignalRelay(wrapper)
            active.relays.append(relay)
            binding.signal.connect(relay.forward)

        for binding in terminal_bindings:
            # A terminal signal is emitted from ``run`` on the worker thread.
            # Move the parentless worker back before stopping that thread so
            # ``thread.finished -> deleteLater`` queues its destruction on the
            # GUI thread instead of racing another Shiboken wrapper teardown.
            binding.signal.connect(
                return_worker_to_owner_thread,
                QtCore.Qt.ConnectionType.DirectConnection,
            )
            wrapper = self._terminal_wrapper(
                token,
                binding.terminal,
                binding.handler,
            )
            relay = _SignalRelay(wrapper)
            active.relays.append(relay)
            binding.signal.connect(relay.forward)
            binding.signal.connect(
                thread.quit,
                QtCore.Qt.ConnectionType.DirectConnection,
            )

        thread.finished.connect(worker.deleteLater)
        finished_relay = _SignalRelay(
            lambda current=token, owned_thread=thread: self._thread_finished(
                current,
                owned_thread,
            )
        )
        active.relays.append(finished_relay)
        thread.finished.connect(finished_relay.forward)
        try:
            thread.start()
        except Exception as exc:
            self._active = None
            self._set_state(TaskState.IDLE)
            raise RuntimeError(f"failed to start {self._name}") from exc
        return token

    def request_cancel(self) -> bool:
        active = self._active
        if active is None:
            return True
        self._set_state(TaskState.CANCELLING)
        active.thread.requestInterruption()
        if self._policy.cooperative_cancel:
            cancel = getattr(active.worker, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception as exc:
                    log.warning("%s cooperative cancel failed: %s", self._name, exc)
        active.thread.quit()
        return True

    def close(self) -> bool:
        active = self._active
        if active is None:
            return True
        if active.handling_terminal:
            log.warning("%s completion handler still active; ownership retained", self._name)
            return False
        if self._policy.close_policy == "cancel":
            self.request_cancel()
        else:
            active.thread.quit()
        try:
            finished = active.thread.wait(self._policy.wait_timeout_ms)
        except RuntimeError:
            return self._active is None
        if finished:
            if self._active is active:
                outcome = active.terminal or TaskOutcome(
                    active.token,
                    TaskTerminal.CANCEL,
                    detail="task closed before queued terminal delivery",
                )
                self._finalize_active(active, outcome)
            return True
        log.warning(
            "%s thread did not stop within %sms; ownership retained",
            self._name,
            self._policy.wait_timeout_ms,
        )
        return False

    def _signal_wrapper(
        self,
        token: int,
        handler: Callable[..., None],
    ) -> Callable[..., None]:
        def guarded(*values) -> None:
            if not self.is_current(token):
                return
            handler(*values)

        return guarded

    def _terminal_wrapper(
        self,
        token: int,
        terminal: TaskTerminal | Callable[..., TaskTerminal],
        handler: Callable[..., None],
    ) -> Callable[..., None]:
        def guarded(*values) -> None:
            active = self._active
            if active is None or active.token != token or active.terminal is not None:
                return
            cancelling = self._state is TaskState.CANCELLING
            resolved_terminal = terminal(*values) if callable(terminal) else terminal
            effective_terminal = TaskTerminal.CANCEL if cancelling else resolved_terminal
            active.terminal = TaskOutcome(
                token,
                effective_terminal,
                tuple(values),
            )
            active.handling_terminal = True
            self._set_state(
                TaskState.FINISHING
                if effective_terminal is TaskTerminal.SUCCESS
                else TaskState.FAILED
                if effective_terminal is TaskTerminal.FAILURE
                else TaskState.CANCELLING
            )
            try:
                if not cancelling:
                    handler(*values)
            except Exception:
                log.exception("%s terminal handler failed", self._name)
            finally:
                active.handling_terminal = False
                if self._active is active:
                    if active.thread_finished:
                        self._finalize_active(active, active.terminal)
                    else:
                        active.thread.quit()

        return guarded

    def _mark_running(self, token: int) -> None:
        if self.is_current(token) and self._state is TaskState.STARTING:
            self._set_state(TaskState.RUNNING)

    def _thread_finished(
        self,
        token: int,
        thread: QtCore.QThread,
        *,
        deferred: bool = False,
    ) -> None:
        active = self._active
        if active is None or active.token != token or active.thread is not thread:
            return
        active.thread_finished = True
        # A terminal handler can open a modal dialog, running a nested Qt event
        # loop. Keep the task and QThread alive until the user's decision has
        # returned; consumers must not receive completion before their handler
        # has prepared the next stage (such as a save commit or language retry).
        if active.handling_terminal:
            return
        if active.terminal is None and not deferred:
            QtCore.QTimer.singleShot(
                0,
                lambda: self._thread_finished(
                    token,
                    thread,
                    deferred=True,
                ),
            )
            return
        outcome = active.terminal
        if outcome is None:
            terminal = (
                TaskTerminal.CANCEL if self._state is TaskState.CANCELLING else TaskTerminal.FAILURE
            )
            outcome = TaskOutcome(
                token,
                terminal,
                detail="thread finished without a terminal worker signal",
            )
        self._finalize_active(active, outcome)

    def _finalize_active(
        self,
        active: _ActiveTask,
        outcome: TaskOutcome,
    ) -> None:
        if self._active is not active:
            return
        self._last_outcome = outcome
        relays = tuple(active.relays)
        self._active = None
        self._set_state(TaskState.IDLE)
        self.terminal.emit(outcome)
        active.thread.deleteLater()
        for relay in relays:
            relay.deleteLater()

    def _set_state(self, state: TaskState) -> None:
        if state is self._state:
            return
        self._state = state
        self.stateChanged.emit(state)
