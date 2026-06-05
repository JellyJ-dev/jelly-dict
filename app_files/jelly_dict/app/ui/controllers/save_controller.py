from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6 import QtWidgets

from app.core.models import VocabularyEntry
from app.services.save_service import SaveService
from app.ui.preview_editor_view import PreviewEditorView
from app.ui.word_input_view import WordInputView

log = logging.getLogger(__name__)


class SaveController:
    def __init__(
        self,
        *,
        parent: QtWidgets.QWidget,
        input_view: WordInputView,
        preview_view: PreviewEditorView,
        stack: QtWidgets.QStackedLayout,
        input_page: QtWidgets.QWidget,
        preview_page: QtWidgets.QWidget,
        save_service: SaveService,
        settings_getter: Callable[[], object],
        status_bar,
        abort_lookup_queue: Callable[[], None],
        schedule_next_lookup: Callable[[], None],
        start_saved_words_cache_load: Callable[[], None],
        queue_tts_pre_generation: Callable[[VocabularyEntry], None],
        refresh_recent: Callable[[bool], None],
        preview_cancelled: Callable[[], None],
    ) -> None:
        self._parent = parent
        self._input_view = input_view
        self._preview_view = preview_view
        self._stack = stack
        self._input_page = input_page
        self._preview_page = preview_page
        self._save_service = save_service
        self._settings_getter = settings_getter
        self._status = status_bar
        self._abort_lookup_queue = abort_lookup_queue
        self._schedule_next_lookup = schedule_next_lookup
        self._start_saved_words_cache_load = start_saved_words_cache_load
        self._queue_tts_pre_generation = queue_tts_pre_generation
        self._refresh_recent = refresh_recent
        self._preview_cancelled = preview_cancelled

    def update_save_service(self, save_service: SaveService) -> None:
        self._save_service = save_service

    def present_entry(self, entry: VocabularyEntry, force_preview: bool = False) -> None:
        settings = self._settings_getter()
        if getattr(settings, "show_preview", False) or force_preview:
            self._preview_view.set_entry(entry)
            self._stack.setCurrentWidget(self._preview_page)
        else:
            self.save_entry(entry)

    def save_entry(self, entry: VocabularyEntry) -> None:
        try:
            outcome = self._save_service.save(entry)
        except Exception as exc:
            log.exception("save failed")
            QtWidgets.QMessageBox.critical(self._parent, "저장 실패", str(exc))
            self._abort_lookup_queue()
            return

        self._start_saved_words_cache_load()
        self._queue_tts_pre_generation(outcome.entry)

        message = f"저장됨 ({outcome.status}) → {outcome.path}"
        if outcome.backup_path is not None:
            message += f" · 백업: {outcome.backup_path}"
        self._status.showMessage(message)
        self.return_to_input()
        self._refresh_recent(True)
        self._schedule_next_lookup()

    def return_to_input(self) -> None:
        self._stack.setCurrentWidget(self._input_page)
        self._input_view.reset_input()

    def preview_save(self, entry: VocabularyEntry) -> None:
        self.save_entry(entry)

    def preview_cancelled(self) -> None:
        self._preview_cancelled()
