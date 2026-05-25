"""Title + subtitle + check menu row used in the language and word list menus.

Extracted from `word_input_view.py` to share between menus and to keep
the input view file focused on flow. UI / styling unchanged.
"""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class LanguageMenuItem(QtWidgets.QFrame):
    clicked = QtCore.Signal()

    def __init__(
        self,
        title: str,
        subtitle: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("languageMenuItem")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._selected = False
        self.setMinimumWidth(340)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 10, 7)
        layout.setSpacing(8)

        text_layout = QtWidgets.QVBoxLayout()
        text_layout.setSpacing(2)
        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("languageMenuTitle")
        self.subtitle = QtWidgets.QLabel(subtitle)
        self.subtitle.setObjectName("languageMenuSubtitle")
        text_layout.addWidget(self.title)
        text_layout.addWidget(self.subtitle)
        layout.addLayout(text_layout, 1)

        self.check = QtWidgets.QLabel("✓")
        self.check.setObjectName("languageMenuCheck")
        self.check.setFixedWidth(18)
        self.check.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.check)
        self.set_selected(False)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setProperty("selected", selected)
        self.check.setVisible(selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
