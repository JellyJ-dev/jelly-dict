"""Wordbook flows: inline display, deletion (Excel + cache + Anki), and
recent-entry detail dialog. Extracted from MainWindow for clarity.

All status bar messages, dialog buttons, and side-effects are
identical to the previous inline implementation.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6 import QtWidgets

from app.core.models import normalize_word_key, wordbook_meaning_hint
from app.services.anki_sync_service import AnkiSyncService
from app.storage import excel_writer
from app.storage.cache_store import CacheStore
from app.storage.settings_store import Settings
from app.ui.entry_detail_dialog import EntryDetailDialog
from app.ui.word_input_view import WordInputView

log = logging.getLogger(__name__)


class WordbookController:
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        input_view: WordInputView,
        cache: CacheStore,
        anki_sync: AnkiSyncService,
        settings: Settings,
        status_bar: QtWidgets.QStatusBar,
    ) -> None:
        self._parent = parent
        self._input_view = input_view
        self._cache = cache
        self._anki_sync = anki_sync
        self._settings = settings
        self._status = status_bar
        self._saved_words: set[tuple[str, str]] = set()
        self._current_sort_option = "최신순"
        self._entries_cache: dict[str, tuple[Path, int, list]] = {}

    def update_settings(self, settings: Settings, anki_sync: AnkiSyncService) -> None:
        self._settings = settings
        self._anki_sync = anki_sync
        self._entries_cache.clear()

    def set_saved_words_cache(self, saved_words: set[tuple[str, str]]) -> None:
        self._saved_words = set(saved_words)

    # ---------- inline rendering ---------------------------------------

    def update_saved_words_cache(self) -> None:
        self._saved_words: set[tuple[str, str]] = set()
        for lang in ("en", "ja"):
            path = Path(self._settings.excel_path_for(lang))
            if not path.exists():
                continue
            try:
                entries = excel_writer.list_entries(path)
                for entry in entries:
                    if entry.language == lang and (entry.word or "").strip():
                        normalized = normalize_word_key(entry.word, lang)
                        self._saved_words.add((lang, normalized))
            except Exception as exc:
                log.warning("Failed to load entries for cache from %s: %s", path, exc)

    def is_word_saved(self, word: str, language: str) -> bool:
        normalized = normalize_word_key(word, language)
        return (language, normalized) in self._saved_words

    # ---------- inline rendering ---------------------------------------

    def show_inline(self, language: str, sort_option: str = "최신순") -> None:
        self._current_sort_option = sort_option
        language = language if language in ("en", "ja") else "en"
        raw_entries = self._load_entries(language)

        filtered = [
            entry
            for entry in raw_entries
            if entry.language == language and (entry.word or "").strip()
        ]

        if sort_option == "오래된순":
            entries = filtered
        elif sort_option == "가나다순":
            entries = sorted(filtered, key=lambda x: (x.word or "").lower())
        else:  # "최신순"
            entries = list(reversed(filtered))

        items: list[tuple[str, str, str, str]] = [
            (entry.word, language, entry.reading or "",
             wordbook_meaning_hint(entry, limit=160))
            for entry in entries
        ]
        self._input_view.set_wordbook(language, items)
        self._status.showMessage(
            f"{'일본어' if language == 'ja' else '영어'} 단어장 {len(items)}개 (정렬: {sort_option})"
        )

    def _load_entries(self, language: str) -> list:
        path = Path(self._settings.excel_path_for(language))
        try:
            mtime_ns = path.stat().st_mtime_ns if path.exists() else -1
        except OSError:
            mtime_ns = -1
        cached = self._entries_cache.get(language)
        if cached is not None:
            cached_path, cached_mtime_ns, cached_entries = cached
            if cached_path == path and cached_mtime_ns == mtime_ns:
                return list(cached_entries)
        try:
            entries = excel_writer.list_entries(path)
        except Exception:
            entries = []
        self._entries_cache[language] = (path, mtime_ns, entries)
        return list(entries)

    # ---------- deletion -----------------------------------------------

    def delete_entries(self, language: str, words_obj: object) -> None:
        language = language if language in ("en", "ja") else "en"
        words = [
            word.strip()
            for word in words_obj
            if isinstance(word, str) and word.strip()
        ] if isinstance(words_obj, list) else []
        if not words:
            return

        preview = "\n".join(f"• {word}" for word in words[:10])
        if len(words) > 10:
            preview += f"\n... 외 {len(words) - 10}개"
        sync_note = ""
        if self._anki_sync.enabled:
            sync_note = (
                "\n\nAnkiConnect가 켜져 있으면 Anki 카드도 함께 삭제를 시도합니다."
            )
        ok = QtWidgets.QMessageBox.warning(
            self._parent,
            "삭제 확인",
            "선택한 단어를 삭제할까요?\n\n" + preview + sync_note,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if ok != QtWidgets.QMessageBox.Yes:
            return

        path = Path(self._settings.excel_path_for(language))
        keys = {
            normalize_word_key(word, language)  # type: ignore[arg-type]
            for word in words
        }
        try:
            delete_outcome = excel_writer.delete_entries_with_backup(path, language, keys)
            removed = delete_outcome.removed
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self._parent, "삭제 실패", str(exc))
            return
        self._entries_cache.pop(language, None)

        try:
            self._cache.delete_entries(language, keys)  # type: ignore[arg-type]
        except Exception as exc:
            log.warning("cache delete failed: %s", exc)

        anki_removed = 0
        anki_errors: list[str] = []
        if self._anki_sync.enabled:
            anki_removed, anki_errors = self._anki_sync.delete_words(words, language)

        # Keep the saved-word index current without re-reading both Excel
        # files on the UI thread; the visible wordbook list below reads only
        # the active workbook because the user is already in that view.
        self._saved_words.difference_update((language, key) for key in keys)
        self.show_inline(language, self._current_sort_option)
        message = (
            f"{'일본어' if language == 'ja' else '영어'} 단어장 {removed}개 삭제됨"
        )
        if delete_outcome.backup_path is not None:
            message += f" · 백업: {delete_outcome.backup_path.name}"
        if anki_removed:
            message += f" · Anki {anki_removed}개"
        if anki_errors:
            log.warning("anki delete errors: %s", anki_errors[:5])
            message += " · Anki 일부 실패"
        self._status.showMessage(message)

    # ---------- recent-entry detail -----------------------------------

    def open_recent_detail(self, word: str, language: str) -> None:
        entry = self._cache.get(word, language)  # type: ignore[arg-type]
        if entry is None:
            path = Path(self._settings.excel_path_for(language))
            key = normalize_word_key(word, language)  # type: ignore[arg-type]
            entry = excel_writer.find_existing(path, language, key)
        if entry is None:
            self._status.showMessage("최근 단어 상세를 찾을 수 없습니다.")
            return
        EntryDetailDialog(entry, self._parent).exec()
