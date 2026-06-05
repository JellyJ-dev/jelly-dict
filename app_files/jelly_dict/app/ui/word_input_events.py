from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.word_input_components import _compact_detection_status


class WordInputEventsMixin:
    def reset_input(self) -> None:
        self.input.clear()
        self.input.setFocus()

    def set_detection_label(self, text: str) -> None:
        self._detection_status = _compact_detection_status(text)
        self._render_footer_status_summary()

    def set_status_summary(self, text: str) -> None:
        self._base_status_summary = text
        self._render_footer_status_summary()

    def _render_footer_status_summary(self) -> None:
        parts = [part for part in (self._base_status_summary, self._detection_status) if part]
        self.status_summary.setText(" · ".join(parts))

    def set_anki_export_status(self, text: str) -> None:
        self.wordbook_export_btn.set_status_text(text)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if self._first_image_path(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        path = self._first_image_path(event.mimeData())
        if path is not None:
            self.imageDropped.emit(str(path))
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if isinstance(watched, QtWidgets.QPushButton) and watched in self._hover_icons:
            normal_icon, active_icon = self._hover_icons[watched]
            if event.type() == QtCore.QEvent.Enter:
                watched.setIcon(active_icon)
            elif event.type() == QtCore.QEvent.Leave:
                watched.setIcon(normal_icon)
        if watched is self.input and event.type() in (
            QtCore.QEvent.FocusIn,
            QtCore.QEvent.KeyPress,
        ):
            self.prewarmRequested.emit()
        if watched is self.input and event.type() == QtCore.QEvent.KeyPress:
            key_event = event
            if isinstance(key_event, QtGui.QKeyEvent) and key_event.matches(
                QtGui.QKeySequence.Paste
            ):
                return self._paste_clipboard_image_if_available()
        if event.type() == QtCore.QEvent.KeyPress and isinstance(event, QtGui.QKeyEvent):
            if watched is getattr(self, "wordbook_search", None):
                return self._handle_list_search_key_press(event)
            if watched is getattr(self, "recent_list", None):
                return self._handle_list_key_press(event)
        return super().eventFilter(watched, event)

    def _handle_list_search_key_press(self, event: QtGui.QKeyEvent) -> bool:
        if self.wordbook_search.isHidden():
            return False
        if event.key() == QtCore.Qt.Key_Escape and self.wordbook_search.text():
            self.wordbook_search.clear()
            self._search_debounce.stop()
            self._render_current_list()
            return True
        if not self._is_plain_key_press(event):
            return False
        if event.key() == QtCore.Qt.Key_Down:
            self._flush_pending_search_render()
            return self._focus_list_item(self._first_selectable_list_item())
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self._flush_pending_search_render()
            return self._open_list_item(self._first_selectable_list_item())
        return False

    def _handle_list_key_press(self, event: QtGui.QKeyEvent) -> bool:
        if (
            event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter)
            and self._is_plain_key_press(event)
        ):
            return self._open_current_or_first_list_item()
        if self._list_mode not in ("en", "ja"):
            return False
        if event.matches(QtGui.QKeySequence.Copy):
            if self._selected_wordbook_words():
                self._copy_selected_wordbook_items()
                return True
            return False
        if event.matches(QtGui.QKeySequence.SelectAll):
            self._select_visible_wordbook_items()
            return True
        if event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            if self._selected_wordbook_words():
                self._request_wordbook_delete()
                return True
            return False
        return False

    def _is_plain_key_press(self, event: QtGui.QKeyEvent) -> bool:
        modifiers = event.modifiers() & ~QtCore.Qt.KeyboardModifier.KeypadModifier
        return modifiers == QtCore.Qt.KeyboardModifier.NoModifier

    def _flush_pending_search_render(self) -> None:
        if self._search_debounce.isActive():
            self._search_debounce.stop()
            self._render_current_list()

    def _first_selectable_list_item(self) -> QtWidgets.QListWidgetItem | None:
        for index in range(self.recent_list.count()):
            item = self.recent_list.item(index)
            if self._is_openable_list_item(item):
                return item
        return None

    def _current_or_first_selectable_list_item(self) -> QtWidgets.QListWidgetItem | None:
        current = self.recent_list.currentItem()
        if current is not None and self._is_openable_list_item(current):
            return current
        return self._first_selectable_list_item()

    def _focus_list_item(self, item: QtWidgets.QListWidgetItem | None) -> bool:
        if item is None:
            return False
        self.recent_list.setFocus(QtCore.Qt.OtherFocusReason)
        self.recent_list.setCurrentItem(item)
        if self._list_mode != "recent" and not item.isSelected():
            item.setSelected(True)
        self._on_list_selection_changed()
        return True

    def _is_openable_list_item(self, item: QtWidgets.QListWidgetItem) -> bool:
        if self._list_mode == "recent":
            return bool(item.flags() & QtCore.Qt.ItemIsEnabled)
        return bool(item.flags() & QtCore.Qt.ItemIsSelectable)

    def _open_current_or_first_list_item(self) -> bool:
        return self._open_list_item(self._current_or_first_selectable_list_item())

    def _open_list_item(self, item: QtWidgets.QListWidgetItem | None) -> bool:
        if item is None:
            return False
        self.recent_list.setCurrentItem(item)
        self._open_recent_entry(item)
        return True

    def _paste_clipboard_image_if_available(self) -> bool:
        clipboard = QtGui.QGuiApplication.clipboard()
        mime_data = clipboard.mimeData()
        path = self._first_image_path(mime_data)
        if path is not None:
            self.imageDropped.emit(str(path))
            return True
        if mime_data.hasImage():
            image_data = mime_data.imageData()
            if isinstance(image_data, QtGui.QImage) and not image_data.isNull():
                self.clipboardImagePasted.emit(image_data)
                return True
            if isinstance(image_data, QtGui.QPixmap) and not image_data.isNull():
                self.clipboardImagePasted.emit(image_data.toImage())
                return True
        return False

    def _first_image_path(self, mime_data: QtCore.QMimeData) -> Path | None:
        if not mime_data.hasUrls():
            return None
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in allowed:
                return path
        return None
