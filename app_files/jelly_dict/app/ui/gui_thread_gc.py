"""Keep cyclic Python garbage collection on Qt's GUI thread.

Python may run an automatic cyclic collection in whichever thread happens to
cross a GC allocation threshold.  A cycle can retain a PySide wrapper after a
dialog has closed, so collecting that cycle in a browser or workbook worker
can destroy a QWidget outside the GUI thread.  Qt widgets must only be
destroyed on the GUI thread.
"""

from __future__ import annotations

import gc
import logging

from PySide6 import QtCore

log = logging.getLogger(__name__)


class GuiThreadGarbageCollector(QtCore.QObject):
    """Disable automatic cyclic GC and collect periodically on our Qt thread."""

    DEFAULT_INTERVAL_MS = 5_000

    def __init__(
        self,
        parent: QtCore.QObject,
        *,
        interval_ms: int = DEFAULT_INTERVAL_MS,
    ) -> None:
        super().__init__(parent)
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        if QtCore.QThread.currentThread() != QtCore.QObject.thread(self):
            raise RuntimeError("GUI-thread garbage collector must be created on its Qt thread")

        self._closed = False
        self._gc_was_enabled = gc.isenabled()
        gc.disable()

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.collect_now)
        self._timer.start()
        log.info("cyclic GC pinned to GUI thread (interval_ms=%s)", interval_ms)

    @QtCore.Slot()
    def collect_now(self) -> int:
        if QtCore.QThread.currentThread() != QtCore.QObject.thread(self):
            raise RuntimeError("cyclic GC must run on the GUI thread")
        return gc.collect()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self.collect_now()
        if self._gc_was_enabled:
            gc.enable()
