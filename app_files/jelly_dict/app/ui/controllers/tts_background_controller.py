from __future__ import annotations

import logging
import threading

from PySide6 import QtCore

from app.core.models import VocabularyEntry, normalize_word_key
from app.core.settings import AppSettings, SettingsDraft, settings_snapshot

log = logging.getLogger(__name__)
TTS_PREGEN_QUEUE_LIMIT = 64


def _tts_pre_generation_entry_key(entry: VocabularyEntry) -> tuple[str, str]:
    return (entry.language, normalize_word_key(entry.word, entry.language))


def append_tts_pre_generation_job(
    queue: list[tuple[AppSettings, VocabularyEntry]],
    settings: AppSettings,
    entry: VocabularyEntry,
    *,
    limit: int = TTS_PREGEN_QUEUE_LIMIT,
) -> None:
    entry_key = _tts_pre_generation_entry_key(entry)
    queue[:] = [
        (queued_settings, queued_entry)
        for queued_settings, queued_entry in queue
        if _tts_pre_generation_entry_key(queued_entry) != entry_key
    ]
    queue.append((settings, entry))
    overflow = len(queue) - max(1, limit)
    if overflow > 0:
        del queue[:overflow]


class TtsBackgroundController(QtCore.QObject):
    def __init__(self, parent: QtCore.QObject) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._queue: list[tuple[AppSettings, VocabularyEntry]] = []
        self._active = False
        self._closed = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._start_timer = QtCore.QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.setInterval(1800)
        self._start_timer.timeout.connect(self._start_worker)

    def queue_entry(
        self,
        settings: AppSettings | SettingsDraft,
        entry: VocabularyEntry,
    ) -> None:
        if not (
            getattr(settings, "tts_enabled", False)
            and getattr(settings, "tts_pre_generate_on_save", False)
        ):
            return
        snapshot = settings_snapshot(settings)
        entry_snapshot = VocabularyEntry.from_dict(entry.to_dict())
        should_start = False
        with self._lock:
            if self._closed:
                return
            append_tts_pre_generation_job(
                self._queue,
                snapshot,
                entry_snapshot,
            )
            if not self._active:
                self._active = True
                should_start = True
        if should_start:
            self._start_timer.start()

    def close(self) -> bool:
        self._closed = True
        self._start_timer.stop()
        self._stop_event.set()
        with self._lock:
            self._queue.clear()
            thread = self._thread
            if thread is None:
                self._active = False
                return True
        thread.join(timeout=3.0)
        if thread.is_alive():
            log.warning("TTS pre-generation thread did not stop; ownership retained")
            return False
        with self._lock:
            if self._thread is thread:
                self._thread = None
            self._active = False
        return True

    def _start_worker(self) -> None:
        with self._lock:
            if self._closed or not self._queue:
                self._active = False
                return
            if self._thread is not None:
                return
            self._stop_event.clear()
            thread = threading.Thread(
                target=self._run_loop,
                name="jelly-dict-tts-pregen",
                daemon=True,
            )
            self._thread = thread
        thread.start()

    def _run_loop(self) -> None:
        from app.tts.process_service import pre_generate_entries_audio_in_process

        try:
            while not self._stop_event.is_set():
                with self._lock:
                    if not self._queue:
                        return
                    jobs = list(self._queue)
                    self._queue.clear()
                try:
                    generated = pre_generate_entries_audio_in_process(
                        jobs,
                        cancel_event=self._stop_event,
                    )
                    if generated:
                        log.info("TTS pre-generated %s file(s)", generated)
                except Exception as exc:
                    log.warning("TTS pre-generation batch failed: %s", exc)
        finally:
            current = threading.current_thread()
            with self._lock:
                if self._thread is current:
                    self._thread = None
                self._active = False
