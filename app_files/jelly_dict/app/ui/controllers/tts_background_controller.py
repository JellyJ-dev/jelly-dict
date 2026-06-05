from __future__ import annotations

import logging
import threading

from PySide6 import QtCore

from app.core.models import VocabularyEntry, normalize_word_key
from app.storage.settings_store import Settings

log = logging.getLogger(__name__)
TTS_PREGEN_QUEUE_LIMIT = 64


def _tts_pre_generation_entry_key(entry: VocabularyEntry) -> tuple[str, str]:
    return (entry.language, normalize_word_key(entry.word, entry.language))


def append_tts_pre_generation_job(
    queue: list[tuple[Settings, VocabularyEntry]],
    settings: Settings,
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
        self._queue: list[tuple[Settings, VocabularyEntry]] = []
        self._active = False
        self._start_timer = QtCore.QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.setInterval(1800)
        self._start_timer.timeout.connect(self._start_worker)

    def queue_entry(self, settings: Settings, entry: VocabularyEntry) -> None:
        if not (
            getattr(settings, "tts_enabled", False)
            and getattr(settings, "tts_pre_generate_on_save", False)
        ):
            return
        settings_snapshot = Settings(**settings.to_dict())
        entry_snapshot = VocabularyEntry.from_dict(entry.to_dict())
        should_start = False
        with self._lock:
            append_tts_pre_generation_job(
                self._queue,
                settings_snapshot,
                entry_snapshot,
            )
            if not self._active:
                self._active = True
                should_start = True
        if should_start:
            self._start_timer.start()

    def close(self) -> None:
        self._start_timer.stop()

    def _start_worker(self) -> None:
        with self._lock:
            if not self._queue:
                self._active = False
                return
        threading.Thread(
            target=self._run_loop,
            name="jelly-dict-tts-pregen",
            daemon=True,
        ).start()

    def _run_loop(self) -> None:
        from app.services.tts_process_service import pre_generate_entries_audio_in_process

        while True:
            with self._lock:
                if not self._queue:
                    self._active = False
                    return
                jobs = list(self._queue)
                self._queue.clear()
            try:
                generated = pre_generate_entries_audio_in_process(jobs)
                if generated:
                    log.info("TTS pre-generated %s file(s)", generated)
            except Exception as exc:
                log.warning("TTS pre-generation batch failed: %s", exc)
