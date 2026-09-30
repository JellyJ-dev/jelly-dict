"""Compact row widget used inside the wordbook list.

Extracted from `word_input_view.py` to keep that file focused on the
input flow. Object names stay stable so the central QSS owns the visual
language, while labels elide long content instead of overflowing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

if TYPE_CHECKING:
    from app.ui.widgets.wordbook_items import WordbookDisplayItem


class _ElideLabel(QtWidgets.QLabel):
    def __init__(self, text: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("", parent)
        self._full_text = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = text or ""
        self.setToolTip("")
        super().setText(self._elided())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        super().setText(self._elided())

    def _elided(self) -> str:
        width = max(24, self.width())
        return self.fontMetrics().elidedText(
            self._full_text,
            QtCore.Qt.ElideRight,
            width,
        )

    @property
    def full_text(self) -> str:
        return self._full_text


class WordbookRow(QtWidgets.QFrame):
    editRequested = QtCore.Signal(str)
    deleteRequested = QtCore.Signal(str)

    def __init__(
        self,
        language: str,
        word: str,
        reading: str,
        hint: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._word = word
        self._language = language
        self._reading = reading
        self._hint = hint
        self._edit_enabled = False
        self._actions_visible = False
        self._selected_count = 1
        self.setObjectName("wordbookRow")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(3)

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        layout.addLayout(top)
        self._top_layout = top

        self.word_label = _ElideLabel(word)
        self.word_label.setObjectName("wordbookWord")
        self.word_label.setMinimumWidth(0)
        self.word_label.setMaximumWidth(360 if language == "ja" and reading else 520)
        self.word_label.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        top.addWidget(self.word_label, 0)

        self.reading_label: _ElideLabel | None = None
        if language == "ja" and reading:
            self.reading_label = self._create_reading_label(reading)
            top.addWidget(self.reading_label, 0)
        top.addStretch(1)

        self.action_bar = QtWidgets.QFrame(self)
        self.action_bar.setObjectName("wordbookRowActions")
        self.action_bar.setFixedSize(96, 28)
        self.action_bar.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        action_layout = QtWidgets.QHBoxLayout(self.action_bar)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(5)
        self.edit_button = self._action_button("수정", "wordbookRowActionButton")
        self.delete_button = self._action_button("삭제", "wordbookRowDeleteButton")
        self.edit_button.clicked.connect(self._request_edit)
        self.delete_button.clicked.connect(lambda: self.deleteRequested.emit(self._word))
        action_layout.addWidget(self.edit_button)
        action_layout.addWidget(self.delete_button)
        self.action_bar.setVisible(False)

        self.meaning_label = _ElideLabel(hint)
        self.meaning_label.setObjectName("wordbookMeaning")
        self.meaning_label.setMinimumWidth(0)
        self.meaning_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.meaning_label)

    def update_item(self, item: WordbookDisplayItem) -> bool:
        """Update only changed content while preserving widget interaction state."""
        language = item.language
        word = item.word
        reading = item.reading
        hint = item.hint
        changed = (language, word, reading, hint) != (
            self._language,
            self._word,
            self._reading,
            self._hint,
        )
        if not changed:
            return False

        self._language = language
        self._word = word
        self._reading = reading
        self._hint = hint
        has_reading = language == "ja" and bool(reading)
        self.word_label.setMaximumWidth(360 if has_reading else 520)
        self._set_label_text(self.word_label, word)
        if has_reading and self.reading_label is None:
            self.reading_label = self._create_reading_label(reading)
            self._top_layout.insertWidget(1, self.reading_label, 0)
        elif self.reading_label is not None:
            self._set_label_text(self.reading_label, reading)
        if self.reading_label is not None:
            self.reading_label.setVisible(has_reading)
        self._set_label_text(self.meaning_label, hint)
        self._refresh_action_state()
        return True

    def set_actions_visible(self, visible: bool, selected_count: int = 1) -> None:
        self._actions_visible = visible
        self._selected_count = selected_count
        self._refresh_action_state()

    def _refresh_action_state(self) -> None:
        visible = self._actions_visible
        selected_count = self._selected_count
        allow_edit = visible and selected_count <= 1
        self._edit_enabled = allow_edit
        self.edit_button.setVisible(allow_edit)
        width = 96 if allow_edit else self.delete_button.width()
        self.action_bar.setFixedSize(width, 28)
        self.action_bar.setVisible(visible)
        if visible:
            self._place_action_bar()
            self.action_bar.raise_()
        count_text = f"선택 {selected_count}개" if selected_count > 1 else self._word
        self.edit_button.setToolTip(f"{self._word} 수정" if allow_edit else "")
        self.delete_button.setToolTip(f"{count_text} 삭제")

    @staticmethod
    def _set_label_text(label: _ElideLabel, text: str) -> None:
        if label.full_text != (text or ""):
            label.setText(text)

    @staticmethod
    def _create_reading_label(reading: str) -> _ElideLabel:
        label = _ElideLabel(reading)
        label.setObjectName("wordbookReading")
        label.setMinimumWidth(0)
        label.setMaximumWidth(240)
        label.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        return label

    def _request_edit(self) -> None:
        if self._edit_enabled:
            self.editRequested.emit(self._word)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_action_bar()

    def paintEvent(self, event) -> None:
        if self.action_bar.isVisible():
            self._place_action_bar()
        super().paintEvent(event)

    def _action_button(self, text: str, object_name: str) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text, self.action_bar)
        button.setObjectName(object_name)
        button.setCursor(QtCore.Qt.PointingHandCursor)
        button.setFixedSize(54 if len(text) > 2 else 42, 26)
        return button

    def _place_action_bar(self) -> None:
        self.action_bar.move(
            max(12, self.width() - self.action_bar.width() - 12),
            7,
        )
