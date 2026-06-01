from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.core.models import (
    Example,
    MeaningGroup,
    Sense,
    SubSense,
    VocabularyEntry,
    build_meanings_summary,
    collect_examples_flat,
)
from app.ui.dialog_buttons import configure_footer_button
from app.ui.dialog_shortcuts import install_standard_close_shortcut


class EntryEditDialog(QtWidgets.QDialog):
    requeryRequested = QtCore.Signal()

    def __init__(
        self,
        entry: VocabularyEntry,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._entry = VocabularyEntry.from_dict(entry.to_dict())
        self.setObjectName("entryEditDialog")
        self.setWindowTitle("단어 수정")
        self.resize(860, 720)
        self.setMinimumSize(680, 560)
        self._build_ui()
        install_standard_close_shortcut(self)
        self.set_entry(entry)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)

        title_box = QtWidgets.QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(4)
        header.addLayout(title_box, 1)

        self.title_label = QtWidgets.QLabel("단어 수정")
        self.title_label.setObjectName("entryEditTitle")
        title_box.addWidget(self.title_label)

        self.subtitle_label = QtWidgets.QLabel("")
        self.subtitle_label.setObjectName("entryEditSubtitle")
        title_box.addWidget(self.subtitle_label)

        close_btn = QtWidgets.QPushButton("×")
        close_btn.setObjectName("entryDetailClose")
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn, 0, QtCore.Qt.AlignTop)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("entryEditScroll")
        layout.addWidget(scroll, 1)

        panel = QtWidgets.QFrame()
        panel.setObjectName("entryEditPanel")
        scroll.setWidget(panel)

        form = QtWidgets.QFormLayout(panel)
        form.setContentsMargins(20, 18, 20, 18)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        self.word_edit = self._line_edit()
        self.reading_edit = self._line_edit()
        self.pos_edit = self._line_edit()
        self.summary_edit = self._line_edit()
        self.examples_edit = self._text_edit(96)
        self.translations_edit = self._text_edit(96)
        self.synonyms_edit = self._line_edit()
        self.antonyms_edit = self._line_edit()
        self.tags_edit = self._line_edit()
        self.memo_edit = self._text_edit(86)
        self.source_edit = self._line_edit()

        form.addRow(_form_label("단어"), self.word_edit)
        form.addRow(_form_label("읽기/발음"), self.reading_edit)
        form.addRow(_form_label("품사"), self.pos_edit)
        form.addRow(_form_label("뜻 요약"), self.summary_edit)
        form.addRow(_form_label("예문"), self.examples_edit)
        form.addRow(_form_label("예문 해석"), self.translations_edit)
        form.addRow(_form_label("동의어"), self.synonyms_edit)
        form.addRow(_form_label("반의어"), self.antonyms_edit)
        form.addRow(_form_label("태그"), self.tags_edit)
        form.addRow(_form_label("메모"), self.memo_edit)
        form.addRow(_form_label("출처"), self.source_edit)

        footer = QtWidgets.QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(10)
        layout.addLayout(footer)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setObjectName("entryEditStatus")
        footer.addWidget(self.status_label, 1)

        self.requery_button = QtWidgets.QPushButton("재조회")
        configure_footer_button(self.requery_button, role="secondary")
        self.cancel_button = QtWidgets.QPushButton("취소")
        configure_footer_button(self.cancel_button, role="secondary")
        self.save_button = QtWidgets.QPushButton("저장")
        configure_footer_button(self.save_button, role="primary")
        self.save_button.setDefault(True)

        footer.addWidget(self.requery_button)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.save_button)

        self.requery_button.clicked.connect(self.requeryRequested.emit)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._accept_if_valid)

    def _line_edit(self) -> QtWidgets.QLineEdit:
        edit = QtWidgets.QLineEdit()
        edit.setObjectName("entryEditLineEdit")
        return edit

    def _text_edit(self, height: int) -> QtWidgets.QPlainTextEdit:
        edit = QtWidgets.QPlainTextEdit()
        edit.setObjectName("entryEditTextEdit")
        edit.setFixedHeight(height)
        return edit

    def set_entry(self, entry: VocabularyEntry) -> None:
        self._entry = VocabularyEntry.from_dict(entry.to_dict())
        self.subtitle_label.setText(entry.word or "")
        self.word_edit.setText(entry.word)
        self.reading_edit.setText(entry.reading or "")
        self.pos_edit.setText(", ".join(entry.part_of_speech))
        self.summary_edit.setText(entry.meanings_summary or build_meanings_summary(entry))
        self.summary_edit.setCursorPosition(0)
        self.synonyms_edit.setText(", ".join(entry.synonyms))
        self.antonyms_edit.setText(", ".join(entry.antonyms))
        self.tags_edit.setText(", ".join(entry.tags))
        self.memo_edit.setPlainText(entry.memo or "")
        flat = entry.examples_flat or collect_examples_flat(entry)
        self.examples_edit.setPlainText("\n".join(ex.source_text_plain for ex in flat))
        self.translations_edit.setPlainText("\n".join(ex.translation_ko or "" for ex in flat))
        self.source_edit.setText(entry.source_url or "")
        self.status_label.clear()

    def current_entry(self) -> VocabularyEntry:
        entry = VocabularyEntry.from_dict(self._entry.to_dict())
        entry.word = self.word_edit.text().strip()
        entry.reading = self.reading_edit.text().strip() or None
        entry.part_of_speech = _split_csv(self.pos_edit.text())
        entry.meanings_summary = self.summary_edit.text().strip()
        entry.synonyms = _split_csv(self.synonyms_edit.text())
        entry.antonyms = _split_csv(self.antonyms_edit.text())
        entry.tags = _split_csv(self.tags_edit.text())
        entry.memo = self.memo_edit.toPlainText().strip()
        entry.source_url = self.source_edit.text().strip() or None

        sources = [s for s in self.examples_edit.toPlainText().split("\n") if s]
        translations = [s for s in self.translations_edit.toPlainText().split("\n")]
        examples: list[Example] = []
        for idx, source in enumerate(sources):
            examples.append(
                Example(
                    source_text=source,
                    source_text_plain=source,
                    translation_ko=translations[idx] if idx < len(translations) else None,
                    order=idx,
                )
            )
        entry.examples_flat = examples
        if not entry.meaning_groups:
            entry.meaning_groups = [
                MeaningGroup(
                    pos=entry.part_of_speech[0] if entry.part_of_speech else "",
                    senses=[
                        Sense(
                            number=1,
                            gloss=entry.meanings_summary,
                            sub_senses=[SubSense(examples=examples)],
                        )
                    ],
                )
            ]
        entry.touch()
        return entry

    def set_busy(self, busy: bool) -> None:
        self.requery_button.setEnabled(not busy)
        self.cancel_button.setEnabled(not busy)
        self.save_button.setEnabled(not busy)
        self.status_label.setText("재조회 중..." if busy else self.status_label.text())
        if busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    def show_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _accept_if_valid(self) -> None:
        if not self.word_edit.text().strip():
            self.status_label.setText("단어는 비울 수 없습니다.")
            self.word_edit.setFocus()
            return
        self.accept()


def _split_csv(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split(",") if p.strip()]


def _form_label(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("entryEditFormLabel")
    return label
