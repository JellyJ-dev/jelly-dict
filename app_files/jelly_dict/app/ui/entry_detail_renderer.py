"""Qt section renderer for an EntryDetailViewModel."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.entry_detail_view_model import EntryDetailViewModel


class EntryDetailSectionRenderer:
    def __init__(
        self,
        view_model: EntryDetailViewModel,
        request_tts: Callable[[str], None],
    ) -> None:
        self.view_model = view_model
        self._request_tts = request_tts

    def render(self, layout: QtWidgets.QVBoxLayout) -> None:
        for text in self.view_model.meaning_rows:
            self._add_plain_row(layout, text)

        if self.view_model.examples:
            self._add_section_label(layout, "예문")
            for example in self.view_model.examples:
                row = _TtsTextLabel(example.display_text, example.tts_text)
                row.setObjectName("entryDetailExampleRow")
                row.clicked.connect(self._request_tts)
                row.setTextFormat(QtCore.Qt.PlainText)
                row.setWordWrap(True)
                layout.addWidget(row)

        for word_list in self.view_model.word_lists:
            self._add_section_label(layout, word_list.title)
            self._add_plain_row(layout, word_list.text)

        if self.view_model.memo:
            self._add_section_label(layout, "메모")
            self._add_plain_row(layout, self.view_model.memo)

        source = self.view_model.source
        if source is not None:
            if source.url:
                row = QtWidgets.QLabel(
                    f'<a style="color:#817b72; text-decoration:none;" href="{escape(source.url)}">'
                    f"{escape(source.text)}</a>"
                )
                row.setOpenExternalLinks(True)
                row.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
            else:
                row = QtWidgets.QLabel(source.text)
                row.setTextFormat(QtCore.Qt.PlainText)
            row.setObjectName("entryDetailSourceMeta")
            row.setWordWrap(True)
            layout.addWidget(row)

    @staticmethod
    def _add_section_label(layout: QtWidgets.QVBoxLayout, text: str) -> None:
        label = QtWidgets.QLabel(text)
        label.setObjectName("entryDetailSection")
        layout.addWidget(label)

    @staticmethod
    def _add_plain_row(layout: QtWidgets.QVBoxLayout, text: str) -> None:
        row = QtWidgets.QLabel(text)
        row.setObjectName("entryDetailSenseRow")
        row.setTextFormat(QtCore.Qt.PlainText)
        row.setWordWrap(True)
        layout.addWidget(row)


class _TtsTextLabel(QtWidgets.QLabel):
    clicked = QtCore.Signal(str)

    def __init__(self, text: str, tts_text: str) -> None:
        super().__init__(text)
        self._tts_text = tts_text
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit(self._tts_text)
            event.accept()
            return
        super().mousePressEvent(event)


__all__ = ["EntryDetailSectionRenderer", "_TtsTextLabel"]
