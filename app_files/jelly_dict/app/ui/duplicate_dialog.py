from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.core.duplicate_checker import DuplicateDecision, DuplicatePolicy
from app.core.models import VocabularyEntry
from app.ui.dialog_shortcuts import install_standard_close_shortcut


class DuplicateDialog(QtWidgets.QDialog):
    """Modal shown when the same (language, word) is already saved."""

    def __init__(
        self,
        existing: VocabularyEntry,
        candidate: VocabularyEntry,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("duplicateDialog")
        self.setWindowTitle("이미 저장된 단어")
        self.setModal(True)
        self.resize(720, 420)
        self._policy: DuplicatePolicy = "keep_existing"
        self._apply_for_session = False
        install_standard_close_shortcut(self)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QtWidgets.QLabel(f"{existing.word} ({existing.language}) 이미 저장됨")
        title.setObjectName("duplicateTitle")
        title.setTextFormat(QtCore.Qt.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)

        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("duplicateScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll, 1)

        compare_body = QtWidgets.QWidget()
        compare = QtWidgets.QHBoxLayout()
        compare.setContentsMargins(0, 0, 0, 0)
        compare.setSpacing(12)
        compare.addWidget(self._build_card("기존", existing))
        compare.addWidget(self._build_card("새로 조회", candidate))
        compare_body.setLayout(compare)
        scroll.setWidget(compare_body)

        self.session_check = QtWidgets.QCheckBox("이 세션 동안 같은 선택 적용")
        layout.addWidget(self.session_check)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(10)
        layout.addLayout(button_row)

        for label, policy in [
            ("기존 유지", "keep_existing"),
            ("덮어쓰기", "update_existing"),
            ("예문/메모 병합", "merge_examples_and_memo"),
            ("새 항목으로 추가", "add_as_new"),
        ]:
            btn = QtWidgets.QPushButton(label)
            btn.setObjectName("duplicateOptionButton")
            btn.setMinimumHeight(40)
            btn.setMinimumWidth(128)
            btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            btn.clicked.connect(lambda _=False, p=policy: self._choose(p))
            button_row.addWidget(btn)

    def _choose(self, policy: DuplicatePolicy) -> None:
        self._policy = policy
        self._apply_for_session = self.session_check.isChecked()
        self.accept()

    def _build_card(self, title: str, entry: VocabularyEntry) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox(title)
        box.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        v = QtWidgets.QVBoxLayout(box)
        v.addWidget(_plain_label(f"{entry.word}  {entry.reading or ''}".strip()))
        if entry.part_of_speech:
            v.addWidget(_plain_label(", ".join(entry.part_of_speech)))
        if entry.meanings_summary:
            v.addWidget(_plain_label(entry.meanings_summary))
        if entry.examples_flat:
            ex = entry.examples_flat[0]
            ex_text = ex.source_text_plain
            if ex.translation_ko:
                ex_text += f"\n  → {ex.translation_ko}"
            ex_label = _plain_label(ex_text)
            ex_label.setStyleSheet("color: #aaa;")
            v.addWidget(ex_label)
        if entry.synonyms:
            syn = _plain_label("동의어: " + ", ".join(entry.synonyms[:5]))
            syn.setStyleSheet("color: #888;")
            v.addWidget(syn)
        if entry.memo:
            memo = _plain_label(entry.memo)
            memo.setStyleSheet("color: #666; font-style: italic;")
            v.addWidget(memo)
        v.addStretch(1)
        return box

    def decision(self) -> DuplicateDecision:
        return DuplicateDecision(policy=self._policy, apply_for_session=self._apply_for_session)


def prompt_duplicate(
    existing: VocabularyEntry,
    candidate: VocabularyEntry,
    parent: QtWidgets.QWidget | None = None,
) -> DuplicateDecision:
    dlg = DuplicateDialog(existing, candidate, parent)
    if dlg.exec() == QtWidgets.QDialog.Accepted:
        return dlg.decision()
    return DuplicateDecision(policy="keep_existing", apply_for_session=False)


def _plain_label(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setTextFormat(QtCore.Qt.PlainText)
    label.setWordWrap(True)
    return label
