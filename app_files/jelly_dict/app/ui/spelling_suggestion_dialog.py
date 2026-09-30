from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from app.ui.dialog_shortcuts import install_standard_close_shortcut


class SpellingSuggestionDialog(QtWidgets.QDialog):
    def __init__(
        self, word: str, candidates: list[str], parent=None, *, related: bool = False
    ) -> None:
        super().__init__(parent)
        self.setObjectName("spellingSuggestionDialog")
        self.setWindowTitle("관련 단어 조회" if related else "혹시 이걸 찾으셨나요?")
        self.setMinimumWidth(440)
        install_standard_close_shortcut(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        message = (
            f"'{word}' 전체와 일치하는 사전 항목이 없습니다.\n"
            "검색 결과에 있는 관련 단어를 선택해 뜻을 확인하세요."
            if related
            else f"'{word}'의 검색 결과가 없습니다.\n찾으려던 단어를 선택하세요."
        )
        label = QtWidgets.QLabel(message)
        label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.candidates = QtWidgets.QListWidget()
        self.candidates.setObjectName("spellingCandidates")
        self.candidates.addItems(candidates[:5])
        self.candidates.setCurrentRow(0)
        self.candidates.setFixedHeight(max(1, self.candidates.count()) * 36 + 12)
        self.candidates.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.candidates)
        buttons = QtWidgets.QDialogButtonBox()
        self.lookup_button = buttons.addButton(
            "이 단어로 조회", QtWidgets.QDialogButtonBox.AcceptRole
        )
        self.lookup_button.setObjectName("spellingLookupButton")
        self.lookup_button.setDefault(True)
        self.lookup_button.setEnabled(bool(candidates))
        buttons.addButton("취소", QtWidgets.QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_word(self) -> str | None:
        item = self.candidates.currentItem()
        return item.text() if item is not None else None


def choose_spelling_suggestion(
    parent, word: str, candidates: list[str], *, related: bool = False
) -> str | None:
    dialog = SpellingSuggestionDialog(word, candidates, parent, related=related)
    try:
        return dialog.selected_word() if dialog.exec() == QtWidgets.QDialog.Accepted else None
    finally:
        dialog.deleteLater()
