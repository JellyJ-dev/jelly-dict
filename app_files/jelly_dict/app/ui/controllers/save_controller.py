from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6 import QtCore, QtWidgets

from app.core.duplicate_checker import DuplicateDecision
from app.core.models import VocabularyEntry
from app.services.save_service import PreparedSave, SaveOutcome, SaveService
from app.ui.async_task import TaskSupervisor, TaskTerminal, TerminalBinding
from app.ui.preview_editor_view import PreviewEditorView
from app.ui.save_worker import SaveCommitWorker, SavePrepareWorker
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
        commit_saved_projection: Callable[[SaveOutcome], None] | None = None,
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
        self._commit_saved_projection = commit_saved_projection
        task_parent = parent if isinstance(parent, QtCore.QObject) else None
        self._async_enabled = task_parent is not None
        self._prepare_task = TaskSupervisor(task_parent, name="save-prepare")
        self._commit_task = TaskSupervisor(task_parent, name="save-commit")
        self._prepare_task.terminal.connect(self._on_prepare_terminal)
        self._active_save_service: SaveService | None = None
        self._pending_commit: tuple[SaveService, PreparedSave, DuplicateDecision | None] | None = (
            None
        )

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
        if not self._async_enabled:
            self._save_entry_sync(entry)
            return
        if self.is_running():
            return
        service = self._save_service
        self._active_save_service = service
        copied = VocabularyEntry.from_json(entry.to_json())
        worker = SavePrepareWorker(service, copied)
        self._prepare_task.start(
            worker,
            run=worker.run,
            terminal_bindings=[
                TerminalBinding(
                    worker.finished,
                    TaskTerminal.SUCCESS,
                    self._on_save_prepared,
                ),
                TerminalBinding(
                    worker.failed,
                    TaskTerminal.FAILURE,
                    self._on_save_failed,
                ),
            ],
        )

    def _save_entry_sync(self, entry: VocabularyEntry) -> None:
        try:
            outcome = self._save_service.save(entry)
        except Exception as exc:
            self._on_save_failed(str(exc))
            return
        self._complete_save(outcome)

    @QtCore.Slot(object)
    def _on_save_prepared(self, prepared_obj: object) -> None:
        if not isinstance(prepared_obj, PreparedSave):
            self._on_save_failed("저장 준비 결과가 올바르지 않습니다.")
            return
        service = self._active_save_service
        if service is None:
            self._on_save_failed("저장 서비스가 변경되었습니다.")
            return
        try:
            decision = (
                service.prompt_for_decision(prepared_obj)
                if prepared_obj.decision_required
                else None
            )
        except Exception as exc:
            self._on_save_failed(str(exc))
            return
        self._pending_commit = (service, prepared_obj, decision)

    @QtCore.Slot(object)
    def _on_prepare_terminal(self, _outcome: object) -> None:
        pending = self._pending_commit
        self._pending_commit = None
        if pending is None:
            return
        service, prepared, decision = pending
        worker = SaveCommitWorker(service, prepared, decision)
        self._commit_task.start(
            worker,
            run=worker.run,
            terminal_bindings=[
                TerminalBinding(
                    worker.finished,
                    TaskTerminal.SUCCESS,
                    self._on_save_committed,
                ),
                TerminalBinding(
                    worker.failed,
                    TaskTerminal.FAILURE,
                    self._on_save_failed,
                ),
            ],
        )

    @QtCore.Slot(object)
    def _on_save_committed(self, outcome_obj: object) -> None:
        if not isinstance(outcome_obj, SaveOutcome):
            self._on_save_failed("저장 결과가 올바르지 않습니다.")
            return
        self._complete_save(outcome_obj)

    def _complete_save(self, outcome: SaveOutcome) -> None:
        self._active_save_service = None

        if self._commit_saved_projection is not None:
            try:
                self._commit_saved_projection(outcome)
            except Exception as exc:
                log.warning("saved projection commit failed: %s", exc)

        self._start_saved_words_cache_load()
        self._queue_tts_pre_generation(outcome.entry)

        message = f"저장됨 ({outcome.status}) → {outcome.path}"
        if outcome.backup_path is not None:
            message += f" · 백업: {outcome.backup_path}"
        self._status.showMessage(message)
        self.return_to_input()
        self._refresh_recent(True)
        self._schedule_next_lookup()

    @QtCore.Slot(str)
    def _on_save_failed(self, message: str) -> None:
        self._active_save_service = None
        self._pending_commit = None
        log.error("save failed: %s", message)
        QtWidgets.QMessageBox.critical(self._parent, "저장 실패", message)
        self._abort_lookup_queue()

    def is_running(self) -> bool:
        return self._prepare_task.is_running() or self._commit_task.is_running()

    def close(self) -> bool:
        prepared = self._prepare_task.close()
        committed = self._commit_task.close()
        return prepared and committed

    def return_to_input(self) -> None:
        self._stack.setCurrentWidget(self._input_page)
        self._input_view.reset_input()

    def preview_save(self, entry: VocabularyEntry) -> None:
        self.save_entry(entry)

    def preview_cancelled(self) -> None:
        self._preview_cancelled()
