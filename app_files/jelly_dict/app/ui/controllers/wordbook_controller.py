"""Wordbook flows: inline display, deletion (Excel + cache + Anki), and
recent-entry detail dialog. Extracted from MainWindow for clarity.

All status bar messages, dialog buttons, and side-effects are
identical to the previous inline implementation.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from app.core.domain import EntryRef, WorkbookRevision
from app.core.models import VocabularyEntry, normalize_word_key
from app.core.settings import Settings
from app.services.lookup_service import LookupService
from app.services.ports import AnkiSyncPort, LookupCachePort, WorkbookRepositoryPort
from app.services.requery_entry import RequeryCommitResult, RequeryPlan
from app.services.wordbook_service import WordbookDeleteResult, WordbookService
from app.ui.async_task import TaskSupervisor, TaskTerminal, TerminalBinding
from app.ui.widgets.wordbook_items import WordbookDisplayItem
from app.ui.word_input_view import WordInputView
from app.ui.wordbook_worker import (
    AnkiDeleteWorker,
    AnkiRetryWorker,
    RequeryWorker,
    WordbookDeleteWorker,
    WordbookEditWorker,
    WordbookListWorker,
    WordbookUndoWorker,
    build_wordbook_items,
)

log = logging.getLogger(__name__)
if TYPE_CHECKING:
    from app.ui.entry_edit_dialog import EntryEditDialog


class WordbookController:
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        input_view: WordInputView,
        cache: LookupCachePort,
        anki_sync: AnkiSyncPort,
        settings: Settings,
        status_bar: QtWidgets.QStatusBar,
        lookup_service: LookupService | None = None,
        queue_tts_pre_generation=None,
        remember_last_view_mode=None,
        workbook_repository: WorkbookRepositoryPort | None = None,
        wordbook_service: WordbookService | None = None,
    ) -> None:
        self._parent = parent
        self._input_view = input_view
        self._cache = cache
        self._anki_sync = anki_sync
        self._settings = settings
        self._status = status_bar
        self._lookup_service = lookup_service
        self._queue_tts_pre_generation = queue_tts_pre_generation
        self._remember_last_view_mode = remember_last_view_mode
        self._wordbook_service = wordbook_service
        if self._wordbook_service is None:
            if workbook_repository is None:
                # Compatibility for older embedders.  Production composition
                # injects the service, keeping concrete storage out of this module.
                from app.storage.excel_repository import WorkbookRepository

                workbook_repository = WorkbookRepository()
            # Deprecated compatibility handle for external test/embedding code.
            # Controller methods do not perform repository I/O through it.
            self._workbook_repository = workbook_repository
            self._wordbook_service = WordbookService(
                settings,
                workbook_repository,
                cache,
                anki_sync,
            )
        else:
            self._workbook_repository = workbook_repository
        task_parent = parent if isinstance(parent, QtCore.QObject) else None
        self._async_enabled = task_parent is not None
        self._requery_task = TaskSupervisor(task_parent, name="wordbook-requery")
        self._list_task = (
            TaskSupervisor(task_parent, name="wordbook-list") if self._async_enabled else None
        )
        self._delete_task = (
            TaskSupervisor(task_parent, name="wordbook-delete") if self._async_enabled else None
        )
        self._undo_task = (
            TaskSupervisor(task_parent, name="wordbook-undo") if self._async_enabled else None
        )
        self._edit_task = (
            TaskSupervisor(task_parent, name="wordbook-edit") if self._async_enabled else None
        )
        self._anki_task = (
            TaskSupervisor(task_parent, name="wordbook-anki") if self._async_enabled else None
        )
        self._requery_task.terminal.connect(self._on_requery_task_terminal)
        if self._list_task is not None:
            self._list_task.terminal.connect(self._on_list_task_terminal)
        if self._anki_task is not None:
            self._anki_task.terminal.connect(self._on_anki_task_terminal)
        self._pending_inline_request: tuple[str, str] | None = None
        self._pending_anki_jobs: list[tuple[str, list[str], str, str | None]] = []
        self._requery_dialog: EntryEditDialog | None = None
        self._current_sort_option = "최신순"

    def update_settings(
        self,
        settings: Settings,
        anki_sync: AnkiSyncPort,
        lookup_service: LookupService | None = None,
    ) -> None:
        self._settings = settings
        self._anki_sync = anki_sync
        self._wordbook_service.update_settings(settings, anki_sync)
        if lookup_service is not None:
            self._lookup_service = lookup_service

    def set_saved_words_cache(self, saved_words: set[tuple[str, str]]) -> None:
        self._wordbook_service.set_saved_words(saved_words)

    # ---------- inline rendering ---------------------------------------

    def update_saved_words_cache(self) -> None:
        self._wordbook_service.refresh_saved_words()

    def is_word_saved(self, word: str, language: str) -> bool:
        return self._wordbook_service.is_saved(word, language)

    # ---------- inline rendering ---------------------------------------

    def show_inline(self, language: str, sort_option: str = "최신순") -> None:
        self._current_sort_option = sort_option
        language = language if language in ("en", "ja") else "en"
        if not self._async_enabled:
            self._input_view.set_wordbook(
                language,
                build_wordbook_items(self._wordbook_service, language, sort_option),
            )
            return
        request = (language, sort_option)
        assert self._list_task is not None
        if self._list_task.is_running():
            self._pending_inline_request = request
            return
        self._start_inline_load(*request)

    def _start_inline_load(self, language: str, sort_option: str) -> None:
        assert self._list_task is not None
        worker = WordbookListWorker(
            self._wordbook_service,
            language,
            sort_option,
        )
        self._list_task.start(
            worker,
            run=worker.run,
            terminal_bindings=[
                TerminalBinding(
                    worker.finished,
                    TaskTerminal.SUCCESS,
                    self._on_inline_loaded,
                ),
                TerminalBinding(
                    worker.failed,
                    TaskTerminal.FAILURE,
                    self._on_inline_load_failed,
                ),
            ],
        )

    @QtCore.Slot(str, str, object)
    def _on_inline_loaded(
        self,
        language: str,
        sort_option: str,
        items_obj: object,
    ) -> None:
        if self._pending_inline_request is not None:
            return
        if not isinstance(items_obj, list) or not all(
            isinstance(item, WordbookDisplayItem) for item in items_obj
        ):
            self._on_inline_load_failed("단어장 표시 결과가 올바르지 않습니다.")
            return
        self._current_sort_option = sort_option
        self._input_view.set_wordbook(language, items_obj)

    @QtCore.Slot(str)
    def _on_inline_load_failed(self, message: str) -> None:
        if self._pending_inline_request is None:
            self._status.showMessage(f"단어장 열기 실패: {message}")

    @QtCore.Slot(object)
    def _on_list_task_terminal(self, _outcome: object) -> None:
        pending = self._pending_inline_request
        self._pending_inline_request = None
        if pending is not None:
            self._start_inline_load(*pending)

    # ---------- deletion -----------------------------------------------

    def delete_entries(self, language: str, words_obj: object) -> None:
        language = language if language in ("en", "ja") else "en"
        words = (
            [word.strip() for word in words_obj if isinstance(word, str) and word.strip()]
            if isinstance(words_obj, list)
            else []
        )
        if not words:
            return

        selected_refs = self._selected_entry_refs(language, words)
        if selected_refs == ():
            self._status.showMessage("삭제할 단어를 찾을 수 없습니다.")
            return
        if self._async_enabled:
            assert self._delete_task is not None
            if self._delete_task.is_running():
                return
            worker = WordbookDeleteWorker(
                self._wordbook_service,
                language,
                words,
                selected_refs,
            )
            self._delete_task.start(
                worker,
                run=worker.run,
                terminal_bindings=[
                    TerminalBinding(
                        worker.finished,
                        TaskTerminal.SUCCESS,
                        self._on_delete_finished,
                    ),
                    TerminalBinding(
                        worker.failed,
                        TaskTerminal.FAILURE,
                        self._on_delete_failed,
                    ),
                ],
            )
            return
        try:
            result = (
                self._wordbook_service.delete_refs(language, selected_refs)
                if selected_refs
                else self._wordbook_service.delete_words(language, words)
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self._parent, "삭제 실패", str(exc))
            return
        self._complete_delete(language, result)

    @QtCore.Slot(str, object)
    def _on_delete_finished(self, language: str, result_obj: object) -> None:
        if not isinstance(result_obj, WordbookDeleteResult):
            self._on_delete_failed("삭제 결과가 올바르지 않습니다.")
            return
        self._complete_delete(language, result_obj)

    @QtCore.Slot(str)
    def _on_delete_failed(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self._parent, "삭제 실패", message)

    def _complete_delete(
        self,
        language: str,
        result: WordbookDeleteResult,
    ) -> None:
        path = Path(self._settings.excel_path_for(language))
        self.show_inline(language, self._current_sort_option)
        message = f"{'일본어' if language == 'ja' else '영어'} 단어장 {result.removed}개 삭제됨"
        if result.backup_path is not None:
            message += f" · 백업: {result.backup_path.name}"
        self._status.showMessage(message)
        self._show_delete_undo(
            language,
            path,
            result,
            list(result.anki_words),
        )

    def _selected_entry_refs(
        self,
        language: str,
        words: list[str],
    ) -> tuple[EntryRef, ...] | None:
        getter = getattr(self._input_view, "selected_wordbook_entry_refs", None)
        if not callable(getter):
            return None
        try:
            raw_refs = tuple(getter())
        except Exception as exc:
            log.warning("selected wordbook refs unavailable: %s", exc)
            return ()
        if not raw_refs:
            return None
        if not all(isinstance(ref, EntryRef) for ref in raw_refs):
            return ()
        refs = tuple(ref for ref in raw_refs if isinstance(ref, EntryRef))
        expected_keys = Counter(
            normalize_word_key(word, language)  # type: ignore[arg-type]
            for word in words
        )
        actual_keys = Counter(ref.word_key for ref in refs if ref.language == language)
        if len(refs) != len(words) or actual_keys != expected_keys:
            return ()
        return refs

    def _show_delete_undo(
        self,
        language: str,
        path: Path,
        outcome: WordbookDeleteResult,
        words: list[str],
    ) -> None:
        if outcome.removed <= 0:
            return
        show_undo_toast = getattr(self._parent, "show_undo_toast", None)
        if not callable(show_undo_toast):
            self._commit_anki_delete(
                words,
                language,
                outcome.deferred_anki_operation_id,
            )
            return
        pending = {"undone": False}

        def undo() -> None:
            pending["undone"] = True
            self._undo_delete(
                language,
                path,
                outcome,
                outcome.deferred_anki_operation_id,
            )

        def expire() -> None:
            if not pending["undone"]:
                self._commit_anki_delete(
                    words,
                    language,
                    outcome.deferred_anki_operation_id,
                )

        if self._anki_sync.enabled:
            try:
                show_undo_toast(
                    f"{outcome.removed}개를 삭제했습니다.",
                    undo,
                    expire,
                )
            except TypeError:
                show_undo_toast(f"{outcome.removed}개를 삭제했습니다.", undo)
                QtCore.QTimer.singleShot(3000, expire)
            return
        show_undo_toast(f"{outcome.removed}개를 삭제했습니다.", undo)

    def _commit_anki_delete(
        self,
        words: list[str],
        language: str,
        operation_id: str | None = None,
    ) -> None:
        if not words or not self._anki_sync.enabled:
            return
        if self._async_enabled:
            self._pending_anki_jobs.append(("delete", list(words), language, operation_id))
            self._start_next_anki_job()
            return
        removed, errors = self._wordbook_service.commit_anki_delete(
            words,
            language,
            operation_id,
        )
        if errors:
            log.warning("anki delete errors: %s", errors[:5])
            self._status.showMessage("Anki 일부 삭제 실패")
            return
        if removed:
            self._status.showMessage(f"Anki {removed}개 삭제됨")

    def retry_pending_anki_deletes(self) -> None:
        if self._async_enabled:
            self._pending_anki_jobs.append(("retry", [], "", None))
            self._start_next_anki_job()
            return
        try:
            self._wordbook_service.retry_pending_anki_deletes()
        except Exception as exc:
            log.warning("Anki delete outbox retry failed: %s", exc)

    def _start_next_anki_job(self) -> None:
        task = self._anki_task
        if task is None or task.is_running() or not self._pending_anki_jobs:
            return
        kind, words, language, operation_id = self._pending_anki_jobs.pop(0)
        if kind == "retry":
            worker = AnkiRetryWorker(self._wordbook_service)
            bindings = [
                TerminalBinding(
                    worker.finished,
                    TaskTerminal.SUCCESS,
                    lambda: None,
                ),
                TerminalBinding(
                    worker.failed,
                    TaskTerminal.FAILURE,
                    self._on_anki_retry_failed,
                ),
            ]
        else:
            worker = AnkiDeleteWorker(
                self._wordbook_service,
                words,
                language,
                operation_id,
            )
            bindings = [
                TerminalBinding(
                    worker.finished,
                    TaskTerminal.SUCCESS,
                    self._on_anki_delete_finished,
                ),
                TerminalBinding(
                    worker.failed,
                    TaskTerminal.FAILURE,
                    self._on_anki_retry_failed,
                ),
            ]
        task.start(worker, run=worker.run, terminal_bindings=bindings)

    @QtCore.Slot(int, object)
    def _on_anki_delete_finished(self, removed: int, errors_obj: object) -> None:
        errors = errors_obj if isinstance(errors_obj, list) else []
        if errors:
            log.warning("anki delete errors: %s", errors[:5])
            self._status.showMessage("Anki 일부 삭제 실패")
            return
        if removed:
            self._status.showMessage(f"Anki {removed}개 삭제됨")

    @QtCore.Slot(str)
    def _on_anki_retry_failed(self, message: str) -> None:
        log.warning("Anki delete worker failed: %s", message)
        self._status.showMessage("Anki 일부 삭제 실패")

    @QtCore.Slot(object)
    def _on_anki_task_terminal(self, _outcome: object) -> None:
        self._start_next_anki_job()

    def _undo_delete(
        self,
        language: str,
        path: Path,
        outcome: WordbookDeleteResult,
        operation_id: str | None = None,
    ) -> None:
        if self._async_enabled:
            assert self._undo_task is not None
            if self._undo_task.is_running():
                return
            worker = WordbookUndoWorker(
                self._wordbook_service,
                language,
                path,
                outcome,
                operation_id,
            )
            self._undo_task.start(
                worker,
                run=worker.run,
                terminal_bindings=[
                    TerminalBinding(
                        worker.finished,
                        TaskTerminal.SUCCESS,
                        self._on_undo_finished,
                    ),
                    TerminalBinding(
                        worker.failed,
                        TaskTerminal.FAILURE,
                        self._on_undo_failed,
                    ),
                ],
            )
            return
        try:
            self._wordbook_service.cancel_anki_delete(operation_id)
            count = self._wordbook_service.undo_delete(outcome, language, path)
        except Exception as exc:
            self._status.showMessage(f"삭제 되돌리기 실패: {exc}")
            return
        self.show_inline(language, self._current_sort_option)
        self._status.showMessage(f"{count}개 삭제를 되돌렸습니다.")

    @QtCore.Slot(str, int)
    def _on_undo_finished(self, language: str, count: int) -> None:
        self.show_inline(language, self._current_sort_option)
        self._status.showMessage(f"{count}개 삭제를 되돌렸습니다.")

    @QtCore.Slot(str)
    def _on_undo_failed(self, message: str) -> None:
        self._status.showMessage(f"삭제 되돌리기 실패: {message}")

    # ---------- editing / requery --------------------------------------

    def edit_entry(self, language: str, word: str) -> None:
        from app.ui.entry_edit_dialog import EntryEditDialog

        language = language if language in ("en", "ja") else "en"
        key = normalize_word_key(word, language)  # type: ignore[arg-type]
        selected_refs = self._selected_entry_refs(language, [word])
        if selected_refs == ():
            self._status.showMessage("수정할 단어를 찾을 수 없습니다.")
            return
        try:
            context = self._wordbook_service.edit_context(
                language,
                word,
                ref=(
                    selected_refs[0]
                    if selected_refs is not None and len(selected_refs) == 1
                    else None
                ),
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self._parent, "수정 실패", str(exc))
            return
        if context is None:
            self._status.showMessage("수정할 단어를 찾을 수 없습니다.")
            return
        row, revision = context

        entry = row.entry
        dialog = EntryEditDialog(entry, self._parent)
        state: dict[str, object] = {
            "key": key,
            "ref": row.ref,
            "revision": revision,
        }
        dialog.requeryRequested.connect(lambda: self._requery_edit_dialog(dialog, language, state))
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        edited = dialog.current_entry()
        edited.language = language  # type: ignore[assignment]
        state_key = state.get("key")
        new_key = self._save_edit(
            language,
            state_key if isinstance(state_key, str) else key,
            edited,
            target_ref=(state["ref"] if isinstance(state.get("ref"), EntryRef) else None),
            expected_revision=(
                state["revision"] if isinstance(state.get("revision"), WorkbookRevision) else None
            ),
        )
        if new_key:
            state["key"] = new_key

    def _save_edit(
        self,
        language: str,
        original_key: str,
        entry: VocabularyEntry,
        *,
        create_backup: bool = True,
        target_ref: EntryRef | None = None,
        expected_revision: WorkbookRevision | None = None,
    ) -> str | None:
        if self._async_enabled:
            assert self._edit_task is not None
            if self._edit_task.is_running():
                return None
            copied = VocabularyEntry.from_json(entry.to_json())
            worker = WordbookEditWorker(
                self._wordbook_service,
                language,
                original_key,
                copied,
                create_backup=create_backup,
                target_ref=target_ref,
                expected_revision=expected_revision,
            )
            self._edit_task.start(
                worker,
                run=worker.run,
                terminal_bindings=[
                    TerminalBinding(
                        worker.finished,
                        TaskTerminal.SUCCESS,
                        self._on_edit_finished,
                    ),
                    TerminalBinding(
                        worker.failed,
                        TaskTerminal.FAILURE,
                        self._on_edit_failed,
                    ),
                ],
            )
            return original_key
        try:
            result = self._wordbook_service.save_edit(
                language,
                original_key,
                entry,
                target_ref=target_ref,
                expected_revision=expected_revision,
                create_backup=create_backup,
            )
        except (ValueError, LookupError, RuntimeError) as exc:
            self._status.showMessage(str(exc))
            return None
        except Exception as exc:
            log.exception("wordbook edit save failed")
            QtWidgets.QMessageBox.critical(self._parent, "수정 실패", str(exc))
            return None
        if callable(self._queue_tts_pre_generation):
            self._queue_tts_pre_generation(entry)
        self._refresh_after_mutation(language)
        message = f"{entry.word} 수정됨"
        if result.backup_path is not None:
            message += f" · 백업: {result.backup_path.name}"
        self._status.showMessage(message)
        return result.new_key

    @QtCore.Slot(str, object)
    def _on_edit_finished(self, language: str, result_obj: object) -> None:
        if not hasattr(result_obj, "entry") or not hasattr(result_obj, "new_key"):
            self._on_edit_failed("수정 결과가 올바르지 않습니다.")
            return
        entry = result_obj.entry
        if callable(self._queue_tts_pre_generation):
            self._queue_tts_pre_generation(entry)
        self._refresh_after_mutation(language)
        message = f"{entry.word} 수정됨"
        if result_obj.backup_path is not None:
            message += f" · 백업: {result_obj.backup_path.name}"
        self._status.showMessage(message)

    @QtCore.Slot(object)
    def _on_edit_failed(self, error: object) -> None:
        message = str(error)
        if isinstance(error, (ValueError, LookupError, RuntimeError)):
            self._status.showMessage(message)
            return
        QtWidgets.QMessageBox.critical(self._parent, "수정 실패", message)

    def _requery_edit_dialog(
        self,
        dialog: EntryEditDialog,
        language: str,
        state: dict[str, object],
    ) -> None:
        current = dialog.current_entry()
        lookup_word = current.word.strip()
        if not lookup_word:
            dialog.show_status("재조회할 단어가 없습니다.")
            return
        if self._lookup_service is None:
            dialog.show_status("재조회 서비스를 사용할 수 없습니다.")
            return
        if self.is_requery_running():
            dialog.show_status("재조회 중...")
            return

        path = Path(self._settings.excel_path_for(language))
        state_key = state.get("key")
        original_key = state_key if isinstance(state_key, str) else current.word_key()
        state_ref = state.get("ref")
        try:
            plan = self._wordbook_service.prepare_requery(
                path,
                language,
                original_key,
                current,
                ref=state_ref if isinstance(state_ref, EntryRef) else None,
            )
        except Exception as exc:
            log.exception("wordbook requery prepare failed")
            dialog.show_status("재조회 실패 · 기존 데이터는 변경되지 않았습니다.")
            self._status.showMessage(f"재조회 실패: {exc}")
            return
        if plan is None:
            dialog.show_status("재조회할 단어를 찾을 수 없습니다.")
            return

        dialog.set_busy(True)
        worker = RequeryWorker(
            self._lookup_service,
            self._wordbook_service,
            plan,
            lookup_word,
            list(self._settings.excel_columns),
        )
        self._requery_dialog = dialog
        self._requery_task.start(
            worker,
            run=worker.run,
            terminal_bindings=[
                TerminalBinding(
                    worker.finished,
                    TaskTerminal.SUCCESS,
                    lambda committed: self._on_requery_finished(
                        dialog,
                        state,
                        plan,
                        committed,
                    ),
                ),
                TerminalBinding(
                    worker.failed,
                    TaskTerminal.FAILURE,
                    lambda message: self._on_requery_lookup_failed(dialog, message),
                ),
            ],
        )

    def _on_requery_finished(
        self,
        dialog: EntryEditDialog,
        state: dict[str, object],
        plan: RequeryPlan,
        committed_obj: object,
    ) -> None:
        if not isinstance(committed_obj, RequeryCommitResult):
            self._on_requery_lookup_failed(
                dialog,
                "재조회 저장 결과가 올바르지 않습니다.",
            )
            return
        committed = committed_obj
        if committed.status == "not_found":
            dialog.set_entry(plan.original_entry)
            dialog.show_status("재조회 결과가 없어 기존 데이터를 유지했습니다.")
            self._status.showMessage("재조회 결과 없음 · 기존 데이터를 유지했습니다.")
            return
        self._apply_requery_commit(dialog, state, plan, committed)

    def _apply_requery_commit(
        self,
        dialog: EntryEditDialog,
        state: dict[str, object],
        plan: RequeryPlan,
        committed: RequeryCommitResult,
    ) -> None:
        entry = committed.entry
        new_key = normalize_word_key(entry.word, plan.language)  # type: ignore[arg-type]
        if callable(self._queue_tts_pre_generation):
            self._queue_tts_pre_generation(entry)
        state["key"] = new_key
        if committed.ref is not None:
            state["ref"] = committed.ref
        if committed.revision is not None:
            state["revision"] = committed.revision
        self._refresh_after_mutation(plan.language)
        dialog.set_entry(entry)
        dialog.show_status("재조회 완료 · 단어장에 반영했습니다.")

    def _on_requery_lookup_failed(
        self,
        dialog: EntryEditDialog,
        message: str,
    ) -> None:
        dialog.show_status("재조회 실패 · 기존 데이터는 변경되지 않았습니다.")
        self._status.showMessage(f"재조회 실패: {message}")

    @QtCore.Slot(object)
    def _on_requery_task_terminal(self, _outcome: object) -> None:
        self._finish_requery_dialog()

    def _finish_requery_dialog(self) -> None:
        dialog = self._requery_dialog
        self._requery_dialog = None
        if dialog is None:
            return
        try:
            dialog.set_busy(False)
        except RuntimeError:
            pass

    def is_requery_running(self) -> bool:
        return self._requery_task.is_running()

    def is_running(self) -> bool:
        return any(
            task.is_running()
            for task in (
                self._requery_task,
                self._list_task,
                self._delete_task,
                self._undo_task,
                self._edit_task,
                self._anki_task,
            )
            if task is not None
        )

    def close(self) -> bool:
        outcomes = [
            task.close()
            for task in (
                self._requery_task,
                self._list_task,
                self._delete_task,
                self._undo_task,
                self._edit_task,
                self._anki_task,
            )
            if task is not None
        ]
        return all(outcomes)

    def _refresh_after_mutation(self, language: str) -> None:
        self.show_inline(language, self._current_sort_option)
        if callable(self._remember_last_view_mode):
            self._remember_last_view_mode(language)

    # ---------- recent-entry detail -----------------------------------

    def saved_entry_projection(
        self,
        word: str,
        language: str,
        lookup_cached: VocabularyEntry | None = None,
    ) -> VocabularyEntry | None:
        return self._wordbook_service.saved_entry_projection(
            word,
            language,
            lookup_cached,
        )

    def open_recent_detail(self, word: str, language: str) -> None:
        from app.ui.entry_detail_dialog import EntryDetailDialog

        cached = self._cache.get(word, language)  # type: ignore[arg-type]
        entry = self.saved_entry_projection(word, language, cached)
        if entry is None:
            self._status.showMessage("최근 단어 상세를 찾을 수 없습니다.")
            return
        EntryDetailDialog(entry, self._parent, settings=self._settings).exec()
