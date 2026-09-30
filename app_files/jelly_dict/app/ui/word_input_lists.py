from __future__ import annotations

from collections import defaultdict

from PySide6 import QtCore, QtWidgets

from app.ui.widgets.wordbook_items import (
    WordbookDisplayItem,
    WordbookItem,
    coerce_wordbook_item,
    filter_wordbook_items,
)
from app.ui.widgets.wordbook_row import WordbookRow
from app.ui.word_input_parts.labels_buttons import _repolish
from app.ui.word_input_parts.layout_constants import (
    NORMAL_LIST_HEIGHT,
    RECENT_EMPTY_TEXT,
    RECENT_FILTER_EMPTY_TEXT,
    ROOT_MARGIN_EXPANDED,
    ROOT_MARGIN_NORMAL,
    WORDBOOK_EMPTY_TEXT,
    WORDBOOK_FILTER_EMPTY_TEXT,
)
from app.ui.word_input_parts.text_parsing import _elide
from app.ui.word_input_ui_refs import WordInputUiRefs

WORDBOOK_ENTRY_REF_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 1
WORDBOOK_IDENTITY_ROLE = WORDBOOK_ENTRY_REF_ROLE + 1
WORDBOOK_EAGER_ROW_LIMIT = 48


class WordbookPresenter:
    def __init__(self, ui: WordInputUiRefs, facade: QtWidgets.QWidget) -> None:
        self.ui = ui
        self._state = facade
        self._signals = facade

    def set_recent(self, items: list[tuple[str, str, str, str]]) -> None:
        """Each item is (word, language, hint, status). Hint is the first Korean
        meaning shown after an em-dash so the user can verify saves at a
        glance."""
        previous_mode = self._state._list_mode
        if previous_mode in ("en", "ja"):
            self._dispose_wordbook_rows()
        display_items = items[:20]
        self._state._list_mode = "recent"
        self._state._recent_items = list(display_items)
        self._state._wordbook_items = []
        self._state._wordbook_dirty_keys.clear()
        self._state._wordbook_visible_keys.clear()
        self.ui.top_area.setVisible(not self._state._wordbook_expanded)
        self.ui.top_area.setMaximumHeight(0 if self._state._wordbook_expanded else 16777215)
        self._apply_wordbook_chrome_state()
        self.ui.recent_title_btn.setText("최근 단어")
        self.ui.wordbook_expand_btn.setVisible(True)
        self.ui.wordbook_sort_btn.setVisible(False)
        self.ui.wordbook_stats.setVisible(False)
        self.ui.clear_recent_btn.setVisible(True)
        self.ui.clear_recent_btn.setEnabled(bool(display_items))
        self.ui.wordbook_export_btn.setVisible(False)
        self.ui.wordbook_export_btn.setEnabled(True)
        self.ui.wordbook_delete_btn.setVisible(False)
        self.ui.wordbook_delete_btn.setEnabled(False)
        self._state._search_debounce.stop()
        if previous_mode != "recent":
            self.ui.wordbook_search.clear()
        self.ui.wordbook_search.setPlaceholderText("최근 단어 검색...")
        self.ui.wordbook_search.setVisible(bool(display_items))
        self.ui.wordbook_search.setMaximumHeight(16777215)
        self.ui.recent_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.ui.recent_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.ui.recent_list.setMinimumHeight(NORMAL_LIST_HEIGHT)
        self.ui.recent_list.setMaximumHeight(16777215)
        if not display_items:
            self.ui.recent_list.clear()
            self._add_empty_list_item(RECENT_EMPTY_TEXT, NORMAL_LIST_HEIGHT)
            return
        self._render_recent()

    def recent_count(self) -> int:
        return len(self._state._recent_items)

    def _render_current_list(self) -> None:
        if self._state._list_mode == "recent":
            self._render_recent()
            return
        self._render_wordbook()

    def _render_recent(self) -> None:
        if self._state._list_mode != "recent":
            return
        needle = self.ui.wordbook_search.text().strip().lower()
        if needle:
            display_items = [
                item
                for item in self._state._recent_items
                if needle in item[0].lower()
                or needle in item[1].lower()
                or needle in item[2].lower()
            ]
        else:
            display_items = list(self._state._recent_items)

        self.ui.recent_list.clear()
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
            self.ui.recent_list.addItem(qt_item)

    def set_wordbook(self, language: str, items: list[WordbookItem]) -> None:
        previous_mode = self._state._list_mode
        previous_display = self._state._wordbook_display_by_key
        if previous_mode in ("en", "ja") and previous_mode != language:
            self._dispose_wordbook_rows()
        self._state._list_mode = language
        self._state._wordbook_items = [coerce_wordbook_item(item) for item in items]
        self._state._wordbook_item_keys = self._make_wordbook_item_keys(self._state._wordbook_items)
        self._state._wordbook_display_by_key = {
            self._state._wordbook_item_keys[id(item)]: item for item in self._state._wordbook_items
        }
        self._state._wordbook_dirty_keys = {
            key
            for key, item in self._state._wordbook_display_by_key.items()
            if self._wordbook_item_changed(previous_display.get(key), item)
        }
        title = "일본어 단어장" if language == "ja" else "영어 단어장"
        self.ui.recent_title_btn.setText(title)
        self.ui.top_area.setVisible(not self._state._wordbook_expanded)
        self.ui.top_area.setMaximumHeight(0 if self._state._wordbook_expanded else 16777215)
        self._apply_wordbook_chrome_state()
        self.ui.wordbook_expand_btn.setVisible(True)
        self.ui.wordbook_sort_btn.setVisible(True)
        self.ui.wordbook_stats.setVisible(True)
        self.ui.clear_recent_btn.setVisible(False)
        self.ui.wordbook_export_btn.setVisible(True)
        self.ui.wordbook_export_btn.setEnabled(bool(self._state._wordbook_items))
        self.ui.wordbook_export_btn.set_language(language)
        self.ui.wordbook_delete_btn.setVisible(False)
        self.ui.wordbook_delete_btn.setEnabled(False)
        self._state._search_debounce.stop()
        self.ui.wordbook_search.setPlaceholderText("단어 / 뜻 / 태그 / 메모 검색...")
        if previous_mode != language:
            self.ui.wordbook_search.clear()
        self.ui.wordbook_search.setVisible(True)
        self.ui.wordbook_search.setMaximumHeight(16777215)
        self.ui.recent_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.ui.recent_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.ui.recent_list.setMinimumHeight(NORMAL_LIST_HEIGHT)
        self.ui.recent_list.setMaximumHeight(16777215)
        if previous_mode not in ("en", "ja"):
            # Drop text-only items from the recent mode before installing rows.
            self.ui.recent_list.clear()
        self._render_wordbook()
        self._prune_wordbook_row_pool(set(self._state._wordbook_item_keys.values()))

    def _render_wordbook(self) -> None:
        if self._state._list_mode not in ("en", "ja"):
            return
        needle = self.ui.wordbook_search.text().strip().lower()
        if needle:
            items = self._filtered_wordbook_items(needle)
        else:
            items = list(self._state._wordbook_items)

        target_keys = [self._state._wordbook_item_keys[id(item)] for item in items]
        full_keys = [
            self._state._wordbook_item_keys[id(item)] for item in self._state._wordbook_items
        ]
        self.ui.recent_list.setUpdatesEnabled(False)
        try:
            current_keys = self._listed_wordbook_keys()
            if self._state._wordbook_items and current_keys == full_keys:
                for key in self._state._wordbook_dirty_keys:
                    item = self._state._wordbook_display_by_key.get(key)
                    pooled = self._state._wordbook_row_pool.get(key)
                    if item is None or pooled is None:
                        continue
                    qt_item, row_obj = pooled
                    self._update_wordbook_qt_item(qt_item, item, key)
                    if isinstance(row_obj, WordbookRow):
                        row_obj.update_item(item)
            else:
                self._reconcile_wordbook_rows(
                    self._state._wordbook_items,
                    full_keys,
                    needle,
                )
            self._apply_wordbook_visibility(set(target_keys), needle)
            self._state._wordbook_dirty_keys.clear()
        finally:
            self.ui.recent_list.setUpdatesEnabled(True)
        self._hydrate_visible_wordbook_rows()
        self._on_list_selection_changed()

    def _build_wordbook_row(
        self,
        item: WordbookDisplayItem,
    ) -> WordbookRow:
        row = WordbookRow(item.language, item.word, item.reading, item.hint)
        row.editRequested.connect(self._edit_wordbook_from_row)
        row.deleteRequested.connect(self._delete_wordbook_from_row)
        return row

    def _reconcile_wordbook_rows(
        self,
        items: list[WordbookDisplayItem],
        target_keys: list[object],
        needle: str,
    ) -> None:
        self._remove_wordbook_empty_item()
        selected_keys = {
            item.data(WORDBOOK_IDENTITY_ROLE) for item in self.ui.recent_list.selectedItems()
        }
        current_item = self.ui.recent_list.currentItem()
        current_key = (
            current_item.data(WORDBOOK_IDENTITY_ROLE) if current_item is not None else None
        )

        blocker = QtCore.QSignalBlocker(self.ui.recent_list)
        scroll_blocker = QtCore.QSignalBlocker(self.ui.recent_list.verticalScrollBar())
        try:
            # takeItem() schedules deletion of its index widget. Reparenting
            # and reattaching that widget cannot undo the DeferredDelete event.
            # Remove only obsolete rows; move surviving model rows in place.
            self._prune_wordbook_row_pool(set(target_keys))

            if not items:
                self._state._wordbook_visible_keys.clear()
                return

            restored_current: QtWidgets.QListWidgetItem | None = None
            attached_visible_keys: set[object] = set()
            eager_all = len(items) <= WORDBOOK_EAGER_ROW_LIMIT
            for position, (item, key) in enumerate(zip(items, target_keys, strict=True)):
                pooled = self._state._wordbook_row_pool.get(key)
                if pooled is None:
                    qt_item = QtWidgets.QListWidgetItem()
                    row = (
                        self._build_wordbook_row(item)
                        if eager_all or position < WORDBOOK_EAGER_ROW_LIMIT
                        else None
                    )
                    self._state._wordbook_row_pool[key] = (qt_item, row)
                else:
                    qt_item, row_obj = pooled
                    row = row_obj if isinstance(row_obj, WordbookRow) else None
                    if row is None and (eager_all or position < WORDBOOK_EAGER_ROW_LIMIT):
                        row = self._build_wordbook_row(item)
                        self._state._wordbook_row_pool[key] = (qt_item, row)
                self._update_wordbook_qt_item(qt_item, item, key)
                if row is not None:
                    row.update_item(item)
                current_position = self.ui.recent_list.row(qt_item)
                if current_position < 0:
                    self.ui.recent_list.insertItem(position, qt_item)
                elif current_position != position:
                    destination = position if current_position > position else position + 1
                    self.ui.recent_list.model().moveRows(
                        QtCore.QModelIndex(),
                        current_position,
                        1,
                        QtCore.QModelIndex(),
                        destination,
                    )
                if row is not None and self.ui.recent_list.itemWidget(qt_item) is not row:
                    self.ui.recent_list.setItemWidget(qt_item, row)
                if not qt_item.isHidden():
                    attached_visible_keys.add(key)
                if key in selected_keys:
                    qt_item.setSelected(True)
                if key == current_key:
                    restored_current = qt_item
            if restored_current is not None:
                self.ui.recent_list.setCurrentItem(
                    restored_current, QtCore.QItemSelectionModel.NoUpdate
                )
            self._state._wordbook_visible_keys = attached_visible_keys
        finally:
            del scroll_blocker
            del blocker

    def _listed_wordbook_keys(self) -> list[object]:
        keys: list[object] = []
        for index in range(self.ui.recent_list.count()):
            key = self.ui.recent_list.item(index).data(WORDBOOK_IDENTITY_ROLE)
            if key is not None:
                keys.append(key)
        return keys

    def _apply_wordbook_visibility(
        self,
        visible_keys: set[object],
        needle: str,
    ) -> None:
        viewport = self.ui.recent_list.viewport()
        changed_keys = self._state._wordbook_visible_keys.symmetric_difference(visible_keys)
        materialize_keys = (
            {
                key
                for key in visible_keys
                if key in self._state._wordbook_row_pool
                and not isinstance(self._state._wordbook_row_pool[key][1], WordbookRow)
            }
            if len(visible_keys) <= WORDBOOK_EAGER_ROW_LIMIT
            else set()
        )
        for key in changed_keys | materialize_keys:
            pooled = self._state._wordbook_row_pool.get(key)
            if pooled is None:
                continue
            qt_item, row_obj = pooled
            visible = key in visible_keys
            qt_item.setHidden(not visible)
            if visible and not isinstance(row_obj, WordbookRow):
                if len(visible_keys) <= WORDBOOK_EAGER_ROW_LIMIT:
                    item = self._state._wordbook_display_by_key.get(key)
                    if item is not None:
                        row_obj = self._build_wordbook_row(item)
                        self._state._wordbook_row_pool[key] = (qt_item, row_obj)
                else:
                    continue
            if not isinstance(row_obj, WordbookRow):
                continue
            if visible:
                if row_obj.parent() is not viewport:
                    self.ui.recent_list.setItemWidget(qt_item, row_obj)
            # QListWidget owns index widgets even while their items are hidden.
            # Keep that ownership instead of turning pooled rows into windows.
            row_obj.setVisible(visible)
        self._state._wordbook_visible_keys = set(visible_keys)

        if visible_keys:
            self._remove_wordbook_empty_item()
            return
        text = WORDBOOK_FILTER_EMPTY_TEXT if needle else WORDBOOK_EMPTY_TEXT
        height = 120 if needle else NORMAL_LIST_HEIGHT
        if self._state._wordbook_empty_item is None:
            self._state._wordbook_empty_item = QtWidgets.QListWidgetItem()
            self.ui.recent_list.addItem(self._state._wordbook_empty_item)
        self._state._wordbook_empty_item.setText(text)
        self._state._wordbook_empty_item.setFlags(QtCore.Qt.NoItemFlags)
        self._state._wordbook_empty_item.setTextAlignment(QtCore.Qt.AlignCenter)
        self._state._wordbook_empty_item.setSizeHint(QtCore.QSize(620, height))
        self._state._wordbook_empty_item.setHidden(False)

    def _remove_wordbook_empty_item(self) -> None:
        item = self._state._wordbook_empty_item
        if item is None:
            return
        index = self.ui.recent_list.row(item)
        if index >= 0:
            self.ui.recent_list.takeItem(index)
        self._state._wordbook_empty_item = None

    def _hydrate_visible_wordbook_rows(self) -> None:
        if self._state._list_mode not in ("en", "ja") or not self._state._wordbook_row_pool:
            return
        viewport = self.ui.recent_list.viewport()
        top_index = self._edge_visible_index(from_top=True)
        bottom_index = self._edge_visible_index(from_top=False)
        if not top_index.isValid():
            return
        first = max(0, top_index.row() - 2)
        last = bottom_index.row() if bottom_index.isValid() else first + 20
        last = min(self.ui.recent_list.count() - 1, last + 2)
        current_item = self.ui.recent_list.currentItem()
        selected_count = max(1, len(self._selected_wordbook_words()))
        for index in range(first, last + 1):
            qt_item = self.ui.recent_list.item(index)
            if qt_item.isHidden():
                continue
            key = qt_item.data(WORDBOOK_IDENTITY_ROLE)
            pooled = self._state._wordbook_row_pool.get(key)
            item = self._state._wordbook_display_by_key.get(key)
            if pooled is None or item is None:
                continue
            _, row_obj = pooled
            if not isinstance(row_obj, WordbookRow):
                row_obj = self._build_wordbook_row(item)
                self._state._wordbook_row_pool[key] = (qt_item, row_obj)
            row_obj.update_item(item)
            if row_obj.parent() is not viewport:
                self.ui.recent_list.setItemWidget(qt_item, row_obj)
            row_obj.set_actions_visible(
                qt_item is current_item and qt_item.isSelected(),
                selected_count,
            )

    def _edge_visible_index(self, *, from_top: bool) -> QtCore.QModelIndex:
        """Find a visible row without assuming that the viewport edge hits a card.

        QListWidget spacing leaves a narrow empty gutter around each item.  Probing
        a fixed point in that gutter returns an invalid index and used to prevent
        every lazy row after the eager prefix from being materialized.
        """
        viewport = self.ui.recent_list.viewport()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return QtCore.QModelIndex()
        x = max(0, viewport.width() // 2)
        edge_scan = min(viewport.height(), 96)
        y_values = (
            range(edge_scan)
            if from_top
            else range(viewport.height() - 1, viewport.height() - edge_scan - 1, -1)
        )
        for y in y_values:
            index = self.ui.recent_list.indexAt(QtCore.QPoint(x, y))
            if index.isValid():
                return index
        return QtCore.QModelIndex()

    @staticmethod
    def _update_wordbook_qt_item(
        qt_item: QtWidgets.QListWidgetItem,
        item: WordbookDisplayItem,
        key: object,
    ) -> None:
        payload = (item.word, item.language)
        flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        if qt_item.text():
            qt_item.setText("")
        if qt_item.flags() != flags:
            qt_item.setFlags(flags)
        if qt_item.data(QtCore.Qt.UserRole) != payload:
            qt_item.setData(QtCore.Qt.UserRole, payload)
        if qt_item.data(WORDBOOK_ENTRY_REF_ROLE) is not item.entry_ref:
            qt_item.setData(WORDBOOK_ENTRY_REF_ROLE, item.entry_ref)
        if qt_item.data(WORDBOOK_IDENTITY_ROLE) != key:
            qt_item.setData(WORDBOOK_IDENTITY_ROLE, key)
        if qt_item.toolTip():
            qt_item.setToolTip("")
        size_hint = QtCore.QSize(620, 62)
        if qt_item.sizeHint() != size_hint:
            qt_item.setSizeHint(size_hint)

    @staticmethod
    def _make_wordbook_item_keys(
        items: list[WordbookDisplayItem],
    ) -> dict[int, object]:
        occurrences: defaultdict[object, int] = defaultdict(int)
        keys: dict[int, object] = {}
        for item in items:
            if item.entry_ref is not None:
                try:
                    hash(item.entry_ref)
                    base: object = ("ref", item.entry_ref)
                except TypeError:
                    base = ("ref-id", id(item.entry_ref))
            else:
                base = ("word", item.language, item.word.casefold())
            occurrence = occurrences[base]
            occurrences[base] += 1
            keys[id(item)] = (base, occurrence)
        return keys

    def _prune_wordbook_row_pool(self, valid_keys: set[object]) -> None:
        for key in list(self._state._wordbook_row_pool):
            if key in valid_keys:
                continue
            qt_item, row = self._state._wordbook_row_pool.pop(key)
            if self.ui.recent_list.row(qt_item) >= 0:
                self.ui.recent_list.takeItem(self.ui.recent_list.row(qt_item))
            if isinstance(row, QtWidgets.QWidget):
                row.hide()
                row.deleteLater()

    def _dispose_wordbook_rows(self) -> None:
        detached_rows = {
            id(row): row
            for _qt_item, row in self._state._wordbook_row_pool.values()
            if isinstance(row, QtWidgets.QWidget) and row.parent() is None
        }
        self.ui.recent_list.clear()
        for row in detached_rows.values():
            row.deleteLater()
        self._state._wordbook_row_pool.clear()
        self._state._wordbook_item_keys.clear()
        self._state._wordbook_display_by_key.clear()
        self._state._wordbook_dirty_keys.clear()
        self._state._wordbook_visible_keys.clear()
        self._state._wordbook_empty_item = None

    def _filtered_wordbook_items(self, needle: str) -> list[WordbookDisplayItem]:
        return filter_wordbook_items(self._state._wordbook_items, needle)

    @staticmethod
    def _wordbook_item_changed(
        previous: WordbookDisplayItem | None,
        current: WordbookDisplayItem,
    ) -> bool:
        return (
            previous is None
            or previous != current
            or previous.search_blob != current.search_blob
            or previous.entry_ref is not current.entry_ref
        )

    def _add_empty_list_item(self, text: str, height: int) -> None:
        item = QtWidgets.QListWidgetItem(text)
        item.setFlags(QtCore.Qt.NoItemFlags)
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        item.setSizeHint(QtCore.QSize(620, height))
        self.ui.recent_list.addItem(item)

    def _toggle_wordbook_expanded(self) -> None:
        if self._state._list_mode not in ("recent", "en", "ja"):
            return
        self._state._wordbook_expanded = not self._state._wordbook_expanded
        self._apply_wordbook_chrome_state()
        self._animate_wordbook_layout()

    def _apply_wordbook_chrome_state(self) -> None:
        expanded = self._state._wordbook_expanded and self._state._list_mode in (
            "recent",
            "en",
            "ja",
        )
        self.ui.wordbook_expand_btn.setText("축소" if expanded else "확대")
        self.ui.wordbook_expand_btn.setToolTip("입력 영역 보이기" if expanded else "목록 크게 보기")
        self.ui.recent_panel.setProperty("expanded", expanded)
        self.ui.recent_panel.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding if expanded else QtWidgets.QSizePolicy.Fixed,
            QtWidgets.QSizePolicy.Expanding,
        )
        self.ui.recent_panel.setMinimumWidth(720 if expanded else 860)
        self.ui.recent_panel.setMaximumWidth(10000 if expanded else 980)
        self.ui.root_layout.setAlignment(
            self.ui.recent_panel,
            QtCore.Qt.Alignment() if expanded else QtCore.Qt.AlignHCenter,
        )
        self.ui.root_layout.setContentsMargins(
            *(ROOT_MARGIN_EXPANDED if expanded else ROOT_MARGIN_NORMAL)
        )
        _repolish(self.ui.recent_panel)

    def _animate_wordbook_layout(self) -> None:
        if self._state._list_mode not in ("recent", "en", "ja"):
            return
        if self._state._top_height_animation is not None:
            self._state._top_height_animation.stop()

        duration = 240
        if not self._state._wordbook_expanded:
            self.ui.top_area.setVisible(True)
            if self.ui.top_area.maximumHeight() == 0:
                self.ui.top_area.setMaximumHeight(0)

        full_top_height = self.ui.top_area.sizeHint().height()
        top_start = self.ui.top_area.height() if self.ui.top_area.isVisible() else 0
        top_end = 0 if self._state._wordbook_expanded else full_top_height
        self._state._top_height_animation = QtCore.QVariantAnimation(self._state)
        self._state._top_height_animation.setStartValue(top_start)
        self._state._top_height_animation.setEndValue(top_end)
        self._state._top_height_animation.setDuration(duration)
        self._state._top_height_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._state._top_height_animation.valueChanged.connect(
            lambda value: self.ui.top_area.setMaximumHeight(int(value))
        )
        self._state._top_height_animation.finished.connect(self._finish_top_animation)
        self._state._top_height_animation.start()

        self.ui.wordbook_search.setVisible(
            self._state._list_mode in ("en", "ja") or bool(self._state._recent_items)
        )
        self.ui.wordbook_search.setMaximumHeight(16777215)

    def _finish_top_animation(self) -> None:
        if self._state._wordbook_expanded:
            self.ui.top_area.setVisible(False)
            self.ui.top_area.setMaximumHeight(0)
            return
        self.ui.top_area.setVisible(True)
        self.ui.top_area.setMaximumHeight(16777215)

    def _finish_search_animation(self) -> None:
        self.ui.wordbook_search.setVisible(self._state._list_mode in ("en", "ja"))
        self.ui.wordbook_search.setMaximumHeight(16777215)

    def _on_list_selection_changed(self) -> None:
        if self._state._list_mode not in ("en", "ja"):
            return
        self._update_wordbook_toolbar_state()

    def _update_wordbook_toolbar_state(self) -> None:
        if self._state._list_mode not in ("en", "ja"):
            return
        selected = self._selected_wordbook_words()
        visible_count = self._visible_wordbook_count()
        selected_count = len(selected)
        stats = f"{visible_count}개"
        if selected_count:
            stats += f" · 선택 {selected_count}개"
        self.ui.wordbook_stats.setText(stats)
        self.ui.wordbook_delete_btn.setVisible(False)
        self.ui.wordbook_delete_btn.setEnabled(False)
        self.ui.wordbook_delete_btn.setText("선택 삭제")
        self._sync_wordbook_row_actions(selected_count)

    def _sync_wordbook_row_actions(self, selected_count: int) -> None:
        current_item = self.ui.recent_list.currentItem()
        viewport = self.ui.recent_list.viewport()
        for item, row_obj in self._state._wordbook_row_pool.values():
            if item.isHidden() or not isinstance(row_obj, WordbookRow):
                continue
            if row_obj.parent() is not viewport:
                continue
            row_obj.set_actions_visible(
                item is current_item and item.isSelected(),
                max(1, selected_count),
            )

    def _visible_wordbook_count(self) -> int:
        count = 0
        for index in range(self.ui.recent_list.count()):
            item = self.ui.recent_list.item(index)
            if not item.isHidden() and item.flags() & QtCore.Qt.ItemIsSelectable:
                count += 1
        return count

    def _selected_wordbook_words(self) -> list[str]:
        words: list[str] = []
        for item in self.ui.recent_list.selectedItems():
            if item.isHidden():
                continue
            payload = item.data(QtCore.Qt.UserRole)
            if not (isinstance(payload, tuple) and len(payload) == 2):
                continue
            word, language = payload
            if language == self._state._list_mode and isinstance(word, str) and word.strip():
                words.append(word.strip())
        return words

    def selected_wordbook_entry_refs(self) -> list[object]:
        """Return hidden row identities for the current selection, if complete."""
        refs: list[object] = []
        for item in self.ui.recent_list.selectedItems():
            if item.isHidden():
                continue
            ref = item.data(WORDBOOK_ENTRY_REF_ROLE)
            if ref is None:
                return []
            refs.append(ref)
        return refs

    def _select_visible_wordbook_items(self) -> None:
        if self._state._list_mode not in ("en", "ja"):
            return
        self.ui.recent_list.clearSelection()
        first_selectable: QtWidgets.QListWidgetItem | None = None
        for index in range(self.ui.recent_list.count()):
            item = self.ui.recent_list.item(index)
            if not item.isHidden() and item.flags() & QtCore.Qt.ItemIsSelectable:
                if first_selectable is None:
                    first_selectable = item
        if first_selectable is not None:
            self.ui.recent_list.setCurrentItem(first_selectable)
        for index in range(self.ui.recent_list.count()):
            item = self.ui.recent_list.item(index)
            if not item.isHidden() and item.flags() & QtCore.Qt.ItemIsSelectable:
                item.setSelected(True)
        self._update_wordbook_toolbar_state()

    def _wordbook_words_for_row_action(self, word: str) -> list[str]:
        if self._state._list_mode not in ("en", "ja"):
            return []
        selected = self._selected_wordbook_words()
        if word in selected:
            return selected
        return [word] if word.strip() else []

    def _edit_wordbook_from_row(self, word: str) -> None:
        if self._state._list_mode in ("en", "ja") and word.strip():
            self._signals.wordbookEditRequested.emit(self._state._list_mode, word.strip())

    def _delete_wordbook_from_row(self, word: str) -> None:
        words = self._wordbook_words_for_row_action(word)
        if words:
            self._signals.wordbookDeleteRequested.emit(self._state._list_mode, words)

    def _copy_selected_wordbook_items(self) -> None:
        words = self._selected_wordbook_words()
        if not words:
            return
        QtWidgets.QApplication.clipboard().setText("\n".join(words))
        self.ui.status_summary.setText(f"선택한 단어 {len(words)}개 복사됨")

    def _request_wordbook_delete(self) -> None:
        if self._state._list_mode not in ("en", "ja"):
            return
        words = self._selected_wordbook_words()
        if words:
            self._signals.wordbookDeleteRequested.emit(self._state._list_mode, words)

    def _request_wordbook_export(self) -> None:
        if self._state._list_mode not in ("en", "ja"):
            return
        self._signals.wordbookExportRequested.emit(self._state._list_mode, "settings", False)


__all__ = ["WordbookPresenter"]
