"""Compact row widget used inside the wordbook list.

Extracted from `word_input_view.py` to keep that file focused on the
input flow. Object names stay stable so the central QSS owns the visual
language, while labels elide long content instead of overflowing.
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets


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
        self._edit_enabled = False
        self.setObjectName("wordbookRow")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(3)

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        layout.addLayout(top)

        word_label = _ElideLabel(word)
        word_label.setObjectName("wordbookWord")
        word_label.setMinimumWidth(0)
        word_label.setMaximumWidth(360 if language == "ja" and reading else 520)
        word_label.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed
        )
        top.addWidget(word_label, 0)

        if language == "ja" and reading:
            reading_label = _ElideLabel(reading)
            reading_label.setObjectName("wordbookReading")
            reading_label.setMinimumWidth(0)
            reading_label.setMaximumWidth(240)
            reading_label.setSizePolicy(
                QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed
            )
            top.addWidget(reading_label, 0)
        top.addStretch(1)

        self.action_bar = QtWidgets.QFrame(self)
        self.action_bar.setObjectName("wordbookRowActions")
        self.action_bar.setFixedSize(96, 28)
        self.action_bar.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed
        )
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

        meaning_label = _ElideLabel(hint)
        meaning_label.setObjectName("wordbookMeaning")
        meaning_label.setMinimumWidth(0)
        meaning_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
        )
        layout.addWidget(meaning_label)

    def set_actions_visible(self, visible: bool, selected_count: int = 1) -> None:
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
