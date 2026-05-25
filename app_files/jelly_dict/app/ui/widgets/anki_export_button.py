from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

RESOURCE_DIR = Path(__file__).resolve().parents[3] / "resources"


def _resource_icon(name: str) -> QtGui.QIcon:
    return QtGui.QIcon(str(RESOURCE_DIR / "icons" / name))


class _ExportPopup(QtWidgets.QFrame):
    exportRequested = QtCore.Signal(str, bool)  # audio_policy, force_options
    settingsRequested = QtCore.Signal()
    closed = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent, QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setObjectName("ankiExportPopup")
        self.setFixedWidth(260)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(3)

        self.status = QtWidgets.QLabel("현재 설정")
        self.status.setObjectName("ankiExportPopupStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        layout.addWidget(self._row("옵션 확인 후 내보내기...", "settings", True))
        layout.addWidget(self._separator())
        layout.addWidget(self._row("이번만 TTS 포함", "force_tts", False))
        layout.addWidget(self._row("이번만 TTS 없이", "no_tts", False))
        layout.addWidget(self._row("기존 Anki 음성 제거용", "remove_audio", True, "warning"))
        layout.addWidget(self._separator())

        settings = QtWidgets.QPushButton("Anki / TTS 설정")
        settings.setObjectName("ankiExportPopupItem")
        settings.clicked.connect(self._emit_settings)
        layout.addWidget(settings)

    def set_status_text(self, text: str) -> None:
        self.status.setText(text or "현재 설정 사용")

    def show_for(self, anchor: QtWidgets.QWidget) -> None:
        self.adjustSize()
        bottom_right = anchor.mapToGlobal(QtCore.QPoint(anchor.width(), anchor.height() + 6))
        self.move(bottom_right.x() - self.width(), bottom_right.y())
        self.show()
        self.raise_()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.closed.emit()

    def _row(
        self,
        text: str,
        policy: str,
        force_options: bool,
        variant: str = "normal",
    ) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.setObjectName(
            "ankiExportPopupWarning" if variant == "warning" else "ankiExportPopupItem"
        )
        button.clicked.connect(
            lambda _checked=False, p=policy, f=force_options: self._emit_export(p, f)
        )
        return button

    def _separator(self) -> QtWidgets.QFrame:
        line = QtWidgets.QFrame()
        line.setObjectName("ankiExportPopupSeparator")
        line.setFrameShape(QtWidgets.QFrame.HLine)
        return line

    def _emit_export(self, policy: str, force_options: bool) -> None:
        self.hide()
        self.exportRequested.emit(policy, force_options)

    def _emit_settings(self) -> None:
        self.hide()
        self.settingsRequested.emit()


class AnkiExportButton(QtWidgets.QWidget):
    exportRequested = QtCore.Signal(str, str, bool)  # language, audio_policy, force_options
    settingsRequested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._language = "en"
        self._status_text = ""
        self._normal_icon = _resource_icon("anki_mark.svg")
        self._active_icon = _resource_icon("anki_mark_active.svg")
        self.setObjectName("ankiExportButton")
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.main_button = QtWidgets.QPushButton("Anki 내보내기")
        self.main_button.setObjectName("wordbookExportButton")
        self.main_button.setIcon(self._normal_icon)
        self.main_button.setIconSize(QtCore.QSize(20, 20))
        self.main_button.clicked.connect(lambda: self._emit_export("settings", False))
        self.main_button.installEventFilter(self)

        self.option_button = QtWidgets.QPushButton("⋯")
        self.option_button.setObjectName("wordbookExportOptionButton")
        self.option_button.setFixedSize(28, 28)
        self.option_button.setToolTip("Anki 내보내기 옵션")
        self.option_button.clicked.connect(self._show_popup)
        self.option_button.installEventFilter(self)

        layout.addWidget(self.main_button)
        layout.addWidget(self.option_button)

        self._popup = _ExportPopup(self)
        self._popup.exportRequested.connect(
            lambda policy, force: self._emit_export(policy, force)
        )
        self._popup.settingsRequested.connect(self.settingsRequested.emit)
        self._popup.closed.connect(lambda: self._set_active(False))
        self.set_status_text("")

    def set_language(self, language: str) -> None:
        self._language = language if language in ("en", "ja") else "en"

    def set_status_text(self, text: str) -> None:
        self._status_text = text
        tooltip = "현재 단어장을 Anki APKG로 내보내기"
        if text:
            tooltip += f"\n{text}"
        self.main_button.setToolTip(tooltip)
        self.option_button.setToolTip(f"Anki 내보내기 옵션\n{text}" if text else "Anki 내보내기 옵션")

    def _show_popup(self) -> None:
        self._set_active(True)
        self._popup.set_status_text(self._status_text)
        self._popup.show_for(self.option_button)

    def _emit_export(self, audio_policy: str, force_options: bool) -> None:
        self.exportRequested.emit(self._language, audio_policy, force_options)

    def _set_active(self, active: bool) -> None:
        self.main_button.setIcon(self._active_icon if active else self._normal_icon)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.main_button:
            if event.type() == QtCore.QEvent.Enter:
                self._set_active(True)
            elif event.type() == QtCore.QEvent.Leave and not self._popup.isVisible():
                self._set_active(False)
        return super().eventFilter(watched, event)
