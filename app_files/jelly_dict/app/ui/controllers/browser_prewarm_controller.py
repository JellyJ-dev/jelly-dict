from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6 import QtCore, QtWidgets

from app.dictionary.base import DictionaryProvider
from app.ui.startup_perf import StartupPerf

log = logging.getLogger(__name__)


class BrowserPrewarmController(QtCore.QObject):
    def __init__(
        self,
        parent: QtCore.QObject,
        provider_getter: Callable[[], DictionaryProvider],
        startup_perf: StartupPerf,
    ) -> None:
        super().__init__(parent)
        self._provider_getter = provider_getter
        self._startup_perf = startup_perf
        self._started = False
        self._closed = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(900)
        self._timer.timeout.connect(self._prewarm)

    def schedule(self) -> None:
        if self._started or self._closed:
            return
        self._timer.start()

    def close(self) -> bool:
        self._closed = True
        self._timer.stop()
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        provider = self._provider_getter()
        cancel_prewarm = getattr(provider, "cancel_prewarm", None)
        if callable(cancel_prewarm):
            cancel_prewarm()
        thread.join(timeout=6.0)
        if thread.is_alive():
            log.warning("browser prewarm thread did not stop; ownership retained")
            return False
        with self._lock:
            if self._thread is thread:
                self._thread = None
        return True

    def _prewarm(self) -> None:
        """Warm Playwright only after real user input.

        Lookup still starts Playwright lazily when needed; this path is only
        an interactive latency optimization.
        """
        if self._started or self._closed:
            return
        platform = QtWidgets.QApplication.platformName().lower()
        if platform in {"offscreen", "minimal"}:
            return
        provider = self._provider_getter()
        prewarm = getattr(provider, "prewarm", None)
        if not callable(prewarm):
            return
        self._started = True

        def warm() -> None:
            try:
                if self._closed:
                    return
                with self._startup_perf.span("playwright_prewarm"):
                    prewarm()
                if self._closed:
                    cancel_prewarm = getattr(provider, "cancel_prewarm", None)
                    if callable(cancel_prewarm):
                        cancel_prewarm()
                    return
                log.info("playwright pre-warmed")
            except Exception as exc:
                log.warning("pre-warm failed: %s", exc)
            finally:
                current = threading.current_thread()
                with self._lock:
                    if self._thread is current:
                        self._thread = None

        thread = threading.Thread(
            target=warm,
            name="jelly-dict-prewarm",
            daemon=True,
        )
        with self._lock:
            if self._closed:
                return
            self._thread = thread
        thread.start()
