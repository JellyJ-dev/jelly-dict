"""Wordbook flows: inline display, deletion (Excel + cache + Anki), and
recent-entry detail dialog. Extracted from MainWindow for clarity.

All status bar messages, dialog buttons, and side-effects are
identical to the previous inline implementation.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from PySide6 import QtWidgets

from app.core.models import (
    VocabularyEntry,
    collect_examples_flat,
    normalize_word_key,
    wordbook_meaning_hint,
)
from app.services.lookup_service import LookupService
from app.services.anki_sync_service import AnkiSyncService
from app.storage import excel_writer
from app.storage.cache_store import CacheStore
from app.storage.settings_store import Settings
from app.ui.entry_edit_dialog import EntryEditDialog
from app.ui.entry_detail_dialog import EntryDetailDialog
from app.ui.word_input_view import WordInputView
from app.ui.widgets.wordbook_items import WordbookDisplayItem

log = logging.getLogger(__name__)


def _entry_example_texts(entry) -> tuple[str, ...]:
    examples = entry.examples_flat or collect_examples_flat(entry)
    texts: list[str] = []
    for example in examples:
        source = (example.source_text_plain or example.source_text or "").strip()
        translation = (example.translation_ko or "").strip()
        text = " ".join(part for part in (source, translation) if part)
        if text:
            texts.append(text)
    return tuple(texts)


class WordbookController:
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        input_view: WordInputView,
        cache: CacheStore,
        anki_sync: AnkiSyncService,
        settings: Settings,
        status_bar: QtWidgets.QStatusBar,
        lookup_service: LookupService | None = None,
        queue_tts_pre_generation=None,
        remember_last_view_mode=None,
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
        self._saved_words: set[tuple[str, str]] = set()
        self._current_sort_option = "최신순"
        self._entries_cache: dict[str, tuple[Path, int, list]] = {}

    def update_settings(
        self,
        settings: Settings,
        anki_sync: AnkiSyncService,
        lookup_service: LookupService | None = None,
    ) -> None:
        self._settings = settings
        self._anki_sync = anki_sync
        if lookup_service is not None:
            self._lookup_service = lookup_service
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

        items = [
            WordbookDisplayItem(
                word=entry.word,
                language=language,
                reading=entry.reading or "",
                hint=wordbook_meaning_hint(entry, limit=160),
                tags=tuple(tag for tag in entry.tags if tag.strip()),
                memo=entry.memo or "",
                examples=_entry_example_texts(entry),
                updated_at=entry.updated_at or entry.created_at,
            )
            for entry in entries
        ]
        self._input_view.set_wordbook(language, items)

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
        try:
            delete_recent = getattr(self._cache, "delete_recent_entries", None)
            if callable(delete_recent):
                delete_recent(language, keys)
        except Exception as exc:
            log.warning("recent delete failed: %s", exc)

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
        self._show_delete_undo(language, path, delete_outcome.backup_path, keys, removed)

    def _show_delete_undo(
        self,
        language: str,
        path: Path,
        backup_path: Path | None,
        keys: set[str],
        removed: int,
    ) -> None:
        if removed <= 0 or backup_path is None:
            return
        show_undo_toast = getattr(self._parent, "show_undo_toast", None)
        if not callable(show_undo_toast):
            return
        show_undo_toast(
            f"{removed}개를 삭제했습니다.",
            lambda: self._undo_delete(language, path, backup_path, keys, removed),
        )

    def _undo_delete(
        self,
        language: str,
        path: Path,
        backup_path: Path,
        keys: set[str],
        removed: int,
    ) -> None:
        if not backup_path.exists():
            self._status.showMessage("삭제 되돌리기 실패: 백업 파일을 찾을 수 없습니다.")
            return
        try:
            shutil.copy2(backup_path, path)
        except OSError as exc:
            self._status.showMessage(f"삭제 되돌리기 실패: {exc}")
            return

        self._entries_cache.pop(language, None)
        self.update_saved_words_cache()
        self._restore_cache_entries(language, keys)
        self.show_inline(language, self._current_sort_option)
        self._status.showMessage(f"{removed}개 삭제를 되돌렸습니다.")

    def _restore_cache_entries(self, language: str, keys: set[str]) -> None:
        path = Path(self._settings.excel_path_for(language))
        try:
            entries = excel_writer.list_entries(path)
        except Exception as exc:
            log.warning("cache restore list failed: %s", exc)
            return
        for entry in entries:
            if entry.language != language:
                continue
            if normalize_word_key(entry.word, language) not in keys:  # type: ignore[arg-type]
                continue
            try:
                self._cache.upsert(entry)
            except Exception as exc:
                log.warning("cache restore upsert failed: %s", exc)

    # ---------- editing / requery --------------------------------------

    def edit_entry(self, language: str, word: str) -> None:
        language = language if language in ("en", "ja") else "en"
        key = normalize_word_key(word, language)  # type: ignore[arg-type]
        path = Path(self._settings.excel_path_for(language))
        entry = excel_writer.find_existing(path, language, key)
        if entry is None:
            self._status.showMessage("수정할 단어를 찾을 수 없습니다.")
            return

        dialog = EntryEditDialog(entry, self._parent)
        state = {"key": key}
        dialog.requeryRequested.connect(
            lambda: self._requery_edit_dialog(dialog, language, state)
        )
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        edited = dialog.current_entry()
        edited.language = language  # type: ignore[assignment]
        new_key = self._save_edit(language, state["key"], edited)
        if new_key:
            state["key"] = new_key

    def _save_edit(
        self,
        language: str,
        original_key: str,
        entry: VocabularyEntry,
        *,
        create_backup: bool = True,
    ) -> str | None:
        if not entry.word.strip():
            self._status.showMessage("단어는 비울 수 없습니다.")
            return None
        path = Path(self._settings.excel_path_for(language))
        try:
            outcome = excel_writer.replace_entry(
                path,
                language,
                original_key,
                entry,
                self._settings.excel_columns,
                create_backup=create_backup,
            )
        except Exception as exc:
            log.exception("wordbook edit save failed")
            QtWidgets.QMessageBox.critical(self._parent, "수정 실패", str(exc))
            return None
        try:
            self._cache.upsert(entry)
        except Exception as exc:
            log.warning("cache upsert after wordbook edit failed: %s", exc)
        if callable(self._queue_tts_pre_generation):
            self._queue_tts_pre_generation(entry)

        self._refresh_after_mutation(language)
        message = f"{entry.word} 수정됨"
        if outcome.backup_path is not None:
            message += f" · 백업: {outcome.backup_path.name}"
        self._status.showMessage(message)
        return normalize_word_key(entry.word, language)  # type: ignore[arg-type]

    def _requery_edit_dialog(
        self,
        dialog: EntryEditDialog,
        language: str,
        state: dict[str, str],
    ) -> None:
        current = dialog.current_entry()
        lookup_word = current.word.strip()
        if not lookup_word:
            dialog.show_status("재조회할 단어가 없습니다.")
            return
        if self._lookup_service is None:
            dialog.show_status("재조회 서비스를 사용할 수 없습니다.")
            return

        path = Path(self._settings.excel_path_for(language))
        original_key = state["key"]
        original_entry = excel_writer.find_existing(path, language, original_key)
        if original_entry is None:
            original_entry = current

        dialog.set_busy(True)
        try:
            excel_writer.delete_entries_with_backup(path, language, {original_key})
            try:
                self._cache.delete_entries(language, {original_key})  # type: ignore[arg-type]
            except Exception as exc:
                log.warning("cache delete before requery failed: %s", exc)

            outcome = self._lookup_service.lookup(
                lookup_word,
                language,  # type: ignore[arg-type]
                force_refresh=True,
            )
            result = outcome.result
            if result.ok and result.entry is not None:
                refreshed = result.entry
                if result.suggested_word:
                    refreshed.word = result.suggested_word
                refreshed.language = language  # type: ignore[assignment]
                refreshed.id = original_entry.id
                refreshed.created_at = original_entry.created_at
                if current.tags:
                    refreshed.tags = list(current.tags)
                if current.memo:
                    refreshed.memo = current.memo
                refreshed.touch()
                new_key = self._save_edit(
                    language,
                    original_key,
                    refreshed,
                    create_backup=False,
                )
                if new_key:
                    state["key"] = new_key
                dialog.set_entry(refreshed)
                dialog.show_status("재조회 완료 · 단어장에 반영했습니다.")
                return

            self._restore_entry(language, original_key, original_entry)
            dialog.set_entry(original_entry)
            dialog.show_status("재조회 결과가 없어 기존 데이터를 복원했습니다.")
            self._status.showMessage("재조회 결과 없음 · 기존 데이터를 복원했습니다.")
        except Exception as exc:
            log.exception("wordbook requery failed")
            self._restore_entry(language, original_key, original_entry)
            dialog.set_entry(original_entry)
            dialog.show_status("재조회 실패 · 기존 데이터를 복원했습니다.")
            self._status.showMessage(f"재조회 실패: {exc}")
        finally:
            dialog.set_busy(False)

    def _restore_entry(
        self,
        language: str,
        original_key: str,
        entry: VocabularyEntry,
    ) -> None:
        path = Path(self._settings.excel_path_for(language))
        try:
            excel_writer.replace_entry(
                path,
                language,
                original_key,
                entry,
                self._settings.excel_columns,
                create_backup=False,
            )
            self._cache.upsert(entry)
            self._refresh_after_mutation(language)
        except Exception as exc:
            log.warning("wordbook restore after requery failed: %s", exc)

    def _refresh_after_mutation(self, language: str) -> None:
        self.update_saved_words_cache()
        self.show_inline(language, self._current_sort_option)
        if callable(self._remember_last_view_mode):
            self._remember_last_view_mode(language)

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
        EntryDetailDialog(entry, self._parent, settings=self._settings).exec()
