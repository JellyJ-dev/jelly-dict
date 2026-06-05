from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.ui.widgets.wordbook_items import (
    WordbookDisplayItem,
    WordbookItem,
    coerce_wordbook_item,
    filter_wordbook_items,
)
from app.ui.widgets.wordbook_row import WordbookRow
from app.ui.word_input_components import (
    NORMAL_LIST_HEIGHT,
    RECENT_EMPTY_TEXT,
    RECENT_FILTER_EMPTY_TEXT,
    ROOT_MARGIN_EXPANDED,
    ROOT_MARGIN_NORMAL,
    WORDBOOK_EMPTY_TEXT,
    WORDBOOK_FILTER_EMPTY_TEXT,
    _elide,
    _repolish,
)


class WordInputListMixin:
    def set_recent(self, items: list[tuple[str, str, str, str]]) -> None:
        """Each item is (word, language, hint, status). Hint is the first Korean
        meaning shown after an em-dash so the user can verify saves at a
        glance."""
        previous_mode = self._list_mode
        display_items = items[:20]
        self._list_mode = "recent"
        self._recent_items = list(display_items)
        self._wordbook_items = []
        self.top_area.setVisible(not self._wordbook_expanded)
        self.top_area.setMaximumHeight(0 if self._wordbook_expanded else 16777215)
        self._apply_wordbook_chrome_state()
        self.recent_title_btn.setText("최근 단어")
        self.wordbook_expand_btn.setVisible(True)
        self.wordbook_sort_btn.setVisible(False)
        self.wordbook_stats.setVisible(False)
        self.clear_recent_btn.setVisible(True)
        self.clear_recent_btn.setEnabled(bool(display_items))
        self.wordbook_export_btn.setVisible(False)
        self.wordbook_export_btn.setEnabled(True)
        self.wordbook_delete_btn.setVisible(False)
        self.wordbook_delete_btn.setEnabled(False)
        self._search_debounce.stop()
        if previous_mode != "recent":
            self.wordbook_search.clear()
        self.wordbook_search.setPlaceholderText("최근 단어 검색...")
        self.wordbook_search.setVisible(bool(display_items))
        self.wordbook_search.setMaximumHeight(16777215)
        self.recent_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.recent_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.recent_list.setMinimumHeight(NORMAL_LIST_HEIGHT)
        self.recent_list.setMaximumHeight(16777215)
        if not display_items:
            self.recent_list.clear()
            self._add_empty_list_item(RECENT_EMPTY_TEXT, NORMAL_LIST_HEIGHT)
            return
        self._render_recent()

    def recent_count(self) -> int:
        return len(self._recent_items)

    def _render_current_list(self) -> None:
        if self._list_mode == "recent":
            self._render_recent()
            return
        self._render_wordbook()

    def _render_recent(self) -> None:
        if self._list_mode != "recent":
            return
        needle = self.wordbook_search.text().strip().lower()
        if needle:
            display_items = [
                item
                for item in self._recent_items
                if needle in item[0].lower()
                or needle in item[1].lower()
                or needle in item[2].lower()
            ]
        else:
            display_items = list(self._recent_items)

        self.recent_list.clear()
        if not display_items:
            self._add_empty_list_item(
                RECENT_FILTER_EMPTY_TEXT if needle else RECENT_EMPTY_TEXT,
                120 if needle else NORMAL_LIST_HEIGHT,
            )
            return
        for word, language, hint, status in display_items:
            prefix = "✓ " if status == "saved" else ""
            label = f"{prefix}[{language}] {word}"
            if hint:
                label += f"  —  {hint}"
            display_label = _elide(label, 58)
            qt_item = QtWidgets.QListWidgetItem(label)
            qt_item.setFlags(QtCore.Qt.ItemIsEnabled)
            qt_item.setText(display_label)
            qt_item.setData(QtCore.Qt.UserRole, (word, language))
            qt_item.setToolTip("")
            qt_item.setSizeHint(QtCore.QSize(620, 36))
            self.recent_list.addItem(qt_item)

    def set_wordbook(self, language: str, items: list[WordbookItem]) -> None:
        previous_mode = self._list_mode
        self._list_mode = language
        self._wordbook_items = [coerce_wordbook_item(item) for item in items]
        title = "일본어 단어장" if language == "ja" else "영어 단어장"
        self.recent_title_btn.setText(title)
        self.top_area.setVisible(not self._wordbook_expanded)
        self.top_area.setMaximumHeight(0 if self._wordbook_expanded else 16777215)
        self._apply_wordbook_chrome_state()
        self.wordbook_expand_btn.setVisible(True)
        self.wordbook_sort_btn.setVisible(True)
        self.wordbook_stats.setVisible(True)
        self.clear_recent_btn.setVisible(False)
        self.wordbook_export_btn.setVisible(True)
        self.wordbook_export_btn.setEnabled(bool(self._wordbook_items))
        self.wordbook_export_btn.set_language(language)
        self.wordbook_delete_btn.setVisible(False)
        self.wordbook_delete_btn.setEnabled(False)
        self._search_debounce.stop()
        self.wordbook_search.setPlaceholderText("단어 / 뜻 / 태그 / 메모 검색...")
        if previous_mode != language:
            self.wordbook_search.clear()
        self.wordbook_search.setVisible(True)
        self.wordbook_search.setMaximumHeight(16777215)
        self.recent_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.recent_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.recent_list.setMinimumHeight(NORMAL_LIST_HEIGHT)
        self.recent_list.setMaximumHeight(16777215)
        # Mode transition: drop any items from the previous (recent) mode
        # so leftover text labels don't bleed through under the wordbook
        # row widgets we install via setItemWidget.
        self.recent_list.clear()
        self._render_wordbook()

    def _render_wordbook(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        needle = self.wordbook_search.text().strip().lower()
        if needle:
            items = self._filtered_wordbook_items(needle)
        else:
            items = list(self._wordbook_items)

        # Reuse existing items in place when the count matches: avoids
        # tearing down + rebuilding QWidget instances on every render
        # (matters when filtering a large wordbook). Visual output is
        # identical to the previous "clear + addItem in a loop" path.
        self.recent_list.setUpdatesEnabled(False)
        try:
            self.recent_list.clearSelection()
            current = self.recent_list.count()
            target = len(items)
            if target == 0:
                self.recent_list.clear()
                self._add_empty_list_item(
                    WORDBOOK_FILTER_EMPTY_TEXT if needle else WORDBOOK_EMPTY_TEXT,
                    120 if needle else NORMAL_LIST_HEIGHT,
                )
                self._on_list_selection_changed()
                return
            for i in range(min(current, target)):
                item = items[i]
                qt_item = self.recent_list.item(i)
                qt_item.setText("")
                qt_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                qt_item.setData(QtCore.Qt.UserRole, (item.word, item.language))
                qt_item.setToolTip("")
                qt_item.setSizeHint(QtCore.QSize(620, 62))
                self._set_wordbook_row_widget(qt_item, item)
            # Append any extra rows.
            for i in range(current, target):
                item = items[i]
                qt_item = QtWidgets.QListWidgetItem()
                qt_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                qt_item.setData(QtCore.Qt.UserRole, (item.word, item.language))
                qt_item.setToolTip("")
                qt_item.setSizeHint(QtCore.QSize(620, 62))
                self.recent_list.addItem(qt_item)
                self._set_wordbook_row_widget(qt_item, item)
            # Drop trailing rows from the previous render.
            while self.recent_list.count() > target:
                trailing_item = self.recent_list.item(self.recent_list.count() - 1)
                self._remove_wordbook_row_widget(trailing_item)
                self.recent_list.takeItem(self.recent_list.count() - 1)
        finally:
            self.recent_list.setUpdatesEnabled(True)
        self._on_list_selection_changed()

    def _build_wordbook_row(
        self,
        item: WordbookDisplayItem,
    ) -> WordbookRow:
        row = WordbookRow(item.language, item.word, item.reading, item.hint)
        row.editRequested.connect(self._edit_wordbook_from_row)
        row.deleteRequested.connect(self._delete_wordbook_from_row)
        return row

    def _set_wordbook_row_widget(
        self,
        qt_item: QtWidgets.QListWidgetItem,
        item: WordbookDisplayItem,
    ) -> None:
        self._remove_wordbook_row_widget(qt_item)
        self.recent_list.setItemWidget(qt_item, self._build_wordbook_row(item))

    def _remove_wordbook_row_widget(self, qt_item: QtWidgets.QListWidgetItem) -> None:
        old_widget = self.recent_list.itemWidget(qt_item)
        if old_widget is not None:
            self.recent_list.removeItemWidget(qt_item)
            old_widget.hide()
            old_widget.setParent(None)
            old_widget.deleteLater()

    def _filtered_wordbook_items(self, needle: str) -> list[WordbookDisplayItem]:
        return filter_wordbook_items(self._wordbook_items, needle)

    def _add_empty_list_item(self, text: str, height: int) -> None:
        item = QtWidgets.QListWidgetItem(text)
        item.setFlags(QtCore.Qt.NoItemFlags)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        item.setSizeHint(QtCore.QSize(620, height))
        self.recent_list.addItem(item)

    def _toggle_wordbook_expanded(self) -> None:
        if self._list_mode not in ("recent", "en", "ja"):
            return
        self._wordbook_expanded = not self._wordbook_expanded
        self._apply_wordbook_chrome_state()
        self._animate_wordbook_layout()

    def _apply_wordbook_chrome_state(self) -> None:
        expanded = self._wordbook_expanded and self._list_mode in ("recent", "en", "ja")
        self.wordbook_expand_btn.setText("축소" if expanded else "확대")
        self.wordbook_expand_btn.setToolTip(
            "입력 영역 보이기" if expanded else "목록 크게 보기"
        )
        self.recent_panel.setProperty("expanded", expanded)
        self.recent_panel.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding if expanded else QtWidgets.QSizePolicy.Fixed,
            QtWidgets.QSizePolicy.Expanding,
        )
        self.recent_panel.setMinimumWidth(720 if expanded else 860)
        self.recent_panel.setMaximumWidth(10000 if expanded else 980)
        self._root_layout.setAlignment(
            self.recent_panel,
            QtCore.Qt.Alignment() if expanded else QtCore.Qt.AlignHCenter,
        )
        self._root_layout.setContentsMargins(
            *(ROOT_MARGIN_EXPANDED if expanded else ROOT_MARGIN_NORMAL)
        )
        _repolish(self.recent_panel)

    def _animate_wordbook_layout(self) -> None:
        if self._list_mode not in ("recent", "en", "ja"):
            return
        if self._top_height_animation is not None:
            self._top_height_animation.stop()

        duration = 240
        if not self._wordbook_expanded:
            self.top_area.setVisible(True)
            if self.top_area.maximumHeight() == 0:
                self.top_area.setMaximumHeight(0)

        full_top_height = self.top_area.sizeHint().height()
        top_start = self.top_area.height() if self.top_area.isVisible() else 0
        top_end = 0 if self._wordbook_expanded else full_top_height
        self._top_height_animation = QtCore.QVariantAnimation(self)
        self._top_height_animation.setStartValue(top_start)
        self._top_height_animation.setEndValue(top_end)
        self._top_height_animation.setDuration(duration)
        self._top_height_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._top_height_animation.valueChanged.connect(
            lambda value: self.top_area.setMaximumHeight(int(value))
        )
        self._top_height_animation.finished.connect(self._finish_top_animation)
        self._top_height_animation.start()

        self.wordbook_search.setVisible(
            self._list_mode in ("en", "ja") or bool(self._recent_items)
        )
        self.wordbook_search.setMaximumHeight(16777215)

    def _finish_top_animation(self) -> None:
        if self._wordbook_expanded:
            self.top_area.setVisible(False)
            self.top_area.setMaximumHeight(0)
            return
        self.top_area.setVisible(True)
        self.top_area.setMaximumHeight(16777215)

    def _finish_search_animation(self) -> None:
        self.wordbook_search.setVisible(self._list_mode in ("en", "ja"))
        self.wordbook_search.setMaximumHeight(16777215)

    def _on_list_selection_changed(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        self._update_wordbook_toolbar_state()

    def _update_wordbook_toolbar_state(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        selected = self._selected_wordbook_words()
        visible_count = self._visible_wordbook_count()
        selected_count = len(selected)
        stats = f"{visible_count}개"
        if selected_count:
            stats += f" · 선택 {selected_count}개"
        self.wordbook_stats.setText(stats)
        self.wordbook_delete_btn.setVisible(False)
        self.wordbook_delete_btn.setEnabled(False)
        self.wordbook_delete_btn.setText("선택 삭제")
        self._sync_wordbook_row_actions(selected_count)

    def _sync_wordbook_row_actions(self, selected_count: int) -> None:
        current_item = self.recent_list.currentItem()
        for index in range(self.recent_list.count()):
            item = self.recent_list.item(index)
            row = self.recent_list.itemWidget(item)
            if isinstance(row, WordbookRow):
                row.set_actions_visible(
                    item is current_item and item.isSelected(),
                    max(1, selected_count),
                )

    def _visible_wordbook_count(self) -> int:
        count = 0
        for index in range(self.recent_list.count()):
            item = self.recent_list.item(index)
            if item.flags() & QtCore.Qt.ItemIsSelectable:
                count += 1
        return count

    def _selected_wordbook_words(self) -> list[str]:
        words: list[str] = []
        for item in self.recent_list.selectedItems():
            payload = item.data(QtCore.Qt.UserRole)
            if not (isinstance(payload, tuple) and len(payload) == 2):
                continue
            word, language = payload
            if language == self._list_mode and isinstance(word, str) and word.strip():
                words.append(word.strip())
        return words

    def _select_visible_wordbook_items(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        self.recent_list.clearSelection()
        first_selectable: QtWidgets.QListWidgetItem | None = None
        for index in range(self.recent_list.count()):
            item = self.recent_list.item(index)
            if item.flags() & QtCore.Qt.ItemIsSelectable:
                if first_selectable is None:
                    first_selectable = item
        if first_selectable is not None:
            self.recent_list.setCurrentItem(first_selectable)
        for index in range(self.recent_list.count()):
            item = self.recent_list.item(index)
            if item.flags() & QtCore.Qt.ItemIsSelectable:
                item.setSelected(True)
        self._update_wordbook_toolbar_state()

    def _wordbook_words_for_row_action(self, word: str) -> list[str]:
        if self._list_mode not in ("en", "ja"):
            return []
        selected = self._selected_wordbook_words()
        if word in selected:
            return selected
        return [word] if word.strip() else []

    def _edit_wordbook_from_row(self, word: str) -> None:
        if self._list_mode in ("en", "ja") and word.strip():
            self.wordbookEditRequested.emit(self._list_mode, word.strip())

    def _delete_wordbook_from_row(self, word: str) -> None:
        words = self._wordbook_words_for_row_action(word)
        if words:
            self.wordbookDeleteRequested.emit(self._list_mode, words)

    def _copy_selected_wordbook_items(self) -> None:
        words = self._selected_wordbook_words()
        if not words:
            return
        QtWidgets.QApplication.clipboard().setText("\n".join(words))
        self.status_summary.setText(f"선택한 단어 {len(words)}개 복사됨")

    def _request_wordbook_delete(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        words = self._selected_wordbook_words()
        if words:
            self.wordbookDeleteRequested.emit(self._list_mode, words)

    def _request_wordbook_export(self) -> None:
        if self._list_mode not in ("en", "ja"):
            return
        self.wordbookExportRequested.emit(self._list_mode, "settings", False)
