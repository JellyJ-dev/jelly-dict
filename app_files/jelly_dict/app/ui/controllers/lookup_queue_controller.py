from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6 import QtCore, QtWidgets

from app.core.models import Language, VocabularyEntry
from app.dictionary.manual_provider import ManualDictionaryProvider
from app.platform.macos_spellchecker import MacOSSpellChecker
from app.services.lookup_queue_state import LookupQueueState
from app.services.lookup_service import LookupService
from app.ui.async_task import TaskSupervisor, TaskTerminal, TerminalBinding
from app.ui.lookup_worker import LookupWorker
from app.ui.spelling_suggestion_dialog import choose_spelling_suggestion
from app.ui.word_input_view import WordInputView

log = logging.getLogger(__name__)


class LookupQueueController(QtCore.QObject):
    def __init__(
        self,
        *,
        parent: QtWidgets.QWidget,
        input_view: WordInputView,
        status_bar,
        lookup_service: LookupService,
        manual_provider: ManualDictionaryProvider,
        present_entry: Callable[[VocabularyEntry, bool], None],
        confirm_suggestion: Callable[[str, str, str], bool],
        return_to_input: Callable[[], None],
        refresh_recent_if_visible: Callable[[], None],
        choose_spelling: Callable[[str, list[str]], str | None] | None = None,
        choose_related: Callable[[str, list[str]], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._input_view = input_view
        self._status = status_bar
        self._lookup_service = lookup_service
        self._manual_provider = manual_provider
        self._present_entry = present_entry
        self._confirm_suggestion = confirm_suggestion
        self._return_to_input = return_to_input
        self._refresh_recent_if_visible = refresh_recent_if_visible
        self._choose_spelling = choose_spelling or (
            lambda word, candidates: choose_spelling_suggestion(parent, word, candidates)
        )
        self._choose_related = choose_related or (
            lambda word, candidates: choose_spelling_suggestion(
                parent, word, candidates, related=True
            )
        )
        self._task = TaskSupervisor(self, name="lookup")
        self._task.terminal.connect(self._on_task_terminal)
        self._current_worker: LookupWorker | None = None
        self._pending_lookup_retry: tuple[str, Language, bool, bool] | None = None
        self._retry_timer = QtCore.QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._start_pending_retry)
        self._spell_checker = MacOSSpellChecker(self)
        self._spell_checker.finished.connect(self._on_spelling_finished)
        self._pending_spelling: tuple[int, str, str | None] | None = None
        self._allow_spelling = True
        self._choosing_spelling = False
        self._lookup_generation = 0
        self._stopped = False
        self._awaiting_entry_completion = False
        self._closed = False
        self._queue_state = LookupQueueState()
        self._queue_timer = QtCore.QTimer(self)
        self._queue_timer.setSingleShot(True)
        # External pacing has one authority: PlaywrightClient's limiter.
        # This timer only yields to the event loop between queue items, so
        # cache hits and manual-provider lookups do not pay a fixed 1s delay.
        self._queue_timer.setInterval(0)
        self._queue_timer.timeout.connect(self.start_next_queued_lookup)

    def update_lookup_service(self, lookup_service: LookupService) -> None:
        self._lookup_service = lookup_service

    @QtCore.Slot(str)
    def cancel_job(self, job_id: str) -> None:
        active = self._queue_state.active
        if active is not None and active.id == job_id:
            return
        target_job = self._queue_state.cancel(job_id)
        if target_job is not None:
            self.refresh_queue_ui()
            self._status.showMessage(f"'{target_job.word}' 대기가 취소되었습니다.")

    def is_already_queued_or_active(
        self,
        word: str,
        forced_language: str,
        *,
        force_refresh: bool = False,
    ) -> bool:
        return self._queue_state.contains(
            word,
            forced_language,
            force_refresh,
        )

    @QtCore.Slot(str, str)
    def submit(self, word: str, forced_language: str) -> None:
        word_stripped = word.strip()
        if not word_stripped:
            return
        if self.is_already_queued_or_active(word_stripped, forced_language):
            self._status.showMessage(
                f"'{word_stripped}' [{forced_language}] 은(는) 이미 대기열에 존재합니다."
            )
            self._input_view.reset_input()
            return

        self._queue_state.add(word_stripped, forced_language)
        self._input_view.reset_input()
        self.refresh_queue_ui()
        if not self.is_active():
            self.start_next_queued_lookup()

    @QtCore.Slot(object, str)
    def submit_ocr_batch(self, tokens_obj: object, forced_language: str) -> None:
        tokens = (
            [token.strip() for token in tokens_obj if isinstance(token, str) and token.strip()]
            if isinstance(tokens_obj, list)
            else []
        )
        if not tokens:
            return

        added_count, _skipped_count = self.queue_lookup_tokens(tokens, forced_language)
        self._input_view.reset_input()
        self.refresh_queue_ui()
        if added_count > 0 and not self.is_active():
            self.start_next_queued_lookup()

    @QtCore.Slot(object, str)
    def submit_bulk(self, tokens_obj: object, forced_language: str) -> None:
        tokens = (
            [token.strip() for token in tokens_obj if isinstance(token, str) and token.strip()]
            if isinstance(tokens_obj, list)
            else []
        )
        if not tokens:
            return

        added_count, skipped_count = self.queue_lookup_tokens(tokens, forced_language)
        self._input_view.reset_input()
        self.refresh_queue_ui()
        if added_count > 0:
            self._status.showMessage(
                f"{added_count}개 단어를 대기열에 추가했습니다."
                + (f" ({skipped_count}개 중복 제외)" if skipped_count else "")
            )
            if not self.is_active():
                self.start_next_queued_lookup()
            return
        self._status.showMessage("추가할 새 단어가 없습니다.")

    def queue_lookup_tokens(
        self,
        tokens: list[str],
        forced_language: str,
        *,
        force_refresh: bool = False,
    ) -> tuple[int, int]:
        return self._queue_state.add_many(
            tokens,
            forced_language,
            force_refresh=force_refresh,
        )

    @QtCore.Slot(list, str)
    def submit_ocr_bulk(self, tokens: list[str], forced_language: str) -> None:
        self.submit_ocr_batch(tokens, forced_language)

    def start_lookup(
        self,
        word: str,
        forced_language: str,
        *,
        force_refresh: bool = False,
        allow_spelling: bool = True,
    ) -> None:
        if self._closed:
            return
        self._stopped = False
        self._lookup_generation += 1
        self._allow_spelling = allow_spelling
        self._spell_checker.cancel()
        self._pending_spelling = None
        self._input_view.set_detection_label("")
        self._input_view.set_lookup_busy(True)
        self._status.showMessage(f"{'재조회' if force_refresh else '조회'} 중: {word}…")
        log.info(
            "lookup task starting: language=%s force_refresh=%s",
            forced_language or "auto",
            force_refresh,
        )
        worker = LookupWorker(
            self._lookup_service,
            word,
            forced_language or None,
            force_refresh=force_refresh,
        )
        self._current_worker = worker
        self._task.start(
            worker,
            run=worker.run,
            terminal_bindings=[
                TerminalBinding(
                    worker.finished,
                    TaskTerminal.SUCCESS,
                    self._on_lookup_finished,
                ),
                TerminalBinding(
                    worker.failed,
                    TaskTerminal.FAILURE,
                    self._on_lookup_failed,
                ),
                TerminalBinding(
                    worker.unsupported,
                    TaskTerminal.FAILURE,
                    self._on_unsupported,
                ),
                TerminalBinding(
                    worker.ambiguous,
                    TaskTerminal.FAILURE,
                    self._on_ambiguous,
                ),
            ],
        )

    def is_running(self) -> bool:
        return self._task.is_running()

    def is_active(self) -> bool:
        return (
            self.is_running()
            or self._queue_timer.isActive()
            or self._pending_lookup_retry is not None
            or self._pending_spelling is not None
            or self._choosing_spelling
            or self._awaiting_entry_completion
            or self._queue_state.active is not None
        )

    def start_next_queued_lookup(self) -> None:
        if self._closed or self.is_running() or self._awaiting_entry_completion:
            return

        job = self._queue_state.start_next()
        if job is None:
            self._input_view.set_lookup_busy(False)
            failed_count = self._queue_state.failed_count
            if failed_count > 0:
                self._status.showMessage(f"조회 대기 완료 (실패 {failed_count}개 보류 중)")
            else:
                self._status.showMessage("모든 조회가 완료되었습니다.")
            self._refresh_recent_if_visible()
            self.refresh_queue_ui()
            return

        index = self._queue_state.progress_index()
        self._status.showMessage(f"순차 조회 {index}/{self._queue_state.total}: {job.word}")
        self._refresh_recent_if_visible()
        self.refresh_queue_ui()
        self.start_lookup(
            job.word,
            job.forced_language,
            force_refresh=job.force_refresh,
        )

    def schedule_next(self) -> None:
        self._awaiting_entry_completion = False
        self._queue_state.complete_active()
        self.refresh_queue_ui()

        if not self._queue_state.has_pending:
            failed_count = self._queue_state.failed_count
            if self._stopped:
                self._status.showMessage("조회가 중지되었습니다.")
            elif failed_count > 0:
                self._status.showMessage(f"조회 대기 완료 (실패 {failed_count}개 보류 중)")
            else:
                self._status.showMessage("모든 조회가 완료되었습니다.")
            self._input_view.set_lookup_busy(False)
            self._refresh_recent_if_visible()
            return

        self._queue_timer.stop()
        self._queue_timer.start()

    @QtCore.Slot()
    def stop(self) -> None:
        self._queue_timer.stop()
        self._cancel_spelling()
        self._stopped = True
        # Do not wait for a network request on the GUI thread. The supervisor
        # discards its late terminal signal and retains ownership until it exits.
        self._task.request_cancel()
        self._queue_state.stop()
        self._input_view.set_lookup_busy(False)
        self._status.showMessage(
            "조회가 중지되었습니다. 이미 시작된 저장은 마무리합니다."
            if self._awaiting_entry_completion
            else "조회가 중지되었습니다."
        )
        self._refresh_recent_if_visible()
        self.refresh_queue_ui()

    def abort(self) -> None:
        self._queue_timer.stop()
        self._cancel_spelling()
        self._stopped = True
        self._awaiting_entry_completion = False
        self._task.request_cancel()
        self._queue_state.abort()
        self._input_view.set_lookup_busy(False)
        self._refresh_recent_if_visible()
        self.refresh_queue_ui()

    def close(self) -> bool:
        self._queue_timer.stop()
        self._cancel_spelling()
        self._closed = True
        stopped = self._task.close()
        if stopped:
            self._spell_checker.close()
        else:
            self._closed = False
        return stopped

    def _cancel_spelling(self) -> None:
        self._lookup_generation += 1
        self._retry_timer.stop()
        self._pending_lookup_retry = None
        self._pending_spelling = None
        self._spell_checker.cancel()

    def preview_cancelled(self) -> None:
        self._queue_state.fail_active()
        self._return_to_input()
        self.refresh_queue_ui()
        self.schedule_next()

    def refresh_queue_ui(self) -> None:
        jobs_data = [(job.word, job.status.value, job.id) for job in self._queue_state.rows()]
        self._input_view.set_lookup_queue(jobs_data)

    @QtCore.Slot(object)
    def _on_lookup_finished(self, outcome) -> None:
        if self._closed or self._stopped:
            return
        generation = self._lookup_generation
        job = self._queue_state.active
        self._input_view.set_lookup_busy(False)

        query_word = (
            job.word if job else (self._current_worker._word if self._current_worker else "?")
        )

        self._input_view.set_detection_label(
            f"감지: {outcome.detected_language}" + (" (캐시)" if outcome.from_cache else "")
        )
        result = outcome.result
        if result.ok and result.entry is not None:
            if result.suggested_word and not outcome.from_cache:
                accepted = self._confirm_suggestion(
                    query_word,
                    result.suggested_word,
                    outcome.detected_language,
                )
                if self._closed or generation != self._lookup_generation:
                    return
                if not accepted:
                    self._status.showMessage("입력어와 다른 결과여서 저장하지 않았습니다.")
                    self._queue_state.fail_active()
                    self._return_to_input()
                    self.refresh_queue_ui()
                    self.schedule_next()
                    return
                result.entry.word = result.suggested_word
            self._awaiting_entry_completion = True
            self._present_entry(result.entry, False)
        elif result.status == "not_found" and outcome.detected_language == "en":
            if self._allow_spelling and result.related_words:
                self._choose_lookup_candidate(
                    query_word, result.related_words, self._choose_related
                )
            elif self._allow_spelling:
                self._input_view.set_lookup_busy(True)
                self._status.showMessage(
                    f"검색 결과 없음: {query_word} — 철자를 확인하고 있습니다."
                )
                token = self._spell_checker.request(query_word)
                self._pending_spelling = (token, query_word, job.id if job else None)
            else:
                self._finish_not_found(query_word)
        elif result.status == "parse_failed":
            typed = query_word
            log.warning(
                "lookup parse failed: word=%s language=%s", typed, outcome.detected_language
            )
            self._status.showMessage(
                f"파싱 실패: {typed} — 페이지 구조 변경 또는 결과 없음. 직접 입력으로 전환합니다."
            )
            entry = self._manual_provider.lookup(
                typed,
                outcome.detected_language,  # type: ignore[arg-type]
            ).entry
            if entry is not None:
                self._awaiting_entry_completion = True
                self._present_entry(entry, True)
                return
            self._queue_state.fail_active()
            self.refresh_queue_ui()
            self.schedule_next()
        else:
            log.warning(
                "lookup failed: word=%s language=%s status=%s detail=%s",
                query_word,
                outcome.detected_language,
                result.status,
                result.error_detail or "",
            )
            self._status.showMessage(f"조회 실패: {result.status}")
            self._queue_state.fail_active()
            self.refresh_queue_ui()
            self.schedule_next()

    def _finish_not_found(self, word: str) -> None:
        log.info("dictionary entry not found: word=%s", word)
        self._queue_state.fail_active()
        self.schedule_next()
        if not self._queue_state.has_pending:
            self._status.showMessage(
                f"검색 결과 없음: '{word}' — 일치하는 사전 항목을 찾지 못했습니다."
            )

    @QtCore.Slot(int, object)
    def _on_spelling_finished(self, token: int, candidates: list[str]) -> None:
        pending = self._pending_spelling
        if self._closed or pending is None or pending[0] != token:
            return
        _token, word, job_id = pending
        self._pending_spelling = None
        job = self._queue_state.active
        if (job.id if job else None) != job_id:
            return
        self._choose_lookup_candidate(word, candidates, self._choose_spelling)

    def _choose_lookup_candidate(
        self,
        word: str,
        candidates: list[str],
        choose: Callable[[str, list[str]], str | None],
    ) -> None:
        job = self._queue_state.active
        if not candidates:
            self._finish_not_found(word)
            return
        generation = self._lookup_generation
        self._choosing_spelling = True
        try:
            selected = choose(word, candidates)
        finally:
            self._choosing_spelling = False
        # Dialogs run a nested event loop: closing/aborting must invalidate the
        # selection, even if Cocoa or a modal callback returns afterwards.
        if self._closed or generation != self._lookup_generation:
            return
        if selected not in candidates:
            self._finish_not_found(word)
            return
        if job and not self._queue_state.correct_active_word(selected, "en"):
            self._finish_not_found(word)
            self._status.showMessage(f"'{selected}'은(는) 이미 대기열에 있습니다.")
            return
        self.refresh_queue_ui()
        refresh = job.force_refresh if job else False
        # One correction per lookup. A candidate without a dictionary entry
        # must not recursively open another correction dialog.
        self._pending_lookup_retry = (selected, "en", refresh, False)
        if not self.is_running():
            self._retry_timer.start(0)

    @QtCore.Slot(str)
    def _on_lookup_failed(self, message: str) -> None:
        if self._closed or self._stopped:
            return
        log.warning("lookup worker failed: %s", message)
        self._status.showMessage(f"오류: {message}")
        self._queue_state.fail_active()
        self._input_view.set_lookup_busy(False)
        self.refresh_queue_ui()
        self.schedule_next()

    @QtCore.Slot(str)
    def _on_unsupported(self, word: str) -> None:
        if self._closed or self._stopped:
            return
        log.info("unsupported input language: %s", word)
        self._status.showMessage("입력 언어 미지원")
        self._queue_state.fail_active()
        self._input_view.set_lookup_busy(False)
        self.refresh_queue_ui()
        self.schedule_next()

    @QtCore.Slot(str)
    def retry_job(self, job_id: str) -> None:
        found_job = self._queue_state.retry(job_id)
        if found_job is not None:
            self._status.showMessage(f"'{found_job.word}' 조회를 재시도합니다.")
            self.refresh_queue_ui()
            if not self.is_active():
                self.start_next_queued_lookup()

    @QtCore.Slot()
    def retry_failed(self) -> None:
        count = self._queue_state.retry_all()
        if count > 0:
            self._status.showMessage(f"실패한 {count}개 단어 조회를 재시도합니다.")
            self.refresh_queue_ui()
            if not self.is_active():
                self.start_next_queued_lookup()

    @QtCore.Slot()
    def clear_failed(self) -> None:
        removed = self._queue_state.clear_failed()
        if removed > 0:
            self._status.showMessage(f"실패한 {removed}개 단어가 대기열에서 제거되었습니다.")
            self.refresh_queue_ui()

    @QtCore.Slot(str)
    def _on_ambiguous(self, word: str) -> None:
        if self._closed or self._stopped:
            return
        generation = self._lookup_generation
        self._input_view.set_lookup_busy(False)
        msg = QtWidgets.QMessageBox(self._parent)
        msg.setIcon(QtWidgets.QMessageBox.Question)
        msg.setWindowTitle("언어 선택")
        msg.setText(f"'{word}' — 영어와 일본어 문자가 섞여 있습니다.\n조회할 사전을 선택하세요.")
        msg.addButton("English", QtWidgets.QMessageBox.AcceptRole)
        ja_btn = msg.addButton("日本語", QtWidgets.QMessageBox.AcceptRole)
        cancel_btn = msg.addButton("취소", QtWidgets.QMessageBox.RejectRole)
        msg.exec()
        if self._closed or generation != self._lookup_generation:
            return
        clicked = msg.clickedButton()
        if clicked is cancel_btn:
            self._queue_state.fail_active()
            self._status.showMessage("언어 선택이 취소되었습니다.")
            self.refresh_queue_ui()
            self.schedule_next()
            return
        forced: Language = "ja" if clicked is ja_btn else "en"
        active = self._queue_state.active
        refresh = active.force_refresh if active is not None else False
        self._queue_state.set_active_language(forced)
        self._pending_lookup_retry = (word, forced, refresh, True)

    @QtCore.Slot(object)
    def _on_task_terminal(self, _outcome: object) -> None:
        self._current_worker = None
        if self._pending_lookup_retry is not None and not self._closed:
            self._retry_timer.start(0)
        elif (
            not self._closed
            and not self._awaiting_entry_completion
            and self._queue_state.active is None
            and self._queue_state.has_pending
        ):
            self._queue_timer.start()

    @QtCore.Slot()
    def _start_pending_retry(self) -> None:
        pending = self._pending_lookup_retry
        if pending is None or self._closed or self.is_running():
            return
        self._pending_lookup_retry = None
        word, forced, refresh, allow_spelling = pending
        if allow_spelling:
            self.start_lookup(word, forced, force_refresh=refresh)
        else:
            self.start_lookup(word, forced, force_refresh=refresh, allow_spelling=False)
