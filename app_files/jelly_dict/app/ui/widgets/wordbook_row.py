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
        self.setToolTip(self._full_text)
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
    def __init__(
        self,
        language: str,
        word: str,
        reading: str,
        hint: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("wordbookRow")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(2)

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(7)
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

        meaning_label = _ElideLabel(hint)
        meaning_label.setObjectName("wordbookMeaning")
        meaning_label.setMinimumWidth(0)
        meaning_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
        )
        layout.addWidget(meaning_label)


def wordbook_tooltip(language: str, word: str, reading: str, hint: str) -> str:
    if language == "ja" and reading:
        return f"{word}\n{reading}\n{hint}".strip()
    return f"{word}\n{hint}".strip()
