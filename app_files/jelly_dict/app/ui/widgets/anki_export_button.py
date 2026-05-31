from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


RESOURCE_DIR = Path(__file__).resolve().parents[3] / "resources"


class _ExportPopup(QtWidgets.QFrame):
    exportRequested = QtCore.Signal(str, bool)  # audio_policy, force_options
    settingsRequested = QtCore.Signal()
    closed = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent, QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setObjectName("ankiExportPopupWindow")
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setFixedWidth(276)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.panel = QtWidgets.QFrame()
        self.panel.setObjectName("ankiExportPopup")
        self.panel.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        root.addWidget(self.panel)

        layout = QtWidgets.QVBoxLayout(self.panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.status = QtWidgets.QLabel("현재 설정")
        self.status.setObjectName("ankiExportPopupStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        layout.addWidget(self._row("옵션 확인 후 내보내기...", "settings", True))
        layout.addWidget(self._separator())
        layout.addWidget(self._row("이번만 TTS 포함", "force_tts", False))
        layout.addWidget(self._row("이번만 TTS 없이", "no_tts", False))
        layout.addWidget(self._row("Anki 카드 음성 비우기", "remove_audio", True))
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
        self._normal_icon = QtGui.QIcon(str(RESOURCE_DIR / "icons" / "anki_mark.svg"))
        self._active_icon = QtGui.QIcon(
            str(RESOURCE_DIR / "icons" / "anki_mark_active.svg")
        )
        self.setObjectName("wordbookExportShell")
        self.setProperty("active", False)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_button = QtWidgets.QPushButton("Anki 내보내기", self)
        self.main_button.setObjectName("wordbookExportButton")
        self.main_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.main_button.setIcon(self._normal_icon)
        self.main_button.setIconSize(QtCore.QSize(18, 18))
        self.main_button.installEventFilter(self)
        self.main_button.setFixedSize(134, 34)
        self.option_button = QtWidgets.QPushButton("...", self)
        self.option_button.setObjectName("wordbookExportOptionButton")
        self.option_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.option_button.setFixedSize(38, 34)
        self.option_button.setToolTip("Anki 내보내기 옵션")
        divider = QtWidgets.QFrame(self)
        divider.setObjectName("wordbookExportDivider")
        self.main_button.clicked.connect(lambda: self._emit_export("settings", False))
        self.option_button.clicked.connect(self._show_popup)
        layout.addWidget(self.main_button)
        layout.addWidget(divider)
        layout.addWidget(self.option_button)
        self.setFixedSize(176, 34)

        self._popup = _ExportPopup(self)
        self._popup.exportRequested.connect(
            lambda policy, force: self._emit_export(policy, force)
        )
        self._popup.settingsRequested.connect(self.settingsRequested.emit)
        self._popup.closed.connect(self._sync_hover_state)
        self.set_status_text("")

    def set_language(self, language: str) -> None:
        self._language = language if language in ("en", "ja") else "en"

    def set_status_text(self, text: str) -> None:
        self._status_text = text
        tooltip = "현재 단어장을 Anki APKG로 내보내기"
        if text:
            tooltip += f"\n{text}"
        self.setToolTip(tooltip)
        self.main_button.setToolTip(tooltip)
        self.option_button.setToolTip(f"Anki 내보내기 옵션\n{text}" if text else "Anki 내보내기 옵션")

    def _show_popup(self) -> None:
        self._set_active(True)
        self._popup.set_status_text(self._status_text)
        self._popup.show_for(self.option_button)

    def _emit_export(self, audio_policy: str, force_options: bool) -> None:
        self.exportRequested.emit(self._language, audio_policy, force_options)

    def _sync_hover_state(self) -> None:
        self._set_active(False)

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self._sync_main_icon(active or self.main_button.underMouse())
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.main_button:
            if event.type() == QtCore.QEvent.Enter:
                self._sync_main_icon(True)
            elif event.type() == QtCore.QEvent.Leave:
                self._sync_main_icon(bool(self.property("active")))
        return super().eventFilter(watched, event)

    def _sync_main_icon(self, active: bool) -> None:
        self.main_button.setIcon(self._active_icon if active else self._normal_icon)
