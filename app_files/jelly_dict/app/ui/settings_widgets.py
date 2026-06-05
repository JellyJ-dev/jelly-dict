from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from app.ui.dialog_buttons import configure_footer_button
from app.ui.dialog_shortcuts import install_standard_close_shortcut


def _settings_combo() -> QtWidgets.QComboBox:
    combo = QtWidgets.QComboBox()
    combo.setObjectName("settingsCombo")
    fusion_style = QtWidgets.QStyleFactory.create("Fusion")
    if fusion_style is not None:
        combo.setStyle(fusion_style)
    view = QtWidgets.QListView(combo)
    view.setObjectName("settingsComboPopup")
    if fusion_style is not None:
        view.setStyle(fusion_style)
    view.setFrameShape(QtWidgets.QFrame.NoFrame)
    view.setUniformItemSizes(True)
    view.setAttribute(QtCore.Qt.WA_MacShowFocusRect, False)
    palette = view.palette()
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#30302d"))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#e8744f"))
    view.setPalette(palette)
    combo.setView(view)
    combo.setMaxVisibleItems(8)
    return combo


class _VoicevoxVoicePicker(QtWidgets.QDialog):
    """Multi-select dialog for VOICEVOX speaker/style entries.

    The list is fetched live from the engine. Users can search by typing
    and check exactly the voices they want kept in their voice combo.
    Returning order matches the visible (sorted) order so the curated
    favorites stay near the top of the dropdown.
    """

    def __init__(
        self,
        all_voices: tuple[str, ...],
        already_selected: set[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setWindowTitle("VOICEVOX 음성 선택")
        self.resize(520, 600)
        self._all_voices = all_voices
        self._initial = already_selected
        install_standard_close_shortcut(self)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("settingsLineEdit")
        self.search.setPlaceholderText("이름 / 스타일 / ID로 필터링…")
        self.search.textChanged.connect(self._apply_filter)
        root.addWidget(self.search)

        from app.anki.tts.voicevox_provider import display_label

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setObjectName("settingsVoiceList")
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        for voice in all_voices:
            item = QtWidgets.QListWidgetItem(display_label(voice))
            item.setData(QtCore.Qt.UserRole, voice)  # canonical, no Korean
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.Checked if voice in already_selected else QtCore.Qt.Unchecked
            )
            self.list_widget.addItem(item)
        root.addWidget(self.list_widget, 1)

        info = _muted_label(
            "✓ 체크된 음성만 일본어 음성 콤보에 표시됩니다. 체크 순서가 아닌 "
            "VOICEVOX의 ID 순서대로 정렬됩니다."
        )
        root.addWidget(info)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        ok_btn = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        cancel_btn = buttons.button(QtWidgets.QDialogButtonBox.Cancel)
        if ok_btn is not None:
            configure_footer_button(ok_btn, role="primary", text="저장")
        if cancel_btn is not None:
            configure_footer_button(cancel_btn, role="secondary", text="취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _apply_filter(self, query: str) -> None:
        q = query.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(bool(q) and q not in item.text().lower())

    def selected(self) -> list[str]:
        out: list[str] = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                out.append(item.data(QtCore.Qt.UserRole) or item.text())
        return out


def _section_header(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("settingsSectionHeader")
    label.setStyleSheet(
        "font-weight: 600; color: #e7e1d6; padding: 12px 0 4px 0;"
        "border-top: 1px solid #3f3f3c; margin-top: 8px;"
    )
    return label


def _muted_label(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("settingsMutedLabel")
    label.setWordWrap(True)
    label.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
    label.setSizePolicy(
        QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
    )
    label.setStyleSheet(
        "color: #aaa59c; font-size: 12px; padding: 4px 0;"
    )
    return label


class _PathPicker(QtWidgets.QWidget):
    def __init__(self, mode: str = "dir", file_filter: str = "", parent=None) -> None:
        """mode: 'dir' | 'file_save' | 'file_open'"""
        super().__init__(parent)
        self._mode = mode
        self._filter = file_filter
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.line = QtWidgets.QLineEdit()
        self.line.setObjectName("settingsPathLine")
        self.line.setMinimumWidth(520)
        self.button = QtWidgets.QPushButton("선택…")
        self.button.setObjectName("settingsSecondaryButton")
        self.button.setMaximumWidth(68)
        self.button.setMinimumHeight(38)
        layout.addWidget(self.line, 1)
        layout.addWidget(self.button)
        self.button.clicked.connect(self._pick)

    def _pick(self) -> None:
        current = self.line.text()
        if self._mode == "dir":
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "폴더 선택", current)
        elif self._mode == "file_open":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "기존 파일 선택", current, self._filter
            )
        else:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "저장할 파일 선택 / 새로 만들기", current, self._filter
            )
        if path:
            self.line.setText(path)

    def path(self) -> str:
        return self.line.text().strip()

    def set_path(self, path: str) -> None:
        self.line.setText(path or "")
