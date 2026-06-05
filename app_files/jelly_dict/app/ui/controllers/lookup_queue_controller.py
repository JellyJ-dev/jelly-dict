from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import uuid4

from PySide6 import QtCore, QtWidgets

from app.core.models import Language, VocabularyEntry
from app.dictionary.manual_provider import ManualDictionaryProvider
from app.services.lookup_service import LookupService
from app.ui.lookup_worker import LookupWorker
from app.ui.word_input_view import WordInputView

log = logging.getLogger(__name__)


class LookupJob:
    def __init__(
        self,
        word: str,
        forced_language: str,
        *,
        force_refresh: bool = False,
    ) -> None:
        self.id = uuid4().hex
        self.word = word
        self.forced_language = forced_language
        self.force_refresh = force_refresh
        self.status = "pending"  # "pending" | "running" | "failed"


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
        self._worker_thread: QtCore.QThread | None = None
        self._current_worker: LookupWorker | None = None
        self._lookup_queue: list[LookupJob] = []
        self._active_job: LookupJob | None = None
        self._lookup_queue_total = 0
        self._queue_timer = QtCore.QTimer(self)
        self._queue_timer.setSingleShot(True)
        self._queue_timer.setInterval(1000)
        self._queue_timer.timeout.connect(self.start_next_queued_lookup)

    def update_lookup_service(self, lookup_service: LookupService) -> None:
        self._lookup_service = lookup_service

    @QtCore.Slot(str)
    def cancel_job(self, job_id: str) -> None:
        if self._active_job is not None and self._active_job.id == job_id:
            return

        target_job = None
        for job in self._lookup_queue:
            if job.id == job_id:
                target_job = job
                break

        if target_job is not None:
            self._lookup_queue.remove(target_job)
            self._lookup_queue_total -= 1
            if not self._lookup_queue:
                self._lookup_queue_total = 1 if self._active_job is not None else 0
            self.refresh_queue_ui()
            self._status.showMessage(f"'{target_job.word}' 대기가 취소되었습니다.")

    def is_already_queued_or_active(
        self,
        word: str,
        forced_language: str,
        *,
        force_refresh: bool = False,
    ) -> bool:
        normalized = word.strip().lower()
        lang_norm = (forced_language or "").strip().lower()
        if self._active_job is not None:
            active_lang = (self._active_job.forced_language or "").strip().lower()
            if (
                self._active_job.word.strip().lower() == normalized
                and active_lang == lang_norm
                and self._active_job.force_refresh == force_refresh
            ):
                return True
        for job in self._lookup_queue:
            job_lang = (job.forced_language or "").strip().lower()
            if (
                job.word.strip().lower() == normalized
                and job_lang == lang_norm
                and job.force_refresh == force_refresh
            ):
                return True
        return False

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

        job = LookupJob(word_stripped, forced_language)
        self._lookup_queue.append(job)
        self._lookup_queue_total += 1
        self._input_view.reset_input()
        self.refresh_queue_ui()
        if not self.is_active():
            self.start_next_queued_lookup()

    @QtCore.Slot(object, str)
    def submit_ocr_batch(self, tokens_obj: object, forced_language: str) -> None:
        tokens = [
            token.strip()
            for token in tokens_obj
            if isinstance(token, str) and token.strip()
        ] if isinstance(tokens_obj, list) else []
        if not tokens:
            return

        added_count, _skipped_count = self.queue_lookup_tokens(tokens, forced_language)
        self._input_view.reset_input()
        self.refresh_queue_ui()
        if added_count > 0 and not self.is_active():
            self.start_next_queued_lookup()

    @QtCore.Slot(object, str)
    def submit_bulk(self, tokens_obj: object, forced_language: str) -> None:
        tokens = [
            token.strip()
            for token in tokens_obj
            if isinstance(token, str) and token.strip()
        ] if isinstance(tokens_obj, list) else []
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
        added_count = 0
        skipped_count = 0
        for token in tokens:
            if self.is_already_queued_or_active(
                token,
                forced_language,
                force_refresh=force_refresh,
            ):
                skipped_count += 1
                continue
            job = LookupJob(token, forced_language, force_refresh=force_refresh)
            self._lookup_queue.append(job)
            self._lookup_queue_total += 1
            added_count += 1
        return added_count, skipped_count

    @QtCore.Slot(list, str)
    def submit_ocr_bulk(self, tokens: list[str], forced_language: str) -> None:
        self.submit_ocr_batch(tokens, forced_language)

    def start_lookup(
        self,
        word: str,
        forced_language: str,
        *,
        force_refresh: bool = False,
    ) -> None:
        self._input_view.set_detection_label("")
        self._input_view.set_lookup_busy(True)
        self._status.showMessage(f"{'재조회' if force_refresh else '조회'} 중: {word}…")
        thread = QtCore.QThread(self)
        worker = LookupWorker(
            self._lookup_service,
            word,
            forced_language or None,
            force_refresh=force_refresh,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_lookup_finished)
        worker.failed.connect(self._on_lookup_failed)
        worker.unsupported.connect(self._on_unsupported)
        worker.ambiguous.connect(self._on_ambiguous)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.unsupported.connect(thread.quit)
        worker.ambiguous.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._worker_thread = thread
        self._current_worker = worker
        thread.start()

    def is_running(self) -> bool:
        if self._worker_thread is None:
            return False
        try:
            return self._worker_thread.isRunning()
        except RuntimeError:
            self._worker_thread = None
            self._current_worker = None
            return False

    def is_active(self) -> bool:
        return self.is_running() or self._queue_timer.isActive()

    def start_next_queued_lookup(self) -> None:
        if self.is_running():
            return

        pending_idx = -1
        for i, job in enumerate(self._lookup_queue):
            if job.status == "pending":
                pending_idx = i
                break

        if pending_idx == -1:
            self._active_job = None
            self._input_view.set_lookup_busy(False)
            failed_count = sum(1 for job in self._lookup_queue if job.status == "failed")
            if failed_count > 0:
                self._status.showMessage(f"조회 대기 완료 (실패 {failed_count}개 보류 중)")
            else:
                self._lookup_queue_total = 0
                self._status.showMessage("모든 조회가 완료되었습니다.")
            self._refresh_recent_if_visible()
            self.refresh_queue_ui()
            return

        job = self._lookup_queue.pop(pending_idx)
        self._active_job = job
        job.status = "running"

        pending_count = sum(1 for job in self._lookup_queue if job.status == "pending")
        index = max(1, self._lookup_queue_total - pending_count)
        self._status.showMessage(f"순차 조회 {index}/{self._lookup_queue_total}: {job.word}")
        self._refresh_recent_if_visible()
        self.refresh_queue_ui()
        self.start_lookup(
            job.word,
            job.forced_language,
            force_refresh=job.force_refresh,
        )

    def schedule_next(self) -> None:
        self._active_job = None
        self.refresh_queue_ui()

        has_pending = any(job.status == "pending" for job in self._lookup_queue)
        if not has_pending:
            failed_count = sum(1 for job in self._lookup_queue if job.status == "failed")
            if failed_count > 0:
                self._status.showMessage(f"조회 대기 완료 (실패 {failed_count}개 보류 중)")
            else:
                self._lookup_queue_total = 0
                self._status.showMessage("모든 조회가 완료되었습니다.")
            self._input_view.set_lookup_busy(False)
            self._refresh_recent_if_visible()
            return

        self._queue_timer.stop()
        self._queue_timer.start()

    def finish_queue(self) -> None:
        self._queue_timer.stop()
        self._active_job = None
        self._lookup_queue = []
        self._lookup_queue_total = 0
        self.refresh_queue_ui()

    def abort(self) -> None:
        self._queue_timer.stop()
        self._active_job = None
        self._lookup_queue = []
        self._lookup_queue_total = 0
        self._input_view.set_lookup_busy(False)
        self._refresh_recent_if_visible()
        self.refresh_queue_ui()

    def close(self) -> None:
        self._queue_timer.stop()
        try:
            if self._worker_thread is not None and self._worker_thread.isRunning():
                self._worker_thread.quit()
                self._worker_thread.wait(2000)
        except Exception as exc:
            log.warning("worker thread cleanup failed: %s", exc)

    def preview_cancelled(self) -> None:
        if self._active_job is not None:
            self._active_job.status = "failed"
            self._lookup_queue.insert(0, self._active_job)
            self._active_job = None
        self._return_to_input()
        self.refresh_queue_ui()
        self.schedule_next()

    def refresh_queue_ui(self) -> None:
        jobs_data = []
        if self._active_job is not None:
            jobs_data.append((self._active_job.word, "running", self._active_job.id))
        for job in self._lookup_queue:
            jobs_data.append((job.word, job.status, job.id))
        self._input_view.set_lookup_queue(jobs_data)

    @QtCore.Slot(object)
    def _on_lookup_finished(self, outcome) -> None:
        job = self._active_job
        self._input_view.set_lookup_busy(False)

        query_word = job.word if job else (self._current_worker._word if self._current_worker else "?")

        self._input_view.set_detection_label(
            f"감지: {outcome.detected_language}"
            + (" (캐시)" if outcome.from_cache else "")
        )
        result = outcome.result
        if result.ok and result.entry is not None:
            if result.suggested_word and not outcome.from_cache:
                accepted = self._confirm_suggestion(
                    query_word,
                    result.suggested_word,
                    outcome.detected_language,
                )
                if not accepted:
                    self._status.showMessage("입력어와 다른 결과여서 저장하지 않았습니다.")
                    if self._active_job is not None:
                        self._active_job.status = "failed"
                        self._lookup_queue.insert(0, self._active_job)
                        self._active_job = None
                    self._return_to_input()
                    self.refresh_queue_ui()
                    self.schedule_next()
                    return
                result.entry.word = result.suggested_word
            self._present_entry(result.entry, False)
        elif result.status == "parse_failed":
            typed = query_word
            log.warning("lookup parse failed: word=%s language=%s", typed, outcome.detected_language)
            self._status.showMessage(
                f"파싱 실패: {typed} — 페이지 구조 변경 또는 결과 없음. 직접 입력으로 전환합니다."
            )
            entry = self._manual_provider.lookup(
                typed, outcome.detected_language  # type: ignore[arg-type]
            ).entry
            if entry is not None:
                self._present_entry(entry, True)
                return
            if self._active_job is not None:
                self._active_job.status = "failed"
                self._lookup_queue.insert(0, self._active_job)
                self._active_job = None
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
            if self._active_job is not None:
                self._active_job.status = "failed"
                self._lookup_queue.insert(0, self._active_job)
                self._active_job = None
            self.refresh_queue_ui()
            self.schedule_next()

    @QtCore.Slot(str)
    def _on_lookup_failed(self, message: str) -> None:
        log.warning("lookup worker failed: %s", message)
        self._status.showMessage(f"오류: {message}")
        if self._active_job is not None:
            self._active_job.status = "failed"
            self._lookup_queue.insert(0, self._active_job)
            self._active_job = None
        self._input_view.set_lookup_busy(False)
        self.refresh_queue_ui()
        self.schedule_next()

    @QtCore.Slot(str)
    def _on_unsupported(self, word: str) -> None:
        log.info("unsupported input language: %s", word)
        self._status.showMessage("입력 언어 미지원")
        if self._active_job is not None:
            self._active_job.status = "failed"
            self._lookup_queue.insert(0, self._active_job)
            self._active_job = None
        self._input_view.set_lookup_busy(False)
        self.refresh_queue_ui()
        self.schedule_next()

    @QtCore.Slot(str)
    def retry_job(self, job_id: str) -> None:
        found_job = None
        for job in self._lookup_queue:
            if job.id == job_id and job.status == "failed":
                job.status = "pending"
                found_job = job
                break
        if found_job is not None:
            self._status.showMessage(f"'{found_job.word}' 조회를 재시도합니다.")
            self.refresh_queue_ui()
            if not self.is_active():
                self.start_next_queued_lookup()

    @QtCore.Slot()
    def retry_failed(self) -> None:
        count = 0
        for job in self._lookup_queue:
            if job.status == "failed":
                job.status = "pending"
                count += 1
        if count > 0:
            self._status.showMessage(f"실패한 {count}개 단어 조회를 재시도합니다.")
            self.refresh_queue_ui()
            if not self.is_active():
                self.start_next_queued_lookup()

    @QtCore.Slot()
    def clear_failed(self) -> None:
        new_queue = [job for job in self._lookup_queue if job.status != "failed"]
        removed = len(self._lookup_queue) - len(new_queue)
        if removed > 0:
            self._lookup_queue = new_queue
            self._lookup_queue_total -= removed
            if not self._lookup_queue:
                self._lookup_queue_total = 1 if self._active_job is not None else 0
            self._status.showMessage(f"실패한 {removed}개 단어가 대기열에서 제거되었습니다.")
            self.refresh_queue_ui()

    @QtCore.Slot(str)
    def _on_ambiguous(self, word: str) -> None:
        self._input_view.set_lookup_busy(False)
        msg = QtWidgets.QMessageBox(self._parent)
        msg.setIcon(QtWidgets.QMessageBox.Question)
        msg.setWindowTitle("언어 선택")
        msg.setText(
            f"'{word}' — 영어와 일본어 문자가 섞여 있습니다.\n"
            "조회할 사전을 선택하세요."
        )
        en_btn = msg.addButton("English", QtWidgets.QMessageBox.AcceptRole)
        ja_btn = msg.addButton("日本語", QtWidgets.QMessageBox.AcceptRole)
        cancel_btn = msg.addButton("취소", QtWidgets.QMessageBox.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is cancel_btn:
            if self._active_job is not None:
                self._active_job.status = "failed"
                self._lookup_queue.insert(0, self._active_job)
                self._active_job = None
            self._status.showMessage("언어 선택이 취소되었습니다.")
            self.refresh_queue_ui()
            self.schedule_next()
            return
        forced: Language = "ja" if clicked is ja_btn else "en"
        refresh = self._active_job.force_refresh if self._active_job is not None else False
        self.start_lookup(word, forced, force_refresh=refresh)
