from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6 import QtCore, QtWidgets

from app.core.models import first_meaning_hint
from app.storage.cache_store import CacheStore
from app.ui.controllers.wordbook_controller import WordbookController
from app.ui.word_input_view import WordInputView

log = logging.getLogger(__name__)


class RecentController(QtCore.QObject):
    def __init__(
        self,
        parent: QtCore.QObject,
        input_view: WordInputView,
        cache: CacheStore,
        wordbook_ctrl: WordbookController,
        status_bar: QtWidgets.QStatusBar,
        remember_last_view_mode: Callable[[str], None],
        show_undo_toast: Callable[[str, Callable[[], None]], None],
    ) -> None:
        super().__init__(parent)
        self._input_view = input_view
        self._cache = cache
        self._wordbook_ctrl = wordbook_ctrl
        self._status = status_bar
        self._remember_last_view_mode = remember_last_view_mode
        self._show_undo_toast = show_undo_toast

    def refresh(self, *, remember: bool = False) -> None:
        items: list[tuple[str, str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        # Single-query JOIN: avoids N+1 round-trips per refresh.
        for lang, word, entry_word, _, cached in self._cache.recent_with_entries(40):
            hint = ""
            display = entry_word or word  # prefer the canonical lemma
            if cached is not None:
                hint = first_meaning_hint(cached)
                if cached.word:
                    display = cached.word
            is_saved = self._wordbook_ctrl.is_word_saved(display, lang)
            if cached is None and not is_saved:
                continue
            dedup_key = (lang, display.lower())
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            status = "saved" if is_saved else "recent"

            items.append((display, lang, hint, status))
            if len(items) >= 20:
                break
        self._input_view.set_recent(items)
        if remember:
            self._remember_last_view_mode("recent")

    def refresh_if_visible(self) -> None:
        if self._input_view._list_mode == "recent":
            self.refresh(remember=False)

    @QtCore.Slot()
    def clear(self) -> None:
        removed = self._input_view.recent_count()
        try:
            snapshot = self._cache.snapshot_recent_lookups()
            self._cache.clear_recent()
        except Exception as exc:
            log.warning("clear recent failed: %s", exc)
            self._status.showMessage("최근 단어 목록 지우기 실패")
            return
        self.refresh(remember=True)
        if removed <= 0:
            self._status.showMessage("최근 단어 목록을 지웠습니다")
            return
        self._status.showMessage(f"최근 단어 {removed}개 삭제됨")
        self._show_undo_toast(
            f"{removed}개를 삭제했습니다.",
            lambda: self._restore_recent(snapshot, removed),
        )

    def _restore_recent(
        self,
        snapshot: list[tuple[str, str, str | None, str]],
        removed: int,
    ) -> None:
        try:
            self._cache.restore_recent_lookups(snapshot)
        except Exception as exc:
            log.warning("restore recent failed: %s", exc)
            self._status.showMessage(f"최근 단어 되돌리기 실패: {exc}")
            return
        self.refresh(remember=True)
        self._status.showMessage(f"{removed}개 삭제를 되돌렸습니다.")
