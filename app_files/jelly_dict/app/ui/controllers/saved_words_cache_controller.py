from __future__ import annotations

import time
from collections.abc import Callable

from PySide6 import QtCore

from app.storage.settings_store import Settings
from app.ui.controllers.wordbook_controller import WordbookController
from app.ui.saved_words_worker import SavedWordsWorker
from app.ui.startup_perf import StartupPerf
from app.ui.word_input_view import WordInputView


class SavedWordsCacheController(QtCore.QObject):
    def __init__(
        self,
        parent: QtCore.QObject,
        settings_getter: Callable[[], Settings],
        input_view: WordInputView,
        wordbook_ctrl: WordbookController,
        refresh_recent_if_visible: Callable[[], None],
        startup_perf: StartupPerf,
    ) -> None:
        super().__init__(parent)
        self._settings_getter = settings_getter
        self._input_view = input_view
        self._wordbook_ctrl = wordbook_ctrl
        self._refresh_recent_if_visible = refresh_recent_if_visible
        self._startup_perf = startup_perf
        self._thread: QtCore.QThread | None = None
        self._worker: SavedWordsWorker | None = None
        self._started: float | None = None

    def start(self) -> None:
        if self._thread is not None:
            try:
                if self._thread.isRunning():
                    return
            except RuntimeError:
                self._clear_worker()
        self._started = time.perf_counter()
        thread = QtCore.QThread(self)
        worker = SavedWordsWorker(self._settings_getter())
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ready)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_worker)
        self._thread = thread
        self._worker = worker
        thread.start()

    def stop(self) -> bool:
        thread = self._thread
        if thread is None:
            return True
        try:
            if thread.isRunning():
                thread.quit()
                if not thread.wait(2000):
                    return False
        except RuntimeError:
            pass
        self._clear_worker()
        return True

    @QtCore.Slot()
    def _clear_worker(self) -> None:
        self._thread = None
        self._worker = None

    @QtCore.Slot(object)
    def _on_ready(self, saved_words: object) -> None:
        if isinstance(saved_words, set):
            self._wordbook_ctrl.set_saved_words_cache(saved_words)
            if self._input_view._list_mode == "recent":
                self._refresh_recent_if_visible()
            self._startup_perf.mark("saved_words_cache", start=self._started)
        self._started = None
