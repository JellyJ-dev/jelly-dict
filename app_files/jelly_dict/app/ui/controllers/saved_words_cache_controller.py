from __future__ import annotations

import time
import threading
from collections.abc import Callable

from PySide6 import QtCore

from app.storage.settings_store import Settings
from app.ui.controllers.wordbook_controller import WordbookController
from app.ui.saved_words_worker import load_saved_words
from app.ui.startup_perf import StartupPerf
from app.ui.word_input_view import WordInputView


class SavedWordsCacheController(QtCore.QObject):
    _load_finished = QtCore.Signal(object, float)

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
        self._thread: threading.Thread | None = None
        self._started: float | None = None
        self._closed = False
        self._load_finished.connect(self._on_thread_ready)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._closed = False
        self._started = time.perf_counter()
        settings = Settings(**self._settings_getter().to_dict())
        started = self._started
        thread = threading.Thread(
            target=self._load_in_background,
            args=(settings, started),
            name="jelly-dict-saved-words-cache",
            daemon=True,
        )
        self._thread = thread
        thread.start()

    def stop(self) -> bool:
        thread = self._thread
        if thread is None:
            return True
        self._closed = True
        thread.join(timeout=2.0)
        if thread.is_alive():
            return False
        self._thread = None
        return True

    def _load_in_background(self, settings: Settings, started: float | None) -> None:
        self._load_finished.emit(load_saved_words(settings), started or 0.0)

    @QtCore.Slot(object, float)
    def _on_thread_ready(self, saved_words: object, started: float) -> None:
        if self._closed:
            self._thread = None
            return
        self._thread = None
        self._on_ready(saved_words, started=started)

    @QtCore.Slot(object)
    def _on_ready(self, saved_words: object, *, started: float | None = None) -> None:
        if isinstance(saved_words, set):
            self._wordbook_ctrl.set_saved_words_cache(saved_words)
            if self._input_view._list_mode == "recent":
                self._refresh_recent_if_visible()
            self._startup_perf.mark("saved_words_cache", start=started or self._started)
        self._started = None
