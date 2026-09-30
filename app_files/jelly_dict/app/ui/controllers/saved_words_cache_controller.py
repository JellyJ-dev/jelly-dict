from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from PySide6 import QtCore

from app.core.settings import AppSettings, SettingsDraft, settings_snapshot
from app.storage.excel_repository import WorkbookRepository
from app.ui.controllers.wordbook_controller import WordbookController
from app.ui.saved_words_worker import load_saved_words
from app.ui.startup_perf import StartupPerf
from app.ui.word_input_view import WordInputView

log = logging.getLogger(__name__)


class SavedWordsCacheController(QtCore.QObject):
    _load_finished = QtCore.Signal(object, float, int)

    def __init__(
        self,
        parent: QtCore.QObject,
        settings_getter: Callable[[], AppSettings | SettingsDraft],
        input_view: WordInputView,
        wordbook_ctrl: WordbookController,
        refresh_recent_if_visible: Callable[[], None],
        startup_perf: StartupPerf,
        workbook_repository: WorkbookRepository | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_getter = settings_getter
        self._input_view = input_view
        self._wordbook_ctrl = wordbook_ctrl
        self._refresh_recent_if_visible = refresh_recent_if_visible
        self._startup_perf = startup_perf
        self._workbook_repository = workbook_repository
        self._thread: threading.Thread | None = None
        self._started: float | None = None
        self._closed = False
        self._requested_generation = 0
        self._active_generation = 0
        self._dirty = False
        self._load_finished.connect(self._on_thread_ready)

    def start(self) -> None:
        self._closed = False
        self._requested_generation += 1
        if self._thread is not None:
            # Coalesce any number of refreshes into one rerun that captures
            # the newest settings after the active scan completes.
            self._dirty = True
            return
        self._start_generation(self._requested_generation)

    def _start_generation(self, generation: int) -> None:
        self._started = time.perf_counter()
        settings = settings_snapshot(self._settings_getter())
        started = self._started
        self._active_generation = generation
        self._dirty = False
        thread = threading.Thread(
            target=self._load_in_background,
            args=(settings, started, generation),
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
        self._dirty = False
        self._requested_generation += 1
        thread.join(timeout=2.0)
        if thread.is_alive():
            return False
        self._thread = None
        return True

    def _load_in_background(
        self,
        settings: AppSettings,
        started: float | None,
        generation: int,
    ) -> None:
        try:
            if self._workbook_repository is None:
                saved_words = load_saved_words(settings)
            else:
                saved_words = load_saved_words(
                    settings,
                    self._workbook_repository,
                )
        except Exception:
            # Never strand the controller in an active generation if an
            # unexpected adapter error escapes the normal per-file handling.
            log.exception("saved words cache generation failed")
            saved_words = set()
        self._load_finished.emit(
            saved_words,
            started or 0.0,
            generation,
        )

    @QtCore.Slot(object, float, int)
    def _on_thread_ready(
        self,
        saved_words: object,
        started: float,
        generation: int,
    ) -> None:
        if generation != self._active_generation:
            return
        self._thread = None
        if self._closed:
            return
        if generation != self._requested_generation or self._dirty:
            self._start_generation(self._requested_generation)
            return
        self._on_ready(saved_words, started=started)

    @QtCore.Slot(object)
    def _on_ready(self, saved_words: object, *, started: float | None = None) -> None:
        if isinstance(saved_words, set):
            self._wordbook_ctrl.set_saved_words_cache(saved_words)
            if self._input_view._list_mode == "recent":
                self._refresh_recent_if_visible()
            self._startup_perf.mark("saved_words_cache", start=started or self._started)
        self._started = None
